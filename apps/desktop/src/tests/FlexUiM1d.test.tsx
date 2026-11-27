import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ankoraApi } from "../api/client";
import { ActiveFlexResBanner } from "../features/docking/ActiveFlexResBanner";
import { LigandFlexibilityControls } from "../features/ligand/LigandFlexibilityControls";
import {
  buildLigandFlexibilitySpec,
  emptyLigandFlexibilityDraft,
  validateSmartsRigidifications,
} from "../features/ligand/ligandFlexibility";
import {
  admitFlexResidues,
  exceedsFlexDofBudget,
  findDockingReceptorPdbqt,
  findFlexReceptorPdbqt,
} from "../features/receptor/flexResidues";
import { PoseInteractionPanel } from "../features/results/PoseInteractionPanel";
import type {
  CatalogEntry,
  GninaLocalRefinementRecord,
  LigandPdbqtRecord,
  PoseInventory,
  ReceptorPreparationRecord,
  VinaLocalRefinementRecord,
} from "../types/api";
import type { ViewerSource } from "../viewer/adapter";
import { entry as baseEntry, inventory as baseInventory, molecule } from "./fixtures/interactionPresentation";

// Spy only at the 3D viewer boundary so we can assert exact ViewerSource payloads.
vi.mock("../viewer/MolecularViewer", () => ({
  MolecularViewer: ({ sources }: { sources: ViewerSource[] }) => (
    <div data-testid="flex-viewer-sources" data-sources={JSON.stringify(sources)} />
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);

function flexReceptorRecord(overrides: Partial<ReceptorPreparationRecord> = {}): ReceptorPreparationRecord {
  return {
    receptor_id: "rec-flex-1",
    source_artifact_id: "src-1",
    created_at: "2026-11-18T12:00:00Z",
    status: "docking_ready",
    display_output_artifact_id: "out-prot",
    decisions: {
      selected_chains: ["A"],
      water_action: "remove",
      reference_component_id: null,
      component_decisions: [],
      issue_decisions: [],
      relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 10.0, max_iterations: 200 },
      protonation: { enabled: true, ph: 7.4, force_field: "PARSE" },
      generate_pdbqt: true,
      flexibility: {
        mode: "sidechain_flex",
        flex_residues: [
          { chain_id: "A", residue_name: "TYR", sequence_number: 4, insertion_code: "" },
          { chain_id: "A", residue_name: "MET", sequence_number: 5, insertion_code: "" },
        ],
      },
    },
    flex_spec: {
      mode: "sidechain_flex",
      flex_residues: [
        { chain_id: "A", residue_name: "TYR", sequence_number: 4, insertion_code: "" },
        { chain_id: "A", residue_name: "MET", sequence_number: 5, insertion_code: "" },
      ],
      receptor_rigid_sha256: SHA_A,
      receptor_flex_sha256: SHA_B,
      added_chi_torsion_count: 6,
    },
    flex_atom_types: ["C", "OA", "SA"],
    outputs: [
      {
        artifact_id: "out-prot",
        stage: "protonated_pdb",
        filename: "protonated.pdb",
        format: "pdb",
        sha256: SHA_C,
        size_bytes: 1200,
        created_at: "2026-11-18T12:00:00Z",
        content_url: "/receptors/rec-flex-1/outputs/out-prot/content",
      },
      {
        artifact_id: "out-rigid",
        stage: "pdbqt_rigid",
        filename: "receptor_rigid.pdbqt",
        format: "pdbqt",
        sha256: SHA_A,
        size_bytes: 900,
        created_at: "2026-11-18T12:00:00Z",
        content_url: "/receptors/rec-flex-1/outputs/out-rigid/content",
      },
      {
        artifact_id: "out-flex",
        stage: "pdbqt_flex",
        filename: "receptor_flex.pdbqt",
        format: "pdbqt",
        sha256: SHA_B,
        size_bytes: 300,
        created_at: "2026-11-18T12:00:00Z",
        content_url: "/receptors/rec-flex-1/outputs/out-flex/content",
      },
    ],
    warnings: [],
    provenance: [],
    ...overrides,
  };
}

function LigandFlexibilityHarness({ pdbqt = null }: { pdbqt?: LigandPdbqtRecord | null }) {
  const [draft, setDraft] = useState(emptyLigandFlexibilityDraft);
  return (
    <div>
      <LigandFlexibilityControls draft={draft} setDraft={setDraft} pdbqt={pdbqt} busy={false} />
      <pre data-testid="spec-json">{JSON.stringify(buildLigandFlexibilitySpec(draft))}</pre>
    </div>
  );
}

describe("M1d explicit semi-flexible ligand controls", () => {
  it("keeps untouched defaults null and emits explicit specs only when customized", () => {
    render(<LigandFlexibilityHarness />);
    expect(screen.getByTestId("spec-json")).toHaveTextContent("null");

    // Select rigid_input_conformation
    fireEvent.click(screen.getByRole("radio", { name: /Rigid input conformation/i }));
    expect(JSON.parse(screen.getByTestId("spec-json").textContent ?? "null")).toEqual({
      macrocycle_policy: "rigid_input_conformation",
      rigidified_smarts: [],
      rigidified_bond_indices: [],
      flexible_amides: false,
      local_only_refinement: false,
    });

    // Enable --flexible_amides and check planarity warning
    fireEvent.click(screen.getByRole("checkbox", { name: /Allow amide bonds to rotate/i }));
    expect(screen.getByText("LIG_FLEXIBLE_AMIDES_PLANARITY")).toBeInTheDocument();
  });

  it("validates SMARTS bond rows and refuses duplicate or self-bond indices", () => {
    const { errors } = validateSmartsRigidifications([
      { smarts: "", firstAtom: "1", secondAtom: "2" },
      { smarts: "[CX3](=O)[NX3]", firstAtom: "2", secondAtom: "2" },
      { smarts: "CC", firstAtom: "1", secondAtom: "2" },
      { smarts: "CN", firstAtom: "2", secondAtom: "1" },
    ]);
    expect(errors.get(0)).toMatch(/Enter a SMARTS pattern/i);
    expect(errors.get(1)).toMatch(/two distinct atoms/i);
    expect(errors.get(2)).toBeUndefined();
    expect(errors.get(3)).toMatch(/already rigidified/i);
  });

  it("surfaces LIG_RIGIDIFY_SMARTS_NO_MATCH outcomes and effective TORSDOF after preparation", () => {
    const pdbqt: LigandPdbqtRecord = {
      artifact: {
        preparation_id: "prep-1",
        ligand_id: "lig-1",
        conformer_id: "conf-1",
        filename: "ligand.pdbqt",
        format: "pdbqt",
        sha256: SHA_A,
        size_bytes: 512,
        created_at: "2026-11-18T12:00:00Z",
      },
      charge_model: "gasteiger",
      tool: { name: "Meeko", version: "0.7.1" },
      command: ["mk_prepare_ligand"],
      stdout: "",
      stderr: "",
      provenance: {
        event_id: "evt-1",
        event_type: "ligand_pdbqt_prepared",
        timestamp: "2026-11-18T12:00:00Z",
        input_artifacts: ["conf-1"],
        output_artifacts: ["prep-1"],
        tool: { name: "Meeko", version: "0.7.1" },
        parameters: {},
        warnings: [],
        command: null,
      },
      content_url: "/ligands/lig-1/preparations/prep-1/content",
      effective_torsdof: 3,
      smarts_rigidification_outcomes: [
        {
          smarts: "[CX3](=O)[NX3]",
          bond_indices: [1, 3],
          match_count: 0,
          matched_bonds_zero_based: [],
          applied: false,
        },
      ],
      warnings: [
        {
          code: "LIG_RIGIDIFY_SMARTS_NO_MATCH",
          stage: "ligand_preparation",
          message: "SMARTS pattern matched 0 bonds.",
          details: {},
          recoverable: true,
        },
      ],
    };
    render(<LigandFlexibilityHarness pdbqt={pdbqt} />);
    expect(screen.getByRole('alert')).toHaveTextContent('LIG_RIGIDIFY_SMARTS_NO_MATCH');
    expect(screen.getAllByText(/LIG_RIGIDIFY_SMARTS_NO_MATCH/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/effective TORSDOF\s*3/)).toBeInTheDocument();
  });
});

describe("M1d receptor FlexRes admission rules and ActiveFlexResBanner", () => {
  it("hard-rejects GLY, ALA, PRO, CYX and duplicate positions while accepting TYR and MET", () => {
    const result = admitFlexResidues([
      { chain_id: "A", residue_name: "GLY", sequence_number: 1, insertion_code: "" },
      { chain_id: "A", residue_name: "ALA", sequence_number: 2, insertion_code: "" },
      { chain_id: "A", residue_name: "PRO", sequence_number: 6, insertion_code: "" },
      { chain_id: "A", residue_name: "CYX", sequence_number: 7, insertion_code: "" },
      { chain_id: "A", residue_name: "TYR", sequence_number: 4, insertion_code: "" },
      { chain_id: "A", residue_name: "TYR", sequence_number: 4, insertion_code: "" },
      { chain_id: "A", residue_name: "MET", sequence_number: 5, insertion_code: "" },
    ]);
    expect(result.accepted.map((item) => item.residue_name)).toEqual(["TYR", "MET"]);
    expect(result.rejections).toHaveLength(5);
    expect(exceedsFlexDofBudget(4, 12)).toBe(false);
    expect(exceedsFlexDofBudget(5, 10)).toBe(true);
    expect(exceedsFlexDofBudget(3, 13)).toBe(true);
  });

  it("recognizes pdbqt_rigid and pdbqt_flex outputs for docking readiness", () => {
    const receptor = flexReceptorRecord();
    expect(findDockingReceptorPdbqt(receptor.outputs)?.stage).toBe("pdbqt_rigid");
    expect(findFlexReceptorPdbqt(receptor.outputs)?.stage).toBe("pdbqt_flex");
  });

  it("renders ActiveFlexResBanner for sidechain_flex with AutoGrid4 union requirement and DOF warning", () => {
    const rigid = flexReceptorRecord({ flex_spec: undefined });
    const { container } = render(<ActiveFlexResBanner receptor={rigid} engineFamily="vina" />);
    expect(container.firstChild).toBeNull();

    const highDof = flexReceptorRecord({
      flex_spec: {
        mode: "sidechain_flex",
        flex_residues: [
          { chain_id: "A", residue_name: "TYR", sequence_number: 4, insertion_code: "" },
          { chain_id: "A", residue_name: "MET", sequence_number: 5, insertion_code: "" },
        ],
        receptor_rigid_sha256: SHA_A,
        receptor_flex_sha256: SHA_B,
        added_chi_torsion_count: 14,
      },
    });
    render(<ActiveFlexResBanner receptor={highDof} engineFamily="autodock4" />);
    expect(screen.getByRole("status", { name: "Active FlexRes split" })).toBeInTheDocument();
    expect(screen.getByText("TYR A:4")).toBeInTheDocument();
    expect(screen.getByText("MET A:5")).toBeInTheDocument();
    expect(screen.getByText(/AutoGrid4 must compute maps/i)).toBeInTheDocument();
    expect(screen.getByText("C OA SA")).toBeInTheDocument();
    expect(screen.getByText("DOCKING_FLEXRES_DOF_HIGH")).toBeInTheDocument();
  });
});

describe("M1d coupled FlexRes viewer overlay and create-only --local_only trigger", () => {
  const flexInventory: PoseInventory = {
    ...baseInventory,
    poses: [
      {
        ...baseInventory.poses[0],
        pose_flex_sidechains_sha256: SHA_B,
        flex_content_url: "/docking/jobs/job-flex-1/poses/pose-1/flex",
        pose_complex_identity_sha256: SHA_C,
      },
    ],
  };

  const vinaJobEntry: CatalogEntry = {
    ...baseEntry,
    catalog_id: "vina_job:job-flex-1",
    engine_key: "vina_job",
    record_id: "job-flex-1",
  };

  it("loads coupled PoseComplex by default, overlays translucent crystal rotamers on toggle, and triggers create-only Vina refinement", async () => {
    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([]);

    const refinedRecord: VinaLocalRefinementRecord = {
      refinement_id: "ref-vina-1",
      created_at: "2026-11-18T12:10:00Z",
      parent_job_id: "job-flex-1",
      parent_pose_artifact_id: flexInventory.poses[0].artifact_id,
      parent_pose_sha256: SHA_A,
      parent_pose_flex_sha256: SHA_B,
      receptor_id: "rec-flex-1",
      binding_site_id: "site-1",
      ligand_id: molecule.ligand_id,
      ligand_preparation_id: "prep-1",
      receptor_output_artifact_id: "out-rigid",
      receptor_sha256: SHA_A,
      receptor_flex_mode: "sidechain_flex",
      scoring: "vinardo",
      tool: { name: "AutoDock Vina", version: "1.2.7" },
      command: ["vina", "--local_only"],
      estimated_free_energy_kcal_mol: -7.42,
      intermolecular_kcal_mol: -8.1,
      total_internal_kcal_mol: -0.25,
      torsional_free_energy_kcal_mol: 0.93,
      unbound_system_energy_kcal_mol: 0.0,
      refined_pose: {
        artifact_id: "pose-ref-1",
        mode: 1,
        filename: "pose_1.pdbqt",
        format: "pdbqt",
        sha256: SHA_A,
        size_bytes: 256,
        content_url: "/docking/refinements/ref-vina-1/poses/pose-ref-1/content",
        flex_filename: "pose_1_flex.pdbqt",
        pose_flex_sidechains_sha256: SHA_B,
        flex_content_url: "/docking/refinements/ref-vina-1/poses/pose-ref-1/flex",
        pose_complex_identity_sha256: SHA_C,
      },
      execution: { command: ["vina", "--local_only"], exit_code: 0, stdout: "", stderr: "", timed_out: false, canceled: false },
      provenance: {
        event_id: "evt-ref",
        event_type: "vina_local_refinement_completed",
        timestamp: "2026-11-18T12:10:00Z",
        input_artifacts: ["job-flex-1"],
        output_artifacts: ["ref-vina-1"],
        tool: { name: "AutoDock Vina", version: "1.2.7" },
        parameters: {},
        warnings: [],
        command: null,
      },
    };
    const refineSpy = vi.spyOn(ankoraApi, "refineVinaPoseLocalOnly").mockResolvedValue(refinedRecord);

    render(<PoseInteractionPanel entry={vinaJobEntry} molecule={molecule} onClose={() => {}} />);

    const viewer = await screen.findByTestId("flex-viewer-sources");
    const defaultSources = JSON.parse(viewer.getAttribute("data-sources") ?? "[]") as ViewerSource[];
    expect(defaultSources).toHaveLength(1);
    expect(defaultSources[0].url).toContain("/complex");
    expect(defaultSources[0].label).toBe("Coupled FlexRes complex");

    // Toggle crystal rotamer reference overlay on
    fireEvent.click(screen.getByRole("checkbox", { name: /Overlay crystal rotamers/i }));
    const overlaySources = JSON.parse(
      screen.getByTestId("flex-viewer-sources").getAttribute("data-sources") ?? "[]",
    ) as ViewerSource[];
    expect(overlaySources.map((item) => item.appearance)).toEqual([
      "flex-crystal-reference",
      "flex-moved-sidechains",
      "interaction-ligand",
    ]);

    // Trigger create-only --local_only derivative
    fireEvent.click(screen.getByRole("button", { name: /Refine locally \(--local_only\)/i }));
    await waitFor(() => expect(refineSpy).toHaveBeenCalledWith({
      parent_job_id: "job-flex-1",
      parent_pose_artifact_id: flexInventory.poses[0].artifact_id,
    }));
    const resultRegion = await screen.findByRole("status", { name: "Local-only refinement derivative" });
    expect(resultRegion).toHaveTextContent("ref-vina-1");
    expect(resultRegion).toHaveTextContent("-7.420 kcal/mol");
    expect(resultRegion).toHaveTextContent(/Parent job and pose remain immutable/i);
  });

  it("triggers create-only GNINA refinement for gnina_job entries", async () => {
    vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(flexInventory);
    vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue([]);

    const gninaRefined: GninaLocalRefinementRecord = {
      refinement_id: "ref-gnina-1",
      created_at: "2026-11-18T12:12:00Z",
      parent_job_id: "gnina-job-1",
      parent_pose_artifact_id: flexInventory.poses[0].artifact_id,
      parent_pose_sha256: SHA_A,
      parent_pose_flex_sha256: SHA_B,
      receptor_id: "rec-flex-1",
      binding_site_id: "site-1",
      ligand_id: molecule.ligand_id,
      ligand_preparation_id: "prep-1",
      receptor_output_artifact_id: "out-rigid",
      receptor_sha256: SHA_A,
      receptor_flex_mode: "sidechain_flex",
      tool: { version: "1.3.3", sha256: SHA_A, architecture: "x86_64" },
      cnn_model_identity: {
        selector: "default_1_3_ensemble",
        cli_argument: null,
        member_names: ["dense_1_3"],
        member_count: 1,
      },
      command: ["gnina", "--local_only"],
      minimized_affinity_kcal_mol: -6.85,
      cnn_score: 0.89,
      cnn_affinity: 6.4,
      cnn_vs: 5.696,
      cnn_vs_source: "derived_from_recorded_axes",
      refined_pose: {
        artifact_id: "gnina-ref-pose-1",
        mode: 1,
        filename: "pose_1.pdbqt",
        sha256: SHA_A,
        size_bytes: 256,
        content_url: "/docking/gnina/refinements/ref-gnina-1/poses/gnina-ref-pose-1/content",
        flex_filename: "pose_1_flex.pdbqt",
        pose_flex_sidechains_sha256: SHA_B,
        flex_content_url: "/docking/gnina/refinements/ref-gnina-1/poses/gnina-ref-pose-1/flex",
        pose_complex_identity_sha256: SHA_C,
      },
      execution: {
        command: ["gnina", "--local_only"],
        exit_code: 0,
        stdout: "",
        stderr: "",
        timed_out: false,
        canceled: false,
        gpu_process_observed: false,
        gpu_observation: null,
        requested_gpu_uuid: null,
        observed_gpu_uuid: null,
      },
    };
    const refineSpy = vi.spyOn(ankoraApi, "refineGninaPoseLocalOnly").mockResolvedValue(gninaRefined);

    const gninaEntry: CatalogEntry = {
      ...baseEntry,
      catalog_id: "gnina_job:gnina-job-1",
      engine_key: "gnina_job",
      record_id: "gnina-job-1",
    };

    render(<PoseInteractionPanel entry={gninaEntry} molecule={molecule} onClose={() => {}} />);
    await screen.findByTestId("flex-viewer-sources");
    fireEvent.click(screen.getByRole("button", { name: /Refine locally \(--local_only\)/i }));
    await waitFor(() => expect(refineSpy).toHaveBeenCalledWith({
      parent_job_id: "gnina-job-1",
      parent_pose_artifact_id: flexInventory.poses[0].artifact_id,
    }));
    const resultRegion = await screen.findByRole("status", { name: "Local-only refinement derivative" });
    expect(resultRegion).toHaveTextContent("ref-gnina-1");
    expect(resultRegion).toHaveTextContent("-6.850 kcal/mol");
    expect(resultRegion).toHaveTextContent("0.890");
  });
});
