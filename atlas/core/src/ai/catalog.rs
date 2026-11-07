//! Static knowledge about provider kinds: defaults, suggested models and key hints. Prices live
//! in `crate::pricing`, which records whether each rate is verified.

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
    /// Placeholder for the key field, e.g. "Paste your OpenAI API key".
    pub key_placeholder: &'static str,
    /// Shown when the provider is optional / advanced.
    pub optional: bool,
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
            key_placeholder: "Paste your Anthropic API key",
            optional: false,
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
            key_placeholder: "Paste your OpenAI API key",
            optional: false,
            privacy_note: "Messages and attached context are processed by OpenAI under your API account's terms.",
        },
        ProviderTemplate {
            kind: ProviderKind::Openrouter,
            label: "OpenRouter",
            default_base_url: super::openai::OPENROUTER_BASE_URL,
            suggested_model: "",
            needs_key: true,
            local: false,
            key_help: "Create a key at openrouter.ai → Keys.",
            key_placeholder: "Paste your OpenRouter API key",
            optional: false,
            privacy_note: "Messages and attached context go to OpenRouter, which forwards them to the vendor of the model you pick.",
        },
        ProviderTemplate {
            kind: ProviderKind::Mistral,
            label: "Mistral AI",
            default_base_url: super::openai::MISTRAL_BASE_URL,
            suggested_model: "",
            needs_key: true,
            local: false,
            key_help: "Create a key at console.mistral.ai → API Keys.",
            key_placeholder: "Paste your Mistral API key",
            optional: false,
            privacy_note: "Messages and attached context are processed by Mistral AI under your API account's terms.",
        },
        ProviderTemplate {
            kind: ProviderKind::Cerebras,
            label: "Cerebras",
            default_base_url: super::openai::CEREBRAS_BASE_URL,
            suggested_model: "",
            needs_key: true,
            local: false,
            key_help: "Create a key at cloud.cerebras.ai → API Keys.",
            key_placeholder: "Paste your Cerebras API key",
            optional: false,
            privacy_note: "Messages and attached context are processed by Cerebras under your API account's terms.",
        },
        ProviderTemplate {
            kind: ProviderKind::OpenaiCompatible,
            label: "OpenAI-compatible server",
            default_base_url: "https://openrouter.ai/api/v1",
            suggested_model: "",
            needs_key: true,
            local: false,
            key_help: "Use the API key issued by the service you point Atlas at (OpenRouter, Groq, ...).",
            key_placeholder: "Paste the API key for this server",
            optional: true,
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
            key_placeholder: "No key needed",
            optional: true,
            privacy_note: "Runs on this computer. Nothing leaves your machine unless your Ollama install is configured to use a remote server.",
        },
    ]
}

/// Estimated cost in USD, or None when the price or token counts are unknown. See `pricing`.
pub fn estimate_cost(kind: ProviderKind, model: &str, input: Option<u64>, output: Option<u64>) -> Option<f64> {
    crate::pricing::estimate(kind, model, &[], input, output).map(|c| c.usd)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_template_is_consistent_and_has_a_placeholder() {
        for t in templates() {
            assert!(!t.key_placeholder.is_empty(), "{:?}", t.kind);
            assert_eq!(t.needs_key, t.kind.needs_key(), "{:?}", t.kind);
            assert!(t.kind.openai_wire() || t.kind == ProviderKind::Anthropic, "{:?}", t.kind);
            assert!(t.default_base_url.starts_with("https://") || t.local, "{:?}", t.kind);
        }
        for ph in ["Paste your OpenAI API key", "Paste your Anthropic API key", "Paste your OpenRouter API key", "Paste your Mistral API key", "Paste your Cerebras API key"] {
            assert!(templates().iter().any(|t| t.key_placeholder == ph), "{ph}");
        }
    }

    #[test]
    fn cost_estimates() {
        let c = estimate_cost(ProviderKind::Anthropic, "claude-opus-5-5", Some(1_000_000), Some(100_000)).unwrap();
        assert!((c - 6.0).abs() < 1e-9);
        assert_eq!(estimate_cost(ProviderKind::Openai, "gpt-x", Some(1), Some(1)), None);
        assert_eq!(estimate_cost(ProviderKind::Ollama, "llama", None, None), Some(0.0));
    }
}
