mod backend_runtime;

use backend_runtime::BackendRuntime;
use tauri::Manager;

#[tauri::command]
fn backend_startup_error(runtime: tauri::State<'_, BackendRuntime>) -> Option<String> {
    runtime.startup_error()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![backend_startup_error])
        .setup(|app| {
            app.manage(BackendRuntime::default());
            #[cfg(any(target_os = "windows", target_os = "linux"))]
            if !cfg!(debug_assertions) {
                let start_result = (|| -> Result<(), String> {
                    let resource_dir = app
                        .path()
                        .resource_dir()
                        .map_err(|err| format!("failed to locate resource directory: {err}"))?;
                    let app_data_dir = app
                        .path()
                        .app_local_data_dir()
                        .map_err(|err| format!("failed to locate local data directory: {err}"))?;
                    app.state::<BackendRuntime>()
                        .start(&resource_dir, &app_data_dir)
                        .map_err(|err| err.to_string())
                })();
                if let Err(err) = start_result {
                    let message = format!("Could not start the bundled Ankora backend: {err}");
                    eprintln!("{message}");
                    app.state::<BackendRuntime>().record_startup_error(message);
                }
            }
            Ok(())
        });

    match builder.build(tauri::generate_context!()) {
        Ok(app) => {
            app.run(|app_handle, event| {
                if matches!(event, tauri::RunEvent::Exit) {
                    app_handle.state::<BackendRuntime>().stop();
                }
            });
        }
        Err(error) => {
            eprintln!("Ankora desktop shell failed to initialize: {error}");
        }
    }
}
