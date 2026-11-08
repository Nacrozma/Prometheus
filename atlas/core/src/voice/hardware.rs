//! What the computer can handle, measured locally (nothing is sent anywhere). Used to recommend a
//! speech model and to warn before a download that would not fit.

use serde::Serialize;
use std::path::Path;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct HardwareReport {
    pub os: String,
    pub arch: String,
    pub cpu: String,
    pub logical_cores: usize,
    /// x86-64 AVX2: whisper.cpp runs much faster with it.
    pub avx2: bool,
    pub total_memory_mb: u64,
    pub available_memory_mb: u64,
    /// Free space where voice files are stored.
    pub free_disk_mb: Option<u64>,
    pub recommended_stt_model: String,
    pub recommendation: String,
}

pub fn report(data_dir: Option<&Path>) -> HardwareReport {
    use sysinfo::{CpuRefreshKind, Disks, MemoryRefreshKind, RefreshKind, System};
    // System facts are best-effort: an unsupported platform reports zeros rather than failing.
    let sys = System::new_with_specifics(RefreshKind::nothing().with_memory(MemoryRefreshKind::everything()).with_cpu(CpuRefreshKind::nothing())).ok();
    let cpu = sys.as_ref().and_then(|s| s.cpus().first().map(|c| c.brand().trim().to_string())).filter(|s| !s.is_empty()).unwrap_or_else(|| "unknown CPU".into());
    let logical_cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    let total_memory_mb = sys.as_ref().map(|s| s.total_memory()).unwrap_or(0) / 1_048_576;
    let available_memory_mb = sys.as_ref().map(|s| s.available_memory()).unwrap_or(0) / 1_048_576;
    let free_disk_mb = data_dir.and_then(|dir| {
        let disks = Disks::new_with_refreshed_list().ok()?;
        disks
            .iter()
            .filter(|d| dir.starts_with(d.mount_point()))
            .max_by_key(|d| d.mount_point().as_os_str().len())
            .map(|d| d.available_space() / 1_048_576)
    });
    let avx2 = has_avx2();
    let (recommended_stt_model, recommendation) = recommend(total_memory_mb, logical_cores, avx2);
    HardwareReport {
        os: std::env::consts::OS.into(),
        arch: std::env::consts::ARCH.into(),
        cpu,
        logical_cores,
        avx2,
        total_memory_mb,
        available_memory_mb,
        free_disk_mb,
        recommended_stt_model: recommended_stt_model.into(),
        recommendation,
    }
}

#[cfg(target_arch = "x86_64")]
fn has_avx2() -> bool {
    std::is_x86_feature_detected!("avx2")
}
#[cfg(not(target_arch = "x86_64"))]
fn has_avx2() -> bool {
    false
}

/// A starting recommendation from memory and cores. The on-device benchmark in Settings → Voice
/// measures the real speed before anything is final.
pub fn recommend(total_memory_mb: u64, cores: usize, avx2: bool) -> (&'static str, String) {
    if total_memory_mb < 4_096 || cores < 2 {
        return ("stt-whisper-tiny", "This PC has little memory or few cores, so the tiny model is the safe choice.".into());
    }
    if !avx2 && cfg!(target_arch = "x86_64") {
        return ("stt-whisper-tiny", "This CPU lacks AVX2, which makes speech recognition slow; start with the tiny model.".into());
    }
    if total_memory_mb >= 16_384 && cores >= 8 {
        return ("stt-whisper-base", "Base is quick here. This PC could also run small or large-v3 turbo for better accuracy; the benchmark shows the cost.".into());
    }
    ("stt-whisper-base", "Base gives good accuracy at a comfortable speed on this PC.".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recommendations_follow_resources() {
        assert_eq!(recommend(2_048, 4, true).0, "stt-whisper-tiny");
        assert_eq!(recommend(8_192, 1, true).0, "stt-whisper-tiny");
        assert_eq!(recommend(8_192, 4, true).0, "stt-whisper-base");
        assert_eq!(recommend(32_768, 16, true).0, "stt-whisper-base");
        let r = report(None);
        assert!(r.logical_cores >= 1 && r.total_memory_mb > 0, "{r:?}");
    }
}
