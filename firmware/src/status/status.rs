#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum BootPhase {
    Hal,
    Pd,
    Net,
    Time,
    Display,
    Running,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum PdStatus {
    Limited,
    Full,
    Fault,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum WifiStatus {
    Down,
    Associating,
    Connected,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum TimeStatus {
    Never,
    Stale,
    Synced,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum ClockStatus {
    Off,
    Starting,
    Good,
    Failed,
}

#[derive(Clone, PartialEq, Eq, defmt::Format)]
pub struct Status {
    pub boot: BootPhase,
    pub pd: PdStatus,
    pub wifi: WifiStatus,
    pub time: TimeStatus,
    pub clock: ClockStatus,
}

impl Status {
    pub const fn new() -> Self {
        Status {
            boot: BootPhase::Hal,
            pd: PdStatus::Fault,
            wifi: WifiStatus::Down,
            time: TimeStatus::Never,
            clock: ClockStatus::Off,
        }
    }
}
