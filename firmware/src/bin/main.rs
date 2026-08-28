#![no_std]
#![no_main]
#![deny(
    clippy::mem_forget,
    reason = "mem::forget is generally not safe to do with esp_hal types, especially those \
    holding buffers for the duration of a data transfer."
)]
#![deny(clippy::large_stack_frames)]

use core::panic::PanicInfo;
use core::sync::atomic::AtomicBool;
use core::sync::atomic::Ordering;

use defmt::error;
use defmt::info;
use embassy_executor::Spawner;
use esp_hal::clock::CpuClock;
use esp_hal::interrupt::software::SoftwareInterruptControl;
use esp_hal::timer::timg::TimerGroup;
use nixie_clock::hv;
use nixie_clock::nixie_pins;
use nixie_clock::pd;
use nixie_clock::status;
use nixie_clock::status::BootPhase;
use nixie_clock::tctm;

extern crate alloc;

esp_bootloader_esp_idf::esp_app_desc!(
    env!("NIXIE_FIRMWARE_ID"),
    env!("CARGO_PKG_NAME"),
    env!("NIXIE_BUILD_TIME"),
    env!("NIXIE_BUILD_DATE"),
    esp_bootloader_esp_idf::ESP_IDF_COMPATIBLE_VERSION,
    esp_bootloader_esp_idf::MMU_PAGE_SIZE,
    0,
    u16::MAX,
    esp_bootloader_esp_idf::SECURE_VERSION
);

#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    static PANICKING: AtomicBool = AtomicBool::new(false);
    critical_section::with(|_| {
        if !PANICKING.swap(true, Ordering::Relaxed) {
            tctm::panic_flush();
            defmt::error!("{}", defmt::Display2Format(info));
            tctm::panic_flush();
        }
        loop {
            core::hint::spin_loop();
        }
    })
}

#[allow(
    clippy::large_stack_frames,
    reason = "it's not unusual to allocate larger buffers etc. in main"
)]
#[esp_rtos::main]
async fn main(spawner: Spawner) -> ! {
    // generator version: 1.3.0
    // generator parameters: --chip esp32s3 -o esp32s3-wroom-1 -o unstable-hal -o alloc -o wifi -o embassy -o vscode -o esp -o probe-rs -o defmt -o panic-rtt-target

    tctm::init_logging();
    info!(
        "Reset reason: {}",
        defmt::Debug2Format(&esp_hal::system::reset_reason())
    );
    info!(
        "Firmware {=str} ({})",
        env!("NIXIE_FIRMWARE_ID"),
        env!("NIXIE_BUILD_TIMESTAMP")
    );

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

    status::report(BootPhase::Hv);
    hv::init(peripherals.GPIO8, peripherals.GPIO48, &spawner);

    status::report(BootPhase::Net);
    let seed = {
        let _trng = esp_hal::rng::TrngSource::new(peripherals.RNG, peripherals.ADC1);
        let rng = esp_hal::rng::Rng::new();
        ((rng.random() as u64) << 32) | (rng.random() as u64)
    };
    let wifi_stack = nixie_clock::net::init(peripherals.WIFI, seed, &spawner);
    nixie_clock::tctm::init(wifi_stack, &spawner);

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
