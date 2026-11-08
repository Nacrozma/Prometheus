//! Every voice download Atlas knows about: the exact HTTPS URL, its published SHA-256, approximate
//! size, licence and source. Nothing outside this list is ever downloaded, and nothing is used
//! until its hash matches. Hashes come from the publishers' own listings (GitHub release digests for
//! the engines and Piper voices, Hugging Face LFS hashes for the Whisper models).

use serde::Serialize;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactKind {
    /// Text-to-speech runtime (sherpa-onnx).
    TtsEngine,
    /// Speech-recognition runtime (whisper.cpp).
    SttEngine,
    /// A Piper voice (VITS, run by sherpa-onnx).
    Voice,
    /// A Whisper model (ggml, run by whisper.cpp).
    SttModel,
}

impl ArtifactKind {
    pub fn dir(self) -> &'static str {
        match self {
            ArtifactKind::TtsEngine | ArtifactKind::SttEngine => "engines",
            ArtifactKind::Voice => "voices",
            ArtifactKind::SttModel => "models",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Archive {
    TarBz2,
    Zip,
    /// A single file, kept under `file_name`.
    File,
}

#[derive(Debug, Clone, Serialize)]
pub struct Artifact {
    pub id: &'static str,
    pub kind: ArtifactKind,
    pub name: &'static str,
    pub description: &'static str,
    pub url: &'static str,
    pub sha256: &'static str,
    /// Approximate download size in bytes (shown before downloading; also bounds the download).
    pub bytes: u64,
    pub archive: Archive,
    /// For `Archive::File`: the name the file is stored under.
    pub file_name: &'static str,
    /// `None`: any platform. Otherwise `"windows-x86_64"` or `"linux-x86_64"`.
    pub platform: Option<&'static str>,
    pub language: Option<&'static str>,
    pub license: &'static str,
    pub license_url: &'static str,
    pub source: &'static str,
    pub recommended: bool,
    /// Relative speed/accuracy note shown in Settings.
    pub note: &'static str,
}

const MIB: u64 = 1_048_576;

/// The pinned catalog. Order matters only for display.
pub static CATALOG: &[Artifact] = &[
    // ---------- engines ----------
    Artifact {
        id: "tts-engine-sherpa-onnx-2.0.1-windows",
        kind: ArtifactKind::TtsEngine,
        name: "sherpa-onnx 2.0.1 (speech output engine)",
        description: "Runs Piper voices on your computer. Maintained, CPU-only; no GPU needed.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-v2.0.1-win-x64-shared-MT-Release.tar.bz2",
        sha256: "dc703575a68594435f53dec93df775ff4913af851a196c0537163f21d8d2364e",
        bytes: 254 * MIB / 10,
        archive: Archive::TarBz2,
        file_name: "",
        platform: Some("windows-x86_64"),
        language: None,
        license: "Apache-2.0 (sherpa-onnx, onnxruntime: MIT; espeak-ng data: GPL-3.0, used as a separate program)",
        license_url: "https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE",
        source: "https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1",
        recommended: true,
        note: "",
    },
    Artifact {
        id: "tts-engine-sherpa-onnx-2.0.1-linux",
        kind: ArtifactKind::TtsEngine,
        name: "sherpa-onnx 2.0.1 (speech output engine)",
        description: "Runs Piper voices on your computer. Maintained, CPU-only; no GPU needed.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-v2.0.1-linux-x64-shared.tar.bz2",
        sha256: "2e823376987c3b6960d50726b6560155e2ad92da0b8b3886325773225ec6bdec",
        bytes: 28_003_506,
        archive: Archive::TarBz2,
        file_name: "",
        platform: Some("linux-x86_64"),
        language: None,
        license: "Apache-2.0 (sherpa-onnx, onnxruntime: MIT; espeak-ng data: GPL-3.0, used as a separate program)",
        license_url: "https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE",
        source: "https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1",
        recommended: true,
        note: "",
    },
    Artifact {
        id: "stt-engine-whisper-cpp-1.8.2-windows",
        kind: ArtifactKind::SttEngine,
        name: "whisper.cpp 1.8.2 (speech recognition engine)",
        description: "Transcribes your speech on your computer. CPU build; no GPU needed.",
        url: "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.2/whisper-bin-x64.zip",
        sha256: "b1514ebc099765e39fa37eb780b92a140a94c86bb0b3b3d98226b38825979732",
        bytes: 365 * MIB / 100,
        archive: Archive::Zip,
        file_name: "",
        platform: Some("windows-x86_64"),
        language: None,
        license: "MIT",
        license_url: "https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE",
        source: "https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.2",
        recommended: true,
        note: "The newest whisper.cpp release that ships Windows binaries (1.9.x releases are source-only).",
    },
    // ---------- voices (Piper VITS, packaged for sherpa-onnx) ----------
    Artifact {
        id: "voice-en_GB-alba-medium",
        kind: ArtifactKind::Voice,
        name: "Alba (English, UK)",
        description: "Clear Scottish-English female voice. The default: its licence is the most permissive.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_GB-alba-medium.tar.bz2",
        sha256: "fcd45962906933eec4431d3688f7d74aaac8713c87c6717f91fd3b23463aa1a1",
        bytes: 641 * MIB / 10,
        archive: Archive::TarBz2,
        file_name: "",
        platform: None,
        language: Some("en-GB"),
        license: "CC BY 4.0 (dataset); Piper voice by Rhasspy",
        license_url: "https://creativecommons.org/licenses/by/4.0/",
        source: "https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_GB/alba/medium",
        recommended: true,
        note: "Medium quality, 22 kHz",
    },
    Artifact {
        id: "voice-en_US-lessac-medium",
        kind: ArtifactKind::Voice,
        name: "Lessac (English, US)",
        description: "Warm, expressive US-English female voice, often rated among the most natural Piper voices.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-lessac-medium.tar.bz2",
        sha256: "9e3febfacf0abf4270172d2958bcec246032b7e88efc2720840cc80c93de334e",
        bytes: 641 * MIB / 10,
        archive: Archive::TarBz2,
        file_name: "",
        platform: None,
        language: Some("en-US"),
        license: "Blizzard 2013 Lessac dataset licence (non-commercial research terms); Piper voice by Rhasspy",
        license_url: "https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html",
        source: "https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium",
        recommended: false,
        note: "Medium quality, 22 kHz",
    },
    Artifact {
        id: "voice-en_US-lessac-medium-int8",
        kind: ArtifactKind::Voice,
        name: "Lessac, light (English, US)",
        description: "The Lessac voice quantised to 8-bit: a third of the size and faster on older PCs, slightly less smooth.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-lessac-medium-int8.tar.bz2",
        sha256: "f1c6d0295cf16087b05f80fdca5b44daca5cd78e2c425d419a42ba34929805f9",
        bytes: 20_969_179,
        archive: Archive::TarBz2,
        file_name: "",
        platform: None,
        language: Some("en-US"),
        license: "Blizzard 2013 Lessac dataset licence (non-commercial research terms); Piper voice by Rhasspy",
        license_url: "https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html",
        source: "https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium",
        recommended: false,
        note: "For weaker hardware",
    },
    Artifact {
        id: "voice-en_US-ryan-medium",
        kind: ArtifactKind::Voice,
        name: "Ryan (English, US)",
        description: "Calm US-English male voice.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-ryan-medium.tar.bz2",
        sha256: "c546af78b6395b4e7c4ce1ed899438b64426a362f5d4ec5fecd090ded9ad7505",
        bytes: 641 * MIB / 10,
        archive: Archive::TarBz2,
        file_name: "",
        platform: None,
        language: Some("en-US"),
        license: "CC BY-NC-SA 4.0 (RyanSpeech dataset); Piper voice by Rhasspy",
        license_url: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        source: "https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/medium",
        recommended: false,
        note: "Medium quality, 22 kHz",
    },
    Artifact {
        id: "voice-ar_JO-kareem-medium",
        kind: ArtifactKind::Voice,
        name: "Kareem (Arabic, Jordan)",
        description: "Arabic male voice.",
        url: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-ar_JO-kareem-medium.tar.bz2",
        sha256: "9ebbcea30e0fbd588f7b2cb45ee897d6aeb1bf5791cbc037a7b5a3f641e3dbce",
        bytes: 641 * MIB / 10,
        archive: Archive::TarBz2,
        file_name: "",
        platform: None,
        language: Some("ar"),
        license: "See the dataset's terms (arabicttstrain); Piper voice by Rhasspy",
        license_url: "https://github.com/AliMokhammad/arabicttstrain/",
        source: "https://huggingface.co/rhasspy/piper-voices/tree/main/ar/ar_JO/kareem/medium",
        recommended: false,
        note: "Medium quality, 22 kHz",
    },
    // ---------- Whisper models (ggml) ----------
    Artifact {
        id: "stt-whisper-tiny",
        kind: ArtifactKind::SttModel,
        name: "Whisper tiny (multilingual)",
        description: "Fastest and smallest; makes noticeably more mistakes.",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        sha256: "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
        bytes: 77_691_713,
        archive: Archive::File,
        file_name: "ggml-tiny.bin",
        platform: None,
        language: None,
        license: "MIT (OpenAI Whisper weights, ggml conversion by whisper.cpp)",
        license_url: "https://github.com/openai/whisper/blob/main/LICENSE",
        source: "https://huggingface.co/ggerganov/whisper.cpp",
        recommended: false,
        note: "For low-memory PCs",
    },
    Artifact {
        id: "stt-whisper-base",
        kind: ArtifactKind::SttModel,
        name: "Whisper base (multilingual)",
        description: "Good everyday accuracy and quick on most PCs. The starting recommendation.",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        sha256: "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
        bytes: 147_951_465,
        archive: Archive::File,
        file_name: "ggml-base.bin",
        platform: None,
        language: None,
        license: "MIT (OpenAI Whisper weights, ggml conversion by whisper.cpp)",
        license_url: "https://github.com/openai/whisper/blob/main/LICENSE",
        source: "https://huggingface.co/ggerganov/whisper.cpp",
        recommended: true,
        note: "Recommended starting point",
    },
    Artifact {
        id: "stt-whisper-small",
        kind: ArtifactKind::SttModel,
        name: "Whisper small (multilingual)",
        description: "Clearly more accurate than base, about three times slower.",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        sha256: "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
        bytes: 487_601_967,
        archive: Archive::File,
        file_name: "ggml-small.bin",
        platform: None,
        language: None,
        license: "MIT (OpenAI Whisper weights, ggml conversion by whisper.cpp)",
        license_url: "https://github.com/openai/whisper/blob/main/LICENSE",
        source: "https://huggingface.co/ggerganov/whisper.cpp",
        recommended: false,
        note: "Needs 8 GB RAM or more",
    },
    Artifact {
        id: "stt-whisper-large-v3-turbo-q5",
        kind: ArtifactKind::SttModel,
        name: "Whisper large-v3 turbo, compressed (multilingual)",
        description: "Near-best accuracy for its size. Slow on older CPUs.",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
        sha256: "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
        bytes: 574_041_195,
        archive: Archive::File,
        file_name: "ggml-large-v3-turbo-q5_0.bin",
        platform: None,
        language: None,
        license: "MIT (OpenAI Whisper weights, ggml conversion by whisper.cpp)",
        license_url: "https://github.com/openai/whisper/blob/main/LICENSE",
        source: "https://huggingface.co/ggerganov/whisper.cpp",
        recommended: false,
        note: "Needs 16 GB RAM and a recent CPU",
    },
];

/// `"windows-x86_64"`, `"linux-x86_64"`, or something unsupported.
pub fn current_platform() -> String {
    format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH)
}

pub fn get(id: &str) -> Option<&'static Artifact> {
    CATALOG.iter().find(|a| a.id == id)
}

/// Artifacts usable on this platform.
pub fn available() -> impl Iterator<Item = &'static Artifact> {
    let p = current_platform();
    CATALOG.iter().filter(move |a| a.platform.is_none_or(|x| x == p))
}

/// The engine of a kind for this platform, if one is published.
pub fn engine(kind: ArtifactKind) -> Option<&'static Artifact> {
    available().find(|a| a.kind == kind)
}

pub fn default_voice() -> &'static Artifact {
    CATALOG.iter().find(|a| a.kind == ArtifactKind::Voice && a.recommended).expect("a recommended voice")
}

pub fn default_stt_model() -> &'static Artifact {
    CATALOG.iter().find(|a| a.kind == ArtifactKind::SttModel && a.recommended).expect("a recommended model")
}

/// Largest download accepted for an artifact (its listed size plus a margin).
pub fn max_download(a: &Artifact) -> u64 {
    a.bytes + a.bytes / 10 + 2 * MIB
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_entry_is_pinned_to_https_on_a_known_host_with_a_sha256() {
        let mut ids = std::collections::HashSet::new();
        for a in CATALOG {
            assert!(ids.insert(a.id), "duplicate id {}", a.id);
            assert!(a.url.starts_with("https://github.com/") || a.url.starts_with("https://huggingface.co/"), "{}", a.url);
            assert_eq!(a.sha256.len(), 64, "{}", a.id);
            assert!(a.sha256.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()), "{}", a.id);
            assert!(a.bytes > 1_000_000, "{}", a.id);
            assert!(!a.license.is_empty() && a.license_url.starts_with("https://"), "{}", a.id);
            if a.archive == Archive::File {
                assert!(!a.file_name.is_empty() && !a.file_name.contains(['/', '\\']), "{}", a.id);
            }
            assert!(a.id.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c)), "{}", a.id);
        }
    }

    #[test]
    fn defaults_and_engines_exist() {
        assert_eq!(default_voice().id, "voice-en_GB-alba-medium");
        assert_eq!(default_stt_model().id, "stt-whisper-base");
        assert!(CATALOG.iter().any(|a| a.kind == ArtifactKind::TtsEngine && a.platform == Some("windows-x86_64")));
        assert!(CATALOG.iter().any(|a| a.kind == ArtifactKind::SttEngine && a.platform == Some("windows-x86_64")));
        assert!(max_download(default_stt_model()) > default_stt_model().bytes);
    }
}
