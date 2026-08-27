use chrono::DateTime;
use chrono::FixedOffset;
use chrono::Utc;
use defmt::error;
use defmt::info;
use embassy_executor::Spawner;
use embassy_net::Stack;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::Watch;
use embassy_time::Duration;
use embassy_time::Instant;

use crate::status;
use crate::status::TimeStatus;

mod sntp;
mod tz;

const STALE_THRESHOLD: Duration = Duration::from_secs(24 * 60 * 60);

static SNAPSHOT: Watch<CriticalSectionRawMutex, Snapshot, 1> = Watch::new();

#[derive(Clone, Copy)]
struct Snapshot {
    offset_us: i64,
    at: Instant,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Clock {
    Never,
    Synced(DateTime<Utc>),
    Stale(DateTime<Utc>),
}

impl Clock {
    pub fn utc(self) -> Option<DateTime<Utc>> {
        match self {
            Clock::Never => None,
            Clock::Synced(now) => Some(now),
            Clock::Stale(now) => Some(now),
        }
    }

    pub fn local(self) -> Option<DateTime<FixedOffset>> {
        let utc = self.utc()?;
        let offset = tz::current().offset_at(utc)?;
        Some(utc.with_timezone(&offset))
    }
}

/// Gets the current NTP time
pub fn now() -> Option<DateTime<Utc>> {
    state().utc()
}

/// Gets the current NTP time, adjusted to the local timezone
pub fn local_now() -> Option<DateTime<FixedOffset>> {
    state().local()
}

/// Gets the raw NTP clock state
pub fn state() -> Clock {
    let mcu_now = Instant::now();
    let Some(value) = SNAPSHOT.try_get() else {
        return Clock::Never;
    };

    let mcu_now_us = mcu_now.as_micros() as i64;
    let ticks = mcu_now_us.saturating_add(value.offset_us);
    let Some(now) = DateTime::from_timestamp_micros(ticks) else {
        error!(
            "Failed to construct DateTime from {} + {} = {}",
            mcu_now_us, value.offset_us, ticks
        );
        return Clock::Never;
    };

    if value.at + STALE_THRESHOLD < mcu_now {
        status::report(TimeStatus::Stale);
        Clock::Stale(now)
    } else {
        status::report(TimeStatus::Synced);
        Clock::Synced(now)
    }
}

fn set_ntp_offset(offset_us: i64) -> Option<i64> {
    let at = Instant::now();
    let state = Snapshot { offset_us, at };
    let previous = SNAPSHOT.try_get();
    SNAPSHOT.sender().send(state);
    previous.map(|p| offset_us - p.offset_us)
}

/// Future that completes when NTP sync has completed. The future completes immediately if NTP sync
/// is already complete.
pub async fn wait_for_ntp() {
    let mut rx = SNAPSHOT.dyn_receiver().unwrap();
    rx.get().await;
}

pub fn init(stack: Stack<'static>, spawner: &Spawner) {
    sntp::init(stack, spawner);
    info!("Time initialized...");
}
