"""Run the predeclared, isolated 1HSG crystallographic redocking smoke."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from ankora_backend.adapters.engines.vina import probe_vina
from ankora_backend.api.app import create_app
from fastapi.testclient import TestClient
from validate_linux_api_preparation import (
    ROOT,
    SmokeFailure,
    digest_bytes,
    require_input,
)

SOURCE_SHA = "d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268"
VINA_SHA = "f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644"
COMPONENT_ID = "ligand|B|MK1|902|"
LOCATOR = {"component_name": "MK1", "chain_id": "B", "sequence_number": 902, "insertion_code": ""}
PLAN = {
    "selected_chains": ["A", "B"],
    "water_action": "remove",
    "component_decisions": [{"component_id": COMPONENT_ID, "action": "remove"}],
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
PARAMETERS = {
    "sampling_protocol": "custom",
    "cpu_threads": 2,
    "seed": 20261029,
    "exhaustiveness": 8,
    "num_modes": 9,
    "min_rmsd_angstrom": 1.0,
    "energy_range_kcal_mol": 3.0,
    "timeout_minutes": 5,
}


def run(source_path: Path, output_path: Path) -> dict[str, Any]:
    output = output_path.resolve()
    allowed = (ROOT / "logs" / "linux-crystal-redocking-smoke").resolve()
    if output == allowed or not output.is_relative_to(allowed):
        raise ValueError("Output must be a new directory under the isolated redocking logs root.")
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "status": "failed",
        "events": events,
        "scope": "WSL engineering smoke; not general scientific or workstation acceptance.",
    }
    previous = {k: os.environ.get(k) for k in ("ANKORA_DATA_DIR", "ANKORA_RESOURCE_CPU_THREADS")}
    stage = "initialization"
    try:
        if sys.platform != "linux":
            raise SmokeFailure("This protocol requires Linux.")
        source_bytes = require_input(source_path, SOURCE_SHA)
        vina = probe_vina()
        if vina.version != "1.2.7" or digest_bytes(Path(vina.executable).read_bytes()) != VINA_SHA:
            raise SmokeFailure("Vina identity differs from the predeclared executable.")
        evidence["vina"] = {"version": vina.version, "sha256": VINA_SHA}
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
                request = {"json": kwargs.get("json"), "params": kwargs.get("params")}
                if "files" in kwargs:
                    uploaded = kwargs["files"]["file"]
                    request["upload"] = {
                        "filename": uploaded[0],
                        "sha256": digest_bytes(uploaded[1]),
                    }
                events.append(
                    {
                        "stage": name,
                        "method": method,
                        "path": path,
                        "request": request,
                        "status": response.status_code,
                        "body": body,
                    }
                )
                if response.status_code != expected or not isinstance(body, dict):
                    raise SmokeFailure(f"{name}: HTTP {response.status_code}; expected {expected}.")
                return body

            stage = "tools"
            call(stage, "GET", "/tools", 200)
            stage = "structure_import"
            source = call(
                stage,
                "POST",
                "/structures/import",
                201,
                files={"file": ("1HSG.cif", source_bytes, "chemical/x-mmcif")},
            )
            structure_id = source["artifact"]["artifact_id"]
            stage = "inspection"
            inspection = call(
                stage,
                "GET",
                f"/structures/{structure_id}/receptor-inspection?inspection_method=templates_v1",
                200,
            )
            if (
                inspection["candidate_chains"] != ["A", "B"]
                or inspection["water_count"] != 127
                or [x["component_id"] for x in inspection["components"]] != [COMPONENT_ID]
                or inspection["issues"]
            ):
                raise SmokeFailure("Inspection differs from the fixed plan.")
            stage = "crystal_extraction"
            reference = call(
                stage,
                "POST",
                f"/structures/{structure_id}/ligands/extract",
                201,
                json={"locator": LOCATOR},
            )
            ligand_id = reference["artifact"]["ligand_id"]
            reference_sha = reference["artifact"]["sha256"]
            stage = "receptor_preparation"
            receptor = call(stage, "POST", f"/structures/{structure_id}/receptors", 201, json=PLAN)
            if receptor["status"] != "docking_ready":
                raise SmokeFailure("The receptor was not docking-ready.")
            receptor_id = receptor["receptor_id"]
            stage = "conformer"
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
            ligand = call(
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
                json={
                    "source": "co_crystallized_ligand",
                    "ligand_origin": {
                        "heterogen": {
                            "chain_id": "B",
                            "residue_name": "MK1",
                            "sequence_number": 902,
                            "insertion_code": "",
                        },
                        "padding_angstrom": 5.0,
                    },
                },
            )
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
                    "ligand_preparation_id": ligand["artifact"]["preparation_id"],
                    "parameters": PARAMETERS,
                    "acknowledge_inputs_and_scoring": True,
                },
            )
            job_id = job["job_id"]
            stage = "docking_result"
            deadline = time.monotonic() + 320
            while job["status"] not in {"completed", "failed", "canceled"}:
                if time.monotonic() >= deadline:
                    call("docking_cancel", "POST", f"/docking/jobs/{job_id}/cancel", 200)
                    raise SmokeFailure("Docking exceeded the bounded wait.")
                time.sleep(0.5)
                job = call(stage, "GET", f"/docking/jobs/{job_id}", 200)
            if job["status"] != "completed" or not 1 <= len(job["poses"]) <= 9:
                raise SmokeFailure("Docking failed or returned no valid pose list.")
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
                    raise SmokeFailure("Persisted pose content hash mismatch.")
            stage = "redocking"
            result = call(
                stage,
                "POST",
                "/validation/redocking",
                201,
                json={
                    "source_kind": "vina_job",
                    "source_id": job_id,
                    "reference_ligand_id": ligand_id,
                    "threshold_angstrom": 2.0,
                },
            )
            if (
                result["source_id"] != job_id
                or result["reference_ligand_id"] != ligand_id
                or result["reference_sha256"] != reference_sha
            ):
                raise SmokeFailure(
                    "Validation record did not identify the original job and reference."
                )
            stage = "original_integrity"
            original = client.get(f"/api/v1/structures/{structure_id}/content")
            ref = client.get(f"/api/v1/ligands/{ligand_id}/content")
            if (
                digest_bytes(source_path.read_bytes()) != SOURCE_SHA
                or original.status_code != 200
                or digest_bytes(original.content) != SOURCE_SHA
                or ref.status_code != 200
                or digest_bytes(ref.content) != reference_sha
            ):
                raise SmokeFailure("Source or reference changed.")
            evidence.update(
                {
                    "status": "completed",
                    "job_id": job_id,
                    "validation_id": result["validation_id"],
                    "pose_count": len(job["poses"]),
                    "reference_sha256": reference_sha,
                    "metrics": result["metrics"],
                }
            )
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.structure, args.output)
    except (ValueError, FileExistsError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"Redocking smoke: {result['status']}")
    if "failure" in result:
        print(json.dumps(result["failure"]))
    print(f"Evidence SHA-256: {digest_bytes((args.output / 'evidence.json').read_bytes())}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
