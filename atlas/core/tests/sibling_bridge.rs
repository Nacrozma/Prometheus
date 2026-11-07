//! Cross-language test: Atlas's SiblingBridge against the real Prometheus-side adapter
//! (`sibling_adapter.py --test-backend --memory-secrets`) over loopback. Skipped (with a message)
//! when python3 is not available. No provider keys or network beyond 127.0.0.1 are used.

use atlas_core::credentials::MemorySecrets;
use atlas_core::events::RecordingBus;
use atlas_core::sibling::missions::{MissionState, Mode, NewMission};
use atlas_core::{Atlas, AtlasConfig};
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

struct Adapter {
    child: Child,
    port: u16,
    code: String,
    _dir: tempfile::TempDir,
}
impl Drop for Adapter {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn python() -> Option<&'static str> {
    ["python3", "python"].into_iter().find(|p| Command::new(p).arg("--version").output().map(|o| o.status.success()).unwrap_or(false))
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

fn start_adapter() -> Option<Adapter> {
    let py = python()?;
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../sibling_adapter.py");
    let dir = tempfile::tempdir().unwrap();
    let port = free_port();
    let mut child = Command::new(py)
        .arg("-u")
        .arg(&script)
        .args(["--test-backend", "--memory-secrets", "--pair", "--port", &port.to_string()])
        .env("PROMETHEUS_SIBLING_DIR", dir.path())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .ok()?;
    let out = child.stdout.take().unwrap();
    let mut lines = BufReader::new(out).lines();
    let mut code = None;
    for line in lines.by_ref() {
        let line = line.ok()?;
        if let Some(rest) = line.split("pairing code: ").nth(1) {
            code = Some(rest.split_whitespace().next()?.to_string());
            break;
        }
    }
    // Keep reading so the adapter's later log lines never hit a closed pipe.
    std::thread::spawn(move || for _ in lines {});
    Some(Adapter { child, port, code: code?, _dir: dir })
}

fn atlas() -> Arc<Atlas> {
    Atlas::new(AtlasConfig {
        db_path: None,
        secrets: Arc::new(MemorySecrets::default()),
        bus: Arc::new(RecordingBus::default()),
        factory: None,
        version: "test".into(),
        data_dir: None,
    })
    .unwrap()
}

async fn wait_for(a: &Atlas, id: &str, states: &[MissionState]) -> atlas_core::sibling::missions::Mission {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        let m = a.mission_sync(id).await.unwrap();
        if states.contains(&m.state) {
            return m;
        }
        assert!(Instant::now() < deadline, "mission stuck in {:?}", m.state);
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

#[tokio::test]
async fn pairing_discovery_missions_and_revocation_against_the_real_adapter() {
    let Some(ad) = start_adapter() else {
        eprintln!("skipping: python3 not available");
        return;
    };
    let a = atlas();
    let ep = format!("127.0.0.1:{}", ad.port);

    // A wrong code is refused and stores nothing.
    let e = a.sibling_pair(&ep, "AAAAA-AAAAA").await.unwrap_err();
    assert_eq!(e.code(), "permission_denied");
    assert!(a.siblings().unwrap().is_empty());

    // Real pairing, then verified HELLO / CAPABILITIES / HEALTH_CHECK.
    let s = a.sibling_pair(&ep, &ad.code).await.unwrap();
    assert!(s.connected, "connected only after a verified health check");
    assert!(s.test_peer, "the deterministic test backend is labelled as such");
    let tools = s.capabilities.as_ref().unwrap()["tools"].as_array().unwrap().clone();
    let shell = tools.iter().find(|t| t["name"] == "execute_shell").unwrap();
    assert_eq!(shell["dangerous"], true);
    assert_eq!(shell["available_to_siblings"], false);
    // The code was single-use.
    assert!(a.sibling_pair(&ep, &ad.code).await.is_err());

    // Consultation through the ledger (what sibling.consult does after approval).
    let r = a.consult("Is WAL mode safe for one writer?", "context line").await.unwrap();
    assert!(r["answer"].as_str().unwrap().contains("test backend"));
    let mid = r["mission_id"].as_str().unwrap();
    let detail = a.mission_detail(mid).unwrap();
    assert_eq!(detail["mission"]["state"], "COMPLETED");
    let kinds: Vec<String> = detail["events"].as_array().unwrap().iter().map(|e| e["kind"].as_str().unwrap().to_string()).collect();
    assert!(kinds.contains(&"approved".to_string()) && kinds.contains(&"message".to_string()), "{kinds:?}");

    // Collaborative engineering: owner drives the state machine; replies flow both ways.
    let m = a
        .mission_create(NewMission { title: "Parser review", mode: Mode::Collaborative, objective: "Review this parser change", shared_context: "fn parse() {}", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
        .unwrap();
    assert!(a.mission_send(&m.id).await.is_err(), "cannot send before planning and approval");
    a.mission_transition(&m.id, MissionState::Planned).unwrap();
    a.mission_transition(&m.id, MissionState::AwaitingApproval).unwrap();
    let sent = a.mission_send(&m.id).await.unwrap();
    assert_eq!(sent.state, MissionState::Running);
    wait_for(&a, &m.id, &[MissionState::NeedsUserInput]).await;
    a.mission_message(&m.id, "Here is version 2").await.unwrap();
    let m2 = wait_for(&a, &m.id, &[MissionState::NeedsUserInput]).await;
    let ev = atlas_core::sibling::missions::events(&a.db, &m.id).unwrap();
    assert!(ev.iter().any(|e| e.source == "atlas" && e.content == "Here is version 2"));
    assert!(ev.iter().filter(|e| e.source == "prometheus" && e.kind == "message").count() >= 2);
    assert!(m2.remote_seq >= 3);
    let done = a.mission_accept(&m.id, "Merged").await.unwrap();
    assert_eq!(done.state, MissionState::Completed);

    // Delegated: the sibling's refusal of its own dangerous tool is visible, then the result is reviewed.
    let d = a
        .mission_create(NewMission { title: "", mode: Mode::Delegated, objective: "Tidy the README", shared_context: "", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
        .unwrap();
    a.mission_transition(&d.id, MissionState::Planned).unwrap();
    a.mission_transition(&d.id, MissionState::AwaitingApproval).unwrap();
    a.mission_send(&d.id).await.unwrap();
    let rev = wait_for(&a, &d.id, &[MissionState::Reviewing]).await;
    assert_eq!(rev.result_summary.as_deref(), Some("[test backend] done"));
    let ev = atlas_core::sibling::missions::events(&a.db, &d.id).unwrap();
    assert!(ev.iter().any(|e| e.kind == "tool_result" && e.content.contains("refused")));

    // Idempotent re-send: simulate a send whose reply was lost (state back to awaiting approval).
    let x = a
        .mission_create(NewMission { title: "", mode: Mode::Consultation, objective: "Once only", shared_context: "", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
        .unwrap();
    a.mission_transition(&x.id, MissionState::Planned).unwrap();
    a.mission_transition(&x.id, MissionState::AwaitingApproval).unwrap();
    a.mission_send(&x.id).await.unwrap();
    a.db.conn().unwrap().execute("UPDATE missions SET state = 'AWAITING_APPROVAL' WHERE id = ?1", [&x.id]).unwrap();
    a.mission_send(&x.id).await.unwrap();
    let ev = atlas_core::sibling::missions::events(&a.db, &x.id).unwrap();
    assert!(ev.iter().any(|e| e.content.contains("not sent twice")), "a retry checks first and never starts the mission twice");

    // Cancellation of a running delegated mission.
    let c = a
        .mission_create(NewMission { title: "", mode: Mode::Delegated, objective: "slow job", shared_context: "", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
        .unwrap();
    a.mission_transition(&c.id, MissionState::Planned).unwrap();
    a.mission_transition(&c.id, MissionState::AwaitingApproval).unwrap();
    a.mission_send(&c.id).await.unwrap();
    assert_eq!(a.mission_cancel(&c.id).await.unwrap().state, MissionState::Cancelled);

    // Revocation on Atlas's side: secret deleted, further calls refused without network use.
    a.sibling_revoke(&s.id).unwrap();
    assert!(a.sibling_refresh(&s.id).await.map(|s| !s.connected).unwrap_or(true));
    let y = a
        .mission_create(NewMission { title: "", mode: Mode::Consultation, objective: "after revoke", shared_context: "", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
        .unwrap();
    a.mission_transition(&y.id, MissionState::Planned).unwrap();
    assert!(a.mission_transition(&y.id, MissionState::AwaitingApproval).is_err(), "unpaired siblings cannot be sent work");
}

#[tokio::test]
async fn atlas_keeps_working_when_the_sibling_goes_away() {
    let Some(mut ad) = start_adapter() else {
        eprintln!("skipping: python3 not available");
        return;
    };
    let a = atlas();
    let g0 = atlas().map_graph().unwrap();
    assert!(!g0.nodes.iter().any(|n| n.kind == "sibling"), "no Prometheus node without pairing");
    let s = a.sibling_pair(&format!("127.0.0.1:{}", ad.port), &ad.code).await.unwrap();
    assert!(s.connected);
    let sid = format!("sibling:{}", s.id);
    let g = a.map_graph().unwrap();
    assert!(g.nodes.iter().any(|n| n.id == sid && n.status == "ok"));
    assert!(g.edges.iter().any(|e| e.source == "core" && e.target == sid && e.kind == "sibling_link"));
    ad.child.kill().unwrap();
    ad.child.wait().unwrap();
    let after = a.sibling_refresh(&s.id).await.unwrap();
    assert!(!after.connected, "no fake green: an unreachable sibling is shown as not connected");
    assert!(after.last_error.unwrap().contains("not running"));
    let g = a.map_graph().unwrap();
    assert!(g.nodes.iter().any(|n| n.id == sid && n.status == "error"), "the node shows the outage");
    assert!(!g.edges.iter().any(|e| e.kind == "sibling_link"), "no link drawn without a live connection");
    a.sibling_revoke(&s.id).unwrap();
    assert!(!a.map_graph().unwrap().nodes.iter().any(|n| n.id == sid), "an unpaired sibling leaves the map");
    // Background sync tolerates the outage.
    a.sibling_sync_once().await;
    assert!(a.consult("still there?", "").await.is_err());
}
