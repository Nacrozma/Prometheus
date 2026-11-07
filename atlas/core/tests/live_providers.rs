//! Opt-in live check of each provider adapter against the real API, using keys from YOUR
//! environment (see atlas/.env.example). Never run in CI; never commit keys.
//!
//!   OPENAI_API_KEY=... ANTHROPIC_API_KEY=... cargo test -p atlas-core --test live_providers -- --ignored --nocapture
//!
//! Optional model overrides: ATLAS_LIVE_<PROVIDER>_MODEL (e.g. ATLAS_LIVE_OPENAI_MODEL=gpt-4.1-nano).
//! Each provider without a key is skipped and reported as skipped, not as passed.

use atlas_core::ai::anthropic::AnthropicProvider;
use atlas_core::ai::openai::{self, OpenAiProvider};
use atlas_core::ai::{ChatMessage, ChatProvider, ChatRequest, ProviderKind};
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

fn env(k: &str) -> Option<String> {
    std::env::var(k).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

#[tokio::test]
#[ignore = "calls paid provider APIs with your own keys"]
async fn live_provider_round_trips() {
    let http = reqwest::Client::new();
    let t = Duration::from_secs(60);
    let mut cases: Vec<(&str, Option<Arc<dyn ChatProvider>>, Option<String>)> = vec![];
    let key = |k: &str| env(k);
    cases.push(("Anthropic", key("ANTHROPIC_API_KEY").map(|k| Arc::new(AnthropicProvider::new(http.clone(), None, k, t)) as _), env("ATLAS_LIVE_ANTHROPIC_MODEL").or(Some("claude-haiku-5-5".into()))));
    for (name, kind, var, base) in [
        ("OpenAI", ProviderKind::Openai, "OPENAI_API_KEY", openai::OPENAI_BASE_URL),
        ("OpenRouter", ProviderKind::Openrouter, "OPENROUTER_API_KEY", openai::OPENROUTER_BASE_URL),
        ("Mistral", ProviderKind::Mistral, "MISTRAL_API_KEY", openai::MISTRAL_BASE_URL),
        ("Cerebras", ProviderKind::Cerebras, "CEREBRAS_API_KEY", openai::CEREBRAS_BASE_URL),
    ] {
        let model = env(&format!("ATLAS_LIVE_{}_MODEL", name.to_uppercase()));
        cases.push((name, key(var).map(|k| Arc::new(OpenAiProvider::new(http.clone(), kind, base, Some(k), t)) as _), model));
    }
    let ollama = env("OLLAMA_BASE_URL").map(|u| format!("{}/v1", u.trim_end_matches('/').trim_end_matches("/v1")));
    cases.push(("Ollama", ollama.map(|u| Arc::new(OpenAiProvider::new(http.clone(), ProviderKind::Ollama, &u, None, t)) as _), env("ATLAS_LIVE_OLLAMA_MODEL")));

    let mut failures = vec![];
    for (name, provider, model) in cases {
        let Some(p) = provider else {
            println!("SKIPPED {name}: no key/endpoint in the environment");
            continue;
        };
        let models = match p.list_models().await {
            Ok(m) => m,
            Err(e) => {
                failures.push(format!("{name}: list_models: {e:?}"));
                continue;
            }
        };
        let model = model.or_else(|| models.first().map(|m| m.id.clone()));
        let Some(model) = model else {
            failures.push(format!("{name}: no model available"));
            continue;
        };
        let req = ChatRequest {
            model: model.clone(),
            system: "Reply with exactly: OK".into(),
            messages: vec![ChatMessage::user_text("Say OK")],
            tools: vec![],
            max_tokens: 20,
            effort: None,
            reasoning_summary: false,
            refusal_fallback: false,
        };
        let mut sink = |_e| {};
        match p.stream_chat(req, &mut sink, CancellationToken::new()).await {
            Ok(r) => println!("PASSED  {name} ({model}): {:?} · usage {:?}", r.message.text(), r.usage),
            Err(e) => failures.push(format!("{name} ({model}): {e:?}")),
        }
    }
    assert!(failures.is_empty(), "live failures:\n{}", failures.join("\n"));
}
