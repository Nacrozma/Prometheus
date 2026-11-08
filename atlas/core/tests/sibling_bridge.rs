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
    let found = ["python3", "python"].into_iter().find(|p| Command::new(p).arg("--version").output().map(|o| o.status.success()).unwrap_or(false));
    // CI always provides Python: there, a missing interpreter is a failure, never a silent skip.
    assert!(found.is_some() || std::env::var_os("CI").is_none(), "python is required for the cross-language tests in CI");
    found
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

/// Starts the real adapter. Returns `None` only when Python is not installed; any other failure
/// (crash, no pairing code, non-UTF-8 console output) fails the test instead of skipping it.
fn start_adapter() -> Option<Adapter> {
    let py = python()?;
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../sibling_adapter.py");
    let dir = tempfile::tempdir().unwrap();
    let port = free_port();
    let child = Command::new(py)
        .arg("-u")
        .arg(&script)
        .args(["--test-backend", "--memory-secrets", "--pair", "--port", &port.to_string()])
        .env("PROMETHEUS_SIBLING_DIR", dir.path())
        // Windows pipes default to the ANSI code page (cp1252), not UTF-8. Reproduce that on every
        // OS: the adapter must still write UTF-8 to a pipe.
        .env("PYTHONIOENCODING", "cp1252")
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("python is installed, so the adapter must start");
    let mut ad = Adapter { child, port, code: String::new(), _dir: dir };
    let mut reader = BufReader::new(ad.child.stdout.take().unwrap());
    let mut seen = String::new();
    let mut buf = Vec::new();
    loop {
        buf.clear();
        if reader.read_until(b'\n', &mut buf).unwrap_or(0) == 0 {
            panic!("the adapter exited without showing a pairing code; its output was:\n{seen}");
        }
        let line = String::from_utf8(buf.clone()).unwrap_or_else(|_| panic!("the adapter's console output must be UTF-8, got {:?}", String::from_utf8_lossy(&buf)));
        seen.push_str(&line);
        if let Some(rest) = line.split("pairing code: ").nth(1) {
            ad.code = rest.split_whitespace().next().expect("a code after 'pairing code:'").to_string();
            break;
        }
    }
    // Keep reading so the adapter's later log lines never hit a closed pipe.
    std::thread::spawn(move || {
        let mut sink = Vec::new();
        while reader.read_until(b'\n', &mut sink).map(|n| n > 0).unwrap_or(false) {
            sink.clear();
        }
    });
    Some(ad)
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

// ---------- Phase 7: recovery, approvals, isolation and reliability (real adapter, test backend) ----------

use atlas_core::ai::mock::MockProvider;
use atlas_core::ai::ChatProvider;
use atlas_core::credentials::SharedSecrets;
use atlas_core::engine::TurnParams;
use atlas_core::providers::{ProviderConfig, ProviderFactory};

struct Fixed(Arc<MockProvider>);
impl ProviderFactory for Fixed {
    fn build(&self, _c: &ProviderConfig, _s: &SharedSecrets, _t: Duration) -> atlas_core::error::Result<Arc<dyn ChatProvider>> {
        Ok(self.0.clone())
    }
}

fn atlas_with(db: Option<std::path::PathBuf>, secrets: SharedSecrets, mock: Option<Arc<MockProvider>>) -> Arc<Atlas> {
    Atlas::new(AtlasConfig {
        db_path: db,
        secrets,
        bus: Arc::new(RecordingBus::default()),
        factory: mock.map(|m| Arc::new(Fixed(m)) as Arc<dyn ProviderFactory>),
        version: "test".into(),
        data_dir: None,
    })
    .unwrap()
}

#[tokio::test]
async fn atlas_restart_during_a_mission_resumes_without_resending() {
    let Some(ad) = start_adapter() else { return };
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("atlas.db");
    let secrets: SharedSecrets = Arc::new(MemorySecrets::default());
    let a1 = atlas_with(Some(db.clone()), secrets.clone(), None);
    let s = a1.sibling_pair(&format!("127.0.0.1:{}", ad.port), &ad.code).await.unwrap();
    let m = a1
        .mission_create(NewMission { title: "", mode: Mode::Delegated, objective: "slow restart test", shared_context: "", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
        .unwrap();
    a1.mission_transition(&m.id, MissionState::Planned).unwrap();
    a1.mission_transition(&m.id, MissionState::AwaitingApproval).unwrap();
    a1.mission_send(&m.id).await.unwrap();
    drop(a1); // Atlas closes while the sibling is still working.
    let a2 = atlas_with(Some(db), secrets, None);
    assert_eq!(atlas_core::sibling::missions::get(&a2.db, &m.id).unwrap().state, MissionState::Running, "the ledger survived the restart");
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        a2.sibling_sync_once().await;
        if atlas_core::sibling::missions::get(&a2.db, &m.id).unwrap().state == MissionState::Reviewing {
            break;
        }
        assert!(Instant::now() < deadline, "mission never finished after restart");
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let ev = atlas_core::sibling::missions::events(&a2.db, &m.id).unwrap();
    assert_eq!(ev.iter().filter(|e| e.kind == "sent").count(), 1, "sent exactly once");
    assert_eq!(ev.iter().filter(|e| e.kind == "result").count(), 1, "result recorded once");
}

#[tokio::test]
async fn consulting_prometheus_needs_approval_and_shares_only_the_approved_text() {
    let Some(ad) = start_adapter() else { return };
    let mock = Arc::new(MockProvider::new(vec![
        MockProvider::tool_call("c1", "sibling_consult", serde_json::json!({"question": "Is WAL mode safe with one writer?", "context": "ONLY-THIS-CONTEXT"})),
        MockProvider::text("Prometheus answered."),
        MockProvider::tool_call("c2", "sibling_consult", serde_json::json!({"question": "Second question", "context": ""})),
        MockProvider::text("You declined."),
    ]));
    let a = atlas_with(None, Arc::new(MemorySecrets::default()), Some(mock.clone()));
    let p = a.add_provider(atlas_core::ai::ProviderKind::Mock, "Mock", "http://mock.local", Some("mock-model")).unwrap();
    let mut st = a.settings().unwrap();
    st.default_provider_id = Some(p.id);
    st.companion.custom_instructions = "PRIVATE-CUSTOM-INSTRUCTIONS: call me captain".into();
    a.update_settings(st).unwrap();
    a.create_memory(None, atlas_core::memory::MemoryKind::Fact, "PRIVATE-ATLAS-MEMORY: my bank PIN hint is the cat", true).unwrap();
    a.sibling_pair(&format!("127.0.0.1:{}", ad.port), &ad.code).await.unwrap();
    let conv = a.create_conversation(None, "").unwrap().id;

    let run = |approve: bool, text: &'static str| {
        let a = a.clone();
        let conv = conv.clone();
        async move {
            let h = {
                let a = a.clone();
                let conv = conv.clone();
                tokio::spawn(async move { a.send_message(TurnParams { conversation_id: conv, text: text.into(), ..Default::default() }, Box::new(|_| {})).await })
            };
            let mut preview = None;
            for _ in 0..300 {
                if let Some(ap) = a.pending_approvals().unwrap().first() {
                    preview = Some(ap.preview.clone());
                    a.decide_approval(&ap.id, approve).unwrap();
                    break;
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
            h.await.unwrap().unwrap();
            preview.expect("sharing with Prometheus asked for approval first")
        }
    };

    // Approved: exactly the question and context shown in the approval are sent; nothing else.
    let preview = run(true, "ask prometheus").await;
    assert!(preview.details.contains("Is WAL mode safe") && preview.details.contains("ONLY-THIS-CONTEXT"), "the approval shows exactly what is sent");
    let missions = a.missions().unwrap();
    assert_eq!(missions.len(), 1);
    let d = a.mission_detail(&missions[0].id).unwrap();
    assert_eq!(d["outgoing"]["objective"], "Is WAL mode safe with one writer?");
    assert_eq!(d["outgoing"]["context"], "ONLY-THIS-CONTEXT");
    assert!(!d.to_string().contains("PRIVATE-ATLAS-MEMORY"), "Atlas's private memory never enters a mission");
    assert!(!d.to_string().contains("PRIVATE-CUSTOM-INSTRUCTIONS"), "the owner's custom instructions never enter a mission");
    assert_eq!(d["mission"]["state"], "COMPLETED");
    // The model saw its own memory (Atlas's private context) but the sibling did not.
    {
        let reqs = mock.requests.lock().unwrap();
        assert!(serde_json::to_string(&reqs[0].messages).unwrap().contains("PRIVATE-ATLAS-MEMORY"));
        assert!(reqs[0].system.contains("PRIVATE-CUSTOM-INSTRUCTIONS"), "Atlas's own model does get them");
        let answer = serde_json::to_string(&reqs[1].messages.last().unwrap().parts).unwrap();
        assert!(answer.contains("test backend") && answer.contains("untrusted"), "the answer comes back attributed and marked untrusted");
    }

    // Declined: nothing is sent and no mission is created.
    run(false, "ask again").await;
    assert_eq!(a.missions().unwrap().len(), 1, "a declined consultation sends nothing");
}

#[tokio::test]
async fn repeated_pairing_consultations_and_cancellations_stay_stable() {
    if python().is_none() {
        return;
    }
    // Pair/unpair cycles: each needs a fresh adapter with a new one-time code.
    let a = atlas();
    for i in 0..5 {
        let ad = start_adapter().unwrap();
        let s = a.sibling_pair(&format!("127.0.0.1:{}", ad.port), &ad.code).await.unwrap();
        assert!(s.connected, "cycle {i}");
        a.sibling_revoke(&s.id).unwrap();
        a.sibling_forget(&s.id).unwrap();
    }
    assert!(a.siblings().unwrap().is_empty(), "no stale siblings after 5 pair/unpair cycles");

    let ad = start_adapter().unwrap();
    let rss = |pid: u32| std::fs::read_to_string(format!("/proc/{pid}/status")).ok().and_then(|s| s.lines().find(|l| l.starts_with("VmRSS")).map(|l| l.split_whitespace().nth(1).unwrap_or("0").parse::<u64>().unwrap_or(0)));
    let threads = |pid: u32| std::fs::read_to_string(format!("/proc/{pid}/status")).ok().and_then(|s| s.lines().find(|l| l.starts_with("Threads")).map(|l| l.split_whitespace().nth(1).unwrap_or("0").parse::<u64>().unwrap_or(0)));
    let pid = ad.child.id();
    let s = a.sibling_pair(&format!("127.0.0.1:{}", ad.port), &ad.code).await.unwrap();
    let start = Instant::now();
    for i in 0..25 {
        let r = a.consult(&format!("question {i}"), "").await.unwrap();
        assert!(r["answer"].as_str().unwrap().contains("test backend"));
    }
    let consult_ms = start.elapsed().as_millis() / 25;
    let rss_mid = rss(pid);
    for i in 0..25 {
        let m = a
            .mission_create(NewMission { title: "", mode: Mode::Delegated, objective: &format!("slow job {i}"), shared_context: "", sibling_id: Some(&s.id), forge_project_id: None, conversation_id: None })
            .unwrap();
        a.mission_transition(&m.id, MissionState::Planned).unwrap();
        a.mission_transition(&m.id, MissionState::AwaitingApproval).unwrap();
        a.mission_send(&m.id).await.unwrap();
        assert_eq!(a.mission_cancel(&m.id).await.unwrap().state, MissionState::Cancelled);
    }
    tokio::time::sleep(Duration::from_millis(2500)).await; // let cancelled workers wind down
    let all = a.missions().unwrap();
    assert_eq!(all.iter().filter(|m| m.state == MissionState::Completed).count(), 25);
    assert_eq!(all.iter().filter(|m| m.state == MissionState::Cancelled).count(), 25);
    assert!(!all.iter().any(|m| m.state == MissionState::Running), "nothing left claiming to run");
    let h = a.sibling_refresh(&s.id).await.unwrap();
    assert_eq!(h.health.unwrap()["active_missions"], 0, "the sibling has no runaway work after cancellations");
    println!(
        "reliability: 5 pair/unpair cycles; 25 consultations (avg {consult_ms} ms); 25 send+cancel; adapter RSS {:?} kB → {:?} kB; adapter threads now {:?}",
        rss_mid,
        rss(pid),
        threads(pid)
    );
    if let (Some(t), true) = (threads(pid), cfg!(target_os = "linux")) {
        assert!(t < 20, "adapter threads must not pile up after cancelled missions ({t})");
    }
}

#[tokio::test]
async fn secrets_never_reach_the_database_exports_or_backups() {
    let Some(ad) = start_adapter() else { return };
    let dir = tempfile::tempdir().unwrap();
    let secrets: SharedSecrets = Arc::new(MemorySecrets::default());
    let a = atlas_with(Some(dir.path().join("atlas.db")), secrets.clone(), None);
    let p = a.add_provider(atlas_core::ai::ProviderKind::Anthropic, "Claude", "https://api.anthropic.com", Some("claude-opus-5-5")).unwrap();
    let api_key = "sk-ant-api03-PHASE7SECRETVALUE-0123456789abcdef";
    a.set_provider_key(&p.id, api_key).unwrap();
    let s = a.sibling_pair(&format!("127.0.0.1:{}", ad.port), &ad.code).await.unwrap();
    a.consult("anything", "ctx").await.unwrap();
    let sibling_secret = secrets.get(&atlas_core::sibling::secret_account(&s.id)).unwrap().expect("secret stored in the credential store");
    // Everything Atlas writes for this profile: the database (+ WAL), a full export and a backup.
    a.backup_to(&dir.path().join("backup.db")).unwrap();
    std::fs::write(dir.path().join("export.json"), serde_json::to_string(&a.export_json().unwrap()).unwrap()).unwrap();
    let diag = a.diagnostics_report().await;
    std::fs::write(dir.path().join("diagnostics.json"), diag.to_string()).unwrap();
    for e in std::fs::read_dir(dir.path()).unwrap().flatten() {
        let bytes = std::fs::read(e.path()).unwrap();
        let text = String::from_utf8_lossy(&bytes);
        for (what, needle) in [("provider API key", api_key), ("API key body", "PHASE7SECRETVALUE"), ("sibling secret", sibling_secret.as_str())] {
            assert!(!text.contains(needle), "{what} found in {}", e.path().display());
        }
    }
}
