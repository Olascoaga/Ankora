"""Build and smoke-verify the slim Linux x86_64 frozen backend (ADR-029 D1).

Creates an isolated packaging venv layered over the locked `ankora-dev` Conda
environment so `ankora-dev` itself is never mutated, builds the relocatable
`ankora-backend` ELF onedir bundle with PyInstaller, verifies 1:1 frozen module
parity and absence of host driver/Tcl/Tk libraries, and runs a clean-PATH
localhost HTTP + POSIX `--parent-pid` watchdog smoke check.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "backend/packaging/ankora_backend_linux.spec"
BACKEND_SRC = ROOT / "backend/src"
PACKAGING_LOCK = ROOT / "requirements/linux-packaging.lock"
DEFAULT_BUILD_ROOT = ROOT / "build/linux-runtime"
FORBIDDEN_DRIVER_PREFIXES = (
    "libcuda.so",
    "libnvidia-ml.so",
    "libnvidia-ptxjitcompiler.so",
)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def discover_locked_conda_python(explicit: Path | None = None) -> Path:
    if explicit is not None:
        resolved = explicit.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Locked Conda Python not found: {resolved}")
        return resolved
    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix and Path(conda_prefix).name == "ankora-dev":
        candidate = Path(conda_prefix) / "bin/python"
        if candidate.is_file():
            return candidate
    for dist in ("miniforge3", "mambaforge", "miniconda3", "anaconda3"):
        candidate = Path.home() / dist / "envs/ankora-dev/bin/python"
        if candidate.is_file():
            return candidate
    if Path(sys.prefix).name == "ankora-dev":
        return Path(sys.executable)
    raise RuntimeError("Could not locate locked 'ankora-dev' Conda Python.")


def verify_locked_conda_runtime(conda_python: Path) -> None:
    subprocess.run(
        [str(conda_python), str(ROOT / "scripts/verify_linux_environment_lock.py"), "--runtime"],
        cwd=ROOT,
        check=True,
    )


def ensure_isolated_packaging_site(
    conda_python: Path, site_dir: Path, wheel_cache: Path | None = None
) -> Path:
    if site_dir.exists():
        import shutil

        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    pip_cmd = [
        str(conda_python),
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--require-hashes",
        "--target",
        str(site_dir),
        "-r",
        str(PACKAGING_LOCK),
    ]
    if wheel_cache is not None and wheel_cache.is_dir():
        pip_cmd.extend(["--no-index", "--find-links", str(wheel_cache)])
    subprocess.run(pip_cmd, cwd=ROOT, check=True)
    return site_dir


def expected_ankora_modules(backend_src: Path = BACKEND_SRC) -> set[str]:
    pkg_root = backend_src / "ankora_backend"
    modules: set[str] = set()
    for py_file in pkg_root.rglob("*.py"):
        rel = py_file.relative_to(backend_src).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.add(".".join(parts))
    return modules


def parse_pyz_toc_modules(pyz_toc_path: Path) -> set[str]:
    raw = ast.literal_eval(pyz_toc_path.read_text(encoding="utf-8"))
    entries = (
        raw[1]
        if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], list)
        else raw
    )
    if not isinstance(entries, list):
        raise TypeError(f"Unsupported PYZ TOC structure in {pyz_toc_path}")
    return {str(entry[0]) for entry in entries if isinstance(entry, tuple) and entry}


def verify_frozen_module_parity(
    pyz_toc_path: Path, backend_src: Path = BACKEND_SRC
) -> set[str]:
    expected = expected_ankora_modules(backend_src)
    frozen_all = parse_pyz_toc_modules(pyz_toc_path)
    frozen_ankora = {
        mod for mod in frozen_all if mod == "ankora_backend" or mod.startswith("ankora_backend.")
    }
    missing = sorted(expected - frozen_ankora)
    extra = sorted(frozen_ankora - expected)
    if missing or extra:
        raise ValueError(
            f"Frozen ankora_backend module parity mismatch: missing={missing}, extra={extra}"
        )
    return frozen_ankora


def verify_elf_x86_64(executable: Path) -> None:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"Missing or non-executable ELF: {executable}")
    with executable.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[5] != 1:
        raise ValueError(f"Not a little-endian ELF executable: {executable}")
    machine = int.from_bytes(header[18:20], byteorder="little")
    if machine != 0x3E:
        raise ValueError(f"Expected x86_64 ELF (0x3e), got {hex(machine)}: {executable}")


def audit_bundle_contents(bundle_dir: Path) -> dict[str, Any]:
    executable = bundle_dir / "ankora-backend"
    verify_elf_x86_64(executable)
    total_bytes = 0
    file_count = 0
    for item in bundle_dir.rglob("*"):
        if item.is_symlink() or item.is_file():
            name_lower = item.name.lower()
            if any(name_lower.startswith(p) for p in FORBIDDEN_DRIVER_PREFIXES):
                raise ValueError(f"Forbidden host GPU driver library bundled: {item}")
            if name_lower.startswith(("libtcl", "libtk", "_tkinter")):
                raise ValueError(f"Unpruned Tcl/Tk artifact in slim bundle: {item}")
        if item.is_file() and not item.is_symlink():
            total_bytes += item.stat().st_size
            file_count += 1
    openmm_plugins = sorted(
        p.name for p in (bundle_dir / "_internal/openmm_plugins").glob("*.so*")
    )
    if "libOpenMMCPU.so" not in openmm_plugins:
        raise ValueError("Bundled OpenMM CPU plugin missing from _internal/openmm_plugins")
    return {
        "executable_sha256": sha256_file(executable),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "total_mib": round(total_bytes / (1024 * 1024), 2),
        "openmm_plugins": openmm_plugins,
    }


def _pick_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_json(
    url: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None
) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def smoke_frozen_backend(bundle_dir: Path) -> dict[str, Any]:
    executable = bundle_dir / "ankora-backend"
    clean_base_env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }

    probe = subprocess.run(
        [str(executable), "--worker", "native-smoke", "--package-probe"],
        cwd=bundle_dir,
        env=clean_base_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    package_versions = json.loads(probe.stdout)
    expected_packages = {
        "dimorphite_dl",
        "MDAnalysis",
        "meeko",
        "openmm",
        "pdb2pqr",
        "pdbfixer",
        "prolif",
        "propka",
        "rdkit",
    }
    if set(package_versions) != expected_packages:
        raise RuntimeError(f"Incomplete frozen package probe: {package_versions}")

    with tempfile.TemporaryDirectory(prefix="ankora-d1-smoke-") as tmp:
        tmp_root = Path(tmp)
        data_dir = tmp_root / "data"
        data_dir.mkdir()
        port = _pick_ephemeral_port()
        # Spawn a benign sleeper acting as the parent desktop process so we can
        # terminate it and prove the POSIX --parent-pid watchdog exits cleanly.
        sleeper = subprocess.Popen(
            ["/bin/sleep", "120"],
            env=clean_base_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        backend_env = {
            **clean_base_env,
            "HOME": str(tmp_root),
            "ANKORA_DATA_DIR": str(data_dir),
            "ANKORA_APP_MODE": "packaged",
            "ANKORA_PYTHON_ENVIRONMENT": "Bundled Python 3.12",
            "ANKORA_BACKEND_PORT": str(port),
        }
        backend_proc = subprocess.Popen(
            [str(executable), "--parent-pid", str(sleeper.pid)],
            cwd=bundle_dir,
            env=backend_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            system_payload: dict[str, Any] | None = None
            for _ in range(100):
                if backend_proc.poll() is not None:
                    out, err = backend_proc.communicate(timeout=5)
                    raise RuntimeError(
                        f"Frozen backend exited early ({backend_proc.returncode}):\n{out}\n{err}"
                    )
                try:
                    code, health = _http_json(f"{base_url}/api/v1/health")
                    if code == 200 and health.get("status") == "ok":
                        sys_code, system_payload = _http_json(f"{base_url}/api/v1/system")
                        if sys_code == 200:
                            break
                except OSError:
                    time.sleep(0.2)
            if system_payload is None:
                raise RuntimeError("Frozen Linux backend did not become healthy on localhost.")
            if (
                system_payload.get("app_mode") != "packaged"
                or system_payload.get("python_environment") != "Bundled Python 3.12"
            ):
                raise RuntimeError(f"Unexpected /api/v1/system payload: {system_payload}")

            foreign_code, foreign_body = _http_json(
                f"{base_url}/api/v1/structures/import",
                method="POST",
                headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
                data=b"synthetic",
            )
            if foreign_code != 403 or foreign_body.get("code") != "UPLOAD_ORIGIN_NOT_ALLOWED":
                raise RuntimeError(
                    f"Origin guard failed on frozen backend: {foreign_code} {foreign_body}"
                )

            # Kill and reap sleeper -> backend must self-exit via _exit_when_parent_stops.
            sleeper.terminate()
            sleeper.wait(timeout=5)
            watchdog_exit_code = backend_proc.wait(timeout=8)
            if watchdog_exit_code != 0:
                raise RuntimeError(
                    f"Backend --parent-pid watchdog exited with non-zero code {watchdog_exit_code}"
                )
        finally:
            if sleeper.poll() is None:
                sleeper.kill()
                sleeper.wait(timeout=5)
            if backend_proc.poll() is None:
                backend_proc.kill()
                backend_proc.wait(timeout=5)

    return {
        "package_versions": package_versions,
        "ephemeral_port_tested": port,
        "origin_guard_verified": True,
        "parent_pid_watchdog_verified": True,
    }


def build_backend(
    *,
    build_root: Path = DEFAULT_BUILD_ROOT,
    conda_python: Path | None = None,
    wheel_cache: Path | None = None,
    verify_only: bool = False,
) -> dict[str, Any]:
    resolved_conda_py = discover_locked_conda_python(conda_python)
    verify_locked_conda_runtime(resolved_conda_py)

    dist_root = build_root / "dist-slim"
    work_root = build_root / "pyinstaller-slim"

    if not verify_only:
        default_tmp_wheels = Path("/tmp/linux-pkg-wheels")
        effective_wheels = wheel_cache
        if effective_wheels is None and default_tmp_wheels.is_dir():
            effective_wheels = default_tmp_wheels

        site_dir = ensure_isolated_packaging_site(
            resolved_conda_py, build_root / "packaging-site", effective_wheels
        )
        for target in (dist_root, work_root):
            if target.exists():
                import shutil

                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)

        pyi_env = os.environ.copy()
        existing_pypath = pyi_env.get("PYTHONPATH", "")
        pyi_env["PYTHONPATH"] = (
            f"{site_dir}{os.pathsep}{existing_pypath}" if existing_pypath else str(site_dir)
        )

        subprocess.run(
            [
                str(resolved_conda_py),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--distpath",
                str(dist_root),
                "--workpath",
                str(work_root),
                str(SPEC_PATH),
            ],
            cwd=ROOT,
            env=pyi_env,
            check=True,
        )

    pyz_toc = work_root / "ankora_backend_linux/PYZ-00.toc"
    frozen_modules = verify_frozen_module_parity(pyz_toc)
    bundle_dir = dist_root / "ankora-backend"
    audit = audit_bundle_contents(bundle_dir)
    smoke = smoke_frozen_backend(bundle_dir)

    # Re-verify that the locked ankora-dev Conda environment remained untouched.
    verify_locked_conda_runtime(resolved_conda_py)

    manifest = {
        "schema_version": 1,
        "platform": "linux-x86_64",
        "spec": SPEC_PATH.relative_to(ROOT).as_posix(),
        "frozen_ankora_module_count": len(frozen_modules),
        "bundle": audit,
        "smoke": smoke,
    }
    manifest_path = dist_root / "backend-build-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--conda-python", type=Path)
    parser.add_argument("--wheel-cache", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = build_backend(
        build_root=args.build_root.resolve(),
        conda_python=args.conda_python,
        wheel_cache=args.wheel_cache,
        verify_only=args.verify_only,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
