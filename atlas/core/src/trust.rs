//! The Trust Center: what Atlas does, built only from what Atlas recorded (the audit log, usage
//! records, settings, providers, grants, the scheduler, the Knowledge Vault, running work). Nothing
//! here is simulated and nothing here can start an operation: it reads records and describes the
//! controls the core already enforces. Changing a control goes through the ordinary, validated
//! commands (settings, providers, grants), never through this module.

use crate::error::Result;
use crate::settings::{GatePolicy, Settings};
use crate::storage::Db;
use serde::Serialize;
use serde_json::{json, Value};

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CategoryCount {
    pub category: String,
    pub events: i64,
    pub problems: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ProviderSummary {
    pub id: String,
    pub label: String,
    pub kind: String,
    pub local: bool,
    pub enabled: bool,
    pub is_default: bool,
    pub requests_30d: i64,
    pub failed_30d: i64,
    /// Sums of what the provider reported (requests that reported no count are not included).
    pub input_tokens_30d: i64,
    pub output_tokens_30d: i64,
    /// Atlas's estimate from its price table; providers do not report cost to Atlas.
    pub estimated_cost_usd_30d: f64,
    pub unpriced_requests_30d: i64,
    pub last_used_at: Option<String>,
}

/// A permission Atlas enforces in the core, how it is set now, and how to change it.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Permission {
    pub id: String,
    pub name: String,
    pub allows: String,
    /// What it is set to now, in words.
    pub status: String,
    /// Whether it currently lets something happen without asking (for at-a-glance review).
    pub open: bool,
    pub scope: String,
    pub component: String,
    pub last_used_at: Option<String>,
    /// How the owner changes it: {"kind": "gate"|"switch", "setting": "permissions.local_write"},
    /// {"kind": "provider", "provider_id": …}, {"kind": "grant", "grant_id": …}, or
    /// {"kind": "page", "route": …} when it is managed on another page.
    pub control: Value,
}

fn last_ts(db: &Db, sql: &str, p: &[&dyn rusqlite::ToSql]) -> Option<String> {
    db.conn().ok()?.query_row(sql, p, |r| r.get::<_, Option<String>>(0)).ok().flatten()
}

pub fn category_counts(db: &Db, since: &str) -> Result<Vec<CategoryCount>> {
    let conn = db.conn()?;
    let mut st = conn.prepare("SELECT category, COUNT(*), SUM(outcome <> 'ok') FROM audit_events WHERE ts >= ?1 GROUP BY category ORDER BY COUNT(*) DESC")?;
    Ok(st.query_map([since], |r| Ok(CategoryCount { category: r.get(0)?, events: r.get(1)?, problems: r.get::<_, Option<i64>>(2)?.unwrap_or(0) }))?.collect::<std::result::Result<_, _>>()?)
}

pub fn providers(db: &Db, settings: &Settings, list: &[crate::providers::ProviderConfig], since: &str) -> Result<Vec<ProviderSummary>> {
    let conn = db.conn()?;
    let mut out = Vec::new();
    for p in list {
        let (req, failed, inp, outp, cost, unpriced, last): (i64, i64, i64, i64, f64, i64, Option<String>) = conn.query_row(
            "SELECT COUNT(*), COALESCE(SUM(outcome <> 'ok'),0), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(estimated_cost_usd),0), COALESCE(SUM(estimated_cost_usd IS NULL),0), MAX(ts)
             FROM usage_records WHERE provider_id = ?1 AND ts >= ?2",
            rusqlite::params![p.id, since],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?)),
        )?;
        out.push(ProviderSummary {
            id: p.id.clone(),
            label: p.label.clone(),
            kind: serde_json::to_value(p.kind).ok().and_then(|v| v.as_str().map(str::to_string)).unwrap_or_default(),
            local: p.local,
            enabled: p.enabled,
            is_default: settings.default_provider_id.as_deref() == Some(p.id.as_str()),
            requests_30d: req,
            failed_30d: failed,
            input_tokens_30d: inp,
            output_tokens_30d: outp,
            estimated_cost_usd_30d: cost,
            unpriced_requests_30d: unpriced,
            last_used_at: last,
        });
    }
    Ok(out)
}

fn gate(db: &Db, id: &str, name: &str, allows: &str, g: GatePolicy, component: &str, last_kind_tools: &[String]) -> Permission {
    let last = if last_kind_tools.is_empty() {
        None
    } else {
        let placeholders = last_kind_tools.iter().map(|t| format!("'{}'", t.replace('\'', ""))).collect::<Vec<_>>().join(",");
        last_ts(db, &format!("SELECT MAX(ts) FROM audit_events WHERE kind = 'tool.step' AND tool_id IN ({placeholders}) AND outcome = 'ok'"), &[])
    };
    Permission {
        id: id.into(),
        name: name.into(),
        allows: allows.into(),
        status: match g {
            GatePolicy::Ask => "Asks you each time".into(),
            GatePolicy::Allow => "Allowed without asking".into(),
        },
        open: g == GatePolicy::Allow,
        scope: "All conversations".into(),
        component: component.into(),
        last_used_at: last,
        control: json!({ "kind": "gate", "setting": format!("permissions.{id}") }),
    }
}

#[allow(clippy::too_many_arguments)]
fn switch(id: &str, name: &str, allows: &str, on: bool, on_text: &str, off_text: &str, open_when_on: bool, component: &str, setting: &str, last: Option<String>) -> Permission {
    Permission {
        id: id.into(),
        name: name.into(),
        allows: allows.into(),
        status: if on { on_text.into() } else { off_text.into() },
        open: on == open_when_on,
        scope: "This computer".into(),
        component: component.into(),
        last_used_at: last,
        control: json!({ "kind": "switch", "setting": setting }),
    }
}

/// Tool ids by permission class, so a gate's "last used" is the last tool it governed.
pub struct ToolClasses {
    pub local_write: Vec<String>,
    pub network: Vec<String>,
    pub planner: Vec<String>,
}

pub fn permissions(db: &Db, s: &Settings, providers: &[crate::providers::ProviderConfig], classes: &ToolClasses) -> Result<Vec<Permission>> {
    let mut out = vec![
        gate(db, "local_write", "Changes on this computer", "Atlas creating or changing files, notes and memories through its tools.", s.permissions.local_write, "Tools", &classes.local_write),
        gate(db, "network_tools", "Tools that use the internet", "Atlas sending a query to an online service (for example web search).", s.permissions.network_tools, "Tools", &classes.network),
        gate(db, "planner", "Changes to your task list", "Atlas adding, editing or completing tasks during a conversation. Deleting a task always asks.", s.permissions.planner, "Tasks", &classes.planner),
        switch("offline_mode", "Offline mode", "When on, no cloud model and no internet tool is contacted.", s.network.offline_mode, "On: nothing leaves this computer", "Off: cloud models and internet tools may be used", false, "Network", "network.offline_mode",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE left_device = 1", &[])),
        switch("memory", "Memory in conversations", "Relevant saved memories are added to your messages.", s.memory.enabled, "On", "Off", true, "Memory", "memory.enabled",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE kind = 'memory.used'", &[])),
        switch("memory_proposals", "Memory suggestions from Atlas", "Atlas may suggest something to remember; each suggestion needs your approval.", s.memory.atlas_may_propose, "On (each one asks)", "Off: only you add memories", true, "Memory", "memory.atlas_may_propose",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE kind = 'memory.created' AND actor = 'assistant'", &[])),
        switch("vault", "Knowledge Vault in conversations", "Relevant passages from your documents are added to your messages.", s.vault.use_in_chat, "On", "Off", true, "Knowledge Vault", "vault.use_in_chat",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE kind = 'vault.passages'", &[])),
        switch("vault_local_only", "Knowledge Vault: local-only", "When on, document passages are only given to a model running on this computer.", s.vault.local_only, "On", "Off: passages may go to the model you use", false, "Knowledge Vault", "vault.local_only",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE kind = 'vault.passages' AND left_device = 1", &[])),
        switch("schedule", "Background activity", "Reminders, due-today notices and the daily briefing run on their own.", !s.schedule.paused, "Running", "Paused", true, "Scheduler", "schedule.paused",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE kind = 'scheduler.ran'", &[])),
        switch("notifications", "System notifications", "Atlas may show notifications outside its window.", s.desktop.notifications.system, "Allowed", "Off", true, "Desktop", "desktop.notifications.system", None),
        switch("shortcut", "Global shortcut", "A keyboard shortcut that brings Atlas forward from any app.", s.desktop.shortcut_enabled, "On", "Off", true, "Desktop", "desktop.shortcut_enabled", None),
        switch("voice", "Voice (microphone and speech)", "Push-to-talk listening and reading replies aloud, all on this computer.", s.voice.enabled, "On", "Off", true, "Voice", "voice.enabled",
            last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE category = 'voice'", &[])),
    ];
    for p in providers {
        out.push(Permission {
            id: format!("provider:{}", p.id),
            name: format!("Model provider: {}", p.label),
            allows: if p.local { "Your messages are processed by a model on this computer.".into() } else { "Your messages, and any memories or document passages attached, are sent to this cloud service.".into() },
            status: if p.enabled { "Enabled".into() } else { "Disabled".into() },
            open: p.enabled && !p.local,
            scope: if p.local { "This computer".into() } else { "Leaves this computer".into() },
            component: "Providers".into(),
            last_used_at: last_ts(db, "SELECT MAX(ts) FROM usage_records WHERE provider_id = ?1", &[&p.id]),
            control: json!({ "kind": "provider", "provider_id": p.id }),
        });
    }
    for g in crate::grants::list(db)? {
        out.push(Permission {
            id: format!("grant:{}", g.id),
            name: format!("Folder: {}", g.label),
            allows: format!("Atlas may read files in {} when you share them.", g.path),
            status: "Granted".into(),
            open: true,
            scope: g.path.clone(),
            component: "Files".into(),
            last_used_at: None,
            control: json!({ "kind": "grant", "grant_id": g.id }),
        });
    }
    let siblings: Vec<(String, String)> = {
        let conn = db.conn()?;
        let mut st = conn.prepare("SELECT id, name FROM siblings WHERE status = 'paired'")?;
        st.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<std::result::Result<_, _>>()?
    };
    for (id, name) in siblings {
        out.push(Permission {
            id: format!("sibling:{id}"),
            name: format!("Paired sibling: {name}"),
            allows: "Missions you start can share the context you choose with this sibling, and receive its results.".into(),
            status: "Paired".into(),
            open: true,
            scope: "Missions you start".into(),
            component: "Siblings".into(),
            last_used_at: last_ts(db, "SELECT MAX(ts) FROM audit_events WHERE category = 'sibling'", &[]),
            control: json!({ "kind": "page", "route": "siblings" }),
        });
    }
    let integrations: Vec<String> = {
        let conn = db.conn()?;
        let mut st = conn.prepare("SELECT id FROM integrations WHERE enabled = 1")?;
        st.query_map([], |r| r.get(0))?.collect::<std::result::Result<_, _>>()?
    };
    for id in integrations {
        out.push(Permission {
            id: format!("integration:{id}"),
            name: format!("Integration: {id}"),
            allows: "Atlas may use this online service through its tool, following the internet-tools permission.".into(),
            status: "Enabled".into(),
            open: true,
            scope: "Leaves this computer".into(),
            component: "Integrations".into(),
            last_used_at: None,
            control: json!({ "kind": "page", "route": "integrations" }),
        });
    }
    Ok(out)
}

/// Work running or waiting now, and what recently finished or failed.
pub fn background(db: &Db, running_turns: usize) -> Result<Value> {
    let conn = db.conn()?;
    let one = |sql: &str| -> Result<i64> { Ok(conn.query_row(sql, [], |r| r.get(0))?) };
    let vault: Vec<(String, String, String)> = {
        let mut st = conn.prepare("SELECT id, title, status FROM vault_documents WHERE status IN ('processing','failed') ORDER BY updated_at DESC LIMIT 20")?;
        st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?.collect::<std::result::Result<_, _>>()?
    };
    Ok(json!({
        "running_conversations": running_turns,
        "pending_approvals": one("SELECT COUNT(*) FROM approvals WHERE status = 'pending'")?,
        "scheduler": {
            "pending": one("SELECT COUNT(*) FROM scheduled_jobs WHERE status = 'pending'")?,
            "running": one("SELECT COUNT(*) FROM scheduled_jobs WHERE status = 'running'")?,
            "missed_7d": one("SELECT COUNT(*) FROM scheduled_jobs WHERE status = 'missed' AND finished_at >= datetime('now','-7 days')")?,
            "next_at": conn.query_row("SELECT MIN(run_at) FROM scheduled_jobs WHERE status = 'pending'", [], |r| r.get::<_, Option<String>>(0))?,
        },
        "vault": vault.iter().map(|(id, t, s)| json!({ "id": id, "title": t, "status": s })).collect::<Vec<_>>(),
        "missions_active": one("SELECT COUNT(*) FROM missions WHERE state NOT IN ('completed','failed','cancelled','rejected')")?,
        "forge_runs_running": one("SELECT COUNT(*) FROM forge_runs WHERE status = 'running'")?,
        "tasks_interrupted_7d": one("SELECT COUNT(*) FROM tasks WHERE status = 'interrupted' AND updated_at >= datetime('now','-7 days')")?,
    }))
}

pub fn retention(db: &Db, s: &Settings) -> Result<Value> {
    let conn = db.conn()?;
    let (n, oldest): (i64, Option<String>) = conn.query_row("SELECT COUNT(*), MIN(ts) FROM audit_events", [], |r| Ok((r.get(0)?, r.get(1)?)))?;
    Ok(json!({ "events_stored": n, "oldest_event": oldest, "max_events": crate::audit::MAX_EVENTS, "audit_days": s.retention.audit_days, "conversation_days": s.retention.conversation_days }))
}

/// Everything Atlas recorded about one category of data in the last `days` days, for export.
/// Content-free by construction (the audit log never holds message, document or memory text).
pub fn export(db: &Db, days: u32) -> Result<String> {
    let since = (chrono::Utc::now() - chrono::Duration::days(days.clamp(1, 3650) as i64)).to_rfc3339();
    let conn = db.conn()?;
    let mut st = conn.prepare("SELECT id FROM audit_events WHERE ts >= ?1 ORDER BY id DESC LIMIT 1")?;
    let newest: Option<i64> = st.query_row([&since], |r| r.get(0)).ok();
    drop(st);
    drop(conn);
    let mut events = Vec::new();
    let mut before = newest.map(|n| n + 1);
    loop {
        let page = crate::audit::page(db, &crate::audit::PageFilter { before_id: before, limit: Some(200), ..Default::default() })?;
        let done = page.len() < 200;
        for e in page {
            if e.ts.as_str() < since.as_str() {
                return Ok(serde_json::to_string_pretty(&json!({ "exported_by": "ATLAS Co-Pilot", "days": days, "events": events }))?);
            }
            before = Some(e.id);
            events.push(e);
        }
        if done {
            break;
        }
    }
    Ok(serde_json::to_string_pretty(&json!({ "exported_by": "ATLAS Co-Pilot", "days": days, "events": events }))?)
}

/// Delete activity records older than `days` days (0 = all). Returns how many were removed. The
/// clearing itself is recorded afterwards, so the log never silently loses history.
pub fn clear(db: &Db, days: u32) -> Result<usize> {
    let n = if days == 0 {
        db.conn()?.execute("DELETE FROM audit_events", [])?
    } else {
        let cutoff = (chrono::Utc::now() - chrono::Duration::days(days as i64)).to_rfc3339();
        db.conn()?.execute("DELETE FROM audit_events WHERE ts < ?1", [cutoff])?
    };
    crate::audit::event(db, crate::audit::Event { kind: "trust.history_cleared", level: "warn", actor: "user", reversible: Some(false), detail: json!({ "removed": n, "older_than_days": days }), ..Default::default() });
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clearing_is_itself_recorded_and_export_is_content_free() {
        let db = Db::open_in_memory().unwrap();
        crate::audit::event(&db, crate::audit::Event { kind: "vault.import", resource: Some("doc1"), ..Default::default() });
        crate::audit::event(&db, crate::audit::Event { kind: "provider.request", provider: Some("Cloud"), left_device: true, ..Default::default() });
        let out = export(&db, 7).unwrap();
        let v: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(v["events"].as_array().unwrap().len(), 2);
        assert_eq!(clear(&db, 0).unwrap(), 2);
        let left = crate::audit::recent(&db, 10, None).unwrap();
        assert_eq!(left.len(), 1);
        assert_eq!(left[0].kind, "trust.history_cleared");
        assert_eq!(left[0].detail["removed"], 2);
        let counts = category_counts(&db, "2000-01-01").unwrap();
        assert_eq!(counts[0].category, "trust");
    }
}
