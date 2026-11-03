use super::descriptor;
use crate::tools::{PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use serde_json::{json, Value};

pub struct Diagnostics(ToolDescriptor);
impl Diagnostics {
    pub fn new() -> Self {
        Self(descriptor(
            "app.diagnostics",
            "Application diagnostics",
            "Report Atlas's own health: version, platform, database status, provider and tool status, task engine state. Contains no message content.",
            "system",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{},"additionalProperties":false}),
            json!({"type":"object"}),
            10,
            "Atlas configuration status (never secrets or message content).",
        ))
    }
}
impl Default for Diagnostics {
    fn default() -> Self {
        Self::new()
    }
}
#[async_trait]
impl Tool for Diagnostics {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, _input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        Ok(ctx.services.diagnostics().await)
    }
}

pub struct ProviderHealth(ToolDescriptor);
impl ProviderHealth {
    pub fn new() -> Self {
        Self(descriptor(
            "providers.health",
            "Check AI providers",
            "Test connectivity and authentication for each configured AI provider by listing its models. Sends no conversation data.",
            "system",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{},"additionalProperties":false}),
            json!({"type":"object","properties":{"providers":{"type":"array"}},"required":["providers"]}),
            60,
            "Contacts your configured AI providers' model-list endpoints only.",
        ))
    }
}
impl Default for ProviderHealth {
    fn default() -> Self {
        Self::new()
    }
}
#[async_trait]
impl Tool for ProviderHealth {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, _input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        Ok(ctx.services.provider_health().await)
    }
}

pub struct TaskStatus(ToolDescriptor);
impl TaskStatus {
    pub fn new() -> Self {
        Self(descriptor(
            "tasks.status",
            "Task status",
            "Inspect Atlas task records: with `task_id`, one task's steps and outcomes; without it, the most recent tasks.",
            "system",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{"task_id":{"type":"string","maxLength":64}},"additionalProperties":false}),
            json!({"type":"object"}),
            5,
            "Atlas's own task history.",
        ))
    }
}
impl Default for TaskStatus {
    fn default() -> Self {
        Self::new()
    }
}
#[async_trait]
impl Tool for TaskStatus {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        Ok(ctx.services.task_status(input["task_id"].as_str()))
    }
}
