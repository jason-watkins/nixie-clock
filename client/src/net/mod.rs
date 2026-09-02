mod frames;
mod link;
mod session;
mod supervisor;

pub use frames::LogEntry;
pub use link::Link;
pub use supervisor::spawn;

use crate::firmware::Descriptor;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ConnectionState {
    #[default]
    Idle,
    Connecting,
    Connected,
    Resetting,
}

impl ConnectionState {
    pub fn is_connected(&self) -> bool {
        self == &ConnectionState::Connected
    }

    pub fn describe(&self) -> &str {
        match self {
            ConnectionState::Idle => "idle",
            ConnectionState::Connecting => "connecting",
            ConnectionState::Connected => "connected",
            ConnectionState::Resetting => "device resetting",
        }
    }
}

#[derive(Debug)]
pub enum Request {
    Connect(String),
    Disconnect,
    Reset,
    Quit,
}

#[derive(Debug)]
pub struct DeviceFirmware {
    pub descriptor: Descriptor,
    pub matches: bool,
}

#[derive(Debug)]
pub enum Event {
    State(ConnectionState),
    Firmware(DeviceFirmware),
    Log(LogEntry),
    Gap { expected: u32, got: u32 },
    Ack(u32),
    Error(String),
}
