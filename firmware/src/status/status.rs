#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum BootPhase {
    Hal,
    Pd,
    Hv,
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
pub enum HvStatus {
    Off,
    Starting,
    Up,
    Failed,
}

#[derive(Clone, PartialEq, Eq, defmt::Format)]
pub struct Status {
    pub boot: BootPhase,
    pub pd: PdStatus,
    pub wifi: WifiStatus,
    pub time: TimeStatus,
    pub hv: HvStatus,
}

impl Status {
    pub const fn new() -> Self {
        Status {
            boot: BootPhase::Hal,
            pd: PdStatus::Limited,
            wifi: WifiStatus::Down,
            time: TimeStatus::Never,
            hv: HvStatus::Off,
        }
    }
}
