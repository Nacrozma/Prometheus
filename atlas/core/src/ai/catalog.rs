//! Static knowledge about provider kinds: defaults, suggested models and published prices.
//! Prices are a snapshot (Anthropic list prices as of 2026-10-06) and every cost shown in the
//! UI is labelled an estimate. Unknown models have unknown cost — never a guessed one.

use super::ProviderKind;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct ProviderTemplate {
    pub kind: ProviderKind,
    pub label: &'static str,
    pub default_base_url: &'static str,
    pub suggested_model: &'static str,
    pub needs_key: bool,
    pub local: bool,
    pub key_help: &'static str,
    pub privacy_note: &'static str,
}

pub fn templates() -> Vec<ProviderTemplate> {
    vec![
        ProviderTemplate {
            kind: ProviderKind::Anthropic,
            label: "Anthropic (Claude)",
            default_base_url: super::anthropic::DEFAULT_BASE_URL,
            suggested_model: "claude-opus-5-5",
            needs_key: true,
            local: false,
            key_help: "Create a key at console.anthropic.com → API Keys.",
            privacy_note: "Messages you send, plus any context Atlas attaches, are processed by Anthropic under your API account's terms.",
        },
        ProviderTemplate {
            kind: ProviderKind::Openai,
            label: "OpenAI",
            default_base_url: super::openai::OPENAI_BASE_URL,
            suggested_model: "",
            needs_key: true,
            local: false,
            key_help: "Create a key at platform.openai.com → API keys.",
            privacy_note: "Messages and attached context are processed by OpenAI under your API account's terms.",
        },
        ProviderTemplate {
            kind: ProviderKind::OpenaiCompatible,
            label: "OpenAI-compatible server",
            default_base_url: "https://openrouter.ai/api/v1",
            suggested_model: "",
            needs_key: true,
            local: false,
            key_help: "Use the API key issued by the service you point Atlas at (OpenRouter, Groq, ...).",
            privacy_note: "Messages and attached context are sent to the server at the base URL you configure.",
        },
        ProviderTemplate {
            kind: ProviderKind::Ollama,
            label: "Ollama (on this computer)",
            default_base_url: super::openai::OLLAMA_BASE_URL,
            suggested_model: "",
            needs_key: false,
            local: true,
            key_help: "Install Ollama from ollama.com, then pull a model (for example `ollama pull qwen3`).",
            privacy_note: "Runs on this computer. Nothing leaves your machine unless your Ollama install is configured to use a remote server.",
        },
    ]
}

/// (input, output) USD per million tokens.
pub fn price_per_mtok(kind: ProviderKind, model: &str) -> Option<(f64, f64)> {
    if kind != ProviderKind::Anthropic {
        return None;
    }
    let table: &[(&str, f64, f64)] = &[
        ("claude-fable-5-1", 10.0, 50.0),
        ("claude-fable-5", 10.0, 50.0),
        ("claude-opus-5-5", 4.0, 20.0),
        ("claude-opus-5", 5.0, 25.0),
        ("claude-opus-4-8", 5.0, 25.0),
        ("claude-opus-4-7", 5.0, 25.0),
        ("claude-opus-4-6", 5.0, 25.0),
        ("claude-sonnet-5-5", 2.0, 10.0),
        ("claude-sonnet-5", 2.0, 10.0),
        ("claude-sonnet-4-6", 3.0, 15.0),
        ("claude-haiku-5-5", 0.10, 0.50),
        ("claude-haiku-4-5", 1.0, 5.0),
    ];
    table.iter().find(|(id, _, _)| *id == model).map(|(_, i, o)| (*i, *o))
}

/// Estimated cost, or None when the price or token counts are unknown. Ignores prompt-cache
/// discounts and long-context tiers, so it is an upper-bound style estimate.
pub fn estimate_cost(kind: ProviderKind, model: &str, input: Option<u64>, output: Option<u64>) -> Option<f64> {
    if kind.is_local() {
        return Some(0.0);
    }
    let (pi, po) = price_per_mtok(kind, model)?;
    Some(input? as f64 * pi / 1e6 + output? as f64 * po / 1e6)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cost_estimates() {
        let c = estimate_cost(ProviderKind::Anthropic, "claude-opus-5-5", Some(1_000_000), Some(100_000)).unwrap();
        assert!((c - 6.0).abs() < 1e-9);
        assert_eq!(estimate_cost(ProviderKind::Openai, "gpt-x", Some(1), Some(1)), None);
        assert_eq!(estimate_cost(ProviderKind::Anthropic, "unknown-model", Some(1), Some(1)), None);
        assert_eq!(estimate_cost(ProviderKind::Ollama, "llama", None, None), Some(0.0));
    }
}
