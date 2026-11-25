import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ResultsWorkspace } from "../features/results/ResultsWorkspace";
import {
  INSUFFICIENT_EVIDENCE_TEXT,
  type CatalogEntry,
  type CatalogPage,
  type ConsensusRunListResponse,
  type ConsensusRunRecord,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Explicitly synthetic campaign catalog entries for M5c UI contract testing.
const SYNTHETIC_GPU_CAMPAIGN: CatalogEntry = {
  catalog_id: "autodock_gpu_batch:synth-gpu-1",
  engine_key: "autodock_gpu_batch",
  record_id: "synth-gpu-1",
  mode: "screening",
  scoring_family: "autodock4",
  backend: "autodock_gpu",
  engine_label: "AutoDock4 · AutoDock-GPU 1.6",
  engine_version: "1.6",
  executable_sha256: "2".repeat(64),
  device_name: "Synthetic GPU",
  reproducibility: {
    status: "measured_reproducible",
    protocol: "ankora-reproducibility-v1",
    scope: "parsed scientific outputs and retained pose-artifact bytes",
    input_fingerprint_sha256: "a".repeat(64),
    executions: [
      {
        catalog_id: "autodock_gpu_batch:synth-gpu-1",
        output_fingerprint_sha256: "b".repeat(64),
      },
    ],
  },
  status: "completed",
  created_at: "2026-11-19T12:00:00Z",
  completed_at: "2026-11-19T12:05:00Z",
  receptor_id: "rec-synth-1",
  binding_site_id: "site-synth-1",
  box: {
    center_x: 10.0,
    center_y: 0.0,
    center_z: 0.0,
    size_x: 20.0,
    size_y: 20.0,
    size_z: 20.0,
  },
  map_set_id: "map-synth-flex-001",
  map_set_identity_key: "c".repeat(64),
  library_id: "lib-synth-1",
  filter_run_id: "flt-synth-1",
  selection_manifest_sha256: "d".repeat(64),
  ligand_id: null,
  selected_count: 2,
  succeeded_count: 2,
  failed_count: 0,
  canceled_count: 0,
  best_result_kcal_mol: -8.4,
  best_molecule: "SYNTH_CMPD_1",
};

const REC_SHA = "1".repeat(64);
const FLEX_SHA = "2".repeat(64);
const BOX_SHA = "3".repeat(64);
const MAP_SHA = "4".repeat(64);
const PANEL_SHA = "5".repeat(64);

const SYNTHETIC_NEURAL_RUN: ConsensusRunRecord = {
  schema_version: 1,
  consensus_id: "cons-synth-neural-1",
  created_at: "2026-11-19T13:00:00Z",
  name: "Synthetic FlexRes Neural Consensus",
  variant_id: "pcq-neural-v1",
  k_max: 3,
  rmsd_threshold_angstrom: 2.0,
  ecr_tau: 0.05,
  receptor_id: "rec-synth-1",
  binding_site_id: "site-synth-1",
  receptor_flex_spec: {
    mode: "sidechain_flex",
    receptor_rigid_sha256: REC_SHA,
    receptor_flex_sha256: FLEX_SHA,
    flex_residues: [
      { chain_id: "A", sequence_number: 85, insertion_code: "", residue_name: "MET" },
      { chain_id: "A", sequence_number: 92, insertion_code: "", residue_name: "ASP" },
    ],
    added_chi_torsion_count: 5,
  },
  binding_box_sha256: BOX_SHA,
  autogrid_map_set_sha256: MAP_SHA,
  source_catalog_ids: [SYNTHETIC_GPU_CAMPAIGN.catalog_id],
  enabled_functions: ["vina", "vinardo", "autodock4", "gnina_cnn_vs"],
  block_weights: {
    vina_vinardo: 1 / 3,
    autodock4: 1 / 3,
    gnina_neural: 1 / 3,
  },
  within_block_weights: {
    vina: 0.5,
    vinardo: 0.5,
    autodock4: 1.0,
    gnina_cnn_vs: 1.0,
  },
  reference_panel: {
    schema_version: 1,
    panel_id: "panel-synth-1",
    created_at: "2026-11-19T13:00:00Z",
    receptor_id: "rec-synth-1",
    binding_site_id: "site-synth-1",
    receptor_flex_spec: {
      mode: "sidechain_flex",
      receptor_rigid_sha256: REC_SHA,
      receptor_flex_sha256: FLEX_SHA,
      flex_residues: [
        { chain_id: "A", sequence_number: 85, insertion_code: "", residue_name: "MET" },
        { chain_id: "A", sequence_number: 92, insertion_code: "", residue_name: "ASP" },
      ],
      added_chi_torsion_count: 5,
    },
    binding_box_sha256: BOX_SHA,
    autogrid_map_set_sha256: MAP_SHA,
    enabled_functions: ["vina", "vinardo", "autodock4", "gnina_cnn_vs"],
    tool_identities: [{ name: "AutoDock Vina", version: "1.2.7" }],
    executable_sha256s: {},
    k_max: 3,
    total_panel_parents: 1,
    entries: [
      {
        parent_compound_id: "SYNTH_CMPD_1",
        parent_state_id: "state-1",
        cluster_id: "cl-1",
        pose_complex: {
          mode: "sidechain_flex",
          receptor_rigid_sha256: REC_SHA,
          pose_flex_sidechains_sha256: "6".repeat(64),
          ligand_pose_sha256: "7".repeat(64),
        },
        scores_by_function: {
          vina: -9.4,
          vinardo: -8.9,
          autodock4: -8.2,
          gnina_cnn_vs: 7.45,
        },
      },
    ],
    reference_panel_sha256: PANEL_SHA,
  },
  ranking: {
    schema_version: 1,
    method: "pc_q_neural_v1",
    reference_panel_sha256: PANEL_SHA,
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 2,
    full_profile_count: 1,
    partial_or_unscored_count: 1,
    entries: [
      {
        parent_compound_id: "SYNTH_CMPD_1",
        parent_state_id: "state-1",
        tier: "full_profile",
        rank: 1,
        score_value: 86.5,
        percentile: 86.5,
        inter_family_disagreement: 44.0,
        search_convergence_count: 3,
        search_engine_count: 3,
        selected_pose_complex: {
          mode: "sidechain_flex",
          receptor_rigid_sha256: REC_SHA,
          pose_flex_sidechains_sha256: "6".repeat(64),
          ligand_pose_sha256: "7".repeat(64),
        },
        failure_or_exclusion_codes: [],
      },
      {
        parent_compound_id: "SYNTH_PARTIAL_2",
        parent_state_id: "state-2",
        tier: "partial_or_unscored",
        rank: null,
        score_value: null,
        percentile: null,
        inter_family_disagreement: null,
        search_convergence_count: null,
        search_engine_count: null,
        selected_pose_complex: null,
        failure_or_exclusion_codes: ["AUTODOCK4_ATOM_TYPE_UNSUPPORTED"],
      },
    ],
  },
  core_ranking: {
    schema_version: 1,
    method: "pc_q_core_v1",
    reference_panel_sha256: PANEL_SHA,
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 2,
    full_profile_count: 1,
    partial_or_unscored_count: 1,
    entries: [
      {
        parent_compound_id: "SYNTH_CMPD_1",
        parent_state_id: "state-1",
        tier: "full_profile",
        rank: 1,
        score_value: 81.25,
        percentile: 81.25,
        inter_family_disagreement: 12.0,
        search_convergence_count: 3,
        search_engine_count: 3,
        selected_pose_complex: {
          mode: "sidechain_flex",
          receptor_rigid_sha256: REC_SHA,
          pose_flex_sidechains_sha256: "6".repeat(64),
          ligand_pose_sha256: "7".repeat(64),
        },
        failure_or_exclusion_codes: [],
      },
      {
        parent_compound_id: "SYNTH_PARTIAL_2",
        parent_state_id: "state-2",
        tier: "partial_or_unscored",
        rank: null,
        score_value: null,
        percentile: null,
        inter_family_disagreement: null,
        search_convergence_count: null,
        search_engine_count: null,
        selected_pose_complex: null,
        failure_or_exclusion_codes: ["AUTODOCK4_ATOM_TYPE_UNSUPPORTED"],
      },
    ],
  },
  ecr_ranking: {
    schema_version: 1,
    method: "pc_ecr_v1",
    reference_panel_sha256: PANEL_SHA,
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 2,
    full_profile_count: 1,
    partial_or_unscored_count: 1,
    entries: [
      {
        parent_compound_id: "SYNTH_CMPD_1",
        parent_state_id: "state-1",
        tier: "full_profile",
        rank: 1,
        score_value: 0.4123,
        percentile: null,
        inter_family_disagreement: 44.0,
        search_convergence_count: 3,
        search_engine_count: 3,
        selected_pose_complex: {
          mode: "sidechain_flex",
          receptor_rigid_sha256: REC_SHA,
          pose_flex_sidechains_sha256: "6".repeat(64),
          ligand_pose_sha256: "7".repeat(64),
        },
        failure_or_exclusion_codes: [],
      },
      {
        parent_compound_id: "SYNTH_PARTIAL_2",
        parent_state_id: "state-2",
        tier: "partial_or_unscored",
        rank: null,
        score_value: null,
        percentile: null,
        inter_family_disagreement: null,
        search_convergence_count: null,
        search_engine_count: null,
        selected_pose_complex: null,
        failure_or_exclusion_codes: ["AUTODOCK4_ATOM_TYPE_UNSUPPORTED"],
      },
    ],
  },
  pc_l2_model: null,
  pc_l2_ranking: null,
  parent_details: [
    {
      parent_compound_id: "SYNTH_CMPD_1",
      parent_state_id: "state-1",
      tier: "full_profile",
      rotatable_bond_count: 4,
      total_input_poses: 5,
      total_clusters_found: 2,
      retained_cluster_count: 1,
      truncated_by_k_max: false,
      selected_medoid_cluster_id: "cl-1",
      selected_pose_complex: {
        mode: "sidechain_flex",
        receptor_rigid_sha256: REC_SHA,
        pose_flex_sidechains_sha256: "6".repeat(64),
        ligand_pose_sha256: "7".repeat(64),
      },
      pcq_score: 86.5,
      pcq_core_score: 81.25,
      pc_ecr_score: 0.4123,
      pc_ecr_selected_cluster_id: "cl-1",
      pc_l2_score: null,
      inter_family_disagreement: 44.0,
      search_convergence_count: 3,
      search_engine_count: 3,
      medoids: [
        {
          cluster_id: "cl-1",
          medoid_pose_id: "pose-1",
          pose_complex: {
            mode: "sidechain_flex",
            receptor_rigid_sha256: REC_SHA,
            pose_flex_sidechains_sha256: "6".repeat(64),
            ligand_pose_sha256: "7".repeat(64),
          },
          canonical_coordinate_sha256: "8".repeat(64),
          member_count: 3,
          max_intra_cluster_rmsd_angstrom: 0.85,
          search_engines_present: ["vina", "autodock4", "gnina"],
          search_convergence_count: 3,
          search_engine_count: 3,
          native_scores: {
            vina: -9.4,
            vinardo: -8.9,
            autodock4: -8.2,
            gnina_cnn_vs: 7.45,
          },
          function_quantiles: {
            vina: 90.0,
            vinardo: 84.0,
            autodock4: 75.5,
            gnina_cnn_vs: 97.0,
          },
          block_quantiles: {
            vina_vinardo: 87.0,
            autodock4: 75.5,
            gnina_neural: 97.0,
          },
          pcq_score: 86.5,
          pcq_core_score: 81.25,
          inter_family_disagreement: 44.0,
          pc_ecr_score: 0.4123,
        },
      ],
      failure_or_exclusion_codes: [],
    },
    {
      parent_compound_id: "SYNTH_PARTIAL_2",
      parent_state_id: "state-2",
      tier: "partial_or_unscored",
      rotatable_bond_count: 6,
      total_input_poses: 1,
      total_clusters_found: 1,
      retained_cluster_count: 1,
      truncated_by_k_max: false,
      selected_medoid_cluster_id: null,
      selected_pose_complex: null,
      pcq_score: null,
      pcq_core_score: null,
      pc_ecr_score: null,
      pc_ecr_selected_cluster_id: null,
      pc_l2_score: null,
      inter_family_disagreement: null,
      search_convergence_count: null,
      search_engine_count: null,
      medoids: [],
      failure_or_exclusion_codes: ["AUTODOCK4_ATOM_TYPE_UNSUPPORTED"],
    },
  ],
  warnings: [
    {
      code: "CONSENSUS_PARTIAL_PROFILE_RETAINED",
      stage: "pose_consensus",
      message: "1 parent compound lacked a full scoring profile and was retained unranked.",
      details: {},
      recoverable: true,
    },
  ],
  provenance: {
    event_id: "evt-synth-cons-1",
    event_type: "consensus_run_created",
    timestamp: "2026-11-19T13:00:00Z",
    input_artifacts: ["rec-synth-1"],
    output_artifacts: ["cons-synth-neural-1"],
    tool: { name: "ankora-pcq-consensus", version: "0.2.0" },
    parameters: {},
    warnings: [],
    command: null,
  },
};

function makePcL2Derivative(promoted: boolean): ConsensusRunRecord {
  const verdict = promoted
    ? "Promoted over every single scoring function on locked Confirmation."
    : INSUFFICIENT_EVIDENCE_TEXT;
  return {
    ...SYNTHETIC_NEURAL_RUN,
    consensus_id: promoted ? "cons-synth-pcl2-promoted" : "cons-synth-pcl2-unpromoted",
    name: promoted ? "Synthetic PC-L2 Promoted" : "Synthetic PC-L2 Unpromoted",
    pc_l2_model: {
      schema_version: 1,
      reference_panel_sha256: PANEL_SHA,
      calibration_id: "cal-synth-1",
      split_identity_sha256: "9".repeat(64),
      selection_identity_sha256: null,
      confirmation_identity_sha256: null,
      feature_functions: ["vina", "vinardo", "autodock4", "gnina_cnn_vs"],
      l2_regularization: 0.75,
      solver_name: "scipy.optimize.L-BFGS-B",
      intercept: -1.125,
      weights: {
        vina: 0.612,
        vinardo: 0.145,
        autodock4: 0.421,
        gnina_cnn_vs: 0.903,
      },
      converged: true,
      iterations: 14,
      final_objective: 0.241,
      promoted,
      promotion_verdict_text: verdict,
      confirmation_deltas_vs_single_engines: {
        vina: {
          candidate_protocol_id: "pc_l2_v1",
          reference_protocol_id: "vina",
          split_name: "confirmation",
          metric_name: "bedroc",
          bedroc_alpha: 20.0,
          point_delta: promoted ? 0.185 : 0.012,
          bootstrap_se: 0.041,
          ci_lower: promoted ? 0.095 : -0.068,
          ci_upper: promoted ? 0.275 : 0.092,
          confidence_level: 0.95,
          replicates: 1000,
          bootstrap_seed: 20260420,
          excludes_zero_positively: promoted,
          within_one_se_of_reference: !promoted,
        },
      },
    },
    parent_details: SYNTHETIC_NEURAL_RUN.parent_details.map((detail) =>
      detail.tier === "full_profile" ? { ...detail, pc_l2_score: 1.482 } : detail,
    ),
  };
}

describe("M5c Desktop UI: ADR-030 PC-Q / PC-ECR / gated PC-L2 Consensus Workspace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stays opt-in silent on mount and renders two-tier neural+core, separate PC-ECR scale, D_ic, block bars, Search Convergence, and native medoid units", async () => {
    const requestedUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      requestedUrls.push(url);
      if (url.includes("/results/campaigns")) {
        const page: CatalogPage = {
          entries: [SYNTHETIC_GPU_CAMPAIGN],
          total: 1,
          offset: 0,
          limit: 25,
        };
        return json(page);
      }
      if (url.endsWith("/consensus/runs")) {
        const payload: ConsensusRunListResponse = { runs: [SYNTHETIC_NEURAL_RUN] };
        return json(payload);
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ResultsWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("AutoDock4 · AutoDock-GPU 1.6")).toBeInTheDocument();
    });

    // Opt-in guarantee: zero consensus fetches while on default Campaigns view.
    expect(requestedUrls.some((u) => u.includes("/consensus/"))).toBe(false);

    // Switch to opt-in PC-Q Consensus view.
    fireEvent.click(screen.getByRole("button", { name: "PC-Q Consensus" }));

    await waitFor(() => {
      expect(screen.getByText("SYNTH_CMPD_1")).toBeInTheDocument();
    });
    expect(requestedUrls.some((u) => u.endsWith("/consensus/runs"))).toBe(true);

    // FlexRes E8 badge & provenance denominator
    expect(screen.getByText(/FlexRes coupled \(2 residues · E8\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 ranked \+ 1 partial\/unscored = 2 total/)).toBeInTheDocument();

    // Tier 1 table: PC-Q + PC-Q Core alongside + separate PC-ECR (1/sigma) + D_ic + block bars + Search Convergence
    const tier1 = screen.getByRole("region", { name: "Tier 1 full-profile rankings" });
    expect(within(tier1).getByText("PC-Q (0–100)")).toBeInTheDocument();
    expect(within(tier1).getByText("PC-Q Core (0–100)")).toBeInTheDocument();
    expect(within(tier1).getByText(/PC-ECR \(τ=0\.05, 1\/σ scale\)/)).toBeInTheDocument();
    expect(within(tier1).getByText("86.50")).toBeInTheDocument();
    expect(within(tier1).getByText("81.25")).toBeInTheDocument();
    expect(within(tier1).getByText("0.4123")).toBeInTheDocument();
    expect(within(tier1).getByText("44.0")).toBeInTheDocument();
    expect(within(tier1).getByText("3/3 engines")).toBeInTheDocument();
    expect(within(tier1).getByLabelText("Family block quantiles")).toBeInTheDocument();

    // Expand parent row to verify native-unit scores stay paired with their native unit
    fireEvent.click(within(tier1).getByRole("button", { name: /SYNTH_CMPD_1/ }));
    expect(within(tier1).getByText(/cl-1 · selected medoid c\*/)).toBeInTheDocument();
    expect(within(tier1).getByText(/-9\.400/)).toBeInTheDocument();
    expect(within(tier1).getByText(/7\.450/)).toBeInTheDocument();
    expect(within(tier1).getAllByText("kcal/mol").length).toBeGreaterThanOrEqual(2);
    expect(within(tier1).getByText("pK")).toBeInTheDocument();

    // Tier 2 E6 partial_or_unscored explicitly retained unranked with failure code
    const tier2 = screen.getByRole("region", { name: "Tier 2 partial or unscored parents" });
    expect(within(tier2).getByText("SYNTH_PARTIAL_2")).toBeInTheDocument();
    expect(within(tier2).getByText("Unranked · no imputation")).toBeInTheDocument();
    expect(within(tier2).getByText("AUTODOCK4_ATOM_TYPE_UNSUPPORTED")).toBeInTheDocument();
  });

  it("enforces explicit required K_max (E2) before calling POST /consensus/runs/campaigns", async () => {
    let postedBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/results/campaigns")) {
        return json({ entries: [SYNTHETIC_GPU_CAMPAIGN], total: 1, offset: 0, limit: 25 });
      }
      if (url.endsWith("/consensus/runs")) {
        return json({ runs: [] });
      }
      if (url.endsWith("/consensus/runs/campaigns") && init?.method === "POST") {
        postedBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return json(SYNTHETIC_NEURAL_RUN, 201);
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ResultsWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("AutoDock4 · AutoDock-GPU 1.6")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "PC-Q Consensus" }));
    await waitFor(() => {
      expect(screen.getByText("No consensus runs recorded yet")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "New consensus run" }));
    const form = screen.getByRole("form", { name: "Create consensus run" });

    fireEvent.change(within(form).getByLabelText("Run name"), {
      target: { value: "My Core Consensus" },
    });
    // Check the campaign source (also auto-fills map_set_id = map-synth-flex-001)
    fireEvent.click(within(form).getByLabelText(/AutoDock4 · AutoDock-GPU 1\.6/));

    // Attempt submit with blank K_max -> must fail locally per ADR-030 E2 without posting
    fireEvent.click(within(form).getByRole("button", { name: "Run PC-Q consensus" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(/Explicit K_max/);
    expect(postedBody).toBeNull();

    // Provide explicit K_max = 3 and submit
    fireEvent.change(within(form).getByLabelText("Explicit K_max per parent (required)"), {
      target: { value: "3" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Run PC-Q consensus" }));

    await waitFor(() => {
      expect(postedBody).not.toBeNull();
    });
    expect(postedBody).toMatchObject({
      name: "My Core Consensus",
      variant_id: "pcq-core-v1",
      autogrid_map_set_id: "map-synth-flex-001",
      k_max: 3,
      sources: [{ catalog_id: SYNTHETIC_GPU_CAMPAIGN.catalog_id }],
    });
    expect(await screen.findByText("SYNTH_CMPD_1")).toBeInTheDocument();
  });

  it("fits gated PC-L2 derivatives and renders both verbatim unpromoted null verdict and promoted verdict", async () => {
    let callCount = 0;
    let lastPcL2Body: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/results/campaigns")) {
        return json({ entries: [SYNTHETIC_GPU_CAMPAIGN], total: 1, offset: 0, limit: 25 });
      }
      if (url.endsWith("/consensus/runs")) {
        return json({ runs: [SYNTHETIC_NEURAL_RUN] });
      }
      if (url.includes("/calibrations")) {
        return json({ runs: [] });
      }
      if (url.includes("/pc-l2") && init?.method === "POST") {
        callCount += 1;
        lastPcL2Body = JSON.parse(String(init.body)) as Record<string, unknown>;
        return json(makePcL2Derivative(callCount > 1), 201);
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ResultsWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("AutoDock4 · AutoDock-GPU 1.6")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "PC-Q Consensus" }));
    await waitFor(() => {
      expect(screen.getByText("SYNTH_CMPD_1")).toBeInTheDocument();
    });

    // 1. Fit first PC-L2 -> Unpromoted verbatim null verdict
    fireEvent.click(screen.getByRole("button", { name: "Fit gated PC-L2 derivative" }));
    const pcL2Region = screen.getByRole("region", { name: "Gated PC-L2 calibration" });
    const calInput = await within(pcL2Region).findByLabelText("Calibration run ID (M2)");
    fireEvent.change(calInput, { target: { value: "cal-synth-1" } });
    fireEvent.change(within(pcL2Region).getByLabelText("L2 regularization (λ > 0)"), {
      target: { value: "0.75" },
    });
    fireEvent.click(within(pcL2Region).getByRole("button", { name: "Fit & gate on Confirmation" }));

    await waitFor(() => {
      expect(within(pcL2Region).getByText(INSUFFICIENT_EVIDENCE_TEXT)).toBeInTheDocument();
    });
    expect(lastPcL2Body).toEqual({ calibration_id: "cal-synth-1", l2_regularization: 0.75 });
    expect(within(pcL2Region).getByText("PC-L2 Unpromoted (audit only)")).toBeInTheDocument();
    expect(within(pcL2Region).getByText("Includes 0")).toBeInTheDocument();

    // 2. Fit second PC-L2 -> Promoted verdict with CI > 0 (pass)
    fireEvent.click(screen.getByRole("button", { name: "Fit gated PC-L2 derivative" }));
    fireEvent.click(within(pcL2Region).getByRole("button", { name: "Fit & gate on Confirmation" }));

    await waitFor(() => {
      expect(within(pcL2Region).getByText("PC-L2 Promoted")).toBeInTheDocument();
    });
    expect(within(pcL2Region).getByText("CI > 0 (pass)")).toBeInTheDocument();
  });
});
