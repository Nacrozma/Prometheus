//! ORBIT for Atlas: sessions, structured plans with versions, workflows and their execution states.
//!
//! Atlas's own implementation (it shares nothing with Prometheus). Every rule that decides what may
//! happen lives here, in the trusted core: plans proposed by Atlas are drafts until the owner approves
//! a version; dependencies can never form a loop; a workflow node changes state only through the
//! transitions below; after a restart anything that was running is paused, never repeated. The UI
//! sends operations, never whole sessions, so it cannot mark a step done or a plan approved by itself.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

pub const MAX_TASKS: usize = 80;
pub const AUTONOMY: [&str; 3] = ["approval_first", "balanced", "advanced"];
pub const CATEGORIES: [&str; 4] = ["think", "read", "organise", "change"];
pub const PRIORITIES: [&str; 3] = ["high", "normal", "low"];

/// Real capabilities a node can map to, with what actually runs it.
pub const OPERATIONS: [(&str, &str, &str, &str); 4] = [
    ("atlas", "Atlas works on it", "an Atlas turn; tools with real-world effects still ask through Approvals", "think"),
    ("todo", "Add to my tasks", "creates a task in Tasks (nothing else runs)", "organise"),
    ("research", "Atlas researches it", "an Atlas turn asked to investigate and report, not to change anything", "read"),
    ("manual", "You do it", "nothing automatic: you mark it done", "manual"),
];

fn category(op: &str) -> &'static str {
    OPERATIONS.iter().find(|o| o.0 == op).map(|o| o.3).unwrap_or("think")
}

fn bad(m: impl Into<String>) -> AtlasError {
    AtlasError::Validation(m.into())
}

fn clip(s: &str, n: usize) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(n).collect()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Task {
    pub id: String,
    pub title: String,
    pub phase: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default = "normal")]
    pub priority: String,
    #[serde(default)]
    pub estimate: String,
    /// "proposed" (from Atlas, not yet approved) or "confirmed".
    #[serde(default = "proposed")]
    pub status: String,
    #[serde(default = "atlas_op")]
    pub operation: String,
}
fn normal() -> String {
    "normal".into()
}
fn proposed() -> String {
    "proposed".into()
}
fn atlas_op() -> String {
    "atlas".into()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Dep {
    pub from: String,
    pub to: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct Plan {
    pub title: String,
    #[serde(default)]
    pub objective: String,
    #[serde(default)]
    pub outcome: String,
    #[serde(default)]
    pub phases: Vec<String>,
    #[serde(default)]
    pub tasks: Vec<Task>,
    #[serde(default)]
    pub deps: Vec<Dep>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub questions: Vec<String>,
    #[serde(default)]
    pub risks: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Version {
    pub version: u32,
    pub plan: Plan,
    /// "you" or "atlas".
    pub author: String,
    pub why: String,
    pub at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub at: String,
    pub event: String,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    pub id: String,
    pub title: String,
    pub detail: String,
    pub phase: String,
    pub operation: String,
    pub deps: Vec<String>,
    pub status: String,
    #[serde(default)]
    pub conversation_id: Option<String>,
    #[serde(default)]
    pub output: String,
    #[serde(default)]
    pub error: String,
    pub history: Vec<HistoryEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Workflow {
    pub id: String,
    pub plan_version: u32,
    pub autonomy: String,
    pub allowed: Vec<String>,
    pub paused: bool,
    pub state: String,
    pub nodes: Vec<Node>,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub at: String,
    pub kind: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub id: String,
    pub title: String,
    pub created_at: String,
    pub updated_at: String,
    pub conversation_id: Option<String>,
    pub autonomy: String,
    pub allowed: Vec<String>,
    pub versions: Vec<Version>,
    pub active_version: u32,
    pub approved_version: u32,
    pub workflow: Option<Workflow>,
    pub events: Vec<Event>,
    pub archived: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct SessionRow {
    pub id: String,
    pub title: String,
    pub updated_at: String,
    pub versions: u32,
    pub workflow_state: Option<String>,
}

// ---------------------------------------------------------------- plans

/// Clean a plan from Atlas or the owner: bounded text, unique ids, known phases and operations,
/// dependencies only between existing tasks and never forming a loop.
pub fn normalise(raw: &serde_json::Value) -> Plan {
    let s = |v: &serde_json::Value, k: &str, n: usize| clip(v.get(k).and_then(|x| x.as_str()).unwrap_or(""), n);
    let list = |k: &str| -> Vec<String> { raw.get(k).and_then(|x| x.as_array()).map(|a| a.iter().filter_map(|x| x.as_str()).map(|x| clip(x, 300)).filter(|x| !x.is_empty()).take(20).collect()).unwrap_or_default() };
    let mut p = Plan { title: s(raw, "title", 120), objective: s(raw, "objective", 300), outcome: s(raw, "outcome", 300), assumptions: list("assumptions"), questions: list("questions"), risks: list("risks"), ..Default::default() };
    if p.title.is_empty() {
        p.title = "Untitled plan".into();
    }
    let mut seen: HashSet<String> = HashSet::new();
    for ph in raw.get("phases").and_then(|x| x.as_array()).into_iter().flatten() {
        let name = clip(ph.as_str().or_else(|| ph.get("name").and_then(|n| n.as_str())).unwrap_or(""), 80);
        if !name.is_empty() && seen.insert(name.to_lowercase()) {
            p.phases.push(name);
        }
    }
    let mut ids: HashSet<String> = HashSet::new();
    for t in raw.get("tasks").and_then(|x| x.as_array()).into_iter().flatten().take(MAX_TASKS) {
        let title = clip(t.get("title").and_then(|x| x.as_str()).unwrap_or(""), 160);
        if title.is_empty() {
            continue;
        }
        let mut id = t.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string();
        if id.is_empty() || id.len() > 24 || !id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') || ids.contains(&id) {
            id = new_id()[..8].to_string();
        }
        ids.insert(id.clone());
        let mut phase = s(t, "phase", 80);
        if phase.is_empty() {
            phase = p.phases.first().cloned().unwrap_or_else(|| "Plan".into());
        }
        if seen.insert(phase.to_lowercase()) {
            p.phases.push(phase.clone());
        }
        let prio = s(t, "priority", 10).to_lowercase();
        let op = s(t, "operation", 20);
        p.tasks.push(Task {
            id,
            title,
            phase,
            detail: s(t, "detail", 600),
            priority: if PRIORITIES.contains(&prio.as_str()) { prio } else { "normal".into() },
            estimate: s(t, "estimate", 40),
            status: if s(t, "status", 12) == "confirmed" { "confirmed".into() } else { "proposed".into() },
            operation: if OPERATIONS.iter().any(|o| o.0 == op) { op } else { "atlas".into() },
        });
    }
    let by_title: HashMap<String, String> = p.tasks.iter().map(|t| (t.title.to_lowercase(), t.id.clone())).collect();
    let resolve = |v: Option<&serde_json::Value>| -> Option<String> {
        let x = v?.as_str()?;
        if ids.contains(x) {
            Some(x.to_string())
        } else {
            by_title.get(&x.to_lowercase()).cloned()
        }
    };
    let mut deps: Vec<Dep> = vec![];
    for d in raw.get("deps").and_then(|x| x.as_array()).into_iter().flatten() {
        if let (Some(a), Some(b)) = (resolve(d.get("from")), resolve(d.get("to"))) {
            let dep = Dep { from: a.clone(), to: b.clone() };
            if a != b && !deps.contains(&dep) && !creates_cycle(&deps, &a, &b) {
                deps.push(dep);
            }
        }
    }
    p.deps = deps;
    p
}

/// True if adding `a` before `b` would make tasks wait for each other in a loop.
pub fn creates_cycle(deps: &[Dep], a: &str, b: &str) -> bool {
    let mut stack = vec![b.to_string()];
    let mut seen = HashSet::new();
    while let Some(n) = stack.pop() {
        if n == a {
            return true;
        }
        if !seen.insert(n.clone()) {
            continue;
        }
        stack.extend(deps.iter().filter(|d| d.from == n).map(|d| d.to.clone()));
    }
    false
}

/// A task by id, exact title or a unique title fragment; never a guess between several.
pub fn find<'a>(p: &'a Plan, r: &str) -> Option<&'a Task> {
    let l = r.trim().to_lowercase();
    if l.is_empty() {
        return None;
    }
    if let Some(t) = p.tasks.iter().find(|t| t.id == r || t.title.to_lowercase() == l) {
        return Some(t);
    }
    let hits: Vec<_> = p.tasks.iter().filter(|t| t.title.to_lowercase().contains(&l)).collect();
    if hits.len() == 1 {
        Some(hits[0])
    } else {
        None
    }
}

/// One edit from the owner (voice, typing or the canvas). Returns the new plan and a plain description.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Edit {
    AddTask { title: String, #[serde(default)] phase: String, #[serde(default)] operation: Option<String> },
    RemoveTask { task: String },
    RenameTask { task: String, title: String },
    SetPriority { task: String, priority: String },
    SetOperation { task: String, operation: String },
    MoveToPhase { task: String, phase: String },
    MoveBefore { task: String, other: String },
    MovePhaseBefore { phase: String, other: String },
    AddDep { before: String, after: String },
    RemoveDep { before: String, after: String },
    SetDetail { task: String, detail: String },
}

pub fn edit(plan: &Plan, e: &Edit) -> Result<(Plan, String)> {
    let mut p = plan.clone();
    let need = |r: &str| find(plan, r).cloned().ok_or_else(|| bad(format!("No single task matches \u{201c}{r}\u{201d}.")));
    let msg = match e {
        Edit::AddTask { title, phase, operation } => {
            let title = clip(title, 160);
            if title.is_empty() {
                return Err(bad("A task needs a title."));
            }
            if p.tasks.len() >= MAX_TASKS {
                return Err(bad("This plan already has the maximum number of tasks."));
            }
            let phase = if clip(phase, 80).is_empty() { p.phases.last().cloned().unwrap_or_else(|| "Plan".into()) } else { clip(phase, 80) };
            if !p.phases.contains(&phase) {
                p.phases.push(phase.clone());
            }
            let op = operation.clone().filter(|o| OPERATIONS.iter().any(|x| x.0 == o)).unwrap_or_else(atlas_op);
            p.tasks.push(Task { id: new_id()[..8].to_string(), title: title.clone(), phase: phase.clone(), detail: String::new(), priority: "normal".into(), estimate: String::new(), status: "confirmed".into(), operation: op });
            format!("Added \u{201c}{title}\u{201d} to {phase}.")
        }
        Edit::RemoveTask { task } => {
            let t = need(task)?;
            p.tasks.retain(|x| x.id != t.id);
            p.deps.retain(|d| d.from != t.id && d.to != t.id);
            format!("Removed \u{201c}{}\u{201d}.", t.title)
        }
        Edit::RenameTask { task, title } => {
            let t = need(task)?;
            let new = clip(title, 160);
            if new.is_empty() {
                return Err(bad("Give the new name."));
            }
            p.tasks.iter_mut().find(|x| x.id == t.id).unwrap().title = new.clone();
            format!("Renamed \u{201c}{}\u{201d} to \u{201c}{new}\u{201d}.", t.title)
        }
        Edit::SetPriority { task, priority } => {
            let t = need(task)?;
            let pr = priority.to_lowercase();
            if !PRIORITIES.contains(&pr.as_str()) {
                return Err(bad("Priority is high, normal or low."));
            }
            p.tasks.iter_mut().find(|x| x.id == t.id).unwrap().priority = pr.clone();
            format!("\u{201c}{}\u{201d} is now {pr} priority.", t.title)
        }
        Edit::SetOperation { task, operation } => {
            let t = need(task)?;
            let op = OPERATIONS.iter().find(|o| o.0 == operation).ok_or_else(|| bad("Unknown operation."))?;
            p.tasks.iter_mut().find(|x| x.id == t.id).unwrap().operation = op.0.into();
            format!("\u{201c}{}\u{201d} will be done by: {}.", t.title, op.1)
        }
        Edit::SetDetail { task, detail } => {
            let t = need(task)?;
            p.tasks.iter_mut().find(|x| x.id == t.id).unwrap().detail = clip(detail, 600);
            format!("Updated the detail of \u{201c}{}\u{201d}.", t.title)
        }
        Edit::MoveToPhase { task, phase } => {
            let t = need(task)?;
            let name = clip(phase, 80);
            if name.is_empty() {
                return Err(bad("Name the phase."));
            }
            let name = p.phases.iter().find(|x| x.to_lowercase() == name.to_lowercase()).cloned().unwrap_or(name);
            if !p.phases.contains(&name) {
                p.phases.push(name.clone());
            }
            p.tasks.iter_mut().find(|x| x.id == t.id).unwrap().phase = name.clone();
            format!("Moved \u{201c}{}\u{201d} to {name}.", t.title)
        }
        Edit::MoveBefore { task, other } => {
            let t = need(task)?;
            let o = need(other)?;
            if t.id == o.id {
                return Err(bad("Name two different tasks."));
            }
            let mut moved = t.clone();
            moved.phase = o.phase.clone();
            p.tasks.retain(|x| x.id != t.id);
            let i = p.tasks.iter().position(|x| x.id == o.id).unwrap_or(0);
            p.tasks.insert(i, moved);
            format!("Moved \u{201c}{}\u{201d} before \u{201c}{}\u{201d}.", t.title, o.title)
        }
        Edit::MovePhaseBefore { phase, other } => {
            let m = |n: &str| p.phases.iter().find(|x| x.to_lowercase() == n.trim().to_lowercase()).cloned();
            let (a, b) = (m(phase).ok_or_else(|| bad("No such phase."))?, m(other).ok_or_else(|| bad("No such phase."))?);
            if a == b {
                return Err(bad("Name two different phases."));
            }
            p.phases.retain(|x| x != &a);
            let i = p.phases.iter().position(|x| x == &b).unwrap_or(0);
            p.phases.insert(i, a.clone());
            format!("{a} now comes before {b}.")
        }
        Edit::AddDep { before, after } | Edit::RemoveDep { before, after } => {
            let x = need(before)?;
            let y = need(after)?;
            if x.id == y.id {
                return Err(bad("Name two different tasks."));
            }
            let dep = Dep { from: x.id.clone(), to: y.id.clone() };
            if matches!(e, Edit::RemoveDep { .. }) {
                if !p.deps.contains(&dep) {
                    return Err(bad("Those tasks are not linked."));
                }
                p.deps.retain(|d| d != &dep);
                format!("\u{201c}{}\u{201d} no longer waits for \u{201c}{}\u{201d}.", y.title, x.title)
            } else {
                if p.deps.contains(&dep) {
                    return Err(bad("They are already linked."));
                }
                if creates_cycle(&p.deps, &x.id, &y.id) {
                    return Err(bad("That would make the tasks wait for each other in a loop."));
                }
                p.deps.push(dep);
                format!("\u{201c}{}\u{201d} now waits for \u{201c}{}\u{201d}.", y.title, x.title)
            }
        }
    };
    Ok((p, msg))
}

/// The last complete ```orbit-plan block in a reply, cleaned; None when absent or invalid.
pub fn extract_plan(text: &str) -> Option<Plan> {
    let re = regex::Regex::new(r"(?s)```orbit-plan\s*(\{.*?\})\s*```").ok()?;
    re.captures_iter(text).filter_map(|c| serde_json::from_str::<serde_json::Value>(&c[1]).ok()).filter(|v| v.is_object()).last().map(|v| normalise(&v))
}

/// The reply without plan blocks, for the transcript and for speech.
pub fn strip_plan_blocks(text: &str) -> String {
    let re = regex::Regex::new(r"(?s)```orbit-plan.*?```").unwrap();
    let t = re.replace_all(text, "").to_string();
    match t.find("```orbit-plan") {
        Some(i) => t[..i].trim().to_string(),
        None => t.trim().to_string(),
    }
}

/// What Atlas is told in an ORBIT turn (added to its system prompt, never to the owner's message).
pub fn system_section(s: &Session) -> String {
    let mut out = String::from(
        "\n\n## ORBIT planning session\nYou are working with the owner in ORBIT, a voice-first planning space. Talk naturally and briefly. \
         Whenever you propose or change a plan, append ONE fenced block ```orbit-plan {json} ``` with keys: title, objective, outcome, \
         phases (names), tasks ({id, title, phase, detail, priority high|normal|low, estimate only with a basis}), deps ({from, to}: \
         from finishes before to), assumptions, questions (what you still need to know), risks. Never present assumptions as confirmed \
         requirements; keep task ids stable between versions. Plans you propose are drafts until the owner approves them.\n",
    );
    match active_plan(s) {
        Some(p) => out.push_str(&format!("Current plan (version {}): {}\n", s.active_version, serde_json::to_string(&p).unwrap_or_default().chars().take(6000).collect::<String>())),
        None => out.push_str("There is no plan yet.\n"),
    }
    out
}

// ---------------------------------------------------------------- workflows

pub const NODE_STATES: [&str; 10] = ["draft", "ready", "waiting", "awaiting_approval", "running", "completed", "failed", "paused", "cancelled", "blocked"];

pub fn allowed(from: &str, to: &str) -> bool {
    let next: &[&str] = match from {
        "draft" => &["ready", "waiting", "cancelled"],
        "waiting" => &["ready", "cancelled", "blocked"],
        "ready" => &["awaiting_approval", "running", "paused", "cancelled", "waiting"],
        "awaiting_approval" => &["running", "cancelled", "paused", "ready"],
        "running" => &["completed", "failed", "paused", "cancelled", "awaiting_approval"],
        "paused" => &["ready", "cancelled"],
        "failed" | "blocked" => &["ready", "cancelled"],
        "cancelled" => &["ready"],
        _ => &[],
    };
    next.contains(&to)
}

pub fn topo_order(p: &Plan) -> Vec<String> {
    let rank: HashMap<&str, usize> = p.phases.iter().enumerate().map(|(i, x)| (x.as_str(), i)).collect();
    let mut tasks: Vec<(usize, usize, &Task)> = p.tasks.iter().enumerate().map(|(i, t)| (*rank.get(t.phase.as_str()).unwrap_or(&99), i, t)).collect();
    tasks.sort_by_key(|x| (x.0, x.1));
    let mut out: Vec<String> = vec![];
    while out.len() < tasks.len() {
        let next = tasks.iter().find(|(_, _, t)| !out.contains(&t.id) && p.deps.iter().filter(|d| d.to == t.id).all(|d| out.contains(&d.from)));
        match next {
            Some((_, _, t)) => out.push(t.id.clone()),
            None => {
                out.extend(tasks.iter().filter(|(_, _, t)| !out.contains(&t.id)).map(|(_, _, t)| t.id.clone()).collect::<Vec<_>>());
            }
        }
    }
    out
}

pub fn make_workflow(p: &Plan, version: u32, autonomy: &str, allowed_cats: &[String]) -> Workflow {
    let by: HashMap<&str, &Task> = p.tasks.iter().map(|t| (t.id.as_str(), t)).collect();
    let nodes = topo_order(p)
        .into_iter()
        .map(|id| {
            let t = by[id.as_str()];
            let deps: Vec<String> = p.deps.iter().filter(|d| d.to == id).map(|d| d.from.clone()).collect();
            let st = if deps.is_empty() { "ready" } else { "waiting" };
            Node { id: id.clone(), title: t.title.clone(), detail: t.detail.clone(), phase: t.phase.clone(), operation: t.operation.clone(), deps, status: st.into(), conversation_id: None, output: String::new(), error: String::new(), history: vec![HistoryEntry { at: now(), event: "created".into(), status: st.into() }] }
        })
        .collect();
    Workflow {
        id: new_id(),
        plan_version: version,
        autonomy: if AUTONOMY.contains(&autonomy) { autonomy.into() } else { "approval_first".into() },
        allowed: allowed_cats.iter().filter(|c| CATEGORIES.contains(&c.as_str())).cloned().collect(),
        paused: false,
        state: "ready".into(),
        nodes,
        created_at: now(),
    }
}

/// Whether a node must wait for the owner's go-ahead before it starts. Tool approvals are separate
/// and always on, whatever this says.
pub fn needs_go_ahead(w: &Workflow, n: &Node) -> bool {
    let cat = category(&n.operation);
    if cat == "manual" {
        return true;
    }
    match w.autonomy.as_str() {
        "balanced" => cat == "change",
        "advanced" => !w.allowed.iter().any(|c| c == cat),
        _ => true,
    }
}

pub fn workflow_state(w: &Workflow) -> String {
    let st: Vec<&str> = w.nodes.iter().map(|n| n.status.as_str()).collect();
    let s = if st.is_empty() {
        "ready"
    } else if st.iter().all(|s| *s == "completed") {
        "completed"
    } else if st.contains(&"running") {
        "running"
    } else if st.contains(&"awaiting_approval") {
        "awaiting_approval"
    } else if w.paused {
        "paused"
    } else if st.contains(&"failed") {
        "failed"
    } else if st.iter().all(|s| matches!(*s, "completed" | "cancelled" | "blocked")) {
        "cancelled"
    } else {
        "ready"
    };
    s.into()
}

pub fn transition(w: &mut Workflow, node_id: &str, to: &str, detail: &str) -> Result<()> {
    let i = w.nodes.iter().position(|n| n.id == node_id).ok_or_else(|| AtlasError::NotFound("workflow step".into()))?;
    let from = w.nodes[i].status.clone();
    if !allowed(&from, to) {
        return Err(AtlasError::Conflict(format!("a step cannot go from {from} to {to}")));
    }
    if to == "running" && from == "ready" && w.nodes[i].deps.iter().any(|d| w.nodes.iter().any(|n| &n.id == d && n.status != "completed")) {
        return Err(AtlasError::Conflict("this step still waits for another".into()));
    }
    let event = if detail.is_empty() { to.to_string() } else { format!("{to}: {}", clip(detail, 400)) };
    w.nodes[i].status = to.into();
    w.nodes[i].history.push(HistoryEntry { at: now(), event, status: to.into() });
    let title = w.nodes[i].title.clone();
    match to {
        "completed" => {
            let done: HashSet<String> = w.nodes.iter().filter(|n| n.status == "completed").map(|n| n.id.clone()).collect();
            for n in w.nodes.iter_mut().filter(|n| n.status == "waiting" && n.deps.iter().all(|d| done.contains(d))) {
                n.status = "ready".into();
                n.history.push(HistoryEntry { at: now(), event: "dependencies done".into(), status: "ready".into() });
            }
        }
        "failed" | "cancelled" => {
            for n in w.nodes.iter_mut().filter(|n| n.deps.iter().any(|d| d == node_id) && matches!(n.status.as_str(), "waiting" | "ready")) {
                n.status = "blocked".into();
                n.history.push(HistoryEntry { at: now(), event: format!("blocked: \u{201c}{title}\u{201d} {to}"), status: "blocked".into() });
            }
        }
        "ready" => {
            for n in w.nodes.iter_mut().filter(|n| n.deps.iter().any(|d| d == node_id) && n.status == "blocked") {
                n.status = "waiting".into();
            }
        }
        _ => {}
    }
    w.state = workflow_state(w);
    Ok(())
}

pub fn next_node(w: &Workflow) -> Option<&Node> {
    if w.paused {
        return None;
    }
    w.nodes.iter().find(|n| n.status == "ready")
}

/// After a restart: running or waiting-for-approval steps are paused with a note, never repeated.
pub fn recover(w: &mut Workflow) -> usize {
    let mut n = 0;
    for node in w.nodes.iter_mut().filter(|x| matches!(x.status.as_str(), "running" | "awaiting_approval")) {
        node.status = "paused".into();
        node.history.push(HistoryEntry { at: now(), event: "interrupted: Atlas was closed while this step ran; it was not repeated".into(), status: "paused".into() });
        n += 1;
    }
    if n > 0 {
        w.paused = true;
        w.state = workflow_state(w);
    }
    n
}

// ---------------------------------------------------------------- sessions

pub fn active_plan(s: &Session) -> Option<Plan> {
    if s.active_version == 0 {
        return None;
    }
    s.versions.get(s.active_version as usize - 1).map(|v| v.plan.clone())
}

pub fn log(s: &mut Session, kind: &str, detail: &str) {
    s.events.push(Event { at: now(), kind: kind.into(), detail: clip(detail, 400) });
    let len = s.events.len();
    if len > 500 {
        s.events.drain(..len - 500);
    }
}

pub fn add_version(s: &mut Session, plan: Plan, author: &str, why: &str) -> u32 {
    let v = s.versions.len() as u32 + 1;
    s.versions.push(Version { version: v, plan, author: if author == "atlas" { "atlas".into() } else { "you".into() }, why: clip(why, 300), at: now() });
    s.active_version = v;
    log(s, "plan.updated", &format!("version {v} by {author}: {}", clip(why, 120)));
    v
}

pub fn compare(a: &Plan, b: &Plan) -> Vec<String> {
    let ta: HashMap<&str, &Task> = a.tasks.iter().map(|t| (t.id.as_str(), t)).collect();
    let tb: HashMap<&str, &Task> = b.tasks.iter().map(|t| (t.id.as_str(), t)).collect();
    let mut out: Vec<String> = b.tasks.iter().filter(|t| !ta.contains_key(t.id.as_str())).map(|t| format!("+ {}", t.title)).collect();
    out.extend(a.tasks.iter().filter(|t| !tb.contains_key(t.id.as_str())).map(|t| format!("\u{2212} {}", t.title)));
    for t in &b.tasks {
        if let Some(x) = ta.get(t.id.as_str()) {
            if x.title != t.title {
                out.push(format!("renamed: {} \u{2192} {}", x.title, t.title));
            }
            if x.phase != t.phase {
                out.push(format!("moved: {} ({} \u{2192} {})", t.title, x.phase, t.phase));
            }
            if x.priority != t.priority {
                out.push(format!("priority: {} {} \u{2192} {}", t.title, x.priority, t.priority));
            }
        }
    }
    if a.phases != b.phases {
        out.push(format!("phases: {}", b.phases.join(" \u{2192} ")));
    }
    if a.deps.len() != b.deps.len() || a.deps.iter().any(|d| !b.deps.contains(d)) {
        out.push(format!("dependencies: {} \u{2192} {}", a.deps.len(), b.deps.len()));
    }
    out
}

pub fn new_session(title: &str, autonomy: &str) -> Session {
    let t = now();
    Session {
        id: new_id(),
        title: if clip(title, 80).is_empty() { "New ORBIT session".into() } else { clip(title, 80) },
        created_at: t.clone(),
        updated_at: t,
        conversation_id: None,
        autonomy: if AUTONOMY.contains(&autonomy) { autonomy.into() } else { "approval_first".into() },
        allowed: vec![],
        versions: vec![],
        active_version: 0,
        approved_version: 0,
        workflow: None,
        events: vec![],
        archived: false,
    }
}

pub fn save(db: &Db, s: &mut Session) -> Result<()> {
    s.updated_at = now();
    let data = serde_json::to_string(s).map_err(|e| AtlasError::Internal(e.to_string()))?;
    db.conn()?.execute(
        "INSERT INTO orbit_sessions (id, title, updated_at, archived, data) VALUES (?1, ?2, ?3, ?4, ?5)
         ON CONFLICT(id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at, archived = excluded.archived, data = excluded.data",
        rusqlite::params![s.id, s.title, s.updated_at, s.archived as i64, data],
    )?;
    Ok(())
}

/// Load a session. A record that no longer parses is reported, not half-read.
pub fn get(db: &Db, id: &str) -> Result<Session> {
    let data: Option<String> = db.conn()?.query_row("SELECT data FROM orbit_sessions WHERE id = ?1", [id], |r| r.get(0)).optional()?;
    let data = data.ok_or_else(|| AtlasError::NotFound("ORBIT session".into()))?;
    serde_json::from_str(&data).map_err(|e| AtlasError::Storage(format!("this ORBIT session could not be read ({e})")))
}

pub fn list(db: &Db) -> Result<Vec<SessionRow>> {
    let conn = db.conn()?;
    let mut st = conn.prepare("SELECT data FROM orbit_sessions WHERE archived = 0 ORDER BY updated_at DESC LIMIT 200")?;
    let rows = st.query_map([], |r| r.get::<_, String>(0))?;
    let mut out = vec![];
    for data in rows.flatten() {
        if let Ok(s) = serde_json::from_str::<Session>(&data) {
            out.push(SessionRow { id: s.id, title: s.title, updated_at: s.updated_at, versions: s.versions.len() as u32, workflow_state: s.workflow.map(|w| w.state) });
        }
    }
    Ok(out)
}

pub fn delete(db: &Db, id: &str) -> Result<bool> {
    Ok(db.conn()?.execute("DELETE FROM orbit_sessions WHERE id = ?1", [id])? > 0)
}

/// At start-up: pause every interrupted step in every session (nothing re-runs by itself).
pub fn recover_all(db: &Db) -> Result<usize> {
    let ids: Vec<String> = {
        let conn = db.conn()?;
        let mut st = conn.prepare("SELECT id FROM orbit_sessions")?;
        let v = st.query_map([], |r| r.get::<_, String>(0))?.flatten().collect();
        v
    };
    let mut total = 0;
    for id in ids {
        if let Ok(mut s) = get(db, &id) {
            let n = s.workflow.as_mut().map(recover).unwrap_or(0);
            if n > 0 {
                log(&mut s, "session.restored", &format!("{n} interrupted step(s) paused, not repeated"));
                save(db, &mut s)?;
                total += n;
            }
        }
    }
    Ok(total)
}

// ---------------------------------------------------------------- operations (what the UI may ask)

/// One owner action on a session. The core checks each against the rules above.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
pub enum Action {
    Edit { edit: Edit, #[serde(default)] why: String },
    Undo,
    Restore { version: u32 },
    Approve,
    BuildWorkflow,
    SetAutonomy { autonomy: String, #[serde(default)] allowed: Vec<String> },
    /// Ask to start the next ready step: it either needs your go-ahead (becomes awaiting_approval) or
    /// may start (becomes running). Returns the node in the reply so the UI can run it.
    StartNext,
    /// Your go-ahead for the step waiting for it.
    ApproveStep { node: String },
    /// Record what really happened while a step ran (reported by the UI from real turn events).
    StepStarted { node: String, conversation_id: String },
    StepFinished { node: String, ok: bool, #[serde(default)] output: String, #[serde(default)] error: String },
    StepWaitingForTool { node: String, tool: String },
    StepToolAnswered { node: String, approved: bool },
    MarkDone { node: String },
    Pause,
    Resume,
    Retry { node: String },
    Cancel,
    Rename { title: String },
    Archive,
}

pub fn apply(s: &mut Session, a: &Action) -> Result<String> {
    let has_running = s.workflow.as_ref().map(|w| w.nodes.iter().any(|n| n.status == "running")).unwrap_or(false);
    let msg = match a {
        Action::Edit { edit: e, why } => {
            if has_running {
                return Err(AtlasError::Conflict("pause or cancel the running step before changing the plan".into()));
            }
            let plan = active_plan(s).unwrap_or_else(|| Plan { title: s.title.clone(), ..Default::default() });
            let (p, m) = edit(&plan, e)?;
            add_version(s, p, "you", if why.is_empty() { &m } else { why });
            m
        }
        Action::Undo => {
            if s.active_version < 2 || has_running {
                return Err(bad("There is nothing to undo."));
            }
            let prev = s.versions[s.active_version as usize - 2].plan.clone();
            let v = s.active_version - 1;
            add_version(s, prev, "you", &format!("Undo: back to the plan of version {v}"));
            format!("Back to version {v}'s plan (kept as a new version).")
        }
        Action::Restore { version } => {
            let p = s.versions.get((*version as usize).wrapping_sub(1)).map(|v| v.plan.clone()).ok_or_else(|| AtlasError::NotFound("plan version".into()))?;
            add_version(s, p, "you", &format!("Restored version {version}"));
            format!("Version {version} restored as a new version.")
        }
        Action::Approve => {
            let v = s.active_version;
            let has_tasks = active_plan(s).map(|p| !p.tasks.is_empty()).unwrap_or(false);
            if v == 0 || !has_tasks {
                return Err(bad("There is no plan with tasks to approve."));
            }
            for t in s.versions[v as usize - 1].plan.tasks.iter_mut() {
                t.status = "confirmed".into();
            }
            s.approved_version = v;
            log(s, "plan.approved", &format!("version {v} approved by you"));
            format!("Plan version {v} approved.")
        }
        Action::BuildWorkflow => {
            let v = s.approved_version;
            if v == 0 || v != s.active_version {
                return Err(bad("Approve the current plan version first."));
            }
            if has_running {
                return Err(AtlasError::Conflict("a step is running".into()));
            }
            let w = make_workflow(&s.versions[v as usize - 1].plan, v, &s.autonomy, &s.allowed);
            let n = w.nodes.len();
            s.workflow = Some(w);
            log(s, "workflow.built", &format!("{n} steps from version {v}"));
            format!("Workflow built: {n} steps.")
        }
        Action::SetAutonomy { autonomy, allowed } => {
            if !AUTONOMY.contains(&autonomy.as_str()) {
                return Err(bad("Unknown autonomy level."));
            }
            s.autonomy = autonomy.clone();
            s.allowed = allowed.iter().filter(|c| CATEGORIES.contains(&c.as_str())).cloned().collect();
            if let Some(w) = s.workflow.as_mut() {
                w.autonomy = s.autonomy.clone();
                w.allowed = s.allowed.clone();
            }
            log(s, "autonomy.changed", autonomy);
            format!("Autonomy: {autonomy}.")
        }
        Action::StartNext => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("Build the workflow first."))?;
            if w.nodes.iter().any(|n| matches!(n.status.as_str(), "running" | "awaiting_approval")) {
                return Err(AtlasError::Conflict("a step is already running or waiting for you".into()));
            }
            let n = next_node(w).cloned().ok_or_else(|| bad("No step is ready."))?;
            if needs_go_ahead(w, &n) {
                transition(w, &n.id, "awaiting_approval", &format!("waiting for your go-ahead (autonomy: {})", w.autonomy))?;
                format!("go-ahead:{}", n.id)
            } else {
                transition(w, &n.id, "running", &format!("started automatically (autonomy: {})", w.autonomy))?;
                format!("run:{}", n.id)
            }
        }
        Action::ApproveStep { node } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            let n = w.nodes.iter().find(|n| &n.id == node).cloned().ok_or_else(|| AtlasError::NotFound("workflow step".into()))?;
            if n.status != "awaiting_approval" {
                return Err(AtlasError::Conflict("this step is not waiting for you".into()));
            }
            transition(w, node, "running", "you gave the go-ahead")?;
            if n.operation == "manual" {
                transition(w, node, "completed", "marked done by you")?;
                "done".into()
            } else {
                format!("run:{node}")
            }
        }
        Action::StepStarted { node, conversation_id } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            let n = w.nodes.iter_mut().find(|n| &n.id == node).ok_or_else(|| AtlasError::NotFound("workflow step".into()))?;
            if n.status != "running" {
                return Err(AtlasError::Conflict("this step was not started".into()));
            }
            n.conversation_id = Some(conversation_id.clone());
            "ok".into()
        }
        Action::StepWaitingForTool { node, tool } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            transition(w, node, "awaiting_approval", &format!("asks to use {tool}"))?;
            "ok".into()
        }
        Action::StepToolAnswered { node, approved } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            transition(w, node, "running", if *approved { "you approved the tool" } else { "you denied the tool" })?;
            "ok".into()
        }
        Action::StepFinished { node, ok, output, error } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            let i = w.nodes.iter().position(|n| &n.id == node).ok_or_else(|| AtlasError::NotFound("workflow step".into()))?;
            if w.nodes[i].status == "awaiting_approval" {
                transition(w, node, "running", "approval closed")?;
            }
            if w.nodes[i].status != "running" {
                return Ok("ignored".into()); // cancelled meanwhile: the record stays as it is
            }
            if *ok {
                w.nodes[i].output = output.chars().take(4000).collect();
                transition(w, node, "completed", "finished")?;
            } else {
                w.nodes[i].error = error.chars().take(400).collect();
                transition(w, node, "failed", error)?;
            }
            "ok".into()
        }
        Action::MarkDone { node } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            let n = w.nodes.iter().find(|n| &n.id == node).cloned().ok_or_else(|| AtlasError::NotFound("workflow step".into()))?;
            if n.operation != "manual" {
                return Err(bad("Only a step you do yourself can be marked done by hand."));
            }
            if n.status == "ready" {
                transition(w, node, "running", "you are doing it")?;
            } else if n.status == "awaiting_approval" {
                transition(w, node, "running", "you are doing it")?;
            }
            transition(w, node, "completed", "marked done by you")?;
            "done".into()
        }
        Action::Pause => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            w.paused = true;
            let ids: Vec<String> = w.nodes.iter().filter(|n| matches!(n.status.as_str(), "ready" | "awaiting_approval")).map(|n| n.id.clone()).collect();
            for id in ids {
                transition(w, &id, "paused", "workflow paused")?;
            }
            w.state = workflow_state(w);
            log(s, "workflow.paused", "the running step, if any, finishes; nothing new starts");
            "Paused.".into()
        }
        Action::Resume => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            w.paused = false;
            let done: HashSet<String> = w.nodes.iter().filter(|n| n.status == "completed").map(|n| n.id.clone()).collect();
            let ids: Vec<(String, bool)> = w.nodes.iter().filter(|n| n.status == "paused").map(|n| (n.id.clone(), n.deps.iter().all(|d| done.contains(d)))).collect();
            for (id, ready) in ids {
                transition(w, &id, "ready", "resumed")?;
                if !ready {
                    w.nodes.iter_mut().find(|n| n.id == id).unwrap().status = "waiting".into();
                }
            }
            w.state = workflow_state(w);
            log(s, "workflow.resumed", "");
            "Resumed.".into()
        }
        Action::Retry { node } => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            let n = w.nodes.iter().find(|n| &n.id == node).cloned().ok_or_else(|| AtlasError::NotFound("workflow step".into()))?;
            if !matches!(n.status.as_str(), "failed" | "cancelled" | "blocked") {
                return Err(bad("Only a failed, cancelled or blocked step can be retried."));
            }
            transition(w, node, "ready", "retry requested by you")?;
            let done: HashSet<String> = w.nodes.iter().filter(|n| n.status == "completed").map(|n| n.id.clone()).collect();
            let i = w.nodes.iter().position(|x| &x.id == node).unwrap();
            w.nodes[i].error.clear();
            if !w.nodes[i].deps.iter().all(|d| done.contains(d)) {
                w.nodes[i].status = "waiting".into();
            }
            w.paused = false;
            w.state = workflow_state(w);
            "Ready to retry.".into()
        }
        Action::Cancel => {
            let w = s.workflow.as_mut().ok_or_else(|| bad("No workflow."))?;
            let ids: Vec<String> = w.nodes.iter().filter(|n| !matches!(n.status.as_str(), "completed" | "cancelled" | "failed")).map(|n| n.id.clone()).collect();
            for id in ids {
                let st = w.nodes.iter().find(|n| n.id == id).unwrap().status.clone();
                if st == "waiting" || allowed(&st, "cancelled") {
                    let _ = transition(w, &id, "cancelled", "you cancelled the workflow");
                }
            }
            w.paused = false;
            w.state = workflow_state(w);
            log(s, "workflow.cancelled", "completed steps stay completed; nothing is undone");
            "Cancelled.".into()
        }
        Action::Rename { title } => {
            let t = clip(title, 80);
            if t.is_empty() {
                return Err(bad("Give the session a name."));
            }
            s.title = t;
            "Renamed.".into()
        }
        Action::Archive => {
            s.archived = true;
            log(s, "session.archived", "");
            "Archived.".into()
        }
    };
    if !matches!(a, Action::Edit { .. } | Action::Undo | Action::Restore { .. } | Action::Approve | Action::SetAutonomy { .. } | Action::Pause | Action::Resume | Action::Cancel | Action::Archive | Action::BuildWorkflow) {
        log(s, "step", &format!("{a:?}").chars().take(160).collect::<String>());
    }
    Ok(msg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample() -> Plan {
        normalise(&json!({
            "title": "Launch", "phases": ["Research", "Build", "Release"],
            "tasks": [
                {"id": "r1", "title": "Survey hosting", "phase": "Research"},
                {"id": "b1", "title": "Write pages", "phase": "Build", "priority": "high"},
                {"id": "b2", "title": "Write tests", "phase": "Build"},
                {"id": "x1", "title": "Publish", "phase": "Release", "operation": "manual"}],
            "deps": [{"from": "r1", "to": "b1"}, {"from": "b1", "to": "x1"}, {"from": "b2", "to": "x1"}, {"from": "x1", "to": "r1"}]
        }))
    }

    #[test]
    fn normalise_drops_loops_and_unknown_operations() {
        let p = sample();
        assert_eq!(p.deps.len(), 3, "the x1 → r1 link would close a loop");
        let q = normalise(&json!({"tasks": [{"title": "a", "operation": "shell rm -rf /"}]}));
        assert_eq!(q.tasks[0].operation, "atlas");
        assert!(p.tasks.iter().all(|t| t.status == "proposed"));
    }

    #[test]
    fn extract_and_strip() {
        let r = "Plan:\n```orbit-plan {\"title\":\"T\",\"tasks\":[{\"id\":\"1\",\"title\":\"Do\"}]}```\nOK?";
        assert_eq!(extract_plan(r).unwrap().tasks[0].title, "Do");
        assert_eq!(strip_plan_blocks(r), "Plan:\n\nOK?");
        assert!(extract_plan("```orbit-plan {nope}```").is_none());
    }

    #[test]
    fn edits_and_refusals() {
        let p = sample();
        let (p, _) = edit(&p, &Edit::MovePhaseBefore { phase: "Release".into(), other: "Build".into() }).unwrap();
        assert_eq!(p.phases, vec!["Research", "Release", "Build"]);
        assert!(edit(&p, &Edit::AddDep { before: "Publish".into(), after: "Survey hosting".into() }).is_err());
        assert!(edit(&p, &Edit::RemoveTask { task: "write".into() }).is_err(), "ambiguous: never guess");
        let (p, _) = edit(&p, &Edit::RemoveTask { task: "Write pages".into() }).unwrap();
        assert!(p.deps.iter().all(|d| d.from != "b1" && d.to != "b1"));
    }

    #[test]
    fn approval_gates_and_state_machine() {
        let mut s = new_session("x", "balanced");
        add_version(&mut s, sample(), "atlas", "Proposed");
        assert!(apply(&mut s, &Action::BuildWorkflow).is_err(), "nothing is built before approval");
        apply(&mut s, &Action::Approve).unwrap();
        apply(&mut s, &Action::BuildWorkflow).unwrap();
        // balanced: thinking steps start on their own
        assert_eq!(apply(&mut s, &Action::StartNext).unwrap(), "run:r1");
        assert!(apply(&mut s, &Action::StartNext).is_err(), "one step at a time");
        assert!(apply(&mut s, &Action::Edit { edit: Edit::RemoveTask { task: "Publish".into() }, why: String::new() }).is_err(), "no plan edits while running");
        apply(&mut s, &Action::StepFinished { node: "r1".into(), ok: true, output: "done".into(), error: String::new() }).unwrap();
        let w = s.workflow.as_ref().unwrap();
        assert_eq!(w.nodes.iter().find(|n| n.id == "b1").unwrap().status, "ready");
        apply(&mut s, &Action::StartNext).unwrap();
        apply(&mut s, &Action::StepFinished { node: "b1".into(), ok: false, output: String::new(), error: "timeout".into() }).unwrap();
        let w = s.workflow.as_ref().unwrap();
        assert_eq!(w.nodes.iter().find(|n| n.id == "x1").unwrap().status, "blocked");
        apply(&mut s, &Action::Retry { node: "b1".into() }).unwrap();
        assert_eq!(s.workflow.as_ref().unwrap().nodes.iter().find(|n| n.id == "x1").unwrap().status, "waiting");
    }

    #[test]
    fn manual_steps_always_wait_and_recovery_never_reruns() {
        let mut s = new_session("x", "advanced");
        apply(&mut s, &Action::SetAutonomy { autonomy: "advanced".into(), allowed: vec!["think".into(), "organise".into(), "change".into()] }).unwrap();
        add_version(&mut s, sample(), "you", "v1");
        apply(&mut s, &Action::Approve).unwrap();
        apply(&mut s, &Action::BuildWorkflow).unwrap();
        let w = s.workflow.as_ref().unwrap();
        assert!(needs_go_ahead(w, w.nodes.iter().find(|n| n.id == "x1").unwrap()));
        apply(&mut s, &Action::StartNext).unwrap();
        let w = s.workflow.as_mut().unwrap();
        assert_eq!(recover(w), 1);
        assert!(w.paused && next_node(w).is_none());
        assert!(w.nodes[0].history.last().unwrap().event.contains("not repeated"));
    }

    #[test]
    fn undo_restore_compare() {
        let mut s = new_session("x", "approval_first");
        add_version(&mut s, sample(), "atlas", "Proposed");
        apply(&mut s, &Action::Edit { edit: Edit::RenameTask { task: "Publish".into(), title: "Go live".into() }, why: String::new() }).unwrap();
        assert!(compare(&s.versions[0].plan, &s.versions[1].plan).contains(&"renamed: Publish \u{2192} Go live".to_string()));
        apply(&mut s, &Action::Undo).unwrap();
        assert_eq!(s.active_version, 3);
        assert!(find(&active_plan(&s).unwrap(), "Publish").is_some());
        assert_eq!(s.versions[2].author, "you");
    }
}
