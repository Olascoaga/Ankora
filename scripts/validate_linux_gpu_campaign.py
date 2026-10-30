"""Run the declared isolated Linux GPU campaign and real cancellation test."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psutil
from ankora_backend.adapters.engines import autodock_gpu as gpu_adapter
from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.api.app import create_app
from fastapi.testclient import TestClient
from validate_linux_api_preparation import SmokeFailure, digest_bytes, require_input
from validate_linux_autodock_gpu_service import (
    AUTOGRID,
    AUTOGRID_SHA,
    GPU,
    GPU_SHA,
    PARAMETERS,
    PRIOR,
    PRIOR_EVIDENCE_SHA,
    require_output_path,
    snapshot,
)

SYNTHETIC_LIBRARY = b"CCO ethanol\nCCN ethylamine\n"
TERMINAL = {"completed", "failed", "canceled"}


def reference_ids(events: list[dict[str, Any]]) -> tuple[str, str]:
    """Read only the two reference events, ignoring payload-free artifact checks."""
    source = {
        item["stage"]: item["body"]
        for item in events
        if item["stage"] in {"receptor_preparation", "binding_site"}
    }
    return source["receptor_preparation"]["receptor_id"], source["binding_site"][
        "binding_site_id"
    ]


def run(output_path: Path, *, product_discovery: bool = False) -> dict[str, Any]:
    output = require_output_path(output_path)
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "status": "failed",
        "events": events,
        "scope": "WSL engineering smoke, not scientific validation",
    }
    names = (
        "ANKORA_DATA_DIR",
        "ANKORA_RESOURCE_CPU_THREADS",
        "ANKORA_RESOURCE_GPU_SLOTS",
        "ANKORA_AUTODOCK_GPU_PATH",
        "ANKORA_AUTOGRID4_PATH",
        "PATH",
    )
    previous = {name: os.environ.get(name) for name in names}
    source_snapshot: dict[str, str] | None = None
    stage = "initialization"
    try:
        gpu_binary = (
            Path.home() / "tools" / "autodock-gpu-1.6" / "bin" / "autodock_gpu_128wi"
            if product_discovery
            else GPU
        ).resolve()
        evidence["discovery_mode"] = (
            "product" if product_discovery else "pinned test override"
        )
        if sys.platform != "linux":
            raise SmokeFailure("This protocol requires Linux.")
        old = json.loads(require_input(PRIOR / "evidence.json", PRIOR_EVIDENCE_SHA))
        if old["status"] != "completed":
            raise SmokeFailure("The prior exploratory project did not complete.")
        require_input(gpu_binary, GPU_SHA)
        require_input(AUTOGRID, AUTOGRID_SHA)
        source_snapshot = snapshot(PRIOR / "data")
        shutil.copytree(PRIOR / "data", output / "data", symlinks=False)
        if snapshot(output / "data") != source_snapshot:
            raise SmokeFailure("The source copy differs from the original.")
        receptor_id, site_id = reference_ids(old["events"])
        os.environ.update(
            {
                "ANKORA_DATA_DIR": str(output / "data"),
                "ANKORA_RESOURCE_CPU_THREADS": "2",
                "ANKORA_RESOURCE_GPU_SLOTS": "1",
                "ANKORA_AUTOGRID4_PATH": str(AUTOGRID),
                "PATH": str(Path(sys.executable).parent)
                + os.pathsep
                + os.environ.get("PATH", ""),
            }
        )
        if product_discovery:
            os.environ.pop("ANKORA_AUTODOCK_GPU_PATH", None)
        else:
            os.environ["ANKORA_AUTODOCK_GPU_PATH"] = str(gpu_binary)

        def explicit_discovery(configured: str | Path | None) -> DiscoveredTool:
            if configured is None or Path(configured).resolve() != gpu_binary:
                return DiscoveredTool(available=False, path=None)
            require_input(gpu_binary, GPU_SHA)
            return DiscoveredTool(
                available=True,
                path=str(gpu_binary),
                architecture="x86_64",
                sha256=GPU_SHA,
            )

        app = create_app()
        discovery_context = (
            nullcontext()
            if product_discovery
            else patch.object(gpu_adapter, "discover_autodock_gpu", explicit_discovery)
        )
        with discovery_context:  # noqa: SIM117
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
                            f"{name}: HTTP {response.status_code}, expected {expected}."
                        )
                    return body

                if product_discovery:
                    stage = "product_discovery"
                    tools = call(stage, "GET", "/tools", 200)
                    gpu_tool = tools["autodock_gpu"]
                    if not gpu_tool["available"] or gpu_tool["sha256"] != GPU_SHA:
                        raise SmokeFailure(
                            "Product discovery did not identify the pinned GPU binary."
                        )
                    if Path(gpu_tool["path"]).resolve() != gpu_binary:
                        raise SmokeFailure(
                            "Product discovery selected a different GPU binary."
                        )
                stage = "import_library"
                library = call(
                    stage,
                    "POST",
                    "/ligand-libraries/import",
                    201,
                    files={
                        "file": (
                            "synthetic_library.smi",
                            SYNTHETIC_LIBRARY,
                            "chemical/x-daylight-smiles",
                        )
                    },
                )
                library_id = library["artifact"]["library_id"]
                if library["imported_count"] != 2 or library["failed_count"] != 0:
                    raise SmokeFailure(
                        "The synthetic two-entry library was not fully imported."
                    )
                stage = "filter_library"
                selection = call(
                    stage,
                    "POST",
                    f"/ligand-libraries/{library_id}/filter-runs",
                    201,
                    json={
                        "plan": {},
                        "state_overrides": {},
                        "acknowledge_selection": True,
                    },
                )
                filter_id = selection["artifact"]["filter_run_id"]
                ligand_ids = selection["selected_ligand_ids"]
                if len(ligand_ids) != 2:
                    raise SmokeFailure(
                        "The declared filter did not select both synthetic molecules."
                    )
                preparations: dict[str, str] = {}
                for ligand_id in ligand_ids:
                    stage = "prepare_ligand"
                    conformer = call(
                        stage,
                        "POST",
                        f"/ligands/{ligand_id}/conformers/generate",
                        201,
                        json={
                            "force_field": "MMFF94s",
                            "max_iterations": 500,
                            "random_seed": 20261029,
                            "acknowledge_current_chemical_state": True,
                        },
                    )
                    conformer_id = conformer["artifact"]["conformer_id"]
                    pdbqt = call(
                        stage,
                        "POST",
                        f"/ligands/{ligand_id}/conformers/{conformer_id}/pdbqt",
                        201,
                        json={"charge_model": "gasteiger"},
                    )
                    preparations[ligand_id] = pdbqt["artifact"]["preparation_id"]
                stage = "autogrid"
                maps = call(
                    stage,
                    "POST",
                    "/autogrid/map-sets",
                    200,
                    json={
                        "receptor_id": receptor_id,
                        "binding_site_id": site_id,
                        "source": "filter_run",
                        "library_id": library_id,
                        "filter_run_id": filter_id,
                    },
                )
                if maps["reused_existing_map_set"]:
                    raise SmokeFailure("The protocol requires fresh maps.")
                map_id = maps["record"]["map_set_id"]
                stage = "campaign_start"
                batch = call(
                    stage,
                    "POST",
                    "/docking/autodock-gpu/batches",
                    202,
                    json={
                        "receptor_id": receptor_id,
                        "binding_site_id": site_id,
                        "map_set_id": map_id,
                        "library_id": library_id,
                        "filter_run_id": filter_id,
                        "parameters": PARAMETERS,
                        "acknowledge_inputs_and_scoring": True,
                    },
                )
                batch_id = batch["batch_id"]
                deadline = time.monotonic() + 140
                while batch["status"] not in TERMINAL:
                    if time.monotonic() >= deadline:
                        call(
                            "campaign_timeout_cancel",
                            "POST",
                            f"/docking/autodock-gpu/batches/{batch_id}/cancel",
                            200,
                        )
                        raise SmokeFailure("Campaign exceeded the declared wait.")
                    time.sleep(0.1)
                    batch = call(
                        "campaign_poll",
                        "GET",
                        f"/docking/autodock-gpu/batches/{batch_id}",
                        200,
                    )
                stage = "campaign_result"
                if batch["status"] != "completed" or batch["succeeded_count"] != 2:
                    raise SmokeFailure(
                        "The two-ligand campaign did not complete successfully."
                    )
                report = batch["provenance"]["parameters"]["execution_device_report"]
                if report["runtime"] != "CUDA" or not report["matches_probe"]:
                    raise SmokeFailure(
                        "Campaign device report did not match the CUDA probe."
                    )
                for entry in batch["entries"]:
                    if entry["status"] != "completed" or not entry["runs"]:
                        raise SmokeFailure("A library entry has no completed runs.")
                    for run_record in entry["runs"]:
                        artifact = run_record["artifact"]
                        response = client.get("/api/v1" + artifact["content_url"])
                        if (
                            response.status_code != 200
                            or digest_bytes(response.content) != artifact["sha256"]
                        ):
                            raise SmokeFailure(
                                "A campaign pose does not match its recorded hash."
                            )
                deadline = time.monotonic() + 10
                while app.state.resource_arbiter.snapshot().gpu_slots_allocated:
                    if time.monotonic() >= deadline:
                        raise SmokeFailure("Campaign GPU reservation was not released.")
                    time.sleep(0.05)
                stage = "cancel_start"
                parameters = {**PARAMETERS, "energy_evaluations": 100_000_000}
                job = call(
                    stage,
                    "POST",
                    "/docking/autodock-gpu/jobs",
                    202,
                    json={
                        "receptor_id": receptor_id,
                        "binding_site_id": site_id,
                        "map_set_id": map_id,
                        "ligand_id": ligand_ids[0],
                        "ligand_preparation_id": preparations[ligand_ids[0]],
                        "parameters": parameters,
                        "acknowledge_inputs_and_scoring": True,
                    },
                )
                job_id = job["job_id"]
                job_dir = (
                    output
                    / "data"
                    / "projects"
                    / "default"
                    / "results"
                    / "autodock_gpu_jobs"
                    / job_id
                )
                stage = "observe_process"
                deadline = time.monotonic() + 30
                target = None
                while time.monotonic() < deadline:
                    for proc in psutil.process_iter(
                        ["pid", "exe", "cwd", "create_time"]
                    ):
                        info = proc.info
                        if info["exe"] == str(gpu_binary) and info["cwd"] == str(
                            job_dir
                        ):
                            target = proc
                            evidence["cancel_process"] = {
                                "pid": info["pid"],
                                "create_time": info["create_time"],
                            }
                            break
                    if target:
                        break
                    time.sleep(0.01)
                if target is None:
                    call(
                        "unobserved_cancel",
                        "POST",
                        f"/docking/autodock-gpu/jobs/{job_id}/cancel",
                        200,
                    )
                    raise SmokeFailure(
                        "Cancellation inconclusive: job process was not observed."
                    )
                stage = "observe_gpu_context"
                observed_gpu = False
                while time.monotonic() < deadline and target.is_running():
                    query = subprocess.run(
                        [
                            "nvidia-smi",
                            "--query-compute-apps=pid",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                    evidence["gpu_process_query"] = {
                        "exit_code": query.returncode,
                        "stdout": query.stdout,
                        "stderr": query.stderr,
                    }
                    if (
                        query.returncode == 0
                        and str(target.pid) in query.stdout.split()
                    ):
                        observed_gpu = True
                        break
                    time.sleep(0.05)
                if not observed_gpu:
                    call(
                        "unobserved_gpu_cancel",
                        "POST",
                        f"/docking/autodock-gpu/jobs/{job_id}/cancel",
                        200,
                    )
                    raise SmokeFailure(
                        "Cancellation inconclusive: GPU context was not observed."
                    )
                stage = "cancel_request"
                call(stage, "POST", f"/docking/autodock-gpu/jobs/{job_id}/cancel", 200)
                deadline = time.monotonic() + 30
                while job["status"] not in TERMINAL:
                    if time.monotonic() >= deadline:
                        raise SmokeFailure(
                            "Canceled job did not reach a terminal state."
                        )
                    time.sleep(0.05)
                    job = call(
                        "cancel_poll",
                        "GET",
                        f"/docking/autodock-gpu/jobs/{job_id}",
                        200,
                    )
                stage = "cancel_result"
                if (
                    job["status"] != "canceled"
                    or job["runs"]
                    or not job["execution"]["canceled"]
                ):
                    raise SmokeFailure(
                        "Cancellation did not preserve the expected terminal state."
                    )
                try:
                    target.wait(timeout=5)
                except psutil.TimeoutExpired as error:
                    raise SmokeFailure(
                        "The canceled GPU process survived its terminal record."
                    ) from error
                deadline = time.monotonic() + 10
                while app.state.resource_arbiter.snapshot().gpu_slots_allocated:
                    if time.monotonic() >= deadline:
                        raise SmokeFailure("Canceled GPU reservation was not released.")
                    time.sleep(0.05)
                require_input(gpu_binary, GPU_SHA)
                evidence.update(
                    {
                        "status": "completed",
                        "batch_id": batch_id,
                        "job_id": job_id,
                        "device_report": report,
                        "library_sha256": digest_bytes(SYNTHETIC_LIBRARY),
                        "gpu_slots_allocated_after": 0,
                    }
                )
    except Exception as error:  # noqa: BLE001 - preserve evidence for every failure
        evidence["failure"] = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error),
        }
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if source_snapshot is not None:
            evidence["original_project_unchanged"] = (
                snapshot(PRIOR / "data") == source_snapshot
            )
            if not evidence["original_project_unchanged"]:
                evidence["status"] = "failed"
    with (output / "evidence.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product-discovery", action="store_true")
    args = parser.parse_args()
    result = run(args.output, product_discovery=args.product_discovery)
    print(f"GPU campaign/cancellation: {result['status']}")
    if "failure" in result:
        print(json.dumps(result["failure"]))
    print(
        f"Evidence SHA-256: {digest_bytes((args.output / 'evidence.json').read_bytes())}"
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
