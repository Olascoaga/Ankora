fn main() {
    std::fs::create_dir_all("resources/backend")
        .expect("failed to create generated backend resource directory");
    std::fs::create_dir_all("resources/complete-legal")
        .expect("failed to create generated legal resource directory");
    tauri_build::build()
}
