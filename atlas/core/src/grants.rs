//! File grants: individual files outside the workspace that the user explicitly picked in a
//! native file dialog. Only the desktop shell's dialog command creates grants.

use crate::error::Result;
use crate::storage::{new_id, now, Db};
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct Grant {
    pub id: String,
    pub path: String,
    pub label: String,
    pub created_at: String,
}

pub fn add(db: &Db, path: &std::path::Path) -> Result<Grant> {
    let canon = path.canonicalize()?;
    let label = canon.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "file".into());
    let id = new_id();
    db.conn()?.execute(
        "INSERT INTO file_grants(id, path, label, created_at) VALUES (?1,?2,?3,?4)",
        rusqlite::params![id, canon.to_string_lossy(), label, now()],
    )?;
    get(db, &id)
}

pub fn get(db: &Db, id: &str) -> Result<Grant> {
    Ok(db.conn()?.query_row("SELECT id, path, label, created_at FROM file_grants WHERE id = ?1", [id], |r| {
        Ok(Grant { id: r.get(0)?, path: r.get(1)?, label: r.get(2)?, created_at: r.get(3)? })
    })?)
}

pub fn list(db: &Db) -> Result<Vec<Grant>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare("SELECT id, path, label, created_at FROM file_grants ORDER BY created_at DESC")?;
    let rows = stmt.query_map([], |r| Ok(Grant { id: r.get(0)?, path: r.get(1)?, label: r.get(2)?, created_at: r.get(3)? }))?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn revoke(db: &Db, id: &str) -> Result<()> {
    db.conn()?.execute("DELETE FROM file_grants WHERE id = ?1", [id])?;
    Ok(())
}
