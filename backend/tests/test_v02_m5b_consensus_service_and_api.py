"""End-to-end live cross-engine service, API, stale-DAG, and Methods tests for M5b.

All receptors, ligands, and poses in this module are explicitly labelled synthetic.
Test 1 executes LIVE AutoGrid4 4.2.6, AutoDock Vina 1.2.7 (`vina` + `vinardo`
`--score_only`), and AutoDock4 4.2.6 (`epdb` `--score_only`) end-to-end through
FastAPI `/api/v1/consensus/runs/campaigns`.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.adapters.engines.autodock4_runner import probe_autodock4
from ankora_backend.adapters.engines.autogrid import probe_autogrid4
from ankora_backend.adapters.engines.vina import probe_vina
from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autogrid import (
    AutoGridExecutionEvidence,
    AutoGridGeometry,
    AutoGridLigandSource,
    AutoGridMapArtifact,
    AutoGridMapKind,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
    AutoGridPreflight,
)
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.calibration import CalibrationCompoundInput, CalibrationSplitPolicy
from ankora_backend.schemas.consensus import ConsensusRunRecord, ConsensusVariantId
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
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
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.v02_contracts import (
    RankingMethod,
    ScoringFamily,
    ScoringFunctionId,
)
from ankora_backend.services.methods_report import render_consensus_methods
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.protocol_calibration import ProtocolCalibrationService

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
meeko: Any = import_module("meeko")

_BOX = BindingBox(
    center_x=2.0,
    center_y=0.0,
    center_z=0.0,
    size_x=18.0,
    size_y=18.0,
    size_z=18.0,
)
_OTHER_BOX = BindingBox(
    center_x=5.0,
    center_y=5.0,
    center_z=5.0,
    size_x=18.0,
    size_y=18.0,
    size_z=18.0,
)

# Synthetic compact alanine-glycine receptor cleanly typed for AutoGrid4 + Vina
_SYNTHETIC_RECEPTOR_PDB = (
    "ATOM      1  N   ALA A   1      -2.000   0.000   0.000  1.00  0.00           N  \n"
    "ATOM      2  CA  ALA A   1      -1.200   1.200   0.000  1.00  0.00           C  \n"
    "ATOM      3  C   ALA A   1       0.250   1.000   0.000  1.00  0.00           C  \n"
    "ATOM      4  O   ALA A   1       0.800   0.000   0.000  1.00  0.00           O  \n"
    "ATOM      5  CB  ALA A   1      -1.600   2.100   1.150  1.00  0.00           C  \n"
    "END\n"
)
_SYNTHETIC_RECEPTOR_PDBQT = (
    "ATOM      1  N   ALA A   1      -2.000   0.000   0.000  1.00  0.00    -0.300 N \n"
    "ATOM      2  CA  ALA A   1      -1.200   1.200   0.000  1.00  0.00     0.100 C \n"
    "ATOM      3  C   ALA A   1       0.250   1.000   0.000  1.00  0.00     0.500 C \n"
    "ATOM      4  O   ALA A   1       0.800   0.000   0.000  1.00  0.00    -0.500 OA\n"
    "ATOM      5  CB  ALA A   1      -1.600   2.100   1.150  1.00  0.00     0.200 C \n"
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _make_ligand_at(smiles: str, dx: float, dy: float = 0.0) -> tuple[bytes, bytes]:
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261119
    params.numThreads = 1
    assert AllChem.EmbedMolecule(mol, params) == 0
    assert AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94s") == 0

    conf = mol.GetConformer()
    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    cx = sum(conf.GetAtomPosition(i).x for i in heavy) / len(heavy)
    cy = sum(conf.GetAtomPosition(i).y for i in heavy) / len(heavy)
    cz = sum(conf.GetAtomPosition(i).z for i in heavy) / len(heavy)
    for idx in range(mol.GetNumAtoms()):
        pt = conf.GetAtomPosition(idx)
        conf.SetAtomPosition(idx, (pt.x - cx + dx, pt.y - cy + dy, pt.z - cz))

    sdf_bytes = (Chem.MolToMolBlock(mol) + "\n$$$$\n").encode("utf-8")
    prep = meeko.MoleculePreparation()
    setups = prep.prepare(mol)
    pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(setups[0])
    assert is_ok, err
    return sdf_bytes, pdbqt_str.encode("utf-8")


def _seed_live_cross_engine_project(tmp_path: Path) -> dict[str, str]:
    now = datetime.now(UTC)
    receptors = ReceptorArtifactStore.from_environment()
    sites = BindingSiteArtifactStore.from_environment()
    maps_store = AutoGridMapStore.from_environment()
    ligands = LigandArtifactStore.from_environment()
    docking = DockingArtifactStore.from_environment()

    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    prot_bytes = _SYNTHETIC_RECEPTOR_PDB.encode("utf-8")
    pdbqt_bytes = _SYNTHETIC_RECEPTOR_PDBQT.encode("utf-8")
    prot_art_id = "art-prot"
    pdbqt_art_id = "art-pdbqt"
    receptors.write_bytes(rec_id, "protonated.pdb", prot_bytes)
    receptors.write_bytes(rec_id, "receptor.pdbqt", pdbqt_bytes)
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="src-synth-ala",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=True,
            ),
            outputs=[
                ReceptorOutputArtifact(
                    artifact_id=prot_art_id,
                    stage=ReceptorOutputStage.PROTONATED_PDB,
                    filename="protonated.pdb",
                    format="pdb",
                    sha256=_sha(prot_bytes),
                    size_bytes=len(prot_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{prot_art_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=pdbqt_art_id,
                    stage=ReceptorOutputStage.PDBQT,
                    filename="receptor.pdbqt",
                    format="pdbqt",
                    sha256=_sha(pdbqt_bytes),
                    size_bytes=len(pdbqt_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{pdbqt_art_id}/content",
                ),
            ],
            warnings=[],
            display_output_artifact_id=prot_art_id,
            provenance=[],
        )
    )

    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="src-synth-ala",
            created_at=now,
            box=_BOX,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=_BOX),
            warnings=[],
            provenance=[],
        )
    )
    other_site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=other_site_id,
            receptor_id=rec_id,
            source_artifact_id="src-synth-ala",
            created_at=now,
            box=_OTHER_BOX,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=_OTHER_BOX),
            warnings=[],
            provenance=[],
        )
    )

    # Create two synthetic ligands with 2 saved poses each (1 near, 1 shifted > 4 A)
    def _create_ligand_and_vina_job(
        name: str, smiles: str, target_site_id: str, x1: float, x2: float
    ) -> tuple[str, str, bytes]:
        sdf1, pose1 = _make_ligand_at(smiles, x1, 0.0)
        _, pose2 = _make_ligand_at(smiles, x2, 3.5)
        lig_id = ligands.new_ligand_id()
        insp = LigandInspection(
            name=name,
            formula="C2H6O",
            formal_charge=0,
            atom_count=9,
            heavy_atom_count=3,
            rotatable_bond_count=1 if len(smiles) > 3 else 0,
            aromatic_ring_count=0,
            stereocenter_count=0,
            conformer_count=1,
            has_3d_coordinates=True,
            canonical_smiles=smiles,
        )
        ligands.create(
            lig_id,
            sdf1,
            LigandRecord(
                artifact=LigandArtifact(
                    ligand_id=lig_id,
                    source=LigandSource.LOCAL,
                    filename=f"{name}.sdf",
                    format=LigandFormat.SDF,
                    sha256=_sha(sdf1),
                    size_bytes=len(sdf1),
                    created_at=now,
                ),
                inspection=insp,
                warnings=[],
                provenance=ProvenanceEvent(
                    event_id=f"evt-lig-{name}",
                    event_type="ligand_imported",
                    timestamp=now,
                    input_artifacts=[],
                    output_artifacts=[lig_id],
                    tool=ToolIdentity(name="RDKit", version="2025.9.6"),
                ),
                content_url=f"/ligands/{lig_id}/content",
            ),
        )
        conf_id = ligands.new_conformer_id()
        ligands.create_conformer(
            lig_id,
            conf_id,
            sdf1,
            LigandConformerRecord(
                artifact=LigandConformerArtifact(
                    conformer_id=conf_id,
                    ligand_id=lig_id,
                    stage="minimized",
                    filename=f"{name}_conf.sdf",
                    format="sdf",
                    sha256=_sha(sdf1),
                    size_bytes=len(sdf1),
                    created_at=now,
                ),
                inspection=insp,
                minimization=LigandMinimizationResult(
                    force_field=LigandForceField.MMFF94S,
                    max_iterations=200,
                    converged=True,
                    initial_energy_kcal_mol=0.2,
                    final_energy_kcal_mol=0.1,
                ),
                warnings=[],
                provenance=ProvenanceEvent(
                    event_id=f"evt-conf-{name}",
                    event_type="ligand_minimized",
                    timestamp=now,
                    input_artifacts=[lig_id],
                    output_artifacts=[conf_id],
                    tool=ToolIdentity(name="RDKit", version="2025.9.6"),
                ),
                content_url=f"/ligands/{lig_id}/conformers/{conf_id}/content",
            ),
        )
        prep_id = ligands.new_preparation_id()
        ligands.create_pdbqt(
            lig_id,
            prep_id,
            pose1,
            LigandPdbqtRecord(
                artifact=LigandPdbqtArtifact(
                    preparation_id=prep_id,
                    ligand_id=lig_id,
                    conformer_id=conf_id,
                    filename=f"{name}.pdbqt",
                    format="pdbqt",
                    sha256=_sha(pose1),
                    size_bytes=len(pose1),
                    created_at=now,
                ),
                charge_model=LigandChargeModel.GASTEIGER,
                tool=ToolIdentity(name="Meeko", version="0.7.1"),
                command=["mk_prepare_ligand"],
                stdout="",
                stderr="",
                provenance=ProvenanceEvent(
                    event_id=f"evt-prep-{name}",
                    event_type="ligand_pdbqt_prepared",
                    timestamp=now,
                    input_artifacts=[conf_id],
                    output_artifacts=[prep_id],
                    tool=ToolIdentity(name="Meeko", version="0.7.1"),
                ),
                content_url=f"/ligands/{lig_id}/pdbqt/{prep_id}/content",
            ),
        )
        job_id = docking.new_job_id()
        docking.create_job(
            VinaDockingJobRecord(
                job_id=job_id,
                status=DockingJobStatus.COMPLETED,
                phase=DockingJobPhase.COMPLETE,
                created_at=now,
                completed_at=now,
                request=VinaDockingRequest(
                    receptor_id=rec_id,
                    binding_site_id=target_site_id,
                    ligand_id=lig_id,
                    ligand_preparation_id=prep_id,
                    parameters=VinaDockingParameters(),
                    acknowledge_inputs_and_scoring=True,
                ),
                tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
                receptor_output_artifact_id=pdbqt_art_id,
                receptor_sha256=_sha(pdbqt_bytes),
                ligand_sha256=_sha(pose1),
                poses=[
                    DockingPoseResult(
                        mode=1,
                        affinity_kcal_mol=-3.2,
                        rmsd_lower_bound_angstrom=0.0,
                        rmsd_upper_bound_angstrom=0.0,
                        artifact=DockingPoseArtifact(
                            artifact_id=f"{job_id}-p1",
                            mode=1,
                            filename="pose_1.pdbqt",
                            format="pdbqt",
                            sha256=_sha(pose1),
                            size_bytes=len(pose1),
                            content_url=f"/docking/vina/jobs/{job_id}/poses/{job_id}-p1/content",
                        ),
                    ),
                    DockingPoseResult(
                        mode=2,
                        affinity_kcal_mol=-2.4,
                        rmsd_lower_bound_angstrom=0.0,
                        rmsd_upper_bound_angstrom=0.0,
                        artifact=DockingPoseArtifact(
                            artifact_id=f"{job_id}-p2",
                            mode=2,
                            filename="pose_2.pdbqt",
                            format="pdbqt",
                            sha256=_sha(pose2),
                            size_bytes=len(pose2),
                            content_url=f"/docking/vina/jobs/{job_id}/poses/{job_id}-p2/content",
                        ),
                    ),
                ],
            )
        )
        docking.write_bytes(job_id, "pose_1.pdbqt", pose1)
        docking.write_bytes(job_id, "pose_2.pdbqt", pose2)
        return lig_id, job_id, pose1

    lig1_id, job1_id, pose1_bytes = _create_ligand_and_vina_job("ethanol", "CCO", site_id, 3.5, 7.5)
    lig2_id, job2_id, pose2_bytes = _create_ligand_and_vina_job(
        "propanol", "CCCO", site_id, 4.0, 8.0
    )
    _, job_mismatch_id, _ = _create_ligand_and_vina_job(
        "other_box_lig", "CCO", other_site_id, 3.5, 7.5
    )

    # Generate real AutoGrid4 maps on disk for the shared receptor & box!
    ag_install = probe_autogrid4()
    map_set_id = maps_store.new_map_set_id()
    map_dir = maps_store.create_map_set_directory(map_set_id)
    (map_dir / "receptor.pdbqt").write_bytes(pdbqt_bytes)

    rec_types = collect_autodock_atom_types([pdbqt_bytes.decode("utf-8")])
    lig_types = collect_autodock_atom_types(
        [pose1_bytes.decode("utf-8"), pose2_bytes.decode("utf-8")]
    )
    gpf_text, grid_plan = render_autogrid_gpf(
        _BOX,
        receptor_filename="receptor.pdbqt",
        receptor_atom_types=rec_types,
        ligand_atom_types=lig_types,
        map_prefix="receptor",
    )
    gpf_path = map_dir / "receptor.gpf"
    gpf_path.write_text(gpf_text, encoding="utf-8")
    glg_path = map_dir / "receptor.glg"
    ag_cmd = [ag_install.executable, "-p", str(gpf_path), "-l", str(glg_path)]
    ag_proc = subprocess.run(
        ag_cmd,
        cwd=str(map_dir),
        check=True,
        capture_output=True,
        text=True,
    )

    map_artifacts: list[AutoGridMapArtifact] = []
    field_artifact_id = f"{map_set_id}-fld"
    for path in sorted(map_dir.iterdir()):
        raw = path.read_bytes()
        if path.suffix == ".map":
            stem_ext = path.name.removeprefix("receptor.").removesuffix(".map")
            kind = (
                AutoGridMapKind.ELECTROSTATIC
                if stem_ext == "e"
                else AutoGridMapKind.DESOLVATION
                if stem_ext == "d"
                else AutoGridMapKind.AFFINITY
            )
            art_id = f"{map_set_id}-map-{stem_ext}"
            map_artifacts.append(
                AutoGridMapArtifact(
                    artifact_id=art_id,
                    filename=path.name,
                    kind=kind,
                    atom_type=None if kind is not AutoGridMapKind.AFFINITY else stem_ext,
                    sha256=_sha(raw),
                    size_bytes=len(raw),
                    content_url=f"/autogrid/maps/{map_set_id}/artifacts/{art_id}/content",
                )
            )
        elif path.name == "receptor.maps.fld":
            map_artifacts.append(
                AutoGridMapArtifact(
                    artifact_id=field_artifact_id,
                    filename=path.name,
                    kind=AutoGridMapKind.FIELD,
                    atom_type=None,
                    sha256=_sha(raw),
                    size_bytes=len(raw),
                    content_url=f"/autogrid/maps/{map_set_id}/artifacts/{field_artifact_id}/content",
                )
            )

    maps_store.write_record(
        AutoGridMapSetRecord(
            map_set_id=map_set_id,
            identity_key=_sha(f"synth-map-{map_set_id}".encode()),
            created_at=now,
            request=AutoGridMapSetRequest(
                receptor_id=rec_id,
                binding_site_id=site_id,
                source=AutoGridLigandSource.LIGAND_PREPARATION,
                ligand_id=lig1_id,
            ),
            receptor_id=rec_id,
            receptor_output_artifact_id=pdbqt_art_id,
            receptor_sha256=_sha(pdbqt_bytes),
            binding_site_id=site_id,
            box=_BOX,
            geometry=AutoGridGeometry(
                spacing_angstrom=grid_plan.spacing_angstrom,
                npts=grid_plan.npts,
                requested_size_angstrom=grid_plan.requested_size_angstrom,
                realized_size_angstrom=grid_plan.realized_size_angstrom,
            ),
            preflight=AutoGridPreflight(
                receptor_atom_types=list(rec_types),
                ligand_atom_types=list(lig_types),
                selected_count=2,
                prepared_count=2,
                compatible_count=2,
                incompatible_count=0,
            ),
            autogrid=ag_install.identity(),
            gpf_sha256=_sha(gpf_path.read_bytes()),
            field_artifact_id=field_artifact_id,
            execution=AutoGridExecutionEvidence(
                command=ag_cmd,
                exit_code=ag_proc.returncode,
                stdout=ag_proc.stdout,
                stderr=ag_proc.stderr,
                duration_seconds=0.1,
                successful_completion_logged=True,
            ),
            artifacts=map_artifacts,
            provenance=ProvenanceEvent(
                event_id="evt-ag-m5b",
                event_type="autogrid_maps_generated",
                timestamp=now,
                input_artifacts=[rec_id, site_id],
                output_artifacts=[map_set_id],
                tool=ToolIdentity(name="AutoGrid", version=ag_install.version),
            ),
        )
    )

    return {
        "receptor_id": rec_id,
        "site_id": site_id,
        "map_set_id": map_set_id,
        "lig1_id": lig1_id,
        "lig2_id": lig2_id,
        "catalog1": f"vina_job:{job1_id}",
        "catalog2": f"vina_job:{job2_id}",
        "catalog_mismatch": f"vina_job:{job_mismatch_id}",
    }


@pytest.mark.live_engine
def test_live_cross_engine_campaign_consensus_panel_reuse_e4_stale_and_methods(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Runs LIVE AutoDock Vina 1.2.7 (vina + vinardo) & AutoDock4 4.2.6 (epdb) consensus."""
    try:
        probe_autogrid4()
        probe_autodock4()
        probe_vina()
    except AnkoraDomainError:
        pytest.skip("Real AutoGrid4 / AutoDock4 / Vina binaries are not configured on this host.")
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    seeded = _seed_live_cross_engine_project(tmp_path)

    with TestClient(app) as client:
        # 1. Fail-closed E4 mismatch when combining jobs from different binding boxes
        bad_resp = client.post(
            "/api/v1/consensus/runs/campaigns",
            json={
                "name": "Mismatched boxes",
                "variant_id": "pcq-core-v1",
                "sources": [
                    {"catalog_id": seeded["catalog1"]},
                    {"catalog_id": seeded["catalog_mismatch"]},
                ],
                "autogrid_map_set_id": seeded["map_set_id"],
                "k_max": 2,
            },
        )
        assert bad_resp.status_code == 422
        assert bad_resp.json()["code"] == "CONSENSUS_SHARED_CONTEXT_MISMATCH"

        # 2. Live cross-engine PC-Q Core (Vina + Vinardo + AutoDock4 epdb) across 2 compounds
        run_resp = client.post(
            "/api/v1/consensus/runs/campaigns",
            json={
                "name": "Live Core Consensus",
                "variant_id": "pcq-core-v1",
                "sources": [
                    {"catalog_id": seeded["catalog1"]},
                    {"catalog_id": seeded["catalog2"]},
                ],
                "autogrid_map_set_id": seeded["map_set_id"],
                "include_vinardo": True,
                "k_max": 2,
                "rmsd_threshold_angstrom": 2.0,
            },
        )
        assert run_resp.status_code == 201, run_resp.text
        run = ConsensusRunRecord.model_validate(run_resp.json())
        assert run.variant_id is ConsensusVariantId.PCQ_CORE_V1
        assert run.ranking.method is RankingMethod.PC_Q_CORE_V1
        assert run.ecr_ranking.method is RankingMethod.PC_ECR_V1
        assert run.ranking.total_parents == 2
        assert run.ranking.full_profile_count == 2
        assert run.ranking.partial_or_unscored_count == 0
        assert run.reference_panel.total_panel_parents == 2
        assert set(run.enabled_functions) == {
            ScoringFunctionId.VINA,
            ScoringFunctionId.VINARDO,
            ScoringFunctionId.AUTODOCK4,
        }
        # Every full-profile parent has 2 retained clusters (poses shifted > 4 A) with real scores!
        for detail in run.parent_details:
            assert detail.tier == "full_profile"
            assert detail.retained_cluster_count == 2
            assert detail.pcq_score is not None and 0.0 <= detail.pcq_score <= 100.0
            assert detail.pc_ecr_score is not None and detail.pc_ecr_score > 0.0
            for medoid in detail.medoids:
                assert ScoringFunctionId.VINA in medoid.native_scores
                assert ScoringFunctionId.VINARDO in medoid.native_scores
                assert ScoringFunctionId.AUTODOCK4 in medoid.native_scores

        # 3. E1 Reference panel reuse on a single-analog follow-up keeps exact panel SHA-256!
        followup_resp = client.post(
            "/api/v1/consensus/runs/campaigns",
            json={
                "name": "Single-analog locked panel follow-up",
                "variant_id": "pcq-core-v1",
                "sources": [{"catalog_id": seeded["catalog1"]}],
                "autogrid_map_set_id": seeded["map_set_id"],
                "include_vinardo": True,
                "k_max": 2,
                "reference_panel_id": run.reference_panel.panel_id,
            },
        )
        assert followup_resp.status_code == 201, followup_resp.text
        followup = ConsensusRunRecord.model_validate(followup_resp.json())
        assert (
            followup.reference_panel.reference_panel_sha256
            == run.reference_panel.reference_panel_sha256
        )
        assert followup.ranking.total_parents == 1

        # 4. GET list and detail endpoints
        listed = client.get("/api/v1/consensus/runs")
        assert listed.status_code == 200
        assert len(listed.json()["runs"]) == 2
        fetched = client.get(f"/api/v1/consensus/runs/{run.consensus_id}")
        assert fetched.status_code == 200
        assert fetched.json()["consensus_id"] == run.consensus_id

        # 5. ProjectDependencyService stale propagation: receptor -> panel + consensus runs
        deps = ProjectDependencyService(root=tmp_path)
        marked = deps.mark_stale(seeded["receptor_id"], "Receptor updated in M5b test")
        assert run.reference_panel.panel_id in marked.affected_node_ids
        assert run.consensus_id in marked.affected_node_ids
        assert followup.consensus_id in marked.affected_node_ids

        # 6. MethodsReport prose cites verified Palacio-Rodriguez (2019) DOI & exact hashes
        methods_md = render_consensus_methods(run)
        assert "10.1038/s41598-019-41594-3" in methods_md
        assert "Palacio-Rodríguez" in methods_md
        assert run.reference_panel.reference_panel_sha256[:12] in methods_md
        assert "`K_max = 2`" in methods_md
        assert "`tau = 0.05`" in methods_md


def test_structured_neural_consensus_and_create_only_pc_l2_derivative_api(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Verifies structured pcq-neural-v1 (with core alongside) + POST /pc-l2 derivative."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()

    # Build a synthetic M2 Calibration run over 8 distinct scaffolds
    cores = (
        "c1ccccc1",
        "c1ccc2ccccc2c1",
        "c1ccncc1",
        "C1CCCCC1",
        "c1ccsc1",
        "C1CCNCC1",
        "c1ccc(-c2ccccc2)cc1",
        "c1cnc2ccccc2c1",
    )
    compounds = [
        CalibrationCompoundInput(
            parent_id=f"c_f{fi}_m{mi}",
            canonical_smiles=f"{core}{'C' * (mi + 1)}",
            is_active=(mi < 3),
        )
        for fi, core in enumerate(cores)
        for mi in range(8)
    ]
    cal_svc = ProtocolCalibrationService(store=CalibrationArtifactStore.from_environment())
    cal_run = cal_svc.create_split(
        project_id="default",
        receptor_id="rec-neural",
        binding_site_id="site-neural",
        compounds=compounds,
        policy=CalibrationSplitPolicy(bootstrap_replicates=150, min_confirmation_actives=6),
    )

    rec_sha = "1" * 64
    box_sha = "2" * 64
    map_sha = "3" * 64
    parents_payload = []
    for comp in cal_run.split.compounds:
        base_score = -9.5 if comp.is_active else -6.5
        parents_payload.append(
            {
                "parent_compound_id": comp.parent_id,
                "parent_state_id": f"{comp.parent_id}-s1",
                "medoids": [
                    {
                        "cluster_id": f"cl-{comp.parent_id}",
                        "medoid_pose_id": f"p-{comp.parent_id}",
                        "pose_complex": {
                            "mode": "rigid",
                            "receptor_rigid_sha256": rec_sha,
                            "ligand_pose_sha256": _sha(comp.parent_id.encode()),
                        },
                        "canonical_coordinate_sha256": _sha(f"coord-{comp.parent_id}".encode()),
                        "search_engines_present": ["vina", "autodock4", "gnina"],
                        "scores_by_function": {
                            "vina": base_score,
                            "autodock4": base_score,
                            "gnina_cnn_vs": 7.5 if comp.is_active else 2.5,
                        },
                    }
                ],
            }
        )

    with TestClient(app) as client:
        create_resp = client.post(
            "/api/v1/consensus/runs/structured",
            json={
                "name": "Structured Linux Neural Consensus",
                "variant_id": "pcq-neural-v1",
                "receptor_id": "rec-neural",
                "binding_site_id": "site-neural",
                "receptor_flex_spec": {"mode": "rigid", "receptor_rigid_sha256": rec_sha},
                "binding_box_sha256": box_sha,
                "autogrid_map_set_sha256": map_sha,
                "enabled_functions": ["vina", "autodock4", "gnina_cnn_vs"],
                "k_max": 1,
                "search_engine_count": 3,
                "parents": parents_payload,
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        base_rec = ConsensusRunRecord.model_validate(create_resp.json())
        assert base_rec.core_ranking is not None
        assert base_rec.pc_l2_model is None
        assert ScoringFamily.GNINA_NEURAL in base_rec.block_weights

        # Fit create-only PC-L2 derivative
        pcl2_resp = client.post(
            f"/api/v1/consensus/runs/{base_rec.consensus_id}/pc-l2",
            json={"calibration_id": cal_run.calibration_id, "l2_regularization": 0.5},
        )
        assert pcl2_resp.status_code == 201, pcl2_resp.text
        deriv = ConsensusRunRecord.model_validate(pcl2_resp.json())
        assert deriv.consensus_id != base_rec.consensus_id
        assert deriv.pc_l2_model is not None
        assert deriv.pc_l2_model.converged is True
        assert all(w >= 0.0 for w in deriv.pc_l2_model.weights.values())
        assert deriv.pc_l2_ranking is not None
        assert deriv.pc_l2_ranking.method is RankingMethod.PC_L2_V1

        # Parent record remains immutable and untouched (ADR-004)
        reloaded_parent = client.get(f"/api/v1/consensus/runs/{base_rec.consensus_id}").json()
        assert reloaded_parent["pc_l2_model"] is None

        # Methods report renders both pcq-core-v1 alongside note and PC-L2 gate verdict
        methods_md = render_consensus_methods(deriv)
        assert "Windows-comparable `pcq-core-v1`" in methods_md
        assert "PC-L2" in methods_md
        assert deriv.pc_l2_model.promotion_verdict_text in methods_md
