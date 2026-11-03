//! Tool contract. A tool declares its schemas, permission class and limits; the registry and
//! dispatcher (not the tool, and never the model) decide whether and how it runs.

pub mod builtin;
pub mod dispatch;
pub mod registry;

use crate::credentials::SharedSecrets;
use crate::settings::Settings;
use crate::storage::Db;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[serde(rename_all = "snake_case")]
pub enum PermissionClass {
    /// Search, calculate, inspect approved data, read status.
    ReadOnly,
    /// Create a draft or a new file inside the approved workspace, save a memory.
    LocalWrite,
    /// Send, publish, modify external records, purchase.
    Consequential,
    /// Permanent deletion, privileged system operations, unrestricted execution.
    Destructive,
}

impl PermissionClass {
    pub fn as_str(self) -> &'static str {
        match self {
            PermissionClass::ReadOnly => "read_only",
            PermissionClass::LocalWrite => "local_write",
            PermissionClass::Consequential => "consequential",
            PermissionClass::Destructive => "destructive",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDescriptor {
    pub id: String,
    pub name: String,
    pub description: String,
    pub category: String,
    pub version: String,
    pub input_schema: Value,
    pub output_schema: Value,
    pub permission: PermissionClass,
    /// Sends data off this computer when it runs.
    pub network: bool,
    /// Integration ids that must be configured (e.g. "web_search").
    pub requires: Vec<String>,
    pub timeout_secs: u32,
    pub max_output_bytes: usize,
    /// Plain-language description of what data the tool can touch.
    pub data_scope: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Availability {
    Available,
    NeedsConfiguration { reason: String },
    Unavailable { reason: String },
}

/// What the approval panel shows the user.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ActionPreview {
    pub action: String,
    pub target: String,
    /// Relevant content or arguments, already bounded in size.
    pub details: String,
    pub consequences: String,
}

#[derive(Debug, Clone, thiserror::Error, Serialize)]
#[error("{message}")]
pub struct ToolError {
    pub code: String,
    pub message: String,
}

impl ToolError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self { code: code.into(), message: crate::redact::redact(&message.into()) }
    }
}

/// Services tools may call that live elsewhere in the core.
#[async_trait]
pub trait ToolServices: Send + Sync {
    async fn diagnostics(&self) -> Value;
    async fn provider_health(&self) -> Value;
    fn task_status(&self, task_id: Option<&str>) -> Value;
}

pub struct ToolContext {
    pub db: Arc<Db>,
    pub secrets: SharedSecrets,
    pub http: reqwest::Client,
    pub settings: Settings,
    pub workspace: Option<PathBuf>,
    pub task_id: Option<String>,
    pub project_id: Option<String>,
    pub cancel: CancellationToken,
    pub services: Arc<dyn ToolServices>,
}

#[async_trait]
pub trait Tool: Send + Sync {
    fn descriptor(&self) -> &ToolDescriptor;
    fn availability(&self, _ctx: &ToolContext) -> Availability {
        Availability::Available
    }
    fn preview(&self, input: &Value) -> ActionPreview {
        let d = self.descriptor();
        ActionPreview {
            action: d.name.clone(),
            target: d.data_scope.clone(),
            details: crate::ai::truncate(&serde_json::to_string_pretty(input).unwrap_or_default(), 4000),
            consequences: String::new(),
        }
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError>;
}

/// Deterministic JSON encoding with sorted object keys, independent of serde_json features.
pub fn canonical_json(v: &Value) -> String {
    match v {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let inner: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}:{}", Value::String(k.clone()), canonical_json(&map[k])))
                .collect();
            format!("{{{}}}", inner.join(","))
        }
        Value::Array(a) => format!("[{}]", a.iter().map(canonical_json).collect::<Vec<_>>().join(",")),
        other => other.to_string(),
    }
}

/// Hash binding an approval to one tool and its exact arguments.
pub fn action_hash(tool_id: &str, input: &Value) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(tool_id.as_bytes());
    h.update(b"\n");
    h.update(canonical_json(input).as_bytes());
    hex::encode(h.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn hash_is_key_order_independent_but_value_sensitive() {
        let a = json!({"path": "a.txt", "content": "x", "nested": {"b": 1, "a": 2}});
        let b = json!({"nested": {"a": 2, "b": 1}, "content": "x", "path": "a.txt"});
        assert_eq!(action_hash("files.create", &a), action_hash("files.create", &b));
        let c = json!({"path": "a.txt", "content": "y", "nested": {"b": 1, "a": 2}});
        assert_ne!(action_hash("files.create", &a), action_hash("files.create", &c));
        assert_ne!(action_hash("files.create", &a), action_hash("doc.draft", &a));
    }
}
