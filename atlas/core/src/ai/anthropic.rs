//! Anthropic Messages API adapter (raw HTTP; there is no official Rust SDK).
//!
//! Wire notes (API version 2026-10-21):
//! * Streaming SSE events: message_start, content_block_start/delta/stop, message_delta,
//!   message_stop, ping, error.
//! * Assistant content (including thinking blocks with signatures) is captured verbatim and
//!   replayed unchanged on later requests, so the history we send is append-only.
//! * `stop_reason: "refusal"` is a normal 200 response and is surfaced as such.
//! * With server-side fallbacks enabled, a `fallback` content block marks the point where
//!   another model continued; blocks before it other than text are not echoed back.

use super::sse::{for_each_event, SseEvent};
use super::*;
use serde_json::json;
use std::time::Duration;

pub const API_VERSION: &str = "2026-10-21";
pub const DEFAULT_BASE_URL: &str = "https://api.anthropic.com";
const FALLBACK_BETA: &str = "server-side-fallback-2026-07-01";
/// Models documented to accept `fallbacks: "default"` on the Claude API.
const FALLBACK_MODELS: &[&str] = &["claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"];

pub struct AnthropicProvider {
    http: reqwest::Client,
    base_url: String,
    api_key: String,
    idle_timeout: Duration,
}

impl AnthropicProvider {
    pub fn new(http: reqwest::Client, base_url: Option<&str>, api_key: String, idle_timeout: Duration) -> Self {
        Self {
            http,
            base_url: base_url.unwrap_or(DEFAULT_BASE_URL).trim_end_matches('/').to_string(),
            api_key,
            idle_timeout,
        }
    }

    fn headers(&self, req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        req.header("x-api-key", &self.api_key)
            .header("anthropic-version", API_VERSION)
            .header("content-type", "application/json")
    }

    pub fn build_body(req: &ChatRequest) -> Value {
        let messages: Vec<Value> = req.messages.iter().filter_map(to_wire_message).collect();
        let mut body = json!({
            "model": req.model,
            "max_tokens": req.max_tokens,
            "stream": true,
            "messages": messages,
            // Automatic prompt caching of the stable prefix (system + tools + history).
            "cache_control": {"type": "ephemeral"},
        });
        if !req.system.is_empty() {
            body["system"] = json!(req.system);
        }
        if !req.tools.is_empty() {
            body["tools"] = Value::Array(
                req.tools
                    .iter()
                    .map(|t| {
                        json!({
                            "name": t.name,
                            "description": t.description,
                            "input_schema": t.input_schema,
                            // Inputs stream as generated; the core validates every input
                            // against its schema before execution.
                            "eager_input_streaming": true,
                        })
                    })
                    .collect(),
            );
        }
        if req.reasoning_summary {
            body["thinking"] = json!({"type": "adaptive", "display": "summarized"});
        }
        if let Some(e) = req.effort {
            let level = match e {
                EffortHint::Low => "low",
                EffortHint::Medium => "medium",
                EffortHint::High => "high",
            };
            body["output_config"] = json!({"effort": level});
        }
        if req.refusal_fallback && FALLBACK_MODELS.contains(&req.model.as_str()) {
            body["fallbacks"] = json!("default");
        }
        body
    }
}

fn to_wire_message(m: &ChatMessage) -> Option<Value> {
    let role = match m.role {
        Role::User => "user",
        Role::Assistant => "assistant",
    };
    if let Some(native) = &m.native
        && native.kind == ProviderKind::Anthropic {
            if native.blocks.as_array().is_some_and(|a| a.is_empty()) {
                return None;
            }
            return Some(json!({"role": role, "content": native.blocks}));
        }
    let blocks: Vec<Value> = m
        .parts
        .iter()
        .filter_map(|p| match p {
            Part::Text { text } if text.is_empty() => None,
            Part::Text { text } => Some(json!({"type": "text", "text": text})),
            Part::ToolCall { id, name, input } => Some(json!({"type": "tool_use", "id": id, "name": name, "input": input})),
            Part::ToolResult { call_id, content, is_error } => {
                Some(json!({"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": is_error}))
            }
        })
        .collect();
    if blocks.is_empty() {
        return None;
    }
    Some(json!({"role": role, "content": blocks}))
}

/// Accumulates one streamed content block.
#[derive(Debug)]
enum BlockAcc {
    Text(String),
    Thinking { thinking: String, signature: String },
    ToolUse { id: String, name: String, json: String },
    Opaque(Value),
}

impl BlockAcc {
    fn finish(self) -> Value {
        match self {
            BlockAcc::Text(text) => json!({"type": "text", "text": text}),
            BlockAcc::Thinking { thinking, signature } => {
                json!({"type": "thinking", "thinking": thinking, "signature": signature})
            }
            BlockAcc::ToolUse { id, name, json: raw } => {
                let input = if raw.trim().is_empty() {
                    json!({})
                } else {
                    // A truncated or malformed input is kept as a marker so the core reports
                    // INVALID_JSON instead of running the tool with partial arguments.
                    serde_json::from_str(&raw).unwrap_or_else(|_| json!({"__invalid_json__": truncate(&raw, 2000)}))
                };
                json!({"type": "tool_use", "id": id, "name": name, "input": input})
            }
            BlockAcc::Opaque(v) => v,
        }
    }
}

/// Apply the documented echo rule after a mid-output fallback: before the last `fallback`
/// block keep only text blocks (and the marker itself).
pub fn sanitize_after_fallback(blocks: Vec<Value>) -> Vec<Value> {
    let last_fallback = blocks.iter().rposition(|b| b["type"] == "fallback");
    match last_fallback {
        None => blocks,
        Some(idx) => blocks
            .into_iter()
            .enumerate()
            .filter(|(i, b)| *i >= idx || b["type"] == "text")
            .map(|(_, b)| b)
            .collect(),
    }
}

fn parts_from_blocks(blocks: &[Value]) -> Vec<Part> {
    blocks
        .iter()
        .filter_map(|b| match b["type"].as_str() {
            Some("text") => Some(Part::Text { text: b["text"].as_str().unwrap_or_default().to_string() }),
            Some("tool_use") => Some(Part::ToolCall {
                id: b["id"].as_str().unwrap_or_default().to_string(),
                name: b["name"].as_str().unwrap_or_default().to_string(),
                input: b["input"].clone(),
            }),
            _ => None,
        })
        .collect()
}

#[async_trait]
impl ChatProvider for AnthropicProvider {
    fn kind(&self) -> ProviderKind {
        ProviderKind::Anthropic
    }

    async fn list_models(&self) -> Result<Vec<ModelInfo>, ProviderError> {
        let resp = self
            .headers(self.http.get(format!("{}/v1/models?limit=100", self.base_url)))
            .timeout(Duration::from_secs(20))
            .send()
            .await
            .map_err(|e| ProviderError::from_reqwest(&e))?;
        let status = resp.status().as_u16();
        let ra = retry_after(resp.headers());
        let body = resp.text().await.map_err(|e| ProviderError::from_reqwest(&e))?;
        if status != 200 {
            return Err(ProviderError::from_status(status, &body, ra));
        }
        let v: Value = serde_json::from_str(&body)
            .map_err(|e| ProviderError::new(ProviderErrorKind::Decode, format!("model list: {e}")))?;
        let data = v["data"].as_array().cloned().unwrap_or_default();
        Ok(data
            .iter()
            .filter_map(|m| {
                let id = m["id"].as_str()?.to_string();
                let caps = &m["capabilities"];
                let flag = |ptr: &str| caps.pointer(ptr).and_then(Value::as_bool);
                Some(ModelInfo {
                    display_name: m["display_name"].as_str().unwrap_or(&id).to_string(),
                    context_window: m["max_input_tokens"].as_u64(),
                    max_output_tokens: m["max_tokens"].as_u64(),
                    supports_tools: Some(true),
                    supports_vision: flag("/image_input/supported"),
                    supports_reasoning: flag("/thinking/types/adaptive/supported"),
                    supports_effort: flag("/effort/medium/supported").or_else(|| flag("/effort/supported")),
                    id,
                })
            })
            .collect())
    }

    async fn stream_chat(
        &self,
        req: ChatRequest,
        sink: EventSink<'_>,
        cancel: CancellationToken,
    ) -> Result<ChatResponse, ProviderError> {
        let body = Self::build_body(&req);
        let mut rb = self.headers(self.http.post(format!("{}/v1/messages", self.base_url))).json(&body);
        if body.get("fallbacks").is_some() {
            rb = rb.header("anthropic-beta", FALLBACK_BETA);
        }
        let resp = tokio::select! {
            _ = cancel.cancelled() => return Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled")),
            r = rb.send() => r.map_err(|e| ProviderError::from_reqwest(&e))?,
        };
        let status = resp.status().as_u16();
        if status != 200 {
            let ra = retry_after(resp.headers());
            let text = resp.text().await.unwrap_or_default();
            return Err(ProviderError::from_status(status, &text, ra));
        }

        let mut blocks: Vec<Option<BlockAcc>> = Vec::new();
        let mut finished: Vec<(usize, Value)> = Vec::new();
        let mut usage = Usage::default();
        let mut served_model = req.model.clone();
        let mut stop: Option<StopReason> = None;
        let mut notices = Vec::new();

        for_each_event(resp, &cancel, self.idle_timeout, |ev: SseEvent| {
            if ev.data.is_empty() {
                return Ok(true);
            }
            let v: Value = serde_json::from_str(&ev.data)
                .map_err(|e| ProviderError::new(ProviderErrorKind::Decode, format!("stream event: {e}")))?;
            match v["type"].as_str().unwrap_or_default() {
                "message_start" => {
                    if let Some(m) = v.pointer("/message/model").and_then(Value::as_str) {
                        served_model = m.to_string();
                    }
                    usage.input_tokens = v.pointer("/message/usage/input_tokens").and_then(Value::as_u64);
                }
                "content_block_start" => {
                    let idx = v["index"].as_u64().unwrap_or(0) as usize;
                    let cb = &v["content_block"];
                    let acc = match cb["type"].as_str().unwrap_or_default() {
                        "text" => BlockAcc::Text(cb["text"].as_str().unwrap_or_default().to_string()),
                        "thinking" => BlockAcc::Thinking {
                            thinking: cb["thinking"].as_str().unwrap_or_default().to_string(),
                            signature: cb["signature"].as_str().unwrap_or_default().to_string(),
                        },
                        "tool_use" => {
                            let id = cb["id"].as_str().unwrap_or_default().to_string();
                            let name = cb["name"].as_str().unwrap_or_default().to_string();
                            sink(StreamEvent::ToolCallStarted { id: id.clone(), name: name.clone() });
                            BlockAcc::ToolUse { id, name, json: String::new() }
                        }
                        "fallback" => {
                            let to = cb.pointer("/to/model").and_then(Value::as_str).unwrap_or("another model");
                            let text = format!("Anthropic routed this response to {to} after the requested model declined.");
                            sink(StreamEvent::Notice { text: text.clone() });
                            notices.push(text);
                            BlockAcc::Opaque(cb.clone())
                        }
                        _ => BlockAcc::Opaque(cb.clone()),
                    };
                    if blocks.len() <= idx {
                        blocks.resize_with(idx + 1, || None);
                    }
                    blocks[idx] = Some(acc);
                }
                "content_block_delta" => {
                    let idx = v["index"].as_u64().unwrap_or(0) as usize;
                    let d = &v["delta"];
                    if let Some(Some(acc)) = blocks.get_mut(idx) {
                        match (d["type"].as_str().unwrap_or_default(), acc) {
                            ("text_delta", BlockAcc::Text(t)) => {
                                let s = d["text"].as_str().unwrap_or_default();
                                t.push_str(s);
                                sink(StreamEvent::TextDelta { text: s.to_string() });
                            }
                            ("thinking_delta", BlockAcc::Thinking { thinking, .. }) => {
                                let s = d["thinking"].as_str().unwrap_or_default();
                                thinking.push_str(s);
                                if !s.is_empty() {
                                    sink(StreamEvent::ReasoningDelta { text: s.to_string() });
                                }
                            }
                            ("signature_delta", BlockAcc::Thinking { signature, .. }) => {
                                signature.push_str(d["signature"].as_str().unwrap_or_default());
                            }
                            ("input_json_delta", BlockAcc::ToolUse { json, .. }) => {
                                json.push_str(d["partial_json"].as_str().unwrap_or_default());
                            }
                            _ => {}
                        }
                    }
                }
                "content_block_stop" => {
                    let idx = v["index"].as_u64().unwrap_or(0) as usize;
                    if let Some(slot) = blocks.get_mut(idx)
                        && let Some(acc) = slot.take() {
                            finished.push((idx, acc.finish()));
                        }
                }
                "message_delta" => {
                    if let Some(out) = v.pointer("/usage/output_tokens").and_then(Value::as_u64) {
                        usage.output_tokens = Some(out);
                    }
                    if let Some(r) = v.pointer("/delta/stop_reason").and_then(Value::as_str) {
                        stop = Some(match r {
                            "end_turn" | "stop_sequence" => StopReason::EndTurn,
                            "tool_use" => StopReason::ToolUse,
                            "max_tokens" => StopReason::MaxTokens,
                            "refusal" => StopReason::Refusal {
                                category: v
                                    .pointer("/delta/stop_details/category")
                                    .and_then(Value::as_str)
                                    .map(str::to_string),
                            },
                            other => StopReason::Other { reason: other.to_string() },
                        });
                    }
                }
                "message_stop" => return Ok(false),
                "error" => {
                    let kind = match v.pointer("/error/type").and_then(Value::as_str) {
                        Some("overloaded_error") => ProviderErrorKind::Overloaded,
                        Some("rate_limit_error") => ProviderErrorKind::RateLimited,
                        Some("authentication_error") | Some("permission_error") => ProviderErrorKind::Auth,
                        Some("invalid_request_error") => ProviderErrorKind::BadRequest,
                        _ => ProviderErrorKind::Server,
                    };
                    let msg = v.pointer("/error/message").and_then(Value::as_str).unwrap_or("stream error");
                    return Err(ProviderError::new(kind, msg));
                }
                _ => {}
            }
            Ok(true)
        })
        .await?;

        // Blocks that never received content_block_stop (stream cut short) are still kept.
        for (idx, slot) in blocks.into_iter().enumerate() {
            if let Some(acc) = slot {
                finished.push((idx, acc.finish()));
            }
        }
        finished.sort_by_key(|(i, _)| *i);
        let native_blocks = sanitize_after_fallback(finished.into_iter().map(|(_, b)| b).collect());
        let stop = stop.ok_or_else(|| ProviderError::new(ProviderErrorKind::Decode, "stream ended without a stop reason"))?;
        Ok(ChatResponse {
            message: ChatMessage {
                role: Role::Assistant,
                parts: parts_from_blocks(&native_blocks),
                native: Some(NativeContent {
                    kind: ProviderKind::Anthropic,
                    model: served_model.clone(),
                    blocks: Value::Array(native_blocks),
                }),
            },
            stop,
            usage,
            served_model,
            notices,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn sse(events: &[(&str, Value)]) -> String {
        events.iter().map(|(e, d)| format!("event: {e}\ndata: {d}\n\n")).collect()
    }

    fn req() -> ChatRequest {
        ChatRequest {
            model: "claude-opus-5-5".into(),
            system: "sys".into(),
            messages: vec![ChatMessage::user_text("hi")],
            tools: vec![ToolSpec { name: "calc".into(), description: "d".into(), input_schema: json!({"type":"object"}) }],
            max_tokens: 1000,
            effort: Some(EffortHint::Medium),
            reasoning_summary: true,
            refusal_fallback: true,
        }
    }

    #[test]
    fn body_shape() {
        let b = AnthropicProvider::build_body(&req());
        assert_eq!(b["stream"], true);
        assert_eq!(b["tools"][0]["eager_input_streaming"], true);
        assert_eq!(b["thinking"]["type"], "adaptive");
        assert_eq!(b["output_config"]["effort"], "medium");
        assert_eq!(b["fallbacks"], "default");
        assert!(b.get("temperature").is_none());
        let mut r = req();
        r.model = "claude-haiku-4-5".into();
        assert!(AnthropicProvider::build_body(&r).get("fallbacks").is_none());
    }

    #[test]
    fn native_blocks_are_replayed_verbatim() {
        let blocks = json!([{"type":"thinking","thinking":"","signature":"sig"},{"type":"text","text":"ok"}]);
        let m = ChatMessage {
            role: Role::Assistant,
            parts: vec![Part::Text { text: "ok".into() }],
            native: Some(NativeContent { kind: ProviderKind::Anthropic, model: "m".into(), blocks: blocks.clone() }),
        };
        assert_eq!(to_wire_message(&m).unwrap()["content"], blocks);
    }

    #[test]
    fn fallback_echo_rule() {
        let blocks = vec![
            json!({"type":"thinking","thinking":"","signature":"a"}),
            json!({"type":"text","text":"partial"}),
            json!({"type":"tool_use","id":"t","name":"x","input":{}}),
            json!({"type":"fallback","from":{"model":"a"},"to":{"model":"b"}}),
            json!({"type":"thinking","thinking":"","signature":"b"}),
            json!({"type":"text","text":"rest"}),
        ];
        let out = sanitize_after_fallback(blocks);
        let types: Vec<&str> = out.iter().map(|b| b["type"].as_str().unwrap()).collect();
        assert_eq!(types, ["text", "fallback", "thinking", "text"]);
    }

    #[tokio::test]
    async fn streams_text_reasoning_and_tool_use() {
        let server = MockServer::start().await;
        let body = sse(&[
            ("message_start", json!({"type":"message_start","message":{"model":"claude-opus-5-5","usage":{"input_tokens":42}}})),
            ("content_block_start", json!({"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Plan."}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"SIG"}})),
            ("content_block_stop", json!({"type":"content_block_stop","index":0})),
            ("content_block_start", json!({"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Let me "}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"compute."}})),
            ("content_block_stop", json!({"type":"content_block_stop","index":1})),
            ("ping", json!({"type":"ping"})),
            ("content_block_start", json!({"type":"content_block_start","index":2,"content_block":{"type":"tool_use","id":"toolu_1","name":"calc","input":{}}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"{\"expression\":"}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":" \"2+2\"}"}})),
            ("content_block_stop", json!({"type":"content_block_stop","index":2})),
            ("message_delta", json!({"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":17}})),
            ("message_stop", json!({"type":"message_stop"})),
        ]);
        Mock::given(method("POST"))
            .and(path("/v1/messages"))
            .and(header("x-api-key", "test-key"))
            .and(header("anthropic-version", API_VERSION))
            .and(header("anthropic-beta", FALLBACK_BETA))
            .respond_with(ResponseTemplate::new(200).insert_header("content-type", "text/event-stream").set_body_string(body))
            .mount(&server)
            .await;
        let p = AnthropicProvider::new(reqwest::Client::new(), Some(&server.uri()), "test-key".into(), Duration::from_secs(5));
        let mut events = Vec::new();
        let mut sink = |e: StreamEvent| events.push(e);
        let r = p.stream_chat(req(), &mut sink, CancellationToken::new()).await.unwrap();
        assert_eq!(r.stop, StopReason::ToolUse);
        assert_eq!(r.usage, Usage { input_tokens: Some(42), output_tokens: Some(17) });
        assert_eq!(r.message.text(), "Let me compute.");
        assert_eq!(r.message.tool_calls(), vec![("toolu_1".into(), "calc".into(), json!({"expression":"2+2"}))]);
        let native = r.message.native.unwrap().blocks;
        assert_eq!(native[0]["signature"], "SIG", "thinking signature must be preserved for replay");
        assert!(events.iter().any(|e| matches!(e, StreamEvent::ReasoningDelta { .. })));
        assert!(events.iter().any(|e| matches!(e, StreamEvent::ToolCallStarted { .. })));
    }

    #[tokio::test]
    async fn refusal_and_errors_are_normalised() {
        let server = MockServer::start().await;
        let body = sse(&[
            ("message_start", json!({"type":"message_start","message":{"model":"claude-opus-5-5","usage":{"input_tokens":5}}})),
            ("message_delta", json!({"type":"message_delta","delta":{"stop_reason":"refusal","stop_details":{"type":"refusal","category":"cyber"}},"usage":{"output_tokens":0}})),
            ("message_stop", json!({"type":"message_stop"})),
        ]);
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200).set_body_string(body))
            .up_to_n_times(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(401).set_body_string(r#"{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}"#))
            .mount(&server)
            .await;
        let p = AnthropicProvider::new(reqwest::Client::new(), Some(&server.uri()), "k".into(), Duration::from_secs(5));
        let mut sink = |_e: StreamEvent| {};
        let r = p.stream_chat(req(), &mut sink, CancellationToken::new()).await.unwrap();
        assert_eq!(r.stop, StopReason::Refusal { category: Some("cyber".into()) });
        let e = p.stream_chat(req(), &mut sink, CancellationToken::new()).await.unwrap_err();
        assert_eq!(e.kind, ProviderErrorKind::Auth);
        assert_eq!(e.status, Some(401));
    }

    #[tokio::test]
    async fn invalid_tool_json_is_marked_not_executed_partially() {
        let server = MockServer::start().await;
        let body = sse(&[
            ("message_start", json!({"type":"message_start","message":{"model":"m","usage":{}}})),
            ("content_block_start", json!({"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"t","name":"calc","input":{}}})),
            ("content_block_delta", json!({"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\"expr"}})),
            ("message_delta", json!({"type":"message_delta","delta":{"stop_reason":"max_tokens"},"usage":{"output_tokens":3}})),
            ("message_stop", json!({"type":"message_stop"})),
        ]);
        Mock::given(method("POST")).respond_with(ResponseTemplate::new(200).set_body_string(body)).mount(&server).await;
        let p = AnthropicProvider::new(reqwest::Client::new(), Some(&server.uri()), "k".into(), Duration::from_secs(5));
        let mut sink = |_e: StreamEvent| {};
        let r = p.stream_chat(req(), &mut sink, CancellationToken::new()).await.unwrap();
        assert_eq!(r.stop, StopReason::MaxTokens);
        assert!(r.message.tool_calls()[0].2.get("__invalid_json__").is_some());
    }

    #[tokio::test]
    async fn lists_models_with_capabilities() {
        let server = MockServer::start().await;
        Mock::given(method("GET")).and(path("/v1/models")).respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "data": [{"id":"claude-opus-5-5","display_name":"Claude Opus 5.5","max_input_tokens":1000000,"max_tokens":128000,
                      "capabilities":{"image_input":{"supported":true},"thinking":{"supported":true,"types":{"adaptive":{"supported":true}}},"effort":{"medium":{"supported":true}}}}],
            "has_more": false
        }))).mount(&server).await;
        let p = AnthropicProvider::new(reqwest::Client::new(), Some(&server.uri()), "k".into(), Duration::from_secs(5));
        let models = p.list_models().await.unwrap();
        assert_eq!(models[0].context_window, Some(1_000_000));
        assert_eq!(models[0].supports_reasoning, Some(true));
        assert_eq!(models[0].supports_effort, Some(true));
    }

    #[tokio::test]
    async fn cancellation_stops_the_stream() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200).set_delay(Duration::from_secs(10)).set_body_string(""))
            .mount(&server)
            .await;
        let p = AnthropicProvider::new(reqwest::Client::new(), Some(&server.uri()), "k".into(), Duration::from_secs(30));
        let cancel = CancellationToken::new();
        let c2 = cancel.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(100)).await;
            c2.cancel();
        });
        let mut sink = |_e: StreamEvent| {};
        let started = std::time::Instant::now();
        let e = p.stream_chat(req(), &mut sink, cancel).await.unwrap_err();
        assert_eq!(e.kind, ProviderErrorKind::Cancelled);
        assert!(started.elapsed() < Duration::from_secs(5));
    }
}
