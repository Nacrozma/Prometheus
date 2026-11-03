//! Persistent memory under user control. Memories are only created by the user, or by the
//! assistant through the approval-gated `memory.save` tool. Credentials are refused.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MemoryKind {
    Preference,
    Fact,
    Note,
}

impl MemoryKind {
    fn as_str(self) -> &'static str {
        match self {
            MemoryKind::Preference => "preference",
            MemoryKind::Fact => "fact",
            MemoryKind::Note => "note",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Memory {
    pub id: String,
    pub project_id: Option<String>,
    pub kind: MemoryKind,
    pub content: String,
    pub source: String,
    pub pinned: bool,
    pub use_count: i64,
    pub last_used_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

/// A memory selected for a request, with the reason it was selected.
#[derive(Debug, Clone, Serialize)]
pub struct Retrieved {
    pub memory: Memory,
    pub reason: String,
    pub score: f64,
}

pub const MAX_MEMORY_CHARS: usize = 2000;

pub fn validate_content(content: &str) -> Result<String> {
    let c = content.trim();
    if c.is_empty() {
        return Err(AtlasError::Validation("memory is empty".into()));
    }
    if c.chars().count() > MAX_MEMORY_CHARS {
        return Err(AtlasError::Validation(format!("memory is longer than {MAX_MEMORY_CHARS} characters")));
    }
    if crate::redact::contains_secret(c) {
        return Err(AtlasError::PermissionDenied(
            "this looks like it contains a password or API key; Atlas never stores credentials as memories".into(),
        ));
    }
    Ok(c.to_string())
}

pub fn create(db: &Db, project_id: Option<&str>, kind: MemoryKind, content: &str, source: &str, pinned: bool) -> Result<Memory> {
    let content = validate_content(content)?;
    let id = new_id();
    let t = now();
    db.conn()?.execute(
        "INSERT INTO memories(id, project_id, kind, content, source, pinned, created_at, updated_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?7)",
        rusqlite::params![id, project_id, kind.as_str(), content, source, pinned as i64, t],
    )?;
    get(db, &id)
}

pub fn update(db: &Db, id: &str, content: Option<&str>, kind: Option<MemoryKind>, pinned: Option<bool>, project_id: Option<Option<&str>>) -> Result<Memory> {
    let current = get(db, id)?;
    let content = match content {
        Some(c) => validate_content(c)?,
        None => current.content,
    };
    let kind = kind.unwrap_or(current.kind);
    let pinned = pinned.unwrap_or(current.pinned);
    let project = match project_id {
        Some(p) => p.map(str::to_string),
        None => current.project_id,
    };
    db.conn()?.execute(
        "UPDATE memories SET content = ?1, kind = ?2, pinned = ?3, project_id = ?4, updated_at = ?5 WHERE id = ?6",
        rusqlite::params![content, kind.as_str(), pinned as i64, project, now(), id],
    )?;
    get(db, id)
}

/// Permanent deletion: the row and its full-text index entry are removed.
pub fn delete(db: &Db, id: &str) -> Result<()> {
    let n = db.conn()?.execute("DELETE FROM memories WHERE id = ?1", [id])?;
    if n == 0 {
        return Err(AtlasError::NotFound("memory".into()));
    }
    Ok(())
}

pub fn delete_all(db: &Db) -> Result<usize> {
    Ok(db.conn()?.execute("DELETE FROM memories", [])?)
}

const COLS: &str = "m.id, m.project_id, m.kind, m.content, m.source, m.pinned, m.use_count, m.last_used_at, m.created_at, m.updated_at";

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Memory> {
    let kind: String = r.get(2)?;
    Ok(Memory {
        id: r.get(0)?,
        project_id: r.get(1)?,
        kind: match kind.as_str() {
            "preference" => MemoryKind::Preference,
            "fact" => MemoryKind::Fact,
            _ => MemoryKind::Note,
        },
        content: r.get(3)?,
        source: r.get(4)?,
        pinned: r.get::<_, i64>(5)? != 0,
        use_count: r.get(6)?,
        last_used_at: r.get(7)?,
        created_at: r.get(8)?,
        updated_at: r.get(9)?,
    })
}

pub fn get(db: &Db, id: &str) -> Result<Memory> {
    Ok(db.conn()?.query_row(&format!("SELECT {COLS} FROM memories m WHERE m.id = ?1"), [id], row)?)
}

/// `project`: None = all memories; Some(None) = global only; Some(Some(id)) = that project only.
pub fn list(db: &Db, project: Option<Option<&str>>) -> Result<Vec<Memory>> {
    let conn = db.conn()?;
    let (sql, param): (String, Option<String>) = match project {
        None => (format!("SELECT {COLS} FROM memories m ORDER BY m.pinned DESC, m.updated_at DESC"), None),
        Some(None) => (format!("SELECT {COLS} FROM memories m WHERE m.project_id IS NULL ORDER BY m.pinned DESC, m.updated_at DESC"), None),
        Some(Some(p)) => (format!("SELECT {COLS} FROM memories m WHERE m.project_id = ?1 ORDER BY m.pinned DESC, m.updated_at DESC"), Some(p.to_string())),
    };
    let mut stmt = conn.prepare(&sql)?;
    let rows = match param {
        Some(p) => stmt.query_map([p], row)?.collect::<std::result::Result<Vec<_>, _>>()?,
        None => stmt.query_map([], row)?.collect::<std::result::Result<Vec<_>, _>>()?,
    };
    Ok(rows)
}

const STOPWORDS: &[&str] = &[
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for", "with", "at",
    "by", "it", "this", "that", "i", "you", "me", "my", "your", "we", "can", "could", "would", "should", "what", "how",
    "do", "does", "did", "please", "about", "from", "as", "so", "if", "then", "there", "have", "has", "had", "will",
];

/// Extract search terms from free text for an FTS5 OR query (quoted to neutralise syntax).
pub fn terms(text: &str) -> Vec<String> {
    let mut out: Vec<String> = text
        .split(|c: char| !c.is_alphanumeric())
        .map(str::to_lowercase)
        .filter(|w| w.chars().count() >= 3 && !STOPWORDS.contains(&w.as_str()))
        .collect();
    out.sort();
    out.dedup();
    out.truncate(24);
    out
}

/// Relevance search. Scope: global memories plus the given project's memories.
pub fn search(db: &Db, query: &str, project_id: Option<&str>, limit: u32) -> Result<Vec<Retrieved>> {
    let ts = terms(query);
    if ts.is_empty() {
        return Ok(vec![]);
    }
    let fts_query = ts.iter().map(|t| format!("\"{t}\"")).collect::<Vec<_>>().join(" OR ");
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS}, bm25(memories_fts) AS score FROM memories_fts
         JOIN memories m ON m.rowid = memories_fts.rowid
         WHERE memories_fts MATCH ?1 AND (m.project_id IS NULL OR m.project_id = ?2)
         ORDER BY m.pinned DESC, score LIMIT ?3"
    ))?;
    let rows = stmt.query_map(rusqlite::params![fts_query, project_id, limit], |r| Ok((row(r)?, r.get::<_, f64>(10)?)))?;
    let mut out = Vec::new();
    for item in rows {
        let (m, score) = item?;
        let lower = m.content.to_lowercase();
        let matched: Vec<&str> = ts.iter().filter(|t| lower.contains(t.as_str())).map(String::as_str).take(5).collect();
        let reason = if matched.is_empty() {
            "related wording".to_string()
        } else {
            format!("matches “{}”", matched.join("”, “"))
        };
        out.push(Retrieved { memory: m, reason, score: -score });
    }
    Ok(out)
}

/// Pinned memories are always eligible for context (still bounded by `max_retrieved`).
pub fn pinned(db: &Db, project_id: Option<&str>) -> Result<Vec<Memory>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS} FROM memories m WHERE m.pinned = 1 AND (m.project_id IS NULL OR m.project_id = ?1) ORDER BY m.updated_at DESC LIMIT 20"
    ))?;
    let rows = stmt.query_map([project_id], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn mark_used(db: &Db, ids: &[String]) {
    if let Ok(conn) = db.conn() {
        for id in ids {
            let _ = conn.execute(
                "UPDATE memories SET use_count = use_count + 1, last_used_at = ?1 WHERE id = ?2",
                rusqlite::params![now(), id],
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crud_search_scope_and_deletion() {
        let db = Db::open_in_memory().unwrap();
        let p = crate::projects::create(&db, "Garden", "", "").unwrap();
        let g = create(&db, None, MemoryKind::Preference, "Prefers metric units for measurements", "user", false).unwrap();
        create(&db, Some(&p.id), MemoryKind::Fact, "The tomato beds get afternoon sun", "user", false).unwrap();
        let other = crate::projects::create(&db, "Other", "", "").unwrap();
        create(&db, Some(&other.id), MemoryKind::Fact, "Tomato prices rose in spring", "user", false).unwrap();

        let r = search(&db, "where should the tomato go?", Some(&p.id), 5).unwrap();
        assert_eq!(r.len(), 1, "other projects' memories must not leak: {r:?}");
        assert!(r[0].reason.contains("tomato"));

        let r = search(&db, "which units for measurements", None, 5).unwrap();
        assert_eq!(r[0].memory.id, g.id);

        update(&db, &g.id, Some("Prefers imperial units"), None, Some(true), None).unwrap();
        assert!(search(&db, "metric", None, 5).unwrap().is_empty(), "FTS index follows edits");
        delete(&db, &g.id).unwrap();
        assert!(search(&db, "imperial", None, 5).unwrap().is_empty(), "deleted memories are gone from search");
        assert!(get(&db, &g.id).is_err());
    }

    #[test]
    fn refuses_secrets_and_fts_syntax_is_neutralised() {
        let db = Db::open_in_memory().unwrap();
        assert_eq!(
            create(&db, None, MemoryKind::Note, "my api_key=sk-ant-abcdefghijklmnop", "user", false).unwrap_err().code(),
            "permission_denied"
        );
        create(&db, None, MemoryKind::Note, "quotes and stars", "user", false).unwrap();
        assert!(search(&db, "\"quotes\" AND * NEAR(", None, 5).is_ok());
    }
}
