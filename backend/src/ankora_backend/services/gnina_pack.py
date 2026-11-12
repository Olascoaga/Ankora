"""Offline Linux GNINA 1.3.3 + CUDA 12.8 / cuDNN 9.25 pack importer and verifier."""

from __future__ import annotations

import ctypes
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ankora_backend.adapters.tools.discovery import (
    DiscoveredTool,
    _is_native_executable,
    _is_wsl_drive_path,
    _read_elf_architecture,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.gnina_pack import GninaPackStatus

_STAGE = "gnina_pack"
_IMPORT_LOCK = threading.Lock()
_PART_SUFFIX_RE = re.compile(r"^(?P<stem>.+)\.part(?P<index>\d{2,4})$")
_INSTALL_SUBDIR = "gnina-1.3.3-cuda12"
_RECEIPT_FILENAME = "installed-pack.json"
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_GPL_OFFER_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class SharedLibrarySpec:
    soname: str
    filename: str
    family: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LicenseDocumentSpec:
    doc_id: str
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class GninaPackSpec:
    pack_id: str
    gnina_version: str
    executable_relative_path: str
    executable_size_bytes: int
    executable_sha256: str
    forbidden_driver_prefixes: tuple[str, ...]
    shared_libraries: tuple[SharedLibrarySpec, ...]
    license_documents: tuple[LicenseDocumentSpec, ...]


DEFAULT_GNINA_PACK_SPEC = GninaPackSpec(
    pack_id="gnina-1.3.3-cuda12.8-cudnn9.25-linux-x86_64",
    gnina_version="1.3.3",
    executable_relative_path="bin/gnina",
    executable_size_bytes=2056131000,
    executable_sha256="3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172",
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
            size_bytes=728800,
            sha256="c3a75b33af334a3486d197dbd1584a2985183ba4688d237a2be5f2f679329920",
        ),
        SharedLibrarySpec(
            soname="libcusparse.so.12",
            filename="libcusparse.so.12.5.8.93",
            family="cuda-12.8",
            size_bytes=386594784,
            sha256="10bf811463c0c67bfe6f1016878392687664bc77fbfeed3130f3a0ecf2b0559f",
        ),
        SharedLibrarySpec(
            soname="libcufft.so.11",
            filename="libcufft.so.11.3.3.83",
            family="cuda-12.8",
            size_bytes=278678584,
            sha256="db7a606984097fdb7ad04f4bd09ade30b493e7cb360bb400037ff634dc208425",
        ),
        SharedLibrarySpec(
            soname="libcublas.so.12",
            filename="libcublas.so.12.8.5.5",
            family="cuda-12.8",
            size_bytes=116388640,
            sha256="18a5df540d156e9aff0363776fefab7884b614f122847b51c3eb1da772048e5c",
        ),
        SharedLibrarySpec(
            soname="libcublasLt.so.12",
            filename="libcublasLt.so.12.8.5.5",
            family="cuda-12.8",
            size_bytes=751775824,
            sha256="974927b9af78cadc0412ea3ab296da791af02c2dd0de5a35b5f0fbb8dc5d0a4d",
        ),
        SharedLibrarySpec(
            soname="libcusolver.so.11",
            filename="libcusolver.so.11.7.3.90",
            family="cuda-12.8",
            size_bytes=241587952,
            sha256="6e8b369baedbd20064e35fa3da5b3e0254959b0f81f9b1d6ee595199d5493b61",
        ),
        SharedLibrarySpec(
            soname="libnvJitLink.so.12",
            filename="libnvJitLink.so.12.8.93",
            family="cuda-12.8",
            size_bytes=94101392,
            sha256="0369e6867d44b800437de4e146d72c65afc6c75adf677a15c2ecd8e6a7ac135f",
        ),
        SharedLibrarySpec(
            soname="libcudnn.so.9",
            filename="libcudnn.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=129240,
            sha256="4f2e3feb0fc0448f7a1997c10a5fcb14cd5e5a72aff9d7c27c8ae68e56e88da3",
        ),
        SharedLibrarySpec(
            soname="libcudnn_adv.so.9",
            filename="libcudnn_adv.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=270760120,
            sha256="bc12a7d6e837ff8589ccdf37ba8ea928d7c5e174aebf8f94b4de5f50e546819f",
        ),
        SharedLibrarySpec(
            soname="libcudnn_cnn.so.9",
            filename="libcudnn_cnn.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=3705712,
            sha256="87740ddcda7ebe8db1518cc30abd0a53bcf8b93dbffe08d32f0c14efe43135ff",
        ),
        SharedLibrarySpec(
            soname="libcudnn_engines_precompiled.so.9",
            filename="libcudnn_engines_precompiled.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=576465888,
            sha256="c3eabb963610e07dcff2feb79049e3a82587019b86ba37d1a3839fe939f86428",
        ),
        SharedLibrarySpec(
            soname="libcudnn_engines_runtime_compiled.so.9",
            filename="libcudnn_engines_runtime_compiled.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=40171728,
            sha256="7595b2201c6201ce3e112dc75c32fc27710564965ea89f1640866c7769fdce67",
        ),
        SharedLibrarySpec(
            soname="libcudnn_engines_tensor_ir.so.9",
            filename="libcudnn_engines_tensor_ir.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=10464,
            sha256="ed39f9e3a9b1b82a661e9ccc88395201fa19cf35eff67255008af9c0301a8560",
        ),
        SharedLibrarySpec(
            soname="libcudnn_ext.so.9",
            filename="libcudnn_ext.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=1994200,
            sha256="5829f761a09d6cebcbc102ab22d54ccb026c72f4ac244c9c4864bd9900809720",
        ),
        SharedLibrarySpec(
            soname="libcudnn_graph.so.9",
            filename="libcudnn_graph.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=113679896,
            sha256="0fb28e041532ef4a9e17cfc99525d5647efce13916f32a902ab0ca01cea216c8",
        ),
        SharedLibrarySpec(
            soname="libcudnn_heuristic.so.9",
            filename="libcudnn_heuristic.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=59141648,
            sha256="368aba313690902cc60a3c4114487dffa46cfa73ec45bc81a8e8ef490767a3de",
        ),
        SharedLibrarySpec(
            soname="libcudnn_ops.so.9",
            filename="libcudnn_ops.so.9.25.0",
            family="cudnn-9.25",
            size_bytes=106704448,
            sha256="03ac6f2a688f8926dfcba08f54335f086898f44eed8cd3c126bf8d02c6b40414",
        ),
    ),
    license_documents=(
        LicenseDocumentSpec(
            doc_id="nvidia-cuda-12.8-eula",
            relative_path="licenses/NVIDIA_CUDA_12_8_EULA.txt",
            size_bytes=63021,
            sha256="e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07",
        ),
        LicenseDocumentSpec(
            doc_id="nvidia-cudnn-9-supplement",
            relative_path="licenses/NVIDIA_CUDNN_9_LICENSE.txt",
            size_bytes=29574,
            sha256="295a1b7118d3417f5d6a943e5f87b59e2a0631fb277129c3b15dee6248adc7cf",
        ),
    ),
)


class _ZstdInBuffer(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class _ZstdOutBuffer(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


def _pack_error(
    code: str,
    message: str,
    *,
    status_code: int = 422,
    **details: object,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=status_code,
        details=details,
    )


def _load_libzstd() -> ctypes.CDLL:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        candidates.append(Path(meipass) / "libzstd.so.1")
    candidates.extend(
        (
            Path(sys.prefix) / "lib" / "libzstd.so.1",
            Path("/lib/x86_64-linux-gnu/libzstd.so.1"),
            Path("/usr/lib/x86_64-linux-gnu/libzstd.so.1"),
        )
    )
    lib: ctypes.CDLL | None = None
    for candidate in candidates:
        if candidate.is_file():
            try:
                lib = ctypes.CDLL(str(candidate))
                break
            except OSError:
                continue
    if lib is None:
        try:
            lib = ctypes.CDLL("libzstd.so.1")
        except OSError as error:
            raise _pack_error(
                "GNINA_PACK_ZSTD_UNAVAILABLE",
                "Zstandard shared library (libzstd.so.1) could not be loaded.",
            ) from error

    lib.ZSTD_createDStream.argtypes = []
    lib.ZSTD_createDStream.restype = ctypes.c_void_p
    lib.ZSTD_initDStream.argtypes = [ctypes.c_void_p]
    lib.ZSTD_initDStream.restype = ctypes.c_size_t
    lib.ZSTD_freeDStream.argtypes = [ctypes.c_void_p]
    lib.ZSTD_freeDStream.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
    lib.ZSTD_getErrorName.restype = ctypes.c_char_p
    lib.ZSTD_decompressStream.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ZstdOutBuffer),
        ctypes.POINTER(_ZstdInBuffer),
    ]
    lib.ZSTD_decompressStream.restype = ctypes.c_size_t
    return lib


class ConcatenatedFileReader(io.RawIOBase):
    """Stream multiple split archive parts sequentially without temporary concatenation."""

    def __init__(self, parts: Sequence[Path]) -> None:
        super().__init__()
        if not parts:
            raise ValueError("At least one archive part is required.")
        self._parts = tuple(parts)
        self._index = 0
        self._current: io.BufferedReader | None = self._parts[0].open("rb")

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        if self.closed:
            raise ValueError("I/O operation on closed ConcatenatedFileReader.")
        view = memoryview(b).cast("B")
        if len(view) == 0:
            return 0
        while self._current is not None:
            count = self._current.readinto(view)
            if count:
                return count
            self._current.close()
            self._index += 1
            self._current = (
                self._parts[self._index].open("rb")
                if self._index < len(self._parts)
                else None
            )
        return 0

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


class ZstdStreamReader(io.RawIOBase):
    """Streaming Zstandard decompressor backed by libzstd.so.1."""

    def __init__(
        self,
        raw: io.RawIOBase | io.BufferedReader,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        super().__init__()
        self._raw = raw
        self._chunk_size = chunk_size
        self._lib = _load_libzstd()
        self._dstream: int | None = self._lib.ZSTD_createDStream()
        if not self._dstream:
            raise _pack_error(
                "GNINA_PACK_ZSTD_UNAVAILABLE",
                "Failed to allocate ZSTD_DStream.",
            )
        init_res = self._lib.ZSTD_initDStream(self._dstream)
        if self._lib.ZSTD_isError(init_res):
            err_name = (self._lib.ZSTD_getErrorName(init_res) or b"unknown").decode(
                "ascii", "replace"
            )
            self._free_dstream()
            raise _pack_error(
                "GNINA_PACK_ZSTD_UNAVAILABLE",
                f"Failed to initialize ZSTD_DStream: {err_name}",
            )
        self._in_chunk: ctypes.Array[ctypes.c_char] | None = None
        self._in_buf = _ZstdInBuffer(None, 0, 0)
        self._last_hint: int = 0
        self._saw_any_input = False
        self._eof = False

    def _free_dstream(self) -> None:
        if self._dstream is not None:
            self._lib.ZSTD_freeDStream(self._dstream)
            self._dstream = None

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        if self.closed or self._dstream is None:
            raise ValueError("I/O operation on closed ZstdStreamReader.")
        view = memoryview(b).cast("B")
        if len(view) == 0 or self._eof:
            return 0

        out_array = (ctypes.c_char * len(view)).from_buffer(view)
        out_buf = _ZstdOutBuffer(ctypes.cast(out_array, ctypes.c_void_p), len(view), 0)

        while out_buf.pos == 0:
            if self._in_buf.pos >= self._in_buf.size:
                chunk = self._raw.read(self._chunk_size)
                if not chunk:
                    if not self._saw_any_input or self._last_hint != 0:
                        raise _pack_error(
                            "GNINA_PACK_CORRUPT_ARCHIVE",
                            "The GNINA offline pack Zstandard stream is empty or truncated.",
                        )
                    self._eof = True
                    return 0
                self._saw_any_input = True
                self._in_chunk = (ctypes.c_char * len(chunk)).from_buffer_copy(chunk)
                self._in_buf = _ZstdInBuffer(
                    ctypes.cast(self._in_chunk, ctypes.c_void_p),
                    len(chunk),
                    0,
                )

            hint = self._lib.ZSTD_decompressStream(
                self._dstream,
                ctypes.byref(out_buf),
                ctypes.byref(self._in_buf),
            )
            if self._lib.ZSTD_isError(hint):
                err_name = (self._lib.ZSTD_getErrorName(hint) or b"unknown").decode(
                    "ascii", "replace"
                )
                raise _pack_error(
                    "GNINA_PACK_CORRUPT_ARCHIVE",
                    f"Zstandard decompression failed while reading GNINA pack: {err_name}",
                )
            self._last_hint = int(hint)

        return int(out_buf.pos)

    def close(self) -> None:
        try:
            self._free_dstream()
        finally:
            self._raw.close()
            super().close()

    def __del__(self) -> None:
        if getattr(self, "_dstream", None) is not None:
            self._free_dstream()


def _linux_x86_64_host() -> bool:
    return sys.platform.startswith("linux") and os.uname().machine.lower() in {"x86_64", "amd64"}


def packaged_gnina_mode() -> bool:
    return bool(getattr(sys, "frozen", False) or os.getenv("ANKORA_APP_MODE") == "packaged")


def toolchains_root_from_environment() -> Path:
    explicit = os.getenv("ANKORA_TOOLCHAINS_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    data_dir = os.getenv("ANKORA_DATA_DIR")
    if data_dir:
        return (Path(data_dir).expanduser().resolve().parent / "toolchains").resolve()
    return (Path.cwd() / ".ankora-toolchains").resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_member_path(name: str) -> str:
    cleaned = name.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("/")
    if not cleaned:
        return ""
    if "\\" in cleaned or cleaned.startswith("/"):
        raise _pack_error(
            "GNINA_PACK_INVALID_PATH",
            f"Archive entry uses an unsafe path: {name!r}",
        )
    posix = PurePosixPath(cleaned)
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise _pack_error(
            "GNINA_PACK_INVALID_PATH",
            f"Archive entry contains path traversal segments: {name!r}",
        )
    return posix.as_posix()


def _resolve_archive_parts(archive_path_raw: str) -> tuple[list[Path], str]:
    candidate = Path(archive_path_raw).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _pack_error(
            "GNINA_PACK_ARCHIVE_NOT_FOUND",
            "The selected GNINA offline pack file does not exist or cannot be read.",
            archive_path=archive_path_raw,
        ) from error
    if not resolved.is_file():
        raise _pack_error(
            "GNINA_PACK_ARCHIVE_NOT_FOUND",
            "The selected GNINA offline pack path is not a regular file.",
            archive_path=str(resolved),
        )

    part_match = _PART_SUFFIX_RE.match(resolved.name)
    if part_match is not None:
        stem_name = part_match.group("stem")
        parent = resolved.parent
        discovered: list[tuple[int, Path]] = []
        for sibling in parent.iterdir():
            m = _PART_SUFFIX_RE.match(sibling.name)
            if m is not None and m.group("stem") == stem_name and sibling.is_file():
                discovered.append((int(m.group("index")), sibling.resolve()))
        discovered.sort(key=lambda item: item[0])
        expected_indices = list(range(1, len(discovered) + 1))
        actual_indices = [idx for idx, _ in discovered]
        if not discovered or actual_indices != expected_indices:
            raise _pack_error(
                "GNINA_PACK_PARTS_INCOMPLETE",
                "Multi-part GNINA offline pack is missing one or more sequential .partNN files.",
                found_parts=[p.name for _, p in discovered],
            )
        compression = _compression_for_name(stem_name)
        return [p for _, p in discovered], compression

    compression = _compression_for_name(resolved.name)
    return [resolved], compression


def _compression_for_name(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith((".tar.zst", ".tzst", ".zst")):
        return "zst"
    if lower.endswith((".tar.gz", ".tgz")):
        return "gz"
    raise _pack_error(
        "GNINA_PACK_FORMAT_UNSUPPORTED",
        "Unsupported GNINA pack archive format; expected .tar.zst (or .tar.zst.part01).",
        filename=filename,
    )


class GninaPackService:
    """Manages installation, cryptographic verification, and isolated runtime lookup."""

    def __init__(
        self,
        *,
        toolchains_root: Path | None = None,
        spec: GninaPackSpec = DEFAULT_GNINA_PACK_SPEC,
    ) -> None:
        self._toolchains_root = (
            toolchains_root.expanduser().resolve()
            if toolchains_root is not None
            else toolchains_root_from_environment()
        )
        self._spec = spec

    @property
    def install_dir(self) -> Path:
        return self._toolchains_root / _INSTALL_SUBDIR

    def status(self) -> GninaPackStatus:
        if not _linux_x86_64_host():
            return GninaPackStatus(
                supported=False,
                installed=False,
                pack_id=self._spec.pack_id,
                gnina_version=self._spec.gnina_version,
            )
        target = self.install_dir
        if not target.exists():
            return GninaPackStatus(
                supported=True,
                installed=False,
                pack_id=self._spec.pack_id,
                gnina_version=self._spec.gnina_version,
            )
        try:
            receipt = self.verify_installed_pack()
        except AnkoraDomainError as error:
            return GninaPackStatus(
                supported=True,
                installed=False,
                pack_id=self._spec.pack_id,
                gnina_version=self._spec.gnina_version,
                install_dir=str(target),
                verification_error=error.message,
            )
        exe_path = target / self._spec.executable_relative_path
        return GninaPackStatus(
            supported=True,
            installed=True,
            pack_id=self._spec.pack_id,
            gnina_version=self._spec.gnina_version,
            install_dir=str(target),
            executable_path=str(exe_path),
            executable_sha256=self._spec.executable_sha256,
            shared_library_count=len(self._spec.shared_libraries),
            imported_at=str(receipt.get("imported_at")) if receipt.get("imported_at") else None,
        )

    def verify_installed_pack(self, *, force_rehash: bool = False) -> dict[str, Any]:
        if not _linux_x86_64_host():
            raise _pack_error(
                "GNINA_LINUX_ONLY",
                "The offline GNINA pack is supported only on Linux x86-64.",
            )
        target = self.install_dir
        if _is_wsl_drive_path(target):
            raise _pack_error(
                "GNINA_PACK_INVALID_TARGET",
                "GNINA toolchains directory must reside on a native Linux filesystem.",
            )
        receipt_path = target / _RECEIPT_FILENAME
        if not receipt_path.is_file() or receipt_path.is_symlink():
            raise _pack_error(
                "GNINA_PACK_NOT_INSTALLED",
                "GNINA offline pack receipt is missing.",
            )
        try:
            receipt: dict[str, Any] = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA pack receipt is unreadable or malformed.",
            ) from error

        if (
            receipt.get("pack_id") != self._spec.pack_id
            or receipt.get("gnina_version") != self._spec.gnina_version
        ):
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA pack identity does not match the required lock specification.",
            )

        exe_path = target / self._spec.executable_relative_path
        if exe_path.is_symlink() or not exe_path.is_file():
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA executable is missing or is a symbolic link.",
            )
        if not _is_native_executable(exe_path) or _read_elf_architecture(exe_path) != "x86_64":
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA executable is not a native Linux x86-64 ELF binary.",
            )
        exe_stat = exe_path.stat()
        recorded_exe = receipt.get("executable") or {}
        if (
            exe_stat.st_size != self._spec.executable_size_bytes
            or recorded_exe.get("sha256") != self._spec.executable_sha256
        ):
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA executable size or recorded SHA-256 does not match lockfile.",
            )
        if (
            force_rehash or recorded_exe.get("mtime_ns") != exe_stat.st_mtime_ns
        ) and _sha256_file(exe_path) != self._spec.executable_sha256:
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA executable SHA-256 verification failed.",
            )

        lib_dir = target / "lib"
        if not lib_dir.is_dir() or lib_dir.is_symlink():
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA pack lib/ directory is missing.",
            )

        recorded_libs = {
            str(entry.get("filename")): entry
            for entry in (receipt.get("shared_libraries") or [])
            if isinstance(entry, dict)
        }
        expected_lib_entries: set[str] = set()
        for lib_spec in self._spec.shared_libraries:
            expected_lib_entries.add(lib_spec.filename)
            expected_lib_entries.add(lib_spec.soname)
            lib_file = lib_dir / lib_spec.filename
            if lib_file.is_symlink() or not lib_file.is_file():
                raise _pack_error(
                    "GNINA_PACK_INTEGRITY_FAILED",
                    f"Missing required runtime shared library: {lib_spec.filename}",
                )
            lib_stat = lib_file.stat()
            rec_lib = recorded_libs.get(lib_spec.filename) or {}
            if (
                lib_stat.st_size != lib_spec.size_bytes
                or rec_lib.get("sha256") != lib_spec.sha256
            ):
                raise _pack_error(
                    "GNINA_PACK_INTEGRITY_FAILED",
                    f"Runtime library size or SHA-256 mismatch: {lib_spec.filename}",
                )
            if (
                force_rehash or rec_lib.get("mtime_ns") != lib_stat.st_mtime_ns
            ) and _sha256_file(lib_file) != lib_spec.sha256:
                raise _pack_error(
                    "GNINA_PACK_INTEGRITY_FAILED",
                    f"Runtime library SHA-256 verification failed: {lib_spec.filename}",
                )
            if lib_spec.soname != lib_spec.filename:
                soname_link = lib_dir / lib_spec.soname
                if not soname_link.is_symlink():
                    raise _pack_error(
                        "GNINA_PACK_INTEGRITY_FAILED",
                        f"Missing required SONAME symbolic link: {lib_spec.soname}",
                    )
                if os.readlink(soname_link) != lib_spec.filename:
                    raise _pack_error(
                        "GNINA_PACK_INTEGRITY_FAILED",
                        f"SONAME symbolic link {lib_spec.soname} points to unexpected target.",
                    )

        actual_lib_entries = set(os.listdir(lib_dir))
        unexpected = sorted(actual_lib_entries - expected_lib_entries)
        if unexpected:
            raise _pack_error(
                "GNINA_PACK_INTEGRITY_FAILED",
                "Installed GNINA pack lib/ contains unexpected or driver shared libraries.",
                unexpected_files=unexpected,
            )

        for doc_spec in self._spec.license_documents:
            doc_file = target / doc_spec.relative_path
            if doc_file.is_symlink() or not doc_file.is_file():
                raise _pack_error(
                    "GNINA_PACK_INTEGRITY_FAILED",
                    f"Missing required license notice: {doc_spec.relative_path}",
                )
            if doc_file.stat().st_size != doc_spec.size_bytes:
                raise _pack_error(
                    "GNINA_PACK_INTEGRITY_FAILED",
                    f"License notice size mismatch: {doc_spec.relative_path}",
                )

        return receipt

    def import_pack(self, archive_path: str) -> GninaPackStatus:
        if not _linux_x86_64_host():
            raise _pack_error(
                "GNINA_LINUX_ONLY",
                "The offline GNINA pack can be imported only on Linux x86-64.",
            )
        if _is_wsl_drive_path(self._toolchains_root):
            raise _pack_error(
                "GNINA_PACK_INVALID_TARGET",
                "GNINA toolchains directory must reside on a native Linux filesystem.",
            )
        if not _IMPORT_LOCK.acquire(blocking=False):
            raise _pack_error(
                "GNINA_PACK_IMPORT_IN_PROGRESS",
                "Another GNINA offline pack import is already running.",
                status_code=409,
            )
        try:
            parts, compression = _resolve_archive_parts(archive_path)
            self._toolchains_root.mkdir(parents=True, exist_ok=True)
            staging_dir = self._toolchains_root / f".gnina-pack-staging-{uuid.uuid4().hex}"
            staging_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
            backup_dir: Path | None = None
            try:
                self._extract_and_verify_into(staging_dir, parts=parts, compression=compression)
                target = self.install_dir
                if target.exists() or target.is_symlink():
                    backup_dir = self._toolchains_root / f".gnina-pack-old-{uuid.uuid4().hex}"
                    target.rename(backup_dir)
                try:
                    staging_dir.chmod(0o755)
                    staging_dir.rename(target)
                except BaseException:
                    if backup_dir is not None and backup_dir.exists() and not target.exists():
                        backup_dir.rename(target)
                    raise
                if backup_dir is not None and backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
            except BaseException:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
                raise
            return self.status()
        finally:
            _IMPORT_LOCK.release()

    def _extract_and_verify_into(
        self,
        staging_dir: Path,
        *,
        parts: Sequence[Path],
        compression: str,
    ) -> None:
        expected_regular: dict[str, tuple[int, str, int]] = {
            self._spec.executable_relative_path: (
                self._spec.executable_size_bytes,
                self._spec.executable_sha256,
                0o755,
            ),
        }
        expected_symlinks: dict[str, str] = {}
        for lib_spec in self._spec.shared_libraries:
            expected_regular[f"lib/{lib_spec.filename}"] = (
                lib_spec.size_bytes,
                lib_spec.sha256,
                0o644,
            )
            if lib_spec.soname != lib_spec.filename:
                expected_symlinks[f"lib/{lib_spec.soname}"] = lib_spec.filename
        for doc_spec in self._spec.license_documents:
            expected_regular[doc_spec.relative_path] = (
                doc_spec.size_bytes,
                doc_spec.sha256,
                0o644,
            )

        seen_entries: set[str] = set()
        seen_required: set[str] = set()
        pack_json_bytes: bytes | None = None

        raw_reader = ConcatenatedFileReader(parts)
        decompressor: Any
        if compression == "zst":
            decompressor = io.BufferedReader(ZstdStreamReader(raw_reader), buffer_size=1024 * 1024)
        else:
            decompressor = gzip.GzipFile(fileobj=io.BufferedReader(raw_reader), mode="rb")

        try:
            try:
                with tarfile.open(fileobj=decompressor, mode="r|") as tar:
                    for member in tar:
                        rel_path = _normalize_member_path(member.name)
                        if not rel_path:
                            continue
                        if member.isdir():
                            if rel_path not in {"bin", "lib", "licenses"}:
                                raise _pack_error(
                                    "GNINA_PACK_UNEXPECTED_ENTRY",
                                    f"Unexpected directory in GNINA pack: {rel_path}",
                                )
                            continue
                        if rel_path in seen_entries:
                            raise _pack_error(
                                "GNINA_PACK_DUPLICATE_ENTRY",
                                f"Duplicate entry in GNINA pack archive: {rel_path}",
                            )
                        seen_entries.add(rel_path)

                        basename = PurePosixPath(rel_path).name
                        if any(
                            basename.startswith(prefix)
                            for prefix in self._spec.forbidden_driver_prefixes
                        ):
                            raise _pack_error(
                                "GNINA_PACK_FORBIDDEN_DRIVER_LIBRARY",
                                f"Archive contains forbidden NVIDIA driver library: {basename}",
                            )

                        if member.issym():
                            expected_target = expected_symlinks.get(rel_path)
                            if expected_target is None or member.linkname != expected_target:
                                raise _pack_error(
                                    "GNINA_PACK_UNEXPECTED_SYMLINK",
                                    f"Unexpected symbolic link in GNINA pack: {rel_path}",
                                    linkname=member.linkname,
                                )
                            continue

                        if not member.isreg():
                            raise _pack_error(
                                "GNINA_PACK_UNSUPPORTED_ENTRY_TYPE",
                                f"Archive entry has an unsupported tar member type: {rel_path}",
                            )

                        stream = tar.extractfile(member)
                        if stream is None:
                            raise _pack_error(
                                "GNINA_PACK_CORRUPT_ARCHIVE",
                                f"Could not read regular archive entry: {rel_path}",
                            )

                        if rel_path == "gnina-pack.json":
                            pack_json_bytes = _read_bounded_bytes(
                                stream, max_bytes=_MAX_METADATA_BYTES, label=rel_path
                            )
                            continue

                        if rel_path == "licenses/GNINA_GPL_SOURCE_OFFER.txt":
                            offer_bytes = _read_bounded_bytes(
                                stream, max_bytes=_MAX_GPL_OFFER_BYTES, label=rel_path
                            )
                            dest_offer = staging_dir / rel_path
                            dest_offer.parent.mkdir(parents=True, exist_ok=True)
                            dest_offer.write_bytes(offer_bytes)
                            dest_offer.chmod(0o644)
                            continue

                        spec_tuple = expected_regular.get(rel_path)
                        if spec_tuple is None:
                            raise _pack_error(
                                "GNINA_PACK_UNEXPECTED_ENTRY",
                                f"Unexpected file in GNINA offline pack: {rel_path}",
                            )
                        expected_size, expected_sha, file_mode = spec_tuple
                        dest_path = staging_dir / rel_path
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        digest = hashlib.sha256()
                        written = 0
                        with dest_path.open("wb") as out_file:
                            while True:
                                chunk = stream.read(1024 * 1024)
                                if not chunk:
                                    break
                                written += len(chunk)
                                if written > expected_size:
                                    raise _pack_error(
                                        "GNINA_PACK_HASH_MISMATCH",
                                        f"Archive entry exceeds locked byte size: {rel_path}",
                                    )
                                digest.update(chunk)
                                out_file.write(chunk)
                        if written != expected_size:
                            raise _pack_error(
                                "GNINA_PACK_HASH_MISMATCH",
                                f"Archive entry size mismatch for {rel_path}: "
                                f"expected {expected_size}, got {written}",
                            )
                        actual_sha = digest.hexdigest()
                        if actual_sha != expected_sha.lower():
                            raise _pack_error(
                                "GNINA_PACK_HASH_MISMATCH",
                                f"Cryptographic SHA-256 mismatch for {rel_path}.",
                                entry=rel_path,
                                expected_sha256=expected_sha.lower(),
                                actual_sha256=actual_sha,
                            )
                        dest_path.chmod(file_mode)
                        seen_required.add(rel_path)
            except tarfile.TarError as error:
                raise _pack_error(
                    "GNINA_PACK_CORRUPT_ARCHIVE",
                    f"Tar stream could not be decoded: {error}",
                ) from error
        finally:
            decompressor.close()

        if pack_json_bytes is not None:
            try:
                manifest = json.loads(pack_json_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise _pack_error(
                    "GNINA_PACK_CORRUPT_ARCHIVE",
                    "gnina-pack.json inside the archive is not valid UTF-8 JSON.",
                ) from error
            if (
                manifest.get("pack_id") != self._spec.pack_id
                or manifest.get("gnina_version") != self._spec.gnina_version
            ):
                raise _pack_error(
                    "GNINA_PACK_VERSION_MISMATCH",
                    "gnina-pack.json pack_id or gnina_version does not match this Ankora release.",
                    pack_id=manifest.get("pack_id"),
                    expected_pack_id=self._spec.pack_id,
                )

        missing_required = sorted(set(expected_regular) - seen_required)
        if missing_required:
            raise _pack_error(
                "GNINA_PACK_INCOMPLETE_ARCHIVE",
                "The GNINA offline pack archive is missing required files.",
                missing_files=missing_required,
            )

        exe_path = staging_dir / self._spec.executable_relative_path
        if not _is_native_executable(exe_path) or _read_elf_architecture(exe_path) != "x86_64":
            raise _pack_error(
                "GNINA_EXECUTABLE_INVALID",
                "The extracted GNINA binary is not a native Linux x86-64 ELF executable.",
            )

        for sym_rel, sym_target in expected_symlinks.items():
            sym_path = staging_dir / sym_rel
            if sym_path.exists() or sym_path.is_symlink():
                sym_path.unlink()
            sym_path.symlink_to(sym_target)

        exe_stat = exe_path.stat()
        receipt = {
            "schema_version": 1,
            "pack_id": self._spec.pack_id,
            "gnina_version": self._spec.gnina_version,
            "imported_at": datetime.now(UTC).isoformat(),
            "executable": {
                "relative_path": self._spec.executable_relative_path,
                "size_bytes": exe_stat.st_size,
                "mtime_ns": exe_stat.st_mtime_ns,
                "sha256": self._spec.executable_sha256,
            },
            "shared_libraries": [
                {
                    "soname": lib.soname,
                    "filename": lib.filename,
                    "size_bytes": (staging_dir / "lib" / lib.filename).stat().st_size,
                    "mtime_ns": (staging_dir / "lib" / lib.filename).stat().st_mtime_ns,
                    "sha256": lib.sha256,
                }
                for lib in self._spec.shared_libraries
            ],
            "license_documents": [
                {
                    "id": doc.doc_id,
                    "relative_path": doc.relative_path,
                    "size_bytes": (staging_dir / doc.relative_path).stat().st_size,
                    "sha256": doc.sha256,
                }
                for doc in self._spec.license_documents
            ],
        }
        (staging_dir / _RECEIPT_FILENAME).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _read_bounded_bytes(stream: io.BufferedReader | Any, *, max_bytes: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = stream.read(65536)
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise _pack_error(
                "GNINA_PACK_CORRUPT_ARCHIVE",
                f"Metadata entry {label} exceeds maximum permitted size.",
            )
        chunks.append(block)
    return b"".join(chunks)


def discover_verified_packaged_gnina(
    *,
    service: GninaPackService | None = None,
) -> DiscoveredTool:
    if not _linux_x86_64_host():
        return DiscoveredTool(available=False, path=None)
    svc = service or GninaPackService()
    pack_status = svc.status()
    if not pack_status.installed or not pack_status.executable_path:
        return DiscoveredTool(available=False, path=None)
    return DiscoveredTool(
        available=True,
        path=pack_status.executable_path,
        version=pack_status.gnina_version,
        architecture="x86_64",
        sha256=pack_status.executable_sha256,
    )


def gnina_subprocess_environment(
    executable_path: Path,
    *,
    base_environment: Mapping[str, str] | None = None,
    service: GninaPackService | None = None,
) -> dict[str, str] | None:
    """Return an isolated LD_LIBRARY_PATH environment when executable is from a verified pack."""
    if not _linux_x86_64_host():
        return None
    svc = service or GninaPackService()
    try:
        resolved_exe = executable_path.resolve(strict=True)
        expected_exe = (svc.install_dir / svc._spec.executable_relative_path).resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if resolved_exe != expected_exe:
        if packaged_gnina_mode():
            raise _pack_error(
                "GNINA_UNVERIFIED_PACKAGED_EXECUTABLE",
                "Packaged Linux Ankora executes GNINA exclusively from a verified offline pack.",
                executable=str(executable_path),
            )
        return None

    svc.verify_installed_pack()
    lib_dir = str((svc.install_dir / "lib").resolve(strict=True))
    env = dict(os.environ if base_environment is None else base_environment)
    existing_ld = env.get("LD_LIBRARY_PATH", "").strip()
    env["LD_LIBRARY_PATH"] = f"{lib_dir}:{existing_ld}" if existing_ld else lib_dir
    return env
