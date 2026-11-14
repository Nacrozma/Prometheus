//! Ordered schema migrations tracked with `PRAGMA user_version`. Never edit a released
//! migration; append a new one instead.

use crate::error::{AtlasError, Result};
use rusqlite::Connection;

pub const MIGRATIONS: &[&str] = &[
    // v1 — initial schema.
    r#"
    CREATE TABLE atlas_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    INSERT INTO atlas_meta(key, value) VALUES ('created_by', 'atlas-copilot');

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '',
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE conversations (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_conversations_project ON conversations(project_id);

    -- role: user | assistant | tool | notice
    -- content: what the UI shows. native: provider-exact payload replayed to that provider.
    CREATE TABLE messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user','assistant','tool','notice')),
        content TEXT NOT NULL,
        parts TEXT,
        native TEXT,
        provider_id TEXT,
        model TEXT,
        status TEXT NOT NULL DEFAULT 'complete',
        task_id TEXT,
        usage TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_messages_conversation ON messages(conversation_id, seq);
    CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', content_rowid='rowid');
    CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
    END;
    CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    END;
    CREATE TRIGGER messages_au AFTER UPDATE OF content ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
        INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
    END;

    CREATE TABLE memories (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('preference','fact','note')),
        content TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('user','assistant')),
        pinned INTEGER NOT NULL DEFAULT 0,
        use_count INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE memories_fts USING fts5(content, content='memories', content_rowid='rowid');
    CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END;
    CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    END;
    CREATE TRIGGER memories_au AFTER UPDATE OF content ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END;

    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
        request TEXT NOT NULL,
        status TEXT NOT NULL,
        plan TEXT,
        summary TEXT,
        error TEXT,
        verification TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE INDEX idx_tasks_status ON tasks(status);

    CREATE TABLE task_steps (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        tool_id TEXT NOT NULL,
        call_id TEXT,
        input TEXT NOT NULL,
        permission TEXT NOT NULL,
        status TEXT NOT NULL,
        output TEXT,
        error TEXT,
        action_hash TEXT NOT NULL,
        approval_id TEXT,
        duration_ms INTEGER,
        started_at TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE INDEX idx_steps_task ON task_steps(task_id, seq);

    -- status: pending | approved | rejected | expired | consumed
    CREATE TABLE approvals (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        step_id TEXT NOT NULL,
        tool_id TEXT NOT NULL,
        action_hash TEXT NOT NULL,
        preview TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        decided_at TEXT,
        consumed_at TEXT
    );
    CREATE INDEX idx_approvals_status ON approvals(status);

    CREATE TABLE providers (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        base_url TEXT NOT NULL,
        default_model TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'not_configured',
        status_detail TEXT,
        last_checked_at TEXT,
        models TEXT,
        key_hint TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE integrations (
        id TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'not_configured',
        status_detail TEXT,
        last_checked_at TEXT,
        key_hint TEXT,
        config TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE tool_state (
        tool_id TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 1,
        use_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT
    );

    CREATE TABLE file_grants (
        id TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        label TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE usage_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER,
        output_tokens INTEGER,
        duration_ms INTEGER NOT NULL,
        estimated_cost_usd REAL,
        outcome TEXT NOT NULL
    );
    CREATE INDEX idx_usage_ts ON usage_records(ts);

    -- Safe, content-free event log. detail never holds message text or secrets.
    CREATE TABLE audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        level TEXT NOT NULL DEFAULT 'info',
        task_id TEXT,
        tool_id TEXT,
        detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX idx_audit_ts ON audit_events(ts);
    "#,
    // v2 — Atlas Forge (engineering projects, change snapshots, command runs) and pricing provenance.
    r#"
    ALTER TABLE usage_records ADD COLUMN price_status TEXT;
    ALTER TABLE usage_records ADD COLUMN mission_id TEXT;
    CREATE INDEX idx_usage_mission ON usage_records(mission_id);

    ALTER TABLE conversations ADD COLUMN forge_project_id TEXT;
    ALTER TABLE conversations ADD COLUMN discipline TEXT;

    CREATE TABLE forge_projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL UNIQUE,
        test_command TEXT,
        build_command TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- One row per file Atlas changed in a Forge project. before_content lets a change be
    -- reverted, but only while the file still matches after_sha256 (checked at revert time).
    CREATE TABLE forge_changes (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES forge_projects(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('create','modify')),
        before_content TEXT,
        before_sha256 TEXT,
        after_sha256 TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        task_id TEXT,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        reverted_at TEXT
    );
    CREATE INDEX idx_forge_changes_project ON forge_changes(project_id, created_at);

    CREATE TABLE forge_runs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES forge_projects(id) ON DELETE CASCADE,
        argv TEXT NOT NULL,
        initiated_by TEXT NOT NULL CHECK (initiated_by IN ('user','model')),
        status TEXT NOT NULL,
        exit_code INTEGER,
        duration_ms INTEGER,
        output TEXT NOT NULL DEFAULT '',
        summary TEXT,
        task_id TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE INDEX idx_forge_runs_project ON forge_runs(project_id, created_at);
    "#,
    // v3 — sibling link (paired peers; secrets live in the OS credential store) and the mission ledger.
    r#"
    CREATE TABLE siblings (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('paired','revoked')),
        remote_version TEXT,
        adapter_version TEXT,
        capabilities TEXT,
        health TEXT,
        last_seen_at TEXT,
        last_error TEXT,
        paired_at TEXT NOT NULL,
        revoked_at TEXT
    );

    CREATE TABLE missions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('consultation','collaborative','delegated')),
        objective TEXT NOT NULL,
        shared_context TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL,
        sibling_id TEXT,
        forge_project_id TEXT,
        conversation_id TEXT,
        idempotency_key TEXT NOT NULL,
        sent_at TEXT,
        remote_state TEXT,
        remote_seq INTEGER NOT NULL DEFAULT 0,
        result_summary TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_missions_state ON missions(state);

    -- Every message and state change is a row; remote events are de-duplicated by their sequence.
    CREATE TABLE mission_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
        source TEXT NOT NULL CHECK (source IN ('atlas','prometheus','user','system')),
        kind TEXT NOT NULL,
        content TEXT NOT NULL,
        remote_seq INTEGER,
        created_at TEXT NOT NULL,
        UNIQUE (mission_id, source, remote_seq)
    );
    CREATE INDEX idx_mission_events ON mission_events(mission_id, id);
    "#,
    // v0.4.2: notifications shown in Atlas (and by the system when the owner allows it).
    r#"
    CREATE TABLE notifications (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL CHECK (category IN ('approval','reply','mission','error','test')),
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        target TEXT NOT NULL DEFAULT '',
        dedupe_key TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        read_at TEXT,
        shown_by_system INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_notifications_unread ON notifications(read_at, created_at);
    CREATE INDEX idx_notifications_dedupe ON notifications(dedupe_key, read_at);
    "#,
    // v0.5.0: the owner's tasks (to-dos), the scheduler, and more notification kinds.
    // "tasks" (above) are records of tool-using turns; the owner's to-do list is "todos".
    r#"
    CREATE TABLE todos (
        id TEXT PRIMARY KEY,
        parent_id TEXT REFERENCES todos(id) ON DELETE CASCADE,
        project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','done','cancelled')),
        priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
        category TEXT NOT NULL DEFAULT '',
        due_date TEXT,
        due_time TEXT,
        remind_at TEXT,
        recurrence TEXT NOT NULL DEFAULT 'none' CHECK (recurrence IN ('none','daily','weekdays','weekly','monthly','yearly')),
        recur_interval INTEGER NOT NULL DEFAULT 1 CHECK (recur_interval BETWEEN 1 AND 365),
        source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user','atlas')),
        conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
        postponed_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE INDEX idx_todos_status_due ON todos(status, due_date);
    CREATE INDEX idx_todos_parent ON todos(parent_id);
    CREATE INDEX idx_todos_project ON todos(project_id);
    CREATE TABLE todo_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        todo_id TEXT NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_todo_events ON todo_events(todo_id, id);

    CREATE TABLE scheduled_jobs (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        run_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','done','missed','cancelled','failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        payload TEXT NOT NULL DEFAULT '{}',
        result TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        UNIQUE (kind, subject, run_at)
    );
    CREATE INDEX idx_jobs_due ON scheduled_jobs(status, run_at);

    -- Notifications gain kinds (reminder, deadline, briefing, focus). The list of kinds is
    -- enforced in the core, so the table no longer repeats it. Existing rows are kept.
    CREATE TABLE notifications_v5 (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        target TEXT NOT NULL DEFAULT '',
        dedupe_key TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        read_at TEXT,
        shown_by_system INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO notifications_v5 SELECT id, category, title, detail, target, dedupe_key, created_at, read_at, shown_by_system FROM notifications;
    DROP TABLE notifications;
    ALTER TABLE notifications_v5 RENAME TO notifications;
    CREATE INDEX idx_notifications_unread ON notifications(read_at, created_at);
    CREATE INDEX idx_notifications_dedupe ON notifications(dedupe_key, read_at);
    "#,
    // v6 (0.5.0 stage 4): Focus Mode sessions; notifications held during one are flagged.
    // The session recap keeps its marker in atlas_meta (no table needed).
    r#"
    CREATE TABLE focus_sessions (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        planned_end TEXT NOT NULL,
        ended_at TEXT,
        todo_id TEXT REFERENCES todos(id) ON DELETE SET NULL,
        label TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '' CHECK (outcome IN ('','completed','stopped'))
    );
    CREATE INDEX idx_focus_active ON focus_sessions(ended_at);
    ALTER TABLE notifications ADD COLUMN held INTEGER NOT NULL DEFAULT 0;
    "#,
];

pub const CURRENT_SCHEMA_VERSION: i64 = MIGRATIONS.len() as i64;

pub fn apply(conn: &Connection) -> Result<()> {
    apply_list(conn, MIGRATIONS)
}

/// Apply each pending migration in its own transaction, bumping `user_version` inside it,
/// so a failure leaves the database at the last fully applied version.
pub fn apply_list(conn: &Connection, migrations: &[&str]) -> Result<()> {
    let current: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    for (idx, sql) in migrations.iter().enumerate() {
        let version = idx as i64 + 1;
        if version <= current {
            continue;
        }
        let script = format!("BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;");
        if let Err(e) = conn.execute_batch(&script) {
            let _ = conn.execute_batch("ROLLBACK;");
            return Err(AtlasError::Storage(format!("migration to v{version} failed: {e}")));
        }
    }
    Ok(())
}
