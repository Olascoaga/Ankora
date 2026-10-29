"""Exercise the predeclared real GNINA Linux adapter in an isolated directory."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psutil
from ankora_backend.adapters.engines.gnina import (
    execute_gnina,
    parse_gnina_pdbqt,
    probe_gnina,
    require_matching_topology,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.gnina import GninaDockingParameters
from validate_linux_gnina_binary import BINARY, LOGS, sha, unique
from validate_linux_gnina_topology import INPUTS, PROJECT

CONFORMER = unique(
    PROJECT + "/derived/ligands/a3b23f57-e4ec-4b91-b309-462848305fa7/"
    "conformers/*/MK1_ETKDGv3_MMFF94s_minimized.sdf"
)
CONFORMER_SHA = "cd1adf846078e3815ed7fac7cb9105bceedf41bd136d066aa8311df747898c01"


def main() -> int:
    output = LOGS / "adapter-01"
    output.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "WSL adapter engineering only",
    }
    previous = os.environ.get("ANKORA_GNINA_PATH")
    try:
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise ValueError(f"Input {name} hash mismatch.")
        if sha(CONFORMER) != CONFORMER_SHA:
            raise ValueError("Input conformer hash mismatch.")
        for name in ("receptor", "ligand"):
            shutil.copyfile(INPUTS[name][0], output / f"{name}.pdbqt")
            if sha(output / f"{name}.pdbqt") != INPUTS[name][1]:
                raise ValueError(f"Copied {name} differs from original.")
        active = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        if active.stdout.strip():
            raise RuntimeError("Another GPU compute process is active.")
        os.environ["ANKORA_GNINA_PATH"] = str(BINARY)
        installation = probe_gnina()
        if installation.sha256 != INPUTS["binary"][1]:
            raise RuntimeError("The adapter probed an unexpected GNINA executable.")
        parameters = GninaDockingParameters(
            compute="cuda",
            device_index=0,
            cpu_threads=2,
            seed=20261029,
            exhaustiveness=1,
            num_modes=2,
            timeout_minutes=3,
        )
        box = BindingBox(
            center_x=11.634,
            center_y=22.47,
            center_z=5.8585,
            size_x=24.854,
            size_y=20.214,
            size_z=18.635,
        )
        evidence["parameters"] = parameters.model_dump(mode="json")
        evidence["executable_sha256"] = installation.sha256
        cancel = threading.Event()
        seen = False
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                execute_gnina,
                installation=installation,
                receptor_path=output / "receptor.pdbqt",
                ligand_path=output / "ligand.pdbqt",
                output_path=output / "poses.pdbqt",
                box=box,
                parameters=parameters,
                cancel_event=cancel,
            )
            deadline = time.monotonic() + 185
            while not future.done():
                if time.monotonic() > deadline:
                    cancel.set()
                    raise TimeoutError(
                        "The adapter did not finish within its bounded wait."
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
                for pid in query.stdout.split():
                    if not pid.isdigit():
                        continue
                    try:
                        process = psutil.Process(int(pid))
                        if process.exe() == str(BINARY) and process.cwd() == str(
                            output
                        ):
                            seen = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                time.sleep(0.1)
            execution = future.result()
        evidence["execution"] = {
            "command": execution.command,
            "exit_code": execution.exit_code,
            "stdout": execution.stdout,
            "stderr": execution.stderr,
            "canceled": execution.canceled,
            "timed_out": execution.timed_out,
        }
        evidence["gpu_process_observed"] = seen
        if (
            execution.exit_code != 0
            or execution.canceled
            or execution.timed_out
            or not seen
        ):
            raise RuntimeError("GNINA did not complete with observed GPU execution.")
        raw = (output / "poses.pdbqt").read_bytes()
        poses = parse_gnina_pdbqt(raw)
        for pose in poses:
            require_matching_topology(pose, CONFORMER.read_bytes())
        evidence["pose_count"] = len(poses)
        evidence["pose_sha256"] = sha(output / "poses.pdbqt")
        evidence["all_topologies_match"] = True
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise RuntimeError(f"Original {name} changed.")
        if sha(CONFORMER) != CONFORMER_SHA:
            raise RuntimeError("Original conformer changed.")
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - retain evidence for every failed stage
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if previous is None:
            os.environ.pop("ANKORA_GNINA_PATH", None)
        else:
            os.environ["ANKORA_GNINA_PATH"] = previous
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
