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
    let rest = match raw.split_once("</atlas_context>") {
        Some((_, rest)) => rest.trim().to_string(),
        None => raw,
    };
    // Knowledge Vault passages come before the question: the question is what follows them.
    match rest.rsplit_once("</vault_passage>") {
        Some((_, q)) => q.trim().to_string(),
        None => rest,
    }
}

/// The first Vault passage given with the last question: (label, text).
fn first_passage(req: &ChatRequest) -> Option<(String, String)> {
    let raw = req.messages.iter().rev().find(|m| m.role == Role::User && !m.text().is_empty()).map(|m| m.text())?;
    let start = raw.find("<vault_passage id=\"")?;
    let label: String = raw[start + 19..].chars().take_while(|c| *c != '"').collect();
    let body_start = start + raw[start..].find('>')? + 1;
    let body_end = body_start + raw[body_start..].find("</vault_passage>")?;
    Some((label, raw[body_start..body_end].trim().to_string()))
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
            return stream(reply(t), sink, &cancel).await;
        }
        if let Some(expr) = lower.split("calculate").nth(1) {
            return Ok(call("calc_evaluate", json!({"expression": expr.trim()})));
        }
        // "Remind me to <something> tomorrow …": add it to the owner's task list.
        if let Some(rest) = text.strip_prefix("Remind me to ")
            && let Some(i) = rest.find(" tomorrow")
        {
            return Ok(call("todo_add", json!({"title": &rest[..i], "when": rest[i..].trim(), "remind": true})));
        }
        if lower.contains("create a note") {
            return Ok(call("files_create", json!({"path": "e2e/hello.md", "content": "# Hello from Atlas\n"})));
        }
        if lower.contains("read main.py") {
            return Ok(call("forge_read_file", json!({"path": "main.py"})));
        }
        if lower.contains("fix the bug") {
            return Ok(call("forge_edit_file", json!({"path": "main.py", "old": "return a - b", "new": "return a + b"})));
        }
        if lower.contains("wait") {
            cancel.cancelled().await;
            return Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled"));
        }
        // With passages from the owner's documents, answer from the first one and cite it (the
        // scripted stand-in for a model; it never follows text inside a passage).
        if let Some((label, passage)) = first_passage(&req) {
            let sentence: String = passage.split_inclusive(['.', '!', '?']).next().unwrap_or(&passage).chars().take(160).collect();
            return stream(reply(format!("From your documents: {} [{label}]", sentence.trim())), sink, &cancel).await;
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
    // Voice in the automated-test build: labelled stand-in engines (no real speech), and voice
    // downloads served by the test harness from 127.0.0.1 (see tests/e2e/voice-fixtures.mjs).
    atlas.voice.use_fixtures(true);
    if let Ok(path) = std::env::var("ATLAS_E2E_VOICE_FIXTURES")
        && let Ok(raw) = std::fs::read_to_string(&path)
        && let Ok(list) = serde_json::from_str::<Vec<serde_json::Value>>(&raw)
    {
        for o in list {
            if let (Some(id), Some(url), Some(sha256), Some(bytes)) = (o["id"].as_str(), o["url"].as_str(), o["sha256"].as_str(), o["bytes"].as_u64()) {
                atlas.voice.set_override(id, atlas_core::voice::Override { url: url.into(), sha256: sha256.into(), bytes });
            }
        }
    }
    // A small sample project for Atlas Forge (the native folder dialog cannot be driven by WebDriver).
    if atlas.forge_projects().map(|p| p.is_empty()).unwrap_or(false) {
        let root = std::env::temp_dir().join(format!("atlas-e2e-forge-{}", std::process::id())).join("e2e-sample");
        if std::fs::create_dir_all(&root).is_ok() && std::fs::write(root.join("main.py"), "def add(a, b):\n    return a - b\n").is_ok() {
            let _ = atlas.forge_add_project("e2e-sample", &root, Some("git --version"), None);
        }
    }
    if atlas.providers().map(|p| p.is_empty()).unwrap_or(false)
        && let Ok(p) = atlas.add_provider(ProviderKind::Mock, "E2E scripted provider", "http://127.0.0.1:1", Some("scripted"))
    {
        // Run the real connection test against the scripted provider so it reports "connected".
        let _ = tauri::async_runtime::block_on(atlas.test_provider(&p.id));
    }
}

/// WebDriver on Windows: msedgedriver passes its remote-debugging settings to WebView2 through
/// `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`. Tauri always sets its own browser arguments and data folder,
/// which can take precedence, so the automation build merges msedgedriver's arguments in explicitly and
/// honours its user-data folder. It also records what it received for CI diagnostics.
#[cfg(windows)]
pub fn webview2_automation<'a, R: tauri::Runtime, M: tauri::Manager<R>>(
    mut builder: tauri::WebviewWindowBuilder<'a, R, M>,
) -> tauri::WebviewWindowBuilder<'a, R, M> {
    let mut report = format!("args: {:?}\n", std::env::args().collect::<Vec<_>>());
    for (k, v) in std::env::vars().filter(|(k, _)| k.starts_with("WEBVIEW2")) {
        report.push_str(&format!("{k}={v}\n"));
    }
    if let Ok(extra) = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") {
        // Tauri's own defaults, plus everything msedgedriver asked for.
        let mut args = String::from("--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required");
        for a in extra.split_whitespace() {
            if let Some(dir) = a.strip_prefix("--user-data-dir=") {
                builder = builder.data_directory(std::path::PathBuf::from(dir.trim_matches('"')));
                report.push_str(&format!("data_directory={dir}\n"));
            }
            args.push(' ');
            args.push_str(a);
        }
        report.push_str(&format!("additional_browser_args={args}\n"));
        builder = builder.additional_browser_args(&args);
    }
    if let Ok(dir) = std::env::var("WEBVIEW2_USER_DATA_FOLDER") {
        builder = builder.data_directory(std::path::PathBuf::from(dir));
    }
    let _ = std::fs::write(std::env::temp_dir().join("atlas-e2e-startup.txt"), report);
    builder
}

/// Stand-in for time away across a real restart: when the previous run left `e2e-away-minutes` in
/// the data folder, Atlas starts as if it had been closed that many minutes longer (see
/// `recap::shift_back_for_test`). The file is removed once read, so it applies to one start only.
pub fn before_start(dir: &std::path::Path) {
    let marker = dir.join("e2e-away-minutes");
    let Ok(text) = std::fs::read_to_string(&marker) else { return };
    let _ = std::fs::remove_file(&marker);
    let (Ok(minutes), Ok(db)) = (text.trim().parse::<i64>(), atlas_core::storage::Db::open(&dir.join("atlas.db"))) else { return };
    if let Err(e) = atlas_core::recap::shift_back_for_test(&db, minutes) {
        eprintln!("[atlas e2e] could not stand in for time away: {e}");
    }
}
