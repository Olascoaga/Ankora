mod backend_runtime;

use backend_runtime::BackendRuntime;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(BackendRuntime::default());
            #[cfg(target_os = "windows")]
            if !cfg!(debug_assertions) {
                let resource_dir = app.path().resource_dir()?;
                let app_data_dir = app.path().app_local_data_dir()?;
                app.state::<BackendRuntime>()
                    .start(&resource_dir, &app_data_dir)?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Ankora desktop shell");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            app_handle.state::<BackendRuntime>().stop();
        }
    });
}
