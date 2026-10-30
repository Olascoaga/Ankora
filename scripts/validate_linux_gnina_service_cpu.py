"""Execute the predeclared isolated GNINA CPU service engineering check."""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingParameters, GninaDockingRequest
from ankora_backend.services.gnina_docking import GninaDockingService
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.work_leases import WorkLeaseManager
from validate_linux_gnina_adapter import CONFORMER, CONFORMER_SHA
from validate_linux_gnina_binary import BINARY, LOGS, ROOT, sha
from validate_linux_gnina_topology import INPUTS

SOURCE = ROOT / "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data"
TARGET = LOGS / "service-cpu-01"
RECEPTOR = "f5069d65-0f0a-4bdc-a4fa-4bcaf31421fa"
SITE = "672c46c6-9f71-4420-986f-ab3ca9d8bc2b"
LIGAND = "a3b23f57-e4ec-4b91-b309-462848305fa7"
PREPARATION = "cd0e7607-9568-43a0-9be7-769bee894d32"


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
        "scope": "isolated WSL CPU engineering",
    }
    service = None
    leases = None
    try:
        original = source_hashes()
        for name, (path, expected) in INPUTS.items():
            if sha(path) != expected:
                raise ValueError(f"Recorded {name} hash mismatch")
        if sha(CONFORMER) != CONFORMER_SHA:
            raise ValueError("Recorded conformer hash mismatch")
        shutil.copytree(SOURCE, TARGET / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        os.environ["ANKORA_GNINA_PATH"] = str(BINARY)
        leases = WorkLeaseManager(WorkLeaseStore.from_environment())
        resources = ResourceArbiter.from_environment()
        service = GninaDockingService.from_environment(
            leases=leases, resources=resources
        )
        request = GninaDockingRequest(
            receptor_id=RECEPTOR,
            binding_site_id=SITE,
            ligand_id=LIGAND,
            ligand_preparation_id=PREPARATION,
            parameters=GninaDockingParameters(
                compute="cpu",
                cpu_threads=2,
                exhaustiveness=1,
                num_modes=2,
                timeout_minutes=3,
            ),
            acknowledge_inputs_and_scoring=True,
        )
        job = service.start(request)
        deadline = time.monotonic() + 190
        while True:
            job = service.get(job.job_id)
            if job.status in {
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
                DockingJobStatus.CANCELED,
            }:
                break
            if time.monotonic() > deadline:
                service.cancel(job.job_id)
                raise TimeoutError("Service did not reach a terminal status")
            time.sleep(0.2)
        evidence["job"] = job.model_dump(mode="json")
        if job.status is not DockingJobStatus.COMPLETED:
            raise RuntimeError(f"GNINA service ended with {job.status.value}")
        if (
            not job.poses
            or not job.execution
            or "--no_gpu" not in job.execution.command
        ):
            raise ValueError("Missing poses or explicit CPU execution evidence")
        if source_hashes() != original:
            raise ValueError("Original project data changed")
        # Completion is persisted just before leases are released by the worker.
        end = time.monotonic() + 10
        while service.has_active_work() and time.monotonic() < end:
            time.sleep(0.1)
        if service.has_active_work() or resources.snapshot().active_allocations:
            raise RuntimeError("Resources were not released")
        evidence["source_unchanged"] = True
        evidence["resources_released"] = True
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve failure evidence
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if service is not None:
            service.shutdown()
        if leases is not None:
            leases.shutdown()
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
