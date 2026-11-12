//! The owner's tasks (to-dos): deadlines, priorities, subtasks, recurrence, reminders, history.
//!
//! Not to be confused with `tasks.rs`, which records runs of tool-using turns. A to-do is
//! something the *owner* wants done. Due dates are wall-clock (a local date and optional time),
//! so "Friday 5pm" stays Friday 5pm; reminders are stored as instants.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use crate::when;
use chrono::{Duration, NaiveDate, NaiveDateTime, NaiveTime, TimeZone};
use rusqlite::{params_from_iter, types::Value as Sql, OptionalExtension, Row};
use serde::{Deserialize, Serialize};

pub const STATUSES: [&str; 4] = ["open", "in_progress", "done", "cancelled"];
pub const PRIORITIES: [&str; 4] = ["low", "normal", "high", "urgent"];
pub const RECURRENCES: [&str; 6] = ["none", "daily", "weekdays", "weekly", "monthly", "yearly"];
const MAX_TITLE: usize = 300;
const MAX_NOTES: usize = 8000;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Todo {
    pub id: String,
    pub parent_id: Option<String>,
    pub project_id: Option<String>,
    pub title: String,
    pub notes: String,
    pub status: String,
    pub priority: String,
    pub category: String,
    /// Local calendar date, YYYY-MM-DD.
    pub due_date: Option<String>,
    /// Local time, HH:MM.
    pub due_time: Option<String>,
    /// When Atlas reminds about it (an instant, UTC).
    pub remind_at: Option<String>,
    pub recurrence: String,
    pub recur_interval: u32,
    /// "user" or "atlas" (created through a conversation).
    pub source: String,
    pub conversation_id: Option<String>,
    pub postponed_count: u32,
    pub created_at: String,
    pub updated_at: String,
    pub completed_at: Option<String>,
    /// Computed for the owner's "now": past its date (or date and time) and not finished.
    pub overdue: bool,
    pub subtasks_total: u32,
    pub subtasks_done: u32,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct NewTodo {
    pub title: String,
    pub notes: String,
    pub priority: Option<String>,
    pub category: Option<String>,
    pub project_id: Option<String>,
    pub parent_id: Option<String>,
    pub due_date: Option<String>,
    pub due_time: Option<String>,
    pub remind_at: Option<String>,
    pub recurrence: Option<String>,
    pub recur_interval: Option<u32>,
    pub source: Option<String>,
    pub conversation_id: Option<String>,
}

/// A change to a task. `Some(None)` clears a value; `None` leaves it as it is.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct TodoPatch {
    pub title: Option<String>,
    pub notes: Option<String>,
    pub priority: Option<String>,
    pub category: Option<String>,
    #[serde(deserialize_with = "double")]
    pub project_id: Option<Option<String>>,
    #[serde(deserialize_with = "double")]
    pub due_date: Option<Option<String>>,
    #[serde(deserialize_with = "double")]
    pub due_time: Option<Option<String>>,
    #[serde(deserialize_with = "double")]
    pub remind_at: Option<Option<String>>,
    pub recurrence: Option<String>,
    pub recur_interval: Option<u32>,
    pub status: Option<String>,
}

fn double<'de, D, T>(d: D) -> std::result::Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Ok(Some(Option::<T>::deserialize(d)?))
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Filter {
    /// "today", "week", "overdue", "upcoming", "someday" (no date), "open", "done", "all".
    pub view: String,
    pub project_id: Option<String>,
    pub category: Option<String>,
    pub priority: Option<String>,
    pub search: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct TodoEvent {
    pub at: String,
    pub kind: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Default)]
pub struct Counts {
    pub open: u32,
    pub overdue: u32,
    pub today: u32,
    pub week: u32,
    pub done_today: u32,
    pub done_week: u32,
}

fn bad(msg: impl Into<String>) -> AtlasError {
    AtlasError::Validation(msg.into())
}

fn clean_title(t: &str) -> Result<String> {
    let t = crate::redact::redact(t.trim());
    if t.is_empty() {
        return Err(bad("a task needs a title"));
    }
    if t.chars().count() > MAX_TITLE {
        return Err(bad(format!("a task title can be at most {MAX_TITLE} characters")));
    }
    Ok(t)
}

fn clean_notes(n: &str) -> Result<String> {
    if n.chars().count() > MAX_NOTES {
        return Err(bad(format!("task notes can be at most {MAX_NOTES} characters")));
    }
    Ok(crate::redact::redact(n.trim()))
}

fn one_of(what: &str, v: &str, allowed: &[&str]) -> Result<String> {
    if allowed.contains(&v) { Ok(v.to_string()) } else { Err(bad(format!("unknown {what} '{v}'"))) }
}

fn clean_date(d: &str) -> Result<String> {
    when::iso_date(d).map(|d| d.to_string()).ok_or_else(|| bad(format!("'{d}' is not a date (use YYYY-MM-DD)")))
}

fn clean_time(t: &str) -> Result<String> {
    when::hhmm(t).map(|t| t.format("%H:%M").to_string()).ok_or_else(|| bad(format!("'{t}' is not a time (use HH:MM)")))
}

fn clean_instant(t: &str) -> Result<String> {
    chrono::DateTime::parse_from_rfc3339(t)
        .map(|d| d.with_timezone(&chrono::Utc).to_rfc3339_opts(chrono::SecondsFormat::Millis, true))
        .map_err(|_| bad(format!("'{t}' is not a valid date and time")))
}

fn clean_category(c: &str) -> Result<String> {
    let c = c.trim().trim_start_matches('#');
    if c.chars().count() > 40 || c.chars().any(char::is_control) {
        return Err(bad("a category can be at most 40 characters"));
    }
    Ok(c.to_string())
}

/// Convert a local date and time to a UTC instant (for reminders).
pub fn local_to_utc(date: NaiveDate, time: NaiveTime) -> String {
    let naive = NaiveDateTime::new(date, time);
    let local = chrono::Local.from_local_datetime(&naive).earliest().unwrap_or_else(|| chrono::Local.from_utc_datetime(&naive));
    local.with_timezone(&chrono::Utc).to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

/// The default reminder for a deadline: at its time, or 09:00 on the day when it has no time.
pub fn default_reminder(due_date: &str, due_time: Option<&str>) -> Option<String> {
    let d = when::iso_date(due_date)?;
    let t = due_time.and_then(when::hhmm).or_else(|| NaiveTime::from_hms_opt(9, 0, 0))?;
    Some(local_to_utc(d, t))
}

fn is_overdue(status: &str, due_date: Option<&str>, due_time: Option<&str>, now_local: NaiveDateTime) -> bool {
    if matches!(status, "done" | "cancelled") {
        return false;
    }
    let Some(d) = due_date.and_then(when::iso_date) else { return false };
    match due_time.and_then(when::hhmm) {
        Some(t) => NaiveDateTime::new(d, t) < now_local,
        None => d < now_local.date(),
    }
}

const COLS: &str = "t.id, t.parent_id, t.project_id, t.title, t.notes, t.status, t.priority, t.category, t.due_date, t.due_time, t.remind_at, \
     t.recurrence, t.recur_interval, t.source, t.conversation_id, t.postponed_count, t.created_at, t.updated_at, t.completed_at, \
     (SELECT COUNT(*) FROM todos c WHERE c.parent_id = t.id AND c.status != 'cancelled'), \
     (SELECT COUNT(*) FROM todos c WHERE c.parent_id = t.id AND c.status = 'done')";

fn from_row(r: &Row<'_>, now_local: NaiveDateTime) -> rusqlite::Result<Todo> {
    let status: String = r.get(5)?;
    let due_date: Option<String> = r.get(8)?;
    let due_time: Option<String> = r.get(9)?;
    Ok(Todo {
        overdue: is_overdue(&status, due_date.as_deref(), due_time.as_deref(), now_local),
        id: r.get(0)?,
        parent_id: r.get(1)?,
        project_id: r.get(2)?,
        title: r.get(3)?,
        notes: r.get(4)?,
        status,
        priority: r.get(6)?,
        category: r.get(7)?,
        due_date,
        due_time,
        remind_at: r.get(10)?,
        recurrence: r.get(11)?,
        recur_interval: r.get(12)?,
        source: r.get(13)?,
        conversation_id: r.get(14)?,
        postponed_count: r.get(15)?,
        created_at: r.get(16)?,
        updated_at: r.get(17)?,
        completed_at: r.get(18)?,
        subtasks_total: r.get(19)?,
        subtasks_done: r.get(20)?,
    })
}

fn event(db: &Db, id: &str, kind: &str, detail: &str) -> Result<()> {
    db.conn()?.execute("INSERT INTO todo_events (todo_id, at, kind, detail) VALUES (?1, ?2, ?3, ?4)", rusqlite::params![id, now(), kind, detail])?;
    Ok(())
}

pub fn get(db: &Db, id: &str, now_local: NaiveDateTime) -> Result<Todo> {
    db.conn()?
        .query_row(&format!("SELECT {COLS} FROM todos t WHERE t.id = ?1"), [id], |r| from_row(r, now_local))
        .optional()?
        .ok_or_else(|| AtlasError::NotFound(format!("task '{id}'")))
}

pub fn create(db: &Db, n: NewTodo, now_local: NaiveDateTime) -> Result<Todo> {
    let title = clean_title(&n.title)?;
    let notes = clean_notes(&n.notes)?;
    let priority = one_of("priority", n.priority.as_deref().unwrap_or("normal"), &PRIORITIES)?;
    let recurrence = one_of("repeat setting", n.recurrence.as_deref().unwrap_or("none"), &RECURRENCES)?;
    let interval = n.recur_interval.unwrap_or(1);
    if !(1..=365).contains(&interval) {
        return Err(bad("the repeat interval must be between 1 and 365"));
    }
    let source = one_of("source", n.source.as_deref().unwrap_or("user"), &["user", "atlas"])?;
    let category = clean_category(n.category.as_deref().unwrap_or(""))?;
    let due_date = n.due_date.as_deref().map(clean_date).transpose()?;
    let due_time = n.due_time.as_deref().map(clean_time).transpose()?;
    if due_time.is_some() && due_date.is_none() {
        return Err(bad("a due time needs a due date"));
    }
    if recurrence != "none" && due_date.is_none() {
        return Err(bad("a repeating task needs a first date"));
    }
    let remind_at = n.remind_at.as_deref().map(clean_instant).transpose()?;
    let mut project_id = n.project_id.clone();
    if let Some(pid) = &n.parent_id {
        let parent = get(db, pid, now_local)?;
        if parent.parent_id.is_some() {
            return Err(bad("a subtask cannot have its own subtasks"));
        }
        if recurrence != "none" {
            return Err(bad("a subtask cannot repeat; make the parent task repeat instead"));
        }
        project_id = parent.project_id; // a subtask lives in its parent's project
    }
    if let Some(p) = &project_id {
        crate::projects::get(db, p)?;
    }
    let id = new_id();
    let ts = now();
    db.conn()?.execute(
        "INSERT INTO todos (id, parent_id, project_id, title, notes, priority, category, due_date, due_time, remind_at, recurrence, recur_interval, source, conversation_id, created_at, updated_at) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?15)",
        rusqlite::params![id, n.parent_id, project_id, title, notes, priority, category, due_date, due_time, remind_at, recurrence, interval, source, n.conversation_id, ts],
    )?;
    event(db, &id, "created", if source == "atlas" { "by Atlas, from a conversation" } else { "" })?;
    get(db, &id, now_local)
}

pub fn update(db: &Db, id: &str, p: TodoPatch, now_local: NaiveDateTime) -> Result<Todo> {
    let cur = get(db, id, now_local)?;
    let title = p.title.as_deref().map(clean_title).transpose()?.unwrap_or_else(|| cur.title.clone());
    let notes = p.notes.as_deref().map(clean_notes).transpose()?.unwrap_or_else(|| cur.notes.clone());
    let priority = p.priority.as_deref().map(|v| one_of("priority", v, &PRIORITIES)).transpose()?.unwrap_or_else(|| cur.priority.clone());
    let category = p.category.as_deref().map(clean_category).transpose()?.unwrap_or_else(|| cur.category.clone());
    let recurrence = p.recurrence.as_deref().map(|v| one_of("repeat setting", v, &RECURRENCES)).transpose()?.unwrap_or_else(|| cur.recurrence.clone());
    let interval = p.recur_interval.unwrap_or(cur.recur_interval);
    if !(1..=365).contains(&interval) {
        return Err(bad("the repeat interval must be between 1 and 365"));
    }
    let due_date = match &p.due_date {
        Some(v) => v.as_deref().map(clean_date).transpose()?,
        None => cur.due_date.clone(),
    };
    let mut due_time = match &p.due_time {
        Some(v) => v.as_deref().map(clean_time).transpose()?,
        None => cur.due_time.clone(),
    };
    if due_date.is_none() {
        due_time = None;
    }
    if recurrence != "none" && due_date.is_none() {
        return Err(bad("a repeating task needs a date"));
    }
    if recurrence != "none" && cur.parent_id.is_some() {
        return Err(bad("a subtask cannot repeat"));
    }
    let date_changed = due_date != cur.due_date || due_time != cur.due_time;
    let mut remind_at = match &p.remind_at {
        Some(v) => v.as_deref().map(clean_instant).transpose()?,
        None => cur.remind_at.clone(),
    };
    // A reminder set for the old deadline moves with the deadline (unless it was changed too).
    if p.remind_at.is_none() && date_changed && cur.remind_at.is_some() {
        remind_at = due_date.as_deref().and_then(|d| default_reminder(d, due_time.as_deref()));
    }
    let project_id = match &p.project_id {
        Some(v) => {
            if cur.parent_id.is_some() {
                return Err(bad("move the parent task; its subtasks follow"));
            }
            if let Some(pid) = v {
                crate::projects::get(db, pid)?;
            }
            v.clone()
        }
        None => cur.project_id.clone(),
    };
    {
        let conn = db.conn()?;
        conn.execute(
            "UPDATE todos SET title=?1, notes=?2, priority=?3, category=?4, due_date=?5, due_time=?6, remind_at=?7, recurrence=?8, recur_interval=?9, project_id=?10, updated_at=?11 WHERE id=?12",
            rusqlite::params![title, notes, priority, category, due_date, due_time, remind_at, recurrence, interval, project_id, now(), id],
        )?;
        if project_id != cur.project_id {
            conn.execute("UPDATE todos SET project_id=?1 WHERE parent_id=?2", rusqlite::params![project_id, id])?;
        }
    }
    if date_changed {
        let fmt = |d: &Option<String>, t: &Option<String>| match (d, t) {
            (Some(d), Some(t)) => format!("{d} {t}"),
            (Some(d), None) => d.clone(),
            _ => "no date".into(),
        };
        event(db, id, "rescheduled", &format!("{} → {}", fmt(&cur.due_date, &cur.due_time), fmt(&due_date, &due_time)))?;
    } else if title != cur.title || notes != cur.notes || priority != cur.priority || category != cur.category || recurrence != cur.recurrence {
        event(db, id, "edited", "")?;
    }
    match p.status.as_deref() {
        Some(s) if s != cur.status => set_status(db, id, s, now_local),
        _ => get(db, id, now_local),
    }
}

/// Change a task's status. Completing a repeating task creates its next occurrence.
/// Completing a task completes its open subtasks; a cancelled task cancels them.
pub fn set_status(db: &Db, id: &str, status: &str, now_local: NaiveDateTime) -> Result<Todo> {
    let status = one_of("status", status, &STATUSES)?;
    let cur = get(db, id, now_local)?;
    if cur.status == status {
        return Ok(cur);
    }
    let ts = now();
    let finished = matches!(status.as_str(), "done" | "cancelled");
    {
        let conn = db.conn()?;
        conn.execute(
            "UPDATE todos SET status=?1, completed_at=?2, updated_at=?3 WHERE id=?4",
            rusqlite::params![status, if status == "done" { Some(ts.clone()) } else { None }, ts, id],
        )?;
        if finished {
            conn.execute(
                "UPDATE todos SET status=?1, completed_at=?2, updated_at=?3 WHERE parent_id=?4 AND status IN ('open','in_progress')",
                rusqlite::params![status, if status == "done" { Some(ts.clone()) } else { None }, ts, id],
            )?;
        }
    }
    let kind = match (cur.status.as_str(), status.as_str()) {
        (_, "done") => "completed",
        (_, "cancelled") => "cancelled",
        ("done" | "cancelled", _) => "reopened",
        (_, "in_progress") => "started",
        _ => "status",
    };
    event(db, id, kind, "")?;
    if status == "done" && cur.recurrence != "none" && cur.parent_id.is_none() {
        spawn_next(db, &cur, now_local)?;
    }
    get(db, id, now_local)
}

/// The next occurrence of a repeating task, after the later of its date and today (so a task
/// finished late does not leave a backlog of past occurrences).
fn spawn_next(db: &Db, done: &Todo, now_local: NaiveDateTime) -> Result<()> {
    let Some(from) = done.due_date.as_deref().and_then(when::iso_date) else { return Ok(()) };
    let mut next = when::next_occurrence(from, &done.recurrence, done.recur_interval);
    while let Some(n) = next {
        if n >= now_local.date() {
            break;
        }
        next = when::next_occurrence(n, &done.recurrence, done.recur_interval);
    }
    let Some(next) = next else { return Ok(()) };
    let date = next.to_string();
    // Never two open copies of the same repeating task on the same date.
    let exists: i64 = db.conn()?.query_row(
        "SELECT COUNT(*) FROM todos WHERE title=?1 AND recurrence=?2 AND due_date=?3 AND status IN ('open','in_progress') AND parent_id IS NULL",
        rusqlite::params![done.title, done.recurrence, date],
        |r| r.get(0),
    )?;
    if exists > 0 {
        return Ok(());
    }
    let remind_at = done.remind_at.as_ref().and_then(|_| default_reminder(&date, done.due_time.as_deref()));
    let created = create(
        db,
        NewTodo {
            title: done.title.clone(),
            notes: done.notes.clone(),
            priority: Some(done.priority.clone()),
            category: Some(done.category.clone()),
            project_id: done.project_id.clone(),
            due_date: Some(date),
            due_time: done.due_time.clone(),
            remind_at,
            recurrence: Some(done.recurrence.clone()),
            recur_interval: Some(done.recur_interval),
            source: Some(done.source.clone()),
            ..Default::default()
        },
        now_local,
    )?;
    // Subtasks repeat with their parent, reset to open.
    let subs: Vec<String> = {
        let conn = db.conn()?;
        let mut st = conn.prepare("SELECT title FROM todos WHERE parent_id=?1 AND status != 'cancelled' ORDER BY created_at, rowid")?;
        let rows = st.query_map([&done.id], |r| r.get::<_, String>(0))?;
        rows.collect::<std::result::Result<_, _>>()?
    };
    for title in subs {
        create(db, NewTodo { title, parent_id: Some(created.id.clone()), ..Default::default() }, now_local)?;
    }
    event(db, &created.id, "repeated", &format!("next occurrence of a {} task", done.recurrence))?;
    Ok(())
}

/// Push a task's date back by `days` (from today if it is already overdue or has no date).
pub fn postpone(db: &Db, id: &str, days: i64, now_local: NaiveDateTime) -> Result<Todo> {
    if !(1..=365).contains(&days) {
        return Err(bad("postpone by 1 to 365 days"));
    }
    let cur = get(db, id, now_local)?;
    if matches!(cur.status.as_str(), "done" | "cancelled") {
        return Err(AtlasError::Conflict("a finished task cannot be postponed; reopen it first".into()));
    }
    let today = now_local.date();
    let base = cur.due_date.as_deref().and_then(when::iso_date).filter(|d| *d >= today).unwrap_or(today);
    let new_date = (base + Duration::days(days)).to_string();
    let remind_at = cur.remind_at.as_ref().and_then(|_| default_reminder(&new_date, cur.due_time.as_deref()));
    db.conn()?.execute(
        "UPDATE todos SET due_date=?1, remind_at=?2, postponed_count=postponed_count+1, updated_at=?3 WHERE id=?4",
        rusqlite::params![new_date, remind_at, now(), id],
    )?;
    event(db, id, "postponed", &format!("{} → {new_date}", cur.due_date.as_deref().unwrap_or("no date")))?;
    get(db, id, now_local)
}

/// Delete a task and its subtasks. Returns how many rows went.
pub fn delete(db: &Db, id: &str) -> Result<usize> {
    let conn = db.conn()?;
    let subs: i64 = conn.query_row("SELECT COUNT(*) FROM todos WHERE parent_id=?1", [id], |r| r.get(0))?;
    let n = conn.execute("DELETE FROM todos WHERE id=?1", [id])?;
    if n == 0 {
        return Err(AtlasError::NotFound(format!("task '{id}'")));
    }
    Ok(n + subs as usize)
}

fn like(s: &str) -> String {
    format!("%{}%", s.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_"))
}

/// Top-level tasks matching a filter, most pressing first.
pub fn list(db: &Db, f: &Filter, now_local: NaiveDateTime) -> Result<Vec<Todo>> {
    let today = now_local.date();
    let week_end = today + Duration::days(6);
    let mut sql = format!("SELECT {COLS} FROM todos t WHERE t.parent_id IS NULL");
    let mut args: Vec<Sql> = Vec::new();
    let open = " AND t.status IN ('open','in_progress')";
    match f.view.as_str() {
        "today" => {
            sql.push_str(open);
            sql.push_str(" AND t.due_date IS NOT NULL AND t.due_date <= ?");
            args.push(today.to_string().into());
        }
        "week" => {
            sql.push_str(open);
            sql.push_str(" AND t.due_date IS NOT NULL AND t.due_date <= ?");
            args.push(week_end.to_string().into());
        }
        "overdue" => {
            sql.push_str(open);
            sql.push_str(" AND t.due_date IS NOT NULL AND t.due_date <= ?");
            args.push(today.to_string().into());
        }
        "upcoming" => {
            sql.push_str(open);
            sql.push_str(" AND t.due_date > ?");
            args.push(today.to_string().into());
        }
        "someday" => {
            sql.push_str(open);
            sql.push_str(" AND t.due_date IS NULL");
        }
        "done" => sql.push_str(" AND t.status = 'done'"),
        "all" => {}
        "" | "open" => sql.push_str(open),
        other => return Err(bad(format!("unknown view '{other}'"))),
    }
    if let Some(p) = &f.project_id {
        sql.push_str(" AND t.project_id = ?");
        args.push(p.clone().into());
    }
    if let Some(c) = f.category.as_deref().filter(|c| !c.is_empty()) {
        sql.push_str(" AND t.category = ? COLLATE NOCASE");
        args.push(c.to_string().into());
    }
    if let Some(p) = f.priority.as_deref().filter(|p| !p.is_empty()) {
        sql.push_str(" AND t.priority = ?");
        args.push(one_of("priority", p, &PRIORITIES)?.into());
    }
    if let Some(s) = f.search.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        sql.push_str(" AND (t.title LIKE ? ESCAPE '\\' OR t.notes LIKE ? ESCAPE '\\' OR t.category LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM todos c WHERE c.parent_id = t.id AND c.title LIKE ? ESCAPE '\\'))");
        for _ in 0..4 {
            args.push(like(s).into());
        }
    }
    sql.push_str(if f.view == "done" {
        " ORDER BY t.completed_at DESC LIMIT 300"
    } else {
        " ORDER BY (t.due_date IS NULL), t.due_date, (t.due_time IS NULL), t.due_time, \
          CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.created_at LIMIT 500"
    });
    let conn = db.conn()?;
    let mut st = conn.prepare(&sql)?;
    let rows = st.query_map(params_from_iter(args), |r| from_row(r, now_local))?;
    let mut out: Vec<Todo> = rows.collect::<std::result::Result<_, _>>()?;
    if f.view == "overdue" {
        out.retain(|t| t.overdue);
    }
    Ok(out)
}

pub fn subtasks(db: &Db, parent_id: &str, now_local: NaiveDateTime) -> Result<Vec<Todo>> {
    let conn = db.conn()?;
    let mut st = conn.prepare(&format!("SELECT {COLS} FROM todos t WHERE t.parent_id = ?1 ORDER BY t.created_at, t.rowid"))?;
    let rows = st.query_map([parent_id], |r| from_row(r, now_local))?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn history(db: &Db, id: &str) -> Result<Vec<TodoEvent>> {
    let conn = db.conn()?;
    let mut st = conn.prepare("SELECT at, kind, detail FROM todo_events WHERE todo_id = ?1 ORDER BY id")?;
    let rows = st.query_map([id], |r| Ok(TodoEvent { at: r.get(0)?, kind: r.get(1)?, detail: r.get(2)? }))?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

/// Distinct categories in use, for filters and suggestions.
pub fn categories(db: &Db) -> Result<Vec<String>> {
    let conn = db.conn()?;
    let mut st = conn.prepare("SELECT DISTINCT category FROM todos WHERE category != '' ORDER BY category COLLATE NOCASE")?;
    let rows = st.query_map([], |r| r.get::<_, String>(0))?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

/// Top-level tasks completed since a local date (for "recent accomplishments").
pub fn completed_since(db: &Db, since_utc: &str, now_local: NaiveDateTime) -> Result<Vec<Todo>> {
    let conn = db.conn()?;
    let mut st = conn.prepare(&format!("SELECT {COLS} FROM todos t WHERE t.parent_id IS NULL AND t.status = 'done' AND t.completed_at >= ?1 ORDER BY t.completed_at DESC LIMIT 100"))?;
    let rows = st.query_map([since_utc], |r| from_row(r, now_local))?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn counts(db: &Db, now_local: NaiveDateTime) -> Result<Counts> {
    let open = list(db, &Filter { view: "open".into(), ..Default::default() }, now_local)?;
    let today = now_local.date().to_string();
    let week_end = (now_local.date() + Duration::days(6)).to_string();
    let start_today = local_to_utc(now_local.date(), NaiveTime::MIN);
    let start_week = local_to_utc(now_local.date() - Duration::days(6), NaiveTime::MIN);
    Ok(Counts {
        open: open.len() as u32,
        overdue: open.iter().filter(|t| t.overdue).count() as u32,
        today: open.iter().filter(|t| t.due_date.as_deref().is_some_and(|d| d <= today.as_str())).count() as u32,
        week: open.iter().filter(|t| t.due_date.as_deref().is_some_and(|d| d <= week_end.as_str())).count() as u32,
        done_today: completed_since(db, &start_today, now_local)?.len() as u32,
        done_week: completed_since(db, &start_week, now_local)?.len() as u32,
    })
}

/// Create a task from a quick-entry line ("Call the dentist friday 9am !high #health").
pub fn quick_add(db: &Db, line: &str, project_id: Option<String>, source: &str, conversation_id: Option<String>, now_local: NaiveDateTime) -> Result<Todo> {
    let q = when::parse_quick(line, now_local);
    // A repeating task with no date starts today.
    let due_date = q.due_date.or(q.recurrence.map(|_| now_local.date())).map(|d| d.to_string());
    let due_time = q.due_time.map(|t| t.format("%H:%M").to_string());
    // "Remind me…" sets a reminder; so does giving a time (a timed task is worth a nudge).
    let remind_at = match (&due_date, q.remind || due_time.is_some()) {
        (Some(d), true) => default_reminder(d, due_time.as_deref()),
        _ => None,
    };
    create(
        db,
        NewTodo {
            title: q.title,
            priority: q.priority.map(str::to_string),
            category: q.category,
            project_id,
            due_date,
            due_time,
            remind_at,
            recurrence: q.recurrence.map(str::to_string),
            source: Some(source.to_string()),
            conversation_id,
            ..Default::default()
        },
        now_local,
    )
}
