"""Predeclared Methods check against an isolated recorded WSL CUDA job."""

import json
import os
import shutil
from typing import Any

from fastapi.testclient import TestClient
from validate_linux_gnina_binary import LOGS, sha

from ankora_backend.api.app import create_app

SOURCE = LOGS / "api-cuda-01" / "data"
SOURCE_EVIDENCE = LOGS / "api-cuda-01" / "evidence.json"
TARGET = LOGS / "methods-cuda-01"
EXPECTED_EVIDENCE = "9723f62c4e1b1dd968c14bb65ebea88e548d6d0097f4cf2a65029339f1e9fd9c"


def source_hashes() -> dict[str, str]:
    return {
        str(p.relative_to(SOURCE)): sha(p) for p in SOURCE.rglob("*") if p.is_file()
    }


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    result: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA Methods engineering",
    }
    try:
        if sha(SOURCE_EVIDENCE) != EXPECTED_EVIDENCE:
            raise ValueError("Source evidence changed")
        original = source_hashes()
        job = json.loads(SOURCE_EVIDENCE.read_text(encoding="utf-8"))["job"]
        if job["status"] != "completed":
            raise ValueError("Source job is not completed")
        shutil.copytree(SOURCE, TARGET / "data")
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        with TestClient(create_app()) as client:
            response = client.get(
                f"/api/v1/results/campaigns/gnina_job/{job['job_id']}/methods"
            )
            response.raise_for_status()
            report = response.json()
            markdown = report["markdown"]
            lower = markdown.lower()
            for term in (
                "gnina",
                "cnn",
                "dense_1_3",
                "rescore",
                "pk",
                "kcal",
                job["tool"]["version"],
                job["tool"]["sha256"],
                str(job["request"]["parameters"]["seed"]),
            ):
                if term.lower() not in lower:
                    raise ValueError(f"Required recorded term missing: {term}")
            if "lamarckian" in lower or "autogrid" in lower:
                raise ValueError("Report attributed another engine's procedure")
            if not any(
                item["name"] == "GNINA" and item["version"] == job["tool"]["version"]
                for item in report["software"]
            ):
                raise ValueError("GNINA version missing from software table")
            result["report"] = report
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
