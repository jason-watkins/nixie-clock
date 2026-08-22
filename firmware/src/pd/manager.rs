use defmt::error;
use defmt::info;
use defmt::warn;
use embassy_futures::select::Either;
use embassy_futures::select::select;
use embassy_time::Duration;
use embassy_time::TimeoutError;
use embassy_time::Timer;
use embassy_time::with_timeout;
use esp_hal::gpio::Input;
use esp_hal::gpio::Level;
use esp_hal::gpio::Output;

use crate::pd::HV_PERMISSION;
use crate::pd::HvPermission;
use crate::pd::hpi::AttachedType;
use crate::pd::hpi::ChargingMode;
use crate::pd::hpi::Error;
use crate::pd::hpi::HpiClient;
use crate::pd::hpi::HpiSnapshot;
use crate::pd::hpi::InterruptFlags;
use crate::pd::hpi::RpLevel;
use crate::pd::rdo::RequestDataObject;
use crate::status;

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Policy {
    Deny,
    Grant { voltage_mv: u32, current_ma: u32 },
    Renegotiate(RequestDataObject),
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum PdEvent {
    CommandSuccess,
    CommandFailed(u8),
    ContractComplete {
        success: bool,
        mismatch: bool,
        rdo: RequestDataObject,
    },
    DeviceReset,
    QueueOverflow,
    Overcurrent,
    Overvoltage,
    Attach,
    Detach,
    ContractCompleteNoPayload,
    SwapCompleted,
    PsReadySeen,
    AcceptSeen,
    GotoMin,
    Rejected,
    WaitReceived,
    HardReset,
    SoftReset,
    SourceCapabilities,
    SourceDisabled,
    TypeCErrorRecovery,
    NotSupportedReceived,
    RpChange,
    CCOvervoltage,
    Unknown(u8),
}

struct UsbMux(Output<'static>);

impl UsbMux {
    fn connect(&mut self) {
        self.0.set_level(Level::Low)
    }

    fn disconnect(&mut self) {
        self.0.set_level(Level::High)
    }
}

pub struct PdManager {
    hpi: HpiClient,
    int_pin: Input<'static>,
    fault_pin: Input<'static>,
    usb: UsbMux,
    negotiation_inhibited: bool,
}

impl PdManager {
    const EVENT_MASK: u32 = 0x0001297E;

    pub fn new(
        hpi: HpiClient,
        int_pin: Input<'static>,
        fault_pin: Input<'static>,
        usb_en: Output<'static>,
    ) -> PdManager {
        PdManager {
            hpi,
            int_pin,
            fault_pin,
            usb: UsbMux(usb_en),
            negotiation_inhibited: false,
        }
    }

    pub async fn run(mut self) -> ! {
        if !self.pd_init().await {
            Self::deny();
            status::report(status::PdStatus::Fault);
            core::future::pending::<()>().await;
            unreachable!("core::future::pending never completes");
        }

        if let Err(e) = self.sync().await {
            error!("PD initial negotiation failed: {}", e);
        }

        loop {
            const INT_TIMEOUT: Duration = Duration::from_secs(1);
            match with_timeout(
                INT_TIMEOUT,
                select(
                    self.int_pin.wait_for_low(),
                    self.fault_pin.wait_for_rising_edge(),
                ),
            )
            .await
            {
                Ok(Either::First(())) | Err(TimeoutError) => {
                    // Interrupt
                    if let Err(e) = self.sync().await {
                        error!("PD sync failed: {}", e);
                    }
                }
                Ok(Either::Second(())) => {
                    // Fault
                    Self::deny();
                    status::report(status::PdStatus::Fault);
                    error!("PD FAULT");
                }
            }
        }
    }

    async fn pd_init(&mut self) -> bool {
        const MAX_ATTEMPTS: usize = 5;
        let mut attempts = 0;
        loop {
            match self.hpi.read_id().await {
                Ok(0x2011) => {
                    info!("CYPD3176 found");
                    break;
                }
                Ok(id) => error!("Unexpected silicon ID {:#06x}", id),
                Err(e) => error!("SILICON_ID read failed: {}", e),
            }
            attempts += 1;
            if attempts >= MAX_ATTEMPTS {
                error!(
                    "Failed to find CYPD3176 after {} attempts. Giving up",
                    MAX_ATTEMPTS
                );
                return false;
            }
            Timer::after_millis(250).await;
        }

        if let Err(e) = self.hpi.write_event_mask(Self::EVENT_MASK).await {
            error!("Failed to set CYPD3176 event mask: {}", e);
            return false;
        }

        return true;
    }

    async fn sync(&mut self) -> Result<(), Error> {
        const MAX_ATTEMPTS: usize = 5;
        let mut attempts = 0;
        loop {
            self.drain_interrupts().await?;
            let snapshot = self.hpi.read_snapshot().await?;
            if !self.int_pin.is_high() {
                attempts += 1;
                if attempts >= MAX_ATTEMPTS {
                    error!(
                        "Failed to get snapshot after {} attempts. Giving up",
                        MAX_ATTEMPTS
                    );
                    Self::deny();
                    status::report(status::PdStatus::Fault);
                    return Ok(());
                }
                Timer::after_millis(500).await;
                continue;
            }

            if matches!(
                snapshot.charging_mode,
                ChargingMode::None | ChargingMode::Bc12
            ) {
                self.usb.connect();
            } else {
                self.usb.disconnect();
            }

            if self.fault_pin.is_high() {
                Self::deny();
                status::report(status::PdStatus::Fault);
                return Ok(());
            }

            let policy = evaluate(&snapshot);
            match policy {
                Policy::Deny => Self::deny(),
                Policy::Grant {
                    voltage_mv,
                    current_ma,
                } => Self::grant(voltage_mv, current_ma),
                Policy::Renegotiate(rdo) => {
                    Self::deny();
                    if !self.negotiation_inhibited {
                        self.hpi.write_rdo(rdo).await?
                    }
                }
            }
            return Ok(());
        }
    }

    async fn drain_interrupts(&mut self) -> Result<(), Error> {
        if self.int_pin.is_high() {
            return Ok(());
        }

        loop {
            if let Some(event) = handle_interrupt(&mut self.hpi).await? {
                use PdEvent::*;

                match event {
                    ContractComplete {
                        success,
                        mismatch,
                        rdo,
                    } => {
                        info!(
                            "PD Negotiated {}, success: {}, mismatch: {}",
                            rdo, success, mismatch
                        );
                        if !success {
                            self.negotiation_inhibited = true;
                            Self::deny();
                        }
                    }
                    ContractCompleteNoPayload => {
                        // NOOP
                    }
                    Attach | Overcurrent | Overvoltage | HardReset | SoftReset | GotoMin
                    | RpChange | SourceCapabilities | SourceDisabled | CCOvervoltage => {
                        Self::deny()
                    }
                    Detach => {
                        self.negotiation_inhibited = false;
                        Self::deny();
                    }
                    AcceptSeen | PsReadySeen | CommandSuccess | SwapCompleted | WaitReceived
                    | NotSupportedReceived => {
                        // NOOP
                    }
                    QueueOverflow => {
                        self.reset_interrupts().await?;
                        self.negotiation_inhibited = false;
                    }
                    Unknown(code) => {
                        warn!("Unknown PD event code {:#02x}", code);
                    }
                    CommandFailed(code) => {
                        error!("Command failed with code {:#02x}", code);
                    }
                    DeviceReset => {
                        Self::deny();
                        self.negotiation_inhibited = false;
                        self.hpi.write_event_mask(Self::EVENT_MASK).await?;
                    }
                    Rejected => {
                        self.negotiation_inhibited = true;
                    }
                    TypeCErrorRecovery => {
                        Self::deny();
                        self.negotiation_inhibited = false;
                    }
                }
            }

            Timer::after_micros(60).await;
            if self.int_pin.is_high() {
                return Ok(());
            }
        }
    }

    async fn reset_interrupts(&mut self) -> Result<(), Error> {
        if self.int_pin.is_high() {
            return Ok(());
        }

        loop {
            let flags = self.hpi.read_interrupt().await?;
            if !flags.any() {
                return Ok(());
            }
            self.hpi.clear_interrupt(flags).await?;

            Timer::after_micros(60).await;
            if self.int_pin.is_high() {
                return Ok(());
            }
        }
    }

    fn deny() {
        HV_PERMISSION.sender().send_if_modified(|v| {
            if *v == Some(HvPermission::Denied) {
                false
            } else {
                *v = Some(HvPermission::Denied);
                true
            }
        });
        status::report(status::PdStatus::Limited);
    }

    fn grant(voltage_mv: u32, current_ma: u32) {
        let permission = HvPermission::Granted {
            voltage_mv,
            current_ma,
        };
        HV_PERMISSION.sender().send_if_modified(|v| {
            if *v == Some(permission) {
                false
            } else {
                *v = Some(permission);
                true
            }
        });
        status::report(status::PdStatus::Full);
    }
}

async fn handle_interrupt(hpi: &mut HpiClient) -> Result<Option<PdEvent>, Error> {
    let mut event = None;
    let flags = hpi.read_interrupt().await?;
    if !flags.any() {
        return Ok(event);
    }

    if flags.device() {
        let dev_response = hpi.read_dev_response().await?;
        let code = u16::to_le_bytes(dev_response)[0];
        event = Some(dev_code_to_event(code));
        hpi.clear_interrupt(InterruptFlags::DEVICE).await?;
    } else if flags.pd() {
        let pd_response = hpi.read_pd_response().await?;
        let code = pd_response[0];
        let len = usize::from(u16::from_le_bytes([pd_response[2], pd_response[3]]));

        let extended;
        let payload: &[u8] = if len > 12 {
            extended = hpi.read_extended_pd_response().await?;
            &extended[4..(4 + len).min(extended.len())]
        } else {
            &pd_response[4..4 + len]
        };

        event = Some(if code == 0x86 && payload.len() >= 8 {
            PdEvent::ContractComplete {
                success: payload[0] & 0x01 != 0,
                mismatch: payload[0] & 0x02 != 0,
                rdo: u32::from_le_bytes(payload[4..8].try_into().unwrap()).into(),
            }
        } else {
            pd_code_to_event(code)
        });

        hpi.clear_interrupt(InterruptFlags::PD).await?;
    }

    Ok(event)
}

fn dev_code_to_event(code: u8) -> PdEvent {
    use PdEvent::*;

    match code {
        0x02 => CommandSuccess,
        v if v <= 0x0D => CommandFailed(v),
        0x80 => DeviceReset,
        v => Unknown(v),
    }
}

fn pd_code_to_event(code: u8) -> PdEvent {
    use PdEvent::*;

    match code {
        0x02 => CommandSuccess,
        v if v < 0x80 => CommandFailed(v),
        0x80 => DeviceReset,
        0x81 => QueueOverflow,
        0x82 => Overcurrent,
        0x83 => Overvoltage,
        0x84 => Attach,
        0x85 => Detach,
        0x86 => ContractCompleteNoPayload,
        0x87 => SwapCompleted,
        0x8A => PsReadySeen,
        0x8B => GotoMin,
        0x8C => AcceptSeen,
        0x8D => Rejected,
        0x8E => WaitReceived,
        0x8F => HardReset,
        0x91 => SourceCapabilities,
        0x9A => HardReset,
        0x9B => SoftReset,
        0x9D => SourceDisabled,
        0xA1 => TypeCErrorRecovery,
        0xA4 => NotSupportedReceived,
        0xAA => RpChange,
        0xBA => CCOvervoltage,
        v => Unknown(v),
    }
}

pub fn evaluate(snapshot: &HpiSnapshot) -> Policy {
    if !snapshot.type_c_status.connected() {
        Policy::Deny
    } else if snapshot.type_c_status.attached_type() != AttachedType::Source {
        Policy::Deny
    } else if snapshot.pd_status.explicit_contract() {
        let Some(pdo) = snapshot.current_pdo.fixed() else {
            return Policy::Deny;
        };
        let Some(required) = required_current_ma(pdo.voltage_mv()) else {
            return Policy::Deny;
        };

        if pdo.max_current_ma() < required {
            Policy::Deny
        } else if snapshot.current_rdo.operating_current_ma() < required
            || snapshot.current_rdo.max_operating_current_ma() < required
        {
            Policy::Renegotiate(
                snapshot
                    .current_rdo
                    .with_capability_mismatch(false)
                    .with_operating_current_ma(required)
                    .with_max_operating_current_ma(required),
            )
        } else {
            Policy::Grant {
                voltage_mv: pdo.voltage_mv(),
                current_ma: required,
            }
        }
    } else {
        match snapshot.charging_mode {
            ChargingMode::None => match snapshot.type_c_status.rp_level() {
                RpLevel::OneAmp5 => Policy::Grant {
                    voltage_mv: 5000,
                    current_ma: 1500,
                },
                RpLevel::ThreeAmp => Policy::Grant {
                    voltage_mv: 5000,
                    current_ma: 3000,
                },
                RpLevel::Default | RpLevel::Reserved => Policy::Deny,
            },
            ChargingMode::Bc12 => Policy::Grant {
                voltage_mv: 5000,
                current_ma: 1500,
            },
            ChargingMode::Qc2 | ChargingMode::Afc => {
                if snapshot.bus_voltage_mv >= 8500 {
                    let voltage_mv = ((snapshot.bus_voltage_mv + 250) / 500) * 500;
                    Policy::Grant {
                        voltage_mv,
                        current_ma: 750,
                    }
                } else {
                    Policy::Deny
                }
            }
            ChargingMode::Apple | ChargingMode::Unknown(_) => Policy::Deny,
        }
    }
}

fn required_current_ma(voltage_mv: u32) -> Option<u32> {
    match voltage_mv {
        5000 => Some(1250),
        9000 | 12000 => Some(750),
        _ => None,
    }
}
