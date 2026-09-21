"""Synthetic contracts for accepted final benchmark receptor production."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import ankora_backend.validation.screening_benchmark_final_receptors as final_receptors
from ankora_backend.validation.screening_benchmark_final_receptors import (
    ScreeningBenchmarkFinalReceptorError,
    run_screening_benchmark_final_receptors,
    verify_final_receptor_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINAL_RECEPTOR_MANIFEST_PATH = (
    PROJECT_ROOT
    / "docs"
    / "validation"
    / "reference_cases"
    / "LIT_PCBA_ANKORA_VS_V1.final-receptors.json"
)
ACCEPTED_REVIEW_SHA256 = "4d01857a5ef7df41eeb8a81ffd76a32d1d0292057562323e16dbd42d6c7743f4"


def _plans() -> dict[str, object]:
    targets: list[dict[str, object]] = []
    for target_index in range(3):
        target: dict[str, object] = {"target_id": f"SYNTHETIC_{target_index + 1}"}
        for key, role in (
            ("primary_template", "primary"),
            ("alternate_template", "alternate"),
        ):
            target[key] = {
                "role": role,
                "pdb_id": f"{target_index + 1}{role[0]}aa",
                "preparation_request": {},
            }
        targets.append(target)
    return {
        "protocol_id": "SYNTHETIC_FINAL_RECEPTORS_V1",
        "manifest_sha256": "a" * 64,
        "targets": targets,
    }


def _previews(plans: dict[str, object]) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for target in plans["targets"]:  # type: ignore[index]
        for key in ("primary_template", "alternate_template"):
            template = target[key]  # type: ignore[index]
            items.append(
                {
                    "target_id": target["target_id"],  # type: ignore[index]
                    "role": template["role"],  # type: ignore[index]
                    "pdb_id": template["pdb_id"],  # type: ignore[index]
                    "proposals": [
                        {
                            "proposal_id": "A|HIS|1||HIS 1 A",
                            "residue": {
                                "chain_id": "A",
                                "residue_name": "HIS",
                                "sequence_number": 1,
                                "insertion_code": "",
                            },
                            "default_state": "HID",
                        }
                    ],
                }
            )
    return {
        "manifest_sha256": "b" * 64,
        "source_receptor_plan_manifest_sha256": "a" * 64,
        "previews": items,
    }


def _review() -> dict[str, object]:
    return {
        "review_sha256": "c" * 64,
        "proposed_overrides": [],
        "decision_census": {
            "templates": 6,
            "source_proposals": 6,
            "accepted_by_default_policy": 6,
            "explicit_overrides": 0,
        },
    }


def _executor(task: dict[str, object], _structures: Path, output_root: Path) -> dict[str, object]:
    sequence = int(task["sequence"])
    task_root = output_root / f"{sequence:02d}-{task['target_id']}-{task['role']}-{task['pdb_id']}"
    task_root.mkdir()
    pdb = task_root / "protonated_receptor.pdb"
    pqr = task_root / "protonated_receptor.pqr"
    meeko_input = task_root / "meeko_input_receptor.pqr"
    pdbqt = task_root / "prepared_receptor.pdbqt"
    selected = task_root / "selected_receptor.pdb"
    record = task_root / "record.json"
    selected.write_text("SYNTHETIC SELECTED\n", encoding="utf-8")
    pdb.write_text("SYNTHETIC PROTONATED\n", encoding="utf-8")
    pqr.write_text("SYNTHETIC PQR\n", encoding="utf-8")
    meeko_input.write_text("SYNTHETIC MEEKO INPUT\n", encoding="utf-8")
    pdbqt.write_text(
        "ATOM      1  C   SYN A   1       0.000   0.000   0.000  0.00  0.00     0.000 C\n",
        encoding="utf-8",
    )
    record.write_text("{}\n", encoding="utf-8")
    paths = [selected, pdb, pqr, meeko_input, pdbqt, record]
    stage_paths = [
        ("selected", selected),
        ("protonated_pdb", pdb),
        ("protonated_pqr", pqr),
        ("meeko_input_pqr", meeko_input),
        ("pdbqt", pdbqt),
    ]
    return {
        "sequence": sequence,
        "target_id": task["target_id"],
        "role": task["role"],
        "pdb_id": task["pdb_id"],
        "status": "completed",
        "final_status": "docking_ready",
        "final_record_path": record.relative_to(output_root).as_posix(),
        "final_record_sha256": hashlib.sha256(record.read_bytes()).hexdigest(),
        "proposal_count": len(task["accepted_decisions"]),
        "explicit_override_count": len(task["overrides"]),
        "receptor_atom_types": ["C"],
        "outputs": [
            {
                "stage": stage,
                "filename": path.name,
                "path": path.relative_to(output_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for stage, path in stage_paths
        ],
        "raw_evidence_files": [
            {
                "path": path.relative_to(output_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
        ],
        "final_receptor_created": True,
        "final_pdbqt_created": True,
        "docking_executed": False,
    }


def _patch_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    plans = _plans()
    monkeypatch.setattr(final_receptors, "verify_receptor_plan_manifest", lambda **_kwargs: plans)
    monkeypatch.setattr(
        final_receptors,
        "verify_protonation_preview_manifest",
        lambda _path: _previews(plans),
    )
    monkeypatch.setattr(
        final_receptors,
        "verify_protonation_decision_review",
        lambda *_args, **_kwargs: _review(),
    )


def test_final_receptors_are_parallel_create_only_and_path_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_sources(monkeypatch)
    output = tmp_path / "final-evidence"
    public = tmp_path / "final-receptors.json"
    manifest = run_screening_benchmark_final_receptors(
        archive=tmp_path / "source.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        protonation_preview_manifest_path=tmp_path / "previews.json",
        tautomer_manifest_path=tmp_path / "tautomers.json",
        protonation_decision_review_path=tmp_path / "decisions.json",
        structures_dir=tmp_path / "structures",
        output_root=output,
        public_manifest_path=public,
        worker_limit=3,
        _task_executor=_executor,
    )

    assert manifest["execution_policy"]["worker_count"] == 3
    assert manifest["receptor_census"] == {
        "requested": 6,
        "completed": 6,
        "failed": 0,
        "docking_ready": 6,
        "pdbqt_created": 6,
    }
    assert manifest["execution_policy"]["docking_executed"] is False
    assert str(tmp_path) not in public.read_text(encoding="utf-8")
    assert (
        verify_final_receptor_manifest(
            public,
            evidence_root=output,
            expected_decision_review_sha256="c" * 64,
        )
        == manifest
    )

    with pytest.raises(ScreeningBenchmarkFinalReceptorError, match="create-only"):
        run_screening_benchmark_final_receptors(
            archive=tmp_path / "source.tar.gz",
            structure_manifest_path=tmp_path / "structures.json",
            receptor_plan_manifest_path=tmp_path / "plans.json",
            protonation_preview_manifest_path=tmp_path / "previews.json",
            tautomer_manifest_path=tmp_path / "tautomers.json",
            protonation_decision_review_path=tmp_path / "decisions.json",
            structures_dir=tmp_path / "structures",
            output_root=output,
            public_manifest_path=tmp_path / "another.json",
            _task_executor=_executor,
        )


def test_final_receptor_verifier_rejects_changed_pdbqt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_sources(monkeypatch)
    output = tmp_path / "final-evidence"
    public = tmp_path / "final-receptors.json"
    manifest = run_screening_benchmark_final_receptors(
        archive=tmp_path / "source.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        protonation_preview_manifest_path=tmp_path / "previews.json",
        tautomer_manifest_path=tmp_path / "tautomers.json",
        protonation_decision_review_path=tmp_path / "decisions.json",
        structures_dir=tmp_path / "structures",
        output_root=output,
        public_manifest_path=public,
        _task_executor=_executor,
    )
    pdbqt = next(item for item in manifest["receptors"][0]["outputs"] if item["stage"] == "pdbqt")
    (output / pdbqt["path"]).write_text("CHANGED\n", encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkFinalReceptorError, match="(size|SHA-256) changed"):
        verify_final_receptor_manifest(public, evidence_root=output)


def test_final_receptor_verifier_rejects_an_absolute_public_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_sources(monkeypatch)
    public = tmp_path / "final-receptors.json"
    manifest = run_screening_benchmark_final_receptors(
        archive=tmp_path / "source.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        protonation_preview_manifest_path=tmp_path / "previews.json",
        tautomer_manifest_path=tmp_path / "tautomers.json",
        protonation_decision_review_path=tmp_path / "decisions.json",
        structures_dir=tmp_path / "structures",
        output_root=tmp_path / "final-evidence",
        public_manifest_path=public,
        _task_executor=_executor,
    )
    manifest["receptors"][0]["final_record_path"] = "//server/share/record.json"
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    manifest["manifest_sha256"] = final_receptors._digest(payload)
    public.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkFinalReceptorError, match="unsafe path"):
        verify_final_receptor_manifest(public)


def test_recorded_decisions_must_match_written_states() -> None:
    accepted = [
        {
            "proposal_id": "A|HIS|1||HIS 1 A",
            "residue": {
                "chain_id": "A",
                "residue_name": "HIS",
                "sequence_number": 1,
                "insertion_code": "",
            },
            "source_default_state": "HID",
            "selected_state": "HIE",
            "decision_source": "scientist_override",
        }
    ]
    proposal = final_receptors.ReceptorProtonationProposal.model_validate(
        {
            "proposal_id": "A|HIS|1||HIS 1 A",
            "residue": accepted[0]["residue"],
            "group_label": "HIS 1 A",
            "predicted_pka": 6.0,
            "predicted_state": "HID",
            "default_state": "HID",
            "selected_state": "HIE",
            "output_state": "HID",
            "allowed_states": ["HID", "HIE"],
            "decision_source": "scientist_override",
        }
    )

    with pytest.raises(
        ScreeningBenchmarkFinalReceptorError,
        match="does not reproduce the written histidine state",
    ):
        final_receptors._verify_recorded_decisions(accepted, [proposal])


def test_recorded_final_receptors_match_the_accepted_pre_result_review() -> None:
    manifest = verify_final_receptor_manifest(
        FINAL_RECEPTOR_MANIFEST_PATH,
        expected_decision_review_sha256=ACCEPTED_REVIEW_SHA256,
    )

    assert manifest["manifest_sha256"] == (
        "b617361c059c9c07b27010c34a3429a86eec355ecd6e27fe69172a7642a1636e"
    )
    assert manifest["scores_seen"] is False
    assert manifest["decision_census"] == {
        "templates": 6,
        "source_proposals": 449,
        "accepted_by_default_policy": 443,
        "explicit_overrides": 6,
    }
    assert manifest["receptor_census"] == {
        "requested": 6,
        "completed": 6,
        "failed": 0,
        "docking_ready": 6,
        "pdbqt_created": 6,
    }
    assert [item["pdb_id"] for item in manifest["receptors"]] == [
        "5ufx",
        "2iog",
        "3b1m",
        "5y2t",
        "3zme",
        "5o1i",
    ]
    assert [item["explicit_override_count"] for item in manifest["receptors"]] == [
        0,
        0,
        0,
        0,
        3,
        3,
    ]
