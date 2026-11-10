//! The dispatcher is the only code path that executes tools.
//!
//! `run` performs the full lifecycle for one model-requested call (validate → record step →
//! classify → approval → execute → validate output). `execute_authorized` is the narrow
//! execution gate: it re-checks the policy and, for gated classes, atomically consumes an
//! approval bound to this exact tool and argument hash. Nothing else calls `Tool::execute`.

use super::registry::{self, ToolRegistry};
use super::{action_hash, ToolContext, ToolError};
use crate::approvals::{self, Approval, Broker, Outcome};
use crate::error::{AtlasError, Result};
use crate::events::{notify, SharedBus, Topic};
use crate::policy::{self, Decision};
use crate::storage::Db;
use crate::tasks::{self, TaskStatus};
use serde::Serialize;
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DispatchEvent {
    StepStarted { step_id: String, tool_id: String, task_id: String },
    ApprovalRequired { approval: Approval },
    StepFinished { step_id: String, tool_id: String, status: String, task_id: String },
}

#[derive(Debug, Clone, Serialize)]
pub struct DispatchResult {
    pub step_id: Option<String>,
    pub tool_id: String,
    pub status: String,
    pub output: Option<Value>,
    pub error: Option<String>,
    /// What is returned to the model as the tool result.
    pub content_for_model: String,
    pub is_error: bool,
}

pub struct Dispatcher {
    pub registry: Arc<ToolRegistry>,
    pub db: Arc<Db>,
    pub broker: Arc<Broker>,
    pub bus: SharedBus,
    pub notifications: Arc<crate::desktop::NotificationCenter>,
}

fn failed(tool_id: &str, step_id: Option<String>, status: &str, msg: String) -> DispatchResult {
    DispatchResult {
        step_id,
        tool_id: tool_id.into(),
        status: status.into(),
        output: None,
        content_for_model: format!("ERROR ({status}): {msg}"),
        error: Some(msg),
        is_error: true,
    }
}

impl Dispatcher {
    pub async fn run(
        &self,
        ctx: &ToolContext,
        task_id: &str,
        call_id: &str,
        tool_id: &str,
        input: Value,
        on_event: &mut (dyn FnMut(DispatchEvent) + Send),
    ) -> DispatchResult {
        let Some(tool) = self.registry.get(tool_id) else {
            return failed(tool_id, None, "failed", format!("unknown tool '{tool_id}'"));
        };
        let d = tool.descriptor().clone();
        let hash = action_hash(tool_id, &input);
        let step_id = match tasks::add_step(&self.db, task_id, tool_id, call_id, &input, d.permission, &hash) {
            Ok(id) => id,
            Err(e) => return failed(tool_id, None, "failed", e.to_string()),
        };
        notify(&self.bus, Topic::Tasks, Some(task_id));
        on_event(DispatchEvent::StepStarted { step_id: step_id.clone(), tool_id: tool_id.into(), task_id: task_id.into() });

        let result = self.run_step(ctx, task_id, &step_id, tool_id, &input, &hash, on_event).await;
        let _ = tasks::update_step(
            &self.db,
            &step_id,
            &result.status,
            result.output.as_ref(),
            result.error.as_deref(),
            None,
            None,
        );
        crate::audit::record(
            &self.db,
            "tool.step",
            if result.is_error { "warn" } else { "info" },
            Some(task_id),
            Some(tool_id),
            json!({"status": result.status, "step_id": step_id}),
        );
        notify(&self.bus, Topic::Tasks, Some(task_id));
        notify(&self.bus, Topic::Registry, Some(tool_id));
        on_event(DispatchEvent::StepFinished {
            step_id: step_id.clone(),
            tool_id: tool_id.into(),
            status: result.status.clone(),
            task_id: task_id.into(),
        });
        DispatchResult { step_id: Some(step_id), ..result }
    }

    #[allow(clippy::too_many_arguments)]
    async fn run_step(
        &self,
        ctx: &ToolContext,
        task_id: &str,
        step_id: &str,
        tool_id: &str,
        input: &Value,
        hash: &str,
        on_event: &mut (dyn FnMut(DispatchEvent) + Send),
    ) -> DispatchResult {
        let Some(tool) = self.registry.get(tool_id) else {
            return failed(tool_id, None, "failed", "tool was removed".into());
        };
        let d = tool.descriptor().clone();
        if !registry::is_enabled(&self.db, tool_id).unwrap_or(false) {
            return failed(tool_id, None, "denied", format!("the '{}' tool is disabled in Atlas", d.name));
        }
        if let super::Availability::NeedsConfiguration { reason } | super::Availability::Unavailable { reason } = tool.availability(ctx) {
            return failed(tool_id, None, "failed", format!("'{}' is not available: {reason}", d.name));
        }
        if input.get("__invalid_json__").is_some() {
            return failed(tool_id, None, "failed", "INVALID_JSON: the tool arguments were not valid JSON (possibly truncated); nothing was executed".into());
        }
        if let Err(errs) = self.registry.validate_input(tool_id, input) {
            return failed(tool_id, None, "failed", format!("invalid arguments, nothing was executed: {}", errs.join("; ")));
        }

        let mut approval_id: Option<String> = None;
        match policy::decide(d.permission, d.network, &ctx.settings) {
            Decision::Deny { reason } => return failed(tool_id, None, "denied", format!("permission denied: {reason}")),
            Decision::Allow => {}
            Decision::Ask => {
                let preview = tool.preview_in(input, ctx);
                let id = match approvals::create(&self.db, task_id, step_id, tool_id, hash, &preview) {
                    Ok(id) => id,
                    Err(e) => return failed(tool_id, None, "failed", e.to_string()),
                };
                let _ = tasks::update_step(&self.db, step_id, "awaiting_approval", None, None, Some(&id), None);
                let _ = tasks::transition(&self.db, task_id, TaskStatus::AwaitingApproval);
                if let Ok(list) = approvals::for_task(&self.db, task_id)
                    && let Some(a) = list.into_iter().find(|a| a.id == id) {
                        on_event(DispatchEvent::ApprovalRequired { approval: a });
                    }
                notify(&self.bus, Topic::Approvals, Some(&id));
                notify(&self.bus, Topic::Tasks, Some(task_id));
                let _ = self.notifications.raise(
                    &ctx.settings.desktop.notifications,
                    crate::desktop::NewNotification {
                        category: crate::desktop::Category::Approval,
                        title: "Atlas needs your approval",
                        detail: &preview.action,
                        target: "approvals",
                        dedupe_key: &format!("approval:{id}"),
                        only_if_away: false,
                    },
                );
                let timeout = Duration::from_secs(ctx.settings.limits.approval_timeout_secs as u64);
                let outcome = self.broker.wait(&self.db, &id, timeout, &ctx.cancel).await;
                self.notifications.resolve(&format!("approval:{id}"));
                notify(&self.bus, Topic::Approvals, Some(&id));
                if tasks::status(&self.db, task_id).ok() == Some(TaskStatus::AwaitingApproval) {
                    let _ = tasks::transition(&self.db, task_id, TaskStatus::Running);
                }
                match outcome {
                    Outcome::Approved => approval_id = Some(id),
                    Outcome::Rejected => return failed(tool_id, None, "rejected", "the user declined this action; it was not performed".into()),
                    Outcome::Expired => return failed(tool_id, None, "expired", "the approval request timed out; the action was not performed".into()),
                    Outcome::Cancelled => return failed(tool_id, None, "cancelled", "the task was cancelled before the action ran".into()),
                }
            }
        }

        let _ = tasks::update_step(&self.db, step_id, "running", None, None, None, None);
        let started = Instant::now();
        let res = self.execute_authorized(ctx, tool_id, input, approval_id.as_deref()).await;
        let ms = started.elapsed().as_millis() as i64;
        let _ = tasks::update_step(&self.db, step_id, "running", None, None, None, Some(ms));
        match res {
            Ok(output) => {
                registry::record_use(&self.db, tool_id, false);
                let mut content = output.to_string();
                if content.len() > d.max_output_bytes {
                    content = crate::ai::truncate(&content, d.max_output_bytes);
                }
                DispatchResult {
                    step_id: None,
                    tool_id: tool_id.into(),
                    status: "succeeded".into(),
                    output: Some(output),
                    error: None,
                    content_for_model: content,
                    is_error: false,
                }
            }
            Err(e) => {
                registry::record_use(&self.db, tool_id, true);
                let status = match &e {
                    AtlasError::Cancelled => "cancelled",
                    AtlasError::PermissionDenied(_) => "denied",
                    _ => "failed",
                };
                failed(tool_id, None, status, e.to_string())
            }
        }
    }

    /// The execution gate. See module docs.
    pub async fn execute_authorized(
        &self,
        ctx: &ToolContext,
        tool_id: &str,
        input: &Value,
        approval_id: Option<&str>,
    ) -> Result<Value> {
        let tool = self.registry.get(tool_id).ok_or_else(|| AtlasError::NotFound(format!("tool '{tool_id}'")))?;
        let d = tool.descriptor().clone();
        if !registry::is_enabled(&self.db, tool_id)? {
            return Err(AtlasError::PermissionDenied(format!("tool '{tool_id}' is disabled")));
        }
        self.registry
            .validate_input(tool_id, input)
            .map_err(|e| AtlasError::Validation(e.join("; ")))?;
        let hash = action_hash(tool_id, input);
        match policy::decide(d.permission, d.network, &ctx.settings) {
            Decision::Deny { reason } => return Err(AtlasError::PermissionDenied(reason)),
            Decision::Allow => {}
            Decision::Ask => {
                let id = approval_id.ok_or_else(|| {
                    AtlasError::PermissionDenied(format!("'{tool_id}' requires an approval for this exact action"))
                })?;
                approvals::consume(&self.db, id, tool_id, &hash)?;
                crate::audit::record(&self.db, "approval.consumed", "info", ctx.task_id.as_deref(), Some(tool_id), json!({"approval_id": id}));
            }
        }
        // The tool's own limit, capped by the user's global tool timeout.
        let secs = d.timeout_secs.min(ctx.settings.limits.tool_timeout_secs).max(1);
        let timeout = Duration::from_secs(secs as u64);
        let out = tokio::select! {
            _ = ctx.cancel.cancelled() => return Err(AtlasError::Cancelled),
            r = tokio::time::timeout(timeout, tool.execute(input.clone(), ctx)) => match r {
                Err(_) => return Err(AtlasError::Timeout(format!("'{tool_id}' exceeded {secs}s"))),
                Ok(Err(ToolError { code, message })) => return Err(AtlasError::Tool(format!("[{code}] {message}"))),
                Ok(Ok(v)) => v,
            },
        };
        if let Err(errs) = self.registry.validate_output(tool_id, &out) {
            return Err(AtlasError::Tool(format!("'{tool_id}' returned output that failed validation: {}", errs.join("; "))));
        }
        Ok(out)
    }
}
