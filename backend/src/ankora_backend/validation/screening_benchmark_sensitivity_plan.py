"""Freeze the post-primary LIT-PCBA one-factor sensitivity program.

The primary result and metrics exist when this plan is created. The module
therefore binds only choices fixed before those results: the complete primary
cohort, hash-selected chemical-state sentinels, alternate receptors, expanded
boxes, seeds, sampling setting, and the pre-result microstate defaults.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from ankora_backend.validation.screening_benchmark_primary_metrics import (
    verify_primary_metrics_manifest,
)
from ankora_backend.validation.screening_benchmark_vina_execution import (
    verify_vina_campaign_manifest,
)
from ankora_backend.validation.screening_benchmark_vina_plan import (
    verify_vina_campaign_plan,
)

SCHEMA_VERSION = 1
RESULT_STATUS = "sensitivity_plan_frozen_no_sensitivity_execution_or_metric"
MICROSTATE_SOURCE_COMMIT = "56a1b918a72aa3551e82e46ccc23583bca8091fe"
MICROSTATE_SOURCE_COMMIT_TIMESTAMP = "2026-09-03T19:21:08-06:00"
MICROSTATE_SCHEMA_REPOSITORY_PATH = "backend/src/ankora_backend/schemas/ligands.py"
MICROSTATE_SERVICE_REPOSITORY_PATH = "backend/src/ankora_backend/services/ligand_microstates.py"
MAX_MICROSTATES_PER_PARENT = 16
MICROSTATE_BOUNDS = {
    "mode": "enumerated_selection",
    "ph_min": 7.4,
    "ph_max": 7.4,
    "precision": 1.0,
    "max_tautomers_per_protomer": 8,
    "max_microstates_per_parent": MAX_MICROSTATES_PER_PARENT,
}


class ScreeningBenchmarkSensitivityPlanError(ValueError):
    """The supplied evidence cannot satisfy the sensitivity contract."""


def build_sensitivity_plan(
    *,
    spec_path: Path,
    geometry_manifest_path: Path,
    final_receptor_manifest_path: Path,
    primary_plan_path: Path,
    primary_result_path: Path,
    primary_metrics_path: Path,
    microstate_schema_path: Path,
    microstate_service_path: Path,
    final_receptor_evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Build an exact path-free sensitivity plan without executing a tool."""

    spec = _load_object(spec_path, "benchmark specification")
    geometry = _load_manifest(geometry_manifest_path, "geometry manifest")
    receptors = _load_manifest(final_receptor_manifest_path, "receptor manifest")
    primary_plan = verify_vina_campaign_plan(primary_plan_path)
    primary_result = verify_vina_campaign_manifest(
        primary_result_path, plan_manifest_path=primary_plan_path
    )
    primary_metrics = verify_primary_metrics_manifest(
        primary_metrics_path,
        primary_result_path=primary_result_path,
        primary_plan_path=primary_plan_path,
    )
    protocol_id = _required_string(spec, "protocol_id")
    for value, label in (
        (geometry, "geometry manifest"),
        (receptors, "receptor manifest"),
        (primary_plan, "primary plan"),
        (primary_result, "primary result"),
        (primary_metrics, "primary metrics"),
    ):
        if value.get("protocol_id") != protocol_id:
            raise ScreeningBenchmarkSensitivityPlanError(
                f"The {label} belongs to a different protocol."
            )
    if primary_result.get("scores_seen") is not True:
        raise ScreeningBenchmarkSensitivityPlanError(
            "The closed primary result must precede sensitivity planning."
        )
    if (
        primary_metrics.get("metrics_computed") is not True
        or primary_metrics.get("sensitivity_executed") is not False
    ):
        raise ScreeningBenchmarkSensitivityPlanError(
            "Primary metrics must close before sensitivity execution."
        )

    sensitivity = _required_object(spec.get("sensitivity"), "sensitivity")
    _verify_frozen_sensitivity_statement(sensitivity)
    primary_parameters = _required_object(primary_plan.get("parameters"), "primary parameters")
    primary_targets = _unique_by(
        _required_list(primary_plan, "targets"), "target_id", "primary target"
    )
    geometry_targets = _unique_by(
        _required_list(geometry, "targets"), "target_id", "geometry target"
    )
    receptor_roles = _receptors_by_target_and_role(receptors)
    if set(primary_targets) != set(geometry_targets) or set(primary_targets) != set(receptor_roles):
        raise ScreeningBenchmarkSensitivityPlanError(
            "Sensitivity target identities differ across frozen manifests."
        )

    sentinel_entries = _sentinel_cohort(
        geometry_targets=geometry_targets, primary_targets=primary_targets
    )
    full_census = _required_object(primary_plan.get("totals"), "primary totals")
    if _required_positive_int(full_census, "source_parents") != 11412:
        raise ScreeningBenchmarkSensitivityPlanError(
            "The full paired population differs from the primary cohort."
        )

    alternate_targets: list[dict[str, Any]] = []
    expanded_targets: list[dict[str, Any]] = []
    for target_id in primary_targets:
        primary_target = primary_targets[target_id]
        geometry_target = geometry_targets[target_id]
        alternate = receptor_roles[target_id]["alternate"]
        alternate_identity = _receptor_identity(alternate)
        if final_receptor_evidence_root is not None:
            _verify_evidence_file(
                final_receptor_evidence_root,
                alternate_identity["pdbqt"],
                f"{target_id} alternate receptor PDBQT",
            )
        alternate_targets.append(
            {
                "target_id": target_id,
                "primary_template_id": _required_string(primary_target, "primary_template_id"),
                "alternate_receptor": alternate_identity,
            }
        )
        box = _required_object(
            _required_object(geometry_target.get("co_crystal_box"), "co-crystal box").get(
                "expanded_sensitivity_box_angstrom"
            ),
            "expanded sensitivity box",
        )
        expanded_targets.append({"target_id": target_id, "box_angstrom": _box(box)})

    _require_regular_file(microstate_schema_path, "microstate schema source")
    _require_regular_file(microstate_service_path, "microstate service source")
    microstate_contract = {
        "introduced_before_primary_results": True,
        "source_commit": MICROSTATE_SOURCE_COMMIT,
        "source_commit_timestamp": MICROSTATE_SOURCE_COMMIT_TIMESTAMP,
        "bounds": MICROSTATE_BOUNDS,
        "schema_source": _source_identity(
            microstate_schema_path, MICROSTATE_SCHEMA_REPOSITORY_PATH
        ),
        "enumerator_source": _source_identity(
            microstate_service_path, MICROSTATE_SERVICE_REPOSITORY_PATH
        ),
        "tools": {
            "dimorphite_dl_version": metadata.version("dimorphite-dl"),
            "rdkit_version": metadata.version("rdkit"),
        },
        "candidate_policy": {
            "all_emitted_candidates_retained": True,
            "candidate_order_is_not_population_ranking": True,
            "truncation_is_recorded": True,
            "single_state_selection_forbidden": True,
            "best_state_enrichment_forbidden": True,
            "parent_report": "score_and_rank_range_across_retained_states",
        },
    }

    variants = [
        {
            "sequence": 1,
            "variant_id": "chemical_state_bounded_panel",
            "factor": "chemical_state",
            "paired_population": "hash_selected_sentinel_panel",
            "parent_count": len(sentinel_entries),
            "prepared_primary_parent_count": len(sentinel_entries),
            "maximum_candidate_executions": len(sentinel_entries) * MAX_MICROSTATES_PER_PARENT,
            "sentinel_entries": sentinel_entries,
            "microstate_contract": microstate_contract,
            "fixed_vina_parameters": _vina_parameters(primary_parameters),
            "fixed_receptor_and_box": "primary_per_target",
        },
        {
            "sequence": 2,
            "variant_id": "alternate_experimental_holo_receptor",
            "factor": "receptor",
            **_full_cohort_variant_fields(full_census),
            "targets": alternate_targets,
            "fixed_box": "primary_per_target",
            "fixed_vina_parameters": _vina_parameters(primary_parameters),
        },
        {
            "sequence": 3,
            "variant_id": "expanded_box_plus_3_angstrom_per_face",
            "factor": "box",
            **_full_cohort_variant_fields(full_census),
            "targets": expanded_targets,
            "fixed_receptor": "primary_per_target",
            "fixed_vina_parameters": _vina_parameters(primary_parameters),
        },
        _parameter_variant(
            4,
            "seed_20260912",
            "seed",
            "seed",
            20260912,
            primary_parameters,
            full_census,
        ),
        _parameter_variant(
            5,
            "seed_20260913",
            "seed",
            "seed",
            20260913,
            primary_parameters,
            full_census,
        ),
        _parameter_variant(
            6,
            "exhaustiveness_32",
            "sampling",
            "exhaustiveness",
            32,
            primary_parameters,
            full_census,
        ),
    ]
    max_executions = (
        5 * _required_positive_int(full_census, "prepared_for_docking")
        + len(sentinel_entries) * MAX_MICROSTATES_PER_PARENT
    )
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "primary_scores_seen": True,
        "sensitivity_scores_seen": False,
        "dependencies": {
            "spec_file_sha256": _file_sha256(spec_path),
            "sensitivity_statement_sha256": _digest(sensitivity),
            "geometry_manifest_sha256": _required_sha256(geometry, "manifest_sha256"),
            "final_receptor_manifest_sha256": _required_sha256(receptors, "manifest_sha256"),
            "primary_vina_plan_sha256": _required_sha256(primary_plan, "manifest_sha256"),
            "primary_vina_result_sha256": _required_sha256(primary_result, "manifest_sha256"),
            "primary_metric_manifest_sha256": _required_sha256(primary_metrics, "manifest_sha256"),
        },
        "engine": _required_object(primary_plan.get("engine"), "engine"),
        "comparison_policy": {
            "design": "one_factor_at_a_time",
            "primary_result_is_immutable_comparator": True,
            "sensitivity_cannot_replace_primary_table": True,
            "full_cohort_used_for_receptor_box_seed_and_sampling": True,
            "sentinel_panel_used_only_for_chemical_state": True,
            "unscored_parents_retained_as_one_worst_tie": True,
            "target_scores_never_pooled": True,
        },
        "cohorts": {
            "full_primary_parent_population": {
                "source_parents": _required_positive_int(full_census, "source_parents"),
                "prepared_for_docking": _required_positive_int(full_census, "prepared_for_docking"),
                "retained_unscored_worst_tie": _required_positive_int(
                    full_census, "retained_unscored_worst_tie"
                ),
                "by_class": _required_object(
                    full_census.get("by_class"), "full cohort class census"
                ),
            },
            "hash_selected_sentinel_panel": _sentinel_census(sentinel_entries),
        },
        "variants": variants,
        "execution_policy": {
            "execution_order_is_variant_sequence": True,
            "create_only_variant_roots": True,
            "restartable_create_only_entry_attempts": True,
            "terminal_entries_persisted_incrementally": True,
            "raw_outputs_preserved": True,
            "primary_outputs_never_modified": True,
            "maximum_additional_vina_executions": max_executions,
            "sensitivity_executed": False,
            "sensitivity_metrics_computed": False,
        },
        "result_status": RESULT_STATUS,
    }
    plan["manifest_sha256"] = _digest(plan)
    _verify_plan_contract(plan)
    return plan


def verify_sensitivity_plan(
    path: Path,
    *,
    spec_path: Path | None = None,
    geometry_manifest_path: Path | None = None,
    final_receptor_manifest_path: Path | None = None,
    primary_plan_path: Path | None = None,
    primary_result_path: Path | None = None,
    primary_metrics_path: Path | None = None,
    microstate_schema_path: Path | None = None,
    microstate_service_path: Path | None = None,
    final_receptor_evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Verify identity, or rebuild from complete supplied dependencies."""

    recorded = _load_object(path, "sensitivity plan")
    if recorded.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkSensitivityPlanError("Unsupported sensitivity plan schema.")
    _verify_manifest_identity(recorded, "sensitivity plan")
    _verify_plan_contract(recorded)
    rebuild_paths = (
        spec_path,
        geometry_manifest_path,
        final_receptor_manifest_path,
        primary_plan_path,
        primary_result_path,
        primary_metrics_path,
        microstate_schema_path,
        microstate_service_path,
    )
    if any(value is not None for value in rebuild_paths):
        if not all(value is not None for value in rebuild_paths):
            raise ScreeningBenchmarkSensitivityPlanError(
                "Complete dependencies are required to rebuild the plan."
            )
        expected = build_sensitivity_plan(
            spec_path=spec_path,  # type: ignore[arg-type]
            geometry_manifest_path=geometry_manifest_path,  # type: ignore[arg-type]
            final_receptor_manifest_path=final_receptor_manifest_path,  # type: ignore[arg-type]
            primary_plan_path=primary_plan_path,  # type: ignore[arg-type]
            primary_result_path=primary_result_path,  # type: ignore[arg-type]
            primary_metrics_path=primary_metrics_path,  # type: ignore[arg-type]
            microstate_schema_path=microstate_schema_path,  # type: ignore[arg-type]
            microstate_service_path=microstate_service_path,  # type: ignore[arg-type]
            final_receptor_evidence_root=final_receptor_evidence_root,
        )
        if recorded != expected:
            raise ScreeningBenchmarkSensitivityPlanError(
                "The sensitivity plan does not reproduce from its dependencies."
            )
    return recorded


def serialize_sensitivity_plan(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _verify_frozen_sensitivity_statement(value: dict[str, Any]) -> None:
    expected = {
        "design": "one_factor_at_a_time_on_a_constant_predeclared_paired_population",
        "chemical_state": (
            "all bounded states on a hash-selected sentinel panel; report ranges, "
            "never best-state enrichment"
        ),
        "receptor": (
            "primary holo receptor versus one predeclared alternate experimental "
            "holo receptor of the same phenotype"
        ),
        "box": (
            "primary co-crystal box versus the same center with 3.0 additional "
            "angstrom on every face"
        ),
        "seeds": [20260911, 20260912, 20260913],
        "sampling_exhaustiveness": [8, 32],
    }
    if value != expected:
        raise ScreeningBenchmarkSensitivityPlanError(
            "The preregistered sensitivity statement changed."
        )


def _sentinel_cohort(
    *,
    geometry_targets: dict[str, dict[str, Any]],
    primary_targets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_identity: dict[tuple[object, ...], dict[str, Any]] = {}
    for target_id, target in primary_targets.items():
        for raw in _required_list(target, "entries"):
            entry = _required_object(raw, "primary entry")
            key = _entry_identity(target_id, entry, "source_identifier")
            if key in by_identity:
                raise ScreeningBenchmarkSensitivityPlanError(
                    "A primary entry identity is duplicated."
                )
            by_identity[key] = entry

    cohort: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    for target_id in primary_targets:
        sentinels = _required_object(
            geometry_targets[target_id].get("chemical_state_sentinels"),
            "chemical-state sentinels",
        )
        for class_label in ("active", "inactive"):
            values = sentinels.get(class_label)
            if not isinstance(values, list) or len(values) != 16:
                raise ScreeningBenchmarkSensitivityPlanError(
                    f"{target_id} must retain 16 {class_label} sentinels."
                )
            for raw in values:
                sentinel = _required_object(raw, "sentinel")
                key = _entry_identity(target_id, sentinel, "source_id")
                matched_entry = by_identity.get(key)
                if matched_entry is None or matched_entry.get("class_label") != class_label:
                    raise ScreeningBenchmarkSensitivityPlanError(
                        "A frozen sentinel differs from the primary cohort."
                    )
                if matched_entry.get("docking_disposition") != "ready":
                    raise ScreeningBenchmarkSensitivityPlanError(
                        "Every chemical-state sentinel must have a primary PDBQT."
                    )
                sequence = _required_positive_int(matched_entry, "sequence")
                if sequence in seen_sequences:
                    raise ScreeningBenchmarkSensitivityPlanError("A sentinel parent is duplicated.")
                seen_sequences.add(sequence)
                cohort.append(
                    {
                        "target_id": target_id,
                        "class_label": class_label,
                        "selection_rank": _required_positive_int(sentinel, "selection_rank"),
                        "selection_sha256": _required_sha256(sentinel, "selection_sha256"),
                        "primary_sequence": sequence,
                        "target_sequence": _required_positive_int(matched_entry, "target_sequence"),
                        "source_member_path": _safe_relative_path(
                            _required_string(matched_entry, "source_member_path")
                        ),
                        "source_line_number": _required_positive_int(
                            matched_entry, "source_line_number"
                        ),
                        "source_identifier": _required_string(matched_entry, "source_identifier"),
                        "source_smiles_sha256": _required_sha256(
                            matched_entry, "source_smiles_sha256"
                        ),
                        "canonical_isomeric_smiles_sha256": _required_sha256(
                            matched_entry, "canonical_isomeric_smiles_sha256"
                        ),
                    }
                )
    if len(cohort) != 96:
        raise ScreeningBenchmarkSensitivityPlanError(
            "The chemical-state cohort must contain 96 parents."
        )
    return cohort


def _entry_identity(
    target_id: str, value: dict[str, Any], source_id_key: str
) -> tuple[object, ...]:
    return (
        target_id,
        _safe_relative_path(_required_string(value, "source_member_path")),
        _required_positive_int(value, "source_line_number"),
        _required_string(value, source_id_key),
        _required_sha256(value, "canonical_isomeric_smiles_sha256"),
    )


def _receptors_by_target_and_role(
    manifest: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for raw in _required_list(manifest, "receptors"):
        receptor = _required_object(raw, "receptor")
        target_id = _required_string(receptor, "target_id")
        role = _required_string(receptor, "role")
        if role not in {"primary", "alternate"}:
            raise ScreeningBenchmarkSensitivityPlanError("A receptor has an unsupported role.")
        if role in result.setdefault(target_id, {}):
            raise ScreeningBenchmarkSensitivityPlanError("A target repeats a receptor role.")
        if receptor.get("status") != "completed" or receptor.get("final_status") != "docking_ready":
            raise ScreeningBenchmarkSensitivityPlanError(
                "Sensitivity requires docking-ready receptors."
            )
        result[target_id][role] = receptor
    if any(set(roles) != {"primary", "alternate"} for roles in result.values()):
        raise ScreeningBenchmarkSensitivityPlanError(
            "Every target requires primary and alternate receptors."
        )
    return result


def _receptor_identity(receptor: dict[str, Any]) -> dict[str, Any]:
    outputs = [
        _required_object(value, "receptor output")
        for value in _required_list(receptor, "outputs")
        if isinstance(value, dict) and value.get("stage") == "pdbqt"
    ]
    if len(outputs) != 1:
        raise ScreeningBenchmarkSensitivityPlanError("Expected one receptor PDBQT output.")
    return {
        "pdb_id": _required_string(receptor, "pdb_id"),
        "final_receptor_id": _required_string(receptor, "final_receptor_id"),
        "pdbqt": _artifact_identity(outputs[0]),
    }


def _full_cohort_variant_fields(census: dict[str, Any]) -> dict[str, Any]:
    return {
        "paired_population": "full_primary_parent_population",
        "parent_count": _required_positive_int(census, "source_parents"),
        "prepared_for_docking": _required_positive_int(census, "prepared_for_docking"),
        "retained_unscored_worst_tie": _required_positive_int(
            census, "retained_unscored_worst_tie"
        ),
    }


def _parameter_variant(
    sequence: int,
    variant_id: str,
    factor: str,
    parameter: str,
    value: int,
    primary_parameters: dict[str, Any],
    full_census: dict[str, Any],
) -> dict[str, Any]:
    parameters = _vina_parameters(primary_parameters)
    parameters[parameter] = value
    return {
        "sequence": sequence,
        "variant_id": variant_id,
        "factor": factor,
        **_full_cohort_variant_fields(full_census),
        "fixed_receptor_and_box": "primary_per_target",
        "vina_parameters": parameters,
    }


def _vina_parameters(value: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "sampling_protocol",
        "total_cpu_threads",
        "parallel_ligands",
        "seed",
        "exhaustiveness",
        "num_modes",
        "min_rmsd_angstrom",
        "energy_range_kcal_mol",
        "timeout_minutes_per_ligand",
        "threads_per_ligand",
    )
    if any(key not in value for key in keys):
        raise ScreeningBenchmarkSensitivityPlanError(
            "The primary Vina parameter record is incomplete."
        )
    return {key: value[key] for key in keys}


def _sentinel_census(entries: list[dict[str, Any]]) -> dict[str, Any]:
    by_target: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    for entry in entries:
        by_target[_required_string(entry, "target_id")] += 1
        by_class[_required_string(entry, "class_label")] += 1
    return {
        "parents": len(entries),
        "by_target": dict(sorted(by_target.items())),
        "by_class": dict(sorted(by_class.items())),
        "all_primary_states_prepared": True,
    }


def _verify_plan_contract(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("primary_scores_seen") is not True
        or manifest.get("sensitivity_scores_seen") is not False
    ):
        raise ScreeningBenchmarkSensitivityPlanError(
            "The primary/sensitivity score boundary changed."
        )
    dependencies = _required_object(manifest.get("dependencies"), "dependencies")
    for key in (
        "spec_file_sha256",
        "sensitivity_statement_sha256",
        "geometry_manifest_sha256",
        "final_receptor_manifest_sha256",
        "primary_vina_plan_sha256",
        "primary_vina_result_sha256",
        "primary_metric_manifest_sha256",
    ):
        _required_sha256(dependencies, key)
    cohorts = _required_object(manifest.get("cohorts"), "cohorts")
    full = _required_object(cohorts.get("full_primary_parent_population"), "full cohort")
    if full != {
        "source_parents": 11412,
        "prepared_for_docking": 11302,
        "retained_unscored_worst_tie": 110,
        "by_class": {"active": 176, "inactive": 11236},
    }:
        raise ScreeningBenchmarkSensitivityPlanError("The full sensitivity cohort changed.")
    sentinel = _required_object(cohorts.get("hash_selected_sentinel_panel"), "sentinel cohort")
    if sentinel != {
        "parents": 96,
        "by_target": {"ESR_antago": 32, "PPARG": 32, "TP53": 32},
        "by_class": {"active": 48, "inactive": 48},
        "all_primary_states_prepared": True,
    }:
        raise ScreeningBenchmarkSensitivityPlanError("The sensitivity sentinel cohort changed.")
    variants = _required_list(manifest, "variants")
    expected_ids = [
        "chemical_state_bounded_panel",
        "alternate_experimental_holo_receptor",
        "expanded_box_plus_3_angstrom_per_face",
        "seed_20260912",
        "seed_20260913",
        "exhaustiveness_32",
    ]
    if [item.get("variant_id") for item in variants if isinstance(item, dict)] != (expected_ids):
        raise ScreeningBenchmarkSensitivityPlanError("The sensitivity variant order changed.")
    if [item.get("sequence") for item in variants if isinstance(item, dict)] != list(range(1, 7)):
        raise ScreeningBenchmarkSensitivityPlanError("Sensitivity variant sequences changed.")
    chemical = _required_object(variants[0], "chemical-state variant")
    if len(_required_list(chemical, "sentinel_entries")) != 96:
        raise ScreeningBenchmarkSensitivityPlanError(
            "The chemical-state variant must retain 96 sentinels."
        )
    microstates = _required_object(chemical.get("microstate_contract"), "microstate contract")
    if (
        microstates.get("source_commit") != MICROSTATE_SOURCE_COMMIT
        or microstates.get("bounds") != MICROSTATE_BOUNDS
    ):
        raise ScreeningBenchmarkSensitivityPlanError("The pre-result microstate bounds changed.")
    execution = _required_object(manifest.get("execution_policy"), "execution policy")
    required_true = (
        "execution_order_is_variant_sequence",
        "create_only_variant_roots",
        "restartable_create_only_entry_attempts",
        "terminal_entries_persisted_incrementally",
        "raw_outputs_preserved",
        "primary_outputs_never_modified",
    )
    if any(execution.get(key) is not True for key in required_true) or any(
        execution.get(key) is not False
        for key in ("sensitivity_executed", "sensitivity_metrics_computed")
    ):
        raise ScreeningBenchmarkSensitivityPlanError("The sensitivity execution boundary changed.")
    if execution.get("maximum_additional_vina_executions") != 58046:
        raise ScreeningBenchmarkSensitivityPlanError(
            "The sensitivity execution upper bound changed."
        )
    if manifest.get("result_status") != RESULT_STATUS:
        raise ScreeningBenchmarkSensitivityPlanError("The sensitivity result boundary changed.")


def _box(value: dict[str, Any]) -> dict[str, float]:
    keys = ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z")
    result = {key: _required_number(value, key) for key in keys}
    if any(result[key] <= 0 for key in ("size_x", "size_y", "size_z")):
        raise ScreeningBenchmarkSensitivityPlanError("A sensitivity box is invalid.")
    return result


def _source_identity(path: Path, repository_path: str) -> dict[str, Any]:
    return {
        "repository_path": repository_path,
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _artifact_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _safe_relative_path(_required_string(value, "path")),
        "size_bytes": _required_nonnegative_int(value, "size_bytes"),
        "sha256": _required_sha256(value, "sha256"),
    }


def _verify_evidence_file(root: Path, artifact: dict[str, Any], label: str) -> None:
    relative = _safe_relative_path(_required_string(artifact, "path"))
    root_resolved = root.resolve()
    path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if path == root_resolved or root_resolved not in path.parents:
        raise ScreeningBenchmarkSensitivityPlanError(f"{label} escapes its root.")
    _require_regular_file(path, label)
    if path.stat().st_size != _required_nonnegative_int(artifact, "size_bytes"):
        raise ScreeningBenchmarkSensitivityPlanError(f"{label} size changed.")
    if _file_sha256(path) != _required_sha256(artifact, "sha256"):
        raise ScreeningBenchmarkSensitivityPlanError(f"{label} SHA-256 changed.")


def _unique_by(values: list[Any], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        item = _required_object(value, label)
        identity = _required_string(item, key)
        if identity in result:
            raise ScreeningBenchmarkSensitivityPlanError(f"Duplicate {label}: {identity}.")
        result[identity] = item
    return result


def _load_manifest(path: Path, label: str) -> dict[str, Any]:
    value = _load_object(path, label)
    _verify_manifest_identity(value, label)
    return value


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkSensitivityPlanError(f"Cannot read {label}.") from error
    return _required_object(value, label)


def _verify_manifest_identity(value: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(value, "manifest_sha256")
    payload = dict(value)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkSensitivityPlanError(f"The {label} differs from its SHA-256.")


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkSensitivityPlanError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ScreeningBenchmarkSensitivityPlanError(f"{key} must be a list.")
    return item


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ScreeningBenchmarkSensitivityPlanError(f"{key} must be a non-empty string.")
    return item


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 1:
        raise ScreeningBenchmarkSensitivityPlanError(f"{key} must be a positive integer.")
    return item


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ScreeningBenchmarkSensitivityPlanError(f"{key} must be a non-negative integer.")
    return item


def _required_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise ScreeningBenchmarkSensitivityPlanError(f"{key} must be numeric.")
    return float(item)


def _required_sha256(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if (
        not isinstance(item, str)
        or len(item) != 64
        or any(character not in "0123456789abcdef" for character in item)
    ):
        raise ScreeningBenchmarkSensitivityPlanError(f"{key} must be a lowercase SHA-256.")
    return item


def _safe_relative_path(value: str) -> str:
    if "\\" in value:
        raise ScreeningBenchmarkSensitivityPlanError("Evidence paths must use POSIX separators.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ScreeningBenchmarkSensitivityPlanError("Evidence paths must remain relative.")
    return path.as_posix()


def _require_regular_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ScreeningBenchmarkSensitivityPlanError(f"{label} is not a readable file.")


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
