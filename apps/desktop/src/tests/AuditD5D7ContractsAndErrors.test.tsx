import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ankoraApi, ApiError } from "../api/client";
import { AnalogExpansionPanel } from "../features/expansion/AnalogExpansionPanel";
import { ExportWorkspace } from "../features/export/ExportWorkspace";
import { ConsensusWorkspace } from "../features/results/ConsensusWorkspace";
import { reproducibilityTitle } from "../features/results/reproducibility";
import type {
  ConsensusExport,
  ConsensusRunListResponse,
  ConsensusRunRecord,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);

const SYNTHETIC_RUN_WITH_PCL2: ConsensusRunRecord = {
  schema_version: 1,
  consensus_id: "cons-audit-1",
  created_at: "2026-11-26T18:00:00Z",
  name: "Synthetic Audit Consensus",
  variant_id: "pcq-core-v1",
  k_max: 3,
  rmsd_threshold_angstrom: 2.0,
  ecr_tau: 0.05,
  receptor_id: "rec-audit-1",
  binding_site_id: "site-audit-1",
  receptor_flex_spec: {
    mode: "rigid",
    receptor_rigid_sha256: SHA_A,
    receptor_flex_sha256: null,
    flex_residues: [],
    added_chi_torsion_count: 0,
  },
  binding_box_sha256: SHA_A,
  autogrid_map_set_sha256: SHA_B,
  source_catalog_ids: ["vina_batch:b1"],
  enabled_functions: ["vina", "autodock4"],
  block_weights: { vina_vinardo: 0.5, autodock4: 0.5 },
  within_block_weights: { vina: 1.0, autodock4: 1.0 },
  reference_panel: {
    schema_version: 1,
    panel_id: "panel-audit-1",
    created_at: "2026-11-26T18:00:00Z",
    receptor_id: "rec-audit-1",
    binding_site_id: "site-audit-1",
    receptor_flex_spec: {
      mode: "rigid",
      receptor_rigid_sha256: SHA_A,
      receptor_flex_sha256: null,
      flex_residues: [],
      added_chi_torsion_count: 0,
    },
    binding_box_sha256: SHA_A,
    autogrid_map_set_sha256: SHA_B,
    enabled_functions: ["vina", "autodock4"],
    tool_identities: [{ name: "AutoDock Vina", version: "1.2.7" }],
    executable_sha256s: {},
    k_max: 3,
    total_panel_parents: 1,
    entries: [
      {
        parent_compound_id: "AUDIT_A",
        parent_state_id: "state-a",
        cluster_id: "c1",
        pose_complex: {
          mode: "rigid",
          receptor_rigid_sha256: SHA_A,
          pose_flex_sidechains_sha256: null,
          ligand_pose_sha256: SHA_C,
        },
        scores_by_function: { vina: -7.5, autodock4: -8.1 },
      },
    ],
    reference_panel_sha256: SHA_A,
  },
  ranking: {
    schema_version: 1,
    method: "pc_q_core_v1",
    reference_panel_sha256: SHA_A,
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 1,
    full_profile_count: 1,
    partial_or_unscored_count: 0,
    entries: [
      {
        parent_compound_id: "AUDIT_A",
        parent_state_id: "state-a",
        tier: "full_profile",
        rank: 1,
        score_value: 92.5,
        percentile: 92.5,
        inter_family_disagreement: 2.1,
        search_convergence_count: 2,
        search_engine_count: 2,
        selected_pose_complex: {
          mode: "rigid",
          receptor_rigid_sha256: SHA_A,
          pose_flex_sidechains_sha256: null,
          ligand_pose_sha256: SHA_C,
        },
        failure_or_exclusion_codes: [],
      },
    ],
  },
  core_ranking: null,
  ecr_ranking: {
    schema_version: 1,
    method: "pc_ecr_v1",
    reference_panel_sha256: SHA_A,
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 1,
    full_profile_count: 1,
    partial_or_unscored_count: 0,
    entries: [],
  },
  pc_l2_model: {
    schema_version: 1,
    reference_panel_sha256: SHA_A,
    calibration_id: "cal-audit-1",
    split_identity_sha256: SHA_B,
    feature_functions: ["vina", "autodock4"],
    l2_regularization: 1.0,
    solver_name: "scipy.optimize.L-BFGS-B",
    intercept: -0.1,
    weights: { vina: 0.6, autodock4: 0.4 },
    converged: true,
    iterations: 12,
    final_objective: 0.42,
    promoted: true,
    promotion_verdict_text: "Promoted: beats all baselines including PC-Q on Confirmation.",
    confirmation_deltas_vs_single_engines: {
      vina: {
        candidate_protocol_id: "pc_l2_v1",
        reference_protocol_id: "vina",
        split_name: "confirmation",
        metric_name: "bedroc",
        bedroc_alpha: 20.0,
        point_delta: 0.08,
        ci_lower: 0.02,
        ci_upper: 0.14,
        bootstrap_se: 0.03,
        confidence_level: 0.95,
        replicates: 1000,
        bootstrap_seed: 20260420,
        excludes_zero_positively: true,
        within_one_se_of_reference: false,
      },
    },
    confirmation_delta_vs_pcq: {
      candidate_protocol_id: "pc_l2_v1",
      reference_protocol_id: "pc_q_core_v1",
      split_name: "confirmation",
      metric_name: "bedroc",
      bedroc_alpha: 20.0,
      point_delta: 0.045,
      ci_lower: 0.011,
      ci_upper: 0.079,
      bootstrap_se: 0.017,
      confidence_level: 0.95,
      replicates: 1000,
      bootstrap_seed: 20260420,
      excludes_zero_positively: true,
      within_one_se_of_reference: false,
    },
  },
  pc_l2_ranking: null,
  parent_details: [
    {
      parent_compound_id: "AUDIT_A",
      parent_state_id: "state-a",
      tier: "full_profile",
      rotatable_bond_count: 4,
      total_input_poses: 2,
      total_clusters_found: 1,
      retained_cluster_count: 1,
      truncated_by_k_max: false,
      selected_medoid_cluster_id: "c1",
      pcq_score: 92.5,
      pcq_core_score: 92.5,
      pc_ecr_score: 0.91,
      pc_l2_score: 1.234,
      inter_family_disagreement: 2.1,
      search_convergence_count: 2,
      search_engine_count: 2,
      medoids: [],
      failure_or_exclusion_codes: [],
    },
  ],
  warnings: [],
  provenance: {
    event_id: "evt-audit-1",
    event_type: "consensus_run_created",
    timestamp: "2026-11-26T18:00:00Z",
    input_artifacts: ["rec-audit-1"],
    output_artifacts: ["cons-audit-1"],
    tool: { name: "ankora-pcq-consensus", version: "0.2.0" },
    parameters: {},
    warnings: [],
    command: null,
  },
};

describe("Audit D5 + D7: typed contracts, Export v6, PC-L2 delta vs PC-Q, and surfaced errors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders Export v6 status, stale warning, PC-Q confirmation delta, and calibration load error in ConsensusWorkspace", async () => {
    const v6Export: ConsensusExport = {
      exported_at: "2026-11-26T18:05:00Z",
      ankora_export_format: 6,
      source_kind: "consensus_run",
      source_id: "cons-audit-1",
      export_id: "exp-audit-v6",
      catalog_id: "consensus_run:cons-audit-1",
      display_name: "Synthetic Audit Consensus",
      input_identity_sha256: SHA_A,
      bundle_identity_sha256: SHA_B,
      archive_filename: "Ankora_Audit_v6.zip",
      variant_id: "pcq-core-v1",
      row_count: 1,
      full_profile_count: 1,
      partial_or_unscored_count: 0,
      pose_quality_count: 0,
      interaction_rule_evaluation_count: 0,
      directory: "project-data/exports/exp-audit-v6",
      outside_project: false,
      record_directory: "project-data/exports/exp-audit-v6",
      files: ["Ankora_Audit_v6.zip", "manifest.json"],
      stale: true,
      stale_reasons: ["Upstream receptor modified"],
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/consensus/runs")) {
        const list: ConsensusRunListResponse = { runs: [SYNTHETIC_RUN_WITH_PCL2] };
        return json(list);
      }
      if (url.includes("/consensus/runs/cons-audit-1/export") && init?.method === "POST") {
        return json(v6Export, 201);
      }
      if (url.endsWith("/calibrations")) {
        return json(
          {
            code: "calibration_store_failed",
            stage: "calibration",
            message: "Calibration catalog unavailable",
            details: {},
            recoverable: true,
          },
          500,
        );
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ConsensusWorkspace campaigns={[]} />);
    await waitFor(() => {
      expect(screen.getByText("AUDIT_A")).toBeInTheDocument();
    });

    // D7-010: confirmation_delta_vs_pcq renders as an explicit baseline row
    expect(screen.getByText("PC-Q (zero-fit consensus)")).toBeInTheDocument();
    expect(screen.getByText("+0.0450")).toBeInTheDocument();

    // D7-004 + D5-001: dynamic Export v6 banner + stale lineage alert
    fireEvent.click(screen.getByRole("button", { name: "Export consensus bundle" }));
    const banner = await screen.findByRole("status", { name: "Export v6 consensus bundle" });
    expect(within(banner).getByText("Export v6")).toBeInTheDocument();
    expect(within(banner).getByRole("alert")).toHaveTextContent("Upstream receptor modified");

    // D5-019: calibration list error is surfaced instead of silently dropped
    fireEvent.click(screen.getByRole("button", { name: "Fit gated PC-L2 derivative" }));
    expect(await screen.findByText("Calibration catalog unavailable")).toBeInTheDocument();
  });

  it("surfaces campaign catalog load failure in ExportWorkspace instead of silently showing empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/results/campaigns")) {
        return json(
          {
            code: "catalog_read_error",
            stage: "results",
            message: "Campaign catalog unavailable on disk",
            details: {},
            recoverable: true,
          },
          500,
        );
      }
      if (url.includes("/exports")) {
        return json({ entries: [], total: 0, offset: 0, limit: 25 });
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ExportWorkspace />);
    expect(await screen.findByText("Campaign catalog unavailable on disk")).toBeInTheDocument();
  });

  it("surfaces analog catalog and library load failures in AnalogExpansionPanel", async () => {
    vi.spyOn(ankoraApi, "listAnalogCatalogs").mockRejectedValue(
      new ApiError("Offline analog store locked", 500, {
        code: "analog_catalog_error",
        stage: "analog_expansion",
        message: "Offline analog store locked",
        details: {},
        recoverable: true,
      }),
    );
    vi.spyOn(ankoraApi, "listLigandLibraries").mockResolvedValue({
      libraries: [],
      total: 0,
      offset: 0,
      limit: 25,
    });

    render(
      <AnalogExpansionPanel
        sourceCatalogId="vina_batch:b1"
        sourceLigandId="lig-1"
        sourcePoseArtifactId="pose-1"
        receptorId="rec-1"
        seedLabel="AUDIT_A"
      />,
    );

    expect(await screen.findByText(/Offline analog store locked/)).toBeInTheDocument();
  });

  it("formats deterministic rank-space consensus reproducibility titles (D7-012)", () => {
    expect(
      reproducibilityTitle({
        status: "deterministic_rank_space_consensus",
        reference_panel_sha256: SHA_A,
      }),
    ).toBe("Deterministic rank-space consensus");
  });
});
