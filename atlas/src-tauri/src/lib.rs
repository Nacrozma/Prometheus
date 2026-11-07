//! ATLAS Co-Pilot desktop shell. A thin layer: it owns the window, native dialogs and the IPC
//! command surface, and delegates every operation to `atlas-core`, the trusted core.

mod commands;
#[cfg(feature = "e2e")]
mod e2e;

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
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let handle = app.handle().clone();
            let dir = data_dir(&handle);
            std::fs::create_dir_all(&dir)?;

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
                    bg.sibling_sync_once().await;
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                }
            });
            app.manage(AppState { atlas, pending_restore: Mutex::new(None) });

            #[allow(unused_mut)]
            let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()));
            #[cfg(all(windows, feature = "e2e"))]
            {
                window = e2e::webview2_automation(window);
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
            Ok(())
        })
        .invoke_handler(commands::handler())
        .run(tauri::generate_context!())
        .expect("error while running ATLAS Co-Pilot");
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
