"""Tests for the Linux offline GNINA 1.3.3 + CUDA 12.8 / cuDNN 9.25 pack."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankora_backend.adapters.tools.discovery import discover_tool
from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.services.gnina_pack import (
    DEFAULT_GNINA_PACK_SPEC,
    GninaPackService,
    GninaPackSpec,
    LicenseDocumentSpec,
    SharedLibrarySpec,
    discover_verified_packaged_gnina,
    gnina_subprocess_environment,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "resources" / "linux-gnina-cuda12-pack.lock.json"


def _synthetic_x86_64_elf_bytes(marker: bytes = b"synthetic-gnina-fixture") -> bytes:
    """Construct a minimal synthetic ELF64 x86-64 header for non-executing discovery tests."""
    # e_ident (16B): magic + ELFCLASS64(2) + ELFDATA2LSB(1) + EV_CURRENT(1)
    e_ident = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    # e_type=ET_DYN(3), e_machine=EM_X86_64(0x3E), e_version=1
    header_rest = struct.pack("<HHIQQQIHHHHHH", 3, 0x3E, 1, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0)
    return e_ident + header_rest + marker


def _make_synthetic_spec() -> tuple[GninaPackSpec, dict[str, bytes]]:
    exe_bytes = _synthetic_x86_64_elf_bytes(b"gnina-1.3.3-synthetic")
    cudart_bytes = _synthetic_x86_64_elf_bytes(b"libcudart-synthetic")
    cudnn_bytes = _synthetic_x86_64_elf_bytes(b"libcudnn-synthetic")
    cuda_lic = b"Synthetic NVIDIA CUDA 12.8 EULA fixture\n"
    cudnn_lic = b"Synthetic NVIDIA cuDNN 9 Supplement fixture\n"

    files = {
        "bin/gnina": exe_bytes,
        "lib/libcudart.so.12.8.90": cudart_bytes,
        "lib/libcudnn.so.9.25.0": cudnn_bytes,
        "licenses/NVIDIA_CUDA_12_8_EULA.txt": cuda_lic,
        "licenses/NVIDIA_CUDNN_9_LICENSE.txt": cudnn_lic,
    }
    spec = GninaPackSpec(
        pack_id="synthetic-gnina-pack-test",
        gnina_version="1.3.3",
        executable_relative_path="bin/gnina",
        executable_size_bytes=len(exe_bytes),
        executable_sha256=hashlib.sha256(exe_bytes).hexdigest(),
        forbidden_driver_prefixes=(
            "libcuda.so",
            "libnvidia-ml.so",
            "libnvidia-ptxjitcompiler.so",
        ),
        shared_libraries=(
            SharedLibrarySpec(
                soname="libcudart.so.12",
                filename="libcudart.so.12.8.90",
                family="cuda-12.8",
                size_bytes=len(cudart_bytes),
                sha256=hashlib.sha256(cudart_bytes).hexdigest(),
            ),
            SharedLibrarySpec(
                soname="libcudnn.so.9",
                filename="libcudnn.so.9.25.0",
                family="cudnn-9.25",
                size_bytes=len(cudnn_bytes),
                sha256=hashlib.sha256(cudnn_bytes).hexdigest(),
            ),
        ),
        license_documents=(
            LicenseDocumentSpec(
                doc_id="nvidia-cuda-12.8-eula",
                relative_path="licenses/NVIDIA_CUDA_12_8_EULA.txt",
                size_bytes=len(cuda_lic),
                sha256=hashlib.sha256(cuda_lic).hexdigest(),
            ),
            LicenseDocumentSpec(
                doc_id="nvidia-cudnn-9-supplement",
                relative_path="licenses/NVIDIA_CUDNN_9_LICENSE.txt",
                size_bytes=len(cudnn_lic),
                sha256=hashlib.sha256(cudnn_lic).hexdigest(),
            ),
        ),
    )
    return spec, files


def _write_tar_zst(
    dest: Path,
    *,
    spec: GninaPackSpec,
    files: dict[str, bytes],
    extra_entries: list[tuple[str, bytes | None, str | None]] | None = None,
) -> Path:
    zstd_exe = Path(sys.executable).resolve().parent / "zstd"
    zstd_bin = str(zstd_exe) if zstd_exe.is_file() else shutil.which("zstd")
    assert zstd_bin is not None, "zstd CLI required for test archive creation"

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        manifest = json.dumps(
            {
                "schema_version": 1,
                "pack_id": spec.pack_id,
                "gnina_version": spec.gnina_version,
            }
        ).encode("utf-8")
        info = tarfile.TarInfo("gnina-pack.json")
        info.size = len(manifest)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(manifest))

        for rel_path, payload in files.items():
            reg = tarfile.TarInfo(rel_path)
            reg.size = len(payload)
            reg.mode = 0o755 if rel_path == "bin/gnina" else 0o644
            tar.addfile(reg, io.BytesIO(payload))

        for lib in spec.shared_libraries:
            sym = tarfile.TarInfo(f"lib/{lib.soname}")
            sym.type = tarfile.SYMTYPE
            sym.linkname = lib.filename
            sym.mode = 0o777
            tar.addfile(sym)

        offer = b"Synthetic GPL source offer\n"
        offer_info = tarfile.TarInfo("licenses/GNINA_GPL_SOURCE_OFFER.txt")
        offer_info.size = len(offer)
        offer_info.mode = 0o644
        tar.addfile(offer_info, io.BytesIO(offer))

        for name, data, link_target in extra_entries or []:
            extra = tarfile.TarInfo(name)
            if link_target is not None:
                extra.type = tarfile.SYMTYPE
                extra.linkname = link_target
                tar.addfile(extra)
            else:
                assert data is not None
                extra.size = len(data)
                extra.mode = 0o644
                tar.addfile(extra, io.BytesIO(data))

    completed = subprocess.run(
        [zstd_bin, "-1", "-f", "-q", "-o", str(dest)],
        input=tar_buf.getvalue(),
        capture_output=True,
        check=True,
    )
    assert completed.returncode == 0
    return dest


def test_embedded_gnina_pack_spec_matches_tracked_lockfile() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert DEFAULT_GNINA_PACK_SPEC.pack_id == lock["pack_id"]
    assert DEFAULT_GNINA_PACK_SPEC.gnina_version == lock["gnina_version"]
    assert DEFAULT_GNINA_PACK_SPEC.executable_relative_path == lock["executable"]["relative_path"]
    assert DEFAULT_GNINA_PACK_SPEC.executable_size_bytes == lock["executable"]["size_bytes"]
    assert DEFAULT_GNINA_PACK_SPEC.executable_sha256 == lock["executable"]["sha256"]
    assert list(DEFAULT_GNINA_PACK_SPEC.forbidden_driver_prefixes) == lock[
        "forbidden_driver_prefixes"
    ]
    assert [
        {
            "soname": lib.soname,
            "filename": lib.filename,
            "family": lib.family,
            "size_bytes": lib.size_bytes,
            "sha256": lib.sha256,
        }
        for lib in DEFAULT_GNINA_PACK_SPEC.shared_libraries
    ] == [
        {
            "soname": entry["soname"],
            "filename": entry["filename"],
            "family": entry["family"],
            "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"],
        }
        for entry in lock["shared_libraries"]
    ]
    assert [
        {
            "id": doc.doc_id,
            "relative_path": doc.relative_path,
            "size_bytes": doc.size_bytes,
            "sha256": doc.sha256,
        }
        for doc in DEFAULT_GNINA_PACK_SPEC.license_documents
    ] == lock["license_documents"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only GNINA offline pack")
def test_zstd_streaming_import_and_isolated_ld_library_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, files = _make_synthetic_spec()
    archive = _write_tar_zst(tmp_path / "synthetic-pack.tar.zst", spec=spec, files=files)
    toolchains = tmp_path / "toolchains"
    service = GninaPackService(toolchains_root=toolchains, spec=spec)

    initial = service.status()
    assert initial.supported is True
    assert initial.installed is False

    imported = service.import_pack(str(archive))
    assert imported.installed is True
    assert imported.shared_library_count == 2
    assert imported.executable_sha256 == spec.executable_sha256
    assert imported.executable_path is not None

    exe_path = Path(imported.executable_path)
    assert exe_path.is_file()
    assert (service.install_dir / "lib" / "libcudart.so.12").is_symlink()
    assert os.readlink(service.install_dir / "lib" / "libcudart.so.12") == "libcudart.so.12.8.90"

    discovered = discover_verified_packaged_gnina(service=service)
    assert discovered.available is True
    assert discovered.path == str(exe_path)
    assert discovered.version == "1.3.3"
    assert discovered.architecture == "x86_64"

    env = gnina_subprocess_environment(
        exe_path,
        base_environment={"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/opt/existing"},
        service=service,
    )
    assert env is not None
    assert env["LD_LIBRARY_PATH"] == f"{service.install_dir / 'lib'}:/opt/existing"

    # Frozen PyInstaller bootloader sets LD_LIBRARY_PATH=_internal and LD_LIBRARY_PATH_ORIG.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/pyinstaller/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/wsl/lib")
    frozen_env = gnina_subprocess_environment(exe_path, service=service)
    assert frozen_env is not None
    assert frozen_env["LD_LIBRARY_PATH"] == f"{service.install_dir / 'lib'}:/usr/lib/wsl/lib"

    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    frozen_clean_env = gnina_subprocess_environment(exe_path, service=service)
    assert frozen_clean_env is not None
    assert frozen_clean_env["LD_LIBRARY_PATH"] == str((service.install_dir / "lib").resolve())
    monkeypatch.delattr(sys, "frozen", raising=False)

    # Non-pack executables in developer mode leave environment untouched (None).
    other_exe = tmp_path / "other-gnina"
    other_exe.write_bytes(files["bin/gnina"])
    other_exe.chmod(0o755)
    assert gnina_subprocess_environment(other_exe, service=service) is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only GNINA offline pack")
def test_multipart_split_archive_import_and_missing_part_rejection(tmp_path: Path) -> None:
    spec, files = _make_synthetic_spec()
    full_archive = _write_tar_zst(tmp_path / "pack.tar.zst", spec=spec, files=files)
    raw = full_archive.read_bytes()
    midpoint = len(raw) // 2
    part1 = tmp_path / "Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part01"
    part2 = tmp_path / "Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part02"
    part1.write_bytes(raw[:midpoint])
    part2.write_bytes(raw[midpoint:])

    service = GninaPackService(toolchains_root=tmp_path / "toolchains", spec=spec)
    # Selecting either part01 or part02 resolves and streams the full sequence.
    status = service.import_pack(str(part2))
    assert status.installed is True

    # Removing part01 leaves a gap [2] != [1], failing closed.
    part1.unlink()
    with pytest.raises(AnkoraDomainError) as exc_info:
        service.import_pack(str(part2))
    assert exc_info.value.code == "GNINA_PACK_PARTS_INCOMPLETE"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only GNINA offline pack")
def test_tampered_digest_forbidden_driver_and_post_install_tamper_rejected(
    tmp_path: Path,
) -> None:
    spec, files = _make_synthetic_spec()
    toolchains = tmp_path / "toolchains"
    service = GninaPackService(toolchains_root=toolchains, spec=spec)

    # 1. Tampered library bytes -> GNINA_PACK_HASH_MISMATCH
    bad_files = dict(files)
    bad_files["lib/libcudnn.so.9.25.0"] = bad_files["lib/libcudnn.so.9.25.0"][:-1] + b"X"
    bad_archive = _write_tar_zst(tmp_path / "tampered.tar.zst", spec=spec, files=bad_files)
    with pytest.raises(AnkoraDomainError) as exc_hash:
        service.import_pack(str(bad_archive))
    assert exc_hash.value.code == "GNINA_PACK_HASH_MISMATCH"
    assert list(toolchains.glob(".gnina-pack-staging-*")) == []

    # 2. Forbidden libcuda.so.1 inside archive -> GNINA_PACK_FORBIDDEN_DRIVER_LIBRARY
    driver_archive = _write_tar_zst(
        tmp_path / "driver.tar.zst",
        spec=spec,
        files=files,
        extra_entries=[("lib/libcuda.so.1", b"forbidden", None)],
    )
    with pytest.raises(AnkoraDomainError) as exc_drv:
        service.import_pack(str(driver_archive))
    assert exc_drv.value.code == "GNINA_PACK_FORBIDDEN_DRIVER_LIBRARY"

    # 3. Path traversal inside archive -> GNINA_PACK_INVALID_PATH
    traversal_archive = _write_tar_zst(
        tmp_path / "traversal.tar.zst",
        spec=spec,
        files=files,
        extra_entries=[("../escape.txt", b"escape", None)],
    )
    with pytest.raises(AnkoraDomainError) as exc_path:
        service.import_pack(str(traversal_archive))
    assert exc_path.value.code == "GNINA_PACK_INVALID_PATH"

    # 4. Valid install followed by post-install rogue file in lib/ -> fails closed!
    valid_archive = _write_tar_zst(tmp_path / "valid.tar.zst", spec=spec, files=files)
    installed = service.import_pack(str(valid_archive))
    assert installed.installed is True
    assert installed.executable_path is not None

    rogue_driver = service.install_dir / "lib" / "libcuda.so.1"
    rogue_driver.write_bytes(b"rogue")
    tampered_status = service.status()
    assert tampered_status.installed is False
    assert tampered_status.verification_error is not None
    with pytest.raises(AnkoraDomainError) as exc_post:
        gnina_subprocess_environment(Path(installed.executable_path), service=service)
    assert exc_post.value.code == "GNINA_PACK_INTEGRITY_FAILED"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only GNINA offline pack")
def test_packaged_mode_discovery_is_fail_closed_and_api_origin_guarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, files = _make_synthetic_spec()
    fake_path_dir = tmp_path / "unverified-bin"
    fake_path_dir.mkdir()
    unverified_gnina = fake_path_dir / "gnina"
    unverified_gnina.write_bytes(files["bin/gnina"])
    unverified_gnina.chmod(0o755)

    toolchains = tmp_path / "toolchains"
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANKORA_TOOLCHAINS_DIR", str(toolchains))
    monkeypatch.setenv("ANKORA_APP_MODE", "packaged")
    monkeypatch.setenv("PATH", str(fake_path_dir))
    monkeypatch.setattr("ankora_backend.services.gnina_pack.DEFAULT_GNINA_PACK_SPEC", spec)
    # Rebind default arg on GninaPackService.__init__ via monkeypatch for endpoint testing
    orig_init = GninaPackService.__init__

    def _patched_init(
        self: GninaPackService,
        *,
        toolchains_root: Path | None = None,
        spec: GninaPackSpec = spec,
    ) -> None:
        orig_init(self, toolchains_root=toolchains_root, spec=spec)

    monkeypatch.setattr(GninaPackService, "__init__", _patched_init)

    # Even with an executable `gnina` on PATH, packaged mode refuses unverified PATH lookup!
    assert discover_tool("gnina").available is False

    archive = _write_tar_zst(tmp_path / "api-pack.tar.zst", spec=spec, files=files)
    app = create_app()
    with TestClient(app) as client:
        status_before = client.get("/api/v1/tools/gnina-pack/status")
        assert status_before.status_code == 200
        assert status_before.json()["installed"] is False

        # Missing Origin header is blocked by require_known_origin_for_uploads
        forbidden = client.post(
            "/api/v1/tools/gnina-pack/import",
            json={"archive_path": str(archive)},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "UPLOAD_ORIGIN_NOT_ALLOWED"

        allowed = client.post(
            "/api/v1/tools/gnina-pack/import",
            json={"archive_path": str(archive)},
            headers={"Origin": "http://tauri.localhost"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["installed"] is True

        tools_after = client.get("/api/v1/tools")
        assert tools_after.status_code == 200
        gnina_tool = tools_after.json()["gnina"]
        assert gnina_tool["available"] is True
        assert gnina_tool["version"] == "1.3.3"
        assert gnina_tool["sha256"] == spec.executable_sha256
