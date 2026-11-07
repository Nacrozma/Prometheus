//! Mission Ledger: every piece of work shared with a sibling, with a state machine enforced here
//! (not in the UI), an append-only event log, idempotent sending and honest recovery.
//!
//! States: DRAFT → PLANNED → AWAITING_APPROVAL → RUNNING → REVIEWING → COMPLETED, plus PAUSED,
//! NEEDS_USER_INPUT, FAILED and CANCELLED. Sending is the only side effect; it carries an
//! idempotency key the adapter de-duplicates, and before any re-send Atlas first asks the sibling
//! whether it already has the mission.

use super::Link;
use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MissionState {
    Draft,
    Planned,
    AwaitingApproval,
    Running,
    Reviewing,
    Completed,
    Paused,
    Failed,
    Cancelled,
    NeedsUserInput,
}

impl MissionState {
    pub fn as_str(self) -> &'static str {
        match self {
            MissionState::Draft => "DRAFT",
            MissionState::Planned => "PLANNED",
            MissionState::AwaitingApproval => "AWAITING_APPROVAL",
            MissionState::Running => "RUNNING",
            MissionState::Reviewing => "REVIEWING",
            MissionState::Completed => "COMPLETED",
            MissionState::Paused => "PAUSED",
            MissionState::Failed => "FAILED",
            MissionState::Cancelled => "CANCELLED",
            MissionState::NeedsUserInput => "NEEDS_USER_INPUT",
        }
    }
    pub fn parse(s: &str) -> Option<Self> {
        serde_json::from_value(Value::String(s.into())).ok()
    }
    pub fn is_terminal(self) -> bool {
        matches!(self, MissionState::Completed | MissionState::Failed | MissionState::Cancelled)
    }
    /// The only transitions the ledger accepts.
    pub fn can_go(self, to: MissionState) -> bool {
        use MissionState::*;
        matches!(
            (self, to),
            (Draft, Planned)
                | (Draft, Cancelled)
                | (Planned, Draft)
                | (Planned, AwaitingApproval)
                | (Planned, Cancelled)
                | (AwaitingApproval, Running)
                | (AwaitingApproval, Planned)
                | (AwaitingApproval, Failed)
                | (AwaitingApproval, Cancelled)
                | (Running, Reviewing)
                | (Running, NeedsUserInput)
                | (Running, Paused)
                | (Running, Failed)
                | (Running, Cancelled)
                | (NeedsUserInput, Running)
                | (NeedsUserInput, Reviewing)
                | (NeedsUserInput, Paused)
                | (NeedsUserInput, Cancelled)
                | (NeedsUserInput, Failed)
                | (Paused, Running)
                | (Paused, NeedsUserInput)
                | (Paused, Reviewing)
                | (Paused, Failed)
                | (Paused, Cancelled)
                | (Reviewing, Completed)
                | (Reviewing, NeedsUserInput)
                | (Reviewing, Failed)
        )
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    /// Ask the sibling a question; one answer.
    Consultation,
    /// Atlas implements (in Forge, with approvals); the sibling reviews and proposes. Default.
    Collaborative,
    /// The sibling does the work in its own environment with its own tools and policy.
    Delegated,
}

impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Consultation => "consultation",
            Mode::Collaborative => "collaborative",
            Mode::Delegated => "delegated",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Mission {
    pub id: String,
    pub title: String,
    pub mode: Mode,
    pub objective: String,
    pub shared_context: String,
    pub state: MissionState,
    pub sibling_id: Option<String>,
    pub forge_project_id: Option<String>,
    pub conversation_id: Option<String>,
    pub sent_at: Option<String>,
    pub remote_state: Option<String>,
    pub remote_seq: i64,
    pub result_summary: Option<String>,
    pub last_error: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct MissionEvent {
    pub id: i64,
    pub mission_id: String,
    /// atlas | prometheus | user | system
    pub source: String,
    pub kind: String,
    pub content: String,
    pub remote_seq: Option<i64>,
    pub created_at: String,
}

const COLS: &str = "id, title, mode, objective, shared_context, state, sibling_id, forge_project_id, conversation_id, sent_at, remote_state, remote_seq, result_summary, last_error, created_at, updated_at, idempotency_key";

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<(Mission, String)> {
    let mode: String = r.get(2)?;
    let state: String = r.get(5)?;
    Ok((
        Mission {
            id: r.get(0)?,
            title: r.get(1)?,
            mode: serde_json::from_value(Value::String(mode)).unwrap_or(Mode::Collaborative),
            objective: r.get(3)?,
            shared_context: r.get(4)?,
            state: MissionState::parse(&state).unwrap_or(MissionState::Failed),
            sibling_id: r.get(6)?,
            forge_project_id: r.get(7)?,
            conversation_id: r.get(8)?,
            sent_at: r.get(9)?,
            remote_state: r.get(10)?,
            remote_seq: r.get(11)?,
            result_summary: r.get(12)?,
            last_error: r.get(13)?,
            created_at: r.get(14)?,
            updated_at: r.get(15)?,
        },
        r.get(16)?,
    ))
}

pub fn get(db: &Db, id: &str) -> Result<Mission> {
    get_with_key(db, id).map(|x| x.0)
}

fn get_with_key(db: &Db, id: &str) -> Result<(Mission, String)> {
    db.conn()?.query_row(&format!("SELECT {COLS} FROM missions WHERE id = ?1"), [id], row).map_err(|e| match e {
        rusqlite::Error::QueryReturnedNoRows => AtlasError::NotFound("mission".into()),
        o => o.into(),
    })
}

pub fn list(db: &Db, limit: u32) -> Result<Vec<Mission>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM missions ORDER BY updated_at DESC LIMIT ?1"))?;
    let rows = stmt.query_map([limit.min(500)], row)?;
    Ok(rows.map(|r| r.map(|x| x.0)).collect::<std::result::Result<_, _>>()?)
}

pub fn events(db: &Db, mission_id: &str) -> Result<Vec<MissionEvent>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare("SELECT id, mission_id, source, kind, content, remote_seq, created_at FROM mission_events WHERE mission_id = ?1 ORDER BY id")?;
    let rows = stmt.query_map([mission_id], |r| {
        Ok(MissionEvent { id: r.get(0)?, mission_id: r.get(1)?, source: r.get(2)?, kind: r.get(3)?, content: r.get(4)?, remote_seq: r.get(5)?, created_at: r.get(6)? })
    })?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

fn add_event(db: &Db, mission_id: &str, source: &str, kind: &str, content: &str, remote_seq: Option<i64>) -> Result<bool> {
    // INSERT OR IGNORE + the UNIQUE(mission, source, remote_seq) key make ingestion idempotent.
    let n = db.conn()?.execute(
        "INSERT OR IGNORE INTO mission_events(mission_id, source, kind, content, remote_seq, created_at) VALUES (?1,?2,?3,?4,?5,?6)",
        rusqlite::params![mission_id, source, kind, crate::redact::redact(content), remote_seq, now()],
    )?;
    Ok(n > 0)
}

/// The single place a mission's state changes. Illegal transitions are refused.
pub fn transition(db: &Db, id: &str, to: MissionState, reason: &str) -> Result<Mission> {
    let cur = get(db, id)?;
    if cur.state == to {
        return Ok(cur);
    }
    if !cur.state.can_go(to) {
        return Err(AtlasError::Conflict(format!("a mission cannot go from {} to {}", cur.state.as_str(), to.as_str())));
    }
    let n = db.conn()?.execute(
        "UPDATE missions SET state = ?1, updated_at = ?2 WHERE id = ?3 AND state = ?4",
        rusqlite::params![to.as_str(), now(), id, cur.state.as_str()],
    )?;
    if n == 0 {
        return Err(AtlasError::Conflict("the mission changed at the same time; try again".into()));
    }
    add_event(db, id, "system", "state", &format!("{} → {}{}", cur.state.as_str(), to.as_str(), if reason.is_empty() { String::new() } else { format!(": {reason}") }), None)?;
    get(db, id)
}

pub struct NewMission<'a> {
    pub title: &'a str,
    pub mode: Mode,
    pub objective: &'a str,
    pub shared_context: &'a str,
    pub sibling_id: Option<&'a str>,
    pub forge_project_id: Option<&'a str>,
    pub conversation_id: Option<&'a str>,
}

pub fn create(db: &Db, m: NewMission<'_>) -> Result<Mission> {
    let objective = m.objective.trim();
    if objective.is_empty() || objective.chars().count() > 20_000 {
        return Err(AtlasError::Validation("describe the mission in 1-20000 characters".into()));
    }
    if m.shared_context.chars().count() > 100_000 {
        return Err(AtlasError::Validation("shared context is limited to 100000 characters".into()));
    }
    let title = if m.title.trim().is_empty() { objective.lines().next().unwrap_or(objective).chars().take(80).collect() } else { m.title.trim().chars().take(120).collect::<String>() };
    let id = format!("mis_{}", uuid::Uuid::new_v4().simple());
    let key = new_id();
    let t = now();
    db.conn()?.execute(
        "INSERT INTO missions(id, title, mode, objective, shared_context, state, sibling_id, forge_project_id, conversation_id, idempotency_key, created_at, updated_at)
         VALUES (?1,?2,?3,?4,?5,'DRAFT',?6,?7,?8,?9,?10,?10)",
        rusqlite::params![id, title, m.mode.as_str(), objective, m.shared_context, m.sibling_id, m.forge_project_id, m.conversation_id, key, t],
    )?;
    add_event(db, &id, "user", "objective", objective, None)?;
    get(db, &id)
}

/// Edit a mission before it is sent.
pub fn update_draft(db: &Db, id: &str, title: &str, objective: &str, shared_context: &str, sibling_id: Option<&str>) -> Result<Mission> {
    let cur = get(db, id)?;
    if !matches!(cur.state, MissionState::Draft | MissionState::Planned) {
        return Err(AtlasError::Conflict("a mission can only be edited before it is sent".into()));
    }
    db.conn()?.execute(
        "UPDATE missions SET title = ?1, objective = ?2, shared_context = ?3, sibling_id = ?4, updated_at = ?5 WHERE id = ?6",
        rusqlite::params![title.trim().chars().take(120).collect::<String>(), objective.trim(), shared_context, sibling_id, now(), id],
    )?;
    get(db, id)
}

/// Exactly what leaves Atlas when the mission is sent. Shown to the owner before approval.
pub fn outgoing_payload(m: &Mission) -> Value {
    json!({"mission_id": m.id, "mode": m.mode.as_str(), "objective": m.objective, "context": m.shared_context})
}

fn set_error(db: &Db, id: &str, err: Option<&str>) -> Result<()> {
    db.conn()?.execute("UPDATE missions SET last_error = ?1, updated_at = ?2 WHERE id = ?3", rusqlite::params![err.map(crate::redact::redact), now(), id])?;
    Ok(())
}

/// Send an approved mission. Safe to call again after a failure: the idempotency key makes the
/// adapter return the existing mission instead of starting a second one, and Atlas checks the
/// sibling's status first when it has tried before.
pub async fn send(link: &Link<'_>, id: &str) -> Result<Mission> {
    let (m, key) = get_with_key(link.db, id)?;
    if m.state != MissionState::AwaitingApproval {
        return Err(AtlasError::Conflict("only a mission awaiting approval can be sent".into()));
    }
    let sid = m.sibling_id.clone().ok_or_else(|| AtlasError::Validation("choose a sibling for this mission".into()))?;
    if m.sent_at.is_some() {
        // A previous attempt may have reached the sibling. Check before sending anything again.
        if let Ok((_, st)) = link.call(&sid, "MISSION_STATUS", json!({"mission_id": m.id, "after_seq": 0}), Duration::from_secs(8)).await
            && st["state"].as_str().is_some_and(|s| s != "unknown") {
                add_event(link.db, id, "system", "note", "The sibling already had this mission from an earlier attempt; it was not sent twice.", None)?;
                transition(link.db, id, MissionState::Running, "already accepted by the sibling")?;
                return ingest(link.db, id, &st);
            }
    }
    link.db.conn()?.execute("UPDATE missions SET sent_at = ?1 WHERE id = ?2", rusqlite::params![now(), id])?;
    let mut payload = outgoing_payload(&m);
    payload["idempotency_key"] = Value::String(key);
    match link.call(&sid, "MISSION_CREATE", payload, Duration::from_secs(15)).await {
        Ok((_, ack)) if ack["accepted"].as_bool() == Some(true) => {
            set_error(link.db, id, None)?;
            let note = if ack["duplicate"].as_bool() == Some(true) { "Accepted (the sibling already had it; not started twice)." } else { "Accepted by the sibling." };
            add_event(link.db, id, "system", "sent", note, None)?;
            transition(link.db, id, MissionState::Running, "sent")
        }
        Ok((_, ack)) => {
            let why = ack["reason"].as_str().unwrap_or("no reason given").to_string();
            set_error(link.db, id, Some(&why))?;
            transition(link.db, id, MissionState::Failed, &format!("the sibling declined: {why}"))
        }
        Err(e) => {
            // Unknown whether it arrived; stay awaiting approval so the owner can retry (safely).
            set_error(link.db, id, Some(&e.to_string()))?;
            Err(e)
        }
    }
}

/// Apply a MISSION_STATUS reply: store new events once, map the sibling's state onto the ledger.
pub fn ingest(db: &Db, id: &str, status: &Value) -> Result<Mission> {
    let mut max_seq = get(db, id)?.remote_seq;
    for e in status["events"].as_array().cloned().unwrap_or_default() {
        let seq = e["seq"].as_i64().unwrap_or(0);
        let kind = e["kind"].as_str().unwrap_or("message");
        let source = if kind == "atlas_message" { "atlas" } else { "prometheus" };
        let text: String = e["text"].as_str().unwrap_or("").chars().take(50_000).collect();
        add_event(db, id, source, kind, &text, Some(seq))?;
        max_seq = max_seq.max(seq);
    }
    let remote = status["state"].as_str().unwrap_or("unknown").to_string();
    let summary = status["result"]["summary"].as_str().map(|s| s.chars().take(20_000).collect::<String>());
    db.conn()?.execute(
        "UPDATE missions SET remote_seq = ?1, remote_state = ?2, result_summary = coalesce(?3, result_summary), updated_at = ?4 WHERE id = ?5",
        rusqlite::params![max_seq, remote, summary, now(), id],
    )?;
    let cur = get(db, id)?;
    let target = match remote.as_str() {
        "accepted" | "running" => Some(MissionState::Running),
        "waiting_for_atlas" => Some(MissionState::NeedsUserInput),
        "completed" | "stopped" => Some(MissionState::Reviewing),
        "failed" => Some(MissionState::Failed),
        "cancelled" => Some(MissionState::Cancelled),
        "interrupted" | "unknown" => Some(MissionState::Paused),
        _ => None,
    };
    if let Some(t) = target
        && !cur.state.is_terminal() && cur.state != t && cur.state != MissionState::Paused && cur.state.can_go(t) {
            let why = match remote.as_str() {
                "interrupted" => "the sibling restarted while working; it will not resume on its own",
                "unknown" => "the sibling does not know this mission",
                "waiting_for_atlas" => "the sibling replied and is waiting for you",
                _ => "",
            };
            return transition(db, id, t, why);
        }
    Ok(cur)
}

/// Poll a running mission once (read-only on the sibling's side).
pub async fn sync(link: &Link<'_>, id: &str, wait_ms: u64) -> Result<Mission> {
    let m = get(link.db, id)?;
    let sid = m.sibling_id.clone().ok_or_else(|| AtlasError::Validation("no sibling".into()))?;
    let (_, st) = link
        .call(&sid, "MISSION_STATUS", json!({"mission_id": m.id, "after_seq": m.remote_seq, "wait_ms": wait_ms}), Duration::from_millis(wait_ms + 10_000))
        .await?;
    ingest(link.db, id, &st)
}

/// Reply to the sibling in a collaborative mission (sends the owner's text, nothing else).
pub async fn message(link: &Link<'_>, id: &str, text: &str) -> Result<Mission> {
    let m = get(link.db, id)?;
    if m.mode != Mode::Collaborative {
        return Err(AtlasError::Validation("only collaborative missions take follow-up messages".into()));
    }
    if !matches!(m.state, MissionState::NeedsUserInput | MissionState::Reviewing) {
        return Err(AtlasError::Conflict("the sibling is not waiting for a message right now".into()));
    }
    let text = text.trim();
    if text.is_empty() || text.chars().count() > 20_000 {
        return Err(AtlasError::Validation("message must be 1-20000 characters".into()));
    }
    let sid = m.sibling_id.clone().ok_or_else(|| AtlasError::Validation("no sibling".into()))?;
    let (_, st) = link.call(&sid, "MISSION_EVENT", json!({"mission_id": m.id, "kind": "message", "text": text, "after_seq": m.remote_seq}), Duration::from_secs(15)).await?;
    if let Some(err) = st["error"].as_str() {
        return Err(AtlasError::Conflict(format!("the sibling did not take the message: {err}")));
    }
    if m.state == MissionState::Reviewing {
        transition(link.db, id, MissionState::NeedsUserInput, "rework requested")?;
    }
    transition(link.db, id, MissionState::Running, "message sent")?;
    ingest(link.db, id, &st)
}

/// Accept the result: tells a collaborative sibling it is done, then marks the mission completed.
pub async fn accept(link: &Link<'_>, id: &str, note: &str) -> Result<Mission> {
    let m = get(link.db, id)?;
    if !matches!(m.state, MissionState::Reviewing | MissionState::NeedsUserInput) {
        return Err(AtlasError::Conflict("only a mission under review can be accepted".into()));
    }
    if m.mode == Mode::Collaborative && m.remote_state.as_deref() != Some("completed")
        && let Some(sid) = &m.sibling_id {
            let _ = link.call(sid, "MISSION_EVENT", json!({"mission_id": m.id, "kind": "complete", "text": note}), Duration::from_secs(10)).await;
        }
    if m.state == MissionState::NeedsUserInput {
        transition(link.db, id, MissionState::Reviewing, "accepted by you")?;
    }
    add_event(link.db, id, "user", "accepted", if note.is_empty() { "Accepted." } else { note }, None)?;
    transition(link.db, id, MissionState::Completed, "accepted")
}

pub async fn cancel(link: &Link<'_>, id: &str) -> Result<Mission> {
    let m = get(link.db, id)?;
    if m.state.is_terminal() {
        return Ok(m);
    }
    if m.sent_at.is_some()
        && let Some(sid) = &m.sibling_id
        && let Err(e) = link.call(sid, "MISSION_CANCEL", json!({"mission_id": m.id}), Duration::from_secs(10)).await {
            add_event(link.db, id, "system", "note", &format!("Could not tell the sibling to stop ({e}); it may still be working."), None)?;
        }
    transition(link.db, id, MissionState::Cancelled, "cancelled by you")
}

/// Atlas restarted: nothing is re-sent automatically. Running missions keep polling (read-only);
/// a send that was in flight stays awaiting approval with a note, so the owner decides.
pub fn recover(db: &Db) -> Result<usize> {
    let rows: Vec<String> = {
        let conn = db.conn()?;
        let mut stmt = conn.prepare("SELECT id FROM missions WHERE state = 'AWAITING_APPROVAL' AND sent_at IS NOT NULL")?;
        stmt.query_map([], |r| r.get(0))?.collect::<std::result::Result<_, _>>()?
    };
    for id in &rows {
        add_event(db, id, "system", "note", "Atlas restarted during sending. Sending again first checks whether the sibling already has it.", None)?;
    }
    Ok(rows.len())
}

pub fn active_ids(db: &Db) -> Result<Vec<String>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare("SELECT id FROM missions WHERE state = 'RUNNING' AND sibling_id IS NOT NULL")?;
    let rows = stmt.query_map([], |r| r.get(0))?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn add_user_note(db: &Db, id: &str, kind: &str, content: &str) -> Result<()> {
    get(db, id)?;
    add_event(db, id, "user", kind, content, None)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use MissionState::*;

    fn mk(db: &Db) -> Mission {
        create(db, NewMission { title: "", mode: Mode::Collaborative, objective: "Review the parser", shared_context: "", sibling_id: Some("sib_x"), forge_project_id: None, conversation_id: None }).unwrap()
    }

    #[test]
    fn state_machine_is_enforced_in_the_backend() {
        let db = Db::open_in_memory().unwrap();
        let m = mk(&db);
        assert_eq!(m.state, Draft);
        assert_eq!(m.title, "Review the parser");
        assert_eq!(transition(&db, &m.id, Running, "").unwrap_err().code(), "conflict", "DRAFT cannot jump to RUNNING");
        assert_eq!(transition(&db, &m.id, Completed, "").unwrap_err().code(), "conflict");
        transition(&db, &m.id, Planned, "").unwrap();
        transition(&db, &m.id, AwaitingApproval, "").unwrap();
        transition(&db, &m.id, Running, "").unwrap();
        transition(&db, &m.id, Reviewing, "").unwrap();
        transition(&db, &m.id, Completed, "").unwrap();
        assert!(transition(&db, &m.id, Running, "").is_err(), "terminal states are final");
        let ev = events(&db, &m.id).unwrap();
        assert_eq!(ev.iter().filter(|e| e.kind == "state").count(), 5, "every transition is logged");
        // Every terminal state refuses every move.
        for s in [Completed, Failed, Cancelled] {
            for t in [Draft, Planned, AwaitingApproval, Running, Reviewing, Completed, Paused, Failed, Cancelled, NeedsUserInput] {
                assert!(!s.can_go(t), "{s:?} -> {t:?}");
            }
        }
    }

    #[test]
    fn ingest_is_idempotent_and_maps_remote_states() {
        let db = Db::open_in_memory().unwrap();
        let m = mk(&db);
        for s in [Planned, AwaitingApproval, Running] {
            transition(&db, &m.id, s, "").unwrap();
        }
        let st = json!({"state": "waiting_for_atlas", "events": [{"seq": 1, "kind": "message", "text": "Looks good, but..."}], "result": null});
        let m2 = ingest(&db, &m.id, &st).unwrap();
        assert_eq!((m2.state, m2.remote_seq), (NeedsUserInput, 1));
        ingest(&db, &m.id, &st).unwrap();
        assert_eq!(events(&db, &m.id).unwrap().iter().filter(|e| e.source == "prometheus").count(), 1, "re-delivered events are stored once");
        transition(&db, &m.id, Running, "").unwrap();
        let done = json!({"state": "completed", "events": [{"seq": 2, "kind": "result", "text": "Done"}], "result": {"outcome": "completed", "summary": "Done"}});
        let m3 = ingest(&db, &m.id, &done).unwrap();
        assert_eq!((m3.state, m3.result_summary.as_deref()), (Reviewing, Some("Done")), "a sibling's 'completed' is reviewed by you, not auto-accepted");
        let lost = json!({"state": "interrupted", "events": [], "result": null});
        transition(&db, &m.id, NeedsUserInput, "").unwrap();
        transition(&db, &m.id, Running, "").unwrap();
        assert_eq!(ingest(&db, &m.id, &lost).unwrap().state, Paused);
    }

    #[test]
    fn drafts_are_editable_until_sent_and_recovery_never_resends() {
        let db = Db::open_in_memory().unwrap();
        let m = mk(&db);
        update_draft(&db, &m.id, "T", "New objective", "ctx", Some("sib_y")).unwrap();
        assert_eq!(outgoing_payload(&get(&db, &m.id).unwrap())["context"], "ctx");
        transition(&db, &m.id, Planned, "").unwrap();
        transition(&db, &m.id, AwaitingApproval, "").unwrap();
        db.conn().unwrap().execute("UPDATE missions SET sent_at = 'x' WHERE id = ?1", [&m.id]).unwrap();
        assert!(update_draft(&db, &m.id, "T", "o", "", None).is_err());
        assert_eq!(recover(&db).unwrap(), 1);
        assert_eq!(get(&db, &m.id).unwrap().state, AwaitingApproval, "recovery leaves the decision to the owner");
    }
}
