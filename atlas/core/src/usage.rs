//! Usage and estimated cost tracking, plus optional budget / request limits.

use crate::ai::{ProviderKind, Usage};
use crate::error::Result;
use crate::pricing::{self, Verification};
use crate::settings::{BudgetAction, Settings};
use crate::storage::{now, Db};
use serde::Serialize;

/// One model request to record.
pub struct UsageEntry<'a> {
    pub provider_id: &'a str,
    pub kind: ProviderKind,
    pub model: &'a str,
    pub usage: &'a Usage,
    pub duration_ms: u128,
    pub outcome: &'a str,
    pub mission_id: Option<&'a str>,
}

pub fn record_entry(db: &Db, settings: &Settings, e: UsageEntry<'_>) -> Option<f64> {
    let est = pricing::estimate(e.kind, e.model, &settings.usage.price_overrides, e.usage.input_tokens, e.usage.output_tokens);
    if let Ok(conn) = db.conn() {
        let _ = conn.execute(
            "INSERT INTO usage_records(ts, provider_id, model, input_tokens, output_tokens, duration_ms, estimated_cost_usd, outcome, price_status, mission_id)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
            rusqlite::params![
                now(),
                e.provider_id,
                e.model,
                e.usage.input_tokens.map(|v| v as i64),
                e.usage.output_tokens.map(|v| v as i64),
                e.duration_ms as i64,
                est.map(|c| c.usd),
                e.outcome,
                est.map(|c| c.verification.as_str()),
                e.mission_id
            ],
        );
    }
    est.map(|c| c.usd)
}

/// Record with built-in prices only (kept for callers without settings at hand).
pub fn record(db: &Db, provider_id: &str, kind: ProviderKind, model: &str, usage: &Usage, duration_ms: u128, outcome: &str) -> Option<f64> {
    record_entry(db, &Settings::default(), UsageEntry { provider_id, kind, model, usage, duration_ms, outcome, mission_id: None })
}

#[derive(Debug, Clone, Serialize)]
pub struct ModelUsage {
    pub provider_id: String,
    pub provider_label: Option<String>,
    pub model: String,
    pub requests: i64,
    pub errors: i64,
    pub rate_limited: i64,
    pub input_tokens: i64,
    pub output_tokens: i64,
    /// Sum of known estimates.
    pub estimated_cost_usd: f64,
    /// Requests whose cost could not be estimated.
    pub unknown_cost_requests: i64,
    pub avg_duration_ms: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct UsageSummary {
    pub period_start: String,
    pub by_model: Vec<ModelUsage>,
    pub month_estimated_cost_usd: f64,
    pub month_has_unknown_costs: bool,
    /// Part of the month's estimate built on unverified seed rates.
    pub month_unverified_cost_usd: f64,
    pub today_requests: i64,
    pub today_estimated_cost_usd: f64,
}

fn month_start() -> String {
    let n = chrono::Utc::now();
    format!("{}", n.format("%Y-%m-01T00:00:00Z"))
}

fn day_start() -> String {
    format!("{}", chrono::Utc::now().format("%Y-%m-%dT00:00:00Z"))
}

pub fn summary(db: &Db) -> Result<UsageSummary> {
    let start = month_start();
    let conn = db.conn()?;
    let mut stmt = conn.prepare(
        "SELECT u.provider_id, p.label, u.model, count(*),
                sum(CASE WHEN u.outcome NOT IN ('ok') THEN 1 ELSE 0 END),
                sum(CASE WHEN u.outcome = 'rate_limited' THEN 1 ELSE 0 END),
                coalesce(sum(u.input_tokens),0), coalesce(sum(u.output_tokens),0),
                coalesce(sum(u.estimated_cost_usd),0), sum(CASE WHEN u.estimated_cost_usd IS NULL THEN 1 ELSE 0 END),
                avg(u.duration_ms)
         FROM usage_records u LEFT JOIN providers p ON p.id = u.provider_id
         WHERE u.ts >= ?1 GROUP BY u.provider_id, u.model ORDER BY count(*) DESC",
    )?;
    let by_model: Vec<ModelUsage> = stmt
        .query_map([&start], |r| {
            Ok(ModelUsage {
                provider_id: r.get(0)?,
                provider_label: r.get(1)?,
                model: r.get(2)?,
                requests: r.get(3)?,
                errors: r.get(4)?,
                rate_limited: r.get(5)?,
                input_tokens: r.get(6)?,
                output_tokens: r.get(7)?,
                estimated_cost_usd: r.get(8)?,
                unknown_cost_requests: r.get(9)?,
                avg_duration_ms: r.get(10)?,
            })
        })?
        .collect::<std::result::Result<_, _>>()?;
    let (today, today_cost): (i64, f64) = conn.query_row(
        "SELECT count(*), coalesce(sum(estimated_cost_usd),0) FROM usage_records WHERE ts >= ?1",
        [day_start()],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    let unverified: f64 = conn.query_row(
        "SELECT coalesce(sum(estimated_cost_usd),0) FROM usage_records WHERE ts >= ?1 AND price_status = 'unverified'",
        [&start],
        |r| r.get(0),
    )?;
    Ok(UsageSummary {
        period_start: start,
        month_estimated_cost_usd: by_model.iter().map(|m| m.estimated_cost_usd).sum(),
        month_has_unknown_costs: by_model.iter().any(|m| m.unknown_cost_requests > 0),
        month_unverified_cost_usd: unverified,
        by_model,
        today_requests: today,
        today_estimated_cost_usd: today_cost,
    })
}

pub fn mission_spend(db: &Db, mission_id: &str) -> Result<f64> {
    Ok(db.conn()?.query_row(
        "SELECT coalesce(sum(estimated_cost_usd),0) FROM usage_records WHERE mission_id = ?1",
        [mission_id],
        |r| r.get(0),
    )?)
}

/// Result of checking budgets before a model request.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "verdict", content = "message", rename_all = "snake_case")]
pub enum BudgetVerdict {
    Ok,
    /// Allowed, but the owner should see this.
    Warn(String),
    /// Over a budget and the owner chose "ask first".
    Confirm(String),
    /// Over a budget and the owner chose "stop", or a hard request limit was hit.
    Stop(String),
}

/// What the next request is expected to cost at most, if known.
#[derive(Debug, Clone, Copy)]
pub struct Projection {
    pub usd: Option<f64>,
    pub verification: Option<Verification>,
}

/// Rough upper bound for one request: prompt characters / 4 as input tokens, plus the full
/// output allowance. Used only to enforce limits, and labelled "up to" in messages.
pub fn project(kind: ProviderKind, model: &str, settings: &Settings, prompt_chars: usize, max_output_tokens: u32) -> Projection {
    let input = (prompt_chars / 4) as u64 + 1;
    let est = pricing::estimate(kind, model, &settings.usage.price_overrides, Some(input), Some(max_output_tokens as u64));
    Projection { usd: est.map(|c| c.usd), verification: est.map(|c| c.verification) }
}

/// Check every configured limit. `mission` is (mission id) when the request belongs to one.
pub fn check_budget(db: &Db, settings: &Settings, projection: Projection, mission: Option<&str>) -> Result<BudgetVerdict> {
    let u = &settings.usage;
    let s = summary(db)?;
    if let Some(limit) = u.daily_request_limit
        && s.today_requests >= limit as i64 {
            return Ok(BudgetVerdict::Stop(format!("the daily limit of {limit} model requests has been reached (Settings → Usage & budgets)")));
        }
    let next = projection.usd.unwrap_or(0.0);
    let over = |msg: String| match u.on_exceed {
        BudgetAction::Stop => BudgetVerdict::Stop(msg),
        BudgetAction::Ask => BudgetVerdict::Confirm(msg),
    };
    if let (Some(limit), Some(p)) = (u.per_request_usd, projection.usd)
        && p > limit {
            return Ok(over(format!("this request could cost up to ${p:.4}, above your per-request limit of ${limit:.2}")));
        }
    let mut warns = Vec::new();
    let mut checks: Vec<(&str, Option<f64>, f64)> = vec![
        ("monthly budget", u.monthly_budget_usd, s.month_estimated_cost_usd),
        ("daily budget", u.daily_budget_usd, s.today_estimated_cost_usd),
    ];
    if let Some(mid) = mission {
        checks.push(("mission budget", u.mission_budget_usd, mission_spend(db, mid)?));
    }
    for (name, limit, spent) in checks {
        let Some(limit) = limit else { continue };
        if spent >= limit {
            return Ok(over(format!("estimated spend (${spent:.2}) has reached your {name} of ${limit:.2}")));
        }
        if spent + next > limit {
            return Ok(over(format!("this request could take estimated spend to ${:.2}, past your {name} of ${limit:.2}", spent + next)));
        }
        if limit > 0.0 && spent / limit * 100.0 >= u.warn_at_percent as f64 {
            warns.push(format!("estimated spend is ${spent:.2} of your {name} (${limit:.2})"));
        }
    }
    let any_budget = u.per_request_usd.is_some() || u.monthly_budget_usd.is_some() || u.daily_budget_usd.is_some() || (mission.is_some() && u.mission_budget_usd.is_some());
    if any_budget && projection.usd.is_none() {
        warns.push("this model's price is unknown, so its cost is not counted toward your budgets (add a price in Settings → Usage & budgets)".into());
    }
    if projection.verification == Some(Verification::Unverified) && any_budget {
        warns.push("this model's price is an unverified seed rate, so budget figures are approximate".into());
    }
    Ok(if warns.is_empty() { BudgetVerdict::Ok } else { BudgetVerdict::Warn(warns.join("; ")) })
}

/// Back-compatible hard-limit check used where no projection is available.
pub fn check_limits(db: &Db, settings: &Settings) -> std::result::Result<(), String> {
    match check_budget(db, settings, Projection { usd: None, verification: None }, None).map_err(|e| e.to_string())? {
        BudgetVerdict::Stop(m) | BudgetVerdict::Confirm(m) => Err(m),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::BudgetAction;

    fn spend(db: &Db, usd: f64, mission: Option<&str>) {
        db.conn()
            .unwrap()
            .execute(
                "INSERT INTO usage_records(ts, provider_id, model, duration_ms, estimated_cost_usd, outcome, mission_id) VALUES (?1,'p','m',1,?2,'ok',?3)",
                rusqlite::params![now(), usd, mission],
            )
            .unwrap();
    }
    const P: Projection = Projection { usd: Some(0.10), verification: Some(Verification::Verified) };

    #[test]
    fn budgets_warn_ask_and_stop() {
        let db = Db::open_in_memory().unwrap();
        let mut s = Settings::default();
        assert_eq!(check_budget(&db, &s, P, None).unwrap(), BudgetVerdict::Ok);
        s.usage.daily_budget_usd = Some(1.0);
        spend(&db, 0.85, None);
        assert!(matches!(check_budget(&db, &s, P, None).unwrap(), BudgetVerdict::Warn(m) if m.contains("daily budget")));
        // Projected spend past the limit: ask (default) or stop.
        let big = Projection { usd: Some(0.5), verification: Some(Verification::Verified) };
        assert!(matches!(check_budget(&db, &s, big, None).unwrap(), BudgetVerdict::Confirm(_)));
        s.usage.on_exceed = BudgetAction::Stop;
        assert!(matches!(check_budget(&db, &s, big, None).unwrap(), BudgetVerdict::Stop(_)));
        // Per-request limit uses the worst-case projection.
        s.usage.daily_budget_usd = None;
        s.usage.per_request_usd = Some(0.2);
        assert!(matches!(check_budget(&db, &s, big, None).unwrap(), BudgetVerdict::Stop(m) if m.contains("per-request")));
        assert!(matches!(check_budget(&db, &s, P, None).unwrap(), BudgetVerdict::Ok));
        // Unknown price with a budget set is surfaced, not silently counted as zero.
        let unknown = Projection { usd: None, verification: None };
        assert!(matches!(check_budget(&db, &s, unknown, None).unwrap(), BudgetVerdict::Warn(m) if m.contains("unknown")));
    }

    #[test]
    fn mission_budget_counts_only_that_mission() {
        let db = Db::open_in_memory().unwrap();
        let mut s = Settings::default();
        s.usage.mission_budget_usd = Some(1.0);
        spend(&db, 5.0, Some("other"));
        spend(&db, 0.95, Some("m1"));
        assert!(matches!(check_budget(&db, &s, P, Some("m1")).unwrap(), BudgetVerdict::Confirm(m) if m.contains("mission budget")));
        assert!(matches!(check_budget(&db, &s, P, Some("m2")).unwrap(), BudgetVerdict::Ok));
        assert!((mission_spend(&db, "m1").unwrap() - 0.95).abs() < 1e-9);
    }

    #[test]
    fn daily_request_limit_always_stops() {
        let db = Db::open_in_memory().unwrap();
        let mut s = Settings::default();
        s.usage.daily_request_limit = Some(1);
        spend(&db, 0.0, None);
        assert!(matches!(check_budget(&db, &s, P, None).unwrap(), BudgetVerdict::Stop(_)));
        assert!(check_limits(&db, &s).is_err());
    }
}
