"""Predeclared isolated WSL GNINA CUDA CNN_VS screening + legacy compatibility check.

Exercises through Ankora's real localhost HTTP API on isolated project copies:
1. 11-compound NCI CUDA screening campaign with hit_ranking_metric='cnn_vs',
   cnn_scoring='rescore', and cnn_model='default_1_3_ensemble' (3 built-in
   networks, --cnn CLI flag omitted), verifying child-job GPU identity, CNN_VS
   persistence, Catalog compound ranking, Methods report prose, and Export v4
   bundle integrity.
2. Non-mutating backward-compatibility check on an isolated copy of frozen
   pre-Fase-C screening-api-cuda-01, verifying default hit_ranking_metric
   ('cnn_score'), preserved CNNscore rank order, and blank gnina_cnn_vs cells
   in Export v4 without touching frozen evidence files.
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
from datetime import datetime
from hashlib import sha256
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

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
from validate_linux_gnina_binary import BINARY, LOGS, ROOT, sha
from validate_linux_gnina_topology import INPUTS

SOURCE = ROOT / "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data"
NCI_SDF = ROOT / "resources/examples/real_screening_library_100/nci_real_100.sdf"
NCI_SDF_SHA256 = "bc45046a563b7d34fb823c2b35da6d70b88af05e422a9f54022453f7b68fee0d"

FROZEN_SCREENING_DIR = LOGS / "screening-api-cuda-01"
FROZEN_SCREENING_EVIDENCE = FROZEN_SCREENING_DIR / "evidence.json"
EXPECTED_FROZEN_SCREENING_SHA = (
    "9662bd482fa2a7c93fbf22ad5b9d22dc98b4c0aa0011d4c9774e898e30c3ddac"
)
FROZEN_CANCEL_EVIDENCE = LOGS / "screening-api-cuda-cancel-02" / "evidence.json"
EXPECTED_FROZEN_CANCEL_SHA = (
    "461beaba3a75fa11a4cff711f6ca5e7e4ab9ba4ca0afd413d12b742ce57281dc"
)

TARGET = LOGS / "screening-cnn-vs-cuda-05"

RECEPTOR_ID = "f5069d65-0f0a-4bdc-a4fa-4bcaf31421fa"
BINDING_SITE_ID = "672c46c6-9f71-4420-986f-ab3ca9d8bc2b"
SEED = 20261029

EXPECTED_ENSEMBLE_IDENTITY = {
    "selector": "default_1_3_ensemble",
    "cli_argument": None,
    "member_names": [
        "dense_1_3",
        "dense_1_3_PT_KD_3",
        "crossdock_default2018_KD_4",
    ],
    "member_count": 3,
}


def source_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha(path)
        for path in root.rglob("*")
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
        raise RuntimeError(f"Expected 1 unambiguous NVIDIA GPU, observed: {rows}")
    idx_str, gpu_uuid = [part.strip() for part in rows[0].split(",", 1)]
    if idx_str != "0" or not gpu_uuid:
        raise RuntimeError(f"Unexpected GPU index/UUID row: {rows[0]!r}")
    return gpu_uuid


def ensure_gpu_idle() -> None:
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
    active = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if active:
        raise RuntimeError(f"Unrelated GPU compute process active: {active}")


def run_cnn_vs_ensemble_screening(work_dir: Path, gpu_uuid: str) -> dict[str, Any]:
    ensure_gpu_idle()
    shutil.copytree(SOURCE, work_dir)
    os.environ["ANKORA_DATA_DIR"] = str(work_dir)
    os.environ["ANKORA_GNINA_PATH"] = str(BINARY)

    ligand_store = LigandArtifactStore.from_environment()
    library = import_local_ligand_library(
        content=NCI_SDF.read_bytes(),
        filename=NCI_SDF.name,
        store=ligand_store,
    )
    if (library.imported_count, library.failed_count) != (100, 0):
        raise ValueError(
            f"Unexpected NCI import counts: {(library.imported_count, library.failed_count)}"
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
            f"Expected 11 eligible NCI compounds, got {len(selection.selected_ligand_ids)}"
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
                "preparation_id": pdbqt.artifact.preparation_id,
                "pdbqt_sha256": pdbqt.artifact.sha256,
            }
        )

    app = create_app()
    with TestClient(app) as client:
        req = {
            "receptor_id": RECEPTOR_ID,
            "binding_site_id": BINDING_SITE_ID,
            "library_id": library.artifact.library_id,
            "filter_run_id": selection.artifact.filter_run_id,
            "hit_ranking_metric": "cnn_vs",
            "parameters": {
                "compute": "cuda",
                "device_index": 0,
                "cpu_threads": 2,
                "seed": SEED,
                "exhaustiveness": 2,
                "num_modes": 3,
                "cnn_scoring": "rescore",
                "cnn_model": "default_1_3_ensemble",
                "timeout_minutes": 5,
            },
            "acknowledge_inputs_and_scoring": True,
        }
        start_t = time.monotonic()
        resp = client.post("/api/v1/docking/gnina/screenings", json=req)
        if resp.status_code != 202:
            raise RuntimeError(
                f"CNN_VS screening admission failed: {resp.status_code} {resp.text}"
            )
        campaign_id = resp.json()["campaign_id"]

        deadline = start_t + 900
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
            raise TimeoutError("CNN_VS CUDA screening did not complete within 900s")
        wall_seconds = round(time.monotonic() - start_t, 4)

        c_resp = client.get(f"/api/v1/docking/gnina/screenings/{campaign_id}")
        c_resp.raise_for_status()
        campaign = c_resp.json()
        counts = (
            campaign["status"],
            campaign["selected_count"],
            campaign["succeeded_count"],
            campaign["failed_count"],
            campaign["canceled_count"],
        )
        if counts != ("completed", 11, 11, 0, 0):
            raise RuntimeError(f"Unexpected CNN_VS campaign counts: {counts}")
        if (
            campaign["hit_ranking_metric"] != "cnn_vs"
            or campaign["request"]["hit_ranking_metric"] != "cnn_vs"
        ):
            raise ValueError("Campaign or request did not persist hit_ranking_metric='cnn_vs'")
        if campaign.get("cnn_model_identity") != EXPECTED_ENSEMBLE_IDENTITY:
            raise ValueError(
                f"Campaign cnn_model_identity mismatch: {campaign.get('cnn_model_identity')}"
            )

        intervals: list[tuple[datetime, datetime]] = []
        top_by_ligand: list[dict[str, Any]] = []
        verified_pose_count = 0
        for order, entry in enumerate(campaign["entries"]):
            job_id = entry["gnina_job_id"]
            if not job_id or entry["status"] != "completed":
                raise ValueError(f"Entry did not complete cleanly: {entry}")
            j_resp = client.get(f"/api/v1/docking/gnina/jobs/{job_id}")
            j_resp.raise_for_status()
            job = j_resp.json()
            if (
                job["screening_campaign_id"] != campaign_id
                or "--cnn" in job["command"]
                or job.get("cnn_model_identity") != EXPECTED_ENSEMBLE_IDENTITY
            ):
                raise ValueError(f"Child job ensemble/command mismatch: {job}")
            ex = job["execution"]
            if (
                not ex
                or not ex["gpu_process_observed"]
                or ex["requested_gpu_uuid"] != gpu_uuid
                or ex["observed_gpu_uuid"] != gpu_uuid
            ):
                raise ValueError(f"Child job GPU observation mismatch: {ex}")
            intervals.append(
                (
                    datetime.fromisoformat(job["started_at"]),
                    datetime.fromisoformat(job["completed_at"]),
                )
            )
            if not (1 <= len(job["poses"]) <= 3):
                raise ValueError(f"Unexpected pose count on {job_id}: {len(job['poses'])}")
            prev_score = float("inf")
            for pose in job["poses"]:
                if pose["cnn_score"] > prev_score:
                    raise ValueError(f"Within-job poses not sorted by CNNscore on {job_id}")
                prev_score = pose["cnn_score"]
                expected_vs = pose["cnn_score"] * pose["cnn_affinity"]
                if (
                    pose["cnn_vs"] is None
                    or not math.isclose(pose["cnn_vs"], expected_vs, rel_tol=0.0, abs_tol=1e-12)
                    or pose["cnn_vs_source"] != "derived_from_recorded_axes"
                ):
                    raise ValueError(f"Pose CNN_VS mismatch on {job_id}: {pose}")
                art = pose["artifact"]
                dl = client.get(
                    f"/api/v1/docking/gnina/jobs/{job_id}/poses/{art['artifact_id']}/content"
                )
                dl.raise_for_status()
                if sha256(dl.content).hexdigest() != art["sha256"]:
                    raise ValueError(f"Downloaded pose SHA-256 mismatch on {job_id}")
                verified_pose_count += 1

            top_pose = job["poses"][0]
            top_by_ligand.append(
                {
                    "selection_order": order,
                    "ligand_id": entry["ligand_id"],
                    "name": entry["name"],
                    "job_id": job_id,
                    "cnn_score": top_pose["cnn_score"],
                    "cnn_affinity": top_pose["cnn_affinity"],
                    "cnn_vs": top_pose["cnn_vs"],
                    "minimized_affinity_kcal_mol": top_pose["minimized_affinity_kcal_mol"],
                }
            )

        sorted_intervals = sorted(intervals, key=lambda pair: pair[0])
        for (_, prev_end), (next_start, _) in pairwise(sorted_intervals):
            if next_start < prev_end:
                raise ValueError("Overlapping child job intervals detected")

        expected_cnn_vs_order = [
            item["ligand_id"]
            for item in sorted(
                top_by_ligand,
                key=lambda row: (-row["cnn_vs"], row["selection_order"]),
            )
        ]
        cnn_score_order = [
            item["ligand_id"]
            for item in sorted(
                top_by_ligand,
                key=lambda row: (-row["cnn_score"], row["selection_order"]),
            )
        ]

        cat_page = client.get(
            "/api/v1/results/campaigns?scoring_family=gnina&mode=screening"
        )
        cat_page.raise_for_status()
        cat_entry = next(
            row
            for row in cat_page.json()["entries"]
            if row["record_id"] == campaign_id
        )
        best_expected = max(
            top_by_ligand, key=lambda row: (row["cnn_vs"], -row["selection_order"])
        )
        if (
            cat_entry["hit_ranking_metric"] != "cnn_vs"
            or not math.isclose(
                cat_entry["primary_cnn_vs"], best_expected["cnn_vs"], abs_tol=1e-12
            )
            or cat_entry["best_result_kcal_mol"] is not None
        ):
            raise ValueError(f"Catalog screening entry mismatch: {cat_entry}")

        comp_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds"
        )
        comp_resp.raise_for_status()
        compounds = comp_resp.json()
        if compounds["value_label"] != "CNN_VS (higher ranks first)":
            raise ValueError(f"Unexpected compounds value_label: {compounds['value_label']!r}")
        observed_compound_ids = [row["ligand_id"] for row in compounds["rows"]]
        if observed_compound_ids != expected_cnn_vs_order:
            raise ValueError(
                f"Catalog compounds order {observed_compound_ids} != expected {expected_cnn_vs_order}"
            )

        methods_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/methods"
        )
        methods_resp.raise_for_status()
        methods = methods_resp.json()
        md = methods["markdown"]
        if methods["gaps"]:
            raise ValueError(f"Expected zero Methods gaps, got: {methods['gaps']}")
        for required_phrase in (
            "`default_1_3_ensemble`",
            "`dense_1_3`, `dense_1_3_PT_KD_3`, `crossdock_default2018_KD_4`",
            "invoked by omitting `--cnn`",
            "`CNN_VS` (`CNNscore × CNNaffinity`)",
        ):
            if required_phrase not in md:
                raise ValueError(f"Missing required screening Methods phrase: {required_phrase!r}")
        lowered_md = md.lower()
        for forbidden in ("measured affinity of", "experimentally", "validated"):
            if forbidden in lowered_md:
                raise ValueError(f"Forbidden overclaim substring {forbidden!r} in Methods")

        exp_resp = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_screening", "source_id": campaign_id},
        )
        exp_resp.raise_for_status()
        exported = exp_resp.json()
        archives = [name for name in exported["files"] if name.endswith(".zip")]
        if len(archives) != 1 or exported["row_count"] != 11:
            raise ValueError(f"Unexpected screening export payload: {exported}")
        zip_dl = client.get(f"/api/v1/exports/{exported['export_id']}/{archives[0]}")
        zip_dl.raise_for_status()
        archive_path = TARGET / "screening_cnn_vs_bundle.zip"
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
                raise ValueError("Unsafe ZIP member path in screening bundle")
            by_name = {n: zf.read(n) for n in names}
            manifest = json.loads(by_name["manifest.json"].decode("utf-8"))
            if (
                manifest["ankora_export_format"] != 4
                or manifest["table"]["ranking_metric"] != "gnina_cnn_vs"
                or manifest["engine"]["cnn_model_identity"] != EXPECTED_ENSEMBLE_IDENTITY
            ):
                raise ValueError(f"Screening Export v4 manifest mismatch: {manifest}")
            for carried in manifest["source_files"]["files"]:
                matched = by_name.get(carried["path"])
                if matched is None or sha256(matched).hexdigest() != carried["sha256"]:
                    raise ValueError(f"Carried ZIP artifact digest mismatch: {carried}")
            csv_rows = list(
                csv.DictReader(io.StringIO(by_name["results.csv"].decode("utf-8")))
            )
            if [r["ligand_id"] for r in csv_rows] != expected_cnn_vs_order:
                raise ValueError("results.csv compound order does not match descending CNN_VS")
            if any(r["gnina_cnn_vs_source"] != "derived_from_recorded_axes" for r in csv_rows):
                raise ValueError("results.csv missing gnina_cnn_vs_source")
            readme = by_name["README.txt"].decode("utf-8")
            if (
                "CNN ensemble  default_1_3_ensemble" not in readme
                or "descending gnina_cnn_vs" not in readme
            ):
                raise ValueError("Screening README.txt missing ensemble or CNN_VS ranking clause")

        wait_end = time.monotonic() + 10
        while (
            app.state.gnina_screening.has_active_work()
            or app.state.gnina_docking.has_active_work()
        ) and time.monotonic() < wait_end:
            time.sleep(0.1)
        snap = app.state.resource_arbiter.snapshot()
        if (
            app.state.gnina_screening.has_active_work()
            or app.state.gnina_docking.has_active_work()
            or snap.gpu_slots_allocated != 0
            or snap.gpu_memory_reserved_bytes != 0
            or snap.active_allocations
        ):
            raise RuntimeError(f"Resources were not released after CNN_VS screening: {snap}")

    return {
        "campaign_id": campaign_id,
        "wall_seconds": wall_seconds,
        "verified_pose_count": verified_pose_count,
        "cnn_vs_ranked_ligand_ids": expected_cnn_vs_order,
        "cnn_score_ranked_ligand_ids": cnn_score_order,
        "rank_order_differs_from_cnn_score": expected_cnn_vs_order != cnn_score_order,
        "top_compounds": sorted(
            top_by_ligand, key=lambda row: (-row["cnn_vs"], row["selection_order"])
        ),
        "export_summary": {
            "export_id": exported["export_id"],
            "archive_sha256": sha(archive_path),
            "ankora_export_format": manifest["ankora_export_format"],
            "ranking_metric": manifest["table"]["ranking_metric"],
            "member_count": len(names),
        },
    }


def run_frozen_legacy_backward_compat_check(work_dir: Path) -> dict[str, Any]:
    frozen_ev = json.loads(FROZEN_SCREENING_EVIDENCE.read_text(encoding="utf-8"))
    legacy_campaign_id = frozen_ev["campaign_id"]
    shutil.copytree(FROZEN_SCREENING_DIR / "data", work_dir)
    os.environ["ANKORA_DATA_DIR"] = str(work_dir)
    os.environ["ANKORA_GNINA_PATH"] = str(BINARY)

    with TestClient(create_app()) as client:
        c_resp = client.get(f"/api/v1/docking/gnina/screenings/{legacy_campaign_id}")
        c_resp.raise_for_status()
        legacy = c_resp.json()
        if (
            legacy["hit_ranking_metric"] != "cnn_score"
            or legacy.get("cnn_model_identity") is not None
        ):
            raise ValueError(
                f"Legacy campaign defaults altered: metric={legacy['hit_ranking_metric']} "
                f"identity={legacy.get('cnn_model_identity')}"
            )

        comp_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{legacy_campaign_id}/compounds"
        )
        comp_resp.raise_for_status()
        compounds = comp_resp.json()
        if compounds["value_label"] != "CNN score (higher ranks first)":
            raise ValueError(
                f"Legacy campaign value_label changed: {compounds['value_label']!r}"
            )
        scores = [row["primary_cnn_score"] for row in compounds["rows"]]
        if scores != sorted(scores, reverse=True):
            raise ValueError("Legacy campaign compounds no longer sorted by CNNscore")

        exp_resp = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_screening", "source_id": legacy_campaign_id},
        )
        exp_resp.raise_for_status()
        exported = exp_resp.json()
        archives = [name for name in exported["files"] if name.endswith(".zip")]
        zip_dl = client.get(f"/api/v1/exports/{exported['export_id']}/{archives[0]}")
        zip_dl.raise_for_status()
        legacy_zip = TARGET / "legacy_compat_bundle.zip"
        legacy_zip.write_bytes(zip_dl.content)

        with zipfile.ZipFile(legacy_zip) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            by_name = {n: zf.read(n) for n in names}
            manifest = json.loads(by_name["manifest.json"].decode("utf-8"))
            if (
                manifest["ankora_export_format"] != 4
                or manifest["table"]["ranking_metric"] != "gnina_cnn_score"
                or "cnn_model_identity" in manifest["engine"]
            ):
                raise ValueError(f"Legacy Export v4 manifest mismatch: {manifest}")
            csv_rows = list(
                csv.DictReader(io.StringIO(by_name["results.csv"].decode("utf-8")))
            )
            if len(csv_rows) != 11 or any(
                r["gnina_cnn_vs"] != "" or r["gnina_cnn_vs_source"] != ""
                for r in csv_rows
            ):
                raise ValueError(
                    "Legacy Export v4 fabricated non-empty gnina_cnn_vs cells on pre-Fase-C poses"
                )

    return {
        "legacy_campaign_id": legacy_campaign_id,
        "loaded_hit_ranking_metric": legacy["hit_ranking_metric"],
        "compounds_value_label": compounds["value_label"],
        "export_ranking_metric": manifest["table"]["ranking_metric"],
        "blank_cnn_vs_cells_verified": True,
        "legacy_export_archive_sha256": sha(legacy_zip),
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    evidence: dict[str, Any] = {
        "status": "failed",
        "scope": (
            "isolated WSL GNINA 1.3.3 11-compound NCI CUDA CNN_VS + "
            "default_1_3_ensemble screening & legacy compatibility check"
        ),
    }
    try:
        for name, (path, expected_digest) in INPUTS.items():
            if sha(path) != expected_digest:
                raise ValueError(f"Declared {name} input hash mismatch")
        if sha(NCI_SDF) != NCI_SDF_SHA256:
            raise ValueError("Declared NCI 100 SDF hash mismatch")
        if sha(FROZEN_SCREENING_EVIDENCE) != EXPECTED_FROZEN_SCREENING_SHA:
            raise ValueError("Frozen screening-api-cuda-01 evidence hash mismatch")
        if sha(FROZEN_CANCEL_EVIDENCE) != EXPECTED_FROZEN_CANCEL_SHA:
            raise ValueError("Frozen screening-api-cuda-cancel-02 evidence hash mismatch")

        original_source = source_hashes(SOURCE)
        original_frozen_screening = source_hashes(FROZEN_SCREENING_DIR / "data")

        gpu_uuid = enumerate_single_gpu_uuid()
        evidence["enumerated_gpu_uuid"] = gpu_uuid
        evidence["cnn_vs_screening"] = run_cnn_vs_ensemble_screening(
            TARGET / "data", gpu_uuid
        )
        evidence["legacy_backward_compatibility"] = (
            run_frozen_legacy_backward_compat_check(TARGET / "legacy_compat_data")
        )

        if source_hashes(SOURCE) != original_source:
            raise ValueError("Source project files changed")
        if source_hashes(FROZEN_SCREENING_DIR / "data") != original_frozen_screening:
            raise ValueError("Frozen screening-api-cuda-01 data files changed")
        if sha(FROZEN_SCREENING_EVIDENCE) != EXPECTED_FROZEN_SCREENING_SHA:
            raise ValueError("Frozen screening-api-cuda-01 evidence.json changed")
        if sha(FROZEN_CANCEL_EVIDENCE) != EXPECTED_FROZEN_CANCEL_SHA:
            raise ValueError("Frozen screening-api-cuda-cancel-02 evidence.json changed")

        evidence["frozen_records_unchanged"] = True
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
