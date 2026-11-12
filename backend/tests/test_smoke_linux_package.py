"""Unit tests for offline Linux package smoke and attestation script (ADR-029 D4/D6)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_smoke_module() -> ModuleType:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "smoke_linux_package",
        ROOT / "scripts" / "smoke_linux_package.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_smoke_module()


def test_build_clean_user_environment_strips_developer_toolchains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/opt/miniforge3/bin:/opt/cargo/bin:/usr/bin:/bin")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/custom/cuda/lib64")
    monkeypatch.setenv("CONDA_PREFIX", "/opt/miniforge3")
    monkeypatch.setenv("ANKORA_GNINA_PATH", "/tmp/gnina")
    monkeypatch.setenv("DISPLAY", ":0")

    clean_home = tmp_path / "clean-home"
    env = _MOD.build_clean_user_environment(
        clean_home=clean_home,
        allow_wsl_driver_path=False,
    )
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == str(clean_home)
    assert env["XDG_DATA_HOME"] == str(clean_home / ".local" / "share")
    assert env["DISPLAY"] == ":0"
    assert "LD_LIBRARY_PATH" not in env
    assert "CONDA_PREFIX" not in env
    assert "ANKORA_GNINA_PATH" not in env


def test_audit_core_app_tree_validates_legal_digests_and_rejects_gnina_or_driver_libs(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "ankora"
    (app_dir / "backend" / "tools").mkdir(parents=True)
    (app_dir / "legal").mkdir(parents=True)
    (app_dir / "ankora-desktop").write_bytes(b"\x7fELFdesktop")
    (app_dir / "backend" / "ankora-backend").write_bytes(b"\x7fELFbackend")
    (app_dir / "backend" / "tools" / "payload.json").write_text("{}\n", encoding="utf-8")

    legal_files = {}
    for fname in (
        "INSTALLATION_TERMS.txt",
        "SOURCE_AVAILABILITY.txt",
        "THIRD_PARTY_NOTICES.txt",
        "THIRD_PARTY_INVENTORY.json",
    ):
        fpath = app_dir / "legal" / fname
        fpath.write_text(f"synthetic {fname}\n", encoding="utf-8")
        legal_files[fname] = hashlib.sha256(fpath.read_bytes()).hexdigest()

    (app_dir / "legal" / "COMPLETE_LEGAL_MANIFEST.json").write_text(
        json.dumps({"files": legal_files}) + "\n",
        encoding="utf-8",
    )

    audit = _MOD.audit_core_app_tree(app_dir)
    assert audit["regular_files"] == 8

    # Inject forbidden GNINA or CUDA library -> must fail closed!
    forbidden = app_dir / "backend" / "tools" / "libcudnn.so.9"
    forbidden.write_bytes(b"forbidden")
    with pytest.raises(ValueError, match="Forbidden driver or GNINA file"):
        _MOD.audit_core_app_tree(app_dir)


def test_native_workstation_attestation_refuses_wsl_kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MOD, "is_wsl_kernel", lambda: True)
    with pytest.raises(
        RuntimeError,
        match="Refusing --native-workstation-attestation on a WSL kernel",
    ):
        _MOD.run_native_workstation_attestation(
            gnina_pack_path=tmp_path / "missing.tar.zst",
            evidence_dir=tmp_path / "ev",
        )
