use alloc::string::String;
use alloc::string::ToString;
use defmt::error;
use defmt::info;
use defmt::warn;
use embassy_executor::Spawner;
use embassy_net::Runner;
use embassy_net::Stack;
use embassy_net::StackResources;
use embassy_time::Duration;
use embassy_time::Timer;
use esp_hal::peripherals::WIFI;
use esp_radio::wifi::Interface;
use esp_radio::wifi::WifiController;
use esp_radio::wifi::sta::StationConfig;
use static_cell::StaticCell;

mod credentials;

struct WifiManager {
    controller: WifiController<'static>,
    last_good: Option<usize>,
    backoff: Duration,
}

impl WifiManager {
    pub fn new(controller: WifiController<'static>) -> Self {
        Self {
            controller,
            last_good: None,
            backoff: Self::default_backoff(),
        }
    }

    fn default_backoff() -> Duration {
        Duration::from_secs(10)
    }

    fn max_backoff() -> Duration {
        Duration::from_secs(600)
    }

    pub async fn run(mut self) -> ! {
        loop {
            if !self.controller.is_connected()
                && let Some(last_good) = self.last_good
            {
                let (ssid, password) = credentials::WIFI_CREDENTIALS[last_good];
                if !self.try_one(ssid, password.to_string(), true).await {
                    warn!("Last good Wi-Fi credentials failed, trying all credentials...");
                    self.last_good = None;
                }
            } else if !self.controller.is_connected() {
                self.last_good = self.connect_any().await;

                // Still not connected, wait a bit before trying again. If it doesn't work the first
                // time, it probably won't work the second time either, so increment backoff each
                // time we fail.
                if !self.controller.is_connected() {
                    warn!(
                        "No Wi-Fi credentials worked, retrying in {} seconds...",
                        self.backoff.as_secs()
                    );
                    Timer::after(self.backoff).await;
                    self.backoff = (self.backoff * 3) / 2;
                    if self.backoff > Self::max_backoff() {
                        self.backoff = Self::max_backoff();
                    }
                }
            } else {
                let result = self.controller.wait_for_disconnect_async().await;
                match result {
                    Ok(_) => info!("Wi-Fi disconnected, retrying..."),
                    Err(e) => error!("Wi-Fi error: {:?}, retrying...", e),
                }
            }
        }
    }

    async fn connect_any(&mut self) -> Option<usize> {
        for (i, &(ssid, password)) in credentials::WIFI_CREDENTIALS.iter().enumerate() {
            if self.try_one(ssid, password.to_string(), false).await {
                return Some(i);
            } else {
                Timer::after(Duration::from_secs(2)).await;
            }
        }
        None
    }

    async fn try_one(&mut self, ssid: &str, password: String, reconnect: bool) -> bool {
        use esp_radio::wifi::Config;

        let config = StationConfig::default()
            .with_ssid(ssid)
            .with_password(password);
        let config = Config::Station(config);
        if self.controller.set_config(&config).is_err() {
            return false;
        }
        let connected = self.controller.connect_async().await.is_ok();
        if connected {
            self.backoff = Self::default_backoff();
            if reconnect {
                info!("Reconnected to {}", ssid);
            } else {
                info!("Connected to {}", ssid);
            }
        }
        connected
    }
}

pub fn init(wifi: WIFI<'static>, seed: u64, spawner: &Spawner) -> Stack<'static> {
    use embassy_net::Config;

    let (wifi_controller, interfaces) = esp_radio::wifi::new(wifi, Default::default())
        .expect("Failed to initialize Wi-Fi controller");

    static RESOURCES: StaticCell<StackResources<3>> = StaticCell::new();
    let resources = RESOURCES.init(StackResources::new());

    let (stack, runner) = embassy_net::new(
        interfaces.station,
        Config::dhcpv4(Default::default()),
        resources,
        seed,
    );

    let net_token = net_task(runner).expect("Failed to spawn net_task");
    let wifi_token = wifi_task(wifi_controller).expect("Failed to spawn wifi_task");

    spawner.spawn(net_token);
    spawner.spawn(wifi_token);

    stack
}

#[embassy_executor::task]
async fn net_task(mut runner: Runner<'static, Interface<'static>>) -> ! {
    runner.run().await
}

#[embassy_executor::task]
async fn wifi_task(controller: WifiController<'static>) -> ! {
    WifiManager::new(controller).run().await
}
