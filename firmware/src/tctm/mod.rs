use defmt::error;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_futures::select::Either;
use embassy_futures::select::Either3;
use embassy_futures::select::select;
use embassy_futures::select::select3;
use embassy_net::Stack;
use embassy_time::Duration;
use embassy_time::TimeoutError;
use embassy_time::Timer;
use embassy_time::with_timeout;
use esp_hal::debugger::debugger_connected;
use nixie_wire::Command;
use nixie_wire::PROTOCOL_VERSION;
use nixie_wire::Telemetry;
use nixie_wire::ToHost;

use crate::tctm::connection::Connection;

pub use log::panic_flush;

mod connection;
mod log;

#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
enum Error {
    /// During handshake, the host did not start with an init command
    UnexpectedHandshakeCommand,

    /// During handshake, the host reported a version that did not match ours
    VersionMismatch,

    /// A command was received with a sequence number other than our expected next sequence.
    OutOfSequence,

    /// A network operation timed out
    Timeout,

    /// The connection reported an error
    Connection(connection::Error),
}

impl From<connection::Error> for Error {
    fn from(value: connection::Error) -> Self {
        Error::Connection(value)
    }
}

impl From<TimeoutError> for Error {
    fn from(_: TimeoutError) -> Self {
        Self::Timeout
    }
}

struct CommandAndTelemetry<'a> {
    connection: Connection<'a>,
    sequence: u32,
}

impl<'a> CommandAndTelemetry<'a> {
    pub fn new(connection: Connection<'a>) -> CommandAndTelemetry<'a> {
        CommandAndTelemetry {
            connection,
            sequence: 0,
        }
    }

    pub async fn run(&mut self) -> ! {
        loop {
            self.listen().await;
            if let Err(e) = self.handshake().await {
                match e {
                    Error::Timeout | Error::Connection(connection::Error::Disconnected) => {
                        info!("Handshake failed: {}", e);
                    }
                    _ => warn!("Handshake failed: {}", e),
                }
                self.connection.reset().await;
                continue;
            }

            let e = self.serve().await;
            match e {
                Error::Timeout | Error::Connection(connection::Error::Disconnected) => {
                    info!("TCTM session ended: {}", e);
                }
                _ => warn!("TCTM session ended: {}", e),
            }
            self.connection.reset().await;
        }
    }

    async fn listen(&mut self) {
        loop {
            let accepted = {
                let mut accept = core::pin::pin!(self.connection.open());
                loop {
                    match select3(
                        accept.as_mut(),
                        log::wait_for_frames(),
                        Timer::after_secs(2),
                    )
                    .await
                    {
                        Either3::First(result) => break result,
                        Either3::Second(()) | Either3::Third(()) => {
                            if debugger_connected() {
                                log::drain_to_rtt();
                            }
                        }
                    }
                }
            };
            match accepted {
                Ok(()) => return,
                Err(e) => {
                    self.connection.reset().await;
                    warn!("TCTM start failed: {}", e);
                    Timer::after_secs(1).await
                }
            }
        }
    }

    async fn serve(&mut self) -> Error {
        if let Err(e) = self.drain_log().await {
            return e;
        }
        loop {
            let result =
                match select(self.connection.wait_read_ready(), log::wait_for_frames()).await {
                    Either::First(Ok(())) => self.handle_command().await,
                    Either::First(Err(e)) => Err(e.into()),
                    Either::Second(()) => self.drain_log().await,
                };
            match result {
                Ok(()) => continue,
                Err(e) => return e,
            }
        }
    }

    async fn handshake(&mut self) -> Result<(), Error> {
        let packet = with_timeout(Duration::from_secs(5), self.connection.read()).await??;
        match packet.payload() {
            Command::Init { version } => {
                // On startup, accept whatever sequence number the host gives us
                self.sequence = packet.sequence();
                self.handle_init(version).await?;
                Ok(())
            }
            _ => Err(Error::UnexpectedHandshakeCommand),
        }
    }

    async fn handle_command(&mut self) -> Result<(), Error> {
        let packet = with_timeout(Duration::from_secs(5), self.connection.read()).await??;
        if packet.sequence() != self.sequence.wrapping_add(1) {
            return Err(Error::OutOfSequence);
        }
        self.sequence = packet.sequence();
        match packet.payload() {
            Command::Init { version } => self.handle_init(version).await,
            Command::Reset => self.handle_reset().await,
        }
    }

    async fn handle_init(&mut self, version: u16) -> Result<(), Error> {
        if version != PROTOCOL_VERSION {
            return Err(Error::VersionMismatch);
        }

        let reply = ToHost::new(
            self.sequence,
            Telemetry::InitAck {
                version: PROTOCOL_VERSION,
                firmware_id: env!("NIXIE_FIRMWARE_ID"),
            },
        );
        self.connection.write(&reply).await?;
        Ok(())
    }

    async fn handle_reset(&mut self) -> ! {
        info!("Reset commanded by host, sequence {}", self.sequence);
        let _ = with_timeout(Duration::from_secs(2), self.drain_log()).await;
        let ack = ToHost::new(self.sequence, Telemetry::Ack);
        if let Err(e) = self.connection.write(&ack).await {
            warn!("Reset ack not sent: {}", e)
        }
        self.connection.close().await;
        esp_hal::system::software_reset()
    }

    async fn drain_log(&mut self) -> Result<(), Error> {
        loop {
            match self
                .connection
                .write_framed(|buffer| {
                    // safety: frame handler does not log
                    unsafe {
                        log::handle_frame(|sequence, frame| {
                            let msg = ToHost::new(
                                self.sequence,
                                nixie_wire::Telemetry::Log { sequence, frame },
                            );
                            postcard::to_slice(&msg, buffer).map(|s| s.len()).ok()
                        })
                    }
                    .flatten()
                })
                .await
            {
                Ok(true) => continue,
                Ok(false) => return Ok(()),
                Err(e) => return Err(e.into()),
            }
        }
    }
}

pub fn init_logging() {
    log::init();
}

pub fn init(stack: Stack<'static>, spawner: &Spawner) {
    let Ok(tctm_token) = tctm(stack) else {
        error!("Failed to create tctm task, network client will be unavailable");
        return;
    };

    spawner.spawn(tctm_token);
    info!("Command & Telemetry initialized...");
}

#[embassy_executor::task]
async fn tctm(stack: Stack<'static>) -> ! {
    let mut tcp_rx_buf = [0u8; 4 * 1024];
    let mut tcp_tx_buf = [0u8; 8 * 1024];
    let client_connection = Connection::new(stack, &mut tcp_rx_buf, &mut tcp_tx_buf);

    CommandAndTelemetry::new(client_connection).run().await;
}
