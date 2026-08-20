use core::net::IpAddr;
use core::net::SocketAddr;

use defmt::debug;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_net::Stack;
use embassy_net::udp::UdpSocket;
use embassy_time::Duration;
use embassy_time::Instant;
use embassy_time::Timer;
use embassy_time::WithTimeout;
use heapless::HistoryBuf;
use heapless::Vec;
use smoltcp::config::DNS_MAX_RESULT_COUNT;
use smoltcp::storage::PacketMetadata;
use smoltcp::wire::DnsQueryType;
use sntpc::Error;
use sntpc::KissOfDeathCode;
use sntpc::NtpContext;
use sntpc::get_time;
use sntpc_net_embassy::UdpSocketWrapper;
use sntpc_time_embassy::EmbassyTimestampGenerator;

/// A set of IP Addresses that have replied to NTP requests with responses indicating they should
/// never be queried again.
struct DenySet {
    buf: HistoryBuf<IpAddr, 8>,
}

impl DenySet {
    pub const fn new() -> DenySet {
        DenySet {
            buf: HistoryBuf::new(),
        }
    }

    pub fn contains(&self, value: &IpAddr) -> bool {
        self.buf.as_slice().contains(value)
    }

    pub fn add(&mut self, value: IpAddr) {
        if !self.contains(&value) {
            self.buf.write(value);
        }
    }
}

/// An NTP host, including hostname and DNS refresh intervals
struct NtpHost {
    name: &'static str,
    cold_dns_interval: Duration,
    warm_dns_interval: Duration,
}

impl NtpHost {
    pub const fn new(
        name: &'static str,
        cold_dns_interval: Duration,
        warm_dns_interval: Duration,
    ) -> NtpHost {
        NtpHost {
            name,
            cold_dns_interval,
            warm_dns_interval,
        }
    }
}

/// An NTP server candidate address, along with the number of times the address has failed
struct NtpServerCandidate {
    address: IpAddr,
    strikes: u8,
    next_allowed: Instant,
}

impl NtpServerCandidate {
    pub const fn new(address: IpAddr) -> NtpServerCandidate {
        NtpServerCandidate {
            address,
            strikes: 0,
            next_allowed: Instant::from_micros(0),
        }
    }
}

#[derive(Clone, Copy)]
enum CandidateResult {
    Ready(IpAddr),
    NotBefore(Instant),
}

struct NtpHostState {
    host: &'static NtpHost,
    candidates: Vec<NtpServerCandidate, DNS_MAX_RESULT_COUNT>,
    denied: DenySet,
    last_dns_attempt: Option<Instant>,
    dns_ever_resolved: bool,
}

impl NtpHostState {
    pub const fn new(host: &'static NtpHost) -> NtpHostState {
        NtpHostState {
            host,
            candidates: Vec::new(),
            denied: DenySet::new(),
            last_dns_attempt: None,
            dns_ever_resolved: false,
        }
    }

    async fn query_dns(&mut self, stack: Stack<'static>) {
        let host = self.host.name;
        match stack.dns_query(host, DnsQueryType::A).await {
            Ok(addresses) => {
                let denied = &self.denied;
                self.candidates = addresses
                    .into_iter()
                    .map(IpAddr::from)
                    .filter(|a| !denied.contains(a))
                    .map(NtpServerCandidate::new)
                    .collect();

                self.dns_ever_resolved = true;

                if self.candidates.is_empty() {
                    warn!(
                        "DNS lookup for {} returned no addresses (or they were all filtered)",
                        host
                    );
                }
            }
            Err(e) => {
                warn!("DNS lookup for {} failed: {}", host, e);
            }
        }
        self.last_dns_attempt = Some(Instant::now());
    }

    fn next_dns(&self) -> Instant {
        const NO_DNS_BACKOFF: Duration = Duration::from_secs(10);
        let Some(last_dns_attempt) = self.last_dns_attempt else {
            return Instant::now();
        };

        let interval = if !self.candidates.is_empty() {
            self.host.warm_dns_interval
        } else if self.dns_ever_resolved {
            self.host.cold_dns_interval
        } else {
            NO_DNS_BACKOFF
        };

        last_dns_attempt + interval
    }

    pub async fn get_candidate(&mut self, stack: Stack<'static>) -> CandidateResult {
        let mut next_dns = self.next_dns();
        if next_dns <= Instant::now() {
            self.query_dns(stack).await;
            next_dns = self.next_dns();
        }

        match self.candidates.iter().min_by_key(|c| c.next_allowed) {
            Some(c) => {
                if c.next_allowed <= Instant::now() {
                    CandidateResult::Ready(c.address)
                } else {
                    CandidateResult::NotBefore(c.next_allowed.min(next_dns))
                }
            }
            None => CandidateResult::NotBefore(next_dns),
        }
    }

    fn apply_strike(&mut self, ip: IpAddr) {
        let Some(candidate) = self.candidates.iter_mut().find(|c| c.address == ip) else {
            // Not reachable in practice since apply_outcome already does this exact same check. We
            // have to do it again separately here to keep the borrow checker happy.
            return;
        };
        const MAX_STRIKES: u8 = 3;
        const BACKOFF_PER_STRIKE: Duration = Duration::from_secs(5);
        candidate.strikes += 1;
        if candidate.strikes >= MAX_STRIKES {
            self.candidates.retain(|c| c.address != ip);
        } else {
            candidate.next_allowed =
                Instant::now() + BACKOFF_PER_STRIKE * u32::from(candidate.strikes);
        }
    }

    pub fn apply_outcome(&mut self, ip: IpAddr, outcome: SyncOutcome) {
        let Some(candidate) = self.candidates.iter_mut().find(|c| c.address == ip) else {
            // apply_outcome gets called on all hosts for all outcomes, so we expect to get plenty
            // of outcomes for ips we don't own. This saves us enough tracking overhead in the next
            // layer up to be worth it.
            return;
        };

        match outcome {
            SyncOutcome::Synced => {
                candidate.strikes = 0;
            }
            SyncOutcome::Timeout => {
                self.apply_strike(ip);
            }
            SyncOutcome::Refused(code) => match code {
                KissOfDeathCode::Deny | KissOfDeathCode::Rstr => {
                    self.denied.add(ip);
                    self.candidates.retain(|c| c.address != ip);
                }
                KissOfDeathCode::Rate => {
                    const RATE_LIMIT_BACKOFF: Duration = Duration::from_secs(30);
                    candidate.next_allowed = Instant::now() + RATE_LIMIT_BACKOFF;
                }
                _ => {
                    self.apply_strike(ip);
                }
            },
            SyncOutcome::Bad => {
                self.apply_strike(ip);
            }
            SyncOutcome::InternalError => {
                // Not the NTP server's fault, but without some rate limiting this could infinite
                // loop and wedge the firmware.
                const INTERNAL_ERROR_BACKOFF: Duration = Duration::from_secs(5);
                candidate.next_allowed = Instant::now() + INTERNAL_ERROR_BACKOFF;
            }
        }
    }
}

const DNS_DEFAULT_SHORT_INTERVAL: Duration = Duration::from_secs(30);
const DNS_POOL_SHORT_INTERVAL: Duration = Duration::from_secs(60 * 60);
const DNS_LONG_INTERVAL: Duration = Duration::from_secs(12 * 60 * 60);
const NTP_HOSTS: [NtpHost; 3] = [
    NtpHost::new(
        "time.cloudflare.com",
        DNS_DEFAULT_SHORT_INTERVAL,
        DNS_LONG_INTERVAL,
    ),
    NtpHost::new("pool.ntp.org", DNS_POOL_SHORT_INTERVAL, DNS_LONG_INTERVAL),
    NtpHost::new(
        "time.nist.gov",
        DNS_DEFAULT_SHORT_INTERVAL,
        DNS_LONG_INTERVAL,
    ),
];

#[derive(Clone, Copy, PartialEq, Eq)]
enum SyncOutcome {
    Synced,
    Timeout,
    Refused(KissOfDeathCode),
    Bad,
    InternalError,
}

struct NtpState {
    hosts: [NtpHostState; NTP_HOSTS.len()],
}

impl NtpState {
    pub fn new() -> NtpState {
        let hosts = core::array::from_fn(|i| NtpHostState::new(&NTP_HOSTS[i]));
        NtpState { hosts }
    }

    pub async fn next_candidate(&mut self, stack: Stack<'static>) -> CandidateResult {
        let mut soonest: Option<Instant> = None;
        for host in self.hosts.iter_mut() {
            match host.get_candidate(stack).await {
                CandidateResult::Ready(ip) => {
                    return CandidateResult::Ready(ip);
                }
                CandidateResult::NotBefore(t) => soonest = Some(soonest.map_or(t, |s| s.min(t))),
            }
        }

        CandidateResult::NotBefore(soonest.expect("NTP_HOSTS is non-empty"))
    }

    pub fn apply_outcome(&mut self, ip: IpAddr, outcome: SyncOutcome) {
        for h in self.hosts.iter_mut() {
            h.apply_outcome(ip, outcome);
        }
    }
}

pub fn init(stack: Stack<'static>, spawner: &Spawner) {
    let sync_token = sync(stack).expect("Failed to create sntp task");

    spawner.spawn(sync_token);
}

#[embassy_executor::task]
async fn sync(stack: Stack<'static>) -> ! {
    let context = NtpContext::new(EmbassyTimestampGenerator::default());
    let mut state = NtpState::new();
    loop {
        let start = Instant::now();
        stack.wait_config_up().await;
        match state.next_candidate(stack).await {
            CandidateResult::Ready(ip) => {
                let outcome = try_one(stack, ip, context).await;
                state.apply_outcome(ip, outcome);
                if outcome == SyncOutcome::Synced {
                    const RESYNC: Duration = Duration::from_secs(60 * 60);
                    Timer::after(RESYNC).await;
                }
            }
            CandidateResult::NotBefore(t) => {
                if let Some(d) = t.checked_duration_since(Instant::now()) {
                    Timer::after(d).await;
                }
            }
        }

        // Forcing each loop to take a minimum time acts as a backstop against error paths that
        // don't introduce their own backoff time, which could otherwise let this loop run away and
        // wedge the firmware.
        const MIN_ITERATION_TIME: Duration = Duration::from_millis(100);
        if let Some(remaining) = (start + MIN_ITERATION_TIME).checked_duration_since(Instant::now())
        {
            Timer::after(remaining).await;
        }
    }
}

async fn try_one(
    stack: Stack<'static>,
    ip: IpAddr,
    context: NtpContext<EmbassyTimestampGenerator>,
) -> SyncOutcome {
    const MAX_ROUNDTRIP: Duration = Duration::from_millis(500);
    let mut rx_meta = [PacketMetadata::EMPTY; 1];
    let mut rx_buf = [0u8; 128];
    let mut tx_meta = [PacketMetadata::EMPTY; 1];
    let mut tx_buf = [0u8; 128];

    let mut socket = UdpSocket::new(stack, &mut rx_meta, &mut rx_buf, &mut tx_meta, &mut tx_buf);
    if let Err(e) = socket.bind(0) {
        warn!("Failed to bind socket: {}", e);
        return SyncOutcome::InternalError;
    }
    let socket = UdpSocketWrapper::from(socket);
    let addr = SocketAddr::new(ip, 123);
    let time = get_time(addr, &socket, context)
        .with_timeout(MAX_ROUNDTRIP * 4)
        .await;
    match time {
        Ok(Ok(result)) => {
            if result.roundtrip() > MAX_ROUNDTRIP.as_micros() {
                info!("Excessive RTT for SNTP response. Dropping");
                return SyncOutcome::Bad;
            }

            let local_us = Instant::now().as_micros() as i64;
            let server_us = result.sec() as i64 * 1_000_000
                + i64::from(sntpc::fraction_to_microseconds(result.sec_fraction()))
                + (result.roundtrip() / 2) as i64;
            match super::set_ntp_offset(server_us - local_us) {
                Some(correction_us) => info!(
                    "Synced from {}: stratum {}, rtt {}us, correction {}us",
                    ip,
                    result.stratum(),
                    result.roundtrip(),
                    correction_us
                ),
                None => info!(
                    "Synced from {}: stratum {}, rtt {}us, initial set",
                    ip,
                    result.stratum(),
                    result.roundtrip()
                ),
            }

            SyncOutcome::Synced
        }
        Ok(Err(Error::KissOfDeath(code))) => {
            warn!("KoD {} from {}", code.as_str(), ip);
            SyncOutcome::Refused(code)
        }
        Ok(Err(e)) => {
            warn!("Failed to get NTP time from {}: {}", ip, e);
            SyncOutcome::Bad
        }
        Err(_) => {
            debug!("Timed out connecting to {}", ip);
            SyncOutcome::Timeout
        }
    }
}
