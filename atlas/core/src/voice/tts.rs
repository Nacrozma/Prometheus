//! Text-to-speech engines behind one interface. The Companion never knows which engine speaks.
//!
//! * `SherpaTts`: Piper voices run by the sherpa-onnx command-line synthesiser, as a separate
//!   process (no shell, scrubbed environment, time limit, killed on cancel). Output goes to a
//!   temporary WAV inside Atlas's voice folder, which is read and deleted immediately.
//! * `FixtureTts`: a deterministic, speech-like test signal for automated tests. It is real audio
//!   (it is played and analysed like speech) but it is not a voice, and it is only used by test
//!   builds.

use crate::error::{AtlasError, Result};
use crate::voice::download::{find_ext, find_file};
use crate::voice::wav::{self, Pcm};
use async_trait::async_trait;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

/// Longest text accepted in one synthesis call (the UI sends a sentence or two at a time).
pub const MAX_TTS_CHARS: usize = 1_200;

#[async_trait]
pub trait TextToSpeech: Send + Sync {
    fn name(&self) -> &str;
    async fn synthesize(&self, text: &str, speed: f32, cancel: &CancellationToken) -> Result<Pcm>;
}

/// Make text safe to hand to the engine: no control characters, no leading dash (it would be read
/// as an option), bounded length.
pub fn sanitize(text: &str) -> Result<String> {
    let cleaned: String = text.chars().map(|c| if c.is_control() { ' ' } else { c }).collect();
    let cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    let cleaned = cleaned.trim_start_matches(['-', '–', '—']).trim().to_string();
    if cleaned.is_empty() {
        return Err(AtlasError::Validation("there is nothing to say".into()));
    }
    if cleaned.chars().count() > MAX_TTS_CHARS {
        return Err(AtlasError::Validation(format!("text to speak is limited to {MAX_TTS_CHARS} characters at a time")));
    }
    Ok(cleaned)
}

pub fn clamp_speed(speed: f32) -> f32 {
    if speed.is_finite() { speed.clamp(0.5, 2.0) } else { 1.0 }
}

pub struct SherpaTts {
    pub program: PathBuf,
    pub lib_dirs: Vec<PathBuf>,
    pub model: PathBuf,
    pub tokens: PathBuf,
    pub data_dir: PathBuf,
    pub tmp_dir: PathBuf,
    pub threads: usize,
    pub voice_name: String,
}

impl SherpaTts {
    /// Locate the engine's synthesiser and the voice's files inside their install folders.
    pub fn locate(engine_dir: &Path, voice_dir: &Path, tmp_dir: &Path, voice_name: &str) -> Result<Self> {
        let exe = if cfg!(windows) { "sherpa-onnx-offline-tts.exe" } else { "sherpa-onnx-offline-tts" };
        let program = find_file(engine_dir, exe).ok_or_else(|| AtlasError::NotFound("the speech engine's synthesiser is missing; reinstall the engine".into()))?;
        let model = find_ext(voice_dir, "onnx").ok_or_else(|| AtlasError::NotFound("the voice model file is missing; reinstall the voice".into()))?;
        let tokens = find_file(voice_dir, "tokens.txt").ok_or_else(|| AtlasError::NotFound("the voice's tokens file is missing; reinstall the voice".into()))?;
        let data_dir = model.parent().map(|p| p.join("espeak-ng-data")).filter(|p| p.is_dir()).ok_or_else(|| AtlasError::NotFound("the voice's pronunciation data is missing; reinstall the voice".into()))?;
        let bin = program.parent().map(Path::to_path_buf).unwrap_or_default();
        let lib = bin.parent().map(|p| p.join("lib")).unwrap_or_default();
        let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(2).clamp(1, 4);
        Ok(Self { program, lib_dirs: vec![bin, lib], model, tokens, data_dir, tmp_dir: tmp_dir.to_path_buf(), threads, voice_name: voice_name.into() })
    }

    /// The exact arguments passed to the engine (also used by tests).
    pub fn args(&self, text: &str, speed: f32, out: &Path) -> Vec<String> {
        // Piper's length scale is the inverse of speed: 0.5 = twice as fast.
        let length_scale = 1.0 / clamp_speed(speed);
        vec![
            self.program.to_string_lossy().into_owned(),
            format!("--vits-model={}", self.model.display()),
            format!("--vits-tokens={}", self.tokens.display()),
            format!("--vits-data-dir={}", self.data_dir.display()),
            format!("--vits-length-scale={length_scale:.3}"),
            format!("--num-threads={}", self.threads),
            format!("--output-filename={}", out.display()),
            text.to_string(),
        ]
    }
}

pub fn path_with(dirs: &[PathBuf]) -> String {
    let sep = if cfg!(windows) { ";" } else { ":" };
    let mut parts: Vec<String> = dirs.iter().filter(|d| d.is_dir()).map(|d| d.to_string_lossy().into_owned()).collect();
    if let Ok(p) = std::env::var("PATH") {
        parts.push(p);
    }
    parts.join(sep)
}

#[async_trait]
impl TextToSpeech for SherpaTts {
    fn name(&self) -> &str {
        &self.voice_name
    }

    async fn synthesize(&self, text: &str, speed: f32, cancel: &CancellationToken) -> Result<Pcm> {
        let text = sanitize(text)?;
        std::fs::create_dir_all(&self.tmp_dir).map_err(|e| AtlasError::Io(e.to_string()))?;
        let out = self.tmp_dir.join(format!("tts-{}.wav", uuid::Uuid::new_v4()));
        let argv = self.args(&text, speed, &out);
        let path = path_with(&self.lib_dirs);
        let ld = self.lib_dirs.iter().map(|d| d.to_string_lossy().into_owned()).collect::<Vec<_>>().join(":");
        let env: Vec<(&str, &str)> = vec![("PATH", path.as_str()), ("LD_LIBRARY_PATH", ld.as_str())];
        let cwd = self.program.parent().unwrap_or(Path::new("."));
        // Long sentences on slow CPUs take a few seconds; a minute means something is wrong.
        let timeout = Duration::from_secs(60);
        let run = crate::forge::runner::run(crate::forge::runner::RunSpec { argv: &argv, cwd, timeout, max_output: 16 * 1024, extra_env: &env }, cancel).await;
        let result = match run {
            Ok(o) if o.status == "cancelled" => Err(AtlasError::Cancelled),
            Ok(o) if o.status == "timed_out" => Err(AtlasError::Timeout("the speech engine took too long and was stopped".into())),
            Ok(o) if o.status != "succeeded" => Err(AtlasError::Tool(format!("the speech engine failed (exit {:?}): {}", o.exit_code, last_line(&o.output)))),
            Ok(_) => std::fs::read(&out).map_err(|_| AtlasError::Tool("the speech engine produced no audio".into())).and_then(|b| wav::decode(&b)),
            Err(e) => Err(e),
        };
        let _ = std::fs::remove_file(&out);
        let pcm = result?;
        if pcm.samples.is_empty() {
            return Err(AtlasError::Tool("the speech engine produced empty audio".into()));
        }
        Ok(pcm)
    }
}

/// The engine's last few non-empty lines (the useful part of its error output).
fn last_line(s: &str) -> String {
    let lines: Vec<&str> = s.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
    let tail = lines[lines.len().saturating_sub(4)..].join(" | ");
    tail.chars().rev().take(600).collect::<Vec<_>>().into_iter().rev().collect()
}

/// Deterministic speech-like audio for tests: syllables at about 4 per second with pauses between
/// words, so its loudness rises and falls like speech. Not a voice.
pub struct FixtureTts;

pub fn fixture_audio(text: &str, speed: f32) -> Pcm {
    let rate = 22_050u32;
    let speed = clamp_speed(speed);
    let mut samples = Vec::new();
    for (wi, word) in text.split_whitespace().enumerate() {
        let syllables = (word.chars().filter(|c| "aeiouyAEIOUY".contains(*c)).count()).clamp(1, 4);
        let f0 = 140.0 + (wi % 5) as f32 * 18.0;
        for _ in 0..syllables {
            let n = (rate as f32 * 0.18 / speed) as usize;
            for i in 0..n {
                let t = i as f32 / rate as f32;
                let env = (std::f32::consts::PI * i as f32 / n as f32).sin().powi(2);
                let v = (2.0 * std::f32::consts::PI * f0 * t).sin() * 0.6 + (2.0 * std::f32::consts::PI * f0 * 2.0 * t).sin() * 0.25 + (2.0 * std::f32::consts::PI * f0 * 3.0 * t).sin() * 0.1;
                samples.push((v * env * 14_000.0) as i16);
            }
        }
        samples.extend(std::iter::repeat_n(0i16, (rate as f32 * 0.07 / speed) as usize));
        if samples.len() > rate as usize * 20 {
            break;
        }
    }
    Pcm { sample_rate: rate, samples }
}

#[async_trait]
impl TextToSpeech for FixtureTts {
    fn name(&self) -> &str {
        "Test voice (fixture, not a real voice)"
    }

    async fn synthesize(&self, text: &str, speed: f32, cancel: &CancellationToken) -> Result<Pcm> {
        let text = sanitize(text)?;
        // A small delay so tests see the "processing" state, cancellable like the real engine.
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(60)) => {}
            _ = cancel.cancelled() => return Err(AtlasError::Cancelled),
        }
        Ok(fixture_audio(&text, speed))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_bounds_and_neutralises_option_like_text() {
        assert_eq!(sanitize("  --help me\u{7} now ").unwrap(), "help me now");
        assert!(sanitize("   ").is_err());
        assert!(sanitize(&"a".repeat(MAX_TTS_CHARS + 1)).is_err());
        assert_eq!(clamp_speed(9.0), 2.0);
        assert_eq!(clamp_speed(f32::NAN), 1.0);
    }

    #[test]
    fn fixture_audio_rises_and_falls_like_speech() {
        let pcm = fixture_audio("Hello there, this is a test.", 1.0);
        assert!(pcm.duration_ms() > 800 && pcm.duration_ms() < 5000, "{}", pcm.duration_ms());
        // Loud syllables and quiet gaps: energy varies across 50 ms windows.
        let win = 22_050 / 20;
        let levels: Vec<f32> = pcm.samples.chunks(win).map(|c| Pcm { sample_rate: 22_050, samples: c.to_vec() }.rms()).collect();
        let max = levels.iter().cloned().fold(0.0, f32::max);
        let min = levels.iter().cloned().fold(1.0, f32::min);
        assert!(max > 0.1 && min < 0.02, "max {max} min {min}");
        assert!(fixture_audio("Hello there, this is a test.", 2.0).duration_ms() < pcm.duration_ms());
    }
}
