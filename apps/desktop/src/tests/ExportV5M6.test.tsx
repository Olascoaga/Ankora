import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ExportWorkspace } from "../features/export/ExportWorkspace";
import { ConsensusWorkspace } from "../features/results/ConsensusWorkspace";
import type {
  ConsensusExport,
  ConsensusRunListResponse,
  ConsensusRunRecord,
  ExportPage,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Labelled synthetic consensus run fixture for M6c Export v5 UI verification.
const SYNTHETIC_RUN: ConsensusRunRecord = {
  schema_version: 1,
  consensus_id: "cons-m6c-synth-1",
  created_at: "2026-11-20T17:00:00Z",
  name: "Synthetic M6c Core Consensus",
  variant_id: "pcq-core-v1",
  k_max: 2,
  rmsd_threshold_angstrom: 2.0,
  ecr_tau: 0.05,
  receptor_id: "rec-m6c",
  binding_site_id: "site-m6c",
  receptor_flex_spec: {
    mode: "rigid",
    receptor_rigid_sha256: "1".repeat(64),
    receptor_flex_sha256: null,
    flex_residues: [],
    added_chi_torsion_count: 0,
  },
  binding_box_sha256: "2".repeat(64),
  autogrid_map_set_sha256: "3".repeat(64),
  source_catalog_ids: ["vina_batch:synth-1"],
  enabled_functions: ["vina", "autodock4"],
  block_weights: { vina_vinardo: 0.5, autodock4: 0.5 },
  within_block_weights: { vina: 1.0, autodock4: 1.0 },
  reference_panel: {
    schema_version: 1,
    panel_id: "panel-m6c-1",
    created_at: "2026-11-20T17:00:00Z",
    receptor_id: "rec-m6c",
    binding_site_id: "site-m6c",
    receptor_flex_spec: {
      mode: "rigid",
      receptor_rigid_sha256: "1".repeat(64),
      receptor_flex_sha256: null,
      flex_residues: [],
      added_chi_torsion_count: 0,
    },
    binding_box_sha256: "2".repeat(64),
    autogrid_map_set_sha256: "3".repeat(64),
    enabled_functions: ["vina", "autodock4"],
    tool_identities: [{ name: "AutoDock Vina", version: "1.2.7" }],
    executable_sha256s: {},
    k_max: 2,
    total_panel_parents: 1,
    entries: [
      {
        parent_compound_id: "SYNTH_A",
        parent_state_id: "state-a",
        cluster_id: "cl-a",
        pose_complex: {
          mode: "rigid",
          receptor_rigid_sha256: "1".repeat(64),
          pose_flex_sidechains_sha256: null,
          ligand_pose_sha256: "4".repeat(64),
        },
        scores_by_function: { vina: -8.5, autodock4: -7.9 },
      },
    ],
    reference_panel_sha256: "5".repeat(64),
  },
  ranking: {
    schema_version: 1,
    method: "pc_q_core_v1",
    reference_panel_sha256: "5".repeat(64),
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 1,
    full_profile_count: 1,
    partial_or_unscored_count: 0,
    entries: [
      {
        parent_compound_id: "SYNTH_A",
        parent_state_id: "state-a",
        tier: "full_profile",
        rank: 1,
        score_value: 75.0,
        percentile: 75.0,
        inter_family_disagreement: 4.0,
        search_convergence_count: 2,
        search_engine_count: 2,
        selected_pose_complex: {
          mode: "rigid",
          receptor_rigid_sha256: "1".repeat(64),
          pose_flex_sidechains_sha256: null,
          ligand_pose_sha256: "4".repeat(64),
        },
        failure_or_exclusion_codes: [],
      },
    ],
  },
  core_ranking: null,
  ecr_ranking: {
    schema_version: 1,
    method: "pc_ecr_v1",
    reference_panel_sha256: "5".repeat(64),
    tie_policy: "parent_weighted_midrank",
    failure_policy: "retained_unscored_in_denominator",
    total_parents: 1,
    full_profile_count: 1,
    partial_or_unscored_count: 0,
    entries: [
      {
        parent_compound_id: "SYNTH_A",
        parent_state_id: "state-a",
        tier: "full_profile",
        rank: 1,
        score_value: 0.35,
        percentile: null,
        inter_family_disagreement: 4.0,
        search_convergence_count: 2,
        search_engine_count: 2,
        selected_pose_complex: {
          mode: "rigid",
          receptor_rigid_sha256: "1".repeat(64),
          pose_flex_sidechains_sha256: null,
          ligand_pose_sha256: "4".repeat(64),
        },
        failure_or_exclusion_codes: [],
      },
    ],
  },
  pc_l2_model: null,
  pc_l2_ranking: null,
  parent_details: [
    {
      parent_compound_id: "SYNTH_A",
      parent_state_id: "state-a",
      tier: "full_profile",
      rotatable_bond_count: 3,
      total_input_poses: 2,
      total_clusters_found: 1,
      retained_cluster_count: 1,
      truncated_by_k_max: false,
      selected_medoid_cluster_id: "cl-a",
      selected_pose_complex: {
        mode: "rigid",
        receptor_rigid_sha256: "1".repeat(64),
        pose_flex_sidechains_sha256: null,
        ligand_pose_sha256: "4".repeat(64),
      },
      pcq_score: 75.0,
      pcq_core_score: 75.0,
      pc_ecr_score: 0.35,
      pc_ecr_selected_cluster_id: "cl-a",
      pc_l2_score: null,
      inter_family_disagreement: 4.0,
      search_convergence_count: 2,
      search_engine_count: 2,
      medoids: [],
      failure_or_exclusion_codes: [],
    },
  ],
  warnings: [],
  provenance: {
    event_id: "evt-m6c-1",
    event_type: "consensus_run_created",
    timestamp: "2026-11-20T17:00:00Z",
    input_artifacts: ["rec-m6c"],
    output_artifacts: ["cons-m6c-synth-1"],
    tool: { name: "ankora-pcq-consensus", version: "0.2.0" },
    parameters: {},
    warnings: [],
    command: null,
  },
};

const SYNTHETIC_CONSENSUS_EXPORT: ConsensusExport = {
  exported_at: "2026-11-20T18:00:00Z",
  ankora_export_format: 5,
  source_kind: "consensus_run",
  source_id: "cons-m6c-synth-1",
  export_id: "exp-m6c-v5-1",
  catalog_id: "consensus_run:cons-m6c-synth-1",
  display_name: "Synthetic M6c Core Consensus",
  input_identity_sha256: "a".repeat(64),
  bundle_identity_sha256: "b".repeat(64),
  archive_filename: "Ankora_Synthetic-M6c_bundle.zip",
  variant_id: "pcq-core-v1",
  row_count: 1,
  full_profile_count: 1,
  partial_or_unscored_count: 0,
  pose_quality_count: 0,
  interaction_rule_evaluation_count: 0,
  directory: "project-data/exports/exp-m6c-v5-1",
  outside_project: false,
  record_directory: "project-data/exports/exp-m6c-v5-1",
  files: [
    "Ankora_Synthetic-M6c_bundle.zip",
    "README.txt",
    "manifest.json",
    "methods.md",
    "results.csv",
  ],
};

describe("M6c Desktop UI: Export v5 consensus bundles & Export Catalog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exports an Export v5 bundle on demand from ConsensusWorkspace and surfaces verified hashes and download links", async () => {
    let exportPostUrl: string | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/consensus/runs")) {
        const list: ConsensusRunListResponse = { runs: [SYNTHETIC_RUN] };
        return json(list);
      }
      if (url.includes("/consensus/runs/cons-m6c-synth-1/export") && init?.method === "POST") {
        exportPostUrl = url;
        return json(SYNTHETIC_CONSENSUS_EXPORT, 201);
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ConsensusWorkspace campaigns={[]} />);
    await waitFor(() => {
      expect(screen.getByText("SYNTH_A")).toBeInTheDocument();
    });

    // Opt-in: no export call until user clicks the button
    expect(exportPostUrl).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Export consensus bundle" }));
    const banner = await screen.findByRole("status", { name: "Export v5 consensus bundle" });
    expect(exportPostUrl).toContain("/consensus/runs/cons-m6c-synth-1/export");
    expect(within(banner).getByText("Export v5")).toBeInTheDocument();
    expect(within(banner).getByText(/Inputs aaaaaaaaaaaa/)).toBeInTheDocument();
    expect(within(banner).getByText(/Bundle bbbbbbbbbbbb/)).toBeInTheDocument();
    expect(
      within(banner).getByRole("link", { name: "Ankora_Synthetic-M6c_bundle.zip" }),
    ).toBeInTheDocument();
    expect(within(banner).getByRole("link", { name: "methods.md" })).toBeInTheDocument();
  });

  it("filters and renders Export v5 consensus bundles inside ExportWorkspace", async () => {
    const requestedUrls: string[] = [];
    const consensusPage: ExportPage = {
      entries: [
        {
          export_id: "exp-m6c-v5-1",
          kind: "consensus",
          exported_at: "2026-11-20T18:00:00Z",
          title: "Synthetic M6c Core Consensus",
          subtitle: "1/1 parents full-profile · pcq-core-v1",
          catalog_id: "consensus_run:cons-m6c-synth-1",
          source_kind: "consensus_run",
          source_id: "cons-m6c-synth-1",
          display_name: "Synthetic M6c Core Consensus",
          input_identity_sha256: "a".repeat(64),
          bundle_identity_sha256: "b".repeat(64),
          archive_filename: "Ankora_Synthetic-M6c_bundle.zip",
          analysis_id: null,
          ligand_id: null,
          reproducibility: null,
          bitwise_reproducible: null,
          directory: "project-data/exports/exp-m6c-v5-1",
          ankora_export_format: 5,
          outside_project: false,
          files: [
            {
              filename: "Ankora_Synthetic-M6c_bundle.zip",
              size_bytes: 24576,
              content_url: "/exports/exp-m6c-v5-1/Ankora_Synthetic-M6c_bundle.zip",
            },
          ],
        },
      ],
      total: 1,
      offset: 0,
      limit: 25,
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      requestedUrls.push(url);
      if (url.includes("/results/campaigns")) {
        return json({ entries: [], total: 0, offset: 0, limit: 200 });
      }
      if (url.includes("/exports")) {
        return json(consensusPage);
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ExportWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("Consensus bundle · Export v5")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Consensus bundles" }));
    await waitFor(() => {
      expect(requestedUrls.some((u) => u.includes("kind=consensus"))).toBe(true);
    });
    expect(screen.getByText("1/1 parents full-profile · pcq-core-v1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ankora_Synthetic-M6c_bundle\.zip/ })).toBeInTheDocument();
  });
});
