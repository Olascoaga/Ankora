"""Verify exact TP53 histidine tautomers before benchmark receptor acceptance."""

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
    ProtonationOverride,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.receptor_preparation import prepare_receptor
from ankora_backend.services.structure_inspection import import_structure_bytes
from ankora_backend.validation.screening_benchmark_protonation_previews import (
    verify_protonation_preview_manifest,
)
from ankora_backend.validation.screening_benchmark_receptor_plans import (
    verify_receptor_plan_manifest,
)

SCHEMA_VERSION = 1


class ScreeningBenchmarkTautomerVerificationError(ValueError):
    """The exact-tautomer verification evidence is incomplete or changed."""


TautomerTaskExecutor = Callable[[dict[str, Any], Path, Path], dict[str, Any]]


def run_screening_benchmark_tautomer_verification(
    *,
    spec_path: Path,
    archive: Path,
    structure_manifest_path: Path,
    receptor_plan_manifest_path: Path,
    protonation_preview_manifest_path: Path,
    structures_dir: Path,
    output_root: Path,
    public_manifest_path: Path,
    worker_limit: int | None = None,
    _task_executor: TautomerTaskExecutor | None = None,
) -> dict[str, Any]:
    """Run the two pre-specified TP53 HIE candidate previews create-only."""

    spec = verify_tautomer_verification_spec(spec_path)
    plans = verify_receptor_plan_manifest(
        archive=archive,
        structure_manifest_path=structure_manifest_path,
        structures_dir=structures_dir,
        receptor_plan_manifest_path=receptor_plan_manifest_path,
    )
    previous = verify_protonation_preview_manifest(protonation_preview_manifest_path)
    if spec["source_receptor_plan_manifest_sha256"] != plans["manifest_sha256"]:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer specification names a different receptor-plan manifest."
        )
    if spec["source_protonation_preview_manifest_sha256"] != previous["manifest_sha256"]:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer specification names a different preview manifest."
        )
    if output_root.exists() or public_manifest_path.exists():
        raise ScreeningBenchmarkTautomerVerificationError(
            "Tautomer verification evidence is create-only."
        )
    output_root.mkdir(parents=True)

    tasks = _verification_tasks(spec, plans)
    worker_count = _parallel_worker_count(len(tasks), worker_limit)
    executor = _task_executor or _execute_tautomer_task
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ankora-tautomer-verification",
    ) as pool:
        futures = {
            pool.submit(executor, task, structures_dir, output_root): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = _failed_task_result(task, output_root, error)
            results.append(result)
    results.sort(key=lambda item: int(item["sequence"]))
    failed = [item for item in results if item["status"] != "completed"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": spec["protocol_id"],
        "verification_id": spec["verification_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "spec_sha256": spec["spec_sha256"],
        "source_receptor_plan_manifest_sha256": plans["manifest_sha256"],
        "source_protonation_preview_manifest_sha256": previous["manifest_sha256"],
        "scores_seen": False,
        "execution_policy": {
            "scope": "review-only TP53 exact-histidine-tautomer verification",
            "worker_count": worker_count,
            "create_only_local_evidence": True,
            "preview_outputs_are_final_receptors": False,
            "scientist_acceptance_required": True,
        },
        "verification_census": {
            "requested": len(tasks),
            "completed": len(tasks) - len(failed),
            "failed": len(failed),
        },
        "previews": results,
        "scientist_review": {
            "status": "pending",
            "candidate_override": "HIE at HIS A:179",
            "remaining_tp53_decisions": ["CYS A:238", "CYS A:242"],
            "boundary": (
                "This verifies that Ankora can write the requested tautomer. "
                "It does not accept the TP53 zinc-site protonation plan or create "
                "a final receptor/PDBQT."
            ),
        },
        "result_status": (
            "tautomer_verification_failed_no_final_receptors_created"
            if failed
            else "two_hie_candidates_verified_scientist_review_pending"
        ),
    }
    manifest["manifest_sha256"] = _digest(manifest)
    _write_create_only(output_root / "manifest.json", _serialized(manifest))
    if failed:
        raise ScreeningBenchmarkTautomerVerificationError(
            f"{len(failed)} of {len(tasks)} tautomer verifications failed."
        )
    _write_create_only(public_manifest_path, _serialized(manifest))
    return manifest


def verify_tautomer_verification_spec(path: Path) -> dict[str, Any]:
    spec = _load_object(path, "tautomer verification specification")
    recorded = _required_sha256(spec, "spec_sha256")
    payload = dict(spec)
    payload.pop("spec_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer verification specification differs from its SHA-256."
        )
    if spec.get("scores_seen") is not False:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer verification must be frozen before docking scores exist."
        )
    entries = _required_list(spec, "templates")
    if len(entries) != 2:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer specification must name exactly two TP53 templates."
        )
    identities: set[tuple[str, str]] = set()
    for raw in entries:
        entry = _required_object(raw, "tautomer template")
        if entry.get("target_id") != "TP53":
            raise ScreeningBenchmarkTautomerVerificationError(
                "Exact tautomer verification is restricted to TP53."
            )
        identity = (_required_string(entry, "role"), _required_string(entry, "pdb_id"))
        if identity in identities:
            raise ScreeningBenchmarkTautomerVerificationError(
                "The tautomer specification repeats a template."
            )
        identities.add(identity)
        override = ProtonationOverride.model_validate(
            _required_object(entry.get("override"), "tautomer override")
        )
        if (
            override.residue.chain_id,
            override.residue.residue_name,
            override.residue.sequence_number,
            override.residue.insertion_code,
            override.state,
        ) != ("A", "HIS", 179, "", "HIE"):
            raise ScreeningBenchmarkTautomerVerificationError(
                "Each frozen TP53 candidate must request HIE at HIS A:179."
            )
    return spec


def verify_tautomer_verification_manifest(
    path: Path,
    *,
    evidence_root: Path | None = None,
    expected_spec_sha256: str | None = None,
) -> dict[str, Any]:
    manifest = _load_object(path, "tautomer verification manifest")
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer verification manifest differs from its SHA-256."
        )
    if manifest.get("scores_seen") is not False:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer verification manifest is not pre-result evidence."
        )
    if expected_spec_sha256 is not None and manifest.get("spec_sha256") != (
        expected_spec_sha256
    ):
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer verification manifest names a different frozen request."
        )
    census = _required_object(manifest.get("verification_census"), "census")
    if (
        census.get("requested"),
        census.get("completed"),
        census.get("failed"),
    ) != (2, 2, 0):
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer manifest does not contain two successful executions."
        )
    previews = _required_list(manifest, "previews")
    if len(previews) != 2:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The tautomer manifest must retain two previews."
        )
    for raw in previews:
        preview = _required_object(raw, "tautomer preview")
        if (
            preview.get("status") != "completed"
            or preview.get("requested_state") != "HIE"
            or preview.get("output_state") != "HIE"
            or preview.get("ring_hydrogen") != "HE2"
            or preview.get("coordinating_atom_left_unprotonated") != "ND1"
            or preview.get("final_receptor_created") is not False
            or preview.get("final_pdbqt_created") is not False
        ):
            raise ScreeningBenchmarkTautomerVerificationError(
                "A TP53 preview lacks exact HIE output verification."
            )
        if evidence_root is not None:
            _verify_local_files(preview, evidence_root.resolve())
    review = _required_object(manifest.get("scientist_review"), "scientist review")
    if review.get("status") != "pending":
        raise ScreeningBenchmarkTautomerVerificationError(
            "Tautomer verification cannot silently accept the zinc-site plan."
        )
    if review.get("remaining_tp53_decisions") != ["CYS A:238", "CYS A:242"]:
        raise ScreeningBenchmarkTautomerVerificationError(
            "The remaining TP53 zinc-site decisions are not preserved."
        )
    return manifest


def _verification_tasks(spec: dict[str, Any], plans: dict[str, Any]) -> list[dict[str, Any]]:
    plan_templates: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_target in _required_list(plans, "targets"):
        target = _required_object(raw_target, "target")
        if target.get("target_id") != "TP53":
            continue
        for key in ("primary_template", "alternate_template"):
            template = _required_object(target.get(key), key)
            plan_templates[
                (_required_string(template, "role"), _required_string(template, "pdb_id"))
            ] = template
    tasks: list[dict[str, Any]] = []
    for sequence, raw_entry in enumerate(_required_list(spec, "templates"), start=1):
        entry = _required_object(raw_entry, "tautomer template")
        identity = (_required_string(entry, "role"), _required_string(entry, "pdb_id"))
        matched_template = plan_templates.get(identity)
        if matched_template is None:
            raise ScreeningBenchmarkTautomerVerificationError(
                f"Frozen receptor plans do not contain TP53 template {identity}."
            )
        tasks.append(
            {
                "sequence": sequence,
                "target_id": "TP53",
                "role": identity[0],
                "pdb_id": identity[1],
                "template": matched_template,
                "override": _required_object(entry.get("override"), "override"),
                "selection_basis": _required_string(entry, "selection_basis"),
            }
        )
    return tasks


def _execute_tautomer_task(
    task: dict[str, Any], structures_dir: Path, output_root: Path
) -> dict[str, Any]:
    sequence = int(task["sequence"])
    pdb_id = str(task["pdb_id"])
    task_root = output_root / f"{sequence:02d}-TP53-{task['role']}-{pdb_id}"
    task_root.mkdir()
    template = _required_object(task.get("template"), "template")
    identity = _required_object(template.get("official_structure"), "official structure")
    source_path = structures_dir / _required_string(identity, "filename")
    content = source_path.read_bytes()
    if len(content) != int(identity["size_bytes"]) or hashlib.sha256(content).hexdigest() != str(
        identity["sha256"]
    ):
        raise ScreeningBenchmarkTautomerVerificationError(
            f"Official structure {pdb_id} changed before tautomer verification."
        )
    _write_create_only(task_root / f"{pdb_id}.cif", content)
    data_root = task_root / "ankora-data"
    structure_store = StructureArtifactStore(data_root, project_id="tautomer-preview")
    receptor_store = ReceptorArtifactStore(data_root, project_id="tautomer-preview")
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
        raise ScreeningBenchmarkTautomerVerificationError(
            "The frozen receptor plan already contains protonation overrides."
        )
    override = ProtonationOverride.model_validate(task["override"])
    protonation = frozen.protonation.model_copy(update={"overrides": [override]})
    request = frozen.model_copy(
        update={"protonation": protonation, "generate_pdbqt": False}
    )
    record = prepare_receptor(
        source_artifact_id=source.artifact.artifact_id,
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
    )
    if record.status is not ReceptorPreparationStatus.PROTONATED:
        raise ScreeningBenchmarkTautomerVerificationError(
            f"TP53 preview {pdb_id} did not stop at the protonated boundary."
        )
    if record.protonation_analysis is None:
        raise ScreeningBenchmarkTautomerVerificationError(
            f"TP53 preview {pdb_id} has no protonation analysis."
        )
    proposal = next(
        (
            item
            for item in record.protonation_analysis.proposals
            if item.residue.chain_id == "A"
            and item.residue.residue_name == "HIS"
            and item.residue.sequence_number == 179
            and item.residue.insertion_code == ""
        ),
        None,
    )
    if proposal is None or proposal.selected_state != "HIE" or proposal.output_state != "HIE":
        raise ScreeningBenchmarkTautomerVerificationError(
            f"TP53 preview {pdb_id} did not verify requested HIE at HIS A:179."
        )
    files = _file_evidence(task_root, output_root)
    return {
        "sequence": sequence,
        "target_id": "TP53",
        "role": task["role"],
        "pdb_id": pdb_id,
        "status": "completed",
        "selection_basis": task["selection_basis"],
        "requested_state": "HIE",
        "output_state": proposal.output_state,
        "ring_hydrogen": "HE2",
        "coordinating_atom_left_unprotonated": "ND1",
        "proposal": proposal.model_dump(mode="json"),
        "tool_version": record.protonation_analysis.tool_version,
        "preview_receptor_id": record.receptor_id,
        "raw_evidence_files": files,
        "final_receptor_created": False,
        "final_pdbqt_created": False,
    }


def _failed_task_result(
    task: dict[str, Any], output_root: Path, error: Exception
) -> dict[str, Any]:
    task_root = output_root / f"{int(task['sequence']):02d}-TP53-{task['role']}-{task['pdb_id']}"
    task_root.mkdir(exist_ok=True)
    failure: dict[str, Any] = {
        "error_type": type(error).__name__,
        "message": str(error),
        "traceback": traceback.format_exc(),
    }
    if isinstance(error, AnkoraDomainError):
        failure.update(
            {"code": error.code, "stage": error.stage, "details": error.details}
        )
    _write_create_only(task_root / "verification-failure.json", _serialized(failure))
    return {
        "sequence": task["sequence"],
        "target_id": "TP53",
        "role": task["role"],
        "pdb_id": task["pdb_id"],
        "status": "failed",
        "message": str(error),
        "raw_evidence_files": _file_evidence(task_root, output_root),
        "final_receptor_created": False,
        "final_pdbqt_created": False,
    }


def _parallel_worker_count(task_count: int, worker_limit: int | None) -> int:
    available = max(1, (os.cpu_count() or 2) - 1)
    if worker_limit is not None:
        if worker_limit < 1:
            raise ScreeningBenchmarkTautomerVerificationError(
                "The tautomer worker limit must be at least one."
            )
        available = min(available, worker_limit)
    return min(task_count, available)


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


def _verify_local_files(preview: dict[str, Any], root: Path) -> None:
    for raw in _required_list(preview, "raw_evidence_files"):
        item = _required_object(raw, "raw evidence file")
        relative = Path(_required_string(item, "path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ScreeningBenchmarkTautomerVerificationError("Unsafe evidence path.")
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise ScreeningBenchmarkTautomerVerificationError(
                f"Raw tautomer evidence is unavailable: {relative.as_posix()}"
            )
        if path.stat().st_size != int(item["size_bytes"]) or _file_sha256(path) != str(
            item["sha256"]
        ):
            raise ScreeningBenchmarkTautomerVerificationError(
                f"Raw tautomer evidence changed: {relative.as_posix()}"
            )


def _write_create_only(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as destination:
        destination.write(content)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkTautomerVerificationError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkTautomerVerificationError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkTautomerVerificationError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkTautomerVerificationError(
            f"{key} must be a non-empty string."
        )
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(char not in "0123456789abcdef" for char in raw):
        raise ScreeningBenchmarkTautomerVerificationError(f"{key} must be a SHA-256.")
    return raw


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
