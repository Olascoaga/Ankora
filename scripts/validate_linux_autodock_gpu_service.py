"""Run the predeclared isolated WSL AutoDock-GPU API engineering smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ankora_backend.adapters.engines import autodock_gpu as gpu_adapter
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.api.app import create_app
from fastapi.testclient import TestClient
from validate_linux_api_preparation import ROOT, SmokeFailure, digest_bytes, require_input

PRIOR_EVIDENCE_SHA = "d0a5ca8c9bfae80f70b607dec17c18b90bb3efb2348aeb3e913dbbeba732db4b"
GPU_SHA = "3e1bba7691983c97e1d64fef6cc45dd8306d54d10e5f81f50185694f06e8be78"
AUTOGRID_SHA = "91621b89d13410efde31aed2a0934b15837172ef167d783bec0b3a94d384dc72"
PRIOR = ROOT / "logs" / "linux-crystal-redocking-smoke" / "exploratory-followup-01"
GPU = (
    ROOT
    / "logs"
    / "linux-autodock-gpu-investigation-20261029"
    / "source-build-02"
    / "AutoDock-GPU-e63e6f6280ebfad18caa3e8f48afdc269e79e063"
    / "bin"
    / "autodock_gpu_128wi"
)
AUTOGRID = Path("/usr/bin/autogrid4")
PARAMETERS = {
    "runs": 2,
    "population_size": 150,
    "energy_evaluations": 5000,
    "heuristics": False,
    "autostop": False,
    "local_search_method": "ad",
    "cluster_rmsd_tolerance_angstrom": 2.0,
    "seed_1": 20261029,
    "seed_2": 20261030,
    "seed_3": 20261031,
    "device_number": 1,
    "timeout_minutes": 2,
}


def snapshot(root: Path) -> dict[str, str]:
    """Hash every regular file, refusing symlinks or non-file entries."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("The source project contains a symbolic link.")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        elif not path.is_dir():
            raise ValueError("The source project contains a non-regular entry.")
    if not result:
        raise ValueError("The source project has no files.")
    return result


def require_output_path(path: Path, root: Path = ROOT) -> Path:
    output = path.resolve()
    allowed = (root / "logs" / "linux-autodock-gpu-service-smoke").resolve()
    if output == allowed or not output.is_relative_to(allowed):
        raise ValueError("Output must be a new directory under the isolated GPU service logs root.")
    return output


def run(output_path: Path) -> dict[str, Any]:
    output = require_output_path(output_path)
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "status": "failed",
        "events": events,
        "scope": "WSL exploratory API smoke; discovery alone overridden, scientific tools real.",
        "discovery_override": "exact predeclared executable and SHA-256 only",
    }
    names = (
        "ANKORA_DATA_DIR",
        "ANKORA_RESOURCE_CPU_THREADS",
        "ANKORA_RESOURCE_GPU_SLOTS",
        "ANKORA_AUTODOCK_GPU_PATH",
        "ANKORA_AUTOGRID4_PATH",
    )
    previous = {name: os.environ.get(name) for name in names}
    stage = "initialization"
    original_snapshot: dict[str, str] | None = None
    try:
        if sys.platform != "linux":
            raise SmokeFailure("This protocol requires Linux.")
        previous_evidence = json.loads(require_input(PRIOR / "evidence.json", PRIOR_EVIDENCE_SHA))
        if previous_evidence["status"] != "completed":
            raise SmokeFailure("The prior exploratory project did not complete.")
        require_input(GPU, GPU_SHA)
        require_input(AUTOGRID, AUTOGRID_SHA)
        if not os.access(GPU, os.X_OK) or GPU.read_bytes()[:4] != b"\x7fELF":
            raise SmokeFailure("The pinned GPU executable is not a native executable ELF.")
        for name in ("ankora-device-probe.fld", "ankora-device-probe.pdbqt"):
            if (GPU.parent / name).exists():
                raise SmokeFailure("The device probe's deliberately missing input exists.")
        source_data = PRIOR / "data"
        original_snapshot = snapshot(source_data)
        shutil.copytree(source_data, output / "data", symlinks=False)
        if snapshot(output / "data") != original_snapshot:
            raise SmokeFailure("Copied source data differs from the isolated original.")
        evidence["original_file_hashes"] = original_snapshot
        source_events = {
            item["stage"]: item["body"]
            for item in previous_evidence["events"]
            if item["stage"]
            in {
                "structure_import",
                "crystal_extraction",
                "receptor_preparation",
                "ligand_pdbqt",
                "binding_site",
            }
        }
        source_id = source_events["structure_import"]["artifact"]["artifact_id"]
        source_sha = source_events["structure_import"]["artifact"]["sha256"]
        ligand_id = source_events["crystal_extraction"]["artifact"]["ligand_id"]
        ligand_sha = source_events["crystal_extraction"]["artifact"]["sha256"]
        preparation_id = source_events["ligand_pdbqt"]["artifact"]["preparation_id"]
        receptor_id = source_events["receptor_preparation"]["receptor_id"]
        site_id = source_events["binding_site"]["binding_site_id"]
        os.environ.update(
            {
                "ANKORA_DATA_DIR": str(output / "data"),
                "ANKORA_RESOURCE_CPU_THREADS": "2",
                "ANKORA_RESOURCE_GPU_SLOTS": "1",
                "ANKORA_AUTODOCK_GPU_PATH": str(GPU),
                "ANKORA_AUTOGRID4_PATH": str(AUTOGRID),
            }
        )

        def explicit_discovery(configured: str | Path | None) -> DiscoveredTool:
            if configured is None or Path(configured).resolve() != GPU.resolve():
                return DiscoveredTool(available=False, path=None)
            require_input(GPU, GPU_SHA)
            return DiscoveredTool(
                available=True, path=str(GPU), architecture="x86_64", sha256=GPU_SHA
            )

        app = create_app()
        with patch.object(gpu_adapter, "discover_autodock_gpu", explicit_discovery):  # noqa: SIM117
            with TestClient(app, headers={"Origin": "http://127.0.0.1:1420"}) as client:

                def call(
                    name: str, method: str, path: str, expected: int, **kwargs: Any
                ) -> dict[str, Any]:
                    response = client.request(method, "/api/v1" + path, **kwargs)
                    try:
                        body = response.json()
                    except ValueError:
                        body = {"text": response.text}
                    events.append(
                        {
                            "stage": name,
                            "method": method,
                            "path": path,
                            "request": kwargs.get("json"),
                            "status": response.status_code,
                            "body": body,
                        }
                    )
                    if response.status_code != expected or not isinstance(body, dict):
                        raise SmokeFailure(
                            f"{name} returned HTTP {response.status_code}, expected {expected}."
                        )
                    return body

                stage = "autogrid"
                maps = call(
                    stage,
                    "POST",
                    "/autogrid/map-sets",
                    200,
                    json={
                        "receptor_id": receptor_id,
                        "binding_site_id": site_id,
                        "source": "ligand_preparation",
                        "ligand_id": ligand_id,
                        "ligand_preparation_id": preparation_id,
                    },
                )
                if maps["reused_existing_map_set"]:
                    raise SmokeFailure("The protocol requires newly generated AutoGrid maps.")
                stage = "gpu_start"
                job = call(
                    stage,
                    "POST",
                    "/docking/autodock-gpu/jobs",
                    202,
                    json={
                        "receptor_id": receptor_id,
                        "binding_site_id": site_id,
                        "map_set_id": maps["record"]["map_set_id"],
                        "ligand_id": ligand_id,
                        "ligand_preparation_id": preparation_id,
                        "parameters": PARAMETERS,
                        "acknowledge_inputs_and_scoring": True,
                    },
                )
                job_id = job["job_id"]
                stage = "gpu_result"
                deadline = time.monotonic() + 140
                while job["status"] not in {"completed", "failed", "canceled"}:
                    if time.monotonic() >= deadline:
                        call(
                            "gpu_cancel", "POST", f"/docking/autodock-gpu/jobs/{job_id}/cancel", 200
                        )
                        raise SmokeFailure("GPU docking did not terminate within the bounded wait.")
                    time.sleep(0.25)
                    job = call(stage, "GET", f"/docking/autodock-gpu/jobs/{job_id}", 200)
                if job["status"] != "completed" or not job["runs"] or not job["clusters"]:
                    raise SmokeFailure("GPU docking did not complete with saved runs and clusters.")
                execution = job["execution"]
                if (
                    not execution
                    or execution["exit_code"] != 0
                    or execution["timed_out"]
                    or execution["canceled"]
                    or not execution["success_reported_on_stdout"]
                ):
                    raise SmokeFailure("The GPU execution record is incomplete or unsuccessful.")
                report = job["provenance"]["parameters"]["execution_device_report"]
                if (
                    report["status"] != "reported"
                    or report["runtime"] != "CUDA"
                    or not report["matches_probe"]
                ):
                    raise SmokeFailure(
                        "Execution did not report the same CUDA device as the probe."
                    )
                for pose in job["runs"]:
                    artifact = pose["artifact"]
                    response = client.get("/api/v1" + artifact["content_url"])
                    actual = digest_bytes(response.content)
                    events.append(
                        {"stage": "pose_content", "status": response.status_code, "sha256": actual}
                    )
                    if response.status_code != 200 or actual != artifact["sha256"]:
                        raise SmokeFailure("A saved pose failed its content hash check.")
                stage = "input_integrity"
                for path, expected in (
                    (f"/structures/{source_id}/content", source_sha),
                    (f"/ligands/{ligand_id}/content", ligand_sha),
                ):
                    response = client.get("/api/v1" + path)
                    if response.status_code != 200 or digest_bytes(response.content) != expected:
                        raise SmokeFailure("An original structure or ligand changed.")
                deadline = time.monotonic() + 10
                while True:
                    scheduler = app.state.resource_arbiter.snapshot()
                    if scheduler.gpu_slots_allocated == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise SmokeFailure("The GPU reservation was not released.")
                    time.sleep(0.1)
                evidence.update(
                    {
                        "status": "completed",
                        "job_id": job_id,
                        "map_set_id": maps["record"]["map_set_id"],
                        "run_count": len(job["runs"]),
                        "device_report": report,
                        "gpu_slots_allocated_after": scheduler.gpu_slots_allocated,
                    }
                )
    except Exception as error:
        evidence["failure"] = {"stage": stage, "type": type(error).__name__, "message": str(error)}
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if original_snapshot is not None:
            try:
                evidence["original_project_unchanged"] = (
                    snapshot(PRIOR / "data") == original_snapshot
                )
                if not evidence["original_project_unchanged"]:
                    evidence["status"] = "failed"
                    evidence["failure"] = {
                        "stage": "input_integrity",
                        "message": "Source project changed.",
                    }
            except Exception as error:
                evidence["status"] = "failed"
                evidence["failure"] = {"stage": "input_integrity", "message": str(error)}
    with (output / "evidence.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.output)
    except (ValueError, FileExistsError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"GPU service smoke: {result['status']}")
    if "failure" in result:
        print(json.dumps(result["failure"]))
    print(f"Evidence SHA-256: {digest_bytes((args.output / 'evidence.json').read_bytes())}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
