from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "prepare_windows_release.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def _load_release_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_windows_release", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _unsigned_evidence(module: ModuleType) -> object:
    return module.SignatureEvidence(
        status="NotSigned",
        signer_subject=None,
        signer_thumbprint=None,
        timestamp_subject=None,
        timestamp_thumbprint=None,
    )


def _synthetic_installer(module: ModuleType, directory: Path) -> Path:
    installer = directory / f"Ankora_{module.project_version()}_x64-setup.exe"
    installer.write_bytes(b"synthetic unsigned Windows installer fixture\n")
    return installer


def _prepare_args(
    installer: Path, output_dir: Path, *, require_signed: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(
        installer=installer,
        output_dir=output_dir,
        source_ref="synthetic-source",
        require_clean=False,
        require_tag=False,
        require_signed=require_signed,
    )


def test_unsigned_candidate_is_deterministic_and_contains_no_private_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_release_module()
    installer = _synthetic_installer(module, tmp_path)
    monkeypatch.setattr(module, "source_identity", lambda _ref: ("c" * 40, "d" * 40))
    monkeypatch.setattr(module, "verify_tag", lambda *_args: False)
    monkeypatch.setattr(module, "signature_evidence", lambda _path: _unsigned_evidence(module))

    first = tmp_path / "first"
    second = tmp_path / "second"
    module.prepare(_prepare_args(installer, first))
    module.prepare(_prepare_args(installer, second))

    assert (first / "release-manifest.json").read_bytes() == (
        second / "release-manifest.json"
    ).read_bytes()
    assert (first / "SHA256SUMS").read_bytes() == (second / "SHA256SUMS").read_bytes()
    manifest_text = (first / "release-manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["authenticode"]["status"] == "NotSigned"
    assert manifest["publication_ready"] is False
    assert str(REPOSITORY_ROOT) not in manifest_text
    assert str(tmp_path) not in manifest_text
    module.verify(argparse.Namespace(release_dir=first, require_signed=False))


def test_verifier_rejects_tampered_release_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_release_module()
    installer = _synthetic_installer(module, tmp_path)
    monkeypatch.setattr(module, "source_identity", lambda _ref: ("c" * 40, "d" * 40))
    monkeypatch.setattr(module, "verify_tag", lambda *_args: False)
    monkeypatch.setattr(module, "signature_evidence", lambda _path: _unsigned_evidence(module))
    release_dir = tmp_path / "release"
    module.prepare(_prepare_args(installer, release_dir))
    (release_dir / "SOURCE_AVAILABILITY.txt").write_text("tampered", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        module.verify(argparse.Namespace(release_dir=release_dir, require_signed=False))


def test_publication_rejects_unsigned_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_release_module()
    installer = _synthetic_installer(module, tmp_path)
    monkeypatch.setattr(module, "source_identity", lambda _ref: ("c" * 40, "d" * 40))
    monkeypatch.setattr(module, "verify_tag", lambda *_args: True)
    monkeypatch.setattr(module, "signature_evidence", lambda _path: _unsigned_evidence(module))
    release_dir = tmp_path / "release"

    with pytest.raises(RuntimeError, match="Valid Authenticode"):
        module.prepare(_prepare_args(installer, release_dir, require_signed=True))

    assert not release_dir.exists()


def test_signature_check_requires_windows_environment_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_release_module()
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.os, "environ", {})

    with pytest.raises(RuntimeError, match="WINDIR or SystemRoot"):
        module.signature_evidence(tmp_path / "synthetic-installer.exe")


def test_release_workflow_is_manual_pinned_and_fails_closed() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    action_references = re.findall(r"uses:\s*([^\s#]+)", workflow)

    assert "workflow_dispatch:" in workflow
    assert "pull_request_target:" not in workflow
    assert "--require-tag" in workflow
    assert workflow.count("--require-signed") >= 2
    assert "subject-checksums: build/windows-runtime/release-assets/SHA256SUMS" in workflow
    assert action_references
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in action_references)
