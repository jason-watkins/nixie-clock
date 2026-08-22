#![no_std]
#![no_main]
#![deny(
    clippy::mem_forget,
    reason = "mem::forget is generally not safe to do with esp_hal types, especially those \
    holding buffers for the duration of a data transfer."
)]
#![deny(clippy::large_stack_frames)]

use defmt::error;
use defmt::info;
use embassy_executor::Spawner;
use esp_hal::clock::CpuClock;
use esp_hal::interrupt::software::SoftwareInterruptControl;
use esp_hal::timer::timg::TimerGroup;
use nixie_clock::nixie_pins;
use nixie_clock::pd;
use nixie_clock::status;
use nixie_clock::status::BootPhase;
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
    let status_led = status::init(peripherals.LEDC, peripherals.GPIO38);

    // These GPIO pins are in use by some feature of the module and should not be used.
    let _ = peripherals.GPIO27;
    let _ = peripherals.GPIO28;
    let _ = peripherals.GPIO29;
    let _ = peripherals.GPIO30;
    let _ = peripherals.GPIO31;
    let _ = peripherals.GPIO32;

    esp_alloc::heap_allocator!(#[esp_hal::ram(reclaimed)] size: 73744);

    let timg0 = TimerGroup::new(peripherals.TIMG0);
    let sw_interrupt = SoftwareInterruptControl::new(peripherals.SW_INTERRUPT);
    esp_rtos::start(timg0.timer0, sw_interrupt.software_interrupt0);

    info!("Embassy initialized...");

    status::spawn(status_led, &spawner);

    status::report(BootPhase::Pd);
    pd::init(
        peripherals.I2C0,
        peripherals.GPIO1,
        peripherals.GPIO2,
        peripherals.GPIO35,
        peripherals.GPIO37,
        peripherals.GPIO36,
        &spawner,
    );

    status::report(BootPhase::Net);
    let seed = {
        let _trng = esp_hal::rng::TrngSource::new(peripherals.RNG, peripherals.ADC1);
        let rng = esp_hal::rng::Rng::new();
        ((rng.random() as u64) << 32) | (rng.random() as u64)
    };
    let wifi_stack = nixie_clock::net::init(peripherals.WIFI, seed, &spawner);

    status::report(BootPhase::Time);
    nixie_clock::time::init(wifi_stack, &spawner);

    status::report(BootPhase::Display);
    let clock_pins = nixie_pins!(peripherals);
    nixie_clock::nixie::init(clock_pins, &spawner);

    wifi_stack.wait_config_up().await;
    match wifi_stack.config_v4() {
        Some(config) => info!("Connected at IP {}", config.address),
        None => error!("No wifi config after up"),
    }

    // All of the operational logic lives in tasks. Park main now that setup is complete.
    status::report(BootPhase::Running);
    core::future::pending::<()>().await;
    unreachable!("core::future::pending never completes");
}
