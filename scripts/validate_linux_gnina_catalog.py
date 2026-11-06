"""Predeclared read-only projection check followed by trash on an isolated copy."""

import json
import os
import shutil
from hashlib import sha256
from typing import Any

from ankora_backend.api.app import create_app
from fastapi.testclient import TestClient
from validate_linux_gnina_binary import LOGS, sha

SOURCE = LOGS / "api-cuda-01" / "data"
SOURCE_EVIDENCE = LOGS / "api-cuda-01" / "evidence.json"
TARGET = LOGS / "catalog-cuda-01"
EXPECTED_EVIDENCE = "9723f62c4e1b1dd968c14bb65ebea88e548d6d0097f4cf2a65029339f1e9fd9c"


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(SOURCE)): sha(path)
        for path in SOURCE.rglob("*")
        if path.is_file()
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    result: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL catalog engineering",
    }
    try:
        if sha(SOURCE_EVIDENCE) != EXPECTED_EVIDENCE:
            raise ValueError("Recorded source evidence changed")
        original = source_hashes()
        evidence = json.loads(SOURCE_EVIDENCE.read_text(encoding="utf-8"))
        original_job = evidence["job"]
        if original_job["status"] != "completed":
            raise ValueError("The recorded source job is not completed")
        shutil.copytree(SOURCE, TARGET / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        with TestClient(create_app()) as client:
            job_id = original_job["job_id"]
            page = client.get("/api/v1/results/campaigns?scoring_family=gnina")
            page.raise_for_status()
            entry = next(
                item for item in page.json()["entries"] if item["record_id"] == job_id
            )
            top = original_job["poses"][0]
            if (
                entry["best_result_kcal_mol"] is not None
                or entry["primary_cnn_score"] != top["cnn_score"]
                or entry["cnn_affinity_pk"] != top["cnn_affinity"]
                or entry["minimized_affinity_kcal_mol"]
                != top["minimized_affinity_kcal_mol"]
            ):
                raise ValueError(
                    "Catalog score axes do not match the recorded top pose"
                )
            for pose in original_job["poses"]:
                response = client.get(
                    f"/api/v1/docking/gnina/jobs/{job_id}/poses/{pose['artifact']['artifact_id']}/content"
                )
                response.raise_for_status()
                if sha256(response.content).hexdigest() != pose["artifact"]["sha256"]:
                    raise ValueError("Pose hash mismatch")
            methods = client.get(
                f"/api/v1/results/campaigns/gnina_job/{job_id}/methods"
            )
            if (
                methods.status_code != 409
                or methods.json()["code"] != "GNINA_METHODS_UNAVAILABLE"
            ):
                raise ValueError("Unsupported Methods did not fail closed")
            trash = client.post(
                "/api/v1/results/campaigns/trash",
                json={
                    "catalog_ids": [f"gnina_job:{job_id}"],
                    "acknowledge_removal": True,
                },
            )
            trash.raise_for_status()
            if client.get(f"/api/v1/docking/gnina/jobs/{job_id}").status_code != 404:
                raise ValueError("Copied result remained visible after Trash")
            result["score"] = entry["primary_cnn_score"]
            result["pose_count"] = len(original_job["poses"])
            result["trash_recoverable"] = trash.json()["recoverable"]
        if source_hashes() != original or sha(SOURCE_EVIDENCE) != EXPECTED_EVIDENCE:
            raise ValueError("Original project or evidence changed")
        result["original_unchanged"] = True
        result["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - retain engineering failure evidence
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
