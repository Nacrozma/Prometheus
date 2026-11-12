//! The daily briefing and the Command Center's data: built only from what Atlas really has
//! (the task list, reminders, missions, approvals, conversations). Nothing is invented: with no
//! calendar connected, the briefing says so instead of listing appointments.

use crate::error::{AtlasError, Result};
use crate::storage::Db;
use crate::todos::{self, Filter, Todo};
use chrono::{Duration, NaiveDateTime, NaiveTime};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct BriefingSettings {
    /// Send a briefing notification every day at `time`. Off until the owner turns it on; the
    /// Command Center shows today's briefing either way.
    pub enabled: bool,
    /// Local time, HH:MM.
    pub time: String,
    pub include_overdue: bool,
    pub include_upcoming: bool,
    pub include_missions: bool,
    pub include_recent: bool,
}

impl Default for BriefingSettings {
    fn default() -> Self {
        Self { enabled: false, time: "08:00".into(), include_overdue: true, include_upcoming: true, include_missions: true, include_recent: true }
    }
}

impl BriefingSettings {
    pub fn validate(&self) -> Result<()> {
        crate::when::hhmm(&self.time).map(|_| ()).ok_or_else(|| AtlasError::Validation(format!("'{}' is not a time (use HH:MM)", self.time)))
    }

    /// The next briefing moment after `now_local`, as a UTC instant.
    pub fn next_run(&self, now_local: NaiveDateTime) -> Option<String> {
        let t = crate::when::hhmm(&self.time)?;
        let today = now_local.date();
        let day = if NaiveDateTime::new(today, t) > now_local { today } else { today + Duration::days(1) };
        Some(todos::local_to_utc(day, t))
    }
}

/// What the Command Center and the briefing show. Lists are bounded.
#[derive(Debug, Clone, Serialize, PartialEq, Default)]
pub struct Briefing {
    pub date: String,
    pub weekday: String,
    pub overdue: Vec<Todo>,
    pub today: Vec<Todo>,
    /// Open tasks due in the next 7 days (after today).
    pub upcoming: Vec<Todo>,
    /// Reminders still to come today, as (local HH:MM, title).
    pub reminders_today: Vec<(String, String)>,
    pub missions: Vec<MissionBrief>,
    pub approvals_pending: u32,
    pub recent_conversations: Vec<ConversationBrief>,
    /// Top-level tasks finished in the last 7 days.
    pub accomplished: Vec<Todo>,
    pub counts: todos::Counts,
    /// Honest limits, e.g. that no calendar is connected.
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MissionBrief {
    pub id: String,
    pub title: String,
    pub state: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ConversationBrief {
    pub id: String,
    pub title: String,
    pub updated_at: String,
}

fn local_hhmm(utc: &str) -> Option<String> {
    chrono::DateTime::parse_from_rfc3339(utc).ok().map(|d| d.with_timezone(&chrono::Local).format("%H:%M").to_string())
}

pub fn build(db: &Db, now_local: NaiveDateTime) -> Result<Briefing> {
    let today = now_local.date();
    let open = todos::list(db, &Filter { view: "open".into(), ..Default::default() }, now_local)?;
    let today_s = today.to_string();
    let week_end = (today + Duration::days(7)).to_string();
    let (overdue, rest): (Vec<Todo>, Vec<Todo>) = open.iter().cloned().partition(|t| t.overdue);
    let today_list: Vec<Todo> = rest.iter().filter(|t| t.due_date.as_deref() == Some(today_s.as_str())).cloned().collect();
    let upcoming: Vec<Todo> = rest.iter().filter(|t| t.due_date.as_deref().is_some_and(|d| d > today_s.as_str() && d <= week_end.as_str())).take(12).cloned().collect();

    let now_utc = todos::local_to_utc(today, now_local.time());
    let end_utc = todos::local_to_utc(today, NaiveTime::from_hms_opt(23, 59, 59).unwrap_or(NaiveTime::MIN));
    let mut reminders_today: Vec<(String, String)> = open
        .iter()
        .filter_map(|t| t.remind_at.as_ref().filter(|r| r.as_str() >= now_utc.as_str() && r.as_str() <= end_utc.as_str()).and_then(|r| local_hhmm(r).map(|h| (h, t.title.clone()))))
        .collect();
    reminders_today.sort();

    let missions = crate::sibling::missions::list(db, 50)?
        .into_iter()
        .filter(|m| !m.state.is_terminal())
        .take(8)
        .map(|m| MissionBrief { id: m.id, title: m.title, state: m.state.as_str().to_string() })
        .collect();
    let conn = db.conn()?;
    let approvals_pending: u32 = conn.query_row("SELECT COUNT(*) FROM approvals WHERE status = 'pending'", [], |r| r.get(0))?;
    let recent_conversations = {
        let mut st = conn.prepare("SELECT id, title, updated_at FROM conversations WHERE archived = 0 ORDER BY updated_at DESC LIMIT 5")?;
        let rows = st.query_map([], |r| Ok(ConversationBrief { id: r.get(0)?, title: r.get(1)?, updated_at: r.get(2)? }))?;
        rows.collect::<std::result::Result<Vec<_>, _>>()?
    };
    drop(conn);
    let since = todos::local_to_utc(today - Duration::days(6), NaiveTime::MIN);
    let accomplished = todos::completed_since(db, &since, now_local)?.into_iter().take(10).collect();
    // Atlas has no calendar connector yet (planned with the Integration Hub), so say so.
    let notes = vec!["No calendar is connected, so appointments are not included.".to_string()];
    Ok(Briefing {
        date: today_s,
        weekday: now_local.format("%A").to_string(),
        overdue,
        today: today_list,
        upcoming,
        reminders_today,
        missions,
        approvals_pending,
        recent_conversations,
        accomplished,
        counts: todos::counts(db, now_local)?,
        notes,
    })
}

fn list_titles(items: &[Todo], max: usize) -> String {
    let mut s = items.iter().take(max).map(|t| t.title.as_str()).collect::<Vec<_>>().join("; ");
    if items.len() > max {
        s.push_str(&format!("; and {} more", items.len() - max));
    }
    s
}

/// The briefing as plain sentences (for the notification and for reading aloud). Task titles
/// are the owner's own words; nothing here is sent anywhere.
pub fn text(b: &Briefing, s: &BriefingSettings) -> String {
    let mut out = Vec::new();
    match b.today.len() {
        0 => out.push("Nothing is due today.".to_string()),
        1 => out.push(format!("Due today: {}.", list_titles(&b.today, 5))),
        n => out.push(format!("{n} tasks are due today: {}.", list_titles(&b.today, 5))),
    }
    if s.include_overdue && !b.overdue.is_empty() {
        out.push(format!("{} overdue: {}.", b.overdue.len(), list_titles(&b.overdue, 3)));
    }
    if !b.reminders_today.is_empty() {
        let r: Vec<String> = b.reminders_today.iter().take(4).map(|(h, t)| format!("{t} at {h}")).collect();
        out.push(format!("Reminders: {}.", r.join("; ")));
    }
    if s.include_upcoming && !b.upcoming.is_empty() {
        out.push(format!("Coming up this week: {}.", list_titles(&b.upcoming, 3)));
    }
    if b.approvals_pending > 0 {
        out.push(format!("{} action{} waiting for your approval.", b.approvals_pending, if b.approvals_pending == 1 { " is" } else { "s are" }));
    }
    if s.include_missions && !b.missions.is_empty() {
        out.push(format!("{} active mission{} with Prometheus.", b.missions.len(), if b.missions.len() == 1 { "" } else { "s" }));
    }
    if s.include_recent && b.counts.done_week > 0 {
        out.push(format!("You finished {} task{} in the last 7 days.", b.counts.done_week, if b.counts.done_week == 1 { "" } else { "s" }));
    }
    out.extend(b.notes.iter().cloned());
    out.join(" ")
}
