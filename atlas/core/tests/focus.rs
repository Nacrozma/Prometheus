//! Focus Mode (what is held, what always comes through, the end summary) and the session recap
//! (built from recorded events after time away), plus the v6 database upgrade.

use atlas_core::desktop::{Category, NewNotification, NotificationCenter, NotificationSettings, Notifier, SystemNotice};
use atlas_core::events::RecordingBus;
use atlas_core::storage::{migrations, Db};
use atlas_core::{focus, recap};
use chrono::{Duration, Utc};
use std::sync::{Arc, Mutex};

#[derive(Default)]
struct Shell {
    shown: Mutex<Vec<String>>,
}
impl Notifier for Shell {
    fn in_front(&self) -> bool {
        false
    }
    fn show(&self, n: &SystemNotice) -> bool {
        self.shown.lock().unwrap().push(n.title.clone());
        true
    }
}

fn setup() -> (Arc<Db>, Arc<NotificationCenter>, Arc<Shell>) {
    let db = Arc::new(Db::open_in_memory().unwrap());
    let center = Arc::new(NotificationCenter::new(db.clone(), Arc::new(RecordingBus::default())));
    let shell = Arc::new(Shell::default());
    center.set_notifier(shell.clone());
    (db, center, shell)
}
fn raise(center: &NotificationCenter, s: &NotificationSettings, c: Category, title: &str) {
    center.raise(s, NewNotification { category: c, title, detail: "", target: "", dedupe_key: "", only_if_away: false }).unwrap();
}

#[test]
fn focus_holds_what_can_wait_and_lets_approvals_and_failures_through() {
    let (db, center, shell) = setup();
    let s = NotificationSettings { system: true, show_details: true, ..Default::default() };
    let t0 = Utc::now();
    focus::start(&db, 25, None, "Write the report", t0).unwrap();
    raise(&center, &s, Category::Reminder, "Stretch");
    raise(&center, &s, Category::Reply, "Atlas has replied");
    raise(&center, &s, Category::Mission, "Mission updated");
    raise(&center, &s, Category::Briefing, "Morning briefing");
    raise(&center, &s, Category::Approval, "Approval needed");
    raise(&center, &s, Category::Error, "Something failed");
    let shown = shell.shown.lock().unwrap().clone();
    assert!(shown.iter().any(|t| t.contains("Approval")) && shown.iter().any(|t| t.contains("failed")), "{shown:?}");
    assert!(!shown.iter().any(|t| t.contains("Stretch") || t.contains("replied") || t.contains("Mission") || t.contains("briefing")), "held ones are not shown by the system: {shown:?}");
    assert_eq!(shown.len(), 2, "only the approval and the failure reached the system: {shown:?}");
    let list = center.list(20).unwrap();
    let held: Vec<_> = list.iter().filter(|n| n.held).map(|n| n.title.as_str()).collect();
    assert_eq!(held, ["Morning briefing", "Mission updated", "Atlas has replied", "Stretch"], "held ones are still listed in Atlas");

    // Ending releases them and says what waited.
    let done = focus::end(&db, "stopped", t0 + Duration::minutes(12)).unwrap().unwrap();
    let released = center.release_held().unwrap();
    assert_eq!(released, ["Morning briefing", "Mission updated", "Atlas has replied", "Stretch"]);
    assert!(center.release_held().unwrap().is_empty(), "nothing is released twice");
    assert_eq!(center.list(20).unwrap().len(), 6, "no notice lost or duplicated");
    assert!(center.list(20).unwrap().iter().all(|n| !n.held));
    let (title, detail) = focus::summary(&done, &released);
    assert_eq!(title, "Focus session stopped: Write the report");
    assert_eq!(detail, "12 minutes of focus. 4 notifications waited, latest: Morning briefing.");
    // After the session, nothing is held.
    raise(&center, &s, Category::Reminder, "After");
    assert!(shell.shown.lock().unwrap().iter().any(|t| t.contains("After")));
}

#[test]
fn a_session_on_a_task_needs_an_open_task() {
    let (db, _, _) = setup();
    let now = chrono::Local::now().naive_local();
    let t = atlas_core::todos::create(&db, atlas_core::todos::NewTodo { title: "Draft the plan".into(), ..Default::default() }, now).unwrap();
    assert_eq!(focus::start(&db, 25, Some("nope"), "", Utc::now()).unwrap_err().code(), "not_found");
    let s = focus::start(&db, 25, Some(&t.id), "", Utc::now()).unwrap();
    assert_eq!(s.todo_title.as_deref(), Some("Draft the plan"));
    focus::end(&db, "completed", Utc::now()).unwrap();
    atlas_core::todos::set_status(&db, &t.id, "done", now).unwrap();
    assert_eq!(focus::start(&db, 25, Some(&t.id), "", Utc::now()).unwrap_err().code(), "validation");
}

#[test]
fn the_recap_reports_what_was_recorded_while_away() {
    let (db, center, _) = setup();
    let s = NotificationSettings::default();
    let away = Utc::now() - Duration::hours(3);
    recap::on_start(&db, away).unwrap();
    // While away (between the last activity and now): a reminder and a reply were raised.
    raise(&center, &s, Category::Reminder, "Water the plants");
    raise(&center, &s, Category::Reply, "Atlas has replied: trip plan");
    raise(&center, &s, Category::Test, "Ignored test notice");
    recap::on_start(&db, Utc::now()).unwrap();
    let r = recap::current(&db).unwrap().expect("a recap after three hours away");
    assert!(!r.empty);
    let titles: Vec<_> = r.notices.iter().map(|(_, t)| t.as_str()).collect();
    assert_eq!(titles, ["Atlas has replied: trip plan", "Water the plants"]);
    recap::dismiss(&db).unwrap();
    assert!(recap::current(&db).unwrap().is_none());
}

#[test]
fn upgrading_a_v5_database_adds_focus_and_keeps_notifications() {
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("PRAGMA foreign_keys = ON;").unwrap();
    migrations::apply_list(&conn, &migrations::MIGRATIONS[..5]).unwrap();
    conn.execute_batch("INSERT INTO notifications(id,category,title,created_at,shown_by_system) VALUES('n1','reminder','Kept notice','2026-11-12T00:00:00Z',1);").unwrap();
    migrations::apply(&conn).unwrap();
    let count = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap();
    assert_eq!(count("SELECT COUNT(*) FROM notifications WHERE id='n1' AND held=0 AND shown_by_system=1"), 1);
    conn.execute("INSERT INTO focus_sessions(id,started_at,planned_end) VALUES('f1','a','b')", []).unwrap();
    assert!(conn.execute("INSERT INTO focus_sessions(id,started_at,planned_end,outcome) VALUES('f2','a','b','sideways')", []).is_err());
}

#[test]
fn every_earlier_schema_upgrades_to_v6_keeping_data_and_a_retry_changes_nothing() {
    for from in 1..migrations::MIGRATIONS.len() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        conn.execute_batch("PRAGMA foreign_keys = ON;").unwrap();
        migrations::apply_list(&conn, &migrations::MIGRATIONS[..from]).unwrap();
        conn.execute_batch("INSERT INTO settings(key, value, updated_at) VALUES ('owner_test', '{\"kept\":true}', '2026-11-12T00:00:00Z'); INSERT INTO atlas_meta(key, value) VALUES ('owner_marker', 'kept');").unwrap();
        if from >= 4 {
            // 'reply' is a kind every schema since v4 accepts.
            conn.execute_batch("INSERT INTO notifications(id,category,title,created_at) VALUES('n1','reply','Kept notice','2026-11-12T00:00:00Z');").unwrap();
        }
        migrations::apply(&conn).unwrap();
        migrations::apply(&conn).unwrap(); // a retry (e.g. the next start) is a no-op
        let one = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap();
        assert_eq!(one("PRAGMA user_version"), migrations::CURRENT_SCHEMA_VERSION, "from v{from}");
        assert_eq!(one("SELECT COUNT(*) FROM settings WHERE key='owner_test' AND value LIKE '%kept%'"), 1, "settings kept from v{from}");
        assert_eq!(one("SELECT COUNT(*) FROM atlas_meta WHERE key='owner_marker'"), 1);
        assert_eq!(one("SELECT COUNT(*) FROM focus_sessions"), 0);
        if from >= 4 {
            assert_eq!(one("SELECT COUNT(*) FROM notifications WHERE id='n1' AND held=0"), 1, "notice kept once from v{from}");
        }
    }
}

#[test]
fn an_interrupted_v6_upgrade_rolls_back_to_v5_and_can_be_retried() {
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("PRAGMA foreign_keys = ON;").unwrap();
    migrations::apply_list(&conn, &migrations::MIGRATIONS[..5]).unwrap();
    conn.execute_batch("INSERT INTO notifications(id,category,title,created_at) VALUES('n1','reminder','Kept notice','2026-11-12T00:00:00Z');").unwrap();
    // The real v6 followed by a statement that fails: the whole step must roll back.
    let broken = format!("{}\nINSERT INTO no_such_table VALUES (1);", migrations::MIGRATIONS[5]);
    let mut list: Vec<&str> = migrations::MIGRATIONS[..5].to_vec();
    list.push(&broken);
    assert!(migrations::apply_list(&conn, &list).is_err());
    let one = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap();
    assert_eq!(one("PRAGMA user_version"), 5);
    assert_eq!(one("SELECT COUNT(*) FROM sqlite_master WHERE name='focus_sessions'"), 0, "no half-made table");
    assert_eq!(one("SELECT COUNT(*) FROM notifications WHERE id='n1'"), 1);
    migrations::apply(&conn).unwrap();
    assert_eq!(one("PRAGMA user_version"), 6);
    assert_eq!(one("SELECT COUNT(*) FROM notifications WHERE id='n1' AND held=0"), 1);
}

#[test]
fn a_fresh_database_starts_at_v6() {
    let db = Db::open_in_memory().unwrap();
    let v: i64 = db.conn().unwrap().query_row("PRAGMA user_version", [], |r| r.get(0)).unwrap();
    assert_eq!(v, 6);
    assert!(!focus::is_active(&db).unwrap());
    assert!(recap::current(&db).unwrap().is_none());
}
