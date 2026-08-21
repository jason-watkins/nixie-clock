use esp_hal::ledc::LowSpeed;
use esp_hal::ledc::channel::Channel;
use esp_hal::ledc::channel::ChannelHW;

#[derive(Default)]
pub struct StatusLed {
    channel: Option<Channel<'static, LowSpeed>>,
}

impl StatusLed {
    pub fn new(channel: Channel<'static, LowSpeed>) -> StatusLed {
        StatusLed {
            channel: Some(channel),
        }
    }

    /// Set the LED level as a percentage
    pub fn set(&self, level: u8) {
        let Some(channel) = self.channel.as_ref() else {
            return;
        };

        channel.set_duty_hw(GAMMA[level.min(100) as usize] as u32);
    }
}

const fn duty_for_level(level: u8) -> u16 {
    let ls = 100 * level as u64;
    let duty = if ls > 800 {
        4095 * (ls + 1600).pow(3) / 11_600u64.pow(3)
    } else {
        4095 * ls / 90_330
    };
    duty as u16
}

const GAMMA: [u16; 101] = {
    let mut table = [0u16; 101];
    let mut level = 0;
    while level < 101 {
        table[level] = duty_for_level(level as u8);
        level += 1;
    }
    table
};
