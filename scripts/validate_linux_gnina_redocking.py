"""Predeclared one-case GNINA redocking engineering check on an isolated copy."""

import json
import math
import os
import shutil
from hashlib import sha256
from typing import Any

from fastapi.testclient import TestClient
from validate_linux_gnina_binary import LOGS, sha

from ankora_backend.adapters.chemistry.redocking_rmsd import (
    in_place_rmsd,
    load_pose,
    load_reference,
)
from ankora_backend.api.app import create_app
from ankora_backend.persistence.ligand_store import LigandArtifactStore

SOURCE = LOGS / "api-cuda-01" / "data"
SOURCE_EVIDENCE = LOGS / "api-cuda-01" / "evidence.json"
TARGET = LOGS / "redocking-cuda-01"
EXPECTED_EVIDENCE = "9723f62c4e1b1dd968c14bb65ebea88e548d6d0097f4cf2a65029339f1e9fd9c"


def source_hashes() -> dict[str, str]:
    return {
        str(p.relative_to(SOURCE)): sha(p) for p in SOURCE.rglob("*") if p.is_file()
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    result: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA redocking engineering",
    }
    try:
        if sha(SOURCE_EVIDENCE) != EXPECTED_EVIDENCE:
            raise ValueError("Recorded source evidence changed")
        original = source_hashes()
        job = json.loads(SOURCE_EVIDENCE.read_text(encoding="utf-8"))["job"]
        if job["status"] != "completed":
            raise ValueError("Recorded job is not completed")
        shutil.copytree(SOURCE, TARGET / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        ligand_id = job["request"]["ligand_id"]
        reference = load_reference(
            LigandArtifactStore.from_environment().content_path(ligand_id)
        )
        with TestClient(create_app()) as client:
            options = client.get(
                "/api/v1/validation/redocking/references",
                params={
                    "source_kind": "gnina_job",
                    "source_id": job["job_id"],
                },
            )
            options.raise_for_status()
            if not any(
                row["ligand_id"] == ligand_id for row in options.json()["references"]
            ):
                raise ValueError("Matching original crystal ligand was not offered")
            expected_rmsd = []
            for pose in job["poses"]:
                artifact = pose["artifact"]
                response = client.get(
                    f"/api/v1/docking/gnina/jobs/{job['job_id']}/poses/{artifact['artifact_id']}/content"
                )
                response.raise_for_status()
                if sha256(response.content).hexdigest() != artifact["sha256"]:
                    raise ValueError("A recorded GNINA pose changed")
                expected_rmsd.append(
                    in_place_rmsd(load_pose(response.text, reference), reference)
                )
            response = client.post(
                "/api/v1/validation/redocking",
                json={
                    "source_kind": "gnina_job",
                    "source_id": job["job_id"],
                    "reference_ligand_id": ligand_id,
                    "threshold_angstrom": 2.0,
                },
            )
            response.raise_for_status()
            record = response.json()
            if (
                record["source_kind"] != "gnina_job"
                or record["bitwise_reproducible"] is not None
            ):
                raise ValueError("Wrong source or unsupported repeatability assertion")
            if len(record["poses"]) != len(job["poses"]):
                raise ValueError("The number of recorded poses changed")
            for expected, actual, rmsd in zip(
                job["poses"], record["poses"], expected_rmsd, strict=True
            ):
                if (
                    actual["rank"] != expected["mode"]
                    or actual["cnn_score"] != expected["cnn_score"]
                    or actual["cnn_affinity_pk"] != expected["cnn_affinity"]
                    or actual["binding_energy_kcal_mol"]
                    != expected["minimized_affinity_kcal_mol"]
                    or not math.isclose(actual["rmsd_angstrom"], rmsd, abs_tol=1e-8)
                ):
                    raise ValueError(
                        "Pose rank, GNINA scores, or in-place RMSD differed"
                    )
            restored = client.get(
                f"/api/v1/validation/redocking/{record['validation_id']}"
            )
            restored.raise_for_status()
            if restored.json()["metrics"] != record["metrics"]:
                raise ValueError("Saved validation did not reopen unchanged")
            result["validation"] = record
        if source_hashes() != original or sha(SOURCE_EVIDENCE) != EXPECTED_EVIDENCE:
            raise ValueError("Original project or evidence changed")
        result.update({"original_unchanged": True, "status": "completed"})
    except Exception as error:  # noqa: BLE001 - preserve engineering failure evidence
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    path = TARGET / "evidence.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "error": result.get("error"),
                "evidence_sha256": sha(path),
            }
        )
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
