"""Synthetic contracts for the frozen benchmark ligand-preparation plan."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from ankora_backend.validation.screening_benchmark_ligand_plan import (
    ScreeningBenchmarkLigandPlanError,
    build_ligand_preparation_plan,
    serialize_ligand_preparation_plan,
    verify_ligand_preparation_plan,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_PLAN = (
    PROJECT_ROOT
    / "docs"
    / "validation"
    / "reference_cases"
    / "LIT_PCBA_ANKORA_VS_V1.ligand-preparation-plan.json"
)


def _canonical_digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_archive(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = "LIT-PCBA_SYNTHETIC/SYNTH"
    files = {
        f"{root}/active_T.smi": b"CCO active-1\n",
        f"{root}/active_V.smi": b"CCN active-2\n",
        f"{root}/inactive_T.smi": b"CCC inactive-1\n",
        f"{root}/inactive_V.smi": b"CCCl inactive-2\n",
    }
    archive = tmp_path / "synthetic.tar.gz"
    _write_archive(archive, files)
    target_members = [
        {
            "path": name,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for name, content in files.items()
    ]
    manifest: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_LIGAND_PLAN_V1",
        "source": {
            "filename": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
        "targets": [
            {
                "target_id": "SYNTH",
                "source_directory": "SYNTH",
                "source_census": {"active_rows": 2, "inactive_rows": 2},
                "members": target_members,
            }
        ],
        "totals": {
            "target_count": 1,
            "evaluation_active_units": 2,
            "evaluation_inactive_units": 2,
        },
    }
    manifest["manifest_sha256"] = _canonical_digest(manifest)
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(manifest), encoding="utf-8")
    return archive, inputs


def test_plan_is_deterministic_loss_preserving_and_does_not_copy_smiles(
    tmp_path: Path,
) -> None:
    archive, inputs = _fixture(tmp_path)
    first = build_ligand_preparation_plan(
        archive=archive,
        input_manifest_path=inputs,
    )
    second = build_ligand_preparation_plan(
        archive=archive,
        input_manifest_path=inputs,
    )

    assert first == second
    assert first["totals"] == {
        "target_count": 1,
        "active_parents": 2,
        "inactive_parents": 2,
        "all_parents": 4,
    }
    parents = first["targets"][0]["parents"]
    assert [item["sequence"] for item in parents] == [1, 2, 3, 4]
    assert len({item["conformer_seed"] for item in parents}) == 4
    serialized = serialize_ligand_preparation_plan(first)
    assert "CCO" not in serialized
    assert "CCCl" not in serialized
    assert str(tmp_path) not in serialized

    path = tmp_path / "plan.json"
    path.write_text(serialized, encoding="utf-8")
    assert (
        verify_ligand_preparation_plan(
            path,
            archive=archive,
            input_manifest_path=inputs,
        )
        == first
    )


def test_plan_rejects_a_duplicate_canonical_parent(tmp_path: Path) -> None:
    archive, inputs = _fixture(tmp_path)
    root = "LIT-PCBA_SYNTHETIC/SYNTH"
    duplicate_files = {
        f"{root}/active_T.smi": b"CCO active-1\n",
        f"{root}/active_V.smi": b"OCC active-2\n",
        f"{root}/inactive_T.smi": b"CCC inactive-1\n",
        f"{root}/inactive_V.smi": b"CCCl inactive-2\n",
    }
    _write_archive(archive, duplicate_files)
    raw = json.loads(inputs.read_text(encoding="utf-8"))
    raw["source"]["size_bytes"] = archive.stat().st_size
    raw["source"]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    for member in raw["targets"][0]["members"]:
        content = duplicate_files[member["path"]]
        member["size_bytes"] = len(content)
        member["sha256"] = hashlib.sha256(content).hexdigest()
    raw.pop("manifest_sha256")
    raw["manifest_sha256"] = _canonical_digest(raw)
    inputs.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkLigandPlanError, match="more than once"):
        build_ligand_preparation_plan(
            archive=archive,
            input_manifest_path=inputs,
        )


def test_plan_verifier_rejects_changed_execution_boundary(tmp_path: Path) -> None:
    archive, inputs = _fixture(tmp_path)
    plan = build_ligand_preparation_plan(
        archive=archive,
        input_manifest_path=inputs,
    )
    plan["execution_policy"]["docking_executed"] = True
    plan.pop("manifest_sha256")
    plan["manifest_sha256"] = _canonical_digest(plan)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkLigandPlanError, match="boundary"):
        verify_ligand_preparation_plan(path)


def test_recorded_plan_retains_all_source_parents_before_results() -> None:
    plan = verify_ligand_preparation_plan(REAL_PLAN)

    assert plan["totals"] == {
        "target_count": 3,
        "active_parents": 176,
        "inactive_parents": 11236,
        "all_parents": 11412,
    }
    assert plan["chemical_state_policy"]["primary_state"] == "exact_imported_state"
    assert plan["execution_policy"]["docking_executed"] is False
    assert plan["execution_policy"]["scores_or_metrics_computed"] is False
