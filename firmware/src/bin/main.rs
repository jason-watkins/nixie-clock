#![no_std]
#![no_main]
#![deny(
    clippy::mem_forget,
    reason = "mem::forget is generally not safe to do with esp_hal types, especially those \
    holding buffers for the duration of a data transfer."
)]
#![deny(clippy::large_stack_frames)]

use defmt::info;
use embassy_executor::Spawner;
use embassy_time::{Duration, Timer};
use esp_hal::clock::CpuClock;
use esp_hal::gpio::OutputPin;
use esp_hal::gpio::{Level, Output, OutputConfig};
use esp_hal::interrupt::software::SoftwareInterruptControl;
use esp_hal::timer::timg::TimerGroup;
use panic_rtt_target as _;

extern crate alloc;

// This creates a default app-descriptor required by the esp-idf bootloader.
// For more information see: <https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/app_image_format.html#application-description>
esp_bootloader_esp_idf::esp_app_desc!();

#[allow(
    clippy::large_stack_frames,
    reason = "it's not unusual to allocate larger buffers etc. in main"
)]
#[esp_rtos::main]
async fn main(spawner: Spawner) -> ! {
    // generator version: 1.3.0
    // generator parameters: --chip esp32s3 -o esp32s3-wroom-1 -o unstable-hal -o alloc -o wifi -o embassy -o vscode -o esp -o probe-rs -o defmt -o panic-rtt-target

    rtt_target::rtt_init_defmt!();

    let config = esp_hal::Config::default().with_cpu_clock(CpuClock::max());
    let peripherals = esp_hal::init(config);

    // These GPIO pins are in use by some feature of the module and should not be used.
    let _ = peripherals.GPIO27;
    let _ = peripherals.GPIO28;
    let _ = peripherals.GPIO29;
    let _ = peripherals.GPIO30;
    let _ = peripherals.GPIO31;
    let _ = peripherals.GPIO32;

    // Enable the USB mux. This steals the USB data pins from the CYPD3176, but if we have power
    // then power negotiation should already be complete.
    let _usb_en = UsbEnable::new(peripherals.GPIO36);

    esp_alloc::heap_allocator!(#[esp_hal::ram(reclaimed)] size: 73744);

    let timg0 = TimerGroup::new(peripherals.TIMG0);
    let sw_interrupt = SoftwareInterruptControl::new(peripherals.SW_INTERRUPT);
    esp_rtos::start(timg0.timer0, sw_interrupt.software_interrupt0);

    info!("Embassy initialized...");

    let mut led = Output::new(peripherals.GPIO38, Level::Low, OutputConfig::default());
    // TODO: Create a status LED task that drives the status LED based on overall clock state

    let seed = {
        let _trng = esp_hal::rng::TrngSource::new(peripherals.RNG, peripherals.ADC1);
        let rng = esp_hal::rng::Rng::new();
        ((rng.random() as u64) << 32) | (rng.random() as u64)
    };
    let wifi_stack = nixie_clock::net::init(peripherals.WIFI, seed, &spawner);

    info!("Wi-Fi initialized...");

    // TODO: Gracefully display something while waiting for wi-fi to connect
    wifi_stack.wait_config_up().await;
    info!(
        "Connected at IP {}",
        wifi_stack.config_v4().expect("No IP after WiFi init")
    );

    loop {
        info!("Hello world!");
        led.toggle();
        Timer::after(Duration::from_secs(1)).await;
    }
}

/// RAII wrapper to hold the USB enable output pin.
struct UsbEnable<'a> {
    _pin: Output<'a>,
}

impl<'a> UsbEnable<'a> {
    pub fn new(pin: impl OutputPin + 'a) -> Self {
        Self {
            _pin: Output::new(pin, Level::Low, OutputConfig::default()),
        }
    }
}
