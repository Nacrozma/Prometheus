//! Verified installs of catalog artifacts.
//!
//! A download streams to `<root>/tmp/<id>.part`, hashing as it goes and refusing anything larger
//! than the catalog allows. Only when the SHA-256 matches is it unpacked, into a staging folder,
//! with every path checked to stay inside it (no absolute paths, no `..`, no links). The staging
//! folder then replaces the install atomically, with a manifest of every file's own hash so a
//! later "verify" can detect tampering or corruption. A cancelled or failed download leaves
//! nothing behind.

use crate::error::{AtlasError, Result};
use crate::voice::catalog::{max_download, Archive, Artifact};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

/// Most files an archive may contain, and most bytes it may unpack to.
const MAX_FILES: usize = 5_000;
const MAX_UNPACKED: u64 = 4 * 1024 * 1024 * 1024;
const MANIFEST: &str = ".atlas-manifest.json";

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum Progress {
    Downloading { received: u64, total: Option<u64> },
    Verifying,
    Unpacking,
    Done,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Manifest {
    pub id: String,
    pub sha256: String,
    pub url: String,
    pub installed_at: String,
    /// Relative path → SHA-256 of every installed file.
    pub files: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum InstallState {
    NotInstalled,
    Installed,
    /// Files are present but the manifest is missing, unreadable or for another version.
    Damaged,
}

pub fn install_dir(root: &Path, a: &Artifact) -> PathBuf {
    root.join(a.kind.dir()).join(a.id)
}

pub fn read_manifest(root: &Path, a: &Artifact) -> Option<Manifest> {
    let raw = std::fs::read_to_string(install_dir(root, a).join(MANIFEST)).ok()?;
    serde_json::from_str(&raw).ok()
}

pub fn state(root: &Path, a: &Artifact) -> InstallState {
    let dir = install_dir(root, a);
    if !dir.exists() {
        return InstallState::NotInstalled;
    }
    match read_manifest(root, a) {
        Some(m) if m.sha256 == a.sha256 && m.id == a.id && !m.files.is_empty() => InstallState::Installed,
        _ => InstallState::Damaged,
    }
}

/// Re-hash every installed file against the manifest. Returns the files that differ or are missing.
pub fn verify(root: &Path, a: &Artifact) -> Result<Vec<String>> {
    let m = read_manifest(root, a).ok_or_else(|| AtlasError::NotFound(format!("{} is not installed", a.name)))?;
    let dir = install_dir(root, a);
    let mut bad = Vec::new();
    for (rel, want) in &m.files {
        match hash_file(&dir.join(rel)) {
            Ok(h) if &h == want => {}
            _ => bad.push(rel.clone()),
        }
    }
    Ok(bad)
}

pub fn remove(root: &Path, a: &Artifact) -> Result<()> {
    let dir = install_dir(root, a);
    if dir.starts_with(root) && dir.exists() {
        std::fs::remove_dir_all(&dir).map_err(|e| AtlasError::Io(format!("could not remove {}: {e}", a.name)))?;
    }
    Ok(())
}

fn hash_file(p: &Path) -> std::io::Result<String> {
    let mut f = std::fs::File::open(p)?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex::encode(h.finalize()))
}

/// Download, verify and unpack `a` under `root` (from `url`, normally the catalog URL; tests point it
/// at a local server). Returns the install folder. Already installed and intact: returns at once.
pub async fn install(
    client: &reqwest::Client,
    a: &Artifact,
    url: &str,
    root: &Path,
    cancel: &CancellationToken,
    on: &mut (dyn FnMut(Progress) + Send),
) -> Result<PathBuf> {
    let dir = install_dir(root, a);
    if state(root, a) == InstallState::Installed {
        on(Progress::Done);
        return Ok(dir);
    }
    let tmp = root.join("tmp");
    std::fs::create_dir_all(&tmp).map_err(|e| AtlasError::Io(e.to_string()))?;
    let part = tmp.join(format!("{}.part", a.id));
    let result = download_to(client, a, url, &part, cancel, on).await;
    if let Err(e) = result {
        let _ = std::fs::remove_file(&part);
        return Err(e);
    }
    on(Progress::Unpacking);
    let staging = root.join(a.kind.dir()).join(format!("{}.staging", a.id));
    let _ = std::fs::remove_dir_all(&staging);
    let unpacked = {
        let (part, staging, a) = (part.clone(), staging.clone(), a.clone());
        tokio::task::spawn_blocking(move || unpack(&a, &part, &staging)).await.map_err(|e| AtlasError::Internal(e.to_string()))?
    };
    let _ = std::fs::remove_file(&part);
    let files = match unpacked {
        Ok(f) => f,
        Err(e) => {
            let _ = std::fs::remove_dir_all(&staging);
            return Err(e);
        }
    };
    let manifest = Manifest { id: a.id.into(), sha256: a.sha256.into(), url: url.into(), installed_at: crate::storage::now(), files };
    std::fs::write(staging.join(MANIFEST), serde_json::to_vec_pretty(&manifest)?).map_err(|e| AtlasError::Io(e.to_string()))?;
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::rename(&staging, &dir).map_err(|e| AtlasError::Io(format!("could not finish installing {}: {e}", a.name)))?;
    on(Progress::Done);
    Ok(dir)
}

async fn download_to(
    client: &reqwest::Client,
    a: &Artifact,
    url: &str,
    part: &Path,
    cancel: &CancellationToken,
    on: &mut (dyn FnMut(Progress) + Send),
) -> Result<()> {
    let cap = max_download(a);
    let resp = tokio::select! {
        r = client.get(url).send() => r.map_err(|e| AtlasError::Io(format!("could not reach the download server for {}: {}", a.name, crate::redact::redact(&e.to_string()))))?,
        _ = cancel.cancelled() => return Err(AtlasError::Cancelled),
    };
    if !resp.status().is_success() {
        return Err(AtlasError::Io(format!("the download server answered {} for {}", resp.status().as_u16(), a.name)));
    }
    let total = resp.content_length();
    if total.is_some_and(|t| t > cap) {
        return Err(AtlasError::Validation(format!("{} is larger than expected; not downloading it", a.name)));
    }
    let mut file = std::fs::File::create(part).map_err(|e| AtlasError::Io(e.to_string()))?;
    let mut hasher = Sha256::new();
    let mut received: u64 = 0;
    let mut stream = resp.bytes_stream();
    let mut last_report = 0u64;
    on(Progress::Downloading { received: 0, total });
    loop {
        let next = tokio::select! {
            c = tokio::time::timeout(Duration::from_secs(60), stream.next()) => c,
            _ = cancel.cancelled() => return Err(AtlasError::Cancelled),
        };
        let chunk = match next {
            Err(_) => return Err(AtlasError::Io(format!("the download of {} stalled", a.name))),
            Ok(None) => break,
            Ok(Some(Err(e))) => return Err(AtlasError::Io(format!("the download of {} was interrupted: {}", a.name, crate::redact::redact(&e.to_string())))),
            Ok(Some(Ok(c))) => c,
        };
        received += chunk.len() as u64;
        if received > cap {
            return Err(AtlasError::Validation(format!("{} is larger than expected; stopped the download", a.name)));
        }
        hasher.update(&chunk);
        file.write_all(&chunk).map_err(|e| AtlasError::Io(format!("could not save {}: {e}", a.name)))?;
        if received - last_report >= 256 * 1024 {
            last_report = received;
            on(Progress::Downloading { received, total });
        }
    }
    file.flush().map_err(|e| AtlasError::Io(e.to_string()))?;
    drop(file);
    on(Progress::Downloading { received, total });
    on(Progress::Verifying);
    let got = hex::encode(hasher.finalize());
    if got != a.sha256 {
        return Err(AtlasError::Validation(format!(
            "{} failed its integrity check (the file is not the one Atlas expects), so it was deleted. Try again later.",
            a.name
        )));
    }
    Ok(())
}

/// A path from an archive, made relative and checked to stay inside the destination.
fn contained(dest: &Path, entry: &Path) -> Result<PathBuf> {
    let mut out = PathBuf::new();
    for c in entry.components() {
        match c {
            Component::Normal(p) => out.push(p),
            Component::CurDir => {}
            _ => return Err(AtlasError::Validation(format!("the archive contains an unsafe path ({}); refused", entry.display()))),
        }
    }
    if out.as_os_str().is_empty() {
        return Err(AtlasError::Validation("the archive contains an empty path; refused".into()));
    }
    Ok(dest.join(out))
}

/// Unpack into `staging` and return the manifest of installed files.
fn unpack(a: &Artifact, archive: &Path, staging: &Path) -> Result<BTreeMap<String, String>> {
    std::fs::create_dir_all(staging).map_err(|e| AtlasError::Io(e.to_string()))?;
    let mut written: Vec<PathBuf> = Vec::new();
    let mut total: u64 = 0;
    let mut account = |n: u64, written_len: usize| -> Result<()> {
        total += n;
        if total > MAX_UNPACKED || written_len > MAX_FILES {
            return Err(AtlasError::Validation("the archive unpacks to more than Atlas allows; refused".into()));
        }
        Ok(())
    };
    match a.archive {
        Archive::File => {
            let to = staging.join(a.file_name);
            std::fs::copy(archive, &to).map_err(|e| AtlasError::Io(e.to_string()))?;
            written.push(to);
        }
        Archive::TarBz2 => {
            let f = std::fs::File::open(archive).map_err(|e| AtlasError::Io(e.to_string()))?;
            let mut t = tar::Archive::new(bzip2::read::BzDecoder::new(f));
            for entry in t.entries().map_err(|e| AtlasError::Validation(format!("unreadable archive: {e}")))? {
                let mut entry = entry.map_err(|e| AtlasError::Validation(format!("unreadable archive: {e}")))?;
                let kind = entry.header().entry_type();
                let rel = entry.path().map_err(|e| AtlasError::Validation(e.to_string()))?.into_owned();
                let to = contained(staging, &rel)?;
                if kind.is_dir() {
                    std::fs::create_dir_all(&to).map_err(|e| AtlasError::Io(e.to_string()))?;
                } else if kind.is_file() {
                    if let Some(parent) = to.parent() {
                        std::fs::create_dir_all(parent).map_err(|e| AtlasError::Io(e.to_string()))?;
                    }
                    let mut out = std::fs::File::create(&to).map_err(|e| AtlasError::Io(e.to_string()))?;
                    let n = std::io::copy(&mut entry, &mut out).map_err(|e| AtlasError::Io(e.to_string()))?;
                    #[cfg(unix)]
                    if let Ok(mode) = entry.header().mode() {
                        use std::os::unix::fs::PermissionsExt;
                        let _ = std::fs::set_permissions(&to, std::fs::Permissions::from_mode(mode & 0o755));
                    }
                    written.push(to);
                    account(n, written.len())?;
                } else if kind.is_symlink() || kind.is_hard_link() {
                    return Err(AtlasError::Validation(format!("the archive contains a link ({}); refused", rel.display())));
                }
                // Other entry types (PAX headers and the like) carry no files.
            }
        }
        Archive::Zip => {
            let f = std::fs::File::open(archive).map_err(|e| AtlasError::Io(e.to_string()))?;
            let mut z = zip::ZipArchive::new(f).map_err(|e| AtlasError::Validation(format!("unreadable archive: {e}")))?;
            if z.len() > MAX_FILES {
                return Err(AtlasError::Validation("the archive has more files than Atlas allows; refused".into()));
            }
            for i in 0..z.len() {
                let mut file = z.by_index(i).map_err(|e| AtlasError::Validation(format!("unreadable archive: {e}")))?;
                let shown = file.name().map(|n| n.to_string()).unwrap_or_default();
                let rel = file.enclosed_name().ok_or_else(|| AtlasError::Validation(format!("the archive contains an unsafe path ({shown}); refused")))?;
                let to = contained(staging, &rel)?;
                if file.is_symlink() {
                    return Err(AtlasError::Validation(format!("the archive contains a link ({}); refused", rel.display())));
                }
                if file.is_dir() {
                    std::fs::create_dir_all(&to).map_err(|e| AtlasError::Io(e.to_string()))?;
                    continue;
                }
                if let Some(parent) = to.parent() {
                    std::fs::create_dir_all(parent).map_err(|e| AtlasError::Io(e.to_string()))?;
                }
                let mut out = std::fs::File::create(&to).map_err(|e| AtlasError::Io(e.to_string()))?;
                let n = std::io::copy(&mut file, &mut out).map_err(|e| AtlasError::Io(e.to_string()))?;
                written.push(to);
                account(n, written.len())?;
            }
        }
    }
    let mut files = BTreeMap::new();
    for p in written {
        let rel = p.strip_prefix(staging).map_err(|e| AtlasError::Internal(e.to_string()))?.to_string_lossy().replace('\\', "/");
        files.insert(rel, hash_file(&p).map_err(|e| AtlasError::Io(e.to_string()))?);
    }
    if files.is_empty() {
        return Err(AtlasError::Validation("the archive is empty".into()));
    }
    Ok(files)
}

/// Find a file by name anywhere under `dir` (engine archives nest their binaries differently per
/// platform and version).
pub fn find_file(dir: &Path, name: &str) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for e in rd.flatten() {
            let p = e.path();
            let Ok(ft) = e.file_type() else { continue };
            if ft.is_symlink() {
                continue;
            }
            if ft.is_dir() {
                stack.push(p);
            } else if p.file_name().is_some_and(|n| n.eq_ignore_ascii_case(name)) {
                return Some(p);
            }
        }
    }
    None
}

/// Find the first file with an extension anywhere under `dir`.
pub fn find_ext(dir: &Path, ext: &str) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        let mut entries: Vec<_> = rd.flatten().collect();
        entries.sort_by_key(|e| e.path());
        for e in entries {
            let p = e.path();
            let Ok(ft) = e.file_type() else { continue };
            if ft.is_dir() {
                stack.push(p);
            } else if p.extension().is_some_and(|x| x.eq_ignore_ascii_case(ext)) {
                return Some(p);
            }
        }
    }
    None
}
