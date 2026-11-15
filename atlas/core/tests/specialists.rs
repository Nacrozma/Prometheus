//! Specialists and orchestration through the real core: scripted model, routing, budgets,
//! dispatcher, approvals, the activity record, missions and the v9 upgrade.

use atlas_core::ai::mock::{MockProvider, Script};
use atlas_core::ai::{ChatProvider, ProviderKind};
use atlas_core::audit::{self, PageFilter};
use atlas_core::credentials::{MemorySecrets, SharedSecrets};
use atlas_core::engine::{TurnEvent, TurnParams};
use atlas_core::events::RecordingBus;
use atlas_core::providers::{ProviderConfig, ProviderFactory};
use atlas_core::specialists::{self, NewMission};
use atlas_core::storage::migrations;
use atlas_core::{Atlas, AtlasConfig};
use serde_json::json;
use std::sync::{Arc, Mutex};
use std::time::Duration;

struct Fixed(Arc<MockProvider>);
impl ProviderFactory for Fixed {
    fn build(&self, _c: &ProviderConfig, _s: &SharedSecrets, _t: Duration) -> atlas_core::error::Result<Arc<dyn ChatProvider>> {
        Ok(self.0.clone())
    }
}

struct H {
    atlas: Arc<Atlas>,
    mock: Arc<MockProvider>,
    conv: String,
    _data: tempfile::TempDir,
    _ws: tempfile::TempDir,
}

fn h(scripts: Vec<Script>) -> H {
    let mock = Arc::new(MockProvider::new(scripts));
    let data = tempfile::tempdir().unwrap();
    let atlas = Atlas::new(AtlasConfig {
        db_path: None,
        secrets: Arc::new(MemorySecrets::default()),
        bus: Arc::new(RecordingBus::default()),
        factory: Some(Arc::new(Fixed(mock.clone()))),
        version: "test".into(),
        data_dir: Some(data.path().to_path_buf()),
    })
    .unwrap();
    let p = atlas.add_provider(ProviderKind::Mock, "Mock", "http://mock.local", Some("mock-model")).unwrap();
    let ws = tempfile::tempdir().unwrap();
    atlas.ensure_workspace(ws.path()).unwrap();
    let mut s = atlas.settings().unwrap();
    s.default_provider_id = Some(p.id);
    s.limits.approval_timeout_secs = 15;
    atlas.update_settings(s).unwrap();
    let conv = atlas.create_conversation(None, "").unwrap().id;
    H { atlas, mock, conv, _data: data, _ws: ws }
}

fn result(summary: &str) -> Script {
    MockProvider::text(&json!({ "summary": summary, "findings": [format!("{summary} (finding)")], "evidence": [], "recommendations": ["Next step"] }).to_string())
}

async fn wait_done(a: &Atlas, id: &str) -> specialists::Mission {
    for _ in 0..400 {
        let m = specialists::get_mission(&a.db, id).unwrap();
        if !matches!(m.status.as_str(), "queued" | "running") {
            return m;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    panic!("mission did not finish");
}

fn mission<'a>(objective: &'a str, wf: &[&str]) -> NewMission<'a> {
    NewMission { objective, workflow: wf.iter().map(|s| s.to_string()).collect(), origin: "user", conversation_id: None, project_id: None, forge_project_id: None }
}

fn events(a: &Atlas) -> Vec<audit::AuditEvent> {
    audit::page(&a.db, &PageFilter { category: Some("specialists".into()), limit: Some(200), ..Default::default() }).unwrap()
}

#[tokio::test]
async fn a_two_specialist_workflow_passes_results_forward_and_is_fully_recorded() {
    let h = h(vec![result("Three sources agree the bridge opened in 1932"), result("Report drafted from the research")]);
    let m = h.atlas.start_mission(mission("Research when the harbour bridge opened and write a short report", &["researcher", "writer"])).unwrap();
    let done = wait_done(&h.atlas, &m.id).await;
    assert_eq!(done.status, "completed");
    assert_eq!(done.steps.iter().map(|s| s.status.as_str()).collect::<Vec<_>>(), ["completed", "completed"]);
    assert_eq!(done.steps[0].result.as_ref().unwrap().summary, "Three sources agree the bridge opened in 1932");
    assert_eq!(done.steps[0].provider.as_deref(), Some("Mock"));
    assert_eq!(done.steps[0].local, Some(true));
    // The writer received the researcher's result (bounded, quoted), and Atlas's specialist rules.
    let reqs = h.mock.requests.lock().unwrap().clone();
    assert!(reqs[1].messages[0].text().contains("<previous_result specialist=\"researcher\">"));
    assert!(reqs[1].messages[0].text().contains("1932"));
    assert!(reqs[0].system.contains("You are the Researcher specialist") && reqs[0].system.contains("cannot approve actions"));
    assert!(reqs[0].tools.iter().all(|t| ["web_search", "vault_search"].contains(&t.name.as_str())), "only the allowlist: {:?}", reqs[0].tools.iter().map(|t| &t.name).collect::<Vec<_>>());
    assert_eq!(done.steps[1].context_manifest["previous_results"][0], "researcher");
    // The activity record: started, invoked twice, completed twice, finished. No objective text.
    let e = events(&h.atlas);
    let kinds: Vec<&str> = e.iter().map(|x| x.kind.as_str()).collect();
    assert_eq!(kinds.iter().filter(|k| **k == "specialist.invoked").count(), 2);
    assert_eq!(kinds.iter().filter(|k| **k == "specialist.completed").count(), 2);
    assert!(kinds.contains(&"specialist.mission_started") && kinds.contains(&"specialist.mission_finished"));
    let inv = e.iter().find(|x| x.kind == "specialist.invoked").unwrap();
    assert_eq!((inv.provider.as_deref(), inv.left_device), (Some("Mock"), false));
    assert!(!serde_json::to_string(&e).unwrap().contains("harbour bridge"), "no objective text in the record");
    let req = audit::page(&h.atlas.db, &PageFilter { category: Some("providers".into()), limit: Some(50), ..Default::default() }).unwrap();
    assert_eq!(req.iter().filter(|x| x.resource.as_deref() == Some(m.id.as_str())).count(), 2, "model requests are attributed to the mission");
}

#[tokio::test]
async fn malformed_output_is_retried_once_then_reported_and_partial_results_survive() {
    let h = h(vec![
        result("Plan in three stages"),
        MockProvider::text("I think it is fine."),
        MockProvider::text("Still not JSON."),
    ]);
    let m = h.atlas.start_mission(mission("Plan the kitchen renovation and check it against my projects", &["planner", "project_coordinator"])).unwrap();
    let done = wait_done(&h.atlas, &m.id).await;
    assert_eq!(done.status, "partial", "one step failed, one result kept");
    assert_eq!(done.steps[0].status, "completed");
    assert_eq!(done.steps[1].status, "invalid_output");
    assert!(done.steps[1].result.is_none(), "malformed output is never shown as a result");
    assert!(done.error.as_deref().unwrap().contains("Project Coordinator"));
    assert!(events(&h.atlas).iter().any(|e| e.kind == "specialist.failed" && e.detail["status"] == "invalid_output"));
}

#[tokio::test]
async fn a_specialist_cannot_use_a_tool_outside_its_allowlist() {
    let h = h(vec![MockProvider::tool_call("c1", "files_create", json!({"path": "x.txt", "content": "x"})), result("Done without writing")]);
    let m = h.atlas.start_mission(mission("Coordinate the projects", &["project_coordinator"])).unwrap();
    let done = wait_done(&h.atlas, &m.id).await;
    assert_eq!(done.status, "completed");
    assert!(h.atlas.pending_approvals().unwrap().is_empty(), "no approval was even requested");
    let refused = events(&h.atlas).into_iter().find(|e| e.kind == "specialist.tool_refused").expect("refusal recorded");
    assert_eq!(refused.resource.as_deref(), Some("files.create"));
    let tool_msg = h.mock.requests.lock().unwrap()[1].messages.last().unwrap().clone();
    assert!(format!("{tool_msg:?}").contains("may not use files.create"));
}

#[tokio::test]
async fn a_specialist_write_waits_for_the_owner_and_cannot_approve_itself() {
    let h = h(vec![MockProvider::tool_call("c1", "files_create", json!({"path": "draft.md", "content": "# Draft"})), result("Draft saved")]);
    let m = h.atlas.start_mission(mission("Write a one-line draft and save it as draft.md", &["writer"])).unwrap();
    let mut approved = false;
    for _ in 0..300 {
        if let Some(a) = h.atlas.pending_approvals().unwrap().first() {
            let cur = specialists::get_mission(&h.atlas.db, &m.id).unwrap();
            assert!(cur.steps[0].awaiting_approval, "the mission shows it is waiting for the owner");
            h.atlas.decide_approval(&a.id, false).unwrap();
            approved = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(approved, "the write asked the owner");
    let done = wait_done(&h.atlas, &m.id).await;
    assert_eq!(done.status, "completed", "the specialist reported after being declined");
    assert!(!h._ws.path().join("draft.md").exists(), "declined: nothing written");
    assert!(audit::page(&h.atlas.db, &PageFilter { category: Some("approvals".into()), limit: Some(20), ..Default::default() }).unwrap().iter().any(|e| e.kind == "approval.decided" && e.actor == "user" && e.approval.as_deref() == Some("declined")));
}

#[tokio::test]
async fn least_context_memories_only_where_declared_and_vault_follows_scope_and_local_only() {
    let h = h(vec![result("plan"), result("status"), result("docs")]);
    h.atlas.create_memory(None, atlas_core::memory::MemoryKind::Preference, "Prefers to renovate kitchens in spring", false).unwrap();
    // Planner declares memories; coordinator does not.
    let m = h.atlas.start_mission(mission("Plan when to renovate kitchens", &["planner", "project_coordinator"])).unwrap();
    let done = wait_done(&h.atlas, &m.id).await;
    let reqs = h.mock.requests.lock().unwrap().clone();
    assert!(reqs[0].messages[0].text().contains("renovate kitchens in spring"));
    assert!(!reqs[1].messages[0].text().contains("renovate kitchens in spring"), "no unrelated personal memory for the coordinator");
    assert!(done.steps[0].context_manifest["memories"].is_array());
    assert!(done.steps[1].context_manifest.get("memories").is_none());
    assert_eq!(done.steps[1].context_manifest["tasks"], 0);
    assert_eq!(done.steps[1].context_manifest["projects"], 0);
    // Memory off: none.
    let mut s = h.atlas.settings().unwrap();
    s.memory.enabled = false;
    h.atlas.update_settings(s).unwrap();
    let m2 = h.atlas.start_mission(mission("Plan when to renovate kitchens again", &["document_analyst"])).unwrap();
    wait_done(&h.atlas, &m2.id).await;
    assert!(!h.mock.requests.lock().unwrap()[2].messages[0].text().contains("Prefers to renovate kitchens"));
}

#[tokio::test]
async fn cancelling_stops_the_mission_before_the_next_specialist() {
    let h = h(vec![MockProvider::tool_call("c1", "files_create", json!({"path": "a.md", "content": "a"})), result("never")]);
    let m = h.atlas.start_mission(mission("Write and save a.md", &["writer", "researcher"])).unwrap();
    for _ in 0..300 {
        if !h.atlas.pending_approvals().unwrap().is_empty() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(h.atlas.cancel_mission(&m.id).unwrap());
    let done = wait_done(&h.atlas, &m.id).await;
    assert_eq!(done.status, "cancelled");
    assert_eq!(done.steps[1].status, "cancelled", "the next specialist did not start");
    assert!(events(&h.atlas).iter().any(|e| e.kind == "specialist.mission_finished" && e.outcome == "cancelled"));
}

#[tokio::test]
async fn budgets_switches_and_validation_are_enforced_by_the_core() {
    let h = h(vec![]);
    // Unknown, duplicate, too many, forge without a project, switched off.
    assert!(specialists::create_mission(&h.atlas.db, &h.atlas.settings().unwrap(), mission("x y z", &["wizard"])).is_err());
    assert!(specialists::create_mission(&h.atlas.db, &h.atlas.settings().unwrap(), mission("x y z", &["writer", "writer"])).is_err());
    assert!(specialists::create_mission(&h.atlas.db, &h.atlas.settings().unwrap(), mission("x y z", &["engineer"])).unwrap_err().to_string().contains("Forge project"));
    h.atlas.specialist_set_enabled("writer", false).unwrap();
    assert_eq!(specialists::create_mission(&h.atlas.db, &h.atlas.settings().unwrap(), mission("x y z", &["writer"])).unwrap_err().code(), "permission_denied");
    let mut s = h.atlas.settings().unwrap();
    s.specialists.enabled = false;
    h.atlas.update_settings(s.clone()).unwrap();
    assert!(specialists::create_mission(&h.atlas.db, &s, mission("x y z", &["planner"])).is_err());
    // The consult tool is not offered and refuses when specialists are off.
    let tool = h.atlas.registry.get("specialist.consult").unwrap();
    let ctx = h.atlas.tool_context(s.clone(), None, None, tokio_util::sync::CancellationToken::new());
    assert!(matches!(tool.availability(&ctx), atlas_core::tools::Availability::Unavailable { .. }));
    // A daily request limit already reached stops a step before anything is sent.
    s.specialists.enabled = true;
    s.usage.daily_request_limit = Some(0);
    h.atlas.update_settings(s).unwrap();
    let m = h.atlas.start_mission(mission("Plan something small", &["planner"])).unwrap();
    let done = wait_done(&h.atlas, &m.id).await;
    assert_eq!(done.status, "failed");
    assert!(done.steps[0].error.as_deref().unwrap().starts_with("budget"), "{:?}", done.steps[0].error);
    assert!(h.mock.requests.lock().unwrap().is_empty(), "nothing was sent");
}

#[tokio::test]
async fn atlas_consults_specialists_in_a_conversation_and_answers_simple_questions_itself() {
    let h = h(vec![
        MockProvider::text("It is 4."),
        MockProvider::tool_call("c1", "specialist_consult", json!({"specialists": ["planner"], "objective": "Plan a two-week study schedule"})),
        result("Two weeks in four stages"),
        MockProvider::text("Here is the plan your Planner prepared."),
    ]);
    let send = |t: &str| {
        let a = h.atlas.clone();
        let c = h.conv.clone();
        let t = t.to_string();
        async move {
            let ev: Arc<Mutex<Vec<TurnEvent>>> = Arc::new(Mutex::new(vec![]));
            let e2 = ev.clone();
            a.send_message(TurnParams { conversation_id: c, text: t, ..Default::default() }, Box::new(move |e| e2.lock().unwrap().push(e))).await.unwrap();
            ev.lock().unwrap().len()
        }
    };
    send("What is 2 + 2?").await;
    assert!(specialists::list_missions(&h.atlas.db, 10).unwrap().is_empty(), "no specialist for a simple question");
    send("Make me a study plan for two weeks").await;
    let ms = specialists::list_missions(&h.atlas.db, 10).unwrap();
    assert_eq!(ms.len(), 1);
    assert_eq!((ms[0].origin.as_str(), ms[0].status.as_str(), ms[0].conversation_id.as_deref()), ("atlas", "completed", Some(h.conv.as_str())));
    // Atlas's conversation model received the structured result to review.
    let reqs = h.mock.requests.lock().unwrap().clone();
    assert!(format!("{:?}", reqs[3].messages.last().unwrap()).contains("Two weeks in four stages"));
    assert!(reqs[1].system.contains("Specialists (specialist.consult) are your team"));
}

#[test]
fn restart_marks_running_missions_interrupted_and_v9_upgrades_cleanly() {
    let data = tempfile::tempdir().unwrap();
    let db_path = data.path().join("atlas.db");
    {
        let db = atlas_core::storage::Db::open(&db_path).unwrap();
        let s = atlas_core::settings::Settings::default();
        let m = specialists::create_mission(&db, &s, mission("Something long", &["researcher", "writer"])).unwrap();
        db.conn().unwrap().execute("UPDATE specialist_missions SET status = 'running' WHERE id = ?1", [&m.id]).unwrap();
    }
    let atlas = Atlas::new(AtlasConfig { db_path: Some(db_path), secrets: Arc::new(MemorySecrets::default()), bus: Arc::new(RecordingBus::default()), factory: None, version: "t".into(), data_dir: Some(data.path().to_path_buf()) }).unwrap();
    let m = &specialists::list_missions(&atlas.db, 5).unwrap()[0];
    assert_eq!(m.status, "interrupted");
    assert!(m.steps.iter().all(|s| s.status == "interrupted"), "nothing resumed silently");

    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("PRAGMA foreign_keys = ON;").unwrap();
    migrations::apply_list(&conn, &migrations::MIGRATIONS[..8]).unwrap();
    conn.execute_batch("INSERT INTO memories(id,kind,content,source,created_at,updated_at) VALUES('m1','fact','Kept','user','t','t'); INSERT INTO audit_events(ts,kind,detail) VALUES('t','vault.import','{}');").unwrap();
    migrations::apply(&conn).unwrap();
    migrations::apply(&conn).unwrap();
    let one = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap();
    assert_eq!(one("PRAGMA user_version"), migrations::CURRENT_SCHEMA_VERSION);
    assert_eq!(one("SELECT COUNT(*) FROM memories") + one("SELECT COUNT(*) FROM audit_events"), 2);
    conn.execute_batch("INSERT INTO specialist_missions(id,title,objective,workflow,origin,status,created_at,updated_at) VALUES('x','t','o','[]','user','queued','t','t'); INSERT INTO specialist_steps(id,mission_id,seq,specialist_id,specialist_version,status) VALUES('s','x',0,'writer',1,'pending');").unwrap();
    assert!(conn.execute("INSERT INTO specialist_steps(id,mission_id,seq,specialist_id,specialist_version,status) VALUES('s2','x',0,'writer',1,'pending')", []).is_err(), "one step per position");
    conn.execute("DELETE FROM specialist_missions WHERE id='x'", []).unwrap();
    assert_eq!(one("SELECT COUNT(*) FROM specialist_steps"), 0);
}
