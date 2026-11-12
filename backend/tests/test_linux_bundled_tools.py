"""Contracts for Linux bundled tools, AutoDock-GPU ELF audit, legal companion, and discovery.

Every binary and JAR here is a SYNTHETIC fixture that is never executed for scientific
inference. Real scientific binaries are validated by recorded package smoke evidence.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from ankora_backend.adapters.tools import discovery, pocket_detection
from ankora_backend.adapters.tools.discovery import (
    discover_autodock4,
    discover_autodock_gpu,
    discover_autogrid4,
    discover_java_home,
    discover_p2rank,
    discover_vina,
)
from ankora_backend.execution.subprocess_runner import ToolExecution

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
X86_64, ARM64 = 0x3E, 0xB7


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_adgpu = _load_script("build_linux_autodock_gpu")
stage_linux = _load_script("stage_linux_scientific_payload")
complete_legal = _load_script("complete_linux_legal")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _elf(path: Path, machine: int = X86_64, mode: int = 0o755) -> Path:
    """SYNTHETIC 64-bit little-endian ELF header; never executed."""
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4], header[5], header[6] = 2, 1, 1
    header[18:20] = machine.to_bytes(2, byteorder="little")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + b"SYNTHETIC ELF fixture; never executed")
    path.chmod(mode)
    return path


def _script(path: Path, interpreter: str = "/usr/bin/env bash") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"#!{interpreter}\n# SYNTHETIC launcher; never executed\n".encode())
    path.chmod(0o755)
    return path


def test_autodock_gpu_target_architectures_cover_turing_through_blackwell() -> None:
    assert build_adgpu.TARGET_SM_ARCHITECTURES == (
        "75",
        "80",
        "86",
        "89",
        "90",
        "100",
        "120",
    )


@pytest.mark.skipif(os.name == "nt", reason="readelf dynamic section audit runs on Linux")
def test_autodock_gpu_elf_audit_rejects_rpath_and_dynamic_cudart(tmp_path: Path) -> None:
    dummy = _elf(tmp_path / "dummy")
    rpath_stdout = (
        " 0x0000000000000001 (NEEDED) Shared library: [libc.so.6]\n"
        " 0x000000000000001d (RUNPATH) Library runpath: [/opt/cuda/lib64]\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = rpath_stdout
        with pytest.raises(RuntimeError, match="embeds host RPATH/RUNPATH"):
            build_adgpu.audit_autodock_gpu_elf(dummy)

    cudart_stdout = (
        " 0x0000000000000001 (NEEDED) Shared library: [libcudart.so.12]\n"
        " 0x0000000000000001 (NEEDED) Shared library: [libc.so.6]\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = cudart_stdout
        with pytest.raises(
            RuntimeError, match="links forbidden non-portable shared libraries"
        ):
            build_adgpu.audit_autodock_gpu_elf(dummy)

    clean_stdout = (
        " 0x0000000000000001 (NEEDED) Shared library: [libgomp.so.1]\n"
        " 0x0000000000000001 (NEEDED) Shared library: [libc.so.6]\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = clean_stdout
        audit = build_adgpu.audit_autodock_gpu_elf(dummy)
        assert audit == {
            "needed_shared_libraries": ["libgomp.so.1", "libc.so.6"],
            "rpaths": [],
            "embedded_fatbin_targets": [],
        }


def test_stage_linux_scientific_payload_declares_slim_model_and_java_rules() -> None:
    assert set(stage_linux.RETAINED_P2RANK_MODELS) == {
        "p2rank-2.5.1/models/default/model.zst",
        "p2rank-2.5.1/models/alphafold/model.zst",
    }
    assert len(stage_linux.OMITTED_P2RANK_MODELS) == 5
    assert set(stage_linux.OMITTED_JAVA_FILES) == {
        "java-21/lib/server/classes.jsa",
        "java-21/lib/server/classes_nocoops.jsa",
    }


def test_verify_complete_linux_legal_enforces_gnina_sources_and_rejects_windows_leak(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    vina = _elf(tools / "vina-1.2.7/vina")
    payload = {
        "schema_version": 1,
        "platform": "linux-x86_64",
        "tools": {"vina": {"path": "vina-1.2.7/vina", "version": "1.2.7"}},
        "files": {"vina-1.2.7/vina": _sha256_bytes(vina.read_bytes())},
    }
    (tools / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    payload_sha = _sha256_bytes((tools / "payload.json").read_bytes())
    gnina_lock_sha = complete_legal.sha256(complete_legal.GNINA_PACK_LOCK)

    legal = tmp_path / "complete-legal"
    legal.mkdir()
    inventory = {
        "schema_version": 1,
        "scientific_payload_sha256": payload_sha,
        "excluded_external_tools": ["GNINA"],
        "components": [
            {"name": name, "category": "scientific-runtime"}
            for name in (
                "AutoDock Vina",
                "AutoGrid4",
                "AutoDock4",
                "AutoDock-GPU",
                "P2Rank",
                "Eclipse Temurin JRE",
            )
        ],
    }
    (legal / "THIRD_PARTY_INVENTORY.json").write_text(json.dumps(inventory), encoding="utf-8")
    (legal / "ANKORA_LICENSE.txt").write_text("MIT\n", encoding="utf-8")

    good_zip = tmp_path / "Ankora_0.1.0_linux-sources-companion.zip"
    with zipfile.ZipFile(good_zip, "w") as zf:
        zf.writestr("SCIENTIFIC_SOURCE_COMPANION.json", "{}\n")
        zf.writestr("sources/autodock-gpu-1.6-ankora-source.zip", b"gpu-src")
        zf.writestr("sources/fffc36d6b4a665dc-gnina-source.tar.gz", b"gnina-src")
        zf.writestr("sources/c97023ac6300d261-openbabel-source.tar.gz", b"obabel-src")

    manifest_files = {
        p.relative_to(legal).as_posix(): complete_legal.sha256(p)
        for p in sorted(legal.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema_version": 1,
        "platform": "linux-x86_64",
        "scientific_payload_sha256": payload_sha,
        "gnina_pack_lock_sha256": gnina_lock_sha,
        "companion_archive_name": good_zip.name,
        "companion_archive_sha256": complete_legal.sha256(good_zip),
        "files": manifest_files,
    }
    (legal / "COMPLETE_LEGAL_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    verified = complete_legal.verify_complete_linux_legal(legal, tools, good_zip)
    assert verified["scientific_payload_sha256"] == payload_sha

    # Missing OpenBabel GPL-2.0 source archive in companion zip must fail closed
    incomplete_zip = tmp_path / "incomplete-companion.zip"
    with zipfile.ZipFile(incomplete_zip, "w") as zf:
        zf.writestr("SCIENTIFIC_SOURCE_COMPANION.json", "{}\n")
        zf.writestr("sources/autodock-gpu-1.6-ankora-source.zip", b"gpu-src")
        zf.writestr("sources/fffc36d6b4a665dc-gnina-source.tar.gz", b"gnina-src")
    manifest["companion_archive_sha256"] = complete_legal.sha256(incomplete_zip)
    (legal / "COMPLETE_LEGAL_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="OpenBabel GPL-2.0 source"):
        complete_legal.verify_complete_linux_legal(legal, tools, incomplete_zip)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="frozen Linux discovery contract")
def test_frozen_linux_native_payload_discovers_all_six_core_tools_and_rejects_arm64(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vina = _elf(tmp_path / "tools/vina-1.2.7/vina", X86_64)
    ad4 = _elf(tmp_path / "tools/autodock4-4.2.6/autodock4", X86_64)
    ag4 = _elf(tmp_path / "tools/autodock4-4.2.6/autogrid4", X86_64)
    adgpu = _elf(tmp_path / "tools/autodock-gpu-1.6/autodock_gpu_128wi", X86_64)
    prank = _script(tmp_path / "tools/p2rank-2.5.1/prank", "/usr/bin/env bash")
    java = _elf(tmp_path / "tools/java-21/bin/java", X86_64)
    (tmp_path / "tools/java-21/release").write_text(
        'JAVA_VERSION="21.0.12.1"\n', encoding="utf-8"
    )

    bundle_map = {
        "vina": (vina, "1.2.7"),
        "autodock4": (ad4, "4.2.6"),
        "autogrid4": (ag4, "4.2.6"),
        "autodock_gpu": (adgpu, "1.6"),
        "p2rank": (prank, "2.5.1"),
        "java": (java, "21.0.12.1+1"),
    }
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(discovery, "bundled_tool", lambda name: bundle_map.get(name))

    assert discover_vina().available is True
    assert discover_vina().architecture == "x86_64"
    assert discover_vina().version == "1.2.7"
    assert discover_autodock4().available is True
    assert discover_autogrid4().available is True
    assert discover_autodock_gpu().available is True
    assert discover_autodock_gpu().version == "1.6"
    assert discover_p2rank().available is True
    assert discover_p2rank().version == "2.5.1"
    assert discover_java_home() == (tmp_path / "tools/java-21").resolve()

    arm_vina = _elf(tmp_path / "tools/arm/vina", ARM64)
    monkeypatch.setattr(discovery, "bundled_tool", lambda name: (arm_vina, "1.2.7"))
    assert discover_vina().available is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="frozen Linux P2Rank execution")
def test_frozen_linux_execute_p2rank_launches_java_directly_with_colon_classpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_dir = tmp_path / "tools with spaces/p2rank-2.5.1"
    prank = _script(install_dir / "prank")
    java_home = tmp_path / "tools with spaces/java-21"
    java_bin = _elf(java_home / "bin/java", X86_64)
    (java_home / "release").write_text('JAVA_VERSION="21.0.12.1"\n', encoding="utf-8")

    receptor = tmp_path / "receptor.pdb"
    receptor.write_text("HEADER SYNTHETIC\nEND\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dinjected=1")
    monkeypatch.setenv("CLASSPATH", "/bad/classpath")
    monkeypatch.setattr(
        pocket_detection,
        "discover_p2rank",
        lambda _: discovery.DiscoveredTool(available=True, path=str(prank), version="2.5.1"),
    )
    monkeypatch.setattr(pocket_detection, "discover_java_home", lambda _: java_home)

    captured: dict[str, object] = {}

    def _fake_run_tool(**kwargs: object) -> ToolExecution:
        captured.update(kwargs)
        return ToolExecution(
            command=[str(kwargs["executable"]), *kwargs["arguments"]],  # type: ignore[misc]
            exit_code=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(pocket_detection, "run_tool", _fake_run_tool)
    _, version = pocket_detection.execute_p2rank(
        receptor_pdb_path=receptor, output_dir=out_dir
    )

    assert version == "2.5.1"
    assert captured["executable"] == str(java_bin)
    assert captured["arguments"] == [
        "-Xmx2048m",
        "-cp",
        f"{install_dir / 'bin/p2rank.jar'}:{install_dir / 'bin/lib/*'}",
        "cz.siret.prank.program.Main",
        "predict",
        "-f",
        str(receptor),
        "-o",
        str(out_dir),
        "-visualizations",
        "0",
    ]
    env = captured["environment"]
    assert isinstance(env, dict)
    assert "JAVA_TOOL_OPTIONS" not in env
    assert "CLASSPATH" not in env
    assert env["JAVA_HOME"] == str(java_home)
