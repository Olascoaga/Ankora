"""Freeze an exact, path-free AutoDock Vina benchmark campaign plan.

The plan binds every benchmark parent to its primary receptor, co-crystal box,
and (when preparation succeeded) exact ligand PDBQT.  Building or verifying a
plan never launches docking, parses a score, or computes a metric.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from ankora_backend.adapters.engines.vina import (
    VinaInstallation,
    build_vina_arguments,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import (
    VinaBatchDockingParameters,
    VinaDockingParameters,
    VinaSamplingProtocol,
)

SCHEMA_VERSION = 1
REQUIRED_VINA_VERSION = "1.2.7"
TIMEOUT_MINUTES_PER_LIGAND = 360
PARSER_SOURCE_REPOSITORY_PATH = (
    "backend/src/ankora_backend/adapters/engines/vina.py"
)


class ScreeningBenchmarkVinaPlanError(ValueError):
    """The supplied evidence cannot satisfy the frozen Vina contract."""


def build_vina_campaign_plan(
    *,
    spec_path: Path,
    geometry_manifest_path: Path,
    final_receptor_manifest_path: Path,
    ligand_preparation_manifest_path: Path,
    final_receptor_evidence_root: Path,
    ligand_preparation_evidence_root: Path,
    installation: VinaInstallation,
    vina_executable_path: Path,
    parser_source_path: Path,
    total_cpu_threads: int,
    parallel_ligands: int,
) -> dict[str, Any]:
    """Build the exact primary Vina campaign plan from verified evidence."""

    spec = _load_manifest(spec_path, "benchmark specification")
    geometry = _load_manifest(geometry_manifest_path, "geometry manifest")
    receptors = _load_manifest(final_receptor_manifest_path, "receptor manifest")
    ligands = _load_manifest(
        ligand_preparation_manifest_path, "ligand-preparation manifest"
    )
    for manifest, label in (
        (geometry, "geometry manifest"),
        (receptors, "receptor manifest"),
        (ligands, "ligand-preparation manifest"),
    ):
        _verify_manifest_identity(manifest, label)

    protocol_id = _required_string(spec, "protocol_id")
    for manifest, label in (
        (geometry, "geometry manifest"),
        (receptors, "receptor manifest"),
        (ligands, "ligand-preparation manifest"),
    ):
        if manifest.get("protocol_id") != protocol_id:
            raise ScreeningBenchmarkVinaPlanError(
                f"The {label} belongs to a different protocol."
            )

    primary_run = _required_object(spec.get("primary_run"), "primary run")
    parameters = _parameters_from_spec(
        primary_run,
        total_cpu_threads=total_cpu_threads,
        parallel_ligands=parallel_ligands,
    )
    threads_per_ligand = max(
        1, parameters.total_cpu_threads // parameters.parallel_ligands
    )
    if installation.version != REQUIRED_VINA_VERSION:
        raise ScreeningBenchmarkVinaPlanError(
            f"Vina {REQUIRED_VINA_VERSION} is required for the frozen campaign."
        )
    if Path(installation.executable).resolve() != vina_executable_path.resolve():
        raise ScreeningBenchmarkVinaPlanError(
            "The probed Vina executable differs from the executable being hashed."
        )
    _require_regular_file(vina_executable_path, "Vina executable")
    _require_regular_file(parser_source_path, "Vina parser source")

    geometry_by_target = _unique_by(
        _required_list(geometry, "targets"), "target_id", "geometry target"
    )
    receptor_by_target = _primary_receptors(receptors)
    ligand_entries = _required_list(ligands, "entries")
    entries_by_target: dict[str, list[dict[str, Any]]] = {}
    for raw_entry in ligand_entries:
        entry = _required_object(raw_entry, "ligand-preparation entry")
        entries_by_target.setdefault(_required_string(entry, "target_id"), []).append(
            entry
        )

    targets: list[dict[str, Any]] = []
    global_sequences: list[int] = []
    class_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for campaign_sequence, raw_geometry in enumerate(
        _required_list(geometry, "targets"), start=1
    ):
        target_geometry = _required_object(raw_geometry, "geometry target")
        target_id = _required_string(target_geometry, "target_id")
        receptor = receptor_by_target.get(target_id)
        if receptor is None:
            raise ScreeningBenchmarkVinaPlanError(
                f"No completed primary receptor exists for {target_id}."
            )
        receptor_output = _one_stage(
            _required_list(receptor, "outputs"), "pdbqt", "receptor output"
        )
        receptor_identity = _artifact_identity(receptor_output)
        _verify_evidence_file(
            final_receptor_evidence_root,
            receptor_identity,
            f"{target_id} receptor PDBQT",
        )

        co_crystal = _required_object(
            target_geometry.get("co_crystal_box"), "co-crystal box"
        )
        box = _binding_box(
            _required_object(
                co_crystal.get("primary_box_angstrom"), "primary box"
            )
        )
        target_entries: list[dict[str, Any]] = []
        target_statuses: Counter[str] = Counter()
        target_classes: Counter[str] = Counter()
        for entry in entries_by_target.get(target_id, []):
            sequence = _required_positive_int(entry, "sequence")
            global_sequences.append(sequence)
            class_label = _required_string(entry, "class_label")
            if class_label not in {"active", "inactive"}:
                raise ScreeningBenchmarkVinaPlanError(
                    f"Unsupported benchmark class {class_label!r}."
                )
            status = _required_string(entry, "status")
            class_counts[class_label] += 1
            status_counts[status] += 1
            target_classes[class_label] += 1
            target_statuses[status] += 1
            planned = _base_entry(entry)
            if entry.get("prepared") is True and status == "prepared":
                ligand_output = _one_stage(
                    _required_list(entry, "artifacts"),
                    "ligand_pdbqt",
                    "ligand output",
                )
                ligand_identity = _artifact_identity(ligand_output)
                pdbqt = _required_object(entry.get("pdbqt"), "ligand PDBQT")
                if (
                    ligand_identity["sha256"] != _required_sha256(pdbqt, "sha256")
                    or ligand_identity["size_bytes"]
                    != _required_positive_int(pdbqt, "size_bytes")
                ):
                    raise ScreeningBenchmarkVinaPlanError(
                        f"Ligand PDBQT identity disagrees for sequence {sequence}."
                    )
                _verify_evidence_file(
                    ligand_preparation_evidence_root,
                    ligand_identity,
                    f"ligand PDBQT sequence {sequence}",
                )
                planned.update(
                    {
                        "docking_disposition": "ready",
                        "ligand_pdbqt": ligand_identity,
                    }
                )
            else:
                error = _required_object(entry.get("error"), "preparation error")
                planned.update(
                    {
                        "docking_disposition": "retained_unscored_worst_tie",
                        "preparation_failure": {
                            "status": status,
                            "code": _required_string(error, "code"),
                            "stage": _required_string(error, "stage"),
                        },
                    }
                )
            target_entries.append(planned)

        target_sequences = [
            _required_positive_int(item, "target_sequence") for item in target_entries
        ]
        if target_sequences != list(range(1, len(target_entries) + 1)):
            raise ScreeningBenchmarkVinaPlanError(
                f"Ligand order is incomplete for {target_id}."
            )
        ready = sum(
            item["docking_disposition"] == "ready" for item in target_entries
        )
        targets.append(
            {
                "campaign_sequence": campaign_sequence,
                "target_id": target_id,
                "primary_template_id": _required_string(
                    target_geometry, "primary_template_id"
                ),
                "receptor": {
                    "final_receptor_id": _required_string(
                        receptor, "final_receptor_id"
                    ),
                    "pdb_id": _required_string(receptor, "pdb_id"),
                    "pdbqt": receptor_identity,
                },
                "box_angstrom": box.model_dump(),
                "argument_template": _argument_template(
                    box=box,
                    parameters=parameters,
                    threads_per_ligand=threads_per_ligand,
                ),
                "census": {
                    "source_parents": len(target_entries),
                    "prepared_for_docking": ready,
                    "retained_unscored_worst_tie": len(target_entries) - ready,
                    "by_class": dict(sorted(target_classes.items())),
                    "by_preparation_status": dict(sorted(target_statuses.items())),
                },
                "entries": target_entries,
            }
        )

    if sorted(global_sequences) != list(range(1, len(ligand_entries) + 1)):
        raise ScreeningBenchmarkVinaPlanError(
            "The campaign does not retain every ligand-preparation entry exactly once."
        )
    if set(entries_by_target) != set(geometry_by_target):
        raise ScreeningBenchmarkVinaPlanError(
            "Geometry and ligand-preparation target sets differ."
        )
    ready_total = sum(target["census"]["prepared_for_docking"] for target in targets)

    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "scores_seen": False,
        "dependencies": {
            "primary_run_sha256": _digest(primary_run),
            "geometry_manifest_sha256": _required_sha256(
                geometry, "manifest_sha256"
            ),
            "final_receptor_manifest_sha256": _required_sha256(
                receptors, "manifest_sha256"
            ),
            "ligand_preparation_manifest_sha256": _required_sha256(
                ligands, "manifest_sha256"
            ),
            "vina_parser": {
                "repository_path": PARSER_SOURCE_REPOSITORY_PATH,
                "size_bytes": parser_source_path.stat().st_size,
                "sha256": _file_sha256(parser_source_path),
            },
        },
        "engine": {
            "name": "AutoDock Vina",
            "version": installation.version,
            "executable_filename": vina_executable_path.name,
            "executable_size_bytes": vina_executable_path.stat().st_size,
            "executable_sha256": _file_sha256(vina_executable_path),
            "score_field": "affinity_kcal_mol",
            "score_direction": "lower_is_better",
        },
        "parameters": {
            **parameters.model_dump(mode="json"),
            "threads_per_ligand": threads_per_ligand,
        },
        "execution_policy": {
            "target_campaign_count": len(targets),
            "all_source_parents_retained": True,
            "failures_retained_as_unscored_worst_tie": True,
            "restartable_create_only_entry_attempts": True,
            "terminal_entries_persisted_incrementally": True,
            "raw_outputs_preserved": True,
            "stdout_not_used_for_scoring": True,
            "docking_executed": False,
            "scores_or_metrics_computed": False,
        },
        "parser_contract": {
            "pose_container": "sequential MODEL/ENDMDL records starting at one",
            "score_source": "one REMARK VINA RESULT record inside each MODEL",
            "content_outside_models": "forbidden_except_whitespace",
            "raw_output_bytes_retained": True,
        },
        "targets": targets,
        "totals": {
            "target_count": len(targets),
            "source_parents": len(ligand_entries),
            "prepared_for_docking": ready_total,
            "retained_unscored_worst_tie": len(ligand_entries) - ready_total,
            "by_class": dict(sorted(class_counts.items())),
            "by_preparation_status": dict(sorted(status_counts.items())),
        },
        "result_status": (
            "primary_vina_campaign_plan_frozen_no_docking_score_or_metric_executed"
        ),
    }
    plan["manifest_sha256"] = _digest(plan)
    _verify_plan_contract(plan)
    return plan


def verify_vina_campaign_plan(
    path: Path,
    *,
    spec_path: Path | None = None,
    geometry_manifest_path: Path | None = None,
    final_receptor_manifest_path: Path | None = None,
    ligand_preparation_manifest_path: Path | None = None,
    parser_source_path: Path | None = None,
    vina_executable_path: Path | None = None,
    final_receptor_evidence_root: Path | None = None,
    ligand_preparation_evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Verify plan identity and optionally rehash exact executable/evidence bytes."""

    manifest = _load_object(path, "Vina campaign plan")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkVinaPlanError("Unsupported Vina plan schema.")
    _verify_manifest_identity(manifest, "Vina campaign plan")
    _verify_plan_contract(manifest)

    dependencies = _required_object(manifest.get("dependencies"), "dependencies")
    if spec_path is not None:
        spec = _load_object(spec_path, "benchmark specification")
        if spec.get("protocol_id") != manifest.get("protocol_id"):
            raise ScreeningBenchmarkVinaPlanError(
                "The benchmark specification belongs to a different protocol."
            )
        primary_run = _required_object(spec.get("primary_run"), "primary run")
        if _digest(primary_run) != _required_sha256(
            dependencies, "primary_run_sha256"
        ):
            raise ScreeningBenchmarkVinaPlanError(
                "The primary run differs from the frozen Vina plan."
            )
    dependency_paths = (
        (
            geometry_manifest_path,
            "geometry_manifest_sha256",
            "geometry manifest",
        ),
        (
            final_receptor_manifest_path,
            "final_receptor_manifest_sha256",
            "final receptor manifest",
        ),
        (
            ligand_preparation_manifest_path,
            "ligand_preparation_manifest_sha256",
            "ligand-preparation manifest",
        ),
    )
    for dependency_path, dependency_key, label in dependency_paths:
        if dependency_path is None:
            continue
        dependency = _load_manifest(dependency_path, label)
        _verify_manifest_identity(dependency, label)
        if _required_sha256(dependency, "manifest_sha256") != _required_sha256(
            dependencies, dependency_key
        ):
            raise ScreeningBenchmarkVinaPlanError(
                f"The {label} differs from the frozen Vina plan."
            )
    parser = _required_object(dependencies.get("vina_parser"), "Vina parser")
    if parser_source_path is not None:
        _verify_direct_file(parser_source_path, parser, "Vina parser source")
    engine = _required_object(manifest.get("engine"), "engine")
    if vina_executable_path is not None:
        executable = {
            "size_bytes": _required_positive_int(engine, "executable_size_bytes"),
            "sha256": _required_sha256(engine, "executable_sha256"),
        }
        _verify_direct_file(vina_executable_path, executable, "Vina executable")

    for target_raw in _required_list(manifest, "targets"):
        target = _required_object(target_raw, "target")
        target_id = _required_string(target, "target_id")
        if final_receptor_evidence_root is not None:
            receptor = _required_object(target.get("receptor"), "receptor")
            _verify_evidence_file(
                final_receptor_evidence_root,
                _required_object(receptor.get("pdbqt"), "receptor PDBQT"),
                f"{target_id} receptor PDBQT",
            )
        if ligand_preparation_evidence_root is not None:
            for entry_raw in _required_list(target, "entries"):
                entry = _required_object(entry_raw, "campaign entry")
                if entry.get("docking_disposition") == "ready":
                    _verify_evidence_file(
                        ligand_preparation_evidence_root,
                        _required_object(entry.get("ligand_pdbqt"), "ligand PDBQT"),
                        f"ligand PDBQT sequence {entry.get('sequence')}",
                    )
    return manifest


def serialize_vina_campaign_plan(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _parameters_from_spec(
    primary_run: dict[str, Any], *, total_cpu_threads: int, parallel_ligands: int
) -> VinaBatchDockingParameters:
    if primary_run.get("engine") != "AutoDock Vina" or primary_run.get(
        "version"
    ) != REQUIRED_VINA_VERSION:
        raise ScreeningBenchmarkVinaPlanError(
            "The primary run does not freeze AutoDock Vina 1.2.7."
        )
    if primary_run.get("library_filters") != "descriptive_only_no_exclusion":
        raise ScreeningBenchmarkVinaPlanError(
            "Benchmark library filters must remain descriptive only."
        )
    if total_cpu_threads != _required_positive_int(
        primary_run, "total_cpu_threads"
    ) or parallel_ligands != _required_positive_int(primary_run, "parallel_ligands"):
        raise ScreeningBenchmarkVinaPlanError(
            "The requested worker allocation differs from the frozen primary run."
        )
    return VinaBatchDockingParameters(
        sampling_protocol=VinaSamplingProtocol.SCREENING,
        total_cpu_threads=total_cpu_threads,
        parallel_ligands=parallel_ligands,
        seed=_required_positive_int(primary_run, "seed"),
        exhaustiveness=_required_positive_int(primary_run, "exhaustiveness"),
        num_modes=_required_positive_int(primary_run, "maximum_poses"),
        min_rmsd_angstrom=_required_number(primary_run, "minimum_rmsd_angstrom"),
        energy_range_kcal_mol=_required_number(
            primary_run, "energy_range_kcal_mol"
        ),
        timeout_minutes_per_ligand=_required_positive_int(
            primary_run, "timeout_minutes_per_ligand"
        ),
    )


def _base_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": _required_positive_int(entry, "sequence"),
        "target_sequence": _required_positive_int(entry, "target_sequence"),
        "class_label": _required_string(entry, "class_label"),
        "class_index": _required_positive_int(entry, "class_index"),
        "source_member_path": _safe_relative_path(
            _required_string(entry, "source_member_path")
        ),
        "source_line_number": _required_positive_int(entry, "source_line_number"),
        "source_identifier": _required_string(entry, "source_identifier"),
        "source_smiles_sha256": _required_sha256(entry, "source_smiles_sha256"),
        "canonical_isomeric_smiles_sha256": _required_sha256(
            entry, "canonical_isomeric_smiles_sha256"
        ),
        "preparation_status": _required_string(entry, "status"),
    }


def _primary_receptors(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in _required_list(manifest, "receptors"):
        receptor = _required_object(raw, "receptor")
        if receptor.get("role") != "primary":
            continue
        target_id = _required_string(receptor, "target_id")
        if target_id in result:
            raise ScreeningBenchmarkVinaPlanError(
                f"More than one primary receptor exists for {target_id}."
            )
        if receptor.get("status") != "completed" or receptor.get(
            "final_status"
        ) != "docking_ready":
            raise ScreeningBenchmarkVinaPlanError(
                f"The primary receptor for {target_id} is not docking ready."
            )
        result[target_id] = receptor
    return result


def _argument_template(
    *,
    box: BindingBox,
    parameters: VinaBatchDockingParameters,
    threads_per_ligand: int,
) -> list[str]:
    single = VinaDockingParameters(
        sampling_protocol=parameters.sampling_protocol,
        cpu_threads=threads_per_ligand,
        seed=parameters.seed,
        exhaustiveness=parameters.exhaustiveness,
        num_modes=parameters.num_modes,
        min_rmsd_angstrom=parameters.min_rmsd_angstrom,
        energy_range_kcal_mol=parameters.energy_range_kcal_mol,
        timeout_minutes=parameters.timeout_minutes_per_ligand,
    )
    return build_vina_arguments(
        receptor_path=Path("<target_receptor_pdbqt>"),
        ligand_path=Path("<entry_ligand_pdbqt>"),
        output_path=Path("<entry_output_pdbqt>"),
        box=box,
        parameters=single,
    )


def _verify_plan_contract(manifest: dict[str, Any]) -> None:
    if manifest.get("scores_seen") is not False:
        raise ScreeningBenchmarkVinaPlanError("The pre-result score boundary changed.")
    engine = _required_object(manifest.get("engine"), "engine")
    if engine.get("name") != "AutoDock Vina" or engine.get(
        "version"
    ) != REQUIRED_VINA_VERSION:
        raise ScreeningBenchmarkVinaPlanError("The frozen Vina identity changed.")
    _required_sha256(engine, "executable_sha256")
    _required_positive_int(engine, "executable_size_bytes")
    if engine.get("score_direction") != "lower_is_better":
        raise ScreeningBenchmarkVinaPlanError("The score direction changed.")
    if engine.get("score_field") != "affinity_kcal_mol":
        raise ScreeningBenchmarkVinaPlanError("The Vina score field changed.")
    executable_filename = _required_string(engine, "executable_filename")
    if Path(executable_filename).name != executable_filename:
        raise ScreeningBenchmarkVinaPlanError(
            "The Vina executable identity must not contain a path."
        )

    parameters_raw = _required_object(manifest.get("parameters"), "parameters")
    expected = VinaBatchDockingParameters(
        sampling_protocol=VinaSamplingProtocol.SCREENING,
        total_cpu_threads=_required_positive_int(parameters_raw, "total_cpu_threads"),
        parallel_ligands=_required_positive_int(parameters_raw, "parallel_ligands"),
        seed=20260911,
        exhaustiveness=8,
        num_modes=9,
        min_rmsd_angstrom=1.0,
        energy_range_kcal_mol=3.0,
        timeout_minutes_per_ligand=TIMEOUT_MINUTES_PER_LIGAND,
    )
    expected_parameters = {
        **expected.model_dump(mode="json"),
        "threads_per_ligand": max(
            1, expected.total_cpu_threads // expected.parallel_ligands
        ),
    }
    if parameters_raw != expected_parameters:
        raise ScreeningBenchmarkVinaPlanError("The frozen Vina parameters changed.")

    execution = _required_object(manifest.get("execution_policy"), "execution policy")
    required_flags = (
        "all_source_parents_retained",
        "failures_retained_as_unscored_worst_tie",
        "restartable_create_only_entry_attempts",
        "terminal_entries_persisted_incrementally",
        "raw_outputs_preserved",
        "stdout_not_used_for_scoring",
    )
    if any(execution.get(flag) is not True for flag in required_flags) or any(
        execution.get(flag) is not False
        for flag in ("docking_executed", "scores_or_metrics_computed")
    ):
        raise ScreeningBenchmarkVinaPlanError("The Vina execution boundary changed.")

    dependencies = _required_object(manifest.get("dependencies"), "dependencies")
    for key in (
        "primary_run_sha256",
        "geometry_manifest_sha256",
        "final_receptor_manifest_sha256",
        "ligand_preparation_manifest_sha256",
    ):
        _required_sha256(dependencies, key)
    parser = _required_object(dependencies.get("vina_parser"), "Vina parser")
    if parser.get("repository_path") != PARSER_SOURCE_REPOSITORY_PATH:
        raise ScreeningBenchmarkVinaPlanError("The Vina parser path changed.")
    _required_sha256(parser, "sha256")
    _required_positive_int(parser, "size_bytes")
    if _required_object(manifest.get("parser_contract"), "parser contract") != {
        "pose_container": "sequential MODEL/ENDMDL records starting at one",
        "score_source": "one REMARK VINA RESULT record inside each MODEL",
        "content_outside_models": "forbidden_except_whitespace",
        "raw_output_bytes_retained": True,
    }:
        raise ScreeningBenchmarkVinaPlanError("The Vina parser contract changed.")

    targets = _required_list(manifest, "targets")
    sequence_values: list[int] = []
    prepared = 0
    retained = 0
    class_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    target_ids: set[str] = set()
    ligand_pdbqt_hashes: set[str] = set()
    for index, raw_target in enumerate(targets, start=1):
        target = _required_object(raw_target, "target")
        if _required_positive_int(target, "campaign_sequence") != index:
            raise ScreeningBenchmarkVinaPlanError("Campaign target order changed.")
        target_id = _required_string(target, "target_id")
        if target_id in target_ids:
            raise ScreeningBenchmarkVinaPlanError("A campaign target is duplicated.")
        target_ids.add(target_id)
        receptor = _required_object(target.get("receptor"), "receptor")
        _required_string(receptor, "final_receptor_id")
        if _required_string(receptor, "pdb_id").lower() != _required_string(
            target, "primary_template_id"
        ).lower():
            raise ScreeningBenchmarkVinaPlanError(
                "A target receptor differs from its primary template."
            )
        _artifact_identity(_required_object(receptor.get("pdbqt"), "receptor PDBQT"))
        box = _binding_box(_required_object(target.get("box_angstrom"), "box"))
        if target.get("argument_template") != _argument_template(
            box=box,
            parameters=expected,
            threads_per_ligand=expected_parameters["threads_per_ligand"],
        ):
            raise ScreeningBenchmarkVinaPlanError("A Vina argument template changed.")
        entries = _required_list(target, "entries")
        target_sequences: list[int] = []
        target_prepared = 0
        target_retained = 0
        target_classes: Counter[str] = Counter()
        target_statuses: Counter[str] = Counter()
        for raw_entry in entries:
            entry = _required_object(raw_entry, "campaign entry")
            sequence_values.append(_required_positive_int(entry, "sequence"))
            target_sequences.append(_required_positive_int(entry, "target_sequence"))
            class_label = _required_string(entry, "class_label")
            if class_label not in {"active", "inactive"}:
                raise ScreeningBenchmarkVinaPlanError(
                    "A campaign entry has an unsupported benchmark class."
                )
            status = _required_string(entry, "preparation_status")
            _required_positive_int(entry, "class_index")
            _safe_relative_path(_required_string(entry, "source_member_path"))
            _required_positive_int(entry, "source_line_number")
            _required_string(entry, "source_identifier")
            _required_sha256(entry, "source_smiles_sha256")
            _required_sha256(entry, "canonical_isomeric_smiles_sha256")
            class_counts[class_label] += 1
            status_counts[status] += 1
            target_classes[class_label] += 1
            target_statuses[status] += 1
            disposition = entry.get("docking_disposition")
            if disposition == "ready":
                if status != "prepared":
                    raise ScreeningBenchmarkVinaPlanError(
                        "A ready docking entry was not prepared."
                    )
                ligand_identity = _artifact_identity(
                    _required_object(entry.get("ligand_pdbqt"), "ligand PDBQT")
                )
                ligand_hash = _required_sha256(ligand_identity, "sha256")
                if ligand_hash in ligand_pdbqt_hashes:
                    raise ScreeningBenchmarkVinaPlanError(
                        "A prepared ligand PDBQT identity is duplicated."
                    )
                ligand_pdbqt_hashes.add(ligand_hash)
                if "preparation_failure" in entry:
                    raise ScreeningBenchmarkVinaPlanError(
                        "A prepared entry also records a preparation failure."
                    )
                prepared += 1
                target_prepared += 1
            elif disposition == "retained_unscored_worst_tie":
                failure = _required_object(
                    entry.get("preparation_failure"), "preparation failure"
                )
                if _required_string(failure, "status") != status:
                    raise ScreeningBenchmarkVinaPlanError(
                        "A preparation failure status differs from its entry."
                    )
                _required_string(failure, "code")
                _required_string(failure, "stage")
                if "ligand_pdbqt" in entry:
                    raise ScreeningBenchmarkVinaPlanError(
                        "An unprepared entry unexpectedly binds a ligand PDBQT."
                    )
                retained += 1
                target_retained += 1
            else:
                raise ScreeningBenchmarkVinaPlanError(
                    "A campaign entry has an unsupported docking disposition."
                )
        if target_sequences != list(range(1, len(entries) + 1)):
            raise ScreeningBenchmarkVinaPlanError("Target ligand order changed.")
        census = _required_object(target.get("census"), "target census")
        if census != {
            "source_parents": len(entries),
            "prepared_for_docking": target_prepared,
            "retained_unscored_worst_tie": target_retained,
            "by_class": dict(sorted(target_classes.items())),
            "by_preparation_status": dict(sorted(target_statuses.items())),
        }:
            raise ScreeningBenchmarkVinaPlanError("A target census does not close.")

    if sorted(sequence_values) != list(range(1, len(sequence_values) + 1)):
        raise ScreeningBenchmarkVinaPlanError("Global ligand order changed.")
    totals = _required_object(manifest.get("totals"), "totals")
    if totals != {
        "target_count": len(targets),
        "source_parents": len(sequence_values),
        "prepared_for_docking": prepared,
        "retained_unscored_worst_tie": retained,
        "by_class": dict(sorted(class_counts.items())),
        "by_preparation_status": dict(sorted(status_counts.items())),
    }:
        raise ScreeningBenchmarkVinaPlanError("The campaign totals do not close.")
    if execution.get("target_campaign_count") != len(targets):
        raise ScreeningBenchmarkVinaPlanError("The target campaign count changed.")
    if manifest.get("result_status") != (
        "primary_vina_campaign_plan_frozen_no_docking_score_or_metric_executed"
    ):
        raise ScreeningBenchmarkVinaPlanError("The Vina result boundary changed.")


def _binding_box(value: dict[str, Any]) -> BindingBox:
    try:
        return BindingBox(
            center_x=_required_number(value, "center_x"),
            center_y=_required_number(value, "center_y"),
            center_z=_required_number(value, "center_z"),
            size_x=_required_number(value, "size_x"),
            size_y=_required_number(value, "size_y"),
            size_z=_required_number(value, "size_z"),
        )
    except ValueError as error:
        raise ScreeningBenchmarkVinaPlanError("The binding box is invalid.") from error


def _artifact_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _safe_relative_path(_required_string(value, "path")),
        "size_bytes": _required_positive_int(value, "size_bytes"),
        "sha256": _required_sha256(value, "sha256"),
    }


def _one_stage(values: list[Any], stage: str, label: str) -> dict[str, Any]:
    matches = [
        _required_object(value, label)
        for value in values
        if isinstance(value, dict) and value.get("stage") == stage
    ]
    if len(matches) != 1:
        raise ScreeningBenchmarkVinaPlanError(
            f"Expected one {label} at stage {stage!r}."
        )
    return matches[0]


def _verify_evidence_file(root: Path, artifact: dict[str, Any], label: str) -> None:
    relative = _safe_relative_path(_required_string(artifact, "path"))
    root_resolved = root.resolve()
    path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if path == root_resolved or root_resolved not in path.parents:
        raise ScreeningBenchmarkVinaPlanError(f"{label} escapes its evidence root.")
    _verify_direct_file(path, artifact, label)


def _verify_direct_file(path: Path, identity: dict[str, Any], label: str) -> None:
    _require_regular_file(path, label)
    if path.stat().st_size != _required_positive_int(identity, "size_bytes"):
        raise ScreeningBenchmarkVinaPlanError(f"{label} size changed.")
    if _file_sha256(path) != _required_sha256(identity, "sha256"):
        raise ScreeningBenchmarkVinaPlanError(f"{label} SHA-256 changed.")


def _require_regular_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ScreeningBenchmarkVinaPlanError(f"{label} is not a readable file.")


def _safe_relative_path(value: str) -> str:
    if "\\" in value:
        raise ScreeningBenchmarkVinaPlanError("Evidence paths must use POSIX separators.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ScreeningBenchmarkVinaPlanError("Evidence paths must remain relative.")
    return path.as_posix()


def _unique_by(values: list[Any], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        item = _required_object(value, label)
        identity = _required_string(item, key)
        if identity in result:
            raise ScreeningBenchmarkVinaPlanError(f"Duplicate {label}: {identity}.")
        result[identity] = item
    return result


def _load_manifest(path: Path, label: str) -> dict[str, Any]:
    value = _load_object(path, label)
    return value


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkVinaPlanError(f"Cannot read {label}.") from error
    return _required_object(value, label)


def _verify_manifest_identity(manifest: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkVinaPlanError(f"The {label} differs from its SHA-256.")


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkVinaPlanError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ScreeningBenchmarkVinaPlanError(f"{key} must be a list.")
    return item


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ScreeningBenchmarkVinaPlanError(f"{key} must be a non-empty string.")
    return item


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 1:
        raise ScreeningBenchmarkVinaPlanError(f"{key} must be a positive integer.")
    return item


def _required_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise ScreeningBenchmarkVinaPlanError(f"{key} must be numeric.")
    return float(item)


def _required_sha256(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if (
        not isinstance(item, str)
        or len(item) != 64
        or any(character not in "0123456789abcdef" for character in item)
    ):
        raise ScreeningBenchmarkVinaPlanError(f"{key} must be a lowercase SHA-256.")
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
