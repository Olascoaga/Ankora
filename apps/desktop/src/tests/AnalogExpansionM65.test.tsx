import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ankoraApi } from "../api/client";
import { AnalogExpansionPanel } from "../features/expansion/AnalogExpansionPanel";
import { ExportWorkspace } from "../features/export/ExportWorkspace";
import type {
  AnalogCatalogSummary,
  AnalogSearchRecord,
  AnalogSelectionRecord,
  BindingSitePreview,
  BindingSiteRecord,
  ExternalConsentPreview,
} from "../types/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const SYNTH_CATALOG: AnalogCatalogSummary = {
  analog_catalog_id: "cat-synth-1",
  name: "Synthetic Local Catalog",
  source_format: "csv",
  filename: "synth.csv",
  sha256: "a".repeat(64),
  size_bytes: 128,
  created_at: "2026-11-21T18:00:00Z",
  source_library_id: null,
  total_records: 10,
  valid_records: 9,
  invalid_records: 1,
};

const SYNTH_SEARCH: AnalogSearchRecord = {
  analog_search_id: "search-synth-1",
  created_at: "2026-11-21T18:01:00Z",
  mode: "offline_catalog",
  source_catalog_id: "vina_job:job-1",
  source_record_id: "job-1",
  source_ligand_id: "lig-1",
  source_pose_artifact_id: "pose-1",
  source_pose_sha256: "b".repeat(64),
  source_consensus_id: null,
  source_cluster_id: null,
  seed_name: "seed_hit",
  seed_chemical_state_id: "state-1",
  query_canonical_isomeric_smiles: "CC(=O)Oc1ccccc1C(=O)O",
  query_search_smiles: "CC(=O)Oc1ccccc1C(=O)O",
  analog_catalog_id: "cat-synth-1",
  fingerprint_profile: {
    algorithm: "morgan",
    radius: 2,
    fp_size: 2048,
    include_chirality: true,
    strip_salts_for_search_only: true,
    canonicalize_tautomers_for_search_only: false,
  },
  rdkit_version: "2025.09.6",
  min_tanimoto: 0.4,
  top_k: 100,
  smarts_filter: null,
  total_evaluated: 9,
  invalid_skipped: 1,
  truncated_by_top_k: false,
  cache_hit: false,
  hits: [
    {
      hit_id: "seed-control",
      role: "seed_control",
      identifier: "seed_hit",
      source_record_index: null,
      canonical_isomeric_smiles: "CC(=O)Oc1ccccc1C(=O)O",
      search_smiles: "CC(=O)Oc1ccccc1C(=O)O",
      local_rdkit_tanimoto: 1.0,
      provider_similarity: null,
      provider_compound_id: null,
      smarts_matched: null,
      molecular_weight_g_mol: 180.16,
      heavy_atom_count: 13,
      rotatable_bond_count: 3,
      undefined_stereocenter_count: 0,
      had_multiple_fragments: false,
      duplicate_of_hit_id: null,
    },
    {
      hit_id: "analog-1",
      role: "analog",
      identifier: "fluoro_analog",
      source_record_index: 1,
      canonical_isomeric_smiles: "CC(=O)Oc1ccc(F)cc1C(=O)O.[Na+]",
      search_smiles: "CC(=O)Oc1ccc(F)cc1C(=O)O",
      local_rdkit_tanimoto: 0.72,
      provider_similarity: null,
      provider_compound_id: null,
      smarts_matched: null,
      molecular_weight_g_mol: 220.13,
      heavy_atom_count: 15,
      rotatable_bond_count: 3,
      undefined_stereocenter_count: 0,
      had_multiple_fragments: true,
      duplicate_of_hit_id: null,
    },
  ],
  external_evidence: null,
  warnings: [],
  provenance: {
    event_id: "ev-1",
    event_type: "analog_similarity_search_offline",
    timestamp: "2026-11-21T18:01:00Z",
    input_artifacts: [],
    output_artifacts: ["search-synth-1"],
    tool: { name: "ankora-analog-expansion", version: "0.2.0" },
    parameters: {},
    warnings: [],
    command: null,
  },
};

describe("M6.5f ADR-033 Hit-to-Analog Expansion & Export v6 UI", () => {
  it("runs offline analog search, curates mini-library, and derives POSE_FOCUSED site", async () => {
    vi.spyOn(ankoraApi, "listAnalogCatalogs").mockResolvedValue([SYNTH_CATALOG]);
    vi.spyOn(ankoraApi, "listLigandLibraries").mockResolvedValue({
      libraries: [],
      total: 0,
      offset: 0,
      limit: 25,
    });
    const offlineSpy = vi
      .spyOn(ankoraApi, "runOfflineAnalogSearch")
      .mockResolvedValue(SYNTH_SEARCH);
    const selectSpy = vi
      .spyOn(ankoraApi, "createAnalogSelection")
      .mockResolvedValue({
        analog_selection_id: "sel-synth-1",
        analog_search_id: "search-synth-1",
        created_at: "2026-11-21T18:02:00Z",
        library_name: "seed_hit_analogs",
        derived_library_id: "lib-derived-1",
        derived_library_sha256: "c".repeat(64),
        include_seed_control: true,
        selected_count: 2,
        excluded_count: 0,
        decisions: [
          { hit_id: "hit-seed-0", selected: true, role: "seed_control", reason: null },
          { hit_id: "hit-1", selected: true, role: "analog", reason: null },
        ],
        warnings: [],
        provenance: SYNTH_SEARCH.provenance,
      } satisfies AnalogSelectionRecord);
    const previewSiteSpy = vi
      .spyOn(ankoraApi, "previewBindingSite")
      .mockResolvedValue({
        receptor_id: "rec-1",
        source: "pose_focused",
        box: { center_x: 2, center_y: 1, center_z: 3, size_x: 14, size_y: 12, size_z: 16 },
        warnings: [],
      } satisfies BindingSitePreview);
    const createSiteSpy = vi
      .spyOn(ankoraApi, "createBindingSite")
      .mockResolvedValue({
        binding_site_id: "site-focused-1",
        receptor_id: "rec-1",
        source_artifact_id: "str-1",
        created_at: "2026-11-21T18:03:00Z",
        decisions: {
          source: "pose_focused",
          ligand_origin: null,
          residue_selection: null,
          manual_box: null,
          blind_margin_angstrom: 6,
          pocket_selection: null,
          parent_binding_site_id: "site-parent-1",
        },
        box: { center_x: 2, center_y: 1, center_z: 3, size_x: 14, size_y: 12, size_z: 16 },
        stale: false,
        warnings: [],
        provenance: [],
      } satisfies BindingSiteRecord);

    render(
      <AnalogExpansionPanel
        sourceCatalogId="vina_job:job-1"
        sourceLigandId="lig-1"
        sourcePoseArtifactId="pose-1"
        receptorId="rec-1"
        parentBindingSiteId="site-parent-1"
        seedLabel="seed_hit"
      />,
    );

    await waitFor(() =>
      expect(screen.getByText(/Synthetic Local Catalog/i)).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /Run offline similarity search/i }));
    await waitFor(() =>
      expect(offlineSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          source_catalog_id: "vina_job:job-1",
          source_ligand_id: "lig-1",
          source_pose_artifact_id: "pose-1",
          analog_catalog_id: "cat-synth-1",
        }),
      ),
    );
    expect(screen.getByText("fluoro_analog")).toBeInTheDocument();
    expect(screen.getByText(/multi-fragment\/salt/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Create derived mini-library/i }));
    await waitFor(() =>
      expect(selectSpy).toHaveBeenCalledWith(
        "search-synth-1",
        expect.objectContaining({
          selected_hit_ids: ["seed-control", "analog-1"],
          include_seed_control: true,
        }),
      ),
    );
    expect(screen.getByText(/lib-derived-1/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Preview POSE_FOCUSED box/i }));
    await waitFor(() =>
      expect(previewSiteSpy).toHaveBeenCalledWith(
        "rec-1",
        expect.objectContaining({
          source: "pose_focused",
          parent_binding_site_id: "site-parent-1",
          pose_focused: expect.objectContaining({
            source_catalog_id: "vina_job:job-1",
            ligand_id: "lig-1",
            pose_artifact_id: "pose-1",
          }),
        }),
      ),
    );
    expect(screen.getByText(/Preview box:/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Save POSE_FOCUSED binding site/i }));
    await waitFor(() =>
      expect(createSiteSpy).toHaveBeenCalledWith(
        "rec-1",
        expect.objectContaining({
          source: "pose_focused",
          parent_binding_site_id: "site-parent-1",
        }),
      ),
    );
    expect(screen.getByText(/site-focused-1/)).toBeInTheDocument();
  });

  it("enforces explicit IP disclosure preview & checkbox before enabling opt-in online search", async () => {
    vi.spyOn(ankoraApi, "listAnalogCatalogs").mockResolvedValue([]);
    vi.spyOn(ankoraApi, "listLigandLibraries").mockResolvedValue({
      libraries: [],
      total: 0,
      offset: 0,
      limit: 25,
    });
    const consentPreview: ExternalConsentPreview = {
      provider: "pubchem_pug_rest",
      endpoint_url: "https://pubchem.ncbi.nlm.nih.gov/rest/pug/...",
      seed_name: "seed_hit",
      seed_chemical_state_id: "state-1",
      query_canonical_isomeric_smiles: "CC(=O)Oc1ccccc1C(=O)O",
      consent_payload_sha256: "d".repeat(64),
      disclosure_message:
        "This explicit opt-in query will transmit the canonical SMILES below off your local machine.",
    };
    const previewSpy = vi
      .spyOn(ankoraApi, "previewExternalAnalogConsent")
      .mockResolvedValue(consentPreview);
    const onlineSpy = vi
      .spyOn(ankoraApi, "runOnlineAnalogSearch")
      .mockResolvedValue({ ...SYNTH_SEARCH, mode: "online_pubchem" });

    render(
      <AnalogExpansionPanel
        sourceCatalogId="vina_job:job-1"
        sourceLigandId="lig-1"
        sourcePoseArtifactId="pose-1"
        receptorId="rec-1"
        seedLabel="seed_hit"
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /Opt-in online lookup/i }));
    expect(screen.queryByRole("button", { name: /Run opt-in online search/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Review IP disclosure/i }));
    await waitFor(() =>
      expect(previewSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          source_catalog_id: "vina_job:job-1",
          source_ligand_id: "lig-1",
          source_pose_artifact_id: "pose-1",
          provider: "pubchem_pug_rest",
        }),
      ),
    );
    expect(screen.getByText("CC(=O)Oc1ccccc1C(=O)O")).toBeInTheDocument();

    const runOnlineBtn = screen.getByRole("button", { name: /Run opt-in online search/i });
    expect(runOnlineBtn).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: /explicitly authorize transmitting/i }));
    expect(runOnlineBtn).not.toBeDisabled();

    fireEvent.click(runOnlineBtn);
    await waitFor(() =>
      expect(onlineSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          source_catalog_id: "vina_job:job-1",
          source_ligand_id: "lig-1",
          source_pose_artifact_id: "pose-1",
          provider: "pubchem_pug_rest",
          consent: {
            provider: "pubchem_pug_rest",
            query_canonical_smiles: "CC(=O)Oc1ccccc1C(=O)O",
            consent_payload_sha256: "d".repeat(64),
            acknowledge_external_transmission: true,
          },
        }),
      ),
    );
  });

  it("renders Export v6 badge for ADR-033 focused campaign bundles in ExportWorkspace", async () => {
    vi.spyOn(ankoraApi, "listResultCampaigns").mockResolvedValue({
      entries: [],
      total: 0,
      offset: 0,
      limit: 50,
    });
    vi.spyOn(ankoraApi, "listExports").mockResolvedValue({
      entries: [
        {
          export_id: "exp-v6-1",
          kind: "campaign",
          title: "Focused Analog Series",
          subtitle: "AutoDock Vina 1.2.7",
          exported_at: "2026-11-21T18:10:00Z",
          directory: "/tmp/export_v6",
          outside_project: false,
          catalog_id: "vina_batch:b1",
          source_kind: "vina_batch",
          source_id: "b1",
          display_name: "Focused Analog Series",
          archive_filename: "Ankora_Focused-Analog-Series_bundle.zip",
          analysis_id: null,
          ligand_id: null,
          input_identity_sha256: "e".repeat(64),
          bundle_identity_sha256: "f".repeat(64),
          reproducibility: null,
          bitwise_reproducible: null,
          files: [],
          ankora_export_format: 6,
        },
      ],
      total: 1,
      offset: 0,
      limit: 25,
    });

    render(<ExportWorkspace />);
    await waitFor(() =>
      expect(screen.getByText(/Campaign bundle · Export v6/i)).toBeInTheDocument(),
    );
  });
});
