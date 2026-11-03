//! Deterministic tools for automated tests only (compiled with `test` or `test-support`).

use super::descriptor;
use crate::tools::{PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

/// Echoes its input. Read-only.
pub struct Echo(ToolDescriptor);
impl Echo {
    pub fn new() -> Self {
        Self(descriptor(
            "test.echo",
            "Echo (test)",
            "Return the message unchanged.",
            "test",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{"message":{"type":"string"}},"required":["message"],"additionalProperties":false}),
            json!({"type":"object","properties":{"echo":{"type":"string"}},"required":["echo"]}),
            5,
            "none",
        ))
    }
}
impl Default for Echo {
    fn default() -> Self {
        Self::new()
    }
}
#[async_trait]
impl Tool for Echo {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        Ok(json!({"echo": input["message"]}))
    }
}

/// A consequential action with an observable side effect counter.
pub struct SendMessage {
    d: ToolDescriptor,
    pub sent: Arc<AtomicUsize>,
}
impl SendMessage {
    pub fn new(sent: Arc<AtomicUsize>) -> Self {
        Self {
            d: descriptor(
                "test.send_message",
                "Send message (test)",
                "Pretend to send a message (increments a counter).",
                "test",
                PermissionClass::Consequential,
                false,
                json!({"type":"object","properties":{"to":{"type":"string"},"body":{"type":"string"}},"required":["to","body"],"additionalProperties":false}),
                json!({"type":"object","properties":{"sent":{"type":"boolean"}},"required":["sent"]}),
                5,
                "test",
            ),
            sent,
        }
    }
}
#[async_trait]
impl Tool for SendMessage {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.d
    }
    async fn execute(&self, _input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        self.sent.fetch_add(1, Ordering::SeqCst);
        Ok(json!({"sent": true}))
    }
}

pub struct Destroy(ToolDescriptor, pub Arc<AtomicUsize>);
impl Destroy {
    pub fn new(count: Arc<AtomicUsize>) -> Self {
        Self(
            descriptor(
                "test.destroy",
                "Destroy (test)",
                "A destructive operation.",
                "test",
                PermissionClass::Destructive,
                false,
                json!({"type":"object","properties":{},"additionalProperties":false}),
                json!({"type":"object"}),
                5,
                "test",
            ),
            count,
        )
    }
}
#[async_trait]
impl Tool for Destroy {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, _input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        self.1.fetch_add(1, Ordering::SeqCst);
        Ok(json!({}))
    }
}

/// Sleeps longer than its timeout.
pub struct Slow(ToolDescriptor);
impl Slow {
    pub fn new() -> Self {
        Self(descriptor(
            "test.slow",
            "Slow (test)",
            "Sleeps for 10 seconds.",
            "test",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{},"additionalProperties":false}),
            json!({"type":"object"}),
            1,
            "none",
        ))
    }
}
impl Default for Slow {
    fn default() -> Self {
        Self::new()
    }
}
#[async_trait]
impl Tool for Slow {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, _input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
        Ok(json!({}))
    }
}

/// Returns output that violates its own schema.
pub struct BadOutput(ToolDescriptor);
impl BadOutput {
    pub fn new() -> Self {
        Self(descriptor(
            "test.bad_output",
            "Bad output (test)",
            "Returns invalid output.",
            "test",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{},"additionalProperties":false}),
            json!({"type":"object","properties":{"n":{"type":"integer"}},"required":["n"]}),
            5,
            "none",
        ))
    }
}
impl Default for BadOutput {
    fn default() -> Self {
        Self::new()
    }
}
#[async_trait]
impl Tool for BadOutput {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, _input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        Ok(json!({"n": "not a number"}))
    }
}
