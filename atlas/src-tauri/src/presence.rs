//! Desktop presence in the shell: the tray icon, the global "summon" shortcut and system
//! notifications. The shell only carries out what the core's settings allow; it holds no
//! settings of its own.

use atlas_core::desktop::{DesktopSettings, Notifier, SystemNotice};
use serde::Serialize;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};

/// Registers system-wide shortcuts. A trait so the bookkeeping can be tested without a desktop.
pub trait ShortcutBackend {
    fn register(&self, shortcut: &str) -> Result<(), String>;
    fn unregister(&self, shortcut: &str);
}

#[derive(Default, Debug, Clone, PartialEq)]
pub struct ShortcutState {
    /// The shortcut currently registered with the system, if any.
    pub registered: Option<String>,
    /// Why the wanted shortcut could not be registered.
    pub error: Option<String>,
}

/// Bring the registered shortcut in line with what the settings want. At most one shortcut is
/// ever registered; an unchanged one is not registered twice; a failure leaves none registered
/// and says why.
pub fn reconcile(backend: &dyn ShortcutBackend, state: &mut ShortcutState, want: Option<&str>) {
    if state.registered.as_deref() == want {
        if want.is_none() {
            state.error = None;
        }
        return;
    }
    if let Some(old) = state.registered.take() {
        backend.unregister(&old);
    }
    state.error = None;
    if let Some(w) = want {
        match backend.register(w) {
            Ok(()) => state.registered = Some(w.to_string()),
            Err(e) => {
                state.error = Some(if e.to_lowercase().contains("already") || e.to_lowercase().contains("registered") {
                    format!("{w} is already used by another app. Choose a different shortcut.")
                } else {
                    format!("{w} could not be registered: {e}")
                })
            }
        }
    }
}

#[derive(Serialize, Clone, Debug)]
pub struct DesktopStatus {
    pub platform: &'static str,
    pub tray_supported: bool,
    pub tray_visible: bool,
    pub shortcut_supported: bool,
    pub shortcut_registered: Option<String>,
    pub shortcut_error: Option<String>,
    pub notifications_supported: bool,
    /// Whether a second launch is redirected to the running Atlas.
    pub single_instance: bool,
    /// Honest platform limits, in plain words (empty when there are none).
    pub notes: Vec<String>,
    /// Test builds only: how many system notifications would have been shown.
    pub test_notifications_shown: Option<usize>,
}

#[derive(Default)]
pub struct Presence {
    shortcut: Mutex<ShortcutState>,
    tray_visible: Mutex<bool>,
    tray_supported: Mutex<bool>,
    close_to_tray: Mutex<bool>,
    listen_on_summon: Mutex<bool>,
    quitting: Mutex<bool>,
    #[cfg(feature = "e2e")]
    pub test_shown: Mutex<Vec<SystemNotice>>,
}

fn wayland() -> bool {
    cfg!(target_os = "linux") && std::env::var("XDG_SESSION_TYPE").is_ok_and(|v| v.eq_ignore_ascii_case("wayland"))
}

struct PluginShortcuts<'a>(&'a AppHandle);

impl ShortcutBackend for PluginShortcuts<'_> {
    fn register(&self, shortcut: &str) -> Result<(), String> {
        use tauri_plugin_global_shortcut::GlobalShortcutExt;
        if wayland() {
            return Err("this desktop (Wayland) does not let apps register system-wide shortcuts".into());
        }
        let parsed: tauri_plugin_global_shortcut::Shortcut = shortcut.parse().map_err(|e| format!("{e}"))?;
        let gs = self.0.global_shortcut();
        if gs.is_registered(parsed) {
            return Ok(());
        }
        gs.register(parsed).map_err(|e| e.to_string())
    }
    fn unregister(&self, shortcut: &str) {
        use tauri_plugin_global_shortcut::GlobalShortcutExt;
        if let Ok(parsed) = shortcut.parse::<tauri_plugin_global_shortcut::Shortcut>() {
            let _ = self.0.global_shortcut().unregister(parsed);
        }
    }
}

const TRAY_ID: &str = "atlas";

impl Presence {
    /// Create the tray icon (hidden until the settings say otherwise).
    pub fn build_tray(&self, app: &AppHandle) {
        use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
        use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
        let built = (|| -> tauri::Result<()> {
            let open = MenuItem::with_id(app, "open", "Open Atlas", true, None::<&str>)?;
            let talk = MenuItem::with_id(app, "talk", "Talk to Atlas", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Atlas", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &talk, &PredefinedMenuItem::separator(app)?, &quit])?;
            let mut b = TrayIconBuilder::with_id(TRAY_ID).tooltip("ATLAS Co-Pilot").menu(&menu).show_menu_on_left_click(false);
            if let Some(icon) = app.default_window_icon() {
                b = b.icon(icon.clone());
            }
            b.on_menu_event(|app, event| match event.id().as_ref() {
                "open" => summon(app, false),
                "talk" => summon(app, true),
                "quit" => quit_app(app),
                _ => {}
            })
            .on_tray_icon_event(|tray, event| {
                if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                    summon(tray.app_handle(), false);
                }
            })
            .build(app)?;
            if let Some(t) = app.tray_by_id(TRAY_ID) {
                let _ = t.set_visible(false);
            }
            Ok(())
        })();
        if let Ok(mut s) = self.tray_supported.lock() {
            *s = built.is_ok();
        }
    }

    /// Apply the owner's desktop settings: tray visibility and the one global shortcut.
    pub fn apply(&self, app: &AppHandle, d: &DesktopSettings) {
        let supported = self.tray_supported.lock().map(|s| *s).unwrap_or(false);
        let show = supported && d.tray;
        if let Some(t) = app.tray_by_id(TRAY_ID) {
            let _ = t.set_visible(show);
        }
        if let Ok(mut v) = self.tray_visible.lock() {
            *v = show;
        }
        // Closing to the tray only makes sense while there is a tray icon to come back from.
        if let Ok(mut c) = self.close_to_tray.lock() {
            *c = show && d.close_to_tray;
        }
        if let Ok(mut l) = self.listen_on_summon.lock() {
            *l = d.shortcut_starts_listening;
        }
        if let Ok(mut st) = self.shortcut.lock() {
            reconcile(&PluginShortcuts(app), &mut st, d.shortcut_enabled.then_some(d.shortcut.as_str()));
        }
    }

    pub fn status(&self) -> DesktopStatus {
        let sc = self.shortcut.lock().map(|s| s.clone()).unwrap_or_default();
        let mut notes = Vec::new();
        if wayland() {
            notes.push("This desktop (Wayland) does not let apps register system-wide shortcuts. Use the tray icon instead.".to_string());
        }
        if cfg!(target_os = "linux") {
            notes.push("On Linux the tray icon needs a desktop with tray (AppIndicator) support; some, such as stock GNOME, hide it.".to_string());
            notes.push("On Linux a second launch opens a second Atlas window instead of returning to the first.".to_string());
        }
        if cfg!(target_os = "macos") {
            notes.push("Desktop presence on macOS is built but has not been tested by a person.".to_string());
        }
        DesktopStatus {
            platform: std::env::consts::OS,
            tray_supported: self.tray_supported.lock().map(|s| *s).unwrap_or(false),
            tray_visible: self.tray_visible.lock().map(|s| *s).unwrap_or(false),
            shortcut_supported: !wayland(),
            shortcut_registered: sc.registered,
            shortcut_error: sc.error,
            notifications_supported: true,
            single_instance: cfg!(all(not(feature = "e2e"), any(windows, target_os = "macos"))),
            notes,
            #[cfg(feature = "e2e")]
            test_notifications_shown: Some(self.test_shown.lock().map(|v| v.len()).unwrap_or(0)),
            #[cfg(not(feature = "e2e"))]
            test_notifications_shown: None,
        }
    }

    /// Whether closing the window should hide it instead of quitting.
    pub fn hides_on_close(&self) -> bool {
        let quitting = self.quitting.lock().map(|q| *q).unwrap_or(false);
        !quitting && self.close_to_tray.lock().map(|c| *c).unwrap_or(false)
    }

    pub fn listen_on_summon(&self) -> bool {
        self.listen_on_summon.lock().map(|l| *l).unwrap_or(false)
    }

    /// Release everything registered with the system (called on exit).
    pub fn shutdown(&self, app: &AppHandle) {
        if let Ok(mut st) = self.shortcut.lock() {
            reconcile(&PluginShortcuts(app), &mut st, None);
        }
    }
}

/// Bring Atlas forward because the owner asked (shortcut, tray or a second launch). This is the
/// only place the window takes focus on its own.
pub fn summon(app: &AppHandle, listen: bool) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
    let _ = app.emit("atlas://summon", serde_json::json!({ "listen": listen }));
}

pub fn quit_app(app: &AppHandle) {
    if let Some(p) = app.try_state::<Presence>() {
        if let Ok(mut q) = p.quitting.lock() {
            *q = true;
        }
        p.shutdown(app);
    }
    app.exit(0);
}

/// Shows system notifications the core has already allowed.
pub struct ShellNotifier(pub AppHandle);

impl Notifier for ShellNotifier {
    fn in_front(&self) -> bool {
        self.0.get_webview_window("main").is_some_and(|w| w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false) && !w.is_minimized().unwrap_or(false))
    }

    #[cfg(feature = "e2e")]
    fn show(&self, notice: &SystemNotice) -> bool {
        // Test builds record what would be shown instead of popping up real notifications.
        if let Some(p) = self.0.try_state::<Presence>()
            && let Ok(mut v) = p.test_shown.lock()
        {
            v.push(notice.clone());
            return true;
        }
        false
    }

    #[cfg(not(feature = "e2e"))]
    fn show(&self, notice: &SystemNotice) -> bool {
        use tauri_plugin_notification::NotificationExt;
        self.0.notification().builder().title(&notice.title).body(&notice.body).show().is_ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[derive(Default)]
    struct Fake {
        taken: Vec<&'static str>,
        log: RefCell<Vec<String>>,
    }
    impl ShortcutBackend for Fake {
        fn register(&self, s: &str) -> Result<(), String> {
            self.log.borrow_mut().push(format!("register {s}"));
            if self.taken.contains(&s) { Err("HotKey already registered".into()) } else { Ok(()) }
        }
        fn unregister(&self, s: &str) {
            self.log.borrow_mut().push(format!("unregister {s}"));
        }
    }

    #[test]
    fn one_shortcut_at_a_time_no_duplicates_and_conflicts_are_reported() {
        let b = Fake { taken: vec!["Ctrl+Alt+T"], ..Default::default() };
        let mut st = ShortcutState::default();
        reconcile(&b, &mut st, None);
        assert!(b.log.borrow().is_empty(), "nothing is registered while the shortcut is off");

        reconcile(&b, &mut st, Some("Ctrl+Alt+Space"));
        reconcile(&b, &mut st, Some("Ctrl+Alt+Space"));
        assert_eq!(*b.log.borrow(), ["register Ctrl+Alt+Space"], "the same shortcut is never registered twice");
        assert_eq!(st.registered.as_deref(), Some("Ctrl+Alt+Space"));

        // Changing it releases the old one first.
        reconcile(&b, &mut st, Some("Ctrl+Alt+K"));
        assert_eq!(b.log.borrow()[1..], ["unregister Ctrl+Alt+Space", "register Ctrl+Alt+K"]);

        // A shortcut another app holds: nothing stays registered, and the owner is told why.
        reconcile(&b, &mut st, Some("Ctrl+Alt+T"));
        assert_eq!(st.registered, None);
        assert!(st.error.as_deref().unwrap().contains("already used by another app"));
        // Asking again retries (the other app may have released it); it is still reported.
        reconcile(&b, &mut st, Some("Ctrl+Alt+T"));
        assert!(st.error.is_some());

        // Turning it off clears the error and registers nothing.
        reconcile(&b, &mut st, None);
        assert_eq!(st, ShortcutState::default());
        let n = b.log.borrow().len();
        reconcile(&b, &mut st, None);
        assert_eq!(b.log.borrow().len(), n);
    }
}
