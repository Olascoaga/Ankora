"""Create and verify the six accepted benchmark receptor/PDBQT derivatives."""

from __future__ import annotations

import hashlib
import json
import os
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    preflight_autodock4_receptor_atom_types,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.receptors import (
    ProtonationOverride,
    ReceptorOutputStage,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ReceptorProtonationProposal,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.receptor_preparation import prepare_receptor
from ankora_backend.services.structure_inspection import import_structure_bytes
from ankora_backend.validation.screening_benchmark_protonation_decisions import (
    verify_protonation_decision_review,
)
from ankora_backend.validation.screening_benchmark_protonation_previews import (
    verify_protonation_preview_manifest,
)
from ankora_backend.validation.screening_benchmark_receptor_plans import (
    verify_receptor_plan_manifest,
)

SCHEMA_VERSION = 1


class ScreeningBenchmarkFinalReceptorError(ValueError):
    """Final benchmark receptor evidence is incomplete, changed, or unsafe."""


FinalReceptorTaskExecutor = Callable[[dict[str, Any], Path, Path], dict[str, Any]]


def run_screening_benchmark_final_receptors(
    *,
    archive: Path,
    structure_manifest_path: Path,
    receptor_plan_manifest_path: Path,
    protonation_preview_manifest_path: Path,
    tautomer_manifest_path: Path,
    protonation_decision_review_path: Path,
    structures_dir: Path,
    output_root: Path,
    public_manifest_path: Path,
    worker_limit: int | None = None,
    _task_executor: FinalReceptorTaskExecutor | None = None,
) -> dict[str, Any]:
    """Rerun all six frozen plans with only the accepted protonation choices."""

    plans = verify_receptor_plan_manifest(
        archive=archive,
        structure_manifest_path=structure_manifest_path,
        structures_dir=structures_dir,
        receptor_plan_manifest_path=receptor_plan_manifest_path,
    )
    previews = verify_protonation_preview_manifest(protonation_preview_manifest_path)
    review = verify_protonation_decision_review(
        protonation_decision_review_path,
        preview_manifest_path=protonation_preview_manifest_path,
        tautomer_manifest_path=tautomer_manifest_path,
        require_scientist_confirmation=True,
    )
    if previews.get("source_receptor_plan_manifest_sha256") != plans.get("manifest_sha256"):
        raise ScreeningBenchmarkFinalReceptorError(
            "The accepted protonation review is not linked to these receptor plans."
        )
    if output_root.exists() or public_manifest_path.exists():
        raise ScreeningBenchmarkFinalReceptorError(
            "Final benchmark receptor evidence is create-only."
        )
    output_root.mkdir(parents=True)

    tasks = _final_receptor_tasks(plans, previews, review)
    worker_count = _parallel_worker_count(len(tasks), worker_limit)
    executor = _task_executor or _execute_final_receptor_task
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ankora-final-receptor",
    ) as pool:
        futures = {pool.submit(executor, task, structures_dir, output_root): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = _failed_task_result(task, output_root, error)
            results.append(result)

    results.sort(key=lambda item: int(item["sequence"]))
    failed = [item for item in results if item["status"] != "completed"]
    decision_census = _required_object(review.get("decision_census"), "decision census")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": _required_string(plans, "protocol_id"),
        "created_at": datetime.now(UTC).isoformat(),
        "scores_seen": False,
        "source_receptor_plan_manifest_sha256": _required_sha256(plans, "manifest_sha256"),
        "source_protonation_preview_manifest_sha256": _required_sha256(previews, "manifest_sha256"),
        "source_protonation_decision_review_sha256": _required_sha256(review, "review_sha256"),
        "execution_policy": {
            "scope": "create-only final receptor and receptor-PDBQT production",
            "worker_count": worker_count,
            "accepted_decisions_only": True,
            "ligand_preparation_executed": False,
            "docking_executed": False,
            "scores_or_metrics_computed": False,
            "raw_evidence_retained_locally": True,
        },
        "decision_census": decision_census,
        "receptor_census": {
            "requested": len(tasks),
            "completed": len(tasks) - len(failed),
            "failed": len(failed),
            "docking_ready": sum(
                item.get("final_status") == ReceptorPreparationStatus.DOCKING_READY.value
                for item in results
            ),
            "pdbqt_created": sum(item.get("final_pdbqt_created") is True for item in results),
        },
        "receptors": results,
        "result_status": (
            "final_receptor_production_failed_partial_evidence_retained"
            if failed
            else "six_final_receptors_and_pdbqt_created_no_docking_executed"
        ),
    }
    manifest["manifest_sha256"] = _digest(manifest)
    _write_create_only(output_root / "manifest.json", _serialized(manifest))
    if failed:
        raise ScreeningBenchmarkFinalReceptorError(
            f"{len(failed)} of {len(tasks)} final receptors failed; "
            f"partial evidence is retained at {output_root}."
        )
    _write_create_only(public_manifest_path, _serialized(manifest))
    return manifest


def verify_final_receptor_manifest(
    path: Path,
    *,
    evidence_root: Path | None = None,
    expected_decision_review_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the path-free summary and, when supplied, every retained file."""

    manifest = _load_object(path, "final receptor manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkFinalReceptorError("Unsupported final receptor manifest schema.")
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkFinalReceptorError(
            "The final receptor manifest differs from its SHA-256."
        )
    if manifest.get("scores_seen") is not False:
        raise ScreeningBenchmarkFinalReceptorError(
            "Final receptor production must remain pre-result evidence."
        )
    if (
        expected_decision_review_sha256 is not None
        and manifest.get("source_protonation_decision_review_sha256")
        != expected_decision_review_sha256
    ):
        raise ScreeningBenchmarkFinalReceptorError(
            "The final receptors name a different accepted decision review."
        )
    policy = _required_object(manifest.get("execution_policy"), "execution policy")
    if (
        policy.get("accepted_decisions_only") is not True
        or policy.get("ligand_preparation_executed") is not False
        or policy.get("docking_executed") is not False
        or policy.get("scores_or_metrics_computed") is not False
    ):
        raise ScreeningBenchmarkFinalReceptorError(
            "The final receptor execution boundary is incomplete or changed."
        )
    census = _required_object(manifest.get("receptor_census"), "receptor census")
    if (
        census.get("requested"),
        census.get("completed"),
        census.get("failed"),
        census.get("docking_ready"),
        census.get("pdbqt_created"),
    ) != (6, 6, 0, 6, 6):
        raise ScreeningBenchmarkFinalReceptorError(
            "The final receptor manifest does not contain six docking-ready receptors."
        )
    decisions = _required_object(manifest.get("decision_census"), "decision census")
    source_proposals = _required_int(decisions, "source_proposals")
    default_count = _required_int(decisions, "accepted_by_default_policy")
    override_count = _required_int(decisions, "explicit_overrides")
    if default_count + override_count != source_proposals:
        raise ScreeningBenchmarkFinalReceptorError(
            "The accepted decision census does not cover every source proposal."
        )

    receptors = _required_list(manifest, "receptors")
    if len(receptors) != 6:
        raise ScreeningBenchmarkFinalReceptorError(
            "The final receptor manifest must retain exactly six templates."
        )
    identities: set[tuple[str, str, str]] = set()
    observed_decisions = 0
    observed_overrides = 0
    for raw in receptors:
        receptor = _required_object(raw, "final receptor")
        identity = (
            _required_string(receptor, "target_id"),
            _required_string(receptor, "role"),
            _required_string(receptor, "pdb_id"),
        )
        if identity in identities:
            raise ScreeningBenchmarkFinalReceptorError(
                "The final receptor manifest repeats a template."
            )
        identities.add(identity)
        if (
            receptor.get("status") != "completed"
            or receptor.get("final_status") != ReceptorPreparationStatus.DOCKING_READY.value
            or receptor.get("final_receptor_created") is not True
            or receptor.get("final_pdbqt_created") is not True
        ):
            raise ScreeningBenchmarkFinalReceptorError(
                "A final receptor is not complete and docking-ready."
            )
        _verify_manifest_paths(receptor)
        proposal_count = _required_int(receptor, "proposal_count")
        explicit_count = _required_int(receptor, "explicit_override_count")
        observed_decisions += proposal_count
        observed_overrides += explicit_count
        atom_types = _required_string_list(receptor, "receptor_atom_types")
        if not atom_types:
            raise ScreeningBenchmarkFinalReceptorError(
                "A final receptor PDBQT has no recorded AutoDock atom types."
            )
        output_stages = {
            _required_string(_required_object(item, "output"), "stage")
            for item in _required_list(receptor, "outputs")
        }
        required_stages = {
            ReceptorOutputStage.SELECTED.value,
            ReceptorOutputStage.PROTONATED_PDB.value,
            ReceptorOutputStage.PROTONATED_PQR.value,
            ReceptorOutputStage.MEEKO_INPUT_PQR.value,
            ReceptorOutputStage.PDBQT.value,
        }
        if not required_stages.issubset(output_stages):
            raise ScreeningBenchmarkFinalReceptorError(
                "A final receptor is missing a required preparation output."
            )
        if evidence_root is not None:
            _verify_local_files(receptor, evidence_root.resolve())
            _verify_local_pdbqt(receptor, evidence_root.resolve())
    if observed_decisions != source_proposals or observed_overrides != override_count:
        raise ScreeningBenchmarkFinalReceptorError(
            "The per-template final decisions do not match the accepted census."
        )
    return manifest


def _final_receptor_tasks(
    plans: dict[str, Any], previews: dict[str, Any], review: dict[str, Any]
) -> list[dict[str, Any]]:
    preview_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in _required_list(previews, "previews"):
        preview = _required_object(raw, "preview")
        identity = (
            _required_string(preview, "target_id"),
            _required_string(preview, "role"),
            _required_string(preview, "pdb_id"),
        )
        preview_index[identity] = preview

    override_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in _required_list(review, "proposed_overrides"):
        override = _required_object(raw, "accepted override")
        key = (
            _required_string(override, "target_id"),
            _required_string(override, "role"),
            _required_string(override, "pdb_id"),
            _required_string(override, "proposal_id"),
        )
        override_index[key] = override

    tasks: list[dict[str, Any]] = []
    consumed_overrides: set[tuple[str, str, str, str]] = set()
    for raw_target in _required_list(plans, "targets"):
        target = _required_object(raw_target, "target")
        target_id = _required_string(target, "target_id")
        for template_key in ("primary_template", "alternate_template"):
            template = _required_object(target.get(template_key), template_key)
            role = _required_string(template, "role")
            pdb_id = _required_string(template, "pdb_id")
            preview_item = preview_index.get((target_id, role, pdb_id))
            if preview_item is None:
                raise ScreeningBenchmarkFinalReceptorError(
                    f"No frozen protonation preview exists for {target_id}/{role}/{pdb_id}."
                )
            decisions: list[dict[str, Any]] = []
            overrides: list[dict[str, Any]] = []
            for raw_proposal in _required_list(preview_item, "proposals"):
                proposal = _required_object(raw_proposal, "proposal")
                proposal_id = _required_string(proposal, "proposal_id")
                override_key = (target_id, role, pdb_id, proposal_id)
                accepted_override = override_index.get(override_key)
                selected_state = _required_string(proposal, "default_state")
                decision_source = "propka_prediction"
                if accepted_override is not None:
                    selected_state = _required_string(accepted_override, "selected_state")
                    overrides.append(
                        {
                            "residue": _required_object(
                                accepted_override.get("residue"), "override residue"
                            ),
                            "state": selected_state,
                        }
                    )
                    consumed_overrides.add(override_key)
                    decision_source = "scientist_override"
                decisions.append(
                    {
                        "proposal_id": proposal_id,
                        "residue": _required_object(proposal.get("residue"), "proposal residue"),
                        "source_default_state": _required_string(proposal, "default_state"),
                        "selected_state": selected_state,
                        "decision_source": decision_source,
                    }
                )
            tasks.append(
                {
                    "sequence": len(tasks) + 1,
                    "target_id": target_id,
                    "role": role,
                    "pdb_id": pdb_id,
                    "template": template,
                    "accepted_decisions": decisions,
                    "overrides": overrides,
                    "source_preview_manifest_sha256": previews["manifest_sha256"],
                    "decision_review_sha256": review["review_sha256"],
                }
            )
    if len(tasks) != 6:
        raise ScreeningBenchmarkFinalReceptorError(
            "The receptor-plan manifest must define exactly six final receptors."
        )
    if consumed_overrides != set(override_index):
        raise ScreeningBenchmarkFinalReceptorError(
            "An accepted override does not belong to one of the six final templates."
        )
    return tasks


def _execute_final_receptor_task(
    task: dict[str, Any], structures_dir: Path, output_root: Path
) -> dict[str, Any]:
    sequence = int(task["sequence"])
    pdb_id = str(task["pdb_id"])
    task_root = output_root / (f"{sequence:02d}-{task['target_id']}-{task['role']}-{pdb_id}")
    task_root.mkdir()
    template = _required_object(task.get("template"), "template")
    identity = _required_object(template.get("official_structure"), "official structure")
    source_path = structures_dir / _required_string(identity, "filename")
    content = source_path.read_bytes()
    if len(content) != _required_int(identity, "size_bytes"):
        raise ScreeningBenchmarkFinalReceptorError(
            f"Official structure {pdb_id} size changed before final preparation."
        )
    if hashlib.sha256(content).hexdigest() != _required_sha256(identity, "sha256"):
        raise ScreeningBenchmarkFinalReceptorError(
            f"Official structure {pdb_id} SHA-256 changed before final preparation."
        )
    _write_create_only(task_root / f"{pdb_id}.cif", content)

    data_root = task_root / "ankora-data"
    project_id = "benchmark-final"
    structure_store = StructureArtifactStore(data_root, project_id=project_id)
    receptor_store = ReceptorArtifactStore(data_root, project_id=project_id)
    source = import_structure_bytes(
        content=content,
        filename=f"{pdb_id}.cif",
        source=StructureSource.RCSB,
        source_uri=f"https://files.rcsb.org/download/{pdb_id.upper()}.cif",
        store=structure_store,
    )
    frozen = ReceptorPreparationRequest.model_validate(
        _required_object(template.get("preparation_request"), "preparation request")
    )
    if frozen.protonation.overrides:
        raise ScreeningBenchmarkFinalReceptorError(
            "The frozen structural plan already contains protonation overrides."
        )
    overrides = [ProtonationOverride.model_validate(item) for item in task["overrides"]]
    protonation = frozen.protonation.model_copy(update={"overrides": overrides})
    request = frozen.model_copy(update={"protonation": protonation, "generate_pdbqt": True})
    record = prepare_receptor(
        source_artifact_id=source.artifact.artifact_id,
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
    )
    if record.status is not ReceptorPreparationStatus.DOCKING_READY:
        raise ScreeningBenchmarkFinalReceptorError(
            f"Final receptor {pdb_id} did not reach docking_ready."
        )
    if record.protonation_analysis is None:
        raise ScreeningBenchmarkFinalReceptorError(
            f"Final receptor {pdb_id} has no structured protonation analysis."
        )
    _verify_recorded_decisions(task["accepted_decisions"], record.protonation_analysis.proposals)

    receptor_root = (
        data_root / "projects" / project_id / "derived" / "receptors" / record.receptor_id
    )
    record_path = receptor_root / "record.json"
    output_summaries: list[dict[str, Any]] = []
    for output in record.outputs:
        output_path = receptor_root / output.filename
        if not output_path.is_file():
            raise ScreeningBenchmarkFinalReceptorError(
                f"Recorded final output is missing: {output.filename}."
            )
        if (
            output_path.stat().st_size != output.size_bytes
            or _file_sha256(output_path) != output.sha256
        ):
            raise ScreeningBenchmarkFinalReceptorError(
                f"Recorded final output changed: {output.filename}."
            )
        output_summaries.append(
            {
                "stage": output.stage.value,
                "filename": output.filename,
                "path": output_path.relative_to(output_root).as_posix(),
                "size_bytes": output.size_bytes,
                "sha256": output.sha256,
            }
        )
    pdbqt = next(
        (item for item in record.outputs if item.stage is ReceptorOutputStage.PDBQT),
        None,
    )
    if pdbqt is None:
        raise ScreeningBenchmarkFinalReceptorError(
            f"Final receptor {pdb_id} produced no PDBQT output."
        )
    pdbqt_path = receptor_root / pdbqt.filename
    atom_types = collect_autodock_atom_types([pdbqt_path.read_text(encoding="utf-8")])
    preflight_autodock4_receptor_atom_types(atom_types)
    files = _file_evidence(task_root, output_root)
    return {
        "sequence": sequence,
        "target_id": task["target_id"],
        "role": task["role"],
        "pdb_id": pdb_id,
        "status": "completed",
        "official_structure_sha256": hashlib.sha256(content).hexdigest(),
        "accepted_decisions_sha256": hashlib.sha256(
            _canonical_json({"decisions": task["accepted_decisions"]})
        ).hexdigest(),
        "request_sha256": hashlib.sha256(
            _canonical_json(request.model_dump(mode="json"))
        ).hexdigest(),
        "source_artifact_id": source.artifact.artifact_id,
        "final_receptor_id": record.receptor_id,
        "final_record_path": record_path.relative_to(output_root).as_posix(),
        "final_record_sha256": _file_sha256(record_path),
        "final_status": record.status.value,
        "proposal_count": len(task["accepted_decisions"]),
        "explicit_override_count": len(overrides),
        "accepted_overrides": [item.model_dump(mode="json") for item in overrides],
        "receptor_atom_types": list(atom_types),
        "outputs": output_summaries,
        "raw_evidence_files": files,
        "final_receptor_created": True,
        "final_pdbqt_created": True,
        "docking_executed": False,
    }


def _verify_recorded_decisions(
    expected: list[dict[str, Any]], actual: list[ReceptorProtonationProposal]
) -> None:
    expected_index = {_required_string(item, "proposal_id"): item for item in expected}
    actual_index = {item.proposal_id: item for item in actual}
    if len(expected_index) != len(expected) or len(actual_index) != len(actual):
        raise ScreeningBenchmarkFinalReceptorError(
            "The final protonation analysis repeats a proposal."
        )
    if set(actual_index) != set(expected_index):
        raise ScreeningBenchmarkFinalReceptorError(
            "The final protonation proposal set differs from the accepted review."
        )
    for proposal_id, accepted in expected_index.items():
        proposal = actual_index[proposal_id]
        expected_residue = _required_object(accepted.get("residue"), "accepted residue")
        if proposal.residue.model_dump(mode="json") != expected_residue:
            raise ScreeningBenchmarkFinalReceptorError(
                f"Final proposal {proposal_id} names a different residue."
            )
        selected_state = _required_string(accepted, "selected_state")
        if (
            proposal.default_state != _required_string(accepted, "source_default_state")
            or proposal.selected_state != selected_state
            or proposal.decision_source.value != _required_string(accepted, "decision_source")
        ):
            raise ScreeningBenchmarkFinalReceptorError(
                f"Final proposal {proposal_id} does not reproduce the accepted state."
            )
        # The structured worker report records a written ``output_state`` only
        # for histidines, whose neutral tautomer cannot be recovered reliably
        # from the generic residue name.  Other accepted states (including
        # termini, carboxylates, and CYM) therefore legitimately retain
        # ``None`` here.  Exact HID/HIE/HIP overrides are different: the
        # production adapter inspects the written PDB and PQR hydrogens and we
        # require that independent observation to agree with the selection.
        if selected_state in {"HID", "HIE", "HIP"} and proposal.output_state != selected_state:
            raise ScreeningBenchmarkFinalReceptorError(
                f"Final proposal {proposal_id} does not reproduce the written histidine state."
            )


def _failed_task_result(
    task: dict[str, Any], output_root: Path, error: Exception
) -> dict[str, Any]:
    task_root = output_root / (
        f"{int(task['sequence']):02d}-{task['target_id']}-{task['role']}-{task['pdb_id']}"
    )
    task_root.mkdir(exist_ok=True)
    failure: dict[str, Any] = {
        "error_type": type(error).__name__,
        "message": str(error),
        "traceback": traceback.format_exc(),
    }
    if isinstance(error, AnkoraDomainError):
        failure.update(
            {
                "code": error.code,
                "stage": error.stage,
                "recoverable": error.recoverable,
                "details": error.details,
            }
        )
    _write_create_only(task_root / "final-receptor-failure.json", _serialized(failure))
    return {
        "sequence": task["sequence"],
        "target_id": task["target_id"],
        "role": task["role"],
        "pdb_id": task["pdb_id"],
        "status": "failed",
        "error_type": type(error).__name__,
        "error_code": error.code if isinstance(error, AnkoraDomainError) else None,
        "error_stage": error.stage if isinstance(error, AnkoraDomainError) else None,
        "message": str(error),
        "raw_evidence_files": _file_evidence(task_root, output_root),
        "final_receptor_created": False,
        "final_pdbqt_created": False,
        "docking_executed": False,
    }


def _verify_local_files(receptor: dict[str, Any], evidence_root: Path) -> None:
    for raw in _required_list(receptor, "raw_evidence_files"):
        item = _required_object(raw, "raw evidence file")
        path = _safe_evidence_path(evidence_root, _required_string(item, "path"))
        if path.stat().st_size != _required_int(item, "size_bytes"):
            raise ScreeningBenchmarkFinalReceptorError(
                f"Final receptor evidence size changed: {path.name}."
            )
        if _file_sha256(path) != _required_sha256(item, "sha256"):
            raise ScreeningBenchmarkFinalReceptorError(
                f"Final receptor evidence SHA-256 changed: {path.name}."
            )


def _verify_manifest_paths(receptor: dict[str, Any]) -> None:
    _relative_manifest_path(_required_string(receptor, "final_record_path"))
    for raw in _required_list(receptor, "outputs"):
        output = _required_object(raw, "output")
        filename = _required_string(output, "filename")
        if Path(filename).name != filename:
            raise ScreeningBenchmarkFinalReceptorError(
                "A final receptor output filename contains a path."
            )
        _relative_manifest_path(_required_string(output, "path"))
    for raw in _required_list(receptor, "raw_evidence_files"):
        evidence = _required_object(raw, "raw evidence file")
        _relative_manifest_path(_required_string(evidence, "path"))


def _relative_manifest_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ScreeningBenchmarkFinalReceptorError(
            "Final receptor evidence contains an unsafe path."
        )
    return path


def _verify_local_pdbqt(receptor: dict[str, Any], evidence_root: Path) -> None:
    pdbqt = next(
        (
            _required_object(raw, "output")
            for raw in _required_list(receptor, "outputs")
            if _required_object(raw, "output").get("stage") == ReceptorOutputStage.PDBQT.value
        ),
        None,
    )
    if pdbqt is None:
        raise ScreeningBenchmarkFinalReceptorError("A final receptor has no PDBQT output summary.")
    path = _safe_evidence_path(evidence_root, _required_string(pdbqt, "path"))
    atom_types = collect_autodock_atom_types([path.read_text(encoding="utf-8")])
    preflight_autodock4_receptor_atom_types(atom_types)
    if list(atom_types) != _required_string_list(receptor, "receptor_atom_types"):
        raise ScreeningBenchmarkFinalReceptorError(
            "The final receptor AutoDock atom-type census changed."
        )


def _safe_evidence_path(root: Path, relative_value: str) -> Path:
    relative = _relative_manifest_path(relative_value)
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise ScreeningBenchmarkFinalReceptorError(
            f"Final receptor evidence is unavailable: {relative.as_posix()}."
        )
    return path


def _file_evidence(task_root: Path, output_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(output_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for path in sorted(task_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    ]


def _parallel_worker_count(task_count: int, worker_limit: int | None) -> int:
    available = max(1, (os.cpu_count() or 2) - 1)
    if worker_limit is not None:
        if worker_limit < 1:
            raise ScreeningBenchmarkFinalReceptorError(
                "The final receptor worker limit must be at least one."
            )
        available = min(available, worker_limit)
    return max(1, min(task_count, available))


def _write_create_only(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as destination:
        destination.write(content)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkFinalReceptorError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkFinalReceptorError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkFinalReceptorError(f"{key} must be a list.")
    return raw


def _required_string_list(value: dict[str, Any], key: str) -> list[str]:
    raw = _required_list(value, key)
    if any(not isinstance(item, str) or not item for item in raw):
        raise ScreeningBenchmarkFinalReceptorError(f"{key} must contain non-empty strings.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkFinalReceptorError(f"{key} must be a non-empty string.")
    return raw


def _required_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkFinalReceptorError(f"{key} must be a non-negative integer.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkFinalReceptorError(f"{key} must be a SHA-256.")
    return raw


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
