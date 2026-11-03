//! Projects scope conversations, memories and instructions.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub description: String,
    pub instructions: String,
    pub archived: bool,
    pub created_at: String,
    pub updated_at: String,
    pub conversation_count: i64,
    pub memory_count: i64,
}

fn validate(name: &str, description: &str, instructions: &str) -> Result<()> {
    if name.trim().is_empty() || name.chars().count() > 80 {
        return Err(AtlasError::Validation("project name must be 1-80 characters".into()));
    }
    if description.chars().count() > 2000 || instructions.chars().count() > 8000 {
        return Err(AtlasError::Validation("description or instructions too long".into()));
    }
    Ok(())
}

pub fn create(db: &Db, name: &str, description: &str, instructions: &str) -> Result<Project> {
    validate(name, description, instructions)?;
    let id = new_id();
    let t = now();
    db.conn()?.execute(
        "INSERT INTO projects(id, name, description, instructions, created_at, updated_at) VALUES (?1,?2,?3,?4,?5,?5)",
        rusqlite::params![id, name.trim(), description, instructions, t],
    )?;
    get(db, &id)
}

pub fn update(db: &Db, id: &str, name: &str, description: &str, instructions: &str, archived: bool) -> Result<Project> {
    validate(name, description, instructions)?;
    let n = db.conn()?.execute(
        "UPDATE projects SET name = ?1, description = ?2, instructions = ?3, archived = ?4, updated_at = ?5 WHERE id = ?6",
        rusqlite::params![name.trim(), description, instructions, archived as i64, now(), id],
    )?;
    if n == 0 {
        return Err(AtlasError::NotFound("project".into()));
    }
    get(db, id)
}

/// Deletes the project and its memories. Conversations are kept but detached.
pub fn delete(db: &Db, id: &str) -> Result<()> {
    let n = db.conn()?.execute("DELETE FROM projects WHERE id = ?1", [id])?;
    if n == 0 {
        return Err(AtlasError::NotFound("project".into()));
    }
    Ok(())
}

const COLS: &str = "p.id, p.name, p.description, p.instructions, p.archived, p.created_at, p.updated_at,
  (SELECT count(*) FROM conversations c WHERE c.project_id = p.id),
  (SELECT count(*) FROM memories m WHERE m.project_id = p.id)";

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Project> {
    Ok(Project {
        id: r.get(0)?,
        name: r.get(1)?,
        description: r.get(2)?,
        instructions: r.get(3)?,
        archived: r.get::<_, i64>(4)? != 0,
        created_at: r.get(5)?,
        updated_at: r.get(6)?,
        conversation_count: r.get(7)?,
        memory_count: r.get(8)?,
    })
}

pub fn get(db: &Db, id: &str) -> Result<Project> {
    Ok(db.conn()?.query_row(&format!("SELECT {COLS} FROM projects p WHERE p.id = ?1"), [id], row)?)
}

pub fn list(db: &Db, include_archived: bool) -> Result<Vec<Project>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS} FROM projects p WHERE (?1 = 1 OR p.archived = 0) ORDER BY p.archived, p.updated_at DESC"
    ))?;
    let rows = stmt.query_map([include_archived as i64], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}
