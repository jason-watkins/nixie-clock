use core::cell::RefCell;
use core::sync::atomic::Ordering;

use critical_section::Mutex;
use defmt::info;
use esp_hal::debugger::debugger_connected;
use nixie_wire::MAX_LOG_FRAME_SIZE;
use rtt_target::ChannelMode;
use rtt_target::UpChannel;

mod logger;
mod ring_buffer;

static RTT: Mutex<RefCell<Option<UpChannel>>> = Mutex::new(RefCell::new(None));

pub struct Drops {
    frame_overflows: u32,
    buffer_full: u32,
}

pub fn init() {
    let channels = rtt_target::rtt_init! {
        up: {
            0: {
                size: ring_buffer::CAPACITY + MAX_LOG_FRAME_SIZE as usize,
                mode: rtt_target::ChannelMode::NoBlockSkip,
                name: "defmt"
            }
        }
    };
    critical_section::with(|cs| {
        RTT.replace(cs, Some(channels.up.0));
    });

    let result = critical_section::with(|_| {
        // safety: Called early in the boot process, no logger call can be in flight
        unsafe { (&raw mut logger::LOG_QUEUE).as_mut_unchecked().init() }
    });
    info!("Logger initialized with state {}", result);
}

/// Pops the next log frame if one is present, writes the frame to the RTT channel, then calls the
/// provided handler with the frame data.
///
/// Returns `None` when the queue is empty. `handler` runs inside a critical section.
///
/// # Safety
///
/// `handler` must not call any `defmt` logging macro. The frame passed to it borrows the internal
/// log queue for the duration of the call, and a log call would create a second mutable reference
/// to the queue.
pub unsafe fn handle_frame<R>(handler: impl FnOnce(u32, &[u8]) -> R) -> Option<R> {
    critical_section::with(|cs| {
        // safety: Safe to create mutable log queue inside critical section. Handler consumes
        // borrowed slice inside critical section.
        let (sequence, frame) = unsafe { (&raw mut logger::LOG_QUEUE).as_mut_unchecked().pop() }?;
        if debugger_connected()
            && let Some(rtt) = RTT.borrow_ref_mut(cs).as_mut()
        {
            rtt.write(frame);
        }
        Some(handler(sequence, frame))
    })
}

/// Wait for log frames to be available. Behaves exactly as embassy_sync::signal::Signal.wait()
pub async fn wait_for_frames() {
    logger::LOG_SIGNAL.wait().await;
}

/// Write all pending log frames to the RTT channel
pub fn drain_to_rtt() {
    // safety: handler is a no-op, trivially complies with the do-not-log requirement
    while unsafe { handle_frame(|_, _| ()).is_some() } {}
}

pub fn panic_flush() {
    if !debugger_connected() {
        return;
    }

    critical_section::with(|cs| {
        if let Some(rtt) = RTT.borrow_ref_mut(cs).as_mut() {
            rtt.set_mode(ChannelMode::BlockIfFull);
        }
    });
    drain_to_rtt();
}

pub fn drop_stats() -> Drops {
    let frame_overflows = logger::DROPPED.load(Ordering::Relaxed);
    let buffer_full = critical_section::with(|_| {
        // safety: Safe to borrow log queue in critical section
        unsafe { (&raw mut logger::LOG_QUEUE).as_ref_unchecked().dropped() }
    });

    Drops {
        frame_overflows,
        buffer_full,
    }
}
