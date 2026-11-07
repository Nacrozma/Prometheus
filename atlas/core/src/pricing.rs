//! Model price schedule used for cost *estimates*.
//!
//! Three sources are kept apart and every quote says which one it came from:
//! - `Verified`: a vendor's published list price, checked against the vendor's own pricing
//!   reference on the date in `as_of`.
//! - `Unverified`: seed rates supplied with the product brief. They have not been checked against
//!   the vendor's pricing page, so the UI labels any cost built on them "unverified".
//! - `User`: a rate the owner entered in Settings → Usage & budgets. It wins over both, because
//!   the owner may know about a price change or a negotiated rate.
//!
//! Unknown models have unknown cost, never a guessed one.

use crate::ai::ProviderKind;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Verification {
    Verified,
    Unverified,
    User,
}

impl Verification {
    pub fn as_str(self) -> &'static str {
        match self {
            Verification::Verified => "verified",
            Verification::Unverified => "unverified",
            Verification::User => "user",
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PriceEntry {
    /// Vendor whose models this row prices ("anthropic", "openai").
    pub vendor: String,
    pub model: String,
    /// USD per million input tokens.
    pub input_per_mtok: f64,
    /// USD per million output tokens.
    pub output_per_mtok: f64,
    pub verification: Verification,
    pub source: String,
    pub as_of: Option<String>,
}

/// A user-entered rate (Settings → Usage & budgets → Price overrides).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PriceOverride {
    pub model: String,
    pub input_per_mtok: f64,
    pub output_per_mtok: f64,
}

const ANTHROPIC_SOURCE: &str = "Anthropic published list price";
const ANTHROPIC_AS_OF: &str = "2026-10-06";

/// Anthropic list prices (USD / MTok), checked against Anthropic's pricing reference.
const VERIFIED: &[(&str, &str, f64, f64)] = &[
    ("anthropic", "claude-fable-5-1", 10.0, 50.0),
    ("anthropic", "claude-fable-5", 10.0, 50.0),
    ("anthropic", "claude-opus-5-5", 4.0, 20.0),
    ("anthropic", "claude-opus-5", 5.0, 25.0),
    ("anthropic", "claude-opus-4-8", 5.0, 25.0),
    ("anthropic", "claude-opus-4-7", 5.0, 25.0),
    ("anthropic", "claude-opus-4-6", 5.0, 25.0),
    ("anthropic", "claude-sonnet-5-5", 2.0, 10.0),
    ("anthropic", "claude-sonnet-5", 2.0, 10.0),
    ("anthropic", "claude-sonnet-4-6", 3.0, 15.0),
    ("anthropic", "claude-haiku-5-5", 0.10, 0.50),
    ("anthropic", "claude-haiku-4-5", 1.0, 5.0),
];

const SEED_SOURCE: &str = "Seed rate from the Atlas evolution brief; not yet checked against the vendor's pricing page";

/// Seed rates as supplied (USD / MTok). Kept separate from `VERIFIED` on purpose.
const SEED: &[(&str, &str, f64, f64)] = &[
    ("anthropic", "claude-haiku-5-5", 0.10, 0.50),
    ("openai", "gpt-4.1-nano", 0.10, 0.40),
    ("openai", "gpt-5-nano", 0.05, 0.40),
    ("anthropic", "claude-sonnet-5-5", 2.00, 10.00),
    ("openai", "gpt-5.4", 2.50, 15.00),
    ("openai", "gpt-4.1", 2.00, 8.00),
    ("anthropic", "claude-opus-5-5", 4.00, 20.00),
    ("openai", "gpt-5.5", 5.00, 30.00),
];

/// The full schedule as shown in Settings: verified rows, then seed rows not covered by a
/// verified row (a seed row that duplicates a verified one adds nothing).
pub fn schedule() -> Vec<PriceEntry> {
    let mut out: Vec<PriceEntry> = VERIFIED
        .iter()
        .map(|(v, m, i, o)| PriceEntry {
            vendor: (*v).into(),
            model: (*m).into(),
            input_per_mtok: *i,
            output_per_mtok: *o,
            verification: Verification::Verified,
            source: ANTHROPIC_SOURCE.into(),
            as_of: Some(ANTHROPIC_AS_OF.into()),
        })
        .collect();
    for (v, m, i, o) in SEED {
        if VERIFIED.iter().any(|(vv, mm, _, _)| vv == v && mm == m) {
            continue;
        }
        out.push(PriceEntry {
            vendor: (*v).into(),
            model: (*m).into(),
            input_per_mtok: *i,
            output_per_mtok: *o,
            verification: Verification::Unverified,
            source: SEED_SOURCE.into(),
            as_of: None,
        });
    }
    out
}

/// Seed rows whose rate disagrees with the verified row for the same model. Shown in
/// diagnostics so a stale seed is visible instead of silently ignored.
pub fn seed_conflicts() -> Vec<String> {
    SEED.iter()
        .filter_map(|(v, m, i, o)| {
            VERIFIED
                .iter()
                .find(|(vv, mm, _, _)| vv == v && mm == m)
                .filter(|(_, _, vi, vo)| (vi - i).abs() > 1e-9 || (vo - o).abs() > 1e-9)
                .map(|(_, _, vi, vo)| format!("{m}: seed {i}/{o} vs verified {vi}/{vo}"))
        })
        .collect()
}

/// Lower-case, drop an OpenRouter-style vendor prefix and a trailing `-YYYY-MM-DD` snapshot date.
pub fn normalize_model(model: &str) -> (Option<String>, String) {
    let m = model.trim().to_ascii_lowercase();
    let (vendor, rest) = match m.split_once('/') {
        Some((v, r)) => (Some(v.to_string()), r.to_string()),
        None => (None, m),
    };
    let b = rest.as_bytes();
    let dated = b.len() > 11 && {
        let tail = &rest[rest.len() - 11..];
        tail.starts_with('-') && tail[1..].chars().enumerate().all(|(i, c)| if i == 4 || i == 7 { c == '-' } else { c.is_ascii_digit() })
    };
    let base = if dated { rest[..rest.len() - 11].to_string() } else { rest };
    (vendor, base)
}

/// Which vendor price rows apply to a provider kind (and an optional model vendor prefix).
fn vendors_for(kind: ProviderKind, prefix: Option<&str>) -> Vec<&'static str> {
    match kind {
        ProviderKind::Anthropic => vec!["anthropic"],
        ProviderKind::Openai => vec!["openai"],
        // Routers pass vendor list prices through; only price models whose vendor is named.
        ProviderKind::Openrouter | ProviderKind::OpenaiCompatible => match prefix {
            Some("anthropic") => vec!["anthropic"],
            Some("openai") => vec!["openai"],
            _ => vec![],
        },
        _ => vec![],
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Quote {
    pub input_per_mtok: f64,
    pub output_per_mtok: f64,
    pub verification: Verification,
}

pub fn quote(kind: ProviderKind, model: &str, overrides: &[PriceOverride]) -> Option<Quote> {
    if kind.is_local() {
        return Some(Quote { input_per_mtok: 0.0, output_per_mtok: 0.0, verification: Verification::Verified });
    }
    let (prefix, base) = normalize_model(model);
    if let Some(o) = overrides.iter().find(|o| normalize_model(&o.model).1 == base) {
        return Some(Quote { input_per_mtok: o.input_per_mtok, output_per_mtok: o.output_per_mtok, verification: Verification::User });
    }
    // OpenRouter spells Anthropic versions with dots ("claude-sonnet-5.5").
    let alt = base.replace('.', "-");
    let vendors = vendors_for(kind, prefix.as_deref());
    let find = |rows: &[(&str, &str, f64, f64)], v: Verification| {
        rows.iter()
            .find(|(vv, mm, _, _)| vendors.contains(vv) && (*mm == base || (*vv == "anthropic" && *mm == alt)))
            .map(|(_, _, i, o)| Quote { input_per_mtok: *i, output_per_mtok: *o, verification: v })
    };
    find(VERIFIED, Verification::Verified).or_else(|| find(SEED, Verification::Unverified))
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq)]
pub struct CostEstimate {
    pub usd: f64,
    pub verification: Verification,
}

/// Estimated cost, or None when the price or token counts are unknown. Ignores prompt-cache
/// discounts and long-context tiers.
pub fn estimate(kind: ProviderKind, model: &str, overrides: &[PriceOverride], input: Option<u64>, output: Option<u64>) -> Option<CostEstimate> {
    if kind.is_local() {
        return Some(CostEstimate { usd: 0.0, verification: Verification::Verified });
    }
    let q = quote(kind, model, overrides)?;
    Some(CostEstimate { usd: input? as f64 * q.input_per_mtok / 1e6 + output? as f64 * q.output_per_mtok / 1e6, verification: q.verification })
}

pub fn validate_overrides(o: &[PriceOverride]) -> Result<(), String> {
    if o.len() > 200 {
        return Err("too many price overrides".into());
    }
    for p in o {
        if p.model.trim().is_empty() || p.model.len() > 200 {
            return Err("each price override needs a model id".into());
        }
        for v in [p.input_per_mtok, p.output_per_mtok] {
            if !v.is_finite() || !(0.0..=10_000.0).contains(&v) {
                return Err(format!("price for {} must be between 0 and 10000 USD per million tokens", p.model));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seed_rates_are_present_and_labelled_unverified() {
        let s = schedule();
        let row = |m: &str| s.iter().find(|r| r.model == m).unwrap().clone();
        assert_eq!(row("gpt-5-nano").verification, Verification::Unverified);
        assert_eq!((row("gpt-5-nano").input_per_mtok, row("gpt-5-nano").output_per_mtok), (0.05, 0.40));
        assert_eq!((row("gpt-4.1-nano").input_per_mtok, row("gpt-4.1-nano").output_per_mtok), (0.10, 0.40));
        assert_eq!((row("gpt-5.4").input_per_mtok, row("gpt-5.4").output_per_mtok), (2.50, 15.00));
        assert_eq!((row("gpt-4.1").input_per_mtok, row("gpt-4.1").output_per_mtok), (2.00, 8.00));
        assert_eq!((row("gpt-5.5").input_per_mtok, row("gpt-5.5").output_per_mtok), (5.00, 30.00));
        // Anthropic seed rows match the verified list exactly, so they appear once, as verified.
        assert_eq!(row("claude-haiku-5-5").verification, Verification::Verified);
        assert_eq!(s.iter().filter(|r| r.model == "claude-opus-5-5").count(), 1);
        assert!(seed_conflicts().is_empty(), "{:?}", seed_conflicts());
    }

    #[test]
    fn quotes_follow_precedence_and_vendor_rules() {
        let q = quote(ProviderKind::Openai, "gpt-4.1-2025-04-14", &[]).unwrap();
        assert_eq!((q.input_per_mtok, q.verification), (2.0, Verification::Unverified));
        let q = quote(ProviderKind::Anthropic, "claude-opus-5-5", &[]).unwrap();
        assert_eq!((q.output_per_mtok, q.verification), (20.0, Verification::Verified));
        // OpenRouter: vendor prefix required; dotted Anthropic versions accepted.
        assert_eq!(quote(ProviderKind::Openrouter, "anthropic/claude-sonnet-5.5", &[]).unwrap().input_per_mtok, 2.0);
        assert!(quote(ProviderKind::Openrouter, "gpt-4.1", &[]).is_none());
        assert!(quote(ProviderKind::Mistral, "mistral-large-latest", &[]).is_none());
        // The OpenAI table never prices an Anthropic model and vice versa.
        assert!(quote(ProviderKind::Openai, "claude-opus-5-5", &[]).is_none());
        // Owner overrides win and are labelled.
        let o = vec![PriceOverride { model: "mistral-large-latest".into(), input_per_mtok: 1.5, output_per_mtok: 4.5 }];
        let q = quote(ProviderKind::Mistral, "mistral-large-latest", &o).unwrap();
        assert_eq!((q.output_per_mtok, q.verification), (4.5, Verification::User));
        assert_eq!(quote(ProviderKind::Ollama, "qwen3", &[]).unwrap().input_per_mtok, 0.0);
    }

    #[test]
    fn estimates() {
        let c = estimate(ProviderKind::Anthropic, "claude-opus-5-5", &[], Some(1_000_000), Some(100_000)).unwrap();
        assert!((c.usd - 6.0).abs() < 1e-9);
        let c = estimate(ProviderKind::Openai, "gpt-5-nano", &[], Some(2_000_000), Some(1_000_000)).unwrap();
        assert!((c.usd - 0.5).abs() < 1e-9 && c.verification == Verification::Unverified);
        assert_eq!(estimate(ProviderKind::Openai, "gpt-x", &[], Some(1), Some(1)), None);
        assert_eq!(estimate(ProviderKind::Anthropic, "claude-opus-5-5", &[], None, Some(1)), None);
        assert!(validate_overrides(&[PriceOverride { model: "m".into(), input_per_mtok: -1.0, output_per_mtok: 1.0 }]).is_err());
    }
}
