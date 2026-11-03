//! OpenAI Chat Completions adapter. Also used for OpenAI-compatible servers (OpenRouter, Groq,
//! LM Studio...) and for Ollama's local `/v1` endpoint.

use super::sse::{for_each_event, SseEvent};
use super::*;
use serde_json::json;
use std::collections::BTreeMap;
use std::time::Duration;

pub const OPENAI_BASE_URL: &str = "https://api.openai.com/v1";
pub const OLLAMA_BASE_URL: &str = "http://127.0.0.1:11434/v1";

pub struct OpenAiProvider {
    http: reqwest::Client,
    kind: ProviderKind,
    base_url: String,
    api_key: Option<String>,
    idle_timeout: Duration,
}

impl OpenAiProvider {
    pub fn new(
        http: reqwest::Client,
        kind: ProviderKind,
        base_url: &str,
        api_key: Option<String>,
        idle_timeout: Duration,
    ) -> Self {
        Self { http, kind, base_url: base_url.trim_end_matches('/').to_string(), api_key, idle_timeout }
    }

    fn auth(&self, rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        match &self.api_key {
            Some(k) => rb.bearer_auth(k),
            None => rb,
        }
    }

    pub fn build_body(kind: ProviderKind, req: &ChatRequest) -> Value {
        let mut messages = Vec::new();
        if !req.system.is_empty() {
            messages.push(json!({"role": "system", "content": req.system}));
        }
        for m in &req.messages {
            match m.role {
                Role::User => {
                    let text = m.text();
                    for p in &m.parts {
                        if let Part::ToolResult { call_id, content, is_error } = p {
                            let content = if *is_error { format!("ERROR: {content}") } else { content.clone() };
                            messages.push(json!({"role": "tool", "tool_call_id": call_id, "content": content}));
                        }
                    }
                    if !text.is_empty() {
                        messages.push(json!({"role": "user", "content": text}));
                    }
                }
                Role::Assistant => {
                    let text = m.text();
                    let calls: Vec<Value> = m
                        .tool_calls()
                        .into_iter()
                        .map(|(id, name, input)| {
                            json!({"id": id, "type": "function", "function": {"name": name, "arguments": input.to_string()}})
                        })
                        .collect();
                    if text.is_empty() && calls.is_empty() {
                        continue;
                    }
                    let mut msg = json!({"role": "assistant", "content": if text.is_empty() { Value::Null } else { json!(text) }});
                    if !calls.is_empty() {
                        msg["tool_calls"] = Value::Array(calls);
                    }
                    messages.push(msg);
                }
            }
        }
        let mut body = json!({
            "model": req.model,
            "messages": messages,
            "stream": true,
            "stream_options": {"include_usage": true},
        });
        // OpenAI's own API uses max_completion_tokens; compatible servers widely accept max_tokens.
        if kind == ProviderKind::Openai {
            body["max_completion_tokens"] = json!(req.max_tokens);
        } else {
            body["max_tokens"] = json!(req.max_tokens);
        }
        if !req.tools.is_empty() {
            body["tools"] = Value::Array(
                req.tools
                    .iter()
                    .map(|t| json!({"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}))
                    .collect(),
            );
        }
        body
    }
}

#[derive(Default)]
struct CallAcc {
    id: String,
    name: String,
    args: String,
}

#[async_trait]
impl ChatProvider for OpenAiProvider {
    fn kind(&self) -> ProviderKind {
        self.kind
    }

    async fn list_models(&self) -> Result<Vec<ModelInfo>, ProviderError> {
        let resp = self
            .auth(self.http.get(format!("{}/models", self.base_url)))
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
        let mut models: Vec<ModelInfo> = v["data"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .filter_map(|m| {
                let id = m["id"].as_str()?.to_string();
                Some(ModelInfo {
                    display_name: m["name"].as_str().unwrap_or(&id).to_string(),
                    context_window: m["context_length"].as_u64(),
                    max_output_tokens: None,
                    supports_tools: None,
                    supports_vision: None,
                    supports_reasoning: None,
                    supports_effort: Some(false),
                    id,
                })
            })
            .collect();
        models.sort_by(|a, b| a.id.cmp(&b.id));
        Ok(models)
    }

    async fn stream_chat(
        &self,
        req: ChatRequest,
        sink: EventSink<'_>,
        cancel: CancellationToken,
    ) -> Result<ChatResponse, ProviderError> {
        let body = Self::build_body(self.kind, &req);
        let rb = self.auth(self.http.post(format!("{}/chat/completions", self.base_url))).json(&body);
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

        let mut text = String::new();
        let mut calls: BTreeMap<u64, CallAcc> = BTreeMap::new();
        let mut finish: Option<String> = None;
        let mut usage = Usage::default();
        let mut served_model = req.model.clone();

        for_each_event(resp, &cancel, self.idle_timeout, |ev: SseEvent| {
            let data = ev.data.trim();
            if data.is_empty() {
                return Ok(true);
            }
            if data == "[DONE]" {
                return Ok(false);
            }
            let v: Value = serde_json::from_str(data)
                .map_err(|e| ProviderError::new(ProviderErrorKind::Decode, format!("stream chunk: {e}")))?;
            if let Some(err) = v.get("error") {
                let msg = err["message"].as_str().unwrap_or("stream error");
                return Err(ProviderError::new(ProviderErrorKind::Server, msg));
            }
            if let Some(m) = v["model"].as_str() {
                served_model = m.to_string();
            }
            if let Some(u) = v.get("usage").filter(|u| !u.is_null()) {
                usage.input_tokens = u["prompt_tokens"].as_u64();
                usage.output_tokens = u["completion_tokens"].as_u64();
            }
            if let Some(choice) = v["choices"].get(0) {
                let d = &choice["delta"];
                if let Some(s) = d["content"].as_str()
                    && !s.is_empty() {
                        text.push_str(s);
                        sink(StreamEvent::TextDelta { text: s.to_string() });
                    }
                for key in ["reasoning_content", "reasoning"] {
                    if let Some(s) = d[key].as_str()
                        && !s.is_empty() {
                            sink(StreamEvent::ReasoningDelta { text: s.to_string() });
                        }
                }
                if let Some(tcs) = d["tool_calls"].as_array() {
                    for tc in tcs {
                        let idx = tc["index"].as_u64().unwrap_or(0);
                        let acc = calls.entry(idx).or_default();
                        if let Some(id) = tc["id"].as_str() {
                            acc.id = id.to_string();
                        }
                        if let Some(n) = tc.pointer("/function/name").and_then(Value::as_str)
                            && acc.name.is_empty() {
                                acc.name = n.to_string();
                                sink(StreamEvent::ToolCallStarted { id: acc.id.clone(), name: acc.name.clone() });
                            }
                        if let Some(a) = tc.pointer("/function/arguments").and_then(Value::as_str) {
                            acc.args.push_str(a);
                        }
                    }
                }
                if let Some(f) = choice["finish_reason"].as_str() {
                    finish = Some(f.to_string());
                }
            }
            Ok(true)
        })
        .await?;

        let mut parts = Vec::new();
        if !text.is_empty() {
            parts.push(Part::Text { text });
        }
        for (i, c) in calls {
            let input = if c.args.trim().is_empty() {
                json!({})
            } else {
                serde_json::from_str(&c.args).unwrap_or_else(|_| json!({"__invalid_json__": truncate(&c.args, 2000)}))
            };
            let id = if c.id.is_empty() { format!("call_{i}") } else { c.id };
            parts.push(Part::ToolCall { id, name: c.name, input });
        }
        let has_calls = parts.iter().any(|p| matches!(p, Part::ToolCall { .. }));
        let stop = match finish.as_deref() {
            Some("tool_calls") | Some("function_call") => StopReason::ToolUse,
            Some("length") => StopReason::MaxTokens,
            Some("content_filter") => StopReason::Refusal { category: Some("content_filter".into()) },
            Some("stop") | None if has_calls => StopReason::ToolUse,
            Some("stop") => StopReason::EndTurn,
            None => return Err(ProviderError::new(ProviderErrorKind::Decode, "stream ended without a finish reason")),
            Some(other) => StopReason::Other { reason: other.to_string() },
        };
        Ok(ChatResponse {
            message: ChatMessage { role: Role::Assistant, parts, native: None },
            stop,
            usage,
            served_model,
            notices: vec![],
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn req() -> ChatRequest {
        ChatRequest {
            model: "gpt-x".into(),
            system: "sys".into(),
            messages: vec![
                ChatMessage::user_text("hi"),
                ChatMessage {
                    role: Role::Assistant,
                    parts: vec![Part::ToolCall { id: "c1".into(), name: "calc".into(), input: json!({"expression":"1+1"}) }],
                    native: None,
                },
                ChatMessage {
                    role: Role::User,
                    parts: vec![Part::ToolResult { call_id: "c1".into(), content: "2".into(), is_error: false }],
                    native: None,
                },
            ],
            tools: vec![ToolSpec { name: "calc".into(), description: "d".into(), input_schema: json!({"type":"object"}) }],
            max_tokens: 500,
            effort: None,
            reasoning_summary: false,
            refusal_fallback: false,
        }
    }

    #[test]
    fn body_maps_tool_turns() {
        let b = OpenAiProvider::build_body(ProviderKind::OpenaiCompatible, &req());
        let msgs = b["messages"].as_array().unwrap();
        assert_eq!(msgs[0]["role"], "system");
        assert_eq!(msgs[2]["tool_calls"][0]["function"]["arguments"], "{\"expression\":\"1+1\"}");
        assert_eq!(msgs[3]["role"], "tool");
        assert_eq!(b["max_tokens"], 500);
        let b2 = OpenAiProvider::build_body(ProviderKind::Openai, &req());
        assert_eq!(b2["max_completion_tokens"], 500);
    }

    #[tokio::test]
    async fn streams_text_and_split_tool_calls() {
        let server = MockServer::start().await;
        let chunks = [
            json!({"model":"gpt-x","choices":[{"delta":{"content":"Hel"}}]}),
            json!({"choices":[{"delta":{"content":"lo"}}]}),
            json!({"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function","function":{"name":"calc","arguments":"{\"expr"}}]}}]}),
            json!({"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ession\":\"3*3\"}"}}]},"finish_reason":"tool_calls"}]}),
            json!({"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7}}),
        ];
        let mut body: String = chunks.iter().map(|c| format!("data: {c}\n\n")).collect();
        body.push_str("data: [DONE]\n\n");
        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .and(header("authorization", "Bearer k"))
            .respond_with(ResponseTemplate::new(200).set_body_string(body))
            .mount(&server)
            .await;
        let p = OpenAiProvider::new(
            reqwest::Client::new(),
            ProviderKind::OpenaiCompatible,
            &format!("{}/v1", server.uri()),
            Some("k".into()),
            Duration::from_secs(5),
        );
        let mut deltas = String::new();
        let mut sink = |e: StreamEvent| {
            if let StreamEvent::TextDelta { text } = e {
                deltas.push_str(&text)
            }
        };
        let r = p.stream_chat(req(), &mut sink, CancellationToken::new()).await.unwrap();
        assert_eq!(deltas, "Hello");
        assert_eq!(r.stop, StopReason::ToolUse);
        assert_eq!(r.message.tool_calls()[0].2, json!({"expression":"3*3"}));
        assert_eq!(r.usage.input_tokens, Some(11));
    }

    #[tokio::test]
    async fn ollama_without_key_lists_models() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v1/models"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"data":[{"id":"llama3.2"},{"id":"qwen3"}]})))
            .mount(&server)
            .await;
        let p = OpenAiProvider::new(reqwest::Client::new(), ProviderKind::Ollama, &format!("{}/v1", server.uri()), None, Duration::from_secs(5));
        let m = p.list_models().await.unwrap();
        assert_eq!(m.len(), 2);
        assert_eq!(m[0].supports_tools, None, "capabilities unknown must stay unknown");
    }

    #[tokio::test]
    async fn unreachable_server_is_unavailable() {
        let p = OpenAiProvider::new(reqwest::Client::new(), ProviderKind::Ollama, "http://127.0.0.1:9/v1", None, Duration::from_secs(5));
        let e = p.list_models().await.unwrap_err();
        assert!(matches!(e.kind, ProviderErrorKind::Unavailable | ProviderErrorKind::Network), "{e:?}");
    }
}
