import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";

import { SingleLigandPreparation } from "../features/ligand/SingleLigandPreparation";
import type { PreparationStep } from "../features/ligand/SingleLigandPreparation";
import type {
  LigandConformerRecord,
  LigandForceField,
  LigandInspection,
  LigandPdbqtRecord,
  LigandProtonationOptions,
} from "../types/api";

/**
 * One ligand, one action - and the places it must refuse to act.
 *
 * The point of merging five stages is not fewer clicks; it is that the click
 * states what it will do and stops where a decision or a gate genuinely exists.
 * These tests fix exactly those stopping points.
 */

const inspection = {
  name: "LIG", formula: "C2H4O", molecular_weight_g_mol: 44.053, exact_mass_da: 44.0262,
  canonical_smiles: "CCO",
  formal_charge: -1, atom_count: 3, heavy_atom_count: 3, rotatable_bond_count: 1,
  aromatic_ring_count: 0, stereocenter_count: 0, undefined_stereocenter_count: 0,
  fragment_count: 1, conformer_count: 1, has_3d_coordinates: true,
} satisfies LigandInspection;

function options(count: number): LigandProtonationOptions {
  return {
    parent_state_id: "state-1", ph_min: 6.4, ph_max: 8.4, precision: 1,
    selection_required: count > 1,
    candidates: Array.from({ length: count }, (_, index) => ({
      index,
      canonical_smiles: `C${"C".repeat(index)}O`,
      // Two charges across the list, so grouping has something to group.
      formal_charge: index % 2 === 0 ? -1 : 0,
    })),
  };
}

function conformerRecord(converged: boolean): LigandConformerRecord {
  return {
    artifact: {
      conformer_id: "conf-1", ligand_id: "lig-1", stage: "minimized",
      filename: "LIG.sdf", format: "sdf", sha256: "9".repeat(64),
      size_bytes: 620, created_at: "2026-08-25T00:00:00Z",
    },
    state_id: "state-1",
    minimization: {
      force_field: "MMFF94s", max_iterations: 500, converged,
      initial_energy_kcal_mol: 12.75, final_energy_kcal_mol: -4.125,
      embedding_method: "ETKDGv3", random_seed: 20260819,
      independent_from_source_coordinates: true, conformer_pool_size: 20,
      conformer_pool_converged_count: converged ? 18 : 0,
      conformer_selection_policy: converged
        ? "lowest_energy_converged"
        : "lowest_energy_nonconverged_fallback",
    },
    warnings: [], provenance: null, content_url: "/conf",
  } as unknown as LigandConformerRecord;
}

interface HarnessProps {
  protonationOptions?: LigandProtonationOptions | null;
  conformer?: LigandConformerRecord | null;
  pdbqt?: LigandPdbqtRecord | null;
  meekoAvailable?: boolean;
  blocked?: boolean;
  step?: PreparationStep;
  busy?: boolean;
  onPrepare?: () => void;
  onPhChange?: (next: { min?: number; max?: number; precision?: number }) => void;
  onSkipProtonation?: () => void;
  protonationSkipped?: boolean;
  protonationError?: string | null;
}

function Harness({
  protonationOptions = options(1),
  conformer = null,
  pdbqt = null,
  meekoAvailable = true,
  blocked = false,
  step = null,
  busy = false,
  onPrepare = () => {},
  onPhChange = () => {},
  onSkipProtonation = () => {},
  protonationSkipped = false,
  protonationError = null,
}: HarnessProps) {
  const [candidate, setCandidate] = useState<number | null>(
    protonationOptions && protonationOptions.candidates.length === 1 ? 0 : null,
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const [forceField, setForceField] = useState<LigandForceField>("MMFF94s");
  const [maxIterations, setMaxIterations] = useState(500);
  const [randomSeed, setRandomSeed] = useState(20260819);
  const [useSourceGeometry, setUseSourceGeometry] = useState(false);
  return (
    <SingleLigandPreparation
      inspection={inspection}
      activeState={null}
      activeProtonation={null}
      protonationOptions={protonationOptions}
      protonationCandidateIndex={candidate}
      onCandidateChange={setCandidate}
      protonationSkipped={protonationSkipped}
      protonationError={protonationError}
      onSkipProtonation={onSkipProtonation}
      onReconsiderProtonation={() => {}}
      phMin={6.4} phMax={8.4} phPrecision={1}
      onPhChange={onPhChange}
      forceField={forceField} setForceField={setForceField}
      maxIterations={maxIterations} setMaxIterations={setMaxIterations}
      randomSeed={randomSeed} setRandomSeed={setRandomSeed}
      useSourceGeometry={useSourceGeometry} setUseSourceGeometry={setUseSourceGeometry}
      acknowledged={acknowledged} setAcknowledged={setAcknowledged}
      conformer={conformer} pdbqt={pdbqt}
      meekoAvailable={meekoAvailable} blocked={blocked}
      step={step} busy={busy}
      onPrepare={onPrepare}
    />
  );
}

function acknowledge() {
  fireEvent.click(screen.getByRole("checkbox", { name: /Use exactly this species/ }));
}

it("states the whole plan before the click, not after", () => {
  render(<Harness />);

  const plan = screen.getByRole("button", { name: /Prepare ligand for docking/ })
    .closest("section") as HTMLElement;
  expect(within(plan).getByText("Species").parentElement).toHaveTextContent(/no ambiguity/);
  expect(within(plan).getByText("Ionization").parentElement).toHaveTextContent(
    /Dimorphite-DL pH 6.4–8.4 · single state/,
  );
  expect(within(plan).getByText("Geometry").parentElement).toHaveTextContent(
    /ETKDGv3 seed 20260819 · MMFF94s ≤500 iterations/,
  );
  expect(within(plan).getByText("Docking format").parentElement).toHaveTextContent(/Meeko/);
});

it("will not run until the scientist confirms the stated plan", () => {
  const onPrepare = vi.fn();
  render(<Harness onPrepare={onPrepare} />);

  expect(screen.getByRole("button", { name: "Prepare ligand for docking" })).toBeDisabled();
  acknowledge();
  fireEvent.click(screen.getByRole("button", { name: "Prepare ligand for docking" }));
  expect(onPrepare).toHaveBeenCalledOnce();
});

it("stops and asks when more than one ionization state exists", () => {
  render(<Harness protonationOptions={options(4)} />);
  acknowledge();

  // A real decision: the chain refuses to guess which species to dock.
  expect(screen.getByRole("button", { name: "Prepare ligand for docking" })).toBeDisabled();
  expect(screen.getByText(/Choose a protonation state above/)).toBeInTheDocument();

  fireEvent.change(screen.getByRole("combobox", { name: /4 states at this pH/ }), {
    target: { value: "2" },
  });
  expect(screen.getByRole("button", { name: "Prepare ligand for docking" })).not.toBeDisabled();
});

it("groups a long list of states by the charge that changes the docking typing", () => {
  render(<Harness protonationOptions={options(4)} />);

  const select = screen.getByRole("combobox", { name: /4 states at this pH/ });
  const groups = [...select.querySelectorAll("optgroup")].map((g) => g.getAttribute("label"));
  expect(groups).toEqual(["formal charge -1", "formal charge 0"]);
});

it("never asks a question when only one state survived enumeration", () => {
  render(<Harness />);

  expect(screen.queryByRole("combobox", { name: /states at this pH/ })).not.toBeInTheDocument();
  acknowledge();
  expect(screen.getByRole("button", { name: "Prepare ligand for docking" })).not.toBeDisabled();
});

it("offers the physiological point as the way out of a crowded pH window", () => {
  const onPhChange = vi.fn();
  render(<Harness protonationOptions={options(8)} onPhChange={onPhChange} />);

  fireEvent.click(screen.getByRole("button", { name: "Physiological point 7.4" }));
  expect(onPhChange).toHaveBeenCalledWith({ min: 7.4, max: 7.4 });
});

it("keeps the as-drawn escape, because a curated SDF may already carry its state", () => {
  const onSkipProtonation = vi.fn();
  render(<Harness onSkipProtonation={onSkipProtonation} />);

  fireEvent.click(screen.getByRole("button", { name: /Skip — dock the as-drawn state/ }));
  expect(onSkipProtonation).toHaveBeenCalledOnce();
});

it("says which charge it will dock once protonation is skipped", () => {
  render(<Harness protonationSkipped protonationOptions={null} />);

  expect(screen.getByRole("alert")).toHaveTextContent(
    /as-drawn formal charge -1 is used for 3D generation and docking/,
  );
});

it("refuses to hand an unconverged geometry to Meeko", () => {
  render(<Harness conformer={conformerRecord(false)} />);

  expect(
    screen.getByText(/None of the 20 embedded conformers converged/),
  ).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "lowest-energy nonconverged outcome was preserved",
  );
});

it("does not invent pool-wide convergence evidence for a historical record", () => {
  const historical = conformerRecord(false);
  historical.minimization.conformer_pool_converged_count = undefined;
  historical.minimization.conformer_selection_policy = undefined;

  render(<Harness conformer={historical} />);

  expect(
    screen.getByText(/reached the iteration limit without converging, so Meeko was not run/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/None of the 20 embedded conformers converged/)).not.toBeInTheDocument();
});

it("still prepares the conformer when Meeko is unavailable", () => {
  // Meeko gates the conversion, never the chemistry before it. Blocking the
  // whole action would leave a scientist without Meeko unable to do anything.
  render(<Harness meekoAvailable={false} />);
  acknowledge();

  const action = screen.getByRole("button", { name: "Prepare conformer (Meeko unavailable)" });
  expect(action).not.toBeDisabled();
  expect(screen.getByText(/stops after minimization/)).toBeInTheDocument();
});

it("refuses to run while the chemical state is unresolved", () => {
  render(<Harness blocked />);
  acknowledge();

  expect(screen.getByRole("button", { name: "Prepare ligand for docking" })).toBeDisabled();
  expect(screen.getByText(/Resolve the chemical state above/)).toBeInTheDocument();
});

it("reports which step of the chain is running", () => {
  render(<Harness busy step="conformer" />);

  expect(screen.getByRole("progressbar", { name: "Preparing ligand" }))
    .toHaveTextContent("2 / 3 · embedding and minimizing");
});

it("keeps source geometry reachable, and says what choosing it means", () => {
  render(<Harness />);

  fireEvent.click(screen.getByRole("checkbox", { name: /Minimize the source geometry instead/ }));
  const plan = screen.getByText("Geometry").parentElement as HTMLElement;
  expect(plan).toHaveTextContent(/Source coordinates/);
  expect(
    screen.getByText(/samples torsions but not ring conformations/),
  ).toBeInTheDocument();
});
