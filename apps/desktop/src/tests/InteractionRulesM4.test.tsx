import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ankoraApi } from "../api/client";
import { PoseInteractionPanel } from "../features/results/PoseInteractionPanel";
import type {
  InteractionRuleEvaluationRecord,
  InteractionRuleSetRecord,
  PoseInventory,
} from "../types/api";
import type { ViewerSelection, ViewerSource } from "../viewer/adapter";
import {
  analysis as makeAnalysis,
  contact as makeContact,
  entry as baseEntry,
  inventory as baseInventory,
  molecule,
} from "./fixtures/interactionPresentation";

// Spy only at the 3D viewer boundary; all M4 pharmacophore rule components and
// API interactions run against explicitly synthetic fixtures.
vi.mock("../viewer/MolecularViewer", () => ({
  MolecularViewer: ({
    sources,
    selection,
  }: {
    sources: ViewerSource[];
    selection?: ViewerSelection | null;
  }) => (
    <div
      data-testid="m4-viewer-mock"
      data-sources={JSON.stringify(sources)}
      data-selection={JSON.stringify(selection ?? null)}
    />
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const SHA_1 = "1".repeat(64);
const SHA_2 = "2".repeat(64);
const SHA_3 = "3".repeat(64);
const SHA_4 = "4".repeat(64);
const SHA_5 = "5".repeat(64);

const flexInventory: PoseInventory = {
  ...baseInventory,
  poses: [
    {
      ...baseInventory.poses[0],
      pose_flex_sidechains_sha256: SHA_2,
      flex_content_url: "/docking/jobs/job-flex-1/poses/pose/flex",
      pose_complex_identity_sha256: SHA_3,
    },
  ],
};

const syntheticContact1 = {
  ...makeContact(1, "HBDonor"),
  residue: { chain_id: "A", residue_name: "SER", sequence_number: 5, insertion_code: "" },
};

const syntheticRuleSet: InteractionRuleSetRecord = {
  schema_version: 1,
  rule_set_id: "rs-m4-1",
  created_at: "2026-11-19T14:20:00Z",
  name: "SER A:5 induced H-bond",
  description: "Sealed prior to Confirmation",
  receptor_id: baseEntry.receptor_id,
  receptor_protonated_artifact_id: "art-prot",
  receptor_protonated_sha256: SHA_1,
  profile: {
    profile_id: "ankora-default-v1",
    vicinity_cutoff_angstrom: 6,
    interactions: ["HBDonor", "HBAcceptor", "Hydrophobic"],
  },
  clauses: [
    {
      clause_id: "clause-1",
      label: "SER A:5 HBDonor",
      kind: "required",
      targets: [
        {
          residue: { chain_id: "A", residue_name: "SER", sequence_number: 5, insertion_code: "" },
          interaction_types: ["HBDonor"],
          max_distance_angstrom: 3.5,
        },
      ],
    },
  ],
  reference_ifp: {
    profile: {
      profile_id: "ankora-default-v1",
      vicinity_cutoff_angstrom: 6,
      interactions: ["HBDonor", "HBAcceptor", "Hydrophobic"],
    },
    bits: [
      {
        residue: { chain_id: "A", residue_name: "SER", sequence_number: 5, insertion_code: "" },
        interaction_type: "HBDonor",
      },
    ],
    counts: [
      {
        bit: {
          residue: { chain_id: "A", residue_name: "SER", sequence_number: 5, insertion_code: "" },
          interaction_type: "HBDonor",
        },
        count: 1,
      },
    ],
    source_kind: "pose_analysis",
    source_catalog_id: baseEntry.catalog_id,
    source_ligand_id: molecule.ligand_id,
    source_pose_artifact_id: flexInventory.poses[0].artifact_id,
    source_pose_complex_sha256: SHA_3,
    fingerprint_sha256: SHA_4,
  },
  min_tanimoto_similarity: 0.75,
  rule_set_identity_sha256: SHA_5,
  provenance: {
    event_id: "evt-rs-m4",
    event_type: "interaction_rule_set_created",
    timestamp: "2026-11-19T14:20:00Z",
    input_artifacts: ["art-prot"],
    output_artifacts: ["rs-m4-1"],
    tool: { name: "ProLIF", version: "2.2.1" },
    parameters: {},
    warnings: [],
    command: null,
  },
};

function syntheticEvaluation(
  overrides: Partial<InteractionRuleEvaluationRecord> = {},
): InteractionRuleEvaluationRecord {
  return {
    schema_version: 1,
    evaluation_id: "eval-m4-1",
    created_at: "2026-11-19T14:21:00Z",
    rule_set_id: syntheticRuleSet.rule_set_id,
    rule_set_name: syntheticRuleSet.name,
    rule_set_identity_sha256: syntheticRuleSet.rule_set_identity_sha256,
    catalog_id: baseEntry.catalog_id,
    engine_key: baseEntry.engine_key,
    record_id: baseEntry.record_id,
    engine_label: baseEntry.engine_label,
    ligand_id: molecule.ligand_id,
    ligand_preparation_id: "prep-1",
    conformer_id: "conf-1",
    conformer_sha256: SHA_1,
    receptor_id: baseEntry.receptor_id,
    docking_receptor_artifact_id: "art-rigid",
    docking_receptor_sha256: SHA_1,
    analysis_receptor_artifact_id: "art-prot",
    analysis_receptor_sha256: SHA_1,
    materialized_coupled_receptor_sha256: SHA_4,
    pose: flexInventory.poses[0],
    pose_complex: {
      mode: "sidechain_flex",
      receptor_rigid_sha256: SHA_1,
      pose_flex_sidechains_sha256: SHA_2,
      ligand_pose_sha256: flexInventory.poses[0].sha256,
    },
    interaction_analysis_id: null,
    detector: { name: "ProLIF", version: "2.2.1" },
    profile: syntheticRuleSet.profile,
    pose_ifp: syntheticRuleSet.reference_ifp!,
    contacts: [syntheticContact1],
    overall_status: "pass",
    clause_results: [
      {
        clause_id: "clause-1",
        label: "SER A:5 HBDonor",
        kind: "required",
        status: "pass",
        satisfied_target_count: 1,
        required_target_count: 1,
        matched_contact_ids: ["contact-1"],
        target_results: [
          {
            target: syntheticRuleSet.clauses[0].targets[0],
            matched: true,
            matched_contact_ids: ["contact-1"],
            shortest_distance_angstrom: 2.81,
          },
        ],
        explanation: "All 1 required target(s) matched (1 contact(s)).",
      },
    ],
    passed_clause_count: 1,
    failed_clause_count: 0,
    tanimoto: {
      reference_fingerprint_sha256: SHA_4,
      pose_fingerprint_sha256: SHA_4,
      status: "pass",
      similarity: 1.0,
      min_threshold: 0.75,
      intersection_count: 1,
      union_count: 1,
      shared_bits: [
        {
          residue: { chain_id: "A", residue_name: "SER", sequence_number: 5, insertion_code: "" },
          interaction_type: "HBDonor",
        },
      ],
      pose_only_bits: [],
      reference_only_bits: [],
    },
    mutated_original_pose: false,
    warnings: [],
    provenance: {
      event_id: "evt-eval-m4",
      event_type: "interaction_rules_evaluated",
      timestamp: "2026-11-19T14:21:00Z",
      input_artifacts: ["rs-m4-1"],
      output_artifacts: ["eval-m4-1"],
      tool: { name: "ProLIF", version: "2.2.1" },
      parameters: {},
      warnings: [],
      command: null,
    },
    ...overrides,
  };
}

describe("M4 InteractionRulesSection inside PoseInteractionPanel", () => {
  it("stays strictly opt-in on mount, builds a sealed rule set from detected contacts, evaluates coupled E8 pose, and focuses matched contact in 3D viewer", async () => {
    const existingAnalysis = makeAnalysis([syntheticContact1]);
    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([existingAnalysis]);
    const listRuleSetsSpy = vi
      .spyOn(ankoraApi, "listInteractionRuleSets")
      .mockResolvedValue([]);
    const listEvalsSpy = vi
      .spyOn(ankoraApi, "listPoseInteractionRuleEvaluations")
      .mockResolvedValue([]);
    const createRuleSetSpy = vi
      .spyOn(ankoraApi, "createInteractionRuleSet")
      .mockResolvedValue(syntheticRuleSet);
    const evaluateSpy = vi
      .spyOn(ankoraApi, "evaluatePoseInteractionRules")
      .mockResolvedValue(syntheticEvaluation());

    render(<PoseInteractionPanel entry={baseEntry} molecule={molecule} onClose={() => {}} />);
    await screen.findByTestId("m4-viewer-mock");
    // Opt-in discipline: zero unsolicited rule-set fetches on mount
    expect(listRuleSetsSpy).not.toHaveBeenCalled();
    expect(listEvalsSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Pharmacophore rules (ProLIF PIC)" }));
    const panel = await screen.findByRole("region", {
      name: "Declarative pharmacophoric interaction rules (ProLIF PIC)",
    });
    await waitFor(() => expect(listRuleSetsSpy).toHaveBeenCalledWith(baseEntry.receptor_id));

    // Quick-add from detected SER A:5 HBDonor contact opens builder prefilled
    fireEvent.click(
      within(panel).getByRole("button", {
        name: /\+ Required: SER A:5 · HBDonor/i,
      }),
    );
    const builder = await within(panel).findByRole("region", {
      name: "Create sealed interaction rule set",
    });
    fireEvent.change(within(builder).getByLabelText("Rule set name"), {
      target: { value: "SER A:5 induced H-bond" },
    });
    fireEvent.click(
      within(builder).getByLabelText("Use current pose as Tanimoto IFP reference"),
    );
    fireEvent.change(within(builder).getByLabelText("Min Tanimoto similarity"), {
      target: { value: "0.75" },
    });
    fireEvent.click(within(builder).getByRole("button", { name: "Create sealed rule set" }));

    await waitFor(() =>
      expect(createRuleSetSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "SER A:5 induced H-bond",
          receptor_id: baseEntry.receptor_id,
          min_tanimoto_similarity: 0.75,
          reference_pose: {
            catalog_id: baseEntry.catalog_id,
            ligand_id: molecule.ligand_id,
            pose_artifact_id: flexInventory.poses[0].artifact_id,
          },
        }),
      ),
    );

    fireEvent.click(
      within(panel).getByRole("button", { name: "Evaluate pose against rule set" }),
    );
    await waitFor(() =>
      expect(evaluateSpy).toHaveBeenCalledWith(
        baseEntry.catalog_id,
        molecule.ligand_id,
        flexInventory.poses[0].artifact_id,
        { rule_set_id: syntheticRuleSet.rule_set_id },
      ),
    );

    const results = await within(panel).findByRole("region", {
      name: "Pharmacophoric rule evaluation results",
    });
    expect(results).toHaveTextContent("Overall: Pass");
    expect(results).toHaveTextContent("1 passed · 0 failed");
    expect(results).toHaveTextContent(/Evaluated on coupled FlexRes complex \(E8\)/i);
    expect(results).toHaveTextContent(/mutated_original_pose: false/i);

    const tanimotoCard = within(results).getByRole("region", {
      name: "Tanimoto IFP similarity",
    });
    expect(tanimotoCard).toHaveTextContent("1.000");
    expect(tanimotoCard).toHaveTextContent("1 / 1");
    expect(tanimotoCard).toHaveTextContent("SER A:5 · HBDonor");

    // Clicking Focus contact-1 selects SER A:5 in the 3D MolecularViewer!
    fireEvent.click(within(results).getByRole("button", { name: "Focus contact-1" }));
    await waitFor(() => {
      const viewer = screen.getByTestId("m4-viewer-mock");
      expect(viewer.getAttribute("data-selection")).toContain('"residueName":"SER"');
      expect(viewer.getAttribute("data-selection")).toContain('"sequenceNumber":5');
    });
  });

  it("renders FORBIDDEN contact warnings and honest not_evaluable 0/0 empty-union Tanimoto", async () => {
    const emptyUnionFail = syntheticEvaluation({
      evaluation_id: "eval-m4-fail",
      overall_status: "fail",
      passed_clause_count: 0,
      failed_clause_count: 1,
      clause_results: [
        {
          clause_id: "forbid-ser5",
          label: "Must not H-bond SER A:5",
          kind: "forbidden",
          status: "fail",
          satisfied_target_count: 1,
          required_target_count: 0,
          matched_contact_ids: ["contact-1"],
          target_results: [
            {
              target: syntheticRuleSet.clauses[0].targets[0],
              matched: true,
              matched_contact_ids: ["contact-1"],
              shortest_distance_angstrom: 2.81,
            },
          ],
          explanation: "Detected 1 forbidden target(s) across 1 contact(s).",
        },
      ],
      tanimoto: {
        reference_fingerprint_sha256: SHA_4,
        pose_fingerprint_sha256: SHA_4,
        status: "not_evaluable",
        similarity: null,
        min_threshold: 0.5,
        intersection_count: 0,
        union_count: 0,
        shared_bits: [],
        pose_only_bits: [],
        reference_only_bits: [],
      },
      warnings: [
        {
          code: "INTERACTION_RULE_FORBIDDEN_CONTACT",
          stage: "interaction_rule_evaluation",
          message: "1 FORBIDDEN interaction clause(s) triggered on this pose complex.",
          recoverable: true,
          details: { forbidden_clause_ids: ["forbid-ser5"], contact_ids: ["contact-1"] },
        },
        {
          code: "INTERACTION_IFP_EMPTY_UNION",
          stage: "interaction_rule_evaluation",
          message: "Both pose and reference IFPs contain zero contacts (0/0 union).",
          recoverable: true,
          details: {},
        },
      ],
    });

    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([]);
    vi.spyOn(ankoraApi, "listInteractionRuleSets").mockResolvedValue([syntheticRuleSet]);
    vi.spyOn(ankoraApi, "listPoseInteractionRuleEvaluations").mockResolvedValue([emptyUnionFail]);

    render(<PoseInteractionPanel entry={baseEntry} molecule={molecule} onClose={() => {}} />);
    await screen.findByTestId("m4-viewer-mock");
    fireEvent.click(screen.getByRole("button", { name: "Pharmacophore rules (ProLIF PIC)" }));

    const results = await screen.findByRole("region", {
      name: "Pharmacophoric rule evaluation results",
    });
    expect(results).toHaveTextContent("Overall: Fail");
    expect(results).toHaveTextContent("FORBIDDEN (NOT)");
    expect(results).toHaveTextContent("INTERACTION_RULE_FORBIDDEN_CONTACT");
    expect(results).toHaveTextContent("INTERACTION_IFP_EMPTY_UNION");
    expect(results).toHaveTextContent("Not evaluable (0 / 0 empty union)");
  });
});
