//! Persistent memory under the owner's control.
//!
//! **What creates a memory:** only the owner (Memory page), or Atlas through the `memory.save` tool,
//! which proposes a memory and needs the owner's approval (and can be switched off). Nothing is
//! inferred and saved silently; imported documents never become memories. Credentials are refused.
//!
//! **Provenance and confidence:** `source` says who worded it ("user": the owner typed it;
//! "assistant": Atlas proposed it and the owner approved it). `confirmed_at` is when the owner last
//! wrote, corrected or confirmed it; `conversation_id` is where it was saved, when it came from one.
//!
//! **Lifecycle:** active → needs_review (a fact unconfirmed for a year, a note for half a year, or a
//! review date the owner set) → active again when confirmed, or outdated / superseded (replaced by a
//! newer memory). Outdated and superseded memories are never used in conversations. Edits keep a
//! history; deleting a memory deletes its history too.
//!
//! **Duplicates and conflicts:** saving what Atlas already remembers is refused, naming the memory;
//! a memory that looks related but different is reported as a possible conflict so the owner (or the
//! approval) can choose to replace the older one.

use crate::error::{AtlasError, Result};
use crate::storage::{new_id, now, Db};
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MemoryKind {
    Preference,
    Fact,
    Note,
}

impl MemoryKind {
    fn as_str(self) -> &'static str {
        match self {
            MemoryKind::Preference => "preference",
            MemoryKind::Fact => "fact",
            MemoryKind::Note => "note",
        }
    }
    /// How long a memory of this kind stays trusted without the owner confirming it.
    pub fn review_after_days(self) -> Option<i64> {
        match self {
            MemoryKind::Preference => None,
            MemoryKind::Fact => Some(365),
            MemoryKind::Note => Some(180),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Memory {
    pub id: String,
    pub project_id: Option<String>,
    pub kind: MemoryKind,
    pub content: String,
    pub source: String,
    pub pinned: bool,
    pub use_count: i64,
    pub last_used_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    /// active | needs_review | outdated | superseded
    #[serde(default = "active")]
    pub status: String,
    #[serde(default)]
    pub confirmed_at: Option<String>,
    #[serde(default)]
    pub review_after: Option<String>,
    #[serde(default)]
    pub superseded_by: Option<String>,
    #[serde(default)]
    pub conversation_id: Option<String>,
}

fn active() -> String {
    "active".into()
}

/// A memory selected for a request, with the reason it was selected.
#[derive(Debug, Clone, Serialize)]
pub struct Retrieved {
    pub memory: Memory,
    pub reason: String,
    pub score: f64,
}

pub const MAX_MEMORY_CHARS: usize = 2000;
/// Most characters of memories added to one request (on top of `max_retrieved`).
pub const CONTEXT_CHAR_BUDGET: usize = 1800;

pub fn validate_content(content: &str) -> Result<String> {
    let c = content.trim();
    if c.is_empty() {
        return Err(AtlasError::Validation("memory is empty".into()));
    }
    if c.chars().count() > MAX_MEMORY_CHARS {
        return Err(AtlasError::Validation(format!("memory is longer than {MAX_MEMORY_CHARS} characters")));
    }
    if crate::redact::contains_secret(c) {
        return Err(AtlasError::PermissionDenied(
            "this looks like it contains a password or API key; Atlas never stores credentials as memories".into(),
        ));
    }
    Ok(c.to_string())
}

fn history(db: &Db, memory_id: &str, action: &str, actor: &str, old: Option<&str>, new: Option<&str>) -> Result<()> {
    db.conn()?.execute(
        "INSERT INTO memory_history(id, memory_id, ts, action, actor, old_content, new_content) VALUES (?1,?2,?3,?4,?5,?6,?7)",
        rusqlite::params![new_id(), memory_id, now(), action, actor, old, new],
    )?;
    Ok(())
}

/// How a candidate relates to an existing memory.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Similar {
    pub memory: Memory,
    /// "duplicate" (says the same thing) or "related" (overlapping subject, different content:
    /// possibly a newer version or a contradiction).
    pub relation: String,
    pub overlap: f64,
}

fn normalized(s: &str) -> String {
    s.to_lowercase().split(|c: char| !c.is_alphanumeric()).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ")
}

fn jaccard(a: &[String], b: &[String]) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let sa: std::collections::HashSet<&String> = a.iter().collect();
    let sb: std::collections::HashSet<&String> = b.iter().collect();
    sa.intersection(&sb).count() as f64 / sa.union(&sb).count() as f64
}

/// Existing memories in the same scope (that project, or global) that say the same thing as
/// `content`, or overlap enough to be a possible conflict. Outdated and superseded ones are ignored.
pub fn similar(db: &Db, content: &str, project_id: Option<&str>, except: Option<&str>) -> Result<Vec<Similar>> {
    let ts = terms(content);
    if ts.is_empty() {
        return Ok(vec![]);
    }
    let fts_query = ts.iter().map(|t| format!("\"{t}\"")).collect::<Vec<_>>().join(" OR ");
    let candidates: Vec<Memory> = {
        let conn = db.conn()?;
        let mut stmt = conn.prepare(&format!(
            "SELECT {COLS} FROM memories_fts JOIN memories m ON m.rowid = memories_fts.rowid
             WHERE memories_fts MATCH ?1 AND m.project_id IS ?2 AND m.id IS NOT ?3 AND m.status IN ('active','needs_review')
             ORDER BY bm25(memories_fts) LIMIT 25"
        ))?;
        stmt.query_map(rusqlite::params![fts_query, project_id, except], row)?.collect::<std::result::Result<_, _>>()?
    };
    let norm = normalized(content);
    // Duplicates are judged on every word, numbers and short words included ("room 12" is not
    // "room 14"); a possible conflict on the meaningful terms.
    let words = |s: &str| normalized(s).split(' ').filter(|w| !w.is_empty() && !STOPWORDS.contains(w)).map(str::to_string).collect::<Vec<_>>();
    let all_words = words(content);
    let mut out = Vec::new();
    for m in candidates {
        let overlap = jaccard(&ts, &terms(&m.content));
        let relation = if normalized(&m.content) == norm || jaccard(&all_words, &words(&m.content)) >= 0.9 {
            "duplicate"
        } else if overlap >= 0.4 {
            "related"
        } else {
            continue;
        };
        out.push(Similar { memory: m, relation: relation.into(), overlap });
    }
    out.sort_by(|a, b| b.overlap.partial_cmp(&a.overlap).unwrap_or(std::cmp::Ordering::Equal));
    Ok(out)
}

/// Everything needed to save a memory.
#[derive(Debug, Clone)]
pub struct NewMemory<'a> {
    pub project_id: Option<&'a str>,
    pub kind: MemoryKind,
    pub content: &'a str,
    /// "user" or "assistant"
    pub source: &'a str,
    pub pinned: bool,
    pub conversation_id: Option<&'a str>,
    pub review_after: Option<&'a str>,
}

/// Save a memory. Refused when an active memory in the same scope already says the same thing.
pub fn save(db: &Db, n: NewMemory<'_>) -> Result<Memory> {
    let content = validate_content(n.content)?;
    if !matches!(n.source, "user" | "assistant") {
        return Err(AtlasError::Validation("unknown memory source".into()));
    }
    if let Some(d) = similar(db, &content, n.project_id, None)?.into_iter().find(|s| s.relation == "duplicate") {
        return Err(AtlasError::Conflict(format!("Atlas already remembers this: “{}”", d.memory.content.chars().take(120).collect::<String>())));
    }
    if let Some(r) = n.review_after {
        DateTime::parse_from_rfc3339(r).map_err(|_| AtlasError::Validation("the review date is not a valid time".into()))?;
    }
    let id = new_id();
    let t = now();
    db.conn()?.execute(
        "INSERT INTO memories(id, project_id, kind, content, source, pinned, created_at, updated_at, confirmed_at, conversation_id, review_after) VALUES (?1,?2,?3,?4,?5,?6,?7,?7,?7,?8,?9)",
        rusqlite::params![id, n.project_id, n.kind.as_str(), content, n.source, n.pinned as i64, t, n.conversation_id, n.review_after],
    )?;
    history(db, &id, "created", n.source, None, Some(&content))?;
    get(db, &id)
}

/// The original form (kept for callers that need no provenance).
pub fn create(db: &Db, project_id: Option<&str>, kind: MemoryKind, content: &str, source: &str, pinned: bool) -> Result<Memory> {
    save(db, NewMemory { project_id, kind, content, source, pinned, conversation_id: None, review_after: None })
}

/// The owner's edit. A changed wording counts as a correction: it is recorded in the history, the
/// memory becomes active and confirmed now.
pub fn update(db: &Db, id: &str, content: Option<&str>, kind: Option<MemoryKind>, pinned: Option<bool>, project_id: Option<Option<&str>>) -> Result<Memory> {
    let current = get(db, id)?;
    let new_content = match content {
        Some(c) => validate_content(c)?,
        None => current.content.clone(),
    };
    let kind = kind.unwrap_or(current.kind);
    let pinned = pinned.unwrap_or(current.pinned);
    let project = match project_id {
        Some(p) => p.map(str::to_string),
        None => current.project_id.clone(),
    };
    let corrected = new_content != current.content;
    if corrected && let Some(d) = similar(db, &new_content, project.as_deref(), Some(id))?.into_iter().find(|s| s.relation == "duplicate") {
        return Err(AtlasError::Conflict(format!("Atlas already remembers this: “{}”", d.memory.content.chars().take(120).collect::<String>())));
    }
    let t = now();
    db.conn()?.execute(
        "UPDATE memories SET content = ?1, kind = ?2, pinned = ?3, project_id = ?4, updated_at = ?5,
            confirmed_at = CASE WHEN ?7 THEN ?5 ELSE confirmed_at END,
            status = CASE WHEN ?7 AND status IN ('needs_review','outdated') THEN 'active' ELSE status END
         WHERE id = ?6",
        rusqlite::params![new_content, kind.as_str(), pinned as i64, project, t, id, corrected],
    )?;
    if corrected {
        history(db, id, "edited", "user", Some(&current.content), Some(&new_content))?;
    }
    get(db, id)
}

/// The owner confirms a memory is still right: active, confirmed now.
pub fn confirm(db: &Db, id: &str) -> Result<Memory> {
    let m = get(db, id)?;
    if m.status == "superseded" {
        return Err(AtlasError::Conflict("this memory was replaced by a newer one; restore it first".into()));
    }
    db.conn()?.execute("UPDATE memories SET status = 'active', confirmed_at = ?2, updated_at = ?2 WHERE id = ?1", rusqlite::params![id, now()])?;
    history(db, id, "confirmed", "user", None, None)?;
    get(db, id)
}

/// The owner says a memory is no longer true. It stays visible (for reference) but is never used.
pub fn mark_outdated(db: &Db, id: &str) -> Result<Memory> {
    get(db, id)?;
    db.conn()?.execute("UPDATE memories SET status = 'outdated', updated_at = ?2 WHERE id = ?1", rusqlite::params![id, now()])?;
    history(db, id, "marked_outdated", "user", None, None)?;
    get(db, id)
}

/// Make an outdated or superseded memory active again.
pub fn restore(db: &Db, id: &str) -> Result<Memory> {
    get(db, id)?;
    db.conn()?.execute("UPDATE memories SET status = 'active', superseded_by = NULL, confirmed_at = ?2, updated_at = ?2 WHERE id = ?1", rusqlite::params![id, now()])?;
    history(db, id, "restored", "user", None, None)?;
    get(db, id)
}

/// `old_id` is replaced by `new_id` (a newer or corrected version). The old one is kept, marked
/// superseded, and never used again.
pub fn supersede(db: &Db, old_id: &str, new_id_: &str, actor: &str) -> Result<()> {
    let old = get(db, old_id)?;
    let new = get(db, new_id_)?;
    if old.project_id != new.project_id {
        return Err(AtlasError::Validation("a memory can only replace one in the same scope".into()));
    }
    db.conn()?.execute("UPDATE memories SET status = 'superseded', superseded_by = ?2, updated_at = ?3 WHERE id = ?1", rusqlite::params![old_id, new_id_, now()])?;
    history(db, old_id, "superseded", actor, Some(&old.content), Some(&new.content))?;
    Ok(())
}

/// Mark memories that have gone too long without confirmation (or passed their review date) as
/// needing review. Returns how many changed. Runs before memories are listed or used.
pub fn refresh_review_status(db: &Db, now_utc: DateTime<Utc>) -> Result<usize> {
    let rows: Vec<(String, String, Option<String>, Option<String>)> = {
        let conn = db.conn()?;
        let mut st = conn.prepare("SELECT id, kind, confirmed_at, review_after FROM memories WHERE status = 'active'")?;
        st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?.collect::<std::result::Result<_, _>>()?
    };
    let parse = |s: &Option<String>| s.as_deref().and_then(|t| DateTime::parse_from_rfc3339(t).ok()).map(|t| t.with_timezone(&Utc));
    let mut n = 0;
    for (id, kind, confirmed, review) in rows {
        let kind = kind_from(&kind);
        let due_by_date = parse(&review).is_some_and(|r| r <= now_utc);
        let due_by_age = kind.review_after_days().zip(parse(&confirmed)).is_some_and(|(days, c)| now_utc - c >= Duration::days(days));
        if due_by_date || due_by_age {
            db.conn()?.execute("UPDATE memories SET status = 'needs_review' WHERE id = ?1 AND status = 'active'", [&id])?;
            history(db, &id, "review_due", "atlas", None, None)?;
            n += 1;
        }
    }
    Ok(n)
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct HistoryEntry {
    pub ts: String,
    pub action: String,
    pub actor: String,
    pub old_content: Option<String>,
    pub new_content: Option<String>,
}

pub fn history_of(db: &Db, id: &str) -> Result<Vec<HistoryEntry>> {
    let conn = db.conn()?;
    let mut st = conn.prepare("SELECT ts, action, actor, old_content, new_content FROM memory_history WHERE memory_id = ?1 ORDER BY ts DESC, rowid DESC LIMIT 100")?;
    Ok(st
        .query_map([id], |r| Ok(HistoryEntry { ts: r.get(0)?, action: r.get(1)?, actor: r.get(2)?, old_content: r.get(3)?, new_content: r.get(4)? }))?
        .collect::<std::result::Result<_, _>>()?)
}

/// Permanent deletion: the row, its full-text index entry and its history are removed. (The
/// content-free activity log keeps only that a memory was deleted; database backups made earlier
/// still contain it until they are deleted.)
pub fn delete(db: &Db, id: &str) -> Result<()> {
    let n = db.conn()?.execute("DELETE FROM memories WHERE id = ?1", [id])?;
    if n == 0 {
        return Err(AtlasError::NotFound("memory".into()));
    }
    Ok(())
}

pub fn delete_all(db: &Db) -> Result<usize> {
    Ok(db.conn()?.execute("DELETE FROM memories", [])?)
}

const COLS: &str = "m.id, m.project_id, m.kind, m.content, m.source, m.pinned, m.use_count, m.last_used_at, m.created_at, m.updated_at, m.status, m.confirmed_at, m.review_after, m.superseded_by, m.conversation_id";

fn kind_from(s: &str) -> MemoryKind {
    match s {
        "preference" => MemoryKind::Preference,
        "fact" => MemoryKind::Fact,
        _ => MemoryKind::Note,
    }
}

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Memory> {
    let kind: String = r.get(2)?;
    Ok(Memory {
        id: r.get(0)?,
        project_id: r.get(1)?,
        kind: kind_from(&kind),
        content: r.get(3)?,
        source: r.get(4)?,
        pinned: r.get::<_, i64>(5)? != 0,
        use_count: r.get(6)?,
        last_used_at: r.get(7)?,
        created_at: r.get(8)?,
        updated_at: r.get(9)?,
        status: r.get(10)?,
        confirmed_at: r.get(11)?,
        review_after: r.get(12)?,
        superseded_by: r.get(13)?,
        conversation_id: r.get(14)?,
    })
}

pub fn get(db: &Db, id: &str) -> Result<Memory> {
    Ok(db.conn()?.query_row(&format!("SELECT {COLS} FROM memories m WHERE m.id = ?1"), [id], row)?)
}

/// `project`: None = all memories; Some(None) = global only; Some(Some(id)) = that project only.
pub fn list(db: &Db, project: Option<Option<&str>>) -> Result<Vec<Memory>> {
    let _ = refresh_review_status(db, Utc::now());
    let conn = db.conn()?;
    let order = "ORDER BY CASE m.status WHEN 'needs_review' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, m.pinned DESC, m.updated_at DESC";
    let (sql, param): (String, Option<String>) = match project {
        None => (format!("SELECT {COLS} FROM memories m {order}"), None),
        Some(None) => (format!("SELECT {COLS} FROM memories m WHERE m.project_id IS NULL {order}"), None),
        Some(Some(p)) => (format!("SELECT {COLS} FROM memories m WHERE m.project_id = ?1 {order}"), Some(p.to_string())),
    };
    let mut stmt = conn.prepare(&sql)?;
    let rows = match param {
        Some(p) => stmt.query_map([p], row)?.collect::<std::result::Result<Vec<_>, _>>()?,
        None => stmt.query_map([], row)?.collect::<std::result::Result<Vec<_>, _>>()?,
    };
    Ok(rows)
}

const STOPWORDS: &[&str] = &[
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for", "with", "at",
    "by", "it", "this", "that", "i", "you", "me", "my", "your", "we", "can", "could", "would", "should", "what", "how",
    "do", "does", "did", "please", "about", "from", "as", "so", "if", "then", "there", "have", "has", "had", "will",
];

/// Extract search terms from free text for an FTS5 OR query (quoted to neutralise syntax).
pub fn terms(text: &str) -> Vec<String> {
    let mut out: Vec<String> = text
        .split(|c: char| !c.is_alphanumeric())
        .map(str::to_lowercase)
        .filter(|w| w.chars().count() >= 3 && !STOPWORDS.contains(&w.as_str()))
        .collect();
    out.sort();
    out.dedup();
    out.truncate(24);
    out
}

/// Relevance search. Scope: global memories plus the given project's memories. Outdated and
/// superseded memories are never returned; one needing review is returned with that said and ranked
/// lower. Ranking: text relevance, then pinned, then how recently the owner confirmed it.
pub fn search(db: &Db, query: &str, project_id: Option<&str>, limit: u32) -> Result<Vec<Retrieved>> {
    let ts = terms(query);
    if ts.is_empty() {
        return Ok(vec![]);
    }
    let _ = refresh_review_status(db, Utc::now());
    let fts_query = ts.iter().map(|t| format!("\"{t}\"")).collect::<Vec<_>>().join(" OR ");
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS}, bm25(memories_fts) AS score FROM memories_fts
         JOIN memories m ON m.rowid = memories_fts.rowid
         WHERE memories_fts MATCH ?1 AND (m.project_id IS NULL OR m.project_id = ?2) AND m.status IN ('active','needs_review')
         ORDER BY score LIMIT ?3"
    ))?;
    let rows = stmt.query_map(rusqlite::params![fts_query, project_id, limit * 3], |r| Ok((row(r)?, r.get::<_, f64>(15)?)))?;
    let now_utc = Utc::now();
    let mut out = Vec::new();
    for item in rows {
        let (m, bm25) = item?;
        let lower = m.content.to_lowercase();
        let matched: Vec<&str> = ts.iter().filter(|t| lower.contains(t.as_str())).map(String::as_str).take(5).collect();
        let mut reason = if matched.is_empty() { "related wording".to_string() } else { format!("matches “{}”", matched.join("”, “")) };
        let age_days = m.confirmed_at.as_deref().and_then(|c| DateTime::parse_from_rfc3339(c).ok()).map(|c| (now_utc - c.with_timezone(&Utc)).num_days()).unwrap_or(0);
        let freshness = 1.0 / (1.0 + age_days as f64 / 365.0);
        let mut score = -bm25 * (0.75 + 0.25 * freshness) + if m.pinned { 0.5 } else { 0.0 };
        if m.status == "needs_review" {
            score *= 0.6;
            reason.push_str("; may be out of date (not confirmed recently)");
        }
        out.push(Retrieved { memory: m, reason, score });
    }
    out.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    out.truncate(limit as usize);
    Ok(out)
}

/// Pinned memories are always eligible for context (still bounded by `max_retrieved`), unless
/// outdated or superseded.
pub fn pinned(db: &Db, project_id: Option<&str>) -> Result<Vec<Memory>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!(
        "SELECT {COLS} FROM memories m WHERE m.pinned = 1 AND m.status IN ('active','needs_review') AND (m.project_id IS NULL OR m.project_id = ?1) ORDER BY m.updated_at DESC LIMIT 20"
    ))?;
    let rows = stmt.query_map([project_id], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

/// Keep memories for a request within the character budget (pinned first, then by rank), and
/// never the same text twice.
pub fn fit_budget(pinned: Vec<Memory>, retrieved: Vec<Retrieved>, max: usize, budget: usize) -> (Vec<Memory>, Vec<Retrieved>) {
    let mut used = 0usize;
    let mut seen = std::collections::HashSet::new();
    let mut p_out = Vec::new();
    for m in pinned {
        let n = m.content.chars().count();
        if p_out.len() >= max || used + n > budget || !seen.insert(normalized(&m.content)) {
            continue;
        }
        used += n;
        p_out.push(m);
    }
    let mut r_out = Vec::new();
    for r in retrieved {
        let n = r.memory.content.chars().count();
        if p_out.len() + r_out.len() >= max || used + n > budget || !seen.insert(normalized(&r.memory.content)) {
            continue;
        }
        used += n;
        r_out.push(r);
    }
    (p_out, r_out)
}

pub fn mark_used(db: &Db, ids: &[String]) {
    if let Ok(conn) = db.conn() {
        for id in ids {
            let _ = conn.execute(
                "UPDATE memories SET use_count = use_count + 1, last_used_at = ?1 WHERE id = ?2",
                rusqlite::params![now(), id],
            );
        }
    }
}

/// How the owner can read a memory's provenance.
pub fn provenance(m: &Memory) -> &'static str {
    match m.source.as_str() {
        "assistant" => "suggested by Atlas, approved by you",
        _ => "added by you",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crud_search_scope_and_deletion() {
        let db = Db::open_in_memory().unwrap();
        let p = crate::projects::create(&db, "Garden", "", "").unwrap();
        let g = create(&db, None, MemoryKind::Preference, "Prefers metric units for measurements", "user", false).unwrap();
        create(&db, Some(&p.id), MemoryKind::Fact, "The tomato beds get afternoon sun", "user", false).unwrap();
        let other = crate::projects::create(&db, "Other", "", "").unwrap();
        create(&db, Some(&other.id), MemoryKind::Fact, "Tomato prices rose in spring", "user", false).unwrap();

        let r = search(&db, "where should the tomato go?", Some(&p.id), 5).unwrap();
        assert_eq!(r.len(), 1, "other projects' memories must not leak: {r:?}");
        assert!(r[0].reason.contains("tomato"));

        let r = search(&db, "which units for measurements", None, 5).unwrap();
        assert_eq!(r[0].memory.id, g.id);

        update(&db, &g.id, Some("Prefers imperial units"), None, Some(true), None).unwrap();
        assert!(search(&db, "metric", None, 5).unwrap().is_empty(), "FTS index follows edits");
        delete(&db, &g.id).unwrap();
        assert!(search(&db, "imperial", None, 5).unwrap().is_empty(), "deleted memories are gone from search");
        assert!(get(&db, &g.id).is_err());
    }

    #[test]
    fn refuses_secrets_and_fts_syntax_is_neutralised() {
        let db = Db::open_in_memory().unwrap();
        assert_eq!(
            create(&db, None, MemoryKind::Note, "my api_key=sk-ant-abcdefghijklmnop", "user", false).unwrap_err().code(),
            "permission_denied"
        );
        create(&db, None, MemoryKind::Note, "quotes and stars", "user", false).unwrap();
        assert!(search(&db, "\"quotes\" AND * NEAR(", None, 5).is_ok());
    }

    #[test]
    fn duplicates_are_refused_and_related_memories_are_reported() {
        let db = Db::open_in_memory().unwrap();
        let a = create(&db, None, MemoryKind::Preference, "Prefers tea over coffee in the morning", "user", false).unwrap();
        let e = create(&db, None, MemoryKind::Preference, "prefers TEA over coffee in the morning!", "assistant", false).unwrap_err();
        assert_eq!(e.code(), "conflict");
        assert!(e.to_string().contains("already remembers"));
        let s = similar(&db, "Prefers coffee over tea in the morning now", None, None).unwrap();
        assert_eq!(s.len(), 1);
        assert_eq!(s[0].memory.id, a.id);
        // The same words in another project are not a duplicate (different scope).
        let p = crate::projects::create(&db, "P", "", "").unwrap();
        assert!(create(&db, Some(&p.id), MemoryKind::Preference, "Prefers tea over coffee in the morning", "user", false).is_ok());
        assert!(similar(&db, "Completely unrelated sentence about bicycles", None, None).unwrap().is_empty());
        // Different numbers are different memories, not duplicates.
        create(&db, None, MemoryKind::Fact, "Meeting room 12 has the projector", "user", false).unwrap();
        assert!(create(&db, None, MemoryKind::Fact, "Meeting room 14 has the projector", "user", false).is_ok());
    }

    #[test]
    fn corrections_supersession_outdated_and_review_shape_what_is_used() {
        let db = Db::open_in_memory().unwrap();
        let old = create(&db, None, MemoryKind::Fact, "Works at the Lisbon office", "user", false).unwrap();
        let new = create(&db, None, MemoryKind::Fact, "Works at the Porto office since November", "assistant", false).unwrap();
        supersede(&db, &old.id, &new.id, "user").unwrap();
        let r = search(&db, "which office does the user work at", None, 5).unwrap();
        assert_eq!(r.iter().map(|x| x.memory.id.as_str()).collect::<Vec<_>>(), [new.id.as_str()], "a superseded memory is never used");
        assert_eq!(get(&db, &old.id).unwrap().superseded_by.as_deref(), Some(new.id.as_str()));

        // A correction is recorded and counts as confirmation.
        let corrected = update(&db, &new.id, Some("Works at the Porto office, Rua das Flores"), None, None, None).unwrap();
        assert_eq!(corrected.status, "active");
        let h = history_of(&db, &new.id).unwrap();
        assert_eq!(h[0].action, "edited");
        assert_eq!(h[0].old_content.as_deref(), Some("Works at the Porto office since November"));

        mark_outdated(&db, &new.id).unwrap();
        assert!(search(&db, "office", None, 5).unwrap().is_empty(), "outdated memories are not used");
        restore(&db, &new.id).unwrap();
        assert_eq!(search(&db, "office", None, 5).unwrap().len(), 1);

        // A fact unconfirmed for over a year needs review: still usable, ranked lower, and said so.
        db.conn().unwrap().execute("UPDATE memories SET confirmed_at = '2024-01-01T00:00:00.000Z' WHERE id = ?1", [&new.id]).unwrap();
        assert_eq!(refresh_review_status(&db, Utc::now()).unwrap(), 1);
        let r = search(&db, "office", None, 5).unwrap();
        assert!(r[0].reason.contains("may be out of date"));
        let c = confirm(&db, &new.id).unwrap();
        assert_eq!(c.status, "active");
        assert!(!search(&db, "office", None, 5).unwrap()[0].reason.contains("out of date"));
        // Preferences never age into review.
        let pref = create(&db, None, MemoryKind::Preference, "Likes short answers", "user", false).unwrap();
        db.conn().unwrap().execute("UPDATE memories SET confirmed_at = '2020-01-01T00:00:00.000Z' WHERE id = ?1", [&pref.id]).unwrap();
        refresh_review_status(&db, Utc::now()).unwrap();
        assert_eq!(get(&db, &pref.id).unwrap().status, "active");
        // Deleting removes the history too.
        delete(&db, &new.id).unwrap();
        assert!(history_of(&db, &new.id).unwrap().is_empty());
    }

    #[test]
    fn the_budget_keeps_requests_small_and_free_of_repeats() {
        let m = |id: &str, c: &str| Memory {
            id: id.into(), project_id: None, kind: MemoryKind::Note, content: c.into(), source: "user".into(), pinned: false, use_count: 0, last_used_at: None,
            created_at: String::new(), updated_at: String::new(), status: "active".into(), confirmed_at: None, review_after: None, superseded_by: None, conversation_id: None,
        };
        let long = "x".repeat(1000);
        let r = |id: &str, c: &str| Retrieved { memory: m(id, c), reason: String::new(), score: 1.0 };
        let (p, rs) = fit_budget(vec![m("p", "Pinned note")], vec![r("a", &long), r("b", "Pinned note"), r("c", &long), r("d", "short")], 6, 1800);
        assert_eq!(p.len(), 1);
        assert_eq!(rs.iter().map(|x| x.memory.id.as_str()).collect::<Vec<_>>(), ["a", "d"], "budget and duplicates respected");
    }
}
