use crate::time;
use chrono::DateTime;
use chrono::FixedOffset;
use chrono::Timelike;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_time::Duration;
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

pub struct ClockFace<'a> {
    h10: Bcd<'a>,
    h1: Bcd<'a>,
    m10: Bcd<'a>,
    m1: Bcd<'a>,
}

impl<'a> ClockFace<'a> {
    pub fn new(h10: Bcd<'a>, h1: Bcd<'a>, m10: Bcd<'a>, m1: Bcd<'a>) -> ClockFace<'a> {
        ClockFace { h10, h1, m10, m1 }
    }

    pub fn write_digits(&mut self, digits: [Option<u8>; 4]) {
        self.h10.write(digits[0]);
        self.h1.write(digits[1]);
        self.m10.write(digits[2]);
        self.m1.write(digits[3]);
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
