"""Regression contracts for PLATFORM_STATUS.json, docs/README.md, and validation/INDEX.md."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_platform_docs", ROOT / "scripts" / "check_platform_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage_minimal_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel in (
        "docs/README.md",
        "docs/product/PLATFORM_STATUS.json",
        "docs/product/PLATFORM_STATUS.md",
        "docs/product/PRODUCT_DEFINITION.md",
        "docs/product/SCOPE.md",
        "docs/scientific/REDOCKING_VALIDATION.md",
        "docs/architecture/ARCHITECTURE.md",
        "docs/DEVELOPMENT_LINUX.md",
        "docs/design/UX_FOUNDATION.md",
        "docs/design/STARTUP_SCREEN.md",
        "docs/DEVELOPMENT.md",
        "docs/architecture/ADR/ADR-026-linux-port-and-native-acceptance.md",
        "docs/architecture/ADR/ADR-029-linux-offline-distribution.md",
        "docs/validation/GNINA_REDOCKING.md",
        "docs/validation/LINUX_GNINA_REDOCKING.md",
        "docs/validation/LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md",
        "docs/validation/INDEX.md",
        "docs/validation/VALIDATION_STATUS.md",
        "docs/validation/PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md",
        "docs/validation/PRIVATE_BETA_INSTALLER_2026-10-15.md",
        "docs/validation/LINUX_OFFLINE_PACKAGE_SMOKE.md",
        "docs/validation/LINUX_NATIVE_WORKSTATION_PROTOCOL.md",
    ):
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    (repo / "docs/USER_GUIDE.md").write_text("# Synthetic User Guide\n", encoding="utf-8")
    return repo


def test_repository_platform_docs_and_validation_index_are_synchronized(
    checker: ModuleType,
) -> None:
    platforms_count, indexed_count = checker.verify_all(ROOT, write=False)
    assert platforms_count == 3
    assert indexed_count >= 125

    data = checker.load_and_validate_platform_status(ROOT)
    platforms = {p["platform_id"]: p for p in data["platforms"]}
    assert platforms["windows_x86_64"]["distribution_status"] == "private_beta"
    assert platforms["windows_x86_64"]["accepted_release"] is False
    assert platforms["linux_x86_64"]["distribution_status"] == "release_candidate"
    assert platforms["linux_x86_64"]["accepted_release"] is False
    assert any("D6" in gate for gate in platforms["linux_x86_64"]["pending_release_gates"])
    assert platforms["macos"]["distribution_status"] == "out_of_scope"


def test_checker_rejects_premature_accepted_release_while_gates_remain(
    checker: ModuleType, tmp_path: Path
) -> None:
    repo = _stage_minimal_repo(tmp_path)
    json_path = repo / "docs/product/PLATFORM_STATUS.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["platforms"][1]["distribution_status"] = "accepted_release"
    payload["platforms"][1]["accepted_release"] = True
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(checker.PlatformDocsError, match="pending_release_gates remain"):
        checker.load_and_validate_platform_status(repo)


def test_checker_detects_stale_rendered_platform_markdown(
    checker: ModuleType, tmp_path: Path
) -> None:
    repo = _stage_minimal_repo(tmp_path)
    # Create minimal portal and index matching only staged validation docs
    (repo / "docs/README.md").write_text(
        "# Docs\n\n- [Status](product/PLATFORM_STATUS.md)\n", encoding="utf-8"
    )
    (repo / "docs/validation/INDEX.md").write_text(
        "# Index\n\n"
        "- [a](VALIDATION_STATUS.md)\n"
        "- [b](PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md)\n"
        "- [c](PRIVATE_BETA_INSTALLER_2026-10-15.md)\n"
        "- [d](LINUX_OFFLINE_PACKAGE_SMOKE.md)\n"
        "- [e](LINUX_NATIVE_WORKSTATION_PROTOCOL.md)\n"
        "- [f](GNINA_REDOCKING.md)\n"
        "- [g](LINUX_GNINA_REDOCKING.md)\n"
        "- [h](LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md)\n",
        encoding="utf-8",
    )
    checker.verify_all(repo, write=False)

    (repo / "docs/product/PLATFORM_STATUS.md").write_text("# Stale\n", encoding="utf-8")
    with pytest.raises(checker.PlatformDocsError, match="out of sync"):
        checker.verify_all(repo, write=False)


def test_checker_rejects_unindexed_validation_record_and_broken_links(
    checker: ModuleType, tmp_path: Path
) -> None:
    repo = _stage_minimal_repo(tmp_path)
    (repo / "docs/README.md").write_text(
        "# Docs\n\n- [Status](product/PLATFORM_STATUS.md)\n", encoding="utf-8"
    )
    (repo / "docs/validation/INDEX.md").write_text(
        "# Index\n\n"
        "- [a](VALIDATION_STATUS.md)\n"
        "- [b](PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md)\n"
        "- [c](PRIVATE_BETA_INSTALLER_2026-10-15.md)\n"
        "- [d](LINUX_OFFLINE_PACKAGE_SMOKE.md)\n"
        "- [e](LINUX_NATIVE_WORKSTATION_PROTOCOL.md)\n"
        "- [f](GNINA_REDOCKING.md)\n"
        "- [g](LINUX_GNINA_REDOCKING.md)\n"
        "- [h](LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md)\n",
        encoding="utf-8",
    )
    (repo / "docs/validation/SYNTHETIC_NEW_RECORD.md").write_text("# Synthetic\n", encoding="utf-8")
    with pytest.raises(checker.PlatformDocsError, match="omits 1 validation record"):
        checker.verify_all(repo, write=False)

    (repo / "docs/validation/SYNTHETIC_NEW_RECORD.md").unlink()
    (repo / "docs/README.md").write_text(
        "# Docs\n\n- [Broken](missing/file.md)\n", encoding="utf-8"
    )
    with pytest.raises(checker.PlatformDocsError, match="Broken relative link"):
        checker.verify_all(repo, write=False)
