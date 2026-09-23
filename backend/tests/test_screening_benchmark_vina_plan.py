"""Synthetic and recorded contracts for the frozen benchmark Vina plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ankora_backend.adapters.engines.vina import VinaInstallation
from ankora_backend.validation.screening_benchmark_vina_plan import (
    ScreeningBenchmarkVinaPlanError,
    build_vina_campaign_plan,
    serialize_vina_campaign_plan,
    verify_vina_campaign_plan,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_PLAN = (
    PROJECT_ROOT
    / "docs"
    / "validation"
    / "reference_cases"
    / "LIT_PCBA_ANKORA_VS_V1.vina-primary-plan.json"
)
REAL_PARSER = (
    PROJECT_ROOT
    / "backend"
    / "src"
    / "ankora_backend"
    / "adapters"
    / "engines"
    / "vina.py"
)


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    value["manifest_sha256"] = _digest(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> dict[str, Path | VinaInstallation]:
    receptor_root = tmp_path / "receptors"
    ligand_root = tmp_path / "ligands"
    receptor_path = receptor_root / "target" / "receptor.pdbqt"
    ligand_path = ligand_root / "target" / "ligand.pdbqt"
    receptor_path.parent.mkdir(parents=True)
    ligand_path.parent.mkdir(parents=True)
    receptor_path.write_bytes(b"RECEPTOR\n")
    ligand_path.write_bytes(b"LIGAND\n")

    executable = tmp_path / "vina_1.2.7_win.exe"
    parser_source = tmp_path / "vina.py"
    executable.write_bytes(b"synthetic Vina executable")
    parser_source.write_text("# synthetic strict pose parser\n", encoding="utf-8")

    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "protocol_id": "SYNTHETIC_VINA_PLAN_V1",
                "primary_run": {
                    "engine": "AutoDock Vina",
                    "version": "1.2.7",
                    "seed": 20260911,
                    "exhaustiveness": 8,
                    "maximum_poses": 9,
                    "minimum_rmsd_angstrom": 1.0,
                    "energy_range_kcal_mol": 3.0,
                    "total_cpu_threads": 3,
                    "parallel_ligands": 3,
                    "timeout_minutes_per_ligand": 360,
                    "library_filters": "descriptive_only_no_exclusion",
                },
            }
        ),
        encoding="utf-8",
    )

    geometry = tmp_path / "geometry.json"
    _write_manifest(
        geometry,
        {
            "schema_version": 1,
            "protocol_id": "SYNTHETIC_VINA_PLAN_V1",
            "targets": [
                {
                    "target_id": "SYNTH",
                    "primary_template_id": "1abc",
                    "co_crystal_box": {
                        "primary_box_angstrom": {
                            "center_x": 1.0,
                            "center_y": 2.0,
                            "center_z": 3.0,
                            "size_x": 10.0,
                            "size_y": 11.0,
                            "size_z": 12.0,
                        }
                    },
                }
            ],
        },
    )
    receptors = tmp_path / "receptors.json"
    _write_manifest(
        receptors,
        {
            "schema_version": 1,
            "protocol_id": "SYNTHETIC_VINA_PLAN_V1",
            "receptors": [
                {
                    "target_id": "SYNTH",
                    "role": "primary",
                    "pdb_id": "1abc",
                    "status": "completed",
                    "final_status": "docking_ready",
                    "final_receptor_id": "receptor-1",
                    "outputs": [
                        {
                            "stage": "pdbqt",
                            "path": "target/receptor.pdbqt",
                            "size_bytes": receptor_path.stat().st_size,
                            "sha256": hashlib.sha256(
                                receptor_path.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                }
            ],
        },
    )
    ligands = tmp_path / "ligands.json"
    _write_manifest(
        ligands,
        {
            "schema_version": 1,
            "protocol_id": "SYNTHETIC_VINA_PLAN_V1",
            "entries": [
                {
                    "sequence": 1,
                    "target_sequence": 1,
                    "target_id": "SYNTH",
                    "class_label": "active",
                    "class_index": 1,
                    "source_member_path": "source/active.smi",
                    "source_line_number": 1,
                    "source_identifier": "active-1",
                    "source_smiles_sha256": "1" * 64,
                    "canonical_isomeric_smiles_sha256": "2" * 64,
                    "status": "prepared",
                    "prepared": True,
                    "pdbqt": {
                        "size_bytes": ligand_path.stat().st_size,
                        "sha256": hashlib.sha256(ligand_path.read_bytes()).hexdigest(),
                    },
                    "artifacts": [
                        {
                            "stage": "ligand_pdbqt",
                            "path": "target/ligand.pdbqt",
                            "size_bytes": ligand_path.stat().st_size,
                            "sha256": hashlib.sha256(
                                ligand_path.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                },
                {
                    "sequence": 2,
                    "target_sequence": 2,
                    "target_id": "SYNTH",
                    "class_label": "inactive",
                    "class_index": 1,
                    "source_member_path": "source/inactive.smi",
                    "source_line_number": 1,
                    "source_identifier": "inactive-1",
                    "source_smiles_sha256": "3" * 64,
                    "canonical_isomeric_smiles_sha256": "4" * 64,
                    "status": "unresolved_chemical_state",
                    "prepared": False,
                    "error": {
                        "code": "STEREOCHEMISTRY_REQUIRES_DECISION",
                        "stage": "ligand_chemical_state",
                    },
                    "artifacts": [],
                },
            ],
        },
    )
    return {
        "spec": spec,
        "geometry": geometry,
        "receptors": receptors,
        "ligands": ligands,
        "receptor_root": receptor_root,
        "ligand_root": ligand_root,
        "executable": executable,
        "parser_source": parser_source,
        "installation": VinaInstallation(
            executable=str(executable), version="1.2.7"
        ),
    }


def _build(fixture: dict[str, Path | VinaInstallation]) -> dict[str, object]:
    return build_vina_campaign_plan(
        spec_path=fixture["spec"],  # type: ignore[arg-type]
        geometry_manifest_path=fixture["geometry"],  # type: ignore[arg-type]
        final_receptor_manifest_path=fixture["receptors"],  # type: ignore[arg-type]
        ligand_preparation_manifest_path=fixture["ligands"],  # type: ignore[arg-type]
        final_receptor_evidence_root=fixture["receptor_root"],  # type: ignore[arg-type]
        ligand_preparation_evidence_root=fixture["ligand_root"],  # type: ignore[arg-type]
        installation=fixture["installation"],  # type: ignore[arg-type]
        vina_executable_path=fixture["executable"],  # type: ignore[arg-type]
        parser_source_path=fixture["parser_source"],  # type: ignore[arg-type]
        total_cpu_threads=3,
        parallel_ligands=3,
    )


def test_plan_is_deterministic_path_free_and_loss_preserving(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = _build(fixture)
    second = _build(fixture)

    assert first == second
    assert first["totals"] == {
        "target_count": 1,
        "source_parents": 2,
        "prepared_for_docking": 1,
        "retained_unscored_worst_tie": 1,
        "by_class": {"active": 1, "inactive": 1},
        "by_preparation_status": {
            "prepared": 1,
            "unresolved_chemical_state": 1,
        },
    }
    serialized = serialize_vina_campaign_plan(first)
    assert str(tmp_path) not in serialized
    assert "synthetic Vina executable" not in serialized
    entries = first["targets"][0]["entries"]  # type: ignore[index]
    assert entries[0]["docking_disposition"] == "ready"
    assert entries[1]["docking_disposition"] == "retained_unscored_worst_tie"

    output = tmp_path / "plan.json"
    output.write_text(serialized, encoding="utf-8")
    assert verify_vina_campaign_plan(
        output,
        parser_source_path=fixture["parser_source"],  # type: ignore[arg-type]
        vina_executable_path=fixture["executable"],  # type: ignore[arg-type]
        final_receptor_evidence_root=fixture["receptor_root"],  # type: ignore[arg-type]
        ligand_preparation_evidence_root=fixture["ligand_root"],  # type: ignore[arg-type]
    ) == first


def test_plan_rejects_parameter_tampering_even_with_a_new_digest(tmp_path: Path) -> None:
    plan = _build(_fixture(tmp_path))
    plan["parameters"]["exhaustiveness"] = 9  # type: ignore[index]
    plan.pop("manifest_sha256")
    plan["manifest_sha256"] = _digest(plan)
    output = tmp_path / "plan.json"
    output.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkVinaPlanError, match="parameters"):
        verify_vina_campaign_plan(output)


def test_plan_rejects_changed_scientific_input_bytes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _build(fixture)
    output = tmp_path / "plan.json"
    output.write_text(serialize_vina_campaign_plan(plan), encoding="utf-8")
    ligand = fixture["ligand_root"] / "target" / "ligand.pdbqt"  # type: ignore[operator]
    ligand.write_bytes(b"changed ligand\n")

    with pytest.raises(ScreeningBenchmarkVinaPlanError, match="ligand PDBQT.*changed"):
        verify_vina_campaign_plan(
            output,
            ligand_preparation_evidence_root=fixture["ligand_root"],  # type: ignore[arg-type]
        )


def test_recorded_primary_plan_closes_before_any_score_is_seen() -> None:
    plan = verify_vina_campaign_plan(REAL_PLAN, parser_source_path=REAL_PARSER)

    assert plan["scores_seen"] is False
    assert plan["engine"] == {
        "name": "AutoDock Vina",
        "version": "1.2.7",
        "executable_filename": "vina_1.2.7_win.exe",
        "executable_size_bytes": 1233920,
        "executable_sha256": (
            "e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5"
        ),
        "score_field": "affinity_kcal_mol",
        "score_direction": "lower_is_better",
    }
    assert plan["parameters"] == {
        "sampling_protocol": "screening",
        "total_cpu_threads": 15,
        "parallel_ligands": 15,
        "seed": 20260911,
        "exhaustiveness": 8,
        "num_modes": 9,
        "min_rmsd_angstrom": 1.0,
        "energy_range_kcal_mol": 3.0,
        "timeout_minutes_per_ligand": 360,
        "threads_per_ligand": 1,
    }
    assert plan["totals"] == {
        "target_count": 3,
        "source_parents": 11412,
        "prepared_for_docking": 11302,
        "retained_unscored_worst_tie": 110,
        "by_class": {"active": 176, "inactive": 11236},
        "by_preparation_status": {
            "preparation_failed": 3,
            "prepared": 11302,
            "unresolved_chemical_state": 107,
        },
    }
    assert plan["execution_policy"]["docking_executed"] is False
    assert plan["execution_policy"]["scores_or_metrics_computed"] is False
