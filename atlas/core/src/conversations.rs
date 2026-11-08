//! Conversations and messages.

use crate::ai::{ChatMessage, NativeContent, Part, Role};
use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Conversation {
    pub id: String,
    pub project_id: Option<String>,
    pub title: String,
    pub archived: bool,
    pub created_at: String,
    pub updated_at: String,
    pub message_count: i64,
    /// Set for Atlas Forge sessions.
    pub forge_project_id: Option<String>,
    pub discipline: Option<crate::forge::Discipline>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredMessage {
    pub id: String,
    pub conversation_id: String,
    pub seq: i64,
    /// user | assistant | tool | notice
    pub role: String,
    pub content: String,
    pub parts: Option<Vec<Part>>,
    #[serde(skip_serializing)]
    pub native: Option<NativeContent>,
    pub provider_id: Option<String>,
    pub model: Option<String>,
    pub status: String,
    pub task_id: Option<String>,
    pub usage: Option<Value>,
    pub created_at: String,
}

pub fn create(db: &Db, project_id: Option<&str>, title: &str) -> Result<Conversation> {
    let id = new_id();
    let t = now();
    let title = if title.trim().is_empty() { "New conversation" } else { title.trim() };
    db.conn()?.execute(
        "INSERT INTO conversations(id, project_id, title, created_at, updated_at) VALUES (?1,?2,?3,?4,?4)",
        rusqlite::params![id, project_id, crate::ai::truncate(title, 120), t],
    )?;
    get(db, &id)
}

const COLS: &str = "c.id, c.project_id, c.title, c.archived, c.created_at, c.updated_at,
  (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id AND m.role IN ('user','assistant')), c.forge_project_id, c.discipline";

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Conversation> {
    Ok(Conversation {
        id: r.get(0)?,
        project_id: r.get(1)?,
        title: r.get(2)?,
        archived: r.get::<_, i64>(3)? != 0,
        created_at: r.get(4)?,
        updated_at: r.get(5)?,
        message_count: r.get(6)?,
        forge_project_id: r.get(7)?,
        discipline: r.get::<_, Option<String>>(8)?.and_then(|d| crate::forge::Discipline::parse(&d)),
    })
}

/// Start an Atlas Forge session on a project in a discipline.
pub fn create_forge(db: &Db, forge_project_id: &str, discipline: crate::forge::Discipline, title: &str) -> Result<Conversation> {
    crate::forge::get_project(db, forge_project_id)?;
    let c = create(db, None, title)?;
    db.conn()?.execute(
        "UPDATE conversations SET forge_project_id = ?1, discipline = ?2 WHERE id = ?3",
        rusqlite::params![forge_project_id, discipline.as_str(), c.id],
    )?;
    get(db, &c.id)
}

pub fn set_discipline(db: &Db, id: &str, discipline: crate::forge::Discipline) -> Result<Conversation> {
    let c = get(db, id)?;
    if c.forge_project_id.is_none() {
        return Err(AtlasError::Validation("only Forge sessions have a discipline".into()));
    }
    db.conn()?.execute("UPDATE conversations SET discipline = ?1 WHERE id = ?2", rusqlite::params![discipline.as_str(), id])?;
    get(db, id)
}

pub fn list_forge(db: &Db, forge_project_id: &str, limit: u32) -> Result<Vec<Conversation>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM conversations c WHERE c.forge_project_id = ?1 ORDER BY c.updated_at DESC LIMIT ?2"))?;
    let rows = stmt.query_map(rusqlite::params![forge_project_id, limit], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn get(db: &Db, id: &str) -> Result<Conversation> {
    Ok(db.conn()?.query_row(&format!("SELECT {COLS} FROM conversations c WHERE c.id = ?1"), [id], row)?)
}

pub fn list(db: &Db, project_id: Option<&str>, include_archived: bool, limit: u32, offset: u32) -> Result<Vec<Conversation>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS} FROM conversations c WHERE (?1 IS NULL OR c.project_id = ?1) AND (?2 = 1 OR c.archived = 0) AND c.forge_project_id IS NULL
         ORDER BY c.updated_at DESC LIMIT ?3 OFFSET ?4"
    ))?;
    let rows = stmt.query_map(rusqlite::params![project_id, include_archived as i64, limit, offset], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn rename(db: &Db, id: &str, title: &str) -> Result<()> {
    let t = title.trim();
    if t.is_empty() || t.chars().count() > 120 {
        return Err(AtlasError::Validation("title must be 1-120 characters".into()));
    }
    db.conn()?.execute("UPDATE conversations SET title = ?1, updated_at = ?2 WHERE id = ?3", rusqlite::params![t, now(), id])?;
    Ok(())
}

pub fn set_archived(db: &Db, id: &str, archived: bool) -> Result<()> {
    db.conn()?.execute("UPDATE conversations SET archived = ?1 WHERE id = ?2", rusqlite::params![archived as i64, id])?;
    Ok(())
}

pub fn set_project(db: &Db, id: &str, project_id: Option<&str>) -> Result<()> {
    db.conn()?.execute("UPDATE conversations SET project_id = ?1 WHERE id = ?2", rusqlite::params![project_id, id])?;
    Ok(())
}

pub fn delete(db: &Db, id: &str) -> Result<()> {
    let n = db.conn()?.execute("DELETE FROM conversations WHERE id = ?1", [id])?;
    if n == 0 {
        return Err(AtlasError::NotFound("conversation".into()));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn append(
    db: &Db,
    conversation_id: &str,
    role: &str,
    content: &str,
    parts: Option<&[Part]>,
    native: Option<&NativeContent>,
    provider_id: Option<&str>,
    model: Option<&str>,
    status: &str,
    task_id: Option<&str>,
    usage: Option<&Value>,
) -> Result<String> {
    let id = new_id();
    db.tx(|tx| {
        let seq: i64 = tx.query_row(
            "SELECT COALESCE(max(seq), 0) + 1 FROM messages WHERE conversation_id = ?1",
            [conversation_id],
            |r| r.get(0),
        )?;
        let t = now();
        tx.execute(
            "INSERT INTO messages(id, conversation_id, seq, role, content, parts, native, provider_id, model, status, task_id, usage, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
            rusqlite::params![
                id,
                conversation_id,
                seq,
                role,
                content,
                parts.map(|p| serde_json::to_string(p).unwrap_or_default()),
                native.map(|n| serde_json::to_string(n).unwrap_or_default()),
                provider_id,
                model,
                status,
                task_id,
                usage.map(|u| u.to_string()),
                t
            ],
        )?;
        tx.execute("UPDATE conversations SET updated_at = ?1 WHERE id = ?2", rusqlite::params![t, conversation_id])?;
        Ok(())
    })?;
    Ok(id)
}

/// For "regenerate": remove the reply that followed the conversation's last user message and
/// return that message's text and id. Refused when the reply made tool calls (answering again
/// could repeat an action) or when there is nothing to answer.
pub fn take_last_reply(db: &Db, conversation_id: &str) -> Result<(String, String)> {
    let rows = messages(db, conversation_id)?;
    let Some(idx) = rows.iter().rposition(|m| m.role == "user") else {
        return Err(AtlasError::Validation("there is no message to answer again".into()));
    };
    let after = &rows[idx + 1..];
    let used_tools = after.iter().any(|m| {
        m.role == "tool" || m.parts.as_ref().is_some_and(|ps| ps.iter().any(|p| matches!(p, Part::ToolCall { .. })))
    });
    if used_tools {
        return Err(AtlasError::Conflict(
            "the last reply used tools, so answering again could repeat those actions; use Ask again instead".into(),
        ));
    }
    db.tx(|tx| {
        for m in after {
            tx.execute("DELETE FROM messages WHERE id = ?1 AND conversation_id = ?2", rusqlite::params![m.id, conversation_id])?;
        }
        Ok(())
    })?;
    Ok((rows[idx].content.clone(), rows[idx].id.clone()))
}

pub fn set_status(db: &Db, message_id: &str, status: &str) -> Result<()> {
    db.conn()?.execute("UPDATE messages SET status = ?1 WHERE id = ?2", rusqlite::params![status, message_id])?;
    Ok(())
}

fn msg_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<StoredMessage> {
    Ok(StoredMessage {
        id: r.get(0)?,
        conversation_id: r.get(1)?,
        seq: r.get(2)?,
        role: r.get(3)?,
        content: r.get(4)?,
        parts: r.get::<_, Option<String>>(5)?.and_then(|s| serde_json::from_str(&s).ok()),
        native: r.get::<_, Option<String>>(6)?.and_then(|s| serde_json::from_str(&s).ok()),
        provider_id: r.get(7)?,
        model: r.get(8)?,
        status: r.get(9)?,
        task_id: r.get(10)?,
        usage: r.get::<_, Option<String>>(11)?.and_then(|s| serde_json::from_str(&s).ok()),
        created_at: r.get(12)?,
    })
}

const MSG_COLS: &str = "id, conversation_id, seq, role, content, parts, native, provider_id, model, status, task_id, usage, created_at";

pub fn messages(db: &Db, conversation_id: &str) -> Result<Vec<StoredMessage>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {MSG_COLS} FROM messages WHERE conversation_id = ?1 ORDER BY seq"))?;
    let rows = stmt.query_map([conversation_id], msg_row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

#[derive(Debug, Clone, Serialize)]
pub struct SearchHit {
    pub conversation_id: String,
    pub conversation_title: String,
    pub message_id: String,
    pub snippet: String,
    pub created_at: String,
}

pub fn search(db: &Db, query: &str, limit: u32) -> Result<Vec<SearchHit>> {
    let terms = crate::memory::terms(query);
    if terms.is_empty() {
        return Ok(vec![]);
    }
    let q = terms.iter().map(|t| format!("\"{t}\"")).collect::<Vec<_>>().join(" AND ");
    let conn = db.conn()?;
    let mut stmt = conn.prepare(
        "SELECT m.conversation_id, c.title, m.id, snippet(messages_fts, 0, '[', ']', '…', 12), m.created_at
         FROM messages_fts JOIN messages m ON m.rowid = messages_fts.rowid JOIN conversations c ON c.id = m.conversation_id
         WHERE messages_fts MATCH ?1 AND m.role IN ('user','assistant') ORDER BY bm25(messages_fts) LIMIT ?2",
    )?;
    let rows = stmt.query_map(rusqlite::params![q, limit], |r| {
        Ok(SearchHit {
            conversation_id: r.get(0)?,
            conversation_title: r.get(1)?,
            message_id: r.get(2)?,
            snippet: r.get(3)?,
            created_at: r.get(4)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

/// Convert stored rows into provider-neutral history. `tool` rows become user-role tool results;
/// notices are UI-only and skipped.
pub fn to_history(rows: &[StoredMessage]) -> Vec<ChatMessage> {
    rows.iter()
        .filter_map(|m| {
            let role = match m.role.as_str() {
                "user" | "tool" => Role::User,
                "assistant" => Role::Assistant,
                _ => return None,
            };
            let parts = m.parts.clone().unwrap_or_else(|| vec![Part::Text { text: m.content.clone() }]);
            Some(ChatMessage { role, parts, native: m.native.clone() })
        })
        .collect()
}

/// Apply the retention setting: delete non-archived conversations not updated in `days`.
pub fn apply_retention(db: &Db, days: u32) -> Result<usize> {
    let cutoff = (chrono::Utc::now() - chrono::Duration::days(days as i64)).to_rfc3339();
    Ok(db.conn()?.execute("DELETE FROM conversations WHERE archived = 0 AND updated_at < ?1", [cutoff])?)
}
