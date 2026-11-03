//! Content-free audit log: ids, tool names, durations, outcomes. Never message text or secrets.

use crate::storage::{now, Db};
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Clone, Serialize)]
pub struct AuditEvent {
    pub id: i64,
    pub ts: String,
    pub kind: String,
    pub level: String,
    pub task_id: Option<String>,
    pub tool_id: Option<String>,
    pub detail: Value,
}

pub fn record(db: &Db, kind: &str, level: &str, task_id: Option<&str>, tool_id: Option<&str>, detail: Value) {
    let detail = crate::redact::redact(&detail.to_string());
    // Audit failures must never break the operation being audited.
    if let Ok(conn) = db.conn() {
        let _ = conn.execute(
            "INSERT INTO audit_events(ts, kind, level, task_id, tool_id, detail) VALUES (?1,?2,?3,?4,?5,?6)",
            rusqlite::params![now(), kind, level, task_id, tool_id, detail],
        );
        // Keep the log bounded.
        let _ = conn.execute(
            "DELETE FROM audit_events WHERE id <= (SELECT max(id) FROM audit_events) - 20000",
            [],
        );
    }
}

pub fn recent(db: &Db, limit: u32, level: Option<&str>) -> crate::error::Result<Vec<AuditEvent>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(
        "SELECT id, ts, kind, level, task_id, tool_id, detail FROM audit_events
         WHERE (?1 IS NULL OR level = ?1) ORDER BY id DESC LIMIT ?2",
    )?;
    let rows = stmt.query_map(rusqlite::params![level, limit], |r| {
        Ok(AuditEvent {
            id: r.get(0)?,
            ts: r.get(1)?,
            kind: r.get(2)?,
            level: r.get(3)?,
            task_id: r.get(4)?,
            tool_id: r.get(5)?,
            detail: serde_json::from_str(&r.get::<_, String>(6)?).unwrap_or(Value::Null),
        })
    })?;
    Ok(rows.collect::<Result<_, _>>()?)
}
