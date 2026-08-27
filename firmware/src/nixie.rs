use crate::hv;
use crate::status::HvStatus;
use crate::time;
use chrono::DateTime;
use chrono::FixedOffset;
use chrono::Timelike;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_sync::watch::DynReceiver;
use embassy_time::Duration;
use embassy_time::Instant;
use embassy_time::Timer;
use esp_hal::gpio::Level;
use esp_hal::gpio::Output;
use esp_hal::gpio::OutputConfig;
use esp_hal::gpio::OutputPin;

/// Binds the board's GPIO assignments to the display.
#[macro_export]
macro_rules! nixie_pins {
    ($p:ident) => {
        $crate::nixie::ClockFace::new(
            $crate::nixie::Bcd::new($p.GPIO9, $p.GPIO13, $p.GPIO21, $p.GPIO11),
            $crate::nixie::Bcd::new($p.GPIO47, $p.GPIO12, $p.GPIO10, $p.GPIO14),
            $crate::nixie::Bcd::new($p.GPIO18, $p.GPIO7, $p.GPIO5, $p.GPIO16),
            $crate::nixie::Bcd::new($p.GPIO4, $p.GPIO15, $p.GPIO17, $p.GPIO6),
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

const DEFAULT_DISPLAY: [Option<u8>; 4] = [None, None, None, None];

pub struct ClockFace<'a> {
    h10: Bcd<'a>,
    h1: Bcd<'a>,
    m10: Bcd<'a>,
    m1: Bcd<'a>,
    hv_status_rx: DynReceiver<'static, HvStatus>,
    hv_status: HvStatus,
    shown: [Option<u8>; 4],
}

impl<'a> ClockFace<'a> {
    pub fn new(h10: Bcd<'a>, h1: Bcd<'a>, m10: Bcd<'a>, m1: Bcd<'a>) -> ClockFace<'a> {
        ClockFace {
            h10,
            h1,
            m10,
            m1,
            hv_status_rx: hv::status_receiver(),
            hv_status: HvStatus::Off,
            shown: DEFAULT_DISPLAY,
        }
    }

    pub async fn write_digits(&mut self, digits: [Option<u8>; 4]) {
        self.m1.write(digits[3]);
        if self.shown[3] == None {
            Timer::after_millis(25).await;
        }
        self.m10.write(digits[2]);
        if self.shown[2] == None {
            Timer::after_millis(25).await;
        }
        self.h1.write(digits[1]);
        if self.shown[1] == None {
            Timer::after_millis(25).await;
        }
        self.h10.write(digits[0]);
        self.shown = digits;
    }

    pub async fn blank(&mut self) {
        self.write_digits(DEFAULT_DISPLAY).await;
    }

    pub async fn run(mut self) -> ! {
        loop {
            self.wait_for_hv().await;

            let now = time::local_now().map(digits).unwrap_or(DEFAULT_DISPLAY);
            if now != self.shown {
                let glyphs = now.map(|d| match d {
                    Some(d) => char::from_digit(d as u32, 10).unwrap_or('?'),
                    None => ' ',
                });
                info!("{}{}:{}{}", glyphs[0], glyphs[1], glyphs[2], glyphs[3]);
                self.write_digits(now).await;
            }

            // Try to keep clock updates precise. On the normal path, tick slowly to just before the
            // next update, then busy wait. The slow ticks rather than a single sleep bound how long
            // it takes us to pick up on an NTP update. On all other paths, degrade gracefully in
            // ways that don't hog the core too badly.
            let remaining = Self::until_next_minute();
            const GUARD: Duration = Duration::from_millis(1);
            let remaining = remaining
                .checked_sub(GUARD)
                .unwrap_or_default()
                .max(Duration::from_micros(100))
                .min(Duration::from_secs(5));
            Timer::after(remaining).await;

            let remaining = Self::until_next_minute();
            if remaining <= GUARD {
                let deadline = Instant::now() + remaining;
                while Instant::now() < deadline {
                    core::hint::spin_loop();
                }
            }
        }
    }

    fn until_next_minute() -> Duration {
        let Some(now) = time::local_now() else {
            const DEFAULT_TICK: Duration = Duration::from_secs(5);
            return DEFAULT_TICK;
        };

        const ONE_MINUTE: Duration = Duration::from_secs(60);
        let current_minute_fraction = Duration::from_secs(now.second() as u64)
            + Duration::from_micros(now.timestamp_subsec_micros() as u64);
        ONE_MINUTE
            .checked_sub(current_minute_fraction)
            .unwrap_or_default()
    }

    async fn wait_for_hv(&mut self) {
        let last_status = self.hv_status;
        self.hv_status = self.hv_status_rx.get().await;
        if self.status_good(last_status).await {
            return;
        }

        loop {
            let last_status = self.hv_status;
            self.hv_status = self.hv_status_rx.changed().await;
            if self.status_good(last_status).await {
                return;
            }
        }
    }

    async fn status_good(&mut self, last_status: HvStatus) -> bool {
        const RAIL_STABILIZATION_TIME: Duration = Duration::from_millis(50);
        match self.hv_status {
            HvStatus::Off => {
                self.blank().await;
                info!("Clock detected HV rail turn off. Blanking display");
                false
            }
            HvStatus::Starting => false,
            HvStatus::Up => {
                if last_status == HvStatus::Up {
                    // Previously up, so we've already waited for the rail to stabilize, and still up so we can
                    // continue operation without delay.
                    true
                } else {
                    info!(
                        "HV rail up, clock waiting {}ms to give it time to stabilize",
                        RAIL_STABILIZATION_TIME.as_millis()
                    );
                    Timer::after(RAIL_STABILIZATION_TIME).await; // Give the rail time to stabilize
                    self.hv_status = self.hv_status_rx.get().await;
                    if self.hv_status == HvStatus::Up {
                        info!("Clock wait complete. Resuming normal operation");
                        true
                    } else {
                        false
                    }
                }
            }
            HvStatus::Failed => false,
        }
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
    clock_face.blank().await;
    clock_face.run().await;
}
