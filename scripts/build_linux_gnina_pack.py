"""Build the verified offline Linux GNINA 1.3.3 + CUDA 12.8 + cuDNN 9.25 pack."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_LOCK_PATH = REPO_ROOT / "resources" / "linux-gnina-cuda12-pack.lock.json"
DEFAULT_GNINA_BINARY = REPO_ROOT / "build" / "linux-runtime" / "upstream" / "gnina.cuda12.8.static"
DEFAULT_CUDA_LIB_DIR = Path("/usr/local/cuda-12.8/targets/x86_64-linux/lib")
DEFAULT_CUDNN_LIB_DIR = Path("/usr/lib/x86_64-linux-gnu")
DEFAULT_CUDA_LICENSE = Path("/usr/share/doc/cuda-cudart-12-8/copyright")
DEFAULT_CUDNN_LICENSE = Path("/usr/share/doc/libcudnn9-cuda-12/copyright")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "linux-runtime"
DEFAULT_PACK_FILENAME = "Ankora_0.1.0_gnina-cuda12-pack.tar.zst"

GPL_SOURCE_OFFER_TEXT = """Ankora Offline GNINA 1.3.3 Pack — Source Code & License Notice
================================================================

1. GNINA 1.3.3 (`bin/gnina`)
   Upstream project: https://github.com/gnina/gnina
   Declared license: Dual Apache License 2.0 OR GNU General Public License v2.0 (GPL-2.0-only).
   Because the official upstream GNINA 1.3.3 binary links Open Babel 3 (GPL-2.0-only),
   Ankora distributes GNINA as a separate process boundary executed via CLI arguments
   and provides the complete corresponding machine-readable source code for both
   GNINA v1.3.3 (`gnina-source.tar.gz`) and Open Babel 3 (`openbabel-source.tar.gz`)
   in `Ankora_0.1.0_linux-sources-companion.zip` alongside every Ankora Linux release.

2. NVIDIA CUDA 12.8 & cuDNN 9.25 Runtime Shared Libraries (`lib/*.so*`)
   Redistributed strictly as unmodified user-space runtime `.so` libraries under:
   - NVIDIA CUDA SDK License Agreement Section 2.6, Attachment A (`licenses/NVIDIA_CUDA_12_8_EULA.txt`)
   - NVIDIA cuDNN License Supplement Chapter 8, Section 2 (`licenses/NVIDIA_CUDNN_9_LICENSE.txt`)
   Kernel/user-mode driver components (`libcuda.so*`, `libnvidia-ml.so*`,
   `libnvidia-ptxjitcompiler.so*`) are never bundled; the host Linux NVIDIA driver
   provides `libcuda.so.1` at runtime when CUDA execution is requested.
"""


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _resolve_zstd_executable() -> str:
    sibling = Path(sys.executable).resolve().parent / "zstd"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("zstd")
    if found:
        return found
    raise FileNotFoundError("zstd CLI executable was not found on PATH or beside sys.executable.")


def _verify_file(path: Path, *, expected_sha256: str, expected_size: int, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required {label}: {path}")
    actual_sha256, actual_size = _sha256_and_size(path)
    if actual_size != expected_size:
        raise ValueError(
            f"Size mismatch for {label} ({path.name}): expected {expected_size}, got {actual_size}"
        )
    if actual_sha256 != expected_sha256.lower():
        raise ValueError(
            f"SHA-256 mismatch for {label} ({path.name}): "
            f"expected {expected_sha256.lower()}, got {actual_sha256}"
        )


def _add_bytes_to_tar(tar: tarfile.TarFile, *, arcname: str, payload: bytes, mode: int) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.type = tarfile.REGTYPE
    info.size = len(payload)
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tar.addfile(info, io.BytesIO(payload))


def _add_file_to_tar(tar: tarfile.TarFile, *, arcname: str, source_path: Path, mode: int) -> None:
    stat_res = source_path.stat()
    info = tarfile.TarInfo(name=arcname)
    info.type = tarfile.REGTYPE
    info.size = stat_res.st_size
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    with source_path.open("rb") as stream:
        tar.addfile(info, stream)


def _add_symlink_to_tar(tar: tarfile.TarFile, *, arcname: str, linkname: str) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.type = tarfile.SYMTYPE
    info.linkname = linkname
    info.size = 0
    info.mode = 0o777
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tar.addfile(info)


def split_archive_parts(archive_path: Path, *, split_mib: int) -> list[dict[str, Any]]:
    if split_mib <= 0:
        raise ValueError("split_mib must be positive.")
    chunk_bytes = split_mib * 1024 * 1024
    parts: list[dict[str, Any]] = []
    for stale in archive_path.parent.glob(f"{archive_path.name}.part*"):
        stale.unlink()
    with archive_path.open("rb") as src:
        index = 1
        while True:
            first_block = src.read(min(1024 * 1024, chunk_bytes))
            if not first_block:
                break
            part_path = archive_path.parent / f"{archive_path.name}.part{index:02d}"
            digest = hashlib.sha256()
            written = 0
            with part_path.open("wb") as dst:
                dst.write(first_block)
                digest.update(first_block)
                written += len(first_block)
                while written < chunk_bytes:
                    block = src.read(min(1024 * 1024, chunk_bytes - written))
                    if not block:
                        break
                    dst.write(block)
                    digest.update(block)
                    written += len(block)
            parts.append(
                {
                    "filename": part_path.name,
                    "size_bytes": written,
                    "sha256": digest.hexdigest(),
                }
            )
            index += 1
    return parts


def build_gnina_pack(
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
    gnina_binary: Path = DEFAULT_GNINA_BINARY,
    cuda_lib_dir: Path = DEFAULT_CUDA_LIB_DIR,
    cudnn_lib_dir: Path = DEFAULT_CUDNN_LIB_DIR,
    cuda_license_path: Path = DEFAULT_CUDA_LICENSE,
    cudnn_license_path: Path = DEFAULT_CUDNN_LICENSE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    pack_filename: str = DEFAULT_PACK_FILENAME,
    zstd_level: int = 3,
    split_mib: int | None = None,
) -> dict[str, Any]:
    lock: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
    forbidden_prefixes = tuple(lock["forbidden_driver_prefixes"])

    exec_spec = lock["executable"]
    _verify_file(
        gnina_binary,
        expected_sha256=exec_spec["sha256"],
        expected_size=int(exec_spec["size_bytes"]),
        label="GNINA 1.3.3 executable",
    )

    resolved_libs: list[tuple[dict[str, Any], Path]] = []
    for lib_entry in lock["shared_libraries"]:
        filename = str(lib_entry["filename"])
        soname = str(lib_entry["soname"])
        if any(
            filename.startswith(prefix) or soname.startswith(prefix)
            for prefix in forbidden_prefixes
        ):
            raise ValueError(f"Forbidden driver library encountered in lockfile: {filename}")
        family = str(lib_entry["family"])
        search_dir = cuda_lib_dir if family.startswith("cuda-") else cudnn_lib_dir
        candidate = search_dir / filename
        # Resolve symlink if host library path points to versioned file via link, then verify bytes.
        resolved = candidate.resolve(strict=True) if candidate.exists() else candidate
        _verify_file(
            resolved,
            expected_sha256=str(lib_entry["sha256"]),
            expected_size=int(lib_entry["size_bytes"]),
            label=f"{family} shared library {filename}",
        )
        resolved_libs.append((lib_entry, resolved))

    license_sources = {
        "nvidia-cuda-12.8-eula": cuda_license_path,
        "nvidia-cudnn-9-supplement": cudnn_license_path,
    }
    resolved_licenses: list[tuple[dict[str, Any], Path]] = []
    for doc in lock["license_documents"]:
        doc_id = str(doc["id"])
        source_path = license_sources[doc_id]
        _verify_file(
            source_path,
            expected_sha256=str(doc["sha256"]),
            expected_size=int(doc["size_bytes"]),
            label=f"license document {doc_id}",
        )
        resolved_licenses.append((doc, source_path))

    gpl_offer_bytes = GPL_SOURCE_OFFER_TEXT.encode("utf-8")
    gpl_offer_sha256 = hashlib.sha256(gpl_offer_bytes).hexdigest()

    pack_metadata = {
        "schema_version": 1,
        "pack_id": lock["pack_id"],
        "platform": lock["platform"],
        "gnina_version": lock["gnina_version"],
        "executable": exec_spec,
        "shared_libraries": lock["shared_libraries"],
        "license_documents": [
            *lock["license_documents"],
            {
                "id": "gnina-gpl-source-offer",
                "relative_path": "licenses/GNINA_GPL_SOURCE_OFFER.txt",
                "size_bytes": len(gpl_offer_bytes),
                "sha256": gpl_offer_sha256,
            },
        ],
    }
    pack_metadata_bytes = (json.dumps(pack_metadata, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / pack_filename
    temp_archive_path = output_dir / f".{pack_filename}.tmp"
    if temp_archive_path.exists():
        temp_archive_path.unlink()

    zstd_exe = _resolve_zstd_executable()
    zstd_cmd = [zstd_exe, f"-{zstd_level}", "-T0", "-f", "-q", "-o", str(temp_archive_path)]
    proc = subprocess.Popen(
        zstd_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdin is not None
        with tarfile.open(fileobj=proc.stdin, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            _add_bytes_to_tar(
                tar, arcname="gnina-pack.json", payload=pack_metadata_bytes, mode=0o644
            )
            _add_file_to_tar(
                tar,
                arcname=str(exec_spec["relative_path"]),
                source_path=gnina_binary,
                mode=0o755,
            )
            for lib_entry, lib_path in resolved_libs:
                filename = str(lib_entry["filename"])
                soname = str(lib_entry["soname"])
                _add_file_to_tar(
                    tar,
                    arcname=f"lib/{filename}",
                    source_path=lib_path,
                    mode=0o644,
                )
                if soname != filename:
                    _add_symlink_to_tar(
                        tar,
                        arcname=f"lib/{soname}",
                        linkname=filename,
                    )
            for doc, doc_path in resolved_licenses:
                _add_file_to_tar(
                    tar,
                    arcname=str(doc["relative_path"]),
                    source_path=doc_path,
                    mode=0o644,
                )
            _add_bytes_to_tar(
                tar,
                arcname="licenses/GNINA_GPL_SOURCE_OFFER.txt",
                payload=gpl_offer_bytes,
                mode=0o644,
            )
        proc.stdin.close()
        proc.stdin = None
        _, stderr_bytes = proc.communicate()
        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"zstd compression failed ({proc.returncode}): {stderr_text}")
    except BaseException:
        proc.kill()
        proc.wait()
        if temp_archive_path.exists():
            temp_archive_path.unlink()
        raise

    temp_archive_path.replace(archive_path)
    archive_sha256, archive_size = _sha256_and_size(archive_path)
    parts = (
        split_archive_parts(archive_path, split_mib=split_mib) if split_mib is not None else []
    )
    receipt = {
        "pack_id": lock["pack_id"],
        "gnina_version": lock["gnina_version"],
        "archive_filename": archive_path.name,
        "archive_size_bytes": archive_size,
        "archive_sha256": archive_sha256,
        "shared_library_count": len(resolved_libs),
        "parts": parts,
    }
    receipt_path = output_dir / "gnina-pack-manifest.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--gnina-binary", type=Path, default=DEFAULT_GNINA_BINARY)
    parser.add_argument("--cuda-lib-dir", type=Path, default=DEFAULT_CUDA_LIB_DIR)
    parser.add_argument("--cudnn-lib-dir", type=Path, default=DEFAULT_CUDNN_LIB_DIR)
    parser.add_argument("--cuda-license", type=Path, default=DEFAULT_CUDA_LICENSE)
    parser.add_argument("--cudnn-license", type=Path, default=DEFAULT_CUDNN_LICENSE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pack-filename", default=DEFAULT_PACK_FILENAME)
    parser.add_argument("--zstd-level", type=int, default=3)
    parser.add_argument("--split-mib", type=int, default=None)
    args = parser.parse_args(argv)

    receipt = build_gnina_pack(
        lock_path=args.lock_file,
        gnina_binary=args.gnina_binary,
        cuda_lib_dir=args.cuda_lib_dir,
        cudnn_lib_dir=args.cudnn_lib_dir,
        cuda_license_path=args.cuda_license,
        cudnn_license_path=args.cudnn_license,
        output_dir=args.output_dir,
        pack_filename=args.pack_filename,
        zstd_level=args.zstd_level,
        split_mib=args.split_mib,
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
