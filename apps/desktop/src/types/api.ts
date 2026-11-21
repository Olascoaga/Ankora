export interface HealthResponse {
  status: "ok";
  backend_version: string;
}

export interface SystemResponse {
  platform: string;
  architecture: string;
  python_version: string;
  python_environment: string;
  app_mode: string;
}

export interface ToolStatus {
  available: boolean;
  path: string | null;
  version: string | null;
  architecture?: string | null;
  sha256?: string | null;
}

export interface ToolsResponse {
  vina: ToolStatus;
  gnina: ToolStatus;
  autogrid4: ToolStatus;
  autodock4: ToolStatus;
  autodock_gpu: ToolStatus;
  pdbfixer: ToolStatus;
  pdb2pqr: ToolStatus;
  propka: ToolStatus;
  meeko: ToolStatus;
  meeko_ligand: ToolStatus;
  p2rank: ToolStatus;
}

export interface ImportGninaPackRequest {
  archive_path: string;
}

export interface GninaPackStatus {
  supported: boolean;
  installed: boolean;
  pack_id: string;
  gnina_version: string;
  install_dir?: string | null;
  executable_path?: string | null;
  executable_sha256?: string | null;
  shared_library_count: number;
  imported_at?: string | null;
  verification_error?: string | null;
}

export type StructureFormat = "pdb" | "mmcif";
export type StructureSource = "local" | "rcsb" | "alphafold";
export type HeterogenKind = "ligand" | "water" | "metal" | "other";

export interface StructuredWarning {
  code: string;
  message: string;
  stage: string;
  details: Record<string, unknown>;
  recoverable: boolean;
}

export interface StructureArtifact {
  artifact_id: string;
  original_filename: string;
  format: StructureFormat;
  sha256: string;
  size_bytes: number;
  source: StructureSource;
  source_uri: string | null;
  imported_at: string;
}

export interface ChainSummary {
  chain_id: string;
  residue_count: number;
  polymer_residue_count: number;
  atom_count: number;
}

export interface HeterogenSummary {
  name: string;
  chain_id: string;
  sequence_number: number | null;
  insertion_code: string;
  atom_count: number;
  kind: HeterogenKind;
}

export interface StructureMetadata {
  entry_id: string | null;
  title: string | null;
  experimental_method: string | null;
  resolution_angstrom: number | null;
  model_count: number;
  atom_count: number;
  residue_count: number;
  chains: ChainSummary[];
  heterogens: HeterogenSummary[];
  alternate_location_atom_count: number;
  missing_residue_count: number;
  missing_atom_count: number;
  nonstandard_polymer_residues: string[];
}

export interface ProvenanceEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  input_artifacts: string[];
  output_artifacts: string[];
  tool: { name: string; version: string };
  parameters: Record<string, unknown>;
  warnings: StructuredWarning[];
  command: string[] | null;
}

export interface StructureRecord {
  artifact: StructureArtifact;
  metadata: StructureMetadata;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  content_url: string;
}

export type ReceptorIssueKind = "missing_residue" | "missing_atoms" | "alternate_location" | "nonstandard_residue";
export type ReceptorIssueSeverity = "unassessed" | "near_reference" | "remote";
export type ReceptorDecisionAction = "leave" | "repair" | "remove" | "manual_review";
export type ComponentAction = "keep" | "remove";
export type ReceptorPreparationStatus = "selected" | "protonated" | "docking_ready";
export type ReceptorOutputStage = "selected" | "repaired" | "relaxed" | "protonated_pdb" | "protonated_pqr" | "meeko_input_pqr" | "pdbqt" | "pdbqt_rigid" | "pdbqt_flex";

export interface ResidueLocator {
  chain_id: string;
  residue_name: string;
  sequence_number: number;
  insertion_code: string;
}

/**
 * ADR-032 §2 — bounded receptor side-chain flexibility.
 *
 * `rigid` reproduces the frozen v0.1 behavior exactly and is the default, so a
 * rigid request omits the spec entirely rather than sending an empty one.
 */
export type ReceptorFlexMode = "rigid" | "sidechain_flex";

export interface ReceptorFlexRequest {
  mode: ReceptorFlexMode;
  flex_residues: ResidueLocator[];
}

/** The recorded, hash-bound identity of one immutable `mk_prepare_receptor -f` split. */
export interface ReceptorFlexSpec {
  mode: ReceptorFlexMode;
  flex_residues: ResidueLocator[];
  receptor_rigid_sha256: string;
  receptor_flex_sha256: string | null;
  added_chi_torsion_count: number;
}

export interface ReceptorIssue {
  issue_id: string;
  kind: ReceptorIssueKind;
  residue: ResidueLocator;
  missing_atoms: string[];
  alternate_locations: string[];
  distance_to_reference_angstrom: number | null;
  severity: ReceptorIssueSeverity;
  allowed_actions: ReceptorDecisionAction[];
  message: string;
}

export interface ReceptorComponent {
  component_id: string;
  name: string;
  chain_id: string;
  sequence_number: number | null;
  insertion_code: string;
  atom_count: number;
  kind: HeterogenKind;
}

export interface ReceptorInspectionReport {
  source_artifact_id: string;
  generated_at: string;
  candidate_chains: string[];
  components: ReceptorComponent[];
  water_count: number;
  issues: ReceptorIssue[];
  terminal_oxygen_candidates?: TerminalHeavyAtomAddition[];
  reference_component_id: string | null;
  near_reference_cutoff_angstrom: number;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
}

export interface ComponentDecision {
  component_id: string;
  action: ComponentAction;
}

export interface IssueDecision {
  issue_id: string;
  action: ReceptorDecisionAction;
  selected_altloc?: string | null;
}

export interface ProjectRecord {
  project_id: string;
  name: string;
  registered_at: string;
  migrated_legacy: boolean;
}

export interface ProjectCatalog {
  active_project_id: string;
  projects: ProjectRecord[];
}

export type DependencyNodeKind =
  | "structure"
  | "receptor"
  | "ligand"
  | "ligand_library"
  | "ligand_filter"
  | "chemical_state"
  | "conformer"
  | "ligand_preparation"
  | "binding_site"
  | "pocket_detection"
  | "autogrid_map_set"
  | "docking_campaign"
  | "validation"
  | "pose_analysis"
  | "export"
  | "unknown";

export interface ProjectDependencyNode {
  node_id: string;
  kind: DependencyNodeKind;
  label: string;
  relative_path: string;
  parent_ids: string[];
  unresolved_parent_ids: string[];
  stale: boolean;
  stale_reasons: string[];
}

export interface ProjectDependencyEdge {
  parent_id: string;
  child_id: string;
}

export interface ProjectDependencyGraph {
  project_id: string;
  generated_at: string;
  nodes: ProjectDependencyNode[];
  edges: ProjectDependencyEdge[];
  total_nodes: number;
  offset: number;
  limit: number;
  stale_count: number;
  unresolved_reference_count: number;
}

export interface MarkArtifactStaleResponse {
  marked_node_id: string;
  affected_node_ids: string[];
}

export interface TerminalHeavyAtomAddition {
  chain_id: string;
  residue_name: string;
  sequence_number: number;
  insertion_code: string;
  atom_name: "OXT";
}

export type ProtonationDecisionSource = "propka_prediction" | "scientist_override";

export interface ProtonationOverride {
  residue: ResidueLocator;
  state: string;
}

export interface ProtonationMetalContact {
  component_id: string;
  name: string;
  chain_id: string;
  sequence_number: number | null;
  insertion_code: string;
  distance_angstrom: number;
}

export interface ReceptorProtonationProposal {
  proposal_id: string;
  residue: ResidueLocator;
  group_label: string;
  group_type: string | null;
  predicted_pka: number;
  model_pka: number | null;
  buried_fraction: number | null;
  coupled_group: string | null;
  predicted_state: string;
  default_state: string;
  selected_state: string;
  output_state: string | null;
  allowed_states: string[];
  decision_source: ProtonationDecisionSource;
  distance_to_reference_angstrom: number | null;
  near_reference: boolean;
  nearby_metals: ProtonationMetalContact[];
  warnings: string[];
}

export interface ReceptorProtonationAnalysis {
  generated_at: string;
  input_sha256: string;
  target_ph: number;
  force_field: string;
  tool_version: string;
  proposals: ReceptorProtonationProposal[];
  reference_component_id: string | null;
  near_reference_cutoff_angstrom: number;
  metal_warning_cutoff_angstrom: number;
}

export interface ProtonationSettings {
  enabled: boolean;
  ph: number;
  force_field: string;
  authorized_terminal_heavy_atom_additions?: TerminalHeavyAtomAddition[];
  overrides?: ProtonationOverride[];
}

export interface RelaxationSettings {
  enabled: boolean;
  restraint_force_constant_kcal_mol_a2: number;
  max_iterations: number;
}

export interface ReceptorPreparationRequest {
  selected_chains: string[];
  water_action: ComponentAction;
  component_decisions: ComponentDecision[];
  issue_decisions: IssueDecision[];
  reference_component_id: string | null;
  relaxation: RelaxationSettings;
  protonation: ProtonationSettings;
  generate_pdbqt: boolean;
  repair_method?: "legacy" | "topology_guard_v3";
  repair_seed?: number;
  inspection_method?: "reported_only" | "templates_v1";
  /** Omitted entirely for a rigid receptor, preserving the exact v0.1 request. */
  flexibility?: ReceptorFlexRequest | null;
}

export interface ReceptorOutputArtifact {
  artifact_id: string;
  stage: ReceptorOutputStage;
  filename: string;
  format: string;
  sha256: string;
  size_bytes: number;
  created_at: string;
  content_url: string;
}

export interface ReceptorPreparationRecord {
  receptor_id: string;
  source_artifact_id: string;
  created_at: string;
  status: ReceptorPreparationStatus;
  decisions: ReceptorPreparationRequest;
  outputs: ReceptorOutputArtifact[];
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent[];
  display_output_artifact_id: string;
  protonation_analysis?: ReceptorProtonationAnalysis | null;
  flex_spec?: ReceptorFlexSpec | null;
  /** Atom types contributed by the moving side chains; AutoGrid4 needs their union. */
  flex_atom_types?: string[];
}

export type BindingSiteSource = "co_crystallized_ligand" | "selected_residues" | "manual" | "full_protein_blind" | "pocket_detected";

export interface BindingBox {
  center_x: number;
  center_y: number;
  center_z: number;
  size_x: number;
  size_y: number;
  size_z: number;
}

export interface LigandDerivedOrigin {
  heterogen: ResidueLocator;
  padding_angstrom: number;
}

export interface ResidueSelectionOrigin {
  residues: ResidueLocator[];
  padding_angstrom: number;
}

export interface PocketCandidate {
  pocket_id: string;
  rank: number;
  druggability_score: number | null;
  volume_angstrom3: number | null;
  box: BindingBox;
  lining_residues: ResidueLocator[];
}

export interface PocketDetectionReport {
  report_id: string;
  receptor_id: string;
  source_output_artifact_id: string;
  generated_at: string;
  tool: { name: string; version: string };
  candidates: PocketCandidate[];
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  execution?: {
    command: string[];
    exit_code: number;
    stdout: string;
    stderr: string;
    predictions_csv: string;
  } | null;
}

export interface PocketSelection {
  report_id: string;
  pocket_id: string;
}

export interface BindingSiteRequest {
  source: BindingSiteSource;
  ligand_origin: LigandDerivedOrigin | null;
  residue_selection: ResidueSelectionOrigin | null;
  manual_box: BindingBox | null;
  blind_margin_angstrom: number;
  acknowledge_exploratory_full_protein?: boolean;
  pocket_selection: PocketSelection | null;
  parent_binding_site_id: string | null;
}

export interface BindingSitePreview {
  receptor_id: string;
  source: BindingSiteSource;
  box: BindingBox;
  warnings: StructuredWarning[];
}

export interface BindingSiteRecord {
  binding_site_id: string;
  receptor_id: string;
  source_artifact_id: string;
  created_at: string;
  decisions: BindingSiteRequest;
  box: BindingBox;
  stale: boolean;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent[];
}

export type LigandSource = "crystallographic" | "local";
export type LigandFormat = "sdf" | "mol" | "smiles";

export interface LigandLocator {
  component_name: string;
  chain_id: string;
  sequence_number: number;
  insertion_code: string;
}

export interface LigandArtifact {
  ligand_id: string;
  source: LigandSource;
  source_structure_id: string | null;
  locator: LigandLocator | null;
  filename: string;
  format: LigandFormat;
  sha256: string;
  size_bytes: number;
  created_at: string;
  library_id: string | null;
  library_record_index: number | null;
}

export interface LigandInspection {
  name: string;
  formula: string;
  molecular_weight_g_mol: number | null;
  exact_mass_da: number | null;
  formal_charge: number;
  atom_count: number;
  heavy_atom_count: number;
  rotatable_bond_count: number;
  aromatic_ring_count: number;
  stereocenter_count: number;
  undefined_stereocenter_count: number;
  fragment_count: number;
  conformer_count: number;
  has_3d_coordinates: boolean;
  canonical_smiles: string | null;
}

export interface LigandChemicalStateArtifact {
  state_id: string;
  ligand_id: string;
  filename: string;
  format: "sdf";
  sha256: string;
  size_bytes: number;
  created_at: string;
}

export interface LigandRecord {
  artifact: LigandArtifact;
  state: LigandChemicalStateArtifact | null;
  inspection: LigandInspection;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  content_url: string;
  original_content_url: string | null;
}

export type LigandLibraryEntryStatus = "imported" | "failed";

export interface LigandLibraryArtifact {
  library_id: string;
  filename: string;
  format: LigandFormat;
  sha256: string;
  size_bytes: number;
  record_count: number;
  created_at: string;
}

/**
 * One imported library, described without any of its molecules.
 *
 * The same boundary the result catalog draws: this project's 38 libraries hold
 * 35.7 MiB of records between them, so a listing carries identity and counts
 * and the molecules stay behind their own request.
 */
export interface LigandLibrarySummary {
  artifact: LigandLibraryArtifact;
  /** Whether a selection was ever applied, and which one was last. */
  filter_run_count: number;
  latest_filter_run_id: string | null;
}

export interface LigandLibraryPage {
  libraries: LigandLibrarySummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface LigandLibraryEntryFailure {
  code: string;
  message: string;
}

export interface LigandLibraryEntry {
  record_index: number;
  status: LigandLibraryEntryStatus;
  ligand: LigandRecord | null;
  failure: LigandLibraryEntryFailure | null;
}

export interface LigandLibraryRecord {
  artifact: LigandLibraryArtifact;
  entries: LigandLibraryEntry[];
  imported_count: number;
  failed_count: number;
  provenance: ProvenanceEvent;
  original_content_url: string;
}

export type LigandPreparationStatus = "needs_decision" | "generating" | "minimized" | "nonconverged" | "prepared" | "failed";

export interface LigandPreparationEntry {
  ligand_id: string;
  parent_compound_id?: string | null;
  chemical_state_id?: string | null;
  chemical_state_formal_charge?: number | null;
  status: LigandPreparationStatus;
  conformer_id: string | null;
  pdbqt_preparation_id: string | null;
  initial_energy_kcal_mol: number | null;
  final_energy_kcal_mol: number | null;
  error_message: string | null;
  updated_at: string;
}

export interface LigandLibraryPreparationRecord {
  library_id: string;
  updated_at: string;
  entries: Record<string, LigandPreparationEntry>;
}

export type LigandAlertPolicy = "ignore" | "review" | "exclude";
export type LigandDuplicatePolicy = "keep" | "review" | "exclude";
export type LigandFilterDisposition = "eligible" | "excluded" | "needs_decision";

// Mirrors LigandFilterDescriptors' field names exactly, so a custom rule's
// descriptor value can be looked up with descriptors[rule.descriptor].
export type LigandCustomRuleDescriptor =
  | "molecular_weight_g_mol"
  | "clogp"
  | "hydrogen_bond_donors"
  | "hydrogen_bond_acceptors"
  | "tpsa_angstrom2"
  | "rotatable_bonds"
  | "molar_refractivity"
  | "total_atom_count_with_hydrogens"
  | "carbon_atom_count"
  | "hetero_atom_count"
  | "ring_count"
  | "qed";

export type LigandCustomRuleOperator = "lt" | "lte" | "gt" | "gte" | "eq" | "between";

export interface LigandCustomFilterRule {
  rule_id: string;
  label: string;
  descriptor: LigandCustomRuleDescriptor;
  operator: LigandCustomRuleOperator;
  value: number;
  value_upper: number | null;
  required: boolean;
}

export interface LigandLibraryFilterPlan {
  preset: "general_oral" | "custom";
  require_lipinski: boolean;
  max_lipinski_violations: number;
  require_veber: boolean;
  require_ghose: boolean;
  require_muegge: boolean;
  minimum_qed: number | null;
  pains_policy: LigandAlertPolicy;
  brenk_policy: LigandAlertPolicy;
  duplicate_policy: LigandDuplicatePolicy;
  custom_rules: LigandCustomFilterRule[];
}

export interface LigandLibraryFilterRequest {
  plan: LigandLibraryFilterPlan;
  microstate_plan: LigandMicrostatePlan;
  state_overrides: Record<string, string>;
}

export interface ApplyLigandLibraryFilterRequest extends LigandLibraryFilterRequest {
  acknowledge_selection: boolean;
}

export interface LigandFilterDescriptors {
  molecular_weight_g_mol: number;
  clogp: number;
  hydrogen_bond_donors: number;
  hydrogen_bond_acceptors: number;
  tpsa_angstrom2: number;
  rotatable_bonds: number;
  molar_refractivity: number;
  total_atom_count_with_hydrogens: number;
  carbon_atom_count: number;
  hetero_atom_count: number;
  ring_count: number;
  qed: number;
}

export interface LigandRuleEvaluation {
  passed: boolean;
  violations: string[];
}

export interface LigandStructuralAlert {
  catalog: "PAINS" | "BRENK";
  description: string;
  atom_indices: number[];
}

export interface LigandCustomRuleResult {
  rule_id: string;
  label: string;
  required: boolean;
  passed: boolean;
  value: number;
}

export interface LigandFilterEvaluation {
  ligand_id: string;
  record_index: number;
  state_id: string;
  canonical_isomeric_smiles: string | null;
  descriptors: LigandFilterDescriptors | null;
  lipinski: LigandRuleEvaluation | null;
  veber: LigandRuleEvaluation | null;
  ghose: LigandRuleEvaluation | null;
  muegge: LigandRuleEvaluation | null;
  custom_rule_results: LigandCustomRuleResult[];
  alerts: LigandStructuralAlert[];
  duplicate_of_ligand_id: string | null;
  disposition: LigandFilterDisposition;
  reasons: string[];
}

export interface LigandFilterSummary {
  imported_count: number;
  eligible_count: number;
  excluded_count: number;
  needs_decision_count: number;
  duplicate_count: number;
  pains_match_count: number;
  brenk_match_count: number;
}

export interface LigandLibraryFilterPreview {
  library_id: string;
  plan: LigandLibraryFilterPlan;
  microstate_plan?: LigandMicrostatePlan;
  evaluations: LigandFilterEvaluation[];
  summary: LigandFilterSummary;
  rdkit_version: string;
  worker_count: number;
}

export interface LigandFilterRunArtifact {
  filter_run_id: string;
  library_id: string;
  filename: "selection_manifest.json";
  sha256: string;
  size_bytes: number;
  created_at: string;
}

export interface LigandLibraryFilterRun {
  artifact: LigandFilterRunArtifact;
  plan: LigandLibraryFilterPlan;
  microstate_plan?: LigandMicrostatePlan;
  evaluations: LigandFilterEvaluation[];
  summary: LigandFilterSummary;
  selected_ligand_ids: string[];
  rdkit_version: string;
  worker_count: number;
  provenance: ProvenanceEvent;
  manifest_content_url: string;
}

export interface LigandComponentOption {
  index: number;
  formula: string;
  formal_charge: number;
  heavy_atom_count: number;
  canonical_smiles: string;
}

export interface LigandStereoisomerOption {
  index: number;
  canonical_isomeric_smiles: string;
}

export interface LigandStateResolutionOptions {
  parent_state_id: string;
  component_options: LigandComponentOption[];
  selected_component_index: number | null;
  stereoisomer_options: LigandStereoisomerOption[];
  component_selection_required: boolean;
  stereoisomer_selection_required: boolean;
}

export interface ResolveLigandStateRequest {
  parent_state_id: string;
  component_index: number;
  stereoisomer_index: number | null;
}

export interface LigandStateSelection {
  component_index: number;
  source_fragment_count: number;
  stereoisomer_index: number | null;
  stereoisomer_count: number;
}

export interface LigandChemicalStateRecord {
  artifact: LigandChemicalStateArtifact;
  parent_state_id: string;
  inspection: LigandInspection;
  selection: LigandStateSelection;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  content_url: string;
}

export interface LigandProtonationCandidate {
  index: number;
  canonical_smiles: string;
  formal_charge: number;
}

export interface LigandProtonationOptions {
  parent_state_id: string;
  ph_min: number;
  ph_max: number;
  precision: number;
  candidates: LigandProtonationCandidate[];
  selection_required: boolean;
}

export interface ResolveLigandProtonationRequest {
  parent_state_id: string;
  ph_min: number;
  ph_max: number;
  precision: number;
  candidate_index: number;
}

export interface LigandProtonationSelection {
  candidate_index: number;
  candidate_count: number;
  ph_min: number;
  ph_max: number;
  precision: number;
}

export interface LigandProtonationRecord {
  artifact: LigandChemicalStateArtifact;
  parent_state_id: string;
  inspection: LigandInspection;
  selection: LigandProtonationSelection;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  content_url: string;
}

export type LigandMicrostateMode = "exact_imported_state" | "enumerated_selection";

export interface LigandMicrostatePlan {
  mode: LigandMicrostateMode;
  ph_min: number;
  ph_max: number;
  precision: number;
  max_tautomers_per_protomer: number;
  max_microstates_per_parent: number;
}

export interface LigandMicrostateCandidate {
  index: number;
  microstate_key: string;
  canonical_isomeric_smiles: string;
  formal_charge: number;
  protonation_candidate_index: number;
  tautomer_index: number;
  matches_parent_state: boolean;
}

export interface LigandMicrostateOptions {
  parent_state_id: string;
  plan: LigandMicrostatePlan;
  candidates: LigandMicrostateCandidate[];
  protonation_candidate_count: number;
  enumerated_candidate_count: number;
  truncated: boolean;
  dimorphite_version: string;
  rdkit_version: string;
}

export interface ResolveLigandMicrostateRequest {
  parent_state_id: string;
  plan: LigandMicrostatePlan;
  candidate_index: number;
  acknowledge_bounded_enumeration: boolean;
}

export interface LigandMicrostateSelection {
  candidate_index: number;
  candidate_count: number;
  microstate_key: string;
  protonation_candidate_index: number;
  tautomer_index: number;
  plan: LigandMicrostatePlan;
  enumeration_truncated: boolean;
}

export interface LigandMicrostateRecord {
  artifact: LigandChemicalStateArtifact;
  parent_state_id: string;
  inspection: LigandInspection;
  selection: LigandMicrostateSelection;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  content_url: string;
}

export type LigandForceField = "MMFF94" | "MMFF94s";

export interface MinimizeLigandRequest {
  force_field: LigandForceField;
  max_iterations: number;
  acknowledge_current_chemical_state: boolean;
  state_id?: string | null;
}

export interface GenerateLigandConformerRequest extends MinimizeLigandRequest {
  random_seed: number;
  /** Informational only: how many of these requests we're issuing concurrently
   * this batch run, recorded into provenance. The server never uses this to
   * size its own execution. */
  client_concurrency_hint?: number | null;
}

export interface LigandConformerArtifact {
  conformer_id: string;
  ligand_id: string;
  stage: "minimized" | "generated_minimized";
  filename: string;
  format: "sdf";
  sha256: string;
  size_bytes: number;
  created_at: string;
  chemical_state_id?: string | null;
}

export interface LigandMinimizationResult {
  force_field: LigandForceField;
  max_iterations: number;
  converged: boolean;
  initial_energy_kcal_mol: number;
  final_energy_kcal_mol: number;
  embedding_method: string | null;
  random_seed: number | null;
  independent_from_source_coordinates: boolean;
  conformer_pool_size: number | null;
  conformer_pool_converged_count?: number | null;
  conformer_selection_policy?:
    | "lowest_energy_converged"
    | "lowest_energy_nonconverged_fallback"
    | null;
}

export interface LigandConformerRecord {
  artifact: LigandConformerArtifact;
  inspection: LigandInspection;
  minimization: LigandMinimizationResult;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  content_url: string;
}

export type LigandChargeModel = "gasteiger";

/**
 * ADR-032 §1.1 — an explicit, recorded two-valued choice with no silent
 * substitution. `flexible_pseudoatoms` samples ring conformations through
 * Meeko's `CG0`/`G0` glue pseudoatoms and stays engine-incompatible with the
 * whole AutoDock4 family; `rigid_input_conformation` surrenders that sampling
 * to keep the prepared input ring and emits no pseudoatoms at all.
 */
export type MacrocyclePolicy = "flexible_pseudoatoms" | "rigid_input_conformation";

export interface LigandFlexibilitySpec {
  macrocycle_policy: MacrocyclePolicy;
  rigidified_smarts: string[];
  rigidified_bond_indices: [number, number][];
  flexible_amides: boolean;
  local_only_refinement: boolean;
}

/**
 * What one `--rigidify_bonds_smarts` pattern actually matched (ADR-032 A2).
 *
 * Meeko exits 0 on a pattern that matches nothing, so Ankora owns the
 * pre-match and reports a zero match count rather than leaving it invisible.
 */
export interface LigandSmartsRigidificationOutcome {
  smarts: string;
  bond_indices: [number, number];
  match_count: number;
  matched_bonds_zero_based?: [number, number][];
  applied: boolean;
}

export interface PrepareLigandPdbqtRequest {
  charge_model: LigandChargeModel;
  /** Informational only: how many of these requests we're issuing concurrently
   * this batch run, recorded into provenance. The server never uses this to
   * size its own execution. */
  client_concurrency_hint?: number | null;
  /** Omitted entirely at default rigid/standard behavior, preserving v0.1. */
  flexibility?: LigandFlexibilitySpec | null;
}

export interface LigandPdbqtArtifact {
  preparation_id: string;
  ligand_id: string;
  conformer_id: string;
  filename: string;
  format: "pdbqt";
  sha256: string;
  size_bytes: number;
  created_at: string;
}

export interface LigandPdbqtRecord {
  artifact: LigandPdbqtArtifact;
  charge_model: LigandChargeModel;
  tool: { name: string; version: string };
  command: string[];
  stdout: string;
  stderr: string;
  provenance: ProvenanceEvent;
  content_url: string;
  flexibility?: LigandFlexibilitySpec | null;
  /** The TORSDOF actually present in the produced PDBQT (ADR-032 §1.4). */
  effective_torsdof?: number | null;
  atom_types?: string[];
  warnings?: StructuredWarning[];
  smarts_rigidification_outcomes?: LigandSmartsRigidificationOutcome[];
}

export interface LigandDockingInput {
  ligand_id: string;
  conformer: LigandConformerRecord | null;
  pdbqt: LigandPdbqtRecord | null;
}

export interface LigandLibraryDockingInput {
  library_id: string;
  library_name: string;
  filter_run_id: string;
  selection_manifest_sha256: string;
  selected_count: number;
  prepared_count: number;
}

/** Explicit Vina 1.2.7 scoring-function selection (ADR-032 / M1). */
export type VinaScoringFunction = "vina" | "vinardo";

export interface VinaDockingParameters {
  sampling_protocol?: "screening" | "pose_refinement" | "custom" | null;
  /** Omitted when "vina", preserving the exact v0.1 parameter shape. */
  scoring?: VinaScoringFunction;
  cpu_threads: number;
  seed: number;
  exhaustiveness: number;
  num_modes: number;
  min_rmsd_angstrom: number;
  energy_range_kcal_mol: number;
  timeout_minutes: number;
}

export interface VinaDockingRequest {
  receptor_id: string;
  binding_site_id: string;
  ligand_id: string;
  ligand_preparation_id: string;
  parameters: VinaDockingParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export interface VinaBatchDockingParameters {
  sampling_protocol?: "screening" | "pose_refinement" | "custom" | null;
  /** Omitted when "vina", preserving the exact v0.1 parameter shape. */
  scoring?: VinaScoringFunction;
  total_cpu_threads: number;
  parallel_ligands: number;
  seed: number;
  exhaustiveness: number;
  num_modes: number;
  min_rmsd_angstrom: number;
  energy_range_kcal_mol: number;
  timeout_minutes_per_ligand: number;
}

export interface VinaBatchDockingRequest {
  receptor_id: string;
  binding_site_id: string;
  library_id: string;
  filter_run_id: string;
  parameters: VinaBatchDockingParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export type DockingJobStatus = "queued" | "running" | "cancel_requested" | "canceled" | "completed" | "failed";
export type DockingJobPhase = "queued" | "validating" | "docking" | "parsing_poses" | "complete";

export type GninaCnnScoringMode = "rescore" | "refinement";
export type GninaCnnModelSelector = "dense_1_3" | "default_1_3_ensemble" | "default1.0";

export interface GninaCnnModelIdentity {
  selector: GninaCnnModelSelector;
  cli_argument: string | null;
  member_names: string[];
  member_count: number;
}

export interface GninaDockingParameters {
  compute: "cpu" | "cuda";
  device_index: number;
  cpu_threads: number;
  seed: number;
  exhaustiveness: number;
  num_modes: number;
  min_rmsd_filter_angstrom: number;
  timeout_minutes: number;
  cnn_scoring: GninaCnnScoringMode;
  cnn_model: GninaCnnModelSelector;
  hydrogen_handling: "prepared_pdbqt_no_add_no_strip";
  pose_sort_order: "cnn_score_descending";
}

export interface GninaDockingRequest {
  receptor_id: string;
  binding_site_id: string;
  ligand_id: string;
  ligand_preparation_id: string;
  parameters: GninaDockingParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export type GninaCnnVsSource = "engine_emitted" | "derived_from_recorded_axes";
export type GninaHitRankingMetric = "cnn_score" | "cnn_vs";

export interface GninaPoseArtifact extends PoseFlexIdentity {
  artifact_id: string;
  mode: number;
  filename: string;
  sha256: string;
  size_bytes: number;
  content_url?: string | null;
}

export interface GninaPoseResult {
  mode: number;
  minimized_affinity_kcal_mol: number;
  cnn_score: number;
  cnn_affinity: number;
  cnn_vs?: number | null;
  cnn_vs_source?: GninaCnnVsSource | null;
  cnn_affinity_variance?: number | null;
  artifact: GninaPoseArtifact;
}

export interface GninaDockingJobRecord {
  job_id: string;
  engine: "gnina";
  screening_campaign_id?: string | null;
  status: DockingJobStatus;
  phase: DockingJobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: GninaDockingRequest;
  tool: { version: string; sha256: string; architecture: "x86_64" };
  cnn_model_identity?: GninaCnnModelIdentity | null;
  box: BindingBox;
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  receptor_flex_mode?: ReceptorFlexMode;
  receptor_flex_output_artifact_id?: string | null;
  receptor_flex_sha256?: string | null;
  flex_residues?: ResidueLocator[];
  ligand_sha256: string;
  conformer_sha256: string;
  command: string[];
  execution: (DockingExecutionEvidence & {
    gpu_process_observed: boolean;
    gpu_observation: string | null;
    requested_gpu_uuid: string | null;
    observed_gpu_uuid: string | null;
  }) | null;
  poses: GninaPoseResult[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
}

// --- GNINA library screening campaigns (Linux only, ADR-027) ---------------

/**
 * A campaign entry is a reference, not a result.
 *
 * The backend contract deliberately keeps no CNN score, no CNN affinity, no
 * minimized affinity and no pose on an entry: the individual GNINA job named by
 * `gnina_job_id` already owns them with its own inputs, command and evidence.
 * Anything this interface gained would be a second, unverifiable account of a
 * scientific result, so scores are read from the job instead.
 *
 * `source_index` is library provenance only. It is absent when the library
 * record could not be resolved and must never be used to order entries - the
 * campaign's own order is selection order.
 */
export interface GninaScreeningEntry {
  ligand_id: string;
  chemical_state_id: string | null;
  source_index: number | null;
  name: string | null;
  ligand_preparation_id: string | null;
  ligand_sha256: string | null;
  conformer_id: string | null;
  conformer_sha256: string | null;
  status: DockingJobStatus;
  phase: DockingJobPhase;
  /** Recorded, not verified: the job this campaign claims as the attempt. */
  gnina_job_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  revision: number;
}

/** The immutable identity of the applied filter selection being docked. */
export interface GninaScreeningSelection {
  library_id: string;
  filter_run_id: string;
  manifest_artifact_id: string;
  manifest_sha256: string;
}

export interface GninaScreeningRequest {
  receptor_id: string;
  binding_site_id: string;
  library_id: string;
  filter_run_id: string;
  /** The single-job parameters unchanged; GNINA settings stay GNINA-specific. */
  parameters: GninaDockingParameters;
  hit_ranking_metric?: GninaHitRankingMetric;
  acknowledge_inputs_and_scoring: boolean;
}

/** The campaign header without its entries, for polling while it runs. */
export interface GninaScreeningProgress {
  campaign_id: string;
  engine: "gnina";
  status: DockingJobStatus;
  phase: DockingJobPhase;
  revision: number;
  started_at: string | null;
  completed_at: string | null;
  selected_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  warnings?: StructuredWarning[];
}

export interface GninaScreeningCampaignRecord {
  campaign_id: string;
  engine: "gnina";
  status: DockingJobStatus;
  phase: DockingJobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: GninaScreeningRequest;
  hit_ranking_metric?: GninaHitRankingMetric;
  tool: { version: string; sha256: string; architecture: "x86_64" };
  cnn_model_identity?: GninaCnnModelIdentity | null;
  selection: GninaScreeningSelection;
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  box: BindingBox;
  /** One job at a time: a recorded fact of the run, not a setting. */
  worker_count: number;
  selected_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  /** The applied selection, in selection order. */
  entries: GninaScreeningEntry[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
  revision: number;
}

/**
 * ADR-032 §4 `E8` — under `sidechain_flex` a pose is a coupled complex, so its
 * identity carries the moved side chains alongside the ligand coordinates.
 * Rigid poses leave every field absent and take the frozen-baseline path.
 */
export interface PoseFlexIdentity {
  flex_filename?: string | null;
  pose_flex_sidechains_sha256?: string | null;
  flex_content_url?: string | null;
  pose_complex_identity_sha256?: string | null;
}

export interface DockingPoseArtifact extends PoseFlexIdentity {
  artifact_id: string;
  mode: number;
  filename: string;
  format: "pdbqt";
  sha256: string;
  size_bytes: number;
  content_url: string;
}

export interface DockingPoseResult {
  mode: number;
  affinity_kcal_mol: number;
  rmsd_lower_bound_angstrom: number;
  rmsd_upper_bound_angstrom: number;
  artifact: DockingPoseArtifact;
}

export interface DockingExecutionEvidence {
  command: string[];
  exit_code: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
  canceled: boolean;
}

export interface VinaDockingJobRecord {
  job_id: string;
  engine: "autodock_vina";
  status: DockingJobStatus;
  phase: DockingJobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: VinaDockingRequest;
  tool: { name: string; version: string };
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  receptor_flex_mode?: ReceptorFlexMode;
  receptor_flex_output_artifact_id?: string | null;
  receptor_flex_sha256?: string | null;
  flex_residues?: ResidueLocator[];
  ligand_sha256: string;
  command: string[];
  execution: DockingExecutionEvidence | null;
  poses: DockingPoseResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
}

export interface VinaBatchLigandResult {
  ligand_id: string;
  parent_compound_id?: string | null;
  chemical_state_id?: string | null;
  chemical_state_formal_charge?: number | null;
  source_index: number;
  name: string;
  canonical_smiles: string | null;
  molecular_weight_g_mol: number | null;
  preparation_initial_energy_kcal_mol: number | null;
  preparation_energy_kcal_mol: number | null;
  ligand_preparation_id: string | null;
  ligand_sha256: string | null;
  status: DockingJobStatus;
  phase: DockingJobPhase;
  started_at: string | null;
  completed_at: string | null;
  command: string[];
  execution: DockingExecutionEvidence | null;
  poses: DockingPoseResult[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
  revision: number;
}

export interface VinaBatchDockingRecord {
  batch_id: string;
  engine: "autodock_vina";
  status: DockingJobStatus;
  phase: DockingJobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: VinaBatchDockingRequest;
  tool: { name: string; version: string };
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  selection_manifest_artifact_id: string;
  selection_manifest_sha256: string;
  selected_count: number;
  worker_count: number;
  threads_per_ligand: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  entries: VinaBatchLigandResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
  revision: number;
}

export interface VinaBatchProgress {
  batch_id: string;
  status: DockingJobStatus;
  phase: DockingJobPhase;
  revision: number;
  started_at: string | null;
  completed_at: string | null;
  selected_count: number;
  worker_count: number;
  threads_per_ligand: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  entries: VinaBatchLigandResult[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
}

export interface DockingCancelResponse {
  job_id: string;
  status: DockingJobStatus;
}

export interface DockingBatchCancelResponse {
  batch_id: string;
  status: DockingJobStatus;
}

/**
 * ADR-032 §1.5 — `--local_only` refinement exists only as an explicit,
 * traceable derivative of an already recorded pose. The parent job and parent
 * pose are never mutated (ADR-004); creating one writes a new record.
 */
export interface VinaLocalRefinementRequest {
  parent_job_id: string;
  parent_pose_artifact_id: string;
  scoring?: VinaScoringFunction;
  cpu_threads?: number;
  seed?: number;
  timeout_minutes?: number;
}

export interface VinaLocalRefinementRecord {
  refinement_id: string;
  created_at: string;
  parent_job_id: string;
  parent_pose_artifact_id: string;
  parent_pose_sha256: string;
  parent_pose_flex_sha256?: string | null;
  receptor_id: string;
  binding_site_id: string;
  ligand_id: string;
  ligand_preparation_id: string;
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  receptor_flex_mode?: ReceptorFlexMode;
  flex_residues?: ResidueLocator[];
  scoring: VinaScoringFunction;
  tool: { name: string; version: string };
  command: string[];
  estimated_free_energy_kcal_mol: number;
  intermolecular_kcal_mol?: number | null;
  total_internal_kcal_mol?: number | null;
  torsional_free_energy_kcal_mol?: number | null;
  unbound_system_energy_kcal_mol?: number | null;
  refined_pose: DockingPoseArtifact;
  execution: DockingExecutionEvidence;
  provenance: ProvenanceEvent;
}

export interface GninaLocalRefinementRequest {
  parent_job_id: string;
  parent_pose_artifact_id: string;
  compute?: "cpu" | "cuda";
  device_index?: number;
  cpu_threads?: number;
  seed?: number;
  cnn_scoring?: GninaCnnScoringMode;
  cnn_model?: GninaCnnModelSelector;
  timeout_minutes?: number;
}

export interface GninaLocalRefinementRecord {
  refinement_id: string;
  created_at: string;
  parent_job_id: string;
  parent_pose_artifact_id: string;
  parent_pose_sha256: string;
  parent_pose_flex_sha256?: string | null;
  receptor_id: string;
  binding_site_id: string;
  ligand_id: string;
  ligand_preparation_id: string;
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  receptor_flex_mode?: ReceptorFlexMode;
  flex_residues?: ResidueLocator[];
  tool: { version: string; sha256: string; architecture: "x86_64" };
  cnn_model_identity?: GninaCnnModelIdentity | null;
  command: string[];
  minimized_affinity_kcal_mol: number;
  cnn_score?: number | null;
  cnn_affinity?: number | null;
  cnn_vs?: number | null;
  cnn_vs_source?: GninaCnnVsSource | null;
  cnn_affinity_variance?: number | null;
  refined_pose: GninaPoseArtifact;
  execution: DockingExecutionEvidence;
}

export interface ErrorResponse {
  code: string;
  stage: string;
  message: string;
  details: Record<string, unknown>;
  recoverable: boolean;
}

// --- AutoGrid immutable map sets (ADR-015 Phase 1) ---

export type AutoGridLigandSource = "ligand_preparation" | "filter_run";
export type AutoGridMapKind =
  | "affinity" | "electrostatic" | "desolvation" | "field"
  | "grid_points" | "receptor" | "grid_parameter_file" | "grid_log";
export type AutoGridJobStatus =
  | "queued" | "running" | "cancel_requested" | "canceled" | "completed" | "failed";
export type AutoGridJobPhase =
  | "queued" | "generating_maps" | "collecting_artifacts" | "complete";

export interface AutoGridParameters {
  spacing_angstrom: number;
  smoothing_angstrom: number;
  dielectric: number;
  timeout_minutes: number;
}

export interface AutoGridMapSetRequest {
  receptor_id: string;
  binding_site_id: string;
  source: AutoGridLigandSource;
  ligand_id?: string | null;
  ligand_preparation_id?: string | null;
  library_id?: string | null;
  filter_run_id?: string | null;
  parameters?: AutoGridParameters;
}

export interface AutoGridGeometry {
  spacing_angstrom: number;
  /** Grid intervals per axis. AutoGrid writes `npts + 1` points. */
  npts: [number, number, number];
  requested_size_angstrom: [number, number, number];
  realized_size_angstrom: [number, number, number];
}

export interface AutoGridLigandPreflightRow {
  ligand_id: string;
  source_index: number;
  name: string;
  compatible: boolean;
  atom_types: string[];
  reason: string | null;
}

export interface AutoGridPreflight {
  receptor_atom_types: string[];
  ligand_atom_types: string[];
  selected_count: number;
  prepared_count: number;
  compatible_count: number;
  incompatible_count: number;
  ligands: AutoGridLigandPreflightRow[];
}

export interface AutoGridMapArtifact {
  artifact_id: string;
  kind: AutoGridMapKind;
  atom_type: string | null;
  filename: string;
  sha256: string;
  size_bytes: number;
  content_url: string;
}

export interface AutoGridToolIdentity {
  tool: { name: string; version: string };
  executable_path: string;
  sha256: string;
  architecture: string | null;
  max_receptor_types: number;
  max_ligand_types: number;
  max_maps: number;
  max_grid_points: number;
}

export interface AutoGridExecutionEvidence {
  command: string[];
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_seconds: number;
  successful_completion_logged: boolean;
}

export interface AutoGridMapSetRecord {
  map_set_id: string;
  identity_key: string;
  created_at: string;
  request: AutoGridMapSetRequest;
  receptor_id: string;
  receptor_output_artifact_id: string;
  receptor_sha256: string;
  binding_site_id: string;
  box: BindingBox;
  geometry: AutoGridGeometry;
  preflight: AutoGridPreflight;
  autogrid: AutoGridToolIdentity;
  gpf_sha256: string;
  field_artifact_id: string;
  execution: AutoGridExecutionEvidence;
  artifacts: AutoGridMapArtifact[];
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
}

export interface AutoGridMapJobRecord {
  job_id: string;
  status: AutoGridJobStatus;
  phase: AutoGridJobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: AutoGridMapSetRequest;
  identity_key: string;
  geometry: AutoGridGeometry;
  preflight: AutoGridPreflight;
  autogrid: AutoGridToolIdentity;
  map_set_id: string | null;
  reused_existing_map_set: boolean;
  evidence_directory: string | null;
  execution: AutoGridExecutionEvidence | null;
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
}

export interface AutoGridJobCancelResponse {
  job_id: string;
  status: AutoGridJobStatus;
}

// --- AutoDock4 CPU docking (ADR-015 Phase 2) ---

export type AutoDock4JobStatus =
  | "queued" | "running" | "cancel_requested" | "canceled" | "completed" | "failed";
export type AutoDock4JobPhase = "queued" | "docking" | "parsing_results" | "complete";

export interface AutoDock4DockingParameters {
  ga_runs: number;
  ga_population_size: number;
  ga_energy_evaluations: number;
  ga_generations: number;
  cluster_rmsd_tolerance_angstrom: number;
  seed_1: number;
  seed_2: number;
  timeout_minutes: number;
}

export interface AutoDock4DockingRequest {
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  ligand_id: string;
  ligand_preparation_id: string;
  parameters: AutoDock4DockingParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export interface AutoDock4ToolIdentity {
  tool: { name: string; version: string };
  executable_path: string;
  sha256: string;
  architecture: string | null;
  max_torsions: number;
  max_atoms: number;
  max_maps: number;
}

export interface AutoDock4PoseArtifact extends PoseFlexIdentity {
  artifact_id: string;
  run: number;
  filename: string;
  format: "pdbqt";
  sha256: string;
  size_bytes: number;
  content_url: string;
}

export interface AutoDock4RunResult {
  run: number;
  cluster_rank: number;
  sub_rank: number;
  binding_energy_kcal_mol: number;
  cluster_rmsd_angstrom: number;
  reference_rmsd_angstrom: number;
  artifact: AutoDock4PoseArtifact;
}

export interface AutoDock4ClusterResult {
  cluster_rank: number;
  lowest_binding_energy_kcal_mol: number;
  mean_binding_energy_kcal_mol: number;
  /** How many independent runs converged here: evidence of reproducibility. */
  run_count: number;
  representative_run: number;
  runs: number[];
}

export interface AutoDock4ExecutionEvidence {
  command: string[];
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_seconds: number;
  successful_completion_logged: boolean;
  canceled: boolean;
  timed_out: boolean;
}

export interface AutoDock4DockingJobRecord {
  job_id: string;
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: AutoDock4DockingRequest;
  autodock4: AutoDock4ToolIdentity;
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  map_set_identity_key: string;
  ligand_sha256: string;
  ligand_atom_types: string[];
  ligand_atom_count: number;
  torsional_degrees_of_freedom: number;
  dpf_sha256: string | null;
  command: string[];
  execution: AutoDock4ExecutionEvidence | null;
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
}

export interface AutoDock4CancelResponse {
  job_id: string;
  status: AutoDock4JobStatus;
}

export interface AutoDock4BatchParameters extends AutoDock4DockingParameters {
  /** AutoDock4 4.2.6 is single-threaded, so this pool is the whole CPU budget. */
  parallel_ligands: number;
}

export interface AutoDock4BatchRequest {
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  library_id: string;
  filter_run_id: string;
  parameters: AutoDock4BatchParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export interface AutoDock4BatchLigandResult {
  ligand_id: string;
  parent_compound_id?: string | null;
  chemical_state_id?: string | null;
  chemical_state_formal_charge?: number | null;
  source_index: number;
  name: string;
  canonical_smiles: string | null;
  molecular_weight_g_mol: number | null;
  ligand_preparation_id: string | null;
  ligand_sha256: string | null;
  ligand_atom_types: string[];
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  started_at: string | null;
  completed_at: string | null;
  command: string[];
  dpf_sha256: string | null;
  execution: AutoDock4ExecutionEvidence | null;
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
  revision: number;
}

export interface AutoDock4BatchRecord {
  batch_id: string;
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: AutoDock4BatchRequest;
  autodock4: AutoDock4ToolIdentity;
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  map_set_identity_key: string;
  selection_manifest_sha256: string;
  selected_count: number;
  worker_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  entries: AutoDock4BatchLigandResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
  revision: number;
}

export interface AutoDock4BatchProgress {
  batch_id: string;
  status: AutoDock4JobStatus;
  revision: number;
  selected_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  running_ligand_ids: string[];
}

// --- Vina / AutoDock4 side-by-side comparison (ADR-015 item 4) ---
// The two engines' scores are never combined: different scoring functions on
// different scales. Only their rankings are compared.

export interface EngineComparisonRow {
  ligand_id: string;
  source_index: number;
  name: string;
  canonical_smiles: string | null;
  vina_best_score_kcal_mol: number | null;
  vina_rank: number | null;
  autodock4_best_energy_kcal_mol: number | null;
  autodock4_rank: number | null;
  autodock4_top_cluster_run_count: number | null;
  rank_difference: number | null;
  docked_by_both: boolean;
}

export interface RankAgreement {
  comparable_count: number;
  /** Agreement between two orderings, never a score for any molecule. */
  spearman_rho: number | null;
  top_n: number;
  top_n_overlap: number;
  top_n_shared_ligand_ids: string[];
}

export interface EngineComparison {
  generated_at: string;
  receptor_id: string;
  binding_site_id: string;
  library_id: string;
  filter_run_id: string;
  selection_manifest_sha256: string;
  vina_batch_id: string;
  vina_version: string;
  autodock4_batch_id: string;
  autodock4_version: string;
  selected_count: number;
  docked_by_both_count: number;
  vina_only_count: number;
  autodock4_only_count: number;
  docked_by_neither_count: number;
  agreement: RankAgreement;
  rows: EngineComparisonRow[];
}

/**
 * One screening campaign that exists on disk, described without its results.
 *
 * A completed campaign record carries every pose of every molecule and is
 * measured in megabytes, so listing what a project has run must not download
 * all of it. `best_result_kcal_mol` is that campaign's own engine's own number:
 * Vina's empirical score and AutoDock4's binding energy are on different
 * scales and are never shown in one column.
 */
export interface CampaignSummary {
  batch_id: string;
  engine: "autodock_vina" | "autodock4";
  engine_version: string;
  status: string;
  is_running: boolean;
  created_at: string;
  completed_at: string | null;
  receptor_id: string;
  binding_site_id: string;
  /** False when this campaign used another site record defining the same box. */
  same_site_record: boolean;
  library_id: string;
  filter_run_id: string;
  selection_manifest_sha256: string;
  selected_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  best_result_kcal_mol: number | null;
  best_ligand_name: string | null;
}

export interface CampaignHistory {
  engine: "autodock_vina" | "autodock4";
  receptor_id: string;
  binding_site_id: string;
  campaigns: CampaignSummary[];
}

/**
 * AutoDock4's two execution backends.
 *
 * The same semi-empirical scoring function reached by different searches -
 * Solis-Wets on the CPU, ADADELTA on the GPU - so results are never pooled and
 * every record says which produced it.
 */
export type AutoDockBackend = "autodock4_cpu" | "autodock_gpu";

/** Only the local-search methods that actually run in the OpenCL build. */
export type AutoDockGpuLocalSearch = "ad" | "sw" | "fire";

export interface AutoDockGpuDockingParameters {
  runs: number;
  population_size: number;
  energy_evaluations: number;
  /** The tool's ligand-based automatic evaluation count. */
  heuristics: boolean;
  /** Converges out early on an energy standard-deviation tolerance. */
  autostop: boolean;
  local_search_method: AutoDockGpuLocalSearch;
  cluster_rmsd_tolerance_angstrom: number;
  seed_1: number;
  seed_2: number;
  seed_3: number;
  device_number: number;
  timeout_minutes: number;
}

/** A campaign is one invocation, so there is no per-ligand parallelism knob. */
export type AutoDockGpuBatchParameters = AutoDockGpuDockingParameters;

export interface AutoDockGpuToolIdentity {
  tool: { name: string; version: string };
  executable_path: string;
  sha256: string;
  architecture: string | null;
  build: string;
  device_number: number;
  device_name: string;
}

export interface AutoDockGpuExecutionEvidence {
  command: string[];
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_seconds: number;
  /** The tool exits zero either way, so the verdict is what it printed. */
  success_reported_on_stdout: boolean;
  canceled: boolean;
  timed_out: boolean;
}

export interface AutoDockGpuDockingRequest {
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  ligand_id: string;
  ligand_preparation_id: string;
  parameters: AutoDockGpuDockingParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export interface AutoDockGpuDockingJobRecord {
  job_id: string;
  backend: AutoDockBackend;
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: AutoDockGpuDockingRequest;
  autodock_gpu: AutoDockGpuToolIdentity;
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  map_set_identity_key: string;
  ligand_sha256: string;
  ligand_atom_types: string[];
  ligand_atom_count: number;
  torsional_degrees_of_freedom: number;
  /** Always false: a seed does not reproduce an AutoDock-GPU run. */
  bitwise_reproducible: boolean;
  command: string[];
  execution: AutoDockGpuExecutionEvidence | null;
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
}

export interface AutoDockGpuBatchRequest {
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  library_id: string;
  filter_run_id: string;
  parameters: AutoDockGpuBatchParameters;
  acknowledge_inputs_and_scoring: boolean;
}

export interface AutoDockGpuBatchLigandResult {
  ligand_id: string;
  parent_compound_id?: string | null;
  chemical_state_id?: string | null;
  chemical_state_formal_charge?: number | null;
  source_index: number;
  name: string;
  canonical_smiles: string | null;
  molecular_weight_g_mol: number | null;
  ligand_preparation_id: string | null;
  ligand_sha256: string | null;
  ligand_atom_types: string[];
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  completed_at: string | null;
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  revision: number;
}

export interface AutoDockGpuBatchRecord {
  batch_id: string;
  backend: AutoDockBackend;
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  request: AutoDockGpuBatchRequest;
  autodock_gpu: AutoDockGpuToolIdentity;
  receptor_id: string;
  binding_site_id: string;
  map_set_id: string;
  map_set_identity_key: string;
  selection_manifest_sha256: string;
  worker_count: number;
  bitwise_reproducible: boolean;
  selected_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  command: string[];
  execution: AutoDockGpuExecutionEvidence | null;
  entries: AutoDockGpuBatchLigandResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string; details: Record<string, unknown> } | null;
  provenance: ProvenanceEvent | null;
  revision: number;
}

export interface AutoDockGpuBatchProgress {
  batch_id: string;
  status: AutoDock4JobStatus;
  revision: number;
  selected_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
}

/** What a redocking run demonstrated, never collapsed into one word. */
export type RedockingOutcome =
  | "recovered_and_ranked"
  | "recovered_but_misranked"
  | "not_recovered";

export interface RedockingPose {
  run: number;
  rank: number;
  binding_energy_kcal_mol: number;
  cnn_score?: number | null;
  cnn_affinity_pk?: number | null;
  rmsd_angstrom: number;
  recovered: boolean;
}

export interface RedockingMetrics {
  threshold_angstrom: number;
  pose_count: number;
  top1_rmsd_angstrom: number;
  best_top5_rmsd_angstrom: number;
  best_overall_rmsd_angstrom: number;
  /** How far down a scientist would have had to look; null if never. */
  first_recovering_rank: number | null;
  recovered_pose_count: number;
  /** The search found the crystallographic pose. */
  sampling_success: boolean;
  /** The scoring function put it first. These can disagree. */
  ranking_success: boolean;
  outcome: RedockingOutcome;
}

export interface RedockingRunRecord {
  validation_id: string;
  created_at: string;
  reference_case: string | null;
  receptor_id: string;
  binding_site_id: string;
  source_kind: "autodock4_job" | "autodock_gpu_job" | "vina_job" | "gnina_job";
  source_id: string;
  engine: string;
  engine_version: string;
  bitwise_reproducible: boolean | null;
  reference_ligand_id: string;
  reference_sha256: string;
  reference_heavy_atom_count: number;
  metrics: RedockingMetrics;
  poses: RedockingPose[];
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent | null;
}

export interface RedockingValidationRequest {
  source_kind: "autodock4_job" | "autodock_gpu_job" | "vina_job" | "gnina_job";
  source_id: string;
  reference_ligand_id: string;
  threshold_angstrom?: number;
  reference_case?: string | null;
}

export interface RedockingReferencePage {
  references: {
    ligand_id: string;
    name: string;
    source_structure_id: string;
    locator: LigandLocator;
    heavy_atom_count: number;
    sha256: string;
  }[];
  total: number;
  offset: number;
  limit: number;
}

export type ReproducibilityStatus =
  | "measured_reproducible"
  | "measured_variable"
  | "not_assessed";

export interface ReproducibilityExecution {
  catalog_id: string;
  output_fingerprint_sha256: string;
}

export interface ReproducibilityAssessment {
  status: ReproducibilityStatus;
  protocol: string;
  scope: string;
  input_fingerprint_sha256: string | null;
  executions: ReproducibilityExecution[];
}

export interface CampaignExport {
  export_id: string;
  exported_at: string;
  source_kind: string;
  source_id: string;
  catalog_id: string;
  display_name: string | null;
  input_identity_sha256: string;
  bundle_identity_sha256: string;
  archive_filename: string;
  engine: string;
  engine_version: string;
  reproducibility: ReproducibilityAssessment;
  row_count: number;
  interaction_analysis_count: number;
  figure_count: number;
  /** Where the bundle was written. */
  directory: string;
  /** True when `directory` is a folder the scientist chose. */
  outside_project: boolean;
  /** The project's own copy, which is what it can serve back. */
  record_directory: string;
  files: string[];
}

/**
 * The project-level result catalog (M6).
 *
 * A read model over every durable result. A listing carries identity and
 * counts, never poses: a completed campaign is megabytes of them, and the real
 * project already holds 25 MiB across nine campaigns.
 */
export type ResultMode = "single_ligand" | "screening";

/** What produced the number, which is what may never be merged. */
export type ScoringFamily = "vina" | "autodock4" | "gnina";

export interface CatalogEntry {
  /** `{engine_key}:{record_id}` - stable, and it names its own source. */
  catalog_id: string;
  engine_key: string;
  record_id: string;
  mode: ResultMode;
  scoring_family: ScoringFamily;
  backend: string | null;
  /** What the interface shows: `AutoDock4 4.2.6 · CPU`. */
  engine_label: string;
  engine_version: string;
  executable_sha256: string | null;
  device_name: string | null;
  reproducibility: ReproducibilityAssessment;
  status: string;
  created_at: string;
  completed_at: string | null;
  receptor_id: string;
  binding_site_id: string;
  box: Record<string, number>;
  map_set_id: string | null;
  map_set_identity_key: string | null;
  library_id: string | null;
  filter_run_id: string | null;
  selection_manifest_sha256: string | null;
  ligand_id: string | null;
  selected_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  /** This engine's own best number, only meaningful beside `engine_label`. */
  best_result_kcal_mol: number | null;
  primary_cnn_score?: number | null;
  primary_cnn_vs?: number | null;
  cnn_affinity_pk?: number | null;
  minimized_affinity_kcal_mol?: number | null;
  hit_ranking_metric?: GninaHitRankingMetric | null;
  warnings?: StructuredWarning[];
  best_molecule: string | null;
}

export interface CatalogPage {
  entries: CatalogEntry[];
  total: number;
  offset: number;
  limit: number;
}

export interface TrashedResultCampaign {
  catalog_id: string;
  engine_label: string;
  status: string;
}

export interface TrashResultCampaignsResponse {
  operation_id: string;
  trashed_at: string;
  campaigns: TrashedResultCampaign[];
  interaction_analysis_count: number;
  redocking_validation_count: number;
  exports_preserved: boolean;
  recoverable: boolean;
}

export interface CompoundRow {
  ligand_id: string;
  parent_compound_id?: string | null;
  chemical_state_id?: string | null;
  chemical_state_formal_charge?: number | null;
  /** Manifest order, so user sorting never destroys which molecule this was. */
  source_index: number;
  name: string;
  canonical_smiles: string | null;
  molecular_weight_g_mol: number | null;
  status: string;
  failure_code: string | null;
  best_result_kcal_mol: number | null;
  primary_cnn_score?: number | null;
  cnn_vs?: number | null;
  cnn_affinity_pk?: number | null;
  minimized_affinity_kcal_mol?: number | null;
  /** Vina counts poses; AutoDock counts clusters. Neither is fabricated. */
  pose_count: number | null;
  cluster_count: number | null;
  top_cluster_runs: number | null;
}

export interface CompoundPage {
  catalog_id: string;
  engine_label: string;
  /** The engine's own column name, so it is never just "score". */
  value_label: string;
  rows: CompoundRow[];
  total: number;
  offset: number;
  limit: number;
}

export type PoseKind = "vina_mode" | "autodock_run" | "gnina_mode";

export interface PoseReference extends PoseFlexIdentity {
  artifact_id: string;
  kind: PoseKind;
  ordinal: number;
  label: string;
  result_kcal_mol: number;
  value_label: string;
  cnn_score?: number | null;
  cnn_affinity_pk?: number | null;
  cluster_rank: number | null;
  sub_rank: number | null;
  rmsd_lower_bound_angstrom: number | null;
  rmsd_upper_bound_angstrom: number | null;
  cluster_rmsd_angstrom: number | null;
  reference_rmsd_angstrom: number | null;
  sha256: string;
  content_url: string;
}

export interface PoseInventory {
  catalog_id: string;
  ligand_id: string;
  engine_label: string;
  receptor_artifact_id: string | null;
  receptor_content_url: string | null;
  poses: PoseReference[];
}

export interface InteractionProfile {
  profile_id: string;
  vicinity_cutoff_angstrom: number;
  interactions: string[];
}

export interface LigandDiagramAtom {
  atom_index: number;
  element: string;
  label: string;
  x: number;
  y: number;
}

export interface LigandDiagramBond {
  begin_atom_index: number;
  end_atom_index: number;
  order: number;
}

/** A position in the docking frame, in ångströms. */
export interface Point3D {
  x: number;
  y: number;
  z: number;
}

export interface InteractionContact {
  contact_id: string;
  detector_type: string;
  display_type: string;
  residue: ResidueLocator;
  ligand_atom_indices: number[];
  protein_atom_indices: number[];
  ligand_atom_labels: string[];
  protein_atom_labels: string[];
  distance_angstrom: number | null;
  geometry: Record<string, number>;
  /**
   * Where the contact is, taken from the atoms the detector used.
   *
   * Null on analyses recorded before Ankora drew contacts in 3D: a record is
   * never rewritten to invent endpoints it did not measure.
   */
  ligand_point: Point3D | null;
  protein_point: Point3D | null;
}

export interface InteractionAnalysisRecord {
  analysis_id: string;
  created_at: string;
  catalog_id: string;
  engine_key: string;
  record_id: string;
  engine_label: string;
  ligand_id: string;
  ligand_preparation_id: string;
  conformer_id: string;
  conformer_sha256: string;
  pose: PoseReference;
  receptor_id: string;
  docking_receptor_artifact_id: string;
  docking_receptor_sha256: string;
  analysis_receptor_artifact_id: string;
  analysis_receptor_sha256: string;
  analysis_receptor_content_url: string;
  detector: { name: string; version: string };
  profile: InteractionProfile;
  contacts: InteractionContact[];
  ligand_diagram: {
    atoms: LigandDiagramAtom[];
    bonds: LigandDiagramBond[];
  };
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
  pose_flex_sidechains_sha256?: string | null;
  pose_complex_identity_sha256?: string | null;
  /** The deterministic coupled complex ProLIF actually read (`E8`). */
  materialized_coupled_receptor_sha256?: string | null;
}

/** One exact preserved pose combined with its prepared receptor on disk. */
export interface PoseComplexExportRequest {
  molecule_name: string;
  /** A folder to write into; unset keeps the PDB inside the project. */
  destination?: string | null;
}

export interface PoseComplexExport {
  export_id: string;
  exported_at: string;
  catalog_id: string;
  ligand_id: string;
  molecule_name: string;
  pose_artifact_id: string;
  pose_label: string;
  directory: string;
  outside_project: boolean;
  record_directory: string;
  file: {
    filename: string;
    sha256: string;
    size_bytes: number;
  };
}

/** Publication figures written out of a recorded analysis (M9). */
export type FigureSource = "interaction_diagram" | "pose_view_3d";
export type FigureFormat = "svg" | "png" | "tiff" | "pdf";

export interface FigureExportRequest {
  source: FigureSource;
  formats: FigureFormat[];
  svg?: string | null;
  png_base64?: string | null;
  dpi?: number;
  catalog_id: string;
  ligand_id: string;
  molecule_name: string;
  pose_artifact_id: string;
  pose_label: string;
  analysis_id?: string | null;
  /** A folder to write into; unset keeps the figure inside the project. */
  destination?: string | null;
}

export interface FigureFile {
  filename: string;
  format: FigureFormat;
  size_bytes: number;
  /** True only for the diagram's SVG: the 3D view has no vector form. */
  vector: boolean;
  width_px: number | null;
  height_px: number | null;
  dpi: number | null;
}

export interface FigureExport {
  figure_id: string;
  exported_at: string;
  source: FigureSource;
  catalog_id: string;
  ligand_id: string;
  molecule_name: string;
  pose_artifact_id: string;
  pose_label: string;
  analysis_id: string | null;
  /** Where the image files were written. */
  directory: string;
  /** True when `directory` is a folder the scientist chose. */
  outside_project: boolean;
  /** Where the project kept its record of this export. */
  record_directory: string;
  files: FigureFile[];
}

/** Everything this project has sent out of Ankora (workflow step 8). */
export type ExportKind = "campaign" | "consensus" | "figure" | "pose_complex";

export interface ExportFile {
  filename: string;
  size_bytes: number;
  /** Null for a file written into a folder the scientist chose. */
  content_url: string | null;
}

export interface ExportEntry {
  export_id: string;
  kind: ExportKind;
  exported_at: string;
  title: string;
  subtitle: string;
  catalog_id: string | null;
  source_kind: string | null;
  source_id: string | null;
  display_name: string | null;
  input_identity_sha256: string | null;
  bundle_identity_sha256: string | null;
  archive_filename: string | null;
  analysis_id: string | null;
  ligand_id: string | null;
  reproducibility: ReproducibilityAssessment | null;
  /** Legacy campaign manifests only; never interpreted as measured evidence. */
  bitwise_reproducible: boolean | null;
  directory: string;
  ankora_export_format?: number | null;
  outside_project: boolean;
  files: ExportFile[];
}

export interface ConsensusExport {
  exported_at: string;
  ankora_export_format: 5;
  source_kind: "consensus_run";
  source_id: string;
  export_id: string;
  catalog_id: string;
  display_name: string | null;
  input_identity_sha256: string;
  bundle_identity_sha256: string;
  archive_filename: string;
  variant_id: ConsensusVariantId;
  row_count: number;
  full_profile_count: number;
  partial_or_unscored_count: number;
  pose_quality_count: number;
  interaction_rule_evaluation_count: number;
  directory: string;
  outside_project: boolean;
  record_directory: string;
  files: string[];
}

export interface ExportPage {
  entries: ExportEntry[];
  total: number;
  offset: number;
  limit: number;
}

/** What the machine is doing right now, for the status bar. */
export interface GpuUsage {
  name: string;
  utilization_percent: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
}

export interface ResourceAllocation {
  workload: string;
  owner_id: string;
  cpu_threads: number;
  memory_bytes: number;
  disk_bytes: number;
  gpu_slots: number;
  gpu_memory_bytes?: number;
}

export interface ResourceSchedulerSnapshot {
  cpu_threads_capacity: number;
  cpu_threads_allocated: number;
  gpu_slots_capacity: number;
  gpu_slots_allocated: number;
  gpu_memory_total_bytes?: number | null;
  gpu_memory_reserve_bytes?: number;
  gpu_memory_reserved_bytes?: number;
  memory_reserve_bytes: number;
  memory_bytes_reserved: number;
  disk_path: string;
  disk_reserve_bytes: number;
  disk_bytes_reserved: number;
  queued_requests: number;
  active_allocations: ResourceAllocation[];
}

export interface ResourceUsage {
  cpu_percent: number;
  logical_cores: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
  memory_percent: number;
  /** Null when there is no NVIDIA GPU, driver, or answer — never a fake 0%. */
  gpu: GpuUsage | null;
  gpu_unavailable_reason: string | null;
  scheduler?: ResourceSchedulerSnapshot | null;
}

/** One tool, the version that ran, and what it did in this campaign. */
export interface MethodsSoftware {
  name: string;
  version: string;
  role: string;
}

/** A Methods section written from what a campaign actually recorded. */
export interface MethodsReport {
  catalog_id: string;
  generated_at: string;
  engine_label: string;
  markdown: string;
  /** What could not be stated, so the author sees the holes as a list. */
  gaps: string[];
  software: MethodsSoftware[];
}

export type WorkKind =
  | "vina_job"
  | "vina_batch"
  | "autogrid_job"
  | "autodock4_job"
  | "autodock4_batch"
  | "autodock_gpu_job"
  | "autodock_gpu_batch"
  | "gnina_job"
  | "gnina_screening";

export interface RecoveredWorkItem {
  work_kind: WorkKind;
  work_id: string;
  previous_status: string;
  interrupted_entry_count: number;
  completed_entry_count: number;
  last_heartbeat_at: string | null;
  previous_owner_instance_id: string | null;
  screening_campaign_id?: string | null;
}

export interface WorkRecoverySummary {
  reconciled_at: string;
  items: RecoveredWorkItem[];
}

export interface WorkRetryResponse {
  work_kind: WorkKind;
  interrupted_work_id: string;
  new_work_id: string;
  status: string;
  created_at: string;
}

/* ------------------------------------------------------------------------ *
 * v0.2 M2a / M2c — cross-engine `--score_only` scoring contracts.
 *
 * Mirrors `backend/src/ankora_backend/schemas/v02_contracts.py` and
 * `schemas/rescoring.py` field for field. A score is only ever read beside the
 * exact scoring function, unit and direction that produced it: the families
 * below are deliberately separate scales and are never pooled or converted.
 * ------------------------------------------------------------------------ */

export type RescoreSourceEngine = "vina" | "autodock4" | "autodock_gpu" | "gnina";

export type ScoringFunctionId =
  | "vina"
  | "vinardo"
  | "autodock4"
  | "gnina_cnn_score"
  | "gnina_cnn_affinity"
  | "gnina_cnn_vs"
  | "gnina_minimized_affinity";

/**
 * The scoring *family* of one observation.
 *
 * Distinct from the catalog-level `ScoringFamily` above, which labels the
 * engine that produced a campaign. This one names the scale an individual
 * `ScoreObservation` lives on, and crossing those scales is what the
 * contract forbids.
 */
export type ScoreObservationFamily = "vina_vinardo" | "autodock4" | "gnina_neural";

export type ObservationStatus = "scored" | "failed" | "not_evaluable";

/** Which numerical direction an engine ranks more favorably. */
export type ScoreDirection = "lower_is_better" | "higher_is_better";

/** `E8` identity of the receptor and ligand coordinates for one pose. */
export interface PoseComplexIdentity {
  mode: ReceptorFlexMode;
  receptor_rigid_sha256: string;
  pose_flex_sidechains_sha256?: string | null;
  ligand_pose_sha256: string;
}

export interface ProtocolSpec {
  schema_version: 1;
  engine: RescoreSourceEngine;
  scoring_function: ScoringFunctionId;
  ligand_flexibility: LigandFlexibilitySpec;
  receptor_flexibility: ReceptorFlexSpec;
  binding_box_sha256: string;
  autogrid_map_set_sha256?: string | null;
  interaction_rule_set_sha256?: string | null;
  random_seed?: number | null;
}

export interface ScoreObservation {
  schema_version: 1;
  protocol_identity_sha256: string;
  parent_compound_id: string;
  parent_state_id: string;
  pose_complex?: PoseComplexIdentity | null;
  scoring_family: ScoreObservationFamily;
  scoring_function: ScoringFunctionId;
  direction: ScoreDirection;
  unit: string;
  tool_name: string;
  tool_version: string;
  status: ObservationStatus;
  raw_score?: number | null;
  failure_code?: string | null;
}

export type AutoDock4RescoreBackend = "autodock4_epdb" | "vina_ad4_maps";

/** Recorded raw execution provenance for one `--score_only` invocation. */
export interface PoseRescoreFunctionEvidence {
  scoring_functions: ScoringFunctionId[];
  tool_name: string;
  tool_version: string;
  tool_sha256?: string | null;
  command: string[];
  exit_code: number;
  stdout_sha256: string;
  stderr_sha256: string;
  used_flex: boolean;
  /**
   * `Gate 0 F4` — Vina `--score_only --flex` recomputes the unbound reference
   * from the moved side chains, so the returned total is not on the same
   * reference as the docking-time total and must not be differenced with it.
   */
  unbound_reference_shifted: boolean;
  intermolecular_kcal_mol?: number | null;
  total_internal_kcal_mol?: number | null;
  torsional_free_energy_kcal_mol?: number | null;
  unbound_system_energy_kcal_mol?: number | null;
  intramolecular_energy_kcal_mol?: number | null;
  cnn_affinity_variance?: number | null;
}

export interface PoseRescoreResult {
  schema_version: 1;
  pose_complex: PoseComplexIdentity;
  observations: ScoreObservation[];
  evidence: PoseRescoreFunctionEvidence[];
  /** Always `false`: cross-scoring reads the saved pose and writes nothing. */
  mutated_original_pose: false;
}

/** `POST /rescoring/score-only` — one saved pose, evaluated exactly in place. */
export interface SavedPoseRescoreRequest {
  source_engine: RescoreSourceEngine;
  job_id: string;
  pose_artifact_id: string;
  scoring_functions: ScoringFunctionId[];
  autogrid_job_id?: string | null;
  autodock4_backend?: AutoDock4RescoreBackend;
  gnina_compute?: "cpu" | "cuda";
  gnina_device_index?: number;
  gnina_cnn_model?: GninaCnnModelSelector;
  cpu_threads?: number;
  timeout_minutes?: number;
}

/* ------------------------------------------------------------------------ *
 * v0.2 M2b / M2c — two-stage out-of-sample protocol calibration.
 *
 * Mirrors `backend/src/ankora_backend/schemas/calibration.py`. Every record is
 * an append-only, hash-identified decision: the protocol is chosen on the
 * Calibration split alone and sealed before the locked Confirmation split is
 * ever opened, and the Confirmation split is single-use (`ADR-031` §3).
 * ------------------------------------------------------------------------ */

export type SplitName = "calibration" | "confirmation";

export type SplitGroupingStrategy = "parent_and_murcko_scaffold";

export type BiasPropertyName =
  | "molecular_weight"
  | "clogp"
  | "hbd"
  | "hba"
  | "rotatable_bonds"
  | "formal_charge";

export type ConfirmationVerdict =
  | "preferred_over_baseline"
  | "insufficient_evidence_to_prefer_over_baseline"
  | "baseline_retained_by_one_se";

export type CalibrationRunStatus =
  | "split_locked"
  | "calibration_selected"
  | "confirmation_completed";

/** `ADR-031` §3 fixes this exact phrase as the null verdict. */
export const INSUFFICIENT_EVIDENCE_TEXT = "Insufficient evidence to prefer over baseline";

/** Everything about the split and its statistics that is fixed in advance. */
export interface CalibrationSplitPolicy {
  grouping_strategy: SplitGroupingStrategy;
  calibration_fraction: number;
  split_seed: number;
  min_confirmation_actives: number;
  bedroc_alpha: number;
  top_fraction: number;
  bootstrap_replicates: number;
  bootstrap_seed: number;
  confidence_level: number;
}

/** One parent compound offered to the split, with its frozen class label. */
export interface CalibrationCompoundInput {
  parent_id: string;
  canonical_smiles: string;
  is_active: boolean;
  state_ids?: string[];
}

export interface CompoundPropertyProfile {
  parent_id: string;
  canonical_smiles: string;
  is_active: boolean;
  murcko_scaffold: string;
  is_acyclic: boolean;
  molecular_weight: number;
  clogp: number;
  hbd: number;
  hba: number;
  rotatable_bonds: number;
  formal_charge: number;
}

/** Active-versus-inactive separation on one physicochemical property. */
export interface PropertyBiasMetric {
  property_name: BiasPropertyName;
  active_median: number;
  active_iqr: number;
  inactive_median: number;
  inactive_iqr: number;
  standardized_mean_difference: number;
  ks_statistic: number;
  ks_p_value: number;
  flagged_bias: boolean;
}

/** The decoy-property audit that qualifies every enrichment read on this set. */
export interface PhysicochemicalBiasAudit {
  active_count: number;
  inactive_count: number;
  metrics: PropertyBiasMetric[];
  any_bias_flagged: boolean;
  flagged_properties: string[];
}

export interface CalibrationSplitArtifact {
  schema_version: 1;
  split_id: string;
  created_at: string;
  policy: CalibrationSplitPolicy;
  calibration_parent_ids: string[];
  confirmation_parent_ids: string[];
  calibration_scaffolds: string[];
  confirmation_scaffolds: string[];
  calibration_active_count: number;
  calibration_inactive_count: number;
  confirmation_active_count: number;
  confirmation_inactive_count: number;
  confirmation_underpowered: boolean;
  compounds: CompoundPropertyProfile[];
  bias_audit: PhysicochemicalBiasAudit;
  split_identity_sha256: string;
}

/** One pre-declared protocol competing on the Calibration split. */
export interface CalibrationCandidateProtocol {
  protocol_id: string;
  label: string;
  protocol_spec: ProtocolSpec;
  added_chi_torsion_count?: number;
  fitted_parameter_count?: number;
  engine_count?: number;
  is_neural_scoring?: boolean;
}

/**
 * Scored and unscored parents, kept separate for actives and inactives.
 *
 * A decoy that fails to prepare and an active that fails to prepare have
 * opposite consequences for an enrichment metric, so one pooled failure count
 * would hide the bias that matters most.
 */
export interface FailureCensusBreakdown {
  total_parents: number;
  scored_count: number;
  failed_count: number;
  scored_active_count: number;
  failed_active_count: number;
  scored_inactive_count: number;
  failed_inactive_count: number;
  failure_codes_active: Record<string, number>;
  failure_codes_inactive: Record<string, number>;
}

/** Tie-aware enrichment metrics for one target and one exact protocol. */
export interface ScreeningTargetMetrics {
  target_id: string;
  total_count: number;
  active_count: number;
  inactive_count: number;
  scored_count: number;
  failed_count: number;
  top_fraction: number;
  top_count: number;
  expected_active_hits_at_top_fraction: number;
  enrichment_factor: number;
  bedroc_alpha: number;
  bedroc: number;
  roc_auc: number;
  pr_auc: number;
  score_direction: ScoreDirection;
  tie_policy: string;
  failure_policy: string;
  pr_auc_definition: string;
}

/** One protocol evaluated on exactly one side of the split. */
export interface ProtocolEvaluationSummary {
  protocol_id: string;
  protocol_identity_sha256: string;
  label: string;
  split_name: SplitName;
  metrics: ScreeningTargetMetrics;
  bedroc_ci_lower: number;
  bedroc_ci_upper: number;
  bedroc_bootstrap_se: number;
  ef_small_sample_caution: boolean;
  failure_census: FailureCensusBreakdown;
}

/**
 * Paired parent-bootstrap difference in `BEDROC_alpha`, `candidate - reference`.
 *
 * Resampling is over parent compounds, and the same resampled parent indices
 * are applied to both protocols in every replicate.
 */
export interface PairedBootstrapDelta {
  candidate_protocol_id: string;
  reference_protocol_id: string;
  split_name: SplitName;
  metric_name: "bedroc";
  bedroc_alpha: number;
  point_delta: number;
  bootstrap_se: number;
  ci_lower: number;
  ci_upper: number;
  confidence_level: number;
  replicates: number;
  bootstrap_seed: number;
  excludes_zero_positively: boolean;
  within_one_se_of_reference: boolean;
}

/** Stage 1 — the sealed protocol choice, made on Calibration data only. */
export interface CalibrationSelectionRecord {
  schema_version: 1;
  selected_at: string;
  split_identity_sha256: string;
  baseline_protocol_id: string;
  best_point_protocol_id: string;
  selected_protocol_id: string;
  selected_by_one_se_parsimony: boolean;
  evaluations: ProtocolEvaluationSummary[];
  deltas_vs_best: PairedBootstrapDelta[];
  deltas_vs_baseline: PairedBootstrapDelta[];
  selection_identity_sha256: string;
}

/** Stage 2 — the single-use unlock of the locked Confirmation split. */
export interface ConfirmationEvaluationRecord {
  schema_version: 1;
  evaluated_at: string;
  split_identity_sha256: string;
  selection_identity_sha256: string;
  baseline_protocol_id: string;
  selected_protocol_id: string;
  verdict: ConfirmationVerdict;
  verdict_text: string;
  selected_evaluation: ProtocolEvaluationSummary;
  baseline_evaluation: ProtocolEvaluationSummary;
  paired_delta_vs_baseline: PairedBootstrapDelta;
  all_candidate_audit_evaluations?: ProtocolEvaluationSummary[];
  confirmation_identity_sha256: string;
}

/** The whole calibration campaign: split, sealed selection, and verdict. */
export interface CalibrationRunRecord {
  schema_version: 1;
  calibration_id: string;
  project_id: string;
  receptor_id: string;
  binding_site_id: string;
  created_at: string;
  status: CalibrationRunStatus;
  confirmation_locked: boolean;
  confirmation_consumed: boolean;
  split: CalibrationSplitArtifact;
  baseline_protocol_id?: string | null;
  candidates?: CalibrationCandidateProtocol[];
  calibration_selection?: CalibrationSelectionRecord | null;
  confirmation_evaluation?: ConfirmationEvaluationRecord | null;
  warnings?: StructuredWarning[];
  provenance?: ProvenanceEvent[];
}

export interface CalibrationRunList {
  runs: CalibrationRunRecord[];
}

export interface CalibrationSplitRequest {
  receptor_id: string;
  binding_site_id: string;
  compounds: CalibrationCompoundInput[];
  policy?: CalibrationSplitPolicy;
}

export interface CalibrationSelectRequest {
  baseline_protocol_id: string;
  candidates: CalibrationCandidateProtocol[];
  observations_by_protocol: Record<string, ScoreObservation[]>;
}

export interface CalibrationConfirmRequest {
  observations_by_protocol: Record<string, ScoreObservation[]>;
}

/* ------------------------------------------------------------------------ *
 * v0.2 M3 — coupled physical pose plausibility (PoseBusters + MMFF94s).
 *
 * Mirrors `schemas/v02_contracts.py` (`PoseAssessment`, `PoseDiagnosticCheck`,
 * `ConformationalStrainDiagnostic`) and `schemas/pose_quality.py`.
 * Every check retains an explicit 4-state status (`pass`, `fail`,
 * `not_applicable`, `not_evaluable`); conformational strain is strictly a
 * diagnostic flag and is never added to or subtracted from any docking score.
 * ------------------------------------------------------------------------ */

export type DiagnosticStatus = "pass" | "fail" | "not_applicable" | "not_evaluable";

export interface PoseDiagnosticCheck {
  check_id: string;
  tool_name: string;
  tool_version: string;
  status: DiagnosticStatus;
  value?: number | null;
  threshold?: number | null;
  message?: string | null;
}

export interface ConformationalStrainDiagnostic {
  force_field: "MMFF94s";
  parent_state_id: string;
  hydrogen_policy: string;
  conformer_seed: number;
  conformer_budget: number;
  pose_restrained_energy_kcal_mol: number;
  lowest_free_conformer_energy_kcal_mol: number;
  delta_e_ref_kcal_mol: number;
}

export interface PoseAssessment {
  schema_version: 1;
  pose_complex: PoseComplexIdentity;
  overall_status: DiagnosticStatus;
  checks: PoseDiagnosticCheck[];
  strain?: ConformationalStrainDiagnostic | null;
  mutated_original_pose: false;
}

export interface PoseQualityRequest {
  include_strain?: boolean;
  conformer_seed?: number;
  conformer_budget?: number;
  strain_flag_threshold_kcal_mol?: number;
}

export interface PoseQualityRecord {
  schema_version: 1;
  assessment_id: string;
  created_at: string;
  catalog_id: string;
  engine_key: string;
  record_id: string;
  engine_label: string;
  ligand_id: string;
  ligand_preparation_id: string;
  conformer_id: string;
  conformer_sha256: string;
  parent_state_id: string;
  receptor_id: string;
  docking_receptor_artifact_id: string;
  docking_receptor_sha256: string;
  analysis_receptor_artifact_id: string;
  analysis_receptor_sha256: string;
  materialized_coupled_receptor_sha256?: string | null;
  pose: PoseReference;
  posebusters_version: string;
  assessment: PoseAssessment;
  passed_count: number;
  failed_count: number;
  not_applicable_count: number;
  not_evaluable_count: number;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
}

/* ------------------------------------------------------------------------ *
 * v0.2 M4 — declarative ProLIF pharmacophoric rules & Tanimoto IFP (PIC).
 *
 * Mirrors `schemas/interaction_rules.py`. Rule sets are validated against the
 * prepared receptor's protonated PDB and sealed by `rule_set_identity_sha256`
 * prior to Confirmation. Pose evaluations run directly on the coupled
 * `PoseComplex` (`ADR-032 E8`) and never mutate parent pose bytes.
 * ------------------------------------------------------------------------ */

export type InteractionRuleKind = "required" | "alternative_or" | "forbidden";

export type IfpSourceKind = "pose_analysis" | "explicit_bits";

export interface IfpBit {
  residue: ResidueLocator;
  interaction_type: string;
}

export interface IfpCountEntry {
  bit: IfpBit;
  count: number;
}

export interface InteractionFingerprint {
  profile: InteractionProfile;
  bits: IfpBit[];
  counts: IfpCountEntry[];
  source_kind: IfpSourceKind;
  source_analysis_id?: string | null;
  source_catalog_id?: string | null;
  source_ligand_id?: string | null;
  source_pose_artifact_id?: string | null;
  source_pose_complex_sha256?: string | null;
  fingerprint_sha256: string;
}

export interface InteractionTarget {
  residue: ResidueLocator;
  interaction_types: string[];
  max_distance_angstrom?: number | null;
}

export interface InteractionRuleClause {
  clause_id: string;
  label: string;
  kind: InteractionRuleKind;
  targets: InteractionTarget[];
  min_satisfied?: number | null;
}

export interface ReferencePoseSelector {
  catalog_id: string;
  ligand_id: string;
  pose_artifact_id: string;
}

export interface CreateInteractionRuleSetRequest {
  name: string;
  description?: string;
  receptor_id: string;
  profile?: InteractionProfile;
  clauses?: InteractionRuleClause[];
  reference_pose?: ReferencePoseSelector | null;
  reference_bits?: IfpBit[] | null;
  min_tanimoto_similarity?: number | null;
}

export interface InteractionRuleSetRecord {
  schema_version: 1;
  rule_set_id: string;
  created_at: string;
  name: string;
  description: string;
  receptor_id: string;
  receptor_protonated_artifact_id: string;
  receptor_protonated_sha256: string;
  profile: InteractionProfile;
  clauses: InteractionRuleClause[];
  reference_ifp?: InteractionFingerprint | null;
  min_tanimoto_similarity?: number | null;
  rule_set_identity_sha256: string;
  provenance: ProvenanceEvent;
}

export interface TargetEvaluationResult {
  target: InteractionTarget;
  matched: boolean;
  matched_contact_ids: string[];
  shortest_distance_angstrom?: number | null;
}

export interface ClauseEvaluationResult {
  clause_id: string;
  label: string;
  kind: InteractionRuleKind;
  status: DiagnosticStatus;
  satisfied_target_count: number;
  required_target_count: number;
  matched_contact_ids: string[];
  target_results: TargetEvaluationResult[];
  explanation: string;
}

export interface IfpTanimotoResult {
  reference_fingerprint_sha256: string;
  pose_fingerprint_sha256: string;
  status: DiagnosticStatus;
  similarity?: number | null;
  min_threshold?: number | null;
  intersection_count: number;
  union_count: number;
  shared_bits: IfpBit[];
  pose_only_bits: IfpBit[];
  reference_only_bits: IfpBit[];
}

export interface EvaluateInteractionRulesRequest {
  rule_set_id: string;
  analysis_id?: string | null;
}

export interface InteractionRuleEvaluationRecord {
  schema_version: 1;
  evaluation_id: string;
  created_at: string;
  rule_set_id: string;
  rule_set_name: string;
  rule_set_identity_sha256: string;
  catalog_id: string;
  engine_key: string;
  record_id: string;
  engine_label: string;
  ligand_id: string;
  ligand_preparation_id: string;
  conformer_id: string;
  conformer_sha256: string;
  receptor_id: string;
  docking_receptor_artifact_id: string;
  docking_receptor_sha256: string;
  analysis_receptor_artifact_id: string;
  analysis_receptor_sha256: string;
  materialized_coupled_receptor_sha256?: string | null;
  pose: PoseReference;
  pose_complex: PoseComplexIdentity;
  interaction_analysis_id?: string | null;
  detector: { name: string; version: string };
  profile: InteractionProfile;
  pose_ifp: InteractionFingerprint;
  contacts: InteractionContact[];
  overall_status: DiagnosticStatus;
  clause_results: ClauseEvaluationResult[];
  passed_clause_count: number;
  failed_clause_count: number;
  tanimoto?: IfpTanimotoResult | null;
  mutated_original_pose: false;
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
}

/* ------------------------------------------------------------------------ *
 * v0.2 M5 — ADR-030 rank-space consensus prioritization (PC-Q, PC-ECR,
 * gated convex non-negative PC-L2) & two-tier RankingArtifact (`E6`).
 *
 * Mirrors `schemas/v02_contracts.py` (`RankingArtifact`, `RankingEntry`,
 * `RankingMethod`) and `schemas/consensus.py`. Fixed published family block
 * weights are server-enforced; `PC-Q` (0–100) is dimensionless concordance,
 * `PC-ECR` (`tau = 0.05`) stays on its separate `1/sigma` scale (`E5`), and
 * `partial_or_unscored` parents remain unranked in the denominator (`E6`).
 * ------------------------------------------------------------------------ */

export const FROZEN_ECR_TAU = 0.05;
export const DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM = 2.0;

export type RankingMethod =
  | "single_engine"
  | "pc_q_core_v1"
  | "pc_q_neural_v1"
  | "pc_ecr_v1"
  | "pc_l2_v1";

export type ConsensusTier = "full_profile" | "partial_or_unscored";

export interface RankingEntry {
  parent_compound_id: string;
  parent_state_id: string;
  tier: ConsensusTier;
  rank?: number | null;
  score_value?: number | null;
  percentile?: number | null;
  inter_family_disagreement?: number | null;
  search_convergence_count?: number | null;
  search_engine_count?: number | null;
  selected_pose_complex?: PoseComplexIdentity | null;
  failure_or_exclusion_codes: string[];
}

export interface RankingArtifact {
  schema_version: 1;
  method: RankingMethod;
  reference_panel_sha256?: string | null;
  tie_policy: string;
  failure_policy: string;
  total_parents: number;
  full_profile_count: number;
  partial_or_unscored_count: number;
  entries: RankingEntry[];
}

export type ConsensusVariantId = "pcq-core-v1" | "pcq-neural-v1";

export interface PoseClusterMemberSummary {
  pose_id: string;
  source_engine: RescoreSourceEngine;
  primary_rank_order: number;
  pose_complex: PoseComplexIdentity;
  canonical_coordinate_sha256: string;
}

export interface PoseClusterSummary {
  cluster_id: string;
  medoid_pose_id: string;
  medoid_pose_complex: PoseComplexIdentity;
  medoid_canonical_coordinate_sha256: string;
  member_count: number;
  max_intra_cluster_rmsd_angstrom: number;
  best_primary_rank_order: number;
  search_engines_present: RescoreSourceEngine[];
  members: PoseClusterMemberSummary[];
}

export interface ReferencePanelEntry {
  parent_compound_id: string;
  parent_state_id: string;
  cluster_id: string;
  pose_complex: PoseComplexIdentity;
  scores_by_function: Partial<Record<ScoringFunctionId, number>>;
}

export interface ReferencePanelArtifact {
  schema_version: 1;
  panel_id: string;
  created_at: string;
  receptor_id: string;
  binding_site_id: string;
  receptor_flex_spec: ReceptorFlexSpec;
  binding_box_sha256: string;
  autogrid_map_set_sha256?: string | null;
  enabled_functions: ScoringFunctionId[];
  tool_identities: Array<{ name: string; version: string }>;
  executable_sha256s: Record<string, string>;
  k_max: number;
  total_panel_parents: number;
  entries: ReferencePanelEntry[];
  reference_panel_sha256: string;
}

export interface MedoidConsensusBreakdown {
  cluster_id: string;
  medoid_pose_id: string;
  pose_complex: PoseComplexIdentity;
  canonical_coordinate_sha256: string;
  member_count: number;
  max_intra_cluster_rmsd_angstrom: number;
  search_engines_present: RescoreSourceEngine[];
  search_convergence_count: number;
  search_engine_count: number;
  native_scores: Partial<Record<ScoringFunctionId, number>>;
  function_quantiles: Partial<Record<ScoringFunctionId, number>>;
  block_quantiles: Partial<Record<ScoreObservationFamily, number>>;
  pcq_score: number;
  pcq_core_score: number;
  inter_family_disagreement: number;
  pc_ecr_score: number;
}

export interface PcL2ModelArtifact {
  schema_version: 1;
  reference_panel_sha256: string;
  calibration_id: string;
  split_identity_sha256: string;
  selection_identity_sha256?: string | null;
  confirmation_identity_sha256?: string | null;
  feature_functions: ScoringFunctionId[];
  l2_regularization: number;
  solver_name: "scipy.optimize.L-BFGS-B";
  intercept: number;
  weights: Partial<Record<ScoringFunctionId, number>>;
  converged: true;
  iterations: number;
  final_objective: number;
  promoted: boolean;
  promotion_verdict_text: string;
  confirmation_deltas_vs_single_engines: Record<string, PairedBootstrapDelta>;
}

export interface ConsensusParentDetail {
  parent_compound_id: string;
  parent_state_id: string;
  tier: ConsensusTier;
  rotatable_bond_count?: number | null;
  total_input_poses: number;
  total_clusters_found: number;
  retained_cluster_count: number;
  truncated_by_k_max: boolean;
  selected_medoid_cluster_id?: string | null;
  selected_pose_complex?: PoseComplexIdentity | null;
  pcq_score?: number | null;
  pcq_core_score?: number | null;
  pc_ecr_score?: number | null;
  pc_ecr_selected_cluster_id?: string | null;
  pc_l2_score?: number | null;
  inter_family_disagreement?: number | null;
  search_convergence_count?: number | null;
  search_engine_count?: number | null;
  medoids: MedoidConsensusBreakdown[];
  failure_or_exclusion_codes: string[];
}

export interface ConsensusPoseScoreInput {
  cluster_id: string;
  medoid_pose_id: string;
  pose_complex: PoseComplexIdentity;
  canonical_coordinate_sha256: string;
  member_count?: number;
  max_intra_cluster_rmsd_angstrom?: number;
  search_engines_present: RescoreSourceEngine[];
  scores_by_function?: Partial<Record<ScoringFunctionId, number>>;
  missing_or_failed_codes?: string[];
}

export interface ConsensusParentInput {
  parent_compound_id: string;
  parent_state_id: string;
  rotatable_bond_count?: number | null;
  total_input_poses?: number;
  total_clusters_found?: number;
  truncated_by_k_max?: boolean;
  medoids?: ConsensusPoseScoreInput[];
  failure_or_exclusion_codes?: string[];
}

export interface CreateStructuredConsensusRequest {
  name: string;
  variant_id: ConsensusVariantId;
  receptor_id: string;
  binding_site_id: string;
  receptor_flex_spec: ReceptorFlexSpec;
  binding_box_sha256: string;
  autogrid_map_set_sha256: string;
  enabled_functions: ScoringFunctionId[];
  k_max: number;
  rmsd_threshold_angstrom?: number;
  search_engine_count: number;
  parents: ConsensusParentInput[];
  reference_panel_id?: string | null;
  tool_identities?: Array<{ name: string; version: string }>;
  executable_sha256s?: Record<string, string>;
}

export interface CampaignSourceRef {
  catalog_id: string;
}

export interface CreateCampaignConsensusRequest {
  name: string;
  variant_id: ConsensusVariantId;
  sources: CampaignSourceRef[];
  autogrid_map_set_id: string;
  autodock4_backend?: AutoDock4RescoreBackend;
  include_vinardo?: boolean;
  gnina_function?: ScoringFunctionId;
  k_max: number;
  rmsd_threshold_angstrom?: number;
  reference_panel_id?: string | null;
}

export interface FitPcL2Request {
  calibration_id: string;
  l2_regularization?: number;
}

export interface ConsensusRunRecord {
  schema_version: 1;
  consensus_id: string;
  created_at: string;
  name: string;
  variant_id: ConsensusVariantId;
  k_max: number;
  rmsd_threshold_angstrom: number;
  ecr_tau: number;
  receptor_id: string;
  binding_site_id: string;
  receptor_flex_spec: ReceptorFlexSpec;
  binding_box_sha256: string;
  autogrid_map_set_sha256: string;
  source_catalog_ids: string[];
  enabled_functions: ScoringFunctionId[];
  block_weights: Partial<Record<ScoreObservationFamily, number>>;
  within_block_weights: Partial<Record<ScoringFunctionId, number>>;
  reference_panel: ReferencePanelArtifact;
  ranking: RankingArtifact;
  core_ranking?: RankingArtifact | null;
  ecr_ranking: RankingArtifact;
  pc_l2_model?: PcL2ModelArtifact | null;
  pc_l2_ranking?: RankingArtifact | null;
  parent_details: ConsensusParentDetail[];
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent;
}

export interface ConsensusRunListResponse {
  runs: ConsensusRunRecord[];
}
