//! Local SQLite persistence. One connection guarded by a mutex: every operation is short and
//! synchronous, and callers never hold the lock across an `.await`.

mod migrations;

pub use migrations::{CURRENT_SCHEMA_VERSION, MIGRATIONS};

use crate::error::{AtlasError, Result};
use rusqlite::Connection;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

pub struct Db {
    conn: Mutex<Connection>,
    path: Option<PathBuf>,
}

pub fn now() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

pub fn new_id() -> String {
    uuid::Uuid::new_v4().to_string()
}

impl Db {
    /// Open (creating if needed) the database at `path` and apply pending migrations.
    /// Before migrating an existing database a copy is written next to it
    /// (`<name>.pre-v<N>.bak`) so a failed upgrade can be recovered by hand.
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let existed = path.exists();
        let conn = Connection::open(path)?;
        configure(&conn)?;
        let version = schema_version(&conn)?;
        if version > CURRENT_SCHEMA_VERSION {
            return Err(AtlasError::Storage(format!(
                "database schema v{version} is newer than this build supports (v{CURRENT_SCHEMA_VERSION}); refusing to open it"
            )));
        }
        if existed && version < CURRENT_SCHEMA_VERSION && version > 0 {
            let backup = path.with_extension(format!("pre-v{CURRENT_SCHEMA_VERSION}.bak"));
            conn.execute("VACUUM INTO ?1", [backup.to_string_lossy().as_ref()])?;
        }
        migrations::apply(&conn)?;
        Ok(Self { conn: Mutex::new(conn), path: Some(path.to_path_buf()) })
    }

    pub fn open_in_memory() -> Result<Self> {
        let conn = Connection::open_in_memory()?;
        configure(&conn)?;
        migrations::apply(&conn)?;
        Ok(Self { conn: Mutex::new(conn), path: None })
    }

    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    pub fn conn(&self) -> Result<MutexGuard<'_, Connection>> {
        self.conn.lock().map_err(|_| AtlasError::Internal("database lock poisoned".into()))
    }

    /// Run `f` inside a transaction; rolled back if it returns an error.
    pub fn tx<T>(&self, f: impl FnOnce(&rusqlite::Transaction<'_>) -> Result<T>) -> Result<T> {
        let mut conn = self.conn()?;
        let tx = conn.transaction()?;
        let out = f(&tx)?;
        tx.commit()?;
        Ok(out)
    }

    pub fn schema_version(&self) -> Result<i64> {
        schema_version(&*self.conn()?)
    }

    /// Write a consistent snapshot of the whole database to `dest` (must not exist).
    pub fn backup_to(&self, dest: &Path) -> Result<()> {
        if dest.exists() {
            return Err(AtlasError::Conflict("backup destination already exists".into()));
        }
        self.conn()?.execute("VACUUM INTO ?1", [dest.to_string_lossy().as_ref()])?;
        Ok(())
    }

    /// Replace the live database with a validated backup file. The backup is opened read-only,
    /// checked for integrity and schema compatibility, then copied in via the SQLite backup API
    /// while holding the connection lock. Migrations are re-applied afterwards.
    pub fn restore_from(&self, src: &Path) -> Result<()> {
        let candidate = validate_backup(src)?;
        let mut conn = self.conn()?;
        {
            let backup = rusqlite::backup::Backup::new(&candidate, &mut conn)?;
            backup.run_to_completion(256, std::time::Duration::from_millis(0), None)?;
        }
        configure(&conn)?;
        migrations::apply(&conn)?;
        Ok(())
    }

    pub fn quick_check(&self) -> Result<String> {
        let conn = self.conn()?;
        Ok(conn.query_row("PRAGMA quick_check", [], |r| r.get::<_, String>(0))?)
    }

    pub fn size_bytes(&self) -> Option<u64> {
        self.path.as_ref().and_then(|p| std::fs::metadata(p).ok()).map(|m| m.len())
    }
}

/// Open a backup read-only and verify it is an ATLAS database we can restore.
pub fn validate_backup(src: &Path) -> Result<Connection> {
    let conn = Connection::open_with_flags(src, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|e| AtlasError::Validation(format!("not a readable database: {e}")))?;
    let ok: String = conn
        .query_row("PRAGMA integrity_check", [], |r| r.get(0))
        .map_err(|e| AtlasError::Validation(format!("not a valid database: {e}")))?;
    if ok != "ok" {
        return Err(AtlasError::Validation(format!("backup failed integrity check: {ok}")));
    }
    let v = schema_version(&conn)?;
    if v == 0 || v > CURRENT_SCHEMA_VERSION {
        return Err(AtlasError::Validation(format!(
            "backup schema version v{v} is not supported (this build: v{CURRENT_SCHEMA_VERSION})"
        )));
    }
    let marker: i64 = conn
        .query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='atlas_meta'", [], |r| r.get(0))?;
    if marker != 1 {
        return Err(AtlasError::Validation("file is not an ATLAS backup".into()));
    }
    Ok(conn)
}

fn configure(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        "PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL; PRAGMA busy_timeout = 5000;",
    )?;
    Ok(())
}

fn schema_version(conn: &Connection) -> Result<i64> {
    Ok(conn.query_row("PRAGMA user_version", [], |r| r.get(0))?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrates_fresh_database() {
        let db = Db::open_in_memory().unwrap();
        assert_eq!(db.schema_version().unwrap(), CURRENT_SCHEMA_VERSION);
        assert_eq!(db.quick_check().unwrap(), "ok");
    }

    #[test]
    fn reopen_is_idempotent_and_refuses_newer_schema() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("atlas.db");
        drop(Db::open(&p).unwrap());
        drop(Db::open(&p).unwrap());
        {
            let c = Connection::open(&p).unwrap();
            c.execute_batch(&format!("PRAGMA user_version = {}", CURRENT_SCHEMA_VERSION + 1)).unwrap();
        }
        let err = Db::open(&p).err().expect("must refuse");
        assert_eq!(err.code(), "storage");
    }

    #[test]
    fn failed_migration_rolls_back() {
        let conn = Connection::open_in_memory().unwrap();
        let bad: &[&str] = &["CREATE TABLE a(x); CREATE TABLE a(x);"];
        let err = migrations::apply_list(&conn, bad).expect_err("must fail");
        assert_eq!(err.code(), "storage");
        assert_eq!(schema_version(&conn).unwrap(), 0);
        let n: i64 = conn.query_row("SELECT count(*) FROM sqlite_master WHERE name='a'", [], |r| r.get(0)).unwrap();
        assert_eq!(n, 0, "partial migration must be rolled back");
    }

    #[test]
    fn backup_and_restore_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("a.db")).unwrap();
        db.conn().unwrap().execute("INSERT INTO settings(key,value,updated_at) VALUES('k','\"v1\"','t')", []).unwrap();
        let bak = dir.path().join("snap.atlasbak");
        db.backup_to(&bak).unwrap();
        assert!(db.backup_to(&bak).is_err(), "never overwrite an existing file");
        db.conn().unwrap().execute("UPDATE settings SET value='\"v2\"' WHERE key='k'", []).unwrap();
        db.restore_from(&bak).unwrap();
        let v: String = db.conn().unwrap().query_row("SELECT value FROM settings WHERE key='k'", [], |r| r.get(0)).unwrap();
        assert_eq!(v, "\"v1\"");
    }

    #[test]
    fn restore_rejects_non_atlas_files() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("a.db")).unwrap();
        let junk = dir.path().join("junk.db");
        std::fs::write(&junk, b"definitely not sqlite").unwrap();
        assert!(db.restore_from(&junk).is_err());
        let other = dir.path().join("other.db");
        Connection::open(&other).unwrap().execute_batch("CREATE TABLE t(x); PRAGMA user_version=1;").unwrap();
        assert!(db.restore_from(&other).is_err());
    }
}
