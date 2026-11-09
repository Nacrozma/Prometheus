//! Atlas Voice: local speech output and recognition.
//!
//! Separation of concerns:
//! * `catalog`: what may be downloaded (pinned URLs and hashes).
//! * `download`: verified installs and integrity checks.
//! * `tts` / `stt`: engines behind traits, so the UI never depends on one engine.
//! * `wav`: audio formats; `hardware`: local capability assessment.
//! * This module: the service the app talks to (status, installs, synthesis, transcription,
//!   cancellation, single-flight recognition, benchmark).
//!
//! Privacy: audio only exists in memory, plus temporary WAV files inside `<data>/voice/tmp` for the
//! duration of one engine call; they are deleted afterwards and on startup. Nothing is logged.
//! Downloads honour offline mode. No cloud service is involved.

pub mod catalog;
pub mod download;
pub mod hardware;
pub mod stt;
pub mod tts;
pub mod wav;

use crate::error::{AtlasError, Result};
use crate::settings::Settings;
use catalog::{Artifact, ArtifactKind};
use download::InstallState;
use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use stt::{SpeechToText, Transcript};
use tokio_util::sync::CancellationToken;
use tts::TextToSpeech;
use wav::Pcm;

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactStatus {
    #[serde(flatten)]
    pub artifact: Artifact,
    pub state: InstallState,
    pub installing: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct VoiceStatus {
    pub platform: String,
    pub tts_supported: bool,
    pub stt_supported: bool,
    pub tts_engine: Option<ArtifactStatus>,
    pub stt_engine: Option<ArtifactStatus>,
    pub voices: Vec<ArtifactStatus>,
    pub stt_models: Vec<ArtifactStatus>,
    pub selected_voice: String,
    pub selected_stt_model: String,
    /// Speech output can be used right now (engine and selected voice installed).
    pub tts_ready: bool,
    /// Speech recognition can be used right now.
    pub stt_ready: bool,
    /// Test build: deterministic stand-in engines, clearly not real speech.
    pub fixtures: bool,
    pub hardware: hardware::HardwareReport,
    /// Temporary audio files present now (should always be 0 between calls).
    pub temp_audio_files: usize,
    pub storage_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct BenchmarkModel {
    pub id: String,
    pub name: String,
    pub elapsed_ms: u64,
    /// Processing time ÷ audio length (below 1 is faster than real time).
    pub real_time_factor: f64,
    pub transcript: String,
    pub word_accuracy: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct BenchmarkReport {
    pub fixtures: bool,
    pub phrase: String,
    pub voice: String,
    pub synthesis_ms: u64,
    pub audio_ms: u64,
    pub synthesis_rtf: f64,
    pub models: Vec<BenchmarkModel>,
    pub hardware: hardware::HardwareReport,
}

/// A replacement download source for an artifact (automated tests serve fixtures locally).
#[derive(Debug, Clone)]
pub struct Override {
    pub url: String,
    pub sha256: String,
    pub bytes: u64,
}

pub struct VoiceService {
    root: Option<PathBuf>,
    fixtures: AtomicBool,
    overrides: Mutex<HashMap<String, Override>>,
    installs: Mutex<HashMap<String, CancellationToken>>,
    speech: Mutex<CancellationToken>,
    transcribing: Mutex<Option<CancellationToken>>,
}

pub const BENCHMARK_PHRASE: &str = "Hello Atlas. Please remind me to call my sister tomorrow at nine in the morning.";

impl VoiceService {
    pub fn new(data_dir: Option<&Path>) -> Self {
        let root = data_dir.map(|d| d.join("voice"));
        if let Some(r) = &root {
            // Leftover temporary audio from a crash is removed at startup.
            let _ = std::fs::remove_dir_all(r.join("tmp"));
            // Interrupted installs leave staging folders; remove them too.
            for kind in ["engines", "voices", "models"] {
                if let Ok(rd) = std::fs::read_dir(r.join(kind)) {
                    for e in rd.flatten() {
                        if e.file_name().to_string_lossy().ends_with(".staging") {
                            let _ = std::fs::remove_dir_all(e.path());
                        }
                    }
                }
            }
        }
        Self {
            root,
            fixtures: AtomicBool::new(false),
            overrides: Mutex::new(HashMap::new()),
            installs: Mutex::new(HashMap::new()),
            speech: Mutex::new(CancellationToken::new()),
            transcribing: Mutex::new(None),
        }
    }

    /// Test builds: use the deterministic stand-in engines instead of real ones.
    pub fn use_fixtures(&self, on: bool) {
        self.fixtures.store(on, Ordering::SeqCst);
    }

    pub fn fixtures(&self) -> bool {
        self.fixtures.load(Ordering::SeqCst)
    }

    /// Automated tests: download an artifact from a local server instead of its public URL.
    pub fn set_override(&self, id: &str, o: Override) {
        self.overrides.lock().expect("overrides").insert(id.into(), o);
    }

    fn root(&self) -> Result<&Path> {
        self.root.as_deref().ok_or_else(|| AtlasError::Validation("voice needs Atlas's data folder".into()))
    }

    fn tmp(&self) -> Result<PathBuf> {
        Ok(self.root()?.join("tmp"))
    }

    /// The artifact as it will be downloaded (public, or overridden by a test).
    fn effective(&self, a: &'static Artifact) -> (Artifact, String) {
        let ov = self.overrides.lock().expect("overrides").get(a.id).cloned();
        match ov {
            Some(o) => {
                let mut x = a.clone();
                x.sha256 = Box::leak(o.sha256.into_boxed_str());
                x.bytes = o.bytes;
                (x, o.url)
            }
            None => (a.clone(), a.url.to_string()),
        }
    }

    fn state_of(&self, a: &'static Artifact) -> InstallState {
        match self.root() {
            Ok(r) => download::state(r, &self.effective(a).0),
            Err(_) => InstallState::NotInstalled,
        }
    }

    fn status_of(&self, a: &'static Artifact) -> ArtifactStatus {
        let installing = self.installs.lock().expect("installs").contains_key(a.id);
        ArtifactStatus { artifact: self.effective(a).0, state: self.state_of(a), installing }
    }

    pub fn selected_voice(settings: &Settings) -> &'static Artifact {
        settings.voice.tts_voice.as_deref().and_then(catalog::get).filter(|a| a.kind == ArtifactKind::Voice).unwrap_or_else(catalog::default_voice)
    }

    pub fn selected_stt_model(settings: &Settings) -> &'static Artifact {
        settings.voice.stt_model.as_deref().and_then(catalog::get).filter(|a| a.kind == ArtifactKind::SttModel).unwrap_or_else(catalog::default_stt_model)
    }

    pub fn status(&self, settings: &Settings) -> VoiceStatus {
        let tts_engine = catalog::engine(ArtifactKind::TtsEngine);
        let stt_engine = catalog::engine(ArtifactKind::SttEngine);
        let voice = Self::selected_voice(settings);
        let model = Self::selected_stt_model(settings);
        let fixtures = self.fixtures();
        let installed = |a: &'static Artifact| self.state_of(a) == InstallState::Installed;
        // Readiness always means "the files are installed". In test builds the stand-in engines
        // replace only the engine programs (and stand in where none is published for the platform).
        let engine_ok = |e: Option<&'static Artifact>| e.map(installed).unwrap_or(fixtures);
        let tts_ready = engine_ok(tts_engine) && installed(voice);
        let stt_ready = engine_ok(stt_engine) && installed(model);
        let temp_audio_files = self
            .tmp()
            .ok()
            .and_then(|t| std::fs::read_dir(t).ok())
            .map(|rd| rd.flatten().filter(|e| e.path().extension().is_some_and(|x| x == "wav")).count())
            .unwrap_or(0);
        let storage_bytes = self.root().ok().map(dir_size).unwrap_or(0);
        VoiceStatus {
            platform: catalog::current_platform(),
            tts_supported: fixtures || tts_engine.is_some(),
            stt_supported: fixtures || stt_engine.is_some(),
            tts_engine: tts_engine.map(|a| self.status_of(a)),
            stt_engine: stt_engine.map(|a| self.status_of(a)),
            voices: catalog::available().filter(|a| a.kind == ArtifactKind::Voice).map(|a| self.status_of(a)).collect(),
            stt_models: catalog::available().filter(|a| a.kind == ArtifactKind::SttModel).map(|a| self.status_of(a)).collect(),
            selected_voice: voice.id.into(),
            selected_stt_model: model.id.into(),
            tts_ready,
            stt_ready,
            fixtures,
            hardware: hardware::report(self.root.as_deref()),
            temp_audio_files,
            storage_bytes,
        }
    }

    /// Download, verify and unpack a catalog artifact. Refused in offline mode.
    pub async fn install(&self, client: &reqwest::Client, settings: &Settings, id: &str, on: &mut (dyn FnMut(download::Progress) + Send)) -> Result<()> {
        let a = catalog::get(id).ok_or_else(|| AtlasError::NotFound(format!("voice download '{id}'")))?;
        if a.platform.is_some_and(|p| p != catalog::current_platform()) {
            return Err(AtlasError::Validation(format!("{} is not for this computer's platform", a.name)));
        }
        let (art, url) = self.effective(a);
        // Offline mode blocks every download, wherever it comes from.
        if settings.network.offline_mode {
            return Err(AtlasError::PermissionDenied("offline mode is on, so Atlas will not download anything. Turn it off in Settings → Data & privacy to download voice files".into()));
        }
        let local = url.starts_with("http://127.0.0.1:") || url.starts_with("http://localhost:");
        if !url.starts_with("https://") && !local {
            return Err(AtlasError::Validation("voice downloads must use HTTPS".into()));
        }
        let root = self.root()?.to_path_buf();
        if let (Some(free), true) = (hardware::report(Some(&root)).free_disk_mb, art.bytes > 0) {
            // The archive and its unpacked files both need room for a moment.
            if free * 1_048_576 < art.bytes * 3 {
                return Err(AtlasError::Validation(format!("not enough free disk space for {} ({} MB needed)", art.name, art.bytes * 3 / 1_000_000)));
            }
        }
        let cancel = {
            let mut m = self.installs.lock().expect("installs");
            if m.contains_key(id) {
                return Err(AtlasError::Conflict(format!("{} is already downloading", a.name)));
            }
            let t = CancellationToken::new();
            m.insert(id.into(), t.clone());
            t
        };
        let r = download::install(client, &art, &url, &root, &cancel, on).await;
        self.installs.lock().expect("installs").remove(id);
        r.map(|_| ())
    }

    pub fn cancel_install(&self, id: &str) -> bool {
        match self.installs.lock().expect("installs").get(id) {
            Some(t) => {
                t.cancel();
                true
            }
            None => false,
        }
    }

    pub fn remove(&self, id: &str) -> Result<()> {
        let a = catalog::get(id).ok_or_else(|| AtlasError::NotFound(format!("voice download '{id}'")))?;
        if self.installs.lock().expect("installs").contains_key(id) {
            return Err(AtlasError::Conflict(format!("{} is downloading; cancel it first", a.name)));
        }
        download::remove(self.root()?, &self.effective(a).0)
    }

    /// Re-hash an installed artifact. Returns the files that are missing or changed.
    pub fn verify(&self, id: &str) -> Result<Vec<String>> {
        let a = catalog::get(id).ok_or_else(|| AtlasError::NotFound(format!("voice download '{id}'")))?;
        download::verify(self.root()?, &self.effective(a).0)
    }

    fn require_installed(&self, a: &'static Artifact) -> Result<PathBuf> {
        let root = self.root()?;
        match self.state_of(a) {
            InstallState::Installed => Ok(download::install_dir(root, &self.effective(a).0)),
            InstallState::Damaged => Err(AtlasError::Validation(format!("{} is damaged; remove it and download it again", a.name))),
            InstallState::NotInstalled => Err(AtlasError::NotFound(format!("{} is not downloaded yet (Settings → Voice)", a.name))),
        }
    }

    pub fn tts_engine(&self, settings: &Settings) -> Result<Arc<dyn TextToSpeech>> {
        let voice = Self::selected_voice(settings);
        let voice_dir = self.require_installed(voice)?;
        let engine = catalog::engine(ArtifactKind::TtsEngine);
        if self.fixtures() {
            if let Some(e) = engine {
                self.require_installed(e)?;
            }
            return Ok(Arc::new(tts::FixtureTts));
        }
        let engine = engine.ok_or_else(|| AtlasError::Validation("speech output is not available on this platform yet".into()))?;
        let engine_dir = self.require_installed(engine)?;
        Ok(Arc::new(tts::SherpaTts::locate(&engine_dir, &voice_dir, &self.tmp()?, voice.name)?))
    }

    fn stt_engine_for(&self, model: &'static Artifact) -> Result<Arc<dyn SpeechToText>> {
        let model_dir = self.require_installed(model)?;
        let engine = catalog::engine(ArtifactKind::SttEngine);
        if self.fixtures() {
            if let Some(e) = engine {
                self.require_installed(e)?;
            }
            return Ok(Arc::new(stt::FixtureStt { phrase: "What is 6 times 7?".into() }));
        }
        let engine = engine.ok_or_else(|| AtlasError::Validation("speech recognition is not available on this platform yet".into()))?;
        let engine_dir = self.require_installed(engine)?;
        Ok(Arc::new(stt::WhisperCli::locate(&engine_dir, &model_dir.join(model.file_name), &self.tmp()?, model.name)?))
    }

    /// The token shared by current synthesis calls; `stop_speech` cancels it.
    fn speech_token(&self) -> CancellationToken {
        self.speech.lock().expect("speech").clone()
    }

    /// Stop every synthesis in progress. Already generated text is untouched.
    pub fn stop_speech(&self) {
        let mut t = self.speech.lock().expect("speech");
        t.cancel();
        *t = CancellationToken::new();
    }

    pub async fn synthesize(&self, settings: &Settings, text: &str, speed: Option<f32>) -> Result<Pcm> {
        let engine = self.tts_engine(settings)?;
        let token = self.speech_token();
        engine.synthesize(text, speed.unwrap_or(settings.voice.speed), &token).await
    }

    /// Transcribe one recording. Only one at a time: a second request is refused, not queued.
    pub async fn transcribe(&self, settings: &Settings, pcm: &Pcm) -> Result<Transcript> {
        stt::check_recording(pcm)?;
        let engine = self.stt_engine_for(Self::selected_stt_model(settings))?;
        let token = {
            let mut slot = self.transcribing.lock().expect("transcribing");
            if slot.is_some() {
                return Err(AtlasError::Conflict("Atlas is already transcribing a recording".into()));
            }
            let t = CancellationToken::new();
            *slot = Some(t.clone());
            t
        };
        let r = engine.transcribe(pcm, &settings.voice.language, &token).await;
        *self.transcribing.lock().expect("transcribing") = None;
        r
    }

    pub fn cancel_transcription(&self) -> bool {
        match self.transcribing.lock().expect("transcribing").as_ref() {
            Some(t) => {
                t.cancel();
                true
            }
            None => false,
        }
    }

    /// Measure synthesis and recognition on this computer: synthesise a fixed phrase with the
    /// selected voice, then transcribe it with every installed model.
    pub async fn benchmark(&self, settings: &Settings) -> Result<BenchmarkReport> {
        let engine = self.tts_engine(settings)?;
        let token = CancellationToken::new();
        let t0 = Instant::now();
        let speech = engine.synthesize(BENCHMARK_PHRASE, 1.0, &token).await?;
        let synthesis_ms = t0.elapsed().as_millis() as u64;
        let audio_ms = speech.duration_ms().max(1);
        let input = wav::resample(&speech, stt::STT_SAMPLE_RATE);
        let mut models = Vec::new();
        let candidates: Vec<&'static Artifact> =
            catalog::available().filter(|a| a.kind == ArtifactKind::SttModel && self.state_of(a) == InstallState::Installed).collect();
        for m in candidates {
            let stt = match self.stt_engine_for(m) {
                Ok(s) => s,
                Err(_) => continue,
            };
            let t = Instant::now();
            let tr = stt.transcribe(&input, "en", &token).await?;
            let elapsed_ms = t.elapsed().as_millis() as u64;
            models.push(BenchmarkModel {
                id: m.id.into(),
                name: m.name.into(),
                elapsed_ms,
                real_time_factor: elapsed_ms as f64 / audio_ms as f64,
                word_accuracy: word_accuracy(BENCHMARK_PHRASE, &tr.text),
                transcript: tr.text,
            });
        }
        Ok(BenchmarkReport {
            fixtures: self.fixtures(),
            phrase: BENCHMARK_PHRASE.into(),
            voice: engine.name().into(),
            synthesis_ms,
            audio_ms,
            synthesis_rtf: synthesis_ms as f64 / audio_ms as f64,
            models,
            hardware: hardware::report(self.root.as_deref()),
        })
    }
}

/// Share of the reference's words found in the hypothesis, in order (a simple, honest measure).
pub fn word_accuracy(reference: &str, hypothesis: &str) -> f64 {
    let norm = |s: &str| s.to_lowercase().split(|c: char| !c.is_alphanumeric()).filter(|w| !w.is_empty()).map(str::to_string).collect::<Vec<_>>();
    let (r, h) = (norm(reference), norm(hypothesis));
    if r.is_empty() {
        return 0.0;
    }
    // Longest common subsequence of words.
    let mut dp = vec![vec![0usize; h.len() + 1]; r.len() + 1];
    for i in 1..=r.len() {
        for j in 1..=h.len() {
            dp[i][j] = if r[i - 1] == h[j - 1] { dp[i - 1][j - 1] + 1 } else { dp[i - 1][j].max(dp[i][j - 1]) };
        }
    }
    dp[r.len()][h.len()] as f64 / r.len() as f64
}

fn dir_size(p: &Path) -> u64 {
    let mut total = 0;
    let mut stack = vec![p.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for e in rd.flatten() {
            match e.file_type() {
                Ok(t) if t.is_dir() => stack.push(e.path()),
                Ok(t) if t.is_file() => total += e.metadata().map(|m| m.len()).unwrap_or(0),
                _ => {}
            }
        }
    }
    total
}

// ---------------- the app-facing API ----------------

impl crate::app::Atlas {
    pub fn voice_status(&self) -> Result<VoiceStatus> {
        Ok(self.voice.status(&self.settings()?))
    }

    pub async fn voice_install(&self, id: &str, on: &mut (dyn FnMut(download::Progress) + Send)) -> Result<VoiceStatus> {
        let settings = self.settings()?;
        let r = self.voice.install(&self.voice_http, &settings, id, on).await;
        match &r {
            Ok(()) => crate::audit::record(&self.db, "voice.installed", "info", None, None, serde_json::json!({"id": id})),
            Err(AtlasError::Cancelled) => crate::audit::record(&self.db, "voice.install_cancelled", "info", None, None, serde_json::json!({"id": id})),
            Err(e) => crate::audit::record(&self.db, "voice.install_failed", "warn", None, None, serde_json::json!({"id": id, "error": crate::redact::redact(&e.to_string())})),
        }
        crate::events::notify(&self.bus, crate::events::Topic::Settings, None);
        r?;
        Ok(self.voice.status(&settings))
    }

    pub fn voice_cancel_install(&self, id: &str) -> bool {
        self.voice.cancel_install(id)
    }

    pub fn voice_remove(&self, id: &str) -> Result<VoiceStatus> {
        self.voice.remove(id)?;
        crate::audit::record(&self.db, "voice.removed", "info", None, None, serde_json::json!({"id": id}));
        crate::events::notify(&self.bus, crate::events::Topic::Settings, None);
        self.voice_status()
    }

    pub fn voice_verify(&self, id: &str) -> Result<Vec<String>> {
        self.voice.verify(id)
    }

    /// Synthesise text with the selected voice; returns a WAV file's bytes for playback.
    pub async fn voice_synthesize(&self, text: &str, speed: Option<f32>) -> Result<Vec<u8>> {
        let settings = self.settings()?;
        let pcm = self.voice.synthesize(&settings, text, speed).await?;
        Ok(wav::encode(&pcm))
    }

    pub fn voice_stop_speech(&self) {
        self.voice.stop_speech();
    }

    /// Transcribe a 16 kHz recording given as little-endian 16-bit samples. The audio is not kept.
    pub async fn voice_transcribe(&self, pcm_le: &[u8], sample_rate: u32) -> Result<Transcript> {
        let settings = self.settings()?;
        if !pcm_le.len().is_multiple_of(2) {
            return Err(AtlasError::Validation("recording data is malformed".into()));
        }
        let samples: Vec<i16> = pcm_le.chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]])).collect();
        let pcm = Pcm { sample_rate, samples };
        self.voice.transcribe(&settings, &pcm).await
    }

    pub fn voice_cancel_transcription(&self) -> bool {
        self.voice.cancel_transcription()
    }

    pub async fn voice_benchmark(&self) -> Result<BenchmarkReport> {
        let settings = self.settings()?;
        self.voice.benchmark(&settings).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn word_accuracy_is_order_aware() {
        assert_eq!(word_accuracy("Hello Atlas, call my sister", "hello atlas call my sister"), 1.0);
        assert!((word_accuracy("one two three four", "one three four") - 0.75).abs() < 1e-9);
        assert_eq!(word_accuracy("one two", ""), 0.0);
    }
}
