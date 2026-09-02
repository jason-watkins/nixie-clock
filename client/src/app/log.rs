use egui_extras::{Column, TableBuilder};

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
            LogColumn::HostTime => "HostTime",
            LogColumn::DeviceTime => "DeviceTime",
            LogColumn::Level => "Level",
            LogColumn::Location => "Location",
            LogColumn::Message => "Message",
        }
    }

    pub fn spec(self) -> Column {
        match self {
            Self::Sequence | Self::HostTime | Self::DeviceTime | Self::Level => Column::auto(),
            Self::Location => Column::initial(220.0).at_least(60.0).clip(true),
            Self::Message => Column::remainder().clip(true),
        }
    }

    pub fn text(self, e: &LogEntry) -> String {
        match self {
            Self::Sequence => e.sequence.to_string(),
            Self::HostTime => e.host_timestamp.clone(),
            Self::DeviceTime => e.device_timestamp.clone().unwrap_or_default(),
            Self::Level => e
                .level
                .map(|l| ["TRACE", "DEBUG", "INFO", "WARN", "ERROR"][l as usize])
                .unwrap_or("UNK")
                .into(),
            Self::Location => e
                .location
                .as_ref()
                .map(|(m, l)| format!("{m}:{l}"))
                .unwrap_or_default(),
            Self::Message => e.text.clone(),
        }
    }
}
