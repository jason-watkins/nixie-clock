use core::cell::Cell;

use chrono::DateTime;
use chrono::FixedOffset;
use chrono::Utc;
use critical_section::Mutex;
use defmt::error;
use embassy_executor::Spawner;
use embassy_net::Stack;
use embassy_time::Duration;
use embassy_time::Instant;

mod sntp;
mod tz;

const STALE_THRESHOLD: Duration = Duration::from_secs(24 * 60 * 60);

#[derive(Clone, Copy)]
struct Snapshot {
    offset_us: i64,
    at: Instant,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Clock {
    Never,
    Synced(DateTime<Utc>),
    Stale(DateTime<Utc>),
}

impl Clock {
    pub fn utc(self) -> Option<DateTime<Utc>> {
        match self {
            Clock::Never => None,
            Clock::Synced(now) => Some(now),
            Clock::Stale(now) => Some(now),
        }
    }

    pub fn local(self) -> Option<DateTime<FixedOffset>> {
        let utc = self.utc()?;
        let offset = tz::current().offset_at(utc)?;
        Some(utc.with_timezone(&offset))
    }
}

static SNAPSHOT: Mutex<Cell<Option<Snapshot>>> = Mutex::new(Cell::new(None));

fn read_state() -> Option<Snapshot> {
    critical_section::with(|cs| SNAPSHOT.borrow(cs).get())
}

fn write_state(value: Snapshot) -> Option<Snapshot> {
    critical_section::with(|cs| SNAPSHOT.borrow(cs).replace(Some(value)))
}

/// Gets the current NTP time
pub fn now() -> Option<DateTime<Utc>> {
    state().utc()
}

/// Gets the current NTP time, adjusted to the local timezone
pub fn local_now() -> Option<DateTime<FixedOffset>> {
    state().local()
}

/// Gets the raw NTP clock state
pub fn state() -> Clock {
    let mcu_now = Instant::now();
    let Some(value) = read_state() else {
        return Clock::Never;
    };

    let mcu_now_us = mcu_now.as_micros() as i64;
    let ticks = mcu_now_us.saturating_add(value.offset_us);
    let Some(now) = DateTime::from_timestamp_micros(ticks) else {
        error!(
            "Failed to construct DateTime from {} + {} = {}",
            mcu_now_us, value.offset_us, ticks
        );
        return Clock::Never;
    };

    if value.at + STALE_THRESHOLD < mcu_now {
        Clock::Stale(now)
    } else {
        Clock::Synced(now)
    }
}

fn set_ntp_offset(offset_us: i64) -> Option<i64> {
    let at = Instant::now();
    let state = Snapshot { offset_us, at };
    let previous = write_state(state);
    previous.map(|p| offset_us - p.offset_us)
}

pub fn init(stack: Stack<'static>, spawner: &Spawner) {
    sntp::init(stack, spawner);
}
