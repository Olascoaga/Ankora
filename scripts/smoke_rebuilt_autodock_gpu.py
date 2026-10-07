"""Run a bounded, recorded calculation with the rebuilt GPU, not a benchmark.

Uses the unmodified 1STP example supplied with the hash-locked GPU 1.6 source.
No expected energy is invented and no equivalence to historical binaries is
asserted. The actual DLG must pass Ankora's existing structured-output parser.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from ankora_backend.adapters.engines.autodock4_job import parse_autodock4_log
from ankora_backend.adapters.engines.autodock_gpu import build_arguments, run_reports_success

try:
    from scripts.windows_scientific_payload import sha256
except ModuleNotFoundError:
    from windows_scientific_payload import sha256


def smoke(build: Path, output: Path) -> dict[str, object]:
    build, output = build.resolve(), output.resolve()
    manifest = json.loads((build / "build-manifest.json").read_text())
    executable = build / "runtime/AutoDock-GPU.exe"
    for path, key in (
        (executable, "executable_sha256"),
        (executable.with_name("vcomp140.dll"), "vcomp140_sha256"),
    ):
        if sha256(path) != manifest[key]:
            raise ValueError("Rebuilt runtime does not match its recorded identity")
    if output.exists():
        raise FileExistsError("GPU smoke evidence is create-only")
    output.mkdir(parents=True)
    fixture = build / "source/input/1stp/derived"
    inputs = {}
    for source in sorted(fixture.iterdir()):
        if source.suffix in {".map", ".fld", ".xyz", ".pdbqt"}:
            destination = output / source.name
            shutil.copyfile(source, destination)
            inputs[source.name] = sha256(source)
    shutil.copyfile(output / "1stp_ligand.pdbqt", output / "ligand.pdbqt")
    arguments = build_arguments(
        field_filename="1stp_protein.maps.fld",
        device_number=1,
        runs=2,
        seed=(20261006, 101, 303),
        heuristics=False,
        autostop=False,
        energy_evaluations=200000,
        population_size=150,
        local_search_method="ad",
        cluster_rmsd_tolerance_angstrom=2.0,
    )
    environment = os.environ.copy()
    environment["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    environment["OMP_NUM_THREADS"] = "2"
    records = []
    for label, args in (("version", ["--help"]), ("docking", arguments)):
        execution = subprocess.run(
            [str(executable), *args], cwd=output, env=environment, capture_output=True, timeout=180
        )
        (output / f"{label}.stdout.txt").write_bytes(execution.stdout)
        (output / f"{label}.stderr.txt").write_bytes(execution.stderr)
        records.append(
            {
                "executable_sha256": manifest["executable_sha256"],
                "arguments": args,
                "exit_code": execution.returncode,
            }
        )
        (output / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
        if execution.returncode:
            raise RuntimeError(f"GPU {label} exited {execution.returncode}; raw logs retained")
    stdout = (output / "docking.stdout.txt").read_text(encoding="utf-8", errors="replace")
    version = (output / "version.stdout.txt").read_text(encoding="utf-8", errors="replace")
    if "v1.6|Release|x64" not in version or not run_reports_success(stdout):
        raise RuntimeError("GPU did not report a supported build and successful calculation")
    device = re.search(r"^\s*OpenCL device:\s*(.+?)\s*$", stdout, re.MULTILINE)
    parsed = parse_autodock4_log((output / "ligand.dlg").read_text())
    if device is None or {pose.run for pose in parsed.poses} != {1, 2}:
        raise RuntimeError("GPU smoke is missing a device or requested runs")
    if not all(math.isfinite(row.binding_energy_kcal_mol) for row in parsed.ranking):
        raise RuntimeError("GPU smoke produced nonfinite scores")
    result = {
        "schema_version": 1,
        "status": "passed",
        "scope": "bounded runtime calculation only",
        "version": "1.6",
        "variant": manifest["variant"],
        "executable_sha256": manifest["executable_sha256"],
        "device": device.group(1),
        "input_sha256": inputs,
        "ranking": [dataclasses.asdict(row) for row in parsed.ranking],
        "clusters": [dataclasses.asdict(row) for row in parsed.clusters],
        "output_sha256": {
            path.name: sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file() and path.name not in inputs
        },
        "not_claimed": [
            "benchmark accuracy",
            "bit identity with official binary",
            "clean Windows installation",
            "other GPU hardware compatibility",
        ],
    }
    (output / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(smoke(args.build, args.output), indent=2))
