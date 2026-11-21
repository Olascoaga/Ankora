"""Typed immutable contracts for ADR-033 Hit-to-Analog Expansion & MCS Core RMSD."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.warnings import StructuredWarning

MAX_ANALOG_CATALOG_BYTES = 100 * 1024 * 1024
MAX_ANALOG_CATALOG_RECORDS = 10_000
MAX_SELECTED_ANALOGS = 200
MAX_ONLINE_CANDIDATES = 500
MAX_ONLINE_RESPONSE_BYTES = 10 * 1024 * 1024


class AnalogCatalogFormat(StrEnum):
    SDF = "sdf"
    SMI = "smi"
    SMILES = "smiles"
    CSV = "csv"
    PROJECT_LIBRARY_SNAPSHOT = "project_library_snapshot"


class AnalogSearchMode(StrEnum):
    OFFLINE_CATALOG = "offline_catalog"
    ONLINE_PUBCHEM = "online_pubchem"
    ONLINE_CHEMBL = "online_chembl"


class AnalogCandidateRole(StrEnum):
    SEED_CONTROL = "seed_control"
    ANALOG = "analog"


class McsCoreRmsdStatus(StrEnum):
    EVALUATED = "evaluated"
    NO_COMMON_SUBSTRUCTURE = "no_common_substructure"
    NOT_EVALUABLE = "not_evaluable"


def compute_external_consent_sha256(*, provider: str, query_canonical_smiles: str) -> str:
    """Bind external transmission consent cryptographically to exact provider and query SMILES."""
    payload = f"{provider.strip()}:{query_canonical_smiles.strip()}".encode()
    return sha256(payload).hexdigest()


class CsvCatalogSchema(BaseModel):
    """Explicit schema for bounded CSV analog catalogs (ADR-033 §4)."""

    model_config = ConfigDict(extra="forbid")

    smiles_column: str = Field(min_length=1)
    id_column: str | None = Field(default=None, min_length=1)
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    encoding: str = Field(default="utf-8", min_length=1)


class AnalogFingerprintProfile(BaseModel):
    """Frozen, explicitly recorded RDKit 2D similarity configuration (ADR-033 §4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["morgan"] = "morgan"
    radius: int = Field(default=2, ge=1, le=4)
    fp_size: int = Field(default=2048, ge=512, le=4096)
    include_chirality: bool = True
    strip_salts_for_search_only: bool = True
    canonicalize_tautomers_for_search_only: bool = False

    def profile_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


class AnalogCatalogEntry(BaseModel):
    """One parsed or failed row inside an immutable local analog catalog snapshot."""

    model_config = ConfigDict(extra="forbid")

    record_index: int = Field(ge=0)
    identifier: str = Field(min_length=1)
    raw_smiles: str | None = None
    canonical_isomeric_smiles: str | None = None
    search_smiles: str | None = None
    had_multiple_fragments: bool = False
    undefined_stereocenter_count: int = Field(default=0, ge=0)
    molecular_weight_g_mol: float | None = Field(default=None, gt=0)
    heavy_atom_count: int | None = Field(default=None, ge=1)
    rotatable_bond_count: int | None = Field(default=None, ge=0)
    parse_error: str | None = None


class AnalogCatalogRecord(BaseModel):
    """Immutable local catalog snapshot available for offline similarity search."""

    model_config = ConfigDict(extra="forbid")

    analog_catalog_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_format: AnalogCatalogFormat
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime
    source_library_id: str | None = None
    csv_schema: CsvCatalogSchema | None = None
    total_records: int = Field(ge=0)
    valid_records: int = Field(ge=0)
    invalid_records: int = Field(ge=0)
    entries: list[AnalogCatalogEntry]
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent


class AnalogCatalogSummary(BaseModel):
    """Lightweight summary for listing immutable local analog catalogs."""

    model_config = ConfigDict(extra="forbid")

    analog_catalog_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_format: AnalogCatalogFormat
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime
    source_library_id: str | None = None
    total_records: int = Field(ge=0)
    valid_records: int = Field(ge=0)
    invalid_records: int = Field(ge=0)


class AnalogSearchHit(BaseModel):
    """One ranked candidate or seed control returned by an analog similarity search."""

    model_config = ConfigDict(extra="forbid")

    hit_id: str = Field(min_length=1)
    role: AnalogCandidateRole
    identifier: str = Field(min_length=1)
    source_record_index: int | None = Field(default=None, ge=0)
    canonical_isomeric_smiles: str = Field(min_length=1)
    search_smiles: str = Field(min_length=1)
    local_rdkit_tanimoto: float = Field(ge=0.0, le=1.0)
    provider_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    provider_compound_id: str | None = None
    smarts_matched: bool | None = None
    molecular_weight_g_mol: float | None = Field(default=None, gt=0)
    heavy_atom_count: int = Field(ge=1)
    rotatable_bond_count: int = Field(ge=0)
    undefined_stereocenter_count: int = Field(default=0, ge=0)
    had_multiple_fragments: bool = False
    duplicate_of_hit_id: str | None = None


class ExternalTransmissionConsent(BaseModel):
    """Explicit IP/confidentiality consent bound to exact provider and query SMILES."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["pubchem_pug_rest", "chembl_rest"]
    query_canonical_smiles: str = Field(min_length=1)
    consent_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_external_transmission: bool = False

    def verify_for(self, *, provider: str, canonical_smiles: str) -> bool:
        if not self.acknowledge_external_transmission:
            return False
        if self.provider != provider:
            return False
        if self.query_canonical_smiles.strip() != canonical_smiles.strip():
            return False
        expected = compute_external_consent_sha256(
            provider=provider,
            query_canonical_smiles=canonical_smiles,
        )
        return self.consent_payload_sha256 == expected


class ExternalProviderEvidence(BaseModel):
    """Immutable audit record of one explicit opt-in online similarity retrieval."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["pubchem_pug_rest", "chembl_rest"]
    endpoint_url: str = Field(min_length=1)
    request_parameters: dict[str, object] = Field(default_factory=dict)
    http_status_codes: list[int] = Field(min_length=1)
    retrieved_at: datetime
    provider_version: str | None = None
    raw_response_filename: str = Field(min_length=1)
    raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_response_bytes: int = Field(ge=1)
    truncated_or_capped: bool = False
    consent: ExternalTransmissionConsent


class AnalogSearchRecord(BaseModel):
    """Immutable record of an offline or opt-in online hit-to-analog similarity search."""

    model_config = ConfigDict(extra="forbid")

    analog_search_id: str = Field(min_length=1)
    created_at: datetime
    mode: AnalogSearchMode
    source_catalog_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_ligand_id: str = Field(min_length=1)
    source_pose_artifact_id: str = Field(min_length=1)
    source_pose_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_consensus_id: str | None = None
    source_cluster_id: str | None = None
    seed_name: str = Field(min_length=1)
    seed_chemical_state_id: str | None = None
    query_canonical_isomeric_smiles: str = Field(min_length=1)
    query_search_smiles: str = Field(min_length=1)
    analog_catalog_id: str | None = None
    fingerprint_profile: AnalogFingerprintProfile
    rdkit_version: str = Field(min_length=1)
    min_tanimoto: float = Field(ge=0.0, le=1.0)
    top_k: int = Field(ge=1, le=MAX_ONLINE_CANDIDATES)
    smarts_filter: str | None = None
    total_evaluated: int = Field(ge=0)
    invalid_skipped: int = Field(ge=0)
    truncated_by_top_k: bool = False
    cache_hit: bool = False
    hits: list[AnalogSearchHit]
    external_evidence: ExternalProviderEvidence | None = None
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent


class AnalogSelectionDecision(BaseModel):
    """Explicit scientist curation decision for one analog search hit."""

    model_config = ConfigDict(extra="forbid")

    hit_id: str = Field(min_length=1)
    selected: bool
    role: AnalogCandidateRole
    reason: str | None = Field(default=None, max_length=240)


class CreateAnalogSelectionRequest(BaseModel):
    """Scientist curation request turning reviewed analog hits into a derived mini-library."""

    model_config = ConfigDict(extra="forbid")

    library_name: str = Field(min_length=1, max_length=120)
    selected_hit_ids: list[str] = Field(min_length=1, max_length=MAX_SELECTED_ANALOGS)
    include_seed_control: bool = True
    seed_exclusion_reason: str | None = Field(default=None, max_length=240)
    exclusion_reasons_by_hit_id: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_selection_policy(self) -> AnalogSelectionRequestSelf:
        if len(set(self.selected_hit_ids)) != len(self.selected_hit_ids):
            raise ValueError("selected_hit_ids must not contain duplicates")
        if not self.include_seed_control and not (self.seed_exclusion_reason or "").strip():
            raise ValueError(
                "Excluding the mandatory seed_control requires an explicit seed_exclusion_reason"
            )
        return self


type AnalogSelectionRequestSelf = CreateAnalogSelectionRequest


class AnalogSelectionRecord(BaseModel):
    """Immutable curation record linking an analog search to a derived LigandLibraryRecord."""

    model_config = ConfigDict(extra="forbid")

    analog_selection_id: str = Field(min_length=1)
    analog_search_id: str = Field(min_length=1)
    created_at: datetime
    library_name: str = Field(min_length=1)
    derived_library_id: str = Field(min_length=1)
    derived_library_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    include_seed_control: bool
    selected_count: int = Field(ge=1, le=MAX_SELECTED_ANALOGS)
    excluded_count: int = Field(ge=0)
    decisions: list[AnalogSelectionDecision]
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent


class RunOfflineAnalogSearchRequest(BaseModel):
    """Request to run a 100% offline RDKit Morgan similarity search against a local catalog."""

    model_config = ConfigDict(extra="forbid")

    source_catalog_id: str = Field(min_length=1)
    source_ligand_id: str = Field(min_length=1)
    source_pose_artifact_id: str = Field(min_length=1)
    source_consensus_id: str | None = Field(default=None, min_length=1)
    source_cluster_id: str | None = Field(default=None, min_length=1)
    analog_catalog_id: str = Field(min_length=1)
    min_tanimoto: float = Field(default=0.4, ge=0.0, le=1.0)
    top_k: int = Field(default=100, ge=1, le=MAX_ONLINE_CANDIDATES)
    smarts_filter: str | None = Field(default=None, min_length=1)
    fingerprint_profile: AnalogFingerprintProfile = Field(
        default_factory=AnalogFingerprintProfile
    )


class ExternalConsentPreviewRequest(BaseModel):
    """Prepare the exact IP disclosure and consent hash before any external HTTP call."""

    model_config = ConfigDict(extra="forbid")

    source_catalog_id: str = Field(min_length=1)
    source_ligand_id: str = Field(min_length=1)
    source_pose_artifact_id: str = Field(min_length=1)
    provider: Literal["pubchem_pug_rest", "chembl_rest"]


class ExternalConsentPreview(BaseModel):
    """Exact disclosure payload shown to the scientist prior to opt-in online lookup."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["pubchem_pug_rest", "chembl_rest"]
    endpoint_url: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    seed_chemical_state_id: str | None = None
    query_canonical_isomeric_smiles: str = Field(min_length=1)
    consent_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    disclosure_message: str = Field(min_length=1)


class RunOnlineAnalogSearchRequest(BaseModel):
    """Explicit opt-in request for PubChem PUG-REST or ChEMBL REST similarity search."""

    model_config = ConfigDict(extra="forbid")

    source_catalog_id: str = Field(min_length=1)
    source_ligand_id: str = Field(min_length=1)
    source_pose_artifact_id: str = Field(min_length=1)
    source_consensus_id: str | None = Field(default=None, min_length=1)
    source_cluster_id: str | None = Field(default=None, min_length=1)
    provider: Literal["pubchem_pug_rest", "chembl_rest"]
    provider_min_similarity: float = Field(default=0.7, ge=0.4, le=1.0)
    min_local_rdkit_tanimoto: float = Field(default=0.4, ge=0.0, le=1.0)
    max_candidates: int = Field(default=100, ge=1, le=MAX_ONLINE_CANDIDATES)
    smarts_filter: str | None = Field(default=None, min_length=1)
    fingerprint_profile: AnalogFingerprintProfile = Field(
        default_factory=AnalogFingerprintProfile
    )
    consent: ExternalTransmissionConsent


class McsCoreRmsdRequest(BaseModel):
    """Compare one analog docked pose against a seed pose in the receptor coordinate frame."""

    model_config = ConfigDict(extra="forbid")

    seed_catalog_id: str = Field(min_length=1)
    seed_ligand_id: str = Field(min_length=1)
    seed_pose_artifact_id: str = Field(min_length=1)
    target_catalog_id: str = Field(min_length=1)
    target_ligand_id: str = Field(min_length=1)
    target_pose_artifact_id: str = Field(min_length=1)
    timeout_seconds: int = Field(default=5, ge=1, le=30)
    ring_matches_ring_only: bool = True
    complete_rings_only: bool = True


class McsCoreRmsdResult(BaseModel):
    """In-place receptor-frame MCS heavy-atom RMSD (zero ligand superposition, ADR-033 §7)."""

    model_config = ConfigDict(extra="forbid")

    seed_pose_artifact_id: str = Field(min_length=1)
    seed_pose_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_pose_artifact_id: str = Field(min_length=1)
    target_pose_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: McsCoreRmsdStatus
    mcs_smarts: str | None = None
    mcs_heavy_atom_count: int = Field(ge=0)
    seed_heavy_atom_count: int = Field(ge=0)
    target_heavy_atom_count: int = Field(ge=0)
    mcs_coverage_seed: float | None = Field(default=None, ge=0.0, le=1.0)
    mcs_coverage_target: float | None = Field(default=None, ge=0.0, le=1.0)
    mcs_timed_out: bool = False
    receptor_frame_rmsd_angstrom: float | None = Field(default=None, ge=0.0)
    superposition_applied: Literal[False] = False
    timeout_seconds: int = Field(ge=1)
    atom_compare: str = Field(min_length=1)
    bond_compare: str = Field(min_length=1)
    ring_matches_ring_only: bool
    complete_rings_only: bool
    warnings: list[StructuredWarning] = Field(default_factory=list)
