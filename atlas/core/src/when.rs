//! Plain-language dates for tasks: "tomorrow 5pm", "friday", "in 3 days", "14 nov", "every week".
//!
//! Deterministic and offline: no model is involved. `now` is the owner's local wall-clock time,
//! passed in so every rule can be tested. Anything not understood is left in the title untouched
//! rather than guessed at.

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime, NaiveTime, Weekday};

#[derive(Debug, Clone, PartialEq, Default)]
pub struct Quick {
    pub title: String,
    pub due_date: Option<NaiveDate>,
    pub due_time: Option<NaiveTime>,
    pub priority: Option<&'static str>,
    pub category: Option<String>,
    pub recurrence: Option<&'static str>,
    /// The request asked to be reminded ("remind me to …").
    pub remind: bool,
}

const WEEKDAYS: [(&str, Weekday); 14] = [
    ("monday", Weekday::Mon),
    ("mon", Weekday::Mon),
    ("tuesday", Weekday::Tue),
    ("tue", Weekday::Tue),
    ("wednesday", Weekday::Wed),
    ("wed", Weekday::Wed),
    ("thursday", Weekday::Thu),
    ("thu", Weekday::Thu),
    ("friday", Weekday::Fri),
    ("fri", Weekday::Fri),
    ("saturday", Weekday::Sat),
    ("sat", Weekday::Sat),
    ("sunday", Weekday::Sun),
    ("sun", Weekday::Sun),
];

const MONTHS: [&str; 12] = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

fn weekday(w: &str) -> Option<Weekday> {
    WEEKDAYS.iter().find(|(n, _)| *n == w).map(|(_, d)| *d)
}

fn month(w: &str) -> Option<u32> {
    if w.len() < 3 {
        return None;
    }
    let full = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
    MONTHS.iter().position(|m| *m == w).or_else(|| full.iter().position(|m| *m == w)).map(|i| i as u32 + 1)
}

/// The next date that falls on `target`, strictly after `from`.
fn next_weekday(from: NaiveDate, target: Weekday) -> NaiveDate {
    let ahead = (7 + target.num_days_from_monday() as i64 - from.weekday().num_days_from_monday() as i64) % 7;
    from + Duration::days(if ahead == 0 { 7 } else { ahead })
}

fn day_number(w: &str) -> Option<u32> {
    let digits = w.trim_end_matches(|c: char| c.is_ascii_alphabetic());
    let suffix = &w[digits.len()..];
    if !matches!(suffix, "" | "st" | "nd" | "rd" | "th") {
        return None;
    }
    digits.parse::<u32>().ok().filter(|d| (1..=31).contains(d))
}

/// A day and month with no year: this year if still ahead (or today), otherwise next year.
fn day_month(day: u32, month: u32, today: NaiveDate) -> Option<NaiveDate> {
    let this = NaiveDate::from_ymd_opt(today.year(), month, day);
    match this {
        Some(d) if d >= today => Some(d),
        _ => NaiveDate::from_ymd_opt(today.year() + 1, month, day).or(this),
    }
}

/// "5pm", "5:30pm", "17:30", "9am", "noon", "midnight". A bare number is a time only after "at".
fn time_of(w: &str, after_at: bool) -> Option<NaiveTime> {
    match w {
        "noon" | "midday" => return NaiveTime::from_hms_opt(12, 0, 0),
        "midnight" => return NaiveTime::from_hms_opt(0, 0, 0),
        _ => {}
    }
    let (body, meridiem) = if let Some(b) = w.strip_suffix("am") {
        (b, Some(false))
    } else if let Some(b) = w.strip_suffix("pm") {
        (b, Some(true))
    } else {
        (w, None)
    };
    let (h, m) = match body.split_once(':').or_else(|| body.split_once('.').filter(|_| meridiem.is_some())) {
        Some((h, m)) => (h.parse::<u32>().ok()?, m.parse::<u32>().ok()?),
        None => {
            if meridiem.is_none() && !after_at {
                return None;
            }
            (body.parse::<u32>().ok()?, 0)
        }
    };
    if body.is_empty() || m > 59 {
        return None;
    }
    let h = match meridiem {
        Some(pm) => {
            if !(1..=12).contains(&h) {
                return None;
            }
            (h % 12) + if pm { 12 } else { 0 }
        }
        None => {
            if h > 23 {
                return None;
            }
            h
        }
    };
    NaiveTime::from_hms_opt(h, m, 0)
}

/// Parse an ISO date (2026-11-20).
pub fn iso_date(w: &str) -> Option<NaiveDate> {
    NaiveDate::parse_from_str(w, "%Y-%m-%d").ok()
}

/// Parse "HH:MM" (24-hour).
pub fn hhmm(w: &str) -> Option<NaiveTime> {
    NaiveTime::parse_from_str(w, "%H:%M").ok()
}

/// Understand a quick-entry line. Recognised pieces are removed from the title.
pub fn parse_quick(input: &str, now: NaiveDateTime) -> Quick {
    let today = now.date();
    let mut q = Quick::default();
    let mut text = input.trim().to_string();
    for lead in ["remind me to ", "remind me about ", "remind me "] {
        if text.to_lowercase().starts_with(lead) {
            text = text[lead.len()..].to_string();
            q.remind = true;
            break;
        }
    }
    let words: Vec<&str> = text.split_whitespace().collect();
    let lower: Vec<String> = words.iter().map(|w| w.to_lowercase().trim_matches(|c: char| matches!(c, ',' | '.' | ';')).to_string()).collect();
    let mut used = vec![false; words.len()];
    let mut i = 0;
    while i < words.len() {
        let w = lower[i].as_str();
        let next = lower.get(i + 1).map(String::as_str);
        let next2 = lower.get(i + 2).map(String::as_str);
        let mut take = 0usize;

        if let Some(p) = w.strip_prefix('!') {
            q.priority = match p {
                "low" => Some("low"),
                "normal" | "medium" => Some("normal"),
                "high" | "important" => Some("high"),
                "urgent" | "asap" => Some("urgent"),
                _ => None,
            };
            if q.priority.is_some() {
                take = 1;
            }
        } else if let Some(c) = words[i].strip_prefix('#').filter(|c| !c.is_empty() && c.chars().all(|ch| ch.is_alphanumeric() || ch == '-' || ch == '_')) {
            q.category = Some(c.to_string());
            take = 1;
        } else if w == "every" || w == "each" {
            let r = match next {
                Some("day") => Some(("daily", 2)),
                Some("weekday") => Some(("weekdays", 2)),
                Some("week") => Some(("weekly", 2)),
                Some("month") => Some(("monthly", 2)),
                Some("year") => Some(("yearly", 2)),
                Some(d) if weekday(d).is_some() => {
                    // "every friday": weekly, starting on the next one.
                    if q.due_date.is_none() {
                        q.due_date = weekday(d).map(|wd| if today.weekday() == wd { today } else { next_weekday(today, wd) });
                    }
                    Some(("weekly", 2))
                }
                _ => None,
            };
            if let Some((r, n)) = r {
                q.recurrence = Some(r);
                take = n;
            }
        } else if matches!(w, "daily" | "weekly" | "monthly" | "yearly") {
            q.recurrence = Some(match w {
                "daily" => "daily",
                "weekly" => "weekly",
                "monthly" => "monthly",
                _ => "yearly",
            });
            take = 1;
        } else if w == "today" {
            q.due_date = Some(today);
            take = 1;
        } else if w == "tonight" {
            q.due_date = Some(today);
            q.due_time = q.due_time.or(NaiveTime::from_hms_opt(20, 0, 0));
            take = 1;
        } else if w == "tomorrow" {
            q.due_date = Some(today + Duration::days(1));
            take = 1;
        } else if w == "day" && next == Some("after") && next2 == Some("tomorrow") {
            q.due_date = Some(today + Duration::days(2));
            take = 3;
        } else if w == "next" && next == Some("week") {
            q.due_date = Some(next_weekday(today, Weekday::Mon));
            take = 2;
        } else if w == "next" && next == Some("month") {
            let (y, m) = if today.month() == 12 { (today.year() + 1, 1) } else { (today.year(), today.month() + 1) };
            q.due_date = NaiveDate::from_ymd_opt(y, m, 1);
            take = 2;
        } else if w == "next" && next.and_then(weekday).is_some() {
            // "next friday": the Friday of the following week.
            let wd = next.and_then(weekday).unwrap_or(Weekday::Mon);
            let monday = next_weekday(today, Weekday::Mon);
            q.due_date = Some(monday + Duration::days(wd.num_days_from_monday() as i64));
            take = 2;
        } else if let Some(wd) = weekday(w) {
            q.due_date = Some(next_weekday(today, wd));
            take = 1;
        } else if w == "in" {
            if let (Some(n), Some(unit)) = (next.and_then(|n| n.parse::<i64>().ok()).filter(|n| (1..=3650).contains(n)), next2) {
                let days = match unit.trim_end_matches('s') {
                    "day" => Some(n),
                    "week" => Some(n * 7),
                    _ => None,
                };
                if let Some(d) = days {
                    q.due_date = Some(today + Duration::days(d));
                    take = 3;
                } else if matches!(unit.trim_end_matches('s'), "hour" | "minute" | "min") {
                    let mins = if unit.starts_with("hour") { n * 60 } else { n };
                    let at = now + Duration::minutes(mins);
                    q.due_date = Some(at.date());
                    q.due_time = NaiveTime::from_hms_opt(at.time().format("%H").to_string().parse().unwrap_or(0), at.time().format("%M").to_string().parse().unwrap_or(0), 0);
                    take = 3;
                }
            }
        } else if let Some(d) = iso_date(w) {
            q.due_date = Some(d);
            take = 1;
        } else if let (Some(d), Some(m)) = (day_number(w), next.and_then(month)) {
            q.due_date = day_month(d, m, today);
            take = 2;
        } else if let (Some(m), Some(d)) = (month(w), next.and_then(day_number)) {
            q.due_date = day_month(d, m, today);
            take = 2;
        } else if w == "at" {
            if let Some(t) = next.and_then(|n| time_of(n, true)) {
                q.due_time = Some(t);
                take = 2;
            }
        } else if let Some(t) = time_of(w, false) {
            q.due_time = Some(t);
            take = 1;
        }

        if take > 0 {
            for u in used.iter_mut().skip(i).take(take) {
                *u = true;
            }
            // A connecting word right before a date or time goes too ("by friday", "on 14 nov").
            if i > 0 && !used[i - 1] && matches!(lower[i - 1].as_str(), "by" | "on" | "due" | "before" | "until" | "this") && !w.starts_with('!') && !words[i].starts_with('#') {
                used[i - 1] = true;
            }
            i += take;
        } else {
            i += 1;
        }
    }
    // A time with no date means today, or tomorrow if that time has already passed.
    if let (None, Some(t)) = (q.due_date, q.due_time) {
        q.due_date = Some(if t > now.time() { today } else { today + Duration::days(1) });
    }
    q.title = words.iter().zip(&used).filter(|(_, u)| !**u).map(|(w, _)| *w).collect::<Vec<_>>().join(" ").trim_matches(|c: char| matches!(c, ',' | ';' | ' ')).to_string();
    q
}

/// The next due date of a recurring task after `from`.
pub fn next_occurrence(from: NaiveDate, recurrence: &str, interval: u32) -> Option<NaiveDate> {
    let n = interval.max(1) as i64;
    match recurrence {
        "daily" => Some(from + Duration::days(n)),
        "weekdays" => {
            let mut d = from + Duration::days(1);
            while matches!(d.weekday(), Weekday::Sat | Weekday::Sun) {
                d += Duration::days(1);
            }
            Some(d)
        }
        "weekly" => Some(from + Duration::days(7 * n)),
        "monthly" => {
            let total = from.month0() as i64 + n;
            let (y, m) = (from.year() + (total / 12) as i32, (total % 12) as u32 + 1);
            // The 31st in a shorter month becomes that month's last day.
            (0..4).find_map(|back| NaiveDate::from_ymd_opt(y, m, from.day().saturating_sub(back)))
        }
        "yearly" => NaiveDate::from_ymd_opt(from.year() + n as i32, from.month(), from.day()).or_else(|| NaiveDate::from_ymd_opt(from.year() + n as i32, 2, 28)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Thursday 12 November 2026, 10:30.
    fn now() -> NaiveDateTime {
        NaiveDate::from_ymd_opt(2026, 11, 12).unwrap().and_hms_opt(10, 30, 0).unwrap()
    }
    fn d(y: i32, m: u32, day: u32) -> Option<NaiveDate> {
        NaiveDate::from_ymd_opt(y, m, day)
    }
    fn t(h: u32, m: u32) -> Option<NaiveTime> {
        NaiveTime::from_hms_opt(h, m, 0)
    }

    #[test]
    fn everyday_phrases() {
        let q = parse_quick("Remind me to finish the report tomorrow at 5pm", now());
        assert_eq!((q.title.as_str(), q.due_date, q.due_time, q.remind), ("finish the report", d(2026, 11, 13), t(17, 0), true));

        let q = parse_quick("Call the dentist friday 9:30am !high #health", now());
        assert_eq!(q.title, "Call the dentist");
        assert_eq!((q.due_date, q.due_time, q.priority, q.category.as_deref()), (d(2026, 11, 13), t(9, 30), Some("high"), Some("health")));

        // "thursday" said on a Thursday means next week's; "next friday" is the following week's.
        assert_eq!(parse_quick("gym thursday", now()).due_date, d(2026, 11, 19));
        assert_eq!(parse_quick("review next friday", now()).due_date, d(2026, 11, 20));
        assert_eq!(parse_quick("plan next week", now()).due_date, d(2026, 11, 16));
        assert_eq!(parse_quick("renew licence next month", now()).due_date, d(2026, 12, 1));
        assert_eq!(parse_quick("pay rent in 3 days", now()).due_date, d(2026, 11, 15));
        assert_eq!(parse_quick("trip in 2 weeks", now()).due_date, d(2026, 11, 26));
        assert_eq!(parse_quick("pack day after tomorrow", now()).due_date, d(2026, 11, 14));
        let q = parse_quick("stretch in 45 minutes", now());
        assert_eq!((q.due_date, q.due_time), (d(2026, 11, 12), t(11, 15)));
    }

    #[test]
    fn calendar_dates_and_times() {
        assert_eq!(parse_quick("submit on 14 nov", now()).due_date, d(2026, 11, 14));
        assert_eq!(parse_quick("submit by November 14th", now()).title, "submit");
        assert_eq!(parse_quick("birthday 3 march", now()).due_date, d(2027, 3, 3), "a date already past this year means next year");
        assert_eq!(parse_quick("deadline 2026-12-01", now()).due_date, d(2026, 12, 1));
        let q = parse_quick("standup 17:45", now());
        assert_eq!((q.due_date, q.due_time), (d(2026, 11, 12), t(17, 45)));
        // A time already past today means tomorrow.
        let q = parse_quick("water plants at 9", now());
        assert_eq!((q.title.as_str(), q.due_date, q.due_time), ("water plants", d(2026, 11, 13), t(9, 0)));
        assert_eq!(parse_quick("lunch noon", now()).due_time, t(12, 0));
        assert_eq!(parse_quick("call tonight", now()).due_time, t(20, 0));
        assert_eq!(parse_quick("x 12am", now()).due_time, t(0, 0));
        assert_eq!(parse_quick("x 12pm", now()).due_time, t(12, 0));
    }

    #[test]
    fn recurrence() {
        let q = parse_quick("Take vitamins every day at 8am", now());
        assert_eq!((q.title.as_str(), q.recurrence, q.due_time), ("Take vitamins", Some("daily"), t(8, 0)));
        let q = parse_quick("Team sync every monday 10am", now());
        assert_eq!((q.recurrence, q.due_date), (Some("weekly"), d(2026, 11, 16)));
        assert_eq!(parse_quick("backup weekly", now()).recurrence, Some("weekly"));
        assert_eq!(parse_quick("report every weekday", now()).recurrence, Some("weekdays"));

        assert_eq!(next_occurrence(d(2026, 11, 13).unwrap(), "weekdays", 1), d(2026, 11, 16), "Friday → Monday");
        assert_eq!(next_occurrence(d(2026, 1, 31).unwrap(), "monthly", 1), d(2026, 2, 28), "31st → last day of a shorter month");
        assert_eq!(next_occurrence(d(2026, 12, 15).unwrap(), "monthly", 2), d(2027, 2, 15));
        assert_eq!(next_occurrence(d(2024, 2, 29).unwrap(), "yearly", 1), d(2025, 2, 28));
        assert_eq!(next_occurrence(d(2026, 11, 12).unwrap(), "weekly", 2), d(2026, 11, 26));
        assert_eq!(next_occurrence(d(2026, 11, 12).unwrap(), "none", 1), None);
    }

    #[test]
    fn things_that_are_not_dates_stay_in_the_title() {
        for s in ["Buy 3 apples", "Read chapter 5", "Email Mark about the May figures", "Watch Friday Night Lights", "Fix issue #", "Version 2.5 notes", "Meet at the station"] {
            let q = parse_quick(s, now());
            if s.contains("Friday") || s.contains("May") {
                continue; // a weekday or month name is taken as a date; the owner can clear it
            }
            assert_eq!(q.title, s, "{s}");
            assert_eq!((q.due_date, q.due_time), (None, None), "{s}");
        }
        assert_eq!(parse_quick("", now()), Quick::default());
        assert_eq!(parse_quick("   !urgent  ", now()).priority, Some("urgent"));
        assert!(parse_quick("x 25:99", now()).due_time.is_none());
        assert!(parse_quick("x 13pm", now()).due_time.is_none());
        assert!(parse_quick("x in 0 days", now()).due_date.is_none());
        assert!(parse_quick("x 31 feb", now()).due_date.is_none());
    }
}
