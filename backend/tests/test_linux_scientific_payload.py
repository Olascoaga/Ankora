"""Tests for ADR-029 Linux scientific payload, GNINA pack, and packaging locks."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ankora_backend.adapters.engines.gnina import VERIFIED_GNINA_1_3_3_SHA256

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
LINUX_PACKAGING_LOCK = ROOT / "requirements/linux-packaging.lock"
WINDOWS_PACKAGING_LOCK = ROOT / "requirements/windows-packaging.lock"


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


linux_payload = _load_script("linux_scientific_payload")
windows_payload = _load_script("windows_scientific_payload")

SHARED_SOURCE_IDS = (
    "vina-source",
    "autodocksuite-source",
    "autodock-gpu-source",
    "p2rank",
    "p2rank-source",
    "p2rank-biojava-source",
    "p2rank-fasterforest-source",
    "p2rank-molecularsurface-source",
    "java-source",
)


def test_committed_linux_scientific_payload_lock_is_valid_and_matches_windows_sources() -> None:
    linux_entries = {item["id"]: item for item in linux_payload.load_lock()}
    windows_entries = {item["id"]: item for item in windows_payload.load_lock()}

    for shared_id in SHARED_SOURCE_IDS:
        assert linux_entries[shared_id]["version"] == windows_entries[shared_id]["version"]
        assert linux_entries[shared_id]["sha256"] == windows_entries[shared_id]["sha256"]
        assert linux_entries[shared_id]["size_bytes"] == windows_entries[shared_id]["size_bytes"]

    assert linux_entries["java"]["version"] == windows_entries["java"]["version"] == "21.0.12.1+1"
    assert linux_entries["gnina"]["sha256"] == VERIFIED_GNINA_1_3_3_SHA256
    assert linux_entries["gnina"]["extra_source_ids"] == ["openbabel-source"]


def test_committed_gnina_cuda12_pack_lock_covers_cudnn_dlopen_closure_and_forbids_driver() -> None:
    pack = linux_payload.load_gnina_pack_lock()
    assert pack["executable"]["sha256"] == VERIFIED_GNINA_1_3_3_SHA256

    libs = {lib["soname"]: lib for lib in pack["shared_libraries"]}
    expected_cuda = {
        "libcudart.so.12",
        "libcusparse.so.12",
        "libcufft.so.11",
        "libcublas.so.12",
        "libcublasLt.so.12",
        "libcusolver.so.11",
        "libnvJitLink.so.12",
    }
    expected_cudnn = {
        "libcudnn.so.9",
        "libcudnn_adv.so.9",
        "libcudnn_cnn.so.9",
        "libcudnn_engines_precompiled.so.9",
        "libcudnn_engines_runtime_compiled.so.9",
        "libcudnn_engines_tensor_ir.so.9",
        "libcudnn_ext.so.9",
        "libcudnn_graph.so.9",
        "libcudnn_heuristic.so.9",
        "libcudnn_ops.so.9",
    }
    assert set(libs) == expected_cuda | expected_cudnn


def test_gnina_pack_lock_rejects_host_driver_library_and_upstream_hash_drift(
    tmp_path: Path,
) -> None:
    raw = json.loads(linux_payload.GNINA_PACK_LOCK.read_text(encoding="utf-8"))

    tampered_driver = copy.deepcopy(raw)
    tampered_driver["shared_libraries"].append(
        {
            "soname": "libcuda.so.1",
            "filename": "libcuda.so.570.00",
            "family": "driver",
            "redistribution_clause": "invalid",
            "size_bytes": 1024,
            "sha256": "a" * 64,
        }
    )
    bad_driver_path = tmp_path / "bad-driver.json"
    bad_driver_path.write_text(json.dumps(tampered_driver), encoding="utf-8")
    with pytest.raises(ValueError, match="Forbidden host GPU driver library"):
        linux_payload.load_gnina_pack_lock(bad_driver_path)

    tampered_sha = copy.deepcopy(raw)
    tampered_sha["executable"]["sha256"] = "0" * 64
    bad_sha_path = tmp_path / "bad-sha.json"
    bad_sha_path.write_text(json.dumps(tampered_sha), encoding="utf-8")
    with pytest.raises(ValueError, match="disagrees with upstream lock"):
        linux_payload.load_gnina_pack_lock(bad_sha_path)


def test_linux_payload_lock_rejects_unverified_host_and_missing_source(tmp_path: Path) -> None:
    raw = json.loads(linux_payload.LOCK.read_text(encoding="utf-8"))

    bad_host = copy.deepcopy(raw)
    bad_host["artifacts"][0]["url"] = "https://example.org/vina"
    host_path = tmp_path / "bad-host.json"
    host_path.write_text(json.dumps(bad_host), encoding="utf-8")
    with pytest.raises(ValueError, match="allowlisted upstream HTTPS URL"):
        linux_payload.load_lock(host_path)

    missing_src = copy.deepcopy(raw)
    del missing_src["artifacts"][0]["source_id"]
    src_path = tmp_path / "missing-src.json"
    src_path.write_text(json.dumps(missing_src), encoding="utf-8")
    with pytest.raises(ValueError, match="must declare source_id"):
        linux_payload.load_lock(src_path)


def test_linux_packaging_lock_pins_hashes_and_excludes_windows_only_packages() -> None:
    lines = [
        line.strip()
        for line in LINUX_PACKAGING_LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines[:2] == ["--only-binary=:all:", "--require-hashes"]

    win_pins: dict[str, str] = {}
    for line in WINDOWS_PACKAGING_LOCK.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([a-z0-9-]+)==([^\s]+)\s+--hash=sha256:([0-9a-f]{64})$", line.strip())
        if m:
            win_pins[m.group(1)] = m.group(2)

    linux_pins: dict[str, str] = {}
    for line in lines[2:]:
        m = re.match(r"^([a-z0-9-]+)==([^\s]+)\s+--hash=sha256:([0-9a-f]{64})$", line)
        assert m is not None, f"Unpinned or unhashed line in linux-packaging.lock: {line}"
        linux_pins[m.group(1)] = m.group(2)

    assert "pefile" not in linux_pins
    assert "pywin32-ctypes" not in linux_pins
    assert set(linux_pins) == {
        "altgraph",
        "packaging",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "setuptools",
    }
    for name, version in linux_pins.items():
        assert version == win_pins[name]


def test_extract_archive_materializes_safe_intra_archive_symlinks_and_rejects_escapes(
    tmp_path: Path,
) -> None:
    import io
    import tarfile

    good_tar = tmp_path / "good.tar.gz"
    with tarfile.open(good_tar, "w:gz") as tf:
        base_bytes = b"GNU GPL v2 with Classpath Exception\n"
        reg = tarfile.TarInfo("jre/legal/java.base/LICENSE")
        reg.size = len(base_bytes)
        reg.mode = 0o644
        tf.addfile(reg, io.BytesIO(base_bytes))

        sym = tarfile.TarInfo("jre/legal/java.xml/LICENSE")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "../java.base/LICENSE"
        tf.addfile(sym)

    extracted = tmp_path / "out-good"
    linux_payload.extract_archive(good_tar, extracted, prefix="jre")
    materialized = extracted / "legal/java.xml/LICENSE"
    assert materialized.is_file()
    assert not materialized.is_symlink()
    assert materialized.read_bytes() == base_bytes

    for label, linkname in (
        ("escape", "../../../etc/passwd"),
        ("absolute", "/etc/passwd"),
        ("dangling", "../java.base/MISSING"),
    ):
        bad_tar = tmp_path / f"bad-{label}.tar.gz"
        with tarfile.open(bad_tar, "w:gz") as tf:
            reg = tarfile.TarInfo("jre/legal/java.base/LICENSE")
            reg.size = 4
            tf.addfile(reg, io.BytesIO(b"ok\n\n"))
            sym = tarfile.TarInfo("jre/legal/java.xml/LICENSE")
            sym.type = tarfile.SYMTYPE
            sym.linkname = linkname
            tf.addfile(sym)
        with pytest.raises(ValueError, match="symlink"):
            linux_payload.extract_archive(bad_tar, tmp_path / f"out-{label}", prefix="jre")
