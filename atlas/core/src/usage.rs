//! Usage and estimated cost tracking, plus optional budget / request limits.

use crate::ai::{catalog, ProviderKind, Usage};
use crate::error::Result;
use crate::settings::Settings;
use crate::storage::{now, Db};
use serde::Serialize;

pub fn record(db: &Db, provider_id: &str, kind: ProviderKind, model: &str, usage: &Usage, duration_ms: u128, outcome: &str) -> Option<f64> {
    let cost = catalog::estimate_cost(kind, model, usage.input_tokens, usage.output_tokens);
    if let Ok(conn) = db.conn() {
        let _ = conn.execute(
            "INSERT INTO usage_records(ts, provider_id, model, input_tokens, output_tokens, duration_ms, estimated_cost_usd, outcome)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
            rusqlite::params![now(), provider_id, model, usage.input_tokens.map(|v| v as i64), usage.output_tokens.map(|v| v as i64), duration_ms as i64, cost, outcome],
        );
    }
    cost
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
    pub today_requests: i64,
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
    let today: i64 = conn.query_row("SELECT count(*) FROM usage_records WHERE ts >= ?1", [day_start()], |r| r.get(0))?;
    Ok(UsageSummary {
        period_start: start,
        month_estimated_cost_usd: by_model.iter().map(|m| m.estimated_cost_usd).sum(),
        month_has_unknown_costs: by_model.iter().any(|m| m.unknown_cost_requests > 0),
        by_model,
        today_requests: today,
    })
}

/// Refuse new model requests past a configured limit. Returns a user-facing reason.
pub fn check_limits(db: &Db, settings: &Settings) -> std::result::Result<(), String> {
    let s = summary(db).map_err(|e| e.to_string())?;
    if let Some(limit) = settings.usage.daily_request_limit
        && s.today_requests >= limit as i64 {
            return Err(format!("the daily limit of {limit} model requests has been reached (Settings → Usage)"));
        }
    if let Some(budget) = settings.usage.monthly_budget_usd
        && s.month_estimated_cost_usd >= budget {
            return Err(format!(
                "estimated spend this month (${:.2}) has reached your budget of ${budget:.2} (Settings → Usage)",
                s.month_estimated_cost_usd
            ));
        }
    Ok(())
}
