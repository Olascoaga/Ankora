"""Documentation build regressions; PDF bytes below are synthetic, not science."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_user_guide_pdf", ROOT / "scripts" / "build_user_guide_pdf.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PDF_WAIT_SECONDS = 0
    return module


def test_real_guide_contents_links_have_heading_targets(builder: ModuleType) -> None:
    rendered = builder.convert((ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8"))
    links = re.findall(r'href="#([^"]+)"', rendered)
    anchors = re.findall(r'id="([^"]+)"', rendered)
    assert len(links) >= 11
    assert set(links) <= set(anchors)
    assert len(anchors) == len(set(anchors))


def test_duplicate_headings_and_html_are_escaped(builder: ModuleType) -> None:
    rendered = builder.convert('## Same\n\n## Same\n\n<script>"test"</script>')
    assert 'id="same"' in rendered and 'id="same-1"' in rendered
    assert "<script>" not in rendered
    assert "&quot;test&quot;" in rendered


def test_browser_discovery_uses_environment(
    builder: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(builder.shutil, "which", lambda _: None)
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        monkeypatch.delenv(variable, raising=False)
    assert builder.find_browser() is None
    browser = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    browser.parent.mkdir(parents=True)
    browser.touch()
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert builder.find_browser() == browser


@pytest.mark.parametrize("failure", ["process", "timeout", "missing", "incomplete"])
def test_failed_build_preserves_previous_pdf(
    builder: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Synthetic guide", encoding="utf-8")
    target = tmp_path / "guide.pdf"
    previous = b"synthetic previous artifact"
    target.write_bytes(previous)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["check"] is True and kwargs["shell"] is False
        if failure == "process":
            raise subprocess.CalledProcessError(1, command)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 240)
        if failure == "incomplete":
            output = next(
                arg.split("=", 1)[1] for arg in command if arg.startswith("--print-to-pdf=")
            )
            Path(output).write_bytes(b"%PDF-1.7\ntruncated")
        return subprocess.CompletedProcess(command, 0, b"", b"synthetic browser diagnostic")

    monkeypatch.setattr(builder.subprocess, "run", run)
    with pytest.raises((OSError, ValueError, subprocess.SubprocessError)):
        builder.build_pdf(source, target, tmp_path / "browser.exe")
    assert target.read_bytes() == previous
    assert not list(tmp_path.glob("ankora-guide-*"))


def test_successful_print_replaces_pdf_and_isolates_browser_profile(
    builder: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Synthetic guide", encoding="utf-8")
    target = tmp_path / "guide.pdf"
    target.write_bytes(b"old synthetic artifact")
    synthetic_pdf = b"%PDF-1.7\nsynthetic test only\n%%EOF\n"

    def run(command: list[str], **kwargs: object) -> None:
        assert any(arg.startswith("--user-data-dir=") for arg in command)
        assert kwargs["timeout"] == 240
        output = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--print-to-pdf="))
        Path(output).write_bytes(synthetic_pdf)

    monkeypatch.setattr(builder.subprocess, "run", run)
    builder.build_pdf(source, target, tmp_path / "browser.exe")
    assert target.read_bytes() == synthetic_pdf
    assert not list(tmp_path.glob("ankora-guide-*"))


def test_missing_image_does_not_start_browser(
    builder: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("![Missing](images/missing.png)", encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(builder.subprocess, "run", run)
    with pytest.raises(ValueError, match="Guide image"):
        builder.build_pdf(source, tmp_path / "guide.pdf", tmp_path / "browser.exe")
    run.assert_not_called()


@pytest.mark.parametrize("release_lock", [False, True])
def test_locked_output_preserves_previous_pdf_or_retries_safely(
    builder: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, release_lock: bool
) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Synthetic guide", encoding="utf-8")
    target = tmp_path / "guide.pdf"
    target.write_bytes(b"previous synthetic artifact")
    synthetic_pdf = b"%PDF-1.7\nsynthetic test only\n%%EOF\n"

    def run(command: list[str], **kwargs: object) -> None:
        output = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--print-to-pdf="))
        Path(output).write_bytes(synthetic_pdf)

    attempts = 0
    replace = Path.replace

    def locked_replace(path: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if not release_lock or attempts == 1:
            raise PermissionError("synthetic viewer lock")
        return replace(path, destination)

    monkeypatch.setattr(builder.subprocess, "run", run)
    monkeypatch.setattr(Path, "replace", locked_replace)
    monkeypatch.setattr(builder.time, "sleep", lambda _: None)
    builder.PDF_WAIT_SECONDS = 30 if release_lock else 0
    if release_lock:
        builder.build_pdf(source, target, tmp_path / "browser.exe")
        assert target.read_bytes() == synthetic_pdf
        assert attempts == 2
    else:
        with pytest.raises(PermissionError):
            builder.build_pdf(source, target, tmp_path / "browser.exe")
        assert target.read_bytes() == b"previous synthetic artifact"
    assert not list(tmp_path.glob("ankora-guide-*"))
