"""Unit tests for the Linux .deb and portable .tar.zst installer builder (ADR-029 D3)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_installer_module() -> ModuleType:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "build_linux_installer",
        ROOT / "scripts" / "build_linux_installer.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_installer_module()
RELEASE_TAURI_CONFIG = _MOD.RELEASE_TAURI_CONFIG
_verify_elf_x86_64_no_home_rpath = _MOD._verify_elf_x86_64_no_home_rpath
build_deb_package = _MOD.build_deb_package
build_portable_tar_zst = _MOD.build_portable_tar_zst
compute_deb_depends = _MOD.compute_deb_depends
stage_application_bundle = _MOD.stage_application_bundle


def _synthetic_elf64_x86_64() -> bytes:
    e_ident = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    header_rest = struct.pack("<HHIQQQIHHHHHH", 3, 0x3E, 1, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0)
    return e_ident + header_rest + b"synthetic-elf-payload"


def test_release_tauri_config_has_strict_production_security_policy() -> None:
    cfg = json.loads(RELEASE_TAURI_CONFIG.read_text(encoding="utf-8"))
    assert cfg["productName"] == "Ankora"
    assert cfg["identifier"] == "science.ankora.workbench"
    assert cfg["build"]["frontendDist"] == "../dist"
    assert "devUrl" not in cfg["build"]
    csp = cfg["app"]["security"]["csp"]
    assert "connect-src 'self' http://127.0.0.1:8765" in csp
    assert "unsafe-eval" not in csp
    assert "127.0.0.1:1420" not in csp
    assert cfg["bundle"]["active"] is False


def test_compute_deb_depends_includes_appindicator_only_when_linked() -> None:
    base = compute_deb_depends(["libwebkit2gtk-4.1.so.0", "libgtk-3.so.0", "libc.so.6"])
    assert "libwebkit2gtk-4.1-0" in base
    assert "libgtk-3-0t64 | libgtk-3-0" in base
    assert "appindicator" not in base

    with_tray = compute_deb_depends(["libwebkit2gtk-4.1.so.0", "libayatana-appindicator3.so.1"])
    assert "libayatana-appindicator3-1 | libappindicator3-1" in with_tray


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux dpkg-deb & ELF packaging")
def test_stage_and_build_deb_and_portable_tar_zst_reject_forbidden_and_produce_valid_packages(
    tmp_path: Path,
) -> None:
    # Use minimal system ELF (`/bin/true`) as synthetic stand-in so `strip` and `readelf` work.
    desktop_bin = tmp_path / "ankora-desktop"
    shutil.copy2("/bin/true", desktop_bin)
    desktop_bin.chmod(0o755)
    needed = _verify_elf_x86_64_no_home_rpath(desktop_bin)
    assert any("libc.so" in lib for lib in needed)

    frozen_backend = tmp_path / "frozen-backend"
    (frozen_backend / "_internal").mkdir(parents=True)
    shutil.copy2("/bin/true", frozen_backend / "ankora-backend")
    (frozen_backend / "ankora-backend").chmod(0o755)
    real_so = frozen_backend / "_internal" / "libzstd.so.1.5.7"
    real_so.write_bytes(_synthetic_elf64_x86_64())
    (frozen_backend / "_internal" / "libzstd.so.1").symlink_to("libzstd.so.1.5.7")

    sci_tools = tmp_path / "sci-tools"
    (sci_tools / "vina").mkdir(parents=True)
    (sci_tools / "vina" / "vina").write_bytes(_synthetic_elf64_x86_64())
    (sci_tools / "vina" / "vina").chmod(0o755)

    legal_dir = tmp_path / "legal"
    legal_dir.mkdir()
    (legal_dir / "THIRD_PARTY_NOTICES.txt").write_text("Synthetic notices\n", encoding="utf-8")
    (legal_dir / "INSTALLATION_TERMS.txt").write_text("Synthetic terms\n", encoding="utf-8")

    # Verify forbidden driver library inside backend or tools is rejected!
    (sci_tools / "libcuda.so.1").write_bytes(b"forbidden")
    with pytest.raises(ValueError, match="Forbidden driver or GNINA file"):
        stage_application_bundle(
            target_app_dir=tmp_path / "bad-app",
            desktop_binary=desktop_bin,
            frozen_backend_dir=frozen_backend,
            scientific_tools_dir=sci_tools,
            legal_dir=legal_dir,
        )
    (sci_tools / "libcuda.so.1").unlink()

    staged_app = tmp_path / "staged-app"
    stage_application_bundle(
        target_app_dir=staged_app,
        desktop_binary=desktop_bin,
        frozen_backend_dir=frozen_backend,
        scientific_tools_dir=sci_tools,
        legal_dir=legal_dir,
    )
    assert (staged_app / "backend" / "_internal" / "libzstd.so.1").is_symlink()
    assert (staged_app / "backend" / "tools" / "vina" / "vina").is_file()

    # Build .deb and inspect via dpkg-deb
    deb_path = tmp_path / "Ankora_0.1.0_amd64.deb"
    build_deb_package(
        staged_app_dir=staged_app,
        version="0.1.0",
        depends=compute_deb_depends(needed),
        work_dir=tmp_path / "work-deb",
        output_deb=deb_path,
    )
    assert deb_path.is_file()
    info = subprocess.run(
        ["dpkg-deb", "--info", str(deb_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Package: ankora" in info
    assert "Architecture: amd64" in info
    contents = subprocess.run(
        ["dpkg-deb", "--contents", str(deb_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "./usr/bin/ankora" in contents
    assert "./usr/lib/ankora/ankora-desktop" in contents
    assert "./usr/lib/ankora/backend/ankora-backend" in contents
    assert "./usr/share/applications/ankora.desktop" in contents

    # Build portable .tar.zst and verify extraction preserves symlink + launcher
    portable_path = tmp_path / "Ankora_0.1.0_linux_x86_64.tar.zst"
    build_portable_tar_zst(
        staged_app_dir=staged_app,
        version="0.1.0",
        work_dir=tmp_path / "work-portable",
        output_tar_zst=portable_path,
    )
    assert portable_path.is_file()
    zstd_exe = Path(sys.executable).resolve().parent / "zstd"
    zstd_bin = str(zstd_exe) if zstd_exe.is_file() else shutil.which("zstd")
    assert zstd_bin is not None
    decomp = subprocess.run(
        [zstd_bin, "-d", "-c", str(portable_path)],
        capture_output=True,
        check=True,
    )
    import io

    with tarfile.open(fileobj=io.BytesIO(decomp.stdout), mode="r:") as tar:
        names = {m.name: m for m in tar.getmembers()}
        assert "Ankora-0.1.0-linux-x86_64/ankora" in names
        assert names["Ankora-0.1.0-linux-x86_64/backend/_internal/libzstd.so.1"].issym()
        assert os.path.basename(
            names["Ankora-0.1.0-linux-x86_64/backend/_internal/libzstd.so.1"].linkname
        ) == "libzstd.so.1.5.7"
