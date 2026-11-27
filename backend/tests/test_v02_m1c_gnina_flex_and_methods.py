"""Tests for GNINA FlexRes, local refinement, HTTP flex/refinement routes, Methods, and Export.

All non-live fixtures in this module are synthetic and explicitly labelled synthetic.
The live GNINA 1.3.3 CPU test executes the real installed Meeko 0.7.1 and GNINA 1.3.3
binaries on Linux when available on the host.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.adapters.chemistry.flex_pose_complex import materialize_coupled_receptor_pdb
from ankora_backend.adapters.engines.gnina import (
    GninaInstallation,
    GninaPdbqtPose,
    build_gnina_arguments,
    build_gnina_local_only_arguments,
    pair_gnina_flex_models,
    probe_gnina,
)
from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchParameters,
    AutoDock4BatchRecord,
    AutoDock4BatchRequest,
    AutoDock4DockingJobRecord,
    AutoDock4DockingParameters,
    AutoDock4DockingRequest,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
    AutoDock4PoseArtifact,
    AutoDock4RunResult,
    AutoDock4ToolIdentity,
)
from ankora_backend.schemas.autodock_gpu import (
    AutoDockBackend,
    AutoDockGpuBatchLigandResult,
    AutoDockGpuBatchParameters,
    AutoDockGpuBatchRecord,
    AutoDockGpuBatchRequest,
    AutoDockGpuDockingJobRecord,
    AutoDockGpuDockingParameters,
    AutoDockGpuDockingRequest,
    AutoDockGpuToolIdentity,
    AutoDockJobPhase,
    AutoDockJobStatus,
)
from ankora_backend.schemas.autogrid import (
    AutoGridExecutionEvidence,
    AutoGridGeometry,
    AutoGridLigandSource,
    AutoGridMapArtifact,
    AutoGridMapKind,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
    AutoGridPreflight,
    AutoGridToolIdentity,
)
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.docking import (
    DockingExecutionEvidence,
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaBatchDockingParameters,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchLigandResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
    VinaLocalRefinementRecord,
    VinaScoringFunction,
)
from ankora_backend.schemas.gnina import (
    GninaCnnModelIdentity,
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaLocalRefinementRecord,
    GninaLocalRefinementRequest,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandChargeModel,
    LigandPdbqtArtifact,
    LigandPdbqtRecord,
    LigandSmartsRigidificationOutcome,
    PrepareLigandPdbqtRequest,
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
from ankora_backend.schemas.structures import StructureSource
from ankora_backend.schemas.v02_contracts import (
    LigandFlexibilitySpec,
    MacrocyclePolicy,
    PoseComplexIdentity,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services import gnina_docking as gnina_module
from ankora_backend.services import receptor_preparation
from ankora_backend.services.campaign_export import (
    _HEADER_GNINA_POSES,
    CampaignExportService,
)
from ankora_backend.services.gnina_docking import GninaDockingService
from ankora_backend.services.ligand_import import import_local_ligand
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from ankora_backend.services.methods_report import MethodsReportService
from ankora_backend.services.pose_interactions import PoseInteractionService
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.result_catalog import ResultCatalogService
from ankora_backend.services.structure_inspection import import_structure_bytes
from ankora_backend.services.work_leases import WorkLeaseManager

_SYNTHETIC_BOX = BindingBox(
    center_x=0.0,
    center_y=0.0,
    center_z=0.0,
    size_x=16.0,
    size_y=16.0,
    size_z=16.0,
)

# Synthetic full-atom crystal PDB with MET A:5 backbone + side chain + non-polar Hs.
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
    "ATOM      1  N   MET A   5      -0.500  -1.350   0.250  1.00  0.00    -0.300 N \n"
    "ATOM      2  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.100 C \n"
    "ATOM      3  C   MET A   5      -0.550   0.500  -1.320  1.00  0.00     0.400 C \n"
    "ATOM      4  O   MET A   5      -0.100   1.550  -1.780  1.00  0.00    -0.400 OA\n"
    "ATOM      5  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "TER\n"
)

_SYNTHETIC_MEEKO_FLEX_TEMPLATE = (
    "BEGIN_RES MET A   5\n"
    "ROOT\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00     0.100 C \n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00     0.000 C \n"
    "ENDROOT\n"
    "BRANCH   2   3\n"
    "ATOM      3  CG  MET A   5       2.040   1.440   0.000  1.00  0.00     0.020 C \n"
    "BRANCH   3   4\n"
    "ATOM      4  SD  MET A   5       3.850   1.440   0.000  1.00  0.00    -0.120 SA\n"
    "BRANCH   4   5\n"
    "ATOM      5  CE  MET A   5       4.200   3.190   0.250  1.00  0.00     0.100 C \n"
    "ENDBRANCH   4   5\n"
    "ENDBRANCH   3   4\n"
    "ENDBRANCH   2   3\n"
    "TORSDOF 3\n"
    "END_RES MET A   5\n"
)

_SYNTHETIC_MOVED_FLEX_PDB_MULTI_SHIFTED = (
    "MODEL 3\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  CG  MET A   5       2.140   1.340   0.450  1.00  0.00           C  \n"
    "ATOM      4  SD  MET A   5       3.950   1.340   0.450  1.00  0.00           S  \n"
    "ATOM      5  CE  MET A   5       4.300   3.090   0.700  1.00  0.00           C  \n"
    "ENDMDL\n"
    "MODEL 4\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  CG  MET A   5       1.940   1.540  -0.350  1.00  0.00           C  \n"
    "ATOM      4  SD  MET A   5       3.750   1.540  -0.350  1.00  0.00           S  \n"
    "ATOM      5  CE  MET A   5       4.100   3.290  -0.100  1.00  0.00           C  \n"
    "ENDMDL\n"
)

_SYNTHETIC_MOVED_FLEX_PDB_SINGLE = (
    "MODEL 1\n"
    "ATOM      1  CA  MET A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      2  CB  MET A   5       1.530   0.000   0.000  1.00  0.00           C  \n"
    "ATOM      3  CG  MET A   5       2.240   1.240   0.650  1.00  0.00           C  \n"
    "ATOM      4  SD  MET A   5       4.050   1.240   0.650  1.00  0.00           S  \n"
    "ATOM      5  CE  MET A   5       4.400   2.990   0.900  1.00  0.00           C  \n"
    "ENDMDL\n"
)

_SYNTHETIC_LIGAND_PDBQT = (
    "ROOT\n"
    "ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
    "ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00    -0.300 OA\n"
    "ENDROOT\n"
    "TORSDOF 0\n"
)

_SYNTHETIC_GNINA_RAW_POSES = (
    "MODEL 1\n"
    "REMARK minimizedAffinity -6.4200\n"
    "REMARK CNNscore 0.8400\n"
    "REMARK CNNaffinity 6.1000\n"
    + _SYNTHETIC_LIGAND_PDBQT
    + "ENDMDL\n"
    "MODEL 2\n"
    "REMARK minimizedAffinity -5.9100\n"
    "REMARK CNNscore 0.6200\n"
    "REMARK CNNaffinity 5.4000\n"
    + _SYNTHETIC_LIGAND_PDBQT
    + "ENDMDL\n"
)

_SYNTHETIC_GNINA_LOCAL_POSE = (
    "REMARK minimizedAffinity -6.7800\n"
    "REMARK CNNscore 0.8800\n"
    "REMARK CNNaffinity 6.3500\n"
    + _SYNTHETIC_LIGAND_PDBQT
)

_SYNTHETIC_CONFORMER_SDF = (
    "SYNTHETIC_CO\n"
    "     RDKit          3D\n"
    "\n"
    "  2  1  0  0  0  0  0  0  0  0999 V2000\n"
    "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
    "    1.2000    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n"
    "  1  2  2  0\n"
    "M  END\n"
    "$$$$\n"
)


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _wait_for_gnina_job(service: GninaDockingService, job_id: str, timeout: float = 120.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = service.get(job_id)
        if record.status in {
            DockingJobStatus.COMPLETED,
            DockingJobStatus.FAILED,
            DockingJobStatus.CANCELED,
        }:
            return record
        time.sleep(0.05)
    raise AssertionError(f"GNINA job {job_id} did not finish within {timeout}s")


def _seed_synthetic_flex_project(root: Path) -> dict[str, Any]:
    """Create a synthetic sidechain_flex receptor, binding site, and semi-flex ligand."""
    now = datetime.now(UTC)
    structures = StructureArtifactStore(root)
    receptors = ReceptorArtifactStore(root)
    sites = BindingSiteArtifactStore(root)
    ligands = LigandArtifactStore(root)

    structure = import_structure_bytes(
        content=_SYNTHETIC_CRYSTAL_PDB.encode("utf-8"),
        filename="synthetic_met5.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structures,
    )

    receptor_id = receptors.new_receptor_id()
    receptors.create_receptor(receptor_id)
    prot_bytes = _SYNTHETIC_CRYSTAL_PDB.encode("utf-8")
    rigid_bytes = _SYNTHETIC_RIGID_PDBQT.encode("utf-8")
    flex_bytes = _SYNTHETIC_MEEKO_FLEX_TEMPLATE.encode("utf-8")

    prot_id = "art-prot-pdb"
    rigid_id = "art-rigid-pdbqt"
    flex_id = "art-flex-pdbqt"
    receptors.write_bytes(receptor_id, "protonated.pdb", prot_bytes)
    receptors.write_bytes(receptor_id, "receptor_rigid.pdbqt", rigid_bytes)
    receptors.write_bytes(receptor_id, "receptor_flex.pdbqt", flex_bytes)

    flex_locator = ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5)
    flex_spec = ReceptorFlexSpec(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        flex_residues=(flex_locator,),
        receptor_rigid_sha256=_sha256_bytes(rigid_bytes),
        receptor_flex_sha256=_sha256_bytes(flex_bytes),
        added_chi_torsion_count=3,
    )
    dof_warning = StructuredWarning(
        code=WarningCode.DOCKING_FLEXRES_DOF_HIGH,
        stage="receptor_preparation",
        message="Synthetic high-DOF FlexRes test warning.",
        details={"flex_residue_count": 1, "added_chi_torsion_count": 3},
    )
    receptor = ReceptorPreparationRecord(
        receptor_id=receptor_id,
        source_artifact_id=structure.artifact.artifact_id,
        created_at=now,
        status=ReceptorPreparationStatus.DOCKING_READY,
        display_output_artifact_id=prot_id,
        decisions=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
            protonation=ProtonationSettings(enabled=True, force_field="PARSE"),
            generate_pdbqt=True,
            flexibility=ReceptorFlexRequest(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=[flex_locator],
            ),
        ),
        flex_spec=flex_spec,
        flex_atom_types=["C", "SA"],
        outputs=[
            ReceptorOutputArtifact(
                artifact_id=prot_id,
                stage=ReceptorOutputStage.PROTONATED_PDB,
                filename="protonated.pdb",
                format="pdb",
                sha256=_sha256_bytes(prot_bytes),
                size_bytes=len(prot_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{prot_id}/content",
            ),
            ReceptorOutputArtifact(
                artifact_id=rigid_id,
                stage=ReceptorOutputStage.PDBQT_RIGID,
                filename="receptor_rigid.pdbqt",
                format="pdbqt",
                sha256=_sha256_bytes(rigid_bytes),
                size_bytes=len(rigid_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{rigid_id}/content",
            ),
            ReceptorOutputArtifact(
                artifact_id=flex_id,
                stage=ReceptorOutputStage.PDBQT_FLEX,
                filename="receptor_flex.pdbqt",
                format="pdbqt",
                sha256=_sha256_bytes(flex_bytes),
                size_bytes=len(flex_bytes),
                created_at=now,
                content_url=f"/receptors/{receptor_id}/outputs/{flex_id}/content",
            ),
        ],
        warnings=[dof_warning],
        provenance=[
            ProvenanceEvent(
                event_id="evt-prot",
                event_type="receptor_protonated",
                timestamp=now,
                input_artifacts=[structure.artifact.artifact_id],
                output_artifacts=[prot_id],
                tool=ToolIdentity(name="PDB2PQR/PROPKA", version="3.7.1"),
                parameters={"ph": 7.4, "force_field": "PARSE"},
            ),
            ProvenanceEvent(
                event_id="evt-flex-pdbqt",
                event_type="receptor_flex_pdbqt_generated",
                timestamp=now,
                input_artifacts=[prot_id],
                output_artifacts=[rigid_id, flex_id],
                tool=ToolIdentity(name="Meeko", version="0.7.1"),
                parameters={"mode": "sidechain_flex"},
            ),
        ],
    )
    receptors.save_record(receptor)

    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=receptor_id,
            source_artifact_id=structure.artifact.artifact_id,
            created_at=now,
            box=_SYNTHETIC_BOX,
            decisions=BindingSiteRequest(
                source=BindingSiteSource.MANUAL,
                manual_box=_SYNTHETIC_BOX,
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
    )

    lig_record = import_local_ligand(
        content=b"C=O SYNTHETIC_CO\n",
        filename="synthetic_co.smi",
        store=ligands,
    )
    ligand_id = lig_record.artifact.ligand_id
    assert lig_record.state is not None
    conformer_record = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            state_id=lig_record.state.state_id,
        ),
        store=ligands,
    )
    conformer_id = conformer_record.artifact.conformer_id
    conformer_sha = conformer_record.artifact.sha256

    prep_id = ligands.new_preparation_id()
    ligand_pdbqt_bytes = _SYNTHETIC_LIGAND_PDBQT.encode("utf-8")
    flex_ligand_spec = LigandFlexibilitySpec(
        macrocycle_policy=MacrocyclePolicy.RIGID_INPUT_CONFORMATION,
        rigidified_smarts=("[CX3](=O)[NX3]",),
        rigidified_bond_indices=((1, 2),),
        flexible_amides=True,
    )
    pdbqt_record = LigandPdbqtRecord(
        artifact=LigandPdbqtArtifact(
            preparation_id=prep_id,
            ligand_id=ligand_id,
            conformer_id=conformer_id,
            filename="ligand.pdbqt",
            format="pdbqt",
            sha256=_sha256_bytes(ligand_pdbqt_bytes),
            size_bytes=len(ligand_pdbqt_bytes),
            created_at=now,
        ),
        charge_model=LigandChargeModel.GASTEIGER,
        tool=ToolIdentity(name="Meeko", version="0.7.1"),
        command=["mk_prepare_ligand"],
        stdout="",
        stderr="",
        provenance=ProvenanceEvent(
            event_id="evt-lig-pdbqt",
            event_type="ligand_pdbqt_prepared",
            timestamp=now,
            input_artifacts=[conformer_id],
            output_artifacts=[prep_id],
            tool=ToolIdentity(name="Meeko", version="0.7.1"),
        ),
        content_url=f"/ligands/{ligand_id}/preparations/{prep_id}/content",
        flexibility=flex_ligand_spec,
        effective_torsdof=2,
        atom_types=["C", "OA"],
        warnings=[
            StructuredWarning(
                code=WarningCode.LIG_RIGIDIFY_SMARTS_NO_MATCH,
                stage="ligand_preparation",
                message="SMARTS matched zero bonds.",
            )
        ],
        smarts_rigidification_outcomes=[
            LigandSmartsRigidificationOutcome(
                smarts="[CX3](=O)[NX3]",
                bond_indices=(1, 2),
                match_count=0,
                matched_bonds_zero_based=[],
                applied=False,
            )
        ],
    )
    ligands.create_pdbqt(ligand_id, prep_id, ligand_pdbqt_bytes, pdbqt_record)

    return {
        "receptor": receptor,
        "rigid_id": rigid_id,
        "flex_id": flex_id,
        "rigid_sha": _sha256_bytes(rigid_bytes),
        "flex_sha": _sha256_bytes(flex_bytes),
        "flex_locator": flex_locator,
        "site_id": site_id,
        "ligand_id": ligand_id,
        "conformer_id": conformer_id,
        "conformer_sha": conformer_sha,
        "prep_id": prep_id,
        "ligand_sha": _sha256_bytes(ligand_pdbqt_bytes),
    }


def test_build_gnina_arguments_and_local_only_enforce_pdb_out_flex(tmp_path: Path) -> None:
    receptor = tmp_path / "receptor.pdbqt"
    ligand = tmp_path / "ligand.pdbqt"
    out = tmp_path / "raw_poses.pdbqt"
    flex = tmp_path / "receptor_flex.pdbqt"
    out_flex_pdb = tmp_path / "raw_flex.pdb"
    out_flex_pdbqt = tmp_path / "raw_flex.pdbqt"

    params = GninaDockingParameters(compute="cpu", exhaustiveness=4, num_modes=3)
    rigid_args = build_gnina_arguments(
        receptor_path=receptor,
        ligand_path=ligand,
        output_path=out,
        box=_SYNTHETIC_BOX,
        parameters=params,
    )
    assert "--flex" not in rigid_args
    assert "--out_flex" not in rigid_args

    flex_args = build_gnina_arguments(
        receptor_path=receptor,
        ligand_path=ligand,
        output_path=out,
        box=_SYNTHETIC_BOX,
        parameters=params,
        flex_receptor_path=flex,
        out_flex_path=out_flex_pdb,
    )
    assert "--flex" in flex_args and str(flex) in flex_args
    assert "--out_flex" in flex_args and str(out_flex_pdb) in flex_args

    # ADR-032 Addendum A6: GNINA --out_flex MUST be .pdb (refuse .pdbqt).
    with pytest.raises(AnkoraDomainError) as exc_info:
        build_gnina_arguments(
            receptor_path=receptor,
            ligand_path=ligand,
            output_path=out,
            box=_SYNTHETIC_BOX,
            parameters=params,
            flex_receptor_path=flex,
            out_flex_path=out_flex_pdbqt,
        )
    assert exc_info.value.code == "GNINA_INPUT_INVALID"

    # Pairing only --flex without --out_flex must fail closed.
    with pytest.raises(AnkoraDomainError) as exc_pair:
        build_gnina_arguments(
            receptor_path=receptor,
            ligand_path=ligand,
            output_path=out,
            box=_SYNTHETIC_BOX,
            parameters=params,
            flex_receptor_path=flex,
            out_flex_path=None,
        )
    assert exc_pair.value.code == "GNINA_INPUT_INVALID"

    local_req = GninaLocalRefinementRequest(
        parent_job_id="00000000-0000-4000-8000-000000000001",
        parent_pose_artifact_id="pose-1",
        compute="cpu",
    )
    local_args = build_gnina_local_only_arguments(
        receptor_path=receptor,
        ligand_path=ligand,
        output_path=out,
        box=_SYNTHETIC_BOX,
        parameters=local_req,
        flex_receptor_path=flex,
        out_flex_path=out_flex_pdb,
    )
    assert "--local_only" in local_args
    assert "--flex" in local_args
    assert "--out_flex" in local_args

    with pytest.raises(AnkoraDomainError) as exc_local:
        build_gnina_local_only_arguments(
            receptor_path=receptor,
            ligand_path=ligand,
            output_path=out,
            box=_SYNTHETIC_BOX,
            parameters=local_req,
            flex_receptor_path=flex,
            out_flex_path=out_flex_pdbqt,
        )
    assert exc_local.value.code == "GNINA_INPUT_INVALID"


def test_pair_gnina_flex_models_uses_zero_based_ordinal_on_shifted_model_headers() -> None:
    poses = [
        GninaPdbqtPose(1, -6.4, 0.84, 6.1, b"MODEL 1\nENDMDL\n"),
        GninaPdbqtPose(2, -5.9, 0.62, 5.4, b"MODEL 2\nENDMDL\n"),
    ]
    paired = pair_gnina_flex_models(
        poses,
        gnina_flex_pdb_text=_SYNTHETIC_MOVED_FLEX_PDB_MULTI_SHIFTED,
        meeko_flex_template_pdbqt=_SYNTHETIC_MEEKO_FLEX_TEMPLATE,
    )
    assert len(paired) == 2
    first = paired[0].decode("utf-8")
    second = paired[1].decode("utf-8")
    assert "BEGIN_RES MET A   5" in first and "TORSDOF 3" in first and "SA" in first
    assert "2.140   1.340   0.450" in first
    assert "1.940   1.540  -0.350" in second

    with pytest.raises(AnkoraDomainError) as exc_count:
        pair_gnina_flex_models(
            poses[:1],
            gnina_flex_pdb_text=_SYNTHETIC_MOVED_FLEX_PDB_MULTI_SHIFTED,
            meeko_flex_template_pdbqt=_SYNTHETIC_MEEKO_FLEX_TEMPLATE,
        )
    assert exc_count.value.code == "GNINA_OUTPUT_INVALID"


def test_gnina_service_flex_single_refinement_methods_and_export_synthetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed_synthetic_flex_project(tmp_path)
    gnina_store = GninaJobStore(tmp_path)
    fake_exe = tmp_path / "fake-gnina"
    fake_exe.write_bytes(b"synthetic-gnina-binary")
    fake_sha = _sha256_bytes(b"synthetic-gnina-binary")
    fake_install = GninaInstallation(
        executable=str(fake_exe),
        version="1.3.3",
        sha256=fake_sha,
        architecture="x86_64",
    )

    monkeypatch.setattr(gnina_module, "_linux_host", lambda: True)
    monkeypatch.setattr(gnina_module, "probe_gnina", lambda: fake_install)
    monkeypatch.setattr(gnina_module, "require_matching_topology", lambda pose, conf: None)

    def _fake_execute_gnina(**kwargs: Any) -> CancellableToolExecution:
        out_path: Path = kwargs["output_path"]
        out_flex_path: Path = kwargs["out_flex_path"]
        assert kwargs["flex_receptor_path"] is not None
        assert out_flex_path.suffix == ".pdb"
        out_path.write_bytes(_SYNTHETIC_GNINA_RAW_POSES.encode("utf-8"))
        out_flex_path.write_bytes(_SYNTHETIC_MOVED_FLEX_PDB_MULTI_SHIFTED.encode("utf-8"))
        return CancellableToolExecution(
            command=[fake_install.executable, "--flex", str(kwargs["flex_receptor_path"])],
            exit_code=0,
            stdout="synthetic gnina stdout\n",
            stderr="",
            timed_out=False,
            canceled=False,
        )

    def _fake_execute_local(**kwargs: Any) -> CancellableToolExecution:
        out_path: Path = kwargs["output_path"]
        out_flex_path: Path = kwargs["out_flex_path"]
        assert kwargs["flex_receptor_path"] is not None
        assert out_flex_path.suffix == ".pdb"
        out_path.write_bytes(_SYNTHETIC_GNINA_LOCAL_POSE.encode("utf-8"))
        out_flex_path.write_bytes(_SYNTHETIC_MOVED_FLEX_PDB_SINGLE.encode("utf-8"))
        return CancellableToolExecution(
            command=[fake_install.executable, "--local_only"],
            exit_code=0,
            stdout="synthetic gnina local stdout\n",
            stderr="",
            timed_out=False,
            canceled=False,
        )

    monkeypatch.setattr(gnina_module, "execute_gnina", _fake_execute_gnina)
    monkeypatch.setattr(gnina_module, "execute_gnina_local_only", _fake_execute_local)

    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    service = GninaDockingService(
        store=gnina_store,
        receptors=ReceptorArtifactStore(tmp_path),
        sites=BindingSiteArtifactStore(tmp_path),
        ligands=LigandArtifactStore(tmp_path),
        leases=WorkLeaseManager(WorkLeaseStore(tmp_path)),
        resources=ResourceArbiter(
            cpu_threads=4,
            gpu_slots=1,
            memory_total_bytes=16 * 1024**3,
            memory_reserve_bytes=0,
            disk_path=tmp_path,
            disk_total_bytes=16 * 1024**3,
            disk_reserve_bytes=0,
            memory_available=lambda: 16 * 1024**3,
            disk_free=lambda: 16 * 1024**3,
        ),
    )
    try:
        started = service.start(
            GninaDockingRequest(
                receptor_id=seeded["receptor"].receptor_id,
                binding_site_id=seeded["site_id"],
                ligand_id=seeded["ligand_id"],
                ligand_preparation_id=seeded["prep_id"],
                parameters=GninaDockingParameters(compute="cpu", exhaustiveness=2, num_modes=2),
                acknowledge_inputs_and_scoring=True,
            )
        )
        completed = _wait_for_gnina_job(service, started.job_id)
        assert completed.status is DockingJobStatus.COMPLETED, completed.failure
        assert completed.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert completed.receptor_flex_sha256 == seeded["flex_sha"]
        assert len(completed.poses) == 2
        assert any(w.code == WarningCode.DOCKING_FLEXRES_DOF_HIGH for w in completed.warnings)

        pose1 = completed.poses[0].artifact
        assert pose1.flex_filename == "pose_1_flex.pdbqt"
        assert pose1.pose_flex_sidechains_sha256 is not None
        assert pose1.flex_content_url == (
            f"/docking/gnina/jobs/{completed.job_id}/poses/{pose1.artifact_id}/flex"
        )
        expected_complex_id = PoseComplexIdentity(
            mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_rigid_sha256=completed.receptor_sha256,
            pose_flex_sidechains_sha256=pose1.pose_flex_sidechains_sha256,
            ligand_pose_sha256=pose1.sha256,
        ).complex_identity_sha256
        assert pose1.pose_complex_identity_sha256 == expected_complex_id

        # Create-only --local_only derivative must keep parent record and bytes untouched.
        parent_before = gnina_store.output_path(completed.job_id, "record.json").read_bytes()
        refinement = service.refine_pose_local_only(
            GninaLocalRefinementRequest(
                parent_job_id=completed.job_id,
                parent_pose_artifact_id=pose1.artifact_id,
                compute="cpu",
            )
        )
        assert refinement.parent_job_id == completed.job_id
        assert refinement.parent_pose_sha256 == pose1.sha256
        assert refinement.parent_pose_flex_sha256 == pose1.pose_flex_sidechains_sha256
        assert refinement.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert refinement.refined_pose.flex_filename == "pose_1_flex.pdbqt"
        assert refinement.refined_pose.pose_flex_sidechains_sha256 != (
            pose1.pose_flex_sidechains_sha256
        )
        assert gnina_store.output_path(completed.job_id, "record.json").read_bytes() == (
            parent_before
        )
        assert service.get_refinement(refinement.refinement_id) == refinement
        assert service.refinement_pose_content_path(
            refinement.refinement_id, refinement.refined_pose.artifact_id
        ).is_file()
        assert (
            service.refinement_pose_flex_content_path(
                refinement.refinement_id, refinement.refined_pose.artifact_id
            )
            is not None
        )

        # Methods report for GNINA sidechain_flex + semi-flex ligand.
        catalog = ResultCatalogService(
            docking_store=DockingArtifactStore(tmp_path),
            autodock4_store=AutoDock4JobStore(tmp_path),
            autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
            binding_site_store=BindingSiteArtifactStore(tmp_path),
            ligand_store=LigandArtifactStore(tmp_path),
            gnina_store=gnina_store,
            gnina_screening_store=GninaScreeningStore(tmp_path),
        )
        methods_service = MethodsReportService(
            catalog=catalog,
            structures=StructureArtifactStore(tmp_path),
            receptors=ReceptorArtifactStore(tmp_path),
            binding_sites=BindingSiteArtifactStore(tmp_path),
            pockets=PocketDetectionArtifactStore(tmp_path),
            ligands=LigandArtifactStore(tmp_path),
            maps=AutoGridMapStore(tmp_path),
            docking=DockingArtifactStore(tmp_path),
            autodock4=AutoDock4JobStore(tmp_path),
            autodock_gpu=AutoDockGpuJobStore(tmp_path),
            gnina=gnina_store,
            gnina_screening=GninaScreeningStore(tmp_path),
        )
        report = methods_service.render(f"gnina_job:{completed.job_id}")
        assert not report.gaps
        assert seeded["flex_sha"] in report.markdown
        assert "MET A:5" in report.markdown
        assert "3 added side-chain chi torsions" in report.markdown
        assert "DOCKING_FLEXRES_DOF_HIGH" in report.markdown
        assert "rigid_input_conformation" in report.markdown
        assert "--flexible_amides" in report.markdown
        assert "LIG_RIGIDIFY_SMARTS_NO_MATCH" in report.markdown
        assert "effective `TORSDOF` of 2" in report.markdown
        assert "--out_flex" in report.markdown
        assert any(sw.name == "Meeko" and sw.version == "0.7.1" for sw in report.software)

        # Export bundle preserves v4 CSV columns + receptor_flex.pdbqt + raw_flex.pdb + flex poses.
        monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
        exporter = CampaignExportService(
            root=tmp_path,
            docking_store=DockingArtifactStore(tmp_path),
            autodock4_store=AutoDock4JobStore(tmp_path),
            autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
            binding_site_store=BindingSiteArtifactStore(tmp_path),
            gnina_store=gnina_store,
            gnina_screening_store=GninaScreeningStore(tmp_path),
            ligand_store=LigandArtifactStore(tmp_path),
        )
        exported = exporter.export_campaign(source_kind="gnina_job", batch_id=completed.job_id)
        export_dir = Path(exported["record_directory"])
        rows_reader = csv.reader(io.StringIO((export_dir / "results.csv").read_text("utf-8")))
        assert next(rows_reader) == _HEADER_GNINA_POSES

        manifest_data = json.loads((export_dir / "manifest.json").read_text("utf-8"))
        assert manifest_data["inputs"]["receptor_flex_mode"] == "sidechain_flex"
        assert manifest_data["inputs"]["receptor_flex_pdbqt_sha256"] == seeded["flex_sha"]
        source_paths = {item["path"] for item in manifest_data["source_files"]["files"]}
        assert "inputs/receptor_flex.pdbqt" in source_paths
        assert "raw/raw_flex.pdb" in source_paths
        assert "poses/pose_1_flex.pdbqt" in source_paths
        assert "poses/pose_2_flex.pdbqt" in source_paths

        with zipfile.ZipFile(export_dir / exported["archive_filename"]) as archive:
            names = set(archive.namelist())
            assert "inputs/receptor_flex.pdbqt" in names
            assert "raw/raw_flex.pdb" in names
            assert "poses/pose_1_flex.pdbqt" in names
            assert "methods.md" in names

        # Tampering stored receptor_flex.pdbqt must cause MethodsReportService to refuse receptor.
        flex_file = ReceptorArtifactStore(tmp_path).content_path(
            seeded["receptor"].receptor_id, seeded["flex_id"]
        )
        flex_file.write_bytes(b"TAMPERED")
        tampered_report = methods_service.render(f"gnina_job:{completed.job_id}")
        assert any("flexible side-chain" in gap for gap in tampered_report.gaps)
    finally:
        service.shutdown()


def test_api_flex_and_refinement_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    now = datetime.now(UTC)
    flex_bytes = _SYNTHETIC_MEEKO_FLEX_TEMPLATE.encode("utf-8")
    flex_sha = _sha256_bytes(flex_bytes)
    pose_bytes = _SYNTHETIC_LIGAND_PDBQT.encode("utf-8")
    pose_sha = _sha256_bytes(pose_bytes)
    rigid_sha = _sha256_bytes(_SYNTHETIC_RIGID_PDBQT.encode("utf-8"))
    conformer_sha = _sha256_bytes(_SYNTHETIC_CONFORMER_SDF.encode("utf-8"))
    tool_sha = _sha256_bytes(b"synthetic-tool")
    flex_res = [ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5)]
    lig_id = "00000000-0000-4000-8000-000000000011"

    # 1. Vina single (flex + rigid) and Vina batch (flex)
    docking_store = DockingArtifactStore(tmp_path)
    vina_job_id = docking_store.new_job_id()
    vina_job = VinaDockingJobRecord(
        job_id=vina_job_id,
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=now,
        request=VinaDockingRequest(
            receptor_id="rec-1",
            binding_site_id="site-1",
            ligand_id=lig_id,
            ligand_preparation_id="prep-1",
            parameters=VinaDockingParameters(scoring=VinaScoringFunction.VINARDO),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
        receptor_output_artifact_id="out-rigid",
        receptor_sha256=rigid_sha,
        receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_flex_output_artifact_id="out-flex",
        receptor_flex_sha256=flex_sha,
        flex_residues=flex_res,
        ligand_sha256=pose_sha,
        poses=[
            DockingPoseResult(
                mode=1,
                affinity_kcal_mol=-6.2,
                rmsd_lower_bound_angstrom=0.0,
                rmsd_upper_bound_angstrom=0.0,
                artifact=DockingPoseArtifact(
                    artifact_id="vina-pose-flex",
                    mode=1,
                    filename="pose_1.pdbqt",
                    format="pdbqt",
                    sha256=pose_sha,
                    size_bytes=len(pose_bytes),
                    content_url=f"/docking/jobs/{vina_job_id}/poses/vina-pose-flex/content",
                    flex_filename="pose_1_flex.pdbqt",
                    pose_flex_sidechains_sha256=flex_sha,
                    flex_content_url=f"/docking/jobs/{vina_job_id}/poses/vina-pose-flex/flex",
                ),
            ),
            DockingPoseResult(
                mode=2,
                affinity_kcal_mol=-5.8,
                rmsd_lower_bound_angstrom=1.2,
                rmsd_upper_bound_angstrom=1.8,
                artifact=DockingPoseArtifact(
                    artifact_id="vina-pose-rigid",
                    mode=2,
                    filename="pose_2.pdbqt",
                    format="pdbqt",
                    sha256=pose_sha,
                    size_bytes=len(pose_bytes),
                    content_url=f"/docking/jobs/{vina_job_id}/poses/vina-pose-rigid/content",
                ),
            ),
        ],
    )
    docking_store.create_job(vina_job)
    docking_store.write_bytes(vina_job_id, "pose_1.pdbqt", pose_bytes)
    docking_store.write_bytes(vina_job_id, "pose_1_flex.pdbqt", flex_bytes)
    docking_store.write_bytes(vina_job_id, "pose_2.pdbqt", pose_bytes)

    vina_batch_id = docking_store.new_batch_id()
    docking_store.create_batch(
        VinaBatchDockingRecord(
            batch_id=vina_batch_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            request=VinaBatchDockingRequest(
                receptor_id="rec-1",
                binding_site_id="site-1",
                library_id="lib-1",
                filter_run_id="flt-1",
                parameters=VinaBatchDockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
            receptor_output_artifact_id="out-rigid",
            receptor_sha256=rigid_sha,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id="out-flex",
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_res,
            selection_manifest_artifact_id="flt-1",
            selection_manifest_sha256=tool_sha,
            selected_count=1,
            worker_count=1,
            threads_per_ligand=1,
            completed_count=1,
            succeeded_count=1,
            failed_count=0,
            canceled_count=0,
            entries=[
                VinaBatchLigandResult(
                    ligand_id=lig_id,
                    source_index=0,
                    name="SYNTH",
                    status=DockingJobStatus.COMPLETED,
                    phase=DockingJobPhase.COMPLETE,
                    poses=[
                        DockingPoseResult(
                            mode=1,
                            affinity_kcal_mol=-6.1,
                            rmsd_lower_bound_angstrom=0.0,
                            rmsd_upper_bound_angstrom=0.0,
                            artifact=DockingPoseArtifact(
                                artifact_id="vb-pose-1",
                                mode=1,
                                filename="pose_1.pdbqt",
                                format="pdbqt",
                                sha256=pose_sha,
                                size_bytes=len(pose_bytes),
                                content_url=(
                                    f"/docking/batches/{vina_batch_id}/ligands/{lig_id}/"
                                    "poses/vb-pose-1/content"
                                ),
                                flex_filename="pose_1_flex.pdbqt",
                                pose_flex_sidechains_sha256=flex_sha,
                                flex_content_url=(
                                    f"/docking/batches/{vina_batch_id}/ligands/{lig_id}/"
                                    "poses/vb-pose-1/flex"
                                ),
                            ),
                        )
                    ],
                )
            ],
        )
    )
    docking_store.write_batch_bytes(vina_batch_id, lig_id, "pose_1.pdbqt", pose_bytes)
    docking_store.write_batch_bytes(vina_batch_id, lig_id, "pose_1_flex.pdbqt", flex_bytes)

    # 2. AutoDock4 single + batch
    ad4_store = AutoDock4JobStore(tmp_path)
    ad4_tool = AutoDock4ToolIdentity(
        tool=ToolIdentity(name="AutoDock4", version="4.2.6"),
        executable_path="/usr/bin/autodock4",
        sha256=tool_sha,
        max_atoms=2048,
        max_torsions=32,
        max_maps=16,
    )
    ad4_job_id = ad4_store.new_job_id()
    ad4_store.create_job(
        AutoDock4DockingJobRecord(
            job_id=ad4_job_id,
            status=AutoDock4JobStatus.COMPLETED,
            phase=AutoDock4JobPhase.COMPLETE,
            created_at=now,
            request=AutoDock4DockingRequest(
                receptor_id="rec-1",
                binding_site_id="site-1",
                map_set_id="map-1",
                ligand_id=lig_id,
                ligand_preparation_id="prep-1",
                parameters=AutoDock4DockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            autodock4=ad4_tool,
            receptor_id="rec-1",
            binding_site_id="site-1",
            map_set_id="map-1",
            map_set_identity_key=tool_sha,
            ligand_sha256=pose_sha,
            ligand_atom_types=["C", "OA"],
            ligand_atom_count=2,
            torsional_degrees_of_freedom=0,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_res,
            runs=[
                AutoDock4RunResult(
                    run=1,
                    cluster_rank=1,
                    sub_rank=1,
                    binding_energy_kcal_mol=-5.5,
                    cluster_rmsd_angstrom=0.0,
                    reference_rmsd_angstrom=0.0,
                    artifact=AutoDock4PoseArtifact(
                        artifact_id="ad4-run-1",
                        run=1,
                        filename="run_1.pdbqt",
                        format="pdbqt",
                        sha256=pose_sha,
                        size_bytes=len(pose_bytes),
                        content_url=f"/docking/autodock4/jobs/{ad4_job_id}/poses/ad4-run-1/content",
                        flex_filename="run_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=flex_sha,
                        flex_content_url=(
                            f"/docking/autodock4/jobs/{ad4_job_id}/poses/ad4-run-1/flex"
                        ),
                    ),
                )
            ],
        )
    )
    ad4_store.write_pose(ad4_job_id, "run_1.pdbqt", pose_bytes)
    ad4_store.write_pose(ad4_job_id, "run_1_flex.pdbqt", flex_bytes)

    ad4_batch_id = ad4_store.new_batch_id()
    ad4_store.create_batch(
        AutoDock4BatchRecord(
            batch_id=ad4_batch_id,
            status=AutoDock4JobStatus.COMPLETED,
            phase=AutoDock4JobPhase.COMPLETE,
            created_at=now,
            request=AutoDock4BatchRequest(
                receptor_id="rec-1",
                binding_site_id="site-1",
                map_set_id="map-1",
                library_id="lib-1",
                filter_run_id="flt-1",
                parameters=AutoDock4BatchParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            autodock4=ad4_tool,
            receptor_id="rec-1",
            binding_site_id="site-1",
            map_set_id="map-1",
            map_set_identity_key=tool_sha,
            selection_manifest_sha256=tool_sha,
            selected_count=1,
            worker_count=1,
            completed_count=1,
            succeeded_count=1,
            failed_count=0,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_res,
            entries=[
                AutoDock4BatchLigandResult(
                    ligand_id=lig_id,
                    source_index=0,
                    name="SYNTH",
                    status=AutoDock4JobStatus.COMPLETED,
                    phase=AutoDock4JobPhase.COMPLETE,
                    runs=[
                        AutoDock4RunResult(
                            run=1,
                            cluster_rank=1,
                            sub_rank=1,
                            binding_energy_kcal_mol=-5.5,
                            cluster_rmsd_angstrom=0.0,
                            reference_rmsd_angstrom=0.0,
                            artifact=AutoDock4PoseArtifact(
                                artifact_id="ad4b-run-1",
                                run=1,
                                filename="run_1.pdbqt",
                                format="pdbqt",
                                sha256=pose_sha,
                                size_bytes=len(pose_bytes),
                                content_url=(
                                    f"/docking/autodock4/batches/{ad4_batch_id}/ligands/{lig_id}/"
                                    "poses/ad4b-run-1/content"
                                ),
                                flex_filename="run_1_flex.pdbqt",
                                pose_flex_sidechains_sha256=flex_sha,
                                flex_content_url=(
                                    f"/docking/autodock4/batches/{ad4_batch_id}/ligands/{lig_id}/"
                                    "poses/ad4b-run-1/flex"
                                ),
                            ),
                        )
                    ],
                )
            ],
        )
    )
    ad4_store.write_batch_pose(ad4_batch_id, lig_id, "run_1.pdbqt", pose_bytes)
    ad4_store.write_batch_pose(ad4_batch_id, lig_id, "run_1_flex.pdbqt", flex_bytes)

    # 3. AutoDock-GPU single + batch
    gpu_store = AutoDockGpuJobStore(tmp_path)
    gpu_tool = AutoDockGpuToolIdentity(
        tool=ToolIdentity(name="AutoDock-GPU", version="1.6"),
        executable_path="/usr/bin/autodock_gpu",
        sha256=tool_sha,
        build="cuda",
        device_number=1,
        device_name="Synthetic GPU",
    )
    gpu_job_id = gpu_store.new_job_id()
    gpu_store.create_job(
        AutoDockGpuDockingJobRecord(
            job_id=gpu_job_id,
            status=AutoDockJobStatus.COMPLETED,
            phase=AutoDockJobPhase.COMPLETE,
            created_at=now,
            request=AutoDockGpuDockingRequest(
                receptor_id="rec-1",
                binding_site_id="site-1",
                map_set_id="map-1",
                ligand_id=lig_id,
                ligand_preparation_id="prep-1",
                parameters=AutoDockGpuDockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            autodock_gpu=gpu_tool,
            backend=AutoDockBackend.GPU,
            receptor_id="rec-1",
            binding_site_id="site-1",
            map_set_id="map-1",
            map_set_identity_key=tool_sha,
            ligand_sha256=pose_sha,
            ligand_atom_types=["C", "OA"],
            ligand_atom_count=2,
            torsional_degrees_of_freedom=0,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_res,
            runs=[
                AutoDock4RunResult(
                    run=1,
                    cluster_rank=1,
                    sub_rank=1,
                    binding_energy_kcal_mol=-5.4,
                    cluster_rmsd_angstrom=0.0,
                    reference_rmsd_angstrom=0.0,
                    artifact=AutoDock4PoseArtifact(
                        artifact_id="gpu-run-1",
                        run=1,
                        filename="run_1.pdbqt",
                        format="pdbqt",
                        sha256=pose_sha,
                        size_bytes=len(pose_bytes),
                        content_url=(
                            f"/docking/autodock-gpu/jobs/{gpu_job_id}/poses/gpu-run-1/content"
                        ),
                        flex_filename="run_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=flex_sha,
                        flex_content_url=(
                            f"/docking/autodock-gpu/jobs/{gpu_job_id}/poses/gpu-run-1/flex"
                        ),
                    ),
                )
            ],
        )
    )
    gpu_store.write_pose(gpu_job_id, "run_1.pdbqt", pose_bytes)
    gpu_store.write_pose(gpu_job_id, "run_1_flex.pdbqt", flex_bytes)

    gpu_batch_id = gpu_store.new_batch_id()
    gpu_store.create_batch(
        AutoDockGpuBatchRecord(
            batch_id=gpu_batch_id,
            status=AutoDockJobStatus.COMPLETED,
            phase=AutoDockJobPhase.COMPLETE,
            created_at=now,
            request=AutoDockGpuBatchRequest(
                receptor_id="rec-1",
                binding_site_id="site-1",
                map_set_id="map-1",
                library_id="lib-1",
                filter_run_id="flt-1",
                parameters=AutoDockGpuBatchParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            autodock_gpu=gpu_tool,
            backend=AutoDockBackend.GPU,
            receptor_id="rec-1",
            binding_site_id="site-1",
            map_set_id="map-1",
            map_set_identity_key=tool_sha,
            selection_manifest_sha256=tool_sha,
            selected_count=1,
            completed_count=1,
            succeeded_count=1,
            failed_count=0,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_res,
            entries=[
                AutoDockGpuBatchLigandResult(
                    ligand_id=lig_id,
                    source_index=0,
                    name="SYNTH",
                    status=AutoDockJobStatus.COMPLETED,
                    phase=AutoDockJobPhase.COMPLETE,
                    runs=[
                        AutoDock4RunResult(
                            run=1,
                            cluster_rank=1,
                            sub_rank=1,
                            binding_energy_kcal_mol=-5.4,
                            cluster_rmsd_angstrom=0.0,
                            reference_rmsd_angstrom=0.0,
                            artifact=AutoDock4PoseArtifact(
                                artifact_id="gpub-run-1",
                                run=1,
                                filename="run_1.pdbqt",
                                format="pdbqt",
                                sha256=pose_sha,
                                size_bytes=len(pose_bytes),
                                content_url=(
                                    f"/docking/autodock-gpu/batches/{gpu_batch_id}/ligands/"
                                    f"{lig_id}/poses/gpub-run-1/content"
                                ),
                                flex_filename="run_1_flex.pdbqt",
                                pose_flex_sidechains_sha256=flex_sha,
                                flex_content_url=(
                                    f"/docking/autodock-gpu/batches/{gpu_batch_id}/ligands/"
                                    f"{lig_id}/poses/gpub-run-1/flex"
                                ),
                            ),
                        )
                    ],
                )
            ],
        )
    )
    gpu_store.write_batch_pose(gpu_batch_id, lig_id, "run_1.pdbqt", pose_bytes)
    gpu_store.write_batch_pose(gpu_batch_id, lig_id, "run_1_flex.pdbqt", flex_bytes)

    # 4. GNINA single flex + Vina refinement + GNINA refinement
    gnina_store = GninaJobStore(tmp_path)
    gnina_job_id = gnina_store.new_job_id()
    gnina_store.create_job(
        GninaJobRecord(
            job_id=gnina_job_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            request=GninaDockingRequest(
                receptor_id="rec-1",
                binding_site_id="site-1",
                ligand_id=lig_id,
                ligand_preparation_id="prep-1",
                parameters=GninaDockingParameters(compute="cpu"),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=GninaToolIdentity(version="1.3.3", sha256=tool_sha, architecture="x86_64"),
            box=_SYNTHETIC_BOX,
            receptor_output_artifact_id="out-rigid",
            receptor_sha256=rigid_sha,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id="out-flex",
            receptor_flex_sha256=flex_sha,
            flex_residues=flex_res,
            ligand_sha256=pose_sha,
            conformer_sha256=conformer_sha,
            execution=GninaExecutionEvidence(
                command=["gnina"], exit_code=0, stdout="", stderr=""
            ),
            poses=[
                GninaPoseResult(
                    mode=1,
                    minimized_affinity_kcal_mol=-6.4,
                    cnn_score=0.84,
                    cnn_affinity=6.1,
                    artifact=GninaPoseArtifact(
                        artifact_id="gnina-pose-1",
                        mode=1,
                        filename="pose_1.pdbqt",
                        sha256=pose_sha,
                        size_bytes=len(pose_bytes),
                        flex_filename="pose_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=flex_sha,
                        flex_content_url=(
                            f"/docking/gnina/jobs/{gnina_job_id}/poses/gnina-pose-1/flex"
                        ),
                    ),
                )
            ],
        )
    )
    gnina_store.write_artifact(gnina_job_id, "pose_1.pdbqt", pose_bytes)
    gnina_store.write_artifact(gnina_job_id, "pose_1_flex.pdbqt", flex_bytes)

    vina_ref_id = docking_store.new_refinement_id()
    docking_store.create_refinement_dir(vina_ref_id)
    docking_store.write_refinement_bytes(vina_ref_id, "pose_1.pdbqt", pose_bytes)
    docking_store.write_refinement_bytes(vina_ref_id, "pose_1_flex.pdbqt", flex_bytes)
    vina_ref = VinaLocalRefinementRecord(
        refinement_id=vina_ref_id,
        created_at=now,
        parent_job_id=vina_job_id,
        parent_pose_artifact_id="vina-pose-flex",
        parent_pose_sha256=pose_sha,
        parent_pose_flex_sha256=flex_sha,
        receptor_id="rec-1",
        binding_site_id="site-1",
        ligand_id=lig_id,
        ligand_preparation_id="prep-1",
        receptor_output_artifact_id="out-rigid",
        receptor_sha256=rigid_sha,
        scoring=VinaScoringFunction.VINARDO,
        receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        flex_residues=flex_res,
        tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
        command=["vina", "--local_only"],
        estimated_free_energy_kcal_mol=-6.5,
        intermolecular_kcal_mol=-6.8,
        total_internal_kcal_mol=-0.3,
        torsional_free_energy_kcal_mol=0.6,
        unbound_system_energy_kcal_mol=0.0,
        refined_pose=DockingPoseArtifact(
            artifact_id="vref-pose-1",
            mode=1,
            filename="pose_1.pdbqt",
            format="pdbqt",
            sha256=pose_sha,
            size_bytes=len(pose_bytes),
            content_url=f"/docking/refinements/{vina_ref_id}/poses/vref-pose-1/content",
            flex_filename="pose_1_flex.pdbqt",
            pose_flex_sidechains_sha256=flex_sha,
            flex_content_url=f"/docking/refinements/{vina_ref_id}/poses/vref-pose-1/flex",
        ),
        execution=DockingExecutionEvidence(
            command=["vina", "--local_only"],
            exit_code=0,
            stdout="Estimated Free Energy of Binding : -6.5 (kcal/mol)\n",
            stderr="",
        ),
        provenance=ProvenanceEvent(
            event_id="evt-vref",
            event_type="vina_local_refinement_completed",
            timestamp=now,
            input_artifacts=[vina_job_id, "vina-pose-flex"],
            output_artifacts=[vina_ref_id],
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
        ),
    )
    docking_store.write_refinement_record(vina_ref)

    gnina_ref_id = gnina_store.new_refinement_id()
    gnina_store.create_refinement_dir(gnina_ref_id)
    gnina_store.write_refinement_artifact(gnina_ref_id, "pose_1.pdbqt", pose_bytes)
    gnina_store.write_refinement_artifact(gnina_ref_id, "pose_1_flex.pdbqt", flex_bytes)
    gnina_ref = GninaLocalRefinementRecord(
        refinement_id=gnina_ref_id,
        created_at=now,
        parent_job_id=gnina_job_id,
        parent_pose_artifact_id="gnina-pose-1",
        parent_pose_sha256=pose_sha,
        parent_pose_flex_sha256=flex_sha,
        receptor_id="rec-1",
        binding_site_id="site-1",
        ligand_id=lig_id,
        ligand_preparation_id="prep-1",
        receptor_output_artifact_id="out-rigid",
        receptor_sha256=rigid_sha,
        receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        flex_residues=flex_res,
        tool=GninaToolIdentity(version="1.3.3", sha256=tool_sha, architecture="x86_64"),
        cnn_model_identity=GninaCnnModelIdentity(
            selector="dense_1_3",
            cli_argument="dense_1_3",
            member_names=("dense_1_3",),
            member_count=1,
        ),
        command=["gnina", "--local_only"],
        minimized_affinity_kcal_mol=-6.7,
        cnn_score=0.88,
        cnn_affinity=6.3,
        cnn_vs=5.544,
        cnn_vs_source="derived_from_recorded_axes",
        refined_pose=GninaPoseArtifact(
            artifact_id="gref-pose-1",
            mode=1,
            filename="pose_1.pdbqt",
            sha256=pose_sha,
            size_bytes=len(pose_bytes),
            content_url=f"/docking/gnina/refinements/{gnina_ref_id}/poses/gref-pose-1/content",
            flex_filename="pose_1_flex.pdbqt",
            pose_flex_sidechains_sha256=flex_sha,
            flex_content_url=f"/docking/gnina/refinements/{gnina_ref_id}/poses/gref-pose-1/flex",
        ),
        execution=GninaExecutionEvidence(
            command=["gnina", "--local_only"], exit_code=0, stdout="", stderr=""
        ),
    )
    gnina_store.save_refinement(gnina_ref)

    with TestClient(create_app()) as client:
        # All 7 /flex endpoints return 200 with exact preserved bytes.
        flex_urls = [
            f"/api/v1/docking/jobs/{vina_job_id}/poses/vina-pose-flex/flex",
            f"/api/v1/docking/batches/{vina_batch_id}/ligands/{lig_id}/poses/vb-pose-1/flex",
            f"/api/v1/docking/autodock4/jobs/{ad4_job_id}/poses/ad4-run-1/flex",
            f"/api/v1/docking/autodock4/batches/{ad4_batch_id}/ligands/{lig_id}/poses/ad4b-run-1/flex",
            f"/api/v1/docking/autodock-gpu/jobs/{gpu_job_id}/poses/gpu-run-1/flex",
            f"/api/v1/docking/autodock-gpu/batches/{gpu_batch_id}/ligands/{lig_id}/poses/gpub-run-1/flex",
            f"/api/v1/docking/gnina/jobs/{gnina_job_id}/poses/gnina-pose-1/flex",
        ]
        for url in flex_urls:
            resp = client.get(url)
            assert resp.status_code == 200, url
            assert resp.content == flex_bytes

        # Rigid pose returns 404 DOCKING_POSE_FLEX_NOT_FOUND.
        rigid_resp = client.get(f"/api/v1/docking/jobs/{vina_job_id}/poses/vina-pose-rigid/flex")
        assert rigid_resp.status_code == 404
        assert rigid_resp.json()["code"] == "DOCKING_POSE_FLEX_NOT_FOUND"

        # GET refinement endpoints (Vina + GNINA)
        assert client.get(f"/api/v1/docking/refinements/{vina_ref_id}").status_code == 200
        assert (
            client.get(
                f"/api/v1/docking/refinements/{vina_ref_id}/poses/vref-pose-1/content"
            ).content
            == pose_bytes
        )
        assert (
            client.get(f"/api/v1/docking/refinements/{vina_ref_id}/poses/vref-pose-1/flex").content
            == flex_bytes
        )
        assert client.get(f"/api/v1/docking/gnina/refinements/{gnina_ref_id}").status_code == 200
        assert (
            client.get(
                f"/api/v1/docking/gnina/refinements/{gnina_ref_id}/poses/gref-pose-1/content"
            ).content
            == pose_bytes
        )
        assert (
            client.get(
                f"/api/v1/docking/gnina/refinements/{gnina_ref_id}/poses/gref-pose-1/flex"
            ).content
            == flex_bytes
        )

        # POST refinement routes wire cleanly to services (mocked to return saved records).
        monkeypatch.setattr(
            client.app.state.vina_docking,  # type: ignore[attr-defined]
            "refine_pose_local_only",
            lambda _req: vina_ref,
        )
        monkeypatch.setattr(
            client.app.state.gnina_docking,  # type: ignore[attr-defined]
            "refine_pose_local_only",
            lambda _req: gnina_ref,
        )
        post_vina = client.post(
            "/api/v1/docking/vina/refinements",
            json={
                "parent_job_id": vina_job_id,
                "parent_pose_artifact_id": "vina-pose-flex",
                "scoring": "vinardo",
            },
        )
        assert post_vina.status_code == 201
        assert post_vina.json()["refinement_id"] == vina_ref_id

        post_gnina = client.post(
            "/api/v1/docking/gnina/refinements",
            json={
                "parent_job_id": gnina_job_id,
                "parent_pose_artifact_id": "gnina-pose-1",
                "compute": "cpu",
            },
        )
        assert post_gnina.status_code == 201
        assert post_gnina.json()["refinement_id"] == gnina_ref_id


def test_methods_report_and_export_vina_vinardo_and_autodock4_flex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    seeded = _seed_synthetic_flex_project(tmp_path)
    now = datetime.now(UTC)
    pose_bytes = _SYNTHETIC_LIGAND_PDBQT.encode("utf-8")
    pose_sha = _sha256_bytes(pose_bytes)
    flex_bytes = _SYNTHETIC_MEEKO_FLEX_TEMPLATE.encode("utf-8")
    flex_sha = _sha256_bytes(flex_bytes)
    tool_sha = _sha256_bytes(b"synthetic-engine")

    docking_store = DockingArtifactStore(tmp_path)
    vina_batch_id = docking_store.new_batch_id()
    docking_store.create_batch(
        VinaBatchDockingRecord(
            batch_id=vina_batch_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            request=VinaBatchDockingRequest(
                receptor_id=seeded["receptor"].receptor_id,
                binding_site_id=seeded["site_id"],
                library_id="lib-missing",
                filter_run_id="flt-missing",
                parameters=VinaBatchDockingParameters(scoring=VinaScoringFunction.VINARDO),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
            receptor_output_artifact_id=seeded["rigid_id"],
            receptor_sha256=seeded["rigid_sha"],
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id=seeded["flex_id"],
            receptor_flex_sha256=flex_sha,
            flex_residues=[seeded["flex_locator"]],
            selection_manifest_artifact_id="flt-missing",
            selection_manifest_sha256=tool_sha,
            selected_count=1,
            worker_count=1,
            threads_per_ligand=1,
            completed_count=1,
            succeeded_count=1,
            failed_count=0,
            canceled_count=0,
            entries=[
                VinaBatchLigandResult(
                    ligand_id=seeded["ligand_id"],
                    ligand_preparation_id=seeded["prep_id"],
                    source_index=0,
                    name="SYNTH_CO",
                    status=DockingJobStatus.COMPLETED,
                    phase=DockingJobPhase.COMPLETE,
                    poses=[
                        DockingPoseResult(
                            mode=1,
                            affinity_kcal_mol=-6.0,
                            rmsd_lower_bound_angstrom=0.0,
                            rmsd_upper_bound_angstrom=0.0,
                            artifact=DockingPoseArtifact(
                                artifact_id="vb-p1",
                                mode=1,
                                filename="pose_1.pdbqt",
                                format="pdbqt",
                                sha256=pose_sha,
                                size_bytes=len(pose_bytes),
                                content_url="/docking/batches/x/ligands/y/poses/vb-p1/content",
                                flex_filename="pose_1_flex.pdbqt",
                                pose_flex_sidechains_sha256=flex_sha,
                                flex_content_url="/docking/batches/x/ligands/y/poses/vb-p1/flex",
                            ),
                        )
                    ],
                )
            ],
        )
    )
    docking_store.write_batch_bytes(vina_batch_id, seeded["ligand_id"], "pose_1.pdbqt", pose_bytes)
    docking_store.write_batch_bytes(
        vina_batch_id, seeded["ligand_id"], "pose_1_flex.pdbqt", flex_bytes
    )

    # Also seed an AutoGrid4 sidechain_flex map set + AutoDock4 flex job for MethodsReport.
    map_store = AutoGridMapStore(tmp_path)
    map_id = map_store.new_map_set_id()
    map_store.create_map_set_directory(map_id)
    map_store.write_record(
        AutoGridMapSetRecord(
            map_set_id=map_id,
            identity_key=tool_sha,
            created_at=now,
            request=AutoGridMapSetRequest(
                receptor_id=seeded["receptor"].receptor_id,
                binding_site_id=seeded["site_id"],
                source=AutoGridLigandSource.LIGAND_PREPARATION,
                ligand_id=seeded["ligand_id"],
                ligand_preparation_id=seeded["prep_id"],
            ),
            receptor_id=seeded["receptor"].receptor_id,
            receptor_output_artifact_id=seeded["rigid_id"],
            receptor_sha256=seeded["rigid_sha"],
            binding_site_id=seeded["site_id"],
            box=_SYNTHETIC_BOX,
            geometry=AutoGridGeometry(
                spacing_angstrom=0.375,
                npts=(40, 40, 40),
                requested_size_angstrom=(16.0, 16.0, 16.0),
                realized_size_angstrom=(15.0, 15.0, 15.0),
            ),
            preflight=AutoGridPreflight(
                receptor_atom_types=["C", "N", "OA"],
                ligand_atom_types=["C", "OA", "SA"],
                selected_count=1,
                prepared_count=1,
                compatible_count=1,
                incompatible_count=0,
                flex_atom_types=["C", "SA"],
                ligand_only_atom_types=["C", "OA"],
            ),
            autogrid=AutoGridToolIdentity(
                tool=ToolIdentity(name="AutoGrid4", version="4.2.6"),
                executable_path="/usr/bin/autogrid4",
                sha256=tool_sha,
                max_receptor_types=16,
                max_ligand_types=16,
                max_maps=16,
                max_grid_points=126,
            ),
            gpf_sha256=tool_sha,
            field_artifact_id="fld-1",
            execution=AutoGridExecutionEvidence(
                command=["autogrid4"],
                exit_code=0,
                stdout="",
                stderr="",
                duration_seconds=0.1,
                successful_completion_logged=True,
            ),
            artifacts=[
                AutoGridMapArtifact(
                    artifact_id="fld-1",
                    kind=AutoGridMapKind.FIELD,
                    filename="receptor.maps.fld",
                    sha256=tool_sha,
                    size_bytes=10,
                    content_url="/autogrid/x/fld-1",
                )
            ],
            provenance=ProvenanceEvent(
                event_id="evt-map",
                event_type="autogrid_maps_generated",
                timestamp=now,
                input_artifacts=[seeded["rigid_id"], seeded["flex_id"]],
                output_artifacts=[map_id],
                tool=ToolIdentity(name="AutoGrid4", version="4.2.6"),
            ),
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id=seeded["flex_id"],
            receptor_flex_sha256=flex_sha,
            flex_residues=[seeded["flex_locator"]],
            flex_atom_types=["C", "SA"],
        )
    )
    ad4_store = AutoDock4JobStore(tmp_path)
    ad4_id = ad4_store.new_job_id()
    ad4_store.create_job(
        AutoDock4DockingJobRecord(
            job_id=ad4_id,
            status=AutoDock4JobStatus.COMPLETED,
            phase=AutoDock4JobPhase.COMPLETE,
            created_at=now,
            request=AutoDock4DockingRequest(
                receptor_id=seeded["receptor"].receptor_id,
                binding_site_id=seeded["site_id"],
                map_set_id=map_id,
                ligand_id=seeded["ligand_id"],
                ligand_preparation_id=seeded["prep_id"],
                parameters=AutoDock4DockingParameters(),
                acknowledge_inputs_and_scoring=True,
            ),
            autodock4=AutoDock4ToolIdentity(
                tool=ToolIdentity(name="AutoDock4", version="4.2.6"),
                executable_path="/usr/bin/autodock4",
                sha256=tool_sha,
                max_atoms=2048,
                max_torsions=32,
                max_maps=16,
            ),
            receptor_id=seeded["receptor"].receptor_id,
            binding_site_id=seeded["site_id"],
            map_set_id=map_id,
            map_set_identity_key=tool_sha,
            ligand_sha256=pose_sha,
            ligand_atom_types=["C", "OA"],
            ligand_atom_count=2,
            torsional_degrees_of_freedom=0,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_sha256=flex_sha,
            flex_residues=[seeded["flex_locator"]],
            flex_atom_types=["C", "SA"],
        )
    )

    catalog = ResultCatalogService(
        docking_store=docking_store,
        autodock4_store=ad4_store,
        autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
        ligand_store=LigandArtifactStore(tmp_path),
        gnina_store=GninaJobStore(tmp_path),
        gnina_screening_store=GninaScreeningStore(tmp_path),
    )
    methods_service = MethodsReportService(
        catalog=catalog,
        structures=StructureArtifactStore(tmp_path),
        receptors=ReceptorArtifactStore(tmp_path),
        binding_sites=BindingSiteArtifactStore(tmp_path),
        pockets=PocketDetectionArtifactStore(tmp_path),
        ligands=LigandArtifactStore(tmp_path),
        maps=map_store,
        docking=docking_store,
        autodock4=ad4_store,
        autodock_gpu=AutoDockGpuJobStore(tmp_path),
        gnina=GninaJobStore(tmp_path),
        gnina_screening=GninaScreeningStore(tmp_path),
    )

    vina_report = methods_service.render(f"vina_batch:{vina_batch_id}")
    assert "--scoring vinardo" in vina_report.markdown
    assert "Vinardo score" in vina_report.markdown
    assert "--flex" in vina_report.markdown
    assert "MET A:5" in vina_report.markdown

    ad4_report = methods_service.render(f"autodock4_job:{ad4_id}")
    assert "union of ligand and flexible side-chain atom types (C, OA, SA" in ad4_report.markdown
    assert "DPF `flexres` directive" in ad4_report.markdown

    # Export Vina flex/vinardo batch and check Export v4 CSV header + flex source files.
    exporter = CampaignExportService(
        root=tmp_path,
        docking_store=docking_store,
        autodock4_store=ad4_store,
        autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
        binding_site_store=BindingSiteArtifactStore(tmp_path),
        gnina_store=GninaJobStore(tmp_path),
        gnina_screening_store=GninaScreeningStore(tmp_path),
        ligand_store=LigandArtifactStore(tmp_path),
    )
    exported = exporter.export_campaign(source_kind="vina_batch", batch_id=vina_batch_id)
    export_dir = Path(exported["record_directory"])
    manifest_data = json.loads((export_dir / "manifest.json").read_text("utf-8"))
    assert manifest_data["inputs"]["receptor_flex_mode"] == "sidechain_flex"
    assert manifest_data["inputs"]["receptor_flex_pdbqt_sha256"] == flex_sha
    assert any("Vinardo" in note for note in manifest_data["scientific_notes"])
    assert any(
        item["path"] == f"poses/{seeded['ligand_id']}/pose_1_flex.pdbqt"
        for item in manifest_data["source_files"]["files"]
    )


@pytest.mark.live_engine
def test_live_real_gnina_flex_end_to_end_with_local_only_and_e8_complex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("GNINA 1.3.3 is Linux-only.")
    try:
        probe_gnina()
    except AnkoraDomainError:
        pytest.skip("Real GNINA 1.3.3 binary is not configured on this Linux host.")

    Chem = import_module("rdkit.Chem")
    AllChem = import_module("rdkit.Chem.AllChem")
    # Build a synthetic GARYMP hexapeptide via RDKit (label: synthetic live test fixture).
    peptide = Chem.AddHs(Chem.MolFromSequence("GARYMP"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    assert AllChem.EmbedMolecule(peptide, params) == 0
    AllChem.MMFFOptimizeMolecule(peptide, maxIters=200)
    pdb_text = Chem.MolToPDBBlock(peptide)

    structures = StructureArtifactStore(tmp_path)
    receptors = ReceptorArtifactStore(tmp_path)
    sites = BindingSiteArtifactStore(tmp_path)
    ligands = LigandArtifactStore(tmp_path)
    gnina_store = GninaJobStore(tmp_path)

    structure = import_structure_bytes(
        content=pdb_text.encode("utf-8"),
        filename="live_synthetic_garymp_gnina.pdb",
        source=StructureSource.LOCAL,
        source_uri=None,
        store=structures,
    )
    flex_residues = [
        ResidueLocator(chain_id="A", residue_name="TYR", sequence_number=4),
        ResidueLocator(chain_id="A", residue_name="MET", sequence_number=5),
    ]
    receptor = receptor_preparation.prepare_receptor(
        source_artifact_id=structure.artifact.artifact_id,
        request=ReceptorPreparationRequest(
            selected_chains=["A"],
            water_action=ComponentAction.REMOVE,
            component_decisions=[],
            issue_decisions=[],
            protonation=ProtonationSettings(enabled=True, force_field="PARSE"),
            generate_pdbqt=True,
            flexibility=ReceptorFlexRequest(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=flex_residues,
            ),
        ),
        structure_store=structures,
        receptor_store=receptors,
    )
    assert receptor.flex_spec is not None

    prot = next(
        item for item in receptor.outputs if item.stage is ReceptorOutputStage.PROTONATED_PDB
    )
    prot_text = receptors.content_path(receptor.receptor_id, prot.artifact_id).read_text("utf-8")
    coords = [
        (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        for line in prot_text.splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    box = BindingBox(
        center_x=sum(p[0] for p in coords) / len(coords),
        center_y=sum(p[1] for p in coords) / len(coords),
        center_z=sum(p[2] for p in coords) / len(coords),
        size_x=22.0,
        size_y=22.0,
        size_z=22.0,
    )
    site_id = sites.new_binding_site_id()
    now = datetime.now(UTC)
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=receptor.receptor_id,
            source_artifact_id=structure.artifact.artifact_id,
            created_at=now,
            box=box,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
            warnings=[],
            provenance=[
                ProvenanceEvent(
                    event_id="evt-live-gnina-site",
                    event_type="binding_site_confirmed",
                    timestamp=now,
                    input_artifacts=[receptor.receptor_id],
                    output_artifacts=[site_id],
                    tool=ToolIdentity(name="Ankora", version="0.2.0-dev"),
                )
            ],
        )
    )

    lig_record = import_local_ligand(
        content=b"CCNC(C)=O LIVE_SYNTHETIC_AMIDE\n",
        filename="live_synthetic_amide.smi",
        store=ligands,
    )
    assert lig_record.state is not None
    conformer = generate_ligand_conformer(
        ligand_id=lig_record.artifact.ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True,
            state_id=lig_record.state.state_id,
        ),
        store=ligands,
    )
    pdbqt_record = prepare_ligand_pdbqt(
        ligand_id=lig_record.artifact.ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(),
        store=ligands,
    )

    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    service = GninaDockingService(
        store=gnina_store,
        receptors=receptors,
        sites=sites,
        ligands=ligands,
        leases=WorkLeaseManager(WorkLeaseStore(tmp_path)),
        resources=ResourceArbiter(
            cpu_threads=4,
            gpu_slots=1,
            memory_total_bytes=16 * 1024**3,
            memory_reserve_bytes=0,
            disk_path=tmp_path,
            disk_total_bytes=16 * 1024**3,
            disk_reserve_bytes=0,
            memory_available=lambda: 16 * 1024**3,
            disk_free=lambda: 16 * 1024**3,
        ),
    )
    try:
        started = service.start(
            GninaDockingRequest(
                receptor_id=receptor.receptor_id,
                binding_site_id=site_id,
                ligand_id=lig_record.artifact.ligand_id,
                ligand_preparation_id=pdbqt_record.artifact.preparation_id,
                parameters=GninaDockingParameters(
                    compute="cpu",
                    cpu_threads=2,
                    exhaustiveness=1,
                    num_modes=2,
                    seed=42,
                    cnn_scoring="rescore",
                    cnn_model="dense_1_3",
                ),
                acknowledge_inputs_and_scoring=True,
            )
        )
        completed = _wait_for_gnina_job(service, started.job_id, timeout=180.0)
        assert completed.status is DockingJobStatus.COMPLETED, completed.failure
        assert completed.receptor_flex_mode is ReceptorFlexMode.SIDECHAIN_FLEX
        assert len(completed.poses) >= 1

        pose1 = completed.poses[0].artifact
        assert pose1.flex_filename == "pose_1_flex.pdbqt"
        assert pose1.pose_flex_sidechains_sha256 is not None
        assert pose1.pose_complex_identity_sha256 is not None
        flex_path = gnina_store.pose_flex_content_path(completed.job_id, pose1.artifact_id)
        assert flex_path is not None
        flex_text = flex_path.read_text("utf-8")
        assert "BEGIN_RES" in flex_text and "BRANCH" in flex_text and "END_RES" in flex_text

        # Materialize E8 coupled complex and verify RDKit sanitization succeeds.
        materialized = materialize_coupled_receptor_pdb(
            protonated_pdb_text=prot_text,
            pose_flex_sidechains_pdbqt=flex_text,
        )
        assert materialized.moved_atom_count >= 14
        coupled_mol = Chem.MolFromPDBBlock(
            materialized.pdb_text, removeHs=False, sanitize=True, proximityBonding=True
        )
        assert coupled_mol is not None

        # Verify PoseInteractionService.complex_pdb serves the coupled complex cleanly.
        interactions = PoseInteractionService.from_environment()
        complex_pdb_text, complex_filename = interactions.complex_pdb(
            f"gnina_job:{completed.job_id}",
            lig_record.artifact.ligand_id,
            pose1.artifact_id,
        )
        assert complex_filename.endswith(".pdb")
        assert "HETATM" in complex_pdb_text

        # Live GNINA --local_only derivative on moved side-chain pose!
        parent_before = gnina_store.output_path(completed.job_id, "record.json").read_bytes()
        refinement = service.refine_pose_local_only(
            GninaLocalRefinementRequest(
                parent_job_id=completed.job_id,
                parent_pose_artifact_id=pose1.artifact_id,
                compute="cpu",
                cpu_threads=2,
                seed=42,
                cnn_scoring="rescore",
                cnn_model="dense_1_3",
            )
        )
        assert refinement.execution.exit_code == 0
        assert refinement.refined_pose.pose_flex_sidechains_sha256 is not None
        assert gnina_store.output_path(completed.job_id, "record.json").read_bytes() == (
            parent_before
        )

        # Live MethodsReport + CampaignExport on the real completed GNINA FlexRes job.
        monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
        exporter = CampaignExportService(
            root=tmp_path,
            docking_store=DockingArtifactStore(tmp_path),
            autodock4_store=AutoDock4JobStore(tmp_path),
            autodock_gpu_store=AutoDockGpuJobStore(tmp_path),
            binding_site_store=sites,
            gnina_store=gnina_store,
            gnina_screening_store=GninaScreeningStore(tmp_path),
            ligand_store=ligands,
        )
        exported = exporter.export_campaign(source_kind="gnina_job", batch_id=completed.job_id)
        export_dir = Path(exported["record_directory"])
        assert (export_dir / "inputs" / "receptor_flex.pdbqt").is_file()
        assert (export_dir / "raw" / "raw_flex.pdb").is_file()
        assert (export_dir / "poses" / "pose_1_flex.pdbqt").is_file()
        assert "TYR A:4" in (export_dir / "methods.md").read_text("utf-8")
    finally:
        service.shutdown()
