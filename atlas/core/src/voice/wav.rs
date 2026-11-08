//! 16-bit PCM WAV encoding/decoding and simple resampling. Only the formats the engines produce
//! and consume (mono, 16-bit) are supported; anything else is refused with a clear error.

use crate::error::{AtlasError, Result};

#[derive(Debug, Clone, PartialEq)]
pub struct Pcm {
    pub sample_rate: u32,
    pub samples: Vec<i16>,
}

impl Pcm {
    pub fn duration_ms(&self) -> u64 {
        if self.sample_rate == 0 {
            return 0;
        }
        self.samples.len() as u64 * 1000 / self.sample_rate as u64
    }

    /// Root-mean-square level in 0..=1.
    pub fn rms(&self) -> f32 {
        if self.samples.is_empty() {
            return 0.0;
        }
        let sum: f64 = self.samples.iter().map(|&s| (s as f64 / 32768.0).powi(2)).sum();
        (sum / self.samples.len() as f64).sqrt() as f32
    }
}

pub fn encode(pcm: &Pcm) -> Vec<u8> {
    let data_len = (pcm.samples.len() * 2) as u32;
    let mut out = Vec::with_capacity(44 + data_len as usize);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&(36 + data_len).to_le_bytes());
    out.extend_from_slice(b"WAVEfmt ");
    out.extend_from_slice(&16u32.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes()); // PCM
    out.extend_from_slice(&1u16.to_le_bytes()); // mono
    out.extend_from_slice(&pcm.sample_rate.to_le_bytes());
    out.extend_from_slice(&(pcm.sample_rate * 2).to_le_bytes());
    out.extend_from_slice(&2u16.to_le_bytes());
    out.extend_from_slice(&16u16.to_le_bytes());
    out.extend_from_slice(b"data");
    out.extend_from_slice(&data_len.to_le_bytes());
    for s in &pcm.samples {
        out.extend_from_slice(&s.to_le_bytes());
    }
    out
}

/// Decode a 16-bit PCM WAV (mono, or stereo mixed down to mono).
pub fn decode(bytes: &[u8]) -> Result<Pcm> {
    let bad = |m: &str| AtlasError::Validation(format!("unreadable audio: {m}"));
    if bytes.len() < 12 || &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return Err(bad("not a WAV file"));
    }
    let mut pos = 12;
    let (mut rate, mut channels, mut bits) = (0u32, 0u16, 0u16);
    let mut data: Option<&[u8]> = None;
    while pos + 8 <= bytes.len() {
        let id = &bytes[pos..pos + 4];
        let len = u32::from_le_bytes(bytes[pos + 4..pos + 8].try_into().unwrap()) as usize;
        let body_start = pos + 8;
        let body_end = body_start.saturating_add(len).min(bytes.len());
        let body = &bytes[body_start..body_end];
        match id {
            b"fmt " if body.len() >= 16 => {
                let format = u16::from_le_bytes([body[0], body[1]]);
                if format != 1 && format != 0xFFFE {
                    return Err(bad("not PCM"));
                }
                channels = u16::from_le_bytes([body[2], body[3]]);
                rate = u32::from_le_bytes(body[4..8].try_into().unwrap());
                bits = u16::from_le_bytes([body[14], body[15]]);
            }
            b"data" => data = Some(body),
            _ => {}
        }
        pos = body_start + len + (len & 1);
    }
    let data = data.ok_or_else(|| bad("no audio data"))?;
    if bits != 16 || channels == 0 || channels > 2 || rate == 0 {
        return Err(bad("only 16-bit mono or stereo PCM is supported"));
    }
    let frames: Vec<i16> = data.chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]])).collect();
    let samples = if channels == 2 { frames.chunks_exact(2).map(|p| ((p[0] as i32 + p[1] as i32) / 2) as i16).collect() } else { frames };
    Ok(Pcm { sample_rate: rate, samples })
}

/// Linear-interpolation resampling (good enough for speech recognition input).
pub fn resample(pcm: &Pcm, to: u32) -> Pcm {
    if pcm.sample_rate == to || pcm.samples.is_empty() {
        return Pcm { sample_rate: to, samples: pcm.samples.clone() };
    }
    let ratio = pcm.sample_rate as f64 / to as f64;
    let n = ((pcm.samples.len() as f64) / ratio).floor() as usize;
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let x = i as f64 * ratio;
        let i0 = x.floor() as usize;
        let i1 = (i0 + 1).min(pcm.samples.len() - 1);
        let t = x - i0 as f64;
        out.push((pcm.samples[i0] as f64 * (1.0 - t) + pcm.samples[i1] as f64 * t).round() as i16);
    }
    Pcm { sample_rate: to, samples: out }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_and_resample() {
        let pcm = Pcm { sample_rate: 22050, samples: (0..22050).map(|i| ((i as f32 / 10.0).sin() * 10000.0) as i16).collect() };
        let back = decode(&encode(&pcm)).unwrap();
        assert_eq!(back, pcm);
        assert_eq!(back.duration_ms(), 1000);
        let r = resample(&pcm, 16000);
        assert_eq!(r.sample_rate, 16000);
        assert!((r.samples.len() as i64 - 16000).abs() <= 1);
        assert!((r.rms() - pcm.rms()).abs() < 0.02);
        assert!(decode(b"RIFF....WAVEjunk").is_err());
        assert!(decode(b"not audio").is_err());
    }
}
