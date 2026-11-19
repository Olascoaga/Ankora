import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ankoraApi } from "../api/client";
import { PoseInteractionPanel } from "../features/results/PoseInteractionPanel";
import type { PoseInventory, PoseQualityRecord } from "../types/api";
import type { ViewerSource } from "../viewer/adapter";
import {
  entry as baseEntry,
  inventory as baseInventory,
  molecule,
} from "./fixtures/interactionPresentation";

// Spy only at the 3D viewer boundary; all M3 quality UI components and API
// calls run against synthetic fixtures explicitly labelled synthetic.
vi.mock("../viewer/MolecularViewer", () => ({
  MolecularViewer: ({ sources }: { sources: ViewerSource[] }) => (
    <div data-testid="m3-viewer-sources" data-sources={JSON.stringify(sources)} />
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const SHA_1 = "1".repeat(64);
const SHA_2 = "2".repeat(64);
const SHA_3 = "3".repeat(64);
const SHA_4 = "4".repeat(64);

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

function syntheticQualityRecord(
  overrides: Partial<PoseQualityRecord> = {},
): PoseQualityRecord {
  return {
    schema_version: 1,
    assessment_id: "assess-m3-1",
    created_at: "2026-11-19T14:00:00Z",
    catalog_id: baseEntry.catalog_id,
    engine_key: baseEntry.engine_key,
    record_id: baseEntry.record_id,
    engine_label: baseEntry.engine_label,
    ligand_id: molecule.ligand_id,
    ligand_preparation_id: "synth-prep-1",
    conformer_id: "synth-conf-1",
    conformer_sha256: SHA_1,
    parent_state_id: "synth-prep-1",
    receptor_id: "synth-rec-1",
    docking_receptor_artifact_id: "art-rigid",
    docking_receptor_sha256: SHA_1,
    analysis_receptor_artifact_id: "art-prot",
    analysis_receptor_sha256: SHA_2,
    materialized_coupled_receptor_sha256: SHA_4,
    pose: flexInventory.poses[0],
    posebusters_version: "0.6.5",
    assessment: {
      schema_version: 1,
      pose_complex: {
        mode: "sidechain_flex",
        receptor_rigid_sha256: SHA_1,
        pose_flex_sidechains_sha256: SHA_2,
        ligand_pose_sha256: flexInventory.poses[0].sha256,
      },
      overall_status: "pass",
      checks: [
        {
          check_id: "pb_minimum_distance_to_protein",
          tool_name: "PoseBusters",
          tool_version: "0.6.5",
          status: "pass",
          value: 1.04,
          threshold: 0.75,
          message: "pairwise protein clashes: 0",
        },
        {
          check_id: "pb_minimum_distance_to_waters",
          tool_name: "PoseBusters",
          tool_version: "0.6.5",
          status: "not_applicable",
          value: null,
          threshold: 0.75,
          message: "No waters within the prepared receptor evaluation window.",
        },
        {
          check_id: "flex_sidechain_bond_lengths",
          tool_name: "Ankora FlexComplexGeometry",
          tool_version: "0.2.0",
          status: "pass",
          value: 0.0021,
          threshold: 0.05,
          message: "Checked 7 covalent heavy-atom bonds across 1 FlexRes residue(s).",
        },
        {
          check_id: "conformational_strain_mmff94s",
          tool_name: "RDKit MMFF94s",
          tool_version: "2025.9.6",
          status: "pass",
          value: 1.45,
          threshold: 10.0,
          message: "Diagnostic flag only; finite conformer budget does not claim a global minimum.",
        },
      ],
      strain: {
        force_field: "MMFF94s",
        parent_state_id: "synth-prep-1",
        hydrogen_policy: "explicit_hydrogens_parent_state_preserved",
        conformer_seed: 20261119,
        conformer_budget: 50,
        pose_restrained_energy_kcal_mol: 12.65,
        lowest_free_conformer_energy_kcal_mol: 11.2,
        delta_e_ref_kcal_mol: 1.45,
      },
      mutated_original_pose: false,
    },
    passed_count: 3,
    failed_count: 0,
    not_applicable_count: 1,
    not_evaluable_count: 0,
    warnings: [],
    provenance: {
      event_id: "evt-m3-1",
      event_type: "pose_quality_assessed",
      timestamp: "2026-11-19T14:00:00Z",
      input_artifacts: ["art-rigid"],
      output_artifacts: ["assess-m3-1"],
      tool: { name: "PoseBusters", version: "0.6.5" },
      parameters: {},
      warnings: [],
      command: null,
    },
    ...overrides,
  };
}

describe("M3 PoseQualitySection inside PoseInteractionPanel", () => {
  it("stays strictly opt-in on mount, runs coupled FlexRes assessment, renders 4-state counts and MMFF94s strain disclaimer", async () => {
    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([]);
    const listQualitySpy = vi
      .spyOn(ankoraApi, "listPoseQualityAssessments")
      .mockResolvedValue([]);
    const assessSpy = vi
      .spyOn(ankoraApi, "assessPoseQuality")
      .mockResolvedValue(syntheticQualityRecord());

    render(<PoseInteractionPanel entry={baseEntry} molecule={molecule} onClose={() => {}} />);
    await screen.findByTestId("m3-viewer-sources");
    // Opt-in discipline: zero unsolicited quality API calls on mount
    expect(listQualitySpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Pose quality (PoseBusters + MMFF94s)" }));
    const panel = await screen.findByRole("region", {
      name: "Pose physical plausibility (PoseBusters and MMFF94s)",
    });
    await waitFor(() => expect(listQualitySpy).toHaveBeenCalledTimes(1));

    fireEvent.click(
      within(panel).getByRole("button", {
        name: "Assess pose quality (PoseBusters + MMFF94s)",
      }),
    );
    await waitFor(() =>
      expect(assessSpy).toHaveBeenCalledWith(
        baseEntry.catalog_id,
        molecule.ligand_id,
        flexInventory.poses[0].artifact_id,
        {
          include_strain: true,
          conformer_budget: 50,
          conformer_seed: 20261119,
          strain_flag_threshold_kcal_mol: 10,
        },
      ),
    );

    const results = await screen.findByRole("region", { name: "Pose quality results" });
    expect(results).toHaveTextContent("Overall: Pass");
    expect(results).toHaveTextContent("3 pass · 0 fail · 1 N/A · 0 not evaluable");
    expect(results).toHaveTextContent(/mutated_original_pose: false/i);
    expect(results).toHaveTextContent(/Evaluated on coupled FlexRes complex \(E8\)/i);

    const strainCard = screen.getByRole("region", {
      name: "Dual MMFF94s conformational strain",
    });
    expect(strainCard).toHaveTextContent("+1.45 kcal/mol");
    expect(strainCard).toHaveTextContent(/never added to or subtracted from any docking score/i);
    expect(strainCard).toHaveTextContent("explicit_hydrogens_parent_state_preserved");

    // Status filter isolates not_applicable rows cleanly
    fireEvent.change(within(results).getByLabelText("Filter checks by status"), {
      target: { value: "not_applicable" },
    });
    const table = within(results).getByRole("table", { name: "Pose quality diagnostic checks" });
    expect(within(table).getAllByRole("row")).toHaveLength(2); // header + 1 N/A row
    expect(within(table).getByText("pb_minimum_distance_to_waters")).toBeInTheDocument();
  });

  it("surfaces failed FlexRes clash warnings and unparameterizable not_evaluable status without hiding or softening them", async () => {
    const failedRecord = syntheticQualityRecord({
      assessment_id: "assess-m3-fail",
      assessment: {
        ...syntheticQualityRecord().assessment,
        overall_status: "fail",
        strain: null,
        checks: [
          {
            check_id: "pb_minimum_distance_to_protein",
            tool_name: "PoseBusters",
            tool_version: "0.6.5",
            status: "fail",
            value: 0.21,
            threshold: 0.75,
            message: "pairwise protein clashes: 3",
          },
          {
            check_id: "conformational_strain_mmff94s",
            tool_name: "RDKit MMFF94s",
            tool_version: "2025.9.6",
            status: "not_evaluable",
            value: null,
            threshold: 10.0,
            message: "MMFF94s lacks force-field parameters; Ankora refuses silent UFF fallback.",
          },
        ],
      },
      passed_count: 0,
      failed_count: 1,
      not_applicable_count: 0,
      not_evaluable_count: 1,
      warnings: [
        {
          code: "POSE_QUALITY_CHECKS_FAILED",
          stage: "pose_quality_assessment",
          message: "1 physical plausibility check(s) failed; pose retained.",
          recoverable: true,
          details: { failed_check_ids: ["pb_minimum_distance_to_protein"] },
        },
        {
          code: "POSE_QUALITY_MMFF94S_UNPARAMETERIZED",
          stage: "pose_quality_strain",
          message: "MMFF94s lacks parameters for boron.",
          recoverable: true,
          details: {},
        },
      ],
    });

    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([]);
    vi.spyOn(ankoraApi, "listPoseQualityAssessments").mockResolvedValue([failedRecord]);

    render(<PoseInteractionPanel entry={baseEntry} molecule={molecule} onClose={() => {}} />);
    await screen.findByTestId("m3-viewer-sources");
    fireEvent.click(screen.getByRole("button", { name: "Pose quality (PoseBusters + MMFF94s)" }));

    const results = await screen.findByRole("region", { name: "Pose quality results" });
    expect(results).toHaveTextContent("Overall: Fail");
    expect(results).toHaveTextContent("0 pass · 1 fail · 0 N/A · 1 not evaluable");
    const alert = within(results).getByRole("alert");
    expect(alert).toHaveTextContent("POSE_QUALITY_CHECKS_FAILED");
    expect(alert).toHaveTextContent("POSE_QUALITY_MMFF94S_UNPARAMETERIZED");
    expect(
      screen.queryByRole("region", { name: "Dual MMFF94s conformational strain" }),
    ).not.toBeInTheDocument();
  });
});
