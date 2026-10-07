"""Typed contracts for immutable M3 ligand extraction and inspection."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning


class LigandSource(StrEnum):
    CRYSTALLOGRAPHIC = "crystallographic"
    LOCAL = "local"


class LigandFormat(StrEnum):
    SDF = "sdf"
    MOL = "mol"
    SMILES = "smiles"


class LigandLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_name: str = Field(min_length=1)
    chain_id: str
    sequence_number: int
    insertion_code: str = ""


class ExtractLigandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator: LigandLocator


class LigandArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    source: LigandSource
    source_structure_id: str | None = None
    locator: LigandLocator | None = None
    filename: str = Field(min_length=1)
    format: LigandFormat
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime
    library_id: str | None = None
    library_record_index: int | None = Field(default=None, ge=0)


class LigandInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    molecular_weight_g_mol: float | None = Field(default=None, gt=0)
    exact_mass_da: float | None = Field(default=None, gt=0)
    formal_charge: int
    atom_count: int = Field(ge=1)
    heavy_atom_count: int = Field(ge=1)
    rotatable_bond_count: int = Field(ge=0)
    aromatic_ring_count: int = Field(ge=0)
    stereocenter_count: int = Field(ge=0)
    undefined_stereocenter_count: int = Field(default=0, ge=0)
    fragment_count: int = Field(default=1, ge=1)
    conformer_count: int = Field(ge=0)
    has_3d_coordinates: bool = False
    canonical_smiles: str | None = None


class LigandChemicalStateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    format: str = Field(pattern="^sdf$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime


class LigandComponentOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    formula: str = Field(min_length=1)
    formal_charge: int
    heavy_atom_count: int = Field(ge=1)
    canonical_smiles: str = Field(min_length=1)


class LigandStereoisomerOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    canonical_isomeric_smiles: str = Field(min_length=1)


class LigandStateResolutionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_state_id: str = Field(min_length=1)
    component_options: list[LigandComponentOption]
    selected_component_index: int | None = Field(default=None, ge=0)
    stereoisomer_options: list[LigandStereoisomerOption]
    component_selection_required: bool
    stereoisomer_selection_required: bool


class ResolveLigandStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_state_id: str = Field(min_length=1)
    component_index: int = Field(ge=0)
    stereoisomer_index: int | None = Field(default=None, ge=0)


class LigandStateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_index: int = Field(ge=0)
    source_fragment_count: int = Field(ge=1)
    stereoisomer_index: int | None = Field(default=None, ge=0)
    stereoisomer_count: int = Field(ge=1)


class LigandChemicalStateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandChemicalStateArtifact
    parent_state_id: str = Field(min_length=1)
    inspection: LigandInspection
    selection: LigandStateSelection
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)


class LigandProtonationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    canonical_smiles: str = Field(min_length=1)
    formal_charge: int


class LigandProtonationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_state_id: str = Field(min_length=1)
    ph_min: float
    ph_max: float
    precision: float = Field(gt=0)
    candidates: list[LigandProtonationCandidate]
    selection_required: bool


class ResolveLigandProtonationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_state_id: str = Field(min_length=1)
    # A single physiological pH, matching the interface. Dimorphite-DL's own
    # 6.4-8.4 default enumerates every state plausible across that window,
    # which is a library-design question rather than a docking one.
    ph_min: float = Field(default=7.4)
    ph_max: float = Field(default=7.4)
    precision: float = Field(default=1.0, gt=0)
    candidate_index: int = Field(ge=0)

    @model_validator(mode="after")
    def require_valid_ph_range(self) -> "ResolveLigandProtonationRequest":
        # A single pH is a legitimate request - "the state at 7.4" - and the
        # enumeration endpoint already accepts it, so rejecting it here left
        # the two halves of the contract disagreeing about the same window.
        if self.ph_max < self.ph_min:
            raise ValueError("ph_max must not be below ph_min")
        return self


class LigandProtonationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(ge=0)
    candidate_count: int = Field(ge=1)
    ph_min: float
    ph_max: float
    precision: float = Field(gt=0)


class LigandProtonationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandChemicalStateArtifact
    parent_state_id: str = Field(min_length=1)
    inspection: LigandInspection
    selection: LigandProtonationSelection
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)


class LigandMicrostateMode(StrEnum):
    EXACT_IMPORTED_STATE = "exact_imported_state"
    ENUMERATED_SELECTION = "enumerated_selection"


class LigandMicrostatePlan(BaseModel):
    """Scientist-visible bounds for one compound's screening microstates.

    The plan deliberately contains no ranking or population model.  Candidate
    order is a reproducibility detail only; a scientist must choose the exact
    state that is carried forward.
    """

    model_config = ConfigDict(extra="forbid")

    mode: LigandMicrostateMode = LigandMicrostateMode.EXACT_IMPORTED_STATE
    ph_min: float = Field(default=7.4, ge=0, le=14)
    ph_max: float = Field(default=7.4, ge=0, le=14)
    precision: float = Field(default=1.0, gt=0, le=5)
    max_tautomers_per_protomer: int = Field(default=8, ge=1, le=32)
    max_microstates_per_parent: int = Field(default=16, ge=1, le=64)

    @model_validator(mode="after")
    def require_valid_ph_range(self) -> "LigandMicrostatePlan":
        if self.ph_max < self.ph_min:
            raise ValueError("ph_max must not be below ph_min")
        return self


class LigandMicrostateCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    microstate_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_isomeric_smiles: str = Field(min_length=1)
    formal_charge: int
    protonation_candidate_index: int = Field(ge=0)
    tautomer_index: int = Field(ge=0)
    matches_parent_state: bool = False


class LigandMicrostateOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_state_id: str = Field(min_length=1)
    plan: LigandMicrostatePlan
    candidates: list[LigandMicrostateCandidate] = Field(min_length=1)
    protonation_candidate_count: int = Field(ge=1)
    enumerated_candidate_count: int = Field(ge=1)
    truncated: bool = False
    dimorphite_version: str = Field(min_length=1)
    rdkit_version: str = Field(min_length=1)


class ResolveLigandMicrostateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_state_id: str = Field(min_length=1)
    plan: LigandMicrostatePlan
    candidate_index: int = Field(ge=0)
    acknowledge_bounded_enumeration: bool = False

    @model_validator(mode="after")
    def require_enumerated_selection(self) -> "ResolveLigandMicrostateRequest":
        if self.plan.mode is not LigandMicrostateMode.ENUMERATED_SELECTION:
            raise ValueError(
                "A derived microstate can only be selected from an enumerated plan."
            )
        if not self.acknowledge_bounded_enumeration:
            raise ValueError(
                "acknowledge_bounded_enumeration must be true before selecting a "
                "screening microstate."
            )
        return self


class LigandMicrostateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(ge=0)
    candidate_count: int = Field(ge=1)
    microstate_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    protonation_candidate_index: int = Field(ge=0)
    tautomer_index: int = Field(ge=0)
    plan: LigandMicrostatePlan
    enumeration_truncated: bool = False


class LigandMicrostateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandChemicalStateArtifact
    parent_state_id: str = Field(min_length=1)
    inspection: LigandInspection
    selection: LigandMicrostateSelection
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)


class LigandRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandArtifact
    state: LigandChemicalStateArtifact | None = None
    inspection: LigandInspection
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)
    original_content_url: str | None = None


class LigandLibraryEntryStatus(StrEnum):
    IMPORTED = "imported"
    FAILED = "failed"


class LigandLibraryArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    format: LigandFormat
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    record_count: int = Field(ge=1)
    created_at: datetime


class LigandLibrarySummary(BaseModel):
    """One imported library, described without any of its molecules.

    The same boundary the result catalog draws: the real project holds 38
    libraries whose records total 35.7 MiB, so a listing that carried entries
    would get slower with every import. The artifact is the whole identity a
    reader needs to recognise a library; its molecules are a separate request.
    """

    model_config = ConfigDict(extra="forbid")

    artifact: LigandLibraryArtifact
    # Whether a selection was ever applied to this library, and which was last.
    # Both come from directory metadata rather than from reading a filter run.
    filter_run_count: int = Field(default=0, ge=0)
    latest_filter_run_id: str | None = None


class LigandLibraryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    libraries: list[LigandLibrarySummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class LigandLibraryEntryFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class LigandLibraryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_index: int = Field(ge=0)
    status: LigandLibraryEntryStatus
    ligand: LigandRecord | None = None
    failure: LigandLibraryEntryFailure | None = None


class LigandLibraryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandLibraryArtifact
    entries: list[LigandLibraryEntry]
    imported_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    provenance: ProvenanceEvent
    original_content_url: str = Field(min_length=1)


class LigandAlertPolicy(StrEnum):
    IGNORE = "ignore"
    REVIEW = "review"
    EXCLUDE = "exclude"


class LigandDuplicatePolicy(StrEnum):
    KEEP = "keep"
    REVIEW = "review"
    EXCLUDE = "exclude"


class LigandFilterDisposition(StrEnum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    NEEDS_DECISION = "needs_decision"


class LigandCustomRuleDescriptor(StrEnum):
    """Mirrors the field names of LigandFilterDescriptors exactly, so the
    evaluation service can resolve a rule's target value with getattr()."""

    MOLECULAR_WEIGHT = "molecular_weight_g_mol"
    CLOGP = "clogp"
    HYDROGEN_BOND_DONORS = "hydrogen_bond_donors"
    HYDROGEN_BOND_ACCEPTORS = "hydrogen_bond_acceptors"
    TPSA = "tpsa_angstrom2"
    ROTATABLE_BONDS = "rotatable_bonds"
    MOLAR_REFRACTIVITY = "molar_refractivity"
    TOTAL_ATOM_COUNT_WITH_HYDROGENS = "total_atom_count_with_hydrogens"
    CARBON_ATOM_COUNT = "carbon_atom_count"
    HETERO_ATOM_COUNT = "hetero_atom_count"
    RING_COUNT = "ring_count"
    QED = "qed"


class LigandCustomRuleOperator(StrEnum):
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    EQUAL = "eq"
    BETWEEN = "between"


class LigandCustomFilterRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=80)
    descriptor: LigandCustomRuleDescriptor
    operator: LigandCustomRuleOperator
    value: float
    value_upper: float | None = None
    required: bool = True

    @model_validator(mode="after")
    def _validate_range(self) -> "LigandCustomFilterRule":
        if self.operator is LigandCustomRuleOperator.BETWEEN:
            if self.value_upper is None:
                raise ValueError("value_upper is required when operator is 'between'.")
            if self.value_upper < self.value:
                raise ValueError("value_upper must be greater than or equal to value.")
        elif self.value_upper is not None:
            raise ValueError("value_upper is only accepted when operator is 'between'.")
        return self


class LigandLibraryFilterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str = Field(default="general_oral", pattern="^(general_oral|custom)$")
    require_lipinski: bool = True
    max_lipinski_violations: int = Field(default=1, ge=0, le=4)
    require_veber: bool = True
    require_ghose: bool = False
    require_muegge: bool = False
    minimum_qed: float | None = Field(default=None, ge=0, le=1)
    pains_policy: LigandAlertPolicy = LigandAlertPolicy.REVIEW
    brenk_policy: LigandAlertPolicy = LigandAlertPolicy.REVIEW
    duplicate_policy: LigandDuplicatePolicy = LigandDuplicatePolicy.EXCLUDE
    custom_rules: list[LigandCustomFilterRule] = Field(default_factory=list)


class LigandLibraryFilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: LigandLibraryFilterPlan = Field(default_factory=LigandLibraryFilterPlan)
    microstate_plan: LigandMicrostatePlan = Field(default_factory=LigandMicrostatePlan)
    state_overrides: dict[str, str] = Field(default_factory=dict)


class ApplyLigandLibraryFilterRequest(LigandLibraryFilterRequest):
    acknowledge_selection: bool = False


class LigandFilterDescriptors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    molecular_weight_g_mol: float = Field(gt=0)
    clogp: float
    hydrogen_bond_donors: int = Field(ge=0)
    hydrogen_bond_acceptors: int = Field(ge=0)
    tpsa_angstrom2: float = Field(ge=0)
    rotatable_bonds: int = Field(ge=0)
    molar_refractivity: float = Field(ge=0)
    total_atom_count_with_hydrogens: int = Field(ge=1)
    carbon_atom_count: int = Field(ge=0)
    hetero_atom_count: int = Field(ge=0)
    ring_count: int = Field(ge=0)
    qed: float = Field(ge=0, le=1)


class LigandRuleEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    violations: list[str] = Field(default_factory=list)


class LigandStructuralAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog: str = Field(pattern="^(PAINS|BRENK)$")
    description: str = Field(min_length=1)
    atom_indices: list[int] = Field(default_factory=list)


class LigandCustomRuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    required: bool
    passed: bool
    value: float


class LigandFilterEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    record_index: int = Field(ge=0)
    state_id: str = Field(min_length=1)
    canonical_isomeric_smiles: str | None = None
    descriptors: LigandFilterDescriptors | None = None
    lipinski: LigandRuleEvaluation | None = None
    veber: LigandRuleEvaluation | None = None
    ghose: LigandRuleEvaluation | None = None
    muegge: LigandRuleEvaluation | None = None
    custom_rule_results: list[LigandCustomRuleResult] = Field(default_factory=list)
    alerts: list[LigandStructuralAlert] = Field(default_factory=list)
    duplicate_of_ligand_id: str | None = None
    disposition: LigandFilterDisposition
    reasons: list[str] = Field(default_factory=list)


class LigandFilterSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imported_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    needs_decision_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    pains_match_count: int = Field(ge=0)
    brenk_match_count: int = Field(ge=0)


class LigandLibraryFilterPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_id: str = Field(min_length=1)
    plan: LigandLibraryFilterPlan
    microstate_plan: LigandMicrostatePlan = Field(default_factory=LigandMicrostatePlan)
    evaluations: list[LigandFilterEvaluation]
    summary: LigandFilterSummary
    rdkit_version: str = Field(min_length=1)
    worker_count: int = Field(ge=1)


class LigandFilterRunArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_run_id: str = Field(min_length=1)
    library_id: str = Field(min_length=1)
    filename: str = Field(pattern="^selection_manifest.json$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime


class LigandLibraryFilterRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandFilterRunArtifact
    plan: LigandLibraryFilterPlan
    microstate_plan: LigandMicrostatePlan = Field(default_factory=LigandMicrostatePlan)
    evaluations: list[LigandFilterEvaluation]
    summary: LigandFilterSummary
    selected_ligand_ids: list[str]
    rdkit_version: str = Field(min_length=1)
    worker_count: int = Field(ge=1)
    provenance: ProvenanceEvent
    manifest_content_url: str = Field(min_length=1)


class LigandForceField(StrEnum):
    MMFF94 = "MMFF94"
    MMFF94S = "MMFF94s"


class LigandConformerSelectionPolicy(StrEnum):
    LOWEST_ENERGY_CONVERGED = "lowest_energy_converged"
    LOWEST_ENERGY_NONCONVERGED_FALLBACK = (
        "lowest_energy_nonconverged_fallback"
    )


class MinimizeLigandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force_field: LigandForceField = LigandForceField.MMFF94S
    max_iterations: int = Field(default=500, ge=1, le=10_000)
    acknowledge_current_chemical_state: bool = False
    state_id: str | None = None


class GenerateLigandConformerRequest(MinimizeLigandRequest):
    random_seed: int = Field(default=20260819, ge=0, le=2_147_483_647)
    client_concurrency_hint: int | None = Field(
        default=None,
        ge=1,
        description=(
            "How many of these requests the client is issuing concurrently for "
            "this batch run, recorded into provenance for reproducibility. "
            "Purely informational: the server always processes one request at a "
            "time on its own thread and never uses this value to size any "
            "internal thread pool."
        ),
    )


class LigandConformerArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conformer_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    chemical_state_id: str | None = None
    stage: str = Field(pattern="^(minimized|generated_minimized)$")
    filename: str = Field(min_length=1)
    format: str = Field(pattern="^sdf$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime


class LigandMinimizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force_field: LigandForceField
    max_iterations: int = Field(ge=1)
    converged: bool
    initial_energy_kcal_mol: float
    final_energy_kcal_mol: float
    embedding_method: str | None = None
    random_seed: int | None = None
    independent_from_source_coordinates: bool = False
    conformer_pool_size: int | None = Field(default=None, ge=1)
    conformer_pool_converged_count: int | None = Field(default=None, ge=0)
    conformer_selection_policy: LigandConformerSelectionPolicy | None = None

    @model_validator(mode="after")
    def require_consistent_pool_selection(self) -> "LigandMinimizationResult":
        count = self.conformer_pool_converged_count
        policy = self.conformer_selection_policy
        if count is None and policy is None:
            # Historical conformer records predate pool-level selection evidence.
            return self
        if count is None or policy is None or self.conformer_pool_size is None:
            raise ValueError(
                "Pool selection policy, converged count, and pool size must be "
                "recorded together."
            )
        if not self.independent_from_source_coordinates:
            raise ValueError(
                "Pool selection metadata requires an independent conformer pool."
            )
        if count > self.conformer_pool_size:
            raise ValueError("Converged conformer count cannot exceed the pool size.")
        if policy is LigandConformerSelectionPolicy.LOWEST_ENERGY_CONVERGED:
            if count == 0 or not self.converged:
                raise ValueError(
                    "A lowest-energy converged selection requires at least one "
                    "converged conformer and a converged selected outcome."
                )
        elif count != 0 or self.converged:
            raise ValueError(
                "A nonconverged fallback requires zero converged conformers and "
                "a nonconverged selected outcome."
            )
        return self


class LigandConformerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandConformerArtifact
    inspection: LigandInspection
    minimization: LigandMinimizationResult
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)


class LigandChargeModel(StrEnum):
    GASTEIGER = "gasteiger"


class PrepareLigandPdbqtRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charge_model: LigandChargeModel = LigandChargeModel.GASTEIGER
    client_concurrency_hint: int | None = Field(
        default=None,
        ge=1,
        description=(
            "How many of these requests the client is issuing concurrently for "
            "this batch run, recorded into provenance for reproducibility. "
            "Purely informational: the server always processes one request at a "
            "time on its own thread and never uses this value to size any "
            "internal thread pool."
        ),
    )


class LigandPdbqtArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preparation_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    conformer_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    format: str = Field(pattern="^pdbqt$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime


class LigandPdbqtRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: LigandPdbqtArtifact
    charge_model: LigandChargeModel
    tool: ToolIdentity
    command: list[str]
    stdout: str
    stderr: str
    provenance: ProvenanceEvent
    content_url: str = Field(min_length=1)
