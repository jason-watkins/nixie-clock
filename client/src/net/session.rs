use std::cell::Cell;
use std::time::Duration;

use nixie_wire::Command;
use nixie_wire::MAX_MESSAGE_SIZE;
use nixie_wire::PROTOCOL_VERSION;
use nixie_wire::Telemetry;
use nixie_wire::ToDevice;
use nixie_wire::ToHost;
use tokio::net::TcpStream;
use tokio::net::tcp::OwnedReadHalf;
use tokio::net::tcp::OwnedWriteHalf;
use tokio::sync::mpsc::UnboundedReceiver;
use tokio::time::timeout;

use crate::net::Event;
use crate::net::frames;

use super::Link;
use super::Request;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(3);

pub enum SessionEnd {
    Disconnect,
    Quit,
    Reset,
    Failed(String),
}

pub struct Session {
    reader: OwnedReadHalf,
    writer: OwnedWriteHalf,
    buffer: Vec<u8>,
    sequence: u32,
    resetting: Cell<bool>,
}

impl Session {
    pub async fn connect(address: &str, link: &Link) -> Result<Session, String> {
        let stream = match timeout(CONNECT_TIMEOUT, TcpStream::connect(address)).await {
            Ok(Ok(s)) => s,
            Ok(Err(e)) => return Err(format!("connect: {e}")),
            Err(_) => return Err("Connect timed out".into()),
        };

        stream
            .set_nodelay(true)
            .map_err(|e| format!("set_nodelay failed: {e}"))?;
        let (mut reader, mut writer) = stream.into_split();
        let mut buffer = vec![0u8; MAX_MESSAGE_SIZE];
        let sequence = 1;

        let init = ToDevice::new(
            sequence,
            Command::Init {
                version: PROTOCOL_VERSION,
            },
        );
        frames::send(&mut writer, &init).await?;

        let len = match timeout(
            HANDSHAKE_TIMEOUT,
            frames::read_frame(&mut reader, &mut buffer),
        )
        .await
        {
            Ok(Ok(len)) => len,
            Ok(Err(e)) => return Err(e),
            Err(_) => return Err("Handshake timed out".into()),
        };
        let (reply, rest): (ToHost, &[u8]) = postcard::take_from_bytes(&buffer[..len])
            .map_err(|e| format!("Handshake reply undecodable: {e}"))?;
        if !rest.is_empty() {
            return Err(format!("Handshake reply had {} trailing bytes", rest.len()));
        }
        match reply.payload() {
            Telemetry::InitAck {
                version,
                firmware_id,
                built,
            } => {
                if sequence != reply.sequence() {
                    return Err(format!(
                        "Mismatched sequence in InitAck. Got {}, expected {}",
                        reply.sequence(),
                        sequence
                    ));
                }
                if version != PROTOCOL_VERSION {
                    return Err(format!(
                        "Device protocol version {version} incompatible with client {PROTOCOL_VERSION}"
                    ));
                }
                link.emit(link.check_firmware(firmware_id, built));
            }
            other => return Err(format!("Unexpected response to handshake: {other:?}")),
        }

        Ok(Session {
            reader,
            writer,
            buffer,
            sequence,
            resetting: Cell::new(false),
        })
    }

    pub async fn run(
        &mut self,
        requests: &mut UnboundedReceiver<Request>,
        link: &Link,
    ) -> SessionEnd {
        let Self {
            reader,
            writer,
            buffer,
            sequence,
            resetting,
        } = self;
        let mut reader = std::pin::pin!(Self::read_loop(reader, buffer, link, resetting));
        loop {
            tokio::select! {
                end = &mut reader => return end,
                req = requests.recv() => match req {
                    Some(Request::Reset) => {
                        *sequence += 1;
                        resetting.set(true);
                        if let Err(e) = frames::send(writer, &ToDevice::new(*sequence, Command::Reset)).await {
                            return SessionEnd::Failed(e);
                        }
                    }
                    Some(Request::Disconnect) => return SessionEnd::Disconnect,
                    Some(Request::Quit) | None => return SessionEnd::Quit,
                    Some(Request::Connect(_)) => {}
                }
            }
        }
    }

    async fn read_loop(
        reader: &mut OwnedReadHalf,
        buffer: &mut [u8],
        link: &Link,
        resetting: &Cell<bool>,
    ) -> SessionEnd {
        let mut next_log: Option<u32> = None;
        loop {
            let len = match frames::read_frame(reader, buffer).await {
                Ok(n) => n,
                Err(e) => {
                    return if resetting.get() {
                        SessionEnd::Reset
                    } else {
                        SessionEnd::Failed(e)
                    };
                }
            };

            let msg = match postcard::take_from_bytes::<ToHost>(&buffer[..len]) {
                Ok((m, r)) => {
                    if !r.is_empty() {
                        return SessionEnd::Failed(format!(
                            "Message {} had {} trailing bytes",
                            m.sequence(),
                            r.len()
                        ));
                    }
                    m
                }
                Err(_) => return SessionEnd::Failed("Malformed frame".into()),
            };

            match msg.payload() {
                Telemetry::Log { sequence, frame } => {
                    if let Some(expected) = next_log
                        && expected != sequence
                    {
                        link.emit(Event::Gap {
                            expected,
                            got: sequence,
                        });
                    }
                    next_log = Some(sequence.wrapping_add(1));
                    link.emit(Event::Log(link.decode(sequence, frame)));
                }
                Telemetry::Ack => link.emit(Event::Ack(msg.sequence())),
                Telemetry::InitAck { .. } => {
                    return SessionEnd::Failed("unexpected InitAck mid-session".into());
                }
            }
        }
    }
}
