//! Atlas Forge: engineering work on a project folder the owner chose.
//!
//! Every path is confined to the project root (no `..`, no absolute paths, no symlink escapes,
//! nothing inside `.git`). Every file Atlas changes is snapshotted first so the change can be
//! reverted — but only while the file still has the content Atlas wrote; if it changed since,
//! revert refuses rather than pretending. Commands run without a shell (see `runner`).

pub mod git;
pub mod runner;

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use crate::workspace;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Component, Path, PathBuf};

/// How Atlas works in a Forge session. Each discipline has its own instructions and tool set.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum Discipline {
    /// Understands the system and designs changes. Reads only.
    Architect,
    /// Implements changes, runs tests, proposes commits.
    Builder,
    /// Reproduces a failure, finds the root cause, fixes it, proves the fix.
    Debugger,
    /// Recovers how unfamiliar or legacy code works and documents it. Reads, and may add new
    /// files (documentation), but does not edit existing ones.
    Reconstructor,
}

impl Discipline {
    pub fn parse(s: &str) -> Option<Self> {
        serde_json::from_value(serde_json::Value::String(s.into())).ok()
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Discipline::Architect => "architect",
            Discipline::Builder => "builder",
            Discipline::Debugger => "debugger",
            Discipline::Reconstructor => "reconstructor",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Discipline::Architect => "Architect",
            Discipline::Builder => "Builder",
            Discipline::Debugger => "Debugger",
            Discipline::Reconstructor => "Reconstructor",
        }
    }
    /// Multi-step analysis disciplines route to the Heavy tier in Auto mode.
    pub fn is_deep(self) -> bool {
        matches!(self, Discipline::Architect | Discipline::Debugger | Discipline::Reconstructor)
    }
    /// Which tools a Forge session in this discipline may be offered. Policy and approvals
    /// still apply on top of this.
    pub fn allows(self, tool_id: &str) -> bool {
        const READ: &[&str] = &["forge.tree", "forge.read_file", "forge.search", "forge.git_status", "forge.git_diff", "forge.git_log"];
        const GENERAL: &[&str] = &["calc.evaluate", "time.now", "text.transform", "memory.search", "memory.save", "tasks.status"];
        if READ.contains(&tool_id) || GENERAL.contains(&tool_id) {
            return true;
        }
        match self {
            Discipline::Architect => false,
            Discipline::Reconstructor => tool_id == "forge.write_file",
            Discipline::Builder | Discipline::Debugger => {
                matches!(tool_id, "forge.edit_file" | "forge.write_file" | "forge.run_tests" | "forge.run_command" | "forge.git_commit")
            }
        }
    }
    pub fn instructions(self) -> &'static str {
        match self {
            Discipline::Architect => "You are working as Forge ARCHITECT. Study the project with the read-only Forge tools, then explain the current design and propose changes as a concrete plan: files to touch, interfaces, risks, migration steps and how to test. Do not claim to have changed anything; you have no write tools in this discipline.",
            Discipline::Builder => "You are working as Forge BUILDER. Implement the requested change in small, reviewable steps. Read the relevant code before editing. Prefer forge.edit_file with an exact, unique `old` snippet over rewriting whole files. After changing code, run the project's tests with forge.run_tests and report the real result (pass/fail counts and failures). Never report success that the tool results do not show. Propose a commit with forge.git_commit only when tests pass or the owner asks.",
            Discipline::Debugger => "You are working as Forge DEBUGGER. First reproduce the failure (run the tests or the failing command), then locate the root cause by reading code, then make the smallest fix, then re-run to prove it. State the root cause plainly. If you cannot reproduce it, say so and say what you tried.",
            Discipline::Reconstructor => "You are working as Forge RECONSTRUCTOR. Recover how unfamiliar or legacy code works: entry points, data flow, module boundaries, build and test commands, and undocumented behaviour. Cite file paths and line ranges. You may create new documentation files with forge.write_file but must not edit existing files.",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForgeProject {
    pub id: String,
    pub name: String,
    pub root_path: String,
    pub test_command: Option<String>,
    pub build_command: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub exists: bool,
}

/// What tools see of the active Forge project.
#[derive(Debug, Clone)]
pub struct ForgeScope {
    pub project_id: String,
    pub root: PathBuf,
    pub test_command: Option<String>,
    pub build_command: Option<String>,
    pub discipline: Discipline,
}

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<ForgeProject> {
    let root: String = r.get(2)?;
    Ok(ForgeProject {
        id: r.get(0)?,
        name: r.get(1)?,
        exists: Path::new(&root).is_dir(),
        root_path: root,
        test_command: r.get(3)?,
        build_command: r.get(4)?,
        created_at: r.get(5)?,
        updated_at: r.get(6)?,
    })
}

const COLS: &str = "id, name, root_path, test_command, build_command, created_at, updated_at";

fn validate_command(c: Option<&str>) -> Result<Option<String>> {
    match c.map(str::trim).filter(|c| !c.is_empty()) {
        None => Ok(None),
        Some(c) => {
            runner::parse_command(c)?;
            Ok(Some(c.to_string()))
        }
    }
}

/// Folders that are never sensible Forge roots.
fn check_root(path: &Path) -> Result<PathBuf> {
    let canon = path.canonicalize().map_err(|_| AtlasError::NotFound("that folder does not exist".into()))?;
    if !canon.is_dir() {
        return Err(AtlasError::Validation("choose a folder, not a file".into()));
    }
    if canon.parent().is_none() || canon.components().count() <= 2 {
        return Err(AtlasError::Validation("choose a project folder, not a drive root or top-level system folder".into()));
    }
    if let Some(home) = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from)
        && home.canonicalize().map(|h| h == canon).unwrap_or(false) {
            return Err(AtlasError::Validation("choose a project folder inside your home folder, not the home folder itself".into()));
        }
    Ok(canon)
}

pub fn add_project(db: &Db, name: &str, root: &Path, test_command: Option<&str>, build_command: Option<&str>) -> Result<ForgeProject> {
    let canon = check_root(root)?;
    let name = if name.trim().is_empty() { canon.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "Project".into()) } else { name.trim().to_string() };
    let id = new_id();
    let t = now();
    db.conn()?
        .execute(
            "INSERT INTO forge_projects(id, name, root_path, test_command, build_command, created_at, updated_at) VALUES (?1,?2,?3,?4,?5,?6,?6)",
            rusqlite::params![id, crate::ai::truncate(&name, 120), canon.to_string_lossy(), validate_command(test_command)?, validate_command(build_command)?, t],
        )
        .map_err(|e| match e {
            rusqlite::Error::SqliteFailure(f, _) if f.code == rusqlite::ErrorCode::ConstraintViolation => AtlasError::Conflict("that folder is already a Forge project".into()),
            o => o.into(),
        })?;
    get_project(db, &id)
}

pub fn update_project(db: &Db, id: &str, name: &str, test_command: Option<&str>, build_command: Option<&str>) -> Result<ForgeProject> {
    get_project(db, id)?;
    db.conn()?.execute(
        "UPDATE forge_projects SET name = ?1, test_command = ?2, build_command = ?3, updated_at = ?4 WHERE id = ?5",
        rusqlite::params![crate::ai::truncate(name.trim(), 120), validate_command(test_command)?, validate_command(build_command)?, now(), id],
    )?;
    get_project(db, id)
}

/// Forget a project (its change history and runs go with it). Files on disk are untouched.
pub fn remove_project(db: &Db, id: &str) -> Result<()> {
    let n = db.conn()?.execute("DELETE FROM forge_projects WHERE id = ?1", [id])?;
    if n == 0 {
        return Err(AtlasError::NotFound("Forge project".into()));
    }
    db.conn()?.execute("UPDATE conversations SET forge_project_id = NULL WHERE forge_project_id = ?1", [id])?;
    Ok(())
}

pub fn get_project(db: &Db, id: &str) -> Result<ForgeProject> {
    db.conn()?.query_row(&format!("SELECT {COLS} FROM forge_projects WHERE id = ?1"), [id], row).map_err(|e| match e {
        rusqlite::Error::QueryReturnedNoRows => AtlasError::NotFound("Forge project".into()),
        o => o.into(),
    })
}

pub fn list_projects(db: &Db) -> Result<Vec<ForgeProject>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM forge_projects ORDER BY updated_at DESC"))?;
    let rows = stmt.query_map([], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn scope(db: &Db, project_id: &str, discipline: Discipline) -> Result<ForgeScope> {
    let p = get_project(db, project_id)?;
    if !p.exists {
        return Err(AtlasError::NotFound(format!("the folder for '{}' no longer exists", p.name)));
    }
    Ok(ForgeScope { project_id: p.id, root: PathBuf::from(p.root_path), test_command: p.test_command, build_command: p.build_command, discipline })
}

// ---------- paths ----------

/// Directories skipped when listing and searching (build output, dependencies, VCS data).
pub const SKIP_DIRS: &[&str] = &[".git", "node_modules", "target", "dist", "build", ".venv", "venv", "__pycache__", ".next", ".turbo", ".cache", ".idea", ".vs", "coverage", ".pytest_cache", ".mypy_cache"];

fn touches_git_dir(rel: &str) -> bool {
    Path::new(rel).components().any(|c| matches!(c, Component::Normal(n) if n.to_string_lossy().eq_ignore_ascii_case(".git")))
}

pub fn resolve_existing(root: &Path, rel: &str) -> Result<PathBuf> {
    if touches_git_dir(rel) {
        return Err(AtlasError::PermissionDenied("the .git folder is managed by git; use the git tools".into()));
    }
    workspace::resolve_existing(root, rel)
}

pub fn display_rel(root: &Path, full: &Path) -> String {
    workspace::relative_display(root, full)
}

#[derive(Debug, Clone, Serialize)]
pub struct TreeEntry {
    pub path: String,
    pub kind: &'static str,
    pub bytes: Option<u64>,
}

/// List a directory subtree (depth-limited, skipping build/dependency folders and symlinks).
pub fn tree(root: &Path, rel: &str, depth: u32, limit: usize) -> Result<(Vec<TreeEntry>, bool)> {
    let start = resolve_existing(root, if rel.trim().is_empty() { "." } else { rel })?;
    if !start.is_dir() {
        return Err(AtlasError::Validation("that path is a file, not a folder".into()));
    }
    let canon_root = workspace::canonical_root(root)?;
    let mut out = Vec::new();
    let mut truncated = false;
    fn walk(dir: &Path, root: &Path, depth: u32, limit: usize, out: &mut Vec<TreeEntry>, truncated: &mut bool) {
        let Ok(rd) = std::fs::read_dir(dir) else { return };
        let mut items: Vec<_> = rd.flatten().collect();
        items.sort_by_key(|e| (!e.file_type().map(|t| t.is_dir()).unwrap_or(false), e.file_name()));
        for e in items {
            if out.len() >= limit {
                *truncated = true;
                return;
            }
            let Ok(ft) = e.file_type() else { continue };
            if ft.is_symlink() {
                continue;
            }
            let name = e.file_name().to_string_lossy().to_string();
            let path = e.path();
            let rel = display_rel(root, &path);
            if ft.is_dir() {
                if SKIP_DIRS.contains(&name.as_str()) {
                    continue;
                }
                out.push(TreeEntry { path: rel, kind: "dir", bytes: None });
                if depth > 1 {
                    walk(&path, root, depth - 1, limit, out, truncated);
                }
            } else {
                out.push(TreeEntry { path: rel, kind: "file", bytes: e.metadata().ok().map(|m| m.len()) });
            }
        }
    }
    walk(&start, &canon_root, depth.clamp(1, 12), limit, &mut out, &mut truncated);
    Ok((out, truncated))
}

pub const MAX_FILE_BYTES: u64 = 1024 * 1024;

/// Read a UTF-8 text file. Binary files are refused rather than mangled.
pub fn read_text(root: &Path, rel: &str) -> Result<(PathBuf, String)> {
    let full = resolve_existing(root, rel)?;
    if !full.is_file() {
        return Err(AtlasError::Validation("that path is a folder, not a file".into()));
    }
    let len = full.metadata()?.len();
    if len > MAX_FILE_BYTES {
        return Err(AtlasError::Validation(format!("the file is {} KB; Forge reads files up to {} KB", len / 1024, MAX_FILE_BYTES / 1024)));
    }
    let bytes = std::fs::read(&full)?;
    if bytes.iter().take(8000).any(|b| *b == 0) {
        return Err(AtlasError::Validation("that looks like a binary file".into()));
    }
    let text = String::from_utf8(bytes).map_err(|_| AtlasError::Validation("the file is not UTF-8 text".into()))?;
    Ok((full, text))
}

#[derive(Debug, Clone, Serialize)]
pub struct SearchHit {
    pub path: String,
    pub line: usize,
    pub text: String,
}

/// Case-insensitive literal search across text files.
pub fn search(root: &Path, query: &str, path_contains: Option<&str>, limit: usize) -> Result<(Vec<SearchHit>, bool)> {
    let q = query.to_lowercase();
    if q.trim().is_empty() || q.len() > 500 {
        return Err(AtlasError::Validation("search text must be 1-500 characters".into()));
    }
    let (entries, _) = tree(root, ".", 12, 20_000)?;
    let canon = workspace::canonical_root(root)?;
    let mut hits = Vec::new();
    for e in entries.iter().filter(|e| e.kind == "file" && e.bytes.unwrap_or(0) <= MAX_FILE_BYTES) {
        if let Some(f) = path_contains
            && !e.path.to_lowercase().contains(&f.to_lowercase()) {
                continue;
            }
        let Ok(bytes) = std::fs::read(canon.join(&e.path)) else { continue };
        if bytes.iter().take(8000).any(|b| *b == 0) {
            continue;
        }
        let text = String::from_utf8_lossy(&bytes);
        for (i, line) in text.lines().enumerate() {
            if line.to_lowercase().contains(&q) {
                if hits.len() >= limit {
                    return Ok((hits, true));
                }
                hits.push(SearchHit { path: e.path.clone(), line: i + 1, text: crate::ai::truncate(line.trim(), 300) });
            }
        }
    }
    Ok((hits, false))
}

// ---------- changes ----------

pub fn sha256(s: &str) -> String {
    hex::encode(Sha256::digest(s.as_bytes()))
}

pub fn unified_diff(path: &str, before: &str, after: &str) -> String {
    let d = similar::TextDiff::from_lines(before, after);
    d.unified_diff().context_radius(3).header(&format!("a/{path}"), &format!("b/{path}")).to_string()
}

#[derive(Debug, Clone, Serialize)]
pub struct Change {
    pub id: String,
    pub project_id: String,
    pub path: String,
    pub kind: String,
    pub summary: String,
    pub source: String,
    pub task_id: Option<String>,
    pub created_at: String,
    pub reverted_at: Option<String>,
    /// Whether revert can still be done reliably (file unchanged since Atlas wrote it).
    pub revertible: bool,
    pub revert_blocker: Option<String>,
}

/// Write `content` atomically: temp file in the same folder, then rename over the target.
fn atomic_write(full: &Path, content: &str) -> Result<()> {
    use std::io::Write;
    let dir = full.parent().ok_or_else(|| AtlasError::Internal("no parent".into()))?;
    let tmp = dir.join(format!(".atlas-tmp-{}", new_id()));
    let res = (|| -> Result<()> {
        let mut f = std::fs::OpenOptions::new().write(true).create_new(true).open(&tmp)?;
        f.write_all(content.as_bytes())?;
        f.sync_all()?;
        if let Ok(meta) = std::fs::metadata(full) {
            let _ = std::fs::set_permissions(&tmp, meta.permissions());
        }
        std::fs::rename(&tmp, full)?;
        Ok(())
    })();
    if res.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    res
}

#[allow(clippy::too_many_arguments)]
fn record_change(db: &Db, scope: &ForgeScope, rel: &str, kind: &str, before: Option<&str>, after: &str, summary: &str, task_id: Option<&str>, source: &str) -> Result<String> {
    let id = new_id();
    db.conn()?.execute(
        "INSERT INTO forge_changes(id, project_id, path, kind, before_content, before_sha256, after_sha256, summary, task_id, source, created_at)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
        rusqlite::params![id, scope.project_id, rel, kind, before, before.map(sha256), sha256(after), crate::ai::truncate(summary, 300), task_id, source, now()],
    )?;
    Ok(id)
}

/// What an edit would do to the file as it is now, as a unified diff with context. Used for the
/// approval preview; does not write anything.
pub fn preview_edit(root: &Path, rel: &str, old: &str, new: &str, replace_all: bool) -> Result<String> {
    let (full, before) = read_text(root, rel)?;
    let count = before.matches(old).count();
    if old.is_empty() || count == 0 {
        return Err(AtlasError::Conflict("`old` was not found in the file as it is now".into()));
    }
    if count > 1 && !replace_all {
        return Err(AtlasError::Conflict(format!("`old` occurs {count} times; the edit will be refused unless it is made unique")));
    }
    let after = if replace_all { before.replace(old, new) } else { before.replacen(old, new, 1) };
    Ok(unified_diff(&display_rel(root, &full), &before, &after))
}

/// Diff for a whole-file write against the current content (or an empty file).
pub fn preview_write(root: &Path, rel: &str, content: &str) -> String {
    match read_text(root, rel) {
        Ok((full, before)) => unified_diff(&display_rel(root, &full), &before, content),
        Err(_) => unified_diff(rel, "", content),
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct EditResult {
    pub change_id: String,
    pub path: String,
    pub diff: String,
    pub replacements: usize,
}

/// Replace `old` with `new` in an existing file. `old` must occur exactly once unless
/// `replace_all`. Fails (changing nothing) if it does not match the file as it is now.
#[allow(clippy::too_many_arguments)]
pub fn edit_file(db: &Db, scope: &ForgeScope, rel: &str, old: &str, new: &str, replace_all: bool, task_id: Option<&str>, source: &str) -> Result<EditResult> {
    if old.is_empty() {
        return Err(AtlasError::Validation("`old` must not be empty; use forge.write_file to create files".into()));
    }
    if old == new {
        return Err(AtlasError::Validation("`old` and `new` are identical".into()));
    }
    let (full, before) = read_text(&scope.root, rel)?;
    let count = before.matches(old).count();
    if count == 0 {
        return Err(AtlasError::Conflict("`old` was not found in the file as it is now; read the file again and use an exact snippet".into()));
    }
    if count > 1 && !replace_all {
        return Err(AtlasError::Conflict(format!("`old` occurs {count} times; include more surrounding lines so it is unique, or set replace_all")));
    }
    let after = if replace_all { before.replace(old, new) } else { before.replacen(old, new, 1) };
    let rel_disp = display_rel(&scope.root, &full);
    atomic_write(&full, &after)?;
    let diff = unified_diff(&rel_disp, &before, &after);
    let change_id = record_change(db, scope, &rel_disp, "modify", Some(&before), &after, &format!("edit ({count} replacement{})", if count == 1 { "" } else { "s" }), task_id, source)?;
    Ok(EditResult { change_id, path: rel_disp, diff, replacements: if replace_all { count } else { 1 } })
}

/// Create a file, or replace one when `overwrite` is true.
pub fn write_file(db: &Db, scope: &ForgeScope, rel: &str, content: &str, overwrite: bool, task_id: Option<&str>, source: &str) -> Result<EditResult> {
    if touches_git_dir(rel) {
        return Err(AtlasError::PermissionDenied("the .git folder is managed by git".into()));
    }
    if content.len() as u64 > MAX_FILE_BYTES {
        return Err(AtlasError::Validation("content is larger than 1 MB".into()));
    }
    match resolve_existing(&scope.root, rel) {
        Ok(full) => {
            if !overwrite {
                return Err(AtlasError::Conflict(format!("'{rel}' already exists; set overwrite to replace it, or use forge.edit_file")));
            }
            let (_, before) = read_text(&scope.root, rel)?;
            let rel_disp = display_rel(&scope.root, &full);
            atomic_write(&full, content)?;
            let diff = unified_diff(&rel_disp, &before, content);
            let change_id = record_change(db, scope, &rel_disp, "modify", Some(&before), content, "replaced file", task_id, source)?;
            Ok(EditResult { change_id, path: rel_disp, diff, replacements: 0 })
        }
        Err(AtlasError::NotFound(_)) => {
            let full = workspace::resolve_new_with(&scope.root, rel, false)?;
            workspace::write_new_file(&full, content)?;
            let rel_disp = display_rel(&scope.root, &full);
            let diff = unified_diff(&rel_disp, "", content);
            let change_id = record_change(db, scope, &rel_disp, "create", None, content, "created file", task_id, source)?;
            Ok(EditResult { change_id, path: rel_disp, diff, replacements: 0 })
        }
        Err(e) => Err(e),
    }
}

fn change_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<(Change, Option<String>, String, String)> {
    Ok((
        Change {
            id: r.get(0)?,
            project_id: r.get(1)?,
            path: r.get(2)?,
            kind: r.get(3)?,
            summary: r.get(4)?,
            source: r.get(5)?,
            task_id: r.get(6)?,
            created_at: r.get(7)?,
            reverted_at: r.get(8)?,
            revertible: false,
            revert_blocker: None,
        },
        r.get(9)?,
        r.get(10)?,
        r.get(11)?,
    ))
}

const CHANGE_COLS: &str = "c.id, c.project_id, c.path, c.kind, c.summary, c.source, c.task_id, c.created_at, c.reverted_at, c.before_content, c.after_sha256, p.root_path";

/// Why a change cannot be reverted reliably right now, if it can't.
fn revert_blocker(root: &Path, c: &Change, after_sha: &str, db: &Db) -> Option<String> {
    if c.reverted_at.is_some() {
        return Some("already reverted".into());
    }
    let later: i64 = db
        .conn()
        .ok()?
        .query_row(
            "SELECT count(*) FROM forge_changes WHERE project_id = ?1 AND path = ?2 AND created_at > ?3 AND reverted_at IS NULL",
            rusqlite::params![c.project_id, c.path, c.created_at],
            |r| r.get(0),
        )
        .unwrap_or(0);
    if later > 0 {
        return Some("a later change to this file must be reverted first".into());
    }
    match read_text(root, &c.path) {
        Ok((_, now_text)) if sha256(&now_text) == after_sha => None,
        Ok(_) => Some("the file has changed since Atlas wrote it, so reverting could lose newer work".into()),
        Err(_) => Some("the file is missing or unreadable".into()),
    }
}

pub fn list_changes(db: &Db, project_id: &str, limit: u32) -> Result<Vec<Change>> {
    let rows: Vec<_> = {
        let conn = db.conn()?;
        let mut stmt = conn.prepare(&format!(
            "SELECT {CHANGE_COLS} FROM forge_changes c JOIN forge_projects p ON p.id = c.project_id WHERE c.project_id = ?1 ORDER BY c.created_at DESC LIMIT ?2"
        ))?;
        stmt.query_map(rusqlite::params![project_id, limit.min(500)], change_row)?.collect::<std::result::Result<_, _>>()?
    };
    Ok(rows
        .into_iter()
        .map(|(mut c, _, after_sha, root)| {
            c.revert_blocker = revert_blocker(Path::new(&root), &c, &after_sha, db);
            c.revertible = c.revert_blocker.is_none();
            c
        })
        .collect())
}

pub fn change_diff(db: &Db, change_id: &str) -> Result<String> {
    let (c, before, _after_sha, root) = db.conn()?.query_row(
        &format!("SELECT {CHANGE_COLS} FROM forge_changes c JOIN forge_projects p ON p.id = c.project_id WHERE c.id = ?1"),
        [change_id],
        change_row,
    )?;
    let now_text = read_text(Path::new(&root), &c.path).map(|x| x.1).unwrap_or_default();
    Ok(unified_diff(&c.path, before.as_deref().unwrap_or(""), &now_text))
}

/// Undo one change: restore the previous content (or remove a created file). Refuses when the
/// file no longer matches what Atlas wrote.
pub fn revert_change(db: &Db, change_id: &str) -> Result<Change> {
    let (c, before, after_sha, root) = db.conn()?.query_row(
        &format!("SELECT {CHANGE_COLS} FROM forge_changes c JOIN forge_projects p ON p.id = c.project_id WHERE c.id = ?1"),
        [change_id],
        change_row,
    )?;
    let root = PathBuf::from(root);
    if let Some(b) = revert_blocker(&root, &c, &after_sha, db) {
        return Err(AtlasError::Conflict(format!("cannot revert {}: {b}", c.path)));
    }
    let full = resolve_existing(&root, &c.path)?;
    match (c.kind.as_str(), before) {
        ("create", _) => std::fs::remove_file(&full)?,
        (_, Some(b)) => atomic_write(&full, &b)?,
        _ => return Err(AtlasError::Internal("missing snapshot".into())),
    }
    db.conn()?.execute("UPDATE forge_changes SET reverted_at = ?1 WHERE id = ?2", rusqlite::params![now(), change_id])?;
    let mut out = list_changes(db, &c.project_id, 500)?.into_iter().find(|x| x.id == change_id).ok_or_else(|| AtlasError::NotFound("change".into()))?;
    out.revertible = false;
    Ok(out)
}

// ---------- runs ----------

#[derive(Debug, Clone, Serialize)]
pub struct RunRecord {
    pub id: String,
    pub project_id: String,
    pub command: String,
    pub initiated_by: String,
    pub status: String,
    pub exit_code: Option<i32>,
    pub duration_ms: Option<i64>,
    pub output: String,
    pub summary: Option<serde_json::Value>,
    pub created_at: String,
    pub finished_at: Option<String>,
}

pub fn start_run(db: &Db, project_id: &str, argv: &[String], by: &str, task_id: Option<&str>) -> Result<String> {
    let id = new_id();
    db.conn()?.execute(
        "INSERT INTO forge_runs(id, project_id, argv, initiated_by, status, task_id, created_at) VALUES (?1,?2,?3,?4,'running',?5,?6)",
        rusqlite::params![id, project_id, serde_json::to_string(argv)?, by, task_id, now()],
    )?;
    Ok(id)
}

pub fn finish_run(db: &Db, run_id: &str, out: &runner::RunOutput) -> Result<()> {
    db.conn()?.execute(
        "UPDATE forge_runs SET status = ?1, exit_code = ?2, duration_ms = ?3, output = ?4, summary = ?5, finished_at = ?6 WHERE id = ?7",
        rusqlite::params![out.status, out.exit_code, out.duration_ms as i64, out.output, out.tests.as_ref().map(|t| serde_json::to_string(t).unwrap_or_default()), now(), run_id],
    )?;
    Ok(())
}

pub fn fail_run(db: &Db, run_id: &str, error: &str) {
    if let Ok(c) = db.conn() {
        let _ = c.execute(
            "UPDATE forge_runs SET status = 'error', output = ?1, finished_at = ?2 WHERE id = ?3",
            rusqlite::params![crate::redact::redact(error), now(), run_id],
        );
    }
}

/// Runs left "running" by a previous session cannot be resumed; mark them honestly.
pub fn recover_runs(db: &Db) -> Result<usize> {
    Ok(db.conn()?.execute(
        "UPDATE forge_runs SET status = 'interrupted', finished_at = ?1 WHERE status = 'running'",
        [now()],
    )?)
}

pub fn list_runs(db: &Db, project_id: &str, limit: u32) -> Result<Vec<RunRecord>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(
        "SELECT id, project_id, argv, initiated_by, status, exit_code, duration_ms, output, summary, created_at, finished_at
         FROM forge_runs WHERE project_id = ?1 ORDER BY created_at DESC LIMIT ?2",
    )?;
    let rows = stmt.query_map(rusqlite::params![project_id, limit.min(200)], |r| {
        let argv: Vec<String> = serde_json::from_str(&r.get::<_, String>(2)?).unwrap_or_default();
        Ok(RunRecord {
            id: r.get(0)?,
            project_id: r.get(1)?,
            command: runner::display_command(&argv),
            initiated_by: r.get(3)?,
            status: r.get(4)?,
            exit_code: r.get(5)?,
            duration_ms: r.get(6)?,
            output: r.get(7)?,
            summary: r.get::<_, Option<String>>(8)?.and_then(|s| serde_json::from_str(&s).ok()),
            created_at: r.get(9)?,
            finished_at: r.get(10)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup() -> (Db, tempfile::TempDir, ForgeScope) {
        let db = Db::open_in_memory().unwrap();
        let base = tempfile::tempdir().unwrap();
        let root = base.path().join("proj");
        std::fs::create_dir_all(root.join("src")).unwrap();
        std::fs::write(root.join("src/lib.rs"), "fn a() {}\nfn b() {}\n").unwrap();
        let p = add_project(&db, "", &root, Some("cargo test"), None).unwrap();
        assert_eq!(p.name, "proj");
        let s = scope(&db, &p.id, Discipline::Builder).unwrap();
        (db, base, s)
    }

    #[test]
    fn discipline_tool_sets() {
        assert!(Discipline::Architect.allows("forge.read_file"));
        assert!(!Discipline::Architect.allows("forge.edit_file"));
        assert!(!Discipline::Architect.allows("forge.run_command"));
        assert!(Discipline::Reconstructor.allows("forge.write_file"));
        assert!(!Discipline::Reconstructor.allows("forge.edit_file"));
        assert!(Discipline::Builder.allows("forge.git_commit"));
        assert!(Discipline::Debugger.allows("forge.run_tests"));
        assert!(!Discipline::Builder.allows("files.create"), "workspace file tools are not part of Forge");
        assert_eq!(Discipline::parse("debugger"), Some(Discipline::Debugger));
    }

    #[test]
    fn edit_snapshot_and_reliable_revert() {
        let (db, _d, s) = setup();
        let r = edit_file(&db, &s, "src/lib.rs", "fn b() {}", "fn b() { todo!() }", false, None, "model").unwrap();
        assert!(r.diff.contains("+fn b() { todo!() }") && r.diff.contains("-fn b() {}"), "{}", r.diff);
        // Ambiguous and missing snippets are refused without touching the file.
        assert_eq!(edit_file(&db, &s, "src/lib.rs", "fn ", "x", false, None, "model").unwrap_err().code(), "conflict");
        assert_eq!(edit_file(&db, &s, "src/lib.rs", "nope", "x", false, None, "model").unwrap_err().code(), "conflict");
        let changes = list_changes(&db, &s.project_id, 10).unwrap();
        assert!(changes[0].revertible);
        revert_change(&db, &r.change_id).unwrap();
        assert_eq!(std::fs::read_to_string(s.root.join("src/lib.rs")).unwrap(), "fn a() {}\nfn b() {}\n");
        assert!(revert_change(&db, &r.change_id).is_err(), "double revert must fail");
    }

    #[test]
    fn revert_refuses_when_file_changed_since() {
        let (db, _d, s) = setup();
        let r = edit_file(&db, &s, "src/lib.rs", "fn a() {}", "fn a() { 1; }", false, None, "model").unwrap();
        std::fs::write(s.root.join("src/lib.rs"), "owner rewrote this\n").unwrap();
        let c = &list_changes(&db, &s.project_id, 10).unwrap()[0];
        assert!(!c.revertible && c.revert_blocker.as_deref().unwrap().contains("changed since"));
        assert_eq!(revert_change(&db, &r.change_id).unwrap_err().code(), "conflict");
        assert_eq!(std::fs::read_to_string(s.root.join("src/lib.rs")).unwrap(), "owner rewrote this\n");
    }

    #[test]
    fn write_create_overwrite_and_revert_create() {
        let (db, _d, s) = setup();
        let r = write_file(&db, &s, "docs/ARCH.md", "# Arch\n", false, None, "model").unwrap();
        assert!(s.root.join("docs/ARCH.md").exists());
        assert_eq!(write_file(&db, &s, "docs/ARCH.md", "x", false, None, "model").unwrap_err().code(), "conflict");
        let r2 = write_file(&db, &s, "docs/ARCH.md", "# Arch v2\n", true, None, "model").unwrap();
        // Out of order revert is refused; in order works and removes the created file.
        assert!(revert_change(&db, &r.change_id).is_err());
        revert_change(&db, &r2.change_id).unwrap();
        revert_change(&db, &r.change_id).unwrap();
        assert!(!s.root.join("docs/ARCH.md").exists());
    }

    #[test]
    fn confinement() {
        let (db, _d, s) = setup();
        assert!(read_text(&s.root, "../outside.txt").is_err());
        assert!(read_text(&s.root, "/etc/passwd").is_err());
        assert_eq!(write_file(&db, &s, ".git/hooks/pre-commit", "x", false, None, "model").unwrap_err().code(), "permission_denied");
        assert!(write_file(&db, &s, "../escape.txt", "x", false, None, "model").is_err());
        std::fs::create_dir_all(s.root.join("node_modules/x")).unwrap();
        std::fs::write(s.root.join("node_modules/x/i.js"), "needle").unwrap();
        std::fs::write(s.root.join("src/m.rs"), "// Needle here\n").unwrap();
        let (hits, _) = search(&s.root, "needle", None, 50).unwrap();
        assert_eq!(hits.len(), 1, "node_modules is skipped");
        assert_eq!((hits[0].path.as_str(), hits[0].line), ("src/m.rs", 1));
        let (t, _) = tree(&s.root, ".", 3, 100).unwrap();
        assert!(t.iter().any(|e| e.path == "src/lib.rs") && !t.iter().any(|e| e.path.starts_with("node_modules")));
    }

    #[test]
    fn rejects_bad_roots_and_duplicate_projects() {
        let (db, _d, s) = setup();
        assert_eq!(add_project(&db, "x", &s.root, None, None).unwrap_err().code(), "conflict");
        assert!(add_project(&db, "x", Path::new("/"), None, None).is_err());
        assert!(add_project(&db, "x", &s.root, Some("echo 'unclosed"), None).is_err());
    }
}
