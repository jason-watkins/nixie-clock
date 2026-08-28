use embassy_net::Stack;
use embassy_net::tcp::TcpSocket;
use embassy_time::Duration;
use embassy_time::with_timeout;
use embedded_io_async::Read;
use embedded_io_async::Write;
use nixie_wire::FRAME_HEADER_SIZE;
use nixie_wire::MAX_MESSAGE_SIZE;
use nixie_wire::TCTM_PORT;
use nixie_wire::ToDevice;
use nixie_wire::ToHost;

#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Error {
    /// The peer closed, reset, or vanished mid-message.
    Disconnected,
    /// The peer sent bytes that violate the wire contract.
    Protocol,
    /// An outgoing message exceeded MAX_MESSAGE_SIZE.
    TooLarge,
    /// An incoming packet did not have a valid length
    InvalidHeaderLen,
}

impl From<embedded_io::ReadExactError<embassy_net::tcp::Error>> for Error {
    fn from(value: embedded_io::ReadExactError<embassy_net::tcp::Error>) -> Self {
        use embedded_io::ReadExactError;
        match value {
            ReadExactError::UnexpectedEof => Error::Disconnected,
            ReadExactError::Other(e) => Error::from(e),
        }
    }
}

impl From<embassy_net::tcp::Error> for Error {
    fn from(value: embassy_net::tcp::Error) -> Self {
        match value {
            embassy_net::tcp::Error::ConnectionReset => Error::Disconnected,
        }
    }
}

impl From<embassy_net::tcp::AcceptError> for Error {
    fn from(value: embassy_net::tcp::AcceptError) -> Self {
        use embassy_net::tcp::AcceptError;
        match value {
            AcceptError::InvalidState => Error::Disconnected,
            AcceptError::InvalidPort => unreachable!("Port is a nonzero constant"),
            AcceptError::ConnectionReset => Error::Disconnected,
        }
    }
}

pub struct Connection<'a> {
    socket: TcpSocket<'a>,
}

impl<'a> Connection<'a> {
    pub fn new(
        stack: Stack<'static>,
        rx_buffer: &'a mut [u8],
        tx_buffer: &'a mut [u8],
    ) -> Connection<'a> {
        let mut socket = TcpSocket::new(stack, rx_buffer, tx_buffer);
        socket.set_timeout(Some(Duration::from_secs(10)));
        socket.set_keep_alive(Some(Duration::from_secs(3)));
        Connection { socket }
    }

    pub async fn open(&mut self) -> Result<(), Error> {
        Ok(self.socket.accept(TCTM_PORT).await?)
    }

    pub async fn close(&mut self) {
        self.socket.close();
        let _ = with_timeout(Duration::from_secs(1), self.socket.flush()).await;
    }

    pub async fn wait_read_ready(&mut self) -> Result<(), Error> {
        Ok(self.socket.read_with(|_| (0, ())).await?)
    }

    pub async fn reset(&mut self) {
        self.socket.abort();
        // Already closing connection, ignore any errors
        let _ = with_timeout(Duration::from_secs(1), self.socket.flush()).await;
    }

    pub async fn read(&mut self) -> Result<ToDevice, Error> {
        // TODO: Use read_with to do fewer copies

        let mut len_buffer = [0u8; FRAME_HEADER_SIZE];
        self.socket.read_exact(&mut len_buffer).await?;
        let Some(len) = nixie_wire::payload_len(len_buffer) else {
            return Err(Error::InvalidHeaderLen);
        };
        if len == 0 || len > MAX_MESSAGE_SIZE {
            return Err(Error::Protocol);
        }
        let mut msg_buffer = [0u8; MAX_MESSAGE_SIZE];
        self.socket.read_exact(&mut msg_buffer[..len]).await?;
        postcard::from_bytes(&msg_buffer[..len]).map_err(|_| Error::Protocol)
    }

    pub async fn write(&mut self, msg: &ToHost<'_>) -> Result<(), Error> {
        let sent = self
            .write_framed(|buffer| nixie_wire::encode(msg, buffer).map(|s| s.len()).ok())
            .await?;
        if sent { Ok(()) } else { Err(Error::TooLarge) }
    }

    pub async fn write_framed(
        &mut self,
        fill: impl FnOnce(&mut [u8]) -> Option<usize>,
    ) -> Result<bool, Error> {
        let mut fill = Some(fill);

        let attempted = self
            .socket
            .write_with(|buffer| {
                if buffer.len() < 2 + MAX_MESSAGE_SIZE {
                    return (0, None);
                }

                // TODO: Re-write to use nixie_wire::encode
                // safety: All branches below this take must return Some to indicate that fill has
                // been taken.
                let fill = fill.take().unwrap();
                match fill(&mut buffer[2..2 + MAX_MESSAGE_SIZE]) {
                    Some(len) => {
                        buffer[..2].copy_from_slice(&(len as u16).to_le_bytes());
                        (2 + len, Some(true))
                    }
                    None => (0, Some(false)),
                }
            })
            .await?;

        match attempted {
            Some(sent) => Ok(sent),
            None => {
                // Socket ring buffer may have a small contiguous region at the end, causing the above
                // write to fail even when there is plenty of total space in the buffer. Fall back to
                // write_all in that case.

                // safety: Can take here because only branches that do not call fill inside
                // write_with return None.
                let fill = fill.take().unwrap();
                let mut buffer = [0u8; 2 + MAX_MESSAGE_SIZE];
                if let Some(len) = fill(&mut buffer[2..2 + MAX_MESSAGE_SIZE]) {
                    buffer[..2].copy_from_slice(&(len as u16).to_le_bytes());
                    self.socket.write_all(&buffer[..(2 + len)]).await?;
                    Ok(true)
                } else {
                    Ok(false)
                }
            }
        }
    }
}
