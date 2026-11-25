"""Frozen contracts for declarative ProLIF pharmacophoric rules & Tanimoto IFP (M4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ankora_backend.schemas.pose_interactions import (
    InteractionContact,
    InteractionProfile,
    PoseReference,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.v02_contracts import (
    DiagnosticStatus,
    PoseComplexIdentity,
    canonical_contract_sha256,
)
from ankora_backend.schemas.warnings import StructuredWarning

type NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

_IFP_IDENTITY_SCHEMA = "ankora.interaction_ifp.v1"
_RULE_SET_IDENTITY_SCHEMA = "ankora.interaction_rule_set.v1"

#: Canonical ProLIF interaction vocabulary exposed in Ankora's default profile.
SUPPORTED_PROLIF_INTERACTIONS: frozenset[str] = frozenset(
    {
        "Hydrophobic",
        "HBDonor",
        "HBAcceptor",
        "FaceToFace",
        "EdgeToFace",
        "CationPi",
        "PiCation",
        "Anionic",
        "Cationic",
        "XBAcceptor",
        "XBDonor",
        "MetalAcceptor",
        "MetalDonor",
        "VdWContact",
    }
)


class InteractionRuleKind(StrEnum):
    """Logical operator governing one declarative pharmacophoric clause."""

    REQUIRED = "required"
    ALTERNATIVE_OR = "alternative_or"
    FORBIDDEN = "forbidden"


class IfpSourceKind(StrEnum):
    """Origin of a recorded binary/counted ProLIF interaction fingerprint."""

    POSE_ANALYSIS = "pose_analysis"
    EXPLICIT_BITS = "explicit_bits"


def residue_locator_sort_key(residue: ResidueLocator) -> tuple[str, int, str, str]:
    """Return a deterministic ordering key for one receptor residue locator."""
    return (
        residue.chain_id.strip(),
        residue.sequence_number,
        residue.insertion_code.strip(),
        residue.residue_name.strip().upper(),
    )


def format_residue_label(residue: ResidueLocator) -> str:
    """Render a residue locator in Ankora's canonical `RES CHAIN:NUM[ICODE]` form."""
    insertion = residue.insertion_code.strip()
    chain = residue.chain_id.strip()
    name = residue.residue_name.strip().upper()
    return f"{name} {chain}:{residue.sequence_number}{insertion}"


class IfpBit(BaseModel):
    """One binary residue-by-interaction bit in a ProLIF fingerprint vector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    residue: ResidueLocator
    interaction_type: NonBlankStr

    def sort_key(self) -> tuple[str, int, str, str, str]:
        chain, seq, icode, resname = residue_locator_sort_key(self.residue)
        return (chain, seq, icode, resname, self.interaction_type)


class IfpCountEntry(BaseModel):
    """Auditable atomic contact multiplicity associated with one IFP bit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bit: IfpBit
    count: int = Field(ge=1)


def compute_ifp_sha256(
    *,
    profile: InteractionProfile,
    bits: Sequence[IfpBit],
) -> str:
    """Compute an order-invariant canonical SHA-256 over an IFP profile and bit set."""
    canonical_bits = sorted(
        {
            (
                b.residue.chain_id.strip(),
                b.residue.sequence_number,
                b.residue.insertion_code.strip(),
                b.residue.residue_name.strip().upper(),
                b.interaction_type,
            )
            for b in bits
        }
    )
    payload: dict[str, object] = {
        "schema": _IFP_IDENTITY_SCHEMA,
        "profile_id": profile.profile_id,
        "vicinity_cutoff_angstrom": profile.vicinity_cutoff_angstrom,
        "interactions": sorted(set(profile.interactions)),
        "bits": [
            {
                "chain_id": chain,
                "sequence_number": seq,
                "insertion_code": icode,
                "residue_name": resname,
                "interaction_type": itype,
            }
            for chain, seq, icode, resname, itype in canonical_bits
        ],
    }
    return canonical_contract_sha256(payload)


class InteractionFingerprint(BaseModel):
    """Canonical residue x interaction fingerprint extracted from ProLIF 2.2.1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: InteractionProfile
    bits: tuple[IfpBit, ...] = ()
    counts: tuple[IfpCountEntry, ...] = ()
    source_kind: IfpSourceKind
    source_analysis_id: str | None = None
    source_catalog_id: str | None = None
    source_ligand_id: str | None = None
    source_pose_artifact_id: str | None = None
    source_pose_complex_sha256: Sha256 | None = None
    fingerprint_sha256: Sha256

    @model_validator(mode="after")
    def validate_bits_and_hash(self) -> Self:
        bit_keys = [bit.sort_key() for bit in self.bits]
        if len(set(bit_keys)) != len(bit_keys):
            raise ValueError("InteractionFingerprint bits must be unique")
        count_keys = [entry.bit.sort_key() for entry in self.counts]
        if len(set(count_keys)) != len(count_keys):
            raise ValueError("InteractionFingerprint counts must not repeat bits")
        if not set(count_keys).issubset(set(bit_keys)):
            raise ValueError("InteractionFingerprint counts must match declared bits")
        expected = compute_ifp_sha256(profile=self.profile, bits=self.bits)
        if self.fingerprint_sha256 != expected:
            raise ValueError("fingerprint_sha256 must match canonical IFP content hash")
        return self


class InteractionTarget(BaseModel):
    """One atomic residue + interaction-type predicate inside a pharmacophoric clause."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    residue: ResidueLocator
    interaction_types: tuple[NonBlankStr, ...] = Field(min_length=1)
    max_distance_angstrom: float | None = Field(
        default=None, gt=0.0, le=20.0, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def validate_unique_types(self) -> Self:
        if len(set(self.interaction_types)) != len(self.interaction_types):
            raise ValueError("InteractionTarget interaction_types must be unique")
        unknown = [t for t in self.interaction_types if t not in SUPPORTED_PROLIF_INTERACTIONS]
        if unknown:
            raise ValueError(f"Unsupported ProLIF interaction type(s): {', '.join(unknown)}")
        return self


class InteractionRuleClause(BaseModel):
    """One declarative REQUIRED (AND), ALTERNATIVE_OR (k-of-n), or FORBIDDEN (NOT) clause."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clause_id: NonBlankStr
    label: NonBlankStr
    kind: InteractionRuleKind
    targets: tuple[InteractionTarget, ...] = Field(min_length=1)
    min_satisfied: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_clause_semantics(self) -> Self:
        if self.kind is InteractionRuleKind.ALTERNATIVE_OR:
            if len(self.targets) < 2:
                raise ValueError("ALTERNATIVE_OR clauses require at least two interaction targets")
            effective_min = 1 if self.min_satisfied is None else self.min_satisfied
            if effective_min > len(self.targets):
                raise ValueError("min_satisfied cannot exceed the number of targets in the clause")
        elif self.min_satisfied is not None:
            raise ValueError("min_satisfied may only be set on ALTERNATIVE_OR clauses")
        return self

    @property
    def effective_min_satisfied(self) -> int:
        if self.kind is InteractionRuleKind.ALTERNATIVE_OR:
            return 1 if self.min_satisfied is None else self.min_satisfied
        if self.kind is InteractionRuleKind.REQUIRED:
            return len(self.targets)
        return 0


def _canonical_target_dict(target: InteractionTarget) -> dict[str, object]:
    return {
        "residue": {
            "chain_id": target.residue.chain_id.strip(),
            "residue_name": target.residue.residue_name.strip().upper(),
            "sequence_number": target.residue.sequence_number,
            "insertion_code": target.residue.insertion_code.strip(),
        },
        "interaction_types": sorted(target.interaction_types),
        "max_distance_angstrom": target.max_distance_angstrom,
    }


def compute_rule_set_identity_sha256(
    *,
    receptor_protonated_sha256: str,
    profile: InteractionProfile,
    clauses: Sequence[InteractionRuleClause],
    reference_fingerprint_sha256: str | None,
    min_tanimoto_similarity: float | None,
) -> str:
    """Compute an order-invariant canonical SHA-256 for a sealed InteractionRuleSet.

    This 64-hex digest plugs directly into `ProtocolSpec.interaction_rule_set_sha256`
    (`v02_contracts.py`) before Confirmation is unlocked (`ADR-031`).
    """
    canonical_clauses = sorted(
        (
            {
                "clause_id": clause.clause_id,
                "kind": clause.kind.value,
                "min_satisfied": (
                    clause.effective_min_satisfied
                    if clause.kind is InteractionRuleKind.ALTERNATIVE_OR
                    else None
                ),
                "targets": sorted(
                    (_canonical_target_dict(t) for t in clause.targets),
                    key=lambda item: canonical_contract_sha256(item),
                ),
            }
            for clause in clauses
        ),
        key=lambda item: (str(item["kind"]), str(item["clause_id"])),
    )
    payload: dict[str, object] = {
        "schema": _RULE_SET_IDENTITY_SCHEMA,
        "receptor_protonated_sha256": receptor_protonated_sha256,
        "profile": {
            "profile_id": profile.profile_id,
            "vicinity_cutoff_angstrom": profile.vicinity_cutoff_angstrom,
            "interactions": sorted(set(profile.interactions)),
        },
        "clauses": canonical_clauses,
        "reference_fingerprint_sha256": reference_fingerprint_sha256,
        "min_tanimoto_similarity": min_tanimoto_similarity,
    }
    return canonical_contract_sha256(payload)


class ReferencePoseSelector(BaseModel):
    """Saved docking pose used to compute an immutable reference IFP for Tanimoto comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_id: NonBlankStr
    ligand_id: NonBlankStr
    pose_artifact_id: NonBlankStr


class CreateInteractionRuleSetRequest(BaseModel):
    """Request to create and seal one immutable declarative pharmacophoric rule set."""

    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr
    description: str = ""
    receptor_id: NonBlankStr
    profile: InteractionProfile = Field(default_factory=InteractionProfile)
    clauses: tuple[InteractionRuleClause, ...] = ()
    reference_pose: ReferencePoseSelector | None = None
    reference_bits: tuple[IfpBit, ...] | None = None
    min_tanimoto_similarity: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def validate_rule_set_request(self) -> Self:
        if self.reference_pose is not None and self.reference_bits is not None:
            raise ValueError("Provide either reference_pose or reference_bits, not both")
        has_reference = self.reference_pose is not None or self.reference_bits is not None
        if not self.clauses and not has_reference:
            raise ValueError(
                "An InteractionRuleSet requires at least one pharmacophoric clause or a "
                "reference IFP"
            )
        if self.min_tanimoto_similarity is not None and not has_reference:
            raise ValueError(
                "min_tanimoto_similarity requires a reference_pose or reference_bits IFP"
            )
        clause_ids = [clause.clause_id for clause in self.clauses]
        if len(set(clause_ids)) != len(clause_ids):
            raise ValueError("Clause IDs inside an InteractionRuleSet must be unique")
        unknown_profile = [
            itype
            for itype in self.profile.interactions
            if itype not in SUPPORTED_PROLIF_INTERACTIONS
        ]
        if unknown_profile:
            raise ValueError(
                f"Profile includes unsupported ProLIF interaction(s): {', '.join(unknown_profile)}"
            )
        profile_set = set(self.profile.interactions)
        for clause in self.clauses:
            for target in clause.targets:
                missing = [t for t in target.interaction_types if t not in profile_set]
                if missing:
                    raise ValueError(
                        f"Clause '{clause.clause_id}' references interaction type(s) not enabled "
                        f"in the rule set profile: {', '.join(missing)}"
                    )
        if self.reference_bits is not None:
            for bit in self.reference_bits:
                if bit.interaction_type not in profile_set:
                    raise ValueError(
                        f"Reference IFP bit references interaction type '{bit.interaction_type}' "
                        "which is not enabled in the rule set profile"
                    )
        return self


class InteractionRuleSetRecord(BaseModel):
    """Immutable, hash-sealed pharmacophoric rule set persisted under the project tree."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    rule_set_id: NonBlankStr
    created_at: datetime
    name: NonBlankStr
    description: str = ""
    receptor_id: NonBlankStr
    receptor_protonated_artifact_id: NonBlankStr
    receptor_protonated_sha256: Sha256
    profile: InteractionProfile
    clauses: tuple[InteractionRuleClause, ...] = ()
    reference_ifp: InteractionFingerprint | None = None
    min_tanimoto_similarity: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False
    )
    rule_set_identity_sha256: Sha256
    provenance: ProvenanceEvent

    @model_validator(mode="after")
    def validate_identity_hash(self) -> Self:
        expected = compute_rule_set_identity_sha256(
            receptor_protonated_sha256=self.receptor_protonated_sha256,
            profile=self.profile,
            clauses=self.clauses,
            reference_fingerprint_sha256=(
                self.reference_ifp.fingerprint_sha256 if self.reference_ifp is not None else None
            ),
            min_tanimoto_similarity=self.min_tanimoto_similarity,
        )
        if self.rule_set_identity_sha256 != expected:
            raise ValueError(
                "rule_set_identity_sha256 must match canonical InteractionRuleSet hash"
            )
        return self


class TargetEvaluationResult(BaseModel):
    """Evaluation outcome of one residue + interaction-type target against detected contacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: InteractionTarget
    matched: bool
    matched_contact_ids: tuple[str, ...] = ()
    shortest_distance_angstrom: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)


class ClauseEvaluationResult(BaseModel):
    """Evaluation outcome of one REQUIRED / ALTERNATIVE_OR / FORBIDDEN clause."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clause_id: NonBlankStr
    label: NonBlankStr
    kind: InteractionRuleKind
    status: DiagnosticStatus
    satisfied_target_count: int = Field(ge=0)
    required_target_count: int = Field(ge=0)
    matched_contact_ids: tuple[str, ...] = ()
    target_results: tuple[TargetEvaluationResult, ...] = Field(min_length=1)
    explanation: NonBlankStr


class IfpTanimotoResult(BaseModel):
    """Exact Tanimoto similarity between a pose IFP and a reference IFP.

    When both bitvectors are empty (`union_count == 0`), `0 / 0` is reported
    honestly as `similarity = None` and `status = not_evaluable` rather than
    fabricating `1.0` or `0.0`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_fingerprint_sha256: Sha256
    pose_fingerprint_sha256: Sha256
    status: DiagnosticStatus
    similarity: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    min_threshold: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    intersection_count: int = Field(ge=0)
    union_count: int = Field(ge=0)
    shared_bits: tuple[IfpBit, ...] = ()
    pose_only_bits: tuple[IfpBit, ...] = ()
    reference_only_bits: tuple[IfpBit, ...] = ()

    @model_validator(mode="after")
    def validate_tanimoto_math(self) -> Self:
        if self.union_count == 0:
            if self.similarity is not None or self.status is not DiagnosticStatus.NOT_EVALUABLE:
                raise ValueError(
                    "Empty IFP union (0/0) must record similarity=None and status=not_evaluable"
                )
        else:
            expected = self.intersection_count / self.union_count
            if self.similarity is None or abs(self.similarity - expected) > 1e-12:
                raise ValueError("similarity must equal intersection_count / union_count")
        return self


class EvaluateInteractionRulesRequest(BaseModel):
    """Request to evaluate one saved docking pose against a sealed InteractionRuleSet."""

    model_config = ConfigDict(extra="forbid")

    rule_set_id: NonBlankStr
    analysis_id: str | None = None


class InteractionRuleEvaluationRecord(BaseModel):
    """Immutable create-only pharmacophoric rule evaluation for one coupled PoseComplex."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evaluation_id: NonBlankStr
    created_at: datetime
    rule_set_id: NonBlankStr
    rule_set_name: NonBlankStr
    rule_set_identity_sha256: Sha256
    catalog_id: NonBlankStr
    engine_key: NonBlankStr
    record_id: NonBlankStr
    engine_label: NonBlankStr
    ligand_id: NonBlankStr
    ligand_preparation_id: NonBlankStr
    conformer_id: NonBlankStr
    conformer_sha256: Sha256
    receptor_id: NonBlankStr
    docking_receptor_artifact_id: NonBlankStr
    docking_receptor_sha256: Sha256
    analysis_receptor_artifact_id: NonBlankStr
    analysis_receptor_sha256: Sha256
    materialized_coupled_receptor_sha256: Sha256 | None = None
    pose: PoseReference
    pose_complex: PoseComplexIdentity
    interaction_analysis_id: str | None = None
    detector: ToolIdentity
    profile: InteractionProfile
    pose_ifp: InteractionFingerprint
    contacts: tuple[InteractionContact, ...] = ()
    overall_status: DiagnosticStatus
    clause_results: tuple[ClauseEvaluationResult, ...] = ()
    passed_clause_count: int = Field(ge=0)
    failed_clause_count: int = Field(ge=0)
    tanimoto: IfpTanimotoResult | None = None
    mutated_original_pose: Literal[False] = False
    warnings: tuple[StructuredWarning, ...] = ()
    provenance: ProvenanceEvent
