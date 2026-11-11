"""Predeclared isolated WSL GNINA CUDA screening & active GPU cancellation checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import psutil
from ankora_backend.api.app import create_app
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    GenerateLigandConformerRequest,
    LigandLibraryFilterPlan,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import import_local_ligand_library
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from fastapi.testclient import TestClient
from validate_linux_gnina_binary import BINARY, HASHES, LOGS, ROOT, sha
from validate_linux_gnina_topology import INPUTS

SOURCE = ROOT / "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data"
NCI_SDF = ROOT / "resources/examples/real_screening_library_100/nci_real_100.sdf"
NCI_SDF_SHA256 = "bc45046a563b7d34fb823c2b35da6d70b88af05e422a9f54022453f7b68fee0d"

RECEPTOR_ID = "f5069d65-0f0a-4bdc-a4fa-4bcaf31421fa"
BINDING_SITE_ID = "672c46c6-9f71-4420-986f-ab3ca9d8bc2b"
SEED = 20261029

TARGET_SCREEN = LOGS / "screening-api-cuda-01"
TARGET_CANCEL = LOGS / "screening-api-cuda-cancel-01"
CANCEL_LIBRARY = b"CCO ethanol\nCCN ethylamine\n"


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(SOURCE)): sha(path)
        for path in SOURCE.rglob("*")
        if path.is_file()
    }


def enumerate_single_gpu_uuid() -> str:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    rows = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise RuntimeError(
            f"Expected exactly 1 NVIDIA GPU, observed {len(rows)}: {rows}"
        )
    idx_str, gpu_uuid = [part.strip() for part in rows[0].split(",", 1)]
    if idx_str != "0" or not gpu_uuid:
        raise RuntimeError(f"Unexpected GPU index/UUID row: {rows[0]!r}")
    return gpu_uuid


def query_compute_apps() -> list[tuple[int, str]]:
    proc = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,gpu_uuid",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    apps: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        pid_s, uuid_s = [part.strip() for part in line.split(",", 1)]
        apps.append((int(pid_s), uuid_s))
    return apps


def ensure_gpu_idle() -> None:
    active = query_compute_apps()
    if active:
        raise RuntimeError(f"Unrelated GPU compute process active before run: {active}")


def write_create_only_json(path: Path, payload: dict[str, Any]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return sha(path)


def run_nci11_cuda_screening(gpu_uuid: str) -> dict[str, Any]:
    TARGET_SCREEN.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA 11-molecule NCI CUDA screening API check",
        "enumerated_gpu_uuid": gpu_uuid,
        "nci_sdf_sha256": NCI_SDF_SHA256,
    }
    try:
        ensure_gpu_idle()
        shutil.copytree(SOURCE, TARGET_SCREEN / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET_SCREEN / "data")
        os.environ["ANKORA_GNINA_PATH"] = str(BINARY)

        ligand_store = LigandArtifactStore.from_environment()
        library = import_local_ligand_library(
            content=NCI_SDF.read_bytes(),
            filename=NCI_SDF.name,
            store=ligand_store,
        )
        if (library.imported_count, library.failed_count) != (100, 0):
            raise ValueError(
                f"Unexpected NCI library import counts: {library.imported_count}, {library.failed_count}"
            )
        demo_plan = LigandLibraryFilterPlan(
            preset="custom",
            require_lipinski=True,
            max_lipinski_violations=1,
            require_veber=True,
            require_ghose=True,
            require_muegge=True,
            minimum_qed=0.3,
            pains_policy="exclude",
            brenk_policy="exclude",
            duplicate_policy="exclude",
        )
        selection = apply_library_filters(
            library_id=library.artifact.library_id,
            request=ApplyLigandLibraryFilterRequest(
                plan=demo_plan,
                acknowledge_selection=True,
            ),
            store=ligand_store,
            worker_limit=1,
        )
        if len(selection.selected_ligand_ids) != 11:
            raise ValueError(
                f"Expected exactly 11 eligible NCI compounds, got {len(selection.selected_ligand_ids)}"
            )

        prepared: list[dict[str, Any]] = []
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
            pdbqt = prepare_ligand_pdbqt(
                ligand_id=ligand_id,
                conformer_id=conformer.artifact.conformer_id,
                request=PrepareLigandPdbqtRequest(),
                store=ligand_store,
            )
            prepared.append(
                {
                    "ligand_id": ligand_id,
                    "state_id": evaluation.state_id,
                    "conformer_id": conformer.artifact.conformer_id,
                    "conformer_sha256": conformer.artifact.sha256,
                    "preparation_id": pdbqt.artifact.preparation_id,
                    "pdbqt_sha256": pdbqt.artifact.sha256,
                    "meeko_version": pdbqt.tool.version,
                }
            )
        evidence["prepared"] = prepared

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
                    "exhaustiveness": 1,
                    "num_modes": 2,
                    "timeout_minutes": 3,
                },
                "acknowledge_inputs_and_scoring": True,
            }
            resp = client.post("/api/v1/docking/gnina/screenings", json=req)
            if resp.status_code != 202:
                raise RuntimeError(
                    f"CUDA screening admission failed: {resp.status_code} {resp.text}"
                )
            campaign_id = resp.json()["campaign_id"]
            evidence["campaign_id"] = campaign_id

            deadline = time.monotonic() + 900
            progress: dict[str, Any] = {}
            while time.monotonic() < deadline:
                p_resp = client.get(
                    f"/api/v1/docking/gnina/screenings/{campaign_id}/progress"
                )
                p_resp.raise_for_status()
                progress = p_resp.json()
                if progress["status"] in {"completed", "failed", "canceled"}:
                    break
                time.sleep(0.25)
            else:
                client.post(f"/api/v1/docking/gnina/screenings/{campaign_id}/cancel")
                raise TimeoutError(
                    "11-molecule CUDA screening did not finish within 900s"
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
            if counts != ("completed", 11, 11, 0, 0):
                raise RuntimeError(f"Unexpected CUDA campaign counts: {counts}")

            jobs: list[dict[str, Any]] = []
            intervals: list[tuple[datetime, datetime]] = []
            total_verified_poses = 0
            for entry in campaign["entries"]:
                j_resp = client.get(
                    f"/api/v1/docking/gnina/jobs/{entry['gnina_job_id']}"
                )
                j_resp.raise_for_status()
                job = j_resp.json()
                execution = job.get("execution")
                if (
                    job["status"] != "completed"
                    or job["screening_campaign_id"] != campaign_id
                    or job["request"]["ligand_id"] != entry["ligand_id"]
                    or not (1 <= len(job["poses"]) <= 2)
                    or job["tool"]["sha256"] != HASHES["binary"]
                ):
                    raise ValueError(
                        f"Completed entry/job mismatch for {entry['ligand_id']}"
                    )
                if (
                    not execution
                    or not execution.get("gpu_process_observed")
                    or execution.get("requested_gpu_uuid") != gpu_uuid
                    or execution.get("observed_gpu_uuid") != gpu_uuid
                ):
                    raise ValueError(
                        f"CUDA GPU UUID observation failed on job {job['job_id']}: {execution}"
                    )
                scores = [pose["cnn_score"] for pose in job["poses"]]
                if scores != sorted(scores, reverse=True):
                    raise ValueError(
                        f"CNN score ordering violated on job {job['job_id']}: {scores}"
                    )
                started_at = datetime.fromisoformat(job["started_at"])
                completed_at = datetime.fromisoformat(job["completed_at"])
                if intervals and intervals[-1][1] > started_at:
                    raise ValueError(
                        f"Overlapping serial job intervals: {intervals[-1][1]} > {started_at}"
                    )
                intervals.append((started_at, completed_at))
                for pose in job["poses"]:
                    artifact = pose["artifact"]
                    pose_resp = client.get(
                        f"/api/v1/docking/gnina/jobs/{job['job_id']}/poses/{artifact['artifact_id']}/content"
                    )
                    pose_resp.raise_for_status()
                    if sha256(pose_resp.content).hexdigest() != artifact["sha256"]:
                        raise ValueError(
                            f"Pose SHA-256 mismatch on {artifact['artifact_id']}"
                        )
                    total_verified_poses += 1
                jobs.append(job)

            evidence["verified_pose_downloads"] = total_verified_poses
            evidence["jobs"] = jobs

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
                    "Resources were not released after 11-molecule CUDA campaign"
                )
            ensure_gpu_idle()
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve failure evidence
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    return evidence


def run_cuda_mid_campaign_cancel(gpu_uuid: str) -> dict[str, Any]:
    TARGET_CANCEL.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA active GPU mid-campaign cancellation API check",
        "enumerated_gpu_uuid": gpu_uuid,
        "library_sha256": sha256(CANCEL_LIBRARY).hexdigest(),
    }
    try:
        ensure_gpu_idle()
        shutil.copytree(SOURCE, TARGET_CANCEL / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET_CANCEL / "data")
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
                    f"/api/v1/docking/gnina/screenings/{campaign_id}/entries"
                )
                entries_resp.raise_for_status()
                payload = entries_resp.json()
                entries = payload["entries"] if isinstance(payload, dict) else payload
                if entries and entries[0].get("gnina_job_id"):
                    first_job_id = str(entries[0]["gnina_job_id"])
                    expected_job_dir = (
                        TARGET_CANCEL
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
    return evidence


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
    if sha(NCI_SDF) != NCI_SDF_SHA256:
        raise SystemExit("Declared nci_real_100.sdf hash mismatch")

    gpu_uuid = enumerate_single_gpu_uuid()

    ev_screen = run_nci11_cuda_screening(gpu_uuid)
    ev_screen["source_unchanged"] = source_hashes() == original
    if not ev_screen["source_unchanged"]:
        ev_screen["status"] = "failed"
    sha_screen = write_create_only_json(TARGET_SCREEN / "evidence.json", ev_screen)

    ev_cancel = run_cuda_mid_campaign_cancel(gpu_uuid)
    ev_cancel["source_unchanged"] = source_hashes() == original
    if not ev_cancel["source_unchanged"]:
        ev_cancel["status"] = "failed"
    sha_cancel = write_create_only_json(TARGET_CANCEL / "evidence.json", ev_cancel)

    summary = {
        "screening_cuda_01": {
            "status": ev_screen["status"],
            "error": ev_screen.get("error"),
            "evidence_sha256": sha_screen,
        },
        "screening_cuda_cancel_01": {
            "status": ev_cancel["status"],
            "error": ev_cancel.get("error"),
            "evidence_sha256": sha_cancel,
        },
    }
    print(json.dumps(summary, indent=2))
    ok = ev_screen["status"] == "completed" and ev_cancel["status"] == "completed"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
