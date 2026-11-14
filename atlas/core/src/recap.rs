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
        // A recap not yet dismissed keeps its earlier start: the new time away is added to it, so
        // nothing from the first absence drops out and the owner sees one recap, not a second one.
        let pending = current_since(db)?.is_some();
        if !pending {
            set_meta(db, "recap_since", &ts(t.with_timezone(&Utc)))?;
            set_meta(db, "recap_dismissed", "")?;
        }
    }
    set_meta(db, "last_active_at", &ts(now_utc))
}

/// While running: keep the "last active" mark fresh (at most one write a minute).
pub fn mark_active(db: &Db, now_utc: DateTime<Utc>) -> Result<()> {
    // Refresh when the mark is a minute old, or when it is ahead of now (the clock was set back).
    let stale = ts(now_utc - Duration::seconds(MARK_EVERY_SECS));
    let now_s = ts(now_utc);
    db.conn()?.execute("UPDATE atlas_meta SET value = ?1 WHERE key = 'last_active_at' AND (value < ?2 OR value > ?1)", [now_s, stale])?;
    Ok(())
}

/// Start a recap from `since`. Automated tests only (it stands in for real time away), so it is
/// not compiled into the desktop app.
#[cfg(any(test, feature = "test-support"))]
pub fn begin_at(db: &Db, since: DateTime<Utc>) -> Result<()> {
    set_meta(db, "recap_since", &ts(since))?;
    set_meta(db, "recap_dismissed", "")
}

/// Automated tests only: make it as if Atlas had been closed `minutes` longer than it really was.
/// The "last active" mark and any running Focus session move back by that much. The e2e build
/// calls this before start-up, so the real restart path (task recovery, the recap, a Focus session
/// that ran out while closed) is what gets tested. Not compiled into the desktop app.
#[cfg(any(test, feature = "test-support"))]
pub fn shift_back_for_test(db: &Db, minutes: i64) -> Result<()> {
    let back = |v: &str| DateTime::parse_from_rfc3339(v).map(|t| ts(t.with_timezone(&Utc) - Duration::minutes(minutes))).ok();
    if let Some(last) = meta(db, "last_active_at")?.as_deref().and_then(back) {
        set_meta(db, "last_active_at", &last)?;
    }
    let conn = db.conn()?;
    let open: Vec<(String, String, String)> = {
        let mut st = conn.prepare("SELECT id, started_at, planned_end FROM focus_sessions WHERE ended_at IS NULL")?;
        let rows = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    for (id, a, b) in open {
        if let (Some(a), Some(b)) = (back(&a), back(&b)) {
            conn.execute("UPDATE focus_sessions SET started_at = ?1, planned_end = ?2 WHERE id = ?3", [a, b, id])?;
        }
    }
    Ok(())
}

pub fn dismiss(db: &Db) -> Result<()> {
    set_meta(db, "recap_dismissed", &now())
}

/// The recap to show, or `None` when there is none (never away long enough, or dismissed).
pub fn current(db: &Db) -> Result<Option<Recap>> {
    match current_since(db)? {
        Some(since) => build(db, &since).map(Some),
        None => Ok(None),
    }
}

/// The start of the recap to show, normalised; `None` when there is none, it was dismissed, or the
/// stored start cannot be read (a damaged value is treated as no recap, never as "everything").
fn current_since(db: &Db) -> Result<Option<String>> {
    let Some(since) = meta(db, "recap_since")? else { return Ok(None) };
    if meta(db, "recap_dismissed")?.is_some_and(|d| !d.is_empty()) {
        return Ok(None);
    }
    Ok(DateTime::parse_from_rfc3339(&since).ok().map(|t| ts(t.with_timezone(&Utc))))
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
        let mut st = conn.prepare(&format!("SELECT category, {} FROM notifications WHERE created_at >= ?1 AND category NOT IN ('test','focus') ORDER BY created_at DESC, rowid DESC LIMIT 8", crate::desktop::NAMED_TITLE))?;
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

    #[test]
    fn a_second_absence_extends_the_recap_instead_of_replacing_it() {
        let db = Db::open_in_memory().unwrap();
        let t0 = Utc::now() - Duration::hours(10);
        on_start(&db, t0).unwrap();
        on_start(&db, t0 + Duration::hours(2)).unwrap();
        assert_eq!(current(&db).unwrap().unwrap().since, ts(t0));
        // Closed again without reading it, back three hours later: still one recap, from t0.
        on_start(&db, t0 + Duration::hours(5)).unwrap();
        assert_eq!(current(&db).unwrap().unwrap().since, ts(t0));
        // Once dismissed, the next absence starts a fresh one.
        dismiss(&db).unwrap();
        on_start(&db, t0 + Duration::hours(9)).unwrap();
        assert_eq!(current(&db).unwrap().unwrap().since, ts(t0 + Duration::hours(5)));
    }

    #[test]
    fn the_test_stand_in_moves_the_mark_and_a_running_focus_session_back() {
        let db = Db::open_in_memory().unwrap();
        let t0 = Utc::now();
        on_start(&db, t0).unwrap();
        crate::focus::start(&db, 15, None, "", t0).unwrap();
        shift_back_for_test(&db, 120).unwrap();
        assert_eq!(meta(&db, "last_active_at").unwrap().unwrap(), ts(t0 - Duration::minutes(120)));
        let f = crate::focus::active(&db).unwrap().unwrap();
        assert_eq!(f.started_at, ts(t0 - Duration::minutes(120)));
        assert_eq!(f.planned_end, ts(t0 - Duration::minutes(105)));
        on_start(&db, t0).unwrap();
        assert_eq!(current(&db).unwrap().unwrap().since, ts(t0 - Duration::minutes(120)));
    }

    #[test]
    fn damaged_records_and_clock_changes_are_safe() {
        let db = Db::open_in_memory().unwrap();
        let now_utc = Utc::now();
        // An unreadable "last active" mark: no recap, and the mark is repaired.
        set_meta(&db, "last_active_at", "not a time").unwrap();
        on_start(&db, now_utc).unwrap();
        assert!(current(&db).unwrap().is_none());
        assert_eq!(meta(&db, "last_active_at").unwrap().unwrap(), ts(now_utc));
        // An unreadable recap start is no recap (never "everything since the beginning").
        set_meta(&db, "recap_since", "garbage").unwrap();
        set_meta(&db, "recap_dismissed", "").unwrap();
        assert!(current(&db).unwrap().is_none());
        // The clock was set back: a mark in the future is not "away", and running pulls it back.
        set_meta(&db, "recap_since", "").unwrap();
        set_meta(&db, "recap_dismissed", "x").unwrap();
        set_meta(&db, "last_active_at", &ts(now_utc + Duration::days(2))).unwrap();
        on_start(&db, now_utc).unwrap();
        assert!(current(&db).unwrap().is_none());
        set_meta(&db, "last_active_at", &ts(now_utc + Duration::days(2))).unwrap();
        mark_active(&db, now_utc).unwrap();
        assert_eq!(meta(&db, "last_active_at").unwrap().unwrap(), ts(now_utc));
    }
}
