use super::descriptor;
use crate::memory::{self, MemoryKind};
use crate::tools::{ActionPreview, Availability, PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use serde_json::{json, Value};

fn memory_enabled(ctx: &ToolContext) -> Availability {
    if ctx.settings.memory.enabled {
        Availability::Available
    } else {
        Availability::Unavailable { reason: "memory is turned off in Settings".into() }
    }
}

pub struct SearchMemory(ToolDescriptor);
impl SearchMemory {
    pub fn new() -> Self {
        Self(descriptor(
            "memory.search",
            "Search memory",
            "Search the user's saved memories (global and the active project's) for relevant preferences, facts and notes.",
            "memory",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{"query":{"type":"string","minLength":2,"maxLength":300}},"required":["query"],"additionalProperties":false}),
            json!({"type":"object","properties":{"results":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string"},"kind":{"type":"string"},"content":{"type":"string"},"reason":{"type":"string"}},"required":["id","kind","content","reason"]}}},"required":["results"]}),
            5,
            "Your saved memories in the current scope.",
        ))
    }
}
impl Default for SearchMemory {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for SearchMemory {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    fn availability(&self, ctx: &ToolContext) -> Availability {
        memory_enabled(ctx)
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        let r = memory::search(&ctx.db, input["query"].as_str().unwrap_or_default(), ctx.project_id.as_deref(), 8)
            .map_err(|e| ToolError::new("memory", e.to_string()))?;
        Ok(json!({"results": r.iter().map(|x| json!({
            "id": x.memory.id, "kind": x.memory.kind, "content": x.memory.content, "reason": x.reason
        })).collect::<Vec<_>>()}))
    }
}

pub struct SaveMemory(ToolDescriptor);
impl SaveMemory {
    pub fn new() -> Self {
        Self(descriptor(
            "memory.save",
            "Save a memory",
            "Propose saving a durable memory (a stated preference, fact or note) for future conversations. Only use when \
             the user asks you to remember something or clearly states a lasting preference. Never save credentials or \
             sensitive personal data. The user must approve.",
            "memory",
            PermissionClass::LocalWrite,
            false,
            json!({"type":"object","properties":{
                "content":{"type":"string","minLength":3,"maxLength":2000},
                "kind":{"type":"string","enum":["preference","fact","note"]},
                "project_scoped":{"type":"boolean"}
            },"required":["content","kind"],"additionalProperties":false}),
            json!({"type":"object","properties":{"id":{"type":"string"},"saved":{"type":"boolean"}},"required":["id","saved"]}),
            5,
            "Adds an entry to your local memory store.",
        ))
    }
}
impl Default for SaveMemory {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for SaveMemory {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    fn availability(&self, ctx: &ToolContext) -> Availability {
        memory_enabled(ctx)
    }
    fn preview(&self, input: &Value) -> ActionPreview {
        let scoped = input["project_scoped"].as_bool().unwrap_or(false);
        ActionPreview {
            action: "Remember this".into(),
            target: if scoped { "Memory (current project)".into() } else { "Memory (all conversations)".into() },
            details: format!("[{}] {}", input["kind"].as_str().unwrap_or("note"), input["content"].as_str().unwrap_or_default()),
            consequences: "Atlas may use this in future conversations. You can edit or delete it any time in Memory.".into(),
        }
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        let kind = match input["kind"].as_str() {
            Some("preference") => MemoryKind::Preference,
            Some("fact") => MemoryKind::Fact,
            _ => MemoryKind::Note,
        };
        let project = if input["project_scoped"].as_bool().unwrap_or(false) { ctx.project_id.as_deref() } else { None };
        let m = memory::create(&ctx.db, project, kind, input["content"].as_str().unwrap_or_default(), "assistant", false)
            .map_err(|e| ToolError::new(e.code(), e.to_string()))?;
        // Verify the write.
        let saved = memory::get(&ctx.db, &m.id).is_ok();
        Ok(json!({"id": m.id, "saved": saved}))
    }
}
