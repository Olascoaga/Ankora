"""End-to-end clean-room offline Linux package smoke & bare-metal workstation attestation (ADR-029 D4/D6).

Uses only the Python 3.12 standard library so it executes unmodified on a fresh
Ubuntu 24.04 LTS / Linux Mint / Debian workstation with `/usr/bin/python3` and
zero Conda or pip dependencies.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_DIR = REPO_ROOT / "build" / "linux-runtime" / "release-0.1.0"
DEFAULT_EVIDENCE_PARENT = REPO_ROOT / "build" / "linux-runtime"

CORE_TOOL_NAMES = (
    "pdbfixer",
    "pdb2pqr",
    "propka",
    "meeko",
    "meeko_ligand",
    "p2rank",
    "vina",
    "autogrid4",
    "autodock4",
    "autodock_gpu",
)

FORBIDDEN_CORE_PREFIXES = (
    "gnina",
    "libcuda.so",
    "libnvidia-ml.so",
    "libnvidia-ptxjitcompiler.so",
    "libcudnn",
    "libcublas",
)

EXPECTED_GNINA_SHA256 = "3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172"
EXPECTED_TEST_PDB_SHA256 = "e1fd07976c0e1ed7aeaa2a2733e1334ad9051744bf2fc196812bdf922f08a981"
EXPECTED_ETHANOL_SMI_SHA256 = "e8aad0bdae1b0bb65afcb6a728823dd0d028c9988d3a34299ce9f3d09c95f92d"

SMOKE_BOX = {
    "center_x": 0.024,
    "center_y": 0.405,
    "center_z": 1.075,
    "size_x": 20.0,
    "size_y": 20.0,
    "size_z": 20.0,
}

SMOKE_RECEPTOR_PLAN = {
    "selected_chains": ["A"],
    "water_action": "remove",
    "component_decisions": [],
    "issue_decisions": [],
    "relaxation": {"enabled": False},
    "protonation": {
        "enabled": True,
        "ph": 7.4,
        "force_field": "AMBER",
        "authorized_terminal_heavy_atom_additions": [],
        "overrides": [],
    },
    "generate_pdbqt": True,
    "inspection_method": "templates_v1",
}

_LOOPBACK_HEX = {
    "/proc/net/tcp": {
        "".join(
            f"{w:08X}" for w in struct.unpack("=I", socket.inet_pton(socket.AF_INET, "127.0.0.1"))
        ),
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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_gnina_pack_sha256_and_parts(pack_path: Path) -> tuple[str, list[dict[str, Any]]]:
    match = re.match(r"^(?P<stem>.+)\.part(?P<idx>\d{2,4})$", pack_path.name)
    if match is None:
        return sha256_file(pack_path), []
    stem = match.group("stem")
    width = len(match.group("idx"))
    parts_meta: list[dict[str, Any]] = []
    stream_digest = hashlib.sha256()
    index = 1
    while True:
        part = pack_path.parent / f"{stem}.part{index:0{width}d}"
        if not part.is_file():
            break
        part_digest = hashlib.sha256()
        size = 0
        with part.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                stream_digest.update(chunk)
                part_digest.update(chunk)
                size += len(chunk)
        parts_meta.append(
            {"filename": part.name, "size_bytes": size, "sha256": part_digest.hexdigest()}
        )
        index += 1
    if len(parts_meta) < 2:
        raise FileNotFoundError(
            f"Incomplete multi-part GNINA pack next to {pack_path}; expected at least .part01 and .part02."
        )
    return stream_digest.hexdigest(), parts_meta


def is_wsl_kernel() -> bool:
    parts = [platform.release().lower()]
    proc_version = Path("/proc/version")
    if proc_version.is_file():
        parts.append(proc_version.read_text(encoding="utf-8", errors="replace").lower())
    joined = " ".join(parts)
    return "microsoft" in joined or "wsl" in joined


def port_accepting(port: int = 8765) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def verify_loopback_listener(port: int = 8765) -> list[str]:
    listeners: list[str] = []
    for table, allowed_addrs in _LOOPBACK_HEX.items():
        table_path = Path(table)
        if not table_path.is_file():
            continue
        for row in table_path.read_text(encoding="ascii").splitlines()[1:]:
            fields = row.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            addr_hex, port_hex = fields[1].rsplit(":", 1)
            if int(port_hex, 16) != port:
                continue
            listeners.append(f"{table}:{addr_hex}")
            if addr_hex not in allowed_addrs:
                raise RuntimeError(
                    f"Port {port} is bound to non-loopback address {addr_hex} in {table}"
                )
    if not listeners:
        raise RuntimeError(f"Expected loopback listener on TCP port {port}, found none")
    return listeners


def build_clean_user_environment(
    *,
    clean_home: Path,
    allow_wsl_driver_path: bool,
) -> dict[str, str]:
    clean_home.mkdir(parents=True, exist_ok=True)
    xdg_data = clean_home / ".local" / "share"
    xdg_config = clean_home / ".config"
    xdg_cache = clean_home / ".cache"
    for directory in (xdg_data, xdg_config, xdg_cache):
        directory.mkdir(parents=True, exist_ok=True)

    path_entries = ["/usr/bin", "/bin"]
    if allow_wsl_driver_path and Path("/usr/lib/wsl/lib/nvidia-smi").is_file():
        path_entries.append("/usr/lib/wsl/lib")

    env: dict[str, str] = {
        "PATH": ":".join(path_entries),
        "HOME": str(clean_home),
        "XDG_DATA_HOME": str(xdg_data),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_CACHE_HOME": str(xdg_cache),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    for display_var in (
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "XAUTHORITY",
    ):
        val = os.environ.get(display_var)
        if val:
            env[display_var] = val
    return env


class LocalApiClient:
    """Zero-dependency HTTP client bound to 127.0.0.1 with Tauri Origin headers."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> tuple[int, bytes]:
        req_headers = {
            "Origin": "http://tauri.localhost",
            "Connection": "close",
        }
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=req_headers,
            method=method,
        )
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expected_status: int = 200,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        body: bytes | None = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, raw = self.request_bytes(
            method, path, body=body, headers=headers, timeout=timeout
        )
        if status != expected_status:
            text = raw.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{method} {path} returned HTTP {status} (expected {expected_status}): {text}"
            )
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError(f"{method} {path} did not return a JSON object")
        return parsed

    def upload_file(
        self,
        path: str,
        *,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        expected_status: int = 201,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        boundary = f"----AnkoraSmokeBoundary{uuid.uuid4().hex}"
        buf = io.BytesIO()
        buf.write(f"--{boundary}\r\n".encode("ascii"))
        buf.write(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        buf.write(file_bytes)
        buf.write(f"\r\n--{boundary}--\r\n".encode("ascii"))
        status, raw = self.request_bytes(
            "POST",
            path,
            body=buf.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=timeout,
        )
        if status != expected_status:
            text = raw.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Multipart POST {path} returned HTTP {status} (expected {expected_status}): {text}"
            )
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError(f"Multipart POST {path} did not return a JSON object")
        return parsed


def wait_for_packaged_desktop_ready(
    proc: subprocess.Popen[bytes],
    client: LocalApiClient,
    *,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Packaged desktop exited prematurely with code {proc.returncode} before healthy"
            )
        with contextlib.suppress(OSError, urllib.error.URLError, RuntimeError):
            health = client.request_json("GET", "/api/v1/health", timeout=1.5)
            if health.get("status") == "ok":
                return client.request_json("GET", "/api/v1/system", timeout=5.0)
        time.sleep(0.25)
    raise TimeoutError("Packaged desktop did not expose a healthy backend on 127.0.0.1:8765")


def terminate_desktop_and_verify_port_closed(
    proc: subprocess.Popen[bytes],
    *,
    port: int = 8765,
    timeout_seconds: float = 15.0,
) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as err:
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError("Packaged desktop did not exit cleanly on SIGTERM") from err

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not port_accepting(port):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Bundled backend left TCP port {port} open after desktop shutdown")


def audit_core_app_tree(app_dir: Path) -> dict[str, Any]:
    desktop_bin = app_dir / "ankora-desktop"
    backend_bin = app_dir / "backend" / "ankora-backend"
    legal_dir = app_dir / "legal"
    tools_dir = app_dir / "backend" / "tools"
    for required in (
        desktop_bin,
        backend_bin,
        legal_dir / "COMPLETE_LEGAL_MANIFEST.json",
        legal_dir / "INSTALLATION_TERMS.txt",
        legal_dir / "SOURCE_AVAILABILITY.txt",
        legal_dir / "THIRD_PARTY_NOTICES.txt",
        legal_dir / "THIRD_PARTY_INVENTORY.json",
        tools_dir / "payload.json",
    ):
        if not required.is_file():
            raise FileNotFoundError(f"Packaged application tree is missing {required}")

    legal_manifest = json.loads(
        (legal_dir / "COMPLETE_LEGAL_MANIFEST.json").read_text(encoding="utf-8")
    )
    for rel_name, expected_sha in legal_manifest["files"].items():
        fpath = legal_dir / rel_name
        if not fpath.is_file() or sha256_file(fpath) != expected_sha:
            raise ValueError(f"Legal file integrity mismatch in packaged app: {rel_name}")

    file_count = 0
    symlink_count = 0
    app_root = app_dir.resolve(strict=True)
    for root, dirs, files in os.walk(app_root, followlinks=False):
        root_p = Path(root)
        for name in [*dirs, *files]:
            item = root_p / name
            if item.is_symlink():
                symlink_count += 1
                target = os.readlink(item)
                if os.path.isabs(target):
                    raise ValueError(f"Forbidden absolute symlink in packaged tree: {item}")
                resolved = (item.parent / target).resolve(strict=True)
                if not resolved.is_relative_to(app_root):
                    raise ValueError(f"Escaping symlink in packaged tree: {item}")
            elif item.is_file():
                file_count += 1
                lower = item.name.lower()
                if any(lower.startswith(prefix) for prefix in FORBIDDEN_CORE_PREFIXES):
                    raise ValueError(f"Forbidden driver or GNINA file in Core bundle: {item}")

    return {
        "desktop_sha256": sha256_file(desktop_bin),
        "backend_sha256": sha256_file(backend_bin),
        "regular_files": file_count,
        "intra_tree_symlinks": symlink_count,
    }


def extract_portable_tar_zst(archive_path: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    tar_exe = shutil.which("tar") or "/bin/tar"
    zstd_candidates = [
        Path(sys.executable).resolve().parent / "zstd",
        Path("/usr/bin/zstd"),
    ]
    zstd_bin = next((str(p) for p in zstd_candidates if p.is_file()), shutil.which("zstd"))
    if zstd_bin is None:
        raise FileNotFoundError("zstd executable required to extract portable .tar.zst in smoke")
    subprocess.run(
        [tar_exe, f"--use-compress-program={zstd_bin}", "-xf", str(archive_path), "-C", str(destination_dir)],
        check=True,
    )
    entries = [p for p in destination_dir.iterdir() if p.is_dir()]
    if len(entries) != 1:
        raise RuntimeError(f"Expected single top-level directory in {archive_path}, got {entries}")
    return entries[0]


def verify_release_directory(release_dir: Path) -> dict[str, Any]:
    sums_file = release_dir / "SHA256SUMS.txt"
    manifest_file = release_dir / "linux-release-manifest.json"
    if not sums_file.is_file() or not manifest_file.is_file():
        raise FileNotFoundError(f"Release directory missing SHA256SUMS.txt or manifest: {release_dir}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    sums_map: dict[str, str] = {}
    for line in sums_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, filename = line.strip().split(None, 1)
        sums_map[filename.strip()] = digest.strip()

    verified: dict[str, dict[str, Any]] = {}
    for item in manifest["artifacts"]:
        fname = item["filename"]
        fpath = release_dir / fname
        if not fpath.is_file():
            raise FileNotFoundError(f"Missing release artifact: {fpath}")
        actual_sha = sha256_file(fpath)
        actual_size = fpath.stat().st_size
        if actual_sha != item["sha256"] or actual_sha != sums_map.get(fname):
            raise ValueError(f"SHA-256 mismatch for {fname}: {actual_sha}")
        if actual_size != item["size_bytes"]:
            raise ValueError(f"Byte size mismatch for {fname}: {actual_size}")
        verified[fname] = {
            "path": str(fpath),
            "size_bytes": actual_size,
            "sha256": actual_sha,
        }

    companion_zip = next(
        release_dir / name for name in verified if name.endswith("_linux-sources-companion.zip")
    )
    with zipfile.ZipFile(companion_zip) as zf:
        names = set(zf.namelist())
        if "SCIENTIFIC_SOURCE_COMPANION.json" not in names:
            raise ValueError("Sources companion zip missing SCIENTIFIC_SOURCE_COMPANION.json")
        if not any(n.endswith("-gnina-source.tar.gz") for n in names):
            raise ValueError("Sources companion zip missing GNINA GPL source archive")

    return {"manifest": manifest, "verified_artifacts": verified}


def run_native_scientific_matrix(
    *,
    app_dir: Path,
    clean_env: dict[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    backend_bin = app_dir / "backend" / "ankora-backend"
    fixtures_root = app_dir / "backend" / "_internal" / "smoke-fixtures"
    receptor_fixture = app_dir / "backend" / "_internal" / "pdbfixer" / "tests" / "data" / "1BHL.pdb"
    if not fixtures_root.is_dir() or not receptor_fixture.is_file():
        raise FileNotFoundError("Bundled smoke fixtures missing inside packaged _internal/")

    start_t = time.monotonic()
    proc = subprocess.run(
        [
            str(backend_bin),
            "--worker",
            "native-smoke",
            "--root",
            str(fixtures_root),
            "--receptor-fixture",
            str(receptor_fixture),
            "--output",
            str(output_dir),
        ],
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    wall_seconds = round(time.monotonic() - start_t, 3)
    manifest_path = output_dir / "manifest.json"
    if proc.returncode != 0 or not manifest_path.is_file():
        raise RuntimeError(
            f"Bundled native-smoke failed (exit={proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    smoke_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if smoke_manifest.get("status") != "passed":
        raise RuntimeError(f"Native tool smoke did not pass all 10 adapters: {smoke_manifest}")
    adapters = {
        row["adapter_id"]: {
            "status": row["status"],
            "version": row.get("version"),
            "executable_sha256": row.get("executable_sha256"),
            "details": row.get("details"),
        }
        for row in smoke_manifest["results"]
    }
    if len(adapters) != 10:
        raise RuntimeError(f"Expected 10 adapters in native-smoke manifest, got {len(adapters)}")
    return {
        "wall_seconds": wall_seconds,
        "manifest_sha256": sha256_file(manifest_path),
        "adapters": adapters,
    }


def _poll_job(
    client: LocalApiClient,
    poll_path: str,
    cancel_path: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while (now := time.monotonic()) < deadline:
        req_timeout = min(60.0, max(15.0, deadline - now))
        try:
            job = client.request_json("GET", poll_path, timeout=req_timeout)
        except TimeoutError:
            if time.monotonic() >= deadline:
                break
            continue
        if job.get("status") in {"completed", "failed", "canceled"}:
            return job
        time.sleep(0.25)
    with contextlib.suppress(Exception):
        client.request_json("POST", cancel_path, expected_status=200, timeout=10.0)
    raise TimeoutError(f"Docking job {poll_path} exceeded {timeout_seconds}s")


def run_packaged_gnina_pack_and_docking_smoke(
    *,
    client: LocalApiClient,
    app_dir: Path,
    gnina_pack_path: Path,
) -> dict[str, Any]:
    # 1. Import 2.55 GiB offline GNINA pack via the packaged localhost endpoint.
    import_t0 = time.monotonic()
    pack_resp = client.request_json(
        "POST",
        "/api/v1/tools/gnina-pack/import",
        payload={"archive_path": str(gnina_pack_path.resolve())},
        expected_status=200,
        timeout=300.0,
    )
    import_seconds = round(time.monotonic() - import_t0, 3)
    if (
        not pack_resp.get("installed")
        or pack_resp.get("gnina_version") != "1.3.3"
        or pack_resp.get("executable_sha256") != EXPECTED_GNINA_SHA256
        or pack_resp.get("shared_library_count") != 17
    ):
        raise RuntimeError(f"Unexpected GNINA pack import response: {pack_resp}")

    if hasattr(os, "sync"):
        os.sync()

    tools_after = client.request_json("GET", "/api/v1/tools", timeout=30.0)
    if not tools_after.get("gnina", {}).get("available"):
        raise RuntimeError(f"GNINA did not become available immediately after pack import: {tools_after.get('gnina')}")

    # 2. Import bundled clean villin structure + synthetic ethanol SMILES and prepare PDBQTs.
    test_pdb = app_dir / "backend" / "_internal" / "pdbfixer" / "tests" / "data" / "test.pdb"
    ethanol_smi = (
        app_dir
        / "backend"
        / "_internal"
        / "smoke-fixtures"
        / "backend"
        / "tests"
        / "fixtures"
        / "synthetic_ethanol.smi"
    )
    pdb_bytes = test_pdb.read_bytes()
    smi_bytes = ethanol_smi.read_bytes()
    if hashlib.sha256(pdb_bytes).hexdigest() != EXPECTED_TEST_PDB_SHA256:
        raise ValueError("Bundled test.pdb SHA-256 mismatch")
    if hashlib.sha256(smi_bytes).hexdigest() != EXPECTED_ETHANOL_SMI_SHA256:
        raise ValueError("Bundled synthetic_ethanol.smi SHA-256 mismatch")

    struct_res = client.upload_file(
        "/api/v1/structures/import",
        filename="test.pdb",
        content_type="chemical/x-pdb",
        file_bytes=pdb_bytes,
    )
    structure_id = struct_res["artifact"]["artifact_id"]

    receptor_res = client.request_json(
        "POST",
        f"/api/v1/structures/{structure_id}/receptors",
        payload=SMOKE_RECEPTOR_PLAN,
        expected_status=201,
        timeout=120.0,
    )
    if receptor_res.get("status") != "docking_ready":
        raise RuntimeError(f"Receptor preparation did not reach docking_ready: {receptor_res}")
    receptor_id = receptor_res["receptor_id"]

    site_res = client.request_json(
        "POST",
        f"/api/v1/receptors/{receptor_id}/binding-sites",
        payload={"source": "manual", "manual_box": SMOKE_BOX},
        expected_status=201,
    )
    binding_site_id = site_res["binding_site_id"]

    lig_res = client.upload_file(
        "/api/v1/ligands/import",
        filename="synthetic_ethanol.smi",
        content_type="text/plain",
        file_bytes=smi_bytes,
    )
    ligand_id = lig_res["artifact"]["ligand_id"]

    conf_res = client.request_json(
        "POST",
        f"/api/v1/ligands/{ligand_id}/conformers/generate",
        payload={
            "force_field": "MMFF94s",
            "max_iterations": 500,
            "random_seed": 20261029,
            "acknowledge_current_chemical_state": True,
        },
        expected_status=201,
    )
    conformer_id = conf_res["artifact"]["conformer_id"]

    pdbqt_res = client.request_json(
        "POST",
        f"/api/v1/ligands/{ligand_id}/conformers/{conformer_id}/pdbqt",
        payload={"charge_model": "gasteiger"},
        expected_status=201,
    )
    preparation_id = pdbqt_res["artifact"]["preparation_id"]

    # 3. Run bundled Vina 1.2.7 job.
    vina_start = client.request_json(
        "POST",
        "/api/v1/docking/vina/jobs",
        payload={
            "receptor_id": receptor_id,
            "binding_site_id": binding_site_id,
            "ligand_id": ligand_id,
            "ligand_preparation_id": preparation_id,
            "parameters": {
                "sampling_protocol": "custom",
                "cpu_threads": 2,
                "seed": 20261029,
                "exhaustiveness": 2,
                "num_modes": 3,
                "min_rmsd_angstrom": 1.0,
                "energy_range_kcal_mol": 3.0,
                "timeout_minutes": 1,
            },
            "acknowledge_inputs_and_scoring": True,
        },
        expected_status=202,
    )
    vina_job = _poll_job(
        client,
        f"/api/v1/docking/jobs/{vina_start['job_id']}",
        f"/api/v1/docking/jobs/{vina_start['job_id']}/cancel",
        timeout_seconds=90.0,
    )
    if vina_job.get("status") != "completed" or not vina_job.get("poses"):
        raise RuntimeError(f"Bundled Vina job failed: {vina_job}")

    # 4. Run imported GNINA 1.3.3 jobs: CPU rescore, CUDA rescore, and CUDA refinement.
    gnina_runs: dict[str, Any] = {}
    gnina_specs = (
        (
            "cpu_rescore",
            {
                "compute": "cpu",
                "cpu_threads": 2,
                "seed": 20261029,
                "exhaustiveness": 2,
                "num_modes": 2,
                "cnn_scoring": "rescore",
                "cnn_model": "dense_1_3",
                "timeout_minutes": 3,
            },
            False,
        ),
        (
            "cuda_rescore",
            {
                "compute": "cuda",
                "device_index": 0,
                "cpu_threads": 2,
                "seed": 20261029,
                "exhaustiveness": 16,
                "num_modes": 3,
                "cnn_scoring": "rescore",
                "cnn_model": "dense_1_3",
                "timeout_minutes": 3,
            },
            True,
        ),
        (
            "cuda_refinement_ensemble",
            {
                "compute": "cuda",
                "device_index": 0,
                "cpu_threads": 2,
                "seed": 20261029,
                "exhaustiveness": 4,
                "num_modes": 3,
                "cnn_scoring": "refinement",
                "cnn_model": "default_1_3_ensemble",
                "timeout_minutes": 10,
            },
            True,
        ),
    )

    for run_label, params, require_gpu in gnina_specs:
        t0 = time.monotonic()
        admitted = client.request_json(
            "POST",
            "/api/v1/docking/gnina/jobs",
            payload={
                "receptor_id": receptor_id,
                "binding_site_id": binding_site_id,
                "ligand_id": ligand_id,
                "ligand_preparation_id": preparation_id,
                "parameters": params,
                "acknowledge_inputs_and_scoring": True,
            },
            expected_status=202,
        )
        jid = admitted["job_id"]
        finished = _poll_job(
            client,
            f"/api/v1/docking/gnina/jobs/{jid}",
            f"/api/v1/docking/gnina/jobs/{jid}/cancel",
            timeout_seconds=300.0,
        )
        elapsed = round(time.monotonic() - t0, 3)
        if finished.get("status") != "completed" or not finished.get("poses"):
            raise RuntimeError(f"GNINA {run_label} job failed: {finished}")
        execution = finished.get("execution") or {}
        if require_gpu:
            req_uuid = execution.get("requested_gpu_uuid")
            if not req_uuid:
                raise RuntimeError(f"GNINA {run_label} missing requested_gpu_uuid: {execution}")
            if execution.get("gpu_process_observed") and execution.get("observed_gpu_uuid") != req_uuid:
                raise RuntimeError(f"GNINA {run_label} GPU UUID mismatch: {execution}")
        top_pose = finished["poses"][0]
        pose_art = top_pose["artifact"]
        dl_status, dl_bytes = client.request_bytes(
            "GET",
            f"/api/v1/docking/gnina/jobs/{jid}/poses/{pose_art['artifact_id']}/content",
        )
        if dl_status != 200 or hashlib.sha256(dl_bytes).hexdigest() != pose_art["sha256"]:
            raise RuntimeError(f"GNINA {run_label} pose download SHA-256 mismatch")

        gnina_runs[run_label] = {
            "job_id": jid,
            "wall_seconds": elapsed,
            "pose_count": len(finished["poses"]),
            "top_cnn_score": top_pose["cnn_score"],
            "top_cnn_affinity": top_pose["cnn_affinity"],
            "top_cnn_vs": top_pose["cnn_vs"],
            "cnn_model_identity": finished.get("cnn_model_identity"),
            "gpu_process_observed": execution.get("gpu_process_observed"),
            "requested_gpu_uuid": execution.get("requested_gpu_uuid"),
            "observed_gpu_uuid": execution.get("observed_gpu_uuid"),
        }

    if not gnina_runs["cuda_refinement_ensemble"]["gpu_process_observed"]:
        raise RuntimeError(
            "Expected live NVIDIA GPU process observation during GNINA CUDA refinement smoke"
        )

    return {
        "pack_import_wall_seconds": import_seconds,
        "pack_status": pack_resp,
        "vina_job": {
            "job_id": vina_job["job_id"],
            "pose_count": len(vina_job["poses"]),
            "top_affinity_kcal_mol": vina_job["poses"][0]["affinity_kcal_mol"],
        },
        "gnina_jobs": gnina_runs,
    }


def run_wsl_or_cleanroom_package_smoke(
    *,
    release_dir: Path,
    evidence_dir: Path,
    keep_temp: bool = False,
) -> dict[str, Any]:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("DISPLAY or WAYLAND_DISPLAY is required to cold-start ankora-desktop GUI")
    if port_accepting(8765):
        raise RuntimeError("TCP port 127.0.0.1:8765 is already occupied before smoke test")

    evidence_dir.mkdir(parents=True, exist_ok=False)
    work_root = evidence_dir / "work"
    work_root.mkdir()

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "mode": "clean_room_package_smoke",
        "started_at": datetime.now(UTC).isoformat(),
        "host_kernel": platform.platform(),
        "is_wsl": is_wsl_kernel(),
        "status": "failed",
    }
    desktop_proc: subprocess.Popen[bytes] | None = None
    log_handle: Any = None
    try:
        # Step 1: Release directory & archive extraction audit
        rel_info = verify_release_directory(release_dir)
        evidence["release_artifacts"] = rel_info["verified_artifacts"]

        deb_path = next(
            Path(v["path"]) for k, v in rel_info["verified_artifacts"].items() if k.endswith(".deb")
        )
        portable_archive = next(
            Path(v["path"])
            for k, v in rel_info["verified_artifacts"].items()
            if k.endswith("_linux_x86_64.tar.zst")
        )
        gnina_pack = next(
            (
                Path(v["path"])
                for k, v in rel_info["verified_artifacts"].items()
                if k.endswith("_gnina-cuda12-pack.tar.zst.part01")
            ),
            None,
        ) or next(
            Path(v["path"])
            for k, v in rel_info["verified_artifacts"].items()
            if k.endswith("_gnina-cuda12-pack.tar.zst")
        )

        deb_info = subprocess.run(
            ["dpkg-deb", "--info", str(deb_path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for expected_ctrl in ("Package: ankora", "Architecture: amd64", "libwebkit2gtk-4.1-0"):
            if expected_ctrl not in deb_info:
                raise ValueError(f".deb control metadata missing {expected_ctrl!r}")

        extracted_deb = work_root / "extracted-deb"
        subprocess.run(["dpkg-deb", "--extract", str(deb_path), str(extracted_deb)], check=True)
        for must_exist in (
            extracted_deb / "usr" / "bin" / "ankora",
            extracted_deb / "usr" / "share" / "applications" / "ankora.desktop",
            extracted_deb / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "ankora.png",
            extracted_deb / "usr" / "share" / "doc" / "ankora" / "copyright",
        ):
            if not must_exist.is_file():
                raise FileNotFoundError(f".deb payload missing {must_exist}")

        deb_app_dir = extracted_deb / "usr" / "lib" / "ankora"
        evidence["deb_bundle_audit"] = audit_core_app_tree(deb_app_dir)

        portable_parent = work_root / "extracted-portable"
        portable_app_dir = extract_portable_tar_zst(portable_archive, portable_parent)
        if not (portable_app_dir / "ankora").is_file():
            raise FileNotFoundError("Portable archive missing ./ankora launcher")
        evidence["portable_bundle_audit"] = audit_core_app_tree(portable_app_dir)

        # Step 2: Packaged desktop cold-start under sanitized PATH & isolated HOME
        clean_home = work_root / "clean-user-home"
        clean_env = build_clean_user_environment(
            clean_home=clean_home,
            allow_wsl_driver_path=evidence["is_wsl"],
        )
        evidence["sanitized_path"] = clean_env["PATH"]

        api = LocalApiClient()
        deb_log_path = evidence_dir / "deb-desktop.log"
        log_handle = deb_log_path.open("wb")
        desktop_proc = subprocess.Popen(
            [str(deb_app_dir / "ankora-desktop")],
            cwd=clean_home,
            env=clean_env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        system_info = wait_for_packaged_desktop_ready(desktop_proc, api)
        if (
            system_info.get("app_mode") != "packaged"
            or system_info.get("python_environment") != "Bundled Python 3.12"
        ):
            raise RuntimeError(f"Unexpected packaged system identity: {system_info}")
        loopback_listeners = verify_loopback_listener(8765)
        tools_before = api.request_json("GET", "/api/v1/tools", timeout=30.0)
        for core_tool in CORE_TOOL_NAMES:
            if not tools_before.get(core_tool, {}).get("available"):
                raise RuntimeError(
                    f"Core bundled tool {core_tool!r} unavailable on cold start: {tools_before.get(core_tool)}"
                )
        if tools_before.get("gnina", {}).get("available"):
            raise RuntimeError("GNINA must be unavailable before offline pack import")
        pack_before = api.request_json("GET", "/api/v1/tools/gnina-pack/status", timeout=10.0)
        if pack_before.get("installed"):
            raise RuntimeError(f"Expected gnina-pack installed=False before import: {pack_before}")

        evidence["cold_start_deb"] = {
            "system": system_info,
            "loopback_listeners": loopback_listeners,
            "core_tools_available": {name: tools_before[name]["version"] for name in CORE_TOOL_NAMES},
            "gnina_available_before_import": False,
        }

        # Step 3: 10/10 Core scientific smoke matrix via bundled ankora-backend --worker native-smoke
        evidence["native_scientific_matrix"] = run_native_scientific_matrix(
            app_dir=deb_app_dir,
            clean_env=clean_env,
            output_dir=evidence_dir / "native-tool-smoke",
        )

        # Step 4: 1-click offline GNINA pack import + live Vina & GNINA CPU/CUDA rescore & refinement
        evidence["gnina_pack_and_docking"] = run_packaged_gnina_pack_and_docking_smoke(
            client=api,
            app_dir=deb_app_dir,
            gnina_pack_path=gnina_pack,
        )

        # Step 5: Graceful SIGTERM shutdown, .deb uninstall simulation, & portable .tar.zst persistence
        terminate_desktop_and_verify_port_closed(desktop_proc)
        desktop_proc = None
        log_handle.close()
        log_handle = None

        shutil.rmtree(extracted_deb)

        portable_log_path = evidence_dir / "portable-desktop.log"
        log_handle = portable_log_path.open("wb")
        desktop_proc = subprocess.Popen(
            [str(portable_app_dir / "ankora")],
            cwd=portable_app_dir,
            env=clean_env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        portable_sys = wait_for_packaged_desktop_ready(desktop_proc, api)
        tools_portable = api.request_json("GET", "/api/v1/tools", timeout=30.0)
        for tool_name in (*CORE_TOOL_NAMES, "gnina"):
            if not tools_portable.get(tool_name, {}).get("available"):
                raise RuntimeError(
                    f"Tool {tool_name!r} unavailable in portable launch after .deb removal: "
                    f"{tools_portable.get(tool_name)}"
                )
        campaigns = api.request_json(
            "GET", "/api/v1/results/campaigns?scoring_family=gnina", timeout=15.0
        )
        persisted_gnina_count = len(campaigns.get("entries", []))
        if persisted_gnina_count < 3:
            raise RuntimeError(
                f"Expected >= 3 persisted GNINA jobs in user data after .deb removal, got {persisted_gnina_count}"
            )
        terminate_desktop_and_verify_port_closed(desktop_proc)
        desktop_proc = None
        log_handle.close()
        log_handle = None

        evidence["portable_persistence_parity"] = {
            "app_mode": portable_sys.get("app_mode"),
            "gnina_persisted_available": True,
            "gnina_version": tools_portable["gnina"]["version"],
            "persisted_gnina_campaign_entries": persisted_gnina_count,
        }
        evidence["completed_at"] = datetime.now(UTC).isoformat()
        evidence["status"] = "passed"
    except Exception as err:
        evidence["error"] = {
            "type": type(err).__name__,
            "message": str(err),
            "desktop_returncode": desktop_proc.poll() if desktop_proc is not None else None,
        }
        raise
    finally:
        for log_name in ("backend.stdout.log", "backend.stderr.log"):
            src_log = (
                work_root
                / "clean-user-home"
                / ".local"
                / "share"
                / "science.ankora.workbench"
                / "logs"
                / log_name
            )
            if src_log.is_file():
                shutil.copy2(src_log, evidence_dir / log_name)
        if desktop_proc is not None and desktop_proc.poll() is None:
            with contextlib.suppress(Exception):
                terminate_desktop_and_verify_port_closed(desktop_proc, timeout_seconds=5.0)
            if desktop_proc.poll() is None:
                desktop_proc.kill()
                desktop_proc.wait(timeout=5)
        if log_handle is not None:
            log_handle.close()
        if not keep_temp and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)
        out_json = evidence_dir / "package-smoke-evidence.json"
        out_json.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    evidence["evidence_sha256"] = sha256_file(evidence_dir / "package-smoke-evidence.json")
    return evidence


def run_native_workstation_attestation(
    *,
    gnina_pack_path: Path,
    evidence_dir: Path,
    keep_temp: bool = False,
) -> dict[str, Any]:
    """Bare-metal Linux workstation gate (ADR-029 D6) against system-installed `/usr/bin/ankora`."""
    if is_wsl_kernel():
        raise RuntimeError(
            "Refusing --native-workstation-attestation on a WSL kernel; run this gate on a "
            "bare-metal Linux workstation."
        )
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("DISPLAY or WAYLAND_DISPLAY is required on the native Linux desktop")
    if port_accepting(8765):
        raise RuntimeError("Close any running Ankora instance before running native attestation")
    if not gnina_pack_path.is_file():
        raise FileNotFoundError(f"Offline GNINA pack not found: {gnina_pack_path}")

    dpkg_status = subprocess.run(
        ["dpkg", "-s", "ankora"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if "Status: install ok installed" not in dpkg_status:
        raise RuntimeError("Package `ankora` is not installed via dpkg/apt (`sudo apt install ./Ankora_0.1.0_amd64.deb`)")

    installed_app_dir = Path("/usr/lib/ankora")
    launcher = Path("/usr/bin/ankora")
    if not launcher.is_file() or not (installed_app_dir / "ankora-desktop").is_file():
        raise FileNotFoundError("Installed /usr/bin/ankora or /usr/lib/ankora/ankora-desktop missing")

    evidence_dir.mkdir(parents=True, exist_ok=False)
    work_root = evidence_dir / "work"
    work_root.mkdir()
    clean_home = work_root / "clean-attestation-home"
    clean_env = build_clean_user_environment(
        clean_home=clean_home,
        allow_wsl_driver_path=False,
    )

    pack_stream_sha256, pack_parts_meta = resolve_gnina_pack_sha256_and_parts(gnina_pack_path)
    attestation: dict[str, Any] = {
        "schema_version": 1,
        "mode": "native_linux_workstation_attestation",
        "started_at": datetime.now(UTC).isoformat(),
        "host_kernel": platform.platform(),
        "is_wsl": False,
        "gnina_pack_sha256": pack_stream_sha256,
        **({"gnina_pack_parts": pack_parts_meta} if pack_parts_meta else {}),
        "status": "failed",
    }
    desktop_proc: subprocess.Popen[bytes] | None = None
    log_handle: Any = None
    try:
        attestation["installed_bundle_audit"] = audit_core_app_tree(installed_app_dir)
        nvidia_smi_out = subprocess.run(
            ["/usr/bin/nvidia-smi", "--query-gpu=name,driver_version,uuid,memory.total", "--format=csv,noheader"],
            env=clean_env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        attestation["gpu_driver_identity"] = nvidia_smi_out

        api = LocalApiClient()
        log_handle = (evidence_dir / "native-desktop.log").open("wb")
        desktop_proc = subprocess.Popen(
            [str(launcher)],
            cwd=clean_home,
            env=clean_env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        system_info = wait_for_packaged_desktop_ready(desktop_proc, api)
        loopback_listeners = verify_loopback_listener(8765)
        tools_before = api.request_json("GET", "/api/v1/tools", timeout=30.0)
        for core_tool in CORE_TOOL_NAMES:
            if not tools_before.get(core_tool, {}).get("available"):
                raise RuntimeError(f"Core bundled tool {core_tool!r} unavailable on native workstation")
        if tools_before.get("gnina", {}).get("available"):
            raise RuntimeError("Expected gnina unavailable in clean attestation home before import")

        attestation["cold_start"] = {
            "system": system_info,
            "loopback_listeners": loopback_listeners,
            "core_tools_available": {name: tools_before[name]["version"] for name in CORE_TOOL_NAMES},
        }
        attestation["native_scientific_matrix"] = run_native_scientific_matrix(
            app_dir=installed_app_dir,
            clean_env=clean_env,
            output_dir=evidence_dir / "native-tool-smoke",
        )
        attestation["gnina_pack_and_docking"] = run_packaged_gnina_pack_and_docking_smoke(
            client=api,
            app_dir=installed_app_dir,
            gnina_pack_path=gnina_pack_path,
        )
        terminate_desktop_and_verify_port_closed(desktop_proc)
        desktop_proc = None
        log_handle.close()
        log_handle = None

        attestation["completed_at"] = datetime.now(UTC).isoformat()
        attestation["status"] = "passed"
    except Exception as err:
        attestation["error"] = {"type": type(err).__name__, "message": str(err)}
        raise
    finally:
        if desktop_proc is not None and desktop_proc.poll() is None:
            with contextlib.suppress(Exception):
                terminate_desktop_and_verify_port_closed(desktop_proc, timeout_seconds=5.0)
            if desktop_proc.poll() is None:
                desktop_proc.kill()
                desktop_proc.wait(timeout=5)
        if log_handle is not None:
            log_handle.close()
        if not keep_temp and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)
        out_json = evidence_dir / "native-workstation-attestation.json"
        out_json.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    attestation["attestation_sha256"] = sha256_file(
        evidence_dir / "native-workstation-attestation.json"
    )
    return attestation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument(
        "--native-workstation-attestation",
        action="store_true",
        help="Run bare-metal Linux workstation attestation (ADR-029 D6) against installed /usr/bin/ankora.",
    )
    parser.add_argument(
        "--gnina-pack",
        type=Path,
        default=None,
        help="Path to Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part01 or .tar.zst (required with --native-workstation-attestation if not in --release-dir).",
    )
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if args.native_workstation_attestation:
        ev_dir = (
            args.evidence_dir
            or Path.cwd() / f"ankora-native-workstation-attestation-{stamp}"
        ).resolve()
        pack = args.gnina_pack
        if pack is None:
            candidates = sorted(args.release_dir.glob("*_gnina-cuda12-pack.tar.zst.part01")) or sorted(
                args.release_dir.glob("*_gnina-cuda12-pack.tar.zst")
            )
            if not candidates:
                raise SystemExit(
                    "Pass --gnina-pack /path/to/Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part01 (or .tar.zst)"
                )
            pack = candidates[0]
        result = run_native_workstation_attestation(
            gnina_pack_path=pack.resolve(),
            evidence_dir=ev_dir,
            keep_temp=args.keep_temp,
        )
        print(json.dumps({"status": result["status"], "evidence_dir": str(ev_dir), "attestation_sha256": result["attestation_sha256"]}, indent=2))
        return 0

    ev_dir = (
        args.evidence_dir
        or DEFAULT_EVIDENCE_PARENT / f"package-smoke-{stamp}"
    ).resolve()
    result = run_wsl_or_cleanroom_package_smoke(
        release_dir=args.release_dir.resolve(),
        evidence_dir=ev_dir,
        keep_temp=args.keep_temp,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "evidence_dir": str(ev_dir),
                "evidence_sha256": result["evidence_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
