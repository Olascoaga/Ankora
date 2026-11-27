"""Immutable service orchestrating ADR-033 Hit-to-Analog Expansion & MCS Core RMSD."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from typing import Any

import httpx

from ankora_backend import __version__
from ankora_backend.adapters.chemistry.analog_similarity import (
    SqliteFingerprintCache,
    parse_local_analog_catalog,
    rdkit_version_string,
    run_offline_similarity_search,
)
from ankora_backend.adapters.chemistry.mcs_core_rmsd import (
    compute_receptor_frame_mcs_core_rmsd,
)
from ankora_backend.adapters.external.analog_providers import (
    _CHEMBL_BASE,
    _PUBCHEM_ENDPOINT,
    run_online_similarity_search,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.analog_expansion_store import AnalogExpansionStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.analog_expansion import (
    MAX_SELECTED_ANALOGS,
    AnalogCandidateRole,
    AnalogCatalogFormat,
    AnalogCatalogRecord,
    AnalogCatalogSummary,
    AnalogSearchHit,
    AnalogSearchMode,
    AnalogSearchRecord,
    AnalogSelectionDecision,
    AnalogSelectionRecord,
    CreateAnalogSelectionRequest,
    CsvCatalogSchema,
    ExternalConsentPreview,
    ExternalConsentPreviewRequest,
    McsCoreRmsdRequest,
    McsCoreRmsdResult,
    RunOfflineAnalogSearchRequest,
    RunOnlineAnalogSearchRequest,
    compute_external_consent_sha256,
)
from ankora_backend.schemas.ligands import LigandSource
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.ligand_import import import_local_ligand_library
from ankora_backend.services.pose_interactions import PoseInteractionService, VerifiedPoseInputs
from ankora_backend.services.project_dependencies import ProjectDependencyService

Chem: Any = import_module("rdkit.Chem")

_STAGE = "analog_expansion"
_SAFE_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


class AnalogExpansionService:
    """Orchestrate offline/opt-in-online analog search, curation, derived libraries & MCS RMSD."""

    def __init__(
        self,
        *,
        store: AnalogExpansionStore,
        ligands: LigandArtifactStore,
        interactions: PoseInteractionService,
        dependencies: ProjectDependencyService,
    ) -> None:
        self._store = store
        self._ligands = ligands
        self._interactions = interactions
        self._dependencies = dependencies

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> AnalogExpansionService:
        return cls(
            store=AnalogExpansionStore.from_environment(project_id=project_id),
            ligands=LigandArtifactStore.from_environment(project_id=project_id),
            interactions=PoseInteractionService.from_environment(),
            dependencies=ProjectDependencyService.from_environment(),
        )

    def list_catalogs(self) -> list[AnalogCatalogSummary]:
        return self._store.list_catalogs()

    def get_catalog(self, analog_catalog_id: str) -> AnalogCatalogRecord:
        return self._store.load_catalog(analog_catalog_id)

    def list_searches(self) -> list[AnalogSearchRecord]:
        return self._store.list_searches()

    def get_search(self, analog_search_id: str) -> AnalogSearchRecord:
        return self._store.load_search(analog_search_id)

    def list_selections(self) -> list[AnalogSelectionRecord]:
        return self._store.list_selections()

    def get_selection(self, analog_selection_id: str) -> AnalogSelectionRecord:
        return self._store.load_selection(analog_selection_id)

    def import_local_catalog(
        self,
        *,
        content: bytes,
        filename: str,
        name: str | None = None,
        csv_schema: CsvCatalogSchema | None = None,
    ) -> AnalogCatalogRecord:
        """Persist an immutable local SDF/SMI/CSV catalog snapshot for 100% offline search."""
        parsed = parse_local_analog_catalog(
            content=content,
            filename=filename,
            csv_schema=csv_schema,
        )
        catalog_id = self._store.new_catalog_id()
        safe_filename = self._store.sanitize_filename(filename)
        created_at = datetime.now(UTC)
        digest = sha256(content).hexdigest()
        display_name = (name or "").strip() or safe_filename
        provenance = ProvenanceEvent(
            event_id=f"analog-catalog-{catalog_id}",
            event_type="analog_catalog_imported",
            timestamp=created_at,
            input_artifacts=[],
            output_artifacts=[catalog_id],
            tool=ToolIdentity(name="RDKit analog catalog importer", version=rdkit_version_string()),
            parameters={
                "filename": safe_filename,
                "source_format": parsed.source_format.value,
                "total_records": len(parsed.entries),
                "valid_records": parsed.valid_records,
                "invalid_records": parsed.invalid_records,
                "csv_schema": csv_schema.model_dump(mode="json") if csv_schema else None,
            },
        )
        record = AnalogCatalogRecord(
            analog_catalog_id=catalog_id,
            name=display_name,
            source_format=parsed.source_format,
            filename=safe_filename,
            sha256=digest,
            size_bytes=len(content),
            created_at=created_at,
            source_library_id=None,
            csv_schema=csv_schema,
            total_records=len(parsed.entries),
            valid_records=parsed.valid_records,
            invalid_records=parsed.invalid_records,
            entries=parsed.entries,
            warnings=[],
            provenance=provenance,
        )
        self._store.create_catalog(record, content)
        return record

    def snapshot_project_library_as_catalog(
        self, *, library_id: str, name: str | None = None
    ) -> AnalogCatalogRecord:
        """Copy an existing project LigandLibraryRecord into an immutable analog catalog."""
        self._dependencies.require_current([library_id])
        lib_record = self._ligands.load_library_record(library_id)
        lib_path = self._ligands.library_content_path(library_id)
        content = lib_path.read_bytes()
        parsed = parse_local_analog_catalog(
            content=content,
            filename=lib_record.artifact.filename,
        )
        catalog_id = self._store.new_catalog_id()
        created_at = datetime.now(UTC)
        digest = sha256(content).hexdigest()
        display_name = (name or "").strip() or f"Snapshot of {lib_record.artifact.filename}"
        provenance = ProvenanceEvent(
            event_id=f"analog-catalog-{catalog_id}",
            event_type="analog_catalog_snapshotted_from_library",
            timestamp=created_at,
            input_artifacts=[library_id],
            output_artifacts=[catalog_id],
            tool=ToolIdentity(name="RDKit analog catalog importer", version=rdkit_version_string()),
            parameters={
                "source_library_id": library_id,
                "source_library_sha256": lib_record.artifact.sha256,
                "total_records": len(parsed.entries),
                "valid_records": parsed.valid_records,
                "invalid_records": parsed.invalid_records,
            },
        )
        record = AnalogCatalogRecord(
            analog_catalog_id=catalog_id,
            name=display_name,
            source_format=AnalogCatalogFormat.PROJECT_LIBRARY_SNAPSHOT,
            filename=lib_record.artifact.filename,
            sha256=digest,
            size_bytes=len(content),
            created_at=created_at,
            source_library_id=library_id,
            csv_schema=None,
            total_records=len(parsed.entries),
            valid_records=parsed.valid_records,
            invalid_records=parsed.invalid_records,
            entries=parsed.entries,
            warnings=[],
            provenance=provenance,
        )
        self._store.create_catalog(record, content)
        return record

    def prepare_external_consent_preview(
        self, request: ExternalConsentPreviewRequest
    ) -> ExternalConsentPreview:
        """Return exact query SMILES and cryptographic consent digest (zero outbound network)."""
        verified = self._interactions.resolve_verified_pose_inputs(
            request.source_catalog_id,
            request.source_ligand_id,
            request.source_pose_artifact_id,
        )
        seed_name, state_id, query_iso = self._resolve_seed_chemical_state_smiles(verified)
        endpoint = (
            _PUBCHEM_ENDPOINT if request.provider == "pubchem_pug_rest" else f"{_CHEMBL_BASE}/..."
        )
        digest = compute_external_consent_sha256(
            provider=request.provider,
            query_canonical_smiles=query_iso,
        )
        provider_label = (
            "PubChem PUG-REST (NCBI)"
            if request.provider == "pubchem_pug_rest"
            else "ChEMBL REST (EMBL-EBI)"
        )
        return ExternalConsentPreview(
            provider=request.provider,
            endpoint_url=endpoint,
            seed_name=seed_name,
            seed_chemical_state_id=state_id,
            query_canonical_isomeric_smiles=query_iso,
            consent_payload_sha256=digest,
            disclosure_message=(
                f"This explicit opt-in query will transmit the canonical SMILES below off your "
                f"local machine to {provider_label}. Sending this structure may disclose "
                "confidential or proprietary intellectual property. Ankora will archive the raw "
                "HTTP response and recalculate all similarity scores locally with RDKit."
            ),
        )

    def run_offline_search(self, request: RunOfflineAnalogSearchRequest) -> AnalogSearchRecord:
        """Execute a 100% offline RDKit Morgan similarity search from a verified lead pose."""
        verified = self._interactions.resolve_verified_pose_inputs(
            request.source_catalog_id,
            request.source_ligand_id,
            request.source_pose_artifact_id,
        )
        fresh_ids = [
            verified.resolved.receptor_id,
            verified.resolved.record_id,
            verified.resolved.pose.artifact_id,
            request.analog_catalog_id,
        ]
        if request.source_consensus_id is not None:
            fresh_ids.append(request.source_consensus_id)
        self._dependencies.require_current(fresh_ids)

        catalog = self._store.load_catalog(request.analog_catalog_id)
        seed_name, state_id, query_iso = self._resolve_seed_chemical_state_smiles(verified)
        pose_sha = sha256(verified.resolved.pose_path.read_bytes()).hexdigest()

        cache = SqliteFingerprintCache(self._store.fp_cache_path)
        result = run_offline_similarity_search(
            query_smiles=query_iso,
            seed_name=seed_name,
            catalog_sha256=catalog.sha256,
            entries=catalog.entries,
            profile=request.fingerprint_profile,
            min_tanimoto=request.min_tanimoto,
            top_k=request.top_k,
            smarts_filter=request.smarts_filter,
            cache=cache,
        )

        search_id = self._store.new_search_id()
        created_at = datetime.now(UTC)
        input_artifacts = [
            verified.resolved.record_id,
            verified.resolved.pose.artifact_id,
            catalog.analog_catalog_id,
        ]
        if request.source_consensus_id is not None:
            input_artifacts.append(request.source_consensus_id)

        provenance = ProvenanceEvent(
            event_id=f"analog-search-{search_id}",
            event_type="analog_similarity_search_offline",
            timestamp=created_at,
            input_artifacts=list(dict.fromkeys(input_artifacts)),
            output_artifacts=[search_id],
            tool=ToolIdentity(name="ankora-analog-expansion", version=__version__),
            parameters={
                "mode": AnalogSearchMode.OFFLINE_CATALOG.value,
                "rdkit_version": result.rdkit_version,
                "fingerprint_profile": request.fingerprint_profile.model_dump(mode="json"),
                "min_tanimoto": request.min_tanimoto,
                "top_k": request.top_k,
                "smarts_filter": request.smarts_filter,
                "cache_hit": result.cache_hit,
                "total_evaluated": result.total_evaluated,
                "invalid_skipped": result.invalid_skipped,
            },
            warnings=list(result.warnings),
        )
        record = AnalogSearchRecord(
            analog_search_id=search_id,
            created_at=created_at,
            mode=AnalogSearchMode.OFFLINE_CATALOG,
            source_catalog_id=request.source_catalog_id,
            source_record_id=verified.resolved.record_id,
            source_ligand_id=verified.resolved.ligand_id,
            source_pose_artifact_id=verified.resolved.pose.artifact_id,
            source_pose_sha256=pose_sha,
            source_consensus_id=request.source_consensus_id,
            source_cluster_id=request.source_cluster_id,
            seed_name=seed_name,
            seed_chemical_state_id=state_id,
            query_canonical_isomeric_smiles=result.query_canonical_isomeric_smiles,
            query_search_smiles=result.query_search_smiles,
            analog_catalog_id=catalog.analog_catalog_id,
            fingerprint_profile=request.fingerprint_profile,
            rdkit_version=result.rdkit_version,
            min_tanimoto=request.min_tanimoto,
            top_k=request.top_k,
            smarts_filter=request.smarts_filter,
            total_evaluated=result.total_evaluated,
            invalid_skipped=result.invalid_skipped,
            truncated_by_top_k=result.truncated_by_top_k,
            cache_hit=result.cache_hit,
            hits=result.hits,
            external_evidence=None,
            warnings=result.warnings,
            provenance=provenance,
        )
        self._store.create_search(record)
        return record

    def run_online_search(
        self,
        request: RunOnlineAnalogSearchRequest,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> AnalogSearchRecord:
        """Execute an explicit opt-in PubChem/ChEMBL search behind cryptographic IP consent."""
        verified = self._interactions.resolve_verified_pose_inputs(
            request.source_catalog_id,
            request.source_ligand_id,
            request.source_pose_artifact_id,
        )
        fresh_ids = [
            verified.resolved.receptor_id,
            verified.resolved.record_id,
            verified.resolved.pose.artifact_id,
        ]
        if request.source_consensus_id is not None:
            fresh_ids.append(request.source_consensus_id)
        self._dependencies.require_current(fresh_ids)

        seed_name, state_id, query_iso = self._resolve_seed_chemical_state_smiles(verified)
        pose_sha = sha256(verified.resolved.pose_path.read_bytes()).hexdigest()

        result = run_online_similarity_search(
            provider=request.provider,
            query_smiles=query_iso,
            seed_name=seed_name,
            consent=request.consent,
            provider_min_similarity=request.provider_min_similarity,
            min_local_rdkit_tanimoto=request.min_local_rdkit_tanimoto,
            max_candidates=request.max_candidates,
            profile=request.fingerprint_profile,
            smarts_filter=request.smarts_filter,
            transport=transport,
        )

        search_id = self._store.new_search_id()
        created_at = datetime.now(UTC)
        mode = (
            AnalogSearchMode.ONLINE_PUBCHEM
            if request.provider == "pubchem_pug_rest"
            else AnalogSearchMode.ONLINE_CHEMBL
        )
        input_artifacts = [
            verified.resolved.record_id,
            verified.resolved.pose.artifact_id,
        ]
        if request.source_consensus_id is not None:
            input_artifacts.append(request.source_consensus_id)

        provenance = ProvenanceEvent(
            event_id=f"analog-search-{search_id}",
            event_type="analog_similarity_search_online",
            timestamp=created_at,
            input_artifacts=list(dict.fromkeys(input_artifacts)),
            output_artifacts=[search_id],
            tool=ToolIdentity(name="ankora-analog-expansion", version=__version__),
            parameters={
                "mode": mode.value,
                "provider": request.provider,
                "endpoint_url": result.external_evidence.endpoint_url,
                "consent_payload_sha256": request.consent.consent_payload_sha256,
                "rdkit_version": result.rdkit_version,
                "fingerprint_profile": request.fingerprint_profile.model_dump(mode="json"),
                "provider_min_similarity": request.provider_min_similarity,
                "min_local_rdkit_tanimoto": request.min_local_rdkit_tanimoto,
                "max_candidates": request.max_candidates,
                "smarts_filter": request.smarts_filter,
            },
            warnings=list(result.warnings),
        )
        record = AnalogSearchRecord(
            analog_search_id=search_id,
            created_at=created_at,
            mode=mode,
            source_catalog_id=request.source_catalog_id,
            source_record_id=verified.resolved.record_id,
            source_ligand_id=verified.resolved.ligand_id,
            source_pose_artifact_id=verified.resolved.pose.artifact_id,
            source_pose_sha256=pose_sha,
            source_consensus_id=request.source_consensus_id,
            source_cluster_id=request.source_cluster_id,
            seed_name=seed_name,
            seed_chemical_state_id=state_id,
            query_canonical_isomeric_smiles=result.query_canonical_isomeric_smiles,
            query_search_smiles=result.query_search_smiles,
            analog_catalog_id=None,
            fingerprint_profile=request.fingerprint_profile,
            rdkit_version=result.rdkit_version,
            min_tanimoto=request.min_local_rdkit_tanimoto,
            top_k=request.max_candidates,
            smarts_filter=request.smarts_filter,
            total_evaluated=result.total_evaluated,
            invalid_skipped=result.invalid_skipped,
            truncated_by_top_k=result.truncated_by_top_k,
            cache_hit=False,
            hits=result.hits,
            external_evidence=result.external_evidence,
            warnings=result.warnings,
            provenance=provenance,
        )
        self._store.create_search(record, raw_provider_response=result.raw_response_bytes)
        return record

    def create_selection_and_derived_library(
        self,
        *,
        analog_search_id: str,
        request: CreateAnalogSelectionRequest,
    ) -> AnalogSelectionRecord:
        """Persist explicit curation and materialize a derived LigandLibraryRecord for ADR-016."""
        self._dependencies.require_current([analog_search_id])
        search = self._store.load_search(analog_search_id)
        hits_by_id: dict[str, AnalogSearchHit] = {hit.hit_id: hit for hit in search.hits}
        unknown_ids = [hid for hid in request.selected_hit_ids if hid not in hits_by_id]
        if unknown_ids:
            raise AnkoraDomainError(
                code="ANALOG_SELECTION_UNKNOWN_HITS",
                stage=_STAGE,
                message="One or more selected hit IDs do not belong to this analog search.",
                status_code=422,
                details={"unknown_hit_ids": unknown_ids},
            )

        seed_hit = next(
            (hit for hit in search.hits if hit.role is AnalogCandidateRole.SEED_CONTROL),
            None,
        )
        ordered_selected_ids: list[str] = []
        warnings: list[StructuredWarning] = []

        if request.include_seed_control and seed_hit is not None:
            ordered_selected_ids.append(seed_hit.hit_id)
        elif not request.include_seed_control and seed_hit is not None:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.ANALOG_SEED_CONTROL_EXCLUDED,
                    stage=_STAGE,
                    message=(
                        "The parent seed_control was explicitly excluded from the derived "
                        "mini-library; focused scores will lack an in-box parent re-docking "
                        "control (ADR-033 §6)."
                    ),
                    details={"seed_exclusion_reason": request.seed_exclusion_reason},
                )
            )

        for hid in request.selected_hit_ids:
            if seed_hit is not None and hid == seed_hit.hit_id and not request.include_seed_control:
                continue
            if hid not in ordered_selected_ids:
                ordered_selected_ids.append(hid)

        if not ordered_selected_ids:
            raise AnkoraDomainError(
                code="ANALOG_SELECTION_EMPTY",
                stage=_STAGE,
                message="At least one compound must be selected to create a derived mini-library.",
                status_code=422,
            )
        if len(ordered_selected_ids) > MAX_SELECTED_ANALOGS:
            raise AnkoraDomainError(
                code="ANALOG_SELECTION_TOO_LARGE",
                stage=_STAGE,
                message=(
                    f"Derived mini-libraries are capped at {MAX_SELECTED_ANALOGS} compounds "
                    "in Ankora v0.2 (including seed_control)."
                ),
                status_code=422,
                details={
                    "selected_count": len(ordered_selected_ids),
                    "max_selected": MAX_SELECTED_ANALOGS,
                },
            )

        selected_set = set(ordered_selected_ids)
        decisions: list[AnalogSelectionDecision] = []
        for hit in search.hits:
            is_sel = hit.hit_id in selected_set
            reason = (
                request.seed_exclusion_reason
                if (not is_sel and hit.role is AnalogCandidateRole.SEED_CONTROL)
                else request.exclusion_reasons_by_hit_id.get(hit.hit_id)
            )
            decisions.append(
                AnalogSelectionDecision(
                    hit_id=hit.hit_id,
                    selected=is_sel,
                    role=hit.role,
                    reason=reason,
                )
            )

        # Build canonical isomeric SMILES library content preserving salts/stereochemistry for
        # downstream ADR-016 curation without silent mutation.
        smi_lines: list[str] = []
        for hid in ordered_selected_ids:
            hit = hits_by_id[hid]
            role_prefix = "SEED_" if hit.role is AnalogCandidateRole.SEED_CONTROL else ""
            safe_ident = _SAFE_SLUG.sub("_", hit.identifier.strip()).strip("._") or hit.hit_id
            smi_lines.append(f"{hit.canonical_isomeric_smiles}\t{role_prefix}{safe_ident}")
        smi_bytes = ("\n".join(smi_lines) + "\n").encode("utf-8")

        selection_id = self._store.new_selection_id()
        lib_slug = _SAFE_SLUG.sub("_", request.library_name.strip()).strip("._") or "analog_series"
        derived_library = import_local_ligand_library(
            content=smi_bytes,
            filename=f"{lib_slug}.smi",
            store=self._ligands,
            ligand_source=LigandSource.ANALOG_EXPANSION,
            origin_analog_selection_id=selection_id,
            origin_analog_search_id=analog_search_id,
            extra_input_artifacts=[analog_search_id, selection_id],
        )

        created_at = datetime.now(UTC)
        provenance = ProvenanceEvent(
            event_id=f"analog-selection-{selection_id}",
            event_type="analog_selection_curated",
            timestamp=created_at,
            input_artifacts=[analog_search_id],
            output_artifacts=[selection_id, derived_library.artifact.library_id],
            tool=ToolIdentity(name="ankora-analog-expansion", version=__version__),
            parameters={
                "library_name": request.library_name,
                "derived_library_id": derived_library.artifact.library_id,
                "include_seed_control": request.include_seed_control,
                "selected_count": len(ordered_selected_ids),
                "excluded_count": len(search.hits) - len(ordered_selected_ids),
            },
            warnings=list(warnings),
        )
        record = AnalogSelectionRecord(
            analog_selection_id=selection_id,
            analog_search_id=analog_search_id,
            created_at=created_at,
            library_name=request.library_name,
            derived_library_id=derived_library.artifact.library_id,
            derived_library_sha256=derived_library.artifact.sha256,
            include_seed_control=request.include_seed_control,
            selected_count=len(ordered_selected_ids),
            excluded_count=len(search.hits) - len(ordered_selected_ids),
            decisions=decisions,
            warnings=warnings,
            provenance=provenance,
        )
        self._store.create_selection(record)
        return record

    def evaluate_mcs_core_rmsd(self, request: McsCoreRmsdRequest) -> McsCoreRmsdResult:
        """Compute receptor-frame MCS core RMSD (zero ligand superposition) between two poses."""
        seed = self._interactions.resolve_verified_pose_inputs(
            request.seed_catalog_id,
            request.seed_ligand_id,
            request.seed_pose_artifact_id,
        )
        target = self._interactions.resolve_verified_pose_inputs(
            request.target_catalog_id,
            request.target_ligand_id,
            request.target_pose_artifact_id,
        )
        if seed.resolved.receptor_id != target.resolved.receptor_id:
            raise AnkoraDomainError(
                code="ANALOG_MCS_RECEPTOR_MISMATCH",
                stage=_STAGE,
                message=(
                    "Receptor-frame MCS core RMSD requires both poses to be docked against "
                    "the exact same prepared receptor coordinate frame."
                ),
                status_code=422,
                details={
                    "seed_receptor_id": seed.resolved.receptor_id,
                    "target_receptor_id": target.resolved.receptor_id,
                },
            )
        seed_bytes = seed.resolved.pose_path.read_bytes()
        target_bytes = target.resolved.pose_path.read_bytes()
        return compute_receptor_frame_mcs_core_rmsd(
            seed_pose_artifact_id=seed.resolved.pose.artifact_id,
            seed_pose_sha256=sha256(seed_bytes).hexdigest(),
            seed_pose_pdbqt_text=seed_bytes.decode("utf-8", errors="replace"),
            seed_conformer_path=seed.conformer_path,
            target_pose_artifact_id=target.resolved.pose.artifact_id,
            target_pose_sha256=sha256(target_bytes).hexdigest(),
            target_pose_pdbqt_text=target_bytes.decode("utf-8", errors="replace"),
            target_conformer_path=target.conformer_path,
            timeout_seconds=request.timeout_seconds,
            ring_matches_ring_only=request.ring_matches_ring_only,
            complete_rings_only=request.complete_rings_only,
        )

    def _resolve_seed_chemical_state_smiles(
        self, verified: VerifiedPoseInputs
    ) -> tuple[str, str | None, str]:
        """Extract canonical isomeric SMILES strictly from the resolved ADR-016 chemical state."""
        seed_name = verified.conformer.inspection.name
        state_id = verified.conformer.artifact.chemical_state_id
        smiles = verified.conformer.inspection.canonical_smiles
        if not smiles:
            lig_rec = self._ligands.load_record(verified.resolved.ligand_id)
            smiles = lig_rec.inspection.canonical_smiles
            if state_id is None and lig_rec.state is not None:
                state_id = lig_rec.state.state_id
        if not smiles:
            mol = Chem.MolFromMolBlock(verified.conformer_path.read_bytes(), removeHs=False)
            if mol is not None:
                smiles = str(Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True))
        if not smiles:
            raise AnkoraDomainError(
                code="ANALOG_SEED_CHEMICAL_STATE_MISSING",
                stage=_STAGE,
                message=(
                    "Could not resolve canonical SMILES from the seed pose's chemical state "
                    "(Ankora never reconstructs SMILES from PDBQT coordinates)."
                ),
                status_code=422,
                details={
                    "ligand_id": verified.resolved.ligand_id,
                    "conformer_id": verified.conformer.artifact.conformer_id,
                },
            )
        # Canonicalize isomeric SMILES cleanly via RDKit so consent hashes match deterministically
        mol_check = Chem.MolFromSmiles(smiles)
        if mol_check is None:
            raise AnkoraDomainError(
                code="ANALOG_SEED_CHEMICAL_STATE_MISSING",
                stage=_STAGE,
                message="Seed chemical state SMILES failed RDKit validation.",
                status_code=422,
            )
        canonical_iso = str(Chem.MolToSmiles(mol_check, isomericSmiles=True, canonical=True))
        return seed_name, state_id, canonical_iso
