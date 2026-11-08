//! Speech recognition engines behind one interface.
//!
//! * `WhisperCli`: whisper.cpp's command-line transcriber as a separate process. The recording is
//!   written to a temporary 16 kHz WAV inside Atlas's voice folder only for the duration of the
//!   call and deleted afterwards, whether it succeeds, fails or is cancelled.
//! * `FixtureStt`: a deterministic stand-in for automated tests (returns a fixed phrase when the
//!   audio has speech-level energy). Only used by test builds.

use crate::error::{AtlasError, Result};
use crate::voice::download::find_file;
use crate::voice::tts::path_with;
use crate::voice::wav::{self, Pcm};
use async_trait::async_trait;
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tokio_util::sync::CancellationToken;

pub const STT_SAMPLE_RATE: u32 = 16_000;
/// Longest recording accepted (push-to-talk is for requests, not dictation of long documents).
pub const MAX_RECORDING_SECS: u64 = 120;
pub const MIN_RECORDING_MS: u64 = 300;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Transcript {
    pub text: String,
    pub audio_ms: u64,
    pub elapsed_ms: u64,
    pub engine: String,
}

#[async_trait]
pub trait SpeechToText: Send + Sync {
    fn name(&self) -> &str;
    async fn transcribe(&self, pcm: &Pcm, language: &str, cancel: &CancellationToken) -> Result<Transcript>;
}

/// Check a recording before it is handed to an engine.
pub fn check_recording(pcm: &Pcm) -> Result<()> {
    if pcm.sample_rate != STT_SAMPLE_RATE {
        return Err(AtlasError::Validation(format!("recordings must be {STT_SAMPLE_RATE} Hz")));
    }
    let ms = pcm.duration_ms();
    if ms < MIN_RECORDING_MS {
        return Err(AtlasError::Validation("that was too short to understand; hold the microphone a little longer".into()));
    }
    if ms > MAX_RECORDING_SECS * 1000 {
        return Err(AtlasError::Validation(format!("recordings are limited to {MAX_RECORDING_SECS} seconds")));
    }
    Ok(())
}

/// Whisper language codes are two or three letters, or "auto". Settings may hold "en-US".
pub fn whisper_language(setting: &str) -> String {
    let s = setting.trim().to_ascii_lowercase();
    if s.is_empty() || s == "auto" {
        return "auto".into();
    }
    let primary: String = s.split(['-', '_']).next().unwrap_or("").chars().filter(|c| c.is_ascii_lowercase()).collect();
    if (2..=3).contains(&primary.len()) { primary } else { "auto".into() }
}

/// Drop whisper's non-speech annotations ("[BLANK_AUDIO]", "(music)") and tidy whitespace.
pub fn clean_transcript(raw: &str) -> String {
    let re = regex::Regex::new(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*").expect("valid regex");
    let text = re.replace_all(raw, " ");
    text.split_whitespace().collect::<Vec<_>>().join(" ").trim().to_string()
}

pub struct WhisperCli {
    pub program: PathBuf,
    pub lib_dirs: Vec<PathBuf>,
    pub model: PathBuf,
    pub tmp_dir: PathBuf,
    pub threads: usize,
    pub model_name: String,
}

impl WhisperCli {
    pub fn locate(engine_dir: &Path, model_file: &Path, tmp_dir: &Path, model_name: &str) -> Result<Self> {
        let exe = if cfg!(windows) { "whisper-cli.exe" } else { "whisper-cli" };
        let program = find_file(engine_dir, exe).ok_or_else(|| AtlasError::NotFound("the speech recognition engine is missing; reinstall it".into()))?;
        if !model_file.is_file() {
            return Err(AtlasError::NotFound("the speech recognition model is missing; reinstall it".into()));
        }
        let bin = program.parent().map(Path::to_path_buf).unwrap_or_default();
        let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(2).clamp(1, 8);
        Ok(Self { program, lib_dirs: vec![bin], model: model_file.to_path_buf(), tmp_dir: tmp_dir.to_path_buf(), threads, model_name: model_name.into() })
    }

    pub fn args(&self, wav: &Path, language: &str) -> Vec<String> {
        vec![
            self.program.to_string_lossy().into_owned(),
            "-m".into(),
            self.model.to_string_lossy().into_owned(),
            "-f".into(),
            wav.to_string_lossy().into_owned(),
            "-l".into(),
            whisper_language(language),
            "-t".into(),
            self.threads.to_string(),
            "-nt".into(), // no timestamps
            "-np".into(), // print only the transcript
        ]
    }
}

#[async_trait]
impl SpeechToText for WhisperCli {
    fn name(&self) -> &str {
        &self.model_name
    }

    async fn transcribe(&self, pcm: &Pcm, language: &str, cancel: &CancellationToken) -> Result<Transcript> {
        check_recording(pcm)?;
        std::fs::create_dir_all(&self.tmp_dir).map_err(|e| AtlasError::Io(e.to_string()))?;
        let file = self.tmp_dir.join(format!("stt-{}.wav", uuid::Uuid::new_v4()));
        std::fs::write(&file, wav::encode(pcm)).map_err(|e| AtlasError::Io(e.to_string()))?;
        let argv = self.args(&file, language);
        let path = path_with(&self.lib_dirs);
        let env: Vec<(&str, &str)> = vec![("PATH", path.as_str())];
        let cwd = self.program.parent().unwrap_or(Path::new("."));
        // Allow several times real time for slow CPUs and large models, never unbounded.
        let timeout = Duration::from_secs(30 + pcm.duration_ms() / 1000 * 6);
        let started = Instant::now();
        let run = crate::forge::runner::run(crate::forge::runner::RunSpec { argv: &argv, cwd, timeout, max_output: 64 * 1024, extra_env: &env }, cancel).await;
        // The recording never outlives the call.
        let _ = std::fs::remove_file(&file);
        let out = run?;
        match out.status.as_str() {
            "cancelled" => Err(AtlasError::Cancelled),
            "timed_out" => Err(AtlasError::Timeout("speech recognition took too long and was stopped; a smaller model may help".into())),
            "succeeded" => Ok(Transcript {
                text: clean_transcript(&transcript_lines(&out.output)),
                audio_ms: pcm.duration_ms(),
                elapsed_ms: started.elapsed().as_millis() as u64,
                engine: self.model_name.clone(),
            }),
            _ => Err(AtlasError::Tool(format!("speech recognition failed (exit {:?})", out.exit_code))),
        }
    }
}

/// whisper-cli with `-np` prints the transcript to stdout; stderr (mixed into the runner's output)
/// can still carry loader lines starting with "whisper_" or "ggml_", which are not speech.
fn transcript_lines(output: &str) -> String {
    output
        .lines()
        .map(str::trim)
        .filter(|l| {
            let t = l.trim();
            !t.is_empty() && !t.starts_with("whisper_") && !t.starts_with("ggml_") && !t.starts_with("main:") && !t.starts_with("system_info")
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Deterministic stand-in for tests. Not speech recognition.
pub struct FixtureStt {
    pub phrase: String,
}

#[async_trait]
impl SpeechToText for FixtureStt {
    fn name(&self) -> &str {
        "Test recogniser (fixture, not speech recognition)"
    }

    async fn transcribe(&self, pcm: &Pcm, _language: &str, cancel: &CancellationToken) -> Result<Transcript> {
        check_recording(pcm)?;
        let started = Instant::now();
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(150)) => {}
            _ = cancel.cancelled() => return Err(AtlasError::Cancelled),
        }
        let text = if pcm.rms() > 0.005 { self.phrase.clone() } else { String::new() };
        Ok(Transcript { text, audio_ms: pcm.duration_ms(), elapsed_ms: started.elapsed().as_millis() as u64, engine: self.name().into() })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn language_codes_and_cleanup() {
        assert_eq!(whisper_language("en-US"), "en");
        assert_eq!(whisper_language("ar"), "ar");
        assert_eq!(whisper_language(""), "auto");
        assert_eq!(whisper_language("auto"), "auto");
        assert_eq!(whisper_language("--rm"), "auto", "option-like text never becomes a language");
        assert_eq!(whisper_language("x"), "auto");
        assert_eq!(clean_transcript(" [BLANK_AUDIO]  Hello   there (music) "), "Hello there");
        assert_eq!(transcript_lines("whisper_init: loading\n What is the time?\nggml_x: y\n"), "What is the time?");
    }

    #[test]
    fn recordings_are_bounded() {
        let ok = Pcm { sample_rate: 16_000, samples: vec![0; 16_000] };
        assert!(check_recording(&ok).is_ok());
        assert!(check_recording(&Pcm { sample_rate: 16_000, samples: vec![0; 1_000] }).is_err());
        assert!(check_recording(&Pcm { sample_rate: 44_100, samples: vec![0; 44_100] }).is_err());
        assert!(check_recording(&Pcm { sample_rate: 16_000, samples: vec![0; 16_000 * 121] }).is_err());
    }
}
