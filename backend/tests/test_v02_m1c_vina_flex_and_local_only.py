"""Tests for Vina 1.2.7 FlexRes, Vinardo, --local_only derivatives, and E8 PoseInteractions.

All fixtures in this module are synthetic and explicitly labelled synthetic.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from ankora_backend.adapters.engines.vina import (
    VinaInstallation,
    build_vina_arguments,
    build_vina_local_only_arguments,
    parse_vina_local_only_output,
    parse_vina_poses,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.pose_interaction_store import PoseInteractionStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.docking import (
    DockingJobStatus,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
    VinaLocalRefinementRequest,
    VinaScoringFunction,
)
from ankora_backend.schemas.ligands import (
    LigandArtifact,
    LigandChargeModel,
    LigandConformerArtifact,
    LigandConformerRecord,
    LigandForceField,
    LigandFormat,
    LigandInspection,
    LigandMinimizationResult,
    LigandPdbqtArtifact,
    LigandPdbqtRecord,
    LigandRecord,
    LigandSource,
)
from ankora_backend.schemas.pose_interactions import (
    InteractionAnalysisRecord,
    InteractionAnalysisRequest,
    LigandDiagram,
    LigandDiagramAtom,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorFlexMode,
    ReceptorFlexRequest,
    ReceptorFlexSpec,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
    ResidueLocator,
)
from ankora_backend.services.pose_interactions import PoseInteractionService
from ankora_backend.services.vina_docking import VinaDockingService

_BOX = BindingBox(
    center_x=-1.0,
    center_y=-1.0,
    center_z=-1.0,
    size_x=20.0,
    size_y=20.0,
    size_z=20.0,
)

_SYNTHETIC_CRYSTAL_PDB = (
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00           N  \n"
    "ATOM      2  CA  MET A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00           C  \n"
    "ATOM      4  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00           O  \n"
    "ATOM      5  HA  MET A   5      -0.350   0.650   0.780  1.00  0.00           H  \n"
    "ATOM      6  CB  MET A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      7  CG  MET A   5       2.040   1.440   0.000  1.00  0.00           C  \n"
    "ATOM      8  SD  MET A   5       3.850   1.440   0.000  1.00  0.00           S  \n"
    "ATOM      9  CE  MET A   5       4.200   3.190   0.250  1.00  0.00           C  \n"
    "ATOM     10  HB2 MET A   5       1.894  -0.514   0.890  1.00  0.00           H  \n"
    "ATOM     11  HB3 MET A   5       1.894  -0.514  -0.890  1.00  0.00           H  \n"
    "ATOM     12  HG2 MET A   5       1.676   1.954   0.890  1.00  0.00           H  \n"
    "ATOM     13  HG3 MET A   5       1.676   1.954  -0.890  1.00  0.00           H  \n"
    "ATOM     14  HE1 MET A   5       5.280   3.310   0.250  1.00  0.00           H  \n"
    "ATOM     15  HE2 MET A   5       3.780   3.620   1.158  1.00  0.00           H  \n"
    "ATOM     16  HE3 MET A   5       3.780   3.620  -0.658  1.00  0.00           H  \n"
    "END\n"
)

_SYNTHETIC_RIGID_PDBQT = (
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00     0.000 N \n"
    "ATOM      2  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00     0.000 C \n"
    "ATOM      3  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00     0.000 OA\n"
)

_SYNTHETIC_FLEX_INITIAL_PDBQT = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040   1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850   1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200   3.190   0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)

# Synthetic moved MET side-chain (rotated around CA-CB by ~180 deg so CG/SD/CE move > 2.8 A).
_SYNTHETIC_FLEX_MOVED_PDBQT = (
    "BEGIN_RES MET A 5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   1   2\n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040  -1.440   0.000  1.00  0.00     0.000 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850  -1.440   0.000  1.00  0.00     0.000 SA\n"
    "ATOM      5  CE  MET A   5       4.200  -3.190  -0.250  1.00  0.00     0.000 C \n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "ENDBRANCH   1   2\n"
    "END_RES MET A 5\n"
)

_SYNTHETIC_LIGAND_PDBQT = (
    "ROOT\n"
    "ATOM      1  C   UNL     1       1.000  -2.500   0.500  1.00  0.00     0.000 C \n"
    "ATOM      2  O   UNL     1       2.200  -2.500   0.500  1.00  0.00     0.000 OA\n"
    "ENDROOT\n"
    "TORSDOF 0\n"
)

_SYNTHETIC_WINDOWS_VINA_FLEX_OUT = (
    "MODEL 1\r\n"
    "REMARK VINA RESULT:    -3.512      0.000      0.000\r\n"
    + _SYNTHETIC_LIGAND_PDBQT.replace("\n", "\r\n")
    + ("\x00" * 30)
    + "\r\n"
    + _SYNTHETIC_FLEX_MOVED_PDBQT.replace("\n", "\r\n")
    + "ENDMDL\r\n"
)

_SYNTHETIC_LOCAL_ONLY_STDOUT = (
    "AutoDock Vina v1.2.7\n"
    "Performing local search ... done.\n"
    "Estimated Free Energy of Binding   : -3.567 (kcal/mol) [=(1)+(2)+(3)-(4)]\n"
    "(1) Final Intermolecular Energy    : -4.285 (kcal/mol)\n"
    "(2) Final Total Internal Energy    : -1.710 (kcal/mol)\n"
    "(3) Torsional Free Energy          : 0.834 (kcal/mol)\n"
    "(4) Unbound System's Energy        : -1.595 (kcal/mol)\n"
)

# Flat PDBQT (0 MODEL tags) echoing STALE REMARK VINA RESULT (-3.512 != -3.567 stdout!).
_SYNTHETIC_LOCAL_ONLY_FLAT_PDBQT = (
    "REMARK VINA RESULT:    -3.512      0.000      0.000\r\n"
    + _SYNTHETIC_LIGAND_PDBQT.replace("\n", "\r\n")
    + ("\x00" * 30)
    + "\r\n"
    + _SYNTHETIC_FLEX_MOVED_PDBQT.replace("\n", "\r\n")
)


def test_vina_arguments_preserve_v01_default_and_expose_flex_and_vinardo() -> None:
    default_params = VinaDockingParameters()
    assert "scoring" not in default_params.model_dump(mode="json")

    default_args = build_vina_arguments(
        receptor_path=Path("receptor.pdbqt"),
        ligand_path=Path("ligand.pdbqt"),
        output_path=Path("out.pdbqt"),
        box=_BOX,
        parameters=default_params,
    )
    assert "--flex" not in default_args
    assert "--scoring" not in default_args

    vinardo_params = VinaDockingParameters(scoring=VinaScoringFunction.VINARDO)
    assert vinardo_params.model_dump(mode="json")["scoring"] == "vinardo"

    flex_args = build_vina_arguments(
        receptor_path=Path("receptor_rigid.pdbqt"),
        flex_receptor_path=Path("receptor_flex.pdbqt"),
        ligand_path=Path("ligand.pdbqt"),
        output_path=Path("out.pdbqt"),
        box=_BOX,
        parameters=vinardo_params,
    )
    assert flex_args[:4] == [
        "--receptor",
        "receptor_rigid.pdbqt",
        "--flex",
        "receptor_flex.pdbqt",
    ]
    assert "--scoring" in flex_args
    assert flex_args[flex_args.index("--scoring") + 1] == "vinardo"

    local_args = build_vina_local_only_arguments(
        receptor_path=Path("receptor_rigid.pdbqt"),
        flex_receptor_path=Path("pose_1_flex.pdbqt"),
        ligand_path=Path("pose_1.pdbqt"),
        output_path=Path("local.pdbqt"),
        box=_BOX,
        scoring=VinaScoringFunction.VINARDO,
    )
    assert "--local_only" in local_args
    assert "--exhaustiveness" not in local_args
    assert "--flex" in local_args
    assert "--scoring" in local_args


def test_parse_vina_poses_splits_windows_nul_flex_output_and_enforces_flex_presence() -> None:
    parsed = parse_vina_poses(
        _SYNTHETIC_WINDOWS_VINA_FLEX_OUT.encode("utf-8"), expect_flex_sidechains=True
    )
    assert len(parsed) == 1
    pose = parsed[0]
    assert pose.affinity_kcal_mol == pytest.approx(-3.512)
    assert pose.stripped_nul_line_count == 1
    assert b"\x00" not in pose.content
    assert b"BEGIN_RES" not in pose.content
    assert pose.flex_sidechains_content is not None
    assert b"\x00" not in pose.flex_sidechains_content
    assert b"BEGIN_RES MET A 5" in pose.flex_sidechains_content
    assert pose.flex_residue_markers == ("MET A 5",)

    rigid_only = (
        "MODEL 1\nREMARK VINA RESULT: -4.000 0.000 0.000\n"
        + _SYNTHETIC_LIGAND_PDBQT
        + "ENDMDL\n"
    ).encode("utf-8")
    with pytest.raises(AnkoraDomainError) as exc_info:
        parse_vina_poses(rigid_only, expect_flex_sidechains=True)
    assert exc_info.value.code == "VINA_OUTPUT_INVALID"


def test_parse_vina_local_only_uses_authoritative_stdout_over_stale_remarks() -> None:
    parsed = parse_vina_local_only_output(
        stdout=_SYNTHETIC_LOCAL_ONLY_STDOUT,
        output_pdbqt=_SYNTHETIC_LOCAL_ONLY_FLAT_PDBQT.encode("utf-8"),
        expect_flex_sidechains=True,
    )
    # Must read -3.567 from stdout, NOT stale -3.512 from REMARK VINA RESULT!
    assert parsed.energy.estimated_free_energy_kcal_mol == pytest.approx(-3.567)
    assert parsed.energy.intermolecular_kcal_mol == pytest.approx(-4.285)
    assert parsed.energy.total_internal_kcal_mol == pytest.approx(-1.710)
    assert parsed.energy.torsional_free_energy_kcal_mol == pytest.approx(0.834)
    assert parsed.energy.unbound_system_energy_kcal_mol == pytest.approx(-1.595)
    assert parsed.stripped_nul_line_count == 1
    assert parsed.flex_sidechains_content is not None
    assert b"\x00" not in parsed.ligand_content
    assert b"\x00" not in parsed.flex_sidechains_content


class _StubProlifAdapter:
    """Deterministic stub capturing the exact coupled receptor PDB passed to ProLIF."""

    def __init__(self) -> None:
        self.seen_receptor_pdb_text: str | None = None

    def version(self) -> str:
        return "2.2.1"

    def analyze(
        self,
        *,
        pose_path: Path,
        conformer_path: Path,
        receptor_path: Path,
        profile: object,
    ) -> tuple[list[object], LigandDiagram]:
        _ = (pose_path, conformer_path, profile)
        self.seen_receptor_pdb_text = receptor_path.read_text(encoding="utf-8")
        return (
            [],
            LigandDiagram(
                atoms=[LigandDiagramAtom(atom_index=0, element="C", label="C1", x=0.0, y=0.0)],
                bonds=[],
            ),
        )


def _seed_flex_project(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    """Create minimal durable synthetic flex receptor, binding site, and ligand records."""
    now = datetime.now(UTC)
    receptor_store = ReceptorArtifactStore(tmp_path)
    site_store = BindingSiteArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)

    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    prot_bytes = _SYNTHETIC_CRYSTAL_PDB.encode("utf-8")
    rigid_bytes = _SYNTHETIC_RIGID_PDBQT.encode("utf-8")
    flex_bytes = _SYNTHETIC_FLEX_INITIAL_PDBQT.encode("utf-8")

    prot_art_id = "rec-prot-pdb"
    rigid_art_id = "rec-rigid-pdbqt"
    flex_art_id = "rec-flex-pdbqt"

    receptor_store.write_bytes(receptor_id, "protonated.pdb", prot_bytes)
    receptor_store.write_bytes(receptor_id, "receptor_rigid.pdbqt", rigid_bytes)
    receptor_store.write_bytes(receptor_id, "receptor_flex.pdbqt", flex_bytes)

    flex_res = ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5)
    flex_spec = ReceptorFlexSpec(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        flex_residues=(flex_res,),
        receptor_rigid_sha256=sha256(rigid_bytes).hexdigest(),
        receptor_flex_sha256=sha256(flex_bytes).hexdigest(),
        added_chi_torsion_count=3,
    )
    receptor_record = ReceptorPreparationRecord(
        receptor_id=receptor_id,
        source_artifact_id="src-synthetic-met",
        created_at=now,
        status=ReceptorPreparationStatus.DOCKING_READY,
        decisions=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
            protonation=ProtonationSettings(enabled=True),
            generate_pdbqt=True,
            flexibility=ReceptorFlexRequest(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=[flex_res],
            ),
        ),
        outputs=[
            ReceptorOutputArtifact(
                artifact_id=prot_art_id,
                stage=ReceptorOutputStage.PROTONATED_PDB,
                filename="protonated.pdb",
                format="pdb",
                sha256=sha256(prot_bytes).hexdigest(),
                size_bytes=len(prot_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{prot_art_id}/content",
            ),
            ReceptorOutputArtifact(
                artifact_id=rigid_art_id,
                stage=ReceptorOutputStage.PDBQT_RIGID,
                filename="receptor_rigid.pdbqt",
                format="pdbqt",
                sha256=sha256(rigid_bytes).hexdigest(),
                size_bytes=len(rigid_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{rigid_art_id}/content",
            ),
            ReceptorOutputArtifact(
                artifact_id=flex_art_id,
                stage=ReceptorOutputStage.PDBQT_FLEX,
                filename="receptor_flex.pdbqt",
                format="pdbqt",
                sha256=sha256(flex_bytes).hexdigest(),
                size_bytes=len(flex_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{flex_art_id}/content",
            ),
        ],
        warnings=[],
        provenance=[],
        display_output_artifact_id=prot_art_id,
        flex_spec=flex_spec,
        flex_atom_types=["C", "SA"],
    )
    receptor_store.save_record(receptor_record)

    site_id = site_store.new_binding_site_id()
    site_record = BindingSiteRecord(
        binding_site_id=site_id,
        receptor_id=receptor_id,
        source_artifact_id="src-synthetic-met",
        created_at=now,
        box=_BOX,
        decisions=BindingSiteRequest(
            source=BindingSiteSource.MANUAL,
            manual_box=_BOX,
        ),
        warnings=[],
        provenance=[
            ProvenanceEvent(
                event_id="evt-site",
                event_type="binding_site_confirmed",
                timestamp=now,
                input_artifacts=[receptor_id],
                output_artifacts=[site_id],
                tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
            )
        ],
    )
    site_store.save_record(site_record)

    ligand_id = ligand_store.new_ligand_id()
    sdf_bytes = b"SYNTHETIC_CO\n  Ankora\n\n  2  1  0  0  0  0            999 V2000\nEND\n$$$$\n"
    inspection = LigandInspection(
        name="SYNTHETIC_M1C_LIG",
        formula="CO",
        formal_charge=0,
        atom_count=2,
        heavy_atom_count=2,
        rotatable_bond_count=0,
        aromatic_ring_count=0,
        stereocenter_count=0,
        conformer_count=1,
        has_3d_coordinates=True,
        canonical_smiles="CO",
    )
    lig_record = LigandRecord(
        artifact=LigandArtifact(
            ligand_id=ligand_id,
            source=LigandSource.LOCAL,
            filename="synthetic.sdf",
            format=LigandFormat.SDF,
            sha256=sha256(sdf_bytes).hexdigest(),
            size_bytes=len(sdf_bytes),
            created_at=now,
        ),
        inspection=inspection,
        warnings=[],
        provenance=ProvenanceEvent(
            event_id="evt-lig",
            event_type="ligand_imported",
            timestamp=now,
            input_artifacts=[],
            output_artifacts=[ligand_id],
            tool=ToolIdentity(name="RDKit", version="2025.9.6"),
        ),
        content_url=f"/ligands/{ligand_id}/content",
    )
    ligand_store.create(ligand_id, sdf_bytes, lig_record)

    conf_id = ligand_store.new_conformer_id()
    conf_record = LigandConformerRecord(
        artifact=LigandConformerArtifact(
            conformer_id=conf_id,
            ligand_id=ligand_id,
            stage="minimized",
            filename="conformer.sdf",
            format="sdf",
            sha256=sha256(sdf_bytes).hexdigest(),
            size_bytes=len(sdf_bytes),
            created_at=now,
        ),
        inspection=inspection,
        minimization=LigandMinimizationResult(
            force_field=LigandForceField.MMFF94S,
            max_iterations=500,
            converged=True,
            initial_energy_kcal_mol=1.0,
            final_energy_kcal_mol=0.5,
        ),
        warnings=[],
        provenance=ProvenanceEvent(
            event_id="evt-conf",
            event_type="ligand_minimized",
            timestamp=now,
            input_artifacts=[ligand_id],
            output_artifacts=[conf_id],
            tool=ToolIdentity(name="RDKit", version="2025.9.6"),
        ),
        content_url=f"/ligands/{ligand_id}/conformers/{conf_id}/content",
    )
    ligand_store.create_conformer(ligand_id, conf_id, sdf_bytes, conf_record)

    prep_id = ligand_store.new_preparation_id()
    lig_pdbqt_bytes = _SYNTHETIC_LIGAND_PDBQT.encode("utf-8")
    prep_record = LigandPdbqtRecord(
        artifact=LigandPdbqtArtifact(
            preparation_id=prep_id,
            ligand_id=ligand_id,
            conformer_id=conf_id,
            filename="synthetic.pdbqt",
            format="pdbqt",
            sha256=sha256(lig_pdbqt_bytes).hexdigest(),
            size_bytes=len(lig_pdbqt_bytes),
            created_at=now,
        ),
        charge_model=LigandChargeModel.GASTEIGER,
        tool=ToolIdentity(name="Meeko ligand preparation", version="0.7.1"),
        command=["mk_prepare_ligand"],
        stdout="",
        stderr="",
        provenance=ProvenanceEvent(
            event_id="evt-prep",
            event_type="ligand_pdbqt_prepared",
            timestamp=now,
            input_artifacts=[conf_id],
            output_artifacts=[prep_id],
            tool=ToolIdentity(name="Meeko ligand preparation", version="0.7.1"),
        ),
        content_url=f"/ligands/{ligand_id}/preparations/{prep_id}/content",
        effective_torsdof=0,
        atom_types=["C", "OA"],
    )
    ligand_store.create_pdbqt(ligand_id, prep_id, lig_pdbqt_bytes, prep_record)
    return tmp_path, receptor_id, site_id, ligand_id, prep_id


def test_vina_flex_docking_local_refinement_and_coupled_pose_interactions_e8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, receptor_id, site_id, ligand_id, prep_id = _seed_flex_project(tmp_path)
    docking_store = DockingArtifactStore(root)
    receptor_store = ReceptorArtifactStore(root)
    site_store = BindingSiteArtifactStore(root)
    ligand_store = LigandArtifactStore(root)

    monkeypatch.setattr(
        "ankora_backend.services.vina_docking.probe_vina",
        lambda: VinaInstallation(executable="synthetic-vina", version="1.2.7"),
    )

    def _fake_execute_vina(
        *,
        installation: VinaInstallation,
        receptor_path: Path,
        ligand_path: Path,
        output_path: Path,
        box: BindingBox,
        parameters: VinaDockingParameters,
        cancel_event: object,
        flex_receptor_path: Path | None = None,
    ) -> CancellableToolExecution:
        _ = (box, parameters, cancel_event)
        assert flex_receptor_path is not None
        assert receptor_path.name == "receptor_rigid.pdbqt"
        assert flex_receptor_path.name == "receptor_flex.pdbqt"
        output_path.write_bytes(_SYNTHETIC_WINDOWS_VINA_FLEX_OUT.encode("utf-8"))
        return CancellableToolExecution(
            command=[
                installation.executable,
                "--receptor",
                str(receptor_path),
                "--flex",
                str(flex_receptor_path),
                "--ligand",
                str(ligand_path),
            ],
            exit_code=0,
            stdout="AutoDock Vina v1.2.7\n   1   -3.512   0.000   0.000\n",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    def _fake_execute_local_only(
        *,
        installation: VinaInstallation,
        receptor_path: Path,
        ligand_path: Path,
        output_path: Path,
        box: BindingBox,
        cpu_threads: int,
        seed: int,
        scoring: VinaScoringFunction,
        timeout_minutes: int,
        cancel_event: object,
        flex_receptor_path: Path | None = None,
    ) -> CancellableToolExecution:
        _ = (box, cpu_threads, seed, scoring, timeout_minutes, cancel_event)
        assert flex_receptor_path is not None
        assert flex_receptor_path.name == "pose_1_flex.pdbqt"
        output_path.write_bytes(_SYNTHETIC_LOCAL_ONLY_FLAT_PDBQT.encode("utf-8"))
        return CancellableToolExecution(
            command=[
                installation.executable,
                "--receptor",
                str(receptor_path),
                "--flex",
                str(flex_receptor_path),
                "--ligand",
                str(ligand_path),
                "--local_only",
            ],
            exit_code=0,
            stdout=_SYNTHETIC_LOCAL_ONLY_STDOUT,
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr("ankora_backend.services.vina_docking.execute_vina", _fake_execute_vina)
    monkeypatch.setattr(
        "ankora_backend.services.vina_docking.execute_vina_local_only",
        _fake_execute_local_only,
    )

    service = VinaDockingService(
        docking_store=docking_store,
        receptor_store=receptor_store,
        binding_site_store=site_store,
        ligand_store=ligand_store,
    )
    try:
        started = service.start(
            VinaDockingRequest(
                receptor_id=receptor_id,
                binding_site_id=site_id,
                ligand_id=ligand_id,
                ligand_preparation_id=prep_id,
                parameters=VinaDockingParameters(scoring=VinaScoringFunction.VINARDO),
                acknowledge_inputs_and_scoring=True,
            )
        )
        deadline = time.monotonic() + 10.0
        job = service.get(started.job_id)
        while job.status not in {DockingJobStatus.COMPLETED, DockingJobStatus.FAILED}:
            assert time.monotonic() < deadline
            time.sleep(0.02)
            job = service.get(started.job_id)

        assert job.status is DockingJobStatus.COMPLETED
        assert job.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert len(job.flex_residues) == 1
        assert len(job.poses) == 1
        pose_art = job.poses[0].artifact
        assert pose_art.flex_filename == "pose_1_flex.pdbqt"
        assert pose_art.pose_flex_sidechains_sha256 is not None
        assert pose_art.pose_complex_identity_sha256 is not None

        # Raw vina_poses.pdbqt stays immutable on disk (retaining original Windows NUL bytes),
        # while derived pose_1.pdbqt & pose_1_flex.pdbqt are sanitized.
        raw_vina = docking_store.output_path(job.job_id, "vina_poses.pdbqt").read_bytes()
        assert b"\x00" in raw_vina
        pose_bytes = docking_store.pose_content_path(job.job_id, pose_art.artifact_id).read_bytes()
        assert b"\x00" not in pose_bytes
        flex_path = docking_store.pose_flex_content_path(job.job_id, pose_art.artifact_id)
        assert flex_path is not None
        assert b"\x00" not in flex_path.read_bytes()

        # Explicit derivative --local_only refinement never mutates parent job or pose.
        parent_record_before = docking_store.output_path(job.job_id, "record.json").read_bytes()
        refinement = service.refine_pose_local_only(
            VinaLocalRefinementRequest(
                parent_job_id=job.job_id,
                parent_pose_artifact_id=pose_art.artifact_id,
                scoring=VinaScoringFunction.VINARDO,
            )
        )
        assert refinement.estimated_free_energy_kcal_mol == pytest.approx(-3.567)
        assert refinement.parent_pose_sha256 == pose_art.sha256
        assert refinement.parent_pose_flex_sha256 == pose_art.pose_flex_sidechains_sha256
        assert refinement.refined_pose.pose_flex_sidechains_sha256 is not None
        assert refinement.refined_pose.pose_complex_identity_sha256 is not None
        parent_record_after = docking_store.output_path(job.job_id, "record.json").read_bytes()
        assert parent_record_after == parent_record_before

        # E8 PoseInteractionService: complex_pdb() and analyze() (ProLIF) use moved side chains.
        stub_prolif = _StubProlifAdapter()
        pose_service = PoseInteractionService(
            docking_store=docking_store,
            autodock4_store=AutoDock4JobStore(root),
            autodock_gpu_store=AutoDockGpuJobStore(root),
            autogrid_store=AutoGridMapStore(root),
            receptor_store=receptor_store,
            ligand_store=ligand_store,
            interaction_store=PoseInteractionStore(root),
            adapter=stub_prolif,  # type: ignore[arg-type]
        )
        catalog_id = f"vina_job:{job.job_id}"
        complex_pdb, _ = pose_service.complex_pdb(catalog_id, ligand_id, pose_art.artifact_id)
        assert f"REMARK   1 FLEX SIDECHAIN  {pose_art.pose_flex_sidechains_sha256}" in complex_pdb
        assert f"REMARK   1 POSE COMPLEX ID {pose_art.pose_complex_identity_sha256}" in complex_pdb
        # Verify MET CE is at the MOVED coordinate (-3.190), NOT crystal (+3.190)!
        assert "   4.200  -3.190  -0.250" in complex_pdb
        assert "   4.200   3.190   0.250" not in complex_pdb

        analysis = pose_service.analyze(
            catalog_id, ligand_id, pose_art.artifact_id, InteractionAnalysisRequest()
        )
        assert analysis.pose_flex_sidechains_sha256 == pose_art.pose_flex_sidechains_sha256
        assert analysis.pose_complex_identity_sha256 == pose_art.pose_complex_identity_sha256
        assert analysis.materialized_coupled_receptor_sha256 is not None
        assert stub_prolif.seen_receptor_pdb_text is not None
        assert "   4.200  -3.190  -0.250" in stub_prolif.seen_receptor_pdb_text
        assert "   4.200   3.190   0.250" not in stub_prolif.seen_receptor_pdb_text
    finally:
        service.shutdown()


def test_v01_vina_and_interaction_records_deserialize_without_flex_fields() -> None:
    now = datetime.now(UTC).isoformat()
    legacy_job = {
        "job_id": "job-1",
        "engine": "autodock_vina",
        "status": "completed",
        "phase": "complete",
        "created_at": now,
        "request": {
            "receptor_id": "rec-1",
            "binding_site_id": "site-1",
            "ligand_id": "lig-1",
            "ligand_preparation_id": "prep-1",
            "parameters": {"cpu_threads": 1},
            "acknowledge_inputs_and_scoring": True,
        },
        "tool": {"name": "AutoDock Vina", "version": "1.2.7"},
        "receptor_output_artifact_id": "art-1",
        "receptor_sha256": "a" * 64,
        "ligand_sha256": "b" * 64,
        "poses": [
            {
                "mode": 1,
                "affinity_kcal_mol": -5.1,
                "rmsd_lower_bound_angstrom": 0.0,
                "rmsd_upper_bound_angstrom": 0.0,
                "artifact": {
                    "artifact_id": "job-1-pose-1",
                    "mode": 1,
                    "filename": "pose_1.pdbqt",
                    "format": "pdbqt",
                    "sha256": "c" * 64,
                    "size_bytes": 100,
                    "content_url": "/docking/jobs/job-1/poses/job-1-pose-1/content",
                },
            }
        ],
    }
    parsed_job = VinaDockingJobRecord.model_validate(legacy_job)
    assert parsed_job.receptor_flex_mode is ReceptorFlexMode.RIGID
    assert parsed_job.poses[0].artifact.pose_flex_sidechains_sha256 is None

    legacy_interaction = {
        "analysis_id": "ana-1",
        "created_at": now,
        "catalog_id": "vina_job:job-1",
        "engine_key": "vina_job",
        "record_id": "job-1",
        "engine_label": "AutoDock Vina 1.2.7",
        "ligand_id": "lig-1",
        "ligand_preparation_id": "prep-1",
        "conformer_id": "conf-1",
        "conformer_sha256": "d" * 64,
        "pose": {
            "artifact_id": "job-1-pose-1",
            "kind": "vina_mode",
            "ordinal": 1,
            "label": "Mode 1",
            "result_kcal_mol": -5.1,
            "value_label": "Vina score",
            "sha256": "c" * 64,
            "content_url": "/docking/jobs/job-1/poses/job-1-pose-1/content",
        },
        "receptor_id": "rec-1",
        "docking_receptor_artifact_id": "art-1",
        "docking_receptor_sha256": "a" * 64,
        "analysis_receptor_artifact_id": "art-pdb",
        "analysis_receptor_sha256": "e" * 64,
        "analysis_receptor_content_url": "/receptors/rec-1/outputs/art-pdb/content",
        "detector": {"name": "ProLIF", "version": "2.2.1"},
        "profile": {},
        "contacts": [],
        "ligand_diagram": {
            "atoms": [{"atom_index": 0, "element": "C", "label": "C1", "x": 0.0, "y": 0.0}],
            "bonds": [],
        },
        "provenance": {
            "event_id": "evt-1",
            "event_type": "pose_interactions_analyzed",
            "timestamp": now,
            "input_artifacts": [],
            "output_artifacts": ["ana-1"],
            "tool": {"name": "ProLIF", "version": "2.2.1"},
        },
    }
    parsed_analysis = InteractionAnalysisRecord.model_validate(legacy_interaction)
    assert parsed_analysis.pose_flex_sidechains_sha256 is None
    assert parsed_analysis.materialized_coupled_receptor_sha256 is None
