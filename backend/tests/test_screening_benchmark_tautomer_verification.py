"""Synthetic contracts for exact TP53 histidine-tautomer verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import ankora_backend.validation.screening_benchmark_tautomer_verification as verification
from ankora_backend.validation.screening_benchmark_tautomer_verification import (
    ScreeningBenchmarkTautomerVerificationError,
    run_screening_benchmark_tautomer_verification,
    verify_tautomer_verification_manifest,
    verify_tautomer_verification_spec,
)


def _spec(path: Path) -> dict[str, object]:
    entries = []
    for role, pdb_id in (("primary", "3zme"), ("alternate", "5o1i")):
        entries.append(
            {
                "target_id": "TP53",
                "role": role,
                "pdb_id": pdb_id,
                "override": {
                    "residue": {
                        "chain_id": "A",
                        "residue_name": "HIS",
                        "sequence_number": 179,
                        "insertion_code": "",
                    },
                    "state": "HIE",
                },
                "selection_basis": "Synthetic zinc-contact evidence.",
            }
        )
    value: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_TAUTOMER_V1",
        "verification_id": "SYNTHETIC_TP53_HIE_V1",
        "scores_seen": False,
        "source_receptor_plan_manifest_sha256": "a" * 64,
        "source_protonation_preview_manifest_sha256": "b" * 64,
        "templates": entries,
    }
    value["spec_sha256"] = verification._digest(value)
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def _plans() -> dict[str, object]:
    return {
        "manifest_sha256": "a" * 64,
        "targets": [
            {
                "target_id": "TP53",
                "primary_template": {
                    "role": "primary",
                    "pdb_id": "3zme",
                    "preparation_request": {},
                },
                "alternate_template": {
                    "role": "alternate",
                    "pdb_id": "5o1i",
                    "preparation_request": {},
                },
            }
        ],
    }


def _executor(
    task: dict[str, object], _structures: Path, output_root: Path
) -> dict[str, object]:
    sequence = int(task["sequence"])
    task_root = output_root / f"{sequence:02d}-TP53-{task['role']}-{task['pdb_id']}"
    task_root.mkdir()
    evidence = task_root / "synthetic-output.pqr"
    evidence.write_text("SYNTHETIC HIE OUTPUT\n", encoding="utf-8")
    return {
        "sequence": sequence,
        "target_id": "TP53",
        "role": task["role"],
        "pdb_id": task["pdb_id"],
        "status": "completed",
        "requested_state": "HIE",
        "output_state": "HIE",
        "ring_hydrogen": "HE2",
        "coordinating_atom_left_unprotonated": "ND1",
        "raw_evidence_files": [
            {
                "path": evidence.relative_to(output_root).as_posix(),
                "size_bytes": evidence.stat().st_size,
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            }
        ],
        "final_receptor_created": False,
        "final_pdbqt_created": False,
    }


def test_tautomer_verification_is_pre_result_create_only_and_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "spec.json"
    _spec(spec_path)
    monkeypatch.setattr(
        verification, "verify_receptor_plan_manifest", lambda **_kwargs: _plans()
    )
    monkeypatch.setattr(
        verification,
        "verify_protonation_preview_manifest",
        lambda _path: {"manifest_sha256": "b" * 64},
    )
    output = tmp_path / "evidence"
    public = tmp_path / "manifest.json"

    manifest = run_screening_benchmark_tautomer_verification(
        spec_path=spec_path,
        archive=tmp_path / "archive.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        protonation_preview_manifest_path=tmp_path / "previews.json",
        structures_dir=tmp_path / "structures",
        output_root=output,
        public_manifest_path=public,
        worker_limit=2,
        _task_executor=_executor,
    )

    assert manifest["scores_seen"] is False
    assert manifest["execution_policy"]["worker_count"] == 2
    assert manifest["verification_census"] == {
        "requested": 2,
        "completed": 2,
        "failed": 0,
    }
    assert manifest["scientist_review"]["status"] == "pending"
    assert str(tmp_path) not in public.read_text(encoding="utf-8")
    assert verify_tautomer_verification_manifest(
        public,
        evidence_root=output,
        expected_spec_sha256=manifest["spec_sha256"],
    ) == manifest

    with pytest.raises(
        ScreeningBenchmarkTautomerVerificationError, match="frozen request"
    ):
        verify_tautomer_verification_manifest(
            public,
            expected_spec_sha256="c" * 64,
        )

    with pytest.raises(
        ScreeningBenchmarkTautomerVerificationError, match="create-only"
    ):
        run_screening_benchmark_tautomer_verification(
            spec_path=spec_path,
            archive=tmp_path / "archive.tar.gz",
            structure_manifest_path=tmp_path / "structures.json",
            receptor_plan_manifest_path=tmp_path / "plans.json",
            protonation_preview_manifest_path=tmp_path / "previews.json",
            structures_dir=tmp_path / "structures",
            output_root=output,
            public_manifest_path=tmp_path / "other.json",
            _task_executor=_executor,
        )


def test_tautomer_spec_rejects_non_hie_or_post_score_choice(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    value = _spec(path)
    value["scores_seen"] = True
    payload = dict(value)
    payload.pop("spec_sha256")
    value["spec_sha256"] = verification._digest(payload)
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        ScreeningBenchmarkTautomerVerificationError, match="before docking scores"
    ):
        verify_tautomer_verification_spec(path)


def test_tautomer_manifest_rejects_changed_raw_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "spec.json"
    _spec(spec_path)
    monkeypatch.setattr(
        verification, "verify_receptor_plan_manifest", lambda **_kwargs: _plans()
    )
    monkeypatch.setattr(
        verification,
        "verify_protonation_preview_manifest",
        lambda _path: {"manifest_sha256": "b" * 64},
    )
    output = tmp_path / "evidence"
    public = tmp_path / "manifest.json"
    manifest = run_screening_benchmark_tautomer_verification(
        spec_path=spec_path,
        archive=tmp_path / "archive.tar.gz",
        structure_manifest_path=tmp_path / "structures.json",
        receptor_plan_manifest_path=tmp_path / "plans.json",
        protonation_preview_manifest_path=tmp_path / "previews.json",
        structures_dir=tmp_path / "structures",
        output_root=output,
        public_manifest_path=public,
        _task_executor=_executor,
    )
    first = manifest["previews"][0]["raw_evidence_files"][0]["path"]
    (output / first).write_text("CHANGED\n", encoding="utf-8")

    with pytest.raises(
        ScreeningBenchmarkTautomerVerificationError, match="evidence changed"
    ):
        verify_tautomer_verification_manifest(public, evidence_root=output)
