//! Git operations for Forge projects, each a fixed argument vector run through the runner.
//! There is deliberately no push, reset, clean or remote management here.

use super::runner::{self, RunOutput, RunSpec};
use crate::error::{AtlasError, Result};
use serde::Serialize;
use std::path::Path;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

const GIT_TIMEOUT: Duration = Duration::from_secs(60);

async fn git(root: &Path, args: &[&str], cancel: &CancellationToken) -> Result<RunOutput> {
    let mut argv: Vec<String> = vec!["git".into(), "--no-pager".into(), "-c".into(), "core.quotepath=off".into(), "-c".into(), "color.ui=never".into()];
    argv.extend(args.iter().map(|s| s.to_string()));
    runner::run(RunSpec { argv: &argv, cwd: root, timeout: GIT_TIMEOUT, max_output: 512 * 1024, extra_env: &[("GIT_OPTIONAL_LOCKS", "0")] }, cancel).await
}

fn ok(r: RunOutput, what: &str) -> Result<String> {
    if r.status == "succeeded" {
        Ok(r.output)
    } else {
        Err(AtlasError::Tool(format!("git {what} failed: {}", crate::ai::truncate(r.output.trim(), 2000))))
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct FileStatus {
    pub path: String,
    /// Two-letter porcelain code, e.g. " M", "A ", "??".
    pub code: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub is_repo: bool,
    pub branch: Option<String>,
    pub ahead_behind: Option<String>,
    pub files: Vec<FileStatus>,
}

pub fn parse_status(out: &str) -> Status {
    let mut branch = None;
    let mut ahead_behind = None;
    let mut files = Vec::new();
    for line in out.lines() {
        if let Some(b) = line.strip_prefix("## ") {
            let (name, rest) = match b.split_once(" [") {
                Some((n, r)) => (n, Some(r.trim_end_matches(']').to_string())),
                None => (b, None),
            };
            let name = name.split("...").next().unwrap_or(name);
            branch = Some(name.trim_start_matches("No commits yet on ").to_string());
            ahead_behind = rest;
        } else if line.len() > 3 {
            let path = line[3..].to_string();
            let path = path.split(" -> ").last().unwrap_or(&path).trim_matches('"').to_string();
            files.push(FileStatus { code: line[..2].to_string(), path });
        }
    }
    Status { is_repo: true, branch, ahead_behind, files }
}

pub async fn status(root: &Path, cancel: &CancellationToken) -> Result<Status> {
    let r = git(root, &["status", "--porcelain=v1", "--branch", "--untracked-files=all"], cancel).await?;
    if r.status != "succeeded" {
        if r.output.contains("not a git repository") {
            return Ok(Status { is_repo: false, branch: None, ahead_behind: None, files: vec![] });
        }
        return Err(AtlasError::Tool(format!("git status failed: {}", crate::ai::truncate(r.output.trim(), 1000))));
    }
    Ok(parse_status(&r.output))
}

fn check_rel(path: &str) -> Result<()> {
    if path.starts_with('-') || path.contains("..") || Path::new(path).is_absolute() || path.contains('\0') {
        return Err(AtlasError::Validation("invalid path".into()));
    }
    Ok(())
}

/// Working-tree diff against HEAD (staged and unstaged), optionally for one path.
pub async fn diff(root: &Path, path: Option<&str>, stat: bool, cancel: &CancellationToken) -> Result<String> {
    let mut args = vec!["diff", "--no-ext-diff", "HEAD"];
    if stat {
        args.push("--stat");
    }
    if let Some(p) = path {
        check_rel(p)?;
        args.push("--");
        args.push(p);
    }
    let r = git(root, &args, cancel).await?;
    if r.status != "succeeded" && r.output.contains("bad revision 'HEAD'") {
        // No commits yet: diff the index against the empty tree.
        let mut a2 = vec!["diff", "--no-ext-diff", "--cached"];
        if let Some(p) = path {
            a2.push("--");
            a2.push(p);
        }
        return ok(git(root, &a2, cancel).await?, "diff");
    }
    ok(r, "diff")
}

#[derive(Debug, Clone, Serialize)]
pub struct Commit {
    pub hash: String,
    pub author: String,
    pub date: String,
    pub subject: String,
}

pub async fn log(root: &Path, limit: u32, cancel: &CancellationToken) -> Result<Vec<Commit>> {
    let n = format!("-n{}", limit.clamp(1, 200));
    let r = git(root, &["log", &n, "--date=short", "--pretty=format:%h%x09%an%x09%ad%x09%s"], cancel).await?;
    if r.status != "succeeded" {
        if r.output.contains("does not have any commits") {
            return Ok(vec![]);
        }
        return Err(AtlasError::Tool(format!("git log failed: {}", crate::ai::truncate(r.output.trim(), 1000))));
    }
    Ok(r
        .output
        .lines()
        .filter_map(|l| {
            let mut it = l.splitn(4, '\t');
            Some(Commit { hash: it.next()?.into(), author: it.next()?.into(), date: it.next()?.into(), subject: it.next()?.into() })
        })
        .collect())
}

pub fn validate_message(msg: &str) -> Result<String> {
    let m = msg.trim();
    if m.is_empty() || m.len() > 5000 || m.contains('\0') {
        return Err(AtlasError::Validation("the commit message must be 1-5000 characters".into()));
    }
    Ok(m.to_string())
}

/// Stage the given paths (or everything when empty) and commit. Returns the new short hash.
pub async fn commit(root: &Path, message: &str, paths: &[String], cancel: &CancellationToken) -> Result<String> {
    let message = validate_message(message)?;
    let mut add: Vec<&str> = vec!["add", "--"];
    if paths.is_empty() {
        add.push(".");
    } else {
        for p in paths {
            check_rel(p)?;
            add.push(p);
        }
    }
    ok(git(root, &add, cancel).await?, "add")?;
    ok(git(root, &["commit", "-m", &message], cancel).await?, "commit")?;
    Ok(ok(git(root, &["rev-parse", "--short", "HEAD"], cancel).await?, "rev-parse")?.trim().to_string())
}

pub fn validate_branch(name: &str) -> Result<()> {
    let bad = name.is_empty()
        || name.len() > 100
        || name.starts_with('-')
        || name.starts_with('/')
        || name.ends_with('/')
        || name.ends_with(".lock")
        || name.contains("..")
        || name.contains("@{")
        || name.chars().any(|c| c.is_whitespace() || c.is_control() || "~^:?*[\\".contains(c));
    if bad { Err(AtlasError::Validation(format!("'{name}' is not a valid branch name"))) } else { Ok(()) }
}

/// Create and switch to a new branch (a checkpoint before larger changes).
pub async fn create_branch(root: &Path, name: &str, cancel: &CancellationToken) -> Result<()> {
    validate_branch(name)?;
    ok(git(root, &["switch", "-c", name], cancel).await?, "switch")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_porcelain() {
        let s = parse_status("## main...origin/main [ahead 2]\n M src/a.rs\n?? new file.txt\nR  old.rs -> new.rs\n");
        assert_eq!(s.branch.as_deref(), Some("main"));
        assert_eq!(s.ahead_behind.as_deref(), Some("ahead 2"));
        assert_eq!(s.files.len(), 3);
        assert_eq!((s.files[1].code.as_str(), s.files[1].path.as_str()), ("??", "new file.txt"));
        assert_eq!(s.files[2].path, "new.rs");
        assert!(validate_branch("atlas/checkpoint-1").is_ok());
        for b in ["-x", "a..b", "a b", "x.lock", "a~1"] {
            assert!(validate_branch(b).is_err(), "{b}");
        }
    }

    #[tokio::test]
    async fn real_git_roundtrip() {
        if runner::resolve_program("git", Path::new(".")).is_err() {
            return;
        }
        let dir = tempfile::tempdir().unwrap();
        let c = CancellationToken::new();
        let root = dir.path();
        assert!(!status(root, &c).await.unwrap().is_repo);
        for args in [&["init", "-q", "-b", "main"][..], &["config", "user.email", "t@example.com"], &["config", "user.name", "T"]] {
            git(root, args, &c).await.unwrap();
        }
        std::fs::write(root.join("a.txt"), "one\n").unwrap();
        let s = status(root, &c).await.unwrap();
        assert!(s.is_repo && s.files.iter().any(|f| f.path == "a.txt" && f.code == "??"));
        let h = commit(root, "first", &[], &c).await.unwrap();
        assert!(!h.is_empty());
        std::fs::write(root.join("a.txt"), "two\n").unwrap();
        let d = diff(root, Some("a.txt"), false, &c).await.unwrap();
        assert!(d.contains("-one") && d.contains("+two"), "{d}");
        assert_eq!(log(root, 5, &c).await.unwrap()[0].subject, "first");
        create_branch(root, "atlas/checkpoint", &c).await.unwrap();
        assert_eq!(status(root, &c).await.unwrap().branch.as_deref(), Some("atlas/checkpoint"));
        assert!(diff(root, Some("../x"), false, &c).await.is_err());
    }
}
