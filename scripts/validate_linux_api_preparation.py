"""Run the predeclared isolated Linux API preparation and Vina smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from ankora_backend.adapters.engines.vina import probe_vina  # noqa: E402
from ankora_backend.api.app import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

STRUCTURE_SHA = "e1fd07976c0e1ed7aeaa2a2733e1334ad9051744bf2fc196812bdf922f08a981"
LIGAND_SHA = "e8aad0bdae1b0bb65afcb6a728823dd0d028c9988d3a34299ce9f3d09c95f92d"
VINA_SHA = "f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644"
BOX = {
    "center_x": 0.024,
    "center_y": 0.405,
    "center_z": 1.075,
    "size_x": 20.0,
    "size_y": 20.0,
    "size_z": 20.0,
}
PARAMETERS = {
    "sampling_protocol": "custom",
    "cpu_threads": 2,
    "seed": 20261029,
    "exhaustiveness": 2,
    "num_modes": 3,
    "min_rmsd_angstrom": 1.0,
    "energy_range_kcal_mol": 3.0,
    "timeout_minutes": 1,
}
RECEPTOR_PLAN = {
    "selected_chains": ["A"],
    "water_action": "remove",
    "component_decisions": [],
    "issue_decisions": [],
    "relaxation": {"enabled": False},
    "protonation": {
        "enabled": True,
        "ph": 7.4,
        "force_field": "AMBER",
        "authorized_terminal_heavy_atom_additions": [],
        "overrides": [],
    },
    "generate_pdbqt": True,
    "inspection_method": "templates_v1",
}


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def require_input(path: Path, expected: str) -> bytes:
    content = path.read_bytes()
    if digest_bytes(content) != expected:
        raise ValueError(f"Input {path.name} does not match its declared SHA-256.")
    return content


def require_output_path(output: Path, root: Path = ROOT) -> Path:
    output = output.resolve()
    allowed = (root / "logs" / "linux-api-preparation-smoke").resolve()
    if output == allowed or not output.is_relative_to(allowed):
        raise ValueError("Output must be a new directory under the isolated smoke logs root.")
    return output


class SmokeFailure(Exception):
    """An API step failed; its response is retained in the event log."""


def run(structure: Path, ligand: Path, output: Path) -> dict[str, Any]:
    output = require_output_path(output)
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "status": "failed",
        "events": events,
        "scope": (
            "Engineering smoke; not redocking, biological validation, GUI or release acceptance."
        ),
    }
    previous = {k: os.environ.get(k) for k in ("ANKORA_DATA_DIR", "ANKORA_RESOURCE_CPU_THREADS")}
    stage = "initialization"
    try:
        if sys.platform != "linux" or platform.machine() != "x86_64":
            raise SmokeFailure("This smoke requires Linux x86-64.")
        original_structure = require_input(structure, STRUCTURE_SHA)
        original_ligand = require_input(ligand, LIGAND_SHA)
        installation = probe_vina()
        if (
            installation.version != "1.2.7"
            or digest_bytes(Path(installation.executable).read_bytes()) != VINA_SHA
        ):
            raise SmokeFailure("The Vina executable does not match the declared identity.")
        evidence["vina"] = {"version": installation.version, "sha256": VINA_SHA}
        os.environ["ANKORA_DATA_DIR"] = str(output / "data")
        os.environ["ANKORA_RESOURCE_CPU_THREADS"] = "2"
        with TestClient(create_app(), headers={"Origin": "http://127.0.0.1:1420"}) as client:

            def call(
                name: str, method: str, path: str, expected: int, **kwargs: Any
            ) -> dict[str, Any]:
                response = client.request(method, "/api/v1" + path, **kwargs)
                try:
                    body = response.json()
                except ValueError:
                    body = {"text": response.text}
                request_details = {"json": kwargs.get("json"), "params": kwargs.get("params")}
                if "files" in kwargs:
                    uploaded = kwargs["files"]["file"]
                    request_details["upload"] = {
                        "filename": uploaded[0],
                        "sha256": digest_bytes(uploaded[1]),
                    }
                events.append(
                    {
                        "stage": name,
                        "method": method,
                        "path": path,
                        "request": request_details,
                        "status": response.status_code,
                        "body": body,
                    }
                )
                if response.status_code != expected or not isinstance(body, dict):
                    raise SmokeFailure(
                        f"{name} returned HTTP {response.status_code}, expected {expected}."
                    )
                return body

            stage = "tools"
            call(stage, "GET", "/tools", 200)
            stage = "structure_import"
            source = call(
                stage,
                "POST",
                "/structures/import",
                201,
                files={"file": ("test.pdb", original_structure, "chemical/x-pdb")},
            )
            structure_id = source["artifact"]["artifact_id"]
            stage = "receptor_inspection"
            inspection = call(
                stage,
                "GET",
                f"/structures/{structure_id}/receptor-inspection?inspection_method=templates_v1",
                200,
            )
            if (
                inspection["candidate_chains"] != ["A"]
                or inspection["water_count"] != 0
                or inspection["components"]
                or inspection["issues"]
            ):
                raise SmokeFailure("Inspection differs from the fixed explicit plan.")
            stage = "receptor_preparation"
            receptor = call(
                stage, "POST", f"/structures/{structure_id}/receptors", 201, json=RECEPTOR_PLAN
            )
            if receptor["status"] != "docking_ready":
                raise SmokeFailure("Receptor did not reach docking-ready status.")
            receptor_id = receptor["receptor_id"]
            stage = "ligand_import"
            ligand_record = call(
                stage,
                "POST",
                "/ligands/import",
                201,
                files={"file": ("synthetic_ethanol.smi", original_ligand, "text/plain")},
            )
            ligand_id = ligand_record["artifact"]["ligand_id"]
            stage = "ligand_conformer"
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
            stage = "ligand_pdbqt"
            ligand_pdbqt = call(
                stage,
                "POST",
                f"/ligands/{ligand_id}/conformers/{conformer_id}/pdbqt",
                201,
                json={"charge_model": "gasteiger"},
            )
            stage = "binding_site"
            site = call(
                stage,
                "POST",
                f"/receptors/{receptor_id}/binding-sites",
                201,
                json={"source": "manual", "manual_box": BOX},
            )
            if site["box"] != BOX:
                raise SmokeFailure("The stored search box differs from the declared box.")
            stage = "docking_start"
            job = call(
                stage,
                "POST",
                "/docking/vina/jobs",
                202,
                json={
                    "receptor_id": receptor_id,
                    "binding_site_id": site["binding_site_id"],
                    "ligand_id": ligand_id,
                    "ligand_preparation_id": ligand_pdbqt["artifact"]["preparation_id"],
                    "parameters": PARAMETERS,
                    "acknowledge_inputs_and_scoring": True,
                },
            )
            job_id = job["job_id"]
            deadline = time.monotonic() + 80
            stage = "docking_result"
            while job["status"] not in {"completed", "failed", "canceled"}:
                if time.monotonic() >= deadline:
                    call("docking_cancel", "POST", f"/docking/jobs/{job_id}/cancel", 200)
                    raise SmokeFailure("Docking did not reach a terminal state within 80 seconds.")
                time.sleep(0.2)
                job = call(stage, "GET", f"/docking/jobs/{job_id}", 200)
            if job["status"] != "completed" or not 1 <= len(job["poses"]) <= 3:
                raise SmokeFailure("Docking did not complete with 1–3 poses.")
            execution = job.get("execution")
            if (
                not execution
                or execution["exit_code"] != 0
                or execution["timed_out"]
                or execution["canceled"]
            ):
                raise SmokeFailure("The saved execution is missing or unsuccessful.")
            folder = output / "data" / "projects" / "default" / "results" / "docking" / job_id
            for name in ("stdout", "stderr"):
                data = (folder / (name + ".log")).read_bytes()
                if data.decode("utf-8") != execution[name]:
                    raise SmokeFailure(f"Persisted {name} differs from the execution record.")
                evidence[name + "_sha256"] = digest_bytes(data)
            raw_pose = (folder / "vina_poses.pdbqt").read_bytes()
            evidence["raw_pose_sha256"] = digest_bytes(raw_pose)
            if [p["mode"] for p in job["poses"]] != list(range(1, len(job["poses"]) + 1)):
                raise SmokeFailure("Persisted poses are not sequential.")
            for pose in job["poses"]:
                artifact = pose["artifact"]
                response = client.get("/api/v1" + artifact["content_url"])
                events.append(
                    {
                        "stage": "pose_content",
                        "path": artifact["content_url"],
                        "status": response.status_code,
                        "sha256": digest_bytes(response.content),
                    }
                )
                if (
                    response.status_code != 200
                    or digest_bytes(response.content) != artifact["sha256"]
                ):
                    raise SmokeFailure(
                        "A pose content response does not match its recorded SHA-256."
                    )
            if (
                digest_bytes(structure.read_bytes()) != STRUCTURE_SHA
                or digest_bytes(ligand.read_bytes()) != LIGAND_SHA
            ):
                raise SmokeFailure("An original input changed.")
            original = client.get(f"/api/v1/structures/{structure_id}/content")
            original_ligand_response = client.get(f"/api/v1/ligands/{ligand_id}/content")
            events.extend(
                [
                    {
                        "stage": "original_structure_content",
                        "status": original.status_code,
                        "sha256": digest_bytes(original.content),
                    },
                    {
                        "stage": "original_ligand_content",
                        "status": original_ligand_response.status_code,
                        "sha256": digest_bytes(original_ligand_response.content),
                    },
                ]
            )
            if (
                original.status_code != 200
                or original_ligand_response.status_code != 200
                or digest_bytes(original.content) != STRUCTURE_SHA
                or digest_bytes(original_ligand_response.content) != LIGAND_SHA
            ):
                raise SmokeFailure("An imported original does not match its source bytes.")
            evidence["job_id"] = job_id
            evidence["pose_count"] = len(job["poses"])
            evidence["status"] = "completed"
    except Exception as error:
        evidence["failure"] = {"stage": stage, "type": type(error).__name__, "message": str(error)}
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    with (output / "evidence.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--ligand", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.structure, args.ligand, args.output)
    except (ValueError, FileExistsError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"API smoke: {result['status']}")
    if "failure" in result:
        print(json.dumps(result["failure"]))
    print(f"Evidence SHA-256: {digest_bytes((args.output / 'evidence.json').read_bytes())}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
