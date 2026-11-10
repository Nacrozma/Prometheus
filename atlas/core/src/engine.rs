//! Turn orchestration: one user message → bounded model/tool loop → verified task record.

use crate::ai::{ChatMessage, ChatRequest, EffortHint, Part, ProviderError, ProviderErrorKind, ProviderKind, Role, StopReason, StreamEvent, ToolSpec, Usage};
use crate::app::{describe_provider_error, ActiveTurn, Atlas};
use crate::context;
use crate::conversations;
use crate::error::{AtlasError, Result};
use crate::events::{notify, Topic};
use crate::memory;
use crate::policy::{self, Decision};
use crate::providers::{self, ProviderStatus};
use crate::settings::Effort;
use crate::storage::new_id;
use crate::tasks::{self, TaskStatus};
use crate::tools::dispatch::DispatchEvent;
use crate::tools::Availability;
use crate::{audit, usage};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio_util::sync::CancellationToken;

pub const MAX_USER_MESSAGE_CHARS: usize = 100_000;
const MAX_PROVIDER_RETRIES: u32 = 2;

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TurnParams {
    pub conversation_id: String,
    pub text: String,
    pub provider_id: Option<String>,
    pub model: Option<String>,
    /// The owner confirmed sending this one message although it exceeds a budget.
    #[serde(default)]
    pub budget_override: bool,
    /// Mission this turn belongs to (for mission budgets and the ledger).
    #[serde(default)]
    pub mission_id: Option<String>,
    /// Answer the conversation's last message again, replacing the reply that followed it.
    /// `text` is ignored: the stored message is used. Refused when that reply used tools, so a
    /// regenerate can never repeat an action.
    #[serde(default)]
    pub regenerate: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct MemoryRef {
    pub id: String,
    pub content: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum TurnEvent {
    Started {
        turn_id: String,
        conversation_id: String,
        user_message_id: String,
        provider_label: String,
        provider_kind: ProviderKind,
        model: String,
        local: bool,
        route_reason: String,
        fell_back: bool,
        tier: Option<crate::settings::Tier>,
        memories: Vec<MemoryRef>,
        tools_offered: usize,
    },
    TextDelta { text: String },
    ReasoningDelta { text: String },
    ToolCallStarted { call_id: String, name: String },
    /// Discard text streamed so far for the current model step (a retry follows).
    StepReset { reason: String },
    Tool { event: DispatchEvent },
    AssistantMessage { message_id: String, stop: StopReason, served_model: String },
    ToolResults { message_id: String },
    Notice { level: String, text: String },
    TaskUpdated { task_id: String, status: TaskStatus },
    Finished { outcome: String, error: Option<String>, usage: Usage, estimated_cost_usd: Option<f64>, task_id: Option<String> },
}

#[derive(Debug, Clone, Serialize)]
pub struct TurnSummary {
    pub turn_id: String,
    pub outcome: String,
    pub task_id: Option<String>,
    pub error: Option<String>,
}

pub type TurnSink = Box<dyn FnMut(TurnEvent) + Send>;

struct TurnGuard {
    atlas: Arc<Atlas>,
    turn_id: String,
}
impl Drop for TurnGuard {
    fn drop(&mut self) {
        if let Ok(mut t) = self.atlas.turns.lock() {
            t.remove(&self.turn_id);
        }
    }
}

fn effort_hint(e: Effort) -> EffortHint {
    match e {
        Effort::Low => EffortHint::Low,
        Effort::Medium => EffortHint::Medium,
        Effort::High => EffortHint::High,
    }
}

impl Atlas {
    /// Cancel the running turn in a conversation. Returns whether one was running.
    pub fn cancel_conversation(&self, conversation_id: &str) -> bool {
        self.turns
            .lock()
            .map(|t| {
                let mut found = false;
                for a in t.values().filter(|a| a.conversation_id == conversation_id) {
                    a.cancel.cancel();
                    found = true;
                }
                found
            })
            .unwrap_or(false)
    }

    pub async fn send_message(&self, p: TurnParams, mut sink: TurnSink) -> Result<TurnSummary> {
        let text = p.text.trim().to_string();
        if !p.regenerate {
            if text.is_empty() {
                return Err(AtlasError::Validation("message is empty".into()));
            }
            if text.chars().count() > MAX_USER_MESSAGE_CHARS {
                return Err(AtlasError::Validation(format!("message is longer than {MAX_USER_MESSAGE_CHARS} characters")));
            }
        }
        let conv = conversations::get(&self.db, &p.conversation_id)?;
        let turn_id = new_id();
        let cancel = CancellationToken::new();
        let task_slot = Arc::new(Mutex::new(None));
        {
            let mut turns = self.turns.lock().map_err(|_| AtlasError::Internal("turns lock".into()))?;
            if turns.values().any(|a| a.conversation_id == conv.id) {
                return Err(AtlasError::Conflict("Atlas is already responding in this conversation".into()));
            }
            turns.insert(
                turn_id.clone(),
                ActiveTurn { conversation_id: conv.id.clone(), cancel: cancel.clone(), task_id: task_slot.clone(), started_at: crate::storage::now() },
            );
        }
        let _guard = TurnGuard { atlas: self.arc(), turn_id: turn_id.clone() };
        // Regenerate: done while this conversation's turn slot is held, so nothing else can
        // append in between.
        let (text, reuse) = if p.regenerate {
            let (t, id) = conversations::take_last_reply(&self.db, &conv.id)?;
            notify(&self.bus, Topic::Conversations, Some(&conv.id));
            (t, Some(id))
        } else {
            (text, None)
        };
        let result = self.run_turn(&turn_id, &conv, &text, &p, reuse, &cancel, &task_slot, &mut sink).await;
        match result {
            Ok(s) => {
                // Worth a notification only if the owner has looked away while Atlas worked.
                let (category, title) = match s.outcome.as_str() {
                    "completed" => (crate::desktop::Category::Reply, "Atlas has replied"),
                    "failed" => (crate::desktop::Category::Error, "Atlas could not finish a reply"),
                    _ => (crate::desktop::Category::Test, ""),
                };
                if !title.is_empty() {
                    self.raise_notification(crate::desktop::NewNotification {
                        category,
                        title,
                        detail: &conv.title,
                        target: &format!("conversation:{}", conv.id),
                        dedupe_key: &format!("turn:{}:{}", conv.id, s.outcome),
                        only_if_away: true,
                    });
                }
                Ok(s)
            }
            Err(e @ AtlasError::BudgetConfirmation(_)) => {
                // Nothing was sent or stored; the client asks the owner and may resend once.
                sink(TurnEvent::Finished { outcome: "needs_confirmation".into(), error: Some(e.to_string()), usage: Usage::default(), estimated_cost_usd: None, task_id: None });
                Err(e)
            }
            Err(e) => {
                // Errors before the loop starts (routing, limits, configuration).
                let msg = e.to_string();
                let _ = conversations::append(&self.db, &conv.id, "notice", &msg, None, None, None, None, "error", None, None);
                sink(TurnEvent::Notice { level: "error".into(), text: crate::redact::redact(&msg) });
                sink(TurnEvent::Finished { outcome: "failed".into(), error: Some(crate::redact::redact(&msg)), usage: Usage::default(), estimated_cost_usd: None, task_id: None });
                notify(&self.bus, Topic::Conversations, Some(&conv.id));
                Err(e)
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn run_turn(
        &self,
        turn_id: &str,
        conv: &conversations::Conversation,
        text: &str,
        p: &TurnParams,
        reuse_user_message: Option<String>,
        cancel: &CancellationToken,
        task_slot: &Arc<Mutex<Option<String>>>,
        sink: &mut TurnSink,
    ) -> Result<TurnSummary> {
        let settings = self.settings()?;
        let project = conv.project_id.as_deref().and_then(|id| crate::projects::get(&self.db, id).ok());
        let forge_scope = match &conv.forge_project_id {
            Some(fp) => Some(crate::forge::scope(&self.db, fp, conv.discipline.unwrap_or(crate::forge::Discipline::Builder))?),
            None => None,
        };
        // A Forge session linked to an open mission counts toward that mission's budget.
        let mission_id: Option<String> = p.mission_id.clone().or_else(|| {
            self.db.conn().ok().and_then(|c| {
                c.query_row(
                    "SELECT id FROM missions WHERE conversation_id = ?1 AND state NOT IN ('COMPLETED','FAILED','CANCELLED') ORDER BY updated_at DESC LIMIT 1",
                    [&conv.id],
                    |r| r.get(0),
                )
                .ok()
            })
        });
        let p = &TurnParams { mission_id, ..p.clone() };
        let all_providers = providers::list(&self.db)?;
        let mut signals = providers::RouteSignals::from_text(text);
        if let Some(fs) = &forge_scope {
            signals.forge = true;
            signals.deep_discipline = fs.discipline.is_deep();
            signals.engineering = true;
        }
        let route = providers::route_tiered(&settings, &all_providers, p.provider_id.as_deref(), p.model.as_deref(), &signals, true)?;
        let request_timeout = Duration::from_secs(settings.limits.request_timeout_secs as u64);
        let provider = self.factory.build(&route.provider, &self.secrets, Duration::from_secs(120).min(request_timeout))?;

        // Tools offered: enabled, available, not denied by policy, and only if the model can use them.
        let mut probe_ctx = self.tool_context(settings.clone(), None, conv.project_id.clone(), cancel.clone());
        probe_ctx.forge = forge_scope.clone();
        let tool_states = crate::tools::registry::stats(&self.db)?;
        let model_tools_ok = route.model_info.as_ref().and_then(|m| m.supports_tools) != Some(false);
        let mut specs: Vec<ToolSpec> = if model_tools_ok && settings.limits.max_tool_calls > 0 {
            self.registry
                .all()
                .into_iter()
                .filter(|t| {
                    let d = t.descriptor();
                    let in_session = match &forge_scope {
                        Some(fs) => fs.discipline.allows(&d.id),
                        None => d.category != "forge",
                    };
                    in_session
                        && tool_states.get(&d.id).map(|s| s.enabled).unwrap_or(true)
                        && t.availability(&probe_ctx) == Availability::Available
                        && !matches!(policy::decide(d.permission, d.network, &settings), Decision::Deny { .. })
                })
                .map(|t| {
                    let d = t.descriptor();
                    ToolSpec { name: crate::ai::wire_tool_name(&d.id), description: d.description.clone(), input_schema: d.input_schema.clone() }
                })
                .collect()
        } else {
            vec![]
        };

        // Tools offered this turn; anything else the model names is not executed.
        let offered: std::collections::HashSet<String> =
            specs.iter().filter_map(|sp| self.registry.id_for_wire(&sp.name)).collect();

        // Budgets: a worst-case projection of this request, checked before anything is stored.
        let max_tokens_projection = route
            .model_info
            .as_ref()
            .and_then(|m| m.max_output_tokens)
            .map(|m| (m as u32).min(settings.limits.max_output_tokens))
            .unwrap_or(settings.limits.max_output_tokens);
        let prior_chars: usize = conversations::messages(&self.db, &conv.id)?.iter().map(|m| m.content.len()).sum();
        let budget_chars = context::history_char_budget(route.model_info.as_ref().and_then(|m| m.context_window));
        let tool_chars: usize = specs.iter().map(|sp| sp.description.len() + sp.input_schema.to_string().len()).sum();
        let prompt_chars = prior_chars.min(budget_chars) + text.len() + tool_chars + 8000;
        let projection = usage::project(route.provider.kind, &route.model, &settings, prompt_chars, max_tokens_projection);
        let mut budget_warning: Option<String> = None;
        match usage::check_budget(&self.db, &settings, projection, p.mission_id.as_deref())? {
            usage::BudgetVerdict::Ok => {}
            usage::BudgetVerdict::Warn(m) => budget_warning = Some(m),
            usage::BudgetVerdict::Confirm(m) if p.budget_override => budget_warning = Some(format!("Sent with your confirmation: {m}")),
            usage::BudgetVerdict::Confirm(m) => return Err(AtlasError::BudgetConfirmation(format!("{m}. Send it anyway?"))),
            usage::BudgetVerdict::Stop(m) => return Err(AtlasError::BudgetExceeded(format!("{m}. Change limits in Settings → Usage & budgets."))),
        }

        // Relevant memories only (plus pinned), bounded.
        let mut mem_refs = Vec::new();
        let (retrieved, pinned) = if settings.memory.enabled && settings.memory.max_retrieved > 0 {
            let max = settings.memory.max_retrieved as usize;
            let pinned: Vec<_> = memory::pinned(&self.db, conv.project_id.as_deref())?.into_iter().take(max).collect();
            let mut r = memory::search(&self.db, text, conv.project_id.as_deref(), max as u32)?;
            r.retain(|x| !pinned.iter().any(|pm| pm.id == x.memory.id));
            r.truncate(max.saturating_sub(pinned.len()));
            (r, pinned)
        } else {
            (vec![], vec![])
        };
        for m in &pinned {
            mem_refs.push(MemoryRef { id: m.id.clone(), content: m.content.clone(), reason: "pinned".into() });
        }
        for r in &retrieved {
            mem_refs.push(MemoryRef { id: r.memory.id.clone(), content: r.memory.content.clone(), reason: r.reason.clone() });
        }
        memory::mark_used(&self.db, &mem_refs.iter().map(|m| m.id.clone()).collect::<Vec<_>>());

        let local_time = chrono::Local::now().format("%A %Y-%m-%d %H:%M (UTC%:z)").to_string();
        let block = context::context_block(&local_time, &retrieved, &pinned);
        let sent_text = format!("{block}{text}");
        let user_message_id = match reuse_user_message {
            // Regenerate: the stored message (with the context it was first sent with) is answered again.
            Some(id) => id,
            None => conversations::append(
                &self.db,
                &conv.id,
                "user",
                text,
                Some(&[Part::Text { text: sent_text }]),
                None,
                None,
                None,
                "complete",
                None,
                None,
            )?,
        };
        if conv.message_count == 0 && conv.title == "New conversation" {
            let title: String = text.lines().next().unwrap_or(text).chars().take(60).collect();
            let _ = conversations::rename(&self.db, &conv.id, &title);
        }
        notify(&self.bus, Topic::Conversations, Some(&conv.id));

        sink(TurnEvent::Started {
            turn_id: turn_id.into(),
            conversation_id: conv.id.clone(),
            user_message_id,
            provider_label: route.provider.label.clone(),
            provider_kind: route.provider.kind,
            model: route.model.clone(),
            local: route.provider.local,
            route_reason: route.reason.clone(),
            fell_back: route.fell_back,
            tier: route.tier,
            memories: mem_refs,
            tools_offered: specs.len(),
        });
        if route.fell_back {
            let _ = conversations::append(&self.db, &conv.id, "notice", &route.reason, None, None, None, None, "warning", None, None);
            sink(TurnEvent::Notice { level: "warn".into(), text: route.reason.clone() });
        }
        if let Some(w) = &budget_warning {
            sink(TurnEvent::Notice { level: "warn".into(), text: format!("Budget: {w}") });
        }

        let mut system = context::system_prompt(&settings, project.as_ref(), !specs.is_empty());
        if let Some(fs) = &forge_scope {
            let name = crate::forge::get_project(&self.db, &fs.project_id).map(|p| p.name).unwrap_or_default();
            system.push_str(&context::forge_section(&name, fs));
        }
        let rows = conversations::messages(&self.db, &conv.id)?;
        let history = conversations::to_history(&rows);
        let current_start = history.len().saturating_sub(1);
        let budget = context::history_char_budget(route.model_info.as_ref().and_then(|m| m.context_window));
        let (mut messages, truncated) = context::fit_history(history, budget, current_start);
        if truncated {
            sink(TurnEvent::Notice { level: "info".into(), text: "This conversation is long, so the oldest messages were left out of this request.".into() });
        }

        let max_tokens = route
            .model_info
            .as_ref()
            .and_then(|m| m.max_output_tokens)
            .map(|m| (m as u32).min(settings.limits.max_output_tokens))
            .unwrap_or(settings.limits.max_output_tokens);
        let effort = (route.model_info.as_ref().and_then(|m| m.supports_effort) == Some(true)).then(|| effort_hint(settings.companion.effort));
        let reasoning_summary =
            settings.companion.show_reasoning_summary && route.model_info.as_ref().and_then(|m| m.supports_reasoning) == Some(true);

        let mut task_id: Option<String> = None;
        let mut tool_calls_used = 0u32;
        let mut total = Usage { input_tokens: Some(0), output_tokens: Some(0) };
        let mut cost: Option<f64> = Some(0.0);
        let mut outcome = "completed".to_string();
        let mut error: Option<String> = None;
        let mut final_text = String::new();
        let mut step_statuses: Vec<String> = Vec::new();
        let mut tools_dropped = false;

        let max_steps = settings.limits.max_model_steps;
        'steps: for step in 0..max_steps {
            if cancel.is_cancelled() {
                outcome = "cancelled".into();
                break;
            }
            if step > 0 {
                let chars: usize = system.len() + messages.iter().map(|m| serde_json::to_string(&m.parts).map(|s| s.len()).unwrap_or(0)).sum::<usize>();
                let proj = usage::project(route.provider.kind, &route.model, &settings, chars, max_tokens);
                let verdict = usage::check_budget(&self.db, &settings, proj, p.mission_id.as_deref())?;
                let blocked = match verdict {
                    usage::BudgetVerdict::Stop(m) => Some(m),
                    usage::BudgetVerdict::Confirm(m) if !p.budget_override => Some(m),
                    _ => None,
                };
                if let Some(m) = blocked {
                    let msg = format!("Atlas paused this task before another model request: {m}. Raise the limit in Settings → Usage & budgets, or continue with a new message.");
                    let _ = conversations::append(&self.db, &conv.id, "notice", &msg, None, None, None, None, "warning", task_id.as_deref(), None);
                    sink(TurnEvent::Notice { level: "warn".into(), text: msg.clone() });
                    outcome = "stopped".into();
                    error = Some(msg);
                    break;
                }
            }
            let mut attempt = 0u32;
            let resp = loop {
                let req = ChatRequest {
                    model: route.model.clone(),
                    system: system.clone(),
                    messages: messages.clone(),
                    tools: specs.clone(),
                    max_tokens,
                    effort,
                    reasoning_summary,
                    refusal_fallback: settings.routing.anthropic_refusal_fallback && route.provider.kind == ProviderKind::Anthropic,
                };
                let started = Instant::now();
                let r = {
                    let mut ev = |e: StreamEvent| {
                        sink(match e {
                            StreamEvent::TextDelta { text } => TurnEvent::TextDelta { text },
                            StreamEvent::ReasoningDelta { text } => TurnEvent::ReasoningDelta { text },
                            StreamEvent::ToolCallStarted { id, name } => TurnEvent::ToolCallStarted { call_id: id, name },
                            StreamEvent::Notice { text } => TurnEvent::Notice { level: "info".into(), text },
                        })
                    };
                    match tokio::time::timeout(request_timeout, provider.stream_chat(req, &mut ev, cancel.clone())).await {
                        Ok(r) => r,
                        Err(_) => Err(ProviderError::new(ProviderErrorKind::Timeout, format!("no complete response within {}s", request_timeout.as_secs()))),
                    }
                };
                let elapsed = started.elapsed().as_millis();
                match r {
                    Ok(resp) => {
                        let c = usage::record_entry(
                            &self.db,
                            &settings,
                            usage::UsageEntry { provider_id: &route.provider.id, kind: route.provider.kind, model: &resp.served_model, usage: &resp.usage, duration_ms: elapsed, outcome: "ok", mission_id: p.mission_id.as_deref() },
                        );
                        cost = match (cost, c) {
                            (Some(a), Some(b)) => Some(a + b),
                            _ => None,
                        };
                        break Ok(resp);
                    }
                    Err(e) => {
                        let label = serde_json::to_value(e.kind).ok().and_then(|v| v.as_str().map(str::to_string)).unwrap_or_default();
                        if e.kind != ProviderErrorKind::Cancelled {
                            usage::record_entry(
                                &self.db,
                                &settings,
                                usage::UsageEntry { provider_id: &route.provider.id, kind: route.provider.kind, model: &route.model, usage: &Usage::default(), duration_ms: elapsed, outcome: &label, mission_id: p.mission_id.as_deref() },
                            );
                        }
                        if e.kind == ProviderErrorKind::Cancelled || cancel.is_cancelled() {
                            break Err(e);
                        }
                        if e.kind == ProviderErrorKind::BadRequest && !specs.is_empty() && !tools_dropped && e.message.to_lowercase().contains("tool") {
                            tools_dropped = true;
                            specs.clear();
                            let msg = "This model did not accept tools, so Atlas is continuing without them.".to_string();
                            sink(TurnEvent::StepReset { reason: msg.clone() });
                            sink(TurnEvent::Notice { level: "warn".into(), text: msg });
                            continue;
                        }
                        if e.retryable() && attempt < MAX_PROVIDER_RETRIES {
                            attempt += 1;
                            let wait = e.retry_after_secs.unwrap_or(2u64.pow(attempt)).min(20);
                            sink(TurnEvent::StepReset { reason: "retrying".into() });
                            sink(TurnEvent::Notice { level: "warn".into(), text: format!("{} Retrying in {wait}s (attempt {}/{}).", describe_provider_error(&e), attempt + 1, MAX_PROVIDER_RETRIES + 1) });
                            tokio::select! {
                                _ = cancel.cancelled() => break Err(ProviderError::new(ProviderErrorKind::Cancelled, "cancelled")),
                                _ = tokio::time::sleep(Duration::from_secs(wait)) => continue,
                            }
                        }
                        break Err(e);
                    }
                }
            };

            let resp = match resp {
                Err(e) if e.kind == ProviderErrorKind::Cancelled => {
                    outcome = "cancelled".into();
                    break;
                }
                Err(e) => {
                    providers::set_status(&self.db, &route.provider.id, ProviderStatus::from_error(&e), Some(&e.message));
                    notify(&self.bus, Topic::Providers, Some(&route.provider.id));
                    let msg = describe_provider_error(&e);
                    let _ = conversations::append(&self.db, &conv.id, "notice", &msg, None, None, Some(&route.provider.id), Some(&route.model), "error", task_id.as_deref(), None);
                    sink(TurnEvent::Notice { level: "error".into(), text: msg.clone() });
                    audit::record(&self.db, "provider.error", "error", task_id.as_deref(), None, json!({"provider_id": route.provider.id, "kind": e.kind, "status": e.status}));
                    outcome = "failed".into();
                    error = Some(msg);
                    break;
                }
                Ok(r) => r,
            };

            if route.provider.status != ProviderStatus::Connected {
                providers::set_status(&self.db, &route.provider.id, ProviderStatus::Connected, None);
                notify(&self.bus, Topic::Providers, Some(&route.provider.id));
            }
            total.input_tokens = total.input_tokens.zip(resp.usage.input_tokens).map(|(a, b)| a + b);
            total.output_tokens = total.output_tokens.zip(resp.usage.output_tokens).map(|(a, b)| a + b);
            for n in &resp.notices {
                let _ = conversations::append(&self.db, &conv.id, "notice", n, None, None, None, None, "info", None, None);
            }

            let calls = resp.message.tool_calls();
            let msg_text = resp.message.text();
            let status = match &resp.stop {
                StopReason::Refusal { .. } => "refused",
                StopReason::MaxTokens => "truncated",
                _ => "complete",
            };
            let message_id = conversations::append(
                &self.db,
                &conv.id,
                "assistant",
                &msg_text,
                Some(&resp.message.parts),
                resp.message.native.as_ref(),
                Some(&route.provider.id),
                Some(&resp.served_model),
                status,
                task_id.as_deref(),
                Some(&json!(resp.usage)),
            )?;
            sink(TurnEvent::AssistantMessage { message_id, stop: resp.stop.clone(), served_model: resp.served_model.clone() });
            messages.push(resp.message.clone());
            if !msg_text.trim().is_empty() {
                final_text = msg_text;
            }

            // Every tool call in history must get a result, executed or not.
            let not_executed = |reason: &str| -> Vec<Part> {
                calls.iter().map(|(id, _, _)| Part::ToolResult { call_id: id.clone(), content: format!("NOT EXECUTED: {reason}"), is_error: true }).collect()
            };
            let stop_reason_text = match &resp.stop {
                StopReason::Refusal { category } => Some(format!(
                    "The model declined this request{}. Any partial reply above is incomplete.",
                    category.as_ref().map(|c| format!(" (category: {c})")).unwrap_or_default()
                )),
                StopReason::MaxTokens => Some("The response reached the output length limit and was cut off.".to_string()),
                _ => None,
            };
            if let Some(reason) = stop_reason_text {
                if !calls.is_empty() {
                    let parts = not_executed("the response was cut off or declined");
                    let id = conversations::append(&self.db, &conv.id, "tool", "Tool calls were not executed.", Some(&parts), None, None, None, "complete", task_id.as_deref(), None)?;
                    sink(TurnEvent::ToolResults { message_id: id });
                }
                let _ = conversations::append(&self.db, &conv.id, "notice", &reason, None, None, None, None, "warning", None, None);
                sink(TurnEvent::Notice { level: "warn".into(), text: reason });
                outcome = "stopped".into();
                break;
            }
            if calls.is_empty() {
                break;
            }

            // Tool calls → task.
            let tid = match &task_id {
                Some(t) => t.clone(),
                None => {
                    let t = tasks::create(&self.db, Some(&conv.id), text)?;
                    tasks::transition(&self.db, &t, TaskStatus::Running)?;
                    if let Ok(mut g) = task_slot.lock() {
                        *g = Some(t.clone());
                    }
                    sink(TurnEvent::TaskUpdated { task_id: t.clone(), status: TaskStatus::Running });
                    notify(&self.bus, Topic::Tasks, Some(&t));
                    task_id = Some(t.clone());
                    t
                }
            };
            let mut results = Vec::new();
            let mut summary_lines = Vec::new();
            for (call_id, wire, input) in calls.iter() {
                let tool_id = self.registry.id_for_wire(wire).unwrap_or_else(|| wire.clone());
                if cancel.is_cancelled() {
                    results.push(Part::ToolResult { call_id: call_id.clone(), content: "NOT EXECUTED: the task was cancelled".into(), is_error: true });
                    summary_lines.push(format!("{tool_id}: cancelled"));
                    continue;
                }
                if tool_calls_used >= settings.limits.max_tool_calls {
                    results.push(Part::ToolResult { call_id: call_id.clone(), content: "NOT EXECUTED: the tool-call limit for this task was reached".into(), is_error: true });
                    summary_lines.push(format!("{tool_id}: skipped (limit)"));
                    continue;
                }
                if !offered.contains(&tool_id) {
                    let why = if forge_scope.is_some() { "that tool is not available in this Forge discipline" } else { "that tool was not offered in this conversation" };
                    results.push(Part::ToolResult { call_id: call_id.clone(), content: format!("NOT EXECUTED: {why}"), is_error: true });
                    summary_lines.push(format!("{tool_id}: not offered"));
                    audit::record(&self.db, "tool.not_offered", "warn", Some(&tid), Some(&tool_id), json!({}));
                    continue;
                }
                tool_calls_used += 1;
                let mut ctx = self.tool_context(settings.clone(), Some(tid.clone()), conv.project_id.clone(), cancel.clone());
                ctx.forge = forge_scope.clone();
                let r = {
                    let mut on_ev = |e: DispatchEvent| sink(TurnEvent::Tool { event: e });
                    self.dispatcher().run(&ctx, &tid, call_id, &tool_id, input.clone(), &mut on_ev).await
                };
                summary_lines.push(format!("{tool_id}: {}", r.status));
                step_statuses.push(r.status.clone());
                results.push(Part::ToolResult { call_id: call_id.clone(), content: r.content_for_model, is_error: r.is_error });
            }
            let id = conversations::append(&self.db, &conv.id, "tool", &summary_lines.join("\n"), Some(&results), None, None, None, "complete", Some(&tid), None)?;
            sink(TurnEvent::ToolResults { message_id: id });
            messages.push(ChatMessage { role: Role::User, parts: results, native: None });
            if cancel.is_cancelled() {
                outcome = "cancelled".into();
                break 'steps;
            }
            if step + 1 == max_steps {
                let msg = format!("Atlas stopped after {max_steps} model steps (the limit in Settings → Limits). The task may be incomplete.");
                let _ = conversations::append(&self.db, &conv.id, "notice", &msg, None, None, None, None, "warning", Some(&tid), None);
                sink(TurnEvent::Notice { level: "warn".into(), text: msg.clone() });
                outcome = "stopped".into();
                error = Some(msg);
            }
        }

        if outcome == "cancelled" {
            let _ = conversations::append(&self.db, &conv.id, "notice", "Stopped by you.", None, None, None, None, "info", task_id.as_deref(), None);
            sink(TurnEvent::Notice { level: "info".into(), text: "Stopped.".into() });
        }

        if let Some(tid) = &task_id {
            let count = |s: &str| step_statuses.iter().filter(|x| x.as_str() == s).count();
            let (ok, rejected) = (count("succeeded"), count("rejected"));
            let problems = step_statuses.len() - ok - rejected;
            let verification = json!({
                "steps": step_statuses.len(), "succeeded": ok, "rejected_by_user": rejected,
                "failed_or_denied": problems, "partial": ok > 0 && (problems + rejected) > 0,
                "note": "Each step's output was validated against its schema; file writes were re-read and compared.",
            });
            let final_status = if outcome == "cancelled" {
                TaskStatus::Cancelled
            } else {
                let _ = tasks::transition(&self.db, tid, TaskStatus::Verifying);
                if ok == 0 && problems > 0 || outcome == "failed" && ok == 0 { TaskStatus::Failed } else { TaskStatus::Completed }
            };
            let summary = (!final_text.is_empty()).then(|| crate::ai::truncate(&final_text, 400));
            let _ = tasks::finish(&self.db, tid, final_status, summary.as_deref(), error.as_deref(), Some(&verification));
            sink(TurnEvent::TaskUpdated { task_id: tid.clone(), status: final_status });
            notify(&self.bus, Topic::Tasks, Some(tid));
        }
        notify(&self.bus, Topic::Conversations, Some(&conv.id));
        notify(&self.bus, Topic::Usage, None);
        sink(TurnEvent::Finished { outcome: outcome.clone(), error: error.clone(), usage: total, estimated_cost_usd: cost, task_id: task_id.clone() });
        Ok(TurnSummary { turn_id: turn_id.into(), outcome, task_id, error })
    }
}
