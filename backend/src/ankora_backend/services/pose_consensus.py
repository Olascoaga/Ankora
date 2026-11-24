"""Create-only ADR-030 consensus prioritization service (`PC-Q`, `PC-ECR`, gated `PC-L2`).

Orchestrates:
1. Fail-closed `E4` shared receptor / flex-spec / binding-box / AutoGrid4-map verification.
2. Per-parent complete-linkage joint `(ligand, flex)` clustering (`E2`/`E3`/`E8`).
3. Live same-geometry `--score_only` cross-evaluation on each retained medoid via
   `PoseRescoringService` (never mutating parent pose bytes).
4. Immutable hash-locked `ReferencePanelArtifact` creation or reuse (`E1`).
5. Pose-First, Molecule-Second `PC-Q` (`pcq-core-v1` / `pcq-neural-v1`), `D_ic`,
   separate-scale `PC-ECR` (`tau = 0.05`, `E5`), two-tier `RankingArtifact` (`E6`),
   and create-only Confirmation-gated `PC-L2` derivatives (`ADR-030 §3`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from ankora_backend import __version__
from ankora_backend.adapters.chemistry.pose_clustering import (
    ClusterCandidatePose,
    ParentClusteringResult,
    cluster_parent_pose_complexes,
)
from ankora_backend.adapters.chemistry.redocking_rmsd import load_reference
from ankora_backend.adapters.consensus.pcq_math import (
    build_reference_panel,
    compute_pcq_and_ecr_consensus,
    fit_and_gate_pc_l2,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.persistence.consensus_store import ConsensusArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autogrid import AutoGridMapKind
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.consensus import (
    FROZEN_ECR_TAU,
    ConsensusParentInput,
    ConsensusPoseScoreInput,
    ConsensusRunRecord,
    ConsensusVariantId,
    CreateCampaignConsensusRequest,
    CreateStructuredConsensusRequest,
    FitPcL2Request,
    PoseClusterSummary,
    ReferencePanelArtifact,
    SourceEngine,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec
from ankora_backend.schemas.rescoring import PoseRescoreContext, PoseRescoreRequest
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    PoseComplexIdentity,
    ScoringFunctionId,
    canonical_contract_sha256,
)
from ankora_backend.services.pose_interactions import PoseInteractionService
from ankora_backend.services.pose_rescoring import PoseRescoringService
from ankora_backend.services.result_catalog import (
    AUTODOCK4_BATCH,
    AUTODOCK4_JOB,
    AUTODOCK_GPU_BATCH,
    AUTODOCK_GPU_JOB,
    GNINA_JOB,
    GNINA_SCREENING,
    VINA_BATCH,
    VINA_JOB,
    ResultCatalogService,
)

_STAGE = "pose_consensus"
_TOOL = ToolIdentity(name="ankora-pcq-consensus", version=__version__)

_ENGINE_KEY_TO_SOURCE: dict[str, SourceEngine] = {
    VINA_JOB: "vina",
    VINA_BATCH: "vina",
    AUTODOCK4_JOB: "autodock4",
    AUTODOCK4_BATCH: "autodock4",
    AUTODOCK_GPU_JOB: "autodock_gpu",
    AUTODOCK_GPU_BATCH: "autodock_gpu",
    GNINA_JOB: "gnina",
    GNINA_SCREENING: "gnina",
}


class PoseConsensusService:
    """Manage immutable ADR-030 consensus runs and hash-locked reference panels."""

    def __init__(
        self,
        *,
        store: ConsensusArtifactStore,
        catalog: ResultCatalogService,
        interactions: PoseInteractionService,
        rescoring: PoseRescoringService,
        receptors: ReceptorArtifactStore,
        binding_sites: BindingSiteArtifactStore,
        maps: AutoGridMapStore,
        ligands: LigandArtifactStore,
        calibrations: CalibrationArtifactStore,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._interactions = interactions
        self._rescoring = rescoring
        self._receptors = receptors
        self._binding_sites = binding_sites
        self._maps = maps
        self._ligands = ligands
        self._calibrations = calibrations

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> PoseConsensusService:
        return cls(
            store=ConsensusArtifactStore.from_environment(project_id=project_id),
            catalog=ResultCatalogService.from_environment(),
            interactions=PoseInteractionService.from_environment(),
            rescoring=PoseRescoringService.from_environment(),
            receptors=ReceptorArtifactStore.from_environment(),
            binding_sites=BindingSiteArtifactStore.from_environment(),
            maps=AutoGridMapStore.from_environment(),
            ligands=LigandArtifactStore.from_environment(),
            calibrations=CalibrationArtifactStore.from_environment(),
        )

    def list_runs(self) -> list[ConsensusRunRecord]:
        return self._store.list_runs()

    def get_run(self, consensus_id: str) -> ConsensusRunRecord:
        return self._store.load_run(consensus_id)

    def list_panels(self) -> list[ReferencePanelArtifact]:
        return self._store.list_panels()

    def get_panel(self, panel_id: str) -> ReferencePanelArtifact:
        return self._store.load_panel(panel_id)

    def create_structured_consensus(
        self,
        request: CreateStructuredConsensusRequest,
        *,
        source_catalog_ids: Sequence[str] = (),
    ) -> ConsensusRunRecord:
        """Compute & persist immutable PC-Q + PC-ECR over verified pose-first observations."""
        if request.reference_panel_id is not None:
            panel = self._store.load_panel(request.reference_panel_id)
            self._verify_reused_panel_context(
                panel=panel,
                receptor_id=request.receptor_id,
                receptor_flex_spec=request.receptor_flex_spec,
                binding_box_sha256=request.binding_box_sha256,
                autogrid_map_set_sha256=request.autogrid_map_set_sha256,
                enabled_functions=request.enabled_functions,
                k_max=request.k_max,
                executable_sha256s=request.executable_sha256s,
            )
            created_new_panel = False
        else:
            panel = build_reference_panel(
                receptor_id=request.receptor_id,
                binding_site_id=request.binding_site_id,
                receptor_flex_spec=request.receptor_flex_spec,
                binding_box_sha256=request.binding_box_sha256,
                autogrid_map_set_sha256=request.autogrid_map_set_sha256,
                enabled_functions=request.enabled_functions,
                k_max=request.k_max,
                parents=request.parents,
                tool_identities=request.tool_identities,
                executable_sha256s=request.executable_sha256s,
                panel_id=self._store.new_panel_id(),
            )
            self._store.create_panel(panel)
            created_new_panel = True

        computed = compute_pcq_and_ecr_consensus(
            variant_id=request.variant_id,
            enabled_functions=request.enabled_functions,
            reference_panel=panel,
            parents=request.parents,
            search_engine_count=request.search_engine_count,
        )

        created_at = datetime.now(UTC)
        consensus_id = self._store.new_consensus_id()
        input_artifacts = [
            request.receptor_id,
            request.binding_site_id,
            panel.panel_id,
            *source_catalog_ids,
        ]
        provenance = ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="consensus_prioritization_computed",
            timestamp=created_at,
            input_artifacts=list(dict.fromkeys(input_artifacts)),
            output_artifacts=[consensus_id],
            tool=_TOOL,
            parameters={
                "variant_id": request.variant_id.value,
                "k_max": request.k_max,
                "rmsd_threshold_angstrom": request.rmsd_threshold_angstrom,
                "ecr_tau": FROZEN_ECR_TAU,
                "reference_panel_id": panel.panel_id,
                "reference_panel_sha256": panel.reference_panel_sha256,
                "created_new_panel": created_new_panel,
                "frozen_panel_parent_count": panel.total_panel_parents,
                "scored_target_parent_count": len(request.parents),
                "enabled_functions": [fn.value for fn in request.enabled_functions],
                "source_catalog_ids": list(source_catalog_ids),
            },
            warnings=list(computed.warnings),
        )
        record = ConsensusRunRecord(
            consensus_id=consensus_id,
            created_at=created_at,
            name=request.name,
            variant_id=request.variant_id,
            k_max=request.k_max,
            rmsd_threshold_angstrom=request.rmsd_threshold_angstrom,
            ecr_tau=FROZEN_ECR_TAU,
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            receptor_flex_spec=request.receptor_flex_spec,
            binding_box_sha256=request.binding_box_sha256,
            autogrid_map_set_sha256=request.autogrid_map_set_sha256,
            source_catalog_ids=tuple(source_catalog_ids),
            enabled_functions=request.enabled_functions,
            block_weights=computed.block_weights,
            within_block_weights=computed.within_block_weights,
            reference_panel=panel,
            ranking=computed.ranking,
            core_ranking=computed.core_ranking,
            ecr_ranking=computed.ecr_ranking,
            parent_details=computed.parent_details,
            warnings=computed.warnings,
            provenance=provenance,
        )
        self._store.create_run(record)
        return record

    def create_campaign_consensus(
        self, request: CreateCampaignConsensusRequest
    ) -> ConsensusRunRecord:
        """End-to-end Pose-First consensus directly across saved Ankora campaign(s) / job(s)."""
        source_catalog_ids = tuple(dict.fromkeys(src.catalog_id for src in request.sources))
        enabled_functions = _enabled_functions_for_campaign_request(request)

        # 1. Load catalog entries and enforce E4 shared receptor + binding box across all sources.
        entries = [self._catalog.get_campaign(cid) for cid in source_catalog_ids]
        receptor_ids = {entry.receptor_id for entry in entries}
        if len(receptor_ids) != 1:
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "All source campaigns must share the exact same prepared receptor.",
                receptor_ids=sorted(receptor_ids),
            )
        receptor_id = next(iter(receptor_ids))

        boxes: list[BindingBox] = []
        box_hashes: set[str] = set()
        for entry in entries:
            site = self._binding_sites.load_record(entry.binding_site_id)
            boxes.append(site.box)
            box_hashes.add(canonical_contract_sha256(site.box))
        if len(box_hashes) != 1:
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "All source campaigns must share the exact same canonical binding box.",
                binding_box_sha256s=sorted(box_hashes),
            )
        shared_box = boxes[0]
        shared_box_sha256 = next(iter(box_hashes))
        primary_binding_site_id = entries[0].binding_site_id

        # 2. Verify receptor and AutoGrid4 map set binding (E4 + E7).
        receptor_record = self._receptors.load_record(receptor_id)
        try:
            map_set = self._maps.load_record(request.autogrid_map_set_id)
        except AnkoraDomainError:
            grid_job = self._maps.load_job(request.autogrid_map_set_id)
            if grid_job.map_set_id is None:
                raise _consensus_error(
                    "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                    "The referenced AutoGrid4 job has not produced a completed map set.",
                ) from None
            map_set = self._maps.load_record(grid_job.map_set_id)
        if map_set.receptor_id != receptor_id:
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "The supplied AutoGrid4 map set belongs to a different receptor.",
                map_receptor_id=map_set.receptor_id,
                source_receptor_id=receptor_id,
            )
        map_site = self._binding_sites.load_record(map_set.binding_site_id)
        map_box_sha = canonical_contract_sha256(map_site.box)
        if map_box_sha != shared_box_sha256:
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "The supplied AutoGrid4 map set binding box differs from the campaign box.",
                map_box_sha256=map_box_sha,
                campaign_box_sha256=shared_box_sha256,
            )
        fld_art = next(
            (art for art in map_set.artifacts if art.kind is AutoGridMapKind.FIELD),
            None,
        )
        if fld_art is None or not fld_art.filename.endswith(".maps.fld"):
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "The AutoGrid4 map set has no valid .maps.fld artifact.",
            )
        map_prefix = fld_art.filename.removesuffix(".maps.fld")
        map_set_sha256 = map_set.identity_key
        maps_dir = self._maps.map_set_directory(map_set.map_set_id)

        receptor_flex_spec = receptor_record.flex_spec
        if receptor_flex_spec is None:
            rigid_output = next(
                (out for out in receptor_record.outputs if out.stage.value == "pdbqt"),
                None,
            )
            if rigid_output is None:
                raise _consensus_error(
                    "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                    "Prepared receptor has no rigid PDBQT artifact for consensus rescoring.",
                )
            receptor_rigid_path = self._receptors.content_path(
                receptor_id, rigid_output.artifact_id
            )
            receptor_rigid_bytes = receptor_rigid_path.read_bytes()
            receptor_flex_spec = ReceptorFlexSpec(
                mode=ReceptorFlexMode.RIGID,
                receptor_rigid_sha256=sha256(receptor_rigid_bytes).hexdigest(),
            )
        else:
            rigid_stage = (
                "pdbqt_rigid"
                if receptor_flex_spec.mode is ReceptorFlexMode.SIDECHAIN_FLEX
                else "pdbqt"
            )
            rigid_output = next(
                (out for out in receptor_record.outputs if out.stage.value == rigid_stage),
                None,
            )
            if rigid_output is None:
                raise _consensus_error(
                    "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                    f"Prepared receptor has no '{rigid_stage}' artifact for consensus rescoring.",
                )
            receptor_rigid_path = self._receptors.content_path(
                receptor_id, rigid_output.artifact_id
            )
            receptor_rigid_bytes = receptor_rigid_path.read_bytes()

        if map_set.receptor_sha256 != receptor_flex_spec.receptor_rigid_sha256:
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "AutoGrid4 map set receptor SHA-256 differs from the rigid receptor PDBQT.",
                map_receptor_sha256=map_set.receptor_sha256,
                receptor_rigid_sha256=receptor_flex_spec.receptor_rigid_sha256,
            )

        # 3. Collect all molecules & saved poses across every source campaign, grouped by parent.
        parent_candidates: dict[str, list[ClusterCandidatePose]] = {}
        parent_meta: dict[str, dict[str, Any]] = {}
        pose_flex_bytes_by_id: dict[str, bytes | None] = {}
        pose_lig_bytes_by_id: dict[str, bytes] = {}
        source_engines_set: set[SourceEngine] = set()

        for entry in entries:
            src_engine = _ENGINE_KEY_TO_SOURCE.get(entry.engine_key)
            if src_engine is None:
                raise _consensus_error(
                    "CONSENSUS_UNSUPPORTED_SOURCE_ENGINE",
                    f"Unsupported catalog engine '{entry.engine_key}' for consensus.",
                )
            source_engines_set.add(src_engine)
            # Paginate all compounds in the source campaign
            offset = 0
            while True:
                page = self._catalog.list_compounds(entry.catalog_id, offset=offset, limit=200)
                for row in page.rows:
                    parent_id = row.parent_compound_id or row.ligand_id
                    meta = parent_meta.setdefault(
                        parent_id,
                        {
                            "ligand_id": row.ligand_id,
                            "parent_state_id": None,
                            "conformer_path": None,
                            "rotatable_bond_count": None,
                            "failure_codes": [],
                        },
                    )
                    if row.status != "completed":
                        meta["failure_codes"].append(
                            row.failure_code or f"{src_engine.upper()}_DOCKING_{row.status.upper()}"
                        )
                        continue
                    inventory = self._interactions.list_poses(entry.catalog_id, row.ligand_id)
                    if not inventory.poses:
                        meta["failure_codes"].append(f"{src_engine.upper()}_NO_POSES")
                        continue
                    for rank_idx, pose_ref in enumerate(inventory.poses, start=1):
                        verified = self._interactions.resolve_verified_pose_inputs(
                            entry.catalog_id, row.ligand_id, pose_ref.artifact_id
                        )
                        if (
                            verified.resolved.docking_receptor_sha256
                            != receptor_flex_spec.receptor_rigid_sha256
                        ):
                            raise _consensus_error(
                                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                                "Pose docking receptor SHA-256 differs from shared rigid receptor.",
                                catalog_id=entry.catalog_id,
                                pose_artifact_id=pose_ref.artifact_id,
                            )
                        lig_bytes = verified.resolved.pose_path.read_bytes()
                        flex_bytes = (
                            verified.resolved.pose_flex_path.read_bytes()
                            if verified.resolved.pose_flex_path is not None
                            and verified.resolved.pose_flex_path.is_file()
                            else None
                        )
                        pose_mode = (
                            ReceptorFlexMode.SIDECHAIN_FLEX
                            if flex_bytes is not None
                            else ReceptorFlexMode.RIGID
                        )
                        if pose_mode is not receptor_flex_spec.mode:
                            raise _consensus_error(
                                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                                "Cannot combine rigid and sidechain_flex poses in one consensus.",
                                catalog_id=entry.catalog_id,
                                pose_mode=pose_mode.value,
                                receptor_mode=receptor_flex_spec.mode.value,
                            )
                        pose_complex = PoseComplexIdentity(
                            mode=pose_mode,
                            receptor_rigid_sha256=receptor_flex_spec.receptor_rigid_sha256,
                            pose_flex_sidechains_sha256=(
                                sha256(flex_bytes).hexdigest() if flex_bytes is not None else None
                            ),
                            ligand_pose_sha256=sha256(lig_bytes).hexdigest(),
                        )
                        unique_pose_id = (
                            f"{entry.catalog_id}:{row.ligand_id}:{pose_ref.artifact_id}"
                        )
                        pose_lig_bytes_by_id[unique_pose_id] = lig_bytes
                        pose_flex_bytes_by_id[unique_pose_id] = flex_bytes
                        parent_candidates.setdefault(parent_id, []).append(
                            ClusterCandidatePose(
                                pose_id=unique_pose_id,
                                source_engine=src_engine,
                                primary_rank_order=rank_idx,
                                pose_complex=pose_complex,
                                ligand_pdbqt_text=lig_bytes.decode("utf-8", errors="replace"),
                                pose_flex_sidechains_pdbqt_text=(
                                    flex_bytes.decode("utf-8", errors="replace")
                                    if flex_bytes is not None
                                    else None
                                ),
                            )
                        )
                        if meta["parent_state_id"] is None:
                            meta["parent_state_id"] = verified.resolved.ligand_preparation_id
                        if meta["conformer_path"] is None:
                            meta["conformer_path"] = verified.conformer_path
                        if meta["rotatable_bond_count"] is None:
                            meta["rotatable_bond_count"] = (
                                verified.conformer.inspection.rotatable_bond_count
                            )
                offset += len(page.rows)
                if offset >= page.total or not page.rows:
                    break

        if not parent_meta:
            raise _consensus_error(
                "CONSENSUS_NO_COMPOUNDS",
                "Source campaigns contained zero parent compounds.",
            )

        # 4. Cluster each parent in joint (ligand, flex) space (E2/E3/E8) and cross-score retained
        #    medoids in place via PoseRescoringService (`--score_only`, E4/E7).
        rescore_context = PoseRescoreContext(
            receptor_flex_spec=receptor_flex_spec,
            binding_box=shared_box,
            binding_box_sha256=shared_box_sha256,
            autogrid_map_set_sha256=map_set_sha256,
            autogrid_map_prefix=map_prefix,
            autogrid_map_receptor_sha256=map_set.receptor_sha256,
            autogrid_map_flex_residues=tuple(map_set.flex_residues),
            autogrid_map_flex_atom_types=tuple(map_set.flex_atom_types),
            autogrid_map_affinity_atom_types=tuple(map_set.preflight.ligand_atom_types),
        )

        parent_inputs_by_id: dict[str, ConsensusParentInput] = {}
        clustered_parents: list[tuple[str, str, dict[str, Any], ParentClusteringResult]] = []
        medoid_jobs: list[tuple[str, str, PoseClusterSummary]] = []

        for parent_id in sorted(parent_meta):
            meta = parent_meta[parent_id]
            candidates = parent_candidates.get(parent_id, [])
            conformer_path: Path | None = meta["conformer_path"]
            state_id = str(meta["parent_state_id"] or f"{parent_id}-unprepared")

            if not candidates or conformer_path is None:
                parent_inputs_by_id[parent_id] = ConsensusParentInput(
                    parent_compound_id=parent_id,
                    parent_state_id=state_id,
                    rotatable_bond_count=meta["rotatable_bond_count"],
                    total_input_poses=0,
                    total_clusters_found=0,
                    truncated_by_k_max=False,
                    medoids=(),
                    failure_or_exclusion_codes=tuple(
                        dict.fromkeys(meta["failure_codes"] or ["CONSENSUS_NO_POSES"])
                    ),
                )
                continue

            try:
                ref_mol = load_reference(conformer_path)
                clustered = cluster_parent_pose_complexes(
                    candidates=candidates,
                    reference_conformer_mol=ref_mol,
                    k_max=request.k_max,
                    rmsd_threshold_angstrom=request.rmsd_threshold_angstrom,
                )
            except AnkoraDomainError as error:
                parent_inputs_by_id[parent_id] = ConsensusParentInput(
                    parent_compound_id=parent_id,
                    parent_state_id=state_id,
                    rotatable_bond_count=meta["rotatable_bond_count"],
                    total_input_poses=len(candidates),
                    total_clusters_found=0,
                    truncated_by_k_max=False,
                    medoids=(),
                    failure_or_exclusion_codes=tuple(
                        dict.fromkeys((*meta["failure_codes"], error.code))
                    ),
                )
                continue

            clustered_parents.append((parent_id, state_id, meta, clustered))
            for cluster in clustered.retained_clusters:
                medoid_jobs.append((parent_id, state_id, cluster))

        def _rescore_job(
            job: tuple[str, str, PoseClusterSummary],
        ) -> tuple[str, PoseClusterSummary, Any]:
            j_parent_id, j_state_id, j_cluster = job
            lig_bytes = pose_lig_bytes_by_id[j_cluster.medoid_pose_id]
            flex_bytes = pose_flex_bytes_by_id[j_cluster.medoid_pose_id]
            res = self._rescoring.rescore_pose(
                request=PoseRescoreRequest(
                    parent_compound_id=j_parent_id,
                    parent_state_id=j_state_id,
                    pose_complex=j_cluster.medoid_pose_complex,
                    scoring_functions=enabled_functions,
                    autodock4_backend=request.autodock4_backend,
                ),
                context=rescore_context,
                receptor_rigid_pdbqt=receptor_rigid_bytes,
                ligand_pose_pdbqt=lig_bytes,
                pose_flex_sidechains_pdbqt=flex_bytes,
                autogrid_maps_dir=maps_dir,
            )
            return j_parent_id, j_cluster, res

        requested_workers = request.rescore_workers
        if requested_workers is None:
            auto_workers = min(8, max(1, (os.cpu_count() or 2) // 2))
            workers = min(auto_workers, max(1, len(medoid_jobs)))
        else:
            workers = min(requested_workers, max(1, len(medoid_jobs)))

        if workers > 1 and len(medoid_jobs) > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                job_results = list(executor.map(_rescore_job, medoid_jobs))
        else:
            job_results = [_rescore_job(job) for job in medoid_jobs]

        medoids_by_parent: dict[str, list[ConsensusPoseScoreInput]] = {}
        observed_tools: dict[tuple[str, str], ToolIdentity] = {}
        observed_exec_shas: dict[str, str] = {}

        for j_parent_id, cluster, rescore_result in job_results:
            scores_map: dict[ScoringFunctionId, float] = {}
            missing_codes: list[str] = []
            for obs in rescore_result.observations:
                observed_tools[(obs.tool_name, obs.tool_version)] = ToolIdentity(
                    name=obs.tool_name, version=obs.tool_version
                )
                if obs.status is ObservationStatus.SCORED and obs.raw_score is not None:
                    scores_map[obs.scoring_function] = float(obs.raw_score)
                else:
                    missing_codes.append(
                        obs.failure_code or f"RESCORE_FAILED_{obs.scoring_function.value}"
                    )
            for ev in rescore_result.evidence:
                if ev.tool_sha256:
                    observed_exec_shas[ev.tool_name] = ev.tool_sha256

            medoids_by_parent.setdefault(j_parent_id, []).append(
                ConsensusPoseScoreInput(
                    cluster_id=cluster.cluster_id,
                    medoid_pose_id=cluster.medoid_pose_id,
                    pose_complex=cluster.medoid_pose_complex,
                    canonical_coordinate_sha256=cluster.medoid_canonical_coordinate_sha256,
                    member_count=cluster.member_count,
                    max_intra_cluster_rmsd_angstrom=cluster.max_intra_cluster_rmsd_angstrom,
                    search_engines_present=cluster.search_engines_present,
                    scores_by_function=scores_map,
                    missing_or_failed_codes=tuple(dict.fromkeys(missing_codes)),
                )
            )

        for parent_id, state_id, meta, clustered in clustered_parents:
            parent_inputs_by_id[parent_id] = ConsensusParentInput(
                parent_compound_id=parent_id,
                parent_state_id=state_id,
                rotatable_bond_count=meta["rotatable_bond_count"],
                total_input_poses=clustered.total_input_poses,
                total_clusters_found=clustered.total_clusters_found,
                truncated_by_k_max=clustered.truncated_by_k_max,
                medoids=tuple(medoids_by_parent.get(parent_id, ())),
                failure_or_exclusion_codes=tuple(dict.fromkeys(meta["failure_codes"])),
            )

        parent_inputs: list[ConsensusParentInput] = [
            parent_inputs_by_id[pid] for pid in sorted(parent_meta)
        ]

        structured_req = CreateStructuredConsensusRequest(
            name=request.name,
            variant_id=request.variant_id,
            receptor_id=receptor_id,
            binding_site_id=primary_binding_site_id,
            receptor_flex_spec=receptor_flex_spec,
            binding_box_sha256=shared_box_sha256,
            autogrid_map_set_sha256=map_set_sha256,
            enabled_functions=enabled_functions,
            k_max=request.k_max,
            rmsd_threshold_angstrom=request.rmsd_threshold_angstrom,
            search_engine_count=max(1, len(source_engines_set)),
            parents=tuple(parent_inputs),
            reference_panel_id=request.reference_panel_id,
            tool_identities=tuple(observed_tools.values()),
            executable_sha256s=observed_exec_shas,
        )
        return self.create_structured_consensus(
            structured_req, source_catalog_ids=source_catalog_ids
        )

    def fit_pc_l2(self, consensus_id: str, request: FitPcL2Request) -> ConsensusRunRecord:
        """Create a new derivative ConsensusRunRecord carrying gated PC-L2 calibration."""
        base = self._store.load_run(consensus_id)
        calibration = self._calibrations.get_run(request.calibration_id)
        if calibration.receptor_id != base.receptor_id:
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "Calibration run belongs to a different receptor than this consensus run.",
                calibration_receptor_id=calibration.receptor_id,
                consensus_receptor_id=base.receptor_id,
            )

        details_by_id = {d.parent_compound_id: d for d in base.parent_details}
        model, pcl2_ranking, pcl2_warnings = fit_and_gate_pc_l2(
            calibration=calibration,
            reference_panel=base.reference_panel,
            feature_functions=base.enabled_functions,
            parent_details_by_id=details_by_id,
            l2_regularization=request.l2_regularization,
        )

        score_by_parent = {
            entry.parent_compound_id: entry.score_value for entry in pcl2_ranking.entries
        }
        updated_details = tuple(
            detail.model_copy(
                update={"pc_l2_score": score_by_parent.get(detail.parent_compound_id)}
            )
            for detail in base.parent_details
        )
        created_at = datetime.now(UTC)
        new_id = self._store.new_consensus_id()
        combined_warnings = (*base.warnings, *pcl2_warnings)
        provenance = ProvenanceEvent(
            event_id=str(uuid4()),
            event_type="consensus_pc_l2_calibrated",
            timestamp=created_at,
            input_artifacts=[base.consensus_id, calibration.calibration_id],
            output_artifacts=[new_id],
            tool=_TOOL,
            parameters={
                "parent_consensus_id": base.consensus_id,
                "calibration_id": calibration.calibration_id,
                "l2_regularization": request.l2_regularization,
                "promoted": model.promoted,
                "promotion_verdict_text": model.promotion_verdict_text,
            },
            warnings=list(combined_warnings),
        )
        derivative = base.model_copy(
            update={
                "consensus_id": new_id,
                "created_at": created_at,
                "name": f"{base.name} (PC-L2)",
                "pc_l2_model": model,
                "pc_l2_ranking": pcl2_ranking,
                "parent_details": updated_details,
                "warnings": combined_warnings,
                "provenance": provenance,
            }
        )
        self._store.create_run(derivative)
        return derivative

    @staticmethod
    def _verify_reused_panel_context(
        *,
        panel: ReferencePanelArtifact,
        receptor_id: str,
        receptor_flex_spec: ReceptorFlexSpec,
        binding_box_sha256: str,
        autogrid_map_set_sha256: str,
        enabled_functions: Sequence[ScoringFunctionId],
        k_max: int,
        executable_sha256s: Mapping[str, str],
    ) -> None:
        panel_exec = dict(panel.executable_sha256s)
        req_exec = dict(executable_sha256s)
        same_function_set = set(enabled_functions) == set(panel.enabled_functions)
        if same_function_set:
            exec_mismatch = panel_exec != req_exec
        else:
            exec_mismatch = (
                bool(panel_exec) != bool(req_exec)
                or any(panel_exec.get(k) != v for k, v in req_exec.items())
            )
        if (
            panel.receptor_id != receptor_id
            or panel.receptor_flex_spec.mode != receptor_flex_spec.mode
            or panel.receptor_flex_spec.receptor_rigid_sha256
            != receptor_flex_spec.receptor_rigid_sha256
            or panel.receptor_flex_spec.canonical_flex_locators()
            != receptor_flex_spec.canonical_flex_locators()
            or panel.binding_box_sha256 != binding_box_sha256
            or panel.autogrid_map_set_sha256 != autogrid_map_set_sha256
            or not set(enabled_functions).issubset(panel.enabled_functions)
            or panel.k_max != k_max
            or exec_mismatch
        ):
            raise _consensus_error(
                "CONSENSUS_SHARED_CONTEXT_MISMATCH",
                "Locked ReferencePanelArtifact context does not match this consensus request.",
                panel_id=panel.panel_id,
                panel_sha256=panel.reference_panel_sha256,
                panel_k_max=panel.k_max,
                request_k_max=k_max,
                panel_executable_sha256s=panel_exec,
                request_executable_sha256s=req_exec,
            )


def _enabled_functions_for_campaign_request(
    request: CreateCampaignConsensusRequest,
) -> tuple[ScoringFunctionId, ...]:
    fns: list[ScoringFunctionId] = [ScoringFunctionId.VINA]
    if request.include_vinardo:
        fns.append(ScoringFunctionId.VINARDO)
    fns.append(ScoringFunctionId.AUTODOCK4)
    if request.variant_id is ConsensusVariantId.PCQ_NEURAL_V1:
        if request.gnina_function not in {
            ScoringFunctionId.GNINA_CNN_SCORE,
            ScoringFunctionId.GNINA_CNN_AFFINITY,
            ScoringFunctionId.GNINA_CNN_VS,
            ScoringFunctionId.GNINA_MINIMIZED_AFFINITY,
        }:
            raise _consensus_error(
                "CONSENSUS_VARIANT_FAMILY_MISMATCH",
                "pcq-neural-v1 requires a GNINA neural scoring function.",
                gnina_function=request.gnina_function.value,
            )
        fns.append(request.gnina_function)
    return tuple(fns)


def _consensus_error(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
