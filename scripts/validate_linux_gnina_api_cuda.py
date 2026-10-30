"""Predeclared isolated WSL GNINA CUDA HTTP service engineering check."""

import json
import os
import shutil
import subprocess
import time
from hashlib import sha256
from typing import Any

from ankora_backend.api.app import create_app
from fastapi.testclient import TestClient
from validate_linux_gnina_adapter import CONFORMER, CONFORMER_SHA
from validate_linux_gnina_binary import BINARY, LOGS, ROOT, sha
from validate_linux_gnina_topology import INPUTS

SOURCE = ROOT / "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data"
TARGET = LOGS / "api-cuda-01"


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(SOURCE)): sha(path)
        for path in SOURCE.rglob("*")
        if path.is_file()
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL CUDA HTTP engineering",
    }
    try:
        original = source_hashes()
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise ValueError(f"Recorded {name} hash mismatch")
        if sha(CONFORMER) != CONFORMER_SHA:
            raise ValueError("Recorded conformer hash mismatch")
        active = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        if active.stdout.strip():
            raise RuntimeError("Another GPU compute process is active")
        shutil.copytree(SOURCE, TARGET / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        os.environ["ANKORA_GNINA_PATH"] = str(BINARY)
        app = create_app()
        with TestClient(app) as client:
            request = {
                "receptor_id": "f5069d65-0f0a-4bdc-a4fa-4bcaf31421fa",
                "binding_site_id": "672c46c6-9f71-4420-986f-ab3ca9d8bc2b",
                "ligand_id": "a3b23f57-e4ec-4b91-b309-462848305fa7",
                "ligand_preparation_id": "cd0e7607-9568-43a0-9be7-769bee894d32",
                "parameters": {
                    "compute": "cuda",
                    "cpu_threads": 2,
                    "exhaustiveness": 1,
                    "num_modes": 2,
                    "timeout_minutes": 3,
                },
                "acknowledge_inputs_and_scoring": True,
            }
            response = client.post("/api/v1/docking/gnina/jobs", json=request)
            if response.status_code != 202:
                raise RuntimeError(
                    f"Admission failed: {response.status_code} {response.text}"
                )
            job_id = response.json()["job_id"]
            deadline = time.monotonic() + 190
            while time.monotonic() < deadline:
                response = client.get(f"/api/v1/docking/gnina/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                if job["status"] in {"completed", "failed", "canceled"}:
                    break
                time.sleep(0.2)
            else:
                client.post(f"/api/v1/docking/gnina/jobs/{job_id}/cancel")
                raise TimeoutError("GNINA job did not finish")
            evidence["job"] = job
            if job["status"] != "completed" or not job["poses"]:
                raise RuntimeError(f"GNINA job ended {job['status']}")
            execution = job["execution"]
            if (
                not execution
                or not execution["gpu_process_observed"]
                or not execution["requested_gpu_uuid"]
                or execution["requested_gpu_uuid"] != execution["observed_gpu_uuid"]
            ):
                raise ValueError(
                    "The observed GPU identity did not match the selected GPU"
                )
            retrieved = []
            for pose in job["poses"]:
                artifact = pose["artifact"]
                response = client.get(
                    f"/api/v1/docking/gnina/jobs/{job_id}/poses/"
                    f"{artifact['artifact_id']}/content"
                )
                response.raise_for_status()
                digest = sha256(response.content).hexdigest()
                if digest != artifact["sha256"]:
                    raise ValueError("Retrieved pose hash differs from its record")
                retrieved.append(digest)
            end = time.monotonic() + 10
            while app.state.gnina_docking.has_active_work() and time.monotonic() < end:
                time.sleep(0.1)
            if (
                app.state.gnina_docking.has_active_work()
                or app.state.resource_arbiter.snapshot().active_allocations
            ):
                raise RuntimeError("Resources were not released")
            evidence["pose_hashes"] = retrieved
        if source_hashes() != original:
            raise ValueError("Original project data changed")
        evidence["source_unchanged"] = True
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve failure evidence
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    path = TARGET / "evidence.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "evidence_sha256": sha(path),
            }
        )
    )
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
