//! Atlas consulting its specialists. The specialists' own tool calls go through the same
//! dispatcher, permissions and approvals; this tool only starts a mission and returns its results.

use super::descriptor;
use crate::tools::{Availability, PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use serde_json::{json, Value};

pub struct Consult(ToolDescriptor);
impl Consult {
    pub fn new() -> Self {
        let ids: Vec<&str> = crate::specialists::registry().iter().map(|s| s.id).collect();
        Self(descriptor(
            "specialist.consult",
            "Consult specialists",
            "Ask one to three of your specialists to work on a focused objective, in order (each sees the previous results): \
             researcher (evidence and sources), planner (staged plan from existing tasks), writer (drafts), data_analyst (computed figures), \
             document_analyst (the user's Knowledge Vault, with citations), project_coordinator (progress from recorded tasks), \
             security_reviewer (read-only review of a Forge project), engineer (changes in a Forge project, with approvals). \
             Only use this when focused work clearly helps; answer simple questions yourself. Review the results before presenting them.",
            "specialists",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{
                "specialists":{"type":"array","items":{"type":"string","enum":ids},"minItems":1,"maxItems":3},
                "objective":{"type":"string","minLength":3,"maxLength":2000},
                "forge_project_id":{"type":"string","maxLength":64}
            },"required":["specialists","objective"],"additionalProperties":false}),
            json!({"type":"object"}),
            30,
            "Starts a specialist mission with only the context each specialist declares.",
        ))
    }
}
impl Default for Consult {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for Consult {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    fn availability(&self, ctx: &ToolContext) -> Availability {
        if ctx.settings.specialists.enabled {
            Availability::Available
        } else {
            Availability::Unavailable { reason: "specialists are turned off in Settings".into() }
        }
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        let workflow: Vec<String> = input["specialists"].as_array().map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect()).unwrap_or_default();
        let conversation: Option<String> =
            ctx.task_id.as_deref().and_then(|t| ctx.db.conn().ok()?.query_row("SELECT conversation_id FROM tasks WHERE id = ?1", [t], |r| r.get(0)).ok()).flatten();
        let forge = input["forge_project_id"].as_str().map(str::to_string).or_else(|| ctx.forge.as_ref().map(|f| f.project_id.clone()));
        ctx.services
            .consult_specialists(input["objective"].as_str().unwrap_or_default(), workflow, ctx.project_id.clone(), forge, conversation)
            .await
            .map_err(|e| ToolError::new("specialist", e))
    }
}
