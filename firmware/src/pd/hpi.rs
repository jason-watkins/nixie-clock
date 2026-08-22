use esp_hal::Async;
use esp_hal::i2c::master::I2c;

use crate::pd::pdo::PowerDataObject;
use crate::pd::rdo::RequestDataObject;

#[derive(defmt::Format)]
pub enum Error {
    I2c(esp_hal::i2c::master::Error),
}

impl From<esp_hal::i2c::master::Error> for Error {
    fn from(value: esp_hal::i2c::master::Error) -> Self {
        Error::I2c(value)
    }
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct InterruptFlags(u8);

impl InterruptFlags {
    pub const DEVICE: InterruptFlags = InterruptFlags(0x01);
    pub const PD: InterruptFlags = InterruptFlags(0x02);

    pub fn device(self) -> bool {
        self.0 & 0x01 != 0
    }

    pub fn pd(self) -> bool {
        self.0 & 0x02 != 0
    }

    pub fn any(self) -> bool {
        self.0 != 0
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub struct PdStatus(u32);

impl PdStatus {
    pub fn explicit_contract(&self) -> bool {
        (self.0 >> 10) & 0x01 == 0x01
    }

    pub fn pe_sink_ready(&self) -> bool {
        (self.0 >> 15) & 0x01 == 0x01
    }
}

impl defmt::Format for PdStatus {
    fn format(&self, fmt: defmt::Formatter) {
        defmt::write!(
            fmt,
            "PdStatus(Contract: {}, Sink Ready: {})",
            self.explicit_contract(),
            self.pe_sink_ready()
        );
    }
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum AttachedType {
    Nothing,
    Source,
    DebugAccessory,
    Reserved(u8),
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum RpLevel {
    Default,
    OneAmp5,
    ThreeAmp,
    Reserved,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub struct TypeCStatus(u32);

impl TypeCStatus {
    pub fn connected(&self) -> bool {
        self.0 & 0x01 == 0x01
    }

    pub fn attached_type(&self) -> AttachedType {
        match (self.0 >> 2) & 0x07 {
            0x00 => AttachedType::Nothing,
            0x02 => AttachedType::Source,
            0x03 => AttachedType::DebugAccessory,
            v => AttachedType::Reserved(v as u8),
        }
    }

    pub fn rp_level(&self) -> RpLevel {
        match (self.0 >> 6) & 0x03 {
            0x00 => RpLevel::Default,
            0x01 => RpLevel::OneAmp5,
            0x02 => RpLevel::ThreeAmp,
            0x03 => RpLevel::Reserved,
            _ => unreachable!("shift and mask guarantees 2 bit"),
        }
    }
}

impl defmt::Format for TypeCStatus {
    fn format(&self, fmt: defmt::Formatter) {
        defmt::write!(
            fmt,
            "TypeCStatus(Connected: {}, Attached: {}, RP Level: {})",
            self.connected(),
            self.attached_type(),
            self.rp_level()
        );
    }
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum ChargingMode {
    None,
    Bc12,
    Qc2,
    Afc,
    Apple,
    Unknown(u8),
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub struct HpiSnapshot {
    pub pd_status: PdStatus,
    pub type_c_status: TypeCStatus,
    pub bus_voltage_mv: u32,
    pub charging_mode: ChargingMode,
    pub current_pdo: PowerDataObject,
    pub current_rdo: RequestDataObject,
}

pub struct HpiClient {
    i2c: I2c<'static, Async>,
}

impl HpiClient {
    const HPI_ADDRESS: u8 = 0x08;

    pub fn new(i2c: I2c<'static, Async>) -> HpiClient {
        HpiClient { i2c }
    }

    async fn read<const N: usize>(&mut self, reg: Register<N>) -> Result<[u8; N], Error> {
        let mut write_buffer = [0u8; 2];
        let mut read_buffer = [0u8; N];
        reg.fill_address(&mut write_buffer);
        self.i2c
            .write_read_async(Self::HPI_ADDRESS, &write_buffer, &mut read_buffer)
            .await?;
        Ok(read_buffer)
    }

    async fn read_u8(&mut self, reg: Register<1>) -> Result<u8, Error> {
        Ok(self.read(reg).await?[0])
    }

    async fn read_u16(&mut self, reg: Register<2>) -> Result<u16, Error> {
        Ok(u16::from_le_bytes(self.read(reg).await?))
    }

    async fn read_u32(&mut self, reg: Register<4>) -> Result<u32, Error> {
        Ok(u32::from_le_bytes(self.read(reg).await?))
    }

    pub async fn read_id(&mut self) -> Result<u16, Error> {
        self.read_u16(Register::SILICON_ID).await
    }

    pub async fn read_interrupt(&mut self) -> Result<InterruptFlags, Error> {
        // Bits 7..2 are reserved, so mask them out
        Ok(InterruptFlags(
            self.read_u8(Register::INTERRUPT).await? & 0x03,
        ))
    }

    pub async fn read_dev_response(&mut self) -> Result<u16, Error> {
        self.read_u16(Register::DEV_RESPONSE).await
    }

    pub async fn read_bus_voltage_mv(&mut self) -> Result<u32, Error> {
        Ok((self.read_u8(Register::BUS_VOLTAGE).await? as u32) * 100)
    }

    pub async fn read_current_rdo(&mut self) -> Result<RequestDataObject, Error> {
        Ok(self.read_u32(Register::CURRENT_RDO).await?.into())
    }

    pub async fn read_current_pdo(&mut self) -> Result<PowerDataObject, Error> {
        Ok(self.read_u32(Register::CURRENT_PDO).await?.into())
    }

    pub async fn read_pd_status(&mut self) -> Result<PdStatus, Error> {
        Ok(PdStatus(self.read_u32(Register::PD_STATUS).await?))
    }

    pub async fn read_type_c_status(&mut self) -> Result<TypeCStatus, Error> {
        Ok(TypeCStatus(self.read_u32(Register::TYPE_C_STATUS).await?))
    }

    pub async fn read_charging_mode(&mut self) -> Result<ChargingMode, Error> {
        Ok(match self.read_u8(Register::CHARGING_MODE_STATUS).await? {
            0 => ChargingMode::None,
            1 => ChargingMode::Bc12,
            2 => ChargingMode::Qc2,
            4 => ChargingMode::Afc,
            5 => ChargingMode::Apple,
            v => ChargingMode::Unknown(v),
        })
    }

    pub async fn read_snapshot(&mut self) -> Result<HpiSnapshot, Error> {
        Ok(HpiSnapshot {
            pd_status: self.read_pd_status().await?,
            type_c_status: self.read_type_c_status().await?,
            bus_voltage_mv: self.read_bus_voltage_mv().await?,
            charging_mode: self.read_charging_mode().await?,
            current_pdo: self.read_current_pdo().await?,
            current_rdo: self.read_current_rdo().await?,
        })
    }

    pub async fn read_pd_response(&mut self) -> Result<[u8; 16], Error> {
        self.read(Register::PD_RESPONSE).await
    }

    pub async fn read_extended_pd_response(&mut self) -> Result<[u8; 36], Error> {
        self.read(Register::PD_RESPONSE_EXTENDED).await
    }

    async fn write<const N: usize>(
        &mut self,
        reg: Register<N>,
        data: &[u8; N],
    ) -> Result<(), Error> {
        const { assert!(N <= 4) }
        let mut buffer = [0u8; 6];
        reg.fill_address(&mut buffer);
        buffer[2..(2 + data.len())].copy_from_slice(data);
        self.i2c
            .write_async(Self::HPI_ADDRESS, &buffer[..2 + data.len()])
            .await?;
        Ok(())
    }

    async fn write_u8(&mut self, reg: Register<1>, data: u8) -> Result<(), Error> {
        self.write(reg, &[data]).await
    }

    async fn write_u32(&mut self, reg: Register<4>, data: u32) -> Result<(), Error> {
        let data = u32::to_le_bytes(data);
        self.write(reg, &data).await
    }

    pub async fn clear_interrupt(&mut self, flags: InterruptFlags) -> Result<(), Error> {
        self.write_u8(Register::INTERRUPT, flags.0).await
    }

    pub async fn write_rdo(&mut self, rdo: RequestDataObject) -> Result<(), Error> {
        self.write_u32(Register::SINK_RDO_REQUEST, rdo.into()).await
    }

    pub async fn write_event_mask(&mut self, mask: u32) -> Result<(), Error> {
        self.write_u32(Register::EVENT_MASK, mask).await
    }
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct Register<const LEN: usize>(u16);

impl Register<1> {
    /// Interrupt source flags
    pub const INTERRUPT: Self = Register(0x0006);

    /// Live VBUS voltage in 100mV units
    pub const BUS_VOLTAGE: Self = Register(0x100D);

    /// Active legacy charging protocol
    pub const CHARGING_MODE_STATUS: Self = Register(0x1095);
}

impl Register<2> {
    /// Device identity; should always read 0x2011
    pub const SILICON_ID: Self = Register(0x0002);

    /// Response to device commands and device events
    pub const DEV_RESPONSE: Self = Register(0x007E);
}

impl Register<4> {
    /// PD contract state
    pub const PD_STATUS: Self = Register(0x1008);

    /// Type-C port state
    pub const TYPE_C_STATUS: Self = Register(0x100C);

    /// The source PDO the active contract selected
    pub const CURRENT_PDO: Self = Register(0x1010);

    /// The RDO most recently sent to the source
    pub const CURRENT_RDO: Self = Register(0x1014);

    /// Enables async event reporting per event class
    pub const EVENT_MASK: Self = Register(0x1024);

    /// Sends a raw RDO to the source, not validated by the BCR
    pub const SINK_RDO_REQUEST: Self = Register(0x1054);
}

impl Register<16> {
    /// Port response header plus the first 12 bytes of read data memory. Covers the 8 byte
    /// contract-complete payload.
    pub const PD_RESPONSE: Self = Register(0x1400);
}

impl Register<36> {
    /// Port response header plus 32 bytes of data memory, enough for the largest payload we expect
    /// to inspect.
    pub const PD_RESPONSE_EXTENDED: Self = Register(0x1400);
}

impl<const N: usize> Register<N> {
    pub fn fill_address(&self, buffer: &mut [u8]) {
        buffer[0] = self.0 as u8;
        buffer[1] = (self.0 >> 8) as u8;
    }
}
