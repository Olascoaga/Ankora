"""Synthetic packaging integrity fixtures, never simulated scientific results."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts import complete_windows_legal as legal
from scripts import prepare_scientific_source_bundle as sources
from scripts.windows_scientific_payload import sha256


def test_source_copy_is_exact_and_never_replaces_existing_bytes(tmp_path: Path) -> None:
    source = tmp_path / "upstream.zip"
    source.write_bytes(b"synthetic unchanged archive")
    output = tmp_path / "companion"
    output.mkdir()
    relative = sources.copy_source(source, output, sha256(source))
    assert (output / relative).read_bytes() == source.read_bytes()
    (output / relative).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="copy mismatch"):
        sources.copy_source(source, output, sha256(source))


def test_wrong_source_hash_stops_before_copy(tmp_path: Path) -> None:
    source = tmp_path / "upstream.zip"
    source.write_bytes(b"synthetic archive")
    with pytest.raises(ValueError, match="changed"):
        sources.copy_source(source, tmp_path, "0" * 64)
    assert not (tmp_path / "sources").exists()


def test_archive_paths_are_labels_not_extraction_targets(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../../LICENSE", "synthetic license")
        stream.writestr("src/a.java", "/* Copyright Synthetic */ class A {}")
        stream.writestr("src/b.java", 'class B { String s = "license"; }')
    notices = sources.archive_notices(archive)
    assert notices == [
        ("../../LICENSE", b"synthetic license"),
        ("src/a.java (source preamble)", b"/* Copyright Synthetic */"),
    ]
    assert list(tmp_path.iterdir()) == [archive]


def test_oversized_license_is_not_silently_omitted(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("LICENSE", b"x" * 11)
    with patch.object(sources, "MAX_NOTICE", 10), pytest.raises(ValueError, match="size"):
        sources.archive_notices(archive)


def test_wrong_runtime_blocks_legal_payload(tmp_path: Path) -> None:
    (tmp_path / "payload.json").write_text("synthetic")
    with patch.object(legal, "verify_tree"), pytest.raises(ValueError, match="Wrong"):
        legal.verify_complete(tmp_path, tmp_path)


@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_legal_verifier_rejects_file_drift(tmp_path: Path, change: str) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "payload.json").write_text("synthetic runtime")
    output = tmp_path / "legal"
    output.mkdir()
    item = output / "NOTICE"
    item.write_text("synthetic terms")
    manifest = {
        "scientific_payload_sha256": sha256(tools / "payload.json"),
        "files": {"NOTICE": sha256(item)},
    }
    (output / "COMPLETE_LEGAL_MANIFEST.json").write_text(json.dumps(manifest))
    if change == "missing":
        item.unlink()
    elif change == "extra":
        (output / "extra").write_text("unlisted")
    else:
        item.write_text("changed")
    with (
        patch.object(legal, "verify_tree"),
        patch.object(legal, "PAYLOAD_SHA256", manifest["scientific_payload_sha256"]),
        pytest.raises(ValueError, match="file|integrity"),
    ):
        legal.verify_complete(output, tools)


def test_installer_declares_offline_browser_and_complete_legal_payload() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "apps/desktop/src-tauri/tauri.conf.json").read_text())
    assert config["bundle"]["windows"]["webviewInstallMode"]["type"] == "offlineInstaller"
    assert config["bundle"]["resources"]["resources/complete-legal/"] == "legal/"
    assert config["bundle"]["licenseFile"].endswith("INSTALLATION_TERMS.txt")
