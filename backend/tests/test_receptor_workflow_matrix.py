"""Synthetic diagnostic-harness policies, never fabricated preparation results."""

import copy
import json
from pathlib import Path

import pytest
from scripts import run_receptor_workflow_matrix as matrix

ROOT = Path(__file__).resolve().parents[2]


def _plan() -> dict:
    return json.loads(
        (ROOT / "docs/validation/reference_cases/RECEPTOR_WORKFLOW_MATRIX_V2.plan.json").read_text()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform", "unrecorded"),
        ("missing_residues", "build"),
        ("repair_seed", True),
        ("repair_seed", 0),
        ("force_field", "unrecorded"),
        ("water_action", "default"),
        ("nonstandard", "replace"),
        ("unknown_policy", "ignored"),
    ],
)
def test_diagnostic_manifest_rejects_unsupported_or_ignored_choices(
    field: str, value: object
) -> None:
    plan = _plan()
    plan[field] = value
    with pytest.raises(ValueError):
        matrix._validate_plan(plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ph", 15),
        ("terminal_policy", "all"),
        ("component_action", "automatic"),
        ("selected_chains", ["A", "A"]),
        ("component_decisions", []),
    ],
)
def test_diagnostic_manifest_rejects_unsupported_case_choices(field: str, value: object) -> None:
    plan = _plan()
    plan["cases"][0][field] = value
    with pytest.raises(ValueError):
        matrix._validate_plan(plan)


def test_retained_incomplete_component_stops_diagnostic_before_scientific_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = (ROOT / "backend/tests/fixtures/synthetic_m1.cif").read_bytes() + (
        b"\nloop_\n_pdbx_unobs_or_zero_occ_atoms.auth_asym_id\n"
        b"_pdbx_unobs_or_zero_occ_atoms.auth_comp_id\n"
        b"_pdbx_unobs_or_zero_occ_atoms.auth_seq_id\n"
        b"_pdbx_unobs_or_zero_occ_atoms.PDB_ins_code\n"
        b"_pdbx_unobs_or_zero_occ_atoms.auth_atom_id\nA LIG 101 ? N1\n#\n"
    )

    async def synthetic_source(_pdb_id: str) -> tuple[bytes, str]:
        return content, "https://example.invalid/synthetic-fixture.cif"

    def forbidden_preparation(**_kwargs: object) -> None:
        pytest.fail("A retained incomplete component must require a decision before preparation")

    monkeypatch.setattr(matrix, "fetch_rcsb_mmcif", synthetic_source)
    monkeypatch.setattr(matrix, "prepare_receptor", forbidden_preparation)
    plan = _plan()
    case = copy.deepcopy(plan["cases"][0])
    case.pop("source_sha256")
    case["component_action"] = "keep"
    result = matrix._run_case(case, tmp_path, plan)
    assert result["status"] == "needs_decision"
    assert result["issue"]["residue"]["residue_name"] == "LIG"
    assert result["source_unchanged"] is True
    assert (tmp_path / case["case_id"] / "outcome.json").is_file()
    with pytest.raises(FileExistsError):
        matrix._run_case(case, tmp_path, plan)
