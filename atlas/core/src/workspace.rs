//! Path confinement for file tools. Every path the model supplies is relative to the approved
//! workspace root; absolute paths, `..`, and symlinks that resolve outside the root are refused.

use crate::error::{AtlasError, Result};
use std::path::{Component, Path, PathBuf};

pub const TEXT_EXTENSIONS: &[&str] = &[
    "txt", "md", "markdown", "json", "csv", "tsv", "yaml", "yml", "toml", "xml", "html", "htm", "css", "js", "ts",
    "tsx", "jsx", "py", "rs", "go", "java", "c", "h", "cpp", "hpp", "sh", "ini", "log", "sql", "rtf",
];

fn check_relative(rel: &str) -> Result<PathBuf> {
    if rel.is_empty() || rel.len() > 512 || rel.contains('\0') {
        return Err(AtlasError::Validation("invalid path".into()));
    }
    let p = Path::new(rel);
    for c in p.components() {
        match c {
            Component::Normal(_) | Component::CurDir => {}
            Component::ParentDir => return Err(AtlasError::PermissionDenied("'..' is not allowed in workspace paths".into())),
            Component::RootDir | Component::Prefix(_) => {
                return Err(AtlasError::PermissionDenied("absolute paths are not allowed; use a path inside the workspace".into()))
            }
        }
    }
    Ok(p.to_path_buf())
}

/// Names Windows reserves for devices; `CON.txt` is still the console device there.
const RESERVED: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1",
    "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

/// Portable file-name rules applied to every component of a path Atlas creates, on every OS, so a
/// workspace synced between machines never receives a name Windows cannot open (or that opens a device).
pub fn check_portable_name(name: &str) -> Result<()> {
    let invalid = |why: &str| Err(AtlasError::Validation(format!("'{name}' is not a valid file name: {why}")));
    if name.is_empty() || name.chars().count() > 200 {
        return invalid("it must be 1-200 characters");
    }
    if let Some(c) = name.chars().find(|c| c.is_control() || matches!(c, '<' | '>' | ':' | '"' | '|' | '?' | '*' | '\\')) {
        return invalid(&format!("it contains {c:?}"));
    }
    if name.ends_with('.') || name.ends_with(' ') {
        return invalid("it ends with a dot or a space");
    }
    let stem = name.split('.').next().unwrap_or("").trim_end().to_ascii_uppercase();
    if RESERVED.contains(&stem.as_str()) {
        return invalid("Windows reserves that name for a device");
    }
    Ok(())
}

pub fn canonical_root(root: &Path) -> Result<PathBuf> {
    root.canonicalize().map_err(|_| AtlasError::NotFound("the workspace folder does not exist".into()))
}

/// Resolve an existing file or directory inside the workspace.
pub fn resolve_existing(root: &Path, rel: &str) -> Result<PathBuf> {
    let root = canonical_root(root)?;
    let rel = if rel.trim().is_empty() || rel == "." { PathBuf::from(".") } else { check_relative(rel)? };
    let full = root.join(rel).canonicalize().map_err(|_| AtlasError::NotFound("no such file in the workspace".into()))?;
    if !full.starts_with(&root) {
        return Err(AtlasError::PermissionDenied("path resolves outside the workspace".into()));
    }
    Ok(full)
}

/// Resolve a path for a new file. Parent directories are created inside the workspace; the
/// target must not already exist (Atlas never overwrites files).
pub fn resolve_new(root: &Path, rel: &str) -> Result<PathBuf> {
    let root = canonical_root(root)?;
    let rel = check_relative(rel)?;
    for comp in rel.components() {
        if let Component::Normal(n) = comp {
            check_portable_name(&n.to_string_lossy())?;
        }
    }
    let file_name = rel.file_name().ok_or_else(|| AtlasError::Validation("missing file name".into()))?.to_owned();
    let ext = rel.extension().and_then(|e| e.to_str()).map(str::to_ascii_lowercase).unwrap_or_default();
    if !TEXT_EXTENSIONS.contains(&ext.as_str()) {
        return Err(AtlasError::Validation(format!("'.{ext}' is not a supported text file type")));
    }
    let parent_rel = rel.parent().map(Path::to_path_buf).unwrap_or_default();
    // Walk and create each directory, re-checking containment so a symlinked directory
    // cannot redirect the write.
    let mut dir = root.clone();
    for comp in parent_rel.components() {
        if let Component::Normal(name) = comp {
            dir = dir.join(name);
            if !dir.exists() {
                std::fs::create_dir(&dir)?;
            }
            let canon = dir.canonicalize()?;
            if !canon.starts_with(&root) {
                return Err(AtlasError::PermissionDenied("path resolves outside the workspace".into()));
            }
            dir = canon;
        }
    }
    let target = dir.join(file_name);
    if target.symlink_metadata().is_ok() {
        return Err(AtlasError::Conflict(format!("'{}' already exists; Atlas does not overwrite files", rel.display())));
    }
    Ok(target)
}

/// Create the file exclusively (fails if it appeared in the meantime) and refuse to follow a
/// symlink at the final component.
pub fn write_new_file(path: &Path, content: &str) -> Result<()> {
    use std::io::Write;
    let mut opts = std::fs::OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.custom_flags(libc_nofollow());
    }
    let mut f = opts.open(path).map_err(|e| {
        if e.kind() == std::io::ErrorKind::AlreadyExists {
            AtlasError::Conflict("file already exists; Atlas does not overwrite files".into())
        } else {
            AtlasError::Io(e.to_string())
        }
    })?;
    f.write_all(content.as_bytes())?;
    f.sync_all()?;
    Ok(())
}

#[cfg(unix)]
fn libc_nofollow() -> i32 {
    // O_NOFOLLOW: 0o400000 on Linux, 0x100 on macOS/BSD.
    if cfg!(target_os = "linux") { 0o400000 } else { 0x0100 }
}

pub fn relative_display(root: &Path, full: &Path) -> String {
    let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
    full.strip_prefix(&root).map(|p| p.to_string_lossy().replace('\\', "/")).unwrap_or_else(|_| "<outside>".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refuses_traversal_absolute_and_overwrite() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        std::fs::write(root.join("a.txt"), "x").unwrap();
        assert!(resolve_existing(root, "a.txt").is_ok());
        assert_eq!(resolve_existing(root, "../etc/passwd").unwrap_err().code(), "permission_denied");
        assert_eq!(resolve_existing(root, "/etc/passwd").unwrap_err().code(), "permission_denied");
        assert_eq!(resolve_new(root, "a.txt").unwrap_err().code(), "conflict");
        assert_eq!(resolve_new(root, "x.exe").unwrap_err().code(), "validation");
        let p = resolve_new(root, "notes/sub/new.md").unwrap();
        write_new_file(&p, "hello").unwrap();
        assert_eq!(std::fs::read_to_string(root.join("notes/sub/new.md")).unwrap(), "hello");
        assert!(write_new_file(&p, "again").is_err());
    }

    #[test]
    fn refuses_names_windows_cannot_open() {
        let dir = tempfile::tempdir().unwrap();
        for bad in ["con.txt", "notes/NUL.md", "aux", "Lpt1.csv", "a:b.txt", "what?.md", "trailing.txt.", "dir /x.md"] {
            assert!(resolve_new(dir.path(), bad).is_err(), "{bad} must be refused");
        }
        // On Windows a backslash is a separator; elsewhere it would create a name Windows can't open.
        #[cfg(not(windows))]
        assert!(resolve_new(dir.path(), "x\\y.txt").is_err());
        for ok in ["console.txt", "notes/null-results.md", "Comet 1.md", "a b/c.txt"] {
            assert!(resolve_new(dir.path(), ok).is_ok(), "{ok} must be allowed");
        }
    }

    #[cfg(unix)]
    #[test]
    fn refuses_symlink_escape() {
        let outside = tempfile::tempdir().unwrap();
        std::fs::write(outside.path().join("secret.txt"), "s").unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::os::unix::fs::symlink(outside.path(), dir.path().join("link")).unwrap();
        assert_eq!(resolve_existing(dir.path(), "link/secret.txt").unwrap_err().code(), "permission_denied");
        assert_eq!(resolve_new(dir.path(), "link/new.txt").unwrap_err().code(), "permission_denied");
        std::os::unix::fs::symlink(outside.path().join("secret.txt"), dir.path().join("f.txt")).unwrap();
        assert_eq!(resolve_existing(dir.path(), "f.txt").unwrap_err().code(), "permission_denied");
    }
}
