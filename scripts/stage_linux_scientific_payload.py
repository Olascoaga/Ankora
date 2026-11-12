"""Stage the private Linux Core scientific tool tree; never install host-wide packages.

Produces the streamlined Option A Core scientific payload under ADR-029:
- AutoDock Vina 1.2.7 (Linux x86_64)
- AutoGrid4 / AutoDock4 4.2.6 (Linux x86_64)
- Multi-arch static-cudart AutoDock-GPU 1.6 (sm_75..sm_120 + compute_120 PTX)
- P2Rank 2.5.1 (vecmath-1.5.2-only, default + alphafold models)
- Eclipse Temurin OpenJDK JRE 21.0.12.1+1 (omitting redundant CDS cache dumps)

GNINA 1.3.3 is packaged separately via scripts/build_linux_gnina_pack.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_linux_autodock_gpu import (
    DEFAULT_OUTPUT_ROOT as DEFAULT_GPU_BUILD_ROOT,
)
from scripts.build_linux_autodock_gpu import (
    verify_built_autodock_gpu,
)
from scripts.linux_scientific_payload import (
    CACHE,
    ROOT,
    acquire,
    extract_archive,
    load_lock,
    sha256,
)
from scripts.validate_p2rank_variant import (
    REMOVED as REMOVED_VECMATH,
)
from scripts.validate_p2rank_variant import (
    REMOVED_SHA as REMOVED_VECMATH_SHA,
)
from scripts.validate_p2rank_variant import (
    RETAINED as RETAINED_VECMATH,
)
from scripts.validate_p2rank_variant import (
    RETAINED_SHA as RETAINED_VECMATH_SHA,
)
from scripts.validate_p2rank_variant import (
    verify_tree,
)

DEFAULT_DESTINATION = ROOT / "build/linux-runtime/scientific-tools-slim"
AUTODOCK_GPU_VARIANT = "ankora-linux-cuda-static-multiarch-v1"
SLIM_P2RANK_VARIANT = "ankora-vecmath-1.5.2-default-alphafold-v1"

LINUX_CPU_AUTODOCK_MEMBERS = {
    "autodock4": (
        "x86_64Linux2/autodock4",
        "6dad50cb0ae291a824dc23d98b242f6243e6e101cc2a8350940897ec08890818",
    ),
    "autogrid4": (
        "x86_64Linux2/autogrid4",
        "e38a7b299336af0e150eadf87d3e89b409a3b3ca43ec7975922e08534ddca19d",
    ),
}

OMITTED_P2RANK_MODELS = (
    "p2rank-2.5.1/models/alphafold_conservation_hmm/model.zst",
    "p2rank-2.5.1/models/conservation_hmm/model.zst",
    "p2rank-2.5.1/models/default_rescore/model.zst",
    "p2rank-2.5.1/models/rescore_2024/model.zst",
    "p2rank-2.5.1/models/rescore_conservation/model.zst",
)
RETAINED_P2RANK_MODELS = (
    "p2rank-2.5.1/models/default/model.zst",
    "p2rank-2.5.1/models/alphafold/model.zst",
)
OMITTED_JAVA_FILES = (
    "java-21/lib/server/classes.jsa",
    "java-21/lib/server/classes_nocoops.jsa",
)


def _extract_pinned_autodock4_cpu(archive: Path, cpu_dir: Path) -> None:
    cpu_dir.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:*") as tf:
        members_by_name = {m.name.lstrip("./"): m for m in tf.getmembers() if m.isfile()}
        for binary_name, (member_path, expected_sha) in LINUX_CPU_AUTODOCK_MEMBERS.items():
            member = members_by_name.get(member_path)
            if member is None:
                raise ValueError(f"Missing AutoDock Suite member: {member_path}")
            stream = tf.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable AutoDock Suite member: {member_path}")
            out_path = cpu_dir / binary_name
            with stream as src, out_path.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            out_path.chmod(0o755)
            if sha256(out_path) != expected_sha:
                raise ValueError(f"Unexpected AutoDock Suite member SHA-256: {binary_name}")


def stage(
    destination: Path = DEFAULT_DESTINATION,
    gpu_build: Path = DEFAULT_GPU_BUILD_ROOT,
    *,
    cache: Path = CACHE,
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"Scientific staging is create-only: {destination}")

    gpu_manifest = verify_built_autodock_gpu(gpu_build)
    entries = {entry["id"]: entry for entry in load_lock()}
    inputs = {
        name: acquire(entries[name], cache, offline=True)
        for name in ("vina", "autodocksuite", "p2rank", "java")
    }

    destination.mkdir(parents=True, exist_ok=False)
    tools: dict[str, dict[str, str]] = {}

    # 1. AutoDock Vina 1.2.7
    vina_dir = destination / "vina-1.2.7"
    vina_dir.mkdir()
    vina_bin = vina_dir / "vina"
    shutil.copyfile(inputs["vina"], vina_bin)
    vina_bin.chmod(0o755)
    tools["vina"] = {"path": "vina-1.2.7/vina", "version": "1.2.7"}

    # 2. AutoDock4 & AutoGrid4 4.2.6
    cpu_dir = destination / "autodock4-4.2.6"
    _extract_pinned_autodock4_cpu(inputs["autodocksuite"], cpu_dir)
    tools["autodock4"] = {"path": "autodock4-4.2.6/autodock4", "version": "4.2.6"}
    tools["autogrid4"] = {"path": "autodock4-4.2.6/autogrid4", "version": "4.2.6"}

    # 3. AutoDock-GPU 1.6 (multi-arch static cudart)
    gpu_dir = destination / "autodock-gpu-1.6"
    gpu_dir.mkdir()
    gpu_src_bin = gpu_build / "runtime" / "autodock_gpu_128wi"
    gpu_dst_bin = gpu_dir / "autodock_gpu_128wi"
    shutil.copyfile(gpu_src_bin, gpu_dst_bin)
    gpu_dst_bin.chmod(0o755)
    for lic_name in ("LICENSE", "LICENSE_LGPL"):
        lic_src = gpu_build / "runtime" / lic_name
        if lic_src.is_file():
            lic_dst = gpu_dir / lic_name
            shutil.copyfile(lic_src, lic_dst)
            lic_dst.chmod(0o644)
    tools["autodock_gpu"] = {
        "path": "autodock-gpu-1.6/autodock_gpu_128wi",
        "version": "1.6",
        "variant": AUTODOCK_GPU_VARIANT,
    }

    # 4. P2Rank 2.5.1 (slim variant: vecmath-1.5.2-only + default & alphafold models)
    extract_archive(
        inputs["p2rank"],
        destination / "p2rank-2.5.1",
        prefix="p2rank_2.5.1",
        include=("bin", "config", "models", "prank", "LICENSE.txt", "README.md"),
    )
    prank_launcher = destination / "p2rank-2.5.1/prank"
    prank_launcher.chmod(0o755)

    removed_vecmath_path = destination / REMOVED_VECMATH
    retained_vecmath_path = destination / RETAINED_VECMATH
    if not removed_vecmath_path.is_file() or sha256(removed_vecmath_path) != REMOVED_VECMATH_SHA:
        raise ValueError("Unexpected upstream vecmath-1.3.1.jar in Linux P2Rank archive")
    if not retained_vecmath_path.is_file() or sha256(retained_vecmath_path) != RETAINED_VECMATH_SHA:
        raise ValueError("Unexpected retained vecmath-1.5.2.jar in Linux P2Rank archive")
    removed_vecmath_path.unlink()

    for required_model in RETAINED_P2RANK_MODELS:
        if not (destination / required_model).is_file():
            raise ValueError(f"Missing required P2Rank model: {required_model}")
    for omitted_model in OMITTED_P2RANK_MODELS:
        omitted_path = destination / omitted_model
        if not omitted_path.is_file():
            raise ValueError(f"Expected upstream P2Rank model not found: {omitted_model}")
        omitted_path.unlink()
        if omitted_path.parent.is_dir() and not any(omitted_path.parent.iterdir()):
            omitted_path.parent.rmdir()

    tools["p2rank"] = {
        "path": "p2rank-2.5.1/prank",
        "version": "2.5.1",
        "variant": SLIM_P2RANK_VARIANT,
    }

    # 5. Eclipse Temurin OpenJDK JRE 21.0.12.1+1 (slim: omit CDS dumps)
    extract_archive(
        inputs["java"],
        destination / "java-21",
        prefix="jdk-21.0.12.1+1-jre",
    )
    for omitted_java in OMITTED_JAVA_FILES:
        java_cache_path = destination / omitted_java
        if not java_cache_path.is_file():
            raise ValueError(f"Expected Java CDS dump not found: {omitted_java}")
        java_cache_path.unlink()
    for exec_candidate in (destination / "java-21/bin").iterdir():
        if exec_candidate.is_file():
            exec_candidate.chmod(0o755)
    jspawnhelper = destination / "java-21/lib/jspawnhelper"
    if jspawnhelper.is_file():
        jspawnhelper.chmod(0o755)
    tools["java"] = {"path": "java-21/bin/java", "version": "21.0.12.1+1"}

    # Ensure zero symlinks exist anywhere inside the staged tools directory
    symlinks = [
        p.relative_to(destination).as_posix()
        for p in destination.rglob("*")
        if p.is_symlink()
    ]
    if symlinks:
        raise ValueError(f"Staged scientific payload must not contain symlinks: {symlinks[:5]}")

    files = {
        path.relative_to(destination).as_posix(): sha256(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    for tool in tools.values():
        if tool["path"] not in files:
            raise ValueError(f"Missing staged tool: {tool['path']}")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "platform": "linux-x86_64",
        "tools": tools,
        "files": files,
        "gpu_build": gpu_manifest,
        "p2rank_variant": {
            "id": SLIM_P2RANK_VARIANT,
            "omitted_jar": REMOVED_VECMATH,
            "omitted_jar_sha256": REMOVED_VECMATH_SHA,
            "retained_models": list(RETAINED_P2RANK_MODELS),
            "omitted_unused_models": list(OMITTED_P2RANK_MODELS),
            "omitted_java_cache_files": list(OMITTED_JAVA_FILES),
        },
        "legal_acceptance": "separate installer gate required",
    }
    payload_path = destination / "payload.json"
    payload_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_tree(destination)
    payload_sha = sha256(payload_path)
    total_bytes = sum(
        p.stat().st_size for p in destination.rglob("*") if p.is_file()
    )
    print(
        f"Staged {len(tools)} Linux Core tools and {len(files)} verified files "
        f"({total_bytes / (1024 * 1024):.2f} MiB, payload_sha256={payload_sha})",
        flush=True,
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--gpu-build", type=Path, default=DEFAULT_GPU_BUILD_ROOT)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    if args.clean and args.destination.exists():
        shutil.rmtree(args.destination)
    stage(args.destination, args.gpu_build, cache=args.cache)


if __name__ == "__main__":
    main()
