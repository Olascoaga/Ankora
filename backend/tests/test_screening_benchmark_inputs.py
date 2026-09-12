"""Synthetic archive tests for the point-26 source-acquisition gate.

These tiny archives exercise provenance and census checks only.  They are not
LIT-PCBA data and provide no evidence about virtual-screening performance.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from ankora_backend.validation.screening_benchmark_inputs import (
    ScreeningBenchmarkInputError,
    inspect_lit_pcba_archive,
    serialize_input_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _target(
    target_id: str, *, active: int, inactive: int, templates: int
) -> dict[str, object]:
    return {
        "target_id": target_id,
        "source_directory": target_id,
        "pubchem_aid": 100,
        "reported_actives": active,
        "reported_inactives": inactive,
        "reported_templates": templates,
    }


def _write_spec(
    path: Path,
    targets: list[dict[str, object]],
    *,
    archive: Path,
    active_files: tuple[str, ...] = ("active.smi",),
    inactive_files: tuple[str, ...] = ("inactive.smi",),
) -> None:
    if archive.exists():
        archive_size = archive.stat().st_size
        archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    else:
        archive_size = 0
        archive_sha256 = "0" * 64
    path.write_text(
        json.dumps(
            {
                "protocol_id": "SYNTHETIC_LIT_PCBA_GATE_V1",
                "primary_evidence": {
                    "dataset_page": "https://example.invalid/synthetic",
                    "publication_doi": "10.0000/synthetic",
                    "source_archive": {
                        "filename": archive.name,
                        "size_bytes": archive_size,
                        "sha256": archive_sha256,
                    },
                    "source_layout": {
                        "active_files": list(active_files),
                        "inactive_files": list(inactive_files),
                    },
                    "targets": targets,
                },
            }
        ),
        encoding="utf-8",
    )


def _add_member(archive: tarfile.TarFile, name: str, content: str) -> None:
    payload = content.encode("utf-8")
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mtime = 0
    archive.addfile(member, io.BytesIO(payload))


def _write_archive(path: Path, members: dict[str, str]) -> None:
    with tarfile.open(path, mode="w") as archive:
        for name, content in members.items():
            _add_member(archive, name, content)


def _valid_members() -> dict[str, str]:
    return {
        "source/TARGET_A/active.smi": "CCO active-1\nOCC active-duplicate\nCCC active-2\n",
        "source/TARGET_A/inactive.smi": "CCN inactive-1\nCCO conflicting-label\n",
        "source/TARGET_A/TEMPLATE_1_protein.mol2": "synthetic receptor 1\n",
        "source/TARGET_A/TEMPLATE_1_ligand.mol2": "synthetic ligand 1\n",
        "source/TARGET_A/TEMPLATE_2_protein.mol2": "synthetic receptor 2\n",
        "source/TARGET_A/TEMPLATE_2_ligand.mol2": "synthetic ligand 2\n",
        "source/TARGET_B/active.smi": "c1ccccc1 active-1\n",
        "source/TARGET_B/inactive.smi": "C inactive-1\n",
        "source/TARGET_B/TEMPLATE_3_protein.mol2": "synthetic receptor 3\n",
        "source/TARGET_B/TEMPLATE_3_ligand.mol2": "synthetic ligand 3\n",
    }


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / "synthetic.spec.json"
    archive = tmp_path / "synthetic.tar"
    return spec, archive


def _write_default_spec(spec: Path, archive: Path) -> None:
    _write_spec(
        spec,
        [
            _target("TARGET_A", active=3, inactive=2, templates=2),
            _target("TARGET_B", active=1, inactive=1, templates=1),
        ],
        archive=archive,
    )


def test_source_manifest_is_deterministic_path_free_and_loss_accounted(
    tmp_path: Path,
) -> None:
    spec, archive = _paths(tmp_path)
    _write_archive(archive, _valid_members())
    _write_default_spec(spec, archive)

    first = inspect_lit_pcba_archive(archive=archive, spec_path=spec)
    second = inspect_lit_pcba_archive(archive=archive, spec_path=spec)

    assert first == second
    assert first["source"] == {
        "filename": "synthetic.tar",
        "size_bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "dataset_page": "https://example.invalid/synthetic",
        "publication_doi": "10.0000/synthetic",
    }
    assert first["totals"] == {
        "target_count": 2,
        "active_rows": 4,
        "inactive_rows": 3,
        "evaluation_active_units": 2,
        "evaluation_inactive_units": 2,
    }
    target_a = first["targets"][0]
    assert target_a["template_ids"] == ["TEMPLATE_1", "TEMPLATE_2"]
    assert target_a["canonicalization"] == {
        "method": (
            "RDKit canonical isomeric SMILES after ordinary sanitization; "
            "no uncharging, tautomerization, or fragment removal"
        ),
        "active_unique_keys": 1,
        "inactive_unique_keys": 1,
        "active_duplicate_rows": 1,
        "inactive_duplicate_rows": 0,
        "active_unparsed_rows": 0,
        "inactive_unparsed_rows": 0,
        "cross_class_conflict_keys": ["CCO"],
        "cross_class_conflict_active_rows": 2,
        "cross_class_conflict_inactive_rows": 1,
        "evaluation_active_units": 1,
        "evaluation_inactive_units": 1,
    }
    assert str(tmp_path) not in serialize_input_manifest(first)
    manifest_without_identity = dict(first)
    manifest_identity = manifest_without_identity.pop("manifest_sha256")
    canonical = json.dumps(
        manifest_without_identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert manifest_identity == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize(
    ("active_count", "template_count", "message"),
    [
        (4, 2, "census differs"),
        (3, 3, "template census differs"),
    ],
)
def test_source_census_must_match_the_frozen_protocol(
    tmp_path: Path,
    active_count: int,
    template_count: int,
    message: str,
) -> None:
    spec, archive = _paths(tmp_path)
    _write_archive(archive, _valid_members())
    _write_spec(
        spec,
        [
            _target(
                "TARGET_A",
                active=active_count,
                inactive=2,
                templates=template_count,
            ),
            _target("TARGET_B", active=1, inactive=1, templates=1),
        ],
        archive=archive,
    )

    with pytest.raises(ScreeningBenchmarkInputError, match=message):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)


def test_split_training_and_validation_files_form_one_exact_population(
    tmp_path: Path,
) -> None:
    spec, archive = _paths(tmp_path)
    members = {
        name: content
        for name, content in _valid_members().items()
        if not name.endswith(("active.smi", "inactive.smi"))
    }
    members.update(
        {
            "source/TARGET_A/active_T.smi": "CCO active-1\nOCC duplicate\n",
            "source/TARGET_A/active_V.smi": "CCC active-2\n",
            "source/TARGET_A/inactive_T.smi": "CCN inactive-1\n",
            "source/TARGET_A/inactive_V.smi": "CCO conflicting-label\n",
            "source/TARGET_B/active_T.smi": "c1ccccc1 active-1\n",
            "source/TARGET_B/active_V.smi": "",
            "source/TARGET_B/inactive_T.smi": "C inactive-1\n",
            "source/TARGET_B/inactive_V.smi": "",
        }
    )
    _write_archive(archive, members)
    _write_spec(
        spec,
        [
            _target("TARGET_A", active=3, inactive=2, templates=2),
            _target("TARGET_B", active=1, inactive=1, templates=1),
        ],
        archive=archive,
        active_files=("active_T.smi", "active_V.smi"),
        inactive_files=("inactive_T.smi", "inactive_V.smi"),
    )

    manifest = inspect_lit_pcba_archive(archive=archive, spec_path=spec)

    assert manifest["totals"]["active_rows"] == 4
    assert manifest["totals"]["inactive_rows"] == 3
    target_a_paths = [member["path"] for member in manifest["targets"][0]["members"]]
    assert target_a_paths[:4] == [
        "source/TARGET_A/active_T.smi",
        "source/TARGET_A/active_V.smi",
        "source/TARGET_A/inactive_T.smi",
        "source/TARGET_A/inactive_V.smi",
    ]


def test_archive_identity_must_match_the_frozen_source(tmp_path: Path) -> None:
    spec, archive = _paths(tmp_path)
    _write_archive(archive, _valid_members())
    _write_default_spec(spec, archive)
    with archive.open("ab") as changed:
        changed.write(b"post-freeze change")

    with pytest.raises(ScreeningBenchmarkInputError, match="SHA-256"):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)


def test_amendment_identity_and_pre_result_claim_must_be_verifiable(
    tmp_path: Path,
) -> None:
    spec, archive = _paths(tmp_path)
    amendment = tmp_path / "amendment-001.json"
    _write_archive(archive, _valid_members())
    _write_default_spec(spec, archive)
    amendment.write_text(
        json.dumps(
            {
                "amendment_id": "001",
                "protocol_id": "SYNTHETIC_LIT_PCBA_GATE_V1",
                "invariants": {"scores_seen": False},
            }
        ),
        encoding="utf-8",
    )
    frozen_spec = json.loads(spec.read_text(encoding="utf-8"))
    frozen_spec["amendments"] = [
        {
            "amendment_id": "001",
            "path": amendment.name,
            "sha256": hashlib.sha256(amendment.read_bytes()).hexdigest(),
        }
    ]
    spec.write_text(json.dumps(frozen_spec), encoding="utf-8")

    manifest = inspect_lit_pcba_archive(archive=archive, spec_path=spec)
    assert manifest["amendments"] == frozen_spec["amendments"]

    amendment.write_text("{}", encoding="utf-8")
    with pytest.raises(ScreeningBenchmarkInputError, match="frozen SHA-256"):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)


def test_unpaired_templates_are_rejected(tmp_path: Path) -> None:
    spec, archive = _paths(tmp_path)
    members = _valid_members()
    del members["source/TARGET_A/TEMPLATE_2_ligand.mol2"]
    _write_archive(archive, members)
    _write_default_spec(spec, archive)

    with pytest.raises(ScreeningBenchmarkInputError, match="do not pair exactly"):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)


def test_archive_member_path_traversal_is_rejected(tmp_path: Path) -> None:
    spec, archive = _paths(tmp_path)
    members = _valid_members()
    members["../outside.txt"] = "synthetic traversal payload\n"
    _write_archive(archive, members)
    _write_default_spec(spec, archive)

    with pytest.raises(ScreeningBenchmarkInputError, match="escapes its source root"):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)


def test_missing_and_unreadable_archives_fail_closed(tmp_path: Path) -> None:
    spec, archive = _paths(tmp_path)
    _write_default_spec(spec, archive)

    with pytest.raises(ScreeningBenchmarkInputError, match="unavailable"):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)

    archive.write_text("not a tar archive", encoding="utf-8")
    _write_default_spec(spec, archive)
    with pytest.raises(ScreeningBenchmarkInputError, match="not a readable tar"):
        inspect_lit_pcba_archive(archive=archive, spec_path=spec)


def test_cli_creates_once_and_then_verifies_the_exact_manifest(tmp_path: Path) -> None:
    spec, archive = _paths(tmp_path)
    manifest = tmp_path / "input-manifest.json"
    _write_archive(archive, _valid_members())
    _write_default_spec(spec, archive)
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "inspect_screening_benchmark_source.py"),
        "--spec",
        str(spec),
        "--archive",
        str(archive),
        "--manifest",
        str(manifest),
    ]

    created = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checked = subprocess.run(
        [*command, "--check"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    overwrite = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert created.returncode == 0, created.stderr
    assert checked.returncode == 0, checked.stderr
    assert overwrite.returncode != 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["result_status"] == (
        "inputs_inspected_no_docking_executed"
    )
