//! Content-free audit log: what happened, who started it, what it touched (by id or name), whether
//! data left the device, whether approval was involved, and how it ended. Never message text,
//! document text, memory text, prompts or secrets: `detail` is redacted and holds counts, ids and
//! labels only. The Trust Center reads this log; nothing reading it can trigger an operation.

use crate::storage::{now, Db};
use serde::Serialize;
use serde_json::Value;

/// Most events kept; older ones are dropped (and the retention setting can drop them sooner).
pub const MAX_EVENTS: i64 = 50_000;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct AuditEvent {
    pub id: i64,
    pub ts: String,
    pub kind: String,
    pub level: String,
    pub task_id: Option<String>,
    pub tool_id: Option<String>,
    pub detail: Value,
    /// knowledge, memory, tools, forge, providers, approvals, sibling, specialists, background, voice, settings, trust, system
    pub category: String,
    /// user, atlas (on its own), assistant (the model, through a tool), sibling
    pub actor: String,
    pub resource: Option<String>,
    pub project_id: Option<String>,
    pub provider: Option<String>,
    pub model: Option<String>,
    /// True when data was sent off this computer (to a cloud model or a network tool).
    pub left_device: bool,
    /// requested, approved, declined, expired, not_needed
    pub approval: Option<String>,
    /// ok, warning, failed, denied, cancelled
    pub outcome: String,
    pub reversible: Option<bool>,
}

/// The Trust Center category of an event kind (also used to classify events recorded before v8).
pub fn category_for(kind: &str) -> &'static str {
    let prefix = kind.split('.').next().unwrap_or("");
    match prefix {
        "vault" => "knowledge",
        "memory" => "memory",
        "tool" | "file" => "tools",
        "forge" => "forge",
        "provider" | "credential" => "providers",
        "approval" => "approvals",
        "mission" | "missions" | "sibling" => "sibling",
        "scheduler" | "focus" | "todo" | "tasks" => "background",
        "voice" => "voice",
        "settings" | "desktop" | "backup" | "permission" => "settings",
        "trust" => "trust",
        "specialist" => "specialists",
        _ => "system",
    }
}

/// A structured event. `kind` is the specific name ("vault.import"); the rest is optional.
#[derive(Debug, Clone, Default)]
pub struct Event<'a> {
    pub kind: &'a str,
    pub level: &'a str,
    pub actor: &'a str,
    pub resource: Option<&'a str>,
    pub project_id: Option<&'a str>,
    pub provider: Option<&'a str>,
    pub model: Option<&'a str>,
    pub left_device: bool,
    pub approval: Option<&'a str>,
    pub outcome: &'a str,
    pub reversible: Option<bool>,
    /// Stable key for operations that can be retried: the same key is recorded once.
    pub op_key: Option<&'a str>,
    pub task_id: Option<&'a str>,
    pub tool_id: Option<&'a str>,
    pub detail: Value,
}

pub fn event(db: &Db, e: Event<'_>) {
    let detail = crate::redact::redact(&if e.detail.is_null() { serde_json::json!({}) } else { e.detail.clone() }.to_string());
    let level = if e.level.is_empty() { "info" } else { e.level };
    let actor = if e.actor.is_empty() { "atlas" } else { e.actor };
    let outcome = if e.outcome.is_empty() { if level == "info" { "ok" } else { "warning" } } else { e.outcome };
    let clip = |s: Option<&str>| s.map(|x| crate::redact::redact(x).chars().take(200).collect::<String>());
    // Audit failures must never break the operation being audited.
    if let Ok(conn) = db.conn() {
        let _ = conn.execute(
            "INSERT OR IGNORE INTO audit_events(ts, kind, level, task_id, tool_id, detail, category, actor, resource, project_id, provider, model, left_device, approval, outcome, reversible, op_key)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17)",
            rusqlite::params![
                now(),
                e.kind,
                level,
                e.task_id,
                e.tool_id,
                detail,
                category_for(e.kind),
                actor,
                clip(e.resource),
                e.project_id,
                clip(e.provider),
                clip(e.model),
                e.left_device,
                e.approval,
                outcome,
                e.reversible,
                e.op_key
            ],
        );
        let _ = conn.execute("DELETE FROM audit_events WHERE id <= (SELECT max(id) FROM audit_events) - ?1", [MAX_EVENTS]);
    }
}

/// The simple form used throughout the core: classified by its kind, started by Atlas.
pub fn record(db: &Db, kind: &str, level: &str, task_id: Option<&str>, tool_id: Option<&str>, detail: Value) {
    event(db, Event { kind, level, task_id, tool_id, detail, ..Default::default() });
}

const COLS: &str = "id, ts, kind, level, task_id, tool_id, detail, category, actor, resource, project_id, provider, model, left_device, approval, outcome, reversible";

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<AuditEvent> {
    Ok(AuditEvent {
        id: r.get(0)?,
        ts: r.get(1)?,
        kind: r.get(2)?,
        level: r.get(3)?,
        task_id: r.get(4)?,
        tool_id: r.get(5)?,
        detail: serde_json::from_str(&r.get::<_, String>(6)?).unwrap_or(Value::Null),
        category: r.get(7)?,
        actor: r.get(8)?,
        resource: r.get(9)?,
        project_id: r.get(10)?,
        provider: r.get(11)?,
        model: r.get(12)?,
        left_device: r.get(13)?,
        approval: r.get(14)?,
        outcome: r.get(15)?,
        reversible: r.get(16)?,
    })
}

pub fn recent(db: &Db, limit: u32, level: Option<&str>) -> crate::error::Result<Vec<AuditEvent>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM audit_events WHERE (?1 IS NULL OR level = ?1) ORDER BY id DESC LIMIT ?2"))?;
    let rows = stmt.query_map(rusqlite::params![level, limit], row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub struct PageFilter {
    pub category: Option<String>,
    /// Words matched against the event name, resource, provider and model (never content).
    pub search: Option<String>,
    pub left_device_only: bool,
    /// ok | problems (anything not ok)
    pub outcome: Option<String>,
    /// Return events older than this id (keyset pagination).
    pub before_id: Option<i64>,
    pub limit: Option<u32>,
}

/// One page of the log, newest first. Never the whole table.
pub fn page(db: &Db, f: &PageFilter) -> crate::error::Result<Vec<AuditEvent>> {
    let conn = db.conn()?;
    let like = f.search.as_deref().map(str::trim).filter(|s| !s.is_empty()).map(|s| format!("%{}%", s.replace(['%', '_'], "")));
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS} FROM audit_events
         WHERE (?1 IS NULL OR category = ?1)
           AND (?2 IS NULL OR kind LIKE ?2 OR resource LIKE ?2 OR provider LIKE ?2 OR model LIKE ?2)
           AND (?3 = 0 OR left_device = 1)
           AND (?4 IS NULL OR (?4 = 'problems' AND outcome <> 'ok') OR outcome = ?4)
           AND (?5 IS NULL OR id < ?5)
         ORDER BY id DESC LIMIT ?6"
    ))?;
    let rows = stmt.query_map(rusqlite::params![f.category, like, f.left_device_only, f.outcome, f.before_id, f.limit.unwrap_or(50).clamp(1, 200)], row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn events_are_classified_redacted_paged_and_recorded_once_per_key() {
        let db = Db::open_in_memory().unwrap();
        record(&db, "vault.import", "info", None, None, serde_json::json!({"note": "key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}));
        for _ in 0..3 {
            event(&db, Event { kind: "provider.request", provider: Some("Claude"), model: Some("m"), left_device: true, op_key: Some("turn-1/step-1"), ..Default::default() });
        }
        for i in 0..60 {
            record(&db, "tool.step", "warn", None, Some("files.read"), serde_json::json!({ "i": i }));
        }
        let all = page(&db, &PageFilter { limit: Some(200), ..Default::default() }).unwrap();
        assert_eq!(all.len(), 62, "the keyed event was recorded once");
        let v = all.iter().find(|e| e.kind == "vault.import").unwrap();
        assert_eq!(v.category, "knowledge");
        assert!(!v.detail.to_string().contains("sk-ant"), "secrets never reach the log: {}", v.detail);
        let remote = page(&db, &PageFilter { left_device_only: true, ..Default::default() }).unwrap();
        assert_eq!((remote.len(), remote[0].provider.as_deref()), (1, Some("Claude")));
        let first = page(&db, &PageFilter { limit: Some(25), ..Default::default() }).unwrap();
        let second = page(&db, &PageFilter { limit: Some(25), before_id: first.last().map(|e| e.id), ..Default::default() }).unwrap();
        assert_eq!(second.len(), 25);
        assert!(second.iter().all(|e| e.id < first.last().unwrap().id), "pages do not overlap");
        assert_eq!(page(&db, &PageFilter { outcome: Some("problems".into()), limit: Some(200), ..Default::default() }).unwrap().len(), 60);
        assert_eq!(page(&db, &PageFilter { search: Some("files.read".into()), ..Default::default() }).unwrap().len(), 0, "search covers names and resources, not details");
        assert_eq!(page(&db, &PageFilter { search: Some("Claude".into()), ..Default::default() }).unwrap().len(), 1);
        assert_eq!(category_for("forge.commit"), "forge");
        assert_eq!(category_for("weird"), "system");
    }
}
