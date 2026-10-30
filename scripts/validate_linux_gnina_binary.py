"""Run the predeclared, isolated GNINA 1.3.3 WSL engineering smoke."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs" / "linux-gnina-investigation" / "v1.3.3"
BINARY = LOGS / "gnina"
PROTEIN_GLOB = (
    "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data/projects/default/"
    "derived/receptors/*/protonated_receptor.pdb"
)
LIGAND_GLOB = (
    "logs/linux-autodock-gpu-service-smoke/campaign-cancel-product-01/data/projects/default/"
    "derived/ligands/*/conformers/*/ethanol_ETKDGv3_MMFF94s_minimized.sdf"
)
HASHES = {
    "binary": "3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172",
    "receptor": "4faa9c5ed9533438bbd001a91abcb38716e05660aac9b3f351475136a2d5d0ee",
    "ligand": "63dc82d64536769833a1744ecb2a5ac42733e91a67ac8db173b0065ea1c18a36",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique(pattern: str) -> Path:
    candidates = list(ROOT.glob(pattern))
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one declared input for {pattern!r}; found {len(candidates)}."
        )
    return candidates[0]


def main() -> int:
    output = LOGS / "cuda-docking-01"
    output.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "WSL exploratory engineering only",
    }
    try:
        if not sys.platform.startswith("linux"):
            raise ValueError("This protocol requires Linux.")
        inputs = {
            "binary": BINARY,
            "receptor": unique(PROTEIN_GLOB),
            "ligand": unique(LIGAND_GLOB),
        }
        for key, path in inputs.items():
            if sha(path) != HASHES[key]:
                raise ValueError(f"Declared {key} hash mismatch.")
        if BINARY.stat().st_size != 2056131000:
            raise ValueError(
                "Official GNINA binary size differs from the declared asset."
            )
        shutil.copyfile(inputs["receptor"], output / "receptor.pdb")
        shutil.copyfile(inputs["ligand"], output / "ligand.sdf")
        for key, name in (("receptor", "receptor.pdb"), ("ligand", "ligand.sdf")):
            if sha(output / name) != HASHES[key]:
                raise ValueError(
                    f"Copied {key} input differs from the declared original."
                )
        gpu = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        if gpu.stdout.strip():
            raise ValueError("Another GPU compute process is active; no test launched.")
        command = [
            str(BINARY),
            "--receptor",
            "receptor.pdb",
            "--ligand",
            "ligand.sdf",
            "--center_x",
            "11.634",
            "--center_y",
            "22.47",
            "--center_z",
            "5.8585",
            "--size_x",
            "24.854",
            "--size_y",
            "20.214",
            "--size_z",
            "18.635",
            "--seed",
            "20261029",
            "--cpu",
            "2",
            "--exhaustiveness",
            "1",
            "--num_modes",
            "2",
            "--cnn_scoring",
            "rescore",
            "--device",
            "0",
            "--out",
            "poses.sdf",
        ]
        evidence["command"] = command
        evidence["input_sha256"] = HASHES
        gpu_seen = False
        start = time.monotonic()
        with (
            (output / "stdout.log").open("x", encoding="utf-8") as stdout,
            (output / "stderr.log").open("x", encoding="utf-8") as stderr,
        ):
            process = subprocess.Popen(
                command,
                cwd=output,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            evidence["pid"] = process.pid
            deadline = start + 180
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=3)
                    raise TimeoutError(
                        "GNINA exceeded the declared 180-second timeout."
                    )
                query = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if query.returncode == 0 and str(process.pid) in query.stdout.split():
                    gpu_seen = True
                time.sleep(0.1)
            evidence["exit_code"] = process.returncode
        evidence["duration_seconds"] = time.monotonic() - start
        evidence["gpu_process_observed"] = gpu_seen
        if process.returncode != 0:
            raise RuntimeError(f"GNINA exited with code {process.returncode}.")
        if not gpu_seen:
            raise RuntimeError(
                "GNINA exited without its PID being observed on the GPU."
            )
        if (
            not (output / "poses.sdf").is_file()
            or not (output / "poses.sdf").stat().st_size
        ):
            raise RuntimeError("GNINA did not produce a nonempty pose file.")
        for key in ("receptor", "ligand"):
            if sha(inputs[key]) != HASHES[key]:
                raise RuntimeError(f"Original {key} input changed.")
        evidence["poses_sha256"] = sha(output / "poses.sdf")
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - retain evidence on any failed stage
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    with (output / "evidence.json").open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "evidence_sha256": sha(output / "evidence.json"),
            }
        )
    )
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
