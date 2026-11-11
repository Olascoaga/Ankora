#!/usr/bin/env python3
"""Predeclared WSLg native desktop check for GninaScreeningWorkspace."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
GNINA_BINARY = REPO_ROOT / "logs/linux-gnina-investigation/v1.3.3/gnina"
EXPECTED_GNINA_SHA256 = "3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172"
SOURCE_RUN_DIR = REPO_ROOT / "logs/linux-gnina-investigation/v1.3.3/screening-api-cuda-01"
EXPECTED_SOURCE_EVIDENCE_SHA256 = (
    "9662bd482fa2a7c93fbf22ad5b9d22dc98b4c0aa0011d4c9774e898e30c3ddac"
)
RUN_DIR = REPO_ROOT / "logs/linux-gnina-investigation/v1.3.3/wslg-screening-ui-03"
HOME_DIR = Path.home()
PYTHON_BIN = Path(os.environ.get("ANKORA_PYTHON_BIN") or HOME_DIR / "Ankora/.venv/bin/python")
NODE_BIN_DIR = Path(
    os.environ.get("ANKORA_NODE_BIN_DIR") or HOME_DIR / ".nvm/versions/node/v24.19.0/bin"
)
CARGO_BIN_DIR = Path(os.environ.get("ANKORA_CARGO_BIN_DIR") or HOME_DIR / ".cargo/bin")
TAURI_DRIVER = CARGO_BIN_DIR / "tauri-driver"
WEBKIT_DRIVER = Path(os.environ.get("ANKORA_WEBKIT_DRIVER") or "/usr/bin/WebKitWebDriver")
DESKTOP_BINARY = Path(
    os.environ.get("ANKORA_DESKTOP_BINARY") or HOME_DIR / "Ankora-linux-target/debug/ankora-desktop"
)
PORTS = {"api": 8765, "web": 1420, "webdriver": 4444, "native_webdriver": 4445}

_LOOPBACK_HEX = {
    "/proc/net/tcp": {
        "".join(f"{w:08X}" for w in struct.unpack("=I", socket.inet_pton(socket.AF_INET, "127.0.0.1"))),
    },
    "/proc/net/tcp6": {
        "".join(
            f"{w:08X}"
            for w in struct.unpack("=4I", socket.inet_pton(socket.AF_INET6, "::ffff:127.0.0.1"))
        ),
        "".join(f"{w:08X}" for w in struct.unpack("=4I", socket.inet_pton(socket.AF_INET6, "::1"))),
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    manifest = hashlib.sha256()
    for file_path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = file_path.relative_to(root).as_posix()
        manifest.update(f"{rel}:{sha256_file(file_path)}\n".encode())
    return manifest.hexdigest()


def ensure_elf_executable(path: Path) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"Missing executable: {path}")
    with path.open("rb") as handle:
        if handle.read(4) != b"\x7fELF":
            raise RuntimeError(f"Expected Linux ELF executable, got non-ELF: {path}")


def port_accepting(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def verify_loopback_only(ports: set[int]) -> dict[str, list[str]]:
    observed: dict[str, list[str]] = {str(p): [] for p in sorted(ports)}
    for table, allowed_addrs in _LOOPBACK_HEX.items():
        table_path = Path(table)
        if not table_path.is_file():
            continue
        for row in table_path.read_text(encoding="ascii").splitlines()[1:]:
            fields = row.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            addr_hex, port_hex = fields[1].rsplit(":", 1)
            port = int(port_hex, 16)
            if port not in ports:
                continue
            observed[str(port)].append(f"{table}:{addr_hex}")
            if addr_hex not in allowed_addrs:
                raise RuntimeError(
                    f"Port {port} is bound to non-loopback address {addr_hex} in {table}"
                )
    for port in sorted(ports):
        if not observed[str(port)]:
            raise RuntimeError(f"Expected loopback listener on port {port}, found none")
    return observed


def query_gpu_state() -> dict[str, Any]:
    gpus_proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,uuid,name", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    gpu_rows = [line.strip() for line in gpus_proc.stdout.splitlines() if line.strip()]
    compute_proc = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,process_name", "--format=csv,noheader"],
        check=True,
        capture_output=True,
        text=True,
    )
    compute_rows = [line.strip() for line in compute_proc.stdout.splitlines() if line.strip()]
    return {"gpus": gpu_rows, "compute_apps": compute_rows}


def session_members(session_id: int) -> dict[int, int]:
    members: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        state, _ppid, group, session = stat[stat.rindex(")") + 2 :].split()[:4]
        if state != "Z" and int(session) == session_id:
            members[int(entry.name)] = int(group)
    return members


def stop_owned_session(proc: subprocess.Popen[bytes] | None, log_handle: Any) -> int | None:
    if proc is None:
        return None
    try:
        for signum in (signal.SIGTERM, signal.SIGKILL):
            members = session_members(proc.pid)
            if not members and proc.poll() is not None:
                break
            groups = set(members.values())
            if proc.poll() is None:
                groups.add(proc.pid)
            for group in groups:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(group, signum)
            deadline = time.monotonic() + 6.0
            while session_members(proc.pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if not session_members(proc.pid):
                break
        return proc.wait(timeout=5.0)
    finally:
        if log_handle is not None:
            with contextlib.suppress(OSError):
                log_handle.close()


class WebDriverClient:
    def __init__(self, base_url: str, trace_dir: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.trace_dir = trace_dir
        self.session_id: str | None = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._seq = 0

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            method=method,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        self._seq += 1
        try:
            with self._opener.open(req, timeout=60.0) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            (self.trace_dir / f"wd-{self._seq:03d}-error.json").write_text(
                json.dumps(
                    {"method": method, "path": path, "status": exc.code, "error": err_body},
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise RuntimeError(f"WebDriver {method} {path} -> HTTP {exc.code}: {err_body}") from exc
        if path != "/screenshot" and not path.endswith("/screenshot"):
            (self.trace_dir / f"wd-{self._seq:03d}.json").write_text(
                json.dumps({"method": method, "path": path, "response": raw}, indent=2),
                encoding="utf-8",
            )
        return raw.get("value")

    def start_session(self, application: Path) -> dict[str, Any]:
        value = self.request(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "tauri:options": {
                            "application": str(application),
                            "args": [],
                        }
                    }
                }
            },
        )
        if not isinstance(value, dict) or not isinstance(value.get("sessionId"), str):
            raise TypeError(f"Unexpected WebDriver session payload: {value!r}")
        self.session_id = value["sessionId"]
        return value

    def close_session(self) -> None:
        if self.session_id is None:
            return
        sid = self.session_id
        self.session_id = None
        with contextlib.suppress(OSError, RuntimeError, urllib.error.URLError):
            self.request("DELETE", f"/session/{sid}")

    def execute(self, script: str, args: list[Any] | None = None) -> Any:
        assert self.session_id is not None
        return self.request(
            "POST",
            f"/session/{self.session_id}/execute/sync",
            {"script": script, "args": args or []},
        )

    def set_window_rect(self, width: int, height: int) -> dict[str, Any]:
        assert self.session_id is not None
        res = self.request(
            "POST",
            f"/session/{self.session_id}/window/rect",
            {"width": width, "height": height, "x": 40, "y": 40},
        )
        return dict(res) if isinstance(res, dict) else {}

    def screenshot(self, target: Path) -> dict[str, Any]:
        assert self.session_id is not None
        b64 = self.request("GET", f"/session/{self.session_id}/screenshot")
        if not isinstance(b64, str):
            raise TypeError("WebDriver screenshot did not return base64 string")
        data = base64.b64decode(b64)
        with target.open("xb") as handle:
            handle.write(data)
        return {
            "filename": target.name,
            "size_bytes": len(data),
            "sha256": sha256_file(target),
        }

    def wait_until(self, description: str, predicate_js: str, timeout: float = 30.0) -> Any:
        deadline = time.monotonic() + timeout
        last_val: Any = None
        while time.monotonic() < deadline:
            last_val = self.execute(predicate_js)
            if last_val:
                return last_val
            time.sleep(0.35)
        body_excerpt = self.execute("return document.body ? document.body.innerText.slice(0, 1500) : '';")
        raise RuntimeError(
            f"Timed out waiting for {description} (last={last_val!r}); body={body_excerpt!r}"
        )


INSTALL_QA_PROBES_JS = """
if (!window.__wslgQaInstalled) {
  window.__wslgQaInstalled = true;
  window.__wslgQaErrors = [];
  window.addEventListener('error', (event) => {
    window.__wslgQaErrors.push('error: ' + String(event.message || event.error || 'unknown'));
  });
  window.addEventListener('unhandledrejection', (event) => {
    window.__wslgQaErrors.push('unhandledrejection: ' + String(event.reason));
  });
  document.addEventListener('securitypolicyviolation', (event) => {
    window.__wslgQaErrors.push('csp: ' + event.violatedDirective + ' -> ' + event.blockedURI);
  });
}
return { installed: true, errors: window.__wslgQaErrors };
"""


def wait_http_ok(url: str, timeout: float = 60.0) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with (
            contextlib.suppress(OSError, urllib.error.URLError),
            opener.open(url, timeout=1.5) as resp,
        ):
            if resp.status == 200:
                return
        time.sleep(0.3)
    raise RuntimeError(f"Timed out waiting for HTTP 200 from {url}")


def main() -> int:
    started_at = datetime.now(UTC).isoformat()
    if RUN_DIR.exists():
        raise SystemExit(f"Refusing to overwrite existing create-only directory: {RUN_DIR}")

    RUN_DIR.mkdir(parents=True, exist_ok=False)
    trace_dir = RUN_DIR / "webdriver-trace"
    trace_dir.mkdir(parents=True, exist_ok=False)

    evidence: dict[str, Any] = {
        "check": "wslg-screening-ui-03",
        "started_at": started_at,
        "passed": False,
        "environment": {
            "display": os.environ.get("DISPLAY"),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY"),
        },
        "screenshots": [],
        "viewports": [],
    }
    dev_proc: subprocess.Popen[bytes] | None = None
    dev_log_handle: Any = None
    driver_proc: subprocess.Popen[bytes] | None = None
    driver_log_handle: Any = None
    wd = WebDriverClient(f"http://127.0.0.1:{PORTS['webdriver']}", trace_dir)
    source_data_dir = SOURCE_RUN_DIR / "data"
    source_tree_before: str | None = None

    try:
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            raise RuntimeError("Neither DISPLAY nor WAYLAND_DISPLAY is set for WSLg")

        for binary in (GNINA_BINARY, PYTHON_BIN, TAURI_DRIVER, WEBKIT_DRIVER, DESKTOP_BINARY):
            ensure_elf_executable(binary)

        gnina_sha = sha256_file(GNINA_BINARY)
        if gnina_sha != EXPECTED_GNINA_SHA256:
            raise RuntimeError(f"GNINA binary SHA-256 mismatch: {gnina_sha}")
        source_ev_sha = sha256_file(SOURCE_RUN_DIR / "evidence.json")
        if source_ev_sha != EXPECTED_SOURCE_EVIDENCE_SHA256:
            raise RuntimeError(f"Source evidence.json SHA-256 mismatch: {source_ev_sha}")

        for name, port in PORTS.items():
            if port_accepting(port):
                raise RuntimeError(f"Port 127.0.0.1:{port} ({name}) is already in use")

        gpu_before = query_gpu_state()
        if len(gpu_before["gpus"]) != 1 or not gpu_before["gpus"][0].startswith("0,"):
            raise RuntimeError(f"Expected single GPU at index 0, got: {gpu_before['gpus']}")
        if gpu_before["compute_apps"]:
            raise RuntimeError(f"GPU compute apps active before run: {gpu_before['compute_apps']}")
        evidence["gpu_before"] = gpu_before

        source_tree_before = tree_digest(source_data_dir)
        evidence["source_tree_sha256_before"] = source_tree_before
        isolated_data_dir = RUN_DIR / "data"
        shutil.copytree(source_data_dir, isolated_data_dir)

        env = dict(os.environ)
        env["ANKORA_PYTHON_PATH"] = str(PYTHON_BIN)
        env["ANKORA_GNINA_PATH"] = str(GNINA_BINARY)
        env["ANKORA_DATA_DIR"] = str(isolated_data_dir)
        env["PATH"] = f"{NODE_BIN_DIR}:{CARGO_BIN_DIR}:{env.get('PATH', '')}"

        dev_log_path = RUN_DIR / "dev-linux.log"
        dev_log_handle = dev_log_path.open("xb")
        dev_proc = subprocess.Popen(
            [str(PYTHON_BIN), str(REPO_ROOT / "scripts/dev_linux.py")],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=dev_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        wait_http_ok(f"http://127.0.0.1:{PORTS['api']}/api/v1/health", timeout=60.0)
        wait_http_ok(f"http://127.0.0.1:{PORTS['web']}/", timeout=60.0)

        driver_log_path = RUN_DIR / "tauri-driver.log"
        driver_log_handle = driver_log_path.open("xb")
        driver_proc = subprocess.Popen(
            [
                str(TAURI_DRIVER),
                "--port",
                str(PORTS["webdriver"]),
                "--native-port",
                str(PORTS["native_webdriver"]),
                "--native-driver",
                str(WEBKIT_DRIVER),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=driver_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        deadline = time.monotonic() + 20.0
        while not port_accepting(PORTS["webdriver"]):
            if time.monotonic() >= deadline:
                raise RuntimeError("tauri-driver did not listen on 127.0.0.1:4444 within 20s")
            time.sleep(0.2)

        session_info = wd.start_session(DESKTOP_BINARY)
        capabilities = session_info.get("capabilities", {})
        evidence["webdriver_capabilities"] = capabilities
        if capabilities.get("browserName") != "wry" or capabilities.get("platformName") != "linux":
            raise RuntimeError(f"Unexpected WebDriver capabilities: {capabilities!r}")
        if capabilities.get("acceptInsecureCerts") is not False:
            raise RuntimeError(f"Expected acceptInsecureCerts=False, got: {capabilities!r}")

        evidence["loopback_listeners"] = verify_loopback_only(set(PORTS.values()))
        wd.set_window_rect(1280, 800)

        # Wait for the workbench shell and install error/CSP probes.
        wd.wait_until(
            "Backend connected and saved receptor button",
            """
            const pill = document.querySelector('.connection-pill');
            const resume = document.querySelector('button.structure-resume');
            return Boolean(pill && pill.textContent.includes('Backend connected') && resume);
            """,
            timeout=35.0,
        )
        wd.execute(INSTALL_QA_PROBES_JS)

        # 1. Reopen saved 1HSG receptor.
        wd.execute("document.querySelector('button.structure-resume').click(); return true;")
        wd.wait_until(
            "Receptor workspace docking_ready",
            """
            const nav = document.querySelector("nav[aria-label='Docking workflow']");
            const btn = nav && [...nav.querySelectorAll('button')].find(b => b.innerText.includes('Ligand') && !b.disabled);
            return Boolean(btn);
            """,
            timeout=25.0,
        )

        # 2. Open Ligand -> Virtual screening -> reopen imported nci_real_100.sdf.
        wd.execute(
            """
            const nav = document.querySelector("nav[aria-label='Docking workflow']");
            const btn = [...nav.querySelectorAll('button')].find(b => b.innerText.includes('Ligand'));
            btn.click();
            return true;
            """
        )
        wd.wait_until(
            "Virtual screening mode switch",
            """
            const sw = document.querySelector("[aria-label='Ligand workspace mode']");
            return Boolean(sw);
            """,
            timeout=20.0,
        )
        wd.execute(
            """
            const sw = document.querySelector("[aria-label='Ligand workspace mode']");
            const btn = [...sw.querySelectorAll('button')].find(b => b.innerText.includes('Virtual screening'));
            btn.click();
            return true;
            """
        )
        wd.wait_until(
            "Imported libraries shelf with nci_real_100.sdf",
            """
            const shelf = document.querySelector("[aria-label='Imported libraries']");
            const item = shelf && [...shelf.querySelectorAll('button')].find(b => b.innerText.includes('nci_real_100.sdf'));
            return Boolean(item && !item.disabled);
            """,
            timeout=20.0,
        )
        wd.execute(
            """
            const shelf = document.querySelector("[aria-label='Imported libraries']");
            const item = [...shelf.querySelectorAll('button')].find(b => b.innerText.includes('nci_real_100.sdf'));
            item.click();
            return true;
            """
        )
        wd.wait_until(
            "Hydrated 11 prepared NCI molecules",
            """
            const nav = document.querySelector("nav[aria-label='Docking workflow']");
            return Boolean(nav && nav.innerText.includes('11/11'));
            """,
            timeout=30.0,
        )

        # 3. Open Binding site -> Co-crystallized ligand MK1 B:902 -> Preview -> Finalize.
        wd.execute(
            """
            const nav = document.querySelector("nav[aria-label='Docking workflow']");
            const btn = [...nav.querySelectorAll('button')].find(b => b.innerText.includes('Binding site'));
            btn.click();
            return true;
            """
        )
        wd.wait_until(
            "Binding site workspace source tabs",
            "return Boolean(document.querySelector('.binding-site-source-section'));",
            timeout=20.0,
        )
        wd.execute(
            """
            const tabs = document.querySelector('.binding-site-source-section .source-tabs');
            const tab = [...tabs.querySelectorAll('button')].find(b => b.innerText.includes('Co-crystallized ligand'));
            tab.click();
            return true;
            """
        )
        wd.wait_until(
            "MK1 heterogen candidate",
            """
            const list = document.querySelector('.binding-site-source-section .selection-list');
            const mk1 = list && [...list.querySelectorAll('button')].find(b => b.innerText.includes('MK1'));
            return Boolean(mk1);
            """,
            timeout=15.0,
        )
        wd.execute(
            """
            const list = document.querySelector('.binding-site-source-section .selection-list');
            const mk1 = [...list.querySelectorAll('button')].find(b => b.innerText.includes('MK1'));
            mk1.click();
            return true;
            """
        )
        wd.execute(
            """
            const previewBtn = [...document.querySelectorAll('.binding-site-source-section button')]
              .find(b => b.innerText.includes('Preview box from this ligand'));
            previewBtn.click();
            return true;
            """
        )
        wd.wait_until(
            "Finalize binding site button enabled",
            """
            const btn = [...document.querySelectorAll('.binding-box-editor-section button')]
              .find(b => b.innerText.includes('Define this binding site and continue to Docking'));
            return Boolean(btn && !btn.disabled);
            """,
            timeout=20.0,
        )
        wd.execute(
            """
            const btn = [...document.querySelectorAll('.binding-box-editor-section button')]
              .find(b => b.innerText.includes('Define this binding site and continue to Docking'));
            btn.click();
            return true;
            """
        )

        # 4. In Docking workspace, switch to GNINA · screening.
        wd.wait_until(
            "Docking experiment mode switch with GNINA · screening",
            """
            const sw = document.querySelector("[aria-label='Docking experiment']");
            const btn = sw && [...sw.querySelectorAll('button')].find(b => b.innerText.trim() === 'GNINA · screening');
            return Boolean(btn);
            """,
            timeout=20.0,
        )
        wd.execute(
            """
            const sw = document.querySelector("[aria-label='Docking experiment']");
            const btn = [...sw.querySelectorAll('button')].find(b => b.innerText.trim() === 'GNINA · screening');
            btn.click();
            return true;
            """
        )
        wd.wait_until(
            "GNINA campaign inspector ready",
            """
            const insp = document.querySelector("[aria-label='GNINA campaign inspector']");
            return Boolean(insp && insp.innerText.includes('11 / 11 selected molecules prepared'));
            """,
            timeout=20.0,
        )

        # Configure CUDA + bounded screening parameters via React native value setters.
        configured = wd.execute(
            """
            function setSelect(el, val) {
              const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
              setter.call(el, val);
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            function setInput(el, val) {
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              setter.call(el, String(val));
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            setSelect(document.querySelector("select[aria-label='Compute']"), 'cuda');
            setInput(document.querySelector("input[aria-label='CPU threads']"), 2);
            setInput(document.querySelector("input[aria-label='Seed']"), 20261029);
            setInput(document.querySelector("input[aria-label='Exhaustiveness']"), 1);
            setInput(document.querySelector("input[aria-label='Maximum poses']"), 2);
            setInput(document.querySelector("input[aria-label='Timeout / molecule (min)']"), 3);
            return {
              compute: document.querySelector("select[aria-label='Compute']").value,
              threads: document.querySelector("input[aria-label='CPU threads']").value,
              exhaustiveness: document.querySelector("input[aria-label='Exhaustiveness']").value,
              modes: document.querySelector("input[aria-label='Maximum poses']").value,
            };
            """
        )
        evidence["configured_parameters"] = configured

        wd.execute(
            """
            const ack = document.querySelector(".docking-inspector .docking-acknowledgement input[type='checkbox']");
            ack.click();
            return ack.checked;
            """
        )
        wd.wait_until(
            "Dock 11 prepared molecules enabled",
            """
            const btn = [...document.querySelectorAll('.docking-inspector button.docking-primary-action')]
              .find(b => b.innerText.includes('Dock 11 prepared molecules'));
            return Boolean(btn && !btn.disabled);
            """,
            timeout=10.0,
        )
        wd.execute(
            """
            const btn = [...document.querySelectorAll('.docking-inspector button.docking-primary-action')]
              .find(b => b.innerText.includes('Dock 11 prepared molecules'));
            btn.click();
            return true;
            """
        )

        # Capture a live running screenshot once campaign mounts.
        wd.wait_until(
            "GNINA campaign results table mounted",
            "return Boolean(document.querySelector(\"[aria-label='GNINA campaign results']\"));",
            timeout=20.0,
        )
        time.sleep(2.5)
        evidence["screenshots"].append(wd.screenshot(RUN_DIR / "1280-running.png"))

        # Wait for all 11 molecules to complete in the live UI and all 11 jobs to be read.
        wd.wait_until(
            "Campaign completed 11 / 11",
            """
            const cancelBtn = [...document.querySelectorAll('.docking-inspector button')]
              .find(b => b.innerText.includes('Cancel campaign'));
            if (cancelBtn) return false;
            const readBtn = [...document.querySelectorAll("[aria-label='GNINA campaign results'] button")]
              .find(b => b.innerText.includes('Read scores from ') && !b.disabled);
            if (readBtn) readBtn.click();
            const results = document.querySelector("[aria-label='GNINA campaign results']");
            if (!results || !results.innerText.includes("Every finished molecule's job has been read")) {
              return false;
            }
            const rows = [...results.querySelectorAll(':scope .docking-results-scroll > table > tbody > tr:not(.pose-expansion)')];
            if (rows.length !== 11) return false;
            return rows.every(tr => {
              const cells = tr.querySelectorAll(':scope > td');
              return cells.length >= 6 && !cells[2].innerText.includes('—');
            });
            """,
            timeout=240.0,
        )

        # Sort by Top CNN score descending, expand the top row, and select Pose 1.
        wd.execute(
            """
            const sortBtn = [...document.querySelectorAll("[aria-label='GNINA campaign results'] thead button.result-sort")]
              .find(b => b.innerText.includes('Top CNN score'));
            sortBtn.click();
            return true;
            """
        )
        time.sleep(0.4)
        wd.execute(
            """
            const firstExpand = document.querySelector("[aria-label='GNINA campaign results'] tbody button.compound-expand");
            firstExpand.click();
            return firstExpand.innerText;
            """
        )
        wd.wait_until(
            "Expanded pose table with Pose 1",
            """
            const poseBtn = [...document.querySelectorAll('.compound-poses button.pose-select')]
              .find(b => b.innerText.trim() === 'Pose 1');
            return Boolean(poseBtn);
            """,
            timeout=15.0,
        )
        wd.execute(
            """
            const poseBtn = [...document.querySelectorAll('.compound-poses button.pose-select')]
              .find(b => b.innerText.trim() === 'Pose 1');
            poseBtn.click();
            return true;
            """
        )

        # Give Mol* time to fetch and render the pose PDBQT alongside the prepared receptor.
        time.sleep(2.5)
        table_audit = wd.execute(
            """
            const results = document.querySelector("[aria-label='GNINA campaign results']");
            const headers = [...results.querySelectorAll(':scope .docking-results-scroll > table > thead th')]
              .map(th => th.innerText.replace(/\\s+/g, ' ').trim());
            const topRows = [...results.querySelectorAll(':scope .docking-results-scroll > table > tbody > tr:not(.pose-expansion)')]
              .map(tr => [...tr.querySelectorAll(':scope > td')].map(td => td.innerText.replace(/\\s+/g, ' ').trim()));
            const poseRows = [...results.querySelectorAll('.compound-poses tbody tr')]
              .map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.replace(/\\s+/g, ' ').trim()));
            const inspectorText = document.querySelector("[aria-label='GNINA campaign inspector']").innerText;
            return { headers, topRows, poseRows, inspectorExcerpt: inspectorText.slice(0, 2000) };
            """
        )
        evidence["table_audit"] = table_audit

        headers_joined = " | ".join(table_audit["headers"])
        for expected_col in (
            "Top CNN score (dimensionless)",
            "CNN affinity (pK)",
            "Minimized affinity (kcal/mol)",
        ):
            if expected_col not in headers_joined:
                raise RuntimeError(f"Missing expected column {expected_col!r} in {headers_joined!r}")
        if len(table_audit["topRows"]) != 11:
            raise RuntimeError(f"Expected 11 compound rows, got {len(table_audit['topRows'])}")
        for row in table_audit["topRows"]:
            # columns: #, Molecule, CNN score, CNN affinity, Minimized affinity, Status
            float(row[2])
            float(row[3])
            float(row[4])
        if len(table_audit["poseRows"]) < 1:
            raise RuntimeError("Expected at least 1 pose row in expanded compound")
        pose_cnn_scores = [float(r[1]) for r in table_audit["poseRows"]]
        if pose_cnn_scores != sorted(pose_cnn_scores, reverse=True):
            raise RuntimeError(f"Expanded poses not ordered by descending CNN score: {pose_cnn_scores}")

        # Verify viewports (1280x800 and 960x680), Mol* WebGL 2.0, zero overflow, screenshots.
        for width, height in ((1280, 800), (960, 680)):
            actual_rect = wd.set_window_rect(width, height)
            time.sleep(1.2)
            probe = wd.execute(
                """
                const doc = document.documentElement;
                const ws = document.querySelector('.workspace');
                const insp = document.querySelector("[aria-label='GNINA campaign inspector']");
                const canvas = document.querySelector('.msp-plugin canvas');
                const gl = canvas ? (canvas.getContext('webgl2') || canvas.getContext('webgl')) : null;
                const wsRect = ws ? ws.getBoundingClientRect() : null;
                const inspRect = insp ? insp.getBoundingClientRect() : null;
                return {
                  innerWidth: window.innerWidth,
                  innerHeight: window.innerHeight,
                  docClientWidth: doc.clientWidth,
                  docScrollWidth: doc.scrollWidth,
                  workspaceRect: wsRect ? { width: wsRect.width, height: wsRect.height } : null,
                  inspectorRect: inspRect ? { width: inspRect.width, height: inspRect.height } : null,
                  viewer: canvas && gl ? {
                    canvasWidth: canvas.width,
                    canvasHeight: canvas.height,
                    contextLost: gl.isContextLost(),
                    version: String(gl.getParameter(gl.VERSION)),
                    renderer: String(gl.getParameter(gl.RENDERER)),
                  } : null,
                  errors: window.__wslgQaErrors || [],
                };
                """
            )
            probe["requested"] = {"width": width, "height": height}
            probe["window_rect"] = actual_rect
            evidence["viewports"].append(probe)

            if probe["docScrollWidth"] > probe["docClientWidth"] + 1:
                raise RuntimeError(f"Horizontal document overflow at {width}x{height}: {probe}")
            if not probe["workspaceRect"] or probe["workspaceRect"]["width"] <= 0:
                raise RuntimeError(f"Workspace not visible at {width}x{height}: {probe}")
            if not probe["inspectorRect"] or probe["inspectorRect"]["width"] <= 0:
                raise RuntimeError(f"Inspector not visible at {width}x{height}: {probe}")
            viewer = probe["viewer"]
            if (
                not viewer
                or viewer["canvasWidth"] <= 0
                or viewer["canvasHeight"] <= 0
                or viewer["contextLost"] is not False
                or not viewer["version"].startswith("WebGL 2.0")
            ):
                raise RuntimeError(f"Invalid Mol* WebGL 2.0 state at {width}x{height}: {viewer}")
            if probe["errors"]:
                raise RuntimeError(f"Recorded UI/CSP errors at {width}x{height}: {probe['errors']}")

            # Top-of-workspace (viewer + pose) screenshot and scrolled results table screenshot.
            wd.execute("document.querySelector('.workspace').scrollTop = 0; return true;")
            time.sleep(0.3)
            evidence["screenshots"].append(
                wd.screenshot(RUN_DIR / f"{width}-viewer-and-inspector.png")
            )
            wd.execute(
                """
                const res = document.querySelector("[aria-label='GNINA campaign results']");
                res.scrollIntoView({ block: 'start' });
                return true;
                """
            )
            time.sleep(0.3)
            evidence["screenshots"].append(
                wd.screenshot(RUN_DIR / f"{width}-campaign-results.png")
            )

        evidence["passed"] = True
        return 0
    except Exception as exc:
        evidence["passed"] = False
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        wd.close_session()
        evidence["driver_exit"] = stop_owned_session(driver_proc, driver_log_handle)
        evidence["dev_launcher_exit"] = stop_owned_session(dev_proc, dev_log_handle)
        time.sleep(1.0)
        ports_after = {name: port_accepting(port) for name, port in PORTS.items()}
        evidence["ports_accepting_after_teardown"] = ports_after
        gpu_after = query_gpu_state()
        evidence["gpu_after"] = gpu_after
        if source_tree_before is not None:
            source_tree_after = tree_digest(source_data_dir)
            evidence["source_tree_sha256_after"] = source_tree_after
            evidence["source_tree_unchanged"] = source_tree_after == source_tree_before
            if source_tree_after != source_tree_before:
                evidence["passed"] = False
        if any(ports_after.values()) or gpu_after["compute_apps"]:
            evidence["passed"] = False
        evidence["completed_at"] = datetime.now(UTC).isoformat()
        ev_path = RUN_DIR / "evidence.json"
        with ev_path.open("x", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"EVIDENCE_PATH={ev_path}")
        print(f"EVIDENCE_SHA256={sha256_file(ev_path)}")
        print(f"PASSED={evidence['passed']}")


if __name__ == "__main__":
    raise SystemExit(main())
