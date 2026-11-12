//! The daily briefing and Command Center data: real data only, scheduled daily, never invented.

use atlas_core::briefing::{self, BriefingSettings};
use atlas_core::desktop::{NotificationCenter, NotificationSettings};
use atlas_core::events::RecordingBus;
use atlas_core::scheduler::{self, ScheduleSettings};
use atlas_core::storage::Db;
use atlas_core::todos::{self, NewTodo};
use chrono::{DateTime, NaiveDateTime, Utc};
use std::sync::Arc;

fn utc(s: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
}
fn local(u: DateTime<Utc>) -> NaiveDateTime {
    u.with_timezone(&chrono::Local).naive_local()
}

#[test]
fn an_empty_day_is_described_honestly() {
    let db = Db::open_in_memory().unwrap();
    let now = local(utc("2026-11-12T07:00:00Z"));
    let b = briefing::build(&db, now).unwrap();
    assert!(b.today.is_empty() && b.overdue.is_empty() && b.missions.is_empty() && b.recent_conversations.is_empty());
    let t = briefing::text(&b, &BriefingSettings::default());
    assert!(t.starts_with("Nothing is due today."), "{t}");
    assert!(t.contains("No calendar is connected"), "appointments are never invented: {t}");
    assert!(!t.contains("meeting") && !t.contains("appointment at"));
}

#[test]
fn the_briefing_reflects_tasks_reminders_and_accomplishments() {
    let db = Db::open_in_memory().unwrap();
    let t0 = utc("2026-11-12T07:00:00Z");
    let now = local(t0);
    let d = |n: i64| (now.date() + chrono::Duration::days(n)).to_string();
    todos::create(&db, NewTodo { title: "Submit the report".into(), due_date: Some(d(0)), ..Default::default() }, now).unwrap();
    todos::create(&db, NewTodo { title: "Pay rent".into(), due_date: Some(d(-2)), ..Default::default() }, now).unwrap();
    todos::create(&db, NewTodo { title: "Dentist".into(), due_date: Some(d(3)), ..Default::default() }, now).unwrap();
    todos::create(&db, NewTodo { title: "Next month thing".into(), due_date: Some(d(40)), ..Default::default() }, now).unwrap();
    let call = todos::create(&db, NewTodo { title: "Call Sam".into(), due_date: Some(d(0)), due_time: Some("23:00".into()), ..Default::default() }, now).unwrap();
    todos::update(&db, &call.id, todos::TodoPatch { remind_at: Some(todos::default_reminder(&d(0), Some("23:00"))), ..Default::default() }, now).unwrap();
    let done = todos::create(&db, NewTodo { title: "Old chore".into(), ..Default::default() }, now).unwrap();
    todos::set_status(&db, &done.id, "done", now).unwrap();

    let b = briefing::build(&db, now).unwrap();
    let titles = |v: &[todos::Todo]| v.iter().map(|t| t.title.clone()).collect::<Vec<_>>();
    assert_eq!(titles(&b.overdue), ["Pay rent"]);
    let mut today = titles(&b.today);
    today.sort();
    assert_eq!(today, ["Call Sam", "Submit the report"]);
    assert_eq!(titles(&b.upcoming), ["Dentist"], "the next 7 days only");
    assert_eq!(b.reminders_today, [("23:00".to_string(), "Call Sam".to_string())]);
    assert_eq!(titles(&b.accomplished), ["Old chore"]);
    let t = briefing::text(&b, &BriefingSettings::default());
    assert!(t.contains("2 tasks are due today") && t.contains("Submit the report"), "{t}");
    assert!(t.contains("1 overdue: Pay rent"));
    assert!(t.contains("Call Sam at 23:00"));
    assert!(t.contains("Coming up this week: Dentist"));
    assert!(t.contains("You finished 1 task in the last 7 days"));
    // The owner chooses what is included.
    let lean = BriefingSettings { include_overdue: false, include_upcoming: false, include_recent: false, ..Default::default() };
    let t = briefing::text(&b, &lean);
    assert!(!t.contains("overdue") && !t.contains("Coming up") && !t.contains("You finished"), "{t}");
}

#[test]
fn the_daily_briefing_is_scheduled_once_delivered_once_and_rescheduled() {
    let db = Arc::new(Db::open_in_memory().unwrap());
    let center = NotificationCenter::new(db.clone(), Arc::new(RecordingBus::default()));
    let s = ScheduleSettings::default();
    let n = NotificationSettings::default();
    let t0 = utc("2026-11-12T07:00:00Z");
    // Off by default: nothing scheduled.
    scheduler::sync(&db, &s, &BriefingSettings::default(), local(t0), t0).unwrap();
    assert!(scheduler::list(&db, local(t0), 10).unwrap().is_empty());

    let on = BriefingSettings { enabled: true, time: local(utc("2026-11-12T08:00:00Z")).format("%H:%M").to_string(), ..Default::default() };
    scheduler::sync(&db, &s, &on, local(t0), t0).unwrap();
    scheduler::sync(&db, &s, &on, local(t0), t0).unwrap();
    let jobs = scheduler::list(&db, local(t0), 10).unwrap();
    assert_eq!(jobs.len(), 1);
    assert_eq!((jobs[0].kind.as_str(), jobs[0].run_at.as_str()), ("briefing", "2026-11-12T08:00:00.000Z"));

    let t1 = utc("2026-11-12T08:00:30Z");
    assert_eq!(scheduler::tick(&db, &center, &s, &on, &n, t1, local(t1)).unwrap().delivered, 1);
    assert_eq!(scheduler::tick(&db, &center, &s, &on, &n, t1, local(t1)).unwrap().delivered, 0);
    let list = center.list(10).unwrap();
    assert_eq!(list[0].title, "Your daily briefing");
    assert!(list[0].detail.contains("Nothing is due today"));
    // The next sync schedules tomorrow's, once.
    scheduler::sync(&db, &s, &on, local(t1), t1).unwrap();
    let pending: Vec<_> = scheduler::list(&db, local(t1), 10).unwrap().into_iter().filter(|j| j.status == "pending").collect();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].run_at, "2026-11-13T08:00:00.000Z");

    // Changing the time moves it; turning it off cancels it.
    let later = BriefingSettings { time: local(utc("2026-11-13T09:30:00Z")).format("%H:%M").to_string(), ..on.clone() };
    scheduler::sync(&db, &s, &later, local(t1), t1).unwrap();
    let pending: Vec<_> = scheduler::list(&db, local(t1), 10).unwrap().into_iter().filter(|j| j.status == "pending").collect();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].run_at, "2026-11-12T09:30:00.000Z", "09:30 is still ahead today");
    scheduler::sync(&db, &s, &BriefingSettings::default(), local(t1), t1).unwrap();
    assert!(scheduler::list(&db, local(t1), 10).unwrap().iter().all(|j| j.status != "pending"));

    // A briefing hours late (Atlas was asleep at 09:30) is skipped quietly, not sent at night.
    scheduler::sync(&db, &s, &later, local(t1), t1).unwrap();
    let night = utc("2026-11-12T22:00:00Z");
    let r = scheduler::tick(&db, &center, &s, &later, &n, night, local(night)).unwrap();
    assert_eq!((r.delivered, r.missed), (0, 1));
    assert_eq!(center.list(10).unwrap().len(), 1, "no extra notice for a skipped briefing");
    assert!(BriefingSettings { time: "25:00".into(), ..Default::default() }.validate().is_err());
}
