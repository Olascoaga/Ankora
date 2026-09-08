fn main() {
    std::fs::create_dir_all("resources/backend")
        .expect("failed to create generated backend resource directory");
    tauri_build::build()
}
