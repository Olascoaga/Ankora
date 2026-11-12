"""Synthetic fixtures for the Option A slim Windows installer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts import build_slim_windows_installer as slim
from scripts import complete_windows_legal as legal
from scripts.windows_scientific_payload import sha256

SYNTHETIC_NSI = """!define OUTFILE "nsis-output.exe"
!define INSTALLWEBVIEW2MODE "offlineInstaller"
!define ESTIMATEDSIZE "1000"
  SetCompressor /SOLID "lzma"
Section "Install"
  ; Copy resources
    CreateDirectory "$INSTDIR\\backend"
    File /a "/oname=backend\\old.txt" "build\\synthetic-old.txt"

  ; Copy external binaries
SectionEnd
Section "Uninstall"
  ; Delete resources
    Delete "$INSTDIR\\backend\\old.txt"

  ; Delete external binaries
  RMDir "$INSTDIR"
SectionEnd
"""


def test_stage_slim_tools_retains_default_and_alphafold_only(tmp_path: Path) -> None:
    ref_tools = tmp_path / "ref_tools"
    ref_tools.mkdir()
    files: dict[str, str] = {}
    all_entries = (
        list(slim.RETAINED_P2RANK_MODELS)
        + list(slim.OMITTED_P2RANK_MODELS)
        + list(slim.OMITTED_JAVA_FILES)
        + ["vina/vina.exe"]
    )
    for rel in all_entries:
        p = ref_tools / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"SYNTHETIC:{rel}".encode())
        files[rel] = sha256(p)

    payload = {
        "schema_version": 1,
        "tools": {"p2rank": {"variant": "ankora-vecmath-1.5.2-only-v1"}},
        "files": files,
    }
    (ref_tools / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    ref_sha = sha256(ref_tools / "payload.json")

    dest_tools = tmp_path / "dest_tools"
    with (
        patch.object(slim, "PAYLOAD_SHA256", ref_sha),
        patch.object(
            slim,
            "verify_tree",
            side_effect=lambda p: json.loads((p / "payload.json").read_text()),
        ),
    ):
        slim_sha = slim.stage_slim_tools(ref_tools, dest_tools)

    assert slim_sha == sha256(dest_tools / "payload.json")
    staged_payload = json.loads((dest_tools / "payload.json").read_text(encoding="utf-8"))
    assert staged_payload["tools"]["p2rank"]["variant"] == slim.SLIM_VARIANT
    for retained in slim.RETAINED_P2RANK_MODELS:
        assert retained in staged_payload["files"]
        assert (dest_tools / retained).is_file()
    for omitted in slim.OMITTED_TOOLS_FILES:
        assert omitted not in staged_payload["files"]
        assert not (dest_tools / omitted).exists()


def test_rewrite_nsis_script_preserves_offline_webview2_and_rewrites_resources(
    tmp_path: Path,
) -> None:
    slim_res = tmp_path / "slim_res"
    (slim_res / "backend").mkdir(parents=True)
    (slim_res / "complete-legal").mkdir(parents=True)
    (slim_res / "backend/ankora-backend.exe").write_bytes(b"SYNTHETIC_BACKEND")
    (slim_res / "complete-legal/ANKORA_LICENSE.txt").write_bytes(b"SYNTHETIC_LICENSE")
    desktop_exe = tmp_path / "ankora-desktop.exe"
    desktop_exe.write_bytes(b"SYNTHETIC_DESKTOP")

    rewritten = slim.rewrite_nsis_script(
        SYNTHETIC_NSI,
        slim_resources=slim_res,
        desktop_exe=desktop_exe,
        dictionary_mb=128,
    )
    assert '!define INSTALLWEBVIEW2MODE "offlineInstaller"' in rewritten
    assert "SetCompressorDictSize 128" in rewritten
    assert '!define OUTFILE "Ankora_0.1.0_x64-setup.exe"' in rewritten
    assert "/oname=backend\\ankora-backend.exe" in rewritten
    assert "/oname=legal\\ANKORA_LICENSE.txt" in rewritten
    assert "old.txt" not in rewritten


def test_verify_complete_accepts_slim_companion_archive_layout(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "payload.json").write_text("synthetic slim runtime", encoding="utf-8")
    payload_sha = sha256(tools / "payload.json")

    legal_dir = tmp_path / "legal"
    legal_dir.mkdir()
    comp_file = legal_dir / "SCIENTIFIC_SOURCE_COMPANION.json"
    comp_file.write_text("synthetic companion", encoding="utf-8")
    comp_sha = sha256(comp_file)

    inv_file = legal_dir / "THIRD_PARTY_INVENTORY.json"
    inv_file.write_text(
        json.dumps(
            {
                "scientific_payload_sha256": payload_sha,
                "excluded_external_tools": ["GNINA"],
                "components": [
                    {"name": "AutoDock Vina"},
                    {"name": "AutoGrid4"},
                    {"name": "AutoDock4"},
                    {"name": "AutoDock-GPU"},
                    {"name": "P2Rank"},
                    {"name": "Eclipse Temurin JRE"},
                    {"name": "Microsoft Edge WebView2 Evergreen"},
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "scientific_payload_sha256": payload_sha,
        "source_distribution": "companion-archive",
        "gpu_source_sha256": legal.GPU_SOURCE_SHA256,
        "files": {
            "SCIENTIFIC_SOURCE_COMPANION.json": comp_sha,
            "THIRD_PARTY_INVENTORY.json": sha256(inv_file),
        },
    }
    (legal_dir / "COMPLETE_LEGAL_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with (
        patch.object(legal, "verify_tree"),
        patch.object(legal, "SLIM_PAYLOAD_SHA256", payload_sha),
        patch.object(legal, "COMPANION_SHA256", comp_sha),
    ):
        legal.verify_complete(legal_dir, tools)
