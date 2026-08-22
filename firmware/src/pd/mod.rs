mod hpi;
mod manager;
pub mod pdo;
pub mod rdo;

use crate::pd::manager::PdManager;
use embassy_executor::Spawner;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::DynReceiver;
use embassy_sync::watch::Watch;
use esp_hal::gpio::Input;
use esp_hal::gpio::InputConfig;
use esp_hal::gpio::InputPin;
use esp_hal::gpio::Level;
use esp_hal::gpio::Output;
use esp_hal::gpio::OutputConfig;
use esp_hal::gpio::OutputPin;
use esp_hal::i2c::master::{Config, I2c};
use esp_hal::peripherals::I2C0;
use esp_hal::time::Rate;
use hpi::HpiClient;

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum HvPermission {
    Denied,
    Granted { voltage_mv: u32, current_ma: u32 },
}

static HV_PERMISSION: Watch<CriticalSectionRawMutex, HvPermission, 1> = Watch::new();

/// Get a receiver for the HV permission state. Panics on failure.
pub fn permission_receiver() -> DynReceiver<'static, HvPermission> {
    HV_PERMISSION.dyn_receiver().unwrap()
}

pub fn init(
    i2c: I2C0<'static>,
    sda: impl OutputPin + InputPin + 'static,
    scl: impl OutputPin + InputPin + 'static,
    pd_int: impl InputPin + 'static,
    pd_fault: impl InputPin + 'static,
    usb_en: impl OutputPin + 'static,
    spawner: &Spawner,
) {
    let config = Config::default().with_frequency(Rate::from_khz(100));
    let i2c = I2c::new(i2c, config)
        .expect("Failed to initialize I2C")
        .with_sda(sda)
        .with_scl(scl)
        .into_async();

    let hpi = HpiClient::new(i2c);
    let pd_int = Input::new(pd_int, InputConfig::default());
    let pd_fault = Input::new(pd_fault, InputConfig::default());
    let usb_en = Output::new(usb_en, Level::High, OutputConfig::default());

    let manager = PdManager::new(hpi, pd_int, pd_fault, usb_en);

    HV_PERMISSION.sender().send(HvPermission::Denied);

    let pd_token = pd_task(manager).expect("Failed to create pd_task");

    spawner.spawn(pd_token);
}

#[embassy_executor::task]
async fn pd_task(manager: PdManager) {
    manager.run().await;
}
