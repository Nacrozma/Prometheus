//! ATLAS Co-Pilot desktop shell. A thin layer: it owns the window, native dialogs and the IPC
//! command surface, and delegates every operation to `atlas-core`, the trusted core.

mod commands;
#[cfg(feature = "e2e")]
mod e2e;
pub mod presence;

use atlas_core::events::{ChangeEvent, EventBus};
use atlas_core::{Atlas, AtlasConfig};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

pub struct AppState {
    pub atlas: Arc<Atlas>,
    /// Backup file the user picked and Atlas validated, awaiting explicit confirmation.
    pub pending_restore: Mutex<Option<PathBuf>>,
}

struct TauriBus(tauri::AppHandle);

impl EventBus for TauriBus {
    fn changed(&self, event: ChangeEvent) {
        let _ = self.0.emit("atlas://changed", event);
    }
}

fn data_dir(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(dir) = std::env::var("ATLAS_DATA_DIR") {
        return PathBuf::from(dir);
    }
    app.path().app_data_dir().unwrap_or_else(|_| PathBuf::from("atlas-data"))
}

/// Only the bundled app (or the dev server) may load in the window. Everything else — such as
/// a link inside a model response — is refused; external links open in the system browser
/// through the `open_external` command after the user clicks them.
fn navigation_allowed(url: &tauri::Url) -> bool {
    match url.scheme() {
        "tauri" | "asset" => true,
        "http" | "https" => matches!(url.host_str(), Some("tauri.localhost") | Some("localhost") | Some("127.0.0.1"))
            && (url.host_str() == Some("tauri.localhost") || cfg!(debug_assertions)),
        _ => false,
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();
    // A second launch brings the running Atlas forward instead of starting another copy
    // (two copies would share one database and one tray icon). Must be the first plugin.
    #[cfg(all(not(feature = "e2e"), any(windows, target_os = "macos")))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| presence::summon(app, false)));
    builder
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    // Only Atlas's one summon shortcut is ever registered.
                    if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                        let listen = app.try_state::<presence::Presence>().is_some_and(|p| p.listen_on_summon());
                        presence::summon(app, listen);
                    }
                })
                .build(),
        )
        .setup(|app| {
            let handle = app.handle().clone();
            let dir = data_dir(&handle);
            std::fs::create_dir_all(&dir)?;

            #[cfg(feature = "e2e")]
            e2e::before_start(&dir);
            #[cfg(feature = "e2e")]
            let (secrets, factory) = e2e::services();
            #[cfg(not(feature = "e2e"))]
            let (secrets, factory): (atlas_core::credentials::SharedSecrets, Option<Arc<dyn atlas_core::providers::ProviderFactory>>) =
                (Arc::new(atlas_core::credentials::OsKeyring), None);

            let atlas = Atlas::new(AtlasConfig {
                db_path: Some(dir.join("atlas.db")),
                secrets,
                bus: Arc::new(TauriBus(handle.clone())),
                factory,
                version: app.package_info().version.to_string(),
                data_dir: Some(dir),
            })
            .map_err(|e| format!("Atlas could not open its database: {e}"))?;
            #[cfg(feature = "e2e")]
            e2e::seed(&atlas);
            // Sibling link upkeep: poll running missions (read-only) and refresh sibling health.
            // With no sibling paired this does nothing; Atlas never depends on it.
            let bg = atlas.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    // Reminders and notices; failures are recorded and never stop the loop.
                    if let Err(e) = bg.scheduler_tick() {
                        eprintln!("[atlas] scheduler: {e}");
                    }
                    bg.sibling_sync_once().await;
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                }
            });
            atlas.notifications.set_notifier(Arc::new(presence::ShellNotifier(handle.clone())));
            let desktop = atlas.settings().map(|s| s.desktop).unwrap_or_default();
            app.manage(AppState { atlas, pending_restore: Mutex::new(None) });
            let presence = presence::Presence::default();
            presence.build_tray(&handle);
            app.manage(presence);

            #[allow(unused_mut)]
            let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()));
            #[cfg(all(windows, feature = "e2e"))]
            {
                window = e2e::webview2_automation(window);
            }
            // Atlas speaks replies that arrive after the click that asked for them; allow its own
            // audio to start without a fresh gesture (Tauri's default arguments are kept).
            #[cfg(all(windows, not(feature = "e2e")))]
            {
                window = window.additional_browser_args("--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required");
            }
            window
                .title("ATLAS Co-Pilot")
                .inner_size(1320.0, 860.0)
                .min_inner_size(760.0, 560.0)
                .background_color(tauri::window::Color(7, 11, 20, 255))
                // Dark title bar on Windows 10/11 from the first frame; the UI updates it with the theme.
                .theme(Some(tauri::Theme::Dark))
                .on_navigation(navigation_allowed)
                .build()?;
            // Tray visibility and the global shortcut follow the saved settings.
            app.state::<presence::Presence>().apply(&handle, &desktop);
            Ok(())
        })
        .on_window_event(|window, event| {
            // "Keep running in the tray": closing the window hides it; Quit is in the tray menu.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event
                && window.label() == "main"
                && window.app_handle().try_state::<presence::Presence>().is_some_and(|p| p.hides_on_close())
            {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(commands::handler())
        .build(tauri::generate_context!())
        .expect("error while running ATLAS Co-Pilot")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event
                && let Some(p) = app.try_state::<presence::Presence>()
            {
                p.shutdown(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::navigation_allowed;

    #[test]
    fn navigation_guard() {
        assert!(navigation_allowed(&"tauri://localhost/index.html".parse().unwrap()));
        assert!(navigation_allowed(&"http://tauri.localhost/index.html".parse().unwrap()));
        assert!(!navigation_allowed(&"https://evil.example.com/".parse().unwrap()));
        assert!(!navigation_allowed(&"file:///etc/passwd".parse().unwrap()));
        assert!(!navigation_allowed(&"javascript:alert(1)".parse().unwrap()));
    }
}
