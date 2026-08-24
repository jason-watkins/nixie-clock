use defmt::info;

mod logger;
mod ring_buffer;

pub fn init() {
    let result = critical_section::with(|_| {
        // safety: Called early in the boot process, no logger call can be in flight
        unsafe { (&raw mut logger::LOG_QUEUE).as_mut_unchecked().init() }
    });
    info!("Logger initialized with state {}", result);
}
