"""Synthetic contracts for explicit M4 binding-site definition."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRequest,
    BindingSiteSource,
    LigandDerivedOrigin,
    PocketCandidate,
    PocketDetectionReport,
    PocketSelection,
    ResidueSelectionOrigin,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.schemas.structures import StructureFormat, StructureSource
from ankora_backend.services.binding_site_definition import define_binding_site
from ankora_backend.services.structure_inspection import import_structure_bytes

FIXTURES = Path(__file__).parent / "fixtures"
LIG_LOCATOR = ResidueLocator(
    chain_id="A", residue_name="LIG", sequence_number=101, insertion_code=""
)


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
    # Real, gemmi-readable content: the full_protein_blind box is computed
    # from this file's actual atoms, not just its record metadata.
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


def test_binding_site_from_co_crystallized_ligand_computes_padded_bounding_box(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    record = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.CO_CRYSTALLIZED_LIGAND,
            ligand_origin=LigandDerivedOrigin(heterogen=LIG_LOCATOR, padding_angstrom=5.0),
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    # LIG A:101 atoms are at (15, 15, 10) and (16, 15, 10); the box must be
    # centered on their midpoint with each extent padded by 5.0 Å per side.
    assert record.box.center_x == pytest.approx(15.5)
    assert record.box.center_y == pytest.approx(15.0)
    assert record.box.center_z == pytest.approx(10.0)
    assert record.box.size_x == pytest.approx(11.0)
    assert record.box.size_y == pytest.approx(10.0)
    assert record.box.size_z == pytest.approx(10.0)
    assert record.receptor_id == receptor.receptor_id
    assert record.source_artifact_id == artifact_id
    assert record.stale is False
    assert record.provenance[0].input_artifacts == [artifact_id, receptor.receptor_id]
    assert binding_site_store.load_record(record.binding_site_id) == record


def test_binding_site_from_selected_residues_fits_the_exact_prepared_atoms(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    ala = ResidueLocator(
        chain_id="A", residue_name="ALA", sequence_number=1, insertion_code=""
    )

    record = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.SELECTED_RESIDUES,
            residue_selection=ResidueSelectionOrigin(residues=[ala], padding_angstrom=4.0),
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    # Synthetic ALA A:1 spans x=11.104..14.500, y=12.400..13.207,
    # z=8.100..9.000. Padding is added independently on both sides.
    assert record.box.center_x == pytest.approx(12.802)
    assert record.box.center_y == pytest.approx(12.8035)
    assert record.box.center_z == pytest.approx(8.55)
    assert record.box.size_x == pytest.approx(11.396)
    assert record.box.size_y == pytest.approx(8.807)
    assert record.box.size_z == pytest.approx(8.9)
    assert record.decisions.residue_selection is not None
    assert record.decisions.residue_selection.residues == [ala]
    assert record.provenance[0].parameters["decisions"]["residue_selection"] == {
        "residues": [ala.model_dump(mode="json")],
        "padding_angstrom": 4.0,
    }


def test_binding_site_from_selected_residues_rejects_a_missing_locator(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    missing = ResidueLocator(
        chain_id="A", residue_name="TYR", sequence_number=999, insertion_code=""
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.SELECTED_RESIDUES,
                residue_selection=ResidueSelectionOrigin(
                    residues=[missing], padding_angstrom=5.0
                ),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )

    assert captured.value.code == "BINDING_SITE_SELECTED_RESIDUE_NOT_FOUND"
    assert captured.value.details["missing_residues"] == [missing.model_dump(mode="json")]


def test_binding_site_manual_box_is_stored_as_is(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    manual_box = BindingBox(
        center_x=1.0, center_y=2.0, center_z=3.0, size_x=20.0, size_y=22.0, size_z=24.0
    )

    record = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=manual_box),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    assert record.box == manual_box


def test_manual_adjustment_links_the_parent_binding_site_in_provenance(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    parent = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.MANUAL,
            manual_box=BindingBox(
                center_x=0, center_y=0, center_z=0, size_x=20, size_y=20, size_z=20
            ),
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    adjusted = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.MANUAL,
            manual_box=BindingBox(
                center_x=2, center_y=0, center_z=0, size_x=24, size_y=20, size_z=20
            ),
            parent_binding_site_id=parent.binding_site_id,
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    assert adjusted.decisions.parent_binding_site_id == parent.binding_site_id
    assert adjusted.provenance[0].input_artifacts == [
        artifact_id,
        receptor.receptor_id,
        parent.binding_site_id,
    ]


def test_manual_adjustment_rejects_a_parent_from_another_receptor(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor_a = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    receptor_b = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    parent = define_binding_site(
        receptor_id=receptor_a.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.MANUAL,
            manual_box=BindingBox(
                center_x=0, center_y=0, center_z=0, size_x=20, size_y=20, size_z=20
            ),
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor_b.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.MANUAL,
                manual_box=parent.box,
                parent_binding_site_id=parent.binding_site_id,
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )

    assert captured.value.code == "BINDING_SITE_PARENT_RECEPTOR_MISMATCH"


def test_binding_site_requires_docking_ready_receptor(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.SELECTED,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.CO_CRYSTALLIZED_LIGAND,
                ligand_origin=LigandDerivedOrigin(heterogen=LIG_LOCATOR),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "BINDING_SITE_RECEPTOR_NOT_READY"


def test_binding_site_rejects_heterogen_not_present_in_structure(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    missing_locator = ResidueLocator(
        chain_id="A", residue_name="XXX", sequence_number=999, insertion_code=""
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.CO_CRYSTALLIZED_LIGAND,
                ligand_origin=LigandDerivedOrigin(heterogen=missing_locator),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "BINDING_SITE_HETEROGEN_NOT_FOUND"


def test_binding_site_rejects_degenerate_box_from_zero_padding(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    # LIG A:101's two atoms share the same y and z coordinates, so a box
    # with zero padding has zero extent on those axes.
    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.CO_CRYSTALLIZED_LIGAND,
                ligand_origin=LigandDerivedOrigin(heterogen=LIG_LOCATOR, padding_angstrom=0.0),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "BINDING_SITE_BOX_DEGENERATE"


def test_binding_site_full_protein_blind_computes_bounding_box_over_the_whole_receptor(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    record = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(source=BindingSiteSource.FULL_PROTEIN_BLIND),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    # Every atom in synthetic_m1.pdb (ALA including both altloc CAs, LIG,
    # HOH, ZN) spans x:[9.0, 16.0], y:[9.0, 15.0], z:[8.1, 10.0]; the
    # default 6.0 Å blind margin pads every side.
    assert record.box.center_x == pytest.approx(12.5)
    assert record.box.center_y == pytest.approx(12.0)
    assert record.box.center_z == pytest.approx(9.05)
    assert record.box.size_x == pytest.approx(19.0)
    assert record.box.size_y == pytest.approx(18.0)
    assert record.box.size_z == pytest.approx(13.9)
    assert record.decisions.source == BindingSiteSource.FULL_PROTEIN_BLIND


def test_binding_site_full_protein_blind_respects_custom_margin(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    record = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.FULL_PROTEIN_BLIND, blind_margin_angstrom=0.0
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    assert record.box.size_x == pytest.approx(7.0)
    assert record.box.size_y == pytest.approx(6.0)
    assert record.box.size_z == pytest.approx(1.9)


def _pocket_report(
    *,
    pocket_detection_store: PocketDetectionArtifactStore,
    receptor_id: str,
    source_output_artifact_id: str,
    pocket_id: str = "pocket1",
) -> PocketDetectionReport:
    report_id = pocket_detection_store.new_report_id()
    generated_at = datetime.now(UTC)
    tool = ToolIdentity(name="P2Rank", version="2.4.1")
    candidate = PocketCandidate(
        pocket_id=pocket_id,
        rank=1,
        druggability_score=0.8,
        volume_angstrom3=None,
        box=BindingBox(
            center_x=1.0, center_y=2.0, center_z=3.0, size_x=10.0, size_y=10.0, size_z=10.0
        ),
        lining_residues=[LIG_LOCATOR],
    )
    report = PocketDetectionReport(
        report_id=report_id,
        receptor_id=receptor_id,
        source_output_artifact_id=source_output_artifact_id,
        generated_at=generated_at,
        tool=tool,
        candidates=[candidate],
        warnings=[],
        provenance=ProvenanceEvent(
            event_id=f"pocket-detection-{report_id}",
            event_type="pockets_detected",
            timestamp=generated_at,
            input_artifacts=[receptor_id],
            output_artifacts=[report_id],
            tool=tool,
        ),
    )
    pocket_detection_store.save_record(report)
    return report


def test_binding_site_from_detected_pocket_uses_the_selected_candidates_box(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    report = _pocket_report(
        pocket_detection_store=pocket_detection_store,
        receptor_id=receptor.receptor_id,
        source_output_artifact_id=receptor.outputs[0].artifact_id,
    )

    record = define_binding_site(
        receptor_id=receptor.receptor_id,
        request=BindingSiteRequest(
            source=BindingSiteSource.POCKET_DETECTED,
            pocket_selection=PocketSelection(report_id=report.report_id, pocket_id="pocket1"),
        ),
        structure_store=structure_store,
        receptor_store=receptor_store,
        binding_site_store=binding_site_store,
        pocket_detection_store=pocket_detection_store,
    )

    assert record.box == report.candidates[0].box


def test_binding_site_rejects_an_unknown_pocket_report(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.POCKET_DETECTED,
                pocket_selection=PocketSelection(
                    report_id="9c1f9c1a-1111-4b2b-8a1a-000000000000", pocket_id="pocket1"
                ),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "BINDING_SITE_POCKET_REPORT_NOT_FOUND"


def test_binding_site_rejects_a_pocket_id_not_in_the_report(tmp_path: Path) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    report = _pocket_report(
        pocket_detection_store=pocket_detection_store,
        receptor_id=receptor.receptor_id,
        source_output_artifact_id=receptor.outputs[0].artifact_id,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.POCKET_DETECTED,
                pocket_selection=PocketSelection(
                    report_id=report.report_id, pocket_id="does-not-exist"
                ),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "BINDING_SITE_POCKET_NOT_FOUND"


def test_binding_site_rejects_a_pocket_report_from_a_different_receptor(
    tmp_path: Path,
) -> None:
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    binding_site_store = BindingSiteArtifactStore(tmp_path)
    pocket_detection_store = PocketDetectionArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor_a = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    receptor_b = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )
    report = _pocket_report(
        pocket_detection_store=pocket_detection_store,
        receptor_id=receptor_a.receptor_id,
        source_output_artifact_id=receptor_a.outputs[0].artifact_id,
    )

    with pytest.raises(AnkoraDomainError) as captured:
        define_binding_site(
            receptor_id=receptor_b.receptor_id,
            request=BindingSiteRequest(
                source=BindingSiteSource.POCKET_DETECTED,
                pocket_selection=PocketSelection(report_id=report.report_id, pocket_id="pocket1"),
            ),
            structure_store=structure_store,
            receptor_store=receptor_store,
            binding_site_store=binding_site_store,
            pocket_detection_store=pocket_detection_store,
        )
    assert captured.value.code == "BINDING_SITE_POCKET_REPORT_MISMATCH"


def test_binding_site_preview_computes_full_receptor_box_without_persisting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthetic preview contract: geometry is returned, no artifact is written."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    response = client.post(
        f"/api/v1/receptors/{receptor.receptor_id}/binding-site-preview",
        json={"source": "full_protein_blind", "blind_margin_angstrom": 6.0},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "full_protein_blind"
    assert response.json()["box"]["size_x"] == pytest.approx(19.0)
    assert not (tmp_path / "projects" / "default" / "derived" / "binding_sites").exists()


def test_binding_site_api_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    structure_store = StructureArtifactStore(tmp_path)
    receptor_store = ReceptorArtifactStore(tmp_path)
    artifact_id = _import_synthetic(structure_store)
    receptor = _receptor_record(
        receptor_store=receptor_store,
        source_artifact_id=artifact_id,
        status=ReceptorPreparationStatus.DOCKING_READY,
    )

    created = client.post(
        f"/api/v1/receptors/{receptor.receptor_id}/binding-sites",
        json={
            "source": "co_crystallized_ligand",
            "ligand_origin": {
                "heterogen": {
                    "chain_id": "A",
                    "residue_name": "LIG",
                    "sequence_number": 101,
                    "insertion_code": "",
                },
                "padding_angstrom": 4.0,
            },
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["box"]["size_x"] == pytest.approx(9.0)

    fetched = client.get(f"/api/v1/binding-sites/{body['binding_site_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body
