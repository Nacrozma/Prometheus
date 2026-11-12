//! The scheduler: time-triggered jobs that survive restarts and never run twice.
//!
//! In 0.5.0 a job only raises a notification (a task reminder, a "due today" notice) or prepares
//! the daily briefing. No job runs a tool or spends money.
//!
//! * **Exactly once:** a job is claimed with one conditional UPDATE (`pending → running`); only
//!   the caller that changed the row runs it. Each job raises its notification under the key
//!   `job:<id>`, so a crash between raising and recording cannot cause a second notice.
//! * **Restart recovery:** jobs left `running` by a crash are finished (if their notice exists)
//!   or returned to `pending` when Atlas starts.
//! * **Missed jobs:** anything due longer ago than the grace period (Atlas was closed, or the
//!   scheduler was paused) is marked `missed` and reported once, as one grouped notice.
//! * **Time zones:** reminders are stored as instants. "Due today" notices are computed from the
//!   owner's local date and re-computed on every sync, so a change of time zone moves them.

use crate::desktop::{Category, NewNotification, NotificationCenter};
use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use crate::todos;
use chrono::{DateTime, NaiveDateTime, NaiveTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct ScheduleSettings {
    /// Global pause for everything Atlas does on its own (reminders, notices, briefing).
    pub paused: bool,
    /// A "due today" notice for open tasks that have a date but no reminder.
    pub deadline_notices: bool,
    /// Local hour for "due today" notices.
    pub deadline_hour: u8,
    /// Jobs due longer ago than this are reported as missed instead of delivered late.
    pub missed_grace_minutes: u32,
}

impl Default for ScheduleSettings {
    fn default() -> Self {
        Self { paused: false, deadline_notices: true, deadline_hour: 9, missed_grace_minutes: 720 }
    }
}

impl ScheduleSettings {
    pub fn validate(&self) -> Result<()> {
        if self.deadline_hour > 23 {
            return Err(AtlasError::Validation("the notice hour must be between 0 and 23".into()));
        }
        if !(5..=10_080).contains(&self.missed_grace_minutes) {
            return Err(AtlasError::Validation("the grace period must be between 5 minutes and 7 days".into()));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Job {
    pub id: String,
    pub kind: String,
    pub subject: String,
    pub run_at: String,
    pub status: String,
    pub attempts: u32,
    pub result: String,
    pub created_at: String,
    pub finished_at: Option<String>,
    /// What the job is about, for display (a task title).
    pub label: String,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct TickReport {
    pub delivered: u32,
    pub missed: u32,
    pub failed: u32,
}

fn ts(t: DateTime<Utc>) -> String {
    t.to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

fn parse_ts(s: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(s).ok().map(|d| d.with_timezone(&Utc))
}

/// Make the pending jobs match the task list: one reminder per open task with a reminder, and
/// (if enabled) one "due today" notice per open dated task without one. Idempotent.
///
/// A moment that has already passed is never scheduled anew: a "due today" notice for a task
/// created after its notice time, or a reminder set further in the past than the grace period,
/// would only produce noise. (Jobs that already existed and fell due while Atlas was closed are
/// handled by `tick`.)
pub fn sync(db: &Db, s: &ScheduleSettings, now_local: NaiveDateTime, now_utc: DateTime<Utc>) -> Result<()> {
    let open = todos::list(db, &todos::Filter { view: "open".into(), ..Default::default() }, now_local)?;
    let mut want: Vec<(String, String, String)> = Vec::new(); // (kind, subject, run_at)
    let mut collect = |t: &todos::Todo| {
        if let Some(r) = t.remind_at.as_deref().and_then(parse_ts) {
            want.push(("reminder".into(), t.id.clone(), ts(r)));
        } else if s.deadline_notices
            && let Some(d) = t.due_date.as_deref().and_then(crate::when::iso_date)
        {
            let at = todos::local_to_utc(d, NaiveTime::from_hms_opt(u32::from(s.deadline_hour), 0, 0).unwrap_or(NaiveTime::MIN));
            want.push(("deadline".into(), t.id.clone(), at));
        }
    };
    for t in &open {
        collect(t);
        // Steps can carry their own reminders.
        for sub in todos::subtasks(db, &t.id, now_local)? {
            if matches!(sub.status.as_str(), "open" | "in_progress") {
                collect(&sub);
            }
        }
    }
    let conn = db.conn()?;
    let tx = conn.unchecked_transaction()?;
    // Cancel pending task jobs that no longer match (task finished, deleted, date or reminder changed).
    let pending: Vec<(String, String, String, String)> = {
        let mut st = tx.prepare("SELECT id, kind, subject, run_at FROM scheduled_jobs WHERE status = 'pending' AND kind IN ('reminder','deadline')")?;
        let rows = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    for (id, kind, subject, run_at) in &pending {
        if !want.iter().any(|(k, sj, at)| k == kind && sj == subject && at == run_at) {
            tx.execute("UPDATE scheduled_jobs SET status = 'cancelled', finished_at = ?1, result = 'the task changed' WHERE id = ?2 AND status = 'pending'", rusqlite::params![now(), id])?;
        }
    }
    // Add what is missing. The UNIQUE (kind, subject, run_at) key makes a repeat insert a no-op,
    // so a reminder already delivered (or cancelled) for that exact moment is never re-created.
    let grace = chrono::Duration::minutes(i64::from(s.missed_grace_minutes));
    for (kind, subject, run_at) in want {
        let exists: i64 = tx.query_row("SELECT COUNT(*) FROM scheduled_jobs WHERE kind = ?1 AND subject = ?2 AND run_at = ?3", rusqlite::params![kind, subject, run_at], |r| r.get(0))?;
        let at = parse_ts(&run_at);
        let passed = match kind.as_str() {
            "deadline" => at.is_some_and(|a| a <= now_utc),
            _ => at.is_some_and(|a| now_utc - a > grace),
        };
        if exists == 0 && passed {
            continue;
        }
        tx.execute(
            "INSERT OR IGNORE INTO scheduled_jobs (id, kind, subject, run_at, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
            rusqlite::params![new_id(), kind, subject, run_at, now()],
        )?;
    }
    tx.commit()?;
    Ok(())
}

/// After a crash: finish jobs whose notice was already raised, and retry the rest.
pub fn recover(db: &Db) -> Result<usize> {
    let conn = db.conn()?;
    let stuck: Vec<String> = {
        let mut st = conn.prepare("SELECT id FROM scheduled_jobs WHERE status = 'running'")?;
        let rows = st.query_map([], |r| r.get::<_, String>(0))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    for id in &stuck {
        let delivered: i64 = conn.query_row("SELECT COUNT(*) FROM notifications WHERE dedupe_key = ?1", [format!("job:{id}")], |r| r.get(0))?;
        if delivered > 0 {
            conn.execute("UPDATE scheduled_jobs SET status = 'done', finished_at = ?1, result = 'delivered before a restart' WHERE id = ?2", rusqlite::params![now(), id])?;
        } else {
            conn.execute("UPDATE scheduled_jobs SET status = 'pending', started_at = NULL WHERE id = ?1", [id])?;
        }
    }
    Ok(stuck.len())
}

/// Claim a job. True only for the one caller that moved it from pending to running.
fn claim(db: &Db, id: &str) -> Result<bool> {
    Ok(db.conn()?.execute("UPDATE scheduled_jobs SET status = 'running', started_at = ?1, attempts = attempts + 1 WHERE id = ?2 AND status = 'pending'", rusqlite::params![now(), id])? == 1)
}

fn finish(db: &Db, id: &str, status: &str, result: &str) -> Result<()> {
    db.conn()?.execute("UPDATE scheduled_jobs SET status = ?1, result = ?2, finished_at = ?3 WHERE id = ?4", rusqlite::params![status, result, now(), id])?;
    Ok(())
}

/// Run every due job once. `notify_settings` decides what reaches the system; the in-app list
/// always records it.
pub fn tick(db: &Db, center: &NotificationCenter, s: &ScheduleSettings, notify_settings: &crate::desktop::NotificationSettings, now_utc: DateTime<Utc>, now_local: NaiveDateTime) -> Result<TickReport> {
    let mut report = TickReport::default();
    if s.paused {
        return Ok(report);
    }
    let due: Vec<(String, String, String, String)> = {
        let conn = db.conn()?;
        let mut st = conn.prepare("SELECT id, kind, subject, run_at FROM scheduled_jobs WHERE status = 'pending' AND run_at <= ?1 ORDER BY run_at LIMIT 200")?;
        let rows = st.query_map([ts(now_utc)], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    let grace = chrono::Duration::minutes(i64::from(s.missed_grace_minutes));
    let mut missed_titles: Vec<String> = Vec::new();
    for (id, kind, subject, run_at) in due {
        if !claim(db, &id)? {
            continue; // someone else has it
        }
        let late = parse_ts(&run_at).is_none_or(|r| now_utc - r > grace);
        let task = todos::get(db, &subject, now_local).ok().filter(|t| matches!(t.status.as_str(), "open" | "in_progress"));
        let Some(task) = task else {
            finish(db, &id, "cancelled", "the task was finished or removed")?;
            continue;
        };
        if late {
            missed_titles.push(task.title.clone());
            finish(db, &id, "missed", "Atlas was closed or paused at the time")?;
            report.missed += 1;
            continue;
        }
        let (category, title) = match kind.as_str() {
            "reminder" => (Category::Reminder, "Reminder"),
            "deadline" => (Category::Deadline, "Due today"),
            other => {
                finish(db, &id, "failed", &format!("unknown job kind '{other}'"))?;
                report.failed += 1;
                continue;
            }
        };
        let when = match (&task.due_date, &task.due_time) {
            (Some(d), Some(t)) => format!(" · due {d} {t}"),
            (Some(d), None) => format!(" · due {d}"),
            _ => String::new(),
        };
        match center.raise(notify_settings, NewNotification { category, title, detail: &format!("{}{when}", task.title), target: &format!("todo:{}", task.id), dedupe_key: &format!("job:{id}"), only_if_away: false }) {
            Ok(n) => {
                let shown = n.as_ref().is_some_and(|n| n.shown_by_system);
                finish(db, &id, "done", if shown { "shown by the system and listed in Atlas" } else { "listed in Atlas" })?;
                report.delivered += 1;
            }
            Err(e) => {
                // Back to pending for the next tick, up to three attempts.
                let attempts: u32 = db.conn()?.query_row("SELECT attempts FROM scheduled_jobs WHERE id = ?1", [&id], |r| r.get(0))?;
                if attempts >= 3 {
                    finish(db, &id, "failed", &e.to_string())?;
                    report.failed += 1;
                } else {
                    db.conn()?.execute("UPDATE scheduled_jobs SET status = 'pending' WHERE id = ?1", [&id])?;
                }
            }
        }
    }
    if !missed_titles.is_empty() {
        let n = missed_titles.len();
        let mut detail: String = missed_titles.iter().take(5).cloned().collect::<Vec<_>>().join(", ");
        if n > 5 {
            detail.push_str(&format!(" and {} more", n - 5));
        }
        let title = if n == 1 { "1 reminder was missed while Atlas was closed or paused".to_string() } else { format!("{n} reminders were missed while Atlas was closed or paused") };
        center.raise(notify_settings, NewNotification { category: Category::Reminder, title: &title, detail: &detail, target: "tasks", dedupe_key: &format!("missed:{}", ts(now_utc)), only_if_away: false })?;
    }
    Ok(report)
}

/// Recent and upcoming jobs, for the owner to inspect.
pub fn list(db: &Db, now_local: NaiveDateTime, limit: u32) -> Result<Vec<Job>> {
    let conn = db.conn()?;
    let mut st = conn.prepare(
        "SELECT j.id, j.kind, j.subject, j.run_at, j.status, j.attempts, j.result, j.created_at, j.finished_at, COALESCE(t.title, '') \
         FROM scheduled_jobs j LEFT JOIN todos t ON t.id = j.subject \
         ORDER BY CASE j.status WHEN 'pending' THEN 0 WHEN 'running' THEN 0 ELSE 1 END, \
                  CASE WHEN j.status IN ('pending','running') THEN j.run_at END ASC, j.finished_at DESC LIMIT ?1",
    )?;
    let _ = now_local;
    let rows = st.query_map([limit.clamp(1, 500)], |r| {
        Ok(Job { id: r.get(0)?, kind: r.get(1)?, subject: r.get(2)?, run_at: r.get(3)?, status: r.get(4)?, attempts: r.get(5)?, result: r.get(6)?, created_at: r.get(7)?, finished_at: r.get(8)?, label: r.get(9)? })
    })?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

/// Remove finished job records older than `days` (the history stays bounded).
pub fn prune(db: &Db, now_utc: DateTime<Utc>, days: i64) -> Result<usize> {
    let cutoff = ts(now_utc - chrono::Duration::days(days));
    Ok(db.conn()?.execute("DELETE FROM scheduled_jobs WHERE status IN ('done','missed','cancelled','failed') AND COALESCE(finished_at, created_at) < ?1", [cutoff])?)
}

pub fn summary(db: &Db) -> Result<serde_json::Value> {
    let conn = db.conn()?;
    let count = |status: &str| -> Result<i64> { Ok(conn.query_row("SELECT COUNT(*) FROM scheduled_jobs WHERE status = ?1", [status], |r| r.get(0))?) };
    let next: Option<String> = conn.query_row("SELECT MIN(run_at) FROM scheduled_jobs WHERE status = 'pending'", [], |r| r.get(0))?;
    Ok(json!({ "pending": count("pending")?, "done": count("done")?, "missed": count("missed")?, "failed": count("failed")?, "next_run_at": next }))
}
