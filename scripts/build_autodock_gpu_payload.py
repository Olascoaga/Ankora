"""Rebuild AutoDock-GPU 1.6 with the redistributable MSVC OpenMP runtime.

No scoring/search source is changed. Three timing-counter atomic updates use
the equivalent OpenMP 2.0 spelling; the scientific pipeline stays parallel.
The exact source changes, compiler invocation and raw build output are kept.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pefile

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

COMPILER_VERSION = "14.44.35207"
REDIST_VERSION = "14.44.35112"


def adapt_source(source: Path) -> list[dict[str, str]]:
    changes = (
        ("AutoDock-GPU.vcxproj", "/openmp:llvm ", "", 2),
        (
            "AutoDock-GPU.vcxproj",
            "<GenerateDebugInformation>true</GenerateDebugInformation>",
            "<GenerateDebugInformation>false</GenerateDebugInformation>",
            4,
        ),
        ("host/src/main.cpp", "#pragma omp atomic update", "#pragma omp atomic", 3),
    )
    evidence = []
    for relative, before, after, count in changes:
        path = source / relative
        original = path.read_bytes()
        if original.count(before.encode()) != count:
            raise ValueError(f"Unexpected GPU source at {relative}; refusing an unreviewed patch")
        prior_hash = sha256(path)
        path.write_bytes(original.replace(before.encode(), after.encode()))
        evidence.append(
            {
                "path": relative,
                "before_sha256": prior_hash,
                "after_sha256": sha256(path),
                "replace": before,
                "with": after,
            }
        )
    return evidence


def build(output: Path, visual_studio: Path, *, cache: Path = CACHE) -> dict[str, object]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError("GPU build evidence is create-only; choose a new output directory")
    entry = next(e for e in load_lock() if e["id"] == "autodock-gpu-source")
    archive = acquire(entry, cache)
    source = output / "source"
    extract_archive(archive, source, prefix="AutoDock-GPU-1.6")
    changes = adapt_source(source)
    msbuild = visual_studio / "MSBuild/Current/Bin/MSBuild.exe"
    redist = (
        visual_studio / f"VC/Redist/MSVC/{REDIST_VERSION}/x64/Microsoft.VC143.OpenMP/vcomp140.dll"
    )
    compiler = visual_studio / f"VC/Tools/MSVC/{COMPILER_VERSION}/bin/Hostx64/x64/cl.exe"
    for required in (msbuild, redist, compiler):
        if not required.is_file():
            raise FileNotFoundError(f"Missing pinned GPU build prerequisite: {required}")
    binary_dir = output / "runtime"
    binary_dir.mkdir()
    command = [
        str(msbuild),
        str(source / "AutoDock-GPU.vcxproj"),
        "/t:Rebuild",
        "/m:2",
        "/p:Configuration=Release",
        "/p:Platform=x64",
        f"/p:VCToolsVersion={COMPILER_VERSION}",
        f"/p:OutDir={binary_dir}{os.sep}",
        f"/p:IntDir={output / 'obj'}{os.sep}",
        "/p:LinkIncremental=false",
    ]
    environment = os.environ.copy()
    environment["LINK"] = "/Brepro"
    result = subprocess.run(command, cwd=source, capture_output=True, check=False, env=environment)
    (output / "build.stdout.log").write_bytes(result.stdout)
    (output / "build.stderr.log").write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError(f"GPU compilation failed ({result.returncode}); see retained build logs")
    executable = binary_dir / "AutoDock-GPU.exe"
    shutil.copyfile(redist, binary_dir / redist.name)
    dependencies = [e.dll.decode() for e in pefile.PE(str(executable)).DIRECTORY_ENTRY_IMPORT]
    if {name.casefold() for name in dependencies} != {"kernel32.dll", "opencl.dll", "vcomp140.dll"}:
        raise RuntimeError(f"Unexpected GPU runtime closure: {dependencies}")
    # Source archive includes our portability edits and upstream license texts,
    # but no build products, user paths or original restricted runtime binary.
    with zipfile.ZipFile(
        output / "autodock-gpu-1.6-ankora-source.zip", "x", compression=zipfile.ZIP_DEFLATED
    ) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, path.read_bytes())
    evidence: dict[str, object] = {
        "schema_version": 1,
        "version": "1.6",
        "variant": "ankora-msvc-openmp-v1",
        "source_sha256": entry["sha256"],
        "compiler_version": COMPILER_VERSION,
        "compiler_sha256": sha256(compiler),
        "redist_version": REDIST_VERSION,
        "portability_changes": changes,
        "dependencies": dependencies,
        "executable_sha256": sha256(executable),
        "vcomp140_sha256": sha256(binary_dir / redist.name),
        "corresponding_source_sha256": sha256(output / "autodock-gpu-1.6-ankora-source.zip"),
        "build_exit_code": result.returncode,
        "scientific_acceptance": "pending; compilation is not scientific validation",
    }
    (output / "build-manifest.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (output / "build-command.private.json").write_text(json.dumps(command, indent=2) + "\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-studio", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.visual_studio), indent=2))


if __name__ == "__main__":
    main()
