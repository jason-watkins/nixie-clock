use chrono::Local;
use defmt_decoder::Locations;
use defmt_decoder::Table;
use egui::Context;
use std::path::Path;
use std::sync::mpsc::Sender;

use super::DeviceFirmware;
use super::Event;
use super::LogEntry;
use crate::firmware;
use crate::firmware::Descriptor;

pub struct Link {
    events: Sender<Event>,
    context: Context,
    table: Table,
    locations: Locations,
    elf_descriptor: Option<Descriptor>,
}

impl Link {
    pub fn new(events: Sender<Event>, context: Context) -> Result<Link, String> {
        let (table, locations) = firmware::table()?;
        Ok(Link {
            events,
            context,
            table,
            locations,
            elf_descriptor: firmware::descriptor(),
        })
    }

    pub fn emit(&self, event: Event) {
        // A send error means the App (the receiver) is gone; the thread is about to exit anyway.
        let _ = self.events.send(event);
        self.context.request_repaint();
    }

    pub fn decode(&self, sequence: u32, frame: &[u8]) -> LogEntry {
        fn short_file(path: &Path) -> String {
            let s = path.to_string_lossy().replace('\\', "/");
            const FIRMWARE_ROOT: &'static str = "/firmware/";
            if let Some(i) = s.find(FIRMWARE_ROOT) {
                // Our files, e.g. src/tctm/mod.rs
                return s[i + FIRMWARE_ROOT.len()..].to_owned();
            }
            const CRATE_ROOT: &'static str = "/index.crates.io-";
            if let Some(i) = s.find(CRATE_ROOT) {
                let from_registry = &s[i + 1..];
                if let Some((_, rest)) = from_registry.split_once("/") {
                    return rest.to_owned();
                }
            }
            s
        }

        let host_time = Local::now().format("%H:%M:%S%.3f").to_string();
        let mut d = self.table.new_stream_decoder();
        d.received(frame);
        match d.decode() {
            Ok(frame) => LogEntry {
                host_timestamp: host_time,
                device_timestamp: frame.display_timestamp().map(|t| t.to_string()),
                level: frame.level().map(|l| l as u8),
                location: self
                    .locations
                    .get(&frame.index())
                    .map(|l| (short_file(&l.file), l.line)),
                text: frame.display_message().to_string(),
                sequence,
            },
            Err(e) => LogEntry {
                host_timestamp: host_time,
                device_timestamp: None,
                level: None,
                location: None,
                text: format!(
                    "<{e:?}> {}",
                    frame
                        .iter()
                        .map(|b| format!("{b:02x}"))
                        .collect::<Vec<_>>()
                        .join(" ")
                ),
                sequence,
            },
        }
    }

    pub fn check_firmware(&self, device_id: &str, device_built: &str) -> Event {
        let matches = self
            .elf_descriptor
            .as_ref()
            .is_some_and(|d| d.id == device_id);
        Event::Firmware(DeviceFirmware {
            descriptor: Descriptor {
                id: device_id.to_owned(),
                built: device_built.to_owned(),
            },
            matches,
        })
    }
}
