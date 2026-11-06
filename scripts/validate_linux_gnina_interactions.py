"""Predeclared ProLIF integration check on an isolated recorded CUDA job."""

import json
import os
import shutil
from typing import Any

from fastapi.testclient import TestClient
from validate_linux_gnina_binary import LOGS, sha

from ankora_backend.api.app import create_app

SOURCE = LOGS / "api-cuda-01" / "data"
SOURCE_EVIDENCE = LOGS / "api-cuda-01" / "evidence.json"
TARGET = LOGS / "interactions-cuda-01"
EXPECTED_EVIDENCE = "9723f62c4e1b1dd968c14bb65ebea88e548d6d0097f4cf2a65029339f1e9fd9c"


def source_hashes() -> dict[str, str]:
    return {
        str(p.relative_to(SOURCE)): sha(p) for p in SOURCE.rglob("*") if p.is_file()
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    result: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA/ProLIF engineering",
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
        pose = job["poses"][0]
        root = (
            f"/api/v1/results/campaigns/gnina_job/{job['job_id']}"
            f"/compounds/{job['request']['ligand_id']}/poses"
        )
        with TestClient(create_app()) as client:
            response = client.get(root)
            response.raise_for_status()
            inventory = response.json()
            first = inventory["poses"][0]
            if (
                first["sha256"] != pose["artifact"]["sha256"]
                or first["cnn_score"] != pose["cnn_score"]
                or first["cnn_affinity_pk"] != pose["cnn_affinity"]
                or first["result_kcal_mol"] != pose["minimized_affinity_kcal_mol"]
            ):
                raise ValueError(
                    "Pose identity or score semantics differ from GNINA output"
                )
            url = f"{root}/{first['artifact_id']}/interactions"
            analyzed = client.post(url, json={})
            analyzed.raise_for_status()
            analysis = analyzed.json()
            if (
                analysis["pose"]["sha256"] != first["sha256"]
                or analysis["engine_key"] != "gnina_job"
            ):
                raise ValueError("Analysis identifies a different pose or engine")
            history = client.get(url)
            history.raise_for_status()
            if not any(
                item["analysis_id"] == analysis["analysis_id"]
                for item in history.json()
            ):
                raise ValueError("Analysis was not preserved")
            result.update(
                {
                    "pose_sha256": first["sha256"],
                    "cnn_score": first["cnn_score"],
                    "detector": analysis["detector"],
                    "contact_count": len(analysis["contacts"]),
                    "analysis_id": analysis["analysis_id"],
                }
            )
        if source_hashes() != original or sha(SOURCE_EVIDENCE) != EXPECTED_EVIDENCE:
            raise ValueError("Original project or evidence changed")
        result.update({"original_unchanged": True, "status": "completed"})
    except Exception as error:  # noqa: BLE001 - retain failure evidence
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
