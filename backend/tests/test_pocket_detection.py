"""Contracts for M4 P2Rank pocket detection.

`_parse_predictions_csv` is verified against a real example output file
pulled from P2Rank's own repository (fixtures/p2rank_1fbl_predictions.csv),
not a guessed format. `detect_pockets` itself uses a mocked `execute_p2rank`
in the deterministic automated suite; real Windows execution evidence is
recorded separately in `memory/SESSION_LOG.md`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.structures import StructureFormat, StructureSource
from ankora_backend.services import pocket_detection as pocket_detection_module
from ankora_backend.services.pocket_detection import (
    POCKET_BOX_PADDING_ANGSTROM,
    _parse_predictions_csv,
    detect_pockets,
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


def _receptor_record(
    *,
    receptor_store: ReceptorArtifactStore,
    source_artifact_id: str,
    status: ReceptorPreparationStatus,
) -> ReceptorPreparationRecord:
    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    created_at = datetime.now(UTC)
    content = (FIXTURES / "synthetic_m1.pdb").read_bytes()
    receptor_store.write_bytes(receptor_id, "selected_receptor.pdb", content)
    output = ReceptorOutputArtifact(
        artifact_id=f"{receptor_id}-selected",
        stage=ReceptorOutputStage.SELECTED,
        filename="selected_receptor.pdb",
        format=StructureFormat.PDB,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
        content_url=f"/receptors/{receptor_id}/outputs/{receptor_id}-selected/content",
    )
    record = ReceptorPreparationRecord(
        receptor_id=receptor_id,
        source_artifact_id=source_artifact_id,
        created_at=created_at,
        status=status,
        decisions=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
        ),
        outputs=[output],
        warnings=[],
        provenance=[],
        display_output_artifact_id=output.artifact_id,
    )
    receptor_store.save_record(record)
    return record


def test_parse_predictions_csv_matches_real_p2rank_output_format() -> None:
    rows = _parse_predictions_csv(FIXTURES / "p2rank_1fbl_predictions.csv")

    assert len(rows) == 4
    first = rows[0]
    assert first.name == "pocket1"
    assert first.rank == 1
    assert first.probability == pytest.approx(0.525)
    assert first.center_x == pytest.approx(70.5274)
    assert first.center_y == pytest.approx(83.4375)
    assert first.center_z == pytest.approx(-11.5099)
    # 18 residue tokens listed for pocket1 in the real fixture.
    assert len(first.residue_keys) == 18
    assert first.residue_keys[0] == ("A", 103)
    assert first.residue_keys[-1] == ("A", 240)


def test_parse_predictions_csv_handles_real_column_padded_header() -> None:
    """A locally-executed P2Rank 2.5.1 pads header/value columns for alignment
    (e.g. "name     ," rather than "name,"), which `skipinitialspace` does not
    strip since the padding is trailing, not leading. Verified against a real
    P2Rank subprocess run, not a guessed format."""
    rows = _parse_predictions_csv(FIXTURES / "p2rank_1fbl_predictions_real_run_padded.csv")

    assert len(rows) == 4
    first = rows[0]
    assert first.name == "pocket1"
    assert first.rank == 1
    assert first.probability == pytest.approx(0.525)
    assert first.center_x == pytest.approx(70.5274)
    assert len(first.residue_keys) == 18


def _fake_execute_p2rank_factory(
    csv_rows: list[str],
) -> Callable[..., tuple[ToolExecution, str]]:
    def fake_execute(*, receptor_pdb_path: Path, output_dir: Path) -> tuple[ToolExecution, str]:
        predictions_path = output_dir / f"{receptor_pdb_path.name}_predictions.csv"
        predictions_path.write_text("\n".join(csv_rows) + "\n", encoding="utf-8")
        execution = ToolExecution(
            command=["cmd", "/c", "prank.bat", "predict"], exit_code=0, stdout="", stderr=""
        )
        return execution, "2.4.1"

    return fake_execute


SYNTHETIC_HEADER = (
    "name, rank, score, probability, sas_points, surf_atoms, "
    "center_x, center_y, center_z, residue_ids, surf_atom_ids"
)


def test_detect_pockets_builds_candidates_from_synthetic_p2rank_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    fake = _fake_execute_p2rank_factory([
        SYNTHETIC_HEADER,
        "pocket1, 1, 5.0, 0.75, 10, 5, 12.5, 13.0, 9.0, A_1 A_101, 1 2",
    ])
    monkeypatch.setattr(pocket_detection_module, "execute_p2rank", fake)

    report = detect_pockets(
        receptor_id=receptor.receptor_id,
        receptor_store=receptor_store,
        pocket_detection_store=pocket_detection_store,
    )

    assert report.receptor_id == receptor.receptor_id
    assert report.source_output_artifact_id == receptor.outputs[0].artifact_id
    assert report.tool.name == "P2Rank"
    assert report.execution is not None
    assert report.execution.command == ["cmd", "/c", "prank.bat", "predict"]
    assert report.execution.exit_code == 0
    assert report.execution.stdout == ""
    assert report.execution.stderr == ""
    assert "pocket1, 1, 5.0, 0.75" in report.execution.predictions_csv
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.pocket_id == "pocket1"
    assert candidate.rank == 1
    assert candidate.druggability_score == pytest.approx(0.75)
    assert candidate.volume_angstrom3 is None
    # Center comes straight from P2Rank's own row, not a geometric midpoint.
    assert candidate.box.center_x == pytest.approx(12.5)
    assert candidate.box.center_y == pytest.approx(13.0)
    assert candidate.box.center_z == pytest.approx(9.0)
    # Size is the padded bounding extent of ALA A:1 (incl. both altloc CAs)
    # and LIG A:101's real atoms: x:[11.104, 16.0], y:[12.4, 15.0], z:[8.1, 10.0].
    assert candidate.box.size_x == pytest.approx(4.896 + 2 * POCKET_BOX_PADDING_ANGSTROM)
    assert candidate.box.size_y == pytest.approx(2.6 + 2 * POCKET_BOX_PADDING_ANGSTROM)
    assert candidate.box.size_z == pytest.approx(1.9 + 2 * POCKET_BOX_PADDING_ANGSTROM)
    assert {(item.chain_id, item.sequence_number) for item in candidate.lining_residues} == {
        ("A", 1),
        ("A", 101),
    }
    assert pocket_detection_store.load_record(report.report_id) == report


def test_detect_pockets_requires_docking_ready_receptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.SELECTED,
    )
    monkeypatch.setattr(
        pocket_detection_module, "execute_p2rank", _fake_execute_p2rank_factory([SYNTHETIC_HEADER])
    )

    with pytest.raises(AnkoraDomainError) as captured:
        detect_pockets(
            receptor_id=receptor.receptor_id,
            receptor_store=receptor_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "POCKET_DETECTION_RECEPTOR_NOT_READY"


def test_detect_pockets_rejects_a_failed_p2rank_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    def failing_execute(*, receptor_pdb_path: Path, output_dir: Path) -> tuple[ToolExecution, str]:
        execution = ToolExecution(
            command=["cmd", "/c", "prank.bat", "predict"],
            exit_code=1,
            stdout="",
            stderr="java.lang.OutOfMemoryError",
        )
        return execution, "2.4.1"

    monkeypatch.setattr(pocket_detection_module, "execute_p2rank", failing_execute)

    with pytest.raises(AnkoraDomainError) as captured:
        detect_pockets(
            receptor_id=receptor.receptor_id,
            receptor_store=receptor_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "POCKET_DETECTION_FAILED"
    assert captured.value.details["stderr"] == "java.lang.OutOfMemoryError"


def _pdb_with_insertion_code_ambiguity() -> bytes:
    """Two real, distinct residues that both answer to "chain A, residue 1"
    — they differ only by insertion code (' ' vs 'A'), which P2Rank's own
    residue_ids column never reports. Built through gemmi's own Structure
    API (not hand-typed fixed-column PDB text) and round-tripped through
    a real `write_pdb`/`read_structure` pass to confirm gemmi actually
    preserves both residues distinctly before using it as a fixture."""
    import gemmi

    structure = gemmi.Structure()
    structure.name = "AMBIGUOUS"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")
    for name, icode in (("ALA", " "), ("SER", "A")):
        residue = gemmi.Residue()
        residue.name = name
        residue.seqid = gemmi.SeqId(1, icode)
        atom = gemmi.Atom()
        atom.name = "CA"
        atom.element = gemmi.Element("C")
        atom.pos = gemmi.Position(0.0, 0.0, 0.0)
        residue.add_atom(atom)
        chain.add_residue(residue)
    model.add_chain(chain)
    structure.add_model(model)
    structure.setup_entities()
    return structure.make_pdb_string().encode("utf-8")


def test_detect_pockets_rejects_an_insertion_code_ambiguous_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    created_at = datetime.now(UTC)
    content = _pdb_with_insertion_code_ambiguity()
    receptor_store.write_bytes(receptor_id, "selected_receptor.pdb", content)
    output = ReceptorOutputArtifact(
        artifact_id=f"{receptor_id}-selected",
        stage=ReceptorOutputStage.SELECTED,
        filename="selected_receptor.pdb",
        format=StructureFormat.PDB,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
        content_url=f"/receptors/{receptor_id}/outputs/{receptor_id}-selected/content",
    )
    receptor_store.save_record(
        ReceptorPreparationRecord(
            receptor_id=receptor_id,
            source_artifact_id=artifact_id,
            created_at=created_at,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
            ),
            outputs=[output],
            warnings=[],
            provenance=[],
            display_output_artifact_id=output.artifact_id,
        )
    )
    fake = _fake_execute_p2rank_factory([
        SYNTHETIC_HEADER,
        "pocket1, 1, 5.0, 0.75, 10, 5, 0.0, 0.0, 0.0, A_1, 1",
    ])
    monkeypatch.setattr(pocket_detection_module, "execute_p2rank", fake)

    with pytest.raises(AnkoraDomainError) as captured:
        detect_pockets(
            receptor_id=receptor_id,
            receptor_store=receptor_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "POCKET_DETECTION_RESIDUE_AMBIGUOUS"
    assert set(captured.value.details["insertion_codes"]) == {"", "A"}


def test_detect_pockets_rejects_a_residue_p2rank_reports_that_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    fake = _fake_execute_p2rank_factory([
        SYNTHETIC_HEADER,
        "pocket1, 1, 5.0, 0.75, 10, 5, 12.5, 13.0, 9.0, A_9999, 1",
    ])
    monkeypatch.setattr(pocket_detection_module, "execute_p2rank", fake)

    with pytest.raises(AnkoraDomainError) as captured:
        detect_pockets(
            receptor_id=receptor.receptor_id,
            receptor_store=receptor_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "POCKET_DETECTION_RESIDUE_NOT_FOUND"
