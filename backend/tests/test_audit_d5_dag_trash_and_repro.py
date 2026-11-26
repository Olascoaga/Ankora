"""Regression tests for D5 Unit 2: Stale DAG completeness, corrupt-node fail-closed,
v0.2 trash cascade, downstream require_current() admission guards, and FlexRes reproducibility.

All records, scores, and digests in this module are explicitly labelled synthetic fixtures.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.consensus_store import ConsensusArtifactStore
from ankora_backend.persistence.interaction_rules_store import (
    InteractionRuleEvaluationStore,
    InteractionRuleSetStore,
)
from ankora_backend.persistence.pose_interaction_store import PoseInteractionStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.calibration import CalibrationCompoundInput, CalibrationSplitPolicy
from ankora_backend.schemas.consensus import (
    ConsensusParentInput,
    ConsensusPoseScoreInput,
    ConsensusVariantId,
    CreateStructuredConsensusRequest,
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
from ankora_backend.schemas.interaction_rules import (
    CreateInteractionRuleSetRequest,
    InteractionRuleClause,
    InteractionRuleKind,
    InteractionTarget,
)
from ankora_backend.schemas.projects import DependencyNodeKind
from ankora_backend.schemas.provenance import ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec, ResidueLocator
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    ReproducibilityStatus,
    ResultMode,
    ScoringFamily,
    TrashResultCampaignsRequest,
)
from ankora_backend.schemas.v02_contracts import PoseComplexIdentity, ScoringFunctionId
from ankora_backend.services.interaction_rules import InteractionRulesService
from ankora_backend.services.pose_consensus import PoseConsensusService
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.protocol_calibration import ProtocolCalibrationService
from ankora_backend.services.reproducibility import ReproducibilityService
from ankora_backend.services.result_deletion import ResultDeletionService


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sha(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def test_d5_002_stale_dag_propagates_across_v02_list_and_refinement_links(tmp_path: Path) -> None:
    """D5-002: Stale marking propagates to consensus (list source_catalog_ids),
    refinements (parent_job_id), GNINA child jobs (screening_campaign_id),
    rule sets (source_catalog_id), and classifies calibrations as CALIBRATION."""
    proj = tmp_path / "projects" / "default"
    batch_id = str(uuid4())
    cons_id = str(uuid4())
    ref_id = str(uuid4())
    gnina_camp_id = str(uuid4())
    gnina_child_id = str(uuid4())
    rule_set_id = str(uuid4())
    cal_id = str(uuid4())

    _write_json(proj / "results" / "docking_batches" / batch_id / "record.json", {"id": batch_id})
    _write_json(
        proj / "analysis" / "consensus" / cons_id / "record.json",
        {"consensus_id": cons_id, "source_catalog_ids": [f"vina_batch:{batch_id}"]},
    )
    _write_json(
        proj / "results" / "docking_refinements" / ref_id / "record.json",
        {"refinement_id": ref_id, "parent_job_id": batch_id},
    )
    _write_json(
        proj / "results" / "gnina_screening_campaigns" / gnina_camp_id / "record.json",
        {"campaign_id": gnina_camp_id},
    )
    _write_json(
        proj / "results" / "gnina_jobs" / gnina_child_id / "record.json",
        {"job_id": gnina_child_id, "screening_campaign_id": gnina_camp_id},
    )
    _write_json(
        proj / "analysis" / "interaction_rule_sets" / rule_set_id / "record.json",
        {
            "rule_set_id": rule_set_id,
            "reference_ifp": {"source_catalog_id": f"vina_batch:{batch_id}"},
        },
    )
    _write_json(
        proj / "calibrations" / cal_id / "record.json",
        {"calibration_id": cal_id, "receptor_id": batch_id},
    )

    deps = ProjectDependencyService(root=tmp_path, project_id="default")
    deps.mark_stale(batch_id, "upstream batch superseded")
    deps.mark_stale(gnina_camp_id, "gnina screening superseded")

    graph = deps.graph(limit=100)
    by_id = {node.node_id: node for node in graph.nodes}
    assert by_id[cons_id].stale is True
    assert batch_id in by_id[cons_id].parent_ids
    assert by_id[ref_id].stale is True
    assert by_id[gnina_child_id].stale is True
    assert by_id[rule_set_id].stale is True
    assert by_id[cal_id].kind is DependencyNodeKind.CALIBRATION
    assert by_id[cal_id].stale is True

    with pytest.raises(AnkoraDomainError) as exc_info:
        deps.require_current([cons_id, ref_id, gnina_child_id, rule_set_id, cal_id])
    assert exc_info.value.code == "PROJECT_INPUT_STALE"
    assert exc_info.value.status_code == 409


def test_d5_016_corrupted_intermediate_record_propagates_stale_fail_closed(tmp_path: Path) -> None:
    """D5-016: Corrupted intermediate record.json stays in the graph as stale and
    propagates staleness to downstream artifacts instead of silently severing the DAG."""
    proj = tmp_path / "projects" / "default"
    rec_id = str(uuid4())
    site_id = str(uuid4())

    rec_path = proj / "derived" / "receptors" / rec_id / "record.json"
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text("{corrupt json", encoding="utf-8")
    _write_json(
        proj / "derived" / "binding_sites" / site_id / "record.json",
        {"binding_site_id": site_id, "receptor_id": rec_id},
    )

    deps = ProjectDependencyService(root=tmp_path, project_id="default")
    graph = deps.graph(limit=50)
    by_id = {node.node_id: node for node in graph.nodes}
    assert rec_id in by_id
    assert by_id[rec_id].stale is True
    assert by_id[site_id].stale is True
    assert rec_id in by_id[site_id].parent_ids

    with pytest.raises(AnkoraDomainError) as exc_info:
        deps.require_current([site_id])
    assert exc_info.value.code == "PROJECT_INPUT_STALE"


def test_d5_006_result_trash_cascades_v02_dependents_and_marks_shared_consensus_stale(
    tmp_path: Path,
) -> None:
    """D5-006: Trashing a campaign moves pose_quality, interaction_rule_evaluations,
    docking_refinements, analog_searches, and single-source consensus runs into Trash,
    while marking multi-source consensus runs stale instead of leaving live orphans."""
    proj = tmp_path / "projects" / "default"
    batch_id = str(uuid4())
    other_batch_id = str(uuid4())
    catalog_id = f"vina_batch:{batch_id}"
    other_catalog_id = f"autodock4_batch:{other_batch_id}"

    pq_id = str(uuid4())
    eval_id = str(uuid4())
    ref_id = str(uuid4())
    search_id = str(uuid4())
    single_cons_id = str(uuid4())
    shared_cons_id = str(uuid4())

    _write_json(proj / "results" / "docking_batches" / batch_id / "record.json", {"id": batch_id})
    _write_json(
        proj / "results" / "autodock4_batches" / other_batch_id / "record.json",
        {"id": other_batch_id},
    )
    _write_json(
        proj / "analysis" / "pose_quality" / pq_id / "record.json",
        {"assessment_id": pq_id, "catalog_id": catalog_id},
    )
    _write_json(
        proj / "analysis" / "interaction_rule_evaluations" / eval_id / "record.json",
        {"evaluation_id": eval_id, "catalog_id": catalog_id},
    )
    _write_json(
        proj / "results" / "docking_refinements" / ref_id / "record.json",
        {"refinement_id": ref_id, "parent_job_id": batch_id},
    )
    _write_json(
        proj / "derived" / "analog_expansion" / "searches" / search_id / "record.json",
        {"search_id": search_id, "seed": {"source_catalog_id": catalog_id}},
    )
    _write_json(
        proj / "analysis" / "consensus" / single_cons_id / "record.json",
        {"consensus_id": single_cons_id, "source_catalog_ids": [catalog_id]},
    )
    _write_json(
        proj / "analysis" / "consensus" / shared_cons_id / "record.json",
        {"consensus_id": shared_cons_id, "source_catalog_ids": [catalog_id, other_catalog_id]},
    )

    entry = CatalogEntry(
        catalog_id=catalog_id,
        engine_key="vina_batch",
        record_id=batch_id,
        mode=ResultMode.SCREENING,
        scoring_family=ScoringFamily.VINA,
        engine_label="AutoDock Vina 1.2.7",
        engine_version="1.2.7",
        status="completed",
        created_at=datetime(2026, 11, 26, 18, 0, tzinfo=UTC),
        receptor_id=str(uuid4()),
        binding_site_id=str(uuid4()),
        selected_count=1,
        succeeded_count=1,
        failed_count=0,
        canceled_count=0,
    )
    svc = ResultDeletionService(
        root=tmp_path,
        catalog=SimpleNamespace(get_campaign=lambda cid: entry),  # type: ignore[arg-type]
    )
    resp = svc.trash(
        TrashResultCampaignsRequest(catalog_ids=[catalog_id], acknowledge_removal=True)
    )
    assert resp.recoverable is True

    # Single-campaign derivatives were moved atomically into Trash (0 live orphans):
    assert not (proj / "results" / "docking_batches" / batch_id).exists()
    assert not (proj / "analysis" / "pose_quality" / pq_id).exists()
    assert not (proj / "analysis" / "interaction_rule_evaluations" / eval_id).exists()
    assert not (proj / "results" / "docking_refinements" / ref_id).exists()
    assert not (proj / "derived" / "analog_expansion" / "searches" / search_id).exists()
    assert not (proj / "analysis" / "consensus" / single_cons_id).exists()

    # Multi-source consensus remains intact on disk AND is marked stale (ADR-011):
    assert (proj / "analysis" / "consensus" / shared_cons_id / "record.json").is_file()
    deps = ProjectDependencyService(root=tmp_path, project_id="default")
    freshness = deps.freshness_for([shared_cons_id])
    assert freshness.stale is True
    assert any("Trash" in r for r in freshness.stale_reasons)


def test_d5_008_downstream_services_reject_stale_inputs_409(tmp_path: Path) -> None:
    """D5-008: ProtocolCalibration, PoseConsensus, and InteractionRules all enforce
    ProjectDependencyService.require_current() and reject stale inputs with HTTP 409."""
    proj = tmp_path / "projects" / "default"
    rec_id = str(uuid4())
    site_id = str(uuid4())
    _write_json(proj / "derived" / "receptors" / rec_id / "record.json", {"receptor_id": rec_id})
    _write_json(
        proj / "derived" / "binding_sites" / site_id / "record.json",
        {"binding_site_id": site_id, "receptor_id": rec_id},
    )
    ProjectDependencyService(root=tmp_path, project_id="default").mark_stale(
        rec_id, "receptor protonation revised"
    )

    # 1. ProtocolCalibrationService.create_split rejects stale receptor/site
    cal_svc = ProtocolCalibrationService(CalibrationArtifactStore.for_project_root(proj))
    compounds = [
        CalibrationCompoundInput(
            parent_id=f"c{i}", canonical_smiles=f"c1ccccc1{'C' * i}", is_active=(i < 4)
        )
        for i in range(1, 13)
    ]
    with pytest.raises(AnkoraDomainError) as cal_err:
        cal_svc.create_split(
            project_id="default",
            receptor_id=rec_id,
            binding_site_id=site_id,
            compounds=compounds,
            policy=CalibrationSplitPolicy(bootstrap_replicates=100, min_confirmation_actives=2),
        )
    assert cal_err.value.code == "PROJECT_INPUT_STALE"
    assert cal_err.value.status_code == 409

    # 2. PoseConsensusService.create_structured_consensus rejects stale receptor/site
    rec_sha = _sha("rec-rigid")
    cons_svc = PoseConsensusService(
        store=ConsensusArtifactStore(root=tmp_path, project_id="default"),
        catalog=SimpleNamespace(),  # type: ignore[arg-type]
        interactions=SimpleNamespace(),  # type: ignore[arg-type]
        rescoring=SimpleNamespace(),  # type: ignore[arg-type]
        receptors=SimpleNamespace(),  # type: ignore[arg-type]
        binding_sites=SimpleNamespace(),  # type: ignore[arg-type]
        maps=SimpleNamespace(),  # type: ignore[arg-type]
        ligands=SimpleNamespace(),  # type: ignore[arg-type]
        calibrations=CalibrationArtifactStore.for_project_root(proj),
    )
    with pytest.raises(AnkoraDomainError) as cons_err:
        cons_svc.create_structured_consensus(
            CreateStructuredConsensusRequest(
                name="Stale Consensus Attempt",
                variant_id=ConsensusVariantId.PCQ_CORE_V1,
                receptor_id=rec_id,
                binding_site_id=site_id,
                receptor_flex_spec=ReceptorFlexSpec(
                    mode=ReceptorFlexMode.RIGID, receptor_rigid_sha256=rec_sha
                ),
                binding_box_sha256=_sha("box"),
                autogrid_map_set_sha256=_sha("maps"),
                enabled_functions=(ScoringFunctionId.VINA, ScoringFunctionId.AUTODOCK4),
                k_max=2,
                search_engine_count=2,
                parents=(
                    ConsensusParentInput(
                        parent_compound_id="p1",
                        parent_state_id="p1-s1",
                        medoids=(
                            ConsensusPoseScoreInput(
                                cluster_id="cl-1",
                                medoid_pose_id="pose-1",
                                pose_complex=PoseComplexIdentity(
                                    mode=ReceptorFlexMode.RIGID,
                                    receptor_rigid_sha256=rec_sha,
                                    ligand_pose_sha256=_sha("lig-1"),
                                ),
                                canonical_coordinate_sha256=_sha("coord-1"),
                                search_engines_present=("vina", "autodock4"),
                                scores_by_function={
                                    ScoringFunctionId.VINA: -8.0,
                                    ScoringFunctionId.AUTODOCK4: -7.5,
                                },
                            ),
                        ),
                    ),
                ),
            )
        )
    assert cons_err.value.code == "PROJECT_INPUT_STALE"
    assert cons_err.value.status_code == 409

    # 3. InteractionRulesService.create_rule_set rejects stale receptor
    rules_svc = InteractionRulesService(
        receptor_store=ReceptorArtifactStore(root=tmp_path, project_id="default"),
        interaction_service=SimpleNamespace(),  # type: ignore[arg-type]
        interaction_store=PoseInteractionStore(root=tmp_path, project_id="default"),
        rule_set_store=InteractionRuleSetStore(root=tmp_path, project_id="default"),
        evaluation_store=InteractionRuleEvaluationStore(root=tmp_path, project_id="default"),
    )
    with pytest.raises(AnkoraDomainError) as rules_err:
        rules_svc.create_rule_set(
            CreateInteractionRuleSetRequest(
                name="Stale Receptor RuleSet",
                receptor_id=rec_id,
                clauses=(
                    InteractionRuleClause(
                        clause_id="c1",
                        label="HBond",
                        kind=InteractionRuleKind.REQUIRED,
                        targets=(
                            InteractionTarget(
                                residue=ResidueLocator(
                                    chain_id="A", sequence_number=100, residue_name="ASP"
                                ),
                                interaction_types=("HBDonor",),
                            ),
                        ),
                    ),
                ),
            )
        )
    assert rules_err.value.code == "PROJECT_INPUT_STALE"
    assert rules_err.value.status_code == 409


def test_d5_015_reproducibility_detects_divergent_flex_sidechains() -> None:
    """D5-015: Two sidechain_flex Vina jobs with identical ligand poses but distinct
    pose_flex_sidechains_sha256 MUST be classified MEASURED_VARIABLE."""
    now = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)
    req = VinaDockingRequest(
        receptor_id="rec-1",
        binding_site_id="site-1",
        ligand_id="lig-1",
        ligand_preparation_id="prep-1",
        parameters=VinaDockingParameters(exhaustiveness=8, num_modes=1, seed=42),
        acknowledge_inputs_and_scoring=True,
    )

    def _flex_job(job_id: str, flex_pose_sha: str) -> VinaDockingJobRecord:
        return VinaDockingJobRecord(
            job_id=job_id,
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
            created_at=now,
            started_at=now,
            completed_at=now,
            request=req,
            tool=ToolIdentity(name="AutoDock Vina", version="1.2.7"),
            receptor_output_artifact_id="rec-out-1",
            receptor_sha256="a" * 64,
            receptor_flex_mode=ReceptorFlexMode.SIDECHAIN_FLEX,
            receptor_flex_output_artifact_id="rec-flex-1",
            receptor_flex_sha256="b" * 64,
            ligand_sha256="c" * 64,
            poses=[
                DockingPoseResult(
                    mode=1,
                    affinity_kcal_mol=-8.4,
                    rmsd_lower_bound_angstrom=0.0,
                    rmsd_upper_bound_angstrom=0.0,
                    artifact=DockingPoseArtifact(
                        artifact_id=f"pose-{job_id}",
                        mode=1,
                        filename="pose_1.pdbqt",
                        format="pdbqt",
                        sha256="d" * 64,
                        size_bytes=512,
                        content_url=f"/jobs/{job_id}/poses/1",
                        flex_filename="pose_1_flex.pdbqt",
                        pose_flex_sidechains_sha256=flex_pose_sha,
                        flex_content_url=f"/jobs/{job_id}/poses/1/flex",
                        pose_complex_identity_sha256=_sha(f"complex-{flex_pose_sha}"),
                    ),
                )
            ],
        )

    job1 = _flex_job("job-flex-1", "1" * 64)
    job2 = _flex_job("job-flex-2", "2" * 64)
    empty = SimpleNamespace(list_batches=lambda: [], list_jobs=lambda: [])
    docking_stub = SimpleNamespace(list_batch_records=lambda: [], list_jobs=lambda: [job1, job2])

    repro = ReproducibilityService(
        docking_store=docking_stub, autodock4_store=empty, autodock_gpu_store=empty
    )
    assessments = repro.all_assessments()
    a1 = assessments["vina_job:job-flex-1"]
    a2 = assessments["vina_job:job-flex-2"]
    assert a1.status is ReproducibilityStatus.MEASURED_VARIABLE
    assert a2.status is ReproducibilityStatus.MEASURED_VARIABLE
    assert len({e.output_fingerprint_sha256 for e in a1.executions}) == 2
