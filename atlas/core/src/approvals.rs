//! Approval records and the broker that waits for the user's decision.
//!
//! Invariants enforced here (and tested):
//! * an approval is bound to one task step, one tool id and one action hash;
//! * it can be decided once (pending → approved | rejected) and consumed once
//!   (approved → consumed) — so the same approval can never run an action twice;
//! * consumption fails if the tool or the arguments differ from what was approved.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use crate::tools::ActionPreview;
use serde::Serialize;
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

#[derive(Debug, Clone, Serialize)]
pub struct Approval {
    pub id: String,
    pub task_id: String,
    pub step_id: String,
    pub tool_id: String,
    pub action_hash: String,
    pub preview: ActionPreview,
    pub status: String,
    pub created_at: String,
    pub decided_at: Option<String>,
}

pub fn create(db: &Db, task_id: &str, step_id: &str, tool_id: &str, hash: &str, preview: &ActionPreview) -> Result<String> {
    let id = new_id();
    db.conn()?.execute(
        "INSERT INTO approvals(id, task_id, step_id, tool_id, action_hash, preview, status, created_at)
         VALUES (?1,?2,?3,?4,?5,?6,'pending',?7)",
        rusqlite::params![id, task_id, step_id, tool_id, hash, serde_json::to_string(preview)?, now()],
    )?;
    Ok(id)
}

/// Record the user's decision. Only a pending approval can be decided.
pub fn decide(db: &Db, id: &str, approve: bool) -> Result<()> {
    let status = if approve { "approved" } else { "rejected" };
    let n = db.conn()?.execute(
        "UPDATE approvals SET status = ?1, decided_at = ?2 WHERE id = ?3 AND status = 'pending'",
        rusqlite::params![status, now(), id],
    )?;
    if n == 0 {
        return Err(AtlasError::Conflict("this approval is no longer pending".into()));
    }
    Ok(())
}

/// Atomically verify and consume an approval for exactly this tool and arguments.
pub fn consume(db: &Db, id: &str, tool_id: &str, hash: &str) -> Result<()> {
    db.tx(|tx| {
        let row: Option<(String, String, String)> = tx
            .query_row("SELECT status, tool_id, action_hash FROM approvals WHERE id = ?1", [id], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?))
            })
            .map(Some)
            .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(e) })?;
        let (status, t, h) = row.ok_or_else(|| AtlasError::PermissionDenied("no such approval".into()))?;
        if t != tool_id || h != hash {
            return Err(AtlasError::PermissionDenied(
                "the action changed after it was approved; a new approval is required".into(),
            ));
        }
        match status.as_str() {
            "approved" => {}
            "consumed" => return Err(AtlasError::PermissionDenied("this approval was already used".into())),
            other => return Err(AtlasError::PermissionDenied(format!("approval is {other}, not approved"))),
        }
        tx.execute("UPDATE approvals SET status = 'consumed', consumed_at = ?1 WHERE id = ?2", rusqlite::params![now(), id])?;
        Ok(())
    })
}

pub fn expire(db: &Db, id: &str) -> Result<()> {
    db.conn()?.execute(
        "UPDATE approvals SET status = 'expired', decided_at = ?1 WHERE id = ?2 AND status = 'pending'",
        rusqlite::params![now(), id],
    )?;
    Ok(())
}

/// Expire every pending approval (startup recovery and emergency stop).
pub fn expire_all_pending(db: &Db) -> Result<usize> {
    Ok(db.conn()?.execute(
        "UPDATE approvals SET status = 'expired', decided_at = ?1 WHERE status = 'pending'",
        [now()],
    )?)
}

fn row_to_approval(r: &rusqlite::Row<'_>) -> rusqlite::Result<Approval> {
    let preview: String = r.get(5)?;
    Ok(Approval {
        id: r.get(0)?,
        task_id: r.get(1)?,
        step_id: r.get(2)?,
        tool_id: r.get(3)?,
        action_hash: r.get(4)?,
        preview: serde_json::from_str(&preview).unwrap_or(ActionPreview {
            action: "unknown".into(),
            target: String::new(),
            details: String::new(),
            consequences: String::new(),
        }),
        status: r.get(6)?,
        created_at: r.get(7)?,
        decided_at: r.get(8)?,
    })
}

const COLS: &str = "id, task_id, step_id, tool_id, action_hash, preview, status, created_at, decided_at";

pub fn list_pending(db: &Db) -> Result<Vec<Approval>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM approvals WHERE status = 'pending' ORDER BY created_at"))?;
    let rows = stmt.query_map([], row_to_approval)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn for_task(db: &Db, task_id: &str) -> Result<Vec<Approval>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM approvals WHERE task_id = ?1 ORDER BY created_at"))?;
    let rows = stmt.query_map([task_id], row_to_approval)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Approved,
    Rejected,
    Expired,
    Cancelled,
}

/// In-process rendezvous between a waiting task and the UI's decision.
#[derive(Default)]
pub struct Broker {
    waiters: Mutex<HashMap<String, oneshot::Sender<bool>>>,
}

impl Broker {
    /// Record the decision durably, then wake the waiting task.
    pub fn resolve(&self, db: &Db, id: &str, approve: bool) -> Result<()> {
        decide(db, id, approve)?;
        if let Some(tx) = self.waiters.lock().map_err(|_| AtlasError::Internal("broker lock".into()))?.remove(id) {
            let _ = tx.send(approve);
        }
        Ok(())
    }

    pub async fn wait(&self, db: &Db, id: &str, timeout: Duration, cancel: &CancellationToken) -> Outcome {
        let (tx, rx) = oneshot::channel();
        if let Ok(mut w) = self.waiters.lock() {
            w.insert(id.to_string(), tx);
        }
        let outcome = tokio::select! {
            _ = cancel.cancelled() => Outcome::Cancelled,
            r = tokio::time::timeout(timeout, rx) => match r {
                Ok(Ok(true)) => Outcome::Approved,
                Ok(Ok(false)) => Outcome::Rejected,
                _ => Outcome::Expired,
            },
        };
        if let Ok(mut w) = self.waiters.lock() {
            w.remove(id);
        }
        if matches!(outcome, Outcome::Expired | Outcome::Cancelled) {
            let _ = expire(db, id);
        }
        outcome
    }

    pub fn pending_count(&self) -> usize {
        self.waiters.lock().map(|w| w.len()).unwrap_or(0)
    }
}
