use egui::Context;
use std::sync::mpsc::Receiver;
use std::time::Duration;
use tokio::sync::mpsc::UnboundedReceiver;
use tokio::sync::mpsc::UnboundedSender;
use tokio::time::Instant;

use crate::net::session::Session;
use crate::net::session::SessionEnd;

use super::ConnectionState;
use super::Event;
use super::Link;
use super::Request;

const RECONNECT_MIN: Duration = Duration::from_secs(1);
const RECONNECT_MAX: Duration = Duration::from_secs(10);
const REBOOT_DELAY: Duration = Duration::from_secs(3);
const REBOOT_RETRY: Duration = Duration::from_secs(1);
const REBOOT_GRACE: Duration = Duration::from_secs(20);

pub struct Supervisor {
    requests: UnboundedReceiver<Request>,
    link: Link,
    target: Option<String>,
    backoff: Duration,
    resetting_since: Option<Instant>,
}

impl Supervisor {
    pub fn new(requests: UnboundedReceiver<Request>, link: Link) -> Supervisor {
        Supervisor {
            requests,
            link,
            target: None,
            backoff: RECONNECT_MIN,
            resetting_since: None,
        }
    }

    pub async fn run(mut self) {
        loop {
            let Some(address) = self.target.clone() else {
                match self.requests.recv().await {
                    Some(Request::Connect(a)) => self.target = Some(a),
                    Some(Request::Quit) | None => return,
                    _ => {}
                }
                continue;
            };

            self.link.emit(Event::State(self.retry_state()));
            let end = match Session::connect(&address, &self.link).await {
                Ok(mut session) => {
                    self.resetting_since = None;
                    self.backoff = RECONNECT_MIN;
                    self.link.emit(Event::State(ConnectionState::Connected));
                    session.run(&mut self.requests, &mut self.link).await
                }
                Err(e) => SessionEnd::Failed(e),
            };

            match end {
                SessionEnd::Quit => return,
                SessionEnd::Disconnect => {
                    self.target = None;
                    self.resetting_since = None;
                    self.backoff = RECONNECT_MIN;
                    self.link.emit(Event::State(ConnectionState::Idle));
                    continue;
                }
                SessionEnd::Reset => {
                    self.resetting_since = Some(Instant::now());
                }
                SessionEnd::Failed(msg) => {
                    if !self.in_reset_grace() {
                        let msg = if self.resetting_since.take().is_some() {
                            format!(
                                "Device did not come back within {}s: {msg}",
                                REBOOT_GRACE.as_secs()
                            )
                        } else {
                            msg
                        };
                        self.link.emit(Event::Error(msg));
                        self.link.emit(Event::State(ConnectionState::Connecting));
                    }
                    // While resetting, we expect timeouts and retries until the clock comes up.
                    // Only emit error messages when that's not happening.
                }
            }

            let delay = if self.in_reset_grace() {
                REBOOT_RETRY
            } else {
                self.backoff
            };
            tokio::select! {
                _ = tokio::time::sleep(delay) => {},
                req = self.requests.recv() => match req {
                    Some(Request::Connect(a)) => {
                        self.target = Some(a);
                        self.resetting_since = None;
                        self.backoff = RECONNECT_MIN;
                    }
                    Some(Request::Disconnect) => {
                        self.target = None;
                        self.resetting_since = None;
                        self.backoff = RECONNECT_MIN;
                        self.link.emit(Event::State(ConnectionState::Idle));
                    }
                    Some(Request::Quit) | None => return,
                    Some(Request::Reset) => {}
                }
            }
            if !self.in_reset_grace() {
                self.backoff = (self.backoff * 2).min(RECONNECT_MAX);
            }
        }
    }

    fn in_reset_grace(&self) -> bool {
        self.resetting_since
            .is_some_and(|since| since.elapsed() < REBOOT_GRACE)
    }

    fn retry_state(&self) -> ConnectionState {
        if self.in_reset_grace() {
            ConnectionState::Resetting
        } else {
            ConnectionState::Connecting
        }
    }
}

pub fn spawn(context: Context) -> (UnboundedSender<Request>, Receiver<Event>) {
    let (req_tx, req_rx) = tokio::sync::mpsc::unbounded_channel();
    let (ev_tx, ev_rx) = std::sync::mpsc::channel();
    std::thread::Builder::new()
        .name("net".into())
        .spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("tokio runtime");
            let link = match Link::new(ev_tx.clone(), context.clone()) {
                Ok(link) => link,
                Err(e) => {
                    let _ = ev_tx.send(Event::Error(e));
                    context.request_repaint();
                    return;
                }
            };
            rt.block_on(Supervisor::new(req_rx, link).run())
        })
        .expect("spawn net thread");
    (req_tx, ev_rx)
}
