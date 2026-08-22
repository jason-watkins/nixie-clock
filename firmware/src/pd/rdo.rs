#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RequestDataObject(u32);

impl RequestDataObject {
    pub fn object_position(&self) -> u32 {
        (self.0 >> 28) & 0x07
    }

    pub fn giveback(&self) -> bool {
        (self.0 >> 27) & 0x01 == 0x01
    }

    pub fn capability_mismatch(&self) -> bool {
        (self.0 >> 26) & 0x01 == 0x01
    }

    pub fn communications_capable(&self) -> bool {
        (self.0 >> 25) & 0x01 == 0x01
    }

    pub fn no_usb_suspend(&self) -> bool {
        (self.0 >> 24) & 0x01 == 0x01
    }

    pub fn unchunked_extended_msg_supported(&self) -> bool {
        (self.0 >> 23) & 0x01 == 0x01
    }

    pub fn epr_mode_capable(&self) -> bool {
        (self.0 >> 22) & 0x01 == 0x01
    }

    pub fn operating_current_ma(&self) -> u32 {
        ((self.0 >> 10) & 0x03FF) * 10
    }

    pub fn max_operating_current_ma(&self) -> u32 {
        (self.0 & 0x03FF) * 10
    }

    pub fn with_capability_mismatch(self, value: bool) -> Self {
        Self((self.0 & !(0x01 << 26)) | ((value as u32) << 26))
    }

    pub fn with_communications_capable(self, value: bool) -> Self {
        Self((self.0 & !(0x01 << 25)) | ((value as u32) << 25))
    }

    pub fn with_no_usb_suspend(self, value: bool) -> Self {
        Self((self.0 & !(0x01 << 24)) | ((value as u32) << 24))
    }

    pub fn with_unchunked_extended_msg_supported(self, value: bool) -> Self {
        Self((self.0 & !(0x01 << 23)) | ((value as u32) << 23))
    }

    pub fn with_epr_mode_capable(self, value: bool) -> Self {
        Self((self.0 & !(0x01 << 22)) | ((value as u32) << 22))
    }

    pub fn with_operating_current_ma(self, ma: u32) -> Self {
        debug_assert!(ma % 10 == 0 && ma <= 10_230);
        Self((self.0 & !(0x03FF << 10)) | (((ma / 10) & 0x03FF) << 10))
    }

    pub fn with_max_operating_current_ma(self, ma: u32) -> Self {
        debug_assert!(ma % 10 == 0 && ma <= 10_230);
        Self((self.0 & !(0x03FF)) | ((ma / 10) & 0x03FF))
    }
}

impl From<u32> for RequestDataObject {
    fn from(value: u32) -> Self {
        Self(value)
    }
}

impl From<RequestDataObject> for u32 {
    fn from(value: RequestDataObject) -> Self {
        value.0
    }
}

impl defmt::Format for RequestDataObject {
    fn format(&self, f: defmt::Formatter) {
        let op = self.operating_current_ma();
        let max = self.max_operating_current_ma();
        defmt::write!(
            f,
            "Pdo {} op {}.{:02}A max {}.{:02}A mismatch={} (raw {:#010x})",
            self.object_position(),
            op / 1000,
            (op % 1000) / 10,
            max / 1000,
            (max % 1000) / 10,
            self.capability_mismatch(),
            self.0
        );
    }
}
