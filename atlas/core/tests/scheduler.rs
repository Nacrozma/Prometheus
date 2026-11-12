//! The scheduler: exactly-once delivery, missed jobs, pause, re-sync and crash recovery.

use atlas_core::desktop::{NotificationCenter, NotificationSettings};
use atlas_core::events::RecordingBus;
use atlas_core::scheduler::{self, ScheduleSettings};
use atlas_core::storage::Db;
use atlas_core::todos::{self, NewTodo, TodoPatch};
use chrono::{DateTime, Duration, NaiveDateTime, Utc};
use std::sync::Arc;

fn setup() -> (Arc<Db>, Arc<NotificationCenter>) {
    let db = Arc::new(Db::open_in_memory().unwrap());
    let center = Arc::new(NotificationCenter::new(db.clone(), Arc::new(RecordingBus::default())));
    (db, center)
}
fn utc(s: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
}
fn local(u: DateTime<Utc>) -> NaiveDateTime {
    u.with_timezone(&chrono::Local).naive_local()
}
fn reminder_task(db: &Db, title: &str, at: &str, now: DateTime<Utc>) -> todos::Todo {
    todos::create(db, NewTodo { title: title.into(), remind_at: Some(at.into()), ..Default::default() }, local(now)).unwrap()
}
fn titles(center: &NotificationCenter) -> Vec<String> {
    center.list(50).unwrap().into_iter().map(|n| n.title).collect()
}
fn job_statuses(db: &Db, now: DateTime<Utc>) -> Vec<(String, String)> {
    scheduler::list(db, local(now), 50).unwrap().into_iter().map(|j| (j.kind, j.status)).collect()
}

#[test]
fn a_reminder_is_delivered_once_at_its_time() {
    let (db, center) = setup();
    let s = ScheduleSettings::default();
    let n = NotificationSettings::default();
    let t0 = utc("2026-11-12T10:00:00Z");
    reminder_task(&db, "Call the dentist", "2026-11-12T10:05:00Z", t0);
    scheduler::sync(&db, &s, local(t0)).unwrap();
    scheduler::sync(&db, &s, local(t0)).unwrap();
    assert_eq!(job_statuses(&db, t0), [("reminder".into(), "pending".into())], "syncing twice schedules it once");

    // Not yet due.
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t0, local(t0)).unwrap().delivered, 0);
    assert!(titles(&center).is_empty());
    // Due: delivered once, with what it is about.
    let t1 = utc("2026-11-12T10:05:01Z");
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t1, local(t1)).unwrap().delivered, 1);
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t1, local(t1)).unwrap().delivered, 0);
    let list = center.list(10).unwrap();
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "Reminder");
    assert!(list[0].detail.starts_with("Call the dentist"));
    assert!(list[0].target.starts_with("todo:"));
    // A re-sync after delivery does not schedule it again (the moment has been used).
    scheduler::sync(&db, &s, local(t1)).unwrap();
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t1, local(t1)).unwrap().delivered, 0);
    assert_eq!(job_statuses(&db, t1), [("reminder".into(), "done".into())]);
}

#[test]
fn two_ticks_at_the_same_moment_deliver_each_job_once() {
    let (db, center) = setup();
    let s = ScheduleSettings::default();
    let t0 = utc("2026-11-12T10:00:00Z");
    for i in 0..20 {
        reminder_task(&db, &format!("Task {i}"), "2026-11-12T09:59:00Z", t0);
    }
    scheduler::sync(&db, &s, local(t0)).unwrap();
    let handles: Vec<_> = (0..4)
        .map(|_| {
            let (db, center, s) = (db.clone(), center.clone(), s.clone());
            std::thread::spawn(move || scheduler::tick(&db, &center, &s, &NotificationSettings::default(), t0, local(t0)).unwrap().delivered)
        })
        .collect();
    let total: u32 = handles.into_iter().map(|h| h.join().unwrap()).sum();
    assert_eq!(total, 20, "every job delivered exactly once across concurrent ticks");
    assert_eq!(center.list(100).unwrap().len(), 20);
}

#[test]
fn jobs_missed_while_closed_are_reported_once_together() {
    let (db, center) = setup();
    let s = ScheduleSettings::default(); // 12 h grace
    let t0 = utc("2026-11-10T08:00:00Z");
    reminder_task(&db, "Pay rent", "2026-11-10T09:00:00Z", t0);
    reminder_task(&db, "Water plants", "2026-11-10T10:00:00Z", t0);
    reminder_task(&db, "Recent one", "2026-11-12T09:30:00Z", t0);
    scheduler::sync(&db, &s, local(t0)).unwrap();
    // Atlas was closed for two days.
    let t1 = utc("2026-11-12T10:00:00Z");
    let r = scheduler::tick(&db, &center, &s, &NotificationSettings::default(), t1, local(t1)).unwrap();
    assert_eq!((r.delivered, r.missed), (1, 2), "within the grace period it is delivered late; older ones are missed");
    let list = center.list(10).unwrap();
    assert_eq!(list.len(), 2, "one reminder plus ONE grouped notice, not a burst");
    let missed = list.iter().find(|n| n.title.contains("missed")).unwrap();
    assert_eq!(missed.title, "2 reminders were missed while Atlas was closed");
    assert!(missed.detail.contains("Pay rent") && missed.detail.contains("Water plants"));
    assert_eq!(scheduler::tick(&db, &center, &s, &NotificationSettings::default(), t1, local(t1)).unwrap(), Default::default());
}

#[test]
fn the_global_pause_holds_everything_and_resuming_is_honest() {
    let (db, center) = setup();
    let mut s = ScheduleSettings { paused: true, ..Default::default() };
    let n = NotificationSettings::default();
    let t0 = utc("2026-11-12T10:00:00Z");
    reminder_task(&db, "Soon", "2026-11-12T10:01:00Z", t0);
    reminder_task(&db, "Much later", "2026-11-13T10:00:00Z", t0);
    scheduler::sync(&db, &s, local(t0)).unwrap();
    let t1 = utc("2026-11-12T10:30:00Z");
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t1, local(t1)).unwrap(), Default::default(), "paused: nothing runs");
    assert!(center.list(10).unwrap().is_empty());
    s.paused = false;
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t1, local(t1)).unwrap().delivered, 1, "resumed within the grace period: delivered");
    // Paused across the next one's time and beyond the grace period: reported as missed.
    s.paused = true;
    let t2 = utc("2026-11-14T10:00:00Z");
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t2, local(t2)).unwrap(), Default::default());
    s.paused = false;
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t2, local(t2)).unwrap().missed, 1);
    assert!(ScheduleSettings { missed_grace_minutes: 1, ..Default::default() }.validate().is_err());
    assert!(ScheduleSettings { deadline_hour: 24, ..Default::default() }.validate().is_err());
}

#[test]
fn editing_completing_or_deleting_a_task_updates_its_jobs() {
    let (db, center) = setup();
    let s = ScheduleSettings::default();
    let n = NotificationSettings::default();
    let t0 = utc("2026-11-12T10:00:00Z");
    let a = reminder_task(&db, "Moved", "2026-11-12T11:00:00Z", t0);
    let b = reminder_task(&db, "Finished early", "2026-11-12T11:00:00Z", t0);
    let c = reminder_task(&db, "Deleted", "2026-11-12T11:00:00Z", t0);
    let d = todos::create(&db, NewTodo { title: "Dated, no reminder".into(), due_date: Some(local(t0).date().to_string()), ..Default::default() }, local(t0)).unwrap();
    scheduler::sync(&db, &s, local(t0)).unwrap();
    assert_eq!(scheduler::list(&db, local(t0), 50).unwrap().iter().filter(|j| j.status == "pending").count(), 4);
    let deadline = scheduler::list(&db, local(t0), 50).unwrap().into_iter().find(|j| j.subject == d.id).unwrap();
    assert_eq!(deadline.kind, "deadline");
    assert_eq!(deadline.run_at, todos::local_to_utc(local(t0).date(), chrono::NaiveTime::from_hms_opt(9, 0, 0).unwrap()), "\"due today\" at 09:00 local");

    todos::update(&db, &a.id, TodoPatch { remind_at: Some(Some("2026-11-12T12:00:00Z".into())), ..Default::default() }, local(t0)).unwrap();
    todos::set_status(&db, &b.id, "done", local(t0)).unwrap();
    todos::delete(&db, &c.id).unwrap();
    scheduler::sync(&db, &s, local(t0)).unwrap();
    let pending: Vec<_> = scheduler::list(&db, local(t0), 50).unwrap().into_iter().filter(|j| j.status == "pending").collect();
    assert_eq!(pending.len(), 2, "{pending:?}");
    assert!(pending.iter().any(|j| j.subject == a.id && j.run_at == "2026-11-12T12:00:00.000Z"));
    let t1 = utc("2026-11-12T11:30:00Z");
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t1, local(t1)).unwrap().delivered, 1, "only the deadline notice (09:00) is due");
    assert!(!titles(&center).iter().any(|t| t == "Reminder"), "nothing for the moved, finished or deleted tasks");

    // A task finished between sync and tick is skipped, not announced.
    let e = reminder_task(&db, "Done just in time", "2026-11-12T11:40:00Z", t1);
    scheduler::sync(&db, &s, local(t1)).unwrap();
    todos::set_status(&db, &e.id, "done", local(t1)).unwrap();
    let t2 = utc("2026-11-12T11:41:00Z");
    assert_eq!(scheduler::tick(&db, &center, &s, &n, t2, local(t2)).unwrap().delivered, 0);

    // Deadline notices can be turned off.
    let off = ScheduleSettings { deadline_notices: false, ..Default::default() };
    scheduler::sync(&db, &off, local(t2)).unwrap();
    assert!(!scheduler::list(&db, local(t2), 50).unwrap().iter().any(|j| j.kind == "deadline" && j.status == "pending"));
}

#[test]
fn after_a_crash_a_half_run_job_is_finished_or_retried_never_doubled() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("atlas.db");
    let t0 = utc("2026-11-12T10:00:00Z");
    {
        let db = Arc::new(Db::open(&path).unwrap());
        let center = NotificationCenter::new(db.clone(), Arc::new(RecordingBus::default()));
        reminder_task(&db, "Delivered then crashed", "2026-11-12T09:59:00Z", t0);
        reminder_task(&db, "Crashed before delivering", "2026-11-12T09:59:00Z", t0);
        scheduler::sync(&db, &ScheduleSettings::default(), local(t0)).unwrap();
        let jobs = scheduler::list(&db, local(t0), 10).unwrap();
        // Simulate the crash: both jobs claimed; only the first had raised its notice.
        let conn = db.conn().unwrap();
        conn.execute("UPDATE scheduled_jobs SET status='running'", []).unwrap();
        drop(conn);
        let first = jobs.iter().find(|j| j.label == "Delivered then crashed").unwrap();
        center
            .raise(&NotificationSettings::default(), atlas_core::desktop::NewNotification { category: atlas_core::desktop::Category::Reminder, title: "Reminder", detail: "Delivered then crashed", target: "", dedupe_key: &format!("job:{}", first.id), only_if_away: false })
            .unwrap();
    }
    let db = Arc::new(Db::open(&path).unwrap());
    let center = NotificationCenter::new(db.clone(), Arc::new(RecordingBus::default()));
    assert_eq!(scheduler::recover(&db).unwrap(), 2);
    let r = scheduler::tick(&db, &center, &ScheduleSettings::default(), &NotificationSettings::default(), t0, local(t0)).unwrap();
    assert_eq!(r.delivered, 1, "only the one that never reached the owner");
    let details: Vec<String> = center.list(10).unwrap().into_iter().map(|n| n.detail).collect();
    assert_eq!(details.iter().filter(|d| d.starts_with("Delivered then crashed")).count(), 1, "no second notice");
    assert_eq!(details.iter().filter(|d| d.starts_with("Crashed before delivering")).count(), 1);
}

#[test]
fn reminders_reach_the_system_only_with_permission_and_respect_the_switch() {
    struct Shell(std::sync::Mutex<u32>);
    impl atlas_core::desktop::Notifier for Shell {
        fn in_front(&self) -> bool {
            true // the owner is looking at Atlas
        }
        fn show(&self, _n: &atlas_core::desktop::SystemNotice) -> bool {
            *self.0.lock().unwrap() += 1;
            true
        }
    }
    let (db, center) = setup();
    let shell = Arc::new(Shell(std::sync::Mutex::new(0)));
    center.set_notifier(shell.clone());
    let s = ScheduleSettings::default();
    let t0 = utc("2026-11-12T10:00:00Z");
    reminder_task(&db, "One", "2026-11-12T09:59:00Z", t0);
    scheduler::sync(&db, &s, local(t0)).unwrap();
    scheduler::tick(&db, &center, &s, &NotificationSettings::default(), t0, local(t0)).unwrap();
    assert_eq!(*shell.0.lock().unwrap(), 0, "system notifications are off by default");
    let on = NotificationSettings { system: true, ..Default::default() };
    reminder_task(&db, "Two", "2026-11-12T09:59:30Z", t0);
    scheduler::sync(&db, &s, local(t0)).unwrap();
    scheduler::tick(&db, &center, &s, &on, t0, local(t0)).unwrap();
    assert_eq!(*shell.0.lock().unwrap(), 1, "a reminder is shown even while Atlas is in front: the owner asked for that moment");
    reminder_task(&db, "Three", "2026-11-12T09:59:40Z", t0);
    scheduler::sync(&db, &s, local(t0)).unwrap();
    scheduler::tick(&db, &center, &s, &NotificationSettings { reminders: false, ..on }, t0, local(t0)).unwrap();
    assert_eq!(*shell.0.lock().unwrap(), 1, "reminders switched off: listed in Atlas only");
    assert_eq!(center.list(10).unwrap().len(), 3);
}
