"""Predeclared isolated WSL GNINA active GPU mid-campaign cancellation check (v2)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

import psutil
from ankora_backend.api.app import create_app
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    GenerateLigandConformerRequest,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import import_local_ligand_library
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from fastapi.testclient import TestClient
from validate_linux_gnina_binary import BINARY, HASHES, LOGS, sha
from validate_linux_gnina_screening_cuda import (
    BINDING_SITE_ID,
    CANCEL_LIBRARY,
    RECEPTOR_ID,
    SEED,
    SOURCE,
    ensure_gpu_idle,
    enumerate_single_gpu_uuid,
    query_compute_apps,
    source_hashes,
    write_create_only_json,
)
from validate_linux_gnina_topology import INPUTS

TARGET_CANCEL_V2 = LOGS / "screening-api-cuda-cancel-02"


def main() -> int:
    if not sys.platform.startswith("linux"):
        raise SystemExit("This protocol requires Linux.")
    original = source_hashes()
    for name in ("binary", "receptor"):
        path, expected = INPUTS[name]
        if sha(path) != expected:
            raise SystemExit(f"Recorded {name} hash mismatch")
    if sha(BINARY) != HASHES["binary"]:
        raise SystemExit("Declared GNINA binary hash mismatch")

    gpu_uuid = enumerate_single_gpu_uuid()
    TARGET_CANCEL_V2.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA active GPU mid-campaign cancellation API check (v2)",
        "enumerated_gpu_uuid": gpu_uuid,
        "library_sha256": sha256(CANCEL_LIBRARY).hexdigest(),
    }
    try:
        ensure_gpu_idle()
        shutil.copytree(SOURCE, TARGET_CANCEL_V2 / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET_CANCEL_V2 / "data")
        os.environ["ANKORA_GNINA_PATH"] = str(BINARY)

        ligand_store = LigandArtifactStore.from_environment()
        library = import_local_ligand_library(
            content=CANCEL_LIBRARY,
            filename="synthetic_cancel_screening.smi",
            store=ligand_store,
        )
        selection = apply_library_filters(
            library_id=library.artifact.library_id,
            request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
            store=ligand_store,
            worker_limit=1,
        )
        if len(selection.selected_ligand_ids) != 2:
            raise ValueError("Cancel library did not select exactly 2 molecules")

        for ligand_id in selection.selected_ligand_ids:
            evaluation = next(
                item for item in selection.evaluations if item.ligand_id == ligand_id
            )
            conformer = generate_ligand_conformer(
                ligand_id=ligand_id,
                request=GenerateLigandConformerRequest(
                    acknowledge_current_chemical_state=True,
                    state_id=evaluation.state_id,
                    random_seed=SEED,
                ),
                store=ligand_store,
            )
            prepare_ligand_pdbqt(
                ligand_id=ligand_id,
                conformer_id=conformer.artifact.conformer_id,
                request=PrepareLigandPdbqtRequest(),
                store=ligand_store,
            )

        app = create_app()
        with TestClient(app) as client:
            req = {
                "receptor_id": RECEPTOR_ID,
                "binding_site_id": BINDING_SITE_ID,
                "library_id": library.artifact.library_id,
                "filter_run_id": selection.artifact.filter_run_id,
                "parameters": {
                    "compute": "cuda",
                    "cpu_threads": 2,
                    "seed": SEED,
                    "exhaustiveness": 128,
                    "num_modes": 2,
                    "timeout_minutes": 3,
                },
                "acknowledge_inputs_and_scoring": True,
            }
            resp = client.post("/api/v1/docking/gnina/screenings", json=req)
            if resp.status_code != 202:
                raise RuntimeError(
                    f"CUDA cancel campaign admission failed: {resp.status_code} {resp.text}"
                )
            campaign_id = resp.json()["campaign_id"]
            evidence["campaign_id"] = campaign_id

            observed_pid: int | None = None
            first_job_id: str | None = None
            obs_deadline = time.monotonic() + 120
            while time.monotonic() < obs_deadline and observed_pid is None:
                entries_resp = client.get(
                    f"/api/v1/docking/gnina/screenings/{campaign_id}/entries?after_revision=0"
                )
                entries_resp.raise_for_status()
                entries = entries_resp.json()
                if entries and entries[0].get("gnina_job_id"):
                    first_job_id = str(entries[0]["gnina_job_id"])
                    expected_job_dir = (
                        TARGET_CANCEL_V2
                        / "data"
                        / "projects"
                        / "default"
                        / "results"
                        / "gnina_jobs"
                        / first_job_id
                    ).resolve()
                    for pid, obs_uuid in query_compute_apps():
                        if obs_uuid != gpu_uuid:
                            continue
                        try:
                            proc = psutil.Process(pid)
                            exe_ok = Path(proc.exe()).resolve() == BINARY.resolve()
                            cwd_ok = Path(proc.cwd()).resolve() == expected_job_dir
                            if exe_ok and cwd_ok:
                                observed_pid = pid
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                time.sleep(0.1)

            if observed_pid is None or first_job_id is None:
                client.post(f"/api/v1/docking/gnina/screenings/{campaign_id}/cancel")
                raise RuntimeError(
                    "Did not observe active child GNINA process on GPU before timeout"
                )

            evidence["observed_gpu_pid"] = observed_pid
            evidence["first_job_id"] = first_job_id

            cancel_resp = client.post(
                f"/api/v1/docking/gnina/screenings/{campaign_id}/cancel"
            )
            cancel_resp.raise_for_status()

            term_deadline = time.monotonic() + 60
            progress: dict[str, Any] = {}
            while time.monotonic() < term_deadline:
                p_resp = client.get(
                    f"/api/v1/docking/gnina/screenings/{campaign_id}/progress"
                )
                p_resp.raise_for_status()
                progress = p_resp.json()
                if progress["status"] in {"completed", "failed", "canceled"}:
                    break
                time.sleep(0.15)
            else:
                raise TimeoutError(
                    "Canceled CUDA campaign did not reach terminal state within 60s"
                )

            c_resp = client.get(f"/api/v1/docking/gnina/screenings/{campaign_id}")
            c_resp.raise_for_status()
            campaign = c_resp.json()
            evidence["campaign"] = campaign

            counts = (
                progress["status"],
                progress["selected_count"],
                progress["succeeded_count"],
                progress["failed_count"],
                progress["canceled_count"],
            )
            if counts != ("canceled", 2, 0, 0, 2):
                raise RuntimeError(
                    f"Unexpected canceled CUDA campaign counts: {counts}"
                )

            entry0, entry1 = campaign["entries"]
            if entry0["gnina_job_id"] != first_job_id or entry0["status"] != "canceled":
                raise ValueError(f"Unexpected first entry state after cancel: {entry0}")
            if entry1["gnina_job_id"] is not None or entry1["status"] != "canceled":
                raise ValueError(
                    f"Second entry should never launch a job after cancel: {entry1}"
                )

            j_resp = client.get(f"/api/v1/docking/gnina/jobs/{first_job_id}")
            j_resp.raise_for_status()
            first_job = j_resp.json()
            evidence["first_job"] = first_job
            if first_job["status"] != "canceled" or first_job["poses"]:
                raise ValueError("Canceled first child job must not publish poses")

            exit_deadline = time.monotonic() + 10
            while psutil.pid_exists(observed_pid) and time.monotonic() < exit_deadline:
                time.sleep(0.1)
            if psutil.pid_exists(observed_pid):
                raise RuntimeError(
                    f"Observed GPU process {observed_pid} still alive after cancellation"
                )

            end = time.monotonic() + 10
            while (
                app.state.gnina_screening.has_active_work()
                or app.state.gnina_docking.has_active_work()
            ) and time.monotonic() < end:
                time.sleep(0.1)
            if (
                app.state.gnina_screening.has_active_work()
                or app.state.gnina_docking.has_active_work()
                or app.state.resource_arbiter.snapshot().active_allocations
            ):
                raise RuntimeError(
                    "Resources were not released after CUDA campaign cancellation"
                )
            ensure_gpu_idle()
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve failure evidence
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}

    evidence["source_unchanged"] = source_hashes() == original
    if not evidence["source_unchanged"]:
        evidence["status"] = "failed"
    sha_cancel = write_create_only_json(TARGET_CANCEL_V2 / "evidence.json", evidence)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "evidence_sha256": sha_cancel,
            },
            indent=2,
        )
    )
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
