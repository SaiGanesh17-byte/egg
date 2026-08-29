/// lib.rs
/// Core entry point for NodeBook Tauri desktop client. Registers submodules, registers handlers,
/// and intercepts exit events to execute the 3-second save-flush handshake.

mod db;
mod config;
mod commands;

use std::sync::Mutex;
use std::path::PathBuf;
use tauri::{Emitter, Listener, Manager, RunEvent};

pub struct AppState {
    pub base_workspace_path: Mutex<Option<PathBuf>>,
    pub workspace_path: Mutex<Option<PathBuf>>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            base_workspace_path: Mutex::new(None),
            workspace_path: Mutex::new(None),
        })
        .setup(|app| {
            // 1. Load active base workspace path from local config and cache in AppState
            let app_handle = app.handle().clone();
            let config = config::load_config(&app_handle);
            if let Some(path_str) = config.workspace_path {
                let path = PathBuf::from(path_str);
                if path.exists() {
                    let state = app.state::<AppState>();
                    let lock_res = state.base_workspace_path.lock();
                    if let Ok(mut base_guard) = lock_res {
                        *base_guard = Some(path);
                    }
                }
            }

            // 2. Intercept window close request to perform the exit flush handshake
            if let Some(window) = app.get_webview_window("main") {
                let app_handle_clone = app_handle.clone();
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();

                        // Notify frontend to run sync save flush
                        let _ = app_handle_clone.emit("window-close-requested", ());

                        // Spawn a 3-second timeout thread to force exit if save hangs
                        let app_handle_timeout = app_handle_clone.clone();
                        tauri::async_runtime::spawn(async move {
                            tokio::time::sleep(std::time::Duration::from_secs(3)).await;
                            
                            // Timeout reached - write dirty save flag to config
                            let mut config = config::load_config(&app_handle_timeout);
                            config.last_session_clean = false;
                            let _ = config::save_config(&app_handle_timeout, &config);

                            app_handle_timeout.exit(1);
                        });
                    }
                });
            }

            // 3. Listen for the frontend's confirmation that flush has completed cleanly
            let app_handle_exit = app_handle.clone();
            app_handle.listen("ready-to-close", move |_| {
                // Save clean session flag in configuration
                let mut config = config::load_config(&app_handle_exit);
                config.last_session_clean = true;
                let _ = config::save_config(&app_handle_exit, &config);

                app_handle_exit.exit(0);
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::notebook::select_workspace_dir,
            commands::notebook::load_notebook,
            commands::notebook::load_page_content,
            commands::notebook::save_page_content,
            commands::notebook::create_section,
            commands::notebook::rename_section,
            commands::notebook::delete_section,
            commands::notebook::create_page,
            commands::notebook::rename_page,
            commands::notebook::delete_page,
            commands::notebook::select_active_notebook,
            commands::notebook::create_notebook,
            commands::notebook::rename_notebook,
            commands::notebook::delete_notebook,
            commands::notebook::take_screen_clipping,
            commands::blocks::save_block_data,
            commands::blocks::delete_block,
            commands::blocks::update_table_block_name,
            commands::links::get_backlinks,
            commands::links::get_all_links,
            commands::links::create_link,
            commands::links::delete_link,
            commands::page_metadata::update_page_record,
            commands::page_metadata::update_page_position,
            commands::page_metadata::load_page_snapshots,
            commands::page_metadata::create_page_snapshot,
            commands::page_metadata::restore_page_snapshot,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Cleanup if needed
            }
        });
}
