//! Real-engine validation (ignored by default; runs in CI, `atlas-voice-engines.yml`).
//!
//! Downloads the genuine pinned artifacts from their public sources, verifies them, synthesises
//! speech with sherpa-onnx + a Piper voice, transcribes that speech with whisper.cpp, and writes a
//! benchmark report (and the synthesised sample) to `ATLAS_VOICE_BENCH_OUT`. No microphone or
//! speaker is involved: this proves the engines, downloads and process handling on the CI machine,
//! not the owner's audio hardware.

use atlas_core::credentials::MemorySecrets;
use atlas_core::events::RecordingBus;
use atlas_core::voice::{catalog, wav, BENCHMARK_PHRASE};
use atlas_core::{Atlas, AtlasConfig};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[tokio::test]
#[ignore = "downloads and runs the real speech engines (hundreds of MB); run in CI"]
async fn real_engines_speak_and_understand_and_report_benchmarks() {
    let keep = std::env::var("ATLAS_VOICE_BENCH_DATA").ok();
    let tmp = tempfile::tempdir().unwrap();
    let data = keep.map(std::path::PathBuf::from).unwrap_or_else(|| tmp.path().to_path_buf());
    let out = std::path::PathBuf::from(std::env::var("ATLAS_VOICE_BENCH_OUT").unwrap_or_else(|_| tmp.path().join("out").to_string_lossy().into_owned()));
    std::fs::create_dir_all(&out).unwrap();
    let a = Atlas::new(AtlasConfig {
        db_path: None,
        secrets: Arc::new(MemorySecrets::default()),
        bus: Arc::new(RecordingBus::default()),
        factory: None,
        version: "voice-bench".into(),
        data_dir: Some(data.clone()),
    })
    .unwrap();

    let models: Vec<String> = std::env::var("VOICE_BENCH_MODELS").unwrap_or_else(|_| "base".into()).split(',').map(|m| format!("stt-whisper-{}", m.trim())).collect();
    let tts_engine = catalog::engine(catalog::ArtifactKind::TtsEngine).expect("a speech output engine for this platform");
    let stt_engine = catalog::engine(catalog::ArtifactKind::SttEngine);
    let mut ids: Vec<String> = vec![tts_engine.id.into(), catalog::default_voice().id.into()];
    if let Some(e) = stt_engine {
        ids.push(e.id.into());
        ids.extend(models.iter().cloned());
    }
    let mut downloads = vec![];
    for id in &ids {
        let t = Instant::now();
        let mut last = 0u64;
        a.voice_install(id, &mut |p| {
            if let atlas_core::voice::download::Progress::Downloading { received, .. } = p {
                last = received;
            }
        })
        .await
        .unwrap_or_else(|e| panic!("install {id}: {e}"));
        assert!(a.voice_verify(id).unwrap().is_empty(), "{id} files match their hashes");
        downloads.push(serde_json::json!({"id": id, "bytes": last, "seconds": t.elapsed().as_secs_f64()}));
        println!("installed {id} ({} MB) in {:.1}s", last / 1_000_000, t.elapsed().as_secs_f64());
    }
    let status = a.voice_status().unwrap();
    assert!(status.tts_ready, "speech output ready");
    println!("hardware: {:?}", status.hardware);

    // Real synthesis: speech-like output, faster speed gives shorter audio.
    let t = Instant::now();
    let normal = wav::decode(&a.voice_synthesize(BENCHMARK_PHRASE, Some(1.0)).await.unwrap()).unwrap();
    let cold_ms = t.elapsed().as_millis();
    let t = Instant::now();
    let again = wav::decode(&a.voice_synthesize(BENCHMARK_PHRASE, Some(1.0)).await.unwrap()).unwrap();
    let warm_ms = t.elapsed().as_millis();
    let fast = wav::decode(&a.voice_synthesize(BENCHMARK_PHRASE, Some(1.5)).await.unwrap()).unwrap();
    assert!(normal.duration_ms() > 2_000 && normal.rms() > 0.02, "real speech: {} ms, rms {}", normal.duration_ms(), normal.rms());
    assert_eq!(normal.sample_rate, again.sample_rate);
    assert!(fast.duration_ms() < normal.duration_ms(), "speed 1.5 is shorter");
    std::fs::write(out.join("atlas-voice-sample.wav"), wav::encode(&normal)).unwrap();
    println!("synthesis: {} ms of audio, first call {cold_ms} ms, second {warm_ms} ms", normal.duration_ms());

    // Stopping a real synthesis is prompt and leaves no files.
    let a2 = a.clone();
    let long = "This is a long sentence that keeps going so that the engine has real work to do while we stop it. ".repeat(6);
    let h = tokio::spawn(async move { a2.voice_synthesize(&long, Some(1.0)).await });
    tokio::time::sleep(Duration::from_millis(150)).await;
    a.voice_stop_speech();
    let r = tokio::time::timeout(Duration::from_secs(5), h).await.expect("stop is prompt").unwrap();
    assert!(r.is_err(), "cancelled synthesis returns an error, not audio");
    assert_eq!(a.voice_status().unwrap().temp_audio_files, 0);

    // Real recognition of the real synthesised speech, for each installed model.
    let mut report = serde_json::json!({
        "platform": catalog::current_platform(),
        "hardware": status.hardware,
        "downloads": downloads,
        "voice": catalog::default_voice().id,
        "synthesis": {"audio_ms": normal.duration_ms(), "first_call_ms": cold_ms, "second_call_ms": warm_ms, "real_time_factor": warm_ms as f64 / normal.duration_ms() as f64},
    });
    if stt_engine.is_some() {
        assert!(status.stt_ready);
        let bench = a.voice_benchmark().await.unwrap();
        for m in &bench.models {
            println!("{}: {} ms ({:.2}× real time), {:.0}% words: \"{}\"", m.name, m.elapsed_ms, m.real_time_factor, m.word_accuracy * 100.0, m.transcript);
        }
        let base = bench.models.iter().find(|m| m.id == "stt-whisper-base").or(bench.models.first()).expect("a model ran");
        assert!(base.word_accuracy >= 0.7, "recognition understood the synthesised phrase: {base:?}");
        report["recognition"] = serde_json::to_value(&bench.models).unwrap();
        // The full round trip through the app's transcription entry point (16 kHz, raw bytes).
        let pcm16 = wav::resample(&normal, 16_000);
        let bytes: Vec<u8> = pcm16.samples.iter().flat_map(|s| s.to_le_bytes()).collect();
        let t = a.voice_transcribe(&bytes, 16_000).await.unwrap();
        assert!(!t.text.is_empty());
        report["transcribe_entry_point"] = serde_json::json!({"text": t.text, "elapsed_ms": t.elapsed_ms});
    } else {
        report["recognition"] = serde_json::json!("not available on this platform (whisper.cpp publishes Windows binaries only)");
    }
    assert_eq!(a.voice_status().unwrap().temp_audio_files, 0, "no temporary audio left behind");
    let pretty = serde_json::to_string_pretty(&report).unwrap();
    std::fs::write(out.join("voice-benchmark.json"), &pretty).unwrap();
    println!("{pretty}");
}
