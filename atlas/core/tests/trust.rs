//! Memory quality and the Trust Center, through the real core: turns with a scripted model, the
//! dispatcher and its approvals, the audit log, the overview, and the v8 upgrade.

use atlas_core::ai::mock::MockProvider;
use atlas_core::ai::{ChatProvider, ProviderKind};
use atlas_core::audit::{self, PageFilter};
use atlas_core::credentials::{MemorySecrets, SharedSecrets};
use atlas_core::engine::{TurnEvent, TurnParams};
use atlas_core::events::RecordingBus;
use atlas_core::memory::{self, MemoryKind};
use atlas_core::providers::{ProviderConfig, ProviderFactory};
use atlas_core::storage::{migrations, Db};
use atlas_core::tools::builtin::test_tools::Fetch;
use atlas_core::{Atlas, AtlasConfig};
use serde_json::json;
use std::sync::atomic::{AtomicUsize, Ordering};
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
    fetched: Arc<AtomicUsize>,
    _data: tempfile::TempDir,
    _ws: tempfile::TempDir,
}

fn h(scripts: Vec<atlas_core::ai::mock::Script>) -> H {
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
    let fetched = Arc::new(AtomicUsize::new(0));
    atlas.registry.register(Arc::new(Fetch::new(fetched.clone()))).unwrap();
    let p = atlas.add_provider(ProviderKind::Mock, "Mock", "http://mock.local", Some("mock-model")).unwrap();
    let ws = tempfile::tempdir().unwrap();
    atlas.ensure_workspace(ws.path()).unwrap();
    let mut s = atlas.settings().unwrap();
    s.default_provider_id = Some(p.id);
    s.limits.approval_timeout_secs = 15;
    atlas.update_settings(s).unwrap();
    let conv = atlas.create_conversation(None, "").unwrap().id;
    H { atlas, mock, conv, fetched, _data: data, _ws: ws }
}

type Events = Arc<Mutex<Vec<TurnEvent>>>;

async fn turn(h: &H, text: &str) -> Vec<TurnEvent> {
    let events: Events = Arc::new(Mutex::new(vec![]));
    let e2 = events.clone();
    h.atlas
        .send_message(TurnParams { conversation_id: h.conv.clone(), text: text.into(), ..Default::default() }, Box::new(move |e| e2.lock().unwrap().push(e)))
        .await
        .unwrap();
    events.lock().unwrap().clone()
}

/// Run a turn in the background, run `while_waiting` when its approval appears, then decide it.
async fn turn_with_approval(h: &H, text: &str, approve: bool, while_waiting: impl FnOnce(&Atlas)) {
    let atlas = h.atlas.clone();
    let conv = h.conv.clone();
    let text = text.to_string();
    let handle = tokio::spawn(async move { atlas.send_message(TurnParams { conversation_id: conv, text, ..Default::default() }, Box::new(|_| {})).await });
    let mut f = Some(while_waiting);
    for _ in 0..300 {
        if let Some(a) = h.atlas.pending_approvals().unwrap().first() {
            if let Some(f) = f.take() {
                f(&h.atlas);
            }
            h.atlas.decide_approval(&a.id, approve).unwrap();
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(f.is_none(), "an approval prompt was expected");
    handle.await.unwrap().unwrap();
}

fn events(atlas: &Atlas) -> Vec<audit::AuditEvent> {
    audit::page(&atlas.db, &PageFilter { limit: Some(200), ..Default::default() }).unwrap()
}

#[tokio::test]
async fn memories_used_in_a_turn_carry_provenance_and_are_recorded_without_their_text() {
    let h = h(vec![MockProvider::text("Noted."), MockProvider::text("Noted again.")]);
    let m = h.atlas.create_memory(None, MemoryKind::Preference, "Prefers answers in metric units with short explanations", false).unwrap();
    let ev = turn(&h, "Which units should the bridge measurements use?").await;
    assert!(ev.iter().any(|e| matches!(e, TurnEvent::Started { memories, .. } if memories.len() == 1)));
    let sent = h.mock.requests.lock().unwrap()[0].messages[0].text();
    assert!(sent.contains("[preference, added by you, confirmed "), "provenance goes with the memory: {sent}");
    assert!(sent.contains("overrides them"), "the current message wins over memories");

    let used = events(&h.atlas).into_iter().find(|e| e.kind == "memory.used").expect("memory use is recorded");
    assert_eq!(used.provider.as_deref(), Some("Mock"));
    assert_eq!(used.model.as_deref(), Some("mock-model"));
    assert!(!used.left_device, "the mock model runs on this computer");
    assert_eq!(used.detail["memories"][0], m.id);
    let req = events(&h.atlas).into_iter().find(|e| e.kind == "provider.request").expect("the model request is recorded");
    assert_eq!((req.provider.as_deref(), req.left_device), (Some("Mock"), false));
    assert_eq!(req.detail["cost_is_estimate"], true);
    let all = serde_json::to_string(&events(&h.atlas)).unwrap();
    assert!(!all.contains("metric units"), "no memory text in the activity log");
    assert!(!all.contains("bridge measurements"), "no message text in the activity log");

    // Outdated: not used. Restored and corrected: the corrected text is used.
    h.atlas.mark_memory_outdated(&m.id).unwrap();
    turn(&h, "Which units should the bridge measurements use?").await;
    assert!(!h.mock.requests.lock().unwrap()[1].messages.last().unwrap().text().contains("metric"), "outdated memories are not sent");
}

#[tokio::test]
async fn a_correction_replaces_what_is_used_and_the_old_version_stays_visible() {
    let h = h(vec![MockProvider::text("a"), MockProvider::text("b")]);
    let old = h.atlas.create_memory(None, MemoryKind::Fact, "The team standup is at 9:30 every weekday", false).unwrap();
    let new = h.atlas.replace_memory(&old.id, "The team standup is at 10:00 every weekday").unwrap();
    turn(&h, "When is the team standup?").await;
    let sent = h.mock.requests.lock().unwrap()[0].messages[0].text();
    assert!(sent.contains("10:00") && !sent.contains("9:30"), "only the current version is used: {sent}");
    let o = memory::get(&h.atlas.db, &old.id).unwrap();
    assert_eq!((o.status.as_str(), o.superseded_by.as_deref()), ("superseded", Some(new.id.as_str())));
    assert!(events(&h.atlas).iter().any(|e| e.kind == "memory.replaced" && e.actor == "user"));
    // Duplicates are refused rather than piling up.
    assert_eq!(h.atlas.create_memory(None, MemoryKind::Fact, "the team standup is at 10:00 every weekday.", false).unwrap_err().code(), "conflict");
}

#[tokio::test]
async fn atlas_proposals_need_approval_can_replace_and_can_be_switched_off() {
    let h = h(vec![
        MockProvider::tool_call("c1", "memory_save", json!({"content": "Prefers window seats on trains", "kind": "preference"})),
        MockProvider::text("Saved."),
    ]);
    turn_with_approval(&h, "Remember that I like window seats on trains", true, |_| {}).await;
    let saved = h.atlas.memories(None).unwrap();
    assert_eq!(saved.len(), 1);
    assert_eq!(saved[0].source, "assistant");
    assert_eq!(saved[0].conversation_id.as_deref(), Some(h.conv.as_str()), "it records where it was saved");
    let e = events(&h.atlas);
    assert!(e.iter().any(|x| x.kind == "approval.requested" && x.resource.as_deref() == Some("memory.save")));
    assert!(e.iter().any(|x| x.kind == "approval.decided" && x.approval.as_deref() == Some("approved") && x.actor == "user"));
    assert!(e.iter().any(|x| x.kind == "memory.created" && x.actor == "assistant" && x.approval.as_deref() == Some("approved")));

    // A proposal that replaces the earlier one.
    let first = saved[0].id.clone();
    let h2_scripts = vec![
        MockProvider::tool_call("c2", "memory_save", json!({"content": "Prefers aisle seats on trains now", "kind": "preference", "replaces": first})),
        MockProvider::text("Updated."),
    ];
    h.mock.scripts.lock().unwrap().extend(h2_scripts);
    turn_with_approval(&h, "Actually I prefer aisle seats now", true, |_| {}).await;
    assert_eq!(memory::get(&h.atlas.db, &first).unwrap().status, "superseded");

    // Switched off: not offered, and refused even if called.
    let mut s = h.atlas.settings().unwrap();
    s.memory.atlas_may_propose = false;
    h.atlas.update_settings(s.clone()).unwrap();
    let tool = h.atlas.registry.get("memory.save").unwrap();
    let ctx = h.atlas.tool_context(s, None, None, tokio_util::sync::CancellationToken::new());
    assert!(matches!(tool.availability(&ctx), atlas_core::tools::Availability::Unavailable { .. }));
    assert!(tool.execute(json!({"content": "Anything", "kind": "note"}), &ctx).await.is_err());
    assert_eq!(h.atlas.memories(None).unwrap().len(), 2);
}

#[tokio::test]
async fn a_permission_revoked_while_an_approval_waits_still_stops_the_action() {
    let h = h(vec![MockProvider::tool_call("c1", "test_fetch", json!({"url": "https://example.com"})), MockProvider::text("Could not.")]);
    // The owner approves, but turned on offline mode while the prompt was open.
    turn_with_approval(&h, "Fetch example.com", true, |atlas| {
        let mut s = atlas.settings().unwrap();
        s.network.offline_mode = true;
        atlas.update_settings(s).unwrap();
    })
    .await;
    assert_eq!(h.fetched.load(Ordering::SeqCst), 0, "nothing was fetched");
    let step = events(&h.atlas).into_iter().find(|e| e.kind == "tool.step").unwrap();
    assert_eq!(step.outcome, "denied");
    assert!(!step.left_device);
}

#[tokio::test]
async fn the_next_action_follows_the_settings_as_they_are_now() {
    // Allowed without asking, then the owner tightens it: the very next call asks.
    let h = h(vec![
        MockProvider::tool_call("c1", "test_fetch", json!({"url": "https://a"})),
        MockProvider::text("ok"),
        MockProvider::tool_call("c2", "test_fetch", json!({"url": "https://b"})),
        MockProvider::text("ok"),
    ]);
    let mut s = h.atlas.settings().unwrap();
    s.permissions.network_tools = atlas_core::settings::GatePolicy::Allow;
    h.atlas.update_settings(s).unwrap();
    turn(&h, "fetch a").await;
    assert_eq!(h.fetched.load(Ordering::SeqCst), 1);
    let e = events(&h.atlas).into_iter().find(|e| e.kind == "tool.step").unwrap();
    assert!(e.left_device, "an internet tool that ran is recorded as data leaving this computer");
    assert_eq!(e.approval.as_deref(), Some("not_needed"));
    let mut s = h.atlas.settings().unwrap();
    s.permissions.network_tools = atlas_core::settings::GatePolicy::Ask;
    h.atlas.update_settings(s).unwrap();
    turn_with_approval(&h, "fetch b", false, |_| {}).await;
    assert_eq!(h.fetched.load(Ordering::SeqCst), 1, "declined: not fetched");
}

#[tokio::test]
async fn the_overview_reflects_real_records_and_settings() {
    let h = h(vec![MockProvider::text("hello")]);
    turn(&h, "hi").await;
    let o = h.atlas.trust_overview().unwrap();
    let p = &o["providers"][0];
    assert_eq!((p["label"].as_str(), p["requests_30d"].as_i64(), p["local"].as_bool()), (Some("Mock"), Some(1), Some(true)));
    let perms = o["permissions"].as_array().unwrap();
    let get = |id: &str| perms.iter().find(|x| x["id"] == id).cloned().unwrap();
    assert_eq!(get("local_write")["status"], "Asks you each time");
    assert_eq!(get("offline_mode")["control"]["setting"], "network.offline_mode");
    assert!(perms.iter().any(|x| x["control"]["kind"] == "provider"));
    assert_eq!(o["background"]["pending_approvals"], 0);
    assert_eq!(o["left_device_7d"], 0, "everything stayed on this computer");
    let mut s = h.atlas.settings().unwrap();
    s.permissions.local_write = atlas_core::settings::GatePolicy::Allow;
    h.atlas.update_settings(s).unwrap();
    let o = h.atlas.trust_overview().unwrap();
    let lw = o["permissions"].as_array().unwrap().iter().find(|x| x["id"] == "local_write").cloned().unwrap();
    assert_eq!((lw["status"].as_str(), lw["open"].as_bool()), (Some("Allowed without asking"), Some(true)));
}

#[test]
fn upgrading_a_v7_database_keeps_memories_and_classifies_old_events() {
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("PRAGMA foreign_keys = ON;").unwrap();
    migrations::apply_list(&conn, &migrations::MIGRATIONS[..7]).unwrap();
    conn.execute_batch(
        "INSERT INTO memories(id,kind,content,source,created_at,updated_at) VALUES('m1','fact','Kept fact','user','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');
         INSERT INTO audit_events(ts,kind,level,detail) VALUES('2026-01-01T00:00:00Z','vault.import','info','{}'),('2026-01-01T00:00:00Z','tool.step','warn','{}');
         INSERT INTO vault_documents(id,title,file_name,stored_name,kind,size_bytes,content_hash,status,imported_at,updated_at) VALUES('d1','T','t.txt','d1.txt','txt',1,'h','indexed','t','t');",
    )
    .unwrap();
    migrations::apply(&conn).unwrap();
    migrations::apply(&conn).unwrap();
    let one = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap();
    assert_eq!(one("PRAGMA user_version"), migrations::CURRENT_SCHEMA_VERSION);
    assert_eq!(one("SELECT COUNT(*) FROM memories WHERE id='m1' AND status='active' AND confirmed_at='2026-01-01T00:00:00Z'"), 1, "memories kept, confirmed when created");
    assert_eq!(one("SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'kept'"), 1, "their index still works");
    assert_eq!(one("SELECT COUNT(*) FROM audit_events WHERE kind='vault.import' AND category='knowledge' AND outcome='ok'"), 1);
    assert_eq!(one("SELECT COUNT(*) FROM audit_events WHERE kind='tool.step' AND category='tools' AND outcome='warning'"), 1);
    assert_eq!(one("SELECT COUNT(*) FROM vault_documents"), 1);
    conn.execute("INSERT INTO memory_history(id,memory_id,ts,action,actor) VALUES('h1','m1','t','created','user')", []).unwrap();
    conn.execute("DELETE FROM memories WHERE id='m1'", []).unwrap();
    assert_eq!(one("SELECT COUNT(*) FROM memory_history"), 0, "history goes with the memory");
    assert!(conn.execute("UPDATE memories SET status='weird'", []).is_ok(), "no rows left to violate");
}

#[test]
fn scale_thousands_of_events_and_memories_stay_fast() {
    let db = Db::open_in_memory().unwrap();
    let t = std::time::Instant::now();
    for i in 0..5000 {
        audit::event(&db, audit::Event { kind: if i % 3 == 0 { "provider.request" } else { "tool.step" }, provider: Some("Cloud"), left_device: i % 3 == 0, ..Default::default() });
    }
    let write_ms = t.elapsed().as_millis();
    let t = std::time::Instant::now();
    let first = audit::page(&db, &PageFilter { left_device_only: true, limit: Some(50), ..Default::default() }).unwrap();
    let page_ms = t.elapsed().as_micros();
    assert_eq!(first.len(), 50);
    for i in 0..2000 {
        memory::create(&db, None, MemoryKind::Note, &format!("Note number {i} about the {} project and its {} milestone", ["harbour", "orchard", "lighthouse", "quarry"][i % 4], ["first", "second", "third"][i % 3]), "user", false).unwrap();
    }
    let t = std::time::Instant::now();
    let r = memory::search(&db, "lighthouse project second milestone", None, 6).unwrap();
    let search_ms = t.elapsed().as_millis();
    assert_eq!(r.len(), 6);
    eprintln!("measured: 5000 audit events written in {write_ms} ms; one filtered page in {page_ms} µs; memory search over 2000 in {search_ms} ms");
}
