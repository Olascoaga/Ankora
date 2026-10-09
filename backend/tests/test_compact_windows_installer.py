"""Synthetic NSIS fixtures; no real installer or scientific payload is changed."""

import subprocess

import pytest
from scripts.compact_windows_installer import build, compact_script, model_script

SCRIPT = """!define OUTFILE "nsis-output.exe"
!define INSTALLWEBVIEW2MODE "offlineInstaller"
  SetCompressor /SOLID "lzma"
File "model.zst"
File "corresponding-source.zip"
File "backend.exe"
"""


@pytest.mark.parametrize("size", [32, 64, 128])
def test_compaction_changes_only_compression_and_output(size):
    result = compact_script(SCRIPT, size)
    restored = result.replace(f"\n  SetCompressorDictSize {size}", "").replace(
        "Ankora_0.1.0_x64-compact-setup.exe", "nsis-output.exe"
    )
    assert restored == SCRIPT


@pytest.mark.parametrize(
    "text",
    [
        SCRIPT.replace('"lzma"', '"zlib"'),
        SCRIPT + '  SetCompressor /SOLID "lzma"',
        SCRIPT + "SetCompressorDictSize 8",
        SCRIPT.replace("offlineInstaller", "downloadBootstrapper"),
        SCRIPT.replace("nsis-output.exe", "old-setup.exe"),
    ],
)
def test_rejects_changed_upstream_or_network_installation(text):
    with pytest.raises(ValueError):
        compact_script(text, 64)


def test_rejects_unreviewed_memory_budget():
    with pytest.raises(ValueError):
        compact_script(SCRIPT, 4096)


def test_model_dedup_preserves_other_files_and_runs_before_registration():
    synthetic = (
        SCRIPT
        + (
            '    File /a "/oname=backend\\tools\\p2rank-2.5.1\\models\\default'
            '\\model.zst" "synthetic-model"\n'
        )
        + """
  WriteUninstaller "$INSTDIR\\uninstall.exe"
  WriteRegStr SHCTX "synthetic" "" "$INSTDIR"
"""
    )
    result = model_script(synthetic, ("default",))
    assert SCRIPT in result
    assert '"synthetic-model"' not in result
    assert result.index("--worker installer-resources") < result.index("WriteRegStr")
    assert "SetErrorLevel 1" in result and "Abort" in result
    with pytest.raises(ValueError, match="entry changed"):
        model_script(result, ("default",))


def test_output_is_create_only_and_original_is_preserved(tmp_path):
    original = tmp_path / "original.exe"
    original.write_bytes(b"SYNTHETIC original installer")
    source = tmp_path / "installer.nsi"
    source.write_text(SCRIPT + f'File "{original}"\n')
    output = tmp_path / "candidate"
    output.mkdir()
    with pytest.raises(FileExistsError):
        build(source, output, tmp_path / "compiler.exe", 64, [original])
    assert original.read_bytes() == b"SYNTHETIC original installer"
    assert not list(output.iterdir())


def test_compiler_failure_never_touches_protected_original(tmp_path, monkeypatch):
    original = tmp_path / "original.exe"
    original.write_bytes(b"SYNTHETIC original installer")
    source = tmp_path / "installer.nsi"
    source.write_text(SCRIPT + f'File "{original}"\n')

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "synthetic compiler")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        build(source, tmp_path / "candidate", tmp_path / "compiler.exe", 64, [original])
    assert original.read_bytes() == b"SYNTHETIC original installer"
