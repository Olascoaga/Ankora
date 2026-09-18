"""Execute and freeze review-only PROPKA previews for benchmark receptors.

Preview outputs are retained as local validation evidence, but they are never
promoted to the final receptor lineage.  Final receptor creation must rerun the
reviewed plan after the scientist has frozen any explicit overrides.
"""

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

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.receptors import (
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.receptor_preparation import prepare_receptor
from ankora_backend.services.structure_inspection import import_structure_bytes
from ankora_backend.validation.screening_benchmark_receptor_plans import (
    verify_receptor_plan_manifest,
)

SCHEMA_VERSION = 1
_REVIEW_WARNINGS = {
    "ACTIVE_SITE_REVIEW",
    "COUPLED_TITRATION_GROUP",
    "METAL_COORDINATION_REVIEW",
    "PKA_NEAR_TARGET_PH",
    "STATE_UNSUPPORTED_BY_FORCE_FIELD",
}


class ScreeningBenchmarkProtonationPreviewError(ValueError):
    """The benchmark protonation-preview evidence is incomplete or changed."""


PreviewTaskExecutor = Callable[[dict[str, Any], Path, Path], dict[str, Any]]


def run_screening_benchmark_protonation_previews(
    *,
    archive: Path,
    structure_manifest_path: Path,
    receptor_plan_manifest_path: Path,
    structures_dir: Path,
    output_root: Path,
    public_manifest_path: Path,
    worker_limit: int | None = None,
    _task_executor: PreviewTaskExecutor | None = None,
) -> dict[str, Any]:
    """Run all frozen preview plans and retain create-only raw evidence."""

    plans = verify_receptor_plan_manifest(
        archive=archive,
        structure_manifest_path=structure_manifest_path,
        structures_dir=structures_dir,
        receptor_plan_manifest_path=receptor_plan_manifest_path,
    )
    if output_root.exists():
        raise ScreeningBenchmarkProtonationPreviewError(
            f"Preview evidence is create-only: {output_root}"
        )
    if public_manifest_path.exists():
        raise ScreeningBenchmarkProtonationPreviewError(
            f"Public preview manifest is create-only: {public_manifest_path}"
        )
    output_root.mkdir(parents=True)

    tasks = _preview_tasks(plans)
    worker_count = _parallel_worker_count(len(tasks), worker_limit=worker_limit)
    executor = _task_executor or _execute_preview_task
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ankora-propka-preview",
    ) as pool:
        futures = {
            pool.submit(executor, task, structures_dir, output_root): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as error:  # preserve one failure without losing neighbors
                result = _failed_task_result(task, output_root, error)
            results.append(result)

    results.sort(key=lambda item: int(item["sequence"]))
    failed = [item for item in results if item["status"] != "completed"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": _required_string(plans, "protocol_id"),
        "created_at": datetime.now(UTC).isoformat(),
        "source_receptor_plan_manifest_sha256": _required_sha256(
            plans, "manifest_sha256"
        ),
        "execution_policy": {
            "scope": "review-only structured PDB2PQR/PROPKA previews",
            "worker_count": worker_count,
            "create_only_local_evidence": True,
            "preview_outputs_are_final_receptors": False,
            "final_creation_requires_scientist_review": True,
        },
        "preview_census": {
            "requested": len(tasks),
            "completed": len(tasks) - len(failed),
            "failed": len(failed),
            "proposal_count": sum(
                int(item.get("proposal_count", 0)) for item in results
            ),
            "review_attention_count": sum(
                int(item.get("review_attention_count", 0)) for item in results
            ),
        },
        "previews": results,
        "scientist_review": {
            "status": "pending",
            "accepted_default_proposals": [],
            "approved_overrides": [],
            "boundary": (
                "No final receptor or PDBQT may be created until every proposal "
                "has been reviewed and the exact default/override decisions are frozen."
            ),
        },
        "result_status": (
            "preview_execution_failed_no_final_receptors_created"
            if failed
            else "six_previews_completed_scientist_review_pending_no_final_receptors_created"
        ),
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    local_manifest = output_root / "manifest.json"
    _write_create_only(local_manifest, _serialized(manifest))
    if failed:
        raise ScreeningBenchmarkProtonationPreviewError(
            f"{len(failed)} of {len(tasks)} protonation previews failed; "
            f"evidence retained at {output_root}."
        )
    _write_create_only(public_manifest_path, _serialized(manifest))
    return manifest


def verify_protonation_preview_manifest(
    manifest_path: Path,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Verify the frozen public summary and optionally every local raw file."""

    manifest = _load_object(manifest_path, "protonation-preview manifest")
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _manifest_digest(payload) != recorded:
        raise ScreeningBenchmarkProtonationPreviewError(
            "The protonation-preview manifest differs from its SHA-256."
        )
    census = _required_object(manifest.get("preview_census"), "preview census")
    if (
        _required_int(census, "requested") != 6
        or _required_int(census, "completed") != 6
        or _required_int(census, "failed") != 0
    ):
        raise ScreeningBenchmarkProtonationPreviewError(
            "The frozen preview census does not contain six successful executions."
        )
    review = _required_object(manifest.get("scientist_review"), "scientist review")
    if review.get("status") != "pending":
        raise ScreeningBenchmarkProtonationPreviewError(
            "This manifest is only the pending-review preview boundary."
        )
    previews = _required_list(manifest, "previews")
    if len(previews) != 6:
        raise ScreeningBenchmarkProtonationPreviewError(
            "The preview manifest must retain exactly six template executions."
        )
    for raw in previews:
        preview = _required_object(raw, "preview")
        if preview.get("status") != "completed":
            raise ScreeningBenchmarkProtonationPreviewError(
                "A frozen protonation preview is not completed."
            )
        if preview.get("final_receptor_created") is not False:
            raise ScreeningBenchmarkProtonationPreviewError(
                "A preview must not claim that a final receptor was created."
            )
        if not isinstance(preview.get("proposals"), list):
            raise ScreeningBenchmarkProtonationPreviewError(
                "A preview is missing its structured proposals."
            )
        if evidence_root is not None:
            _verify_local_files(preview, evidence_root.resolve())
    return manifest


def _preview_tasks(plans: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for target in _required_list(plans, "targets"):
        target_object = _required_object(target, "target")
        target_id = _required_string(target_object, "target_id")
        for role in ("primary_template", "alternate_template"):
            template = _required_object(target_object.get(role), role)
            tasks.append(
                {
                    "sequence": len(tasks) + 1,
                    "target_id": target_id,
                    "role": _required_string(template, "role"),
                    "pdb_id": _required_string(template, "pdb_id"),
                    "template": template,
                }
            )
    if len(tasks) != 6:
        raise ScreeningBenchmarkProtonationPreviewError(
            "The receptor-plan manifest must define exactly six previews."
        )
    return tasks


def _execute_preview_task(
    task: dict[str, Any], structures_dir: Path, output_root: Path
) -> dict[str, Any]:
    sequence = int(task["sequence"])
    pdb_id = str(task["pdb_id"])
    task_root = output_root / f"{sequence:02d}-{task['target_id']}-{task['role']}-{pdb_id}"
    task_root.mkdir()
    template = _required_object(task.get("template"), "template")
    identity = _required_object(template.get("official_structure"), "official structure")
    source_path = structures_dir / _required_string(identity, "filename")
    content = source_path.read_bytes()
    if len(content) != _required_int(identity, "size_bytes"):
        raise ScreeningBenchmarkProtonationPreviewError(
            f"Official structure {pdb_id} size changed before preview execution."
        )
    if hashlib.sha256(content).hexdigest() != _required_sha256(identity, "sha256"):
        raise ScreeningBenchmarkProtonationPreviewError(
            f"Official structure {pdb_id} SHA-256 changed before preview execution."
        )
    input_path = task_root / f"{pdb_id}.cif"
    _write_create_only(input_path, content)

    data_root = task_root / "ankora-data"
    structure_store = StructureArtifactStore(data_root, project_id="preview")
    receptor_store = ReceptorArtifactStore(data_root, project_id="preview")
    source_record = import_structure_bytes(
        content=content,
        filename=input_path.name,
        source=StructureSource.RCSB,
        source_uri=f"https://files.rcsb.org/download/{pdb_id.upper()}.cif",
        store=structure_store,
    )
    frozen_request = ReceptorPreparationRequest.model_validate(
        _required_object(template.get("preparation_request"), "preparation request")
    )
    if frozen_request.protonation.overrides:
        raise ScreeningBenchmarkProtonationPreviewError(
            "The pre-review receptor plan already contains protonation overrides."
        )
    preview_request = frozen_request.model_copy(update={"generate_pdbqt": False})
    record = prepare_receptor(
        source_artifact_id=source_record.artifact.artifact_id,
        request=preview_request,
        structure_store=structure_store,
        receptor_store=receptor_store,
    )
    if record.status is not ReceptorPreparationStatus.PROTONATED:
        raise ScreeningBenchmarkProtonationPreviewError(
            f"Preview {pdb_id} did not reach the protonated review boundary."
        )
    analysis = record.protonation_analysis
    if analysis is None:
        raise ScreeningBenchmarkProtonationPreviewError(
            f"Preview {pdb_id} produced no structured PROPKA analysis."
        )
    proposals = [item.model_dump(mode="json") for item in analysis.proposals]
    attention_ids = _attention_proposal_ids(proposals)
    files = _file_evidence(task_root, output_root)
    record_path = (
        data_root
        / "projects"
        / "preview"
        / "derived"
        / "receptors"
        / record.receptor_id
        / "record.json"
    )
    return {
        "sequence": sequence,
        "target_id": task["target_id"],
        "role": task["role"],
        "pdb_id": pdb_id,
        "status": "completed",
        "official_structure_sha256": hashlib.sha256(content).hexdigest(),
        "request_sha256": hashlib.sha256(
            _canonical_json(preview_request.model_dump(mode="json"))
        ).hexdigest(),
        "source_artifact_id": source_record.artifact.artifact_id,
        "preview_receptor_id": record.receptor_id,
        "preview_record_path": record_path.relative_to(output_root).as_posix(),
        "preview_record_sha256": _file_sha256(record_path),
        "analysis_generated_at": analysis.generated_at.isoformat(),
        "analysis_input_sha256": analysis.input_sha256,
        "tool_version": analysis.tool_version,
        "target_ph": analysis.target_ph,
        "force_field": analysis.force_field,
        "proposal_count": len(proposals),
        "review_attention_count": len(attention_ids),
        "review_attention_proposal_ids": attention_ids,
        "proposals": proposals,
        "raw_evidence_files": files,
        "final_receptor_created": False,
        "final_pdbqt_created": False,
    }


def _failed_task_result(
    task: dict[str, Any], output_root: Path, error: Exception
) -> dict[str, Any]:
    sequence = int(task["sequence"])
    task_root = output_root / f"{sequence:02d}-{task['target_id']}-{task['role']}-{task['pdb_id']}"
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
    _write_create_only(task_root / "preview-failure.json", _serialized(failure))
    return {
        "sequence": sequence,
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
    }


def _attention_proposal_ids(proposals: list[dict[str, Any]]) -> list[str]:
    return [
        _required_string(proposal, "proposal_id")
        for proposal in proposals
        if _REVIEW_WARNINGS.intersection(_string_list(proposal.get("warnings")))
    ]


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


def _verify_local_files(preview: dict[str, Any], evidence_root: Path) -> None:
    for raw in _required_list(preview, "raw_evidence_files"):
        item = _required_object(raw, "raw evidence file")
        relative = Path(_required_string(item, "path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ScreeningBenchmarkProtonationPreviewError(
                "Raw preview evidence contains an unsafe path."
            )
        path = (evidence_root / relative).resolve()
        if evidence_root not in path.parents or not path.is_file():
            raise ScreeningBenchmarkProtonationPreviewError(
                f"Raw preview evidence is unavailable: {relative.as_posix()}"
            )
        if path.stat().st_size != _required_int(item, "size_bytes"):
            raise ScreeningBenchmarkProtonationPreviewError(
                f"Raw preview evidence size changed: {relative.as_posix()}"
            )
        if _file_sha256(path) != _required_sha256(item, "sha256"):
            raise ScreeningBenchmarkProtonationPreviewError(
                f"Raw preview evidence SHA-256 changed: {relative.as_posix()}"
            )


def _parallel_worker_count(task_count: int, *, worker_limit: int | None) -> int:
    logical = os.cpu_count() or 2
    available = logical - 1 if logical > 1 else 1
    if worker_limit is not None:
        if worker_limit < 1:
            raise ScreeningBenchmarkProtonationPreviewError(
                "The preview worker limit must be at least one."
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
        raise ScreeningBenchmarkProtonationPreviewError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkProtonationPreviewError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkProtonationPreviewError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkProtonationPreviewError(
            f"{key} must be a non-empty string."
        )
    return raw


def _required_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkProtonationPreviewError(
            f"{key} must be a non-negative integer."
        )
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkProtonationPreviewError(f"{key} must be a SHA-256.")
    return raw


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ScreeningBenchmarkProtonationPreviewError(
            "Proposal warnings must be a list of strings."
        )
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
