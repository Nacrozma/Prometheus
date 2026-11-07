//! Phase 7, Test C/D: Atlas against the REAL Prometheus runtime.
//!
//! The adapter runs with `PrometheusBackend` (it imports Prometheus's own prometheus.py: router, system
//! prompt, tool table, DANGEROUS_TOOLS, dispatch_tool and the real tools), from a disposable copy of the
//! Prometheus files so no real Prometheus state is touched. The only stand-in is the language model:
//! `tests/support/scripted_llm.py` answers on Ollama's port because no real model is reachable here.
//! Every reply it writes is tagged "[scripted stand-in LLM]".
//!
//! Needs python3 with Prometheus's core deps (openai, python-dotenv, numpy) and port 11434 free.
//!   cargo test -p atlas-core --test real_prometheus_runtime -- --ignored --nocapture --test-threads=1

use atlas_core::credentials::MemorySecrets;
use atlas_core::events::RecordingBus;
use atlas_core::sibling::missions::{self, MissionState, Mode, NewMission};
use atlas_core::{Atlas, AtlasConfig};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

const CANARY: &str = "PROMETHEUS-PRIVATE-CANARY-7f3a";

struct Proc(Child);
impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize().unwrap()
}

/// Disposable copy of Prometheus: every top-level .py file (prometheus.py, its modules, sibling_adapter.py).
fn prometheus_copy() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for e in std::fs::read_dir(repo_root()).unwrap().flatten() {
        let p = e.path();
        if p.extension().is_some_and(|x| x == "py") {
            std::fs::copy(&p, dir.path().join(p.file_name().unwrap())).unwrap();
        }
    }
    // A private file in Prometheus's own folder, standing in for its memory and notes.
    std::fs::write(dir.path().join("private_notes.txt"), format!("owner's private note: {CANARY}\n")).unwrap();
    dir
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

fn start_stub(log: &Path) -> Proc {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/support/scripted_llm.py");
    let mut c = Command::new("python3").arg("-u").arg(script).arg("11434").arg(log).stdout(Stdio::piped()).spawn().expect("python3");
    let mut l = String::new();
    BufReader::new(c.stdout.take().unwrap()).read_line(&mut l).unwrap();
    assert!(l.contains("listening"), "stub did not start: {l}");
    Proc(c)
}

/// Start the real adapter (real backend). Returns the process and the pairing code if `pair`.
fn start_adapter(copy: &Path, state: &Path, port: u16, pair: bool) -> (Proc, Option<String>, Vec<String>) {
    let mut cmd = Command::new("python3");
    cmd.arg("-u").arg(copy.join("sibling_adapter.py")).args(["--port", &port.to_string(), "--allow-file-secret"]);
    if pair {
        cmd.arg("--pair");
    }
    let mut c = cmd.current_dir(copy).env("PROMETHEUS_SIBLING_DIR", state).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().unwrap();
    let out = c.stdout.take().unwrap();
    let mut lines = BufReader::new(out).lines();
    let mut seen = vec![];
    let mut code = None;
    let deadline = Instant::now() + Duration::from_secs(90);
    for line in lines.by_ref() {
        let line = line.unwrap_or_default();
        seen.push(line.clone());
        if let Some(rest) = line.split("pairing code: ").nth(1) {
            code = rest.split_whitespace().next().map(str::to_string);
            break;
        }
        if !pair && line.contains("listening on 127.0.0.1") {
            break;
        }
        assert!(Instant::now() < deadline, "adapter did not start");
    }
    std::thread::spawn(move || for _ in lines {});
    (Proc(c), code, seen)
}

fn atlas() -> Arc<Atlas> {
    Atlas::new(AtlasConfig { db_path: None, secrets: Arc::new(MemorySecrets::default()), bus: Arc::new(RecordingBus::default()), factory: None, version: "phase7".into(), data_dir: None }).unwrap()
}

async fn wait(a: &Atlas, id: &str, states: &[MissionState], secs: u64) -> missions::Mission {
    let deadline = Instant::now() + Duration::from_secs(secs);
    loop {
        if let Ok(m) = a.mission_sync(id).await
            && states.contains(&m.state) {
                return m;
            }
        let m = missions::get(&a.db, id).unwrap();
        if states.contains(&m.state) {
            return m;
        }
        assert!(Instant::now() < deadline, "mission stuck in {:?} (want {states:?})", m.state);
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

fn stub_requests(log: &Path) -> Vec<serde_json::Value> {
    std::fs::read_to_string(log).unwrap_or_default().lines().filter_map(|l| serde_json::from_str(l).ok()).collect()
}

fn send_mission(a: &Atlas, sid: &str, mode: Mode, objective: &str) -> String {
    send_mission_ctx(a, sid, mode, objective, "")
}

fn send_mission_ctx(a: &Atlas, sid: &str, mode: Mode, objective: &str, ctx: &str) -> String {
    let m = a.mission_create(NewMission { title: "", mode, objective, shared_context: ctx, sibling_id: Some(sid), forge_project_id: None, conversation_id: None }).unwrap();
    a.mission_transition(&m.id, MissionState::Planned).unwrap();
    a.mission_transition(&m.id, MissionState::AwaitingApproval).unwrap();
    m.id
}

#[tokio::test]
#[ignore = "runs the real Prometheus runtime (needs its Python deps and port 11434)"]
async fn atlas_with_the_real_prometheus_runtime() {
    let copy = prometheus_copy();
    let state = tempfile::tempdir().unwrap();
    let logdir = tempfile::tempdir().unwrap();
    let log = logdir.path().join("model-requests.jsonl");
    let _stub = start_stub(&log);
    let port = free_port();
    let (adapter, code, startup) = start_adapter(copy.path(), state.path(), port, true);
    let code = code.unwrap_or_else(|| panic!("no pairing code; adapter output: {startup:?}"));
    println!("adapter startup:\n  {}", startup.join("\n  "));
    let a = atlas();

    // --- C: pairing, discovery and health against the real runtime.
    let s = a.sibling_pair(&format!("127.0.0.1:{port}"), &code).await.unwrap();
    assert!(s.connected && !s.test_peer, "paired with the real backend, not the test backend");
    assert_eq!(s.name, "Prometheus");
    let caps = s.capabilities.clone().unwrap();
    let reported: Vec<String> = caps["tools"].as_array().unwrap().iter().map(|t| t["name"].as_str().unwrap().to_string()).collect();
    let real = Command::new("python3")
        .args(["-c", "import prometheus as P; print('\\n'.join(t['function']['name'] for t in P.TOOLS))"])
        .current_dir(copy.path())
        .output()
        .unwrap();
    let real: Vec<String> = String::from_utf8_lossy(&real.stdout).lines().filter(|l| !l.trim().is_empty()).map(str::to_string).collect();
    let real_tail: Vec<String> = real.iter().rev().take(reported.len()).rev().cloned().collect();
    assert_eq!(reported, real_tail, "capabilities are Prometheus's real tool table");
    assert_eq!(caps["providers"], serde_json::json!(["ollama"]), "providers reported by the real router");
    println!("discovered {} real tools; providers {}; health {}", reported.len(), caps["providers"], s.health.clone().unwrap());

    // --- D-A: consultation reaches the real router and comes back attributed to Prometheus.
    let r = a.consult("PHASE7 consultation: is SQLite WAL safe with one writer?", "shared line A").await.unwrap();
    assert!(r["answer"].as_str().unwrap().starts_with("[scripted stand-in LLM]"));
    let reqs = stub_requests(&log);
    let sys = reqs.last().unwrap()["messages"][0]["content"].as_str().unwrap().to_string();
    assert!(sys.contains("ATLAS Co-Pilot") && sys.contains("PROMETHEUS"), "Prometheus's own system prompt (with the sibling preface) was used");
    let user = reqs.last().unwrap()["messages"][1]["content"].as_str().unwrap().to_string();
    assert!(user.contains("PHASE7 consultation") && user.contains("shared line A"), "exactly the approved question and context reached the model");
    println!("consultation answer: {}", r["answer"]);

    // --- D-C: delegated mission runs a REAL tool and the REAL dangerous-tool gate.
    let d = send_mission(&a, &s.id, Mode::Delegated, "DELEGATE-TEST compute an orbit");
    a.mission_send(&d).await.unwrap();
    let done = wait(&a, &d, &[MissionState::Reviewing, MissionState::Failed], 60).await;
    let ev = missions::events(&a.db, &d).unwrap();
    for e in &ev {
        println!("  [{}:{}] {}", e.source, e.kind, e.content.chars().take(220).collect::<String>());
    }
    assert_eq!(done.state, MissionState::Reviewing, "a sibling's result waits for review: {:?}", done.result_summary);
    let calc = ev.iter().find(|e| e.kind == "tool_result" && e.content.contains("engineering_calc")).expect("real engineering_calc ran");
    let expect = Command::new("python3")
        .args(["-c", "import engineering, json; r=engineering.calculate('circular_orbit', altitude_m=400000); print(json.dumps(r))"])
        .current_dir(copy.path())
        .output()
        .unwrap();
    let expect: serde_json::Value = serde_json::from_slice(&expect.stdout).unwrap();
    let speed = expect["results"]["speed_m_s"].to_string();
    assert!(calc.content.contains(&speed[..6.min(speed.len())]), "the tool result is the real calculator's output ({speed})");
    let shell = ev.iter().find(|e| e.kind == "tool_result" && e.content.contains("execute_shell")).expect("shell attempt reported");
    assert!(shell.content.contains("refused"), "the real DANGEROUS_TOOLS gate refused execute_shell: {}", shell.content);
    assert!(!ev.iter().any(|e| e.content.contains("SHOULD-NOT-RUN") && e.kind == "tool_result" && !e.content.contains("refused")));

    // --- Security: a delegated mission must not read Prometheus's private files or memory.
    let l = send_mission_ctx(&a, &s.id, Mode::Delegated, "LEAK-TEST look around", "SHARED-CONTEXT-OK: the parser lives in src/parse.rs");
    a.mission_send(&l).await.unwrap();
    wait(&a, &l, &[MissionState::Reviewing, MissionState::Failed], 60).await;
    let leak_ev = missions::events(&a.db, &l).unwrap();
    for e in &leak_ev {
        println!("  leak-test [{}:{}] {}", e.source, e.kind, e.content.chars().take(220).collect::<String>());
    }
    assert!(!leak_ev.iter().any(|e| e.content.contains(CANARY)), "Prometheus's private data reached Atlas");
    let summary = missions::get(&a.db, &l).unwrap().result_summary.unwrap_or_default();
    assert!(!summary.contains(CANARY), "Prometheus's private data reached Atlas in the result");
    let results: Vec<&str> = leak_ev.iter().filter(|e| e.kind == "tool_result").map(|e| e.content.as_str()).collect();
    assert_eq!(results.len(), 7, "every attempt was answered: {results:#?}");
    assert!(results[1].contains("outside this mission"), "traversal refused: {}", results[1]);
    assert!(results[2].contains("outside this mission"), "absolute path refused: {}", results[2]);
    for (i, tool) in [(3, "recall_memory"), (4, "update_memory"), (5, "web_search")] {
        assert!(results[i].contains("not available to sibling missions"), "{tool} refused: {}", results[i]);
    }
    assert!(results[6].contains("SHARED-CONTEXT-OK"), "the mission workspace works for the shared context: {}", results[6]);
    let memory_written = std::fs::read_to_string(copy.path().join("memory.json")).unwrap_or_default();
    assert!(!memory_written.contains("Atlas wrote this"), "nothing was written into Prometheus's memory");

    // --- Disconnect, restart and reconnect without re-running anything.
    let c = send_mission(&a, &s.id, Mode::Collaborative, "PHASE7 collaborative review");
    a.mission_send(&c).await.unwrap();
    wait(&a, &c, &[MissionState::NeedsUserInput], 60).await;
    let before = stub_requests(&log).iter().filter(|r| r.to_string().contains("PHASE7 collaborative review")).count();
    drop(adapter);
    let s2 = a.sibling_refresh(&s.id).await.unwrap();
    assert!(!s2.connected, "disconnect detected");
    // NEEDS_USER_INPUT is not polled; move it to RUNNING as a reply would, then let background sync notice the loss.
    a.db.conn().unwrap().execute("UPDATE missions SET state = 'RUNNING' WHERE id = ?1", [&c]).unwrap();
    a.sibling_sync_once().await;
    let lost = missions::get(&a.db, &c).unwrap();
    assert_eq!((lost.state, lost.remote_state.as_deref()), (MissionState::Paused, Some("unreachable")), "not left falsely running");
    let (adapter2, _, _) = start_adapter(copy.path(), state.path(), port, false);
    let s3 = a.sibling_refresh(&s.id).await.unwrap();
    assert!(s3.connected, "reconnected with the stored pairing (file secret store, explicitly allowed)");
    a.sibling_sync_once().await;
    let after = missions::get(&a.db, &c).unwrap();
    assert_eq!(after.remote_state.as_deref(), Some("interrupted"), "the restarted adapter reports the mission honestly");
    assert_eq!(after.state, MissionState::Paused);
    let after_count = stub_requests(&log).iter().filter(|r| r.to_string().contains("PHASE7 collaborative review")).count();
    assert_eq!(before, after_count, "nothing was re-run after the restart");

    // --- Revocation on the Prometheus side invalidates the old credentials immediately.
    let out = Command::new("python3")
        .arg(copy.path().join("sibling_adapter.py"))
        .args(["--revoke", &s.id, "--allow-file-secret"])
        .env("PROMETHEUS_SIBLING_DIR", state.path())
        .current_dir(copy.path())
        .output()
        .unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let e = a.consult("after revoke", "").await.unwrap_err();
    println!("after revocation: {e}");
    assert!(e.to_string().contains("no longer accepts"), "{e}");
    drop(adapter2);
}
