use core::sync::atomic::AtomicBool;
use core::sync::atomic::AtomicU32;
use core::sync::atomic::Ordering;

use critical_section::RestoreState;
use defmt::Encoder;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::signal::Signal;
use nixie_wire::MAX_LOG_FRAME_SIZE;

use crate::tctm::log::ring_buffer::RingBuffer;

static TAKEN: AtomicBool = AtomicBool::new(false);
static mut RESTORE_STATE: RestoreState = RestoreState::invalid();
static mut ENCODER: Encoder = Encoder::new();

static mut STAGING: [u8; MAX_LOG_FRAME_SIZE as usize] = [0; MAX_LOG_FRAME_SIZE as usize];
static mut STAGED: usize = 0;
static mut OVERFLOWED: bool = false;

static DROPPED: AtomicU32 = AtomicU32::new(0);

#[esp_hal::ram(unstable(rtc_fast, persistent))]
pub static mut LOG_QUEUE: RingBuffer = RingBuffer::new();

static LOG_SIGNAL: Signal<CriticalSectionRawMutex, ()> = Signal::new();

#[defmt::global_logger]
pub struct Logger;

unsafe impl defmt::Logger for Logger {
    fn acquire() {
        // safety: At this point we are only taking the critical section. Need to prove
        // non-reentrance before storing it in RESTORE_STATE.
        let restore = unsafe { critical_section::acquire() };

        if TAKEN.swap(true, Ordering::Acquire) {
            panic!("Reentering logger critical section");
        }

        // safety: Safe to store in RESTORE_STATE now because we are in the critical section and did
        // not re-enter.
        unsafe { RESTORE_STATE = restore };

        // safety: Safe to deref encoder and staging since we are in the critical section
        unsafe {
            *(&raw mut STAGED) = 0;
            *(&raw mut OVERFLOWED) = false;

            let encoder = (&raw mut ENCODER).as_mut_unchecked();
            encoder.start_frame(encoder_write)
        };
    }

    unsafe fn flush() {
        // NO-OP. No useful way to measure host read at this time.
    }

    unsafe fn release() {
        // safety: Safe to deref encoder, queue, and related since we are in the critical section
        unsafe {
            let encoder = (&raw mut ENCODER).as_mut_unchecked();
            encoder.end_frame(encoder_write);

            if OVERFLOWED {
                DROPPED.fetch_add(1, Ordering::Relaxed);
            } else {
                let queue = (&raw mut LOG_QUEUE).as_mut_unchecked();
                // Logging is best effort. We can't do anything useful with an error
                let _ = queue.push(&STAGING[..STAGED]);
            }
        };

        TAKEN.store(false, Ordering::Release);

        // safety: Safe to read RESTORE_STATE because we are in the critical section. Safe to
        // release because we guarantee non-reentrance and trait contract guarantees exactly one
        // release per acquire.
        unsafe { critical_section::release(RESTORE_STATE) };

        LOG_SIGNAL.signal(());
    }

    unsafe fn write(bytes: &[u8]) {
        unsafe {
            let encoder = (&raw mut ENCODER).as_mut_unchecked();
            encoder.write(bytes, encoder_write);
        };
    }
}

fn encoder_write(bytes: &[u8]) {
    // safety: encoder_write is only called while the logger critical section is held.
    unsafe {
        let staging = (&raw mut STAGING).as_mut_unchecked();
        let staged = (&raw mut STAGED).as_mut_unchecked();
        if *staged + bytes.len() > staging.len() {
            *(&raw mut OVERFLOWED) = true;
            return;
        }
        staging[*staged..(*staged + bytes.len())].copy_from_slice(bytes);
        *staged += bytes.len();
    }
}
