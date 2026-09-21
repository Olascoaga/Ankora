"""Execute and verify the frozen loss-preserving ligand-preparation plan.

Every source parent receives exactly one public terminal outcome.  Local raw
evidence is create-only and resumable; the path-free public manifest is only
written after the full source census closes.  This module never docks a ligand
and never computes a docking score or enrichment metric.
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import traceback
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandAlertPolicy,
    LigandChargeModel,
    LigandDuplicatePolicy,
    LigandFilterDisposition,
    LigandFilterEvaluation,
    LigandForceField,
    LigandLibraryFilterPlan,
    LigandLibraryFilterRun,
    LigandLibraryRecord,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import import_local_ligand_library
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from ankora_backend.validation.screening_benchmark_ligand_plan import (
    verify_ligand_preparation_plan,
)

SCHEMA_VERSION = 1
TERMINAL_STATUSES = frozenset(
    {
        "prepared",
        "unresolved_chemical_state",
        "import_failed",
        "conformer_nonconverged",
        "conformer_failed",
        "pdbqt_failed",
        "preparation_failed",
        "internal_failed",
    }
)


class ScreeningBenchmarkLigandPreparationError(ValueError):
    """The execution evidence is incomplete, changed, or unsafe."""


ProgressCallback = Callable[[int, int, str], None]
LigandTaskExecutor = Callable[[dict[str, Any], LigandArtifactStore, Path, int], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _TargetContext:
    target: dict[str, Any]
    store: LigandArtifactStore
    library: LigandLibraryRecord
    filter_run: LigandLibraryFilterRun


def run_screening_benchmark_ligand_preparation(
    *,
    archive: Path,
    input_manifest_path: Path,
    plan_manifest_path: Path,
    output_root: Path,
    public_manifest_path: Path,
    worker_limit: int | None = None,
    progress_callback: ProgressCallback | None = None,
    _task_executor: LigandTaskExecutor | None = None,
) -> dict[str, Any]:
    """Execute or resume all frozen parent preparations and close the census."""

    plan = verify_ligand_preparation_plan(
        plan_manifest_path,
        archive=archive,
        input_manifest_path=input_manifest_path,
    )
    local_manifest = output_root / "manifest.json"
    if local_manifest.is_file():
        manifest = verify_ligand_preparation_manifest(
            local_manifest,
            evidence_root=output_root,
            plan_manifest_path=plan_manifest_path,
        )
        if public_manifest_path.exists():
            if public_manifest_path.read_bytes() != local_manifest.read_bytes():
                raise ScreeningBenchmarkLigandPreparationError(
                    "The public and local ligand-preparation manifests differ."
                )
        else:
            _write_create_only(public_manifest_path, local_manifest.read_bytes())
        return manifest
    if public_manifest_path.exists():
        raise ScreeningBenchmarkLigandPreparationError(
            "A public ligand-preparation manifest exists without its local evidence."
        )

    _initialize_or_verify_run(output_root, plan)
    worker_count = _parallel_worker_count(
        _required_int(_required_object(plan.get("totals"), "plan totals"), "all_parents"),
        worker_limit,
    )
    source_libraries = _source_libraries(archive, plan)
    contexts = [
        _load_or_prepare_target(
            target=_required_object(raw_target, "target plan"),
            source_content=source_libraries[
                _required_string(_required_object(raw_target, "target plan"), "target_id")
            ],
            output_root=output_root,
            worker_count=worker_count,
        )
        for raw_target in _required_list(plan, "targets")
    ]

    task_contexts = _preparation_tasks(contexts)
    total = len(task_contexts)
    expected_total = _required_int(
        _required_object(plan.get("totals"), "plan totals"), "all_parents"
    )
    if total != expected_total:
        raise ScreeningBenchmarkLigandPreparationError(
            "The imported ligand tasks do not cover the frozen source census."
        )

    results: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], LigandArtifactStore]] = []
    completed = 0
    for task, store in task_contexts:
        terminal = _existing_terminal(task, output_root)
        if terminal is None:
            pending.append((task, store))
            continue
        results.append(terminal)
        completed += 1
        if progress_callback is not None:
            progress_callback(completed, total, str(terminal["status"]))

    executor = _task_executor or _execute_ligand_task
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ankora-benchmark-ligand",
    ) as pool:
        futures = {
            pool.submit(
                _execute_attempt,
                task=task,
                store=store,
                output_root=output_root,
                worker_count=worker_count,
                executor=executor,
            ): task
            for task, store in pending
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, total, str(result["status"]))

    results.sort(key=lambda item: int(item["sequence"]))
    manifest = _completion_manifest(
        plan=plan,
        worker_count=worker_count,
        entries=results,
    )
    serialized = _serialized(manifest)
    _write_create_only(local_manifest, serialized)
    _write_create_only(public_manifest_path, serialized)
    return verify_ligand_preparation_manifest(
        public_manifest_path,
        evidence_root=output_root,
        plan_manifest_path=plan_manifest_path,
    )


def verify_ligand_preparation_manifest(
    path: Path,
    *,
    evidence_root: Path | None = None,
    plan_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Verify census closure, execution boundaries, identities, and evidence."""

    manifest = _load_object(path, "ligand-preparation manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkLigandPreparationError(
            "Unsupported ligand-preparation manifest schema."
        )
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkLigandPreparationError(
            "The ligand-preparation manifest differs from its SHA-256."
        )
    if manifest.get("scores_seen") is not False:
        raise ScreeningBenchmarkLigandPreparationError(
            "Ligand preparation must remain pre-result evidence."
        )
    policy = _required_object(manifest.get("execution_policy"), "execution policy")
    if (
        policy.get("all_source_parents_retained") is not True
        or policy.get("failures_retained_as_unscored_worst_tie") is not True
        or policy.get("docking_executed") is not False
        or policy.get("scores_or_metrics_computed") is not False
        or policy.get("raw_evidence_retained_locally") is not True
    ):
        raise ScreeningBenchmarkLigandPreparationError(
            "The loss-preserving ligand-preparation boundary changed."
        )

    entries = _required_list(manifest, "entries")
    census = _required_object(manifest.get("preparation_census"), "preparation census")
    requested = _required_int(census, "requested")
    terminal_count = _required_int(census, "terminal")
    prepared_count = _required_int(census, "prepared")
    unscored_count = _required_int(census, "unscored_worst_tie")
    if requested != len(entries) or terminal_count != requested:
        raise ScreeningBenchmarkLigandPreparationError(
            "The terminal ligand-preparation census does not close."
        )
    if prepared_count + unscored_count != requested:
        raise ScreeningBenchmarkLigandPreparationError(
            "Prepared and unscored parents do not cover the source population."
        )

    expected_parents: list[dict[str, Any]] | None = None
    if plan_manifest_path is not None:
        plan = verify_ligand_preparation_plan(plan_manifest_path)
        if manifest.get("source_ligand_preparation_plan_sha256") != plan.get("manifest_sha256"):
            raise ScreeningBenchmarkLigandPreparationError(
                "The outcomes name a different frozen ligand-preparation plan."
            )
        expected_parents = [
            _required_object(parent, "planned parent")
            for target in _required_list(plan, "targets")
            for parent in _required_list(_required_object(target, "target"), "parents")
        ]
        if len(expected_parents) != requested:
            raise ScreeningBenchmarkLigandPreparationError(
                "The result census differs from the frozen ligand plan."
            )

    statuses: Counter[str] = Counter()
    identities: set[tuple[str, int]] = set()
    for index, raw_entry in enumerate(entries):
        entry = _required_object(raw_entry, "terminal entry")
        sequence = _required_positive_int(entry, "sequence")
        if sequence != index + 1:
            raise ScreeningBenchmarkLigandPreparationError(
                "Terminal ligand outcomes must remain source ordered."
            )
        target_id = _required_string(entry, "target_id")
        target_sequence = _required_positive_int(entry, "target_sequence")
        identity = (target_id, target_sequence)
        if identity in identities:
            raise ScreeningBenchmarkLigandPreparationError(
                "A terminal ligand outcome repeats a source parent."
            )
        identities.add(identity)
        status = _required_string(entry, "status")
        if status not in TERMINAL_STATUSES:
            raise ScreeningBenchmarkLigandPreparationError(
                f"Unsupported terminal ligand status: {status}."
            )
        statuses[status] += 1
        prepared = entry.get("prepared") is True
        if prepared != (status == "prepared"):
            raise ScreeningBenchmarkLigandPreparationError(
                "A ligand preparation status contradicts its prepared flag."
            )
        _required_sha256(entry, "source_smiles_sha256")
        _required_sha256(entry, "canonical_isomeric_smiles_sha256")
        _safe_relative_path(_required_string(entry, "source_member_path"))
        terminal = _required_object(entry.get("terminal_evidence"), "terminal evidence")
        _verify_evidence_item(terminal, evidence_root)
        artifacts = _required_list(entry, "artifacts")
        stages = {
            _required_string(_required_object(item, "artifact evidence"), "stage")
            for item in artifacts
        }
        for item in artifacts:
            _verify_evidence_item(_required_object(item, "artifact evidence"), evidence_root)
        if prepared and not {"conformer_sdf", "ligand_pdbqt"}.issubset(stages):
            raise ScreeningBenchmarkLigandPreparationError(
                "A prepared parent lacks conformer or PDBQT evidence."
            )
        if expected_parents is not None:
            planned = expected_parents[index]
            for key in (
                "sequence",
                "target_sequence",
                "class_label",
                "class_index",
                "source_member_path",
                "source_line_number",
                "source_identifier",
                "source_smiles_sha256",
                "canonical_isomeric_smiles_sha256",
                "conformer_seed",
            ):
                if entry.get(key) != planned.get(key):
                    raise ScreeningBenchmarkLigandPreparationError(
                        f"Terminal ligand identity changed at sequence {sequence}: {key}."
                    )

    status_census = _required_object(census.get("by_status"), "status census")
    if dict(sorted(statuses.items())) != {
        key: _required_int(status_census, key) for key in sorted(status_census)
    }:
        raise ScreeningBenchmarkLigandPreparationError(
            "The per-status ligand census differs from the terminal rows."
        )
    if statuses["prepared"] != prepared_count:
        raise ScreeningBenchmarkLigandPreparationError(
            "The prepared ligand census differs from the terminal rows."
        )
    return manifest


def _initialize_or_verify_run(output_root: Path, plan: dict[str, Any]) -> None:
    run_path = output_root / "run.json"
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": _required_string(plan, "protocol_id"),
        "source_ligand_preparation_plan_sha256": _required_sha256(plan, "manifest_sha256"),
        "docking_executed": False,
        "scores_or_metrics_computed": False,
    }
    if run_path.is_file():
        if _load_object(run_path, "ligand-preparation run") != expected:
            raise ScreeningBenchmarkLigandPreparationError(
                "The existing preparation run belongs to a different frozen plan."
            )
        return
    output_root.mkdir(parents=True, exist_ok=True)
    _write_create_only(run_path, _serialized(expected))


def _source_libraries(archive: Path, plan: dict[str, Any]) -> dict[str, bytes]:
    try:
        with tarfile.open(archive, mode="r:*") as source:
            members = {
                _safe_relative_path(member.name).as_posix(): member
                for member in source.getmembers()
                if member.isfile()
            }
            result: dict[str, bytes] = {}
            for raw_target in _required_list(plan, "targets"):
                target = _required_object(raw_target, "target plan")
                lines_by_member: dict[str, list[str]] = {}
                output_lines: list[str] = []
                for raw_parent in _required_list(target, "parents"):
                    parent = _required_object(raw_parent, "planned parent")
                    member_path = _required_string(parent, "source_member_path")
                    if member_path not in lines_by_member:
                        member = members.get(member_path)
                        if member is None:
                            raise ScreeningBenchmarkLigandPreparationError(
                                f"Source member is unavailable: {member_path}."
                            )
                        stream = source.extractfile(member)
                        if stream is None:
                            raise ScreeningBenchmarkLigandPreparationError(
                                f"Source member is unreadable: {member_path}."
                            )
                        try:
                            text = stream.read().decode("utf-8")
                        except UnicodeDecodeError as error:
                            raise ScreeningBenchmarkLigandPreparationError(
                                f"Source member is not UTF-8: {member_path}."
                            ) from error
                        lines_by_member[member_path] = text.splitlines()
                    line_number = _required_positive_int(parent, "source_line_number")
                    source_lines = lines_by_member[member_path]
                    if line_number > len(source_lines):
                        raise ScreeningBenchmarkLigandPreparationError(
                            f"Source line is unavailable: {member_path}:{line_number}."
                        )
                    fields = source_lines[line_number - 1].strip().split()
                    if len(fields) < 2:
                        raise ScreeningBenchmarkLigandPreparationError(
                            f"Source ligand row is incomplete: {member_path}:{line_number}."
                        )
                    source_smiles, source_identifier = fields[0], fields[1]
                    if hashlib.sha256(
                        source_smiles.encode("utf-8")
                    ).hexdigest() != _required_sha256(
                        parent, "source_smiles_sha256"
                    ) or source_identifier != _required_string(parent, "source_identifier"):
                        raise ScreeningBenchmarkLigandPreparationError(
                            f"Source ligand identity changed: {member_path}:{line_number}."
                        )
                    output_lines.append(f"{source_smiles} {source_identifier}")
                target_id = _required_string(target, "target_id")
                result[target_id] = ("\n".join(output_lines) + "\n").encode("utf-8")
            return result
    except (OSError, tarfile.TarError) as error:
        raise ScreeningBenchmarkLigandPreparationError(
            "The frozen ligand source archive is unreadable."
        ) from error


def _load_or_prepare_target(
    *,
    target: dict[str, Any],
    source_content: bytes,
    output_root: Path,
    worker_count: int,
) -> _TargetContext:
    target_id = _required_string(target, "target_id")
    target_root = output_root / "targets" / _slug(target_id)
    completed = sorted(target_root.glob("attempt-*/target.json"))
    if len(completed) > 1:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Target {target_id} has more than one completed import attempt."
        )
    if completed:
        record = _load_object(completed[0], "target preparation")
        return _target_context_from_record(
            target=target,
            source_content=source_content,
            output_root=output_root,
            record=record,
        )

    attempt_root = _next_attempt_directory(target_root)
    attempt_root.mkdir(parents=True)
    data_root = attempt_root / "ankora-data"
    project_id = f"benchmark-{_slug(target_id)}"
    store = LigandArtifactStore(data_root, project_id=project_id)
    library = import_local_ligand_library(
        content=source_content,
        filename=f"{_slug(target_id)}-exact-source.smi",
        store=store,
    )
    parents = _required_list(target, "parents")
    if library.artifact.record_count != len(parents):
        raise ScreeningBenchmarkLigandPreparationError(
            f"Target {target_id} import did not preserve every source row."
        )
    filter_run = apply_library_filters(
        library_id=library.artifact.library_id,
        request=_descriptive_filter_request(),
        store=store,
        worker_limit=worker_count,
    )
    record = {
        "target_id": target_id,
        "source_content_sha256": hashlib.sha256(source_content).hexdigest(),
        "record_count": len(parents),
        "data_root": data_root.relative_to(output_root).as_posix(),
        "project_id": project_id,
        "library_id": library.artifact.library_id,
        "filter_run_id": filter_run.artifact.filter_run_id,
        "filter_run_sha256": filter_run.artifact.sha256,
        "rdkit_version": filter_run.rdkit_version,
        "descriptive_only": True,
    }
    _write_create_only(attempt_root / "target.json", _serialized(record))
    return _TargetContext(
        target=target,
        store=store,
        library=library,
        filter_run=filter_run,
    )


def _target_context_from_record(
    *,
    target: dict[str, Any],
    source_content: bytes,
    output_root: Path,
    record: dict[str, Any],
) -> _TargetContext:
    target_id = _required_string(target, "target_id")
    if (
        record.get("target_id") != target_id
        or record.get("source_content_sha256") != hashlib.sha256(source_content).hexdigest()
        or record.get("record_count") != len(_required_list(target, "parents"))
        or record.get("descriptive_only") is not True
    ):
        raise ScreeningBenchmarkLigandPreparationError(
            f"Completed target evidence changed for {target_id}."
        )
    data_root = _safe_evidence_path(
        output_root,
        _required_string(record, "data_root"),
        require_file=False,
    )
    store = LigandArtifactStore(
        data_root,
        project_id=_required_string(record, "project_id"),
    )
    library = store.load_library_record(_required_string(record, "library_id"))
    filter_run = store.load_filter_run(
        library.artifact.library_id,
        _required_string(record, "filter_run_id"),
    )
    if filter_run.artifact.sha256 != _required_sha256(record, "filter_run_sha256"):
        raise ScreeningBenchmarkLigandPreparationError(
            f"Descriptive filter evidence changed for {target_id}."
        )
    return _TargetContext(
        target=target,
        store=store,
        library=library,
        filter_run=filter_run,
    )


def _descriptive_filter_request() -> Any:
    from ankora_backend.schemas.ligands import ApplyLigandLibraryFilterRequest

    return ApplyLigandLibraryFilterRequest(
        acknowledge_selection=True,
        plan=LigandLibraryFilterPlan(
            preset="custom",
            require_lipinski=False,
            require_veber=False,
            require_ghose=False,
            require_muegge=False,
            minimum_qed=None,
            pains_policy=LigandAlertPolicy.REVIEW,
            brenk_policy=LigandAlertPolicy.REVIEW,
            duplicate_policy=LigandDuplicatePolicy.KEEP,
        ),
    )


def _preparation_tasks(
    contexts: list[_TargetContext],
) -> list[tuple[dict[str, Any], LigandArtifactStore]]:
    tasks: list[tuple[dict[str, Any], LigandArtifactStore]] = []
    for context in contexts:
        parents = _required_list(context.target, "parents")
        entries = context.library.entries
        evaluations = {item.record_index: item for item in context.filter_run.evaluations}
        if len(entries) != len(parents):
            raise ScreeningBenchmarkLigandPreparationError(
                "An imported target library changed after filtering."
            )
        target_id = _required_string(context.target, "target_id")
        for record_index, raw_parent in enumerate(parents):
            parent = _required_object(raw_parent, "planned parent")
            entry = entries[record_index]
            task: dict[str, Any] = {
                **parent,
                "target_id": target_id,
                "record_index": record_index,
                "library_id": context.library.artifact.library_id,
                "evaluation": evaluations.get(record_index),
                "import_failure": (
                    entry.failure.model_dump(mode="json") if entry.failure is not None else None
                ),
                "ligand_id": (
                    entry.ligand.artifact.ligand_id if entry.ligand is not None else None
                ),
                "state_id": (
                    entry.ligand.state.state_id
                    if entry.ligand is not None and entry.ligand.state is not None
                    else None
                ),
            }
            tasks.append((task, context.store))
    tasks.sort(key=lambda item: int(item[0]["sequence"]))
    return tasks


def _existing_terminal(task: dict[str, Any], output_root: Path) -> dict[str, Any] | None:
    entry_root = output_root / "entries" / f"{int(task['sequence']):05d}"
    terminals = sorted(entry_root.glob("attempt-*/terminal.json"))
    if len(terminals) > 1:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Parent {task['sequence']} has more than one terminal attempt."
        )
    if not terminals:
        return None
    terminal = _load_object(terminals[0], "terminal ligand attempt")
    result = _required_object(terminal.get("public_result"), "public terminal result")
    _verify_task_identity(task, result)
    return _with_terminal_evidence(result, terminals[0], output_root)


def _execute_attempt(
    *,
    task: dict[str, Any],
    store: LigandArtifactStore,
    output_root: Path,
    worker_count: int,
    executor: LigandTaskExecutor,
) -> dict[str, Any]:
    sequence = int(task["sequence"])
    entry_root = output_root / "entries" / f"{sequence:05d}"
    attempt_root = _next_attempt_directory(entry_root)
    attempt_root.mkdir(parents=True)
    started = {
        "sequence": sequence,
        "target_id": task["target_id"],
        "target_sequence": task["target_sequence"],
        "source_smiles_sha256": task["source_smiles_sha256"],
        "canonical_isomeric_smiles_sha256": task["canonical_isomeric_smiles_sha256"],
        "conformer_seed": task["conformer_seed"],
        "started_at": datetime.now(UTC).isoformat(),
    }
    _write_create_only(attempt_root / "started.json", _serialized(started))

    local_error: dict[str, Any] | None = None
    try:
        public_result = _base_public_result(task)
        import_failure = task.get("import_failure")
        evaluation = task.get("evaluation")
        if import_failure is not None:
            failure = _required_object(import_failure, "import failure")
            public_result.update(
                {
                    "status": "import_failed",
                    "prepared": False,
                    "state_disposition": "import_failed",
                    "descriptor_evidence": None,
                    "error": {
                        "code": _required_string(failure, "code"),
                        "stage": "ligand_import",
                        "message": _required_string(failure, "message"),
                    },
                    "artifacts": [],
                }
            )
        elif not isinstance(evaluation, LigandFilterEvaluation):
            raise ScreeningBenchmarkLigandPreparationError(
                "An imported parent lacks descriptive filter evidence."
            )
        elif evaluation.disposition is LigandFilterDisposition.NEEDS_DECISION:
            public_result.update(
                {
                    "status": "unresolved_chemical_state",
                    "prepared": False,
                    "state_disposition": evaluation.disposition.value,
                    "descriptor_evidence": _evaluation_evidence(evaluation),
                    "error": {
                        "code": "+".join(evaluation.reasons),
                        "stage": "ligand_chemical_state",
                        "message": (
                            "The exact imported state requires a scientific decision; "
                            "the frozen benchmark policy forbids guessing it."
                        ),
                    },
                    "artifacts": [],
                }
            )
        elif evaluation.disposition is not LigandFilterDisposition.ELIGIBLE:
            raise ScreeningBenchmarkLigandPreparationError(
                "A descriptive-only filter excluded a benchmark parent."
            )
        else:
            public_result.update(
                {
                    "state_disposition": evaluation.disposition.value,
                    "descriptor_evidence": _evaluation_evidence(evaluation),
                }
            )
            public_result.update(executor(task, store, output_root, worker_count))
    except AnkoraDomainError as error:
        public_result = _base_public_result(task)
        evaluation = task.get("evaluation")
        public_result.update(
            {
                "status": _domain_failure_status(error),
                "prepared": False,
                "state_disposition": (
                    evaluation.disposition.value
                    if isinstance(evaluation, LigandFilterEvaluation)
                    else "unknown"
                ),
                "descriptor_evidence": (
                    _evaluation_evidence(evaluation)
                    if isinstance(evaluation, LigandFilterEvaluation)
                    else None
                ),
                "error": {
                    "code": error.code,
                    "stage": error.stage,
                    "message": error.message,
                    **(
                        {"tool_version": error.details["tool_version"]}
                        if isinstance(error.details.get("tool_version"), str)
                        else {}
                    ),
                },
                "artifacts": _failure_artifacts(error, store, output_root),
            }
        )
        local_error = {
            "kind": "AnkoraDomainError",
            "code": error.code,
            "stage": error.stage,
            "message": error.message,
            "details": error.details,
            "traceback": traceback.format_exc(),
        }
    except ScreeningBenchmarkLigandPreparationError:
        raise
    except Exception as error:
        public_result = _base_public_result(task)
        evaluation = task.get("evaluation")
        public_result.update(
            {
                "status": "internal_failed",
                "prepared": False,
                "state_disposition": (
                    evaluation.disposition.value
                    if isinstance(evaluation, LigandFilterEvaluation)
                    else "unknown"
                ),
                "descriptor_evidence": (
                    _evaluation_evidence(evaluation)
                    if isinstance(evaluation, LigandFilterEvaluation)
                    else None
                ),
                "error": {
                    "code": "BENCHMARK_LIGAND_PREPARATION_UNEXPECTED",
                    "stage": "benchmark_ligand_preparation",
                    "message": "An unexpected ligand-preparation failure was retained.",
                },
                "artifacts": [],
            }
        )
        local_error = {
            "kind": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }

    _validate_public_result(public_result)
    terminal = {
        "completed_at": datetime.now(UTC).isoformat(),
        "public_result": public_result,
        "local_error": local_error,
    }
    terminal_path = attempt_root / "terminal.json"
    _write_create_only(terminal_path, _serialized(terminal))
    return _with_terminal_evidence(public_result, terminal_path, output_root)


def _execute_ligand_task(
    task: dict[str, Any],
    store: LigandArtifactStore,
    output_root: Path,
    worker_count: int,
) -> dict[str, Any]:
    ligand_id = _required_string(task, "ligand_id")
    state_id = _required_string(task, "state_id")
    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            force_field=LigandForceField.MMFF94S,
            max_iterations=500,
            acknowledge_current_chemical_state=True,
            state_id=state_id,
            random_seed=_required_positive_int(task, "conformer_seed"),
            client_concurrency_hint=worker_count,
        ),
        store=store,
    )
    conformer_artifacts = _record_artifacts(
        stage="conformer_sdf",
        content_path=store.conformer_content_path(ligand_id, conformer.artifact.conformer_id),
        output_root=output_root,
    )
    conformer_summary = {
        "conformer_id": conformer.artifact.conformer_id,
        "chemical_state_id": conformer.artifact.chemical_state_id,
        "sha256": conformer.artifact.sha256,
        "size_bytes": conformer.artifact.size_bytes,
        "force_field": conformer.minimization.force_field.value,
        "max_iterations": conformer.minimization.max_iterations,
        "converged": conformer.minimization.converged,
        "initial_energy_kcal_mol": conformer.minimization.initial_energy_kcal_mol,
        "final_energy_kcal_mol": conformer.minimization.final_energy_kcal_mol,
        "embedding_method": conformer.minimization.embedding_method,
        "random_seed": conformer.minimization.random_seed,
        "conformer_pool_size": conformer.minimization.conformer_pool_size,
        "conformer_pool_converged_count": (conformer.minimization.conformer_pool_converged_count),
        "selection_policy": (
            conformer.minimization.conformer_selection_policy.value
            if conformer.minimization.conformer_selection_policy is not None
            else None
        ),
    }
    if not conformer.minimization.converged:
        return {
            "status": "conformer_nonconverged",
            "prepared": False,
            "conformer": conformer_summary,
            "pdbqt": None,
            "error": {
                "code": "LIGAND_CONFORMER_NOT_CONVERGED",
                "stage": "ligand_minimization",
                "message": (
                    "No member of the frozen ETKDGv3 pool converged within the "
                    "MMFF94s iteration limit; the best nonconverged geometry was retained."
                ),
            },
            "artifacts": conformer_artifacts,
        }

    pdbqt = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(
            charge_model=LigandChargeModel.GASTEIGER,
            client_concurrency_hint=worker_count,
        ),
        store=store,
    )
    pdbqt_artifacts = _record_artifacts(
        stage="ligand_pdbqt",
        content_path=store.pdbqt_content_path(ligand_id, pdbqt.artifact.preparation_id),
        output_root=output_root,
        include_logs=True,
    )
    return {
        "status": "prepared",
        "prepared": True,
        "conformer": conformer_summary,
        "pdbqt": {
            "preparation_id": pdbqt.artifact.preparation_id,
            "conformer_id": pdbqt.artifact.conformer_id,
            "sha256": pdbqt.artifact.sha256,
            "size_bytes": pdbqt.artifact.size_bytes,
            "charge_model": pdbqt.charge_model.value,
            "tool_name": pdbqt.tool.name,
            "tool_version": pdbqt.tool.version,
        },
        "error": None,
        "artifacts": [*conformer_artifacts, *pdbqt_artifacts],
    }


def _base_public_result(task: dict[str, Any]) -> dict[str, Any]:
    return {
        key: task[key]
        for key in (
            "sequence",
            "target_sequence",
            "target_id",
            "class_label",
            "class_index",
            "source_member_path",
            "source_line_number",
            "source_identifier",
            "source_smiles_sha256",
            "canonical_isomeric_smiles_sha256",
            "conformer_seed",
        )
    }


def _evaluation_evidence(evaluation: LigandFilterEvaluation) -> dict[str, Any]:
    return {
        "descriptors": (
            evaluation.descriptors.model_dump(mode="json")
            if evaluation.descriptors is not None
            else None
        ),
        "lipinski": (
            evaluation.lipinski.model_dump(mode="json") if evaluation.lipinski is not None else None
        ),
        "veber": (
            evaluation.veber.model_dump(mode="json") if evaluation.veber is not None else None
        ),
        "ghose": (
            evaluation.ghose.model_dump(mode="json") if evaluation.ghose is not None else None
        ),
        "muegge": (
            evaluation.muegge.model_dump(mode="json") if evaluation.muegge is not None else None
        ),
        "alerts": [
            {"catalog": item.catalog, "description": item.description} for item in evaluation.alerts
        ],
        "duplicate_recorded": evaluation.duplicate_of_ligand_id is not None,
        "reasons": evaluation.reasons,
    }


def _domain_failure_status(error: AnkoraDomainError) -> str:
    if error.stage == "ligand_pdbqt":
        return "pdbqt_failed"
    if error.code in {
        "LIG_STEREOCHEMISTRY_UNDEFINED",
        "LIGAND_MULTICOMPONENT_REQUIRES_DECISION",
        "LIGAND_STATE_CONFIRMATION_REQUIRED",
    }:
        return "unresolved_chemical_state"
    if error.stage == "ligand_minimization":
        return "conformer_failed"
    return "preparation_failed"


def _failure_artifacts(
    error: AnkoraDomainError,
    store: LigandArtifactStore,
    output_root: Path,
) -> list[dict[str, Any]]:
    preparation_id = error.details.get("preparation_id")
    if not isinstance(preparation_id, str) or not preparation_id:
        return []
    candidates = [path for path in store.root.rglob(preparation_id) if path.is_dir()]
    if len(candidates) != 1:
        return []
    return [
        _file_evidence(path, output_root, stage="pdbqt_failure")
        for path in sorted(candidates[0].iterdir(), key=lambda item: item.name)
        if path.is_file()
    ]


def _record_artifacts(
    *,
    stage: str,
    content_path: Path,
    output_root: Path,
    include_logs: bool = False,
) -> list[dict[str, Any]]:
    paths = [content_path, content_path.parent / "record.json"]
    if include_logs:
        paths.extend(
            path
            for path in (content_path.parent / "stdout.log", content_path.parent / "stderr.log")
            if path.is_file()
        )
    return [
        _file_evidence(
            path,
            output_root,
            stage=stage if path == content_path else f"{stage}_evidence",
        )
        for path in paths
    ]


def _completion_manifest(
    *, plan: dict[str, Any], worker_count: int, entries: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = _required_int(_required_object(plan.get("totals"), "plan totals"), "all_parents")
    if len(entries) != expected:
        raise ScreeningBenchmarkLigandPreparationError(
            "Not every frozen parent has a terminal preparation outcome."
        )
    statuses = Counter(str(item.get("status")) for item in entries)
    unknown = set(statuses) - TERMINAL_STATUSES
    if unknown:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Unsupported terminal statuses: {sorted(unknown)}."
        )
    prepared = statuses["prepared"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": _required_string(plan, "protocol_id"),
        "created_at": datetime.now(UTC).isoformat(),
        "scores_seen": False,
        "source_ligand_preparation_plan_sha256": _required_sha256(plan, "manifest_sha256"),
        "tool_contract": _required_object(plan.get("tool_contract"), "tool contract"),
        "execution_policy": {
            "scope": "exact-state ETKDGv3/MMFF94s/Meeko ligand preparation",
            "worker_count": worker_count,
            "restartable_create_only_entry_attempts": True,
            "all_source_parents_retained": True,
            "failures_retained_as_unscored_worst_tie": True,
            "raw_evidence_retained_locally": True,
            "docking_executed": False,
            "scores_or_metrics_computed": False,
        },
        "preparation_census": {
            "requested": expected,
            "terminal": len(entries),
            "prepared": prepared,
            "unscored_worst_tie": expected - prepared,
            "by_status": dict(sorted(statuses.items())),
        },
        "entries": entries,
        "result_status": (
            "all_ligand_parents_terminal_preparation_failures_retained_"
            "no_docking_or_metrics_executed"
        ),
    }
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def _with_terminal_evidence(
    result: dict[str, Any], terminal_path: Path, output_root: Path
) -> dict[str, Any]:
    copied = dict(result)
    copied["terminal_evidence"] = _file_evidence(
        terminal_path, output_root, stage="terminal_record"
    )
    return copied


def _verify_task_identity(task: dict[str, Any], result: dict[str, Any]) -> None:
    expected = _base_public_result(task)
    if any(result.get(key) != value for key, value in expected.items()):
        raise ScreeningBenchmarkLigandPreparationError(
            f"Terminal evidence changed for parent {task['sequence']}."
        )
    _validate_public_result(result)


def _validate_public_result(result: dict[str, Any]) -> None:
    status = _required_string(result, "status")
    if status not in TERMINAL_STATUSES:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Unsupported terminal ligand status: {status}."
        )
    if (result.get("prepared") is True) != (status == "prepared"):
        raise ScreeningBenchmarkLigandPreparationError(
            "A terminal result contradicts its prepared flag."
        )
    if not isinstance(result.get("artifacts"), list):
        raise ScreeningBenchmarkLigandPreparationError(
            "A terminal result must list retained artifacts."
        )


def _verify_evidence_item(evidence: dict[str, Any], evidence_root: Path | None) -> None:
    relative = _required_string(evidence, "path")
    _safe_relative_path(relative)
    size = _required_int(evidence, "size_bytes")
    digest = _required_sha256(evidence, "sha256")
    if evidence_root is None:
        return
    path = _safe_evidence_path(evidence_root, relative, require_file=True)
    if path.stat().st_size != size:
        raise ScreeningBenchmarkLigandPreparationError(f"Ligand evidence size changed: {relative}.")
    if _file_sha256(path) != digest:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Ligand evidence SHA-256 changed: {relative}."
        )


def _file_evidence(path: Path, output_root: Path, *, stage: str) -> dict[str, Any]:
    resolved_root = output_root.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents or not resolved.is_file():
        raise ScreeningBenchmarkLigandPreparationError(
            "Ligand evidence resolves outside the run root or is missing."
        )
    return {
        "stage": stage,
        "path": resolved.relative_to(resolved_root).as_posix(),
        "size_bytes": resolved.stat().st_size,
        "sha256": _file_sha256(resolved),
    }


def _next_attempt_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    numbers: list[int] = []
    for candidate in root.glob("attempt-*"):
        try:
            numbers.append(int(candidate.name.removeprefix("attempt-")))
        except ValueError:
            continue
    return root / f"attempt-{max(numbers, default=0) + 1:03d}"


def _parallel_worker_count(task_count: int, worker_limit: int | None) -> int:
    available = max(1, (os.cpu_count() or 2) - 1)
    if worker_limit is not None:
        if worker_limit < 1:
            raise ScreeningBenchmarkLigandPreparationError(
                "The ligand-preparation worker limit must be at least one."
            )
        available = min(available, worker_limit)
    return max(1, min(task_count, available))


def _slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    normalized = "-".join(part for part in slug.split("-") if part)
    if not normalized:
        raise ScreeningBenchmarkLigandPreparationError("Target identifier is empty.")
    return normalized[:48]


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\\" in value or ":" in value:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Manifest contains an unsafe path: {value}."
        )
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ScreeningBenchmarkLigandPreparationError(
            f"Manifest contains an unsafe path: {value}."
        )
    return path


def _safe_evidence_path(root: Path, relative_value: str, *, require_file: bool) -> Path:
    relative = _safe_relative_path(relative_value)
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if resolved_root not in path.parents:
        raise ScreeningBenchmarkLigandPreparationError(
            f"Evidence path escapes the run root: {relative_value}."
        )
    if require_file and not path.is_file():
        raise ScreeningBenchmarkLigandPreparationError(
            f"Ligand evidence is unavailable: {relative_value}."
        )
    if not require_file and not path.is_dir():
        raise ScreeningBenchmarkLigandPreparationError(
            f"Ligand evidence directory is unavailable: {relative_value}."
        )
    return path


def _write_create_only(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as destination:
        destination.write(content)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkLigandPreparationError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkLigandPreparationError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkLigandPreparationError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkLigandPreparationError(f"{key} must be a non-empty string.")
    return raw


def _required_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkLigandPreparationError(f"{key} must be a non-negative integer.")
    return raw


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    raw = _required_int(value, key)
    if raw < 1:
        raise ScreeningBenchmarkLigandPreparationError(f"{key} must be positive.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkLigandPreparationError(f"{key} must be a SHA-256.")
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
