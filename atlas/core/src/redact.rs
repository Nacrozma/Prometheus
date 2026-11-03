//! Secret detection and redaction. Used on every string that leaves the trusted core through
//! logs, diagnostics, error messages and exports, and to refuse saving secrets as memories.

use regex::Regex;
use std::sync::LazyLock;

static PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    [
        // Provider-style API keys (Anthropic, OpenAI, OpenRouter, Groq, Tavily, generic sk-).
        r"\b(sk-ant-[A-Za-z0-9_\-]{8,}|sk-or-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{16,}|gsk_[A-Za-z0-9]{16,}|tvly-[A-Za-z0-9_\-]{8,})",
        // AWS access key ids.
        r"\bAKIA[0-9A-Z]{16}\b",
        // GitHub tokens.
        r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b",
        // Bearer tokens in headers.
        r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}",
        // key=value style secrets.
        r#"(?i)\b(api[_-]?key|secret|password|passwd|token|x-api-key)\b\s*[:=]\s*["']?[^\s"',;]{6,}"#,
        // PEM private keys.
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ]
    .iter()
    .map(|p| Regex::new(p).expect("valid redaction regex"))
    .collect()
});

/// Replace anything that looks like a credential with `[REDACTED]`.
pub fn redact(input: &str) -> String {
    let mut out = input.to_string();
    for re in PATTERNS.iter() {
        out = re.replace_all(&out, "[REDACTED]").into_owned();
    }
    out
}

/// True when the text appears to contain a credential.
pub fn contains_secret(input: &str) -> bool {
    PATTERNS.iter().any(|re| re.is_match(input))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_common_keys() {
        let s = "key sk-ant-api03-abcdefghijklmnop and Bearer abcdefghijklmnopqrstuv and password=hunter22x";
        let r = redact(s);
        assert!(!r.contains("abcdefghijklmnop"), "{r}");
        assert!(!r.contains("hunter22x"), "{r}");
        assert!(r.contains("[REDACTED]"));
    }

    #[test]
    fn leaves_ordinary_text() {
        let s = "The sky is blue and my task list has 3 items.";
        assert_eq!(redact(s), s);
        assert!(!contains_secret(s));
    }

    #[test]
    fn detects_secrets() {
        assert!(contains_secret("my token: ghp_abcdefghijklmnopqrstuvwxyz0123"));
        assert!(contains_secret("AKIAABCDEFGHIJKLMNOP"));
    }
}
