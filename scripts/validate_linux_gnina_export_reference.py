"""Predeclared portable GNINA export check using isolated recorded evidence."""

import json
import os
import re
import shutil
import zipfile
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from fastapi.testclient import TestClient
from validate_linux_gnina_binary import LOGS, sha

from ankora_backend.api.app import create_app
from ankora_backend.persistence.ligand_store import LigandArtifactStore

REDOCK = LOGS / "redocking-cuda-01"
INTERACTION = LOGS / "interactions-cuda-01"
SOURCE_EVIDENCE = LOGS / "api-cuda-01" / "evidence.json"
TARGET = LOGS / "export-reference-cuda-01"
EXPECTED = {
    REDOCK
    / "evidence.json": "7696efa2f3aa405d3991fd241f4dcb206a0bd5afbf23ec129162addbe70bdfea",
    INTERACTION
    / "evidence.json": "8b15df695fa878089ffc15192a43d2b4a460f7675e829910e66a53d9a56fc337",
    SOURCE_EVIDENCE: "9723f62c4e1b1dd968c14bb65ebea88e548d6d0097f4cf2a65029339f1e9fd9c",
}


def hashes(root):
    return {str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()}


def main() -> int:
    TARGET.mkdir(exist_ok=False)
    result: dict[str, Any] = {
        "status": "failed",
        "scope": "isolated WSL GNINA export engineering",
    }
    try:
        if any(sha(path) != digest for path, digest in EXPECTED.items()):
            raise ValueError("Recorded source evidence changed")
        redock_source = REDOCK / "data"
        interaction_source = INTERACTION / "data"
        before = (hashes(redock_source), hashes(interaction_source))
        job = json.loads(SOURCE_EVIDENCE.read_text(encoding="utf-8"))["job"]
        project = "projects/default"
        job_path = f"{project}/results/gnina_jobs/{job['job_id']}"
        if sha(redock_source / job_path / "record.json") != sha(
            interaction_source / job_path / "record.json"
        ):
            raise ValueError(
                "The two evidence records do not name identical GNINA jobs"
            )
        shutil.copytree(redock_source, TARGET / "data")
        analysis = json.loads(
            (INTERACTION / "evidence.json").read_text(encoding="utf-8")
        )["analysis_id"]
        analysis_dir = f"{project}/analysis/pose_interactions/{analysis}"
        source_analysis = interaction_source / analysis_dir
        if (
            json.loads((source_analysis / "record.json").read_text(encoding="utf-8"))[
                "catalog_id"
            ]
            != f"gnina_job:{job['job_id']}"
        ):
            raise ValueError("Interaction analysis belongs to a different job")
        shutil.copytree(source_analysis, TARGET / "data" / analysis_dir)
        os.environ["ANKORA_DATA_DIR"] = str(TARGET / "data")
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/exports/campaigns",
                params={
                    "source_kind": "gnina_job",
                    "source_id": job["job_id"],
                },
            )
            response.raise_for_status()
            exported = response.json()
            archives = [name for name in exported["files"] if name.endswith(".zip")]
            if len(archives) != 1:
                raise ValueError("Expected one portable ZIP")
            download = client.get(
                f"/api/v1/exports/{exported['export_id']}/{archives[0]}"
            )
            download.raise_for_status()
            archive_path = TARGET / "bundle.zip"
            archive_path.write_bytes(download.content)
            with zipfile.ZipFile(archive_path) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                if any(
                    PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                    or "\\" in name
                    or re.match(r"^[a-zA-Z]:", name)
                    for name in names
                ):
                    raise ValueError("Unsafe ZIP member path")
                data = {name: archive.read(name) for name in names}
                source_job = redock_source / job_path
                required = [
                    source_job / name
                    for name in (
                        "receptor.pdbqt",
                        "ligand.pdbqt",
                        "conformer.sdf",
                        "raw_poses.pdbqt",
                        "stdout.log",
                        "stderr.log",
                        "record.json",
                    )
                ] + [source_job / pose["artifact"]["filename"] for pose in job["poses"]]
                redock = json.loads(
                    (REDOCK / "evidence.json").read_text(encoding="utf-8")
                )["validation"]["validation_id"]
                required += [
                    redock_source
                    / project
                    / "validation"
                    / "redocking"
                    / redock
                    / "record.json",
                    source_analysis / "record.json",
                ]
                reference = LigandArtifactStore.from_environment().content_path(
                    job["request"]["ligand_id"]
                )
                reference_digest = json.loads(
                    (REDOCK / "evidence.json").read_text(encoding="utf-8")
                )["validation"]["reference_sha256"]
                if sha(reference) != reference_digest:
                    raise ValueError("The saved crystallographic reference changed")
                required.append(reference)
                for path in required:
                    if not any(
                        PurePosixPath(name).name == path.name
                        and sha256(content).hexdigest() == sha(path)
                        for name, content in data.items()
                    ):
                        raise ValueError(
                            f"Recorded artifact not present byte-for-byte in ZIP: {path.name}"
                        )
                csv_text = "\n".join(
                    content.decode("utf-8")
                    for name, content in data.items()
                    if name.endswith(".csv")
                )
                if not all(term in csv_text.lower() for term in ("cnn", "affinity")):
                    raise ValueError("Export table does not identify GNINA score axes")
                if not any(name.endswith("manifest.json") for name in names):
                    raise ValueError("Export manifest missing")
                result.update(
                    {
                        "member_count": len(names),
                        "archive_sha256": sha(archive_path),
                        "job_id": job["job_id"],
                        "analysis_id": analysis,
                        "validation_id": redock,
                        "pose_count": len(job["poses"]),
                    }
                )
        if (hashes(redock_source), hashes(interaction_source)) != before or any(
            sha(path) != digest for path, digest in EXPECTED.items()
        ):
            raise ValueError("An original project or evidence changed")
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
