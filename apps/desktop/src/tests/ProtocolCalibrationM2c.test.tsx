import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ankoraApi } from "../api/client";
import { PoseInteractionPanel } from "../features/results/PoseInteractionPanel";
import { ProtocolCalibrationWorkspace } from "../features/validation/ProtocolCalibrationWorkspace";
import { RedockingWorkspace } from "../features/validation/RedockingWorkspace";
import type {
  CalibrationRunRecord,
  CalibrationSelectionRecord,
  CalibrationSplitArtifact,
  CatalogEntry,
  ConfirmationEvaluationRecord,
  PoseInventory,
  PoseRescoreResult,
  ProtocolEvaluationSummary,
} from "../types/api";
import { INSUFFICIENT_EVIDENCE_TEXT } from "../types/api";
import type { ViewerSource } from "../viewer/adapter";
import {
  entry as baseEntry,
  inventory as baseInventory,
  molecule,
} from "./fixtures/interactionPresentation";

// Spy only at the 3D viewer boundary; all calibration & rescoring components
// and API clients run unmodified against synthetic fixtures labelled synthetic.
vi.mock("../viewer/MolecularViewer", () => ({
  MolecularViewer: ({ sources }: { sources: ViewerSource[] }) => (
    <div data-testid="m2c-viewer-sources" data-sources={JSON.stringify(sources)} />
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const SHA_1 = "1".repeat(64);
const SHA_2 = "2".repeat(64);
const SHA_3 = "3".repeat(64);
const SHA_4 = "4".repeat(64);

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function syntheticEvaluation(
  protocolId: string,
  label: string,
  splitName: "calibration" | "confirmation",
  bedroc: number,
  overrides: Partial<ProtocolEvaluationSummary> = {},
): ProtocolEvaluationSummary {
  return {
    protocol_id: protocolId,
    protocol_identity_sha256: SHA_2,
    label,
    split_name: splitName,
    metrics: {
      target_id: `synth-cal:${splitName}:${protocolId}`,
      total_count: 10,
      active_count: 4,
      inactive_count: 6,
      scored_count: 9,
      failed_count: 1,
      top_fraction: 0.01,
      top_count: 1,
      expected_active_hits_at_top_fraction: 0.4,
      enrichment_factor: 2.5,
      bedroc_alpha: 20,
      bedroc,
      roc_auc: 0.81,
      pr_auc: 0.76,
      score_direction: "lower_is_better",
      tie_policy: "fractional_expected_rank",
      failure_policy: "worst_tied_rank",
      pr_auc_definition: "average_precision",
    },
    bedroc_ci_lower: Math.max(0, bedroc - 0.12),
    bedroc_ci_upper: Math.min(1, bedroc + 0.12),
    bedroc_bootstrap_se: 0.06,
    ef_small_sample_caution: true,
    failure_census: {
      total_parents: 10,
      scored_count: 9,
      failed_count: 1,
      scored_active_count: 4,
      failed_active_count: 0,
      scored_inactive_count: 5,
      failed_inactive_count: 1,
      failure_codes_active: {},
      failure_codes_inactive: { DOCKING_FAILED: 1 },
    },
    ...overrides,
  };
}

function syntheticSplit(): CalibrationSplitArtifact {
  return {
    schema_version: 1,
    split_id: "synth-split-1",
    created_at: "2026-11-19T12:00:00Z",
    policy: {
      grouping_strategy: "parent_and_murcko_scaffold",
      calibration_fraction: 0.6,
      split_seed: 20261119,
      min_confirmation_actives: 10,
      bedroc_alpha: 20,
      top_fraction: 0.01,
      bootstrap_replicates: 2000,
      bootstrap_seed: 20261119,
      confidence_level: 0.95,
    },
    calibration_parent_ids: ["SYNTH_A1", "SYNTH_A2", "SYNTH_I1", "SYNTH_I2"],
    confirmation_parent_ids: ["SYNTH_A3", "SYNTH_A4", "SYNTH_I3", "SYNTH_I4"],
    calibration_scaffolds: ["c1ccccc1", "c1ccncc1"],
    confirmation_scaffolds: ["c1ccc2ccccc2c1", "C1CCCCC1"],
    calibration_active_count: 2,
    calibration_inactive_count: 2,
    confirmation_active_count: 2,
    confirmation_inactive_count: 2,
    confirmation_underpowered: true,
    compounds: [],
    bias_audit: {
      active_count: 4,
      inactive_count: 4,
      metrics: [
        {
          property_name: "molecular_weight",
          active_median: 420.5,
          active_iqr: 35.0,
          inactive_median: 245.2,
          inactive_iqr: 22.0,
          standardized_mean_difference: 1.85,
          ks_statistic: 0.75,
          ks_p_value: 0.012,
          flagged_bias: true,
        },
        {
          property_name: "clogp",
          active_median: 3.1,
          active_iqr: 0.6,
          inactive_median: 2.9,
          inactive_iqr: 0.5,
          standardized_mean_difference: 0.15,
          ks_statistic: 0.25,
          ks_p_value: 0.89,
          flagged_bias: false,
        },
      ],
      any_bias_flagged: true,
      flagged_properties: ["molecular_weight"],
    },
    split_identity_sha256: SHA_1,
  };
}

function syntheticSplitLockedRun(): CalibrationRunRecord {
  return {
    schema_version: 1,
    calibration_id: "11111111-2222-3333-4444-555555555555",
    project_id: "default",
    receptor_id: "synth-rec-1",
    binding_site_id: "synth-site-1",
    created_at: "2026-11-19T12:00:00Z",
    status: "split_locked",
    confirmation_locked: true,
    confirmation_consumed: false,
    split: syntheticSplit(),
    warnings: [
      {
        code: "CALIBRATION_CONFIRMATION_UNDERPOWERED",
        stage: "protocol_calibration",
        message: "Synthetic underpowered confirmation split.",
        recoverable: true,
        details: { confirmation_active_count: 2, min_confirmation_actives: 10 },
      },
      {
        code: "CALIBRATION_DECOY_PROPERTY_BIAS",
        stage: "protocol_calibration",
        message: "Synthetic physicochemical decoy bias on molecular_weight.",
        recoverable: true,
        details: { flagged_properties: ["molecular_weight"] },
      },
    ],
    provenance: [],
  };
}

function syntheticSelectedRun(
  overrides: Partial<CalibrationSelectionRecord> = {},
): CalibrationRunRecord {
  const base = syntheticSplitLockedRun();
  const rigidEval = syntheticEvaluation("rigid-vina", "Rigid Vina", "calibration", 0.71, {
    failure_census: {
      total_parents: 4,
      scored_count: 4,
      failed_count: 0,
      scored_active_count: 2,
      failed_active_count: 0,
      scored_inactive_count: 2,
      failed_inactive_count: 0,
      failure_codes_active: {},
      failure_codes_inactive: {},
    },
  });
  const flexEval = syntheticEvaluation("flex-vina", "FlexRes Vina", "calibration", 0.74, {
    failure_census: {
      total_parents: 4,
      scored_count: 3,
      failed_count: 1,
      scored_active_count: 2,
      failed_active_count: 0,
      scored_inactive_count: 1,
      failed_inactive_count: 1,
      failure_codes_active: {},
      failure_codes_inactive: { VINA_NONZERO: 1 },
    },
  });
  return {
    ...base,
    status: "calibration_selected",
    confirmation_locked: true,
    confirmation_consumed: false,
    baseline_protocol_id: "rigid-vina",
    calibration_selection: {
      schema_version: 1,
      selected_at: "2026-11-19T12:05:00Z",
      split_identity_sha256: SHA_1,
      baseline_protocol_id: "rigid-vina",
      best_point_protocol_id: "flex-vina",
      selected_protocol_id: "rigid-vina",
      selected_by_one_se_parsimony: true,
      evaluations: [rigidEval, flexEval],
      deltas_vs_best: [
        {
          candidate_protocol_id: "rigid-vina",
          reference_protocol_id: "flex-vina",
          split_name: "calibration",
          metric_name: "bedroc",
          bedroc_alpha: 20,
          point_delta: -0.03,
          bootstrap_se: 0.08,
          ci_lower: -0.18,
          ci_upper: 0.12,
          confidence_level: 0.95,
          replicates: 2000,
          bootstrap_seed: 20261119,
          excludes_zero_positively: false,
          within_one_se_of_reference: true,
        },
      ],
      deltas_vs_baseline: [
        {
          candidate_protocol_id: "flex-vina",
          reference_protocol_id: "rigid-vina",
          split_name: "calibration",
          metric_name: "bedroc",
          bedroc_alpha: 20,
          point_delta: 0.03,
          bootstrap_se: 0.08,
          ci_lower: -0.12,
          ci_upper: 0.18,
          confidence_level: 0.95,
          replicates: 2000,
          bootstrap_seed: 20261119,
          excludes_zero_positively: false,
          within_one_se_of_reference: true,
        },
      ],
      selection_identity_sha256: SHA_3,
      ...overrides,
    },
  };
}

function syntheticConfirmedRun(
  verdict: ConfirmationEvaluationRecord["verdict"],
): CalibrationRunRecord {
  const preferred = verdict === "preferred_over_baseline";
  const selected = syntheticSelectedRun({
    selected_protocol_id: "flex-vina",
    selected_by_one_se_parsimony: false,
  });
  const selectedEval = syntheticEvaluation(
    "flex-vina",
    "FlexRes Vina",
    "confirmation",
    preferred ? 0.89 : 0.48,
  );
  const baselineEval = syntheticEvaluation(
    "rigid-vina",
    "Rigid Vina",
    "confirmation",
    0.52,
  );
  return {
    ...selected,
    status: "confirmation_completed",
    confirmation_locked: false,
    confirmation_consumed: true,
    confirmation_evaluation: {
      schema_version: 1,
      evaluated_at: "2026-11-19T12:15:00Z",
      split_identity_sha256: SHA_1,
      selection_identity_sha256: SHA_3,
      baseline_protocol_id: "rigid-vina",
      selected_protocol_id: "flex-vina",
      verdict,
      verdict_text: preferred
        ? "Preferred over baseline (paired 95% CI excludes zero positively)"
        : INSUFFICIENT_EVIDENCE_TEXT,
      selected_evaluation: selectedEval,
      baseline_evaluation: baselineEval,
      paired_delta_vs_baseline: {
        candidate_protocol_id: "flex-vina",
        reference_protocol_id: "rigid-vina",
        split_name: "confirmation",
        metric_name: "bedroc",
        bedroc_alpha: 20,
        point_delta: preferred ? 0.37 : -0.04,
        bootstrap_se: 0.09,
        ci_lower: preferred ? 0.19 : -0.21,
        ci_upper: preferred ? 0.55 : 0.13,
        confidence_level: 0.95,
        replicates: 2000,
        bootstrap_seed: 20261119,
        excludes_zero_positively: preferred,
        within_one_se_of_reference: !preferred,
      },
      all_candidate_audit_evaluations: [selectedEval, baselineEval],
      confirmation_identity_sha256: SHA_4,
    },
  };
}

describe("M2c Validation workspace switch and two-stage Protocol Calibration UI", () => {
  it("defaults Validation to Redocking and switches cleanly to Protocol calibration", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/results/campaigns?")) {
        return json({ entries: [], total: 0, offset: 0, limit: 25 });
      }
      if (url.endsWith("/calibrations")) {
        return json({ runs: [] });
      }
      return json([]);
    });

    render(<RedockingWorkspace receptorId="synth-rec-1" bindingSiteId="synth-site-1" />);
    expect(
      await screen.findByRole("region", { name: "Redocking validation workspace" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Protocol calibration" }));
    expect(
      await screen.findByRole("region", { name: "Protocol calibration workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Receptor")).toHaveValue("synth-rec-1");
    expect(screen.getByLabelText("Binding site")).toHaveValue("synth-site-1");
  });

  it("creates a Stage 1 scaffold-grouped split, surfaces decoy bias & power alerts, and keeps Confirmation locked", async () => {
    const splitRun = syntheticSplitLockedRun();
    vi.spyOn(ankoraApi, "listCalibrations").mockResolvedValue([]);
    const createSpy = vi.spyOn(ankoraApi, "createCalibrationSplit").mockResolvedValue(splitRun);

    render(<ProtocolCalibrationWorkspace receptorId="synth-rec-1" bindingSiteId="synth-site-1" />);
    await screen.findByText("No calibration run recorded yet");

    fireEvent.change(
      screen.getByLabelText(/Compound rows/),
      {
        target: {
          value: [
            "SYNTH_A1, c1ccccc1O, active",
            "SYNTH_A2, c1ccncc1O, active",
            "SYNTH_I1, c1ccc2ccccc2c1, inactive",
            "SYNTH_I2, C1CCCCC1, inactive",
          ].join("\n"),
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create split and lock Confirmation" }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const stage1 = await screen.findByRole("region", {
      name: "Calibration split and bias audit",
    });
    expect(within(stage1).getByText("CALIBRATION_DECOY_PROPERTY_BIAS")).toBeInTheDocument();
    expect(within(stage1).getByText("CALIBRATION_CONFIRMATION_UNDERPOWERED")).toBeInTheDocument();
    expect(within(stage1).getByText("Property bias")).toBeInTheDocument();
    expect(within(stage1).getByText("Confirmation is locked")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Unlock and evaluate Confirmation/ }),
    ).not.toBeInTheDocument();
  });

  it("highlights 1-SE parsimony retention of rigid baseline, active/inactive failure census, EF caution, and unlocks Stage 3", async () => {
    const selectedRun = syntheticSelectedRun();
    vi.spyOn(ankoraApi, "listCalibrations").mockResolvedValue([selectedRun]);

    render(<ProtocolCalibrationWorkspace />);
    const stage2 = await screen.findByRole("region", {
      name: "Calibration evaluation and selection",
    });
    expect(
      within(stage2).getByText(/1-SE parsimony rule retained the simpler protocol/i),
    ).toBeInTheDocument();
    expect(
      within(stage2).getByText(/rigid baseline was retained/i),
    ).toBeInTheDocument();
    expect(within(stage2).getAllByText("small-sample caution").length).toBeGreaterThanOrEqual(1);
    expect(within(stage2).getByText("1 / 1")).toBeInTheDocument();

    // Stage 3 single-use trigger is now visible, gated by explicit checkbox acknowledgement.
    const confirmButton = screen.getByRole("button", {
      name: "Unlock and evaluate Confirmation (single use)",
    });
    expect(confirmButton).toBeDisabled();
    expect(
      screen.getByText(/Confirmation is single-use and permanently consumed once evaluated/i),
    ).toBeInTheDocument();
  });

  it("renders verbatim null verdict phrase, paired Δ BEDROC CI, audit table, and permanently removes re-run button once Confirmation is consumed", async () => {
    const nullRun = syntheticConfirmedRun("insufficient_evidence_to_prefer_over_baseline");
    vi.spyOn(ankoraApi, "listCalibrations").mockResolvedValue([nullRun]);

    render(<ProtocolCalibrationWorkspace />);
    const verdictBox = await screen.findByRole("status", { name: "Confirmation verdict" });
    expect(verdictBox).toHaveTextContent(INSUFFICIENT_EVIDENCE_TEXT);
    expect(
      screen.getByText("Confirmation consumed — immutable"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "All-candidate confirmation audit evaluations" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Unlock and evaluate Confirmation/ }),
    ).not.toBeInTheDocument();
  });

  it("renders positive PREFERRED_OVER_BASELINE verdict with paired CI excluding zero", async () => {
    const preferredRun = syntheticConfirmedRun("preferred_over_baseline");
    vi.spyOn(ankoraApi, "listCalibrations").mockResolvedValue([preferredRun]);

    render(<ProtocolCalibrationWorkspace />);
    const verdictBox = await screen.findByRole("status", { name: "Confirmation verdict" });
    expect(verdictBox).toHaveTextContent("Preferred over baseline");
    expect(screen.getByText("Excludes zero positively")).toBeInTheDocument();
    expect(screen.getByText("+0.3700")).toBeInTheDocument();
  });
});

describe("M2c PoseInteractionPanel opt-in --score_only cross-scoring", () => {
  const flexInventory: PoseInventory = {
    ...baseInventory,
    poses: [
      {
        ...baseInventory.poses[0],
        pose_flex_sidechains_sha256: SHA_2,
        flex_content_url: "/docking/jobs/job-flex-1/poses/pose-1/flex",
        pose_complex_identity_sha256: SHA_3,
      },
    ],
  };

  const vinaJobEntry: CatalogEntry = {
    ...baseEntry,
    catalog_id: "vina_job:job-flex-1",
    engine_key: "vina_job",
    record_id: "job-flex-1",
  };

  it("evaluates saved FlexRes pose in place in native units without pooling and surfaces Gate 0 F4 shift notice", async () => {
    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([]);

    const syntheticRescore: PoseRescoreResult = {
      schema_version: 1,
      pose_complex: {
        mode: "sidechain_flex",
        receptor_rigid_sha256: SHA_1,
        pose_flex_sidechains_sha256: SHA_2,
        ligand_pose_sha256: SHA_3,
      },
      observations: [
        {
          schema_version: 1,
          protocol_identity_sha256: SHA_1,
          parent_compound_id: molecule.ligand_id,
          parent_state_id: "synth-prep-1",
          scoring_family: "vina_vinardo",
          scoring_function: "vina",
          direction: "lower_is_better",
          unit: "kcal/mol",
          tool_name: "AutoDock Vina",
          tool_version: "1.2.7",
          status: "scored",
          raw_score: -6.25,
        },
        {
          schema_version: 1,
          protocol_identity_sha256: SHA_2,
          parent_compound_id: molecule.ligand_id,
          parent_state_id: "synth-prep-1",
          scoring_family: "vina_vinardo",
          scoring_function: "vinardo",
          direction: "lower_is_better",
          unit: "kcal/mol",
          tool_name: "AutoDock Vina",
          tool_version: "1.2.7",
          status: "scored",
          raw_score: -6.91,
        },
        {
          schema_version: 1,
          protocol_identity_sha256: SHA_4,
          parent_compound_id: molecule.ligand_id,
          parent_state_id: "synth-prep-1",
          scoring_family: "gnina_neural",
          scoring_function: "gnina_cnn_score",
          direction: "higher_is_better",
          unit: "dimensionless",
          tool_name: "GNINA",
          tool_version: "1.3.3",
          status: "scored",
          raw_score: 0.8412,
        },
      ],
      evidence: [
        {
          scoring_functions: ["vina"],
          tool_name: "AutoDock Vina",
          tool_version: "1.2.7",
          command: ["vina", "--score_only", "--flex", "pose_flex.pdbqt"],
          exit_code: 0,
          stdout_sha256: SHA_1,
          stderr_sha256: SHA_2,
          used_flex: true,
          unbound_reference_shifted: true,
          unbound_system_energy_kcal_mol: -0.3,
        },
      ],
      mutated_original_pose: false,
    };
    const rescoreSpy = vi.spyOn(ankoraApi, "rescorePoseOnly").mockResolvedValue(syntheticRescore);

    render(<PoseInteractionPanel entry={vinaJobEntry} molecule={molecule} onClose={() => {}} />);
    await screen.findByTestId("m2c-viewer-sources");

    // Opt-in disclosure toggle
    fireEvent.click(screen.getByRole("button", { name: "Cross-score (--score_only)" }));
    const panel = screen.getByRole("region", { name: "Cross-score pose (--score_only)" });
    // Add GNINA CNNscore alongside default Vina + Vinardo
    fireEvent.click(within(panel).getByRole("checkbox", { name: /GNINA CNNscore/i }));
    fireEvent.click(within(panel).getByRole("button", { name: "Cross-score pose (--score_only)" }));

    await waitFor(() => expect(rescoreSpy).toHaveBeenCalledWith({
      source_engine: "vina",
      job_id: "job-flex-1",
      pose_artifact_id: flexInventory.poses[0].artifact_id,
      scoring_functions: ["vina", "vinardo", "gnina_cnn_score"],
    }));

    const results = await screen.findByRole("region", {
      name: "Cross-score (--score_only) results",
    });
    expect(results).toHaveTextContent(/mutated_original_pose: false/i);
    expect(within(results).getByRole("alert")).toHaveTextContent(/Gate 0 F4/i);
    expect(within(results).getByText("-6.2500")).toBeInTheDocument();
    expect(within(results).getByText("-6.9100")).toBeInTheDocument();
    expect(within(results).getByText("0.8412")).toBeInTheDocument();
    expect(within(results).getByText("dimensionless")).toBeInTheDocument();
  });
});
