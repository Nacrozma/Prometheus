//! Focus Mode: a timed session, optionally on one task. While it runs, notifications that can wait
//! (reminders, replies, mission updates, the briefing) are listed but held: no system notification,
//! no toast. Approvals and failures always come through. When the session ends, on time or stopped,
//! what was held is released and one summary notice says what happened.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, Db};
use crate::desktop::Category;
use chrono::{DateTime, Duration, Utc};
use rusqlite::OptionalExtension;
use serde::Serialize;

pub const MIN_MINUTES: u32 = 5;
pub const MAX_MINUTES: u32 = 240;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct FocusSession {
    pub id: String,
    pub started_at: String,
    pub planned_end: String,
    pub ended_at: Option<String>,
    pub todo_id: Option<String>,
    /// The task's title when the session is on a task (looked up, so it follows renames).
    pub todo_title: Option<String>,
    pub label: String,
    /// "" while running, then "completed" (ran to its end) or "stopped".
    pub outcome: String,
}

/// What Focus Mode never holds back.
pub fn passes_through(c: Category) -> bool {
    matches!(c, Category::Approval | Category::Error | Category::Focus | Category::Test)
}

const COLS: &str = "f.id, f.started_at, f.planned_end, f.ended_at, f.todo_id, t.title, f.label, f.outcome";

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<FocusSession> {
    Ok(FocusSession { id: r.get(0)?, started_at: r.get(1)?, planned_end: r.get(2)?, ended_at: r.get(3)?, todo_id: r.get(4)?, todo_title: r.get(5)?, label: r.get(6)?, outcome: r.get(7)? })
}

fn ts(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

/// The running session, if any (it may be past its planned end until the next `tick`).
pub fn active(db: &Db) -> Result<Option<FocusSession>> {
    let conn = db.conn()?;
    Ok(conn.query_row(&format!("SELECT {COLS} FROM focus_sessions f LEFT JOIN todos t ON t.id = f.todo_id WHERE f.ended_at IS NULL ORDER BY f.started_at DESC LIMIT 1"), [], row).optional()?)
}

pub fn is_active(db: &Db) -> Result<bool> {
    Ok(db.conn()?.query_row("SELECT COUNT(*) FROM focus_sessions WHERE ended_at IS NULL", [], |r| r.get::<_, i64>(0))? > 0)
}

pub fn start(db: &Db, minutes: u32, todo_id: Option<&str>, label: &str, now_utc: DateTime<Utc>) -> Result<FocusSession> {
    if !(MIN_MINUTES..=MAX_MINUTES).contains(&minutes) {
        return Err(AtlasError::Validation(format!("a focus session lasts {MIN_MINUTES} to {MAX_MINUTES} minutes")));
    }
    let label: String = label.trim().chars().take(120).collect();
    let conn = db.conn()?;
    if let Some(id) = todo_id {
        let open: Option<String> = conn.query_row("SELECT status FROM todos WHERE id = ?1", [id], |r| r.get(0)).optional()?;
        match open.as_deref() {
            None => return Err(AtlasError::NotFound(format!("task {id}"))),
            Some("open" | "in_progress") => {}
            Some(_) => return Err(AtlasError::Validation("that task is already finished".into())),
        }
    }
    let id = new_id();
    // One running session at a time, enforced in the same statement that creates it.
    let n = conn.execute(
        "INSERT INTO focus_sessions (id, started_at, planned_end, todo_id, label) SELECT ?1, ?2, ?3, ?4, ?5 WHERE NOT EXISTS (SELECT 1 FROM focus_sessions WHERE ended_at IS NULL)",
        rusqlite::params![id, ts(now_utc), ts(now_utc + Duration::minutes(minutes as i64)), todo_id, label],
    )?;
    drop(conn);
    if n == 0 {
        return Err(AtlasError::Conflict("a focus session is already running".into()));
    }
    active(db)?.ok_or_else(|| AtlasError::Storage("the focus session was not saved".into()))
}

/// End the running session. Returns it (with its outcome), or `None` if none was running.
pub fn end(db: &Db, outcome: &str, now_utc: DateTime<Utc>) -> Result<Option<FocusSession>> {
    if !matches!(outcome, "completed" | "stopped") {
        return Err(AtlasError::Validation(format!("unknown outcome '{outcome}'")));
    }
    let Some(s) = active(db)? else { return Ok(None) };
    // Only the caller that actually ends it gets it back (the upkeep loop and the owner can race).
    let n = db.conn()?.execute("UPDATE focus_sessions SET ended_at = ?1, outcome = ?2 WHERE id = ?3 AND ended_at IS NULL", rusqlite::params![ts(now_utc), outcome, s.id])?;
    if n == 0 {
        return Ok(None);
    }
    Ok(Some(FocusSession { ended_at: Some(ts(now_utc)), outcome: outcome.into(), ..s }))
}

/// Ends the running session when its time is up. Returns the session that just completed.
/// A session that ran out while Atlas was closed (or asleep) ends at its planned end, so the time
/// reported is the time it was set for, not the time until Atlas next looked.
pub fn tick(db: &Db, now_utc: DateTime<Utc>) -> Result<Option<FocusSession>> {
    let Some(s) = active(db)? else { return Ok(None) };
    match DateTime::parse_from_rfc3339(&s.planned_end).map(|e| e.with_timezone(&Utc)) {
        Ok(planned) if planned <= now_utc => {
            // Never before it started (a clock set back while it ran).
            let started = DateTime::parse_from_rfc3339(&s.started_at).map(|t| t.with_timezone(&Utc)).unwrap_or(planned);
            end(db, "completed", planned.max(started))
        }
        Ok(_) => Ok(None),
        // An unreadable end time cannot be waited for: end it now.
        Err(_) => end(db, "completed", now_utc),
    }
}

pub fn history(db: &Db, limit: u32) -> Result<Vec<FocusSession>> {
    let conn = db.conn()?;
    let mut st = conn.prepare(&format!("SELECT {COLS} FROM focus_sessions f LEFT JOIN todos t ON t.id = f.todo_id WHERE f.ended_at IS NOT NULL ORDER BY f.started_at DESC LIMIT ?1"))?;
    let rows = st.query_map([limit.clamp(1, 200)], row)?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

/// Minutes actually spent, for the summary.
pub fn minutes_spent(s: &FocusSession) -> i64 {
    let start = DateTime::parse_from_rfc3339(&s.started_at).ok();
    let end = s.ended_at.as_deref().and_then(|e| DateTime::parse_from_rfc3339(e).ok());
    match (start, end) {
        (Some(a), Some(b)) => ((b - a).num_seconds() as f64 / 60.0).round() as i64,
        _ => 0,
    }
}

/// The summary notice raised when a session ends.
pub fn summary(s: &FocusSession, held: &[String]) -> (String, String) {
    let what = s.todo_title.clone().filter(|t| !t.is_empty()).or_else(|| Some(s.label.clone()).filter(|l| !l.is_empty()));
    let title = match (s.outcome.as_str(), &what) {
        ("completed", Some(w)) => format!("Focus session finished: {w}"),
        ("completed", None) => "Focus session finished".to_string(),
        (_, Some(w)) => format!("Focus session stopped: {w}"),
        (_, None) => "Focus session stopped".to_string(),
    };
    let mins = minutes_spent(s);
    let mut detail = format!("{mins} minute{} of focus.", if mins == 1 { "" } else { "s" });
    match held.len() {
        0 => detail.push_str(" Nothing was held back."),
        1 => detail.push_str(&format!(" 1 notification waited: {}.", held[0])),
        n => detail.push_str(&format!(" {n} notifications waited, latest: {}.", held[0])),
    }
    (title, detail)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn db() -> Db {
        Db::open_in_memory().unwrap()
    }

    #[test]
    fn one_session_at_a_time_with_limits() {
        let db = db();
        let t0 = Utc::now();
        assert!(start(&db, 2, None, "", t0).is_err(), "too short");
        assert!(start(&db, 500, None, "", t0).is_err(), "too long");
        let s = start(&db, 25, None, "  Write the report  ", t0).unwrap();
        assert_eq!(s.label, "Write the report");
        assert!(is_active(&db).unwrap());
        assert!(start(&db, 25, None, "", t0).is_err(), "a second session is refused");
        assert!(end(&db, "sideways", t0).is_err());
        let done = end(&db, "stopped", t0 + Duration::minutes(10)).unwrap().unwrap();
        assert_eq!(done.outcome, "stopped");
        assert_eq!(minutes_spent(&done), 10);
        assert!(end(&db, "stopped", t0).unwrap().is_none(), "ending twice does nothing");
        assert!(!is_active(&db).unwrap());
        assert_eq!(history(&db, 10).unwrap().len(), 1);
    }

    #[test]
    fn tick_completes_on_time_and_not_before() {
        let db = db();
        let t0 = Utc::now();
        start(&db, 5, None, "", t0).unwrap();
        assert!(tick(&db, t0 + Duration::minutes(4)).unwrap().is_none());
        let s = tick(&db, t0 + Duration::minutes(5)).unwrap().unwrap();
        assert_eq!(s.outcome, "completed");
        assert!(tick(&db, t0 + Duration::minutes(6)).unwrap().is_none());
    }

    #[test]
    fn a_session_that_ran_out_while_closed_ends_at_its_planned_end() {
        let db = db();
        let t0 = Utc::now() - Duration::hours(6);
        start(&db, 25, None, "", t0).unwrap();
        // Atlas was closed; the next upkeep tick is hours later.
        let s = tick(&db, t0 + Duration::hours(6)).unwrap().unwrap();
        assert_eq!(s.outcome, "completed");
        assert_eq!(minutes_spent(&s), 25, "the time set, not the time until Atlas looked again");
        assert_eq!(s.ended_at.as_deref(), Some(s.planned_end.as_str()));
    }

    #[test]
    fn summary_names_the_task_and_what_waited() {
        let s = FocusSession { id: "x".into(), started_at: "2026-01-01T10:00:00.000Z".into(), planned_end: "2026-01-01T10:25:00.000Z".into(), ended_at: Some("2026-01-01T10:25:00.000Z".into()), todo_id: None, todo_title: Some("Write the report".into()), label: String::new(), outcome: "completed".into() };
        let (t, d) = summary(&s, &["Reply ready".into(), "Stretch".into()]);
        assert_eq!(t, "Focus session finished: Write the report");
        assert_eq!(d, "25 minutes of focus. 2 notifications waited, latest: Reply ready.");
        assert!(passes_through(Category::Approval) && passes_through(Category::Error));
        assert!(!passes_through(Category::Reminder) && !passes_through(Category::Reply) && !passes_through(Category::Briefing));
    }
}
