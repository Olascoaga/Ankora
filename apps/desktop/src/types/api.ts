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
export type ReceptorOutputStage = "selected" | "repaired" | "relaxed" | "protonated_pdb" | "protonated_pqr" | "meeko_input_pqr" | "pdbqt";

export interface ResidueLocator {
  chain_id: string;
  residue_name: string;
  sequence_number: number;
  insertion_code: string;
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

export interface PrepareLigandPdbqtRequest {
  charge_model: LigandChargeModel;
  /** Informational only: how many of these requests we're issuing concurrently
   * this batch run, recorded into provenance. The server never uses this to
   * size its own execution. */
  client_concurrency_hint?: number | null;
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

export interface VinaDockingParameters {
  sampling_protocol?: "screening" | "pose_refinement" | "custom" | null;
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

export interface DockingPoseArtifact {
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

export interface AutoDock4PoseArtifact {
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
  source_kind: "autodock4_job" | "autodock_gpu_job" | "vina_job";
  source_id: string;
  engine: string;
  engine_version: string;
  bitwise_reproducible: boolean;
  reference_ligand_id: string;
  reference_sha256: string;
  reference_heavy_atom_count: number;
  metrics: RedockingMetrics;
  poses: RedockingPose[];
  warnings: StructuredWarning[];
  provenance: ProvenanceEvent | null;
}

export interface RedockingValidationRequest {
  source_kind: "autodock4_job" | "autodock_gpu_job" | "vina_job";
  source_id: string;
  reference_ligand_id: string;
  threshold_angstrom?: number;
  reference_case?: string | null;
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
export type ScoringFamily = "vina" | "autodock4";

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

export type PoseKind = "vina_mode" | "autodock_run";

export interface PoseReference {
  artifact_id: string;
  kind: PoseKind;
  ordinal: number;
  label: string;
  result_kcal_mol: number;
  value_label: string;
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
export type ExportKind = "campaign" | "figure" | "pose_complex";

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
  analysis_id: string | null;
  ligand_id: string | null;
  reproducibility: ReproducibilityAssessment | null;
  /** Legacy campaign manifests only; never interpreted as measured evidence. */
  bitwise_reproducible: boolean | null;
  directory: string;
  outside_project: boolean;
  files: ExportFile[];
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
}

export interface ResourceSchedulerSnapshot {
  cpu_threads_capacity: number;
  cpu_threads_allocated: number;
  gpu_slots_capacity: number;
  gpu_slots_allocated: number;
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
  | "autodock_gpu_batch";

export interface RecoveredWorkItem {
  work_kind: WorkKind;
  work_id: string;
  previous_status: string;
  interrupted_entry_count: number;
  completed_entry_count: number;
  last_heartbeat_at: string | null;
  previous_owner_instance_id: string | null;
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
