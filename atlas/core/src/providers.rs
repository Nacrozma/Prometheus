//! Provider configurations (no secrets), instantiation, health and routing.

use crate::ai::anthropic::AnthropicProvider;
use crate::ai::openai::OpenAiProvider;
use crate::ai::{ChatProvider, ModelInfo, ProviderError, ProviderErrorKind, ProviderKind};
use crate::credentials::{mask, provider_account, validate_secret, SharedSecrets};
use crate::error::{AtlasError, Result};
use crate::settings::{RoutingMode, Settings, Tier};
use crate::storage::{new_id, now, Db};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProviderStatus {
    NotConfigured,
    Untested,
    Connected,
    Unavailable,
    AuthFailed,
    RateLimited,
    Degraded,
}

impl ProviderStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            ProviderStatus::NotConfigured => "not_configured",
            ProviderStatus::Untested => "untested",
            ProviderStatus::Connected => "connected",
            ProviderStatus::Unavailable => "unavailable",
            ProviderStatus::AuthFailed => "auth_failed",
            ProviderStatus::RateLimited => "rate_limited",
            ProviderStatus::Degraded => "degraded",
        }
    }
    fn parse(s: &str) -> Self {
        serde_json::from_value(serde_json::Value::String(s.into())).unwrap_or(ProviderStatus::NotConfigured)
    }
    pub fn from_error(e: &ProviderError) -> Self {
        match e.kind {
            ProviderErrorKind::Auth => ProviderStatus::AuthFailed,
            ProviderErrorKind::RateLimited => ProviderStatus::RateLimited,
            ProviderErrorKind::Unavailable | ProviderErrorKind::Network | ProviderErrorKind::Timeout => ProviderStatus::Unavailable,
            ProviderErrorKind::Server | ProviderErrorKind::Overloaded | ProviderErrorKind::Decode => ProviderStatus::Degraded,
            _ => ProviderStatus::Degraded,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderConfig {
    pub id: String,
    pub kind: ProviderKind,
    pub label: String,
    pub base_url: String,
    pub default_model: Option<String>,
    pub enabled: bool,
    pub status: ProviderStatus,
    pub status_detail: Option<String>,
    pub last_checked_at: Option<String>,
    pub models: Vec<ModelInfo>,
    pub has_credential: bool,
    pub key_hint: Option<String>,
    pub local: bool,
}

fn validate_base_url(kind: ProviderKind, url: &str) -> Result<String> {
    let u = url.trim().trim_end_matches('/');
    let parsed = reqwest::Url::parse(u).map_err(|_| AtlasError::Validation("base URL is not a valid URL".into()))?;
    let host = parsed.host_str().unwrap_or_default();
    let loopback = matches!(host, "localhost" | "127.0.0.1" | "::1" | "[::1]");
    match parsed.scheme() {
        "https" => {}
        // Plain HTTP only to this machine; never send API keys over cleartext to remote hosts.
        "http" if loopback => {}
        "http" if kind == ProviderKind::Mock => {}
        _ => return Err(AtlasError::Validation("use https:// (plain http is only allowed for localhost)".into())),
    }
    Ok(u.to_string())
}

pub fn create(db: &Db, kind: ProviderKind, label: &str, base_url: &str, default_model: Option<&str>) -> Result<ProviderConfig> {
    if kind == ProviderKind::Mock && !cfg!(any(test, feature = "test-support")) {
        return Err(AtlasError::Validation("unknown provider kind".into()));
    }
    let base = validate_base_url(kind, base_url)?;
    let label = if label.trim().is_empty() { format!("{kind:?}") } else { label.trim().to_string() };
    let id = new_id();
    let t = now();
    let status = if kind.needs_key() { ProviderStatus::NotConfigured } else { ProviderStatus::Untested };
    db.conn()?.execute(
        "INSERT INTO providers(id, kind, label, base_url, default_model, status, created_at, updated_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?7)",
        rusqlite::params![id, serde_json::to_value(kind)?.as_str(), label, base, default_model.filter(|m| !m.trim().is_empty()), status.as_str(), t],
    )?;
    get(db, &id)
}

pub fn update(db: &Db, id: &str, label: &str, base_url: &str, default_model: Option<&str>, enabled: bool) -> Result<ProviderConfig> {
    let cur = get(db, id)?;
    let base = validate_base_url(cur.kind, base_url)?;
    let url_changed = base != cur.base_url;
    db.conn()?.execute(
        "UPDATE providers SET label = ?1, base_url = ?2, default_model = ?3, enabled = ?4, updated_at = ?5,
           status = CASE WHEN ?6 = 1 AND status != 'not_configured' THEN 'untested' ELSE status END
         WHERE id = ?7",
        rusqlite::params![label.trim(), base, default_model.filter(|m| !m.trim().is_empty()), enabled as i64, now(), url_changed as i64, id],
    )?;
    get(db, id)
}

pub fn delete(db: &Db, secrets: &SharedSecrets, id: &str) -> Result<()> {
    secrets.delete(&provider_account(id))?;
    db.conn()?.execute("DELETE FROM providers WHERE id = ?1", [id])?;
    Ok(())
}

pub fn set_key(db: &Db, secrets: &SharedSecrets, id: &str, key: &str) -> Result<ProviderConfig> {
    let key = validate_secret(key)?;
    get(db, id)?;
    secrets.set(&provider_account(id), &key)?;
    db.conn()?.execute(
        "UPDATE providers SET key_hint = ?1, status = 'untested', status_detail = NULL, updated_at = ?2 WHERE id = ?3",
        rusqlite::params![mask(&key), now(), id],
    )?;
    get(db, id)
}

pub fn clear_key(db: &Db, secrets: &SharedSecrets, id: &str) -> Result<ProviderConfig> {
    let cur = get(db, id)?;
    secrets.delete(&provider_account(id))?;
    let status = if cur.kind.needs_key() { ProviderStatus::NotConfigured } else { cur.status };
    db.conn()?.execute(
        "UPDATE providers SET key_hint = NULL, status = ?1, updated_at = ?2 WHERE id = ?3",
        rusqlite::params![status.as_str(), now(), id],
    )?;
    get(db, id)
}

pub fn set_status(db: &Db, id: &str, status: ProviderStatus, detail: Option<&str>) {
    if let Ok(conn) = db.conn() {
        let _ = conn.execute(
            "UPDATE providers SET status = ?1, status_detail = ?2, last_checked_at = ?3 WHERE id = ?4",
            rusqlite::params![status.as_str(), detail.map(crate::redact::redact), now(), id],
        );
    }
}

pub fn save_models(db: &Db, id: &str, models: &[ModelInfo]) -> Result<()> {
    db.conn()?.execute("UPDATE providers SET models = ?1 WHERE id = ?2", rusqlite::params![serde_json::to_string(models)?, id])?;
    Ok(())
}

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<ProviderConfig> {
    let kind: String = r.get(1)?;
    let kind: ProviderKind = serde_json::from_value(serde_json::Value::String(kind)).unwrap_or(ProviderKind::OpenaiCompatible);
    let key_hint: Option<String> = r.get(10)?;
    Ok(ProviderConfig {
        id: r.get(0)?,
        kind,
        label: r.get(2)?,
        base_url: r.get(3)?,
        default_model: r.get(4)?,
        enabled: r.get::<_, i64>(5)? != 0,
        status: ProviderStatus::parse(&r.get::<_, String>(6)?),
        status_detail: r.get(7)?,
        last_checked_at: r.get(8)?,
        models: r.get::<_, Option<String>>(9)?.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default(),
        has_credential: key_hint.is_some(),
        key_hint,
        local: kind.is_local(),
    })
}

const COLS: &str = "id, kind, label, base_url, default_model, enabled, status, status_detail, last_checked_at, models, key_hint";

pub fn get(db: &Db, id: &str) -> Result<ProviderConfig> {
    db.conn()?
        .query_row(&format!("SELECT {COLS} FROM providers WHERE id = ?1"), [id], row)
        .map_err(|e| match e {
            rusqlite::Error::QueryReturnedNoRows => AtlasError::NotFound("provider".into()),
            o => o.into(),
        })
}

pub fn list(db: &Db) -> Result<Vec<ProviderConfig>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM providers ORDER BY created_at"))?;
    let rows = stmt.query_map([], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

/// Shared HTTP client: connection timeout bounded; per-request timeouts set by callers.
pub fn http_client() -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .user_agent(concat!("ATLAS-CoPilot/", env!("CARGO_PKG_VERSION")))
        .build()
        .unwrap_or_default()
}

/// Factory for provider instances; tests inject scripted providers by id.
pub trait ProviderFactory: Send + Sync {
    fn build(&self, cfg: &ProviderConfig, secrets: &SharedSecrets, idle_timeout: Duration) -> Result<Arc<dyn ChatProvider>>;
}

pub struct DefaultFactory {
    pub http: reqwest::Client,
}

impl ProviderFactory for DefaultFactory {
    fn build(&self, cfg: &ProviderConfig, secrets: &SharedSecrets, idle_timeout: Duration) -> Result<Arc<dyn ChatProvider>> {
        let key = if cfg.kind.needs_key() || cfg.has_credential { secrets.get(&provider_account(&cfg.id))? } else { None };
        if cfg.kind.needs_key() && key.is_none() {
            return Err(AtlasError::Validation(format!("{} has no API key configured", cfg.label)));
        }
        Ok(match cfg.kind {
            ProviderKind::Anthropic => Arc::new(AnthropicProvider::new(self.http.clone(), Some(&cfg.base_url), key.unwrap_or_default(), idle_timeout)),
            ProviderKind::Mock => return Err(AtlasError::Validation("mock providers are test-only".into())),
            _ => Arc::new(OpenAiProvider::new(self.http.clone(), cfg.kind, &cfg.base_url, key, idle_timeout)),
        })
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Route {
    pub provider: ProviderConfig,
    pub model: String,
    pub model_info: Option<ModelInfo>,
    /// Plain-language explanation shown to the user.
    pub reason: String,
    /// True when the route differs from the user's preferred provider.
    pub fell_back: bool,
    /// Model tier used, when tier routing chose the model.
    pub tier: Option<Tier>,
}

/// What the router knows about a request when picking a tier. Built from the request itself;
/// never from model output.
#[derive(Debug, Clone, Default)]
pub struct RouteSignals {
    pub text_chars: usize,
    /// The text looks like engineering work (code, stack traces, build/test talk).
    pub engineering: bool,
    /// A Forge discipline whose work is multi-step analysis (Architect, Debugger, Reconstructor).
    pub deep_discipline: bool,
    /// A Forge discipline is active at all.
    pub forge: bool,
}

impl RouteSignals {
    pub fn from_text(text: &str) -> Self {
        let lower = text.to_lowercase();
        const WORDS: &[&str] = &[
            "```", "traceback", "stack trace", "exception", "compile", "refactor", "debug", "unit test", "failing test",
            "segfault", "panic", "architecture", "implement", "function", "regression", "error:", "fn ", "def ", "class ",
        ];
        Self { text_chars: text.chars().count(), engineering: WORDS.iter().any(|w| lower.contains(w)), ..Default::default() }
    }
}

/// Pick a tier for the routing mode. Returns the tier and a plain-language reason.
pub fn select_tier(mode: RoutingMode, sig: &RouteSignals) -> Option<(Tier, &'static str)> {
    match mode {
        RoutingMode::Manual => None,
        RoutingMode::Budget => Some((Tier::Fast, "Budget mode")),
        RoutingMode::Balanced => Some((Tier::Standard, "Balanced mode")),
        RoutingMode::Quality => Some((Tier::Heavy, "Quality mode")),
        RoutingMode::Auto => Some(if sig.deep_discipline {
            (Tier::Heavy, "Auto: multi-step engineering discipline")
        } else if (sig.engineering && sig.text_chars > 1200) || sig.text_chars > 6000 {
            (Tier::Heavy, "Auto: long or complex engineering request")
        } else if sig.text_chars < 280 && !sig.engineering && !sig.forge {
            (Tier::Fast, "Auto: short everyday request")
        } else {
            (Tier::Standard, "Auto: typical request")
        }),
    }
}

/// Tier-aware routing. An explicit provider/model choice for the conversation always wins.
/// A tier's model is used when it is configured and its provider is usable; otherwise Atlas
/// steps down to the next configured tier (Heavy → Standard → Fast) and then to your default,
/// saying so in the reason. Tier providers are ones the owner chose for that tier, so using
/// them is not a silent provider switch.
pub fn route_tiered(
    settings: &Settings,
    providers: &[ProviderConfig],
    provider_override: Option<&str>,
    model_override: Option<&str>,
    signals: &RouteSignals,
    needs_tools: bool,
) -> Result<Route> {
    let explicit = provider_override.is_some() || model_override.is_some();
    let picked = if explicit { None } else { select_tier(settings.routing.mode, signals) };
    let Some((tier, why)) = picked else {
        return route(settings, providers, provider_override, model_override, needs_tools);
    };
    let order: &[Tier] = match tier {
        Tier::Heavy => &[Tier::Heavy, Tier::Standard, Tier::Fast],
        Tier::Standard => &[Tier::Standard, Tier::Heavy, Tier::Fast],
        Tier::Fast => &[Tier::Fast, Tier::Standard, Tier::Heavy],
    };
    let mut skipped: Vec<String> = Vec::new();
    for t in order {
        let Some(tm) = settings.routing.tier_model(*t) else {
            skipped.push(format!("{} tier not set", t.label()));
            continue;
        };
        let Some(p) = providers.iter().find(|p| p.id == tm.provider_id) else {
            skipped.push(format!("{} tier's provider was removed", t.label()));
            continue;
        };
        let usable_now = usable(p).and_then(|_| {
            if settings.network.offline_mode && !p.local { Err(format!("offline mode is on and {} is a cloud service", p.label)) } else { Ok(()) }
        }).and_then(|_| match crate::pricing::unavailable_reason(p.kind, &tm.model) {
            Some(why) => Err(why),
            None => Ok(()),
        });
        if let Err(problem) = usable_now {
            skipped.push(format!("{} tier unavailable: {problem}", t.label()));
            continue;
        }
        let model_info = p.models.iter().find(|m| m.id == tm.model).cloned();
        let mut reason = format!("{why} → {} tier: {} on {}", t.label(), tm.model, p.label);
        if !skipped.is_empty() {
            reason.push_str(&format!(" ({})", skipped.join("; ")));
        }
        if needs_tools && model_info.as_ref().and_then(|m| m.supports_tools) == Some(false) {
            reason.push_str("; this model cannot use tools");
        }
        return Ok(Route { provider: p.clone(), model: tm.model.clone(), model_info, reason, fell_back: false, tier: Some(*t) });
    }
    let mut r = route(settings, providers, None, None, needs_tools)?;
    r.reason = format!("{} — {why}, but no tier model is usable ({}), so using your default", r.reason, skipped.join("; "));
    Ok(r)
}

fn usable(p: &ProviderConfig) -> std::result::Result<(), String> {
    if !p.enabled {
        return Err(format!("{} is disabled", p.label));
    }
    if p.kind.needs_key() && !p.has_credential {
        return Err(format!("{} has no API key", p.label));
    }
    if p.status == ProviderStatus::AuthFailed {
        return Err(format!("{} rejected its API key last time", p.label));
    }
    Ok(())
}

/// Choose a provider and model for a request. Never silently switches provider: a fallback
/// requires `allow_cross_provider_fallback` and is reported in `reason`.
pub fn route(settings: &Settings, providers: &[ProviderConfig], provider_override: Option<&str>, model_override: Option<&str>, needs_tools: bool) -> Result<Route> {
    if providers.is_empty() {
        return Err(AtlasError::Validation("no AI provider is configured yet — add one in Integrations → AI providers".into()));
    }
    let offline = settings.network.offline_mode;
    let preferred_id = provider_override.or(settings.default_provider_id.as_deref());
    let preferred = preferred_id.and_then(|id| providers.iter().find(|p| p.id == id)).or_else(|| providers.iter().find(|p| p.enabled));
    let preferred = preferred.ok_or_else(|| AtlasError::Validation("no enabled AI provider".into()))?;

    let check = |p: &ProviderConfig| -> std::result::Result<(), String> {
        usable(p)?;
        if offline && !p.local {
            return Err(format!("offline mode is on and {} is a cloud service", p.label));
        }
        Ok(())
    };

    let (chosen, reason, fell_back) = match check(preferred) {
        Ok(()) => {
            let why = if provider_override.is_some() { "chosen for this conversation" } else { "your default provider" };
            (preferred, format!("{} ({why})", preferred.label), false)
        }
        Err(problem) => {
            if !settings.routing.allow_cross_provider_fallback || provider_override.is_some() {
                return Err(AtlasError::Validation(format!(
                    "{problem}. Atlas will not switch to another provider automatically; fix it in Integrations or enable fallback in Settings → Model routing."
                )));
            }
            let alt = providers
                .iter()
                .filter(|p| p.id != preferred.id && check(p).is_ok())
                .min_by_key(|p| match p.status {
                    ProviderStatus::Connected => 0,
                    ProviderStatus::Untested => 1,
                    _ => 2,
                })
                .ok_or_else(|| AtlasError::Validation(format!("{problem}, and no other provider is usable")))?;
            (alt, format!("{} — fallback because {problem}. Your message will be processed by {}.", alt.label, alt.label), true)
        }
    };

    let model = model_override
        .map(str::to_string)
        .or_else(|| chosen.default_model.clone())
        .or_else(|| if settings.default_provider_id.as_deref() == Some(&chosen.id) { settings.default_model.clone() } else { None })
        .or_else(|| chosen.models.first().map(|m| m.id.clone()))
        .ok_or_else(|| AtlasError::Validation(format!("choose a model for {} (test the connection to load its model list)", chosen.label)))?;
    if let Some(why) = crate::pricing::unavailable_reason(chosen.kind, &model) {
        return Err(AtlasError::Validation(format!("{why}. Choose another model for {} in Integrations.", chosen.label)));
    }
    let model_info = chosen.models.iter().find(|m| m.id == model).cloned();
    if needs_tools && model_info.as_ref().and_then(|m| m.supports_tools) == Some(false) {
        return Ok(Route { reason: format!("{reason}; this model cannot use tools"), provider: chosen.clone(), model, model_info, fell_back, tier: None });
    }
    Ok(Route { provider: chosen.clone(), model, model_info, reason, fell_back, tier: None })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::credentials::MemorySecrets;

    fn setup() -> (Db, SharedSecrets) {
        (Db::open_in_memory().unwrap(), Arc::new(MemorySecrets::default()))
    }

    #[test]
    fn rejects_cleartext_remote_urls() {
        let (db, _) = setup();
        assert!(create(&db, ProviderKind::OpenaiCompatible, "x", "http://example.com/v1", None).is_err());
        assert!(create(&db, ProviderKind::Ollama, "o", "http://127.0.0.1:11434/v1", None).is_ok());
    }

    #[test]
    fn key_lifecycle_never_stores_secret_in_db() {
        let (db, secrets) = setup();
        let p = create(&db, ProviderKind::Anthropic, "Claude", "https://api.anthropic.com", Some("claude-opus-5-5")).unwrap();
        assert_eq!(p.status, ProviderStatus::NotConfigured);
        let p = set_key(&db, &secrets, &p.id, "sk-ant-api03-SUPERSECRETVALUE-abcd").unwrap();
        assert_eq!(p.status, ProviderStatus::Untested);
        assert_eq!(p.key_hint.as_deref(), Some("sk-ant…abcd"));
        let dump: String = db.conn().unwrap().query_row("SELECT group_concat(coalesce(key_hint,'') || base_url || coalesce(models,'')) FROM providers", [], |r| r.get(0)).unwrap();
        assert!(!dump.contains("SUPERSECRET"));
        let p = clear_key(&db, &secrets, &p.id).unwrap();
        assert!(!p.has_credential);
        assert!(secrets.get(&provider_account(&p.id)).unwrap().is_none());
    }

    #[test]
    fn routing_never_silently_switches() {
        let (db, secrets) = setup();
        let a = create(&db, ProviderKind::Anthropic, "Claude", "https://api.anthropic.com", Some("claude-opus-5-5")).unwrap();
        let o = create(&db, ProviderKind::Ollama, "Local", "http://127.0.0.1:11434/v1", Some("qwen3")).unwrap();
        let mut s = Settings { default_provider_id: Some(a.id.clone()), ..Settings::default() };
        // No key → error, no fallback.
        let err = route(&s, &list(&db).unwrap(), None, None, true).unwrap_err();
        assert!(err.to_string().contains("will not switch"));
        // With fallback consent → routed to Ollama, and the reason says so.
        s.routing.allow_cross_provider_fallback = true;
        let r = route(&s, &list(&db).unwrap(), None, None, true).unwrap();
        assert_eq!(r.provider.id, o.id);
        assert!(r.fell_back && r.reason.contains("processed by Local"));
        // Offline mode blocks cloud providers.
        set_key(&db, &secrets, &a.id, "sk-ant-api03-abcdefghijklmnop").unwrap();
        s.network.offline_mode = true;
        let r = route(&s, &list(&db).unwrap(), None, None, true).unwrap();
        assert_eq!(r.provider.id, o.id);
        s.routing.allow_cross_provider_fallback = false;
        assert!(route(&s, &list(&db).unwrap(), None, None, true).is_err());
    }

    #[test]
    fn auto_mode_picks_tiers_from_the_request() {
        let sig = |t: &str| RouteSignals::from_text(t);
        assert_eq!(select_tier(RoutingMode::Auto, &sig("What's a good name for a cat?")).unwrap().0, Tier::Fast);
        let long_code = format!("Please refactor this module:\n```rust\n{}\n```", "fn a() {}\n".repeat(200));
        assert_eq!(select_tier(RoutingMode::Auto, &sig(&long_code)).unwrap().0, Tier::Heavy);
        assert_eq!(select_tier(RoutingMode::Auto, &sig("Why does this panic? fn main() { let v: Vec<u8> = vec![]; v[0]; }")).unwrap().0, Tier::Standard);
        let deep = RouteSignals { deep_discipline: true, forge: true, ..sig("hi") };
        assert_eq!(select_tier(RoutingMode::Auto, &deep).unwrap().0, Tier::Heavy);
        assert_eq!(select_tier(RoutingMode::Budget, &deep).unwrap().0, Tier::Fast);
        assert_eq!(select_tier(RoutingMode::Quality, &sig("hi")).unwrap().0, Tier::Heavy);
        assert!(select_tier(RoutingMode::Manual, &sig("hi")).is_none());
    }

    #[test]
    fn tiers_route_to_configured_models_and_step_down_honestly() {
        use crate::settings::TierModel;
        let (db, secrets) = setup();
        let a = create(&db, ProviderKind::Anthropic, "Claude", "https://api.anthropic.com", Some("claude-opus-5-5")).unwrap();
        set_key(&db, &secrets, &a.id, "sk-ant-api03-abcdefghijklmnop").unwrap();
        let o = create(&db, ProviderKind::Openai, "OpenAI", "https://api.openai.com/v1", Some("gpt-4.1")).unwrap();
        let mut s = Settings { default_provider_id: Some(a.id.clone()), ..Settings::default() };
        s.routing.mode = RoutingMode::Quality;
        s.routing.heavy = Some(TierModel { provider_id: o.id.clone(), model: "gpt-5.5".into() });
        s.routing.standard = Some(TierModel { provider_id: a.id.clone(), model: "claude-sonnet-5-5".into() });
        let sig = RouteSignals::from_text("hi");
        // OpenAI has no key → Heavy is skipped, Standard is used, and the reason says why.
        let r = route_tiered(&s, &list(&db).unwrap(), None, None, &sig, true).unwrap();
        assert_eq!((r.model.as_str(), r.tier), ("claude-sonnet-5-5", Some(Tier::Standard)));
        assert!(r.reason.contains("Heavy tier unavailable") && r.reason.contains("no API key"), "{}", r.reason);
        set_key(&db, &secrets, &o.id, "sk-proj-abcdefghijklmnopqrstu").unwrap();
        let r = route_tiered(&s, &list(&db).unwrap(), None, None, &sig, true).unwrap();
        assert_eq!((r.provider.id.as_str(), r.model.as_str()), (o.id.as_str(), "gpt-5.5"));
        // An explicit choice for the conversation overrides tiers.
        let r = route_tiered(&s, &list(&db).unwrap(), Some(&a.id), None, &sig, true).unwrap();
        assert_eq!((r.model.as_str(), r.tier), ("claude-opus-5-5", None));
        // Manual ignores tiers entirely.
        s.routing.mode = RoutingMode::Manual;
        assert_eq!(route_tiered(&s, &list(&db).unwrap(), None, None, &sig, true).unwrap().model, "claude-opus-5-5");
        // No usable tier → default, with an explanation.
        s.routing.mode = RoutingMode::Budget;
        s.routing.heavy = None;
        s.routing.standard = None;
        let r = route_tiered(&s, &list(&db).unwrap(), None, None, &sig, true).unwrap();
        assert!(r.tier.is_none() && r.reason.contains("no tier model is usable"), "{}", r.reason);
    }

    #[test]
    fn shut_down_models_are_never_routed_to() {
        use crate::settings::TierModel;
        let (db, secrets) = setup();
        let o = create(&db, ProviderKind::Openai, "OpenAI", "https://api.openai.com/v1", Some("gpt-4.1-nano")).unwrap();
        set_key(&db, &secrets, &o.id, "sk-proj-abcdefghijklmnopqrstu").unwrap();
        let mut s = Settings { default_provider_id: Some(o.id.clone()), ..Settings::default() };
        let e = route(&s, &list(&db).unwrap(), None, None, true).unwrap_err();
        assert!(e.to_string().contains("shut down") && e.to_string().contains("gpt-5.6-luna"), "{e}");
        s.routing.mode = RoutingMode::Budget;
        s.routing.fast = Some(TierModel { provider_id: o.id.clone(), model: "gpt-4.1-nano".into() });
        s.routing.standard = Some(TierModel { provider_id: o.id.clone(), model: "gpt-6.1-sol".into() });
        let r = route_tiered(&s, &list(&db).unwrap(), None, None, &RouteSignals::from_text("hi"), true).unwrap();
        assert_eq!(r.model, "gpt-6.1-sol");
        assert!(r.reason.contains("shut down"), "{}", r.reason);
    }
}
