//! Desktop presence: tray, the global "summon Atlas" shortcut and notifications.
//!
//! The core owns the settings, validates the shortcut and decides whether a notification may be
//! shown; the desktop shell only carries out what the core allows. Everything here is off or
//! harmless by default: no global shortcut is registered and no system notification is shown
//! until the owner turns it on.

use crate::error::{AtlasError, Result};
use crate::events::{notify, SharedBus, Topic};
use crate::storage::{new_id, now, Db};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};

pub const DEFAULT_SHORTCUT: &str = "Ctrl+Alt+Space";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct DesktopSettings {
    /// Show the Atlas icon in the system tray / notification area.
    pub tray: bool,
    /// Closing the window keeps Atlas running in the tray (only while the tray icon is on).
    pub close_to_tray: bool,
    /// Register the system-wide shortcut that brings Atlas forward. Off until the owner enables it.
    pub shortcut_enabled: bool,
    /// The shortcut, e.g. "Ctrl+Alt+Space".
    pub shortcut: String,
    /// After the shortcut brings Atlas forward, start listening (needs voice set up).
    pub shortcut_starts_listening: bool,
    pub notifications: NotificationSettings,
}

impl Default for DesktopSettings {
    fn default() -> Self {
        Self {
            tray: true,
            close_to_tray: false,
            shortcut_enabled: false,
            shortcut: DEFAULT_SHORTCUT.into(),
            shortcut_starts_listening: false,
            notifications: NotificationSettings::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct NotificationSettings {
    /// Show system notifications. Off until the owner enables them; the in-app list always works.
    pub system: bool,
    /// Only while the Atlas window is hidden or not in front.
    pub only_when_away: bool,
    /// Include what the notification is about (a conversation or mission title). Off = generic
    /// wording, because system notifications can appear on a lock screen.
    pub show_details: bool,
    pub approvals: bool,
    pub replies: bool,
    pub missions: bool,
    pub errors: bool,
    /// Reminders the owner set on tasks.
    pub reminders: bool,
    /// "Due today" notices for tasks without a reminder.
    pub deadlines: bool,
    /// The daily briefing.
    pub briefings: bool,
}

impl Default for NotificationSettings {
    fn default() -> Self {
        Self { system: false, only_when_away: true, show_details: false, approvals: true, replies: true, missions: true, errors: true, reminders: true, deadlines: true, briefings: true }
    }
}

impl NotificationSettings {
    pub fn category_on(&self, c: Category) -> bool {
        match c {
            Category::Approval => self.approvals,
            Category::Reply => self.replies,
            Category::Mission => self.missions,
            Category::Error => self.errors,
            Category::Reminder => self.reminders,
            Category::Deadline => self.deadlines,
            Category::Briefing => self.briefings,
            Category::Focus => true,
            Category::Test => true,
        }
    }
}

impl DesktopSettings {
    pub fn validate(&self) -> Result<()> {
        // The shortcut is validated even while disabled, so a bad value can never be enabled later.
        parse_shortcut(&self.shortcut).map(|_| ())
    }
}

// ----- shortcut -----

const MODIFIERS: [&str; 4] = ["Ctrl", "Alt", "Shift", "Super"];

fn key_ok(k: &str) -> bool {
    let named = ["Space", "Enter", "Tab", "Backspace", "Insert", "Home", "End", "PageUp", "PageDown", "Up", "Down", "Left", "Right", "Backquote", "Minus", "Equal", "Comma", "Period", "Slash", "Semicolon"];
    if named.contains(&k) {
        return true;
    }
    if let Some(n) = k.strip_prefix('F') {
        return n.parse::<u8>().is_ok_and(|n| (1..=24).contains(&n)) && !n.starts_with('0');
    }
    k.len() == 1 && k.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit())
}

/// Combinations the system or nearly every app already uses; Atlas refuses to take them.
const RESERVED: [&str; 14] = [
    "Alt+F4",
    "Alt+Tab",
    "Ctrl+Alt+Delete",
    "Ctrl+Shift+Escape",
    "Super+L",
    "Super+D",
    "Super+E",
    "Super+R",
    "Super+Tab",
    "Super+Space",
    "Ctrl+Space",
    "Alt+Space",
    "Shift+Space",
    "Ctrl+Shift+Space", // Atlas's own in-app push-to-talk
];

/// Parse and normalise a shortcut ("ctrl + alt + space" → "Ctrl+Alt+Space").
/// Rules: at least one modifier, exactly one key, not a reserved combination, and letters or
/// digits need two modifiers (so ordinary typing shortcuts like Ctrl+C are never captured).
pub fn parse_shortcut(s: &str) -> Result<String> {
    let bad = |why: &str| AtlasError::Validation(format!("shortcut \"{}\": {why}", s.trim()));
    if s.len() > 64 {
        return Err(bad("too long"));
    }
    let mut mods: Vec<&'static str> = Vec::new();
    let mut key: Option<String> = None;
    for raw in s.split('+').map(str::trim) {
        if raw.is_empty() {
            return Err(bad("has an empty part"));
        }
        let lower = raw.to_ascii_lowercase();
        let m = match lower.as_str() {
            "ctrl" | "control" => Some("Ctrl"),
            "alt" | "option" => Some("Alt"),
            "shift" => Some("Shift"),
            "super" | "win" | "windows" | "cmd" | "command" | "meta" => Some("Super"),
            _ => None,
        };
        if let Some(m) = m {
            if mods.contains(&m) {
                return Err(bad("repeats a modifier"));
            }
            mods.push(m);
            continue;
        }
        if key.is_some() {
            return Err(bad("needs exactly one key besides Ctrl, Alt, Shift or the Windows key"));
        }
        let k = if raw.len() == 1 {
            raw.to_ascii_uppercase()
        } else {
            let mut c = lower.chars();
            let first = c.next().map(|f| f.to_ascii_uppercase()).unwrap_or_default();
            let rest: String = c.collect();
            match format!("{first}{rest}").as_str() {
                "Pageup" => "PageUp".into(),
                "Pagedown" => "PageDown".into(),
                other => other.to_string(),
            }
        };
        if !key_ok(&k) {
            return Err(bad("uses a key Atlas can't register"));
        }
        key = Some(k);
    }
    let key = key.ok_or_else(|| bad("needs a key besides the modifiers"))?;
    if mods.is_empty() {
        return Err(bad("needs Ctrl, Alt, Shift or the Windows key"));
    }
    mods.sort_by_key(|m| MODIFIERS.iter().position(|x| x == m));
    let plain = key.len() == 1;
    if plain && mods.len() < 2 {
        return Err(bad("needs two modifiers with a letter or number (for example Ctrl+Alt+A)"));
    }
    if mods == ["Shift"] {
        return Err(bad("needs Ctrl, Alt or the Windows key, not only Shift"));
    }
    let out = format!("{}+{key}", mods.join("+"));
    if RESERVED.contains(&out.as_str()) {
        return Err(bad("is already used by the system or by Atlas itself"));
    }
    Ok(out)
}

// ----- notifications -----

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Category {
    Approval,
    Reply,
    Mission,
    Error,
    Reminder,
    Deadline,
    Briefing,
    /// A Focus session ended (with what was held).
    Focus,
    Test,
}

impl Category {
    pub fn as_str(self) -> &'static str {
        match self {
            Category::Approval => "approval",
            Category::Reply => "reply",
            Category::Mission => "mission",
            Category::Error => "error",
            Category::Reminder => "reminder",
            Category::Deadline => "deadline",
            Category::Briefing => "briefing",
            Category::Focus => "focus",
            Category::Test => "test",
        }
    }
    fn parse(s: &str) -> Category {
        match s {
            "approval" => Category::Approval,
            "reply" => Category::Reply,
            "mission" => Category::Mission,
            "error" => Category::Error,
            "reminder" => Category::Reminder,
            "deadline" => Category::Deadline,
            "briefing" => Category::Briefing,
            "focus" => Category::Focus,
            _ => Category::Test,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Notification {
    pub id: String,
    pub category: Category,
    pub title: String,
    /// What it is about (a conversation or mission title). Shown in Atlas; shown by the system
    /// only when the owner allows details.
    pub detail: String,
    /// Where it leads in Atlas: "conversation:<id>", "mission:<id>", "approvals" or "".
    pub target: String,
    pub created_at: String,
    pub read_at: Option<String>,
    /// Whether the system notification was shown (false: not allowed, or Atlas was in front).
    pub shown_by_system: bool,
    /// Held by a Focus session: listed, but not shown until the session ends.
    pub held: bool,
}

/// What the system may show for a notification.
#[derive(Debug, Clone, PartialEq)]
pub struct SystemNotice {
    pub id: String,
    pub title: String,
    pub body: String,
}

/// Shows system notifications. Implemented by the desktop shell.
pub trait Notifier: Send + Sync {
    /// Whether the Atlas window is visible and in front right now.
    fn in_front(&self) -> bool;
    /// Show it. Returns false if the system refused.
    fn show(&self, notice: &SystemNotice) -> bool;
}

pub struct NewNotification<'a> {
    pub category: Category,
    pub title: &'a str,
    pub detail: &'a str,
    pub target: &'a str,
    /// Notifications with the same key are not repeated while one is still unread.
    pub dedupe_key: &'a str,
    /// Only worth raising while the owner is not looking at Atlas (for example "Atlas has
    /// replied"): skipped entirely when the window is in front.
    pub only_if_away: bool,
}

const KEEP: usize = 200;

/// The one place notifications are created. It records each one for the in-app list, drops
/// duplicates, and asks the shell to show a system notification only when the settings allow it.
pub struct NotificationCenter {
    db: Arc<Db>,
    bus: SharedBus,
    notifier: Mutex<Option<Arc<dyn Notifier>>>,
}

impl NotificationCenter {
    pub fn new(db: Arc<Db>, bus: SharedBus) -> Self {
        Self { db, bus, notifier: Mutex::new(None) }
    }

    pub fn set_notifier(&self, n: Arc<dyn Notifier>) {
        if let Ok(mut slot) = self.notifier.lock() {
            *slot = Some(n);
        }
    }

    /// The wording the system may show: generic unless the owner allows details.
    pub fn system_notice(n: &Notification, s: &NotificationSettings) -> SystemNotice {
        let body = if s.show_details && !n.detail.is_empty() { n.detail.chars().take(120).collect() } else { "Open Atlas to see it.".to_string() };
        SystemNotice { id: n.id.clone(), title: n.title.clone(), body }
    }

    /// Record a notification. `None` when it duplicates an unread one.
    pub fn raise(&self, s: &NotificationSettings, n: NewNotification<'_>) -> Result<Option<Notification>> {
        let notifier = self.notifier.lock().ok().and_then(|g| g.clone());
        if n.only_if_away && notifier.as_ref().is_none_or(|nf| nf.in_front()) {
            return Ok(None);
        }
        let conn = self.db.conn()?;
        if !n.dedupe_key.is_empty() {
            let dup: i64 = conn.query_row("SELECT COUNT(*) FROM notifications WHERE dedupe_key = ?1 AND read_at IS NULL", [n.dedupe_key], |r| r.get(0))?;
            if dup > 0 {
                return Ok(None);
            }
        }
        let mut out = Notification {
            id: new_id(),
            category: n.category,
            title: crate::redact::redact(n.title).chars().take(120).collect(),
            detail: crate::redact::redact(n.detail).chars().take(200).collect(),
            target: n.target.chars().take(120).collect(),
            created_at: now(),
            read_at: None,
            shown_by_system: false,
            held: false,
        };
        // Focus Mode holds what can wait; approvals and failures always come through.
        // (Checked on this connection: the database lock is already held here.)
        if !crate::focus::passes_through(n.category) {
            out.held = conn.query_row("SELECT EXISTS (SELECT 1 FROM focus_sessions WHERE ended_at IS NULL)", [], |r| r.get(0))?;
        }
        // Permission is decided here, in the core, from the stored settings.
        let allowed = s.system && s.category_on(n.category);
        if allowed
            && !out.held
            && let Some(nf) = notifier
            // A reminder is shown even while Atlas is in front: the owner asked for that moment.
            && !(s.only_when_away && n.category != Category::Reminder && nf.in_front())
        {
            out.shown_by_system = nf.show(&Self::system_notice(&out, s));
        }
        // The connection (and so the database) stays locked from the Focus check to this write, so a
        // session cannot end in between and leave this notice held after its release.
        conn.execute(
            "INSERT INTO notifications (id, category, title, detail, target, dedupe_key, created_at, shown_by_system, held) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            rusqlite::params![out.id, out.category.as_str(), out.title, out.detail, out.target, n.dedupe_key, out.created_at, out.shown_by_system, out.held],
        )?;
        conn.execute("DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY created_at DESC, rowid DESC LIMIT ?1)", [KEEP as i64])?;
        notify(&self.bus, Topic::Notifications, Some(&out.id));
        Ok(Some(out))
    }

    pub fn list(&self, limit: u32) -> Result<Vec<Notification>> {
        let conn = self.db.conn()?;
        let mut st = conn.prepare("SELECT id, category, title, detail, target, created_at, read_at, shown_by_system, held FROM notifications ORDER BY created_at DESC, rowid DESC LIMIT ?1")?;
        let rows = st.query_map([limit.clamp(1, KEEP as u32)], |r| {
            Ok(Notification {
                id: r.get(0)?,
                category: Category::parse(&r.get::<_, String>(1)?),
                title: r.get(2)?,
                detail: r.get(3)?,
                target: r.get(4)?,
                created_at: r.get(5)?,
                read_at: r.get(6)?,
                shown_by_system: r.get(7)?,
                held: r.get(8)?,
            })
        })?;
        Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
    }

    pub fn unread(&self) -> Result<u32> {
        Ok(self.db.conn()?.query_row("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL", [], |r| r.get(0))?)
    }

    /// Mark one (or, with `None`, all) as read.
    pub fn mark_read(&self, id: Option<&str>) -> Result<()> {
        let conn = self.db.conn()?;
        match id {
            Some(id) => conn.execute("UPDATE notifications SET read_at = ?1 WHERE id = ?2 AND read_at IS NULL", rusqlite::params![now(), id])?,
            None => conn.execute("UPDATE notifications SET read_at = ?1 WHERE read_at IS NULL", [now()])?,
        };
        notify(&self.bus, Topic::Notifications, None);
        Ok(())
    }

    /// Mark everything about one target as read (the owner opened it).
    pub fn mark_target_read(&self, target: &str) -> Result<()> {
        let n = self.db.conn()?.execute("UPDATE notifications SET read_at = ?1 WHERE target = ?2 AND read_at IS NULL", rusqlite::params![now(), target])?;
        if n > 0 {
            notify(&self.bus, Topic::Notifications, None);
        }
        Ok(())
    }

    /// The thing a notification was about has been dealt with (for example an approval decided).
    pub fn resolve(&self, dedupe_key: &str) {
        if let Ok(conn) = self.db.conn()
            && conn.execute("UPDATE notifications SET read_at = ?1 WHERE dedupe_key = ?2 AND read_at IS NULL", rusqlite::params![now(), dedupe_key]).unwrap_or(0) > 0
        {
            notify(&self.bus, Topic::Notifications, None);
        }
    }

    /// End of a Focus session: what it held is no longer held. Returns the titles, newest first.
    pub fn release_held(&self) -> Result<Vec<String>> {
        let mut conn = self.db.conn()?;
        // One transaction: every notice counted in the summary is the one released, none twice.
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let titles: Vec<String> = {
            let mut st = tx.prepare("SELECT title FROM notifications WHERE held = 1 ORDER BY created_at DESC, rowid DESC")?;
            let rows = st.query_map([], |r| r.get(0))?;
            rows.collect::<std::result::Result<_, _>>()?
        };
        tx.execute("UPDATE notifications SET held = 0 WHERE held = 1", [])?;
        tx.commit()?;
        if !titles.is_empty() {
            notify(&self.bus, Topic::Notifications, None);
        }
        Ok(titles)
    }

    pub fn clear(&self) -> Result<()> {
        self.db.conn()?.execute("DELETE FROM notifications", [])?;
        notify(&self.bus, Topic::Notifications, None);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shortcuts_are_normalised_and_unsafe_ones_refused() {
        assert_eq!(parse_shortcut("ctrl + alt + space").unwrap(), "Ctrl+Alt+Space");
        assert_eq!(parse_shortcut("Shift+Ctrl+a").unwrap(), "Ctrl+Shift+A");
        assert_eq!(parse_shortcut("win+alt+F9").unwrap(), "Alt+Super+F9");
        assert_eq!(parse_shortcut("Ctrl+F8").unwrap(), "Ctrl+F8");
        assert_eq!(parse_shortcut("Alt+PageUp").unwrap(), "Alt+PageUp");
        for bad in ["", "A", "Space", "Ctrl", "Ctrl+C", "Shift+F5", "Ctrl+Alt", "Ctrl+A+B", "Ctrl+Ctrl+A", "Alt+F4", "Ctrl+Alt+Delete", "Ctrl+Shift+Space", "Super+L", "Ctrl+Alt+F25", "Ctrl+Alt+F01", "Ctrl+Alt+é", "Ctrl++A", "Ctrl+Alt+Escape"] {
            assert!(parse_shortcut(bad).is_err(), "{bad:?} must be refused");
        }
        assert!(parse_shortcut(&"Ctrl+".repeat(40)).is_err());
        assert!(DesktopSettings::default().validate().is_ok());
        let d = DesktopSettings::default();
        assert!(d.tray && !d.close_to_tray && !d.shortcut_enabled && !d.notifications.system, "nothing intrusive is on by default");
    }

    /// Regression: `raise` used to take the database lock again (through `focus::is_active`) while
    /// already holding it, which hung the first notice raised during a Focus session. Run on a
    /// thread with a deadline so a regression fails instead of hanging the suite.
    #[test]
    fn raising_during_focus_does_not_deadlock_and_holds_and_releases_once() {
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let db = Arc::new(Db::open_in_memory().unwrap());
            let center = NotificationCenter::new(db.clone(), Arc::new(crate::events::NullBus));
            let s = NotificationSettings::default();
            crate::focus::start(&db, 25, None, "", chrono::Utc::now()).unwrap();
            let n = |c, t| NewNotification { category: c, title: t, detail: "", target: "", dedupe_key: "", only_if_away: false };
            let held = center.raise(&s, n(Category::Reminder, "Stretch")).unwrap().unwrap().held;
            let approval = center.raise(&s, n(Category::Approval, "Approve a command")).unwrap().unwrap().held;
            crate::focus::end(&db, "stopped", chrono::Utc::now()).unwrap();
            let first = center.release_held().unwrap();
            let second = center.release_held().unwrap();
            let after = center.raise(&s, n(Category::Reminder, "After")).unwrap().unwrap().held;
            tx.send((held, approval, first, second, after)).unwrap();
        });
        let (held, approval, first, second, after) = rx.recv_timeout(std::time::Duration::from_secs(20)).expect("raise must not deadlock during Focus");
        assert!(held && !approval, "reminder held, approval through");
        assert_eq!(first, vec!["Stretch".to_string()]);
        assert!(second.is_empty(), "released once, not twice");
        assert!(!after, "nothing is held once the session has ended");
    }
}
