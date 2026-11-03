//! Minimal Server-Sent Events decoder for streaming provider responses.

use super::{ProviderError, ProviderErrorKind};
use futures_util::StreamExt;

#[derive(Debug, Clone, PartialEq)]
pub struct SseEvent {
    pub event: Option<String>,
    pub data: String,
}

/// Incremental parser: feed bytes, get complete events.
#[derive(Default)]
pub struct SseParser {
    buf: String,
    pending: Vec<u8>,
}

impl SseParser {
    pub fn push(&mut self, chunk: &[u8]) -> Vec<SseEvent> {
        // Bytes may split a UTF-8 sequence; keep the incomplete tail for the next chunk.
        self.pending.extend_from_slice(chunk);
        let valid_up_to = match std::str::from_utf8(&self.pending) {
            Ok(_) => self.pending.len(),
            Err(e) => e.valid_up_to(),
        };
        let text = String::from_utf8_lossy(&self.pending[..valid_up_to]).into_owned();
        self.pending.drain(..valid_up_to);
        self.buf.push_str(&text.replace("\r\n", "\n"));

        let mut out = Vec::new();
        while let Some(idx) = self.buf.find("\n\n") {
            let block: String = self.buf.drain(..idx + 2).collect();
            if let Some(ev) = parse_block(&block) {
                out.push(ev);
            }
        }
        out
    }
}

fn parse_block(block: &str) -> Option<SseEvent> {
    let mut event = None;
    let mut data: Vec<&str> = Vec::new();
    for line in block.lines() {
        if line.starts_with(':') {
            continue;
        }
        let (field, value) = match line.split_once(':') {
            Some((f, v)) => (f, v.strip_prefix(' ').unwrap_or(v)),
            None => (line, ""),
        };
        match field {
            "event" => event = Some(value.to_string()),
            "data" => data.push(value),
            _ => {}
        }
    }
    if data.is_empty() && event.is_none() {
        return None;
    }
    Some(SseEvent { event, data: data.join("\n") })
}

/// Drive a response body through the parser, calling `on_event` for each event. Stops when the
/// body ends, `on_event` returns `false`, or `cancel` fires.
pub async fn for_each_event(
    resp: reqwest::Response,
    cancel: &tokio_util::sync::CancellationToken,
    idle_timeout: std::time::Duration,
    mut on_event: impl FnMut(SseEvent) -> Result<bool, ProviderError>,
) -> Result<(), ProviderError> {
    let mut stream = resp.bytes_stream();
    let mut parser = SseParser::default();
    loop {
        let next = tokio::select! {
            _ = cancel.cancelled() => return Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled")),
            r = tokio::time::timeout(idle_timeout, stream.next()) => r,
        };
        let chunk = match next {
            Err(_) => return Err(ProviderError::new(ProviderErrorKind::Timeout, "the provider stopped sending data")),
            Ok(None) => return Ok(()),
            Ok(Some(Err(e))) => return Err(ProviderError::from_reqwest(&e)),
            Ok(Some(Ok(b))) => b,
        };
        for ev in parser.push(&chunk) {
            if !on_event(ev)? {
                return Ok(());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_split_chunks_and_crlf() {
        let mut p = SseParser::default();
        assert!(p.push(b"event: a\r\ndata: {\"x\"").is_empty());
        let evs = p.push(b":1}\r\n\r\ndata: two\n\n: comment\n\n");
        assert_eq!(evs.len(), 2);
        assert_eq!(evs[0], SseEvent { event: Some("a".into()), data: "{\"x\":1}".into() });
        assert_eq!(evs[1].data, "two");
    }

    #[test]
    fn handles_split_utf8() {
        let mut p = SseParser::default();
        let s = "data: héllo\n\n".as_bytes();
        let (a, b) = s.split_at(8); // splits inside 'é'
        assert!(p.push(a).is_empty());
        assert_eq!(p.push(b)[0].data, "héllo");
    }
}
