//! Deterministic scripted provider for automated tests. It is compiled only for tests or the
//! `test-support` feature and is never offered in the desktop app's provider list.

use super::*;
use std::collections::VecDeque;
use std::sync::Mutex;

pub enum Script {
    Reply(ChatResponse),
    Fail(ProviderError),
    /// Wait until cancelled (used to test cancellation).
    Hang,
}

pub struct MockProvider {
    pub scripts: Mutex<VecDeque<Script>>,
    pub requests: Mutex<Vec<ChatRequest>>,
}

impl MockProvider {
    pub fn new(scripts: Vec<Script>) -> Self {
        Self { scripts: Mutex::new(scripts.into()), requests: Mutex::new(vec![]) }
    }

    pub fn text(text: &str) -> Script {
        Script::Reply(ChatResponse {
            message: ChatMessage { role: Role::Assistant, parts: vec![Part::Text { text: text.into() }], native: None },
            stop: StopReason::EndTurn,
            usage: Usage { input_tokens: Some(10), output_tokens: Some(5) },
            served_model: "mock-model".into(),
            notices: vec![],
        })
    }

    pub fn tool_call(id: &str, wire_name: &str, input: Value) -> Script {
        Script::Reply(ChatResponse {
            message: ChatMessage {
                role: Role::Assistant,
                parts: vec![Part::ToolCall { id: id.into(), name: wire_name.into(), input }],
                native: None,
            },
            stop: StopReason::ToolUse,
            usage: Usage { input_tokens: Some(10), output_tokens: Some(5) },
            served_model: "mock-model".into(),
            notices: vec![],
        })
    }
}

#[async_trait]
impl ChatProvider for MockProvider {
    fn kind(&self) -> ProviderKind {
        ProviderKind::Mock
    }
    async fn list_models(&self) -> Result<Vec<ModelInfo>, ProviderError> {
        Ok(vec![ModelInfo {
            id: "mock-model".into(),
            display_name: "Mock model".into(),
            context_window: Some(100_000),
            max_output_tokens: Some(4096),
            supports_tools: Some(true),
            supports_vision: Some(false),
            supports_reasoning: Some(false),
            supports_effort: Some(false),
        }])
    }
    async fn stream_chat(
        &self,
        req: ChatRequest,
        sink: EventSink<'_>,
        cancel: CancellationToken,
    ) -> Result<ChatResponse, ProviderError> {
        self.requests.lock().unwrap().push(req);
        let next = self.scripts.lock().unwrap().pop_front();
        match next {
            Some(Script::Reply(r)) => {
                let text = r.message.text();
                for word in text.split_inclusive(' ') {
                    sink(StreamEvent::TextDelta { text: word.to_string() });
                }
                Ok(r)
            }
            Some(Script::Fail(e)) => Err(e),
            Some(Script::Hang) => {
                cancel.cancelled().await;
                Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled"))
            }
            None => Err(ProviderError::new(ProviderErrorKind::Server, "mock script exhausted")),
        }
    }
}
