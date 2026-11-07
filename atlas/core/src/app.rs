//! `Atlas`: the trusted core's public surface. The desktop shell calls only these methods.

use crate::ai::catalog;
use crate::approvals::{self, Broker};
use crate::credentials::SharedSecrets;
use crate::error::{AtlasError, Result};
use crate::events::{notify, SharedBus, Topic};
use crate::providers::{self, DefaultFactory, ProviderConfig, ProviderFactory, ProviderStatus};
use crate::settings::Settings;
use crate::storage::Db;
use crate::tasks::{self, TaskStatus};
use crate::tools::dispatch::Dispatcher;
use crate::tools::registry::{self, ToolInfo, ToolRegistry};
use crate::tools::{ToolContext, ToolServices};
use crate::{audit, conversations, grants, integrations, memory, projects, usage};
use async_trait::async_trait;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, Weak};
use std::time::Duration;
use tokio_util::sync::CancellationToken;

pub struct AtlasConfig {
    /// None = in-memory database (tests).
    pub db_path: Option<PathBuf>,
    pub secrets: SharedSecrets,
    pub bus: SharedBus,
    pub factory: Option<Arc<dyn ProviderFactory>>,
    pub version: String,
    pub data_dir: Option<PathBuf>,
}

pub(crate) struct ActiveTurn {
    pub conversation_id: String,
    pub cancel: CancellationToken,
    pub task_id: Arc<Mutex<Option<String>>>,
    pub started_at: String,
}

pub struct Atlas {
    pub db: Arc<Db>,
    pub secrets: SharedSecrets,
    pub bus: SharedBus,
    pub registry: Arc<ToolRegistry>,
    pub broker: Arc<Broker>,
    pub factory: Arc<dyn ProviderFactory>,
    pub http: reqwest::Client,
    pub version: String,
    pub data_dir: Option<PathBuf>,
    pub(crate) turns: Mutex<HashMap<String, ActiveTurn>>,
    pub(crate) me: Weak<Atlas>,
    pub(crate) recovered_tasks: usize,
    pub(crate) forge_cancels: Mutex<HashMap<String, CancellationToken>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProviderTestResult {
    pub provider: ProviderConfig,
    pub ok: bool,
    pub message: String,
}

impl Atlas {
    pub fn new(cfg: AtlasConfig) -> Result<Arc<Atlas>> {
        let db = Arc::new(match &cfg.db_path {
            Some(p) => Db::open(p)?,
            None => Db::open_in_memory()?,
        });
        let registry = Arc::new(ToolRegistry::default());
        crate::tools::builtin::register_all(&registry)?;
        let recovered = tasks::recover_after_restart(&db)?;
        if recovered > 0 {
            audit::record(&db, "tasks.recovered", "warn", None, None, json!({"interrupted": recovered}));
        }
        let runs = crate::forge::recover_runs(&db)?;
        if runs > 0 {
            audit::record(&db, "forge.runs_interrupted", "warn", None, None, json!({"interrupted": runs}));
        }
        let settings = Settings::load(&db)?;
        if let Some(days) = settings.retention.conversation_days {
            let _ = conversations::apply_retention(&db, days);
        }
        if let Some(days) = settings.retention.audit_days {
            let cutoff = (chrono::Utc::now() - chrono::Duration::days(days as i64)).to_rfc3339();
            let _ = db.conn()?.execute("DELETE FROM audit_events WHERE ts < ?1", [cutoff]);
        }
        let http = providers::http_client();
        let factory = cfg.factory.unwrap_or_else(|| Arc::new(DefaultFactory { http: http.clone() }));
        audit::record(&db, "app.start", "info", None, None, json!({"version": cfg.version}));
        Ok(Arc::new_cyclic(|me| Atlas {
            db,
            secrets: cfg.secrets,
            bus: cfg.bus,
            registry,
            broker: Arc::new(Broker::default()),
            factory,
            http,
            version: cfg.version,
            data_dir: cfg.data_dir,
            turns: Mutex::new(HashMap::new()),
            forge_cancels: Mutex::new(HashMap::new()),
            me: me.clone(),
            recovered_tasks: recovered,
        }))
    }

    pub(crate) fn arc(&self) -> Arc<Atlas> {
        self.me.upgrade().expect("Atlas is alive while its methods run")
    }

    pub fn dispatcher(&self) -> Dispatcher {
        Dispatcher { registry: self.registry.clone(), db: self.db.clone(), broker: self.broker.clone(), bus: self.bus.clone() }
    }

    pub fn tool_context(&self, settings: Settings, task_id: Option<String>, project_id: Option<String>, cancel: CancellationToken) -> ToolContext {
        ToolContext {
            db: self.db.clone(),
            secrets: self.secrets.clone(),
            http: self.http.clone(),
            workspace: settings.workspace_dir.as_ref().map(PathBuf::from),
            settings,
            task_id,
            project_id,
            cancel,
            services: self.arc(),
            forge: None,
        }
    }

    // ---------- settings ----------
    pub fn settings(&self) -> Result<Settings> {
        Settings::load(&self.db)
    }

    pub fn update_settings(&self, new: Settings) -> Result<Settings> {
        if let Some(ws) = &new.workspace_dir {
            let p = Path::new(ws);
            if !p.is_absolute() || !p.is_dir() {
                return Err(AtlasError::Validation("the workspace folder must be an existing folder".into()));
            }
        }
        if let Some(pid) = &new.default_provider_id {
            providers::get(&self.db, pid)?;
        }
        new.save(&self.db)?;
        audit::record(&self.db, "settings.updated", "info", None, None, json!({}));
        notify(&self.bus, Topic::Settings, None);
        notify(&self.bus, Topic::Registry, None);
        Ok(new)
    }

    /// Create (if needed) and select a default workspace folder.
    pub fn ensure_workspace(&self, path: &Path) -> Result<Settings> {
        std::fs::create_dir_all(path)?;
        let mut s = self.settings()?;
        s.workspace_dir = Some(path.canonicalize()?.to_string_lossy().to_string());
        self.update_settings(s)
    }

    // ---------- providers ----------
    pub fn providers(&self) -> Result<Vec<ProviderConfig>> {
        providers::list(&self.db)
    }

    pub fn provider_templates(&self) -> Vec<catalog::ProviderTemplate> {
        catalog::templates()
    }

    pub fn add_provider(&self, kind: crate::ai::ProviderKind, label: &str, base_url: &str, default_model: Option<&str>) -> Result<ProviderConfig> {
        let p = providers::create(&self.db, kind, label, base_url, default_model)?;
        let mut s = self.settings()?;
        if s.default_provider_id.is_none() {
            s.default_provider_id = Some(p.id.clone());
            s.save(&self.db)?;
            notify(&self.bus, Topic::Settings, None);
        }
        audit::record(&self.db, "provider.added", "info", None, None, json!({"provider_id": p.id, "kind": p.kind}));
        notify(&self.bus, Topic::Providers, Some(&p.id));
        Ok(p)
    }

    pub fn update_provider(&self, id: &str, label: &str, base_url: &str, default_model: Option<&str>, enabled: bool) -> Result<ProviderConfig> {
        let p = providers::update(&self.db, id, label, base_url, default_model, enabled)?;
        notify(&self.bus, Topic::Providers, Some(id));
        Ok(p)
    }

    pub fn delete_provider(&self, id: &str) -> Result<()> {
        providers::delete(&self.db, &self.secrets, id)?;
        let mut s = self.settings()?;
        if s.default_provider_id.as_deref() == Some(id) {
            s.default_provider_id = self.providers()?.first().map(|p| p.id.clone());
            s.save(&self.db)?;
        }
        audit::record(&self.db, "provider.deleted", "info", None, None, json!({"provider_id": id}));
        notify(&self.bus, Topic::Providers, Some(id));
        notify(&self.bus, Topic::Settings, None);
        Ok(())
    }

    pub fn set_provider_key(&self, id: &str, key: &str) -> Result<ProviderConfig> {
        let p = providers::set_key(&self.db, &self.secrets, id, key)?;
        audit::record(&self.db, "credential.stored", "info", None, None, json!({"provider_id": id}));
        notify(&self.bus, Topic::Providers, Some(id));
        Ok(p)
    }

    pub fn clear_provider_key(&self, id: &str) -> Result<ProviderConfig> {
        let p = providers::clear_key(&self.db, &self.secrets, id)?;
        audit::record(&self.db, "credential.removed", "info", None, None, json!({"provider_id": id}));
        notify(&self.bus, Topic::Providers, Some(id));
        Ok(p)
    }

    /// Test a provider by listing its models. Updates status honestly either way.
    pub async fn test_provider(&self, id: &str) -> Result<ProviderTestResult> {
        let cfg = providers::get(&self.db, id)?;
        if self.settings()?.network.offline_mode && !cfg.local {
            return Ok(ProviderTestResult { provider: cfg, ok: false, message: "offline mode is on; cloud providers are not contacted".into() });
        }
        let provider = match self.factory.build(&cfg, &self.secrets, Duration::from_secs(30)) {
            Ok(p) => p,
            Err(e) => {
                let msg = e.to_string();
                return Ok(ProviderTestResult { provider: providers::get(&self.db, id)?, ok: false, message: msg });
            }
        };
        let (ok, message) = match provider.list_models().await {
            Ok(models) => {
                providers::save_models(&self.db, id, &models)?;
                providers::set_status(&self.db, id, ProviderStatus::Connected, None);
                (true, format!("Connected. {} models available.", models.len()))
            }
            Err(e) => {
                providers::set_status(&self.db, id, ProviderStatus::from_error(&e), Some(&e.message));
                (false, describe_provider_error(&e))
            }
        };
        audit::record(&self.db, "provider.tested", if ok { "info" } else { "warn" }, None, None, json!({"provider_id": id, "ok": ok}));
        notify(&self.bus, Topic::Providers, Some(id));
        Ok(ProviderTestResult { provider: providers::get(&self.db, id)?, ok, message })
    }

    // ---------- integrations ----------
    pub fn integrations(&self) -> Result<Vec<integrations::Integration>> {
        integrations::list(&self.db)
    }

    pub fn set_integration_key(&self, id: &str, key: &str) -> Result<integrations::Integration> {
        let i = integrations::set_key(&self.db, &self.secrets, id, key)?;
        audit::record(&self.db, "credential.stored", "info", None, None, json!({"integration": id}));
        notify(&self.bus, Topic::Registry, Some(id));
        Ok(i)
    }

    pub fn clear_integration_key(&self, id: &str) -> Result<integrations::Integration> {
        let i = integrations::clear_key(&self.db, &self.secrets, id)?;
        audit::record(&self.db, "credential.removed", "info", None, None, json!({"integration": id}));
        notify(&self.bus, Topic::Registry, Some(id));
        Ok(i)
    }

    pub fn set_integration_enabled(&self, id: &str, enabled: bool) -> Result<integrations::Integration> {
        let i = integrations::set_enabled(&self.db, id, enabled)?;
        notify(&self.bus, Topic::Registry, Some(id));
        Ok(i)
    }

    /// Test an integration with one real call. For web search this costs one search credit,
    /// which the UI states before the user clicks.
    pub async fn test_integration(&self, id: &str) -> Result<integrations::Integration> {
        if id != crate::tools::builtin::web::INTEGRATION_ID {
            return Err(AtlasError::Validation("this integration has no test".into()));
        }
        let settings = self.settings()?;
        let mut s = settings.clone();
        // A test is an explicit user action; it bypasses the tool approval prompt but not offline mode.
        s.permissions.network_tools = crate::settings::GatePolicy::Allow;
        if settings.network.offline_mode {
            integrations::set_status(&self.db, id, "unavailable", Some("offline mode is on"))?;
            return integrations::get(&self.db, id);
        }
        let ctx = self.tool_context(s, None, None, CancellationToken::new());
        let tool = self.registry.get("web.search").ok_or_else(|| AtlasError::NotFound("web.search".into()))?;
        let res = tool.execute(json!({"query": "ATLAS connection test", "max_results": 1}), &ctx).await;
        match res {
            Ok(_) => integrations::set_status(&self.db, id, "connected", None)?,
            Err(e) => integrations::set_status(&self.db, id, if e.message.contains("401") { "auth_failed" } else { "unavailable" }, Some(&e.message))?,
        }
        notify(&self.bus, Topic::Registry, Some(id));
        integrations::get(&self.db, id)
    }

    // ---------- tools ----------
    pub fn tools(&self) -> Result<Vec<ToolInfo>> {
        let ctx = self.tool_context(self.settings()?, None, None, CancellationToken::new());
        self.registry.info(&self.db, &ctx)
    }

    pub fn set_tool_enabled(&self, id: &str, enabled: bool) -> Result<()> {
        if self.registry.get(id).is_none() {
            return Err(AtlasError::NotFound(format!("tool '{id}'")));
        }
        registry::set_enabled(&self.db, id, enabled)?;
        audit::record(&self.db, "tool.toggled", "info", None, Some(id), json!({"enabled": enabled}));
        notify(&self.bus, Topic::Registry, Some(id));
        Ok(())
    }

    // ---------- approvals & tasks ----------
    pub fn pending_approvals(&self) -> Result<Vec<approvals::Approval>> {
        approvals::list_pending(&self.db)
    }

    pub fn decide_approval(&self, id: &str, approve: bool) -> Result<()> {
        self.broker.resolve(&self.db, id, approve)?;
        audit::record(&self.db, if approve { "approval.approved" } else { "approval.rejected" }, "info", None, None, json!({"approval_id": id}));
        notify(&self.bus, Topic::Approvals, Some(id));
        Ok(())
    }

    pub fn tasks(&self, status: Option<&str>, limit: u32) -> Result<Vec<tasks::Task>> {
        tasks::list(&self.db, status, limit.min(500))
    }

    pub fn task_detail(&self, id: &str) -> Result<tasks::TaskDetail> {
        tasks::detail(&self.db, id)
    }

    /// Cancel the running turn that owns `task_id`, if any.
    pub fn cancel_task(&self, task_id: &str) -> Result<bool> {
        let turns = self.turns.lock().map_err(|_| AtlasError::Internal("turns lock".into()))?;
        for t in turns.values() {
            if t.task_id.lock().ok().and_then(|g| g.clone()).as_deref() == Some(task_id) {
                t.cancel.cancel();
                return Ok(true);
            }
        }
        Ok(false)
    }

    /// Interrupted tasks are never resumed automatically. The user may dismiss them.
    pub fn dismiss_task(&self, task_id: &str) -> Result<()> {
        let st = tasks::status(&self.db, task_id)?;
        if st != TaskStatus::Interrupted && st != TaskStatus::Recoverable {
            return Err(AtlasError::Conflict("only interrupted tasks can be dismissed".into()));
        }
        tasks::finish(&self.db, task_id, TaskStatus::Cancelled, None, Some("dismissed by the user after interruption"), None)?;
        notify(&self.bus, Topic::Tasks, Some(task_id));
        Ok(())
    }

    /// Retry a failed step — only for read-only, offline tools. Anything that writes or sends is
    /// never replayed; the user asks Atlas again instead, which goes through approval anew.
    pub async fn retry_step(&self, step_id: &str) -> Result<Value> {
        let (task_id, tool_id, status): (String, String, String) = self.db.conn()?.query_row(
            "SELECT task_id, tool_id, status FROM task_steps WHERE id = ?1",
            [step_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        let tool = self.registry.get(&tool_id).ok_or_else(|| AtlasError::NotFound("tool".into()))?;
        let d = tool.descriptor();
        if d.permission != crate::tools::PermissionClass::ReadOnly || d.network {
            return Err(AtlasError::PermissionDenied("only read-only, offline steps can be retried; ask Atlas again for anything else".into()));
        }
        if !matches!(status.as_str(), "failed" | "cancelled") {
            return Err(AtlasError::Conflict("only failed or cancelled steps can be retried".into()));
        }
        let step = tasks::steps(&self.db, &task_id)?.into_iter().find(|s| s.id == step_id).ok_or_else(|| AtlasError::NotFound("step".into()))?;
        let ctx = self.tool_context(self.settings()?, Some(task_id.clone()), None, CancellationToken::new());
        let mut sink = |_e: crate::tools::dispatch::DispatchEvent| {};
        let r = self.dispatcher().run(&ctx, &task_id, "retry", &tool_id, step.input, &mut sink).await;
        Ok(serde_json::to_value(r)?)
    }

    /// Emergency stop: cancel every running turn and expire every pending approval.
    pub fn emergency_stop(&self) -> Result<usize> {
        let n = {
            let turns = self.turns.lock().map_err(|_| AtlasError::Internal("turns lock".into()))?;
            for t in turns.values() {
                t.cancel.cancel();
            }
            turns.len()
        };
        approvals::expire_all_pending(&self.db)?;
        audit::record(&self.db, "emergency_stop", "warn", None, None, json!({"turns": n}));
        notify(&self.bus, Topic::Approvals, None);
        notify(&self.bus, Topic::Tasks, None);
        Ok(n)
    }

    pub fn active_turns(&self) -> Vec<Value> {
        self.turns
            .lock()
            .map(|t| {
                t.iter()
                    .map(|(id, a)| json!({"turn_id": id, "conversation_id": a.conversation_id, "started_at": a.started_at,
                        "task_id": a.task_id.lock().ok().and_then(|g| g.clone())}))
                    .collect()
            })
            .unwrap_or_default()
    }

    // ---------- memory ----------
    pub fn memories(&self, project: Option<Option<&str>>) -> Result<Vec<memory::Memory>> {
        memory::list(&self.db, project)
    }
    pub fn create_memory(&self, project_id: Option<&str>, kind: memory::MemoryKind, content: &str, pinned: bool) -> Result<memory::Memory> {
        let m = memory::create(&self.db, project_id, kind, content, "user", pinned)?;
        notify(&self.bus, Topic::Memory, Some(&m.id));
        Ok(m)
    }
    pub fn update_memory(&self, id: &str, content: Option<&str>, kind: Option<memory::MemoryKind>, pinned: Option<bool>, project_id: Option<Option<&str>>) -> Result<memory::Memory> {
        let m = memory::update(&self.db, id, content, kind, pinned, project_id)?;
        notify(&self.bus, Topic::Memory, Some(id));
        Ok(m)
    }
    pub fn delete_memory(&self, id: &str) -> Result<()> {
        memory::delete(&self.db, id)?;
        audit::record(&self.db, "memory.deleted", "info", None, None, json!({}));
        notify(&self.bus, Topic::Memory, Some(id));
        Ok(())
    }
    pub fn delete_all_memories(&self) -> Result<usize> {
        let n = memory::delete_all(&self.db)?;
        audit::record(&self.db, "memory.deleted_all", "warn", None, None, json!({"count": n}));
        notify(&self.bus, Topic::Memory, None);
        Ok(n)
    }
    pub fn search_memories(&self, q: &str, project_id: Option<&str>) -> Result<Vec<memory::Retrieved>> {
        memory::search(&self.db, q, project_id, 20)
    }

    // ---------- projects ----------
    pub fn projects(&self, include_archived: bool) -> Result<Vec<projects::Project>> {
        projects::list(&self.db, include_archived)
    }
    pub fn create_project(&self, name: &str, description: &str, instructions: &str) -> Result<projects::Project> {
        let p = projects::create(&self.db, name, description, instructions)?;
        notify(&self.bus, Topic::Projects, Some(&p.id));
        Ok(p)
    }
    pub fn update_project(&self, id: &str, name: &str, description: &str, instructions: &str, archived: bool) -> Result<projects::Project> {
        let p = projects::update(&self.db, id, name, description, instructions, archived)?;
        notify(&self.bus, Topic::Projects, Some(id));
        Ok(p)
    }
    pub fn delete_project(&self, id: &str) -> Result<()> {
        projects::delete(&self.db, id)?;
        let mut s = self.settings()?;
        if s.default_project_id.as_deref() == Some(id) {
            s.default_project_id = None;
            s.save(&self.db)?;
        }
        notify(&self.bus, Topic::Projects, Some(id));
        notify(&self.bus, Topic::Memory, None);
        notify(&self.bus, Topic::Conversations, None);
        Ok(())
    }

    // ---------- conversations ----------
    pub fn conversations(&self, project_id: Option<&str>, include_archived: bool, limit: u32, offset: u32) -> Result<Vec<conversations::Conversation>> {
        conversations::list(&self.db, project_id, include_archived, limit.min(500), offset)
    }
    pub fn create_conversation(&self, project_id: Option<&str>, title: &str) -> Result<conversations::Conversation> {
        if let Some(p) = project_id {
            projects::get(&self.db, p)?;
        }
        let c = conversations::create(&self.db, project_id, title)?;
        notify(&self.bus, Topic::Conversations, Some(&c.id));
        Ok(c)
    }
    pub fn messages(&self, conversation_id: &str) -> Result<Vec<conversations::StoredMessage>> {
        conversations::messages(&self.db, conversation_id)
    }
    pub fn rename_conversation(&self, id: &str, title: &str) -> Result<()> {
        conversations::rename(&self.db, id, title)?;
        notify(&self.bus, Topic::Conversations, Some(id));
        Ok(())
    }
    pub fn archive_conversation(&self, id: &str, archived: bool) -> Result<()> {
        conversations::set_archived(&self.db, id, archived)?;
        notify(&self.bus, Topic::Conversations, Some(id));
        Ok(())
    }
    pub fn move_conversation(&self, id: &str, project_id: Option<&str>) -> Result<()> {
        conversations::set_project(&self.db, id, project_id)?;
        notify(&self.bus, Topic::Conversations, Some(id));
        Ok(())
    }
    pub fn delete_conversation(&self, id: &str) -> Result<()> {
        if self.turns.lock().map(|t| t.values().any(|a| a.conversation_id == id)).unwrap_or(false) {
            return Err(AtlasError::Conflict("stop the running response before deleting this conversation".into()));
        }
        conversations::delete(&self.db, id)?;
        notify(&self.bus, Topic::Conversations, Some(id));
        Ok(())
    }
    pub fn search_conversations(&self, q: &str) -> Result<Vec<conversations::SearchHit>> {
        conversations::search(&self.db, q, 50)
    }

    // ---------- Atlas Forge ----------
    pub fn forge_projects(&self) -> Result<Vec<crate::forge::ForgeProject>> {
        crate::forge::list_projects(&self.db)
    }

    pub fn forge_add_project(&self, name: &str, root: &Path, test_command: Option<&str>, build_command: Option<&str>) -> Result<crate::forge::ForgeProject> {
        let p = crate::forge::add_project(&self.db, name, root, test_command, build_command)?;
        audit::record(&self.db, "forge.project_added", "info", None, None, json!({"project_id": p.id}));
        notify(&self.bus, Topic::Forge, Some(&p.id));
        Ok(p)
    }

    pub fn forge_update_project(&self, id: &str, name: &str, test_command: Option<&str>, build_command: Option<&str>) -> Result<crate::forge::ForgeProject> {
        let p = crate::forge::update_project(&self.db, id, name, test_command, build_command)?;
        notify(&self.bus, Topic::Forge, Some(id));
        Ok(p)
    }

    pub fn forge_remove_project(&self, id: &str) -> Result<()> {
        crate::forge::remove_project(&self.db, id)?;
        audit::record(&self.db, "forge.project_removed", "info", None, None, json!({"project_id": id}));
        notify(&self.bus, Topic::Forge, Some(id));
        notify(&self.bus, Topic::Conversations, None);
        Ok(())
    }

    fn forge_root(&self, project_id: &str) -> Result<PathBuf> {
        Ok(crate::forge::scope(&self.db, project_id, crate::forge::Discipline::Architect)?.root)
    }

    pub fn forge_tree(&self, project_id: &str, rel: &str, depth: u32) -> Result<Value> {
        let (entries, truncated) = crate::forge::tree(&self.forge_root(project_id)?, rel, depth, 5000)?;
        Ok(json!({"entries": entries, "truncated": truncated}))
    }

    pub fn forge_read_file(&self, project_id: &str, rel: &str) -> Result<Value> {
        let root = self.forge_root(project_id)?;
        let (full, content) = crate::forge::read_text(&root, rel)?;
        Ok(json!({"path": crate::forge::display_rel(&root, &full), "content": content}))
    }

    pub fn forge_create_session(&self, project_id: &str, discipline: crate::forge::Discipline) -> Result<conversations::Conversation> {
        let title = format!("{} session", discipline.label());
        let c = conversations::create_forge(&self.db, project_id, discipline, &title)?;
        notify(&self.bus, Topic::Forge, Some(project_id));
        Ok(c)
    }

    pub fn forge_sessions(&self, project_id: &str) -> Result<Vec<conversations::Conversation>> {
        conversations::list_forge(&self.db, project_id, 100)
    }

    pub fn forge_set_discipline(&self, conversation_id: &str, discipline: crate::forge::Discipline) -> Result<conversations::Conversation> {
        let c = conversations::set_discipline(&self.db, conversation_id, discipline)?;
        notify(&self.bus, Topic::Conversations, Some(conversation_id));
        Ok(c)
    }

    /// A command the owner typed in the Forge terminal. It is the owner's own action, so it
    /// needs no approval, but it still runs without a shell, with limits, and is audited.
    pub async fn forge_run(&self, project_id: &str, command: &str) -> Result<crate::forge::RunRecord> {
        let root = self.forge_root(project_id)?;
        let argv = crate::forge::runner::parse_command(command)?;
        let settings = self.settings()?;
        let run_id = crate::forge::start_run(&self.db, project_id, &argv, "user", None)?;
        notify(&self.bus, Topic::Forge, Some(project_id));
        audit::record(&self.db, "forge.command", "info", None, None, json!({"project_id": project_id, "program": argv[0]}));
        let spec = crate::forge::runner::RunSpec {
            argv: &argv,
            cwd: &root,
            timeout: Duration::from_secs(settings.forge.command_timeout_secs as u64),
            max_output: settings.forge.max_output_kb as usize * 1024,
            extra_env: &[],
        };
        let cancel = CancellationToken::new();
        if let Ok(mut m) = self.forge_cancels.lock() {
            m.insert(run_id.clone(), cancel.clone());
        }
        let res = crate::forge::runner::run(spec, &cancel).await;
        if let Ok(mut m) = self.forge_cancels.lock() {
            m.remove(&run_id);
        }
        match res {
            Ok(out) => crate::forge::finish_run(&self.db, &run_id, &out)?,
            Err(e) => {
                crate::forge::fail_run(&self.db, &run_id, &e.to_string());
                notify(&self.bus, Topic::Forge, Some(project_id));
                return Err(e);
            }
        }
        notify(&self.bus, Topic::Forge, Some(project_id));
        crate::forge::list_runs(&self.db, project_id, 50)?.into_iter().find(|r| r.id == run_id).ok_or_else(|| AtlasError::NotFound("run".into()))
    }

    pub fn forge_cancel_run(&self, run_id: &str) -> bool {
        self.forge_cancels.lock().ok().and_then(|m| m.get(run_id).cloned()).map(|c| c.cancel()).is_some()
    }

    pub fn forge_runs(&self, project_id: &str) -> Result<Vec<crate::forge::RunRecord>> {
        crate::forge::list_runs(&self.db, project_id, 50)
    }

    pub async fn forge_git_status(&self, project_id: &str) -> Result<crate::forge::git::Status> {
        crate::forge::git::status(&self.forge_root(project_id)?, &CancellationToken::new()).await
    }

    pub async fn forge_git_diff(&self, project_id: &str, path: Option<&str>) -> Result<String> {
        crate::forge::git::diff(&self.forge_root(project_id)?, path, false, &CancellationToken::new()).await
    }

    pub async fn forge_git_log(&self, project_id: &str) -> Result<Vec<crate::forge::git::Commit>> {
        crate::forge::git::log(&self.forge_root(project_id)?, 50, &CancellationToken::new()).await
    }

    pub async fn forge_git_commit(&self, project_id: &str, message: &str, paths: &[String]) -> Result<String> {
        let h = crate::forge::git::commit(&self.forge_root(project_id)?, message, paths, &CancellationToken::new()).await?;
        audit::record(&self.db, "forge.commit", "info", None, None, json!({"project_id": project_id, "by": "user"}));
        notify(&self.bus, Topic::Forge, Some(project_id));
        Ok(h)
    }

    pub async fn forge_git_branch(&self, project_id: &str, name: &str) -> Result<()> {
        crate::forge::git::create_branch(&self.forge_root(project_id)?, name, &CancellationToken::new()).await?;
        notify(&self.bus, Topic::Forge, Some(project_id));
        Ok(())
    }

    pub fn forge_changes(&self, project_id: &str) -> Result<Vec<crate::forge::Change>> {
        crate::forge::list_changes(&self.db, project_id, 200)
    }

    pub fn forge_change_diff(&self, change_id: &str) -> Result<String> {
        crate::forge::change_diff(&self.db, change_id)
    }

    pub fn forge_revert(&self, change_id: &str) -> Result<crate::forge::Change> {
        let c = crate::forge::revert_change(&self.db, change_id)?;
        audit::record(&self.db, "forge.reverted", "info", None, None, json!({"change_id": change_id}));
        notify(&self.bus, Topic::Forge, Some(&c.project_id));
        Ok(c)
    }

    pub fn pricing_schedule(&self) -> Value {
        json!({"entries": crate::pricing::schedule(), "seed_conflicts": crate::pricing::seed_conflicts()})
    }

    // ---------- file grants ----------
    pub fn add_grant(&self, path: &Path) -> Result<grants::Grant> {
        let g = grants::add(&self.db, path)?;
        audit::record(&self.db, "file.granted", "info", None, None, json!({"grant_id": g.id}));
        Ok(g)
    }
    pub fn grants(&self) -> Result<Vec<grants::Grant>> {
        grants::list(&self.db)
    }
    pub fn revoke_grant(&self, id: &str) -> Result<()> {
        grants::revoke(&self.db, id)
    }

    // ---------- usage, diagnostics, audit ----------
    pub fn usage(&self) -> Result<usage::UsageSummary> {
        usage::summary(&self.db)
    }

    pub fn recent_errors(&self, limit: u32) -> Result<Vec<audit::AuditEvent>> {
        let mut v = audit::recent(&self.db, limit, Some("error"))?;
        v.extend(audit::recent(&self.db, limit, Some("warn"))?);
        v.sort_by(|a, b| b.id.cmp(&a.id));
        v.truncate(limit as usize);
        Ok(v)
    }

    pub async fn diagnostics_report(&self) -> Value {
        let settings = self.settings().unwrap_or_default();
        let providers = self.providers().unwrap_or_default();
        let tools = self.tools().unwrap_or_default();
        let task_counts: Vec<(String, i64)> = self
            .db
            .conn()
            .ok()
            .and_then(|c| {
                let mut s = c.prepare("SELECT status, count(*) FROM tasks GROUP BY status").ok()?;
                let rows = s.query_map([], |r| Ok((r.get(0)?, r.get(1)?))).ok()?;
                Some(rows.flatten().collect())
            })
            .unwrap_or_default();
        let credential_store = match self.secrets.health() {
            Ok(()) => json!({"backend": self.secrets.backend(), "ok": true}),
            Err(e) => json!({"backend": self.secrets.backend(), "ok": false, "detail": e.to_string()}),
        };
        json!({
            "app": {"name": "ATLAS Co-Pilot", "version": self.version},
            "platform": {"os": std::env::consts::OS, "arch": std::env::consts::ARCH, "family": std::env::consts::FAMILY},
            "database": {
                "schema_version": self.db.schema_version().ok(),
                "quick_check": self.db.quick_check().unwrap_or_else(|e| e.to_string()),
                "size_bytes": self.db.size_bytes(),
            },
            "credential_store": credential_store,
            "providers": providers.iter().map(|p| json!({
                "label": p.label, "kind": p.kind, "status": p.status, "has_credential": p.has_credential,
                "models_known": p.models.len(), "last_checked_at": p.last_checked_at, "local": p.local,
            })).collect::<Vec<_>>(),
            "tools": {
                "registered": tools.len(),
                "enabled": tools.iter().filter(|t| t.enabled).count(),
                "available": tools.iter().filter(|t| t.enabled && t.availability == crate::tools::Availability::Available).count(),
            },
            "task_engine": {
                "active_turns": self.active_turns().len(),
                "waiting_approvals": self.broker.pending_count(),
                "tasks_by_status": task_counts.into_iter().collect::<HashMap<_, _>>(),
                "recovered_after_restart": self.recovered_tasks,
            },
            "settings": {
                "offline_mode": settings.network.offline_mode,
                "memory_enabled": settings.memory.enabled,
                "workspace_configured": settings.workspace_dir.is_some(),
                "cross_provider_fallback": settings.routing.allow_cross_provider_fallback,
            },
        })
    }

    // ---------- export, backup, restore ----------
    /// Export user-owned data as JSON. Excludes credentials (never in the database anyway),
    /// provider-native payloads and the audit log.
    pub fn export_json(&self) -> Result<Value> {
        let convs = conversations::list(&self.db, None, true, 100_000, 0)?;
        let mut cv = Vec::new();
        for c in convs {
            let msgs: Vec<Value> = conversations::messages(&self.db, &c.id)?
                .into_iter()
                .filter(|m| m.role == "user" || m.role == "assistant")
                .map(|m| json!({"role": m.role, "content": m.content, "model": m.model, "created_at": m.created_at}))
                .collect();
            cv.push(json!({"conversation": c, "messages": msgs}));
        }
        Ok(json!({
            "format": "atlas-copilot-export",
            "format_version": 1,
            "app_version": self.version,
            "exported_at": crate::storage::now(),
            "note": "Contains no API keys or credentials.",
            "settings": self.settings()?,
            "projects": self.projects(true)?,
            "memories": self.memories(None)?,
            "conversations": cv,
        }))
    }

    pub fn conversation_markdown(&self, id: &str) -> Result<String> {
        let c = conversations::get(&self.db, id)?;
        let mut out = format!("# {}\n\n_Exported from ATLAS Co-Pilot on {}_\n\n", c.title, crate::storage::now());
        for m in conversations::messages(&self.db, id)? {
            match m.role.as_str() {
                "user" => out.push_str(&format!("## You\n\n{}\n\n", m.content)),
                "assistant" if !m.content.is_empty() => out.push_str(&format!("## Atlas\n\n{}\n\n", m.content)),
                _ => {}
            }
        }
        Ok(out)
    }

    pub fn backup_to(&self, dest: &Path) -> Result<()> {
        self.db.backup_to(dest)?;
        audit::record(&self.db, "backup.created", "info", None, None, json!({}));
        Ok(())
    }

    pub fn restore_from(&self, src: &Path) -> Result<()> {
        if !self.active_turns().is_empty() {
            return Err(AtlasError::Conflict("stop running tasks before restoring a backup".into()));
        }
        self.db.restore_from(src)?;
        // Restored task state is history only: nothing restored is "running".
        tasks::recover_after_restart(&self.db)?;
        audit::record(&self.db, "backup.restored", "warn", None, None, json!({}));
        for t in [Topic::Settings, Topic::Providers, Topic::Conversations, Topic::Memory, Topic::Projects, Topic::Tasks, Topic::Registry] {
            notify(&self.bus, t, None);
        }
        Ok(())
    }

    /// Remove every stored credential (providers and integrations).
    pub fn remove_all_credentials(&self) -> Result<()> {
        for p in self.providers()? {
            let _ = providers::clear_key(&self.db, &self.secrets, &p.id);
        }
        for i in integrations::CATALOG {
            let _ = integrations::clear_key(&self.db, &self.secrets, i.id);
        }
        audit::record(&self.db, "credential.removed_all", "warn", None, None, json!({}));
        notify(&self.bus, Topic::Providers, None);
        notify(&self.bus, Topic::Registry, None);
        Ok(())
    }
}

pub fn describe_provider_error(e: &crate::ai::ProviderError) -> String {
    use crate::ai::ProviderErrorKind::*;
    let hint = match e.kind {
        Auth => "The provider rejected the API key. Check or replace it in Integrations.",
        RateLimited => "The provider is rate limiting requests. Wait a moment and try again.",
        Unavailable | Network => "Atlas couldn't reach the provider. Check your connection (or that Ollama is running).",
        Timeout => "The provider took too long to respond.",
        NotFound => "The model or endpoint was not found. Check the model name and base URL.",
        BadRequest => "The provider rejected the request.",
        Overloaded | Server => "The provider had a temporary problem. Try again shortly.",
        Decode => "The provider's response could not be read.",
        Cancelled => "Cancelled.",
    };
    if e.message.is_empty() { hint.into() } else { format!("{hint} ({})", e.message) }
}

#[async_trait]
impl ToolServices for Atlas {
    async fn diagnostics(&self) -> Value {
        self.diagnostics_report().await
    }
    async fn provider_health(&self) -> Value {
        let mut out = Vec::new();
        for p in self.providers().unwrap_or_default() {
            if !p.enabled {
                out.push(json!({"label": p.label, "ok": false, "message": "disabled"}));
                continue;
            }
            match self.test_provider(&p.id).await {
                Ok(r) => out.push(json!({"label": p.label, "ok": r.ok, "message": r.message})),
                Err(e) => out.push(json!({"label": p.label, "ok": false, "message": e.to_string()})),
            }
        }
        json!({"providers": out})
    }
    fn task_status(&self, task_id: Option<&str>) -> Value {
        match task_id {
            Some(id) => tasks::detail(&self.db, id).map(|d| json!(d)).unwrap_or_else(|e| json!({"error": e.to_string()})),
            None => json!({"recent": tasks::list(&self.db, None, 10).unwrap_or_default()}),
        }
    }
}
