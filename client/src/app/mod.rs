use std::collections::VecDeque;
use std::time::Duration;

use chrono::Local;
use eframe::APP_KEY;
use eframe::CreationContext;
use eframe::Storage;
use egui::Button;
use egui::CentralPanel;
use egui::Color32;
use egui::Label;
use egui::Panel;
use egui::RichText;
use egui::TextEdit;
use egui::TextStyle;
use egui_extras::TableBuilder;
use serde::Deserialize;
use serde::Serialize;
use std::sync::mpsc::Receiver;
use tokio::sync::mpsc::UnboundedSender;
use tokio::time::Instant;

use crate::app::log::LogColumn;
use crate::firmware;
use crate::firmware::Descriptor;
use crate::net;
use crate::net::ConnectionState;
use crate::net::DeviceFirmware;
use crate::net::Event;
use crate::net::LogEntry;
use crate::net::Request;
use crate::theme;

mod log;

#[derive(Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub address: String,
    pub autoscroll: bool,
    pub min_level: u8,
    pub high_contrast_text: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            address: "192.168.19.58:2718".into(),
            autoscroll: true,
            min_level: 1,
            high_contrast_text: false,
        }
    }
}

pub struct App {
    settings: Settings,
    state: ConnectionState,
    state_since: Instant,
    firmware: Option<DeviceFirmware>,
    client_firmware: Option<Descriptor>,
    log: VecDeque<LogEntry>,
    filtered: Vec<usize>,
    requests: UnboundedSender<Request>,
    events: Receiver<Event>,
    last_ack: Option<u32>,
    last_error: Option<String>,
}

impl App {
    pub fn new(context: &CreationContext) -> App {
        let settings = context
            .storage
            .and_then(|s| eframe::get_value(s, eframe::APP_KEY))
            .unwrap_or_default();
        theme::apply(&context.egui_ctx, &settings);
        let (requests, events) = net::spawn(context.egui_ctx.clone());
        App {
            settings,
            state: Default::default(),
            state_since: Instant::now(),
            firmware: None,
            client_firmware: firmware::descriptor(),
            log: VecDeque::new(),
            filtered: Vec::new(),
            requests,
            events,
            last_ack: None,
            last_error: None,
        }
    }

    fn apply(&mut self, event: Event) {
        match event {
            Event::State(s) => {
                if self.state != s {
                    self.state_since = Instant::now();
                }
                self.state = s;
                if s == ConnectionState::Idle {
                    self.firmware = None;
                }
                if s == ConnectionState::Connected {
                    self.last_error = None;
                }
            }
            Event::Firmware(firmware) => {
                self.firmware = Some(firmware);
            }
            Event::Log(entry) => self.push(entry),
            Event::Gap { expected, got } => {
                let entry = LogEntry {
                    host_timestamp: Local::now().format("%H:%M:%S%.3f").to_string(),
                    device_timestamp: None,
                    level: Some(3),
                    location: None,
                    text: format!("{} frames dropped", got.wrapping_sub(expected)),
                    sequence: got,
                };
                self.push(entry);
            }
            Event::Ack(sequence) => self.last_ack = Some(sequence),
            Event::Error(msg) => self.last_error = Some(msg),
        }
    }

    fn push(&mut self, entry: LogEntry) {
        const LOG_CAP: usize = 10_000;
        let visible = self.visible(&entry);
        self.log.push_back(entry);
        if self.log.len() > LOG_CAP {
            self.log.pop_front();
            self.refilter();
        } else if visible {
            self.filtered.push(self.log.len() - 1);
        }
    }

    fn visible(&self, entry: &LogEntry) -> bool {
        entry.level.is_none_or(|l| l >= self.settings.min_level)
    }

    fn refilter(&mut self) {
        self.filtered = (0..self.log.len())
            .filter(|i| self.visible(&self.log[*i]))
            .collect();
    }

    fn request(&self, request: Request) {
        self.requests.send(request).expect(
            "net thread exited early; the only pre-Quit exit is Link::new failing at start",
        );
    }
}

impl eframe::App for App {
    fn logic(&mut self, _ctx: &egui::Context, _frame: &mut eframe::Frame) {
        while let Ok(event) = self.events.try_recv() {
            self.apply(event);
        }
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        Panel::top("status").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label("Device");
                ui.add(TextEdit::singleline(&mut self.settings.address).desired_width(160.0));
                let connected = self.state.is_connected();
                if ui.add_enabled(!connected, Button::new("Connect")).clicked() {
                    self.request(Request::Connect(self.settings.address.clone()));
                }
                if ui
                    .add_enabled(connected, Button::new("Disconnect"))
                    .clicked()
                {
                    self.request(Request::Disconnect);
                }
                if ui.add_enabled(connected, Button::new("Reset")).clicked() {
                    // TODO: Add confirmation dialog
                    self.request(Request::Reset);
                }
                ui.separator();
                match self.state {
                    ConnectionState::Resetting => {
                        ui.label(format!(
                            "{} ({} s)",
                            self.state.describe(),
                            self.state_since.elapsed().as_secs()
                        ));
                        ui.request_repaint_after(Duration::from_secs(1));
                    }
                    _ => {
                        ui.label(self.state.describe());
                    }
                }

                if let Some(firmware) = &self.firmware {
                    let DeviceFirmware {
                        descriptor: Descriptor { id, built },
                        matches,
                    } = firmware;

                    if *matches {
                        ui.colored_label(Color32::LIGHT_GREEN, format!("{} built {}", id, built));
                    } else {
                        let client = self.client_firmware.as_ref();
                        let newer = match client {
                            Some(c) if c.built > *built => "client is newer",
                            Some(_) => "device is newer",
                            None => "client has no descriptor",
                        };
                        ui.colored_label(
                            Color32::LIGHT_RED,
                            format!(
                                "MISMATCH: device {} built {}, client {} built {} ({newer})",
                                id,
                                built,
                                client.map_or("?", |c| c.id.as_str()),
                                client.map_or("?", |c| c.built.as_str()),
                            ),
                        );
                    }
                }
                if let Some(sequence) = self.last_ack {
                    ui.weak(format!("Ack {sequence}"));
                }
                if let Some(err) = &self.last_error {
                    match self.state {
                        ConnectionState::Connecting => {
                            ui.weak(format!("last attempt: {err}"));
                        }
                        ConnectionState::Resetting => {}
                        _ => {
                            ui.colored_label(Color32::LIGHT_RED, err);
                        }
                    }
                }
            });
        });

        Panel::bottom("filters").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.checkbox(&mut self.settings.autoscroll, "Autoscroll");
                ui.separator();
                let mut changed = false;
                for (level, name) in [
                    (0, "trace"),
                    (1, "debug"),
                    (2, "info"),
                    (3, "warn"),
                    (4, "error"),
                ] {
                    changed |= ui
                        .selectable_value(&mut self.settings.min_level, level, name)
                        .changed();
                }
                if changed {
                    self.refilter();
                }
                ui.separator();
                ui.label(format!("{} entries", self.log.len()));
                ui.separator();
                if ui.button("Clear").clicked() {
                    // TODO: Confirmation dialog
                    self.log.clear();
                    self.filtered.clear();
                }
            })
        });

        CentralPanel::default().show(ui, |ui| {
            let row_height = ui.text_style_height(&TextStyle::Monospace);
            let mut table = TableBuilder::new(ui)
                .id_salt("log")
                .striped(true)
                .resizable(true)
                .auto_shrink(false)
                .stick_to_bottom(self.settings.autoscroll);
            for column in LogColumn::ORDER {
                table = table.column(column.spec());
            }
            table
                .header(row_height + 4.0, |mut header| {
                    for column in LogColumn::ORDER {
                        header.col(|ui| {
                            ui.strong(column.title());
                        });
                    }
                })
                .body(|body| {
                    body.rows(row_height, self.filtered.len(), |mut row| {
                        let entry = &self.log[self.filtered[row.index()]];
                        for column in LogColumn::ORDER {
                            row.col(|ui| {
                                let mut text = RichText::new(column.text(entry)).monospace();
                                if let Some(color) = column.color(entry, ui.visuals()) {
                                    text = text.color(color);
                                }
                                let label = Label::new(text);
                                ui.add(if column.bounded() {
                                    label.extend()
                                } else {
                                    label.truncate()
                                });
                            });
                        }
                    });
                })
        });
    }

    fn save(&mut self, storage: &mut dyn Storage) {
        eframe::set_value(storage, APP_KEY, &self.settings);
    }

    fn on_exit(&mut self) {
        let _ = self.requests.send(Request::Quit);
    }
}
