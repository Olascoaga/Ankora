"""Stage the complete private tool tree; never install host-wide dependencies.

This staging command is not the installer legal/acceptance gate. Build inputs
must already be acquired against the upstream lock; GPU is the reviewed build.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

try:
    from scripts.windows_scientific_payload import (
        CACHE,
        acquire,
        extract_archive,
        load_lock,
        sha256,
    )
except ModuleNotFoundError:
    from windows_scientific_payload import CACHE, acquire, extract_archive, load_lock, sha256

CPU_HASHES = {
    "autodock4.exe": "36c0b16c04d7df8e6225737bae65bb04058d1f4c90accfaf2d230dbc913954bf",
    "autogrid4.exe": "797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e",
}
EXTRACTOR_HASHES = {
    # Exact files extracted from the hash-locked official 7-Zip 26.04 MSI.
    "7z.exe": "95fff19b73eff77c87c0d7bd32822e43fb90dd2932459f962eb532d8dfb6ba53",
    "7z.dll": "899cd73d7fc60e1c1c35c7de0f5bed3dc69bfe2cecbd48014d868a347970a0b1",
}


def verify_extractor(extractor: Path) -> None:
    if extractor.name.casefold() != "7z.exe":
        raise ValueError("Expected the pinned 7-Zip extractor")
    for name, expected in EXTRACTOR_HASHES.items():
        if sha256(extractor.with_name(name)) != expected:
            raise ValueError("Unverified build-only extractor")


def stage(destination: Path, gpu_build: Path, extractor: Path) -> None:
    if destination.exists():
        raise FileExistsError("Scientific staging is create-only")
    verify_extractor(extractor)
    entries = {entry["id"]: entry for entry in load_lock()}
    inputs = {
        name: acquire(entries[name], CACHE, offline=True)
        for name in ("vina", "autodocksuite", "p2rank", "java")
    }
    gpu = json.loads((gpu_build / "build-manifest.json").read_text())
    if gpu["variant"] != "ankora-msvc-openmp-v1" or gpu["version"] != "1.6":
        raise ValueError("Unreviewed AutoDock-GPU build variant")
    for name, key in (
        ("AutoDock-GPU.exe", "executable_sha256"),
        ("vcomp140.dll", "vcomp140_sha256"),
    ):
        if sha256(gpu_build / "runtime" / name) != gpu[key]:
            raise ValueError("GPU build no longer matches its manifest")
    destination.mkdir(parents=True)
    tools = {}
    vina = destination / "vina-1.2.7"
    vina.mkdir()
    shutil.copyfile(inputs["vina"], vina / "vina.exe")
    tools["vina"] = {"path": "vina-1.2.7/vina.exe", "version": "1.2.7"}
    cpu = destination / "autodock4-4.2.6"
    cpu.mkdir()
    extraction = subprocess.run(
        [
            str(extractor.resolve()),
            "e",
            str(inputs["autodocksuite"]),
            f"-o{cpu.resolve()}",
            "-aos",
            *CPU_HASHES,
        ],
        capture_output=True,
        check=False,
    )
    if extraction.returncode:
        raise RuntimeError("Pinned AutoDock Suite extraction failed")
    for name, expected in CPU_HASHES.items():
        if sha256(cpu / name) != expected:
            raise ValueError(f"Unexpected AutoDock Suite member: {name}")
        tools[Path(name).stem] = {"path": f"autodock4-4.2.6/{name}", "version": "4.2.6"}
    gpu_root = destination / "autodock-gpu-1.6"
    gpu_root.mkdir()
    for name in ("AutoDock-GPU.exe", "vcomp140.dll"):
        shutil.copyfile(gpu_build / "runtime" / name, gpu_root / name)
    tools["autodock_gpu"] = {"path": "autodock-gpu-1.6/AutoDock-GPU.exe", "version": "1.6"}
    extract_archive(
        inputs["p2rank"],
        destination / "p2rank-2.5.1",
        prefix="p2rank_2.5.1",
        include=("bin", "config", "models", "prank.bat", "LICENSE.txt", "README.md"),
    )
    tools["p2rank"] = {"path": "p2rank-2.5.1/prank.bat", "version": "2.5.1"}
    extract_archive(inputs["java"], destination / "java-21", prefix="jdk-21.0.12.1+1-jre")
    tools["java"] = {"path": "java-21/bin/java.exe", "version": "21.0.12.1+1"}
    files = {
        path.relative_to(destination).as_posix(): sha256(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    for tool in tools.values():
        if tool["path"] not in files:
            raise ValueError(f"Missing staged tool: {tool['path']}")
    manifest = {
        "schema_version": 1,
        "tools": tools,
        "files": files,
        "gpu_build": gpu,
        "legal_acceptance": "separate installer gate required",
    }
    (destination / "payload.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Staged {len(tools)} private tools and {len(files)} verified files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--extractor", type=Path, required=True)
    args = parser.parse_args()
    stage(args.destination, args.gpu_build, args.extractor)
