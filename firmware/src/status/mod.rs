use defmt::error;
use defmt::info;
use embassy_executor::Spawner;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::Watch;

mod animation;
mod led;
mod report;
mod status;

use embassy_time::Duration;
use embassy_time::Instant;
use embassy_time::with_timeout;
use esp_hal::gpio::DriveMode;
use esp_hal::gpio::OutputPin;
use esp_hal::gpio::interconnect::OutputSignal;
use esp_hal::ledc::LSGlobalClkSource;
use esp_hal::ledc::Ledc;
use esp_hal::ledc::LowSpeed;
use esp_hal::ledc::channel;
use esp_hal::ledc::channel::Channel;
use esp_hal::ledc::channel::ChannelIFace;
use esp_hal::ledc::timer;
use esp_hal::ledc::timer::Timer;
use esp_hal::ledc::timer::TimerIFace;
use esp_hal::ledc::timer::config::Duty;
use esp_hal::peripherals::LEDC;
use esp_hal::time::Rate;
pub use led::*;
pub use report::*;
use static_cell::StaticCell;
pub use status::*;

use crate::status::animation::Pattern;
use crate::status::animation::Segment;

static STATUS: Watch<CriticalSectionRawMutex, Status, 1> = Watch::new_with(Status::new());

pub fn report(report: impl Into<Report>) {
    let report = report.into();
    STATUS.sender().send_if_modified(|s| {
        let Some(s) = s.as_mut() else {
            error!("No status in report closure");
            return false;
        };

        match report {
            Report::Boot(v) => {
                if v != s.boot {
                    s.boot = v;
                    return true;
                }
            }
            Report::Pd(v) => {
                if v != s.pd {
                    s.pd = v;
                    return true;
                }
            }
            Report::Wifi(v) => {
                if v != s.wifi {
                    s.wifi = v;
                    return true;
                }
            }
            Report::Time(v) => {
                if v != s.time {
                    s.time = v;
                    return true;
                }
            }
            Report::Hv(v) => {
                if v != s.hv {
                    s.hv = v;
                    return true;
                }
            }
        }

        false
    });
}

pub fn init(ledc: LEDC<'static>, led_pin: impl OutputPin + 'static) -> StatusLed {
    static LEDC_CELL: StaticCell<Ledc> = StaticCell::new();
    let ledc = LEDC_CELL.init(Ledc::new(ledc));
    ledc.set_global_slow_clock(LSGlobalClkSource::APBClk);

    static TIMER: StaticCell<Timer<'static, LowSpeed>> = StaticCell::new();
    let timer = TIMER.init(ledc.timer(timer::Number::Timer0));
    if let Err(e) = timer.configure(timer::config::Config {
        duty: Duty::Duty12Bit,
        clock_source: timer::LSClockSource::APBClk,
        frequency: Rate::from_khz(4),
    }) {
        error!("Failed to configure LED timer: {}", e);
        return StatusLed::default();
    };

    let led = OutputSignal::from(led_pin).with_output_inverter(true);

    let mut channel: Channel<LowSpeed> = ledc.channel(channel::Number::Channel0, led);
    if let Err(e) = channel.configure(channel::config::Config {
        timer,
        duty_pct: 0,
        drive_mode: DriveMode::PushPull,
    }) {
        error!("Failed to configure LED channel: {}", e);
        return StatusLed::default();
    };

    let led = StatusLed::new(channel);
    led.set(100);
    led
}

pub fn spawn(led: StatusLed, spawner: &Spawner) {
    let Ok(led_task_token) = led_task(led) else {
        error!("Failed to spawn status led_task");
        return;
    };

    spawner.spawn(led_task_token);
    info!("Status reporter initialized...")
}

#[embassy_executor::task]
async fn led_task(led: StatusLed) -> ! {
    let mut rx = STATUS.receiver().unwrap();
    let mut pattern = pattern_for(&rx.try_get().unwrap_or(Status::new()));
    let mut started = Instant::now();

    loop {
        let elapsed = started.elapsed().as_millis() as u32;
        let level = pattern.level_at(elapsed);
        led.set(level);

        let update = match pattern.next_update_ms(elapsed) {
            Some(ms) => with_timeout(Duration::from_millis(ms as u64), rx.changed())
                .await
                .ok(),
            None => Some(rx.changed().await),
        };

        if let Some(status) = update {
            let next = pattern_for(&status);
            pattern = next;
            started = Instant::now();
        }
    }
}

fn pattern_for(s: &Status) -> &'static Pattern {
    pd_pattern(&s.pd)
        .or_else(|| wifi_pattern(&s.wifi))
        .or_else(|| time_pattern(&s.time))
        .or_else(|| hv_pattern(&s.hv))
        .unwrap_or_else(|| boot_pattern(&s.boot))
}

fn boot_pattern(phase: &BootPhase) -> &'static Pattern {
    static P_HAL: Pattern<[Segment; 2]> = Pattern::pulse(1, true);
    static P_PD: Pattern<[Segment; 4]> = Pattern::pulse(2, true);
    static P_HV: Pattern<[Segment; 6]> = Pattern::pulse(3, true);
    static P_NET: Pattern<[Segment; 8]> = Pattern::pulse(4, true);
    static P_TIME: Pattern<[Segment; 10]> = Pattern::pulse(5, true);
    static P_DISPLAY: Pattern<[Segment; 12]> = Pattern::pulse(6, true);
    static P_RUNNING: Pattern<[Segment; 2]> = Pattern::heartbeat(25, 10000);
    match phase {
        BootPhase::Hal => &P_HAL,
        BootPhase::Hv => &P_HV,
        BootPhase::Pd => &P_PD,
        BootPhase::Net => &P_NET,
        BootPhase::Time => &P_TIME,
        BootPhase::Display => &P_DISPLAY,
        BootPhase::Running => &P_RUNNING,
    }
}

fn pd_pattern(status: &PdStatus) -> Option<&'static Pattern> {
    static P_LIMITED: Pattern<[Segment; 10]> = Pattern::blink_code(3, 2, true);
    static P_FAULT: Pattern<[Segment; 12]> = Pattern::blink_code(3, 3, true);
    match status {
        PdStatus::Limited => Some(&P_LIMITED),
        PdStatus::Full => None,
        PdStatus::Fault => Some(&P_FAULT),
    }
}

fn wifi_pattern(status: &WifiStatus) -> Option<&'static Pattern> {
    static P1: Pattern<[Segment; 2]> = Pattern::blink_code(0, 1, true);
    static P2: Pattern<[Segment; 4]> = Pattern::blink_code(0, 2, true);
    match status {
        WifiStatus::Down => Some(&P1),
        WifiStatus::Associating => Some(&P2),
        WifiStatus::Connected => None,
    }
}

fn time_pattern(status: &TimeStatus) -> Option<&'static Pattern> {
    static P1: Pattern<[Segment; 6]> = Pattern::blink_code(1, 2, true);
    static P2: Pattern<[Segment; 2]> = Pattern::heartbeat(100, 2000);
    match status {
        TimeStatus::Never => Some(&P1),
        TimeStatus::Stale => Some(&P2),
        TimeStatus::Synced => None,
    }
}

fn hv_pattern(status: &HvStatus) -> Option<&'static Pattern> {
    static P_HV_STARTING: Pattern<[Segment; 8]> = Pattern::blink_code(2, 2, true);
    static P_HV_FAILED: Pattern<[Segment; 10]> = Pattern::blink_code(2, 3, true);
    match status {
        HvStatus::Off => None,
        HvStatus::Starting => Some(&P_HV_STARTING),
        HvStatus::Up => None,
        HvStatus::Failed => Some(&P_HV_FAILED),
    }
}
