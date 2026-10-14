"""Bounded Windows receptor-preparation diagnostics, never docking or a user project.

The supplied plan declares scientific choices before execution. Each invocation
uses a new output directory, preserves source bytes and tool failures, and never
retries with altered chemistry to obtain success. Public RCSB fetching is opt-in.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

import gemmi  # noqa: E402

from ankora_backend.domain.errors import AnkoraDomainError  # noqa: E402
from ankora_backend.persistence.artifact_store import StructureArtifactStore  # noqa: E402
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore  # noqa: E402
from ankora_backend.schemas.receptors import ReceptorPreparationRequest  # noqa: E402
from ankora_backend.schemas.structures import StructureSource  # noqa: E402
from ankora_backend.services.receptor_inspection import inspect_receptor  # noqa: E402
from ankora_backend.services.receptor_preparation import prepare_receptor  # noqa: E402
from ankora_backend.services.structure_inspection import (  # noqa: E402
    fetch_rcsb_mmcif,
    import_structure_bytes,
)


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def _run_case(
    case: dict[str, Any], output: Path, plan: dict[str, Any]
) -> dict[str, Any]:
    root = output / case["case_id"]
    root.mkdir()
    result: dict[str, Any] = {"case_id": case["case_id"], "pdb_id": case["pdb_id"]}
    source_path: Path | None = None
    source_sha: str | None = None
    try:
        content, source_uri = asyncio.run(fetch_rcsb_mmcif(case["pdb_id"]))
        structures = StructureArtifactStore(root)
        imported = import_structure_bytes(
            content=content,
            filename=f"{case['pdb_id']}.cif",
            source=StructureSource.RCSB,
            source_uri=source_uri,
            store=structures,
        )
        source_path = structures.content_path(imported.artifact.artifact_id)
        source_sha = imported.artifact.sha256
        result.update(source_sha256=source_sha, source_uri=source_uri)
        if case.get("source_sha256") and case["source_sha256"] != source_sha:
            raise ValueError("Public source differs from the declared source hash")
        report = inspect_receptor(
            artifact_id=imported.artifact.artifact_id, store=structures
        )
        _write(root / "inspection.json", report.model_dump(mode="json"))
        chains = case["selected_chains"]
        components = [
            component for component in report.components if component.chain_id in chains
        ]
        component_decisions = [
            {"component_id": c.component_id, "action": case["component_action"]}
            for c in components
        ]
        issues = [
            issue
            for issue in report.issues
            if issue.residue.chain_id in chains
            and not any(
                case["component_action"] == "remove"
                and (c.chain_id, c.name, c.sequence_number, c.insertion_code)
                == (
                    issue.residue.chain_id,
                    issue.residue.residue_name,
                    issue.residue.sequence_number,
                    issue.residue.insertion_code,
                )
                for c in components
            )
        ]
        _write(
            root / "pre-run-system.json",
            {"selected_chains": chains, "component_decisions": component_decisions},
        )
        decisions = []
        for issue in issues:
            kind = issue.kind.value
            if kind == "missing_atoms" and "repair" in [
                action.value for action in issue.allowed_actions
            ]:
                decisions.append({"issue_id": issue.issue_id, "action": "repair"})
            elif kind == "missing_residue":
                decisions.append({"issue_id": issue.issue_id, "action": "leave"})
            elif kind == "alternate_location" and "A" in issue.alternate_locations:
                decisions.append(
                    {
                        "issue_id": issue.issue_id,
                        "action": "repair",
                        "selected_altloc": "A",
                    }
                )
            else:
                result.update(
                    status="needs_decision", issue=issue.model_dump(mode="json")
                )
                return result
        terminal_additions = []
        model = gemmi.make_structure_from_block(
            gemmi.cif.read_string(content.decode()).sole_block()
        )[0]
        if case["terminal_policy"] != "exact_missing_final_OXT":
            raise ValueError("Unknown declared terminal-completion policy")
        for chain in model:
            if chain.name not in chains:
                continue
            polymer = [residue for residue in chain if residue.het_flag == "A"]
            if polymer and "OXT" not in {atom.name for atom in polymer[-1]}:
                last = polymer[-1]
                terminal_additions.append(
                    {
                        "chain_id": chain.name,
                        "residue_name": last.name,
                        "sequence_number": last.seqid.num,
                        "insertion_code": last.seqid.icode.strip(),
                        "atom_name": "OXT",
                    }
                )
        request = ReceptorPreparationRequest.model_validate(
            {
                "selected_chains": chains,
                "water_action": plan["water_action"],
                "component_decisions": component_decisions,
                "issue_decisions": decisions,
                "repair_method": plan["repair_method"],
                "repair_seed": plan["repair_seed"],
                "protonation": {
                    "enabled": True,
                    "ph": case["ph"],
                    "force_field": plan["force_field"],
                    "authorized_terminal_heavy_atom_additions": terminal_additions,
                },
                "generate_pdbqt": True,
            }
        )
        _write(root / "pre-run-request.json", request.model_dump(mode="json"))
        result["request"] = request.model_dump(mode="json")
        record = prepare_receptor(
            source_artifact_id=imported.artifact.artifact_id,
            request=request,
            structure_store=structures,
            receptor_store=ReceptorArtifactStore(root),
        )
        result.update(
            status=record.status.value,
            receptor_id=record.receptor_id,
            outputs=[item.model_dump(mode="json") for item in record.outputs],
        )
    except AnkoraDomainError as error:
        result.update(
            status="failed",
            code=error.code,
            stage=error.stage,
            message=error.message,
            details=error.details,
        )
    except Exception as error:
        result.update(
            status="harness_failed", diagnostic=f"{type(error).__name__}: {error}"
        )
    finally:
        if source_path is not None:
            result["source_unchanged"] = (
                hashlib.sha256(source_path.read_bytes()).hexdigest() == source_sha
            )
        _write(root / "outcome.json", result)
    return result


def _validate_plan(plan: dict[str, Any]) -> None:
    # Reject unsupported recipes instead of silently ignoring manifest fields.
    global_fields = {
        "schema_version",
        "purpose",
        "repair_method",
        "repair_seed",
        "platform",
        "missing_atoms",
        "missing_residues",
        "alternate_location",
        "nonstandard",
        "water_action",
        "force_field",
        "cases",
    }
    case_fields = {
        "case_id",
        "pdb_id",
        "source_sha256",
        "selected_chains",
        "ph",
        "component_action",
        "terminal_policy",
    }
    if set(plan) - global_fields or any(
        set(case) - case_fields for case in plan["cases"]
    ):
        raise ValueError("Unknown declared policy field")
    supported = {
        "schema_version": 1,
        "repair_method": "topology_guard_v3",
        "platform": "Reference",
        "missing_residues": "leave_unmodelled",
        "alternate_location": "A_if_reported_otherwise_needs_decision",
        "nonstandard": "needs_decision",
        "force_field": "AMBER",
    }
    if any(plan.get(key) != value for key, value in supported.items()):
        raise ValueError("Unsupported declared preparation policy")
    if plan.get("missing_atoms") not in {
        "repair",
        "repair_if_supported_otherwise_needs_decision",
    }:
        raise ValueError("Unsupported declared missing-atom policy")
    if plan.get("water_action") not in {"keep", "remove"}:
        raise ValueError("Declare a water policy")
    if (
        type(plan.get("repair_seed")) is not int
        or not 1 <= plan["repair_seed"] <= 2147483647
    ):
        raise ValueError("Invalid repair seed")
    for case in plan["cases"]:
        if case.get("component_action") not in {"keep", "remove"}:
            raise ValueError("Declare a component policy")
        if not case.get("selected_chains") or len(case["selected_chains"]) != len(
            set(case["selected_chains"])
        ):
            raise ValueError("Declare unique selected chains")
        if not isinstance(case.get("ph"), (int, float)) or not 0 <= case["ph"] <= 14:
            raise ValueError("Invalid target pH")
        if case.get("terminal_policy") != "exact_missing_final_OXT":
            raise ValueError("Unsupported terminal policy")
        if case.get("source_sha256") and not re.fullmatch(
            r"[a-f0-9]{64}", case["source_sha256"]
        ):
            raise ValueError("Invalid source hash")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fetch-public-rcsb", action="store_true")
    args = parser.parse_args()
    if not args.fetch_public_rcsb:
        parser.error("Confirm public-source fetching with --fetch-public-rcsb")
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    _validate_plan(plan)
    cases = plan["cases"]
    if not cases or len(cases) > 8:
        parser.error("A diagnostic invocation needs 1–8 declared cases")
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)) or any(
        not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in ids
    ):
        parser.error("Case IDs must be unique safe directory names")
    if any(not re.fullmatch(r"[A-Za-z0-9]{4}", case["pdb_id"]) for case in cases):
        parser.error("Each public PDB ID must have four alphanumeric characters")
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    workers = min(3, len(cases), max(1, (os.cpu_count() or 1) - 1))
    _write(
        output / "pre-run-plan.json",
        {
            "plan": plan,
            "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "started_at": datetime.now(UTC).isoformat(),
            "workers": workers,
            "versions": {
                name: version(name)
                for name in (
                    "pdbfixer",
                    "openmm",
                    "pdb2pqr",
                    "propka",
                    "meeko",
                    "rdkit",
                    "gemmi",
                )
            },
        },
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(lambda case: _run_case(case, output, plan), cases))
    _write(output / "outcomes.json", outcomes)
    for result in outcomes:
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in ("case_id", "status", "code")
                    if key in result
                }
            )
        )
    return int(
        any(
            result["status"] == "harness_failed"
            or result.get("source_unchanged") is False
            for result in outcomes
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
