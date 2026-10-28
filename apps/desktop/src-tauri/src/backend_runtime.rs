use std::{process::Child, sync::Mutex};

#[cfg(any(target_os = "windows", test))]
use std::path::{Path, PathBuf};

#[cfg(target_os = "windows")]
use std::{
    fs::{self, OpenOptions},
    io,
    net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream},
    os::windows::process::CommandExt,
    process::{Command, Stdio},
    time::Duration,
};

#[cfg(target_os = "windows")]
const BACKEND_PORT: u16 = 8765;
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Default)]
pub(crate) struct BackendRuntime(Mutex<Option<Child>>);

impl BackendRuntime {
    #[cfg(target_os = "windows")]
    pub(crate) fn start(&self, resource_dir: &Path, app_data_dir: &Path) -> io::Result<()> {
        if backend_port_is_in_use() {
            return Err(io::Error::new(
                io::ErrorKind::AddrInUse,
                "127.0.0.1:8765 is already in use; close the other Ankora session",
            ));
        }

        let executable = bundled_backend_path(resource_dir);
        if !executable.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                format!("bundled backend is missing: {}", executable.display()),
            ));
        }

        let data_dir = app_data_dir.join("data");
        let log_dir = app_data_dir.join("logs");
        fs::create_dir_all(&data_dir)?;
        fs::create_dir_all(&log_dir)?;
        let stdout = append_log(&log_dir.join("backend.stdout.log"))?;
        let stderr = append_log(&log_dir.join("backend.stderr.log"))?;

        let mut command = Command::new(&executable);
        command
            .arg("--parent-pid")
            .arg(std::process::id().to_string())
            .current_dir(executable.parent().ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "backend has no parent directory",
                )
            })?)
            .env("ANKORA_APP_MODE", "packaged")
            .env("ANKORA_DATA_DIR", &data_dir)
            .env("ANKORA_PYTHON_ENVIRONMENT", "Bundled Python 3.12")
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));
        command.creation_flags(CREATE_NO_WINDOW);

        let child = command.spawn()?;
        *self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(child);
        Ok(())
    }

    pub(crate) fn stop(&self) {
        let mut process = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(child) = process.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        *process = None;
    }
}

#[cfg(target_os = "windows")]
fn append_log(path: &Path) -> io::Result<std::fs::File> {
    OpenOptions::new().create(true).append(true).open(path)
}

#[cfg(target_os = "windows")]
fn backend_port_is_in_use() -> bool {
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), BACKEND_PORT);
    TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok()
}

#[cfg(any(target_os = "windows", test))]
pub(crate) fn bundled_backend_path(resource_dir: &Path) -> PathBuf {
    resource_dir.join("backend").join("ankora-backend.exe")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_backend_has_one_stable_resource_location() {
        assert_eq!(
            bundled_backend_path(Path::new("installation")),
            PathBuf::from("installation/backend/ankora-backend.exe")
        );
    }

    #[test]
    fn stop_is_noop_when_no_packaged_backend_is_running() {
        let runtime = BackendRuntime::default();
        runtime.stop();
        let guard = runtime
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        assert!(guard.is_none());
    }

    #[test]
    fn linux_tauri_config_stays_separate_and_preserves_security_policy() {
        let windows_cfg = include_str!("../tauri.conf.json");
        let linux_cfg = include_str!("../tauri.linux.conf.json");
        let pkg_json = include_str!("../../package.json");

        assert!(windows_cfg.contains("\"npm run dev:tauri-prereq\""));
        assert!(windows_cfg.contains("\"targets\": [\"nsis\"]"));
        assert!(linux_cfg.contains("\"npm run dev:tauri-prereq:linux\""));
        assert!(linux_cfg.contains("\"http://127.0.0.1:1420\""));
        assert!(linux_cfg.contains("connect-src 'self' http://127.0.0.1:8765"));
        assert!(!linux_cfg.contains("unsafe-eval"));
        assert!(linux_cfg.contains("\"active\": false"));
        assert!(linux_cfg.contains("\"targets\": []"));
        assert!(pkg_json.contains("python3 ../../scripts/dev_linux.py"));
    }
}
