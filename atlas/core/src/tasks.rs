//! Task records and the bounded task state machine.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use crate::tools::PermissionClass;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Created,
    Planning,
    AwaitingApproval,
    Ready,
    Running,
    Verifying,
    Completed,
    Failed,
    Cancelled,
    Interrupted,
    Recoverable,
}

impl TaskStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            TaskStatus::Created => "created",
            TaskStatus::Planning => "planning",
            TaskStatus::AwaitingApproval => "awaiting_approval",
            TaskStatus::Ready => "ready",
            TaskStatus::Running => "running",
            TaskStatus::Verifying => "verifying",
            TaskStatus::Completed => "completed",
            TaskStatus::Failed => "failed",
            TaskStatus::Cancelled => "cancelled",
            TaskStatus::Interrupted => "interrupted",
            TaskStatus::Recoverable => "recoverable",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        serde_json::from_value(Value::String(s.into())).ok()
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, TaskStatus::Completed | TaskStatus::Failed | TaskStatus::Cancelled | TaskStatus::Interrupted)
    }

    pub fn is_active(self) -> bool {
        matches!(
            self,
            TaskStatus::Created
                | TaskStatus::Planning
                | TaskStatus::AwaitingApproval
                | TaskStatus::Ready
                | TaskStatus::Running
                | TaskStatus::Verifying
        )
    }

    /// Allowed transitions. Anything else is a bug and is refused.
    pub fn can_transition(self, to: TaskStatus) -> bool {
        use TaskStatus::*;
        if self == to {
            return true;
        }
        match self {
            Created => matches!(to, Planning | Running | Cancelled | Failed | Interrupted),
            Planning => matches!(to, Ready | Running | AwaitingApproval | Cancelled | Failed | Interrupted),
            Ready => matches!(to, Running | Cancelled | Interrupted),
            Running => matches!(to, AwaitingApproval | Verifying | Completed | Failed | Cancelled | Interrupted),
            AwaitingApproval => matches!(to, Running | Cancelled | Failed | Interrupted),
            Verifying => matches!(to, Completed | Failed | Running | Interrupted | Cancelled),
            Recoverable => matches!(to, Running | Cancelled | Failed),
            Interrupted => matches!(to, Recoverable | Cancelled),
            Completed | Failed | Cancelled => false,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Task {
    pub id: String,
    pub conversation_id: Option<String>,
    pub request: String,
    pub status: TaskStatus,
    pub summary: Option<String>,
    pub error: Option<String>,
    pub verification: Option<Value>,
    pub created_at: String,
    pub updated_at: String,
    pub finished_at: Option<String>,
    pub step_count: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Step {
    pub id: String,
    pub task_id: String,
    pub seq: i64,
    pub tool_id: String,
    pub input: Value,
    pub permission: String,
    pub status: String,
    pub output: Option<Value>,
    pub error: Option<String>,
    pub approval_id: Option<String>,
    pub duration_ms: Option<i64>,
    pub started_at: String,
    pub finished_at: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TaskDetail {
    pub task: Task,
    pub steps: Vec<Step>,
    pub approvals: Vec<crate::approvals::Approval>,
}

pub fn create(db: &Db, conversation_id: Option<&str>, request: &str) -> Result<String> {
    let id = new_id();
    let t = now();
    db.conn()?.execute(
        "INSERT INTO tasks(id, conversation_id, request, status, created_at, updated_at) VALUES (?1,?2,?3,'created',?4,?4)",
        rusqlite::params![id, conversation_id, crate::ai::truncate(request, 2000), t],
    )?;
    Ok(id)
}

pub fn status(db: &Db, id: &str) -> Result<TaskStatus> {
    let s: String = db.conn()?.query_row("SELECT status FROM tasks WHERE id = ?1", [id], |r| r.get(0))?;
    TaskStatus::parse(&s).ok_or_else(|| AtlasError::Internal(format!("unknown task status {s}")))
}

pub fn transition(db: &Db, id: &str, to: TaskStatus) -> Result<()> {
    db.tx(|tx| {
        let s: String = tx.query_row("SELECT status FROM tasks WHERE id = ?1", [id], |r| r.get(0))?;
        let from = TaskStatus::parse(&s).ok_or_else(|| AtlasError::Internal("bad status".into()))?;
        if !from.can_transition(to) {
            return Err(AtlasError::Conflict(format!("task cannot move from {} to {}", from.as_str(), to.as_str())));
        }
        let finished = if to.is_terminal() { Some(now()) } else { None };
        tx.execute(
            "UPDATE tasks SET status = ?1, updated_at = ?2, finished_at = COALESCE(?3, finished_at) WHERE id = ?4",
            rusqlite::params![to.as_str(), now(), finished, id],
        )?;
        Ok(())
    })
}

pub fn finish(db: &Db, id: &str, to: TaskStatus, summary: Option<&str>, error: Option<&str>, verification: Option<&Value>) -> Result<()> {
    transition(db, id, to)?;
    db.conn()?.execute(
        "UPDATE tasks SET summary = COALESCE(?1, summary), error = COALESCE(?2, error), verification = COALESCE(?3, verification) WHERE id = ?4",
        rusqlite::params![summary, error.map(crate::redact::redact), verification.map(|v| v.to_string()), id],
    )?;
    Ok(())
}

pub fn add_step(db: &Db, task_id: &str, tool_id: &str, call_id: &str, input: &Value, permission: PermissionClass, hash: &str) -> Result<String> {
    let id = new_id();
    db.tx(|tx| {
        let seq: i64 = tx.query_row("SELECT COALESCE(max(seq), 0) + 1 FROM task_steps WHERE task_id = ?1", [task_id], |r| r.get(0))?;
        tx.execute(
            "INSERT INTO task_steps(id, task_id, seq, tool_id, call_id, input, permission, status, action_hash, started_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,'pending',?8,?9)",
            rusqlite::params![id, task_id, seq, tool_id, call_id, redacted_json(input), permission.as_str(), hash, now()],
        )?;
        Ok(())
    })?;
    Ok(id)
}

/// Inputs/outputs are stored for the execution history, with secrets redacted and size bounded.
fn redacted_json(v: &Value) -> String {
    crate::ai::truncate(&crate::redact::redact(&v.to_string()), 20_000)
}

pub fn update_step(
    db: &Db,
    step_id: &str,
    status: &str,
    output: Option<&Value>,
    error: Option<&str>,
    approval_id: Option<&str>,
    duration_ms: Option<i64>,
) -> Result<()> {
    let finished = if matches!(status, "succeeded" | "failed" | "denied" | "rejected" | "cancelled" | "expired") { Some(now()) } else { None };
    db.conn()?.execute(
        "UPDATE task_steps SET status = ?1, output = COALESCE(?2, output), error = COALESCE(?3, error),
           approval_id = COALESCE(?4, approval_id), duration_ms = COALESCE(?5, duration_ms), finished_at = COALESCE(?6, finished_at)
         WHERE id = ?7",
        rusqlite::params![status, output.map(redacted_json), error.map(crate::redact::redact), approval_id, duration_ms, finished, step_id],
    )?;
    Ok(())
}

fn row_to_task(r: &rusqlite::Row<'_>) -> rusqlite::Result<Task> {
    let status: String = r.get(3)?;
    Ok(Task {
        id: r.get(0)?,
        conversation_id: r.get(1)?,
        request: r.get(2)?,
        status: TaskStatus::parse(&status).unwrap_or(TaskStatus::Failed),
        summary: r.get(4)?,
        error: r.get(5)?,
        verification: r.get::<_, Option<String>>(6)?.and_then(|s| serde_json::from_str(&s).ok()),
        created_at: r.get(7)?,
        updated_at: r.get(8)?,
        finished_at: r.get(9)?,
        step_count: r.get(10)?,
    })
}

const TASK_COLS: &str = "t.id, t.conversation_id, t.request, t.status, t.summary, t.error, t.verification, t.created_at, t.updated_at, t.finished_at,
    (SELECT count(*) FROM task_steps s WHERE s.task_id = t.id)";

pub fn list(db: &Db, status_filter: Option<&str>, limit: u32) -> Result<Vec<Task>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {TASK_COLS} FROM tasks t WHERE (?1 IS NULL OR t.status = ?1) ORDER BY t.created_at DESC LIMIT ?2"
    ))?;
    let rows = stmt.query_map(rusqlite::params![status_filter, limit], row_to_task)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn get(db: &Db, id: &str) -> Result<Task> {
    let conn = db.conn()?;
    Ok(conn.query_row(&format!("SELECT {TASK_COLS} FROM tasks t WHERE t.id = ?1"), [id], row_to_task)?)
}

pub fn steps(db: &Db, task_id: &str) -> Result<Vec<Step>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(
        "SELECT id, task_id, seq, tool_id, input, permission, status, output, error, approval_id, duration_ms, started_at, finished_at
         FROM task_steps WHERE task_id = ?1 ORDER BY seq",
    )?;
    let rows = stmt.query_map([task_id], |r| {
        Ok(Step {
            id: r.get(0)?,
            task_id: r.get(1)?,
            seq: r.get(2)?,
            tool_id: r.get(3)?,
            input: serde_json::from_str(&r.get::<_, String>(4)?).unwrap_or(Value::Null),
            permission: r.get(5)?,
            status: r.get(6)?,
            output: r.get::<_, Option<String>>(7)?.and_then(|s| serde_json::from_str(&s).ok()),
            error: r.get(8)?,
            approval_id: r.get(9)?,
            duration_ms: r.get(10)?,
            started_at: r.get(11)?,
            finished_at: r.get(12)?,
        })
    })?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn detail(db: &Db, id: &str) -> Result<TaskDetail> {
    Ok(TaskDetail { task: get(db, id)?, steps: steps(db, id)?, approvals: crate::approvals::for_task(db, id)? })
}

/// After a crash or restart, nothing is still running: mark active tasks interrupted, their
/// in-flight steps cancelled, and pending approvals expired. Nothing is re-executed.
pub fn recover_after_restart(db: &Db) -> Result<usize> {
    crate::approvals::expire_all_pending(db)?;
    db.tx(|tx| {
        let t = now();
        tx.execute(
            "UPDATE task_steps SET status = 'cancelled', error = 'interrupted by application restart', finished_at = ?1
             WHERE status IN ('pending','awaiting_approval','running')",
            [&t],
        )?;
        let n = tx.execute(
            "UPDATE tasks SET status = 'interrupted', updated_at = ?1, finished_at = ?1,
               error = COALESCE(error, 'Atlas was closed while this task was in progress')
             WHERE status IN ('created','planning','awaiting_approval','ready','running','verifying')",
            [&t],
        )?;
        Ok(n)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transitions_are_enforced() {
        let db = Db::open_in_memory().unwrap();
        let id = create(&db, None, "do it").unwrap();
        transition(&db, &id, TaskStatus::Running).unwrap();
        transition(&db, &id, TaskStatus::Verifying).unwrap();
        finish(&db, &id, TaskStatus::Completed, Some("done"), None, None).unwrap();
        assert!(transition(&db, &id, TaskStatus::Running).is_err(), "completed is terminal");
        assert!(get(&db, &id).unwrap().finished_at.is_some());
    }

    #[test]
    fn restart_marks_interrupted_and_expires_approvals() {
        let db = Db::open_in_memory().unwrap();
        let id = create(&db, None, "x").unwrap();
        transition(&db, &id, TaskStatus::Running).unwrap();
        let step = add_step(&db, &id, "files.create", "c", &serde_json::json!({}), PermissionClass::LocalWrite, "h").unwrap();
        update_step(&db, &step, "awaiting_approval", None, None, None, None).unwrap();
        let preview = crate::tools::ActionPreview { action: "a".into(), target: "t".into(), details: "d".into(), consequences: "c".into() };
        let ap = crate::approvals::create(&db, &id, &step, "files.create", "h", &preview).unwrap();
        assert_eq!(recover_after_restart(&db).unwrap(), 1);
        assert_eq!(status(&db, &id).unwrap(), TaskStatus::Interrupted);
        assert_eq!(steps(&db, &id).unwrap()[0].status, "cancelled");
        assert!(crate::approvals::consume(&db, &ap, "files.create", "h").is_err());
        assert!(crate::approvals::decide(&db, &ap, true).is_err(), "expired approvals cannot be approved later");
    }

    #[test]
    fn step_storage_redacts_secrets() {
        let db = Db::open_in_memory().unwrap();
        let id = create(&db, None, "x").unwrap();
        add_step(&db, &id, "t", "c", &serde_json::json!({"note": "api_key=sk-ant-abcdefghijklmnopqrst"}), PermissionClass::ReadOnly, "h").unwrap();
        let s = &steps(&db, &id).unwrap()[0];
        assert!(!s.input.to_string().contains("abcdefghijklmnopqrst"));
    }
}
