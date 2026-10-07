"""Synthetic build metadata only, never a mock scientific result."""

from pathlib import Path

import pytest
from scripts.build_autodock_gpu_payload import adapt_source, build
from scripts.stage_windows_scientific_payload import verify_extractor


def test_gpu_portability_patch_changes_only_reviewed_patterns(tmp_path: Path) -> None:
    project = (
        b"/openmp:llvm " * 2 + b"<GenerateDebugInformation>true</GenerateDebugInformation>" * 4
    )
    (tmp_path / "AutoDock-GPU.vcxproj").write_bytes(project)
    host = tmp_path / "host/src"
    host.mkdir(parents=True)
    (host / "main.cpp").write_bytes(b"#pragma omp atomic update\n" * 3)
    untouched = tmp_path / "scientific-kernel.cl"
    untouched.write_bytes(b"synthetic unchanged kernel fixture")
    changes = adapt_source(tmp_path)
    assert len(changes) == 3
    assert (host / "main.cpp").read_bytes() == b"#pragma omp atomic\n" * 3
    assert b"/openmp:llvm" not in (tmp_path / "AutoDock-GPU.vcxproj").read_bytes()
    assert b"Information>true" not in (tmp_path / "AutoDock-GPU.vcxproj").read_bytes()
    assert untouched.read_bytes() == b"synthetic unchanged kernel fixture"
    assert all(change["before_sha256"] != change["after_sha256"] for change in changes)


def test_gpu_patch_refuses_drifted_source(tmp_path: Path) -> None:
    (tmp_path / "AutoDock-GPU.vcxproj").write_text("unexpected version")
    with pytest.raises(ValueError, match="unreviewed patch"):
        adapt_source(tmp_path)


def test_gpu_build_never_replaces_existing_evidence(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError, match="create-only"):
        build(tmp_path, tmp_path / "unused-compiler")


def test_stager_refuses_unverified_extractor(tmp_path: Path) -> None:
    executable = tmp_path / "7z.exe"
    executable.write_bytes(b"synthetic, not executable")
    with pytest.raises(ValueError, match="Unverified"):
        verify_extractor(executable)
