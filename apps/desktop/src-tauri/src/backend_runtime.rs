use std::{process::Child, sync::Mutex};

#[cfg(any(target_os = "windows", target_os = "linux", test))]
use std::path::{Path, PathBuf};

#[cfg(any(target_os = "windows", target_os = "linux"))]
use std::{
    fs::{self, OpenOptions},
    io,
    net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream},
    process::{Command, Stdio},
    time::Duration,
};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "linux")]
use std::thread;

#[cfg(any(target_os = "windows", target_os = "linux"))]
const BACKEND_PORT: u16 = 8765;
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Default)]
pub(crate) struct BackendRuntime(Mutex<Option<Child>>);

impl BackendRuntime {
    #[cfg(any(target_os = "windows", target_os = "linux"))]
    pub(crate) fn start(&self, resource_dir: &Path, app_data_dir: &Path) -> io::Result<()> {
        if backend_port_is_in_use() {
            return Err(io::Error::new(
                io::ErrorKind::AddrInUse,
                "127.0.0.1:8765 is already in use; close the other Ankora session",
            ));
        }

        let current_exe_dir = std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(Path::to_path_buf));
        let executable = resolve_backend_executable(resource_dir, current_exe_dir.as_deref());
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
        #[cfg(target_os = "linux")]
        let toolchains_dir = app_data_dir.join("toolchains");
        #[cfg(target_os = "linux")]
        fs::create_dir_all(&toolchains_dir)?;

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

        #[cfg(target_os = "linux")]
        command.env("ANKORA_TOOLCHAINS_DIR", &toolchains_dir);

        #[cfg(target_os = "windows")]
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
            terminate_child(child);
        }
        *process = None;
    }
}

#[cfg(target_os = "linux")]
fn terminate_child(child: &mut Child) {
    if let Ok(Some(_)) = child.try_wait() {
        return;
    }
    let _ = Command::new("/bin/kill")
        .arg("-TERM")
        .arg(child.id().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    for _ in 0..60 {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(not(target_os = "linux"))]
fn terminate_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(any(target_os = "windows", target_os = "linux"))]
fn append_log(path: &Path) -> io::Result<std::fs::File> {
    OpenOptions::new().create(true).append(true).open(path)
}

#[cfg(any(target_os = "windows", target_os = "linux"))]
fn backend_port_is_in_use() -> bool {
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), BACKEND_PORT);
    TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok()
}

#[cfg(any(target_os = "windows", target_os = "linux", test))]
pub(crate) fn resolve_backend_executable(
    resource_dir: &Path,
    executable_dir: Option<&Path>,
) -> PathBuf {
    #[cfg(target_os = "linux")]
    if let Some(exe_dir) = executable_dir {
        let colocated = bundled_backend_path(exe_dir);
        if colocated.is_file() {
            return colocated;
        }
    }
    #[cfg(not(target_os = "linux"))]
    let _ = executable_dir;
    bundled_backend_path(resource_dir)
}

#[cfg(target_os = "windows")]
pub(crate) fn bundled_backend_path(resource_dir: &Path) -> PathBuf {
    resource_dir.join("backend").join("ankora-backend.exe")
}

#[cfg(all(not(target_os = "windows"), any(target_os = "linux", test)))]
pub(crate) fn bundled_backend_path(resource_dir: &Path) -> PathBuf {
    resource_dir.join("backend").join("ankora-backend")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_backend_has_one_stable_resource_location() {
        #[cfg(target_os = "windows")]
        let expected = PathBuf::from("installation/backend/ankora-backend.exe");
        #[cfg(not(target_os = "windows"))]
        let expected = PathBuf::from("installation/backend/ankora-backend");
        assert_eq!(bundled_backend_path(Path::new("installation")), expected);
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

    #[cfg(target_os = "linux")]
    #[test]
    fn resolve_backend_executable_prefers_colocated_linux_bundle() {
        let root = std::env::temp_dir().join(format!("ankora-rust-test-{}", std::process::id()));
        let colocated_dir = root.join("portable");
        let fallback_dir = root.join("system-resources");
        fs::create_dir_all(colocated_dir.join("backend")).expect("create colocated backend dir");
        fs::create_dir_all(fallback_dir.join("backend")).expect("create fallback backend dir");
        let colocated_bin = colocated_dir.join("backend").join("ankora-backend");
        let fallback_bin = fallback_dir.join("backend").join("ankora-backend");
        fs::write(&colocated_bin, b"portable").expect("write colocated bin");
        fs::write(&fallback_bin, b"fallback").expect("write fallback bin");

        assert_eq!(
            resolve_backend_executable(&fallback_dir, Some(&colocated_dir)),
            colocated_bin
        );
        fs::remove_file(&colocated_bin).expect("remove colocated bin");
        assert_eq!(
            resolve_backend_executable(&fallback_dir, Some(&colocated_dir)),
            fallback_bin
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn stop_gracefully_terminates_posix_child() {
        let child = Command::new("/bin/sleep")
            .arg("60")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn sleep");
        let runtime = BackendRuntime(Mutex::new(Some(child)));
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
        let linux_release_cfg = include_str!("../tauri.linux.release.conf.json");
        let pkg_json = include_str!("../../package.json");

        assert!(windows_cfg.contains("\"npm run dev:tauri-prereq\""));
        assert!(windows_cfg.contains("\"targets\": [\"nsis\"]"));
        assert!(linux_cfg.contains("\"npm run dev:tauri-prereq:linux\""));
        assert!(linux_cfg.contains("\"http://127.0.0.1:1420\""));
        assert!(linux_cfg.contains("connect-src 'self' http://127.0.0.1:8765"));
        assert!(!linux_cfg.contains("unsafe-eval"));
        assert!(linux_cfg.contains("\"active\": false"));
        assert!(linux_cfg.contains("\"targets\": []"));
        assert!(linux_release_cfg.contains("connect-src 'self' http://127.0.0.1:8765"));
        assert!(!linux_release_cfg.contains("unsafe-eval"));
        assert!(!linux_release_cfg.contains("127.0.0.1:1420"));
        assert!(linux_release_cfg.contains("\"active\": false"));
        assert!(pkg_json.contains("python3 ../../scripts/dev_linux.py"));
    }
}
