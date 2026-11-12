"""Build a portable multi-architecture Linux x86_64 AutoDock-GPU 1.6 executable.

Compiles upstream AutoDock-GPU 1.6 (`DEVICE=CUDA`, `NUMWI=128`, `OVERLAP=ON`,
`TENSOR=OFF`, `GIT_VERSION=v1.6`) across Turing through Blackwell (`sm_75`,
`sm_80`, `sm_86`, `sm_89`, `sm_90`, `sm_100`, `sm_120` + `compute_120` PTX)
against `libcudart_static.a` (redistributable under NVIDIA CUDA SDK License
Agreement Attachment A) with zero host `RPATH`/`RUNPATH` and zero external
CUDA Toolkit `.so` dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = REPOSITORY_ROOT / "resources" / "linux-scientific-payload.lock.json"
DEFAULT_CACHE_ROOT = REPOSITORY_ROOT / "build" / "linux-runtime" / "upstream"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "build" / "linux-runtime" / "autodock-gpu-1.6"

TARGET_SM_ARCHITECTURES = ("75", "80", "86", "89", "90", "100", "120")
EXPECTED_VERSION = "v1.6"
FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
FORBIDDEN_NEEDED_PATTERNS = (
    re.compile(r"^libcudart\.so", re.IGNORECASE),
    re.compile(r"^libcurand\.so", re.IGNORECASE),
    re.compile(r"^libcuda\.so", re.IGNORECASE),
    re.compile(r"^libnvidia-ml\.so", re.IGNORECASE),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_cuda_root(explicit_cuda_root: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_cuda_root is not None:
        candidates.append(explicit_cuda_root)
    env_cuda = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
    if env_cuda:
        candidates.append(Path(env_cuda))
    usr_local = Path("/usr/local")
    if usr_local.is_dir():
        versioned = sorted(
            (p for p in usr_local.glob("cuda-*") if (p / "bin" / "nvcc").is_file()),
            reverse=True,
        )
        candidates.extend(versioned)
        if (usr_local / "cuda" / "bin" / "nvcc").is_file():
            candidates.append(usr_local / "cuda")
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "bin" / "nvcc").is_file():
            return resolved
    raise FileNotFoundError("Could not locate CUDA Toolkit root containing bin/nvcc.")


def _load_autodock_gpu_source_lock(lock_path: Path) -> dict[str, object]:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    for entry in payload.get("artifacts", []):
        if isinstance(entry, dict) and entry.get("id") == "autodock-gpu-source":
            return entry
    raise KeyError(f"autodock-gpu-source entry missing from {lock_path}")


def _cuda_gencode_flags(architectures: tuple[str, ...] = TARGET_SM_ARCHITECTURES) -> str:
    flags = [f"-gencode arch=compute_{arch},code=sm_{arch}" for arch in architectures]
    highest = architectures[-1]
    flags.append(f"-gencode arch=compute_{highest},code=compute_{highest}")
    return " ".join(flags)


def parse_elf_dynamic_section(readelf_output: str) -> dict[str, list[str]]:
    needed: list[str] = []
    rpaths: list[str] = []
    for line in readelf_output.splitlines():
        if "(NEEDED)" in line:
            match = re.search(r"Shared library:\s*\[([^\]]+)\]", line)
            if match:
                needed.append(match.group(1))
        elif "(RPATH)" in line or "(RUNPATH)" in line:
            match = re.search(r"Library r(?:un)?path:\s*\[([^\]]+)\]", line)
            if match:
                rpaths.append(match.group(1))
    return {"needed": needed, "rpaths": rpaths}


def audit_autodock_gpu_elf(binary_path: Path) -> dict[str, object]:
    if not binary_path.is_file():
        raise FileNotFoundError(f"AutoDock-GPU binary not found: {binary_path}")
    header = binary_path.read_bytes()[:20]
    if len(header) < 20 or not header.startswith(b"\x7fELF"):
        raise ValueError(f"Expected ELF binary at {binary_path}")
    machine = int.from_bytes(header[18:20], byteorder="little")
    if machine != 0x3E:
        raise ValueError(f"Expected x86_64 ELF (0x3E), got {hex(machine)}")

    proc = subprocess.run(
        ["/usr/bin/readelf", "-d", str(binary_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    dynamic = parse_elf_dynamic_section(proc.stdout)
    if dynamic["rpaths"]:
        raise RuntimeError(
            f"AutoDock-GPU binary embeds host RPATH/RUNPATH: {dynamic['rpaths']}"
        )
    forbidden = [
        lib
        for lib in dynamic["needed"]
        for pattern in FORBIDDEN_NEEDED_PATTERNS
        if pattern.search(lib)
    ]
    if forbidden:
        raise RuntimeError(
            f"AutoDock-GPU binary links forbidden non-portable shared libraries: {forbidden}"
        )

    cuobjdump_architectures: list[str] = []
    return {
        "needed_shared_libraries": dynamic["needed"],
        "rpaths": dynamic["rpaths"],
        "embedded_fatbin_targets": cuobjdump_architectures,
    }


def _create_deterministic_source_zip(
    *,
    source_tree: Path,
    destination_zip: Path,
    build_notes: str,
) -> tuple[str, int]:
    destination_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(source_tree.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            rel = path.relative_to(source_tree.parent).as_posix()
            info = zipfile.ZipInfo(rel, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.access(path, os.X_OK) else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())
        notes_info = zipfile.ZipInfo(
            f"{source_tree.name}/ANKORA_LINUX_BUILD_NOTES.txt",
            date_time=FIXED_ZIP_TIMESTAMP,
        )
        notes_info.compress_type = zipfile.ZIP_DEFLATED
        notes_info.external_attr = (0o644 & 0xFFFF) << 16
        archive.writestr(notes_info, build_notes.encode("utf-8"))
    return sha256_file(destination_zip), destination_zip.stat().st_size


def build_linux_autodock_gpu(
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    cuda_root: Path | None = None,
) -> dict[str, object]:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("build_linux_autodock_gpu.py must run on Linux.")

    source_entry = _load_autodock_gpu_source_lock(lock_path)
    source_zip = cache_root / str(source_entry["filename"])
    if not source_zip.is_file():
        raise FileNotFoundError(f"Cached AutoDock-GPU source archive missing: {source_zip}")
    actual_source_sha = sha256_file(source_zip)
    expected_source_sha = str(source_entry["sha256"])
    if actual_source_sha != expected_source_sha:
        raise ValueError(
            f"AutoDock-GPU source SHA-256 mismatch: expected {expected_source_sha}, got {actual_source_sha}"
        )

    resolved_cuda = _resolve_cuda_root(cuda_root)
    nvcc = resolved_cuda / "bin" / "nvcc"
    cuobjdump = resolved_cuda / "bin" / "cuobjdump"
    cuda_inc = resolved_cuda / "targets" / "x86_64-linux" / "include"
    cuda_lib = resolved_cuda / "targets" / "x86_64-linux" / "lib"
    cuda_stubs = cuda_lib / "stubs"
    if not cuda_inc.is_dir():
        cuda_inc = resolved_cuda / "include"
    if not cuda_lib.is_dir():
        cuda_lib = resolved_cuda / "lib64"
        cuda_stubs = cuda_lib / "stubs"

    work_dir = output_root / "work"
    runtime_dir = output_root / "runtime"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source_zip) as zf:
        zf.extractall(work_dir)

    source_root = work_dir / "AutoDock-GPU-1.6"
    if not source_root.is_dir():
        raise FileNotFoundError(f"Expected AutoDock-GPU-1.6 directory inside {source_zip}")
    for script_name in ("test_cuda.sh", "version_string.sh"):
        script_path = source_root / script_name
        if script_path.is_file():
            script_path.chmod(0o755)

    nvcc_version = subprocess.run(
        [str(nvcc), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    gxx_version = subprocess.run(
        ["/usr/bin/g++", "--version"], check=True, capture_output=True, text=True
    ).stdout.splitlines()[0]

    gencode_flags = _cuda_gencode_flags(TARGET_SM_ARCHITECTURES)
    targets_str = " ".join(TARGET_SM_ARCHITECTURES)
    lib_search_flags = f"-L{cuda_lib}"
    if Path("/usr/lib/wsl/lib").is_dir():
        test_gpu_lib_path = "/usr/lib/wsl/lib"
    elif cuda_stubs.is_dir():
        test_gpu_lib_path = str(cuda_stubs)
    else:
        test_gpu_lib_path = str(cuda_lib)

    env = {
        "PATH": f"{resolved_cuda / 'bin'}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "DEVICE": "CUDA",
        "GPU_INCLUDE_PATH": str(cuda_inc),
        "GPU_LIBRARY_PATH": f"{cuda_lib} -L{test_gpu_lib_path}",
    }

    make_cmd = [
        "/usr/bin/make",
        "-j4",
        "odock",
        "DEVICE=CUDA",
        "NUMWI=128",
        "OVERLAP=ON",
        "TENSOR=OFF",
        f"TARGETS={targets_str}",
        f"CUDA_TARGETS={gencode_flags}",
        f"GIT_VERSION={EXPECTED_VERSION}",
        f"IFLAGS=-I./common -I./host/inc -I{cuda_inc} -I./cuda",
        f"LFLAGS={lib_search_flags} -Wl,--as-needed",
        (
            "LIB_CUDA=kernels.o -Wl,--as-needed "
            "-lcurand_static -lculibos -lcudart_static -ldl -lrt -lpthread -DUSE_CUDA"
        ),
    ]
    subprocess.run(make_cmd, cwd=str(source_root), env=env, check=True)

    built_binary = source_root / "bin" / "autodock_gpu_128wi"
    if not built_binary.is_file():
        raise FileNotFoundError(f"Expected compiled binary at {built_binary}")

    subprocess.run(["/usr/bin/strip", "--strip-unneeded", str(built_binary)], check=True)
    built_binary.chmod(0o755)

    elf_audit = audit_autodock_gpu_elf(built_binary)
    if cuobjdump.is_file():
        fatbin_proc = subprocess.run(
            [str(cuobjdump), "--list-elf", str(built_binary)],
            check=True,
            capture_output=True,
            text=True,
        )
        sm_matches = sorted(set(re.findall(r"sm_\d+", fatbin_proc.stdout)))
        elf_audit["embedded_fatbin_targets"] = sm_matches
        expected_sms = sorted(f"sm_{arch}" for arch in TARGET_SM_ARCHITECTURES)
        if sm_matches != expected_sms:
            raise RuntimeError(
                f"Embedded CUDA SM architectures {sm_matches} != expected {expected_sms}"
            )

    clean_probe_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    help_proc = subprocess.run(
        [str(built_binary), "--help"],
        env=clean_probe_env,
        check=True,
        capture_output=True,
        text=True,
    )
    if f"AutoDock-GPU version: {EXPECTED_VERSION}" not in help_proc.stdout:
        raise RuntimeError(
            f"Compiled AutoDock-GPU --help output missing expected version header: {help_proc.stdout[:400]}"
        )

    staged_binary = runtime_dir / "autodock_gpu_128wi"
    shutil.copy2(built_binary, staged_binary)
    staged_binary.chmod(0o755)
    for license_name in ("LICENSE", "LICENSE_LGPL"):
        src_license = source_root / license_name
        if src_license.is_file():
            shutil.copy2(src_license, runtime_dir / license_name)

    binary_sha = sha256_file(staged_binary)
    binary_size = staged_binary.stat().st_size

    build_notes = "\n".join(
        [
            "Ankora Linux AutoDock-GPU 1.6 Redistributable Build Notes",
            "=========================================================",
            f"Upstream archive SHA-256: {actual_source_sha}",
            f"Upstream version: {EXPECTED_VERSION}",
            f"Target architectures: {', '.join(f'sm_{a}' for a in TARGET_SM_ARCHITECTURES)} + compute_{TARGET_SM_ARCHITECTURES[-1]} PTX",
            f"NVCC version: {nvcc_version.splitlines()[-1]}",
            f"Host C++ compiler: {gxx_version}",
            "CUDA runtime linkage: static (libcudart_static.a / libcurand_static.a / libculibos.a)",
            "Host RPATH/RUNPATH: none",
            f"Compiled binary SHA-256: {binary_sha}",
            "",
        ]
    )
    companion_source_zip = output_root / "autodock-gpu-1.6-ankora-source.zip"
    companion_sha, companion_size = _create_deterministic_source_zip(
        source_tree=source_root,
        destination_zip=companion_source_zip,
        build_notes=build_notes,
    )

    shutil.rmtree(work_dir)

    manifest: dict[str, object] = {
        "schema_version": 1,
        "built_at": datetime.now(UTC).isoformat(),
        "upstream_source_sha256": actual_source_sha,
        "version": "1.6",
        "git_version_define": EXPECTED_VERSION,
        "target_sm_architectures": list(TARGET_SM_ARCHITECTURES),
        "ptx_fallback_architecture": f"compute_{TARGET_SM_ARCHITECTURES[-1]}",
        "nvcc_version": nvcc_version,
        "gxx_version": gxx_version,
        "binary": {
            "filename": "autodock_gpu_128wi",
            "size_bytes": binary_size,
            "sha256": binary_sha,
            **elf_audit,
        },
        "corresponding_source_archive": {
            "filename": companion_source_zip.name,
            "size_bytes": companion_size,
            "sha256": companion_sha,
        },
        "help_header_line": help_proc.stdout.splitlines()[0] if help_proc.stdout else "",
    }
    manifest_path = output_root / "build-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_built_autodock_gpu(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, object]:
    manifest_path = output_root / "build-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"AutoDock-GPU build manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    binary_info = manifest["binary"]
    binary_path = output_root / "runtime" / str(binary_info["filename"])
    audit_autodock_gpu_elf(binary_path)
    actual_sha = sha256_file(binary_path)
    if actual_sha != binary_info["sha256"]:
        raise ValueError(
            f"AutoDock-GPU binary SHA-256 mismatch: expected {binary_info['sha256']}, got {actual_sha}"
        )
    source_info = manifest["corresponding_source_archive"]
    source_zip = output_root / str(source_info["filename"])
    if sha256_file(source_zip) != source_info["sha256"]:
        raise ValueError("AutoDock-GPU corresponding source archive SHA-256 mismatch.")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--cuda-root", type=Path, default=None)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    if args.verify_only:
        manifest = verify_built_autodock_gpu(args.output_root)
    else:
        manifest = build_linux_autodock_gpu(
            lock_path=args.lock,
            cache_root=args.cache_root,
            output_root=args.output_root,
            cuda_root=args.cuda_root,
        )
    binary = manifest["binary"]
    assert isinstance(binary, dict)
    print(
        f"AutoDock-GPU 1.6 verified: sha256={binary['sha256']}, "
        f"size={binary['size_bytes']} B, needed={binary['needed_shared_libraries']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
