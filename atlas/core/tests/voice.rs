//! Voice subsystem tests: verified installs (real download, hash check and unpacking, served by a
//! local test server), integrity checks, safety of archive contents, cancellation, offline mode,
//! the engine process wrappers (driven by small test scripts this file writes, standing in for the
//! real engines), single-flight recognition, and the test-build stand-in engines.
//! No public network access and no third-party binaries are used here.

use atlas_core::credentials::MemorySecrets;
use atlas_core::events::RecordingBus;
use atlas_core::voice::download::{self, InstallState};
use atlas_core::voice::{catalog, wav, Override};
use atlas_core::{Atlas, AtlasConfig};
use sha2::{Digest, Sha256};
use std::sync::Arc;
use std::time::Duration;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn atlas(dir: &std::path::Path) -> Arc<Atlas> {
    Atlas::new(AtlasConfig {
        db_path: None,
        secrets: Arc::new(MemorySecrets::default()),
        bus: Arc::new(RecordingBus::default()),
        factory: None,
        version: "test".into(),
        data_dir: Some(dir.to_path_buf()),
    })
    .unwrap()
}

fn sha(b: &[u8]) -> String {
    hex::encode(Sha256::digest(b))
}

/// A .tar.bz2 with the given (path, contents, mode) entries.
fn tar_bz2(entries: &[(&str, &[u8], u32)]) -> Vec<u8> {
    let enc = bzip2::write::BzEncoder::new(Vec::new(), bzip2::Compression::fast());
    let mut b = tar::Builder::new(enc);
    for (p, data, mode) in entries {
        let mut h = tar::Header::new_gnu();
        h.set_size(data.len() as u64);
        h.set_mode(*mode);
        h.set_cksum();
        b.append_data(&mut h, p, *data).unwrap();
    }
    b.into_inner().unwrap().finish().unwrap()
}

/// A tar whose single entry has a raw, unvalidated name (to model a malicious archive).
fn tar_bz2_raw_name(name: &str, kind: tar::EntryType, link: Option<&str>) -> Vec<u8> {
    let enc = bzip2::write::BzEncoder::new(Vec::new(), bzip2::Compression::fast());
    let mut b = tar::Builder::new(enc);
    let mut h = tar::Header::new_gnu();
    let gnu = h.as_gnu_mut().unwrap();
    gnu.name[..name.len()].copy_from_slice(name.as_bytes());
    h.set_entry_type(kind);
    if let Some(l) = link {
        h.set_link_name(l).unwrap();
    }
    let data: &[u8] = if kind == tar::EntryType::Regular { b"evil" } else { b"" };
    h.set_size(data.len() as u64);
    h.set_mode(0o644);
    h.set_cksum();
    b.append(&h, data).unwrap();
    b.into_inner().unwrap().finish().unwrap()
}

async fn serve(server: &MockServer, route: &str, body: Vec<u8>) {
    Mock::given(method("GET")).and(path(route)).respond_with(ResponseTemplate::new(200).set_body_bytes(body)).mount(server).await;
}

fn over(a: &Atlas, id: &str, url: String, body: &[u8]) {
    a.voice.set_override(id, Override { url, sha256: sha(body), bytes: body.len() as u64 + 2_000_000 });
}

const VOICE: &str = "voice-en_GB-alba-medium";
const MODEL: &str = "stt-whisper-base";

#[tokio::test]
async fn verified_install_unpacks_records_hashes_detects_tampering_and_removes() {
    let dir = tempfile::tempdir().unwrap();
    let a = atlas(dir.path());
    let server = MockServer::start().await;
    let body = tar_bz2(&[("v/model.onnx", b"onnx-bytes", 0o644), ("v/tokens.txt", b"a 1", 0o644), ("v/espeak-ng-data/phontab", b"x", 0o644)]);
    serve(&server, "/voice.tar.bz2", body.clone()).await;
    over(&a, VOICE, format!("{}/voice.tar.bz2", server.uri()), &body);

    let mut phases = vec![];
    let st = a.voice_install(VOICE, &mut |p| phases.push(p)).await.unwrap();
    let v = st.voices.iter().find(|v| v.artifact.id == VOICE).unwrap();
    assert_eq!(v.state, InstallState::Installed);
    assert!(matches!(phases.first(), Some(download::Progress::Downloading { .. })));
    assert!(phases.contains(&download::Progress::Verifying) && phases.contains(&download::Progress::Unpacking));
    assert_eq!(phases.last(), Some(&download::Progress::Done));
    assert!(a.voice_verify(VOICE).unwrap().is_empty(), "freshly installed files match their hashes");
    // No temporary files remain.
    assert_eq!(std::fs::read_dir(dir.path().join("voice/tmp")).unwrap().count(), 0);

    // Installing again does not download again (the server would fail a second request).
    server.reset().await;
    a.voice_install(VOICE, &mut |_| {}).await.unwrap();

    // Tampering with an installed file is detected.
    let inst = dir.path().join("voice/voices").join(VOICE);
    std::fs::write(inst.join("v/model.onnx"), b"changed").unwrap();
    assert_eq!(a.voice_verify(VOICE).unwrap(), vec!["v/model.onnx".to_string()]);

    // A missing manifest marks the install as damaged; speaking from it is refused clearly.
    std::fs::remove_file(inst.join(".atlas-manifest.json")).unwrap();
    let st = a.voice_status().unwrap();
    assert_eq!(st.voices.iter().find(|v| v.artifact.id == VOICE).unwrap().state, InstallState::Damaged);
    assert!(!st.tts_ready);

    a.voice_remove(VOICE).unwrap();
    assert!(!inst.exists());
}

#[tokio::test]
async fn a_corrupt_or_oversized_download_is_rejected_and_leaves_nothing() {
    let dir = tempfile::tempdir().unwrap();
    let a = atlas(dir.path());
    let server = MockServer::start().await;
    let good = b"model-bytes".to_vec();
    serve(&server, "/m.bin", b"tampered!!".to_vec()).await;
    // The override expects the good file's hash; the server sends something else.
    over(&a, MODEL, format!("{}/m.bin", server.uri()), &good);
    let e = a.voice_install(MODEL, &mut |_| {}).await.unwrap_err();
    assert!(e.to_string().contains("integrity check"), "{e}");
    assert!(!dir.path().join("voice/models").join(MODEL).exists());
    assert_eq!(std::fs::read_dir(dir.path().join("voice/tmp")).unwrap().count(), 0, "the partial download is deleted");

    // Larger than the catalog allows: stopped.
    let big = vec![7u8; 3_000_000];
    serve(&server, "/big.bin", big.clone()).await;
    a.voice.set_override(MODEL, Override { url: format!("{}/big.bin", server.uri()), sha256: sha(&big), bytes: 10 });
    let e = a.voice_install(MODEL, &mut |_| {}).await.unwrap_err();
    assert!(e.to_string().contains("larger than expected"), "{e}");
    assert_eq!(std::fs::read_dir(dir.path().join("voice/tmp")).unwrap().count(), 0);
}

#[tokio::test]
async fn archives_cannot_write_outside_their_folder_or_contain_links() {
    let dir = tempfile::tempdir().unwrap();
    let a = atlas(dir.path());
    let server = MockServer::start().await;
    for (i, body) in [
        tar_bz2_raw_name("../escape.txt", tar::EntryType::Regular, None),
        tar_bz2_raw_name("/abs.txt", tar::EntryType::Regular, None),
        tar_bz2_raw_name("link", tar::EntryType::Symlink, Some("/etc/passwd")),
    ]
    .into_iter()
    .enumerate()
    {
        let route = format!("/bad{i}.tar.bz2");
        serve(&server, &route, body.clone()).await;
        over(&a, VOICE, format!("{}{route}", server.uri()), &body);
        let e = a.voice_install(VOICE, &mut |_| {}).await.unwrap_err();
        assert!(e.to_string().contains("refused"), "case {i}: {e}");
        assert!(!dir.path().join("voice/escape.txt").exists() && !dir.path().join("escape.txt").exists());
        assert!(!dir.path().join("voice/voices").join(VOICE).exists(), "case {i}: nothing installed");
        assert!(!dir.path().join("voice/voices").join(format!("{VOICE}.staging")).exists(), "case {i}: staging removed");
    }
}

#[tokio::test]
async fn cancelling_a_download_stops_it_and_cleans_up() {
    let dir = tempfile::tempdir().unwrap();
    let a = atlas(dir.path());
    let server = MockServer::start().await;
    let body = vec![1u8; 1_000_000];
    Mock::given(method("GET"))
        .and(path("/slow.bin"))
        .respond_with(ResponseTemplate::new(200).set_body_bytes(body.clone()).set_delay(Duration::from_secs(5)))
        .mount(&server)
        .await;
    over(&a, MODEL, format!("{}/slow.bin", server.uri()), &body);
    let a2 = a.clone();
    let h = tokio::spawn(async move { a2.voice_install(MODEL, &mut |_| {}).await });
    tokio::time::sleep(Duration::from_millis(300)).await;
    // A second download of the same file is refused while the first runs.
    let e = a.voice_install(MODEL, &mut |_| {}).await.unwrap_err();
    assert_eq!(e.code(), "conflict");
    assert!(a.voice_cancel_install(MODEL));
    let r = tokio::time::timeout(Duration::from_secs(3), h).await.expect("cancel is prompt").unwrap();
    assert_eq!(r.unwrap_err().code(), "cancelled");
    assert!(!dir.path().join("voice/models").join(MODEL).exists());
    assert_eq!(std::fs::read_dir(dir.path().join("voice/tmp")).unwrap().count(), 0);
}

#[tokio::test]
async fn offline_mode_refuses_downloads_but_settings_validate() {
    let dir = tempfile::tempdir().unwrap();
    let a = atlas(dir.path());
    let mut s = a.settings().unwrap();
    s.network.offline_mode = true;
    a.update_settings(s.clone()).unwrap();
    let e = a.voice_install(MODEL, &mut |_| {}).await.unwrap_err();
    assert_eq!(e.code(), "permission_denied");
    assert!(e.to_string().contains("offline mode"));

    // Voice settings are validated in the core.
    s.network.offline_mode = false;
    s.voice.speed = 3.0;
    assert!(a.update_settings(s.clone()).is_err());
    s.voice.speed = 1.25;
    s.voice.tts_voice = Some("stt-whisper-base".into()); // a model is not a voice
    assert!(a.update_settings(s.clone()).is_err());
    s.voice.tts_voice = Some(VOICE.into());
    s.voice.language = "en US; rm".into();
    assert!(a.update_settings(s.clone()).is_err());
    s.voice.language = "ar".into();
    s.voice.stt_model = Some("stt-whisper-small".into());
    let saved = a.update_settings(s).unwrap();
    assert_eq!(saved.voice.stt_model.as_deref(), Some("stt-whisper-small"));
    // Unknown downloads are refused.
    assert_eq!(a.voice_install("nope", &mut |_| {}).await.unwrap_err().code(), "not_found");
}

#[tokio::test]
async fn stand_in_engines_for_test_builds_speak_and_transcribe_and_say_so() {
    let dir = tempfile::tempdir().unwrap();
    let a = atlas(dir.path());
    assert!(!a.voice_status().unwrap().tts_ready, "nothing installed, so speech output is not ready");
    assert_eq!(a.voice_synthesize("Hello", None).await.unwrap_err().code(), "not_found");
    a.voice.use_fixtures(true);
    let st = a.voice_status().unwrap();
    assert!(st.fixtures && st.tts_ready && st.stt_ready);
    let wav_bytes = a.voice_synthesize("Hello there, this is Atlas.", Some(1.0)).await.unwrap();
    let pcm = wav::decode(&wav_bytes).unwrap();
    assert!(pcm.duration_ms() > 500 && pcm.rms() > 0.05);
    let pcm16: Vec<u8> = wav::resample(&pcm, 16_000).samples.iter().flat_map(|s| s.to_le_bytes()).collect();
    let t = a.voice_transcribe(&pcm16, 16_000).await.unwrap();
    assert_eq!(t.text, "What is 6 times 7?");
    assert!(t.engine.contains("fixture"));
    // Silence is not turned into words.
    let silent = vec![0u8; 16_000 * 2];
    assert_eq!(a.voice_transcribe(&silent, 16_000).await.unwrap().text, "");
    let report = a.voice_benchmark().await.unwrap();
    assert!(report.fixtures && report.audio_ms > 0 && report.models.len() == 1);
    assert_eq!(a.voice_status().unwrap().temp_audio_files, 0);
}

#[cfg(unix)]
mod engines {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    /// Install a stand-in engine (a shell script) through the real download path.
    async fn install_script(a: &Atlas, server: &MockServer, id: &str, name: &str, script: &str) {
        let body = tar_bz2(&[(&format!("pkg/bin/{name}"), script.as_bytes(), 0o755), ("pkg/lib/README", b"libs", 0o644)]);
        let route = format!("/{id}.tar.bz2");
        serve(server, &route, body.clone()).await;
        over(a, id, format!("{}{route}", server.uri()), &body);
        a.voice_install(id, &mut |_| {}).await.unwrap();
    }

    fn tts_engine_id() -> &'static str {
        catalog::engine(catalog::ArtifactKind::TtsEngine).expect("linux has a TTS engine entry").id
    }

    #[tokio::test]
    async fn speech_output_runs_the_engine_with_exact_arguments_and_cleans_up() {
        if catalog::current_platform() != "linux-x86_64" {
            return;
        }
        let dir = tempfile::tempdir().unwrap();
        let a = atlas(dir.path());
        let server = MockServer::start().await;
        let fixture_wav = dir.path().join("fixture.wav");
        std::fs::write(&fixture_wav, wav::encode(&atlas_core::voice::tts::fixture_audio("one two three", 1.0))).unwrap();
        let args_log = dir.path().join("args.txt");
        // Records its arguments, then writes the WAV where it was told to.
        let script = format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\nfor a in \"$@\"; do case \"$a\" in --output-filename=*) cp {wav} \"${{a#--output-filename=}}\";; esac; done\n",
            log = args_log.display(),
            wav = fixture_wav.display()
        );
        install_script(&a, &server, tts_engine_id(), "sherpa-onnx-offline-tts", &script).await;
        let voice = tar_bz2(&[("v/voice.onnx", b"m", 0o644), ("v/tokens.txt", b"t", 0o644), ("v/espeak-ng-data/x", b"d", 0o644)]);
        serve(&server, "/voice.tar.bz2", voice.clone()).await;
        over(&a, VOICE, format!("{}/voice.tar.bz2", server.uri()), &voice);
        a.voice_install(VOICE, &mut |_| {}).await.unwrap();
        assert!(a.voice_status().unwrap().tts_ready);

        let out = a.voice_synthesize("-- Hello, I'm Atlas.", Some(2.0)).await.unwrap();
        assert!(wav::decode(&out).unwrap().duration_ms() > 300);
        let args = std::fs::read_to_string(&args_log).unwrap();
        assert!(args.contains("--vits-model=") && args.contains("voice.onnx") && args.contains("--vits-tokens=") && args.contains("--vits-data-dir="), "{args}");
        assert!(args.contains("--vits-length-scale=0.500"), "speed 2 → length scale 0.5: {args}");
        assert_eq!(args.lines().last().unwrap(), "Hello, I'm Atlas.", "text is the last argument, never an option");
        assert_eq!(a.voice_status().unwrap().temp_audio_files, 0, "the engine's WAV is deleted after reading");
    }

    #[tokio::test]
    async fn a_hung_engine_is_stopped_on_request_and_a_failing_one_reports_an_error() {
        if catalog::current_platform() != "linux-x86_64" {
            return;
        }
        let dir = tempfile::tempdir().unwrap();
        let a = atlas(dir.path());
        let server = MockServer::start().await;
        install_script(&a, &server, tts_engine_id(), "sherpa-onnx-offline-tts", "#!/bin/sh\nsleep 30\n").await;
        let voice = tar_bz2(&[("v/voice.onnx", b"m", 0o644), ("v/tokens.txt", b"t", 0o644), ("v/espeak-ng-data/x", b"d", 0o644)]);
        serve(&server, "/voice.tar.bz2", voice.clone()).await;
        over(&a, VOICE, format!("{}/voice.tar.bz2", server.uri()), &voice);
        a.voice_install(VOICE, &mut |_| {}).await.unwrap();
        let a2 = a.clone();
        let h = tokio::spawn(async move { a2.voice_synthesize("Long sentence", None).await });
        tokio::time::sleep(Duration::from_millis(300)).await;
        a.voice_stop_speech();
        let r = tokio::time::timeout(Duration::from_secs(5), h).await.expect("stop is prompt").unwrap();
        assert_eq!(r.unwrap_err().code(), "cancelled");
        assert_eq!(a.voice_status().unwrap().temp_audio_files, 0);

        // Replace the engine script with one that fails.
        let bin = download::find_file(&dir.path().join("voice/engines").join(tts_engine_id()), "sherpa-onnx-offline-tts").unwrap();
        std::fs::write(&bin, "#!/bin/sh\necho 'model load failed' >&2\nexit 3\n").unwrap();
        std::fs::set_permissions(&bin, std::fs::Permissions::from_mode(0o755)).unwrap();
        let e = a.voice_synthesize("Hello", None).await.unwrap_err();
        assert!(e.to_string().contains("model load failed"), "{e}");
    }
}

#[test]
fn whisper_arguments_are_fixed_and_bounded() {
    let dir = tempfile::tempdir().unwrap();
    let engine = dir.path().join("engine");
    std::fs::create_dir_all(engine.join("Release")).unwrap();
    let exe = if cfg!(windows) { "whisper-cli.exe" } else { "whisper-cli" };
    std::fs::write(engine.join("Release").join(exe), b"").unwrap();
    let model = dir.path().join("ggml-base.bin");
    std::fs::write(&model, b"m").unwrap();
    let w = atlas_core::voice::stt::WhisperCli::locate(&engine, &model, &dir.path().join("tmp"), "base").unwrap();
    let args = w.args(std::path::Path::new("in.wav"), "en-GB");
    assert_eq!(&args[1..7], &["-m".to_string(), model.to_string_lossy().into_owned(), "-f".into(), "in.wav".into(), "-l".into(), "en".into()]);
    assert!(args.contains(&"-nt".to_string()) && args.contains(&"-np".to_string()));
}
