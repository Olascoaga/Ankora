"""Predeclared isolated WSL GNINA CUDA refinement + built-in ensemble check.

Exercises through Ankora's real localhost HTTP API on isolated project copies:
1. Fail-closed admission checks: HTTP 422 on CPU refinement, HTTP 422 on
   sub-10-minute refinement timeout, and HTTP 422 RESOURCE_REQUEST_EXCEEDS_CAPACITY
   on resources.gpu_memory_bytes when configured VRAM is below the 2 GiB claim.
2. End-to-end 1HSG/MK1 CUDA single-job run with cnn_scoring='refinement' and
   cnn_model='default_1_3_ensemble' (3 built-in models, --cnn CLI flag omitted),
   followed by in-place crystallographic redocking RMSD measurement, Catalog
   projection, Methods report verification, and Export v4 portable bundle audit.
3. Active-GPU cancellation under cnn_scoring='refinement', verifying live 2 GiB
   VRAM reservation while running and complete GPU/VRAM/CPU release on exit.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import time
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

import psutil
from ankora_backend.adapters.chemistry.redocking_rmsd import (
    in_place_rmsd,
    load_pose,
    load_reference,
)
from ankora_backend.api.app import create_app
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from fastapi.testclient import TestClient
from meeko import PDBQTMolecule, RDKitMolCreate
from rdkit import Chem
from validate_linux_gnina_adapter import CONFORMER, CONFORMER_SHA
from validate_linux_gnina_binary import BINARY, LOGS, ROOT, sha, unique
from validate_linux_gnina_topology import INPUTS

SOURCE = ROOT / "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data"
REDOCK_BASELINE_EVIDENCE = LOGS / "redocking-cuda-01" / "evidence.json"
EXPECTED_REDOCK_BASELINE_SHA = (
    "7696efa2f3aa405d3991fd241f4dcb206a0bd5afbf23ec129162addbe70bdfea"
)
STATE_SDF = unique(
    "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data/projects/default/"
    "derived/ligands/a3b23f57-e4ec-4b91-b309-462848305fa7/states/*/inspected_state.sdf"
)
EXPECTED_STATE_SHA = "0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982"

TARGET = LOGS / "refinement-cuda-02"

RECEPTOR_ID = "f5069d65-0f0a-4bdc-a4fa-4bcaf31421fa"
BINDING_SITE_ID = "672c46c6-9f71-4420-986f-ab3ca9d8bc2b"
LIGAND_ID = "a3b23f57-e4ec-4b91-b309-462848305fa7"
PREPARATION_ID = "cd0e7607-9568-43a0-9be7-769bee894d32"
SEED = 20261029

EXPECTED_ENSEMBLE_MEMBERS = [
    "dense_1_3",
    "dense_1_3_PT_KD_3",
    "crossdock_default2018_KD_4",
]
GIB = 1024 * 1024 * 1024


def source_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha(path)
        for path in root.rglob("*")
        if path.is_file()
    }


def canonical_smiles(mol: Any) -> str:
    return str(Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True))


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
        raise RuntimeError(f"Expected 1 unambiguous NVIDIA GPU, observed: {rows}")
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
        raise RuntimeError(f"Unrelated GPU compute process active: {active}")


def run_fail_closed_checks(work_dir: Path) -> dict[str, Any]:
    shutil.copytree(SOURCE, work_dir)
    os.environ["ANKORA_DATA_DIR"] = str(work_dir)
    os.environ["ANKORA_GNINA_PATH"] = str(BINARY)
    os.environ.pop("ANKORA_RESOURCE_GPU_MEMORY_TOTAL_BYTES", None)

    results: dict[str, Any] = {}
    with TestClient(create_app()) as client:
        cpu_resp = client.post(
            "/api/v1/docking/gnina/jobs",
            json={
                "receptor_id": RECEPTOR_ID,
                "binding_site_id": BINDING_SITE_ID,
                "ligand_id": LIGAND_ID,
                "ligand_preparation_id": PREPARATION_ID,
                "parameters": {
                    "compute": "cpu",
                    "cnn_scoring": "refinement",
                    "cnn_model": "default_1_3_ensemble",
                    "timeout_minutes": 15,
                },
                "acknowledge_inputs_and_scoring": True,
            },
        )
        if cpu_resp.status_code != 422:
            raise RuntimeError(
                f"Expected HTTP 422 for CPU refinement, got {cpu_resp.status_code}: {cpu_resp.text}"
            )
        results["cpu_refinement_status_code"] = cpu_resp.status_code

        short_timeout_resp = client.post(
            "/api/v1/docking/gnina/jobs",
            json={
                "receptor_id": RECEPTOR_ID,
                "binding_site_id": BINDING_SITE_ID,
                "ligand_id": LIGAND_ID,
                "ligand_preparation_id": PREPARATION_ID,
                "parameters": {
                    "compute": "cuda",
                    "cnn_scoring": "refinement",
                    "cnn_model": "default_1_3_ensemble",
                    "timeout_minutes": 9,
                },
                "acknowledge_inputs_and_scoring": True,
            },
        )
        if short_timeout_resp.status_code != 422:
            raise RuntimeError(
                f"Expected HTTP 422 for timeout_minutes=9 refinement, got {short_timeout_resp.status_code}"
            )
        results["short_timeout_status_code"] = short_timeout_resp.status_code

    os.environ["ANKORA_RESOURCE_GPU_MEMORY_TOTAL_BYTES"] = str(1 * GIB)
    try:
        with TestClient(create_app()) as low_vram_client:
            vram_resp = low_vram_client.post(
                "/api/v1/docking/gnina/jobs",
                json={
                    "receptor_id": RECEPTOR_ID,
                    "binding_site_id": BINDING_SITE_ID,
                    "ligand_id": LIGAND_ID,
                    "ligand_preparation_id": PREPARATION_ID,
                    "parameters": {
                        "compute": "cuda",
                        "cnn_scoring": "refinement",
                        "cnn_model": "default_1_3_ensemble",
                        "timeout_minutes": 15,
                    },
                    "acknowledge_inputs_and_scoring": True,
                },
            )
            if vram_resp.status_code != 422:
                raise RuntimeError(
                    f"Expected HTTP 422 for insufficient VRAM, got {vram_resp.status_code}: {vram_resp.text}"
                )
            vram_body = vram_resp.json()
            gpu_mem_err = (
                vram_body.get("details", {}).get("resources", {}).get("gpu_memory_bytes")
            )
            if (
                vram_body.get("code") != "RESOURCE_REQUEST_EXCEEDS_CAPACITY"
                or not isinstance(gpu_mem_err, dict)
                or gpu_mem_err.get("requested") != 2 * GIB
            ):
                raise RuntimeError(f"Unexpected VRAM refusal payload: {vram_body}")
            results["vram_capacity_refusal"] = {
                "status_code": vram_resp.status_code,
                "code": vram_body["code"],
                "details": vram_body["details"],
            }
    finally:
        os.environ.pop("ANKORA_RESOURCE_GPU_MEMORY_TOTAL_BYTES", None)

    return results


def run_refinement_and_downstream(
    work_dir: Path, gpu_uuid: str, expected_smiles: str
) -> dict[str, Any]:
    ensure_gpu_idle()
    shutil.copytree(SOURCE, work_dir)
    os.environ["ANKORA_DATA_DIR"] = str(work_dir)
    os.environ["ANKORA_GNINA_PATH"] = str(BINARY)

    reference = load_reference(
        LigandArtifactStore.from_environment().content_path(LIGAND_ID)
    )

    app = create_app()
    with TestClient(app) as client:
        req = {
            "receptor_id": RECEPTOR_ID,
            "binding_site_id": BINDING_SITE_ID,
            "ligand_id": LIGAND_ID,
            "ligand_preparation_id": PREPARATION_ID,
            "parameters": {
                "compute": "cuda",
                "device_index": 0,
                "cpu_threads": 2,
                "seed": SEED,
                "exhaustiveness": 4,
                "num_modes": 5,
                "cnn_scoring": "refinement",
                "cnn_model": "default_1_3_ensemble",
                "timeout_minutes": 15,
            },
            "acknowledge_inputs_and_scoring": True,
        }
        start_t = time.monotonic()
        resp = client.post("/api/v1/docking/gnina/jobs", json=req)
        if resp.status_code != 202:
            raise RuntimeError(
                f"Refinement job admission failed: {resp.status_code} {resp.text}"
            )
        job_id = resp.json()["job_id"]

        deadline = start_t + 600
        job: dict[str, Any] = {}
        while time.monotonic() < deadline:
            poll = client.get(f"/api/v1/docking/gnina/jobs/{job_id}")
            poll.raise_for_status()
            job = poll.json()
            if job["status"] in {"completed", "failed", "canceled"}:
                break
            time.sleep(0.25)
        else:
            client.post(f"/api/v1/docking/gnina/jobs/{job_id}/cancel")
            raise TimeoutError("Refinement CUDA job did not finish within 600s")
        wall_seconds = round(time.monotonic() - start_t, 4)

        if job["status"] != "completed" or not (1 <= len(job["poses"]) <= 5):
            raise RuntimeError(
                f"Unexpected refinement job outcome: status={job['status']} poses={len(job.get('poses', []))}"
            )
        cmd = job["command"]
        if "--cnn" in cmd:
            raise ValueError(
                f"default_1_3_ensemble must omit --cnn in CLI command, got: {cmd}"
            )
        if "--cnn_scoring" not in cmd or cmd[cmd.index("--cnn_scoring") + 1] != "refinement":
            raise ValueError(f"CLI command did not carry --cnn_scoring refinement: {cmd}")
        expected_identity = {
            "selector": "default_1_3_ensemble",
            "cli_argument": None,
            "member_names": EXPECTED_ENSEMBLE_MEMBERS,
            "member_count": 3,
        }
        if job.get("cnn_model_identity") != expected_identity:
            raise ValueError(
                f"Persisted cnn_model_identity mismatch: {job.get('cnn_model_identity')}"
            )
        execution = job["execution"]
        if (
            not execution
            or not execution["gpu_process_observed"]
            or execution["requested_gpu_uuid"] != gpu_uuid
            or execution["observed_gpu_uuid"] != gpu_uuid
        ):
            raise ValueError(f"GPU observation mismatch: {execution}")

        prev_score = float("inf")
        pose_digests: list[str] = []
        direct_rmsds: list[float] = []
        for idx, pose in enumerate(job["poses"], start=1):
            if pose["mode"] != idx:
                raise ValueError(f"Pose mode numbering mismatch at index {idx}: {pose}")
            if pose["cnn_score"] > prev_score:
                raise ValueError("Poses are not sorted by descending CNNscore")
            prev_score = pose["cnn_score"]
            expected_vs = pose["cnn_score"] * pose["cnn_affinity"]
            if (
                pose["cnn_vs"] is None
                or not math.isclose(pose["cnn_vs"], expected_vs, rel_tol=0.0, abs_tol=1e-12)
                or pose["cnn_vs_source"] != "derived_from_recorded_axes"
                or pose["cnn_affinity_variance"] is not None
            ):
                raise ValueError(f"Pose CNN_VS or variance contract violated: {pose}")

            art = pose["artifact"]
            dl = client.get(
                f"/api/v1/docking/gnina/jobs/{job_id}/poses/{art['artifact_id']}/content"
            )
            dl.raise_for_status()
            digest = sha256(dl.content).hexdigest()
            if digest != art["sha256"]:
                raise ValueError(f"Downloaded pose {idx} SHA-256 mismatch")
            pose_digests.append(digest)

            pose_file = work_dir / f"_verify_pose_{idx}.pdbqt"
            pose_file.write_bytes(dl.content)
            pdbqt_mol = PDBQTMolecule.from_file(str(pose_file), skip_typing=True)
            reconstructed = [
                m for m in RDKitMolCreate.from_pdbqt_mol(pdbqt_mol) if m is not None
            ]
            pose_file.unlink()
            if len(reconstructed) != 1 or canonical_smiles(reconstructed[0]) != expected_smiles:
                raise ValueError(f"Pose {idx} failed Meeko/RDKit topology verification")

            direct_rmsds.append(in_place_rmsd(load_pose(dl.text, reference), reference))

        redock_resp = client.post(
            "/api/v1/validation/redocking",
            json={
                "source_kind": "gnina_job",
                "source_id": job_id,
                "reference_ligand_id": LIGAND_ID,
                "threshold_angstrom": 2.0,
            },
        )
        redock_resp.raise_for_status()
        validation = redock_resp.json()
        if (
            validation["source_kind"] != "gnina_job"
            or validation["bitwise_reproducible"] is not None
            or len(validation["poses"]) != len(job["poses"])
        ):
            raise ValueError(f"Unexpected redocking validation payload: {validation}")
        for pose, val_pose, expected_rmsd in zip(
            job["poses"], validation["poses"], direct_rmsds, strict=True
        ):
            if (
                val_pose["rank"] != pose["mode"]
                or val_pose["cnn_score"] != pose["cnn_score"]
                or val_pose["cnn_affinity_pk"] != pose["cnn_affinity"]
                or val_pose["binding_energy_kcal_mol"] != pose["minimized_affinity_kcal_mol"]
                or not math.isclose(val_pose["rmsd_angstrom"], expected_rmsd, abs_tol=1e-8)
            ):
                raise ValueError(f"Redocking pose mismatch: {val_pose} vs {pose}")

        cat_resp = client.get("/api/v1/results/campaigns?scoring_family=gnina")
        cat_resp.raise_for_status()
        cat_entry = next(
            row for row in cat_resp.json()["entries"] if row["record_id"] == job_id
        )
        top_pose = job["poses"][0]
        if (
            cat_entry["best_result_kcal_mol"] is not None
            or not math.isclose(cat_entry["primary_cnn_vs"], top_pose["cnn_vs"], abs_tol=1e-12)
            or cat_entry["primary_cnn_score"] != top_pose["cnn_score"]
            or cat_entry["cnn_affinity_pk"] != top_pose["cnn_affinity"]
        ):
            raise ValueError(f"Catalog entry score axes mismatch: {cat_entry}")

        methods_resp = client.get(
            f"/api/v1/results/campaigns/gnina_job/{job_id}/methods"
        )
        methods_resp.raise_for_status()
        methods = methods_resp.json()
        md = methods["markdown"]
        if methods["gaps"]:
            raise ValueError(f"Expected zero Methods gaps, got: {methods['gaps']}")
        for required_phrase in (
            "scoring mode `refinement`",
            "`default_1_3_ensemble`",
            "`dense_1_3`, `dense_1_3_PT_KD_3`, `crossdock_default2018_KD_4`",
            "invoked by omitting `--cnn`",
            "combined 3D CNN and empirical scoring gradients",
            "not an independent empirical energy check",
        ):
            if required_phrase not in md:
                raise ValueError(f"Missing required Methods phrase: {required_phrase!r}")
        lowered_md = md.lower()
        for forbidden in ("measured affinity of", "experimentally", "validated"):
            if forbidden in lowered_md:
                raise ValueError(f"Forbidden overclaim substring {forbidden!r} in Methods")

        exp_resp = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_job", "source_id": job_id},
        )
        exp_resp.raise_for_status()
        exported = exp_resp.json()
        archives = [name for name in exported["files"] if name.endswith(".zip")]
        if len(archives) != 1 or exported["redocking_validation_count"] != 1:
            raise ValueError(f"Unexpected export response: {exported}")
        zip_dl = client.get(f"/api/v1/exports/{exported['export_id']}/{archives[0]}")
        zip_dl.raise_for_status()
        archive_path = TARGET / "refinement_bundle.zip"
        archive_path.write_bytes(zip_dl.content)

        with zipfile.ZipFile(archive_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if any(
                PurePosixPath(n).is_absolute()
                or ".." in PurePosixPath(n).parts
                or "\\" in n
                or re.match(r"^[a-zA-Z]:", n)
                for n in names
            ):
                raise ValueError("Unsafe ZIP member path in refinement bundle")
            by_suffix = {PurePosixPath(n).name: zf.read(n) for n in names}
            manifest = json.loads(by_suffix["manifest.json"].decode("utf-8"))
            if (
                manifest["ankora_export_format"] != 4
                or manifest["engine"]["cnn_model_identity"] != expected_identity
            ):
                raise ValueError(f"Export v4 manifest mismatch: {manifest}")
            notes_joined = " ".join(manifest["scientific_notes"])
            if (
                "dense_1_3, dense_1_3_PT_KD_3, crossdock_default2018_KD_4" not in notes_joined
                or "not an independent empirical energy check" not in notes_joined
            ):
                raise ValueError(f"Export scientific_notes missing disclosures: {notes_joined}")
            readme = by_suffix["README.txt"].decode("utf-8")
            if (
                "CNN ensemble  default_1_3_ensemble" not in readme
                or "Refinement note:" not in readme
            ):
                raise ValueError("README.txt missing ensemble or refinement disclosure")
            csv_rows = list(
                csv.DictReader(io.StringIO(by_suffix["results.csv"].decode("utf-8")))
            )
            if len(csv_rows) != len(job["poses"]):
                raise ValueError("results.csv pose count mismatch")
            for row, pose in zip(csv_rows, job["poses"], strict=True):
                if (
                    row["gnina_cnn_vs_source"] != "derived_from_recorded_axes"
                    or not math.isclose(float(row["gnina_cnn_vs"]), pose["cnn_vs"], abs_tol=1e-9)
                ):
                    raise ValueError(f"CSV CNN_VS mismatch: {row}")

        end_wait = time.monotonic() + 10
        while app.state.gnina_docking.has_active_work() and time.monotonic() < end_wait:
            time.sleep(0.1)
        snap = app.state.resource_arbiter.snapshot()
        if (
            app.state.gnina_docking.has_active_work()
            or snap.gpu_slots_allocated != 0
            or snap.gpu_memory_reserved_bytes != 0
            or snap.active_allocations
        ):
            raise RuntimeError(f"Resources were not fully released after completion: {snap}")

    return {
        "wall_seconds": wall_seconds,
        "job": job,
        "pose_sha256s": pose_digests,
        "redocking_validation": {
            "validation_id": validation["validation_id"],
            "metrics": validation["metrics"],
            "poses": validation["poses"],
        },
        "catalog_entry": cat_entry,
        "methods_software": methods["software"],
        "export_summary": {
            "export_id": exported["export_id"],
            "archive_sha256": sha(archive_path),
            "ankora_export_format": manifest["ankora_export_format"],
            "member_count": len(names),
        },
    }


def run_active_gpu_refinement_cancellation(
    work_dir: Path, gpu_uuid: str
) -> dict[str, Any]:
    ensure_gpu_idle()
    shutil.copytree(SOURCE, work_dir)
    os.environ["ANKORA_DATA_DIR"] = str(work_dir)
    os.environ["ANKORA_GNINA_PATH"] = str(BINARY)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/docking/gnina/jobs",
            json={
                "receptor_id": RECEPTOR_ID,
                "binding_site_id": BINDING_SITE_ID,
                "ligand_id": LIGAND_ID,
                "ligand_preparation_id": PREPARATION_ID,
                "parameters": {
                    "compute": "cuda",
                    "device_index": 0,
                    "cpu_threads": 2,
                    "seed": SEED,
                    "exhaustiveness": 64,
                    "num_modes": 5,
                    "cnn_scoring": "refinement",
                    "cnn_model": "default_1_3_ensemble",
                    "timeout_minutes": 15,
                },
                "acknowledge_inputs_and_scoring": True,
            },
        )
        if resp.status_code != 202:
            raise RuntimeError(
                f"Cancellation refinement job admission failed: {resp.status_code} {resp.text}"
            )
        job_id = resp.json()["job_id"]
        job_dir = work_dir / "projects" / "default" / "results" / "gnina_jobs" / job_id

        deadline = time.monotonic() + 180
        observed_proc: psutil.Process | None = None
        observed_vram_reserved = 0
        while time.monotonic() < deadline:
            cur = client.get(f"/api/v1/docking/gnina/jobs/{job_id}").json()
            if cur["status"] in {"completed", "failed", "canceled"}:
                raise RuntimeError(
                    f"Refinement job ended ({cur['status']}) before live GPU observation"
                )
            snap_live = app.state.resource_arbiter.snapshot()
            for pid, pid_uuid in query_compute_apps():
                if pid_uuid != gpu_uuid:
                    continue
                try:
                    cand = psutil.Process(pid)
                    if cand.exe() == str(BINARY) and Path(cand.cwd()).resolve() == job_dir.resolve():
                        observed_proc = cand
                        observed_vram_reserved = snap_live.gpu_memory_reserved_bytes or 0
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if observed_proc is not None:
                break
            time.sleep(0.1)

        if observed_proc is None:
            client.post(f"/api/v1/docking/gnina/jobs/{job_id}/cancel")
            raise TimeoutError("Live GPU process was not observed for refinement job")
        if observed_vram_reserved != 2 * GIB:
            client.post(f"/api/v1/docking/gnina/jobs/{job_id}/cancel")
            raise ValueError(
                f"Expected 2 GiB live VRAM reservation while running, got {observed_vram_reserved}"
            )

        cancel_resp = client.post(f"/api/v1/docking/gnina/jobs/{job_id}/cancel")
        cancel_resp.raise_for_status()

        term_deadline = time.monotonic() + 60
        final_job: dict[str, Any] = {}
        while time.monotonic() < term_deadline:
            final_job = client.get(f"/api/v1/docking/gnina/jobs/{job_id}").json()
            if final_job["status"] in {"completed", "failed", "canceled"}:
                break
            time.sleep(0.15)
        else:
            raise TimeoutError("Canceled refinement job did not reach terminal status")

        if (
            final_job["status"] != "canceled"
            or final_job["poses"]
            or not final_job["execution"]
            or not final_job["execution"]["canceled"]
        ):
            raise RuntimeError(f"Unexpected canceled refinement job record: {final_job}")

        wait_end = time.monotonic() + 10
        while app.state.gnina_docking.has_active_work() and time.monotonic() < wait_end:
            time.sleep(0.1)
        snap_after = app.state.resource_arbiter.snapshot()
        if (
            app.state.gnina_docking.has_active_work()
            or snap_after.gpu_slots_allocated != 0
            or snap_after.gpu_memory_reserved_bytes != 0
            or snap_after.active_allocations
        ):
            raise RuntimeError(f"Resources were not released after cancellation: {snap_after}")
        if observed_proc.is_running() and observed_proc.status() != psutil.STATUS_ZOMBIE:
            raise RuntimeError("Observed GNINA refinement GPU process did not exit")
        ensure_gpu_idle()

    return {
        "job_id": job_id,
        "observed_gpu_pid": observed_proc.pid,
        "live_vram_reserved_bytes": observed_vram_reserved,
        "final_status": final_job["status"],
        "published_pose_count": len(final_job["poses"]),
        "canceled_flag": final_job["execution"]["canceled"],
        "post_cancel_gpu_slots": snap_after.gpu_slots_allocated,
        "post_cancel_vram_reserved_bytes": snap_after.gpu_memory_reserved_bytes,
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": (
            "isolated WSL GNINA 1.3.3 CUDA refinement + default_1_3_ensemble "
            "engineering check (not a multi-target scientific benchmark)"
        ),
    }
    try:
        original_source = source_hashes(SOURCE)
        for name, (path, expected_digest) in INPUTS.items():
            if sha(path) != expected_digest:
                raise ValueError(f"Declared {name} input hash mismatch")
        if sha(CONFORMER) != CONFORMER_SHA:
            raise ValueError("Declared conformer hash mismatch")
        if sha(STATE_SDF) != EXPECTED_STATE_SHA:
            raise ValueError("Declared state SDF hash mismatch")
        if sha(REDOCK_BASELINE_EVIDENCE) != EXPECTED_REDOCK_BASELINE_SHA:
            raise ValueError("Frozen redocking-cuda-01 evidence hash mismatch")

        baseline_redock = json.loads(
            REDOCK_BASELINE_EVIDENCE.read_text(encoding="utf-8")
        )["validation"]
        state_mol = next(
            m for m in Chem.SDMolSupplier(str(STATE_SDF), removeHs=False) if m is not None
        )
        expected_smiles = canonical_smiles(state_mol)

        gpu_uuid = enumerate_single_gpu_uuid()
        evidence["enumerated_gpu_uuid"] = gpu_uuid
        evidence["fail_closed_checks"] = run_fail_closed_checks(
            TARGET / "failclosed_data"
        )
        evidence["refinement_single_job"] = run_refinement_and_downstream(
            TARGET / "data", gpu_uuid, expected_smiles
        )
        evidence["rescore_baseline_comparison"] = {
            "note": (
                "Exploratory single-target comparison on 1HSG/MK1 only; baseline "
                "redocking-cuda-01 used exhaustiveness=1, num_modes=2, rescore, dense_1_3, "
                "whereas refinement-cuda-02 used exhaustiveness=4, num_modes=5, refinement, "
                "default_1_3_ensemble."
            ),
            "rescore_baseline_metrics": baseline_redock["metrics"],
            "refinement_ensemble_metrics": evidence["refinement_single_job"][
                "redocking_validation"
            ]["metrics"],
        }
        evidence["active_gpu_cancellation"] = run_active_gpu_refinement_cancellation(
            TARGET / "cancel_data", gpu_uuid
        )

        if source_hashes(SOURCE) != original_source:
            raise ValueError("Source project files changed")
        if sha(REDOCK_BASELINE_EVIDENCE) != EXPECTED_REDOCK_BASELINE_SHA:
            raise ValueError("Frozen redocking-cuda-01 evidence changed")
        evidence["source_unchanged"] = True
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve failure evidence
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}

    out_path = TARGET / "evidence.json"
    with out_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "evidence_sha256": sha(out_path),
            }
        )
    )
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
