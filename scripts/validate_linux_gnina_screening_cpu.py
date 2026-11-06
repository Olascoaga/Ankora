"""Predeclared, isolated two-molecule WSL GNINA CPU API engineering check."""

from __future__ import annotations

import json
import os
import shutil
import time
from hashlib import sha256
from typing import Any

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
from validate_linux_gnina_binary import BINARY, HASHES, LOGS, ROOT, sha
from validate_linux_gnina_topology import INPUTS

SOURCE = ROOT / "logs/linux-crystal-redocking-smoke/exploratory-followup-01/data"
TARGET = LOGS / "screening-api-cpu-01"
LIBRARY = b"CCO ethanol\nCCN ethylamine\n"


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
        "scope": "isolated WSL GNINA screening CPU API engineering only",
        "library_sha256": sha256(LIBRARY).hexdigest(),
        "source_unchanged": None,
    }
    original: dict[str, str] | None = None
    try:
        original = source_hashes()
        for name in ("binary", "receptor"):
            path, expected = INPUTS[name]
            if sha(path) != expected:
                raise ValueError(f"Recorded {name} hash mismatch")
        if sha(BINARY) != HASHES["binary"]:
            raise ValueError("Declared GNINA binary hash mismatch")
        shutil.copytree(SOURCE, TARGET / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        os.environ["ANKORA_GNINA_PATH"] = str(BINARY)
        ligand_store = LigandArtifactStore.from_environment()
        library = import_local_ligand_library(
            content=LIBRARY, filename="synthetic_screening.smi", store=ligand_store
        )
        selection = apply_library_filters(
            library_id=library.artifact.library_id,
            request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
            store=ligand_store,
            worker_limit=1,
        )
        if len(selection.selected_ligand_ids) != 2:
            raise ValueError(
                "The declared library did not select exactly two molecules"
            )
        prepared = []
        for ligand_id in selection.selected_ligand_ids:
            evaluation = next(
                item for item in selection.evaluations if item.ligand_id == ligand_id
            )
            conformer = generate_ligand_conformer(
                ligand_id=ligand_id,
                request=GenerateLigandConformerRequest(
                    acknowledge_current_chemical_state=True,
                    state_id=evaluation.state_id,
                    random_seed=20261029,
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
            request = {
                "receptor_id": "f5069d65-0f0a-4bdc-a4fa-4bcaf31421fa",
                "binding_site_id": "672c46c6-9f71-4420-986f-ab3ca9d8bc2b",
                "library_id": library.artifact.library_id,
                "filter_run_id": selection.artifact.filter_run_id,
                "parameters": {
                    "compute": "cpu",
                    "cpu_threads": 2,
                    "seed": 20261029,
                    "exhaustiveness": 1,
                    "num_modes": 2,
                    "timeout_minutes": 3,
                },
                "acknowledge_inputs_and_scoring": True,
            }
            response = client.post("/api/v1/docking/gnina/screenings", json=request)
            if response.status_code != 202:
                raise RuntimeError(
                    f"Admission failed: {response.status_code} {response.text}"
                )
            campaign_id = response.json()["campaign_id"]
            evidence["campaign_id"] = campaign_id
            deadline = time.monotonic() + 400
            while time.monotonic() < deadline:
                response = client.get(
                    f"/api/v1/docking/gnina/screenings/{campaign_id}/progress"
                )
                response.raise_for_status()
                progress = response.json()
                if progress["status"] in {"completed", "failed", "canceled"}:
                    break
                time.sleep(0.2)
            else:
                client.post(f"/api/v1/docking/gnina/screenings/{campaign_id}/cancel")
                raise TimeoutError("GNINA screening did not finish")
            response = client.get(f"/api/v1/docking/gnina/screenings/{campaign_id}")
            response.raise_for_status()
            campaign = response.json()
            evidence["campaign"] = campaign
            if (
                progress["status"],
                progress["selected_count"],
                progress["succeeded_count"],
                progress["failed_count"],
                progress["canceled_count"],
            ) != ("completed", 2, 2, 0, 0):
                raise RuntimeError(f"Unexpected campaign outcome: {progress}")
            evidence["jobs"] = []
            for entry in campaign["entries"]:
                job_response = client.get(
                    f"/api/v1/docking/gnina/jobs/{entry['gnina_job_id']}"
                )
                job_response.raise_for_status()
                job = job_response.json()
                if (
                    job["status"] != "completed"
                    or job["screening_campaign_id"] != campaign_id
                    or job["request"]["ligand_id"] != entry["ligand_id"]
                    or not job["poses"]
                    or job["tool"]["sha256"] != HASHES["binary"]
                ):
                    raise ValueError("A completed entry does not match its GNINA job")
                scores = [pose["cnn_score"] for pose in job["poses"]]
                if scores != sorted(scores, reverse=True):
                    raise ValueError("GNINA pose order did not preserve CNN scores")
                for pose in job["poses"]:
                    artifact = pose["artifact"]
                    pose_response = client.get(
                        f"/api/v1/docking/gnina/jobs/{job['job_id']}/poses/{artifact['artifact_id']}/content"
                    )
                    pose_response.raise_for_status()
                    if sha256(pose_response.content).hexdigest() != artifact["sha256"]:
                        raise ValueError("Retrieved pose hash differs from its record")
                evidence["jobs"].append(job)
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
                raise RuntimeError("Resources were not released")
        evidence["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve the observed failure
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    if original is not None:
        evidence["source_unchanged"] = source_hashes() == original
        if not evidence["source_unchanged"]:
            evidence["status"] = "failed"
            evidence["source_integrity_error"] = "Original source project files changed"
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
