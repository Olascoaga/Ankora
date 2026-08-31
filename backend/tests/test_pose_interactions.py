"""M9 pose-interaction contracts.

Every molecule and coordinate file in this module is explicitly synthetic.
The detector itself is replaced by a deterministic test double here: the real
ProLIF adapter is exercised by the recorded Windows smoke, while these tests
fix identity, hash, persistence, and engine-native pose semantics without
inventing a reference scientific result.
"""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.pose_interaction_store import PoseInteractionStore
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.pose_complexes import PoseComplexExportRequest
from ankora_backend.schemas.pose_interactions import (
    InteractionAnalysisRequest,
    InteractionContact,
    LigandDiagram,
    LigandDiagramAtom,
)
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.schemas.receptors import ReceptorOutputArtifact, ReceptorOutputStage
from ankora_backend.schemas.structures import StructureFormat
from ankora_backend.services.pose_complex_export import PoseComplexExportService
from ankora_backend.services.pose_interactions import PoseInteractionService

NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)
RECEPTOR = "00000000-0000-0000-0000-000000000001"
LIGAND = "00000000-0000-0000-0000-000000000002"
PREPARATION = "00000000-0000-0000-0000-000000000003"
CONFORMER = "00000000-0000-0000-0000-000000000004"
JOB = "00000000-0000-0000-0000-000000000005"
POSE = f"{JOB}-pose-1"


class _VinaStore:
    def __init__(self, record: VinaDockingJobRecord, pose_path: Path) -> None:
        self.record = record
        self.pose_path = pose_path

    def load_record(self, job_id: str) -> VinaDockingJobRecord:
        assert job_id == JOB
        return self.record

    def pose_content_path(self, job_id: str, artifact_id: str) -> Path:
        assert (job_id, artifact_id) == (JOB, POSE)
        return self.pose_path


class _UnusedStore:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"The synthetic Vina test must not use {name}")


class _ReceptorStore:
    def __init__(self, pdbqt: Path, pdb: Path) -> None:
        self.paths = {"receptor-pdbqt": pdbqt, "receptor-pdb": pdb}
        self.outputs = [
            _output("receptor-pdbqt", ReceptorOutputStage.PDBQT, pdbqt, "pdbqt"),
            _output("receptor-pdb", ReceptorOutputStage.PROTONATED_PDB, pdb, StructureFormat.PDB),
        ]

    def load_record(self, receptor_id: str) -> Any:
        assert receptor_id == RECEPTOR
        return SimpleNamespace(outputs=self.outputs)

    def content_path(self, receptor_id: str, artifact_id: str) -> Path:
        assert receptor_id == RECEPTOR
        return self.paths[artifact_id]


class _LigandStore:
    def __init__(self, pdbqt: Path, conformer: Path) -> None:
        self.pdbqt = pdbqt
        self.conformer = conformer
        self.preparation = SimpleNamespace(
            artifact=SimpleNamespace(
                preparation_id=PREPARATION,
                ligand_id=LIGAND,
                conformer_id=CONFORMER,
                sha256=_hash(pdbqt),
            )
        )
        self.conformer_record = SimpleNamespace(
            artifact=SimpleNamespace(conformer_id=CONFORMER, sha256=_hash(conformer))
        )

    def load_pdbqt_record(self, ligand_id: str, preparation_id: str) -> Any:
        assert (ligand_id, preparation_id) == (LIGAND, PREPARATION)
        return self.preparation

    def load_conformer_record(self, ligand_id: str, conformer_id: str) -> Any:
        assert (ligand_id, conformer_id) == (LIGAND, CONFORMER)
        return self.conformer_record

    def conformer_content_path(self, ligand_id: str, conformer_id: str) -> Path:
        assert (ligand_id, conformer_id) == (LIGAND, CONFORMER)
        return self.conformer


class _Detector:
    calls = 0

    @staticmethod
    def version() -> str:
        return "2.2.synthetic"

    def analyze(self, **paths: Any) -> tuple[list[InteractionContact], LigandDiagram]:
        self.calls += 1
        assert all(Path(value).is_file() for key, value in paths.items() if key.endswith("_path"))
        return [
            InteractionContact(
                contact_id="contact-1",
                detector_type="Hydrophobic",
                display_type="Hydrophobic",
                residue={
                    "chain_id": "A",
                    "residue_name": "LEU",
                    "sequence_number": 42,
                    "insertion_code": "",
                },
                ligand_atom_indices=[0],
                protein_atom_indices=[8],
                ligand_atom_labels=["C1"],
                protein_atom_labels=["CD1"],
                distance_angstrom=3.8,
                geometry={"distance": 3.8},
            )
        ], LigandDiagram(
            atoms=[LigandDiagramAtom(atom_index=0, element="C", label="C1", x=0, y=0)]
        )


def _output(
    artifact_id: str, stage: ReceptorOutputStage, path: Path, format_: str | StructureFormat
) -> ReceptorOutputArtifact:
    return ReceptorOutputArtifact(
        artifact_id=artifact_id,
        stage=stage,
        filename=path.name,
        format=format_,
        sha256=_hash(path),
        size_bytes=path.stat().st_size,
        created_at=NOW,
        content_url=f"/synthetic/{artifact_id}",
    )


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _service(
    tmp_path: Path,
    *,
    receptor_pdb: bytes | None = None,
    pose_pdbqt: bytes | None = None,
) -> tuple[PoseInteractionService, Path, _Detector]:
    pdbqt = tmp_path / "receptor.pdbqt"
    pdb = tmp_path / "receptor.pdb"
    ligand_pdbqt = tmp_path / "ligand.pdbqt"
    conformer = tmp_path / "conformer.sdf"
    pose_path = tmp_path / "pose_1.pdbqt"
    pdbqt.write_bytes(b"REMARK explicitly synthetic receptor\n")
    pdb.write_bytes(
        receptor_pdb or b"REMARK explicitly synthetic protonated receptor\n"
    )
    ligand_pdbqt.write_bytes(b"REMARK explicitly synthetic ligand\n")
    conformer.write_bytes(b"explicitly synthetic conformer\n")
    pose_path.write_bytes(pose_pdbqt or b"REMARK explicitly synthetic pose\n")
    pose = DockingPoseResult(
        mode=1,
        affinity_kcal_mol=-6.25,
        rmsd_lower_bound_angstrom=0,
        rmsd_upper_bound_angstrom=0,
        artifact=DockingPoseArtifact(
            artifact_id=POSE,
            mode=1,
            filename="pose_1.pdbqt",
            format="pdbqt",
            sha256=_hash(pose_path),
            size_bytes=pose_path.stat().st_size,
            content_url="/synthetic/pose",
        ),
    )
    record = VinaDockingJobRecord(
        job_id=JOB,
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=NOW,
        request=VinaDockingRequest(
            receptor_id=RECEPTOR,
            binding_site_id="synthetic-site",
            ligand_id=LIGAND,
            ligand_preparation_id=PREPARATION,
            parameters=VinaDockingParameters(),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=ToolIdentity(name="synthetic Vina", version="1.2.7"),
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256=_hash(pdbqt),
        ligand_sha256=_hash(ligand_pdbqt),
        poses=[pose],
    )
    detector = _Detector()
    return PoseInteractionService(
        docking_store=_VinaStore(record, pose_path),  # type: ignore[arg-type]
        autodock4_store=_UnusedStore(),  # type: ignore[arg-type]
        autodock_gpu_store=_UnusedStore(),  # type: ignore[arg-type]
        autogrid_store=_UnusedStore(),  # type: ignore[arg-type]
        receptor_store=_ReceptorStore(pdbqt, pdb),  # type: ignore[arg-type]
        ligand_store=_LigandStore(ligand_pdbqt, conformer),  # type: ignore[arg-type]
        interaction_store=PoseInteractionStore(tmp_path),
        adapter=detector,  # type: ignore[arg-type]
    ), pose_path, detector


def test_vina_inventory_preserves_the_native_mode_and_quantity(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    inventory = service.list_poses(f"vina_job:{JOB}", LIGAND)

    assert inventory.engine_label == "synthetic Vina 1.2.7"
    assert inventory.receptor_artifact_id == "receptor-pdb"
    assert inventory.poses[0].kind == "vina_mode"
    assert inventory.poses[0].label == "Mode 1"
    assert inventory.poses[0].value_label == "Vina score"


def test_an_analysis_is_create_only_and_reopens_after_restart(tmp_path: Path) -> None:
    service, _, detector = _service(tmp_path)

    first = service.analyze(f"vina_job:{JOB}", LIGAND, POSE, InteractionAnalysisRequest())
    second = service.analyze(f"vina_job:{JOB}", LIGAND, POSE, InteractionAnalysisRequest())
    reopened = PoseInteractionStore(tmp_path).list_for_pose(f"vina_job:{JOB}", LIGAND, POSE)

    assert first.analysis_id != second.analysis_id
    assert detector.calls == 2
    assert {item.analysis_id for item in reopened} == {first.analysis_id, second.analysis_id}
    assert reopened[0].detector.version == "2.2.synthetic"
    assert reopened[0].contacts[0].residue.sequence_number == 42
    assert reopened[0].conformer_sha256 == _hash(tmp_path / "conformer.sdf")


def test_hash_drift_fails_before_the_detector_runs(tmp_path: Path) -> None:
    service, pose_path, detector = _service(tmp_path)
    pose_path.write_bytes(b"mutated synthetic pose\n")

    with pytest.raises(AnkoraDomainError) as captured:
        service.analyze(f"vina_job:{JOB}", LIGAND, POSE, InteractionAnalysisRequest())

    assert captured.value.code == "POSE_INTERACTION_INPUT_HASH_MISMATCH"
    assert detector.calls == 0


def test_a_pose_from_another_molecule_is_rejected(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    with pytest.raises(AnkoraDomainError) as captured:
        service.list_poses(f"vina_job:{JOB}", "some-other-ligand")

    assert captured.value.code == "RESULT_LIGAND_NOT_FOUND"


# --- one PDB a scientist can open somewhere else ---------------------------

RECEPTOR_PDB = (
    """
ATOM      1  N   LEU A  42      10.000  11.000  12.000  1.00 20.00           N
ATOM      2  CD1 LEU A  42      11.500  11.200  12.400  1.00 20.00           C
HETATM    3  O   HOH B 501      30.000  30.000  30.000  1.00 30.00           O
ATOM      4  CA  GLY Z   7      40.000  40.000  40.000  1.00 25.00           C
"""
    .lstrip()
    .encode()
)

POSE_PDBQT = (
    """
REMARK  explicitly synthetic pose
ROOT
ATOM      1  C1  UNL     1      12.000  11.000  12.500  1.00  0.00     0.012 C
ATOM      2  O1  UNL     1      13.100  11.400  12.900  1.00  0.00    -0.245 OA
ATOM      3  H1  UNL     1      13.600  11.900  13.400  1.00  0.00     0.210 HD
ENDROOT
TORSDOF 0
"""
    .lstrip()
    .encode()
)


def _complex(tmp_path: Path) -> str:
    service, _, _ = _service(
        tmp_path, receptor_pdb=RECEPTOR_PDB, pose_pdbqt=POSE_PDBQT
    )
    document, _ = service.complex_pdb(f"vina_job:{JOB}", LIGAND, POSE)
    return document


def _atoms(document: str) -> list[str]:
    return [
        line for line in document.splitlines() if line.startswith(("ATOM", "HETATM"))
    ]


def test_the_complex_carries_the_receptor_coordinates_unchanged(tmp_path: Path) -> None:
    """A file opened in PyMOL has to be the geometry Ankora analyzed.

    Anything re-minimized, superimposed or re-oriented on the way out would
    make the other viewer disagree with this one about where the pose is.
    """
    lines = _atoms(_complex(tmp_path))

    assert lines[:4] == RECEPTOR_PDB.decode().splitlines()


def test_the_pose_reads_back_as_one_ligand_rather_than_many(tmp_path: Path) -> None:
    """Three separate columns each split this ligand apart, measured with gemmi.

    A PDBQT names every atom for its element, restarts serials at 1, and leaves
    the partial charge in columns 67-76 - where 73-76 are the *segment*
    identifier. Any one of those makes a reader treat one 30-atom ligand as a
    handful of fragments, which is exactly what "open it in PyMOL" must not do.
    """
    document = _complex(tmp_path)
    ligand = [line for line in _atoms(document) if "UNL" in line]

    # Unique names, so no two atoms of the residue collide.
    assert len({line[12:16] for line in ligand}) == len(ligand)
    # Serials continue the receptor's rather than restarting at 1.
    assert [int(line[6:11]) for line in ligand] == [5, 6, 7]
    # Columns 67-76 are blank: the charge is a PDBQT field, not a PDB one.
    assert all(line[66:76] == " " * 10 for line in ligand)


def test_the_pose_keeps_its_own_coordinates_and_atoms(tmp_path: Path) -> None:
    ligand = [line for line in _atoms(_complex(tmp_path)) if "UNL" in line]

    assert len(ligand) == 3
    assert "12.000  11.000  12.500" in ligand[0]
    # The AutoDock type is translated to the element it stands for, and the
    # polar hydrogen the pose carries is kept rather than dropped.
    assert [line[76:78].strip() for line in ligand] == ["C", "O", "H"]
    assert [line[12:16].strip() for line in ligand] == ["C1", "O1", "H1"]


def test_the_ligand_gets_a_chain_the_receptor_does_not_already_use(
    tmp_path: Path,
) -> None:
    """Reusing A or B would silently merge the pose into the protein."""
    document = _complex(tmp_path)
    ligand = [line for line in _atoms(document) if "UNL" in line]

    # The receptor already occupies A, B and Z, so Y is the first one free.
    chains = {line[21] for line in ligand}
    assert chains == {"Y"}
    assert "LIGAND CHAIN    Y" in document


def test_the_complex_states_what_it_is_and_what_the_number_is_not(
    tmp_path: Path,
) -> None:
    document = _complex(tmp_path)

    assert "REMARK   1 Ankora ligand-receptor complex" in document
    assert f"REMARK   1 RESULT          vina_job:{JOB}" in document
    assert "POSE            Mode 1" in document
    assert "-6.250 kcal/mol (Vina score)" in document
    assert "not a" in document and "measured binding affinity" in document
    # The two hashes that make the file traceable back to this exact result.
    assert document.count("SHA256") == 2
    assert document.rstrip().endswith("END")


def test_the_complex_refuses_a_receptor_whose_bytes_changed(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path, receptor_pdb=RECEPTOR_PDB, pose_pdbqt=POSE_PDBQT)
    receptor = tmp_path / "receptor.pdb"
    receptor.write_bytes(
        RECEPTOR_PDB + b"ATOM      4  CA  GLY A  43       1.0   1.0   1.0"
    )

    with pytest.raises(AnkoraDomainError) as captured:
        service.complex_pdb(f"vina_job:{JOB}", LIGAND, POSE)

    assert captured.value.code == "POSE_INTERACTION_INPUT_HASH_MISMATCH"


# --- the coordinate file lands somewhere explicit --------------------------


def test_the_complex_is_written_into_the_chosen_working_folder(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path, receptor_pdb=RECEPTOR_PDB, pose_pdbqt=POSE_PDBQT)
    expected, _ = service.complex_pdb(f"vina_job:{JOB}", LIGAND, POSE)
    destination = tmp_path / "working"
    destination.mkdir()

    exported = PoseComplexExportService(root=tmp_path, pose_service=service).export(
        f"vina_job:{JOB}",
        LIGAND,
        POSE,
        PoseComplexExportRequest(molecule_name="RV2", destination=str(destination)),
    )

    written = destination / exported.file.filename
    assert exported.file.filename == "RV2_complex_Mode_1.pdb"
    assert written.read_text(encoding="utf-8") == expected
    assert exported.directory == str(destination)
    assert exported.outside_project is True
    assert exported.pose_label == "Mode 1"
    assert exported.file.sha256 == _hash(written)


def test_the_project_keeps_an_exact_manifest_when_the_pdb_leaves_it(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path, receptor_pdb=RECEPTOR_PDB, pose_pdbqt=POSE_PDBQT)
    destination = tmp_path / "working"
    destination.mkdir()

    exported = PoseComplexExportService(root=tmp_path, pose_service=service).export(
        f"vina_job:{JOB}",
        LIGAND,
        POSE,
        PoseComplexExportRequest(molecule_name="RV2", destination=str(destination)),
    )

    record_directory = Path(exported.record_directory)
    assert {item.name for item in record_directory.iterdir()} == {"complex.json"}
    manifest = json.loads((record_directory / "complex.json").read_text(encoding="utf-8"))
    assert manifest["catalog_id"] == f"vina_job:{JOB}"
    assert manifest["ligand_id"] == LIGAND
    assert manifest["pose_artifact_id"] == POSE
    assert manifest["file"]["sha256"] == exported.file.sha256
    assert manifest["written_to"] == str(destination)
    assert (destination / "RV2_complex_Mode_1.json").is_file()


def test_saving_the_same_complex_twice_never_overwrites_the_first(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path, receptor_pdb=RECEPTOR_PDB, pose_pdbqt=POSE_PDBQT)
    destination = tmp_path / "working"
    destination.mkdir()
    exporter = PoseComplexExportService(root=tmp_path, pose_service=service)
    request = PoseComplexExportRequest(molecule_name="RV2", destination=str(destination))

    first = exporter.export(f"vina_job:{JOB}", LIGAND, POSE, request)
    second = exporter.export(f"vina_job:{JOB}", LIGAND, POSE, request)

    assert first.file.filename == "RV2_complex_Mode_1.pdb"
    assert second.file.filename == "RV2_complex_Mode_1 (2).pdb"
    assert (destination / first.file.filename).is_file()
    assert (destination / second.file.filename).is_file()


def test_without_a_chosen_folder_the_pdb_stays_in_the_project(
    tmp_path: Path,
) -> None:
    service, _, _ = _service(tmp_path, receptor_pdb=RECEPTOR_PDB, pose_pdbqt=POSE_PDBQT)

    exported = PoseComplexExportService(root=tmp_path, pose_service=service).export(
        f"vina_job:{JOB}",
        LIGAND,
        POSE,
        PoseComplexExportRequest(molecule_name="RV2"),
    )

    assert exported.outside_project is False
    assert exported.directory == exported.record_directory
    assert {item.name for item in Path(exported.directory).iterdir()} == {
        "ligand_receptor_complex.pdb",
        "complex.json",
    }
