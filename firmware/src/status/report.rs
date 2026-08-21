use super::BootPhase;
use super::ClockStatus;
use super::TimeStatus;
use super::WifiStatus;

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Report {
    Boot(BootPhase),
    Wifi(WifiStatus),
    Time(TimeStatus),
    Clock(ClockStatus),
}

impl From<BootPhase> for Report {
    fn from(value: BootPhase) -> Self {
        Report::Boot(value)
    }
}

impl From<WifiStatus> for Report {
    fn from(value: WifiStatus) -> Self {
        Report::Wifi(value)
    }
}

impl From<TimeStatus> for Report {
    fn from(value: TimeStatus) -> Self {
        Report::Time(value)
    }
}

impl From<ClockStatus> for Report {
    fn from(value: ClockStatus) -> Self {
        Report::Clock(value)
    }
}
