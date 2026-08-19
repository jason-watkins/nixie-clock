use chrono::DateTime;
use chrono::Datelike;
use chrono::FixedOffset;
use chrono::NaiveDate;
use chrono::NaiveDateTime;
use chrono::TimeDelta;
use chrono::Utc;
use chrono::Weekday;

/// The date and local time at which a DST transition takes effect
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Rule {
    /// Calendar month of the transition
    month: u8,
    /// Which occurrence of `weekday` within `month`
    ///
    /// `5` means "last", even in months with only 4 occurrences of `weekday`
    week: u8,
    /// Day of the week of the transition
    weekday: Weekday,
    /// Seconds after local midnight of the transition
    time_s: u32,
}

impl Rule {
    pub const fn new(month: u8, week: u8, weekday: Weekday, time_s: u32) -> Rule {
        Rule {
            month,
            week,
            weekday,
            time_s,
        }
    }

    /// The instant this rule fires, in UTC, for `year`.
    ///
    /// `offset_s` is the offset in force prior to the instant.
    fn transition_utc(&self, year: i32, offset_s: i64) -> Option<NaiveDateTime> {
        let month = u32::from(self.month);
        let date = NaiveDate::from_weekday_of_month_opt(year, month, self.weekday, self.week)
            .or_else(|| {
                NaiveDate::from_weekday_of_month_opt(
                    year,
                    month,
                    self.weekday,
                    self.week.saturating_sub(1),
                )
            })?;

        date.and_hms_opt(0, 0, 0)?
            .checked_add_signed(TimeDelta::seconds(i64::from(self.time_s)))?
            .checked_sub_signed(TimeDelta::seconds(offset_s))
    }
}

/// The DST rules for a location.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Tz {
    /// Seconds east of UTC while standard time is in effect
    std_offset: i32,
    /// Seconds east of UTC while daylight time is in effect
    dst_offset: i32,
    /// When daylight time begins. `time_s`` in this rule is in *standard* time.
    start: Rule,
    /// When daylight time ends. `time_s` in this rule is in *daylight* time.
    end: Rule,
}

impl Tz {
    pub const fn new(std_offset: i32, dst_offset: i32, start: Rule, end: Rule) -> Tz {
        Tz {
            std_offset,
            dst_offset,
            start,
            end,
        }
    }

    pub fn offset_at(&self, utc: DateTime<Utc>) -> Option<FixedOffset> {
        let year = utc.year();
        let start = self
            .start
            .transition_utc(year, i64::from(self.std_offset))?;
        let end = self.end.transition_utc(year, i64::from(self.dst_offset))?;
        let now = utc.naive_utc();

        let in_dst = if start < end {
            now >= start && now < end
        } else {
            now >= start || now < end
        };

        FixedOffset::east_opt(if in_dst {
            self.dst_offset
        } else {
            self.std_offset
        })
    }
}

/// America/Los Angeles
pub const DEFAULT_LOCAL: Tz = Tz::new(
    -8 * 3600,
    -7 * 3600,
    Rule::new(3, 2, Weekday::Sun, 2 * 3600),
    Rule::new(11, 1, Weekday::Sun, 2 * 3600),
);

pub fn current() -> Tz {
    DEFAULT_LOCAL
}
