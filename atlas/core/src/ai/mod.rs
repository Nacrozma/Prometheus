//! Provider-neutral AI types and the `ChatProvider` trait. Adapters translate between these
//! types and each provider's wire format. Credentials are injected into adapters by the core
//! at request time and never appear in these types.

pub mod anthropic;
pub mod catalog;
#[cfg(any(test, feature = "test-support"))]
pub mod mock;
pub mod openai;
pub mod sse;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio_util::sync::CancellationToken;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum ProviderKind {
    Anthropic,
    /// OpenAI's own API.
    Openai,
    /// Any server implementing the OpenAI Chat Completions API (OpenRouter, Groq, LM Studio...).
    OpenaiCompatible,
    /// Ollama's OpenAI-compatible endpoint on this machine.
    Ollama,
    /// OpenRouter (OpenAI-compatible API that fronts many vendors).
    Openrouter,
    /// Mistral AI's API (OpenAI-compatible chat completions).
    Mistral,
    /// Cerebras Inference API (OpenAI-compatible chat completions).
    Cerebras,
    /// Deterministic scripted provider for automated tests only.
    Mock,
}

impl ProviderKind {
    pub fn is_local(self) -> bool {
        matches!(self, ProviderKind::Ollama | ProviderKind::Mock)
    }
    pub fn needs_key(self) -> bool {
        matches!(
            self,
            ProviderKind::Anthropic
                | ProviderKind::Openai
                | ProviderKind::OpenaiCompatible
                | ProviderKind::Openrouter
                | ProviderKind::Mistral
                | ProviderKind::Cerebras
        )
    }
    /// Kinds served by the OpenAI Chat Completions adapter.
    pub fn openai_wire(self) -> bool {
        matches!(
            self,
            ProviderKind::Openai
                | ProviderKind::OpenaiCompatible
                | ProviderKind::Ollama
                | ProviderKind::Openrouter
                | ProviderKind::Mistral
                | ProviderKind::Cerebras
        )
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    User,
    Assistant,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Part {
    Text { text: String },
    ToolCall { id: String, name: String, input: Value },
    ToolResult { call_id: String, content: String, is_error: bool },
}

/// Provider-exact content captured from a response (e.g. Anthropic content blocks including
/// thinking signatures). Replayed verbatim to the same provider kind so history stays
/// append-only, which some providers require.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct NativeContent {
    pub kind: ProviderKind,
    pub model: String,
    pub blocks: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ChatMessage {
    pub role: Role,
    pub parts: Vec<Part>,
    pub native: Option<NativeContent>,
}

impl ChatMessage {
    pub fn user_text(text: impl Into<String>) -> Self {
        Self { role: Role::User, parts: vec![Part::Text { text: text.into() }], native: None }
    }
    pub fn text(&self) -> String {
        self.parts
            .iter()
            .filter_map(|p| if let Part::Text { text } = p { Some(text.as_str()) } else { None })
            .collect::<Vec<_>>()
            .join("")
    }
    pub fn tool_calls(&self) -> Vec<(String, String, Value)> {
        self.parts
            .iter()
            .filter_map(|p| match p {
                Part::ToolCall { id, name, input } => Some((id.clone(), name.clone(), input.clone())),
                _ => None,
            })
            .collect()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSpec {
    /// Wire-safe name (`^[a-zA-Z0-9_-]{1,64}$`), derived from the registry id.
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EffortHint {
    Low,
    Medium,
    High,
}

#[derive(Debug, Clone)]
pub struct ChatRequest {
    pub model: String,
    pub system: String,
    pub messages: Vec<ChatMessage>,
    pub tools: Vec<ToolSpec>,
    pub max_tokens: u32,
    pub effort: Option<EffortHint>,
    pub reasoning_summary: bool,
    /// Provider-specific opt-in (Anthropic server-side refusal fallback).
    pub refusal_fallback: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Usage {
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum StopReason {
    EndTurn,
    ToolUse,
    MaxTokens,
    Refusal { category: Option<String> },
    Other { reason: String },
}

#[derive(Debug, Clone)]
pub struct ChatResponse {
    pub message: ChatMessage,
    pub stop: StopReason,
    pub usage: Usage,
    /// Model that actually produced the response (may differ after a provider-side fallback).
    pub served_model: String,
    pub notices: Vec<String>,
}

/// Incremental events while a response streams.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum StreamEvent {
    TextDelta { text: String },
    ReasoningDelta { text: String },
    ToolCallStarted { id: String, name: String },
    Notice { text: String },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelInfo {
    pub id: String,
    pub display_name: String,
    pub context_window: Option<u64>,
    pub max_output_tokens: Option<u64>,
    /// None = unknown.
    pub supports_tools: Option<bool>,
    pub supports_vision: Option<bool>,
    pub supports_reasoning: Option<bool>,
    pub supports_effort: Option<bool>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProviderErrorKind {
    Auth,
    RateLimited,
    Unavailable,
    BadRequest,
    NotFound,
    Timeout,
    Cancelled,
    Network,
    Decode,
    Server,
    Overloaded,
}

#[derive(Debug, Clone, Serialize, Deserialize, thiserror::Error)]
#[error("{kind:?}: {message}")]
pub struct ProviderError {
    pub kind: ProviderErrorKind,
    pub message: String,
    pub status: Option<u16>,
    pub retry_after_secs: Option<u64>,
}

impl ProviderError {
    pub fn new(kind: ProviderErrorKind, message: impl Into<String>) -> Self {
        Self { kind, message: crate::redact::redact(&message.into()), status: None, retry_after_secs: None }
    }

    /// Whether a bounded retry of the same request is reasonable.
    pub fn retryable(&self) -> bool {
        matches!(
            self.kind,
            ProviderErrorKind::RateLimited
                | ProviderErrorKind::Server
                | ProviderErrorKind::Overloaded
                | ProviderErrorKind::Network
        )
    }

    pub fn from_status(status: u16, body: &str, retry_after: Option<u64>) -> Self {
        let kind = match status {
            401 | 403 => ProviderErrorKind::Auth,
            404 => ProviderErrorKind::NotFound,
            408 => ProviderErrorKind::Timeout,
            429 => ProviderErrorKind::RateLimited,
            400 | 409 | 413 | 422 => ProviderErrorKind::BadRequest,
            529 => ProviderErrorKind::Overloaded,
            500..=599 => ProviderErrorKind::Server,
            _ => ProviderErrorKind::Unavailable,
        };
        let detail = extract_error_message(body).unwrap_or_else(|| format!("HTTP {status}"));
        Self {
            kind,
            message: crate::redact::redact(&truncate(&detail, 500)),
            status: Some(status),
            retry_after_secs: retry_after,
        }
    }

    pub fn from_reqwest(e: &reqwest::Error) -> Self {
        let kind = if e.is_timeout() {
            ProviderErrorKind::Timeout
        } else if e.is_connect() {
            ProviderErrorKind::Unavailable
        } else if e.is_decode() {
            ProviderErrorKind::Decode
        } else {
            ProviderErrorKind::Network
        };
        // reqwest errors may include the URL; never a header, so no key can leak, but redact anyway.
        Self::new(kind, e.to_string())
    }
}

fn extract_error_message(body: &str) -> Option<String> {
    let v: Value = serde_json::from_str(body).ok()?;
    v.pointer("/error/message")
        .or_else(|| v.get("message"))
        .or_else(|| v.get("error"))
        .and_then(|m| m.as_str().map(str::to_string))
}

pub(crate) fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        return s.to_string();
    }
    let mut end = max;
    while !s.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}…", &s[..end])
}

pub fn retry_after(headers: &reqwest::header::HeaderMap) -> Option<u64> {
    headers.get("retry-after").and_then(|v| v.to_str().ok()).and_then(|s| s.trim().parse().ok())
}

pub type EventSink<'a> = &'a mut (dyn FnMut(StreamEvent) + Send);

#[async_trait]
pub trait ChatProvider: Send + Sync {
    fn kind(&self) -> ProviderKind;
    async fn list_models(&self) -> Result<Vec<ModelInfo>, ProviderError>;
    async fn stream_chat(
        &self,
        req: ChatRequest,
        sink: EventSink<'_>,
        cancel: CancellationToken,
    ) -> Result<ChatResponse, ProviderError>;
}

/// Map registry ids like `files.read` to wire-safe tool names like `files_read`.
pub fn wire_tool_name(id: &str) -> String {
    id.chars().map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c } else { '_' }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_mapping() {
        assert_eq!(ProviderError::from_status(401, "{}", None).kind, ProviderErrorKind::Auth);
        let e = ProviderError::from_status(429, r#"{"error":{"message":"slow down"}}"#, Some(7));
        assert_eq!(e.kind, ProviderErrorKind::RateLimited);
        assert_eq!(e.message, "slow down");
        assert_eq!(e.retry_after_secs, Some(7));
        assert!(e.retryable());
        assert!(!ProviderError::from_status(400, "", None).retryable());
    }

    #[test]
    fn error_messages_are_redacted() {
        let e = ProviderError::from_status(401, r#"{"error":{"message":"bad key sk-ant-api03-abcdefghijklmnop"}}"#, None);
        assert!(!e.message.contains("abcdefghijklmnop"));
    }

    #[test]
    fn wire_names() {
        assert_eq!(wire_tool_name("files.read"), "files_read");
    }
}
