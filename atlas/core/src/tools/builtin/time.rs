use super::descriptor;
use crate::tools::{PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use chrono::{Datelike, Local, Utc};
use serde_json::{json, Value};

pub struct Now(ToolDescriptor);

impl Now {
    pub fn new() -> Self {
        Self(descriptor(
            "time.now",
            "Current date and time",
            "Return the current date and time from this computer's clock, in UTC and in local time.",
            "compute",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{},"additionalProperties":false}),
            json!({"type":"object","properties":{"utc":{"type":"string"},"local":{"type":"string"},"utc_offset":{"type":"string"},"weekday":{"type":"string"},"unix_seconds":{"type":"integer"}},"required":["utc","local","utc_offset","weekday","unix_seconds"]}),
            2,
            "Reads the system clock only.",
        ))
    }
}

impl Default for Now {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for Now {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, _input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        let local = Local::now();
        Ok(json!({
            "utc": Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
            "local": local.format("%Y-%m-%d %H:%M:%S").to_string(),
            "utc_offset": local.format("%:z").to_string(),
            "weekday": local.weekday().to_string(),
            "unix_seconds": Utc::now().timestamp(),
        }))
    }
}
