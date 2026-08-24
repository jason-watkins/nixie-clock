use nixie_wire::MAX_LOG_FRAME_SIZE;

const CAPACITY: usize = 4 * 1024;

// Power of two guarantees wrapping arithmetic on indexes works as expected.
const _: () = assert!(CAPACITY.is_power_of_two());

const MAGIC: u32 = 0xAAFF0001;

const SKIP_SENTINEL: u16 = 0xFFFF;

pub enum PushError {
    TooBig,
    Full,
}

#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum InitResult {
    Reset,
    Adopted,
}

#[repr(C)]
pub struct RingBuffer {
    magic: u32,
    sequence: u32,
    dropped: u32,
    hold_index: usize,
    read_index: usize,
    write_index: usize,
    records: [u8; CAPACITY],
}

// safety: All fields are integers or byte arrays, so every bit pattern is a valid RingBuffer.
// init() decides whether the content is trustworthy.
unsafe impl esp_hal::Persistable for RingBuffer {}

impl RingBuffer {
    pub const fn new() -> RingBuffer {
        RingBuffer {
            magic: MAGIC,
            sequence: 0,
            dropped: 0,
            hold_index: 0,
            read_index: 0,
            write_index: 0,
            records: [0; CAPACITY],
        }
    }

    // Verifies the state of the buffer
    pub fn init(&mut self) -> InitResult {
        if self.magic != MAGIC {
            self.reset();
            return InitResult::Reset;
        }

        InitResult::Adopted
    }

    fn reset(&mut self) {
        self.magic = MAGIC;
        self.sequence = 0;
        self.dropped = 0;
        self.hold_index = 0;
        self.read_index = 0;
        self.write_index = 0;
        self.records[..].fill(0);
    }

    fn free_bytes(&self) -> usize {
        CAPACITY - (self.write_index - self.hold_index)
    }

    fn hold_ptr(&self) -> usize {
        self.hold_index & (CAPACITY - 1)
    }

    fn read_ptr(&self) -> usize {
        self.read_index & (CAPACITY - 1)
    }

    fn write_ptr(&self) -> usize {
        self.write_index & (CAPACITY - 1)
    }

    fn write_u16(&mut self, value: u16) {
        self.write_slice(&u16::to_le_bytes(value));
    }

    fn write_u32(&mut self, value: u32) {
        self.write_slice(&u32::to_le_bytes(value));
    }

    fn write_slice(&mut self, data: &[u8]) {
        let ptr = self.write_ptr();
        self.records[ptr..(ptr + data.len())].copy_from_slice(data);
        self.write_index = self.write_index.wrapping_add(data.len());
    }

    /// Pushes a frame to the buffer. If there is not enough room, the push fails rather than
    /// evicting old data. Individual frames never wrap in the ring buffer, so there must be either
    /// enough space at the current position or enough space at the beginning of the buffer or the
    /// push will fail.
    pub fn push(&mut self, data: &[u8]) -> Result<(), PushError> {
        if data.len() > MAX_LOG_FRAME_SIZE as usize {
            self.dropped = self.dropped.wrapping_add(1);
            return Err(PushError::TooBig);
        }

        let frame_size = 6 + data.len();
        let remaining = CAPACITY - self.write_ptr();
        if remaining < 2 {
            // No room for sentinel, skip to front of the buffer.
            self.write_index = self.write_index.wrapping_add(remaining);
        } else if remaining < frame_size {
            // Not enough room for the frame at the end of the buffer, but we can write the
            // sentinel. Check first whether the frame will fit at the front of the buffer.
            if self.free_bytes() < remaining + frame_size {
                self.dropped = self.dropped.wrapping_add(1);
                return Err(PushError::Full);
            }

            self.write_u16(SKIP_SENTINEL);
            self.write_index = self.write_index.wrapping_add(remaining - 2);
        }

        if self.free_bytes() < frame_size {
            // Writing this frame would overwrite pending reads.
            self.dropped = self.dropped.wrapping_add(1);
            return Err(PushError::Full);
        }

        self.write_u16(data.len() as u16);
        self.write_u32(self.sequence);
        self.sequence = self.sequence.wrapping_add(1);
        self.write_slice(data);
        Ok(())
    }

    fn read_u16(&mut self) -> u16 {
        u16::from_le_bytes(self.read_slice(2).try_into().unwrap())
    }

    fn read_u32(&mut self) -> u32 {
        u32::from_le_bytes(self.read_slice(4).try_into().unwrap())
    }

    fn read_slice(&mut self, len: usize) -> &[u8] {
        let ptr = self.read_ptr();
        let value = &self.records[ptr..(ptr + len)];
        self.read_index = self.read_index.wrapping_add(len);
        value
    }

    /// Gets the sequence and content of the next frame in the buffer, or None if the buffer is
    /// empty.
    pub fn pop(&mut self) -> Option<(u32, &[u8])> {
        if self.read_index == self.write_index {
            // Empty queue
            return None;
        }

        let remaining = CAPACITY - self.read_ptr();
        if remaining < 2 {
            self.read_index = self.read_index.wrapping_add(remaining);
            // Repeat empty check. This should actually happen in practice
            if self.read_index == self.write_index {
                return None;
            }
        }

        self.hold_index = self.read_index;
        let mut len = self.read_u16();
        if len == 0 {
            self.read_index = self.read_index.wrapping_sub(2);
            return None;
        }
        if len == SKIP_SENTINEL && self.read_ptr() != 0 {
            self.read_index = self.read_index.wrapping_add(CAPACITY - self.read_ptr());
            len = self.read_u16();
        }

        let sequence = self.read_u32();
        let data = self.read_slice(len as usize);
        Some((sequence, data))
    }
}
