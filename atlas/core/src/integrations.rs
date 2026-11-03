//! External integrations catalog. Only integrations with a real adapter are marked
//! `implemented`; the rest are listed as planned so the UI never implies they work.

use crate::credentials::{integration_account, mask, validate_secret, SharedSecrets};
use crate::error::{AtlasError, Result};
use crate::storage::{now, Db};
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Clone, Serialize)]
pub struct CatalogEntry {
    pub id: &'static str,
    pub name: &'static str,
    pub category: &'static str,
    pub description: &'static str,
    pub capabilities: &'static [&'static str],
    pub auth: &'static str,
    pub permission_scope: &'static str,
    pub setup: &'static str,
    pub implemented: bool,
}

pub const CATALOG: &[CatalogEntry] = &[
    CatalogEntry {
        id: "web_search",
        name: "Web search (Tavily)",
        category: "Research",
        description: "Lets Atlas search the web and cite sources.",
        capabilities: &["web.search"],
        auth: "api_key",
        permission_scope: "Sends search queries (not conversations) to Tavily. Read-only.",
        setup: "Create a free key at app.tavily.com, paste it here, then run the connection test (uses 1 search credit).",
        implemented: true,
    },
    CatalogEntry { id: "email", name: "Email", category: "Communication", description: "Read and draft email; sending would always require approval.", capabilities: &[], auth: "oauth", permission_scope: "Planned: consequential actions require approval.", setup: "Not available in this version.", implemented: false },
    CatalogEntry { id: "calendar", name: "Calendar", category: "Productivity", description: "Read availability and propose events.", capabilities: &[], auth: "oauth", permission_scope: "Planned.", setup: "Not available in this version.", implemented: false },
    CatalogEntry { id: "tasks", name: "Task manager", category: "Productivity", description: "Sync tasks with an external task manager.", capabilities: &[], auth: "oauth", permission_scope: "Planned.", setup: "Not available in this version.", implemented: false },
    CatalogEntry { id: "cloud_files", name: "Cloud files", category: "Files", description: "Browse and import from cloud storage.", capabilities: &[], auth: "oauth", permission_scope: "Planned.", setup: "Not available in this version.", implemented: false },
    CatalogEntry { id: "git", name: "Git repositories", category: "Developer", description: "Inspect local repositories and diffs.", capabilities: &[], auth: "none", permission_scope: "Planned: read-only first.", setup: "Not available in this version.", implemented: false },
    CatalogEntry { id: "transcription", name: "Speech-to-text", category: "Voice", description: "Transcribe push-to-talk audio.", capabilities: &[], auth: "api_key", permission_scope: "Planned: audio is sent only when you hold the talk button.", setup: "Not available in this version.", implemented: false },
    CatalogEntry { id: "http_tools", name: "Custom HTTP tools", category: "Automation", description: "User-defined API tools with declared schemas, run as untrusted.", capabilities: &[], auth: "api_key", permission_scope: "Planned: each tool declares a permission class; consequential calls require approval.", setup: "Not available in this version.", implemented: false },
];

#[derive(Debug, Clone, Serialize)]
pub struct Integration {
    #[serde(flatten)]
    pub catalog: CatalogEntry,
    pub enabled: bool,
    pub status: String,
    pub status_detail: Option<String>,
    pub last_checked_at: Option<String>,
    pub has_credential: bool,
    pub key_hint: Option<String>,
    #[serde(skip)]
    pub config: Value,
}

fn entry(id: &str) -> Result<&'static CatalogEntry> {
    CATALOG.iter().find(|c| c.id == id).ok_or_else(|| AtlasError::NotFound(format!("integration '{id}'")))
}

pub fn get(db: &Db, id: &str) -> Result<Integration> {
    let c = entry(id)?;
    let row: Option<(i64, String, Option<String>, Option<String>, Option<String>, String)> = db
        .conn()?
        .query_row(
            "SELECT enabled, status, status_detail, last_checked_at, key_hint, config FROM integrations WHERE id = ?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)),
        )
        .map(Some)
        .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(e) })?;
    let (enabled, status, detail, checked, hint, config) =
        row.unwrap_or((0, if c.implemented { "not_configured".into() } else { "planned".into() }, None, None, None, "{}".into()));
    Ok(Integration {
        catalog: c.clone(),
        enabled: enabled != 0,
        status,
        status_detail: detail,
        last_checked_at: checked,
        has_credential: hint.is_some(),
        key_hint: hint,
        config: serde_json::from_str(&config).unwrap_or(Value::Null),
    })
}

pub fn list(db: &Db) -> Result<Vec<Integration>> {
    CATALOG.iter().map(|c| get(db, c.id)).collect()
}

fn ensure_row(db: &Db, id: &str) -> Result<()> {
    db.conn()?.execute("INSERT OR IGNORE INTO integrations(id) VALUES (?1)", [id])?;
    Ok(())
}

pub fn set_key(db: &Db, secrets: &SharedSecrets, id: &str, key: &str) -> Result<Integration> {
    let c = entry(id)?;
    if !c.implemented {
        return Err(AtlasError::Validation(format!("{} is not available in this version", c.name)));
    }
    let key = validate_secret(key)?;
    secrets.set(&integration_account(id), &key)?;
    ensure_row(db, id)?;
    db.conn()?.execute(
        "UPDATE integrations SET key_hint = ?1, status = 'untested', status_detail = NULL, enabled = 1 WHERE id = ?2",
        rusqlite::params![mask(&key), id],
    )?;
    get(db, id)
}

pub fn clear_key(db: &Db, secrets: &SharedSecrets, id: &str) -> Result<Integration> {
    entry(id)?;
    secrets.delete(&integration_account(id))?;
    ensure_row(db, id)?;
    db.conn()?.execute("UPDATE integrations SET key_hint = NULL, status = 'not_configured', enabled = 0 WHERE id = ?1", [id])?;
    get(db, id)
}

pub fn set_enabled(db: &Db, id: &str, enabled: bool) -> Result<Integration> {
    let c = entry(id)?;
    if enabled && !c.implemented {
        return Err(AtlasError::Validation(format!("{} is not available in this version", c.name)));
    }
    ensure_row(db, id)?;
    db.conn()?.execute("UPDATE integrations SET enabled = ?1 WHERE id = ?2", rusqlite::params![enabled as i64, id])?;
    get(db, id)
}

pub fn set_config(db: &Db, id: &str, config: &Value) -> Result<()> {
    entry(id)?;
    ensure_row(db, id)?;
    db.conn()?.execute("UPDATE integrations SET config = ?1 WHERE id = ?2", rusqlite::params![config.to_string(), id])?;
    Ok(())
}

pub fn set_status(db: &Db, id: &str, status: &str, detail: Option<&str>) -> Result<()> {
    ensure_row(db, id)?;
    db.conn()?.execute(
        "UPDATE integrations SET status = ?1, status_detail = ?2, last_checked_at = ?3 WHERE id = ?4",
        rusqlite::params![status, detail.map(crate::redact::redact), now(), id],
    )?;
    Ok(())
}
