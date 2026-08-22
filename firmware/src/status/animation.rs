#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Segment {
    pub from: u8,
    pub to: u8,
    pub ms: u16,
}

impl Segment {
    pub const NONE: Segment = Segment::hold(0, 0);

    pub const fn ramp(from: u8, to: u8, ms: u16) -> Segment {
        Segment { from, to, ms }
    }

    pub const fn hold(level: u8, ms: u16) -> Segment {
        Segment {
            from: level,
            to: level,
            ms,
        }
    }

    pub fn level_at(&self, elapsed_ms: u16) -> u8 {
        let from = self.from as i32;
        let to = self.to as i32;
        (from + (to - from) * (elapsed_ms as i32) / (self.ms as i32)) as u8
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Repeat {
    None,
    After { ms: u16 },
}

enum Position<'a> {
    In(&'a Segment, u32),
    Gap(u32),
    Done,
}

#[derive(Clone, PartialEq, Eq)]
pub struct Pattern<S: ?Sized = [Segment]> {
    pub repeat: Repeat,
    pub segments: S,
}

impl Pattern {
    pub fn level_at(&self, elapsed_ms: u32) -> u8 {
        match self.locate(elapsed_ms) {
            Position::In(segment, t) => segment.level_at(t as u16),
            _ => self.segments.last().map_or(0, |s| s.to),
        }
    }

    pub fn next_update_ms(&self, elapsed_ms: u32) -> Option<u32> {
        const FRAME_MS: u32 = 10;
        match self.locate(elapsed_ms) {
            Position::In(segment, t) => {
                let remaining = (segment.ms as u32) - t;
                Some(if segment.from == segment.to {
                    remaining
                } else {
                    remaining.min(FRAME_MS)
                })
            }
            Position::Gap(remaining) => Some(remaining),
            Position::Done => None,
        }
    }

    pub fn cycle_ms(&self) -> u32 {
        let sum: u32 = self.segments.iter().map(|s| s.ms as u32).sum();
        match self.repeat {
            Repeat::None => sum,
            Repeat::After { ms } => sum + (ms as u32),
        }
    }

    fn locate(&self, elapsed_ms: u32) -> Position<'_> {
        let cycle = self.cycle_ms();
        let mut t = match self.repeat {
            Repeat::After { .. } if cycle > 0 => elapsed_ms % cycle,
            _ => elapsed_ms,
        };
        for segment in self.segments.iter() {
            let ms = segment.ms as u32;
            if t < ms {
                return Position::In(segment, t);
            }
            t -= ms;
        }
        match self.repeat {
            Repeat::After { ms } if (ms as u32) > t => Position::Gap((ms as u32) - t),
            _ => Position::Done,
        }
    }
}

impl Pattern<[Segment; 2]> {
    pub const fn heartbeat(level: u8, duration_ms: u16) -> Self {
        const BEAT_DIVIDER: u16 = 8;
        const RISE_DIVIDER: u16 = 4;
        let beat_ms = duration_ms / BEAT_DIVIDER;
        let rest_ms = beat_ms * (BEAT_DIVIDER - 1);
        let rise_ms = beat_ms / RISE_DIVIDER;
        let fall_ms = rise_ms * (RISE_DIVIDER - 1);
        Pattern {
            repeat: Repeat::After { ms: rest_ms },
            segments: [
                Segment::ramp(0, level, rise_ms),
                Segment::ramp(level, 0, fall_ms),
            ],
        }
    }
}

impl<const N: usize> Pattern<[Segment; N]> {
    pub const fn blink_code(long: u8, short: u8, repeat: bool) -> Self {
        let blinks = (long + short) as usize;
        assert!(
            blinks * 2 == N,
            "blink code segment count must be 2x total blink count"
        );

        let mut segments = [Segment::NONE; N];
        let mut i = 0;
        while i < long as usize {
            segments[i * 2] = Segment::hold(100, 750);
            segments[i * 2 + 1] = Segment::hold(0, 250);
            i += 1
        }
        while i < (short + long) as usize {
            segments[i * 2] = Segment::hold(100, 250);
            segments[i * 2 + 1] = Segment::hold(0, 250);
            i += 1
        }

        let repeat = if repeat {
            Repeat::After { ms: 2000 }
        } else {
            Repeat::None
        };

        Pattern { repeat, segments }
    }

    pub const fn pulse(count: u8, repeat: bool) -> Self {
        assert!(
            2 * (count as usize) == N,
            "pulse segment count must be 2x count"
        );

        let mut segments = [Segment::NONE; N];
        let mut i = 0;
        while i < count as usize {
            segments[i * 2] = Segment::ramp(0, 100, 250);
            segments[i * 2 + 1] = Segment::ramp(100, 0, 250);
            i += 1
        }

        let repeat = if repeat {
            Repeat::After { ms: 1000 }
        } else {
            Repeat::None
        };

        Pattern { repeat, segments }
    }
}
