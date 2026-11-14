//! The session recap: "while you were away". Built only from what Atlas recorded since it was last
//! active (notifications, scheduled jobs, finished tasks, mission events, interrupted runs). Nothing
//! is resumed from here: an interrupted run is listed with a way to open it, and the owner decides.

use crate::error::Result;
use crate::storage::{now, Db};
use chrono::{DateTime, Duration, Utc};
use rusqlite::OptionalExtension;
use serde::Serialize;

/// Away for at least this long before Atlas offers a recap.
pub const AWAY_MINUTES: i64 = 30;
/// How often the "last active" mark is refreshed while Atlas runs.
const MARK_EVERY_SECS: i64 = 60;

#[derive(Debug, Clone, Serialize, PartialEq, Default)]
pub struct Recap {
    /// Start of the time away (Atlas's last activity before this start).
    pub since: String,
    pub reminders_delivered: u32,
    pub reminders_missed: u32,
    /// Titles of tasks finished while away (by recurrence, or from another device later), newest first.
    pub tasks_done: Vec<String>,
    /// Notifications raised while away, newest first: (category, title).
    pub notices: Vec<(String, String)>,
    pub missions_updated: u32,
    /// Runs that were in progress when Atlas closed: (id, request, conversation id).
    pub interrupted: Vec<(String, String, Option<String>)>,
    pub approvals_pending: u32,
    /// True when there is nothing to report.
    pub empty: bool,
}

fn meta(db: &Db, key: &str) -> Result<Option<String>> {
    Ok(db.conn()?.query_row("SELECT value FROM atlas_meta WHERE key = ?1", [key], |r| r.get(0)).optional()?)
}

fn set_meta(db: &Db, key: &str, value: &str) -> Result<()> {
    db.conn()?.execute("INSERT INTO atlas_meta(key, value) VALUES (?1, ?2) ON CONFLICT(key) DO UPDATE SET value = excluded.value", [key, value])?;
    Ok(())
}

fn ts(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

/// At start-up: if Atlas was last active long enough ago, remember that moment as the start of the
/// recap. Then mark Atlas active now.
pub fn on_start(db: &Db, now_utc: DateTime<Utc>) -> Result<()> {
    if let Some(last) = meta(db, "last_active_at")?
        && let Ok(t) = DateTime::parse_from_rfc3339(&last)
        && now_utc - t.with_timezone(&Utc) >= Duration::minutes(AWAY_MINUTES)
    {
        set_meta(db, "recap_since", &last)?;
        set_meta(db, "recap_dismissed", "")?;
    }
    set_meta(db, "last_active_at", &ts(now_utc))
}

/// While running: keep the "last active" mark fresh (at most one write a minute).
pub fn mark_active(db: &Db, now_utc: DateTime<Utc>) -> Result<()> {
    let stale = ts(now_utc - Duration::seconds(MARK_EVERY_SECS));
    db.conn()?.execute("UPDATE atlas_meta SET value = ?1 WHERE key = 'last_active_at' AND value < ?2", [ts(now_utc), stale])?;
    Ok(())
}

/// Start a recap from `since` (used by the automated-test build to stand in for real time away).
pub fn begin_at(db: &Db, since: DateTime<Utc>) -> Result<()> {
    set_meta(db, "recap_since", &ts(since))?;
    set_meta(db, "recap_dismissed", "")
}

pub fn dismiss(db: &Db) -> Result<()> {
    set_meta(db, "recap_dismissed", &now())
}

/// The recap to show, or `None` when there is none (never away long enough, or dismissed).
pub fn current(db: &Db) -> Result<Option<Recap>> {
    let Some(since) = meta(db, "recap_since")? else { return Ok(None) };
    if meta(db, "recap_dismissed")?.is_some_and(|d| !d.is_empty()) {
        return Ok(None);
    }
    build(db, &since).map(Some)
}

pub fn build(db: &Db, since: &str) -> Result<Recap> {
    let conn = db.conn()?;
    let count = |sql: &str| -> Result<u32> { Ok(conn.query_row(sql, [since], |r| r.get(0))?) };
    let reminders_delivered = count("SELECT COUNT(*) FROM scheduled_jobs WHERE kind = 'reminder' AND status = 'done' AND finished_at >= ?1")?;
    let reminders_missed = count("SELECT COUNT(*) FROM scheduled_jobs WHERE kind = 'reminder' AND status = 'missed' AND finished_at >= ?1")?;
    let missions_updated = count("SELECT COUNT(DISTINCT mission_id) FROM mission_events WHERE created_at >= ?1 AND source <> 'user'")?;
    let tasks_done: Vec<String> = {
        let mut st = conn.prepare("SELECT title FROM todos WHERE status = 'done' AND completed_at >= ?1 AND parent_id IS NULL ORDER BY completed_at DESC LIMIT 8")?;
        let rows = st.query_map([since], |r| r.get(0))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    let notices: Vec<(String, String)> = {
        let mut st = conn.prepare("SELECT category, title FROM notifications WHERE created_at >= ?1 AND category NOT IN ('test','focus') ORDER BY created_at DESC, rowid DESC LIMIT 8")?;
        let rows = st.query_map([since], |r| Ok((r.get(0)?, r.get(1)?)))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    let interrupted: Vec<(String, String, Option<String>)> = {
        let mut st = conn.prepare("SELECT id, request, conversation_id FROM tasks WHERE status = 'interrupted' AND finished_at >= ?1 ORDER BY finished_at DESC LIMIT 5")?;
        let rows = st.query_map([since], |r| Ok((r.get(0)?, r.get::<_, String>(1)?.chars().take(140).collect(), r.get(2)?)))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    let approvals_pending: u32 = conn.query_row("SELECT COUNT(*) FROM approvals WHERE status = 'pending'", [], |r| r.get(0))?;
    let empty = reminders_delivered + reminders_missed + missions_updated + approvals_pending == 0 && tasks_done.is_empty() && notices.is_empty() && interrupted.is_empty();
    Ok(Recap { since: since.to_string(), reminders_delivered, reminders_missed, tasks_done, notices, missions_updated, interrupted, approvals_pending, empty })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_recap_only_after_time_away_and_until_dismissed() {
        let db = Db::open_in_memory().unwrap();
        let t0 = Utc::now() - Duration::hours(5);
        on_start(&db, t0).unwrap();
        assert!(current(&db).unwrap().is_none(), "first ever start: nothing to recap");
        // Restarted 10 minutes later: not away long enough.
        on_start(&db, t0 + Duration::minutes(10)).unwrap();
        assert!(current(&db).unwrap().is_none());
        // Running: the mark moves forward, but at most once a minute.
        mark_active(&db, t0 + Duration::minutes(10) + Duration::seconds(30)).unwrap();
        assert_eq!(meta(&db, "last_active_at").unwrap().unwrap(), ts(t0 + Duration::minutes(10)));
        mark_active(&db, t0 + Duration::minutes(20)).unwrap();
        assert_eq!(meta(&db, "last_active_at").unwrap().unwrap(), ts(t0 + Duration::minutes(20)));
        // Back after four hours: a recap from the last activity.
        on_start(&db, t0 + Duration::hours(4)).unwrap();
        let r = current(&db).unwrap().expect("a recap after time away");
        assert_eq!(r.since, ts(t0 + Duration::minutes(20)));
        assert!(r.empty);
        dismiss(&db).unwrap();
        assert!(current(&db).unwrap().is_none(), "dismissed");
    }
}
