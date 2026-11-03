//! The tool registry: the single authoritative list of tools, their schemas and their state.
//! Screens, the model's tool list and the Atlas Map are all derived from it.

use super::{Availability, Tool, ToolContext, ToolDescriptor};
use crate::error::{AtlasError, Result};
use crate::storage::{now, Db};
use regex::Regex;
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::sync::{Arc, LazyLock, RwLock};

static ID_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$").unwrap());

struct Entry {
    tool: Arc<dyn Tool>,
    input: jsonschema::Validator,
    output: jsonschema::Validator,
}

#[derive(Default)]
pub struct ToolRegistry {
    entries: RwLock<BTreeMap<String, Entry>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ToolInfo {
    #[serde(flatten)]
    pub descriptor: ToolDescriptor,
    pub enabled: bool,
    pub availability: Availability,
    pub use_count: i64,
    pub failure_count: i64,
    pub last_used_at: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct ToolStats {
    pub enabled: bool,
    pub use_count: i64,
    pub failure_count: i64,
    pub last_used_at: Option<String>,
}

impl ToolRegistry {
    pub fn register(&self, tool: Arc<dyn Tool>) -> Result<()> {
        let d = tool.descriptor().clone();
        if !ID_RE.is_match(&d.id) || d.id.len() > 64 {
            return Err(AtlasError::Validation(format!("invalid tool id '{}'", d.id)));
        }
        if d.input_schema.get("type") != Some(&Value::String("object".into())) {
            return Err(AtlasError::Validation(format!("tool '{}' input schema must be an object", d.id)));
        }
        let input = jsonschema::validator_for(&d.input_schema)
            .map_err(|e| AtlasError::Validation(format!("tool '{}' input schema: {e}", d.id)))?;
        let output = jsonschema::validator_for(&d.output_schema)
            .map_err(|e| AtlasError::Validation(format!("tool '{}' output schema: {e}", d.id)))?;
        let mut map = self.entries.write().map_err(|_| AtlasError::Internal("registry lock".into()))?;
        if map.contains_key(&d.id) {
            return Err(AtlasError::Conflict(format!("tool '{}' is already registered", d.id)));
        }
        let wire = crate::ai::wire_tool_name(&d.id);
        if map.keys().any(|k| crate::ai::wire_tool_name(k) == wire) {
            return Err(AtlasError::Conflict(format!("tool '{}' collides with an existing wire name", d.id)));
        }
        map.insert(d.id.clone(), Entry { tool, input, output });
        Ok(())
    }

    pub fn unregister(&self, id: &str) -> bool {
        self.entries.write().map(|mut m| m.remove(id).is_some()).unwrap_or(false)
    }

    pub fn get(&self, id: &str) -> Option<Arc<dyn Tool>> {
        self.entries.read().ok()?.get(id).map(|e| e.tool.clone())
    }

    /// Resolve a model-facing wire name back to the registry id.
    pub fn id_for_wire(&self, wire: &str) -> Option<String> {
        self.entries.read().ok()?.keys().find(|k| crate::ai::wire_tool_name(k) == wire).cloned()
    }

    pub fn ids(&self) -> Vec<String> {
        self.entries.read().map(|m| m.keys().cloned().collect()).unwrap_or_default()
    }

    pub fn all(&self) -> Vec<Arc<dyn Tool>> {
        self.entries.read().map(|m| m.values().map(|e| e.tool.clone()).collect()).unwrap_or_default()
    }

    pub fn validate_input(&self, id: &str, input: &Value) -> std::result::Result<(), Vec<String>> {
        self.validate(id, input, true)
    }

    pub fn validate_output(&self, id: &str, output: &Value) -> std::result::Result<(), Vec<String>> {
        self.validate(id, output, false)
    }

    fn validate(&self, id: &str, v: &Value, input: bool) -> std::result::Result<(), Vec<String>> {
        let map = self.entries.read().map_err(|_| vec!["registry lock".to_string()])?;
        let e = map.get(id).ok_or_else(|| vec![format!("unknown tool '{id}'")])?;
        let validator = if input { &e.input } else { &e.output };
        let errors: Vec<String> = validator
            .iter_errors(v)
            .take(8)
            .map(|err| {
                let path = err.instance_path().to_string();
                if path.is_empty() { err.to_string() } else { format!("{path}: {err}") }
            })
            .collect();
        if errors.is_empty() { Ok(()) } else { Err(errors) }
    }

    pub fn info(&self, db: &Db, ctx: &ToolContext) -> Result<Vec<ToolInfo>> {
        let stats = stats(db)?;
        Ok(self
            .all()
            .into_iter()
            .map(|t| {
                let d = t.descriptor().clone();
                let s = stats.get(&d.id).cloned().unwrap_or(ToolStats { enabled: true, ..Default::default() });
                ToolInfo {
                    availability: t.availability(ctx),
                    descriptor: d,
                    enabled: s.enabled,
                    use_count: s.use_count,
                    failure_count: s.failure_count,
                    last_used_at: s.last_used_at,
                }
            })
            .collect())
    }
}

pub fn stats(db: &Db) -> Result<HashMap<String, ToolStats>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare("SELECT tool_id, enabled, use_count, failure_count, last_used_at FROM tool_state")?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            ToolStats { enabled: r.get::<_, i64>(1)? != 0, use_count: r.get(2)?, failure_count: r.get(3)?, last_used_at: r.get(4)? },
        ))
    })?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn is_enabled(db: &Db, id: &str) -> Result<bool> {
    let v: Option<i64> = db
        .conn()?
        .query_row("SELECT enabled FROM tool_state WHERE tool_id = ?1", [id], |r| r.get(0))
        .map(Some)
        .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(e) })?;
    Ok(v.map(|x| x != 0).unwrap_or(true))
}

pub fn set_enabled(db: &Db, id: &str, enabled: bool) -> Result<()> {
    db.conn()?.execute(
        "INSERT INTO tool_state(tool_id, enabled) VALUES (?1, ?2) ON CONFLICT(tool_id) DO UPDATE SET enabled = excluded.enabled",
        rusqlite::params![id, enabled as i64],
    )?;
    Ok(())
}

pub fn record_use(db: &Db, id: &str, failed: bool) {
    if let Ok(conn) = db.conn() {
        let _ = conn.execute(
            "INSERT INTO tool_state(tool_id, use_count, failure_count, last_used_at) VALUES (?1, 1, ?2, ?3)
             ON CONFLICT(tool_id) DO UPDATE SET use_count = use_count + 1, failure_count = failure_count + ?2, last_used_at = ?3",
            rusqlite::params![id, failed as i64, now()],
        );
    }
}
