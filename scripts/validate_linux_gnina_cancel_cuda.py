"""Cancel an isolated GNINA service job only after observing its GPU process."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

import psutil
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
TARGET = LOGS / "service-cancel-cuda-01"
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
        "scope": "isolated WSL CUDA cancellation engineering",
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
        leases = WorkLeaseManager(WorkLeaseStore.from_environment())
        resources = ResourceArbiter.from_environment()
        service = GninaDockingService.from_environment(
            leases=leases, resources=resources, enable_experimental_cuda=True
        )
        request = GninaDockingRequest(
            receptor_id=RECEPTOR,
            binding_site_id=SITE,
            ligand_id=LIGAND,
            ligand_preparation_id=PREPARATION,
            parameters=GninaDockingParameters(
                compute="cuda",
                cpu_threads=2,
                exhaustiveness=128,
                num_modes=2,
                timeout_minutes=3,
            ),
            acknowledge_inputs_and_scoring=True,
        )
        job = service.start(request)
        job_dir = (
            TARGET
            / "data"
            / "projects"
            / "default"
            / "results"
            / "gnina_jobs"
            / job.job_id
        )
        deadline = time.monotonic() + 190
        process = None
        while time.monotonic() < deadline:
            job = service.get(job.job_id)
            if job.status in {
                DockingJobStatus.COMPLETED,
                DockingJobStatus.FAILED,
                DockingJobStatus.CANCELED,
            }:
                raise RuntimeError("The job ended before observing its GPU process")
            query = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            for value in query.stdout.split():
                if not value.isdigit():
                    continue
                try:
                    candidate = psutil.Process(int(value))
                    if candidate.exe() == str(BINARY) and candidate.cwd() == str(
                        job_dir
                    ):
                        process = candidate
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if process is not None:
                break
            time.sleep(0.1)
        if process is None:
            service.cancel(job.job_id)
            raise TimeoutError("The job's GPU process was not observed")
        evidence["observed_gpu_pid"] = process.pid
        service.cancel(job.job_id)
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
        if job.status is not DockingJobStatus.CANCELED:
            raise RuntimeError(f"GNINA service ended with {job.status.value}")
        if job.poses or not job.execution or not job.execution.canceled:
            raise ValueError(
                "Canceled execution published poses or lacked cancellation evidence"
            )
        if source_hashes() != original:
            raise ValueError("Original project data changed")
        # Completion is persisted just before leases are released by the worker.
        end = time.monotonic() + 10
        while service.has_active_work() and time.monotonic() < end:
            time.sleep(0.1)
        if service.has_active_work() or resources.snapshot().active_allocations:
            raise RuntimeError("Resources were not released")
        if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
            raise RuntimeError("The observed GNINA process did not exit")
        evidence["source_unchanged"] = True
        evidence["resources_released"] = True
        evidence["process_exited"] = True
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
