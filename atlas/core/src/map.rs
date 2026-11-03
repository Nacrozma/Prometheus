//! Atlas Map graph, generated entirely from live state: the tool registry, provider configs,
//! integrations, memory, projects and recent task executions. Nothing here is decorative.

use crate::app::Atlas;
use crate::error::Result;
use crate::tasks::{self, TaskStatus};
use crate::tools::{Availability, PermissionClass};
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::BTreeSet;

#[derive(Debug, Clone, Serialize)]
pub struct Node {
    pub id: String,
    pub label: String,
    pub kind: String,
    /// ok | warning | error | idle | disabled | active
    pub status: String,
    pub status_label: String,
    pub category: String,
    pub permission: Option<PermissionClass>,
    pub capabilities: Vec<String>,
    pub details: Value,
    pub active: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct Edge {
    pub id: String,
    pub source: String,
    pub target: String,
    pub kind: String,
    pub active: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct Graph {
    pub nodes: Vec<Node>,
    pub edges: Vec<Edge>,
    pub generated_at: String,
}

fn edge(source: &str, target: &str, kind: &str, active: bool) -> Edge {
    Edge { id: format!("{source}->{target}:{kind}"), source: source.into(), target: target.into(), kind: kind.into(), active }
}

/// Window in which finished tasks still appear on the map.
const RECENT_TASK_MINUTES: i64 = 30;

impl Atlas {
    pub fn map_graph(&self) -> Result<Graph> {
        let settings = self.settings()?;
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        let active_turns = self.active_turns().len();
        nodes.push(Node {
            id: "core".into(),
            label: "Atlas Core".into(),
            kind: "core".into(),
            status: if active_turns > 0 { "active".into() } else { "ok".into() },
            status_label: if active_turns > 0 { format!("{active_turns} active") } else { "Ready".into() },
            category: "core".into(),
            permission: None,
            capabilities: vec!["orchestration".into(), "permissions".into(), "approvals".into()],
            details: json!({"version": self.version, "offline_mode": settings.network.offline_mode}),
            active: active_turns > 0,
        });

        // Providers and models.
        for p in self.providers()? {
            let pid = format!("provider:{}", p.id);
            let (status, label) = match p.status {
                crate::providers::ProviderStatus::Connected => ("ok", "Connected"),
                crate::providers::ProviderStatus::Untested => ("idle", "Not tested yet"),
                crate::providers::ProviderStatus::NotConfigured => ("warning", "Needs an API key"),
                crate::providers::ProviderStatus::AuthFailed => ("error", "Key rejected"),
                crate::providers::ProviderStatus::RateLimited => ("warning", "Rate limited"),
                crate::providers::ProviderStatus::Unavailable => ("error", "Unreachable"),
                crate::providers::ProviderStatus::Degraded => ("warning", "Degraded"),
            };
            let (status, label) = if p.enabled { (status, label) } else { ("disabled", "Disabled") };
            nodes.push(Node {
                id: pid.clone(),
                label: p.label.clone(),
                kind: "provider".into(),
                status: status.into(),
                status_label: label.into(),
                category: if p.local { "local".into() } else { "cloud".into() },
                permission: None,
                capabilities: vec!["chat".into(), "streaming".into(), "tool_calling".into()],
                details: json!({"provider_id": p.id, "kind": p.kind, "base_url": p.base_url, "default_model": p.default_model,
                    "is_default": settings.default_provider_id.as_deref() == Some(&p.id), "last_checked_at": p.last_checked_at,
                    "status_detail": p.status_detail, "models_known": p.models.len()}),
                active: false,
            });
            edges.push(edge("core", &pid, "routes_to", false));
            // Show the default model plus a few others; the inspector lists the rest.
            let mut shown: BTreeSet<String> = BTreeSet::new();
            if let Some(m) = &p.default_model {
                shown.insert(m.clone());
            }
            for m in p.models.iter().take(4) {
                shown.insert(m.id.clone());
            }
            for mid in shown {
                let info = p.models.iter().find(|m| m.id == mid);
                let id = format!("model:{}:{}", p.id, mid);
                let mut caps = vec!["chat".to_string()];
                if let Some(i) = info {
                    if i.supports_tools == Some(true) { caps.push("tools".into()); }
                    if i.supports_vision == Some(true) { caps.push("vision".into()); }
                    if i.supports_reasoning == Some(true) { caps.push("reasoning".into()); }
                }
                nodes.push(Node {
                    id: id.clone(),
                    label: info.map(|i| i.display_name.clone()).unwrap_or_else(|| mid.clone()),
                    kind: "model".into(),
                    status: if p.default_model.as_deref() == Some(&mid) { "ok".into() } else { "idle".into() },
                    status_label: if p.default_model.as_deref() == Some(&mid) { "Default".into() } else { "Available".into() },
                    category: "model".into(),
                    permission: None,
                    capabilities: caps,
                    details: json!({"model_id": mid, "context_window": info.and_then(|i| i.context_window), "max_output_tokens": info.and_then(|i| i.max_output_tokens)}),
                    active: false,
                });
                edges.push(edge(&pid, &id, "serves", false));
            }
        }

        // Tool groups and tools (from the registry).
        let tools = self.tools()?;
        let mut categories: BTreeSet<String> = BTreeSet::new();
        for t in &tools {
            categories.insert(t.descriptor.category.clone());
        }
        for c in &categories {
            let n = tools.iter().filter(|t| &t.descriptor.category == c).count();
            nodes.push(Node {
                id: format!("group:{c}"),
                label: titlecase(c),
                kind: "group".into(),
                status: "ok".into(),
                status_label: format!("{n} tools"),
                category: c.clone(),
                permission: None,
                capabilities: vec![],
                details: json!({"tools": n}),
                active: false,
            });
            edges.push(edge("core", &format!("group:{c}"), "orchestrates", false));
        }

        // Recent/active task steps drive "active" paths.
        let cutoff = (chrono::Utc::now() - chrono::Duration::minutes(RECENT_TASK_MINUTES)).to_rfc3339();
        let recent: Vec<tasks::Task> = tasks::list(&self.db, None, 30)?
            .into_iter()
            .filter(|t| t.status.is_active() || t.updated_at > cutoff)
            .take(8)
            .collect();
        let mut active_tools: BTreeSet<String> = BTreeSet::new();

        for t in &tools {
            let d = &t.descriptor;
            let tid = format!("tool:{}", d.id);
            let (status, label) = if !t.enabled {
                ("disabled", "Disabled".to_string())
            } else {
                match &t.availability {
                    Availability::Available => ("ok", "Available".to_string()),
                    Availability::NeedsConfiguration { reason } => ("warning", reason.clone()),
                    Availability::Unavailable { reason } => ("error", reason.clone()),
                }
            };
            nodes.push(Node {
                id: tid.clone(),
                label: d.name.clone(),
                kind: "tool".into(),
                status: status.into(),
                status_label: label,
                category: d.category.clone(),
                permission: Some(d.permission),
                capabilities: vec![if d.network { "network".into() } else { "offline".into() }],
                details: json!({"tool_id": d.id, "description": d.description, "version": d.version, "data_scope": d.data_scope,
                    "timeout_secs": d.timeout_secs, "use_count": t.use_count, "failure_count": t.failure_count, "last_used_at": t.last_used_at,
                    "requires": d.requires}),
                active: false,
            });
            edges.push(edge(&format!("group:{}", d.category), &tid, "contains", false));
            for r in &d.requires {
                edges.push(edge(&tid, &format!("integration:{r}"), "requires", false));
            }
            if d.category == "memory" {
                edges.push(edge(&tid, "memory", "uses", false));
            }
            if d.category == "files" || d.category == "documents" || d.category == "data" {
                edges.push(edge(&tid, "workspace", "uses", false));
            }
        }

        for task in &recent {
            let id = format!("task:{}", task.id);
            let active = task.status.is_active();
            nodes.push(Node {
                id: id.clone(),
                label: crate::ai::truncate(&task.request, 40),
                kind: "task".into(),
                status: match task.status {
                    TaskStatus::Completed => "ok",
                    TaskStatus::Failed | TaskStatus::Interrupted => "error",
                    TaskStatus::AwaitingApproval => "warning",
                    TaskStatus::Cancelled => "disabled",
                    _ => "active",
                }
                .into(),
                status_label: task.status.as_str().replace('_', " "),
                category: "task".into(),
                permission: None,
                capabilities: vec![],
                details: json!({"task_id": task.id, "steps": task.step_count, "created_at": task.created_at}),
                active,
            });
            edges.push(edge("core", &id, "runs", active));
            let mut seen = BTreeSet::new();
            for s in tasks::steps(&self.db, &task.id)? {
                if !seen.insert(s.tool_id.clone()) {
                    continue;
                }
                let step_active = active && matches!(s.status.as_str(), "running" | "awaiting_approval" | "pending");
                if step_active {
                    active_tools.insert(s.tool_id.clone());
                }
                if self.registry.get(&s.tool_id).is_some() {
                    edges.push(edge(&id, &format!("tool:{}", s.tool_id), "invoked", step_active));
                }
            }
        }
        for n in nodes.iter_mut() {
            if n.kind == "tool" && active_tools.contains(n.id.trim_start_matches("tool:")) {
                n.active = true;
                n.status = "active".into();
                n.status_label = "Running now".into();
            }
        }

        // Integrations with real adapters.
        for i in self.integrations()?.into_iter().filter(|i| i.catalog.implemented) {
            let (status, label) = match (i.enabled, i.status.as_str()) {
                (_, "auth_failed") => ("error", "Key rejected"),
                (true, "connected") => ("ok", "Connected"),
                (true, _) if i.has_credential => ("idle", "Configured, not tested"),
                (false, _) if i.has_credential => ("disabled", "Disabled"),
                _ => ("warning", "Not configured"),
            };
            nodes.push(Node {
                id: format!("integration:{}", i.catalog.id),
                label: i.catalog.name.into(),
                kind: "integration".into(),
                status: status.into(),
                status_label: label.into(),
                category: i.catalog.category.to_lowercase(),
                permission: None,
                capabilities: i.catalog.capabilities.iter().map(|c| c.to_string()).collect(),
                details: json!({"integration_id": i.catalog.id, "permission_scope": i.catalog.permission_scope, "last_checked_at": i.last_checked_at}),
                active: false,
            });
        }

        // Memory, workspace, storage.
        let mem_count: i64 = self.db.conn()?.query_row("SELECT count(*) FROM memories", [], |r| r.get(0))?;
        nodes.push(Node {
            id: "memory".into(),
            label: "Memory".into(),
            kind: "memory".into(),
            status: if settings.memory.enabled { "ok".into() } else { "disabled".into() },
            status_label: if settings.memory.enabled { format!("{mem_count} memories") } else { "Turned off".into() },
            category: "memory".into(),
            permission: None,
            capabilities: vec!["retrieval".into()],
            details: json!({"count": mem_count, "enabled": settings.memory.enabled}),
            active: false,
        });
        edges.push(edge("core", "memory", "remembers", false));
        nodes.push(Node {
            id: "workspace".into(),
            label: "Workspace".into(),
            kind: "storage".into(),
            status: if settings.workspace_dir.is_some() { "ok".into() } else { "warning".into() },
            status_label: if settings.workspace_dir.is_some() { "Folder selected".into() } else { "No folder chosen".into() },
            category: "storage".into(),
            permission: None,
            capabilities: vec![],
            details: json!({"path": settings.workspace_dir}),
            active: false,
        });
        nodes.push(Node {
            id: "storage".into(),
            label: "Local database".into(),
            kind: "storage".into(),
            status: "ok".into(),
            status_label: format!("Schema v{}", self.db.schema_version().unwrap_or(0)),
            category: "storage".into(),
            permission: None,
            capabilities: vec![],
            details: json!({"size_bytes": self.db.size_bytes()}),
            active: false,
        });
        edges.push(edge("core", "storage", "persists", false));

        for p in self.projects(false)? {
            let id = format!("project:{}", p.id);
            nodes.push(Node {
                id: id.clone(),
                label: p.name.clone(),
                kind: "project".into(),
                status: "idle".into(),
                status_label: format!("{} chats · {} memories", p.conversation_count, p.memory_count),
                category: "project".into(),
                permission: None,
                capabilities: vec![],
                details: json!({"project_id": p.id, "description": p.description}),
                active: false,
            });
            edges.push(edge("core", &id, "scopes", false));
            if p.memory_count > 0 {
                edges.push(edge("memory", &id, "belongs_to", false));
            }
        }

        // Drop edges whose endpoints are missing (e.g. a removed integration).
        let ids: BTreeSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();
        let edges = edges.into_iter().filter(|e| ids.contains(e.source.as_str()) && ids.contains(e.target.as_str())).collect();
        Ok(Graph { nodes, edges, generated_at: crate::storage::now() })
    }
}

fn titlecase(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}
