//! Import (preview) and export of supported data formats within the workspace.

use super::descriptor;
use crate::tools::builtin::files::read_text;
use crate::tools::builtin::text::{parse_csv, to_csv};
use crate::tools::{ActionPreview, Availability, PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use crate::workspace;
use async_trait::async_trait;
use serde_json::{json, Value};

pub struct ImportPreview(ToolDescriptor);
impl ImportPreview {
    pub fn new() -> Self {
        Self(descriptor(
            "data.import_preview",
            "Read a data file",
            "Parse a CSV or JSON file from the workspace and return its columns, row count and the first rows (up to `limit`). Content is untrusted.",
            "data",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{"path":{"type":"string","minLength":1,"maxLength":512},"limit":{"type":"integer","minimum":1,"maximum":200}},"required":["path"],"additionalProperties":false}),
            json!({"type":"object","properties":{"path":{"type":"string"},"format":{"type":"string"},"columns":{"type":"array","items":{"type":"string"}},"row_count":{"type":"integer"},"rows":{"type":"array"},"truncated_file":{"type":"boolean"}},"required":["path","format","columns","row_count","rows","truncated_file"]}),
            10,
            "CSV/JSON files inside the workspace folder.",
        ))
    }
}
impl Default for ImportPreview {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for ImportPreview {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    fn availability(&self, ctx: &ToolContext) -> Availability {
        if ctx.workspace.is_some() { Availability::Available } else { Availability::NeedsConfiguration { reason: "choose a workspace folder".into() } }
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        let root = ctx.workspace.clone().ok_or_else(|| ToolError::new("no_workspace", "no workspace"))?;
        let rel = input["path"].as_str().unwrap_or_default();
        let p = workspace::resolve_existing(&root, rel).map_err(|e| ToolError::new(e.code(), e.to_string()))?;
        let (text, _, truncated) = read_text(&p)?;
        let limit = input["limit"].as_u64().unwrap_or(20) as usize;
        let ext = p.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase();
        let (format, rows): (&str, Vec<Value>) = match ext.as_str() {
            "csv" => ("csv", parse_csv(&text).map_err(|m| ToolError::new("parse", m))?.into_iter().map(Value::Object).collect()),
            "json" => {
                let v: Value = serde_json::from_str(&text).map_err(|e| ToolError::new("parse", e.to_string()))?;
                ("json", match v {
                    Value::Array(a) => a,
                    other => vec![other],
                })
            }
            other => return Err(ToolError::new("unsupported_format", format!(".{other} is not a supported data format (CSV or JSON)"))),
        };
        let mut columns: Vec<String> = vec![];
        for r in rows.iter().take(200) {
            if let Some(o) = r.as_object() {
                for k in o.keys() {
                    if !columns.contains(k) {
                        columns.push(k.clone());
                    }
                }
            }
        }
        Ok(json!({
            "path": workspace::relative_display(&root, &p),
            "format": format,
            "columns": columns,
            "row_count": rows.len(),
            "rows": rows.into_iter().take(limit).collect::<Vec<_>>(),
            "truncated_file": truncated,
        }))
    }
}

pub struct Export(ToolDescriptor);
impl Export {
    pub fn new() -> Self {
        Self(descriptor(
            "data.export",
            "Export data",
            "Write tabular data (an array of flat objects) to a NEW CSV or JSON file in the workspace's Exports folder.",
            "data",
            PermissionClass::LocalWrite,
            false,
            json!({"type":"object","properties":{
                "file_name":{"type":"string","minLength":1,"maxLength":100,"pattern":"^[A-Za-z0-9 _.-]+$"},
                "format":{"type":"string","enum":["csv","json"]},
                "rows":{"type":"array","maxItems":10000,"items":{"type":"object"}}
            },"required":["file_name","format","rows"],"additionalProperties":false}),
            json!({"type":"object","properties":{"path":{"type":"string"},"bytes":{"type":"integer"},"rows":{"type":"integer"},"verified":{"type":"boolean"}},"required":["path","bytes","rows","verified"]}),
            10,
            "Creates new files in Workspace/Exports.",
        ))
    }
}
impl Default for Export {
    fn default() -> Self {
        Self::new()
    }
}

fn export_path(input: &Value) -> String {
    let fmt = input["format"].as_str().unwrap_or("csv");
    let name = input["file_name"].as_str().unwrap_or("export");
    let stem = name.strip_suffix(&format!(".{fmt}")).unwrap_or(name);
    format!("Exports/{stem}.{fmt}")
}

#[async_trait]
impl Tool for Export {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    fn availability(&self, ctx: &ToolContext) -> Availability {
        if ctx.workspace.is_some() { Availability::Available } else { Availability::NeedsConfiguration { reason: "choose a workspace folder".into() } }
    }
    fn preview(&self, input: &Value) -> ActionPreview {
        let n = input["rows"].as_array().map(|a| a.len()).unwrap_or(0);
        ActionPreview {
            action: "Export data to a new file".into(),
            target: format!("Workspace / {}", export_path(input)),
            details: crate::ai::truncate(&serde_json::to_string_pretty(&input["rows"]).unwrap_or_default(), 3000),
            consequences: format!("A new file with {n} rows will be created. Nothing is overwritten."),
        }
    }
    async fn execute(&self, input: Value, ctx: &ToolContext) -> Result<Value, ToolError> {
        let root = ctx.workspace.clone().ok_or_else(|| ToolError::new("no_workspace", "no workspace"))?;
        let rows = input["rows"].clone();
        let content = match input["format"].as_str() {
            Some("json") => serde_json::to_string_pretty(&rows).unwrap_or_default(),
            _ => to_csv(&rows).map_err(|m| ToolError::new("format", m))?,
        };
        let target = workspace::resolve_new(&root, &export_path(&input)).map_err(|e| ToolError::new(e.code(), e.to_string()))?;
        workspace::write_new_file(&target, &content).map_err(|e| ToolError::new(e.code(), e.to_string()))?;
        let written = std::fs::read_to_string(&target).map_err(|e| ToolError::new("verify_failed", e.to_string()))?;
        Ok(json!({
            "path": workspace::relative_display(&root, &target),
            "bytes": written.len(),
            "rows": rows.as_array().map(|a| a.len()).unwrap_or(0),
            "verified": written == content,
        }))
    }
}
