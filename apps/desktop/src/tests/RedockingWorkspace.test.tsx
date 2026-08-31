import { render, screen, within } from "@testing-library/react";

import { RedockingWorkspace } from "../features/validation/RedockingWorkspace";
import type { RedockingRunRecord } from "../types/api";

/**
 * The workspace must never show one pass/fail.
 *
 * On this project's own reference case the two verdicts disagreed: AutoDock4
 * recovered the 7AQF/RV2 pose to 0.490 Å and then ranked a 3.139 Å pose above
 * it. A single "validated" tick would have had to misreport one of them.
 */

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function run(overrides: Partial<RedockingRunRecord> = {}): RedockingRunRecord {
  return {
    validation_id: "validation-1",
    created_at: "2026-08-26T12:00:00Z",
    reference_case: "SERPINE1_7AQF_RV2",
    receptor_id: "receptor-1",
    binding_site_id: "site-1",
    source_kind: "autodock4_job",
    source_id: "job-1",
    engine: "AutoDock",
    engine_version: "4.2.6",
    bitwise_reproducible: true,
    reference_ligand_id: "ligand-1",
    reference_sha256: "a".repeat(64),
    reference_heavy_atom_count: 27,
    metrics: {
      threshold_angstrom: 2,
      pose_count: 10,
      top1_rmsd_angstrom: 3.139,
      best_top5_rmsd_angstrom: 0.49,
      best_overall_rmsd_angstrom: 0.454,
      first_recovering_rank: 2,
      recovered_pose_count: 6,
      sampling_success: true,
      ranking_success: false,
      outcome: "recovered_but_misranked",
    },
    poses: [
      { run: 9, rank: 1, binding_energy_kcal_mol: -4.96, rmsd_angstrom: 3.139, recovered: false },
      { run: 7, rank: 2, binding_energy_kcal_mol: -4.94, rmsd_angstrom: 0.685, recovered: true },
    ],
    warnings: [],
    provenance: null,
    ...overrides,
  };
}

function mock(runs: RedockingRunRecord[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(runs));
}

it("reports finding the pose and ranking it as two separate verdicts", async () => {
  mock([run()]);
  render(<RedockingWorkspace />);

  const results = await screen.findByRole("region", { name: "Redocking validation results" });
  const sampling = within(results).getByText("Sampling").parentElement as HTMLElement;
  const ranking = within(results).getByText("Ranking").parentElement as HTMLElement;

  expect(sampling).toHaveTextContent("Passed");
  expect(ranking).toHaveTextContent("Failed");
  // The word carries the verdict, so it is never readable by colour alone.
  expect(sampling).toHaveTextContent(/Did the search find the crystallographic pose/);
  expect(ranking).toHaveTextContent(/Did the scoring function put it first/);
});

it("says how far down the scientist would have had to look", async () => {
  mock([run()]);
  render(<RedockingWorkspace />);

  const results = await screen.findByRole("region", { name: "Redocking validation results" });

  expect(within(results).getByText("First recovering").parentElement)
    .toHaveTextContent("Rank 2 of 10");
  expect(within(results).getByText("Top-1").parentElement).toHaveTextContent("3.139 Å");
  expect(within(results).getByText("Best overall").parentElement).toHaveTextContent("0.454 Å");
});

it("states that the RMSD is measured in place, not after superimposing", async () => {
  mock([run()]);
  render(<RedockingWorkspace />);
  await screen.findByRole("region", { name: "Redocking validation results" });

  // A validator that aligned first would pass a completely wrong binding mode.
  expect(screen.getByText(/never superimposed on the reference first/))
    .toBeInTheDocument();
});

it("says what a pass does and does not mean", async () => {
  mock([run()]);
  render(<RedockingWorkspace />);

  expect(
    await screen.findByText(/recovered this reference pose, under the stated/),
  ).toBeInTheDocument();
});

it("carries whether the validated run could be repeated at all", async () => {
  mock([run({
    engine: "AutoDock-GPU", engine_version: "1.6",
    source_kind: "autodock_gpu_job", bitwise_reproducible: false,
  })]);
  render(<RedockingWorkspace />);

  const results = await screen.findByRole("region", { name: "Redocking validation results" });

  expect(within(results).getByText("Repeatable").parentElement)
    .toHaveTextContent("Not from its seed");
});

it("says plainly when nothing has been validated yet", async () => {
  mock([]);
  render(<RedockingWorkspace />);

  expect(
    await screen.findByText(/No redocking validation recorded yet/),
  ).toBeInTheDocument();
  // And that validating docks nothing, so it is never mistaken for a run.
  expect(screen.getByText(/It docks nothing itself/)).toBeInTheDocument();
});
