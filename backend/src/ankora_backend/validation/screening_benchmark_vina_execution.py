"""Execute and verify the frozen primary Vina benchmark campaign.

The executor consumes the path-free campaign plan literally.  Every source
parent receives one terminal public outcome, every scientific-tool attempt is
create-only, and the completion manifest is withheld until the full census
closes.  This module computes no enrichment metric.
"""

from __future__ import annotations

import hashlib
import json
import threading
import traceback
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ankora_backend.adapters.engines.vina import (
    VinaInstallation,
    build_vina_arguments,
    execute_vina,
    parse_vina_poses,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import VinaDockingParameters, VinaSamplingProtocol
from ankora_backend.validation.screening_benchmark_vina_plan import (
    verify_vina_campaign_plan,
)

SCHEMA_VERSION = 1
TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "preparation_unscored",
        "docking_failed",
        "output_invalid",
        "internal_failed",
    }
)


class ScreeningBenchmarkVinaExecutionError(ValueError):
    """Frozen Vina execution evidence is incomplete, changed, or unsafe."""


ProgressCallback = Callable[[int, int, str], None]
VinaEntryExecutor = Callable[
    [
        VinaInstallation,
        Path,
        Path,
        Path,
        BindingBox,
        VinaDockingParameters,
        threading.Event,
    ],
    CancellableToolExecution,
]


def run_screening_benchmark_vina_campaign(
    *,
    plan_manifest_path: Path,
    final_receptor_evidence_root: Path,
    ligand_preparation_evidence_root: Path,
    parser_source_path: Path,
    installation: VinaInstallation,
    output_root: Path,
    public_manifest_path: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    _entry_executor: VinaEntryExecutor | None = None,
) -> dict[str, Any]:
    """Execute or resume every exact entry in the frozen primary campaign."""

    executable = Path(installation.executable)
    plan = verify_vina_campaign_plan(
        plan_manifest_path,
        parser_source_path=parser_source_path,
        vina_executable_path=executable,
        final_receptor_evidence_root=final_receptor_evidence_root,
        ligand_preparation_evidence_root=ligand_preparation_evidence_root,
    )
    _verify_installation(plan, installation, executable)
    local_manifest = output_root / "manifest.json"
    if local_manifest.is_file():
        manifest = verify_vina_campaign_manifest(
            local_manifest,
            evidence_root=output_root,
            plan_manifest_path=plan_manifest_path,
        )
        if public_manifest_path.exists():
            if public_manifest_path.read_bytes() != local_manifest.read_bytes():
                raise ScreeningBenchmarkVinaExecutionError(
                    "The public and local Vina campaign manifests differ."
                )
        else:
            _write_create_only(public_manifest_path, local_manifest.read_bytes())
        return manifest
    if public_manifest_path.exists():
        raise ScreeningBenchmarkVinaExecutionError(
            "A public Vina campaign manifest exists without its local evidence."
        )

    _initialize_or_verify_run(output_root, plan)
    tasks = _campaign_tasks(
        plan,
        final_receptor_evidence_root=final_receptor_evidence_root,
        ligand_preparation_evidence_root=ligand_preparation_evidence_root,
    )
    parameters = _execution_parameters(plan)
    plan_parameters = _required_object(plan.get("parameters"), "plan parameters")
    worker_count = _required_positive_int(plan_parameters, "parallel_ligands")
    total = len(tasks)
    stop = cancel_event or threading.Event()
    executor = _entry_executor or _execute_vina_entry

    results: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    completed = 0
    for task in tasks:
        terminal = _existing_terminal(task, output_root)
        if terminal is None:
            pending.append(task)
            continue
        results.append(terminal)
        completed += 1
        if progress_callback is not None:
            progress_callback(completed, total, str(terminal["status"]))

    try:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="ankora-benchmark-vina",
        ) as pool:
            futures = {
                pool.submit(
                    _execute_attempt,
                    task=task,
                    installation=installation,
                    parameters=parameters,
                    output_root=output_root,
                    cancel_event=stop,
                    executor=executor,
                ): task
                for task in pending
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total, str(result["status"]))
    except BaseException:
        stop.set()
        raise

    results.sort(key=lambda item: int(item["sequence"]))
    manifest = _completion_manifest(plan=plan, entries=results)
    serialized = _serialized(manifest)
    _write_create_only(local_manifest, serialized)
    _write_create_only(public_manifest_path, serialized)
    return verify_vina_campaign_manifest(
        public_manifest_path,
        evidence_root=output_root,
        plan_manifest_path=plan_manifest_path,
    )


def verify_vina_campaign_manifest(
    path: Path,
    *,
    evidence_root: Path | None = None,
    plan_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Verify closure, exact identities, parsed poses, failures, and evidence."""

    manifest = _load_object(path, "Vina campaign manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkVinaExecutionError(
            "Unsupported Vina campaign manifest schema."
        )
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkVinaExecutionError(
            "The Vina campaign manifest differs from its SHA-256."
        )
    policy = _required_object(manifest.get("execution_policy"), "execution policy")
    if (
        policy.get("all_source_parents_retained") is not True
        or policy.get("failures_retained_as_unscored_worst_tie") is not True
        or policy.get("restartable_create_only_entry_attempts") is not True
        or policy.get("terminal_entries_persisted_incrementally") is not True
        or policy.get("raw_evidence_retained_locally") is not True
        or policy.get("scores_read_from_strict_pdbqt_parser") is not True
        or policy.get("metrics_computed") is not False
    ):
        raise ScreeningBenchmarkVinaExecutionError(
            "The loss-preserving Vina execution boundary changed."
        )

    expected_entries: list[dict[str, Any]] | None = None
    if plan_manifest_path is not None:
        plan = verify_vina_campaign_plan(plan_manifest_path)
        if manifest.get("source_vina_campaign_plan_sha256") != plan.get(
            "manifest_sha256"
        ):
            raise ScreeningBenchmarkVinaExecutionError(
                "The results name a different frozen Vina campaign plan."
            )
        expected_entries = [
            _required_object(entry, "planned entry")
            for target_raw in _required_list(plan, "targets")
            for entry in _required_list(_required_object(target_raw, "target"), "entries")
        ]

    entries = _required_list(manifest, "entries")
    census = _required_object(manifest.get("campaign_census"), "campaign census")
    if _required_positive_int(census, "requested") != len(entries) or _required_positive_int(
        census, "terminal"
    ) != len(entries):
        raise ScreeningBenchmarkVinaExecutionError(
            "The terminal Vina campaign census does not close."
        )
    if expected_entries is not None and len(expected_entries) != len(entries):
        raise ScreeningBenchmarkVinaExecutionError(
            "The result census differs from the frozen Vina plan."
        )

    statuses: Counter[str] = Counter()
    target_statuses: dict[str, Counter[str]] = {}
    scored = 0
    for index, raw_entry in enumerate(entries):
        entry = _required_object(raw_entry, "terminal Vina entry")
        if _required_positive_int(entry, "sequence") != index + 1:
            raise ScreeningBenchmarkVinaExecutionError(
                "Terminal Vina outcomes must remain source ordered."
            )
        target_id = _required_string(entry, "target_id")
        status = _required_string(entry, "status")
        if status not in TERMINAL_STATUSES:
            raise ScreeningBenchmarkVinaExecutionError(
                f"Unsupported terminal Vina status: {status}."
            )
        statuses[status] += 1
        target_statuses.setdefault(target_id, Counter())[status] += 1
        _validate_public_result(entry)
        _verify_evidence_item(
            _required_object(entry.get("terminal_evidence"), "terminal evidence"),
            evidence_root,
        )
        for evidence_raw in _required_list(entry, "artifacts"):
            _verify_evidence_item(
                _required_object(evidence_raw, "Vina artifact evidence"), evidence_root
            )
        if status == "completed":
            scored += 1
        if expected_entries is not None:
            _verify_planned_identity(expected_entries[index], entry)

    recorded_statuses = _required_object(census.get("by_status"), "status census")
    if dict(sorted(statuses.items())) != {
        key: _required_nonnegative_int(recorded_statuses, key)
        for key in sorted(recorded_statuses)
    }:
        raise ScreeningBenchmarkVinaExecutionError(
            "The Vina status census differs from terminal rows."
        )
    unscored = len(entries) - scored
    if (
        census.get("scored") != scored
        or census.get("unscored_worst_tie") != unscored
    ):
        raise ScreeningBenchmarkVinaExecutionError(
            "The scored/unscored campaign census differs from terminal rows."
        )
    recorded_targets = _required_list(manifest, "target_census")
    observed_targets = [
        {
            "target_id": target_id,
            "requested": sum(counts.values()),
            "scored": counts["completed"],
            "unscored_worst_tie": sum(counts.values()) - counts["completed"],
            "by_status": dict(sorted(counts.items())),
        }
        for target_id, counts in target_statuses.items()
    ]
    if recorded_targets != observed_targets:
        raise ScreeningBenchmarkVinaExecutionError(
            "The per-target Vina census differs from terminal rows."
        )
    if manifest.get("scores_seen") is not (scored > 0):
        raise ScreeningBenchmarkVinaExecutionError(
            "The score-visibility boundary contradicts terminal results."
        )
    if manifest.get("result_status") != (
        "all_primary_vina_entries_terminal_failures_retained_metrics_not_computed"
    ):
        raise ScreeningBenchmarkVinaExecutionError(
            "The primary Vina completion boundary changed."
        )
    return manifest


def _verify_installation(
    plan: dict[str, Any], installation: VinaInstallation, executable: Path
) -> None:
    engine = _required_object(plan.get("engine"), "engine")
    if installation.version != _required_string(engine, "version"):
        raise ScreeningBenchmarkVinaExecutionError("The Vina version changed.")
    if executable.name != _required_string(engine, "executable_filename"):
        raise ScreeningBenchmarkVinaExecutionError(
            "The Vina executable filename changed."
        )
    if executable.stat().st_size != _required_positive_int(
        engine, "executable_size_bytes"
    ) or _file_sha256(executable) != _required_sha256(engine, "executable_sha256"):
        raise ScreeningBenchmarkVinaExecutionError(
            "The Vina executable bytes changed."
        )


def _initialize_or_verify_run(output_root: Path, plan: dict[str, Any]) -> None:
    run_path = output_root / "run.json"
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": _required_string(plan, "protocol_id"),
        "source_vina_campaign_plan_sha256": _required_sha256(
            plan, "manifest_sha256"
        ),
        "scores_or_metrics_computed": False,
    }
    if run_path.is_file():
        if _load_object(run_path, "Vina campaign run") != expected:
            raise ScreeningBenchmarkVinaExecutionError(
                "The existing Vina run belongs to a different frozen plan."
            )
        return
    output_root.mkdir(parents=True, exist_ok=True)
    _write_create_only(run_path, _serialized(expected))


def _campaign_tasks(
    plan: dict[str, Any],
    *,
    final_receptor_evidence_root: Path,
    ligand_preparation_evidence_root: Path,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for target_raw in _required_list(plan, "targets"):
        target = _required_object(target_raw, "target")
        receptor = _required_object(target.get("receptor"), "receptor")
        receptor_identity = _required_object(receptor.get("pdbqt"), "receptor PDBQT")
        receptor_path = _safe_evidence_path(
            final_receptor_evidence_root,
            _required_string(receptor_identity, "path"),
            require_file=True,
        )
        box = BindingBox.model_validate(
            _required_object(target.get("box_angstrom"), "binding box")
        )
        argument_template = _required_list(target, "argument_template")
        if not all(isinstance(item, str) for item in argument_template):
            raise ScreeningBenchmarkVinaExecutionError(
                "The Vina argument template must contain only strings."
            )
        for entry_raw in _required_list(target, "entries"):
            entry = _required_object(entry_raw, "planned entry")
            task: dict[str, Any] = {
                **entry,
                "target_id": _required_string(target, "target_id"),
                "receptor_path": receptor_path,
                "box": box,
                "argument_template": list(argument_template),
            }
            if entry.get("docking_disposition") == "ready":
                ligand = _required_object(entry.get("ligand_pdbqt"), "ligand PDBQT")
                task["ligand_path"] = _safe_evidence_path(
                    ligand_preparation_evidence_root,
                    _required_string(ligand, "path"),
                    require_file=True,
                )
            tasks.append(task)
    tasks.sort(key=lambda item: int(item["sequence"]))
    if [int(task["sequence"]) for task in tasks] != list(range(1, len(tasks) + 1)):
        raise ScreeningBenchmarkVinaExecutionError(
            "The frozen Vina tasks do not cover every source parent."
        )
    return tasks


def _execution_parameters(plan: dict[str, Any]) -> VinaDockingParameters:
    value = _required_object(plan.get("parameters"), "plan parameters")
    return VinaDockingParameters(
        sampling_protocol=VinaSamplingProtocol(_required_string(value, "sampling_protocol")),
        cpu_threads=_required_positive_int(value, "threads_per_ligand"),
        seed=_required_positive_int(value, "seed"),
        exhaustiveness=_required_positive_int(value, "exhaustiveness"),
        num_modes=_required_positive_int(value, "num_modes"),
        min_rmsd_angstrom=_required_number(value, "min_rmsd_angstrom"),
        energy_range_kcal_mol=_required_number(value, "energy_range_kcal_mol"),
        timeout_minutes=_required_positive_int(value, "timeout_minutes_per_ligand"),
    )


def _existing_terminal(task: dict[str, Any], output_root: Path) -> dict[str, Any] | None:
    entry_root = output_root / "entries" / f"{int(task['sequence']):05d}"
    terminals = sorted(entry_root.glob("attempt-*/terminal.json"))
    if len(terminals) > 1:
        raise ScreeningBenchmarkVinaExecutionError(
            f"Vina entry {task['sequence']} has more than one terminal attempt."
        )
    if not terminals:
        return None
    terminal = _load_object(terminals[0], "terminal Vina attempt")
    result = _required_object(terminal.get("public_result"), "public terminal result")
    _verify_task_identity(task, result)
    return _with_terminal_evidence(result, terminals[0], output_root)


def _execute_attempt(
    *,
    task: dict[str, Any],
    installation: VinaInstallation,
    parameters: VinaDockingParameters,
    output_root: Path,
    cancel_event: threading.Event,
    executor: VinaEntryExecutor,
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
        "canonical_isomeric_smiles_sha256": task[
            "canonical_isomeric_smiles_sha256"
        ],
        "started_at": datetime.now(UTC).isoformat(),
    }
    _write_create_only(attempt_root / "started.json", _serialized(started))
    public_result = _base_public_result(task)
    local_execution: dict[str, Any] | None = None
    local_error: dict[str, Any] | None = None

    if task.get("docking_disposition") == "retained_unscored_worst_tie":
        public_result.update(
            {
                "status": "preparation_unscored",
                "best_affinity_kcal_mol": None,
                "poses": [],
                "error": _required_object(
                    task.get("preparation_failure"), "preparation failure"
                ),
                "artifacts": [],
            }
        )
    else:
        output_path = attempt_root / "vina_poses.pdbqt"
        stdout_path = attempt_root / "stdout.log"
        stderr_path = attempt_root / "stderr.log"
        try:
            if cancel_event.is_set():
                raise KeyboardInterrupt
            receptor_path = _required_path(task, "receptor_path")
            ligand_path = _required_path(task, "ligand_path")
            box = task.get("box")
            if not isinstance(box, BindingBox):
                raise ScreeningBenchmarkVinaExecutionError(
                    "A Vina task lacks its binding box."
                )
            expected_arguments = build_vina_arguments(
                receptor_path=receptor_path,
                ligand_path=ligand_path,
                output_path=output_path,
                box=box,
                parameters=parameters,
            )
            _verify_argument_template(
                _required_list(task, "argument_template"), expected_arguments
            )
            execution = executor(
                installation,
                receptor_path,
                ligand_path,
                output_path,
                box,
                parameters,
                cancel_event,
            )
            _write_create_only(stdout_path, execution.stdout.encode("utf-8"))
            _write_create_only(stderr_path, execution.stderr.encode("utf-8"))
            expected_command = [installation.executable, *expected_arguments]
            if execution.command != expected_command:
                raise ScreeningBenchmarkVinaExecutionError(
                    "Vina executed a command different from the frozen template."
                )
            local_execution = {
                "command": execution.command,
                "exit_code": execution.exit_code,
                "timed_out": execution.timed_out,
                "canceled": execution.canceled,
            }
            artifacts = [
                _file_evidence(stdout_path, output_root, stage="vina_stdout"),
                _file_evidence(stderr_path, output_root, stage="vina_stderr"),
            ]
            if execution.canceled:
                raise KeyboardInterrupt
            if execution.timed_out:
                public_result.update(
                    _failure_result(
                        "docking_failed",
                        "VINA_TIMEOUT",
                        "vina_docking",
                        "AutoDock Vina exceeded the frozen per-ligand timeout.",
                        artifacts,
                    )
                )
            elif execution.exit_code != 0:
                public_result.update(
                    _failure_result(
                        "docking_failed",
                        "VINA_EXECUTION_FAILED",
                        "vina_docking",
                        "AutoDock Vina returned a non-zero exit code.",
                        artifacts,
                    )
                )
            elif not output_path.is_file():
                public_result.update(
                    _failure_result(
                        "docking_failed",
                        "VINA_OUTPUT_MISSING",
                        "vina_docking",
                        "AutoDock Vina completed without a pose file.",
                        artifacts,
                    )
                )
            else:
                output_content = output_path.read_bytes()
                artifacts.insert(
                    0, _file_evidence(output_path, output_root, stage="vina_pose_output")
                )
                poses = parse_vina_poses(output_content)
                public_result.update(
                    {
                        "status": "completed",
                        "best_affinity_kcal_mol": min(
                            pose.affinity_kcal_mol for pose in poses
                        ),
                        "poses": [
                            {
                                "mode": pose.mode,
                                "affinity_kcal_mol": pose.affinity_kcal_mol,
                                "rmsd_lower_bound_angstrom": (
                                    pose.rmsd_lower_bound_angstrom
                                ),
                                "rmsd_upper_bound_angstrom": (
                                    pose.rmsd_upper_bound_angstrom
                                ),
                                "sha256": hashlib.sha256(pose.content).hexdigest(),
                                "size_bytes": len(pose.content),
                            }
                            for pose in poses
                        ],
                        "error": None,
                        "artifacts": artifacts,
                    }
                )
        except KeyboardInterrupt:
            cancel_event.set()
            interrupted = {
                "interrupted_at": datetime.now(UTC).isoformat(),
                "local_execution": local_execution,
                "reason": "execution_interrupted_before_terminal_evidence",
            }
            _write_create_only(
                attempt_root / "interrupted.json", _serialized(interrupted)
            )
            raise
        except AnkoraDomainError as error:
            public_result.update(
                _failure_result(
                    "output_invalid" if error.stage == "vina_pose_parsing" else "docking_failed",
                    error.code,
                    error.stage,
                    error.message,
                    _existing_attempt_artifacts(attempt_root, output_root),
                )
            )
            local_error = {
                "kind": "AnkoraDomainError",
                "code": error.code,
                "stage": error.stage,
                "message": error.message,
                "details": error.details,
                "traceback": traceback.format_exc(),
            }
        except ScreeningBenchmarkVinaExecutionError:
            raise
        except Exception as error:
            public_result.update(
                _failure_result(
                    "internal_failed",
                    "BENCHMARK_VINA_UNEXPECTED",
                    "benchmark_vina_execution",
                    "An unexpected Vina execution failure was retained.",
                    _existing_attempt_artifacts(attempt_root, output_root),
                )
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
        "local_execution": local_execution,
        "local_error": local_error,
    }
    terminal_path = attempt_root / "terminal.json"
    _write_create_only(terminal_path, _serialized(terminal))
    return _with_terminal_evidence(public_result, terminal_path, output_root)


def _execute_vina_entry(
    installation: VinaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: VinaDockingParameters,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    return execute_vina(
        installation=installation,
        receptor_path=receptor_path,
        ligand_path=ligand_path,
        output_path=output_path,
        box=box,
        parameters=parameters,
        cancel_event=cancel_event,
    )


def _verify_argument_template(template: list[Any], arguments: list[str]) -> None:
    expected = list(arguments)
    for index, value in enumerate(expected):
        if value.endswith("vina_poses.pdbqt"):
            expected[index] = "<entry_output_pdbqt>"
        elif index > 0 and expected[index - 1] == "--receptor":
            expected[index] = "<target_receptor_pdbqt>"
        elif index > 0 and expected[index - 1] == "--ligand":
            expected[index] = "<entry_ligand_pdbqt>"
    if template != expected:
        raise ScreeningBenchmarkVinaExecutionError(
            "Resolved Vina arguments differ from the frozen template."
        )


def _failure_result(
    status: str, code: str, stage: str, message: str, artifacts: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "status": status,
        "best_affinity_kcal_mol": None,
        "poses": [],
        "error": {"code": code, "stage": stage, "message": message},
        "artifacts": artifacts,
    }


def _existing_attempt_artifacts(
    attempt_root: Path, output_root: Path
) -> list[dict[str, Any]]:
    stages = {
        "vina_poses.pdbqt": "vina_pose_output",
        "stdout.log": "vina_stdout",
        "stderr.log": "vina_stderr",
    }
    return [
        _file_evidence(path, output_root, stage=stages[path.name])
        for path in sorted(attempt_root.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name in stages
    ]


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
            "preparation_status",
            "docking_disposition",
        )
    }


def _validate_public_result(result: dict[str, Any]) -> None:
    status = _required_string(result, "status")
    if status not in TERMINAL_STATUSES:
        raise ScreeningBenchmarkVinaExecutionError(
            f"Unsupported terminal Vina status: {status}."
        )
    poses = _required_list(result, "poses")
    artifacts = _required_list(result, "artifacts")
    if status == "completed":
        best = _required_number(result, "best_affinity_kcal_mol")
        if result.get("error") is not None or not poses:
            raise ScreeningBenchmarkVinaExecutionError(
                "A completed Vina entry lacks parsed poses or records an error."
            )
        modes: list[int] = []
        affinities: list[float] = []
        for pose_raw in poses:
            pose = _required_object(pose_raw, "Vina pose")
            modes.append(_required_positive_int(pose, "mode"))
            affinities.append(_required_number(pose, "affinity_kcal_mol"))
            _required_nonnegative_number(pose, "rmsd_lower_bound_angstrom")
            _required_nonnegative_number(pose, "rmsd_upper_bound_angstrom")
            _required_sha256(pose, "sha256")
            _required_positive_int(pose, "size_bytes")
        if modes != list(range(1, len(modes) + 1)) or min(affinities) != best:
            raise ScreeningBenchmarkVinaExecutionError(
                "Parsed Vina poses are not sequential or disagree with the best score."
            )
        stages = {
            _required_string(_required_object(item, "artifact"), "stage")
            for item in artifacts
        }
        if not {"vina_pose_output", "vina_stdout", "vina_stderr"}.issubset(stages):
            raise ScreeningBenchmarkVinaExecutionError(
                "A completed Vina entry lacks raw output or logs."
            )
    else:
        if result.get("best_affinity_kcal_mol") is not None or poses:
            raise ScreeningBenchmarkVinaExecutionError(
                "An unscored Vina entry unexpectedly records poses or a score."
            )
        error = _required_object(result.get("error"), "Vina terminal error")
        _required_string(error, "code")
        _required_string(error, "stage")


def _verify_task_identity(task: dict[str, Any], result: dict[str, Any]) -> None:
    expected = _base_public_result(task)
    if any(result.get(key) != value for key, value in expected.items()):
        raise ScreeningBenchmarkVinaExecutionError(
            f"Terminal evidence changed for Vina entry {task['sequence']}."
        )
    _validate_public_result(result)


def _verify_planned_identity(planned: dict[str, Any], result: dict[str, Any]) -> None:
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
        "preparation_status",
        "docking_disposition",
    ):
        if result.get(key) != planned.get(key):
            raise ScreeningBenchmarkVinaExecutionError(
                f"Terminal Vina identity changed at sequence {result.get('sequence')}: {key}."
            )


def _completion_manifest(
    *, plan: dict[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = _required_positive_int(
        _required_object(plan.get("totals"), "plan totals"), "source_parents"
    )
    if len(entries) != expected:
        raise ScreeningBenchmarkVinaExecutionError(
            "Not every frozen parent has a terminal Vina outcome."
        )
    statuses = Counter(str(item.get("status")) for item in entries)
    unknown = set(statuses) - TERMINAL_STATUSES
    if unknown:
        raise ScreeningBenchmarkVinaExecutionError(
            f"Unsupported terminal Vina statuses: {sorted(unknown)}."
        )
    target_statuses: dict[str, Counter[str]] = {}
    for entry in entries:
        target_statuses.setdefault(str(entry["target_id"]), Counter())[str(entry["status"])] += 1
    scored = statuses["completed"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": _required_string(plan, "protocol_id"),
        "created_at": datetime.now(UTC).isoformat(),
        "scores_seen": scored > 0,
        "source_vina_campaign_plan_sha256": _required_sha256(
            plan, "manifest_sha256"
        ),
        "engine": _required_object(plan.get("engine"), "engine"),
        "parameters": _required_object(plan.get("parameters"), "parameters"),
        "execution_policy": {
            "worker_count": _required_positive_int(
                _required_object(plan.get("parameters"), "parameters"),
                "parallel_ligands",
            ),
            "all_source_parents_retained": True,
            "failures_retained_as_unscored_worst_tie": True,
            "restartable_create_only_entry_attempts": True,
            "terminal_entries_persisted_incrementally": True,
            "raw_evidence_retained_locally": True,
            "scores_read_from_strict_pdbqt_parser": True,
            "metrics_computed": False,
        },
        "campaign_census": {
            "requested": expected,
            "terminal": len(entries),
            "scored": scored,
            "unscored_worst_tie": expected - scored,
            "by_status": dict(sorted(statuses.items())),
        },
        "target_census": [
            {
                "target_id": target_id,
                "requested": sum(counts.values()),
                "scored": counts["completed"],
                "unscored_worst_tie": sum(counts.values()) - counts["completed"],
                "by_status": dict(sorted(counts.items())),
            }
            for target_id, counts in target_statuses.items()
        ],
        "entries": entries,
        "result_status": (
            "all_primary_vina_entries_terminal_failures_retained_metrics_not_computed"
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


def _verify_evidence_item(evidence: dict[str, Any], evidence_root: Path | None) -> None:
    relative = _required_string(evidence, "path")
    _safe_relative_path(relative)
    size = _required_nonnegative_int(evidence, "size_bytes")
    digest = _required_sha256(evidence, "sha256")
    if evidence_root is None:
        return
    path = _safe_evidence_path(evidence_root, relative, require_file=True)
    if path.stat().st_size != size or _file_sha256(path) != digest:
        raise ScreeningBenchmarkVinaExecutionError(
            f"Vina evidence changed: {relative}."
        )


def _file_evidence(path: Path, output_root: Path, *, stage: str) -> dict[str, Any]:
    resolved_root = output_root.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents or not resolved.is_file():
        raise ScreeningBenchmarkVinaExecutionError(
            "Vina evidence resolves outside the run root or is missing."
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


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise ScreeningBenchmarkVinaExecutionError("Vina evidence has an unsafe path.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ScreeningBenchmarkVinaExecutionError("Vina evidence has an unsafe path.")
    return path


def _safe_evidence_path(root: Path, relative_value: str, *, require_file: bool) -> Path:
    relative = _safe_relative_path(relative_value)
    resolved_root = root.resolve()
    resolved = (root / Path(*relative.parts)).resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ScreeningBenchmarkVinaExecutionError("Vina evidence escapes its root.")
    if require_file and not resolved.is_file():
        raise ScreeningBenchmarkVinaExecutionError(
            f"Vina evidence is missing: {relative.as_posix()}."
        )
    return resolved


def _write_create_only(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkVinaExecutionError(f"Cannot read {label}.") from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkVinaExecutionError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be a list.")
    return item


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be a non-empty string.")
    return item


def _required_path(value: dict[str, Any], key: str) -> Path:
    item = value.get(key)
    if not isinstance(item, Path):
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be a resolved path.")
    return item


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 1:
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be a positive integer.")
    return item


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ScreeningBenchmarkVinaExecutionError(
            f"{key} must be a non-negative integer."
        )
    return item


def _required_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be numeric.")
    return float(item)


def _required_nonnegative_number(value: dict[str, Any], key: str) -> float:
    item = _required_number(value, key)
    if item < 0:
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be non-negative.")
    return item


def _required_sha256(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if (
        not isinstance(item, str)
        or len(item) != 64
        or any(character not in "0123456789abcdef" for character in item)
    ):
        raise ScreeningBenchmarkVinaExecutionError(f"{key} must be a lowercase SHA-256.")
    return item


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
