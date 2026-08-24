use defmt::error;
use embassy_executor::Spawner;

mod log;

pub fn init_logging() {
    log::init();
}

pub fn init(spawner: &Spawner) {
    // Logging should be initialized much earlier, but its init is idempotent, so make sure it's
    // initialized now.
    init_logging();

    let Ok(tctm_token) = tctm() else {
        error!("Failed to create tctm task, network client will be unavailable");
        return;
    };

    spawner.spawn(tctm_token);
}

#[embassy_executor::task]
async fn tctm() -> ! {
    loop {
        core::future::pending::<()>().await;
    }
}
