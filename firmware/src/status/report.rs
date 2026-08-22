use crate::status::PdStatus;

use super::BootPhase;
use super::HvStatus;
use super::TimeStatus;
use super::WifiStatus;

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Report {
    Boot(BootPhase),
    Pd(PdStatus),
    Wifi(WifiStatus),
    Time(TimeStatus),
    Hv(HvStatus),
}

impl From<BootPhase> for Report {
    fn from(value: BootPhase) -> Self {
        Report::Boot(value)
    }
}

impl From<PdStatus> for Report {
    fn from(value: PdStatus) -> Self {
        Report::Pd(value)
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

impl From<HvStatus> for Report {
    fn from(value: HvStatus) -> Self {
        Report::Hv(value)
    }
}
