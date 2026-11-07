//! Typed, validated application settings. Stored as one JSON document so a partial or older
//! document is filled with defaults (`#[serde(default)]`) instead of failing.

use crate::error::{AtlasError, Result};
use crate::storage::{now, Db};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
#[derive(Default)]
pub struct Settings {
    pub onboarding_completed: bool,
    pub companion: CompanionSettings,
    pub default_provider_id: Option<String>,
    pub default_model: Option<String>,
    pub routing: RoutingSettings,
    pub permissions: PermissionSettings,
    pub memory: MemorySettings,
    pub workspace_dir: Option<String>,
    pub appearance: AppearanceSettings,
    pub limits: Limits,
    pub network: NetworkSettings,
    pub retention: RetentionSettings,
    pub usage: UsageSettings,
    pub voice: VoiceSettings,
    pub default_project_id: Option<String>,
    pub forge: ForgeSettings,
}


#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Tone {
    Warm,
    Balanced,
    Precise,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Verbosity {
    Concise,
    Balanced,
    Detailed,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Proactivity {
    Reserved,
    Balanced,
    Proactive,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Effort {
    Low,
    Medium,
    High,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct CompanionSettings {
    /// How Atlas addresses the user. Empty means "don't use a name".
    pub preferred_name: String,
    pub tone: Tone,
    pub verbosity: Verbosity,
    pub proactivity: Proactivity,
    /// Reasoning effort hint for providers that support it.
    pub effort: Effort,
    /// Show the provider's reasoning summary (where available) in a collapsed panel.
    pub show_reasoning_summary: bool,
}

impl Default for CompanionSettings {
    fn default() -> Self {
        Self {
            preferred_name: String::new(),
            tone: Tone::Balanced,
            verbosity: Verbosity::Balanced,
            proactivity: Proactivity::Balanced,
            effort: Effort::Medium,
            show_reasoning_summary: true,
        }
    }
}

/// How Atlas picks a model tier for each request.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RoutingMode {
    /// Pick Fast / Standard / Heavy from the request (length, engineering work, discipline).
    Auto,
    /// Always the Fast tier.
    Budget,
    /// Always the Standard tier.
    Balanced,
    /// Always the Heavy tier.
    Quality,
    /// Always your default provider and model (tiers ignored).
    Manual,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum Tier {
    Fast,
    Standard,
    Heavy,
}

impl Tier {
    pub fn label(self) -> &'static str {
        match self {
            Tier::Fast => "Fast",
            Tier::Standard => "Standard",
            Tier::Heavy => "Heavy",
        }
    }
}

/// A configured model for one tier: a provider the owner set up plus a model id.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TierModel {
    pub provider_id: String,
    pub model: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct RoutingSettings {
    /// Allow a different configured provider when the preferred one is unavailable.
    /// Off by default: switching providers changes who receives your data.
    pub allow_cross_provider_fallback: bool,
    /// Anthropic only: let the API re-run a declined request on Anthropic's recommended
    /// fallback model (same provider, different model).
    pub anthropic_refusal_fallback: bool,
    pub mode: RoutingMode,
    pub fast: Option<TierModel>,
    pub standard: Option<TierModel>,
    pub heavy: Option<TierModel>,
}

impl RoutingSettings {
    pub fn tier_model(&self, t: Tier) -> Option<&TierModel> {
        match t {
            Tier::Fast => self.fast.as_ref(),
            Tier::Standard => self.standard.as_ref(),
            Tier::Heavy => self.heavy.as_ref(),
        }
    }
}

impl Default for RoutingSettings {
    fn default() -> Self {
        Self {
            allow_cross_provider_fallback: false,
            anthropic_refusal_fallback: true,
            mode: RoutingMode::Manual,
            fast: None,
            standard: None,
            heavy: None,
        }
    }
}

/// Policy for gated permission classes. `Consequential` actions always ask and
/// `Destructive` actions are always denied — neither is configurable here by design.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum GatePolicy {
    Ask,
    Allow,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct PermissionSettings {
    pub local_write: GatePolicy,
    /// Tools that send data to an external service (e.g. web search).
    pub network_tools: GatePolicy,
}

impl Default for PermissionSettings {
    fn default() -> Self {
        Self { local_write: GatePolicy::Ask, network_tools: GatePolicy::Ask }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct MemorySettings {
    pub enabled: bool,
    /// Maximum memories added to a single request.
    pub max_retrieved: u32,
}

impl Default for MemorySettings {
    fn default() -> Self {
        Self { enabled: true, max_retrieved: 6 }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Theme {
    Dark,
    Light,
    System,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MotionPref {
    System,
    Reduced,
    Full,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct AppearanceSettings {
    pub theme: Theme,
    pub motion: MotionPref,
    /// Percentage, 85..=130.
    pub font_scale: u32,
}

impl Default for AppearanceSettings {
    fn default() -> Self {
        Self { theme: Theme::Dark, motion: MotionPref::System, font_scale: 100 }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct Limits {
    /// Model round-trips per user turn.
    pub max_model_steps: u32,
    /// Tool invocations per task.
    pub max_tool_calls: u32,
    pub request_timeout_secs: u32,
    pub tool_timeout_secs: u32,
    /// How long an approval prompt waits before it expires.
    pub approval_timeout_secs: u32,
    pub max_output_tokens: u32,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_model_steps: 8,
            max_tool_calls: 12,
            request_timeout_secs: 300,
            tool_timeout_secs: 30,
            approval_timeout_secs: 600,
            max_output_tokens: 16_000,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
#[serde(default)]
pub struct NetworkSettings {
    /// When on, no cloud provider or network tool is contacted.
    pub offline_mode: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
#[serde(default)]
pub struct RetentionSettings {
    /// Delete non-archived conversations older than this many days. None keeps everything.
    pub conversation_days: Option<u32>,
    /// Delete audit events older than this many days.
    pub audit_days: Option<u32>,
}

/// What happens when a request would exceed a budget.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BudgetAction {
    /// Refuse the request.
    Stop,
    /// Ask before sending it (one confirmation covers one message).
    Ask,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct UsageSettings {
    /// Estimated spend per calendar month (UTC).
    pub monthly_budget_usd: Option<f64>,
    /// Estimated spend per day (UTC).
    pub daily_budget_usd: Option<f64>,
    /// Worst-case estimated cost of one model request.
    pub per_request_usd: Option<f64>,
    /// Estimated spend per Forge / sibling mission.
    pub mission_budget_usd: Option<f64>,
    /// Block new model requests beyond this count per day.
    pub daily_request_limit: Option<u32>,
    /// Show a warning once spend reaches this percentage of a budget.
    pub warn_at_percent: u32,
    pub on_exceed: BudgetAction,
    /// Owner-entered prices; they take precedence over built-in rates.
    pub price_overrides: Vec<crate::pricing::PriceOverride>,
}

impl Default for UsageSettings {
    fn default() -> Self {
        Self {
            monthly_budget_usd: None,
            daily_budget_usd: None,
            per_request_usd: None,
            mission_budget_usd: None,
            daily_request_limit: None,
            warn_at_percent: 80,
            on_exceed: BudgetAction::Ask,
            price_overrides: vec![],
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct ForgeSettings {
    /// Wall-clock limit for one command (tests, builds) run in a Forge project.
    pub command_timeout_secs: u32,
    /// Output kept per command run; older output is dropped from the middle.
    pub max_output_kb: u32,
}

impl Default for ForgeSettings {
    fn default() -> Self {
        Self { command_timeout_secs: 600, max_output_kb: 256 }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct VoiceSettings {
    pub enabled: bool,
    pub speak_responses: bool,
    pub language: String,
}

impl Default for VoiceSettings {
    fn default() -> Self {
        Self { enabled: false, speak_responses: false, language: "en-US".into() }
    }
}

impl Settings {
    pub fn validate(&self) -> Result<()> {
        let l = &self.limits;
        let check = |name: &str, v: u32, lo: u32, hi: u32| {
            if v < lo || v > hi {
                Err(AtlasError::Validation(format!("{name} must be between {lo} and {hi}")))
            } else {
                Ok(())
            }
        };
        check("max_model_steps", l.max_model_steps, 1, 25)?;
        check("max_tool_calls", l.max_tool_calls, 0, 50)?;
        check("request_timeout_secs", l.request_timeout_secs, 10, 1800)?;
        check("tool_timeout_secs", l.tool_timeout_secs, 1, 300)?;
        check("approval_timeout_secs", l.approval_timeout_secs, 15, 3600)?;
        check("max_output_tokens", l.max_output_tokens, 256, 128_000)?;
        check("font_scale", self.appearance.font_scale, 85, 130)?;
        check("memory.max_retrieved", self.memory.max_retrieved, 0, 20)?;
        if self.companion.preferred_name.chars().count() > 60 {
            return Err(AtlasError::Validation("preferred name is too long".into()));
        }
        let u = &self.usage;
        for (name, v) in [
            ("monthly budget", u.monthly_budget_usd),
            ("daily budget", u.daily_budget_usd),
            ("per-request limit", u.per_request_usd),
            ("mission budget", u.mission_budget_usd),
        ] {
            if let Some(b) = v
                && (!b.is_finite() || !(0.0..=100_000.0).contains(&b)) {
                    return Err(AtlasError::Validation(format!("{name} must be between 0 and 100000 USD")));
                }
        }
        check("warn_at_percent", u.warn_at_percent, 1, 100)?;
        crate::pricing::validate_overrides(&u.price_overrides).map_err(AtlasError::Validation)?;
        check("forge.command_timeout_secs", self.forge.command_timeout_secs, 5, 3600)?;
        check("forge.max_output_kb", self.forge.max_output_kb, 16, 4096)?;
        for t in [&self.routing.fast, &self.routing.standard, &self.routing.heavy].into_iter().flatten() {
            if t.model.trim().is_empty() || t.model.len() > 200 || t.provider_id.is_empty() {
                return Err(AtlasError::Validation("each model tier needs a provider and a model".into()));
            }
        }
        Ok(())
    }

    pub fn load(db: &Db) -> Result<Settings> {
        let conn = db.conn()?;
        let raw: Option<String> = conn
            .query_row("SELECT value FROM settings WHERE key = 'app'", [], |r| r.get(0))
            .map(Some)
            .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(e) })?;
        match raw {
            None => Ok(Settings::default()),
            Some(s) => Ok(serde_json::from_str(&s).unwrap_or_default()),
        }
    }

    pub fn save(&self, db: &Db) -> Result<()> {
        self.validate()?;
        let json = serde_json::to_string(self)?;
        db.conn()?.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES ('app', ?1, ?2)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            rusqlite::params![json, now()],
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_roundtrip_and_partial_documents_fill_defaults() {
        let db = Db::open_in_memory().unwrap();
        assert_eq!(Settings::load(&db).unwrap(), Settings::default());
        let mut s = Settings::default();
        s.companion.preferred_name = "Sam".into();
        s.save(&db).unwrap();
        assert_eq!(Settings::load(&db).unwrap().companion.preferred_name, "Sam");
        let partial: Settings = serde_json::from_str(r#"{"companion":{"tone":"warm"}}"#).unwrap();
        assert_eq!(partial.companion.tone, Tone::Warm);
        assert_eq!(partial.limits, Limits::default());
    }

    #[test]
    fn rejects_out_of_range_limits() {
        let mut s = Settings::default();
        s.limits.max_model_steps = 1000;
        assert!(s.validate().is_err());
    }
}
