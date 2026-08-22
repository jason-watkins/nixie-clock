#[derive(Clone, Copy, PartialEq, Eq, Debug, defmt::Format)]
pub enum Kind {
    Fixed,
    Battery,
    Variable,
    Apdo,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, defmt::Format)]
pub enum PeakCurrent {
    NoOverload,
    OverloadLevel1,
    OverloadLevel2,
    OverloadLevel3,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PowerDataObject(u32);

impl PowerDataObject {
    pub fn pdo_type(&self) -> Kind {
        match self.0 >> 30 {
            0x00 => Kind::Fixed,
            0x01 => Kind::Battery,
            0x02 => Kind::Variable,
            0x03 => Kind::Apdo,
            _ => unreachable!("logic shift guarantees 2 bits"),
        }
    }

    pub fn fixed(self) -> Option<FixedSupplyPdo> {
        match self.pdo_type() {
            Kind::Fixed => Some(FixedSupplyPdo(self.0)),
            _ => None,
        }
    }
}

impl From<u32> for PowerDataObject {
    fn from(value: u32) -> Self {
        Self(value)
    }
}

impl defmt::Format for PowerDataObject {
    fn format(&self, f: defmt::Formatter) {
        match self.pdo_type() {
            Kind::Fixed => defmt::write!(f, "{}", FixedSupplyPdo(self.0)),
            Kind::Battery => defmt::write!(f, "Battery (raw {:#010x})", self.0),
            Kind::Variable => defmt::write!(f, "Variable (raw {:#010x})", self.0),
            Kind::Apdo => defmt::write!(f, "Apdo (raw {:#010x})", self.0),
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct FixedSupplyPdo(u32);

impl FixedSupplyPdo {
    pub fn dual_role_power(&self) -> bool {
        (self.0 >> 29) & 0x01 == 0x01
    }

    pub fn suspend_supported(&self) -> bool {
        (self.0 >> 28) & 0x01 == 0x01
    }

    pub fn unconstrained_power(&self) -> bool {
        (self.0 >> 27) & 0x01 == 0x01
    }

    pub fn communications_capable(&self) -> bool {
        (self.0 >> 26) & 0x01 == 0x01
    }

    pub fn dual_role_data(&self) -> bool {
        (self.0 >> 25) & 0x01 == 0x01
    }

    pub fn unchunked_extended_msg_supported(&self) -> bool {
        (self.0 >> 24) & 0x01 == 0x01
    }

    pub fn epr_mode_capable(&self) -> bool {
        (self.0 >> 23) & 0x01 == 0x01
    }

    pub fn peak_current(&self) -> PeakCurrent {
        match (self.0 >> 20) & 0x03 {
            0x00 => PeakCurrent::NoOverload,
            0x01 => PeakCurrent::OverloadLevel1,
            0x02 => PeakCurrent::OverloadLevel2,
            0x03 => PeakCurrent::OverloadLevel3,
            _ => unreachable!("logic shift and mask guarantees 2 bits"),
        }
    }

    pub fn voltage_mv(&self) -> u32 {
        ((self.0 >> 10) & 0x03FF) * 50
    }

    pub fn max_current_ma(&self) -> u32 {
        (self.0 & 0x03FF) * 10
    }
}

impl defmt::Format for FixedSupplyPdo {
    fn format(&self, f: defmt::Formatter) {
        let mv = self.voltage_mv();
        let ma = self.max_current_ma();
        defmt::write!(
            f,
            "Fixed {}.{:02}V {}.{:02}A (raw {:#010x})",
            mv / 1000,
            (mv % 1000) / 10,
            ma / 1000,
            (ma % 1000) / 10,
            self.0
        );
    }
}
