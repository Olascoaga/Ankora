"""M1a engineering checks using synthetic ligands and the recorded Gate 0 expectations."""

import json
from base64 import b64decode
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdkit import Chem, rdBase

from ankora_backend.adapters.engines.autodock4 import preflight_autodock4_cpu_atom_types
from ankora_backend.adapters.tools.ligand_preparation import (
    parse_ligand_pdbqt_summary,
    precheck_ligand_smarts_rigidification,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandChargeModel,
    LigandPdbqtRecord,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.schemas.v02_contracts import LigandFlexibilitySpec, MacrocyclePolicy
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.ligand_import import import_local_ligand
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt

SYNTHETIC_M1A_AMIDE = "CC(=O)NCc1ccc(CCC)cc1"
SYNTHETIC_M1A_MACROCYCLE = "O=C1CCCCCCCCCCCCO1"
MATCHING_SMARTS = "[c:1]-[CH2:2]-[CH2:3]-[CH3:4]"
UNMATCHED_SMARTS = "[#16]-[CH3]"


def test_v01_prepare_request_and_shared_refinement_option() -> None:
    request = PrepareLigandPdbqtRequest.model_validate({"charge_model": "gasteiger"})
    assert request.charge_model is LigandChargeModel.GASTEIGER
    assert request.flexibility is None
    refinement = PrepareLigandPdbqtRequest.model_validate(
        {"flexibility": {"local_only_refinement": True}}
    )
    assert refinement.flexibility is not None and refinement.flexibility.local_only_refinement


@pytest.mark.parametrize("smarts,indices", [(["CC"], []), ([], [[1, 2]])])
def test_request_rejects_unpaired_rigidification(
    smarts: list[str], indices: list[list[int]]
) -> None:
    with pytest.raises(ValidationError, match="exactly one bond-index pair"):
        PrepareLigandPdbqtRequest.model_validate(
            {"flexibility": {"rigidified_smarts": smarts, "rigidified_bond_indices": indices}}
        )


def test_deserializes_v01_persisted_pdbqt_record() -> None:
    record = LigandPdbqtRecord.model_validate_json(
        """{
            "artifact": {
                "preparation_id": "synthetic-preparation", "ligand_id": "synthetic-ligand",
                "conformer_id": "synthetic-conformer", "filename": "synthetic.pdbqt",
                "format": "pdbqt", "size_bytes": 1, "created_at": "2026-11-18T00:00:00Z",
                "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
            },
            "charge_model": "gasteiger",
            "tool": {"name": "Meeko ligand preparation", "version": "0.7.1"},
            "command": ["mk_prepare_ligand"], "stdout": "", "stderr": "",
            "provenance": {
                "event_id": "synthetic-event", "event_type": "ligand_pdbqt_prepared",
                "timestamp": "2026-11-18T00:00:00Z",
                "tool": {"name": "Meeko ligand preparation", "version": "0.7.1"}
            },
            "content_url": "/ligands/synthetic-ligand/preparations/synthetic-preparation/content"
        }"""
    )
    assert record.flexibility is None
    assert record.effective_torsdof is None
    assert record.atom_types == record.warnings == record.smarts_rigidification_outcomes == []


def test_parse_pdbqt_summary_returns_unique_sorted_atom_types_and_torsdof() -> None:
    content = (
        b"REMARK synthetic PDBQT parser fixture \xff\n"
        b"ROOT\n"
        b"ATOM      1  O   UNL     1       0.000   0.000   0.000  1.00  0.00    -0.200 OA\n"
        b"HETATM    2  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.200 C\n"
        b"ATOM      3  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
        b"ENDROOT\nTORSDOF  2\r\nTORSDOF 2\n"
    )
    assert parse_ligand_pdbqt_summary(content) == (2, ["C", "OA"])


@pytest.mark.parametrize(
    "torsdof_records",
    [b"REMARK TORSDOF 2", b"TORSDOF", b"TORSDOF 1.5", b"TORSDOF -1", b"TORSDOF 1\nTORSDOF 2"],
    ids=["missing", "missing-value", "non-integer", "negative", "conflicting"],
)
def test_parse_pdbqt_summary_rejects_invalid_torsdof(torsdof_records: bytes) -> None:
    with pytest.raises(AnkoraDomainError) as caught:
        parse_ligand_pdbqt_summary(b"REMARK synthetic PDBQT parser fixture\n" + torsdof_records)
    assert caught.value.code == "MEEKO_LIGAND_TORSDOF_INVALID"
    assert caught.value.stage == "ligand_pdbqt"
    assert caught.value.status_code == 422


@pytest.fixture
def synthetic_amide_sdf(tmp_path: Path) -> Path:
    molecule = Chem.AddHs(Chem.MolFromSmiles(SYNTHETIC_M1A_AMIDE))
    molecule.SetProp("_Name", "SYNTHETIC_M1A_AMIDE_PRECHECK")
    path = tmp_path / "synthetic_ámide.sdf"
    path.write_bytes(Chem.MolToMolBlock(molecule).encode() + b"$$$$\n")
    return path


def test_smarts_precheck_records_paired_outcomes_and_warns_on_no_match(
    synthetic_amide_sdf: Path,
) -> None:
    outcomes, warnings = precheck_ligand_smarts_rigidification(
        input_sdf_path=synthetic_amide_sdf,
        flexibility=LigandFlexibilitySpec(
            rigidified_smarts=(MATCHING_SMARTS, UNMATCHED_SMARTS),
            rigidified_bond_indices=((3, 2), (1, 2)),
        ),
    )
    matched, unmatched = outcomes
    assert matched.smarts == MATCHING_SMARTS
    assert matched.bond_indices == (3, 2)
    assert matched.match_count == 1 and matched.applied
    assert matched.matched_bonds_zero_based == [(9, 10)]
    assert unmatched.smarts == UNMATCHED_SMARTS
    assert unmatched.bond_indices == (1, 2)
    assert unmatched.match_count == 0 and not unmatched.applied
    assert unmatched.matched_bonds_zero_based == []
    (warning,) = warnings
    assert warning.code is WarningCode.LIG_RIGIDIFY_SMARTS_NO_MATCH
    assert warning.stage == "ligand_pdbqt"
    assert warning.details == {"smarts": UNMATCHED_SMARTS, "bond_indices": [1, 2]}


@pytest.mark.parametrize(
    "smarts,indices,code",
    [
        ("[", (1, 2), "LIG_RIGIDIFY_SMARTS_INVALID"),
        ("CC", (1, 3), "LIG_RIGIDIFY_BOND_INDICES_INVALID"),
        ("CCC", (1, 3), "LIG_RIGIDIFY_BOND_INDICES_INVALID"),
    ],
    ids=["syntax", "out-of-range", "unbonded"],
)
def test_smarts_precheck_rejects_invalid_queries(
    synthetic_amide_sdf: Path, smarts: str, indices: tuple[int, int], code: str
) -> None:
    with pytest.raises(AnkoraDomainError) as caught:
        precheck_ligand_smarts_rigidification(
            input_sdf_path=synthetic_amide_sdf,
            flexibility=LigandFlexibilitySpec(
                rigidified_smarts=(smarts,), rigidified_bond_indices=(indices,)
            ),
        )
    assert caught.value.code == code
    assert caught.value.stage == "ligand_pdbqt"
    assert caught.value.status_code == 422
    assert caught.value.details == {"smarts": smarts, "bond_indices": list(indices)}


def test_smarts_precheck_requires_an_sdf_only_when_queries_are_supplied(tmp_path: Path) -> None:
    path = tmp_path / "missing_synthetic.sdf"
    assert precheck_ligand_smarts_rigidification(
        input_sdf_path=path, flexibility=LigandFlexibilitySpec()
    ) == ([], [])
    with pytest.raises(AnkoraDomainError) as caught:
        precheck_ligand_smarts_rigidification(
            input_sdf_path=path,
            flexibility=LigandFlexibilitySpec(
                rigidified_smarts=(MATCHING_SMARTS,), rigidified_bond_indices=((2, 3),)
            ),
        )
    assert caught.value.code == "LIG_RIGIDIFY_INPUT_UNREADABLE"
    assert caught.value.status_code == 422


def test_smarts_precheck_rejects_unpaired_spec_before_opening_sdf(tmp_path: Path) -> None:
    with pytest.raises(AnkoraDomainError) as caught:
        precheck_ligand_smarts_rigidification(
            input_sdf_path=tmp_path / "missing_synthetic.sdf",
            flexibility=LigandFlexibilitySpec(rigidified_smarts=(MATCHING_SMARTS,)),
        )
    assert caught.value.code == "LIG_RIGIDIFY_SPEC_INVALID"
    assert caught.value.status_code == 422


def _generate_synthetic_conformer(
    tmp_path: Path, smiles: str, name: str
) -> tuple[LigandArtifactStore, str, str]:
    store = LigandArtifactStore(tmp_path)
    ligand = import_local_ligand(
        content=f"{smiles} {name}\n".encode(), filename=f"{name}.smi", store=store
    )
    ligand_id = ligand.artifact.ligand_id
    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            random_seed=20261118,
            max_iterations=2000,
        ),
        store=store,
    )
    assert conformer.minimization.converged
    assert conformer.minimization.embedding_method == "ETKDGv3"
    assert conformer.minimization.force_field == "MMFF94s"
    return store, ligand_id, conformer.artifact.conformer_id


def _check_meeko_record(
    store: LigandArtifactStore, record: LigandPdbqtRecord, flags: list[str]
) -> None:
    assert record.tool.version == "0.7.1"
    executable, _, input_path, _, output_path, *_ = record.command
    assert Path(executable).is_file()
    assert input_path.isascii() and not Path(input_path).is_absolute()
    assert Path(output_path).name == "prepared_ligand.pdbqt"
    assert record.command[1:] == [
        "-i",
        input_path,
        "-o",
        output_path,
        "--charge_model",
        "gasteiger",
        *flags,
    ]
    assert record.provenance.command == record.command
    assert record.provenance.warnings == record.warnings
    parameters = record.provenance.parameters
    assert parameters["effective_torsdof"] == record.effective_torsdof
    assert parameters["atom_types"] == record.atom_types
    assert parameters["smarts_rigidification_outcomes"] == [
        outcome.model_dump(mode="json") for outcome in record.smarts_rigidification_outcomes
    ]
    if record.flexibility is None:
        assert "flexibility" not in parameters
    else:
        assert parameters["flexibility"] == record.flexibility.model_dump(mode="json")
    ligand_id, preparation_id = record.artifact.ligand_id, record.artifact.preparation_id
    assert store.load_pdbqt_record(ligand_id, preparation_id) == record
    content = store.pdbqt_content_path(ligand_id, preparation_id).read_bytes()
    assert parse_ligand_pdbqt_summary(content) == (record.effective_torsdof, record.atom_types)


@pytest.mark.parametrize(
    "smarts_pairs,flexible_amides,expected_torsdof,warning_codes",
    [
        ((), False, 4, []),
        ((), True, 5, [WarningCode.LIG_FLEXIBLE_AMIDES_PLANARITY]),
        (((MATCHING_SMARTS, (2, 3)),), False, 3, []),
        (((UNMATCHED_SMARTS, (1, 2)),), False, 4, [WarningCode.LIG_RIGIDIFY_SMARTS_NO_MATCH]),
        (
            ((UNMATCHED_SMARTS, (1, 2)), (MATCHING_SMARTS, (2, 3))),
            False,
            3,
            [WarningCode.LIG_RIGIDIFY_SMARTS_NO_MATCH],
        ),
    ],
    ids=["v01-default", "flexible-amides", "matched-smarts", "unmatched-smarts", "repeated-flags"],
)
def test_meeko_071_prepares_synthetic_amide(
    tmp_path: Path,
    smarts_pairs: tuple[tuple[str, tuple[int, int]], ...],
    flexible_amides: bool,
    expected_torsdof: int,
    warning_codes: list[WarningCode],
) -> None:
    # Torsion counts and atom types come from the measured Gate 0 probe, section 3.1.
    store, ligand_id, conformer_id = _generate_synthetic_conformer(
        tmp_path, SYNTHETIC_M1A_AMIDE, "SYNTHETIC_M1A_AMIDE"
    )
    flexibility = None
    if flexible_amides or smarts_pairs:
        flexibility = LigandFlexibilitySpec(
            flexible_amides=flexible_amides,
            rigidified_smarts=tuple(smarts for smarts, _ in smarts_pairs),
            rigidified_bond_indices=tuple(pair for _, pair in smarts_pairs),
            local_only_refinement=True,
        )
    record = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer_id,
        request=PrepareLigandPdbqtRequest(flexibility=flexibility),
        store=store,
    )
    assert record.flexibility == flexibility
    assert record.effective_torsdof == expected_torsdof
    assert record.atom_types == ["A", "C", "HD", "N", "OA"]
    assert [warning.code for warning in record.warnings] == warning_codes
    flags = ["--flexible_amides"] if flexible_amides else []
    if flexible_amides:
        assert record.warnings[0].details == {"flexible_amides": True}
    for smarts, (first, second) in smarts_pairs:
        flags.extend(
            ["--rigidify_bonds_smarts", smarts, "--rigidify_bonds_indices", str(first), str(second)]
        )
    for outcome, (smarts, pair) in zip(
        record.smarts_rigidification_outcomes, smarts_pairs, strict=True
    ):
        matched = smarts == MATCHING_SMARTS
        assert (outcome.smarts, outcome.bond_indices) == (smarts, pair)
        assert outcome.applied is matched
        assert outcome.match_count == int(matched)
        assert outcome.matched_bonds_zero_based == ([(9, 10)] if matched else [])
    if smarts_pairs:
        assert record.provenance.parameters["rdkit_version"] == rdBase.rdkitVersion
    _check_meeko_record(store, record, flags)


@pytest.mark.parametrize("policy", list(MacrocyclePolicy))
def test_meeko_071_prepares_synthetic_macrocycle(tmp_path: Path, policy: MacrocyclePolicy) -> None:
    molecule = Chem.MolFromSmiles(SYNTHETIC_M1A_MACROCYCLE)
    assert [len(ring) for ring in molecule.GetRingInfo().AtomRings()] == [14]
    store, ligand_id, conformer_id = _generate_synthetic_conformer(
        tmp_path, SYNTHETIC_M1A_MACROCYCLE, "SYNTHETIC_M1A_MACROCYCLE"
    )
    record = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer_id,
        request=PrepareLigandPdbqtRequest(
            flexibility=LigandFlexibilitySpec(macrocycle_policy=policy)
        ),
        store=store,
    )
    assert record.effective_torsdof == 0
    assert record.smarts_rigidification_outcomes == []
    if policy is MacrocyclePolicy.FLEXIBLE_PSEUDOATOMS:
        assert record.atom_types == ["C", "CG0", "G0", "OA"]
        assert record.warnings == []
        with pytest.raises(ValueError, match="macrocycle glue"):
            preflight_autodock4_cpu_atom_types(record.atom_types)
        _check_meeko_record(store, record, [])
    else:
        assert record.atom_types == ["C", "OA"]
        assert preflight_autodock4_cpu_atom_types(record.atom_types) == ("C", "OA")
        (warning,) = record.warnings
        assert warning.code is WarningCode.LIG_MACROCYCLE_RIGID_SCOPE
        assert warning.details == {"macrocycle_policy": policy.value}
        _check_meeko_record(store, record, ["--rigid_macrocycles"])


def test_invalid_meeko_summary_keeps_raw_failure_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ligand_id, conformer_id = _generate_synthetic_conformer(
        tmp_path, SYNTHETIC_M1A_AMIDE, "SYNTHETIC_M1A_AMIDE"
    )
    raw_output = b"REMARK synthetic malformed Meeko output \xff\r\n"

    def malformed_meeko(*, output_pdbqt_path: Path, **_kwargs: object) -> tuple[ToolExecution, str]:
        output_pdbqt_path.write_bytes(raw_output)
        return ToolExecution(
            command=["synthetic-meeko"], exit_code=0, stdout="raw stdout\n", stderr="raw stderr\n"
        ), "0.7.1"

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand", malformed_meeko
    )
    with pytest.raises(AnkoraDomainError) as caught:
        prepare_ligand_pdbqt(
            ligand_id=ligand_id,
            conformer_id=conformer_id,
            request=PrepareLigandPdbqtRequest(),
            store=store,
        )
    assert caught.value.code == "MEEKO_LIGAND_TORSDOF_INVALID"
    preparation_id = str(caught.value.details["preparation_id"])
    directory = store._preparation_dir(ligand_id, preparation_id)
    failure = json.loads((directory / "failure.json").read_text(encoding="utf-8"))
    assert failure["code"] == caught.value.code
    assert failure["tool_version"] == "0.7.1"
    assert b64decode(failure["pdbqt_base64"]) == raw_output
    assert (directory / "stdout.log").read_text(encoding="utf-8") == "raw stdout\n"
    assert (directory / "stderr.log").read_text(encoding="utf-8") == "raw stderr\n"
    assert not (directory / "record.json").exists()
