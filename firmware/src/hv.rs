use defmt::error;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_futures::select::Either;
use embassy_futures::select::select;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::DynReceiver;
use embassy_sync::watch::Watch;
use embassy_time::Duration;
use embassy_time::Instant;
use embassy_time::TimeoutError;
use embassy_time::with_timeout;
use esp_hal::gpio::Input;
use esp_hal::gpio::InputConfig;
use esp_hal::gpio::InputPin;
use esp_hal::gpio::Level;
use esp_hal::gpio::Output;
use esp_hal::gpio::OutputConfig;
use esp_hal::gpio::OutputPin;

use crate::pd;
use crate::pd::HvPermission;
use crate::status;
use crate::status::HvStatus;
use crate::time;

static HV_STATUS: Watch<CriticalSectionRawMutex, HvStatus, 1> = Watch::new();

/// Get a receiver for the HV permission state. Panics on failure.
pub fn status_receiver() -> DynReceiver<'static, HvStatus> {
    HV_STATUS.dyn_receiver().unwrap()
}

struct HvManager {
    en: Output<'static>,
    pgood: Input<'static>,
    receiver: DynReceiver<'static, HvPermission>,
}

impl HvManager {
    pub fn new(
        en: Output<'static>,
        pgood: Input<'static>,
        receiver: DynReceiver<'static, HvPermission>,
    ) -> HvManager {
        HvManager {
            en,
            pgood,
            receiver,
        }
    }

    pub async fn run(mut self) -> ! {
        let mut state = HvStatus::Off;
        loop {
            status::report(state);
            HV_STATUS.sender().send_if_modified(|v| {
                if *v == Some(state) {
                    false
                } else {
                    *v = Some(state);
                    true
                }
            });
            state = match state {
                HvStatus::Off => self.off().await,
                HvStatus::Starting => self.starting().await,
                HvStatus::Up => self.up().await,
                HvStatus::Failed => self.failed().await,
            };
        }
    }

    async fn off(&mut self) -> HvStatus {
        self.en.set_low();
        time::wait_for_ntp().await;

        if let HvPermission::Granted = self.receiver.get().await {
            HvStatus::Starting
        } else {
            match self.receiver.changed().await {
                HvPermission::Denied => HvStatus::Off,
                HvPermission::Granted => HvStatus::Starting,
            }
        }
    }

    async fn starting(&mut self) -> HvStatus {
        info!("Enabling HV rail");
        const MAX_ATTEMPTS: u32 = 5;
        for attempt in 1..=MAX_ATTEMPTS {
            let start = Instant::now();
            self.en.set_high();
            const HV_STARTUP_MAX: Duration = Duration::from_millis(500);
            match with_timeout(
                HV_STARTUP_MAX,
                select(
                    self.pgood.wait_for_high(),
                    self.receiver.changed_and(|p| *p == HvPermission::Denied),
                ),
            )
            .await
            {
                Ok(Either::First(())) => {
                    info!("HV rail up in {}ms", start.elapsed().as_millis());
                    return HvStatus::Up;
                }
                Ok(Either::Second(_)) => {
                    warn!("HV startup cancelled, permission revoked");
                    return HvStatus::Off;
                }
                Err(TimeoutError) => {
                    self.en.set_low();
                    if attempt == MAX_ATTEMPTS {
                        break;
                    }

                    const HV_RETRY_BASE: Duration = Duration::from_millis(500);
                    let retry_duration = HV_RETRY_BASE * attempt;
                    warn!(
                        "HV Failed to come up within {}ms. Retrying in {}ms",
                        HV_STARTUP_MAX.as_millis(),
                        retry_duration.as_millis()
                    );
                    match with_timeout(
                        retry_duration,
                        self.receiver.changed_and(|p| *p == HvPermission::Denied),
                    )
                    .await
                    {
                        Ok(_) => {
                            warn!("HV startup cancelled, permission revoked");
                            return HvStatus::Off;
                        }
                        Err(TimeoutError) => {
                            continue;
                        }
                    }
                }
            }
        }

        error!("HV rail startup failed");
        HvStatus::Failed
    }

    async fn up(&mut self) -> HvStatus {
        match select(self.receiver.changed(), self.pgood.wait_for_low()).await {
            Either::First(new_permission) => match new_permission {
                HvPermission::Denied => {
                    warn!("HV disabled, permission revoked");
                    HvStatus::Off
                }
                HvPermission::Granted => HvStatus::Up,
            },
            Either::Second(()) => {
                const PGOOD_MAX_GLITCH: Duration = Duration::from_millis(2);
                if let Ok(_) = with_timeout(
                    PGOOD_MAX_GLITCH,
                    self.receiver.changed_and(|p| *p == HvPermission::Denied),
                )
                .await
                {
                    warn!("HV startup cancelled, permission revoked during glitch");
                    return HvStatus::Off;
                }
                if self.pgood.is_high() {
                    // Glitch. Stay up
                    warn!("HV PGOOD glitch");
                    HvStatus::Up
                } else {
                    error!("PGOOD asserted low for too long");
                    HvStatus::Failed
                }
            }
        }
    }

    async fn failed(&mut self) -> ! {
        self.en.set_low();
        error!("HV rail failed. Power cycle to reset");
        core::future::pending::<()>().await;
        unreachable!("core::future::pending never completes");
    }
}

pub fn init(en: impl OutputPin + 'static, pgood: impl InputPin + 'static, spawner: &Spawner) {
    let en = Output::new(en, Level::Low, OutputConfig::default());
    let pgood = Input::new(pgood, InputConfig::default());
    let receiver = pd::permission_receiver();
    let manager = HvManager::new(en, pgood, receiver);

    let hv_token = hv_task(manager).expect("Failed to create hv task");

    status::report(HvStatus::Off);

    spawner.spawn(hv_token);
}

#[embassy_executor::task]
async fn hv_task(manager: HvManager) {
    manager.run().await;
}
