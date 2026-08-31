from pathlib import Path

import gemmi
import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ComponentDecision,
    IssueDecision,
    ProtonationSettings,
    ReceptorDecisionAction,
    ReceptorIssueKind,
    ReceptorOutputStage,
    ReceptorPreparationRequest,
    RelaxationSettings,
    TerminalHeavyAtomAddition,
)
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.services.receptor_inspection import inspect_receptor
from ankora_backend.services.receptor_preparation import (
    _assert_heavy_atoms_unchanged,
    _assert_restrained_atoms_stable,
    _normalize_pqr_for_meeko,
    prepare_receptor,
)
from ankora_backend.services.structure_inspection import import_structure_bytes

FIXTURES = Path(__file__).parent / "fixtures"


def _import_synthetic(store: StructureArtifactStore) -> str:
    record = import_structure_bytes(
        content=(FIXTURES / "synthetic_m1.pdb").read_bytes(),
        filename="synthetic_m1.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=store,
    )
    return record.artifact.artifact_id


def _selection_request(
    report,  # type: ignore[no-untyped-def]
    *,
    missing_atom_action: ReceptorDecisionAction = ReceptorDecisionAction.LEAVE,
) -> ReceptorPreparationRequest:
    issue_decisions: list[IssueDecision] = []
    for issue in report.issues:
        action = (
            ReceptorDecisionAction.REPAIR
            if issue.kind is ReceptorIssueKind.ALTERNATE_LOCATION
            else missing_atom_action
            if issue.kind is ReceptorIssueKind.MISSING_ATOMS
            else ReceptorDecisionAction.LEAVE
        )
        issue_decisions.append(
            IssueDecision(
                issue_id=issue.issue_id,
                action=action,
                selected_altloc="A"
                if issue.kind is ReceptorIssueKind.ALTERNATE_LOCATION
                else None,
            )
        )
    return ReceptorPreparationRequest(
        selected_chains=["A"],
        water_action=ComponentAction.REMOVE,
        component_decisions=[
            ComponentDecision(
                component_id=component.component_id,
                action=(
                    ComponentAction.KEEP
                    if component.name == "LIG"
                    else ComponentAction.REMOVE
                ),
            )
            for component in report.components
        ],
        issue_decisions=issue_decisions,
        protonation=ProtonationSettings(enabled=False),
        generate_pdbqt=False,
    )


def test_synthetic_receptor_report_exposes_residue_level_decisions(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)

    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)

    assert report.candidate_chains == ["A"]
    assert report.water_count == 1
    assert {component.name for component in report.components} == {"LIG", "ZN"}
    assert {issue.kind for issue in report.issues} == {
        ReceptorIssueKind.MISSING_RESIDUE,
        ReceptorIssueKind.MISSING_ATOMS,
        ReceptorIssueKind.ALTERNATE_LOCATION,
    }
    missing_atoms = next(
        issue for issue in report.issues if issue.kind is ReceptorIssueKind.MISSING_ATOMS
    )
    assert missing_atoms.residue.sequence_number == 1
    assert missing_atoms.missing_atoms == ["CB"]
    assert missing_atoms.distance_to_reference_angstrom is None
    assert ReceptorDecisionAction.REPAIR in missing_atoms.allowed_actions


def test_explicit_selection_creates_immutable_receptor_derivative(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    original = structure_store.content_path(artifact_id).read_bytes()
    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)

    record = prepare_receptor(
        source_artifact_id=artifact_id,
        request=_selection_request(report),
        structure_store=structure_store,
        receptor_store=receptor_store,
    )

    assert record.status.value == "selected"
    assert len(record.outputs) == 1
    output = record.outputs[0]
    assert output.stage.value == "selected"
    derived_path = receptor_store.content_path(record.receptor_id, output.artifact_id)
    derived = gemmi.read_pdb(str(derived_path))
    residue_names = [residue.name for chain in derived[0] for residue in chain]
    assert "LIG" in residue_names
    assert "HOH" not in residue_names
    assert "ZN" not in residue_names
    alternate_labels = {
        atom.altloc
        for chain in derived[0]
        for residue in chain
        for atom in residue
        if atom.altloc not in {"\x00", " "}
    }
    assert alternate_labels == set()
    assert structure_store.content_path(artifact_id).read_bytes() == original
    assert record.provenance[0].input_artifacts == [artifact_id]


def test_repair_removes_reported_zero_occupancy_atoms_before_pdbfixer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    source = (FIXTURES / "synthetic_m1.pdb").read_text().replace(
        "HETATM    6  C1  LIG",
        "ATOM     10  CB  ALA A   1      12.500  11.400   7.400  0.00 20.00           C  \n"
        "HETATM    6  C1  LIG",
    )
    imported = import_structure_bytes(
        content=source.encode(),
        filename="synthetic_zero_occupancy_atom.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structure_store,
    )
    report = inspect_receptor(
        artifact_id=imported.artifact.artifact_id,
        store=structure_store,
    )
    request = _selection_request(
        report, missing_atom_action=ReceptorDecisionAction.REPAIR
    )

    def fake_run_pdbfixer(
        *, input_path: Path, output_path: Path, **_kwargs: object
    ) -> tuple[ToolExecution, str]:
        selected = input_path.read_text()
        assert " CB  ALA A   1" not in selected
        output_path.write_text(selected)
        return (
            ToolExecution(
                command=["pdbfixer"],
                exit_code=0,
                stdout='{"requested_residues": 1, "matched_residues": 1}',
                stderr="",
            ),
            "1.12.0",
        )

    monkeypatch.setattr(
        "ankora_backend.services.receptor_preparation.run_pdbfixer",
        fake_run_pdbfixer,
    )
    record = prepare_receptor(
        source_artifact_id=imported.artifact.artifact_id,
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
    )

    assert record.status.value == "selected"
    assert " CB  ALA A   1" in structure_store.content_path(
        imported.artifact.artifact_id
    ).read_text()


def test_manual_review_blocks_transformation_before_creating_derivative(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)
    request = _selection_request(report)
    request.issue_decisions[0] = IssueDecision(
        issue_id=request.issue_decisions[0].issue_id,
        action=ReceptorDecisionAction.MANUAL_REVIEW,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        prepare_receptor(
            source_artifact_id=artifact_id,
            request=request,
            structure_store=structure_store,
            receptor_store=receptor_store,
        )

    assert captured.value.code == "RECEPTOR_DECISIONS_INCOMPLETE"
    derived_root = tmp_path / "projects" / "default" / "derived" / "receptors"
    assert not derived_root.exists()


def test_pdbqt_requires_explicit_protonation() -> None:
    with pytest.raises(ValueError, match="requires an explicit protonation"):
        ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
            protonation=ProtonationSettings(enabled=False),
            generate_pdbqt=True,
        )


def test_meeko_pqr_normalization_changes_only_compact_four_digit_boundary() -> None:
    source = (
        b"REMARK EXPLICITLY SYNTHETIC PQR FORMAT FIXTURE\r\n"
        b"ATOM      1  N   ALA A 999      10.000  11.000  12.000 -0.3000 1.8240\r\n"
        b"ATOM  14498  N   ASP A1000       7.742   3.909  40.857 -0.5163 1.8240\r\n"
        b"END\r\n"
    )

    normalized, count = _normalize_pqr_for_meeko(source)

    assert count == 1
    assert normalized == source.replace(b"ASP A1000", b"ASP A 1000")
    assert normalized.splitlines()[0] == source.splitlines()[0]
    assert normalized.splitlines()[1] == source.splitlines()[1]
    assert normalized.splitlines()[2].split()[6:] == source.splitlines()[2].split()[5:]
    assert normalized.endswith(b"END\r\n")


def test_prepare_receptor_preserves_and_traces_exact_meeko_pqr_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)
    request = _selection_request(
        report, missing_atom_action=ReceptorDecisionAction.REMOVE
    )
    request.protonation = ProtonationSettings(enabled=True, ph=7.4)
    request.generate_pdbqt = True
    original_pqr = (
        b"REMARK EXPLICITLY SYNTHETIC PQR FORMAT FIXTURE\n"
        b"ATOM  14498  N   ASP A1000       7.742   3.909  40.857 -0.5163 1.8240\n"
    )

    def fake_run_pdb2pqr_propka(
        *,
        input_path: Path,
        pqr_output_path: Path,
        pdb_output_path: Path,
        **_kwargs: object,
    ) -> tuple[ToolExecution, str]:
        pqr_output_path.write_bytes(original_pqr)
        pdb_output_path.write_bytes(input_path.read_bytes())
        return (
            ToolExecution(
                command=["pdb2pqr", str(input_path), str(pqr_output_path)],
                exit_code=0,
                stdout="explicitly synthetic PDB2PQR stdout",
                stderr="",
            ),
            "pdb2pqr synthetic; propka synthetic",
        )

    def fake_run_meeko_receptor(
        *, input_pqr_path: Path, output_pdbqt_path: Path
    ) -> tuple[ToolExecution, str]:
        assert input_pqr_path.name == "meeko_input_receptor.pqr"
        assert input_pqr_path.read_bytes() == original_pqr.replace(
            b"ASP A1000", b"ASP A 1000"
        )
        output_pdbqt_path.write_text("REMARK EXPLICITLY SYNTHETIC PDBQT\n")
        return (
            ToolExecution(
                command=["mk_prepare_receptor", "--read_pqr", str(input_pqr_path)],
                exit_code=0,
                stdout="explicitly synthetic Meeko stdout",
                stderr="",
            ),
            "0.7.1",
        )

    monkeypatch.setattr(
        "ankora_backend.services.receptor_preparation.run_pdb2pqr_propka",
        fake_run_pdb2pqr_propka,
    )
    monkeypatch.setattr(
        "ankora_backend.services.receptor_preparation.run_meeko_receptor",
        fake_run_meeko_receptor,
    )

    record = prepare_receptor(
        source_artifact_id=artifact_id,
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
    )

    assert record.status.value == "docking_ready"
    source_output = next(
        output
        for output in record.outputs
        if output.stage is ReceptorOutputStage.PROTONATED_PQR
    )
    meeko_input_output = next(
        output
        for output in record.outputs
        if output.stage is ReceptorOutputStage.MEEKO_INPUT_PQR
    )
    assert receptor_store.content_path(
        record.receptor_id, source_output.artifact_id
    ).read_bytes() == original_pqr
    assert receptor_store.content_path(
        record.receptor_id, meeko_input_output.artifact_id
    ).read_bytes() == original_pqr.replace(b"ASP A1000", b"ASP A 1000")
    formatting_event = next(
        event
        for event in record.provenance
        if event.event_type == "receptor_pqr_formatted_for_meeko"
    )
    assert formatting_event.input_artifacts == [source_output.artifact_id]
    assert formatting_event.output_artifacts == [meeko_input_output.artifact_id]
    assert formatting_event.parameters["format_only"] is True
    assert formatting_event.parameters["normalized_compact_residue_lines"] == 1
    meeko_event = next(
        event
        for event in record.provenance
        if event.event_type == "receptor_pdbqt_generated"
    )
    assert meeko_event.input_artifacts == [meeko_input_output.artifact_id]


def test_protonation_blocks_unrepaired_observed_residues_before_derivative(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)
    request = _selection_request(report)
    request.protonation = ProtonationSettings(enabled=True, ph=7.4)

    with pytest.raises(AnkoraDomainError) as captured:
        prepare_receptor(
            source_artifact_id=artifact_id,
            request=request,
            structure_store=structure_store,
            receptor_store=receptor_store,
        )

    assert captured.value.code == "RECEPTOR_PROTONATION_REQUIRES_RESOLUTION"
    blockers = captured.value.details["blocking_issues"]
    assert isinstance(blockers, list)
    assert blockers[0]["issue_id"] == "missing_atoms|A|ALA|1|"
    derived_root = tmp_path / "projects" / "default" / "derived" / "receptors"
    assert not derived_root.exists()


def test_protonation_postcondition_rejects_unapproved_heavy_atom_change(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdb"
    output_path = tmp_path / "output.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    input_path.write_text(original)
    output_path.write_text(
        original.replace(
            "HETATM    6  C1  LIG",
            "ATOM     10  CB  ALA A   1      12.500  11.400   7.400  1.00 20.00           C  \n"
            "HETATM    6  C1  LIG",
        )
    )
    execution = ToolExecution(
        command=["pdb2pqr.exe", "input.pdb", "output.pqr"],
        exit_code=0,
        stdout="synthetic stdout",
        stderr="synthetic stderr",
    )

    with pytest.raises(AnkoraDomainError) as captured:
        _assert_heavy_atoms_unchanged(
            input_path=input_path,
            output_path=output_path,
            execution=execution,
        )

    assert captured.value.code == "PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE"
    assert any(
        item.endswith("|CB")
        for item in captured.value.details["added_heavy_atoms"]
    )


def test_protonation_postcondition_accepts_only_an_explicit_terminal_oxt(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdb"
    output_path = tmp_path / "output.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    input_path.write_text(original)
    output_path.write_text(
        original.replace(
            "ATOM      5  O   ALA A   1      14.500  12.700   9.000",
            "ATOM      5  O   ALA A   1      14.500  12.700   9.000\n"
            "ATOM     10  OXT ALA A   1      15.000  12.900   9.400  1.00 20.00           O  ",
        )
    )
    execution = ToolExecution(
        command=["pdb2pqr.exe", "input.pdb", "output.pqr"],
        exit_code=0,
        stdout="explicitly synthetic stdout",
        stderr="",
    )

    applied = _assert_heavy_atoms_unchanged(
        input_path=input_path,
        output_path=output_path,
        execution=execution,
        authorized_terminal_additions=[
            TerminalHeavyAtomAddition(
                chain_id="A", residue_name="ALA", sequence_number=1
            )
        ],
    )

    assert applied == ["A|ALA|1||OXT"]


def test_terminal_oxt_authorization_is_rejected_for_an_internal_residue(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdb"
    output_path = tmp_path / "output.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    input_path.write_text(original)
    output_path.write_text(original)
    execution = ToolExecution(
        command=["pdb2pqr.exe", "input.pdb", "output.pqr"],
        exit_code=0,
        stdout="explicitly synthetic stdout",
        stderr="",
    )

    with pytest.raises(AnkoraDomainError) as captured:
        _assert_heavy_atoms_unchanged(
            input_path=input_path,
            output_path=output_path,
            execution=execution,
            authorized_terminal_additions=[
                TerminalHeavyAtomAddition(
                    chain_id="A", residue_name="ALA", sequence_number=999
                )
            ],
        )

    assert captured.value.code == "RECEPTOR_TERMINAL_ADDITION_INVALID"


def test_terminal_oxt_authorization_does_not_allow_another_heavy_atom(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdb"
    output_path = tmp_path / "output.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    input_path.write_text(original)
    output_path.write_text(
        original.replace(
            "HETATM    6  C1  LIG",
            "ATOM     10  CB  ALA A   1      12.500  11.400   7.400  1.00 20.00           C  \n"
            "HETATM    6  C1  LIG",
        )
    )
    execution = ToolExecution(
        command=["pdb2pqr.exe", "input.pdb", "output.pqr"],
        exit_code=0,
        stdout="explicitly synthetic stdout",
        stderr="",
    )

    with pytest.raises(AnkoraDomainError) as captured:
        _assert_heavy_atoms_unchanged(
            input_path=input_path,
            output_path=output_path,
            execution=execution,
            authorized_terminal_additions=[
                TerminalHeavyAtomAddition(
                    chain_id="A", residue_name="ALA", sequence_number=1
                )
            ],
        )

    assert captured.value.details["authorized_terminal_heavy_atom_additions"] == [
        "A|ALA|1||OXT"
    ]
    assert any(
        item.endswith("|CB")
        for item in captured.value.details["unapproved_added_heavy_atoms"]
    )


def test_protonation_state_residue_renaming_is_not_a_heavy_atom_change(
    tmp_path: Path,
) -> None:
    """PDB2PQR renames HIS to HID/HIE/HIP (and similar AMBER/CHARMM variants)
    for the same heavy atoms; the identity check must tolerate that rename."""
    input_path = tmp_path / "input.pdb"
    output_path = tmp_path / "output.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    input_path.write_text(original.replace("ALA A   1", "HIS A   1"))
    output_path.write_text(original.replace("ALA A   1", "HID A   1"))
    execution = ToolExecution(
        command=["pdb2pqr.exe", "input.pdb", "output.pqr"],
        exit_code=0,
        stdout="synthetic stdout",
        stderr="synthetic stderr",
    )

    _assert_heavy_atoms_unchanged(
        input_path=input_path, output_path=output_path, execution=execution
    )


def test_relaxation_within_tolerance_reports_the_displacement(tmp_path: Path) -> None:
    original_path = tmp_path / "repaired.pdb"
    relaxed_path = tmp_path / "relaxed.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    original_path.write_text(original)
    # Shift the O atom by 0.3 A in x - within the 0.5 A tolerance.
    relaxed_path.write_text(
        original.replace(
            "ATOM      5  O   ALA A   1      14.500  12.700   9.000",
            "ATOM      5  O   ALA A   1      14.800  12.700   9.000",
        )
    )

    displacement = _assert_restrained_atoms_stable(
        original_path=original_path, relaxed_path=relaxed_path
    )

    assert displacement == pytest.approx(0.3, abs=0.001)


def test_relaxation_beyond_tolerance_is_rejected(tmp_path: Path) -> None:
    original_path = tmp_path / "repaired.pdb"
    relaxed_path = tmp_path / "relaxed.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    original_path.write_text(original)
    # Shift the O atom by 0.9 A in x - beyond the 0.5 A tolerance.
    relaxed_path.write_text(
        original.replace(
            "ATOM      5  O   ALA A   1      14.500  12.700   9.000",
            "ATOM      5  O   ALA A   1      15.400  12.700   9.000",
        )
    )

    with pytest.raises(AnkoraDomainError) as captured:
        _assert_restrained_atoms_stable(original_path=original_path, relaxed_path=relaxed_path)

    assert captured.value.code == "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED"
    assert captured.value.details["max_displacement_angstrom"] == pytest.approx(0.9, abs=0.001)


def test_relaxation_check_ignores_atoms_pdbfixer_just_added(tmp_path: Path) -> None:
    """Regression test: a newly reconstructed atom exists in the relaxed output
    but not in the pre-repair original, so it must never count toward the
    restrained-atom displacement - no matter how far the declash step moved it
    to resolve a real clash. Comparing against the *repaired* (not pre-repair)
    file previously misclassified this as a tolerance violation on every real
    receptor with a genuinely reconstructed side chain."""
    original_path = tmp_path / "selected.pdb"
    relaxed_path = tmp_path / "relaxed.pdb"
    original = (FIXTURES / "synthetic_m1.pdb").read_text()
    original_path.write_text(original)
    relaxed_path.write_text(
        original.replace(
            "HETATM    6  C1  LIG A 101",
            "ATOM      9  CB  ALA A   1      99.000  99.000  99.000  1.00 20.00"
            "           C  \nHETATM    6  C1  LIG A 101",
        )
    )

    displacement = _assert_restrained_atoms_stable(
        original_path=original_path, relaxed_path=relaxed_path
    )

    assert displacement == 0.0


def test_prepare_receptor_relaxation_adds_relaxed_stage_with_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)
    base_request = _selection_request(report, missing_atom_action=ReceptorDecisionAction.REPAIR)
    request = base_request.model_copy(
        update={
            "relaxation": RelaxationSettings(
                enabled=True,
                restraint_force_constant_kcal_mol_a2=200.0,
                max_iterations=200,
            )
        }
    )

    def fake_run_pdbfixer(
        *,
        input_path: Path,
        output_path: Path,
        residues: object,
        relaxed_output_path: Path | None = None,
        restraint_force_constant_kcal_mol_a2: float | None = None,
        relax_max_iterations: int | None = None,
    ) -> tuple[ToolExecution, str]:
        content = input_path.read_text()
        output_path.write_text(content)
        if relaxed_output_path is not None:
            relaxed_output_path.write_text(content)
        return (
            ToolExecution(command=["pdbfixer"], exit_code=0, stdout="{}", stderr=""),
            "1.12.0",
        )

    monkeypatch.setattr(
        "ankora_backend.services.receptor_preparation.run_pdbfixer", fake_run_pdbfixer
    )

    record = prepare_receptor(
        source_artifact_id=artifact_id,
        request=request,
        structure_store=structure_store,
        receptor_store=receptor_store,
    )

    assert [output.stage for output in record.outputs] == [
        ReceptorOutputStage.SELECTED,
        ReceptorOutputStage.REPAIRED,
        ReceptorOutputStage.RELAXED,
    ]
    relax_event = next(
        event for event in record.provenance if event.event_type == "receptor_clashes_relaxed"
    )
    assert relax_event.parameters["max_restrained_atom_displacement_angstrom"] == 0.0
    assert relax_event.parameters["restraint_force_constant_kcal_mol_a2"] == 200.0
    assert relax_event.parameters["tolerance_angstrom"] == 0.5


def test_failed_scientific_tool_preserves_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    report = inspect_receptor(artifact_id=artifact_id, store=structure_store)
    request = _selection_request(
        report, missing_atom_action=ReceptorDecisionAction.REMOVE
    )
    request.protonation = ProtonationSettings(enabled=True, ph=7.4)

    def fail_protonation(**_kwargs: object) -> None:
        raise AnkoraDomainError(
            code="PDB2PQR_PROPKA_FAILED",
            stage="receptor_protonation",
            message="Synthetic external-tool failure.",
            status_code=422,
            details={
                "command": ["pdb2pqr.exe", "synthetic-input.pdb"],
                "exit_code": 1,
                "stdout": "synthetic stdout evidence",
                "stderr": "synthetic stderr evidence",
            },
        )

    monkeypatch.setattr(
        "ankora_backend.services.receptor_preparation.run_pdb2pqr_propka",
        fail_protonation,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        prepare_receptor(
            source_artifact_id=artifact_id,
            request=request,
            structure_store=structure_store,
            receptor_store=receptor_store,
        )

    receptor_id = str(captured.value.details["receptor_id"])
    receptor_root = (
        tmp_path / "projects" / "default" / "derived" / "receptors" / receptor_id
    )
    assert (receptor_root / "failed-tool.stdout.log").read_text() == (
        "synthetic stdout evidence"
    )
    assert (receptor_root / "failed-tool.stderr.log").read_text() == (
        "synthetic stderr evidence"
    )
    failure_record = (receptor_root / "failure.json").read_text()
    assert "PDB2PQR_PROPKA_FAILED" in failure_record
    assert "pdb2pqr.exe" in failure_record


def test_receptor_api_round_trip_preserves_typed_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.headers["Origin"] = "tauri://localhost"
    imported = client.post(
        "/api/v1/structures/import",
        files={
            "file": (
                "synthetic_m1.pdb",
                (FIXTURES / "synthetic_m1.pdb").read_bytes(),
                "chemical/x-pdb",
            )
        },
    ).json()
    artifact_id = imported["artifact"]["artifact_id"]
    inspection_response = client.get(
        f"/api/v1/structures/{artifact_id}/receptor-inspection"
    )
    report = inspection_response.json()
    assert inspection_response.status_code == 200
    request = _selection_request(
        inspect_receptor(
            artifact_id=artifact_id,
            store=StructureArtifactStore(tmp_path),
        )
    )

    prepare_response = client.post(
        f"/api/v1/structures/{artifact_id}/receptors",
        json=request.model_dump(mode="json"),
    )

    assert prepare_response.status_code == 201
    prepared = prepare_response.json()
    assert prepared["status"] == "selected"
    assert report["source_artifact_id"] == artifact_id
    latest_response = client.get("/api/v1/receptors/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["receptor_id"] == prepared["receptor_id"]
    output = prepared["outputs"][0]
    content_response = client.get(
        f"/api/v1/receptors/{prepared['receptor_id']}/outputs/"
        f"{output['artifact_id']}/content"
    )
    assert content_response.status_code == 200
    assert b"LIG" in content_response.content

    # An artifact_id that isn't one of this receptor's real outputs used to
    # hit an `AssertionError("unreachable")` in the route, which no
    # registered exception handler catches — FastAPI would have returned a
    # bare, undocumented 500 instead of a clean, structured 404 for this
    # entirely reachable case (a stale or mistyped artifact_id).
    missing_response = client.get(
        f"/api/v1/receptors/{prepared['receptor_id']}/outputs/"
        "00000000-0000-0000-0000-000000000000/content"
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["code"] == "RECEPTOR_NOT_FOUND"


def test_latest_receptor_reports_empty_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))

    response = TestClient(create_app()).get("/api/v1/receptors/latest")

    assert response.status_code == 404
    assert response.json()["code"] == "RECEPTOR_HISTORY_EMPTY"
