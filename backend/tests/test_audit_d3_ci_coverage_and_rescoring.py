"""Binary-free Dual-OS CI integration tests closing D3-001, D3-002, and D3-005.

Every receptor, ligand, map set, and external binary output here is explicitly
synthetic (or replayed from tracked real fixtures) so all three paths execute
in BOTH Windows CI (`verify`) and Linux CI (`verify-linux`) with zero skips.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_v02_m5b_consensus_service_and_api import (
    _BOX,
    _OTHER_BOX,
    _SYNTHETIC_RECEPTOR_PDB,
    _SYNTHETIC_RECEPTOR_PDBQT,
    _make_ligand_at,
)

from ankora_backend.adapters.engines.autodock4 import (
    collect_autodock_atom_types,
    render_autogrid_gpf,
)
from ankora_backend.adapters.engines.autodock4_runner import (
    DOCKING_LOG_FILENAME,
    DOCKING_PARAMETER_FILENAME,
    AutoDock4Installation,
)
from ankora_backend.adapters.engines.autogrid import AutoGridInstallation
from ankora_backend.adapters.engines.vina import VinaInstallation
from ankora_backend.api.app import create_app
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
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
from ankora_backend.schemas.consensus import (
    ConsensusRunRecord,
    ConsensusVariantId,
)
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    DockingPoseArtifact,
    DockingPoseResult,
    VinaDockingJobRecord,
    VinaDockingParameters,
    VinaDockingRequest,
)
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningRequest,
    GninaScreeningSelection,
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
    ReceptorFlexMode,
    ReceptorFlexSpec,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.schemas.rescoring import (
    AutoDock4RescoreBackend,
    PoseRescoreContext,
    PoseRescoreRequest,
    ScoringFunctionId,
)
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    PoseComplexIdentity,
    RankingMethod,
    canonical_contract_sha256,
)
from ankora_backend.services import pose_rescoring as rescoring_module
from ankora_backend.services.methods_report import render_consensus_methods
from ankora_backend.services.pose_rescoring import PoseRescoringService
from ankora_backend.services.project_dependencies import ProjectDependencyService

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERIFIER_SCRIPT = _REPO_ROOT / "scripts" / "verify_export_bundle.py"

_SYNTHETIC_EPDB_DLG = (
    b"epdb: USER    Estimated Free Energy of Binding    =   -5.61 kcal/mol\n"
    b"epdb: USER    (1) Final Intermolecular Energy     =   -4.33 kcal/mol\n"
    b"epdb: USER    (2) Final Total Internal Energy     =   -2.47 kcal/mol\n"
    b"epdb: USER    (3) Torsional Free Energy           =   +1.19 kcal/mol\n"
    b"epdb: USER    (4) Unbound System's Energy         =   +0.00 kcal/mol\n"
    b"autodock4: Successful Completion\n"
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _seed_binary_free_cross_engine_project(root: Path) -> dict[str, Any]:
    """Seed receptor, sites, 2 Vina jobs, and synthetic AutoGrid4 map files without binaries."""
    receptors = ReceptorArtifactStore(root)
    sites = BindingSiteArtifactStore(root)
    ligands = LigandArtifactStore(root)
    docking = DockingArtifactStore(root)
    maps_store = AutoGridMapStore(root)
    now = datetime.now(UTC)

    prot_bytes = _SYNTHETIC_RECEPTOR_PDB.encode("utf-8")
    pdbqt_bytes = _SYNTHETIC_RECEPTOR_PDBQT.encode("utf-8")
    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    receptors.write_bytes(rec_id, "protonated.pdb", prot_bytes)
    receptors.write_bytes(rec_id, "receptor.pdbqt", pdbqt_bytes)
    prot_art_id = f"{rec_id}-prot"
    pdbqt_art_id = f"{rec_id}-pdbqt"
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
                protonation=ProtonationSettings(enabled=True, ph=7.4, force_field="AMBER"),
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

    lig1_id, job1_id, pose1_bytes = _create_ligand_and_vina_job(
        "ethanol", "CCO", site_id, 3.5, 7.5
    )
    lig2_id, job2_id, pose2_bytes = _create_ligand_and_vina_job(
        "propanol", "CCCO", site_id, 4.0, 8.0
    )
    _, job_mismatch_id, _ = _create_ligand_and_vina_job(
        "other_box_lig", "CCO", other_site_id, 3.5, 7.5
    )

    # Synthesize AutoGrid4 map set files without invoking autogrid4 binary
    ag_install = AutoGridInstallation(
        executable="synthetic-autogrid4",
        version="4.2.6",
        sha256="b" * 64,
        architecture="x86_64",
        max_receptor_types=20,
        max_ligand_types=14,
        max_maps=16,
        max_grid_points=1025,
    )
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
    (map_dir / "receptor.maps.fld").write_text(
        "# AVS field file (synthetic test fixture)\n", encoding="utf-8"
    )
    for ext in (*lig_types, "e", "d"):
        (map_dir / f"receptor.{ext}.map").write_text(
            f"GRID_PARAMETER_FILE receptor.gpf\n# synthetic {ext} map\n",
            encoding="utf-8",
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
                command=["synthetic-autogrid4", "-p", "receptor.gpf"],
                exit_code=0,
                stdout="Successful Completion",
                stderr="",
                duration_seconds=0.1,
                successful_completion_logged=True,
            ),
            artifacts=map_artifacts,
            provenance=ProvenanceEvent(
                event_id="evt-ag-d3",
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
        "map_dir": map_dir,
        "lig1_id": lig1_id,
        "lig2_id": lig2_id,
        "catalog1": f"vina_job:{job1_id}",
        "catalog2": f"vina_job:{job2_id}",
        "catalog_mismatch": f"vina_job:{job_mismatch_id}",
        "receptor_pdbqt": pdbqt_bytes,
        "pose1_bytes": pose1_bytes,
        "lig_types": lig_types,
    }


def _install_synthetic_rescoring_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[Any]]:
    """Stub ONLY external binaries (Vina + AutoDock4) so full orchestration runs in CI."""
    fake_vina = tmp_path / "synthetic-vina"
    fake_vina.write_bytes(b"synthetic-vina-binary")
    captured: dict[str, list[Any]] = {"dpf_texts": [], "vina_calls": []}

    monkeypatch.setattr(
        rescoring_module,
        "probe_vina",
        lambda: VinaInstallation(executable=str(fake_vina), version="1.2.7"),
    )
    monkeypatch.setattr(
        rescoring_module,
        "probe_autodock4",
        lambda: AutoDock4Installation(
            executable="synthetic-autodock4",
            version="4.2.6",
            sha256="c" * 64,
            architecture="x86_64",
            max_torsions=32,
            max_atoms=2048,
            max_maps=16,
        ),
    )

    def _fake_vina_score_only(**kwargs: Any) -> CancellableToolExecution:
        captured["vina_calls"].append(kwargs)
        scoring = kwargs.get("scoring", "vina")
        if scoring == "ad4":
            stdout = (
                "Estimated Free Energy of Binding   : -6.420 (kcal/mol) [=(1)+(2)+(3)-(4)]\n"
                "(1) Final Intermolecular Energy    : -7.020 (kcal/mol)\n"
                "(2) Final Total Internal Energy    : -0.500 (kcal/mol)\n"
                "(3) Torsional Free Energy          : 0.600 (kcal/mol)\n"
                "(4) Unbound System's Energy        : -0.500 (kcal/mol)\n"
            )
        else:
            val = -6.150 if scoring == "vinardo" else -6.850
            stdout = (
                f"Estimated Free Energy of Binding   : {val:.3f} (kcal/mol) [=(1)+(2)+(3)-(4)]\n"
                f"Affinity: {val:.3f} (kcal/mol)\n"
                "Intermolecular (1): -7.200\n"
                "Internal (2): -0.250\n"
                "Torsional (3): 0.350\n"
                "Unbound (4): -0.250\n"
            )
        return CancellableToolExecution(
            command=[str(fake_vina), "--scoring", str(scoring), "--score_only"],
            exit_code=0,
            stdout=stdout,
            stderr="",
            canceled=False,
            timed_out=False,
        )

    def _fake_autodock4_epdb(**kwargs: Any) -> CancellableToolExecution:
        job_dir = kwargs["job_directory"]
        assert isinstance(job_dir, Path)
        dpf_text = (job_dir / DOCKING_PARAMETER_FILENAME).read_text(encoding="utf-8")
        captured["dpf_texts"].append(dpf_text)
        (job_dir / DOCKING_LOG_FILENAME).write_bytes(_SYNTHETIC_EPDB_DLG)
        return CancellableToolExecution(
            command=["synthetic-autodock4", "-p", DOCKING_PARAMETER_FILENAME],
            exit_code=0,
            stdout="",
            stderr="",
            canceled=False,
            timed_out=False,
        )

    monkeypatch.setattr(rescoring_module, "execute_vina_score_only", _fake_vina_score_only)
    monkeypatch.setattr(rescoring_module, "execute_autodock4_cancellable", _fake_autodock4_epdb)
    return captured


def test_d3_001_campaign_consensus_e4_panel_reuse_stale_and_methods_binary_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3-001: Full Dual-OS CI coverage of POST /api/v1/consensus/runs/campaigns."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    _install_synthetic_rescoring_binaries(tmp_path, monkeypatch)
    seeded = _seed_binary_free_cross_engine_project(tmp_path)

    with TestClient(create_app()) as client:
        # 1. E4 fail-closed cross-box mismatch
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

        # 2. Cross-engine PC-Q Core + PC-ECR across Vina, Vinardo, and AutoDock4 epdb
        run_resp = client.post(
            "/api/v1/consensus/runs/campaigns",
            json={
                "name": "Synthetic Binary-Free Core Consensus",
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
        assert set(run.enabled_functions) == {
            ScoringFunctionId.VINA,
            ScoringFunctionId.VINARDO,
            ScoringFunctionId.AUTODOCK4,
        }
        for detail in run.parent_details:
            assert detail.tier == "full_profile"
            assert detail.retained_cluster_count == 2
            assert detail.pcq_score is not None and 0.0 <= detail.pcq_score <= 100.0
            assert detail.pc_ecr_score is not None and detail.pc_ecr_score > 0.0

        # 3. E1 Reference panel reuse
        reuse_resp = client.post(
            "/api/v1/consensus/runs/campaigns",
            json={
                "name": "Panel Reuse Consensus",
                "variant_id": "pcq-core-v1",
                "sources": [{"catalog_id": seeded["catalog1"]}],
                "autogrid_map_set_id": seeded["map_set_id"],
                "include_vinardo": True,
                "k_max": 2,
                "reference_panel_id": run.reference_panel.panel_id,
            },
        )
        assert reuse_resp.status_code == 201, reuse_resp.text
        reused = ConsensusRunRecord.model_validate(reuse_resp.json())
        assert reused.reference_panel.panel_id == run.reference_panel.panel_id
        assert (
            reused.reference_panel.reference_panel_sha256
            == run.reference_panel.reference_panel_sha256
        )

        # 4. Methods prose rendering
        methods_md = render_consensus_methods(run)
        assert "PC-Q" in methods_md
        assert "PC-ECR" in methods_md

        # 5. Stale input rejection via unmodified ProjectDependencyService
        ProjectDependencyService(root=tmp_path).mark_stale(
            seeded["site_id"], reason="Synthetic stale site for D3-001"
        )
        stale_resp = client.post(
            "/api/v1/consensus/runs/campaigns",
            json={
                "name": "Stale Consensus Blocked",
                "variant_id": "pcq-core-v1",
                "sources": [{"catalog_id": seeded["catalog1"]}],
                "autogrid_map_set_id": seeded["map_set_id"],
                "k_max": 2,
            },
        )
        assert stale_resp.status_code == 409
        assert stale_resp.json()["code"] == "PROJECT_INPUT_STALE"


def test_d3_002_pose_rescoring_autodock4_epdb_and_vina_ad4_maps_binary_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3-002: Exercise PoseRescoringService._run_autodock4_family (epdb & VINA_AD4_MAPS) in CI."""
    captured = _install_synthetic_rescoring_binaries(tmp_path, monkeypatch)
    seeded = _seed_binary_free_cross_engine_project(tmp_path)

    rigid_bytes: bytes = seeded["receptor_pdbqt"]
    pose_bytes: bytes = seeded["pose1_bytes"]
    rigid_sha = _sha(rigid_bytes)
    pose_sha = _sha(pose_bytes)
    box_sha = canonical_contract_sha256(_BOX)
    map_set = AutoGridMapStore(tmp_path).load_record(seeded["map_set_id"])
    map_set_sha = canonical_contract_sha256(map_set.identity_key)

    spec = ReceptorFlexSpec(mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=rigid_sha)
    pose_complex = PoseComplexIdentity(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=rigid_sha,
        ligand_pose_sha256=pose_sha,
    )
    context = PoseRescoreContext(
        receptor_flex_spec=spec,
        binding_box=_BOX,
        binding_box_sha256=box_sha,
        autogrid_map_set_sha256=map_set_sha,
        autogrid_map_receptor_sha256=rigid_sha,
        autogrid_map_prefix="receptor",
        autogrid_map_affinity_atom_types=tuple(seeded["lig_types"]),
    )
    service = PoseRescoringService()

    # 1. Canonical AutoDock4 epdb path (verifies DPF staging + bound_unbound (1)+(3) = -3.14)
    epdb_result = service.rescore_pose(
        request=PoseRescoreRequest(
            parent_compound_id="synth-ethanol",
            parent_state_id="synth-ethanol-s1",
            pose_complex=pose_complex,
            scoring_functions=(ScoringFunctionId.AUTODOCK4,),
            autodock4_backend=AutoDock4RescoreBackend.AUTODOCK4_EPDB,
        ),
        context=context,
        receptor_rigid_pdbqt=rigid_bytes,
        ligand_pose_pdbqt=pose_bytes,
        autogrid_maps_dir=seeded["map_dir"],
    )
    assert len(epdb_result.observations) == 1
    obs_epdb = epdb_result.observations[0]
    assert obs_epdb.status is ObservationStatus.SCORED
    assert obs_epdb.scoring_function is ScoringFunctionId.AUTODOCK4
    assert obs_epdb.raw_score == pytest.approx(-3.14)
    assert epdb_result.evidence[0].intermolecular_kcal_mol == pytest.approx(-4.33)
    assert epdb_result.evidence[0].total_internal_kcal_mol == pytest.approx(-2.47)
    assert epdb_result.evidence[0].torsional_free_energy_kcal_mol == pytest.approx(1.19)
    assert epdb_result.evidence[0].unbound_system_energy_kcal_mol == pytest.approx(0.0)
    assert len(captured["dpf_texts"]) == 1
    assert "epdb" in captured["dpf_texts"][0]
    assert "fld receptor.maps.fld" in captured["dpf_texts"][0]
    assert "map receptor.C.map" in captured["dpf_texts"][0]

    # 2. VINA_AD4_MAPS path (verifies scoring="ad4" + maps_prefix + exact score -6.420)
    vina_ad4_result = service.rescore_pose(
        request=PoseRescoreRequest(
            parent_compound_id="synth-ethanol",
            parent_state_id="synth-ethanol-s1",
            pose_complex=pose_complex,
            scoring_functions=(ScoringFunctionId.AUTODOCK4,),
            autodock4_backend=AutoDock4RescoreBackend.VINA_AD4_MAPS,
        ),
        context=context,
        receptor_rigid_pdbqt=rigid_bytes,
        ligand_pose_pdbqt=pose_bytes,
        autogrid_maps_dir=seeded["map_dir"],
    )
    assert len(vina_ad4_result.observations) == 1
    obs_ad4 = vina_ad4_result.observations[0]
    assert obs_ad4.status is ObservationStatus.SCORED
    assert obs_ad4.tool_name == "AutoDock Vina (ad4 maps)"
    assert obs_ad4.raw_score == pytest.approx(-6.420)
    assert captured["vina_calls"][-1]["scoring"] == "ad4"
    assert str(captured["vina_calls"][-1]["maps_prefix"]).endswith("receptor")


def test_d3_005_gnina_screening_http_prolif_complex_methods_and_export_binary_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3-005: Exercise real ProLIF, /complex, /methods, and /exports for gnina_screening in CI."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    Chem: Any = import_module("rdkit.Chem")
    AllChem: Any = import_module("rdkit.Chem.AllChem")
    Geometry: Any = import_module("rdkit.Geometry")

    # Build a synthetic FFF tripeptide receptor & place a synthetic phenol ligand 3.6 A from CB
    # so real ProLIF computes genuine Hydrophobic / VdW contacts deterministically.
    rec_mol = Chem.AddHs(Chem.MolFromSequence("FFF"))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261126
    assert AllChem.EmbedMolecule(rec_mol, params) == 0
    AllChem.MMFFOptimizeMolecule(rec_mol, maxIters=200)
    rec_conf = rec_mol.GetConformer()
    anchor_pos = rec_conf.GetAtomPosition(0)
    for atom in rec_mol.GetAtoms():
        info = atom.GetPDBResidueInfo()
        if info is not None and info.GetName().strip() == "CB":
            anchor_pos = rec_conf.GetAtomPosition(atom.GetIdx())
            break
    rec_pdb_bytes = Chem.MolToPDBBlock(rec_mol).encode("utf-8")

    # Build synthetic receptor PDBQT matching atom coords
    rec_pdbqt_lines = [
        line for line in rec_pdb_bytes.decode("utf-8").splitlines() if line.startswith("ATOM  ")
    ]
    rec_pdbqt_bytes = ("\n".join(rec_pdbqt_lines) + "\n").encode("utf-8")

    def _make_close_ligand(
        smiles: str, dx: float, *, min_aff: float, cnn_score: float, cnn_aff: float
    ) -> tuple[bytes, bytes]:
        meeko: Any = import_module("meeko")
        mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
        lp = AllChem.ETKDGv3()
        lp.randomSeed = 77
        assert AllChem.EmbedMolecule(mol, lp) == 0
        conf = mol.GetConformer()
        c0 = conf.GetAtomPosition(0)
        shift_x = (anchor_pos.x + dx) - c0.x
        shift_y = anchor_pos.y - c0.y
        shift_z = anchor_pos.z - c0.z
        for idx in range(mol.GetNumAtoms()):
            pos = conf.GetAtomPosition(idx)
            conf.SetAtomPosition(
                idx, Geometry.Point3D(pos.x + shift_x, pos.y + shift_y, pos.z + shift_z)
            )
        sdf_bytes = Chem.MolToMolBlock(mol).encode("utf-8") + b"\n$$$$\n"
        prep = meeko.MoleculePreparation()
        mol_setups = prep.prepare(mol)
        pdbqt_str, is_ok, err = meeko.PDBQTWriterLegacy.write_string(mol_setups[0])
        assert is_ok, err
        pdbqt_lines = [
            "MODEL 1",
            f"REMARK minimizedAffinity {min_aff:.3f}",
            f"REMARK CNNscore {cnn_score:.4f}",
            f"REMARK CNNaffinity {cnn_aff:.4f}",
            *pdbqt_str.strip().splitlines(),
            "ENDMDL",
        ]
        return sdf_bytes, ("\n".join(pdbqt_lines) + "\n").encode("utf-8")

    now = datetime.now(UTC)
    receptors = ReceptorArtifactStore(tmp_path)
    sites = BindingSiteArtifactStore(tmp_path)
    ligands = LigandArtifactStore(tmp_path)
    gnina_jobs = GninaJobStore(tmp_path)
    screenings = GninaScreeningStore(tmp_path)

    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    receptors.write_bytes(rec_id, "protonated.pdb", rec_pdb_bytes)
    receptors.write_bytes(rec_id, "receptor.pdbqt", rec_pdbqt_bytes)
    prot_id = f"{rec_id}-prot"
    pdbqt_id = f"{rec_id}-pdbqt"
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="src-synth-aaa",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True, ph=7.4, force_field="AMBER"),
                generate_pdbqt=True,
            ),
            outputs=[
                ReceptorOutputArtifact(
                    artifact_id=prot_id,
                    stage=ReceptorOutputStage.PROTONATED_PDB,
                    filename="protonated.pdb",
                    format="pdb",
                    sha256=_sha(rec_pdb_bytes),
                    size_bytes=len(rec_pdb_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{prot_id}/content",
                ),
                ReceptorOutputArtifact(
                    artifact_id=pdbqt_id,
                    stage=ReceptorOutputStage.PDBQT,
                    filename="receptor.pdbqt",
                    format="pdbqt",
                    sha256=_sha(rec_pdbqt_bytes),
                    size_bytes=len(rec_pdbqt_bytes),
                    created_at=now,
                    content_url=f"/receptors/{rec_id}/outputs/{pdbqt_id}/content",
                ),
            ],
            warnings=[],
            display_output_artifact_id=prot_id,
            provenance=[],
        )
    )
    box = BindingBox(
        center_x=round(anchor_pos.x, 2),
        center_y=round(anchor_pos.y, 2),
        center_z=round(anchor_pos.z, 2),
        size_x=20.0,
        size_y=20.0,
        size_z=20.0,
    )
    site_id = sites.new_binding_site_id()
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="src-synth-aaa",
            created_at=now,
            box=box,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
            warnings=[],
            provenance=[],
        )
    )

    from ankora_backend.schemas.ligands import ApplyLigandLibraryFilterRequest
    from ankora_backend.services.ligand_filtering import apply_library_filters
    from ankora_backend.services.ligand_import import import_local_ligand_library

    library = import_local_ligand_library(
        content=b"c1ccccc1O synth_phenol\nCCO synth_ethanol\n",
        filename="two_synth.smi",
        store=ligands,
    )
    filter_run = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=ligands,
    )

    campaign_id = screenings.new_campaign_id()
    tool_id = GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64")
    queued_entries: list[GninaScreeningEntry] = []
    entry_job_ids: list[str] = []
    first_ligand_id = ""
    first_pose_id = ""

    for idx, lid in enumerate(filter_run.selected_ligand_ids):
        ev = next(item for item in filter_run.evaluations if item.ligand_id == lid)
        smiles = "c1ccccc1O" if idx == 0 else "CCO"
        name = "synth_phenol" if idx == 0 else "synth_ethanol"
        cnn_score = 0.8750 if idx == 0 else 0.7200
        cnn_aff = 6.9500 if idx == 0 else 6.1000
        min_aff = -6.120 if idx == 0 else -5.400
        sdf_bytes, pose_bytes = _make_close_ligand(
            smiles,
            dx=3.6 + idx * 0.4,
            min_aff=min_aff,
            cnn_score=cnn_score,
            cnn_aff=cnn_aff,
        )
        lig_rec = ligands.load_record(lid)
        conf_id = ligands.new_conformer_id()
        ligands.create_conformer(
            lid,
            conf_id,
            sdf_bytes,
            LigandConformerRecord(
                artifact=LigandConformerArtifact(
                    conformer_id=conf_id,
                    ligand_id=lid,
                    chemical_state_id=ev.state_id,
                    stage="minimized",
                    filename=f"{name}.sdf",
                    format="sdf",
                    sha256=_sha(sdf_bytes),
                    size_bytes=len(sdf_bytes),
                    created_at=now,
                ),
                inspection=lig_rec.inspection,
                minimization=LigandMinimizationResult(
                    force_field=LigandForceField.MMFF94S,
                    max_iterations=200,
                    converged=True,
                    initial_energy_kcal_mol=1.0,
                    final_energy_kcal_mol=0.5,
                ),
                warnings=[],
                provenance=ProvenanceEvent(
                    event_id=f"evt-gconf-{idx}",
                    event_type="ligand_minimized",
                    timestamp=now,
                    tool=ToolIdentity(name="RDKit", version="2025.9.6"),
                ),
                content_url=f"/ligands/{lid}/conformers/{conf_id}/content",
            ),
        )
        prep_id = ligands.new_preparation_id()
        ligands.create_pdbqt(
            lid,
            prep_id,
            pose_bytes,
            LigandPdbqtRecord(
                artifact=LigandPdbqtArtifact(
                    preparation_id=prep_id,
                    ligand_id=lid,
                    conformer_id=conf_id,
                    filename=f"{name}.pdbqt",
                    format="pdbqt",
                    sha256=_sha(pose_bytes),
                    size_bytes=len(pose_bytes),
                    created_at=now,
                ),
                charge_model=LigandChargeModel.GASTEIGER,
                tool=ToolIdentity(name="Meeko", version="0.7.1"),
                command=["mk_prepare_ligand"],
                stdout="",
                stderr="",
                provenance=ProvenanceEvent(
                    event_id=f"evt-gprep-{idx}",
                    event_type="ligand_pdbqt_prepared",
                    timestamp=now,
                    tool=ToolIdentity(name="Meeko", version="0.7.1"),
                ),
                content_url=f"/ligands/{lid}/pdbqt/{prep_id}/content",
            ),
        )
        job_id = gnina_jobs.new_job_id()
        pose_art_id = f"{job_id}-pose-1"
        job_rec = GninaJobRecord(
            job_id=job_id,
            screening_campaign_id=campaign_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            completed_at=now,
            request=GninaDockingRequest(
                receptor_id=rec_id,
                binding_site_id=site_id,
                ligand_id=lid,
                ligand_preparation_id=prep_id,
                parameters=GninaDockingParameters(compute="cpu", cpu_threads=1),
                acknowledge_inputs_and_scoring=True,
            ),
            tool=tool_id,
            box=box,
            receptor_output_artifact_id=pdbqt_id,
            receptor_sha256=_sha(rec_pdbqt_bytes),
            ligand_sha256=_sha(pose_bytes),
            conformer_sha256=_sha(sdf_bytes),
            command=["gnina", "--no_gpu"],
            execution=GninaExecutionEvidence(
                command=["gnina", "--no_gpu"],
                exit_code=0,
                stdout="synthetic gnina stdout",
                stderr="",
            ),
            poses=[
                GninaPoseResult(
                    mode=1,
                    cnn_score=cnn_score,
                    cnn_affinity=cnn_aff,
                    minimized_affinity_kcal_mol=min_aff,
                    artifact=GninaPoseArtifact(
                        artifact_id=pose_art_id,
                        mode=1,
                        filename="pose_1.pdbqt",
                        sha256=_sha(pose_bytes),
                        size_bytes=len(pose_bytes),
                        content_url=f"/docking/gnina/jobs/{job_id}/poses/{pose_art_id}/content",
                    ),
                )
            ],
        )
        gnina_jobs.create_job(job_rec)
        gnina_jobs.write_artifact(job_id, "receptor.pdbqt", rec_pdbqt_bytes)
        gnina_jobs.write_artifact(job_id, "ligand.pdbqt", pose_bytes)
        gnina_jobs.write_artifact(job_id, "conformer.sdf", sdf_bytes)
        gnina_jobs.write_artifact(job_id, "raw_poses.pdbqt", pose_bytes)
        gnina_jobs.write_artifact(job_id, "pose_1.pdbqt", pose_bytes)
        gnina_jobs.write_artifact(job_id, "stdout.log", b"synthetic gnina stdout")
        gnina_jobs.write_artifact(job_id, "stderr.log", b"")
        if idx == 0:
            first_ligand_id = lid
            first_pose_id = pose_art_id
        ev = next(item for item in filter_run.evaluations if item.ligand_id == lid)
        entry_job_ids.append(job_id)
        queued_entries.append(
            GninaScreeningEntry(
                ligand_id=lid,
                chemical_state_id=ev.state_id or f"{lid}-s1",
                source_index=ev.record_index,
                name=name,
                ligand_preparation_id=prep_id,
                ligand_sha256=_sha(pose_bytes),
                conformer_id=conf_id,
                conformer_sha256=_sha(sdf_bytes),
                status=DockingJobStatus.QUEUED,
                phase=DockingJobPhase.QUEUED,
                gnina_job_id=None,
                revision=0,
            )
        )

    campaign = GninaScreeningCampaignRecord(
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=now,
        request=GninaScreeningRequest(
            receptor_id=rec_id,
            binding_site_id=site_id,
            library_id=library.artifact.library_id,
            filter_run_id=filter_run.artifact.filter_run_id,
            parameters=GninaDockingParameters(compute="cpu", cpu_threads=1),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=tool_id,
        selection=GninaScreeningSelection(
            library_id=library.artifact.library_id,
            filter_run_id=filter_run.artifact.filter_run_id,
            manifest_artifact_id=filter_run.artifact.filter_run_id,
            manifest_sha256=filter_run.artifact.sha256,
        ),
        box=box,
        receptor_output_artifact_id=pdbqt_id,
        receptor_sha256=_sha(rec_pdbqt_bytes),
        selected_count=2,
        completed_count=0,
        succeeded_count=0,
        failed_count=0,
        canceled_count=0,
        entries=queued_entries,
        revision=0,
    )
    screenings.create_campaign(campaign)
    for entry, job_id in zip(queued_entries, entry_job_ids, strict=True):
        running_entry = screenings.update_entry(
            campaign_id,
            entry.model_copy(
                update={
                    "status": DockingJobStatus.RUNNING,
                    "phase": DockingJobPhase.DOCKING,
                    "gnina_job_id": job_id,
                    "started_at": now,
                }
            ),
        )
        screenings.update_entry(
            campaign_id,
            running_entry.model_copy(
                update={
                    "status": DockingJobStatus.COMPLETED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": now,
                }
            ),
        )
    screenings.finalize_campaign(campaign_id)

    with TestClient(create_app()) as client:
        # 1. Real ProLIF interaction analysis over gnina_screening HTTP endpoint
        inter_resp = client.post(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds/"
            f"{first_ligand_id}/poses/{first_pose_id}/interactions",
            json={},
        )
        assert inter_resp.status_code == 201, inter_resp.text
        inter = inter_resp.json()
        assert inter["detector"]["name"] == "ProLIF"
        assert len(inter["ligand_diagram"]["atoms"]) > 0
        assert len(inter["contacts"]) > 0

        # 2. Complex PDB endpoint
        complex_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/compounds/"
            f"{first_ligand_id}/poses/{first_pose_id}/complex"
        )
        assert complex_resp.status_code == 200, complex_resp.text
        assert f"REMARK   1 RESULT          gnina_screening:{campaign_id}" in complex_resp.text
        assert "REMARK   1 POSE CNN SCORE  0.8750 (dimensionless)" in complex_resp.text

        # 3. Methods report HTTP endpoint
        methods_resp = client.get(
            f"/api/v1/results/campaigns/gnina_screening/{campaign_id}/methods"
        )
        assert methods_resp.status_code == 200, methods_resp.text
        methods = methods_resp.json()
        assert "GNINA" in methods["markdown"]
        assert "0.8750" in methods["markdown"] or "CNN" in methods["markdown"]

        # 4. Campaign export ZIP HTTP endpoint + offline verifier
        export_resp = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_screening", "source_id": campaign_id},
        )
        assert export_resp.status_code == 201, export_resp.text
        receipt = export_resp.json()
        bundle_zip = Path(receipt["record_directory"]) / receipt["archive_filename"]
        assert bundle_zip.is_file()

        spec_mod = importlib.util.spec_from_file_location("verify_d3005", _VERIFIER_SCRIPT)
        assert spec_mod is not None and spec_mod.loader is not None
        verifier = importlib.util.module_from_spec(spec_mod)
        sys.modules["verify_d3005"] = verifier
        spec_mod.loader.exec_module(verifier)
        report = verifier.verify_bundle(bundle_zip, require_core_hashes=True)
        assert report["verified"] is True, report
