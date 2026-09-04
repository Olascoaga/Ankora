import { ankoraApi } from "../api/client";

describe("typed API client", () => {
  it("returns the typed health response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", backend_version: "0.1.0" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(ankoraApi.health()).resolves.toEqual({ status: "ok", backend_version: "0.1.0" });
  });

  it("raises an API error for a failed response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));

    await expect(ankoraApi.health()).rejects.toEqual(
      expect.objectContaining({
        name: "ApiError",
        status: 503,
        message: "Ankora backend returned 503",
      }),
    );
  });

  it("imports a local structure as multipart data without setting a conflicting content type", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifact: { artifact_id: "synthetic" } }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.importStructure(new File(["SYNTHETIC"], "synthetic.pdb"));

    const [, init] = fetchSpy.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  });

  it("imports a local ligand as preserved multipart data", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifact: { ligand_id: "synthetic" } }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.importLigand(new File(["CCO synthetic"], "synthetic.smi"));

    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/ligands\/import$/);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  });

  it("imports a multirecord ligand library as preserved multipart data", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifact: { library_id: "synthetic-library" } }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.importLigandLibrary(
      new File(["synthetic multirecord SDF"], "synthetic_library.sdf"),
    );

    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/ligand-libraries\/import$/);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  });

  it("previews and applies an explicit ligand-library filter selection", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ library_id: "library-1", evaluations: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const plan = {
      preset: "general_oral" as const,
      require_lipinski: true,
      max_lipinski_violations: 1,
      require_veber: true,
      require_ghose: false,
      require_muegge: false,
      minimum_qed: null,
      pains_policy: "review" as const,
      brenk_policy: "review" as const,
      duplicate_policy: "exclude" as const,
      custom_rules: [],
    };
    const microstatePlan = {
      mode: "exact_imported_state" as const,
      ph_min: 7.4,
      ph_max: 7.4,
      precision: 1,
      max_tautomers_per_protomer: 8,
      max_microstates_per_parent: 16,
    };

    await ankoraApi.previewLigandLibraryFilters("library-1", {
      plan,
      microstate_plan: microstatePlan,
      state_overrides: { "ligand-1": "state-2" },
    });
    await ankoraApi.applyLigandLibraryFilters("library-1", {
      plan,
      microstate_plan: microstatePlan,
      state_overrides: { "ligand-1": "state-2" },
      acknowledge_selection: true,
    });
    await ankoraApi.latestLigandLibraryFilterRun("library-1");

    expect(String(fetchSpy.mock.calls[0][0])).toMatch(
      /\/ligand-libraries\/library-1\/filter-preview$/,
    );
    expect(JSON.parse(String(fetchSpy.mock.calls[1][1]?.body))).toEqual({
      plan,
      microstate_plan: microstatePlan,
      state_overrides: { "ligand-1": "state-2" },
      acknowledge_selection: true,
    });
    expect(String(fetchSpy.mock.calls[2][0])).toMatch(
      /\/ligand-libraries\/library-1\/filter-runs\/latest$/,
    );
  });

  it("preserves stable backend error details", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        code: "STRUCTURE_PARSE_FAILED",
        stage: "structure_inspection",
        message: "Gemmi could not parse this coordinate file.",
        details: { parser_message: "synthetic fixture" },
        recoverable: true,
      }), { status: 422, headers: { "Content-Type": "application/json" } }),
    );

    await expect(ankoraApi.importStructure(new File(["bad"], "bad.pdb"))).rejects.toEqual(
      expect.objectContaining({
        status: 422,
        code: "STRUCTURE_PARSE_FAILED",
        stage: "structure_inspection",
      }),
    );
  });

  it("records explicit state selection and ligand PDBQT requests", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ artifact: { preparation_id: "synthetic" } }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.resolveLigandState("ligand-1", {
      parent_state_id: "state-1",
      component_index: 2,
      stereoisomer_index: 1,
    });
    await ankoraApi.prepareLigandPdbqt("ligand-1", "conformer-1", {
      charge_model: "gasteiger",
    });

    expect(fetchSpy.mock.calls).toHaveLength(2);
    expect(JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))).toEqual({
      parent_state_id: "state-1",
      component_index: 2,
      stereoisomer_index: 1,
    });
    expect(String(fetchSpy.mock.calls[1][0])).toMatch(
      /\/ligands\/ligand-1\/conformers\/conformer-1\/pdbqt$/,
    );
    expect(JSON.parse(String(fetchSpy.mock.calls[1][1]?.body))).toEqual({
      charge_model: "gasteiger",
    });
  });

  it("requests matching campaign history and incremental progress", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ batch_id: "synthetic" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.latestDockingBatch("library 1", "receptor-1", "site-1");
    await ankoraApi.getDockingBatchProgress("batch-1", 37);

    expect(String(fetchSpy.mock.calls[0][0])).toContain(
      "/docking/batches/latest?library_id=library+1&receptor_id=receptor-1&binding_site_id=site-1",
    );
    expect(String(fetchSpy.mock.calls[1][0])).toMatch(
      /\/docking\/batches\/batch-1\/progress\?after_revision=37$/,
    );
  });
  it("requests AlphaFold predictions through the typed alphafold endpoint", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifact: { artifact_id: "synthetic", source: "alphafold" } }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.fetchAlphafoldStructure("P04637");

    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/structures\/fetch\/alphafold$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ uniprot_id: "P04637" });
  });
  it("declares a JSON content type on every JSON-bodied request", async () => {
    // Without this header `fetch` labels the body `text/plain`, FastAPI
    // rejects it with its own 422 before any handler runs, and that response
    // carries no `message` - so the scientist only sees "returned 422".
    // A fresh Response per call: a body can only be consumed once.
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({}), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.startAutoGridJob({
      receptor_id: "receptor-1",
      binding_site_id: "site-1",
      source: "ligand_preparation",
      ligand_id: "ligand-1",
      ligand_preparation_id: "preparation-1",
    });
    await ankoraApi.startAutoDock4Docking({
      receptor_id: "receptor-1",
      binding_site_id: "site-1",
      map_set_id: "map-set-1",
      ligand_id: "ligand-1",
      ligand_preparation_id: "preparation-1",
      parameters: {
        ga_runs: 10, ga_population_size: 150, ga_energy_evaluations: 2_500_000,
        ga_generations: 27_000, cluster_rmsd_tolerance_angstrom: 2,
        seed_1: 1, seed_2: 2, timeout_minutes: 360,
      },
      acknowledge_inputs_and_scoring: true,
    });

    for (const [, init] of fetchSpy.mock.calls) {
      expect(init?.method).toBe("POST");
      const headers = init?.headers as Record<string, string>;
      expect(headers["Content-Type"]).toBe("application/json");
    }
  });

  it("leaves a FormData upload without an explicit content type", async () => {
    // The browser must set the multipart boundary itself.
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({}), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await ankoraApi.importLigand(new File(["synthetic"], "ligand.sdf"));

    const headers = fetchSpy.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });
});
