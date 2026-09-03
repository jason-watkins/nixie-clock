use egui::Color32;
use egui::Visuals;
use egui_extras::Column;

use crate::net::LogEntry;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogColumn {
    Sequence,
    HostTime,
    DeviceTime,
    Level,
    Location,
    Message,
}

impl LogColumn {
    pub const ORDER: [LogColumn; 6] = [
        Self::Sequence,
        Self::HostTime,
        Self::DeviceTime,
        Self::Level,
        Self::Location,
        Self::Message,
    ];

    pub fn title(self) -> &'static str {
        match self {
            LogColumn::Sequence => "Sequence",
            LogColumn::HostTime => "Host Time",
            LogColumn::DeviceTime => "Device Time",
            LogColumn::Level => "Level",
            LogColumn::Location => "Location",
            LogColumn::Message => "Message",
        }
    }

    pub fn bounded(self) -> bool {
        matches!(self, Self::HostTime | Self::DeviceTime | Self::Level)
    }

    pub fn spec(self) -> Column {
        match self {
            Self::Sequence | Self::HostTime | Self::DeviceTime | Self::Level => Column::auto(),
            Self::Location => Column::initial(220.0).at_least(60.0).clip(true),
            Self::Message => Column::remainder().clip(true),
        }
    }

    pub fn text(self, entry: &LogEntry) -> String {
        match self {
            Self::Sequence => entry.sequence.to_string(),
            Self::HostTime => entry.host_timestamp.clone(),
            Self::DeviceTime => entry.device_timestamp.clone().unwrap_or_default(),
            Self::Level => entry
                .level
                .map(|l| ["TRACE", "DEBUG", "INFO", "WARN", "ERROR"][l as usize])
                .unwrap_or("UNK")
                .into(),
            Self::Location => entry
                .location
                .as_ref()
                .map(|(m, l)| format!("{m}:{l}"))
                .unwrap_or_default(),
            Self::Message => entry.text.clone(),
        }
    }

    pub fn color(self, entry: &LogEntry, visuals: &Visuals) -> Option<Color32> {
        match self {
            Self::Level => match entry.level {
                Some(0) => Some(visuals.weak_text_color()),
                Some(1) => Some(Color32::MAGENTA),
                Some(2) => None,
                Some(3) => Some(visuals.warn_fg_color),
                Some(4) => Some(visuals.error_fg_color),
                _ => Some(visuals.weak_text_color()),
            },
            _ => None,
        }
    }
}
