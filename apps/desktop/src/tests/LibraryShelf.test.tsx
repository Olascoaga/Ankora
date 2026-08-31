import { useState } from "react";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { LigandWorkspace } from "../features/ligand/LigandWorkspace";
import type {
  LigandLibraryPage,
  LigandLibraryRecord,
  LigandRecord,
  StructureRecord,
  ToolsResponse,
} from "../types/api";

/**
 * Reopening a library the project already holds.
 *
 * Until a listing existed a library was addressable by id but not
 * enumerable, so it lived only as long as the session that imported it. This
 * project recorded 38 imports of four distinct files as a result.
 */

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const structure = {
  artifact: {
    artifact_id: "source", original_filename: "source.cif", format: "mmcif",
    sha256: "a".repeat(64), size_bytes: 100, source: "local", source_uri: null,
    imported_at: "2026-08-19T00:00:00Z",
  },
  metadata: {
    entry_id: "SYN", title: "Synthetic test structure", experimental_method: "SYNTHETIC",
    resolution_angstrom: null, model_count: 1, atom_count: 1, residue_count: 1,
    chains: [], heterogens: [], alternate_location_atom_count: 0,
    missing_residue_count: 0, missing_atom_count: 0, nonstandard_polymer_residues: [],
  },
  warnings: [],
  provenance: {
    event_id: "source", event_type: "structure_imported",
    timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["source"],
    tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null,
  },
  content_url: "/structures/source/content",
} as unknown as StructureRecord;

const tools = {
  vina: { available: false, path: null, version: null },
  meeko_ligand: { available: false, path: null, version: null },
} as unknown as ToolsResponse;

const page: LigandLibraryPage = {
  libraries: [
    {
      artifact: {
        library_id: "library-recent", filename: "dbv6.sdf", format: "sdf",
        sha256: "d".repeat(64), size_bytes: 485514, record_count: 323,
        created_at: "2026-08-28T23:37:00Z",
      },
      filter_run_count: 1,
      latest_filter_run_id: "run-1",
    },
    {
      artifact: {
        library_id: "library-older", filename: "moleculas_lab.sdf", format: "sdf",
        sha256: "e".repeat(64), size_bytes: 2048, record_count: 12,
        created_at: "2026-08-20T09:00:00Z",
      },
      filter_run_count: 0,
      latest_filter_run_id: null,
    },
  ],
  total: 2,
  offset: 0,
  limit: 200,
};

function ligand(index: number): unknown {
  return {
    artifact: {
      ligand_id: `ligand-${index}`, filename: `ligand-${index}.sdf`, format: "sdf",
      sha256: String(index).repeat(64).slice(0, 64), size_bytes: 100,
      created_at: "2026-08-19T00:00:00Z", library_id: "library-recent",
      source_index: index,
    },
    state: null,
    inspection: {
      name: `Compound ${index}`, formula: "C2H6O", molecular_weight_g_mol: 46.07,
      exact_mass_da: 46.04, formal_charge: 0, atom_count: 9, heavy_atom_count: 3,
      rotatable_bond_count: 0, aromatic_ring_count: 0, stereocenter_count: 0,
      undefined_stereocenter_count: 0, fragment_count: 1, conformer_count: 0,
      has_3d_coordinates: false, canonical_smiles: "CCO",
    },
    warnings: [],
    provenance: {
      event_id: `ligand-${index}`, event_type: "ligand_imported",
      timestamp: "2026-08-19T00:00:00Z", input_artifacts: [],
      output_artifacts: [`ligand-${index}`],
      tool: { name: "RDKit", version: "2026.3.5" }, parameters: {},
    },
    content_url: `/ligands/ligand-${index}/content`,
  };
}

const reopened = {
  artifact: page.libraries[0].artifact,
  entries: [{ record_index: 0, status: "imported", ligand: ligand(1), failure: null }],
  imported_count: 1,
  failed_count: 0,
  provenance: {
    event_id: "library-recent", event_type: "local_ligand_library_imported",
    timestamp: "2026-08-28T23:37:00Z", input_artifacts: [],
    output_artifacts: ["library-recent"],
    tool: { name: "RDKit", version: "2026.3.5" }, parameters: {},
  },
  original_content_url: "/ligand-libraries/library-recent/content",
} as unknown as LigandLibraryRecord;

const appliedRun = {
  artifact: {
    filter_run_id: "run-1", library_id: "library-recent",
    filename: "selection.json", sha256: "f".repeat(64), size_bytes: 512,
    created_at: "2026-08-28T23:40:00Z",
  },
  plan: { rules: [], alert_policy: "review", duplicate_policy: "exclude", custom_rules: [] },
  evaluations: [],
  summary: {
    total_count: 1, eligible_count: 1, excluded_count: 0,
    needs_decision_count: 0, duplicate_count: 0,
  },
  selected_ligand_ids: ["ligand-1"],
  rdkit_version: "2026.3.5",
  worker_count: 1,
  provenance: {
    event_id: "run-1", event_type: "ligand_library_filtered",
    timestamp: "2026-08-28T23:40:00Z", input_artifacts: ["library-recent"],
    output_artifacts: ["run-1"], tool: { name: "RDKit", version: "2026.3.5" },
    parameters: {},
  },
  content_url: "/ligand-libraries/library-recent/filter-runs/run-1/content",
} as unknown as Record<string, unknown>;

function Harness() {
  const [record, setRecord] = useState<LigandRecord | null>(null);
  return (
    <LigandWorkspace
      structure={structure}
      record={record}
      tools={tools}
      onRecordChange={setRecord}
    />
  );
}

function mockApi(options: { hasAppliedRun?: boolean } = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/ligand-libraries?")) return json(page);
    if (url.includes("/filter-runs/latest")) {
      return options.hasAppliedRun ? json(appliedRun) : json({ code: "NOT_FOUND" }, 404);
    }
    if (url.includes("/filter-preview")) {
      return json({
        library_id: "library-recent",
        plan: appliedRun.plan,
        evaluations: [],
        summary: {
          total_count: 1, eligible_count: 1, excluded_count: 0,
          needs_decision_count: 0, duplicate_count: 0,
        },
        rdkit_version: "2026.3.5",
        worker_count: 1,
      });
    }
    if (url.includes("/ligand-libraries/library-recent")) return json(reopened);
    return new Response(null, { status: 404 });
  });
}

async function openScreening() {
  render(<Harness />);
  // The shelf only belongs to the library flow, not to single-ligand work.
  const screening = await screen.findByRole("button", { name: "Virtual screening" });
  fireEvent.click(screening);
}

it("lists the libraries this project already holds, newest first", async () => {
  mockApi();
  await openScreening();

  const shelf = await screen.findByRole("list", { name: "Imported libraries" });
  const items = within(shelf).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(items[0]).toHaveTextContent("dbv6.sdf");
  expect(items[0]).toHaveTextContent("323 records");
  expect(items[1]).toHaveTextContent("moleculas_lab.sdf");
});

it("says which libraries already have a selection applied", async () => {
  // It is the difference between resuming a screen and starting one over.
  mockApi();
  await openScreening();

  const shelf = await screen.findByRole("list", { name: "Imported libraries" });
  const items = within(shelf).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("1 applied selection");
  expect(items[1]).toHaveTextContent("no selection applied");
});

it("reopens a library without importing the file again", async () => {
  const fetcher = mockApi();
  await openScreening();

  const shelf = await screen.findByRole("list", { name: "Imported libraries" });
  fireEvent.click(within(shelf).getAllByRole("listitem")[0]);

  await waitFor(() =>
    expect(fetcher.mock.calls.some(([url]) =>
      String(url).includes("/ligand-libraries/library-recent"))).toBe(true));
  // Nothing was uploaded: the library was already here.
  expect(fetcher.mock.calls.every(([, init]) => !(init?.body instanceof FormData))).toBe(true);
});

it("restores the selection the library was last run with", async () => {
  const fetcher = mockApi({ hasAppliedRun: true });
  await openScreening();

  const shelf = await screen.findByRole("list", { name: "Imported libraries" });
  fireEvent.click(within(shelf).getAllByRole("listitem")[0]);

  // A screen resumes at the selection it actually ran with, rather than at an
  // unfiltered library that looks the same.
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([url]) =>
      String(url).includes("/filter-runs/latest"))).toBe(true));
});
