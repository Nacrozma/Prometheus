//! End-to-end test build only (`--features e2e`): in-memory credentials and a deterministic
//! scripted provider so the real desktop app can be driven without API keys or network.
//! The provider is labelled "E2E scripted provider" everywhere it appears.

use async_trait::async_trait;
use atlas_core::ai::*;
use atlas_core::credentials::{MemorySecrets, SharedSecrets};
use atlas_core::providers::{ProviderConfig, ProviderFactory};
use atlas_core::Atlas;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

struct Scripted;

static CALLS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// The user's words, without the <atlas_context> block Atlas prepends for the model.
fn last_user_text(req: &ChatRequest) -> String {
    let raw = req.messages.iter().rev().find(|m| m.role == Role::User && !m.text().is_empty()).map(|m| m.text()).unwrap_or_default();
    match raw.split_once("</atlas_context>") {
        Some((_, rest)) => rest.trim().to_string(),
        None => raw,
    }
}

#[async_trait]
impl ChatProvider for Scripted {
    fn kind(&self) -> ProviderKind {
        ProviderKind::Mock
    }
    async fn list_models(&self) -> Result<Vec<ModelInfo>, ProviderError> {
        Ok(vec![ModelInfo {
            id: "scripted".into(),
            display_name: "Scripted model".into(),
            context_window: Some(100_000),
            max_output_tokens: Some(4096),
            supports_tools: Some(true),
            supports_vision: Some(false),
            supports_reasoning: Some(false),
            supports_effort: Some(false),
        }])
    }
    async fn stream_chat(&self, req: ChatRequest, sink: EventSink<'_>, cancel: CancellationToken) -> Result<ChatResponse, ProviderError> {
        let last = req.messages.last().cloned();
        let after_tool = last.as_ref().is_some_and(|m| m.parts.iter().any(|p| matches!(p, Part::ToolResult { .. })));
        let text = last_user_text(&req);
        let lower = text.to_lowercase();
        let reply = |t: String| ChatResponse {
            message: ChatMessage { role: Role::Assistant, parts: vec![Part::Text { text: t }], native: None },
            stop: StopReason::EndTurn,
            usage: Usage { input_tokens: Some(20), output_tokens: Some(10) },
            served_model: "scripted".into(),
            notices: vec![],
        };
        let call = |name: &str, input: serde_json::Value| ChatResponse {
            message: ChatMessage { role: Role::Assistant, parts: vec![Part::ToolCall { id: format!("call_{}_{name}", CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed)), name: name.into(), input }], native: None },
            stop: StopReason::ToolUse,
            usage: Usage { input_tokens: Some(20), output_tokens: Some(10) },
            served_model: "scripted".into(),
            notices: vec![],
        };
        if after_tool {
            let result = match last.unwrap().parts.first() {
                Some(Part::ToolResult { content, is_error, .. }) => (content.clone(), *is_error),
                _ => (String::new(), true),
            };
            let t = if result.1 { format!("The action did not complete: {}", result.0) } else { format!("Done. Tool result: {}", result.0) };
            return Ok(stream(reply(t), sink, &cancel).await?);
        }
        if let Some(expr) = lower.split("calculate").nth(1) {
            return Ok(call("calc_evaluate", json!({"expression": expr.trim()})));
        }
        if lower.contains("create a note") {
            return Ok(call("files_create", json!({"path": "e2e/hello.md", "content": "# Hello from Atlas\n"})));
        }
        if lower.contains("wait") {
            cancel.cancelled().await;
            return Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled"));
        }
        stream(reply(format!("Echo: {text}")), sink, &cancel).await
    }
}

async fn stream(r: ChatResponse, sink: EventSink<'_>, cancel: &CancellationToken) -> Result<ChatResponse, ProviderError> {
    for w in r.message.text().split_inclusive(' ') {
        if cancel.is_cancelled() {
            return Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled"));
        }
        sink(StreamEvent::TextDelta { text: w.to_string() });
        tokio::time::sleep(Duration::from_millis(15)).await;
    }
    Ok(r)
}

struct Factory;
impl ProviderFactory for Factory {
    fn build(&self, _c: &ProviderConfig, _s: &SharedSecrets, _t: Duration) -> atlas_core::error::Result<Arc<dyn ChatProvider>> {
        Ok(Arc::new(Scripted))
    }
}

pub fn services() -> (SharedSecrets, Option<Arc<dyn ProviderFactory>>) {
    (Arc::new(MemorySecrets::default()), Some(Arc::new(Factory)))
}

pub fn seed(atlas: &Atlas) {
    if atlas.providers().map(|p| p.is_empty()).unwrap_or(false) {
        if let Ok(p) = atlas.add_provider(ProviderKind::Mock, "E2E scripted provider", "http://127.0.0.1:1", Some("scripted")) {
            // Run the real connection test against the scripted provider so it reports "connected".
            let _ = tauri::async_runtime::block_on(atlas.test_provider(&p.id));
        }
    }
}
