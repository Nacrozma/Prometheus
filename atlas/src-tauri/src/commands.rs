//! The IPC surface. Every command here is narrow, takes typed arguments, and delegates to the
//! trusted core. There is no general filesystem, shell or network command. Paths that leave the
//! workspace only ever come from native dialogs the user operated.

use crate::AppState;
use atlas_core::ai::ProviderKind;
use atlas_core::engine::{TurnEvent, TurnParams, TurnSummary};
use atlas_core::error::AtlasError;
use atlas_core::memory::MemoryKind;
use atlas_core::settings::Settings;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::PathBuf;
use tauri::ipc::Channel;
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

type R<T> = Result<T, AtlasError>;

pub fn handler() -> impl Fn(tauri::ipc::Invoke<tauri::Wry>) -> bool + Send + Sync + 'static {
    tauri::generate_handler![
        app_info, diagnostics, recent_errors, open_external, save_text_via_dialog,
        settings_get, settings_update, first_launch_complete, workspace_pick, workspace_use_default, workspace_add_sample, workspace_browse, workspace_preview, workspace_reveal,
        provider_templates, providers_list, provider_add, provider_update, provider_delete, provider_set_key, provider_clear_key, provider_test,
        integrations_list, integration_set_key, integration_clear_key, integration_set_enabled, integration_test,
        tools_list, tool_set_enabled,
        conversations_list, conversation_create, conversation_messages, conversation_rename, conversation_archive,
        conversation_move, conversation_delete, conversations_search, conversation_export,
        chat_send, chat_cancel,
        approvals_pending, approval_decide,
        tasks_list, task_detail, task_cancel, task_dismiss, task_retry_step, emergency_stop, active_turns,
        memories_list, memory_create, memory_update, memory_delete, memory_delete_all, memory_search, memory_export,
        projects_list, project_create, project_update, project_delete, project_export,
        file_share_pick, grants_list, grant_revoke,
        usage_summary, map_graph,
        export_all, backup_create, backup_inspect, backup_restore_confirm, credentials_remove_all,
        pricing_schedule,
        forge_projects, forge_project_pick, forge_project_update, forge_project_remove, forge_tree, forge_read_file,
        forge_session_create, forge_sessions, forge_set_discipline, forge_run, forge_run_cancel, forge_runs,
        forge_git_status, forge_git_diff, forge_git_log, forge_git_commit, forge_git_branch,
        forge_changes, forge_change_diff, forge_revert,
        siblings_list, sibling_pair, sibling_refresh, sibling_revoke, sibling_forget,
        missions_list, mission_detail, mission_create, mission_update, mission_transition, mission_send,
        mission_message, mission_accept, mission_cancel, mission_sync, mission_note,
        voice_status, voice_install, voice_install_cancel, voice_remove, voice_verify,
        voice_synthesize, voice_stop_speech, voice_transcribe, voice_cancel_transcription, voice_benchmark,
    ]
}

fn io(e: impl std::fmt::Display) -> AtlasError {
    AtlasError::Io(e.to_string())
}

// ---------------- native dialogs (run off the main thread) ----------------

async fn pick_folder(app: &AppHandle, title: &str) -> R<Option<PathBuf>> {
    let app = app.clone();
    let title = title.to_string();
    let picked = tauri::async_runtime::spawn_blocking(move || app.dialog().file().set_title(title).blocking_pick_folder())
        .await
        .map_err(io)?;
    picked.map(|p| p.into_path().map_err(io)).transpose()
}

async fn pick_file(app: &AppHandle, title: &str, filter: Option<(&str, Vec<String>)>) -> R<Option<PathBuf>> {
    let app = app.clone();
    let title = title.to_string();
    let filter = filter.map(|(n, e)| (n.to_string(), e));
    let picked = tauri::async_runtime::spawn_blocking(move || {
        let mut d = app.dialog().file().set_title(title);
        if let Some((name, exts)) = &filter {
            let refs: Vec<&str> = exts.iter().map(String::as_str).collect();
            d = d.add_filter(name, &refs);
        }
        d.blocking_pick_file()
    })
    .await
    .map_err(io)?;
    picked.map(|p| p.into_path().map_err(io)).transpose()
}

async fn save_file(app: &AppHandle, title: &str, suggested: &str, ext: &str) -> R<Option<PathBuf>> {
    let app = app.clone();
    let (title, suggested, ext) = (title.to_string(), suggested.to_string(), ext.to_string());
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog().file().set_title(title).set_file_name(suggested).add_filter(ext.to_uppercase(), &[ext.as_str()]).blocking_save_file()
    })
    .await
    .map_err(io)?;
    picked.map(|p| p.into_path().map_err(io)).transpose()
}

fn sanitize_file_name(name: &str) -> String {
    let s: String = name.chars().map(|c| if c.is_alphanumeric() || " -_.".contains(c) { c } else { '-' }).take(80).collect();
    if s.trim().is_empty() { "atlas-export".into() } else { s }
}

// ---------------- app ----------------

#[derive(Serialize)]
pub struct AppInfo {
    name: &'static str,
    version: String,
    os: &'static str,
    arch: &'static str,
    data_dir: Option<String>,
    credential_backend: &'static str,
    e2e_build: bool,
}

#[tauri::command]
fn app_info(state: State<'_, AppState>) -> AppInfo {
    let a = &state.atlas;
    AppInfo {
        name: "ATLAS Co-Pilot",
        version: a.version.clone(),
        os: std::env::consts::OS,
        arch: std::env::consts::ARCH,
        data_dir: a.data_dir.as_ref().map(|p| p.to_string_lossy().to_string()),
        credential_backend: a.secrets.backend(),
        e2e_build: cfg!(feature = "e2e"),
    }
}

#[tauri::command]
async fn diagnostics(state: State<'_, AppState>) -> R<Value> {
    Ok(state.atlas.diagnostics_report().await)
}

#[tauri::command]
fn recent_errors(state: State<'_, AppState>, limit: Option<u32>) -> R<Vec<atlas_core::audit::AuditEvent>> {
    state.atlas.recent_errors(limit.unwrap_or(30).min(200))
}

/// Open an http(s) link in the system browser. Only called from an explicit user click.
#[tauri::command]
fn open_external(app: AppHandle, url: String) -> R<()> {
    let parsed = tauri::Url::parse(&url).map_err(|_| AtlasError::Validation("invalid URL".into()))?;
    if !matches!(parsed.scheme(), "https" | "http") {
        return Err(AtlasError::PermissionDenied("only web links can be opened".into()));
    }
    app.opener().open_url(parsed.as_str(), None::<&str>).map_err(io)
}

/// Write text the user is looking at (e.g. a diagnostics preview) to a file they choose.
#[tauri::command]
async fn save_text_via_dialog(app: AppHandle, suggested_name: String, extension: String, content: String) -> R<Option<String>> {
    if !matches!(extension.as_str(), "json" | "md" | "txt" | "csv") {
        return Err(AtlasError::Validation("unsupported extension".into()));
    }
    if content.len() > 50 * 1024 * 1024 {
        return Err(AtlasError::Validation("content too large".into()));
    }
    let content = atlas_core::redact::redact(&content);
    match save_file(&app, "Save", &sanitize_file_name(&suggested_name), &extension).await? {
        Some(p) => {
            std::fs::write(&p, content)?;
            Ok(Some(p.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}

// ---------------- settings & workspace ----------------

#[tauri::command]
fn settings_get(state: State<'_, AppState>) -> R<Settings> {
    state.atlas.settings()
}

#[tauri::command]
fn settings_update(state: State<'_, AppState>, settings: Settings) -> R<Settings> {
    // The workspace may only change through the folder picker or the default-folder command.
    let current = state.atlas.settings()?;
    if settings.workspace_dir != current.workspace_dir {
        return Err(AtlasError::PermissionDenied("change the workspace folder with the folder picker".into()));
    }
    state.atlas.update_settings(settings)
}

#[tauri::command]
fn first_launch_complete(state: State<'_, AppState>) -> R<Settings> {
    state.atlas.complete_first_launch()
}

#[tauri::command]
async fn workspace_pick(app: AppHandle, state: State<'_, AppState>) -> R<Option<Settings>> {
    match pick_folder(&app, "Choose the Atlas workspace folder").await? {
        Some(dir) => Ok(Some(state.atlas.ensure_workspace(&dir)?)),
        None => Ok(None),
    }
}

#[tauri::command]
fn workspace_use_default(app: AppHandle, state: State<'_, AppState>) -> R<Settings> {
    use tauri::Manager;
    let base = app.path().document_dir().or_else(|_| app.path().home_dir()).map_err(io)?;
    state.atlas.ensure_workspace(&base.join("Atlas Workspace"))
}

const SAMPLE_NAME: &str = "Atlas Sample (demo data)/household-budget-DEMO.csv";
const SAMPLE_CSV: &str = "category,month,planned,actual,note\nGroceries,October,450,472.18,DEMO DATA - not real\nUtilities,October,180,166.40,DEMO DATA - not real\nTransport,October,120,138.75,DEMO DATA - not real\nDining out,October,90,61.20,DEMO DATA - not real\nGifts,October,60,84.99,DEMO DATA - not real\nSavings,October,300,300.00,DEMO DATA - not real\n";

/// Add a clearly labelled demonstration file to the workspace (never overwrites).
#[tauri::command]
fn workspace_add_sample(state: State<'_, AppState>) -> R<String> {
    let root = workspace_root(&state)?;
    let target = atlas_core::workspace::resolve_new(&root, SAMPLE_NAME)?;
    atlas_core::workspace::write_new_file(&target, SAMPLE_CSV)?;
    Ok(SAMPLE_NAME.to_string())
}

fn workspace_root(state: &State<'_, AppState>) -> R<PathBuf> {
    state
        .atlas
        .settings()?
        .workspace_dir
        .map(PathBuf::from)
        .ok_or_else(|| AtlasError::Validation("no workspace folder is configured".into()))
}

#[derive(Serialize)]
struct Entry {
    name: String,
    path: String,
    kind: &'static str,
    bytes: Option<u64>,
    modified: Option<String>,
}

#[tauri::command]
fn workspace_browse(state: State<'_, AppState>, path: Option<String>) -> R<Value> {
    let root = workspace_root(&state)?;
    let dir = atlas_core::workspace::resolve_existing(&root, path.as_deref().unwrap_or("."))?;
    let mut entries = Vec::new();
    for e in std::fs::read_dir(&dir)?.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        if name.starts_with('.') || e.file_type().map(|t| t.is_symlink()).unwrap_or(true) {
            continue;
        }
        let Ok(meta) = e.metadata() else { continue };
        let rel = atlas_core::workspace::relative_display(&root, &e.path());
        entries.push(Entry {
            name,
            path: rel,
            kind: if meta.is_dir() { "dir" } else { "file" },
            bytes: meta.is_file().then_some(meta.len()),
            modified: meta.modified().ok().map(chrono_like),
        });
        if entries.len() >= 2000 {
            break;
        }
    }
    entries.sort_by_key(|a| (a.kind != "dir", a.name.to_lowercase()));
    Ok(json!({"root": root.to_string_lossy(), "path": atlas_core::workspace::relative_display(&root, &dir), "entries": entries}))
}

fn chrono_like(t: std::time::SystemTime) -> String {
    let secs = t.duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    secs.to_string()
}

#[tauri::command]
fn workspace_preview(state: State<'_, AppState>, path: String) -> R<Value> {
    let root = workspace_root(&state)?;
    let p = atlas_core::workspace::resolve_existing(&root, &path)?;
    match atlas_core::tools::builtin::files::read_text(&p) {
        Ok((content, bytes, truncated)) => Ok(json!({"path": path, "content": content, "bytes": bytes, "truncated": truncated})),
        Err(e) => Ok(json!({"path": path, "error": e.message, "code": e.code})),
    }
}

#[tauri::command]
fn workspace_reveal(app: AppHandle, state: State<'_, AppState>, path: Option<String>) -> R<()> {
    let root = workspace_root(&state)?;
    let p = atlas_core::workspace::resolve_existing(&root, path.as_deref().unwrap_or("."))?;
    app.opener().reveal_item_in_dir(p).map_err(io)
}

// ---------------- providers ----------------

#[tauri::command]
fn provider_templates(state: State<'_, AppState>) -> Vec<atlas_core::ai::catalog::ProviderTemplate> {
    state.atlas.provider_templates()
}

#[tauri::command]
fn providers_list(state: State<'_, AppState>) -> R<Vec<atlas_core::providers::ProviderConfig>> {
    state.atlas.providers()
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewProvider {
    kind: ProviderKind,
    label: String,
    base_url: String,
    default_model: Option<String>,
}

#[tauri::command]
fn provider_add(state: State<'_, AppState>, provider: NewProvider) -> R<atlas_core::providers::ProviderConfig> {
    if provider.kind == ProviderKind::Mock {
        return Err(AtlasError::Validation("unknown provider kind".into()));
    }
    state.atlas.add_provider(provider.kind, &provider.label, &provider.base_url, provider.default_model.as_deref())
}

#[tauri::command]
fn provider_update(state: State<'_, AppState>, id: String, label: String, base_url: String, default_model: Option<String>, enabled: bool) -> R<atlas_core::providers::ProviderConfig> {
    state.atlas.update_provider(&id, &label, &base_url, default_model.as_deref(), enabled)
}

#[tauri::command]
fn provider_delete(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.delete_provider(&id)
}

/// The key travels UI → core once, is stored in the OS credential store, and is never returned.
#[tauri::command]
fn provider_set_key(state: State<'_, AppState>, id: String, key: String) -> R<atlas_core::providers::ProviderConfig> {
    state.atlas.set_provider_key(&id, &key)
}

#[tauri::command]
fn provider_clear_key(state: State<'_, AppState>, id: String) -> R<atlas_core::providers::ProviderConfig> {
    state.atlas.clear_provider_key(&id)
}

#[tauri::command]
async fn provider_test(state: State<'_, AppState>, id: String) -> R<atlas_core::app::ProviderTestResult> {
    state.atlas.test_provider(&id).await
}

// ---------------- integrations & tools ----------------

#[tauri::command]
fn integrations_list(state: State<'_, AppState>) -> R<Vec<atlas_core::integrations::Integration>> {
    state.atlas.integrations()
}
#[tauri::command]
fn integration_set_key(state: State<'_, AppState>, id: String, key: String) -> R<atlas_core::integrations::Integration> {
    state.atlas.set_integration_key(&id, &key)
}
#[tauri::command]
fn integration_clear_key(state: State<'_, AppState>, id: String) -> R<atlas_core::integrations::Integration> {
    state.atlas.clear_integration_key(&id)
}
#[tauri::command]
fn integration_set_enabled(state: State<'_, AppState>, id: String, enabled: bool) -> R<atlas_core::integrations::Integration> {
    state.atlas.set_integration_enabled(&id, enabled)
}
#[tauri::command]
async fn integration_test(state: State<'_, AppState>, id: String) -> R<atlas_core::integrations::Integration> {
    state.atlas.test_integration(&id).await
}
#[tauri::command]
fn tools_list(state: State<'_, AppState>) -> R<Vec<atlas_core::tools::registry::ToolInfo>> {
    state.atlas.tools()
}
#[tauri::command]
fn tool_set_enabled(state: State<'_, AppState>, id: String, enabled: bool) -> R<()> {
    state.atlas.set_tool_enabled(&id, enabled)
}

// ---------------- conversations & chat ----------------

#[tauri::command]
fn conversations_list(state: State<'_, AppState>, project_id: Option<String>, include_archived: Option<bool>, limit: Option<u32>, offset: Option<u32>) -> R<Vec<atlas_core::conversations::Conversation>> {
    state.atlas.conversations(project_id.as_deref(), include_archived.unwrap_or(false), limit.unwrap_or(100), offset.unwrap_or(0))
}
#[tauri::command]
fn conversation_create(state: State<'_, AppState>, project_id: Option<String>, title: Option<String>) -> R<atlas_core::conversations::Conversation> {
    state.atlas.create_conversation(project_id.as_deref(), title.as_deref().unwrap_or(""))
}
#[tauri::command]
fn conversation_messages(state: State<'_, AppState>, id: String) -> R<Vec<atlas_core::conversations::StoredMessage>> {
    state.atlas.messages(&id)
}
#[tauri::command]
fn conversation_rename(state: State<'_, AppState>, id: String, title: String) -> R<()> {
    state.atlas.rename_conversation(&id, &title)
}
#[tauri::command]
fn conversation_archive(state: State<'_, AppState>, id: String, archived: bool) -> R<()> {
    state.atlas.archive_conversation(&id, archived)
}
#[tauri::command]
fn conversation_move(state: State<'_, AppState>, id: String, project_id: Option<String>) -> R<()> {
    state.atlas.move_conversation(&id, project_id.as_deref())
}
#[tauri::command]
fn conversation_delete(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.delete_conversation(&id)
}
#[tauri::command]
fn conversations_search(state: State<'_, AppState>, query: String) -> R<Vec<atlas_core::conversations::SearchHit>> {
    state.atlas.search_conversations(&query)
}
#[tauri::command]
async fn conversation_export(app: AppHandle, state: State<'_, AppState>, id: String) -> R<Option<String>> {
    let md = state.atlas.conversation_markdown(&id)?;
    let title = atlas_core::conversations::get(&state.atlas.db, &id)?.title;
    match save_file(&app, "Export conversation", &format!("{}.md", sanitize_file_name(&title)), "md").await? {
        Some(p) => {
            std::fs::write(&p, md)?;
            Ok(Some(p.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}

/// Run one turn. Streaming events go to `on_event`; the promise resolves when the turn ends.
#[tauri::command]
async fn chat_send(state: State<'_, AppState>, params: TurnParamsIn, on_event: Channel<TurnEvent>) -> R<TurnSummary> {
    let atlas = state.atlas.clone();
    let p = TurnParams { conversation_id: params.conversation_id, text: params.text, provider_id: params.provider_id, model: params.model, budget_override: params.budget_override, mission_id: None, regenerate: params.regenerate };
    atlas
        .send_message(p, Box::new(move |e| {
            let _ = on_event.send(e);
        }))
        .await
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TurnParamsIn {
    conversation_id: String,
    text: String,
    provider_id: Option<String>,
    model: Option<String>,
    #[serde(default)]
    budget_override: bool,
    #[serde(default)]
    regenerate: bool,
}

#[tauri::command]
fn chat_cancel(state: State<'_, AppState>, conversation_id: String) -> bool {
    state.atlas.cancel_conversation(&conversation_id)
}

// ---------------- approvals & tasks ----------------

#[tauri::command]
fn approvals_pending(state: State<'_, AppState>) -> R<Vec<atlas_core::approvals::Approval>> {
    state.atlas.pending_approvals()
}
#[tauri::command]
fn approval_decide(state: State<'_, AppState>, id: String, approve: bool) -> R<()> {
    state.atlas.decide_approval(&id, approve)
}
#[tauri::command]
fn tasks_list(state: State<'_, AppState>, status: Option<String>, limit: Option<u32>) -> R<Vec<atlas_core::tasks::Task>> {
    state.atlas.tasks(status.as_deref(), limit.unwrap_or(100))
}
#[tauri::command]
fn task_detail(state: State<'_, AppState>, id: String) -> R<atlas_core::tasks::TaskDetail> {
    state.atlas.task_detail(&id)
}
#[tauri::command]
fn task_cancel(state: State<'_, AppState>, id: String) -> R<bool> {
    state.atlas.cancel_task(&id)
}
#[tauri::command]
fn task_dismiss(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.dismiss_task(&id)
}
#[tauri::command]
async fn task_retry_step(state: State<'_, AppState>, step_id: String) -> R<Value> {
    state.atlas.retry_step(&step_id).await
}
#[tauri::command]
fn emergency_stop(state: State<'_, AppState>) -> R<usize> {
    state.atlas.emergency_stop()
}
#[tauri::command]
fn active_turns(state: State<'_, AppState>) -> Vec<Value> {
    state.atlas.active_turns()
}

// ---------------- memory & projects ----------------

#[tauri::command]
fn memories_list(state: State<'_, AppState>, scope: Option<String>) -> R<Vec<atlas_core::memory::Memory>> {
    match scope.as_deref() {
        None | Some("all") => state.atlas.memories(None),
        Some("global") => state.atlas.memories(Some(None)),
        Some(project) => state.atlas.memories(Some(Some(project))),
    }
}
#[tauri::command]
fn memory_create(state: State<'_, AppState>, project_id: Option<String>, kind: MemoryKind, content: String, pinned: Option<bool>) -> R<atlas_core::memory::Memory> {
    state.atlas.create_memory(project_id.as_deref(), kind, &content, pinned.unwrap_or(false))
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryPatch {
    content: Option<String>,
    kind: Option<MemoryKind>,
    pinned: Option<bool>,
    /// Present → change scope; null → global.
    #[serde(default, deserialize_with = "double_option")]
    project_id: Option<Option<String>>,
}
/// Distinguishes a missing field (None) from an explicit null (Some(None)).
fn double_option<'de, D, T>(d: D) -> Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(d).map(Some)
}

#[tauri::command]
fn memory_update(state: State<'_, AppState>, id: String, patch: MemoryPatch) -> R<atlas_core::memory::Memory> {
    let project = patch.project_id.as_ref().map(|o| o.as_deref());
    state.atlas.update_memory(&id, patch.content.as_deref(), patch.kind, patch.pinned, project)
}
#[tauri::command]
fn memory_delete(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.delete_memory(&id)
}
#[tauri::command]
fn memory_delete_all(state: State<'_, AppState>, confirm: String) -> R<usize> {
    if confirm != "DELETE" {
        return Err(AtlasError::Validation("confirmation text did not match".into()));
    }
    state.atlas.delete_all_memories()
}
#[tauri::command]
fn memory_search(state: State<'_, AppState>, query: String, project_id: Option<String>) -> R<Vec<atlas_core::memory::Retrieved>> {
    state.atlas.search_memories(&query, project_id.as_deref())
}
#[tauri::command]
async fn memory_export(app: AppHandle, state: State<'_, AppState>) -> R<Option<String>> {
    let data = json!({"format": "atlas-memories", "format_version": 1, "exported_at": atlas_core::storage::now(), "memories": state.atlas.memories(None)?});
    match save_file(&app, "Export memories", "atlas-memories.json", "json").await? {
        Some(p) => {
            std::fs::write(&p, serde_json::to_string_pretty(&data)?)?;
            Ok(Some(p.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}
#[tauri::command]
fn projects_list(state: State<'_, AppState>, include_archived: Option<bool>) -> R<Vec<atlas_core::projects::Project>> {
    state.atlas.projects(include_archived.unwrap_or(true))
}
#[tauri::command]
fn project_create(state: State<'_, AppState>, name: String, description: String, instructions: String) -> R<atlas_core::projects::Project> {
    state.atlas.create_project(&name, &description, &instructions)
}
#[tauri::command]
fn project_update(state: State<'_, AppState>, id: String, name: String, description: String, instructions: String, archived: bool) -> R<atlas_core::projects::Project> {
    state.atlas.update_project(&id, &name, &description, &instructions, archived)
}
#[tauri::command]
fn project_delete(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.delete_project(&id)
}
#[tauri::command]
async fn project_export(app: AppHandle, state: State<'_, AppState>, id: String) -> R<Option<String>> {
    let a = &state.atlas;
    let p = atlas_core::projects::get(&a.db, &id)?;
    let convs = a.conversations(Some(&id), true, 10_000, 0)?;
    let mut cv = Vec::new();
    for c in convs {
        let msgs: Vec<Value> = a
            .messages(&c.id)?
            .into_iter()
            .filter(|m| m.role == "user" || m.role == "assistant")
            .map(|m| json!({"role": m.role, "content": m.content, "created_at": m.created_at}))
            .collect();
        cv.push(json!({"conversation": c, "messages": msgs}));
    }
    let data = json!({"format": "atlas-project", "format_version": 1, "project": p, "memories": a.memories(Some(Some(&id)))?, "conversations": cv});
    match save_file(&app, "Export project", &format!("{}.json", sanitize_file_name(&p.name)), "json").await? {
        Some(path) => {
            std::fs::write(&path, serde_json::to_string_pretty(&data)?)?;
            Ok(Some(path.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}

// ---------------- files shared outside the workspace ----------------

#[tauri::command]
async fn file_share_pick(app: AppHandle, state: State<'_, AppState>) -> R<Option<atlas_core::grants::Grant>> {
    let exts: Vec<String> = atlas_core::workspace::TEXT_EXTENSIONS.iter().map(|s| s.to_string()).collect();
    match pick_file(&app, "Share a text file with Atlas", Some(("Text files", exts))).await? {
        Some(p) => Ok(Some(state.atlas.add_grant(&p)?)),
        None => Ok(None),
    }
}
#[tauri::command]
fn grants_list(state: State<'_, AppState>) -> R<Vec<atlas_core::grants::Grant>> {
    state.atlas.grants()
}
#[tauri::command]
fn grant_revoke(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.revoke_grant(&id)
}

// ---------------- usage, map ----------------

#[tauri::command]
fn usage_summary(state: State<'_, AppState>) -> R<atlas_core::usage::UsageSummary> {
    state.atlas.usage()
}
#[tauri::command]
fn map_graph(state: State<'_, AppState>) -> R<atlas_core::map::Graph> {
    state.atlas.map_graph()
}

// ---------------- export, backup, restore ----------------

#[tauri::command]
async fn export_all(app: AppHandle, state: State<'_, AppState>) -> R<Option<String>> {
    let data = state.atlas.export_json()?;
    match save_file(&app, "Export all data", "atlas-export.json", "json").await? {
        Some(p) => {
            std::fs::write(&p, serde_json::to_string_pretty(&data)?)?;
            Ok(Some(p.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}

#[tauri::command]
async fn backup_create(app: AppHandle, state: State<'_, AppState>) -> R<Option<String>> {
    let name = format!("atlas-backup-{}.atlasbak", chrono_date());
    match save_file(&app, "Save backup", &name, "atlasbak").await? {
        Some(p) => {
            if p.exists() {
                std::fs::remove_file(&p)?; // the user confirmed overwrite in the native dialog
            }
            state.atlas.backup_to(&p)?;
            Ok(Some(p.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}

fn chrono_date() -> String {
    atlas_core::storage::now().chars().take(10).collect()
}

/// Step 1 of restore: the user picks a file; Atlas validates it and reports what it contains.
#[tauri::command]
async fn backup_inspect(app: AppHandle, state: State<'_, AppState>) -> R<Option<Value>> {
    let Some(p) = pick_file(&app, "Choose a backup to restore", Some(("Atlas backup", vec!["atlasbak".into()]))).await? else {
        return Ok(None);
    };
    let conn = atlas_core::storage::validate_backup(&p)?;
    let count = |t: &str| conn.query_row(&format!("SELECT count(*) FROM {t}"), [], |r| r.get::<_, i64>(0)).unwrap_or(0);
    let info = json!({
        "file": p.file_name().map(|n| n.to_string_lossy().to_string()),
        "schema_version": conn.query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0)).unwrap_or(0),
        "conversations": count("conversations"),
        "memories": count("memories"),
        "projects": count("projects"),
        "providers": count("providers"),
    });
    *state.pending_restore.lock().map_err(|_| AtlasError::Internal("lock".into()))? = Some(p);
    Ok(Some(info))
}

/// Step 2: replace current data with the inspected backup (after explicit confirmation).
#[tauri::command]
fn backup_restore_confirm(state: State<'_, AppState>) -> R<()> {
    let p = state
        .pending_restore
        .lock()
        .map_err(|_| AtlasError::Internal("lock".into()))?
        .take()
        .ok_or_else(|| AtlasError::Validation("choose a backup first".into()))?;
    state.atlas.restore_from(&p)
}

#[tauri::command]
fn credentials_remove_all(state: State<'_, AppState>, confirm: String) -> R<()> {
    if confirm != "REMOVE" {
        return Err(AtlasError::Validation("confirmation text did not match".into()));
    }
    state.atlas.remove_all_credentials()
}

// ---------------- pricing ----------------

#[tauri::command]
fn pricing_schedule(state: State<'_, AppState>) -> Value {
    state.atlas.pricing_schedule()
}

// ---------------- Atlas Forge ----------------
// Project folders only ever come from the native folder dialog the owner operated. Every other
// Forge path is relative to a registered project and confined by the core.

#[tauri::command]
fn forge_projects(state: State<'_, AppState>) -> R<Vec<atlas_core::forge::ForgeProject>> {
    state.atlas.forge_projects()
}

#[tauri::command]
async fn forge_project_pick(app: AppHandle, state: State<'_, AppState>, test_command: Option<String>) -> R<Option<atlas_core::forge::ForgeProject>> {
    match pick_folder(&app, "Choose a project folder for Atlas Forge").await? {
        Some(dir) => Ok(Some(state.atlas.forge_add_project("", &dir, test_command.as_deref(), None)?)),
        None => Ok(None),
    }
}

#[tauri::command]
fn forge_project_update(state: State<'_, AppState>, id: String, name: String, test_command: Option<String>, build_command: Option<String>) -> R<atlas_core::forge::ForgeProject> {
    state.atlas.forge_update_project(&id, &name, test_command.as_deref(), build_command.as_deref())
}

#[tauri::command]
fn forge_project_remove(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.forge_remove_project(&id)
}

#[tauri::command]
fn forge_tree(state: State<'_, AppState>, project_id: String, path: Option<String>, depth: Option<u32>) -> R<Value> {
    state.atlas.forge_tree(&project_id, path.as_deref().unwrap_or("."), depth.unwrap_or(1))
}

#[tauri::command]
fn forge_read_file(state: State<'_, AppState>, project_id: String, path: String) -> R<Value> {
    state.atlas.forge_read_file(&project_id, &path)
}

#[tauri::command]
fn forge_session_create(state: State<'_, AppState>, project_id: String, discipline: atlas_core::forge::Discipline) -> R<atlas_core::conversations::Conversation> {
    state.atlas.forge_create_session(&project_id, discipline)
}

#[tauri::command]
fn forge_sessions(state: State<'_, AppState>, project_id: String) -> R<Vec<atlas_core::conversations::Conversation>> {
    state.atlas.forge_sessions(&project_id)
}

#[tauri::command]
fn forge_set_discipline(state: State<'_, AppState>, conversation_id: String, discipline: atlas_core::forge::Discipline) -> R<atlas_core::conversations::Conversation> {
    state.atlas.forge_set_discipline(&conversation_id, discipline)
}

/// A command the owner typed in the Forge terminal (no shell; time and output limits apply).
#[tauri::command]
async fn forge_run(state: State<'_, AppState>, project_id: String, command: String) -> R<atlas_core::forge::RunRecord> {
    state.atlas.clone().forge_run(&project_id, &command).await
}

#[tauri::command]
fn forge_run_cancel(state: State<'_, AppState>, run_id: String) -> bool {
    state.atlas.forge_cancel_run(&run_id)
}

#[tauri::command]
fn forge_runs(state: State<'_, AppState>, project_id: String) -> R<Vec<atlas_core::forge::RunRecord>> {
    state.atlas.forge_runs(&project_id)
}

#[tauri::command]
async fn forge_git_status(state: State<'_, AppState>, project_id: String) -> R<atlas_core::forge::git::Status> {
    state.atlas.clone().forge_git_status(&project_id).await
}

#[tauri::command]
async fn forge_git_diff(state: State<'_, AppState>, project_id: String, path: Option<String>) -> R<String> {
    state.atlas.clone().forge_git_diff(&project_id, path.as_deref()).await
}

#[tauri::command]
async fn forge_git_log(state: State<'_, AppState>, project_id: String) -> R<Vec<atlas_core::forge::git::Commit>> {
    state.atlas.clone().forge_git_log(&project_id).await
}

#[tauri::command]
async fn forge_git_commit(state: State<'_, AppState>, project_id: String, message: String, paths: Vec<String>) -> R<String> {
    state.atlas.clone().forge_git_commit(&project_id, &message, &paths).await
}

#[tauri::command]
async fn forge_git_branch(state: State<'_, AppState>, project_id: String, name: String) -> R<()> {
    state.atlas.clone().forge_git_branch(&project_id, &name).await
}

#[tauri::command]
fn forge_changes(state: State<'_, AppState>, project_id: String) -> R<Vec<atlas_core::forge::Change>> {
    state.atlas.forge_changes(&project_id)
}

#[tauri::command]
fn forge_change_diff(state: State<'_, AppState>, change_id: String) -> R<String> {
    state.atlas.forge_change_diff(&change_id)
}

#[tauri::command]
fn forge_revert(state: State<'_, AppState>, change_id: String) -> R<atlas_core::forge::Change> {
    state.atlas.forge_revert(&change_id)
}

// ---------------- sibling link & mission ledger ----------------
// The shell only passes typed requests through; pairing, authentication and the mission state
// machine live in the core. Sibling secrets never reach the frontend.

#[tauri::command]
fn siblings_list(state: State<'_, AppState>) -> R<Vec<atlas_core::sibling::Sibling>> {
    state.atlas.siblings()
}

#[tauri::command]
async fn sibling_pair(state: State<'_, AppState>, endpoint: String, code: String) -> R<atlas_core::sibling::Sibling> {
    state.atlas.clone().sibling_pair(&endpoint, &code).await
}

#[tauri::command]
async fn sibling_refresh(state: State<'_, AppState>, id: String) -> R<atlas_core::sibling::Sibling> {
    state.atlas.clone().sibling_refresh(&id).await
}

#[tauri::command]
fn sibling_revoke(state: State<'_, AppState>, id: String) -> R<atlas_core::sibling::Sibling> {
    state.atlas.sibling_revoke(&id)
}

#[tauri::command]
fn sibling_forget(state: State<'_, AppState>, id: String) -> R<()> {
    state.atlas.sibling_forget(&id)
}

#[tauri::command]
fn missions_list(state: State<'_, AppState>) -> R<Vec<atlas_core::sibling::missions::Mission>> {
    state.atlas.missions()
}

#[tauri::command]
fn mission_detail(state: State<'_, AppState>, id: String) -> R<Value> {
    state.atlas.mission_detail(&id)
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MissionIn {
    title: String,
    mode: atlas_core::sibling::missions::Mode,
    objective: String,
    shared_context: String,
    sibling_id: Option<String>,
    forge_project_id: Option<String>,
    conversation_id: Option<String>,
}

#[tauri::command]
fn mission_create(state: State<'_, AppState>, mission: MissionIn) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.mission_create(atlas_core::sibling::missions::NewMission {
        title: &mission.title,
        mode: mission.mode,
        objective: &mission.objective,
        shared_context: &mission.shared_context,
        sibling_id: mission.sibling_id.as_deref(),
        forge_project_id: mission.forge_project_id.as_deref(),
        conversation_id: mission.conversation_id.as_deref(),
    })
}

#[tauri::command]
fn mission_update(state: State<'_, AppState>, id: String, title: String, objective: String, shared_context: String, sibling_id: Option<String>) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.mission_update_draft(&id, &title, &objective, &shared_context, sibling_id.as_deref())
}

#[tauri::command]
fn mission_transition(state: State<'_, AppState>, id: String, to: atlas_core::sibling::missions::MissionState) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.mission_transition(&id, to)
}

/// The owner approved sending the mission's shown payload to the sibling.
#[tauri::command]
async fn mission_send(state: State<'_, AppState>, id: String) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.clone().mission_send(&id).await
}

#[tauri::command]
async fn mission_message(state: State<'_, AppState>, id: String, text: String) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.clone().mission_message(&id, &text).await
}

#[tauri::command]
async fn mission_accept(state: State<'_, AppState>, id: String, note: String) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.clone().mission_accept(&id, &note).await
}

#[tauri::command]
async fn mission_cancel(state: State<'_, AppState>, id: String) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.clone().mission_cancel(&id).await
}

#[tauri::command]
async fn mission_sync(state: State<'_, AppState>, id: String) -> R<atlas_core::sibling::missions::Mission> {
    state.atlas.clone().mission_sync(&id).await
}

#[tauri::command]
fn mission_note(state: State<'_, AppState>, id: String, text: String) -> R<()> {
    state.atlas.mission_note(&id, &text)
}

// ---------------- voice (local speech; no audio is stored or logged) ----------------

#[tauri::command]
fn voice_status(state: State<'_, AppState>) -> R<atlas_core::voice::VoiceStatus> {
    state.atlas.voice_status()
}

#[tauri::command]
async fn voice_install(state: State<'_, AppState>, id: String, on_progress: Channel<atlas_core::voice::download::Progress>) -> R<atlas_core::voice::VoiceStatus> {
    let atlas = state.atlas.clone();
    atlas
        .voice_install(&id, &mut |p| {
            let _ = on_progress.send(p);
        })
        .await
}

#[tauri::command]
fn voice_install_cancel(state: State<'_, AppState>, id: String) -> bool {
    state.atlas.voice_cancel_install(&id)
}

#[tauri::command]
fn voice_remove(state: State<'_, AppState>, id: String) -> R<atlas_core::voice::VoiceStatus> {
    state.atlas.voice_remove(&id)
}

#[tauri::command]
fn voice_verify(state: State<'_, AppState>, id: String) -> R<Vec<String>> {
    state.atlas.voice_verify(&id)
}

/// Returns a WAV file's bytes (binary response, not JSON).
#[tauri::command]
async fn voice_synthesize(state: State<'_, AppState>, text: String, speed: Option<f32>) -> R<tauri::ipc::Response> {
    let atlas = state.atlas.clone();
    let wav = atlas.voice_synthesize(&text, speed).await?;
    Ok(tauri::ipc::Response::new(wav))
}

#[tauri::command]
fn voice_stop_speech(state: State<'_, AppState>) {
    state.atlas.voice_stop_speech();
}

/// The body is the raw recording (16-bit little-endian samples); the `x-sample-rate` header gives
/// its rate. It is transcribed in memory and discarded.
#[tauri::command]
async fn voice_transcribe(state: State<'_, AppState>, request: tauri::ipc::Request<'_>) -> R<atlas_core::voice::stt::Transcript> {
    let tauri::ipc::InvokeBody::Raw(bytes) = request.body() else {
        return Err(AtlasError::Validation("the recording must be sent as raw audio".into()));
    };
    let rate = request
        .headers()
        .get("x-sample-rate")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<u32>().ok())
        .ok_or_else(|| AtlasError::Validation("the recording's sample rate is missing".into()))?;
    let atlas = state.atlas.clone();
    let bytes = bytes.clone();
    atlas.voice_transcribe(&bytes, rate).await
}

#[tauri::command]
fn voice_cancel_transcription(state: State<'_, AppState>) -> bool {
    state.atlas.voice_cancel_transcription()
}

#[tauri::command]
async fn voice_benchmark(state: State<'_, AppState>) -> R<atlas_core::voice::BenchmarkReport> {
    let atlas = state.atlas.clone();
    atlas.voice_benchmark().await
}
