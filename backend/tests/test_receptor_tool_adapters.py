import json
import sys
from pathlib import Path

import pytest

from ankora_backend.adapters.tools.discovery import DiscoveredTool
from ankora_backend.adapters.tools.receptor_preparation import (
    _diagnose_pqr_connectivity,
    _pqr_residue_locator,
    run_meeko_receptor,
    run_pdb2pqr_propka,
    run_pdbfixer,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.schemas.receptors import ProtonationOverride, ResidueLocator


def _successful_execution(
    *, executable: str, arguments: list[str], **_kwargs: object
) -> ToolExecution:
    return ToolExecution(
        command=[executable, *arguments],
        exit_code=0,
        stdout="synthetic tool stdout",
        stderr="synthetic tool stderr",
    )


def _successful_pdbfixer_execution(
    *, executable: str, arguments: list[str], **_kwargs: object
) -> ToolExecution:
    requested = arguments.count("--repair")
    output_path = Path(arguments[arguments.index("--output") + 1])
    output_path.write_text("SYNTHETIC PDBFIXER OUTPUT\n")
    relaxation: dict[str, object] | None = None
    if "--relax" in arguments:
        relaxed_path = Path(arguments[arguments.index("--relaxed-output") + 1])
        relaxed_path.write_text("SYNTHETIC RELAXED OUTPUT\n")
        relaxation = {"relaxed": True, "new_atom_count": requested}
    return ToolExecution(
        command=[executable, *arguments],
        exit_code=0,
        stdout=json.dumps(
            {
                "requested_residues": requested,
                "matched_residues": requested,
                "relaxation": relaxation,
            }
        ),
        stderr="",
    )


def test_pdbfixer_adapter_uses_isolated_worker_and_explicit_residues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_python_package",
        lambda *_args: DiscoveredTool(True, "pdbfixer.py", "1.12.0"),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        _successful_pdbfixer_execution,
    )

    execution, tool_version = run_pdbfixer(
        input_path=tmp_path / "selected.pdb",
        output_path=tmp_path / "repaired.pdb",
        residues=[
            ResidueLocator(
                chain_id="A",
                residue_name="ARG",
                sequence_number=271,
                insertion_code="",
            )
        ],
    )

    assert execution.command[1:3] == [
        "-m",
        "ankora_backend.adapters.tools.pdbfixer_worker",
    ]
    assert execution.command[-2:] == ["--repair", "A|ARG|271|"]
    assert tool_version == "1.12.0"


def test_pdbfixer_adapter_appends_relaxation_flags_only_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_python_package",
        lambda *_args: DiscoveredTool(True, "pdbfixer.py", "1.12.0"),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        _successful_pdbfixer_execution,
    )
    residues = [
        ResidueLocator(chain_id="A", residue_name="ALA", sequence_number=1, insertion_code="")
    ]

    without_relax, _ = run_pdbfixer(
        input_path=tmp_path / "selected.pdb",
        output_path=tmp_path / "repaired.pdb",
        residues=residues,
    )
    assert "--relax" not in without_relax.command

    with_relax, _ = run_pdbfixer(
        input_path=tmp_path / "selected.pdb",
        output_path=tmp_path / "repaired.pdb",
        residues=residues,
        relaxed_output_path=tmp_path / "relaxed.pdb",
        restraint_force_constant_kcal_mol_a2=200.0,
        relax_max_iterations=200,
    )
    assert "--relax" in with_relax.command
    assert with_relax.command[-7:] == [
        "--relax",
        "--relaxed-output",
        str(tmp_path / "relaxed.pdb"),
        "--restraint-force-constant",
        "200.0",
        "--relax-max-iterations",
        "200",
    ]


def test_pdbfixer_adapter_rejects_an_unmatched_repair_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_python_package",
        lambda *_args: DiscoveredTool(True, "pdbfixer.py", "1.12.0"),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        lambda *, executable, arguments, **_kwargs: ToolExecution(
            command=[executable, *arguments],
            exit_code=0,
            stdout=json.dumps(
                {
                    "requested_residues": 1,
                    "matched_residues": 0,
                    "relaxation": {"relaxed": False, "reason": "no_new_atoms"},
                }
            ),
            stderr="synthetic unmatched residue evidence",
        ),
    )

    with pytest.raises(AnkoraDomainError) as captured:
        run_pdbfixer(
            input_path=tmp_path / "selected.pdb",
            output_path=tmp_path / "repaired.pdb",
            residues=[
                ResidueLocator(
                    chain_id="A",
                    residue_name="ASN",
                    sequence_number=17,
                    insertion_code="",
                )
            ],
            relaxed_output_path=tmp_path / "relaxed.pdb",
            restraint_force_constant_kcal_mol_a2=50.0,
            relax_max_iterations=200,
        )

    assert captured.value.code == "PDBFIXER_REPAIR_INCOMPLETE"
    assert captured.value.details["report"] == {
        "requested_residues": 1,
        "matched_residues": 0,
        "relaxation": {"relaxed": False, "reason": "no_new_atoms"},
    }
    assert captured.value.details["stderr"] == "synthetic unmatched residue evidence"


def test_pdb2pqr_adapter_records_explicit_propka_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str(tmp_path / "pdb2pqr.exe")
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_tool",
        lambda *_args: DiscoveredTool(True, executable),
    )
    def successful_worker(
        *, executable: str, arguments: list[str], **_kwargs: object
    ) -> ToolExecution:
        return ToolExecution(
            command=[executable, *arguments],
            exit_code=0,
            stdout=json.dumps({"predictions": [], "applied_overrides": []}),
            stderr="synthetic PDB2PQR log",
        )

    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        successful_worker,
    )

    execution, tool_version, report = run_pdb2pqr_propka(
        input_path=tmp_path / "selected.pdb",
        pqr_output_path=tmp_path / "protonated.pqr",
        pdb_output_path=tmp_path / "protonated.pdb",
        ph=7.4,
        force_field="AMBER",
        overrides=[
            ProtonationOverride(
                residue=ResidueLocator(
                    chain_id="A",
                    residue_name="ASP",
                    sequence_number=17,
                ),
                state="ASH",
            )
        ],
    )

    assert execution.command == [
        sys.executable,
        "-m",
        "ankora_backend.adapters.tools.pdb2pqr_worker",
        "--input",
        str(tmp_path / "selected.pdb"),
        "--pqr-output",
        str(tmp_path / "protonated.pqr"),
        "--pdb-output",
        str(tmp_path / "protonated.pdb"),
        "--ph",
        "7.4",
        "--force-field",
        "AMBER",
        "--override",
        json.dumps(
            {
                "residue": {
                    "chain_id": "A",
                    "insertion_code": "",
                    "residue_name": "ASP",
                    "sequence_number": 17,
                },
                "state": "ASH",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    ]
    assert tool_version.startswith("pdb2pqr ")
    assert "; propka " in tool_version
    assert report == {"predictions": [], "applied_overrides": []}


def test_meeko_adapter_reads_pqr_and_writes_named_pdbqt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str(tmp_path / "mk_prepare_receptor.exe")
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_tool",
        lambda *_args: DiscoveredTool(True, executable),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        _successful_execution,
    )

    execution, _tool_version = run_meeko_receptor(
        input_pqr_path=tmp_path / "protonated.pqr",
        output_pdbqt_path=tmp_path / "prepared.pdbqt",
    )

    assert execution.command == [
        executable,
        "--read_pqr",
        str(tmp_path / "protonated.pqr"),
        "--charge_model",
        "read",
        "-o",
        str(tmp_path / "prepared"),
        "-p",
        str(tmp_path / "prepared.pdbqt"),
    ]


def test_meeko_failure_reports_structured_affected_residues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str(tmp_path / "mk_prepare_receptor.exe")
    pqr_path = tmp_path / "protonated.pqr"
    pqr_path.write_text("SYNTHETIC PQR TEST DATA\n")
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_tool",
        lambda *_args: DiscoveredTool(True, executable),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        lambda **_kwargs: ToolExecution(
            command=[executable, "--read_pqr", str(pqr_path)],
            exit_code=1,
            stdout="synthetic stdout",
            stderr="synthetic AtomValenceException",
        ),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.diagnose_meeko_pqr_connectivity",
        lambda _path: [
            {
                "chain_id": "A",
                "residue_name": "ASP",
                "sequence_number": 231,
                "insertion_code": "",
                "diagnostic": "SyntheticConnectivityError: synthetic test evidence",
            }
        ],
    )

    with pytest.raises(AnkoraDomainError) as captured:
        run_meeko_receptor(
            input_pqr_path=pqr_path,
            output_pdbqt_path=tmp_path / "prepared.pdbqt",
        )

    assert captured.value.code == "MEEKO_CONNECTIVITY_FAILURE"
    assert captured.value.details["affected_residues"] == [
        {
            "chain_id": "A",
            "residue_name": "ASP",
            "sequence_number": 231,
            "insertion_code": "",
            "diagnostic": "SyntheticConnectivityError: synthetic test evidence",
        }
    ]
    assert captured.value.details["possible_actions"] == ["remove", "manual_review"]


def test_meeko_failure_is_not_masked_when_connectivity_diagnosis_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str(tmp_path / "mk_prepare_receptor.exe")
    pqr_path = tmp_path / "protonated.pqr"
    pqr_path.write_text("EXPLICITLY SYNTHETIC PQR TEST DATA\n")
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.discover_tool",
        lambda *_args: DiscoveredTool(True, executable),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.run_tool",
        lambda **_kwargs: ToolExecution(
            command=[executable, "--read_pqr", str(pqr_path)],
            exit_code=1,
            stdout="preserved synthetic stdout",
            stderr="preserved synthetic stderr",
        ),
    )
    monkeypatch.setattr(
        "ankora_backend.adapters.tools.receptor_preparation.diagnose_meeko_pqr_connectivity",
        lambda _path: (_ for _ in ()).throw(ValueError("synthetic parser failure")),
    )

    with pytest.raises(AnkoraDomainError) as captured:
        run_meeko_receptor(
            input_pqr_path=pqr_path,
            output_pdbqt_path=tmp_path / "prepared.pdbqt",
        )

    assert captured.value.code == "MEEKO_CONNECTIVITY_FAILURE"
    assert captured.value.details["stdout"] == "preserved synthetic stdout"
    assert captured.value.details["stderr"] == "preserved synthetic stderr"
    assert captured.value.details["connectivity_diagnostic_error"] == (
        "ValueError: synthetic parser failure"
    )


def test_pqr_locator_reads_real_compact_four_digit_residue_number() -> None:
    locator = _pqr_residue_locator(
        "ATOM  14498  N   ASP A1000       7.742   3.909  40.857 -0.5163 1.8240\n"
    )

    assert locator == ResidueLocator(
        chain_id="A",
        residue_name="ASP",
        sequence_number=1000,
        insertion_code="",
    )


def test_pqr_connectivity_diagnosis_is_residue_scoped() -> None:
    pqr = (
        "ATOM      1  N   ALA A   1      10.000  10.000  10.000  0.1000 1.8000\n"
        "ATOM      2  CA  ALA A   1      11.000  10.000  10.000  0.1000 1.9000\n"
        "ATOM      3  N   ASP A 231      20.000  20.000  20.000  0.1000 1.8000\n"
        "ATOM      4  CA  ASP A 231      21.000  20.000  20.000  0.1000 1.9000\n"
    )

    def synthetic_parser(block: str) -> object:
        if "ASP A 231" in block:
            raise ValueError("synthetic invalid connectivity")
        return object()

    assert _diagnose_pqr_connectivity(pqr, synthetic_parser) == [
        {
            "chain_id": "A",
            "residue_name": "ASP",
            "sequence_number": 231,
            "insertion_code": "",
            "diagnostic": "ValueError: synthetic invalid connectivity",
        }
    ]


def test_pqr_connectivity_diagnosis_reports_excess_inter_residue_bonds() -> None:
    pqr = (
        "ATOM      1  C   GLY A 230      10.000  10.000  10.000  0.1000 1.9000\n"
        "ATOM      2  O   GLY A 230      11.000  10.000  10.000 -0.1000 1.6000\n"
        "ATOM      3  N   ASP A 231      10.500  10.000  10.000 -0.1000 1.8000\n"
        "ATOM      4  OD1 ASP A 231      11.500  10.000  10.000 -0.1000 1.6000\n"
    )

    def synthetic_parser(block: str) -> object:
        key = "A:230" if "GLY A 230" in block else "A:231"
        residue_name = "GLY" if key == "A:230" else "ASP"
        return {key: (object(), residue_name, False, False)}

    def synthetic_bond_finder(
        _residues: dict[str, tuple[object, str]],
    ) -> object:
        return {("A:230", "A:231"): [(0, 0), (1, 1)]}

    assert _diagnose_pqr_connectivity(
        pqr, synthetic_parser, synthetic_bond_finder
    ) == [
        {
            "chain_id": "A",
            "residue_name": "GLY",
            "sequence_number": 230,
            "insertion_code": "",
            "diagnostic": "Meeko inferred 2 inter-residue bonds between A:230 and A:231.",
            "related_residue_keys": ["A:230", "A:231"],
            "inter_residue_bond_count": 2,
            "inter_residue_bonds": ["?-?", "?-?"],
        },
        {
            "chain_id": "A",
            "residue_name": "ASP",
            "sequence_number": 231,
            "insertion_code": "",
            "diagnostic": "Meeko inferred 2 inter-residue bonds between A:230 and A:231.",
            "related_residue_keys": ["A:230", "A:231"],
            "inter_residue_bond_count": 2,
            "inter_residue_bonds": ["?-?", "?-?"],
        },
    ]


def test_pqr_connectivity_diagnosis_reports_unexpected_nonlocal_single_bond() -> None:
    pqr = (
        "ATOM      1  O   THR A 296      10.000  10.000  10.000 -0.1000 1.6000\n"
        "ATOM      2 HH21 ARG A 300      10.900  10.000  10.000  0.1000 0.6000\n"
    )

    def synthetic_parser(block: str) -> object:
        key = "A:296" if "THR A 296" in block else "A:300"
        residue_name = "THR" if key == "A:296" else "ARG"
        return {key: (object(), residue_name, False, False)}

    def synthetic_bond_finder(
        _residues: dict[str, tuple[object, str]],
    ) -> object:
        return {("A:296", "A:300"): [(1, 22)]}

    affected = _diagnose_pqr_connectivity(
        pqr, synthetic_parser, synthetic_bond_finder
    )

    assert [item["sequence_number"] for item in affected] == [296, 300]
    assert all(item["inter_residue_bond_count"] == 1 for item in affected)
    assert all(item["related_residue_keys"] == ["A:296", "A:300"] for item in affected)
