use chrono::DateTime;
use chrono::FixedOffset;
use chrono::Timelike;
use defmt::error;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_time::Duration;
use embassy_time::TimeoutError;
use embassy_time::Timer;
use embassy_time::with_timeout;
use esp_hal::gpio::Input;
use esp_hal::gpio::InputConfig;
use esp_hal::gpio::InputPin;
use esp_hal::gpio::Level;
use esp_hal::gpio::Output;
use esp_hal::gpio::OutputConfig;
use esp_hal::gpio::OutputPin;

use crate::status;
use crate::status::ClockStatus;
use crate::time;

/// Binds the board's GPIO assignments to the display.
#[macro_export]
macro_rules! nixie_pins {
    ($p:ident) => {
        $crate::nixie::ClockFace::new(
            $crate::nixie::Bcd::new($p.GPIO9, $p.GPIO13, $p.GPIO21, $p.GPIO11),
            $crate::nixie::Bcd::new($p.GPIO47, $p.GPIO12, $p.GPIO10, $p.GPIO14),
            $crate::nixie::Bcd::new($p.GPIO18, $p.GPIO7, $p.GPIO5, $p.GPIO16),
            $crate::nixie::Bcd::new($p.GPIO4, $p.GPIO15, $p.GPIO17, $p.GPIO6),
            $p.GPIO8,
            $p.GPIO48,
        )
    };
}

/// Represents a single BCD converter/tube output
pub struct Bcd<'a> {
    pins: [Output<'a>; 4], // [A, B, C, D]
}

impl<'a> Bcd<'a> {
    pub fn new(
        a: impl OutputPin + 'a,
        b: impl OutputPin + 'a,
        c: impl OutputPin + 'a,
        d: impl OutputPin + 'a,
    ) -> Bcd<'a> {
        let initial_level = Level::High;
        let config = OutputConfig::default();
        let a = Output::new(a, initial_level, config);
        let b = Output::new(b, initial_level, config);
        let c = Output::new(c, initial_level, config);
        let d = Output::new(d, initial_level, config);
        Bcd { pins: [a, b, c, d] }
    }

    pub fn write(&mut self, d: Option<u8>) {
        const BLANK: u8 = 0b00001111;
        let d = d
            .map(|d| {
                if d > 9 {
                    warn!("Writing out of range digit {}, display will be blank", d);
                    BLANK
                } else {
                    const DIGIT_TO_BCD: [u8; 10] = [6, 4, 5, 1, 0, 9, 8, 2, 3, 7];
                    DIGIT_TO_BCD[d as usize]
                }
            })
            .unwrap_or(BLANK);

        for i in 0..4 {
            let on = if (d >> i) & 1 == 1 {
                Level::High
            } else {
                Level::Low
            };
            self.pins[i].set_level(on);
        }
    }
}

pub struct ClockFace<'a> {
    h10: Bcd<'a>,
    h1: Bcd<'a>,
    m10: Bcd<'a>,
    m1: Bcd<'a>,
    hv_en: Output<'a>,
    hv_pgood: Input<'a>,
}

impl<'a> ClockFace<'a> {
    pub fn new(
        h10: Bcd<'a>,
        h1: Bcd<'a>,
        m10: Bcd<'a>,
        m1: Bcd<'a>,
        hv_en: impl OutputPin + 'a,
        hv_pgood: impl InputPin + 'a,
    ) -> ClockFace<'a> {
        let hv_en = Output::new(hv_en, Level::Low, OutputConfig::default());
        let hv_pgood = Input::new(hv_pgood, InputConfig::default());
        ClockFace {
            h10,
            h1,
            m10,
            m1,
            hv_en,
            hv_pgood,
        }
    }

    pub fn write_digits(&mut self, digits: [Option<u8>; 4]) {
        self.h10.write(digits[0]);
        self.h1.write(digits[1]);
        self.m10.write(digits[2]);
        self.m1.write(digits[3]);
    }

    pub async fn enable_hv(&mut self) {
        info!("Enabling HV rail");
        const MAX_ATTEMPTS: usize = 5;
        let mut fail_count = 0;
        for _ in 0..MAX_ATTEMPTS {
            self.hv_en.set_high();
            const HV_STARTUP_MAX: Duration = Duration::from_millis(250);
            match with_timeout(HV_STARTUP_MAX, self.hv_pgood.wait_for_high()).await {
                Ok(()) => {
                    info!("HV rail up");
                    return;
                }
                Err(TimeoutError) => {
                    self.hv_en.set_low();
                    fail_count += 1;

                    const HV_RETRY_BASE: Duration = Duration::from_millis(250);
                    const HV_RETRY_MAX: Duration = Duration::from_secs(60);
                    let retry_delay = (HV_RETRY_BASE * fail_count).min(HV_RETRY_MAX);
                    Timer::after(retry_delay).await
                }
            }
        }

        // Fall through loop indicates we failed MAX_ATTEMPTS times. Give up and park the clock task.
        status::report(ClockStatus::Failed);
        error!("Failed to start HV converter");
        core::future::pending::<()>().await;
        unreachable!("core::future::pending never completes");
    }

    pub fn disable_hv(&mut self) {
        self.hv_en.set_low();
    }

    pub fn hv_good(&self) -> bool {
        self.hv_pgood.is_high()
    }
}

fn digits(t: DateTime<FixedOffset>) -> [Option<u8>; 4] {
    let hour = t.hour();
    let minute = t.minute();

    let h10 = (hour / 10) as u8;
    let h1 = (hour % 10) as u8;
    let m10 = (minute / 10) as u8;
    let m1 = (minute % 10) as u8;

    [Some(h10), Some(h1), Some(m10), Some(m1)]
}

pub fn init(clock_face: ClockFace<'static>, spawner: &Spawner) {
    let clock_token = update_clock(clock_face).expect("Failed to create clock task token");

    spawner.spawn(clock_token);
    info!("Clock initialized");
}

#[embassy_executor::task]
async fn update_clock(mut clock_face: ClockFace<'static>) -> ! {
    const DEFAULT_DISPLAY: [Option<u8>; 4] = [None, None, None, None];
    let mut shown = DEFAULT_DISPLAY;

    loop {
        status::report(ClockStatus::Starting);
        clock_face.enable_hv().await;

        const HV_FAIL_LIMIT: usize = 3;
        let mut hv_fail_count = 0;
        loop {
            if !clock_face.hv_good() {
                hv_fail_count += 1;
                if hv_fail_count >= HV_FAIL_LIMIT {
                    warn!("HV rail failed");
                    clock_face.disable_hv();
                    break;
                }
            } else {
                hv_fail_count = 0;
            }

            status::report(ClockStatus::Good);
            let now = time::local_now().map(digits).unwrap_or(DEFAULT_DISPLAY);
            if now != shown {
                let glyphs = now.map(|d| match d {
                    Some(d) => char::from_digit(d as u32, 10).unwrap_or('?'),
                    None => ' ',
                });
                info!("{}{}:{}{}", glyphs[0], glyphs[1], glyphs[2], glyphs[3]);
                clock_face.write_digits(now);
                shown = now;
            }

            const TICK: Duration = Duration::from_millis(200);
            Timer::after(TICK).await
        }
    }
}
