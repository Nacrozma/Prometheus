//! The owner's task list: lifecycle, deadlines, repeats, subtasks, search, and the database upgrade.

use atlas_core::storage::{migrations, Db};
use atlas_core::todos::{self, Filter, NewTodo, TodoPatch};
use chrono::{NaiveDate, NaiveDateTime};

// Thursday 12 November 2026, 10:30 local.
fn now() -> NaiveDateTime {
    NaiveDate::from_ymd_opt(2026, 11, 12).unwrap().and_hms_opt(10, 30, 0).unwrap()
}
fn at(day: u32, h: u32) -> NaiveDateTime {
    NaiveDate::from_ymd_opt(2026, 11, day).unwrap().and_hms_opt(h, 0, 0).unwrap()
}
fn db() -> Db {
    Db::open_in_memory().unwrap()
}
fn view(db: &Db, v: &str, now: NaiveDateTime) -> Vec<String> {
    todos::list(db, &Filter { view: v.into(), ..Default::default() }, now).unwrap().into_iter().map(|t| t.title).collect()
}
fn new(title: &str, date: Option<&str>) -> NewTodo {
    NewTodo { title: title.into(), due_date: date.map(str::to_string), ..Default::default() }
}

#[test]
fn lifecycle_with_history() {
    let db = db();
    let t = todos::create(&db, new("Write the report", Some("2026-11-13")), now()).unwrap();
    assert_eq!((t.status.as_str(), t.priority.as_str(), t.source.as_str(), t.overdue), ("open", "normal", "user", false));
    let t = todos::set_status(&db, &t.id, "in_progress", now()).unwrap();
    assert_eq!(t.status, "in_progress");
    let t = todos::update(&db, &t.id, TodoPatch { due_date: Some(Some("2026-11-20".into())), priority: Some("high".into()), ..Default::default() }, now()).unwrap();
    assert_eq!((t.due_date.as_deref(), t.priority.as_str()), (Some("2026-11-20"), "high"));
    let t = todos::postpone(&db, &t.id, 3, now()).unwrap();
    assert_eq!((t.due_date.as_deref(), t.postponed_count), (Some("2026-11-23"), 1));
    let t = todos::set_status(&db, &t.id, "done", now()).unwrap();
    assert!(t.completed_at.is_some() && !t.overdue);
    assert_eq!(todos::postpone(&db, &t.id, 1, now()).unwrap_err().code(), "conflict", "a finished task cannot be postponed");
    let t = todos::set_status(&db, &t.id, "open", now()).unwrap();
    assert!(t.completed_at.is_none());
    let kinds: Vec<String> = todos::history(&db, &t.id).unwrap().into_iter().map(|e| e.kind).collect();
    assert_eq!(kinds, ["created", "started", "rescheduled", "postponed", "completed", "reopened"]);
    assert_eq!(todos::delete(&db, &t.id).unwrap(), 1);
    assert_eq!(todos::get(&db, &t.id, now()).unwrap_err().code(), "not_found");
    assert_eq!(todos::delete(&db, &t.id).unwrap_err().code(), "not_found");
}

#[test]
fn overdue_today_week_and_someday_views() {
    let db = db();
    todos::create(&db, new("Yesterday's", Some("2026-11-11")), now()).unwrap();
    todos::create(&db, NewTodo { due_time: Some("09:00".into()), ..new("This morning", Some("2026-11-12")) }, now()).unwrap();
    todos::create(&db, NewTodo { due_time: Some("17:00".into()), ..new("This evening", Some("2026-11-12")) }, now()).unwrap();
    todos::create(&db, new("Today, no time", Some("2026-11-12")), now()).unwrap();
    todos::create(&db, new("Monday", Some("2026-11-16")), now()).unwrap();
    todos::create(&db, new("Next month", Some("2026-12-20")), now()).unwrap();
    todos::create(&db, new("Someday", None), now()).unwrap();

    assert_eq!(view(&db, "overdue", now()), ["Yesterday's", "This morning"], "a timed task is overdue once its time passes; an all-day one only the next day");
    assert_eq!(view(&db, "today", now()), ["Yesterday's", "This morning", "This evening", "Today, no time"]);
    assert_eq!(view(&db, "week", now()).len(), 5);
    assert_eq!(view(&db, "upcoming", now()), ["Monday", "Next month"]);
    assert_eq!(view(&db, "someday", now()), ["Someday"]);
    assert_eq!(view(&db, "open", now()).len(), 7);
    // The same list seen the next evening: everything from today is now overdue.
    assert_eq!(view(&db, "overdue", at(13, 20)).len(), 4);
    let c = todos::counts(&db, now()).unwrap();
    assert_eq!((c.open, c.overdue, c.today, c.week), (7, 2, 4, 5));
    assert!(todos::list(&db, &Filter { view: "nonsense".into(), ..Default::default() }, now()).is_err());
}

#[test]
fn repeating_tasks_roll_forward_once_and_never_pile_up() {
    let db = db();
    let t = todos::create(&db, NewTodo { recurrence: Some("weekly".into()), due_time: Some("10:00".into()), remind_at: Some("2026-11-12T08:00:00Z".into()), ..new("Team sync", Some("2026-11-12")) }, now()).unwrap();
    let sub = todos::create(&db, NewTodo { parent_id: Some(t.id.clone()), ..new("Prepare agenda", None) }, now()).unwrap();
    todos::set_status(&db, &sub.id, "done", now()).unwrap();
    todos::set_status(&db, &t.id, "done", now()).unwrap();
    let open = todos::list(&db, &Filter { view: "open".into(), ..Default::default() }, now()).unwrap();
    assert_eq!(open.len(), 1, "exactly one next occurrence");
    let next = &open[0];
    assert_eq!((next.title.as_str(), next.due_date.as_deref(), next.due_time.as_deref(), next.recurrence.as_str()), ("Team sync", Some("2026-11-19"), Some("10:00"), "weekly"));
    assert!(next.remind_at.is_some(), "the reminder repeats with the task");
    assert_eq!((next.subtasks_total, next.subtasks_done), (1, 0), "subtasks repeat, reset to open");
    // Completing the same occurrence again (a double click, a retry) creates nothing more.
    todos::set_status(&db, &t.id, "open", now()).unwrap();
    todos::set_status(&db, &t.id, "done", now()).unwrap();
    assert_eq!(view(&db, "open", now()).len(), 1, "no duplicate occurrence");
    // A daily task finished three weeks late gets one occurrence from today, not twenty.
    let d = todos::create(&db, NewTodo { recurrence: Some("daily".into()), ..new("Vitamins", Some("2026-10-20")) }, now()).unwrap();
    todos::set_status(&db, &d.id, "done", now()).unwrap();
    let v: Vec<_> = todos::list(&db, &Filter { view: "open".into(), search: Some("Vitamins".into()), ..Default::default() }, now()).unwrap();
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].due_date.as_deref(), Some("2026-11-12"));
    // A cancelled repeating task does not come back.
    todos::set_status(&db, &v[0].id, "cancelled", now()).unwrap();
    assert!(todos::list(&db, &Filter { view: "open".into(), search: Some("Vitamins".into()), ..Default::default() }, now()).unwrap().is_empty());
}

#[test]
fn subtasks_follow_their_parent() {
    let db = db();
    let p = atlas_core::projects::create(&db, "Thesis", "", "").unwrap();
    let parent = todos::create(&db, NewTodo { project_id: Some(p.id.clone()), ..new("Chapter 2", None) }, now()).unwrap();
    let a = todos::create(&db, NewTodo { parent_id: Some(parent.id.clone()), ..new("Outline", None) }, now()).unwrap();
    let b = todos::create(&db, NewTodo { parent_id: Some(parent.id.clone()), ..new("Draft", None) }, now()).unwrap();
    assert_eq!(a.project_id.as_deref(), Some(p.id.as_str()), "a subtask lives in its parent's project");
    assert_eq!(todos::create(&db, NewTodo { parent_id: Some(a.id.clone()), ..new("Too deep", None) }, now()).unwrap_err().code(), "validation");
    assert_eq!(todos::create(&db, NewTodo { parent_id: Some("missing".into()), ..new("Orphan", None) }, now()).unwrap_err().code(), "not_found");
    todos::set_status(&db, &a.id, "done", now()).unwrap();
    let parent = todos::get(&db, &parent.id, now()).unwrap();
    assert_eq!((parent.subtasks_total, parent.subtasks_done), (2, 1));
    assert_eq!(view(&db, "open", now()), ["Chapter 2"], "lists show top-level tasks; subtasks sit inside them");
    // Finishing the parent finishes what was still open underneath it.
    todos::set_status(&db, &parent.id, "done", now()).unwrap();
    assert_eq!(todos::get(&db, &b.id, now()).unwrap().status, "done");
    // Deleting the parent removes its subtasks and their history.
    assert_eq!(todos::delete(&db, &parent.id).unwrap(), 3);
    assert_eq!(todos::get(&db, &b.id, now()).unwrap_err().code(), "not_found");
    // Deleting a project keeps its tasks (they become unfiled) rather than deleting the owner's work.
    let t = todos::create(&db, NewTodo { project_id: Some(p.id.clone()), ..new("Keep me", None) }, now()).unwrap();
    atlas_core::projects::delete(&db, &p.id).unwrap();
    assert_eq!(todos::get(&db, &t.id, now()).unwrap().project_id, None);
}

#[test]
fn search_filters_and_hostile_input() {
    let db = db();
    let p = atlas_core::projects::create(&db, "Home", "", "").unwrap();
    todos::create(&db, NewTodo { category: Some("health".into()), priority: Some("urgent".into()), ..new("Book the dentist", None) }, now()).unwrap();
    todos::create(&db, NewTodo { project_id: Some(p.id.clone()), notes: "50% off until friday_morning".into(), ..new("Order paint", None) }, now()).unwrap();
    let parent = todos::create(&db, new("Trip", None), now()).unwrap();
    todos::create(&db, NewTodo { parent_id: Some(parent.id.clone()), ..new("Renew passport", None) }, now()).unwrap();
    let find = |f: Filter| todos::list(&db, &f, now()).unwrap().into_iter().map(|t| t.title).collect::<Vec<_>>();
    assert_eq!(find(Filter { search: Some("dentist".into()), ..Default::default() }), ["Book the dentist"]);
    assert_eq!(find(Filter { search: Some("passport".into()), ..Default::default() }), ["Trip"], "a search matches subtasks and shows their parent");
    assert_eq!(find(Filter { category: Some("HEALTH".into()), ..Default::default() }), ["Book the dentist"]);
    assert_eq!(find(Filter { priority: Some("urgent".into()), ..Default::default() }), ["Book the dentist"]);
    assert_eq!(find(Filter { project_id: Some(p.id.clone()), ..Default::default() }), ["Order paint"]);
    // Wildcards in a search are literal text, not patterns.
    assert_eq!(find(Filter { search: Some("50%".into()), ..Default::default() }), ["Order paint"]);
    assert!(find(Filter { search: Some("%".into()), ..Default::default() }).len() == 1);
    assert!(find(Filter { search: Some("friday_morning".into()), ..Default::default() }).len() == 1);
    assert!(find(Filter { search: Some("x' OR '1'='1".into()), ..Default::default() }).is_empty());
    assert_eq!(todos::categories(&db).unwrap(), ["health"]);

    for bad in [
        NewTodo { title: "  ".into(), ..Default::default() },
        NewTodo { title: "x".repeat(301), ..Default::default() },
        NewTodo { priority: Some("extreme".into()), ..new("x", None) },
        NewTodo { due_time: Some("09:00".into()), ..new("time without a date", None) },
        NewTodo { recurrence: Some("weekly".into()), ..new("repeat without a date", None) },
        NewTodo { recurrence: Some("hourly".into()), ..new("x", Some("2026-11-12")) },
        NewTodo { recur_interval: Some(0), ..new("x", Some("2026-11-12")) },
        NewTodo { remind_at: Some("soon".into()), ..new("x", None) },
        NewTodo { project_id: Some("no-such-project".into()), ..new("x", None) },
        new("x", Some("2026-02-31")),
        new("x", Some("tomorrow")),
    ] {
        assert!(todos::create(&db, bad.clone(), now()).is_err(), "{bad:?}");
    }
    // A pasted secret never lands in the task list.
    let t = todos::create(&db, new("rotate key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", None), now()).unwrap();
    assert!(!t.title.contains("AAAAAAAA"), "{}", t.title);
}

#[test]
fn quick_entry_creates_what_it_says() {
    let db = db();
    let t = todos::quick_add(&db, "Remind me to call the dentist tomorrow at 9am !high #health", None, "user", None, now()).unwrap();
    assert_eq!((t.title.as_str(), t.due_date.as_deref(), t.due_time.as_deref(), t.priority.as_str(), t.category.as_str()), ("call the dentist", Some("2026-11-13"), Some("09:00"), "high", "health"));
    assert!(t.remind_at.is_some());
    let t = todos::quick_add(&db, "Buy milk", None, "user", None, now()).unwrap();
    assert_eq!((t.due_date, t.remind_at), (None, None), "no date is invented");
    let t = todos::quick_add(&db, "Backup weekly", None, "user", None, now()).unwrap();
    assert_eq!((t.recurrence.as_str(), t.due_date.as_deref()), ("weekly", Some("2026-11-12")), "a repeat with no date starts today");
    assert_eq!(todos::quick_add(&db, "tomorrow", None, "user", None, now()).unwrap_err().code(), "validation", "a line that is only a date has no title");
    // Moving a deadline moves its reminder with it.
    let t = todos::quick_add(&db, "Remind me to submit friday 5pm", None, "user", None, now()).unwrap();
    let before = t.remind_at.clone();
    let t = todos::update(&db, &t.id, TodoPatch { due_date: Some(Some("2026-11-20".into())), ..Default::default() }, now()).unwrap();
    assert!(t.remind_at.is_some() && t.remind_at != before);
    let t = todos::update(&db, &t.id, TodoPatch { due_date: Some(None), ..Default::default() }, now()).unwrap();
    assert_eq!((t.due_date, t.due_time, t.remind_at), (None, None, None), "clearing the date clears its time and reminder");
}

#[test]
fn upgrading_a_0_4_2_database_keeps_everything_and_adds_the_task_tables() {
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("PRAGMA foreign_keys = ON;").unwrap();
    // A database exactly as 0.4.2 left it (schema 4), with the owner's data in it.
    migrations::apply_list(&conn, &migrations::MIGRATIONS[..4]).unwrap();
    conn.execute_batch(
        "INSERT INTO projects(id,name,description,instructions,created_at,updated_at) VALUES('p1','Kept project','','','2026-11-01T00:00:00Z','2026-11-01T00:00:00Z');
         INSERT INTO conversations(id,project_id,title,archived,created_at,updated_at) VALUES('c1','p1','Kept conversation',0,'2026-11-01T00:00:00Z','2026-11-01T00:00:00Z');
         INSERT INTO memories(id,kind,content,source,created_at,updated_at) VALUES('m1','fact','Kept memory','user','2026-11-01T00:00:00Z','2026-11-01T00:00:00Z');
         INSERT INTO notifications(id,category,title,detail,target,dedupe_key,created_at,read_at,shown_by_system) VALUES('n1','approval','Kept notice','d','approvals','k','2026-11-10T00:00:00Z',NULL,1);
         INSERT INTO notifications(id,category,title,created_at,read_at) VALUES('n2','reply','Read notice','2026-11-10T00:00:01Z','2026-11-10T00:01:00Z');",
    )
    .unwrap();
    migrations::apply(&conn).unwrap();
    let v: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0)).unwrap();
    assert_eq!(v, migrations::CURRENT_SCHEMA_VERSION);
    let count = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap();
    assert_eq!(count("SELECT COUNT(*) FROM projects WHERE name='Kept project'"), 1);
    assert_eq!(count("SELECT COUNT(*) FROM conversations WHERE title='Kept conversation'"), 1);
    assert_eq!(count("SELECT COUNT(*) FROM memories WHERE content='Kept memory'"), 1);
    assert_eq!(count("SELECT COUNT(*) FROM notifications"), 2);
    assert_eq!(count("SELECT COUNT(*) FROM notifications WHERE id='n1' AND read_at IS NULL AND shown_by_system=1 AND dedupe_key='k'"), 1);
    assert_eq!(count("SELECT COUNT(*) FROM notifications WHERE id='n2' AND read_at IS NOT NULL"), 1);
    // New notification kinds are accepted; the task and scheduler tables exist and enforce their rules.
    conn.execute("INSERT INTO notifications(id,category,title,created_at) VALUES('n3','reminder','New kind','2026-11-12T00:00:00Z')", []).unwrap();
    conn.execute("INSERT INTO todos(id,title,project_id,conversation_id,created_at,updated_at) VALUES('t1','First task','p1','c1','x','x')", []).unwrap();
    assert!(conn.execute("INSERT INTO todos(id,title,status,created_at,updated_at) VALUES('t2','Bad','sideways','x','x')", []).is_err());
    conn.execute("INSERT INTO scheduled_jobs(id,kind,subject,run_at,created_at) VALUES('j1','reminder','t1','2026-11-13T09:00:00Z','x')", []).unwrap();
    assert!(conn.execute("INSERT INTO scheduled_jobs(id,kind,subject,run_at,created_at) VALUES('j2','reminder','t1','2026-11-13T09:00:00Z','x')", []).is_err(), "the same job cannot be scheduled twice");
    let broken = conn.prepare("PRAGMA foreign_key_check").unwrap().query_map([], |_| Ok(())).unwrap().count();
    assert_eq!(broken, 0, "no dangling references after the upgrade");
    let ok: String = conn.query_row("PRAGMA integrity_check", [], |r| r.get(0)).unwrap();
    assert_eq!(ok, "ok");
    // Applying again is a no-op.
    migrations::apply(&conn).unwrap();
    assert_eq!(count("SELECT COUNT(*) FROM todos"), 1);
}
