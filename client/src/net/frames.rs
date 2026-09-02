use nixie_wire::FRAME_HEADER_SIZE;
use nixie_wire::MAX_MESSAGE_SIZE;
use nixie_wire::ToDevice;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

#[derive(Debug)]
pub struct LogEntry {
    pub host_timestamp: String,
    pub device_timestamp: Option<String>,
    pub level: Option<u8>,
    pub location: Option<(String, u64)>,
    pub text: String,
    pub sequence: u32,
}

const FRAME_SIZE: usize = FRAME_HEADER_SIZE + MAX_MESSAGE_SIZE;

pub(super) async fn read_frame<R: AsyncReadExt + Unpin>(
    reader: &mut R,
    buffer: &mut [u8],
) -> Result<usize, String> {
    let mut header = [0u8; FRAME_HEADER_SIZE];
    reader
        .read_exact(&mut header)
        .await
        .map_err(|e| e.to_string())?;
    let len = nixie_wire::payload_len(header).ok_or("Bad frame length")?;
    reader
        .read_exact(&mut buffer[..len])
        .await
        .map_err(|e| e.to_string())?;
    Ok(len)
}

pub(super) async fn send<W: AsyncWriteExt + Unpin>(
    writer: &mut W,
    msg: &ToDevice,
) -> Result<(), String> {
    let mut buffer = [0u8; FRAME_SIZE];
    let frame = nixie_wire::encode(msg, &mut buffer).map_err(|e| e.to_string())?;
    writer.write_all(frame).await.map_err(|e| e.to_string())
}
