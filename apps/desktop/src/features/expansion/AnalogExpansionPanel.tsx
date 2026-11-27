import { useEffect, useState } from "react";
import { ankoraApi, ApiError } from "../../api/client";
import type {
  AnalogCatalogSummary,
  AnalogSearchRecord,
  AnalogSelectionRecord,
  BindingSitePreview,
  BindingSiteRecord,
  ExternalAnalogProvider,
  ExternalConsentPreview,
  LigandLibrarySummary,
} from "../../types/api";
import { formatScientificNumber } from "../../utils/format";

export interface AnalogExpansionPanelProps {
  sourceCatalogId: string;
  sourceLigandId: string;
  sourcePoseArtifactId: string;
  receptorId: string;
  parentBindingSiteId?: string | null;
  sourceConsensusId?: string | null;
  sourceClusterId?: string | null;
  seedLabel: string;
}

export function AnalogExpansionPanel({
  sourceCatalogId,
  sourceLigandId,
  sourcePoseArtifactId,
  receptorId,
  parentBindingSiteId = null,
  sourceConsensusId = null,
  sourceClusterId = null,
  seedLabel,
}: AnalogExpansionPanelProps) {
  const [sourceTab, setSourceTab] = useState<"offline" | "online">("offline");

  // Offline catalog state
  const [catalogs, setCatalogs] = useState<AnalogCatalogSummary[]>([]);
  const [projectLibraries, setProjectLibraries] = useState<LigandLibrarySummary[]>([]);
  const [selectedCatalogId, setSelectedCatalogId] = useState<string>("");
  const [selectedLibraryId, setSelectedLibraryId] = useState<string>("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState<string>("");
  const [csvSmilesCol, setCsvSmilesCol] = useState<string>("smiles");
  const [csvIdCol, setCsvIdCol] = useState<string>("id");
  const [uploading, setUploading] = useState(false);

  // Search parameters
  const [minTanimoto, setMinTanimoto] = useState("0.4");
  const [topK, setTopK] = useState("100");
  const [smartsFilter, setSmartsFilter] = useState("");
  const [searching, setSearching] = useState(false);

  // Opt-in online state (strictly gated behind cryptographic IP consent)
  const [provider, setProvider] = useState<ExternalAnalogProvider>("pubchem_pug_rest");
  const [providerMinSim, setProviderMinSim] = useState("0.7");
  const [consentPreview, setConsentPreview] = useState<ExternalConsentPreview | null>(null);
  const [consentLoading, setConsentLoading] = useState(false);
  const [ipConsentChecked, setIpConsentChecked] = useState(false);

  // Results & explicit human curation -> derived mini-library
  const [searchResult, setSearchResult] = useState<AnalogSearchRecord | null>(null);
  const [selectedHitIds, setSelectedHitIds] = useState<Record<string, boolean>>({});
  const [includeSeedControl, setIncludeSeedControl] = useState(true);
  const [seedExclusionReason, setSeedExclusionReason] = useState("");
  const [derivedLibraryName, setDerivedLibraryName] = useState(`${seedLabel}_analogs`);
  const [curating, setCurating] = useState(false);
  const [selectionResult, setSelectionResult] = useState<AnalogSelectionRecord | null>(null);

  // Pose-focused binding site derivation (ADR-033 §3)
  const [paddingInput, setPaddingInput] = useState("5.0");
  const [flexMarginInput, setFlexMarginInput] = useState("1.5");
  const [sitePreview, setSitePreview] = useState<BindingSitePreview | null>(null);
  const [savedSite, setSavedSite] = useState<BindingSiteRecord | null>(null);
  const [siteBusy, setSiteBusy] = useState(false);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const loadErrors: string[] = [];
    Promise.all([
      ankoraApi.listAnalogCatalogs().catch((err: unknown) => {
        loadErrors.push(`Analog catalogs could not be loaded: ${describeError(err)}`);
        return [] as AnalogCatalogSummary[];
      }),
      ankoraApi
        .listLigandLibraries()
        .then((page) => page.libraries)
        .catch((err: unknown) => {
          loadErrors.push(`Project libraries could not be loaded: ${describeError(err)}`);
          return [] as LigandLibrarySummary[];
        }),
    ]).then(([cats, libs]) => {
      if (!active) return;
      setCatalogs(cats);
      setProjectLibraries(libs);
      if (loadErrors.length > 0) {
        setError(loadErrors.join(" "));
      }
      if (cats.length > 0) {
        setSelectedCatalogId((prev) => prev || cats[0].analog_catalog_id);
      }
      if (libs.length > 0) {
        setSelectedLibraryId((prev) => prev || libs[0].artifact.library_id);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  function describeError(err: unknown): string {
    if (err instanceof ApiError) return `${err.message} (${err.code})`;
    if (err instanceof Error) return err.message;
    return "Unexpected error during analog expansion.";
  }

  async function handleUploadCatalog() {
    if (!uploadFile) return;
    setUploading(true);
    setError(null);
    try {
      const isCsv = uploadFile.name.toLowerCase().endsWith(".csv");
      const created = await ankoraApi.importAnalogCatalog(uploadFile, {
        name: uploadName.trim() || undefined,
        smilesColumn: isCsv ? csvSmilesCol.trim() || "smiles" : undefined,
        idColumn: isCsv && csvIdCol.trim() ? csvIdCol.trim() : undefined,
      });
      setCatalogs((prev) => [created, ...prev]);
      setSelectedCatalogId(created.analog_catalog_id);
      setUploadFile(null);
      setUploadName("");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleSnapshotLibrary() {
    if (!selectedLibraryId) return;
    setUploading(true);
    setError(null);
    try {
      const created = await ankoraApi.snapshotLibraryAsAnalogCatalog(selectedLibraryId);
      setCatalogs((prev) => [created, ...prev]);
      setSelectedCatalogId(created.analog_catalog_id);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setUploading(false);
    }
  }

  function hydrateSearchSelection(record: AnalogSearchRecord) {
    setSearchResult(record);
    setSelectionResult(null);
    const defaults: Record<string, boolean> = {};
    for (const hit of record.hits) {
      defaults[hit.hit_id] = true;
    }
    setSelectedHitIds(defaults);
    setIncludeSeedControl(true);
    setSeedExclusionReason("");
  }

  async function handleRunOfflineSearch() {
    if (!selectedCatalogId) {
      setError("Select or import a local analog catalog first.");
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const record = await ankoraApi.runOfflineAnalogSearch({
        source_catalog_id: sourceCatalogId,
        source_ligand_id: sourceLigandId,
        source_pose_artifact_id: sourcePoseArtifactId,
        source_consensus_id: sourceConsensusId,
        source_cluster_id: sourceClusterId,
        analog_catalog_id: selectedCatalogId,
        min_tanimoto: Number(minTanimoto) || 0.4,
        top_k: Number(topK) || 100,
        smarts_filter: smartsFilter.trim() || null,
      });
      hydrateSearchSelection(record);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSearching(false);
    }
  }

  async function handlePreviewConsent() {
    setConsentLoading(true);
    setError(null);
    setIpConsentChecked(false);
    try {
      const preview = await ankoraApi.previewExternalAnalogConsent({
        source_catalog_id: sourceCatalogId,
        source_ligand_id: sourceLigandId,
        source_pose_artifact_id: sourcePoseArtifactId,
        provider,
      });
      setConsentPreview(preview);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setConsentLoading(false);
    }
  }

  async function handleRunOnlineSearch() {
    if (!consentPreview || !ipConsentChecked) return;
    setSearching(true);
    setError(null);
    try {
      const record = await ankoraApi.runOnlineAnalogSearch({
        source_catalog_id: sourceCatalogId,
        source_ligand_id: sourceLigandId,
        source_pose_artifact_id: sourcePoseArtifactId,
        source_consensus_id: sourceConsensusId,
        source_cluster_id: sourceClusterId,
        provider: consentPreview.provider,
        provider_min_similarity: Number(providerMinSim) || 0.7,
        min_local_rdkit_tanimoto: Number(minTanimoto) || 0.4,
        max_candidates: Number(topK) || 100,
        smarts_filter: smartsFilter.trim() || null,
        consent: {
          provider: consentPreview.provider,
          query_canonical_smiles: consentPreview.query_canonical_isomeric_smiles,
          consent_payload_sha256: consentPreview.consent_payload_sha256,
          acknowledge_external_transmission: true,
        },
      });
      hydrateSearchSelection(record);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSearching(false);
    }
  }

  async function handleCreateSelection() {
    if (!searchResult) return;
    const chosen = searchResult.hits
      .filter((h) => selectedHitIds[h.hit_id])
      .map((h) => h.hit_id);
    if (chosen.length === 0) {
      setError("Select at least one analog to create a curated mini-library.");
      return;
    }
    setCurating(true);
    setError(null);
    try {
      const sel = await ankoraApi.createAnalogSelection(searchResult.analog_search_id, {
        library_name: derivedLibraryName.trim() || `${seedLabel}_analogs`,
        selected_hit_ids: chosen,
        include_seed_control: includeSeedControl,
        seed_exclusion_reason: includeSeedControl ? null : seedExclusionReason.trim(),
      });
      setSelectionResult(sel);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setCurating(false);
    }
  }

  async function handlePoseFocusedSite(persist: boolean) {
    setSiteBusy(true);
    setError(null);
    const req = {
      source: "pose_focused" as const,
      ligand_origin: null,
      residue_selection: null,
      manual_box: null,
      blind_margin_angstrom: 6.0,
      pocket_selection: null,
      parent_binding_site_id: parentBindingSiteId,
      pose_focused: {
        source_catalog_id: sourceCatalogId,
        ligand_id: sourceLigandId,
        pose_artifact_id: sourcePoseArtifactId,
        padding_angstrom: Number(paddingInput) || 5.0,
        flex_containment_margin_angstrom: Number(flexMarginInput) || 1.5,
        source_consensus_id: sourceConsensusId,
        source_cluster_id: sourceClusterId,
      },
    };
    try {
      if (persist) {
        const rec = await ankoraApi.createBindingSite(receptorId, req);
        setSavedSite(rec);
      } else {
        const prev = await ankoraApi.previewBindingSite(receptorId, req);
        setSitePreview(prev);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSiteBusy(false);
    }
  }

  const chosenCount = searchResult
    ? searchResult.hits.filter((h) => selectedHitIds[h.hit_id]).length
    : 0;

  return (
    <section
      className="pose-quality-section analog-expansion-panel"
      aria-label="Hit-to-Analog Structural Similarity Expansion"
    >
      <div className="pose-quality-heading">
        <div>
          <strong>Hit-to-Analog Expansion &amp; Pose-Focused Site (ADR-033)</strong>
          <p className="field-note">
            Explore structural analogs around seed <code>{seedLabel}</code> and derive an
            immutable <code>POSE_FOCUSED</code> binding box. Outputs represent computational
            hypotheses compatible with this binding mode — not confirmed activity or affinity.
          </p>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      {/* Step 1: Search source switcher */}
      <div className="analog-source-tabs" role="tablist" aria-label="Analog search source">
        <button
          type="button"
          role="tab"
          aria-selected={sourceTab === "offline"}
          className={sourceTab === "offline" ? "primary-button" : "quiet-button"}
          onClick={() => setSourceTab("offline")}
        >
          Offline local catalog (100% local)
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sourceTab === "online"}
          className={sourceTab === "online" ? "primary-button" : "quiet-button"}
          onClick={() => {
            setSourceTab("online");
            setConsentPreview(null);
            setIpConsentChecked(false);
          }}
        >
          Opt-in online lookup (PubChem / ChEMBL)
        </button>
      </div>

      {sourceTab === "offline" ? (
        <div className="analog-step-card">
          <h4>1. Offline RDKit Morgan Similarity Search</h4>
          <div className="analog-form-grid">
            <label>
              Local catalog snapshot
              <select
                value={selectedCatalogId}
                onChange={(e) => setSelectedCatalogId(e.target.value)}
              >
                <option value="">Choose an imported analog catalog…</option>
                {catalogs.map((cat) => (
                  <option key={cat.analog_catalog_id} value={cat.analog_catalog_id}>
                    {cat.name} ({cat.valid_records} valid / {cat.total_records} rows)
                  </option>
                ))}
              </select>
            </label>
            <label>
              Min RDKit Tanimoto (Morgan r=2, 2048, chiral)
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={minTanimoto}
                onChange={(e) => setMinTanimoto(e.target.value)}
              />
            </label>
            <label>
              Top K analogs
              <input
                type="number"
                min={1}
                max={500}
                step={1}
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
              />
            </label>
            <label>
              Optional core SMARTS filter (graph-verified)
              <input
                type="text"
                value={smartsFilter}
                onChange={(e) => setSmartsFilter(e.target.value)}
                placeholder="e.g. c1ccccc1"
              />
            </label>
          </div>

          <details className="analog-catalog-import-details">
            <summary>Import a local .sdf / .smi / .csv catalog or snapshot a project library</summary>
            <div className="analog-form-grid">
              <label>
                Local catalog file (.sdf, .smi, .csv)
                <input
                  type="file"
                  accept=".sdf,.smi,.smiles,.csv"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <label>
                Catalog label (optional)
                <input
                  type="text"
                  value={uploadName}
                  onChange={(e) => setUploadName(e.target.value)}
                  placeholder="Vendor subset or internal series"
                />
              </label>
              {uploadFile?.name.toLowerCase().endsWith(".csv") ? (
                <>
                  <label>
                    CSV SMILES column
                    <input
                      type="text"
                      value={csvSmilesCol}
                      onChange={(e) => setCsvSmilesCol(e.target.value)}
                    />
                  </label>
                  <label>
                    CSV ID column (optional)
                    <input
                      type="text"
                      value={csvIdCol}
                      onChange={(e) => setCsvIdCol(e.target.value)}
                    />
                  </label>
                </>
              ) : null}
            </div>
            <div className="analog-inline-actions">
              <button
                type="button"
                className="quiet-button"
                disabled={!uploadFile || uploading}
                onClick={() => void handleUploadCatalog()}
              >
                {uploading ? "Importing snapshot…" : "Import immutable catalog"}
              </button>
              {projectLibraries.length > 0 ? (
                <>
                  <select
                    aria-label="Project library to snapshot"
                    value={selectedLibraryId}
                    onChange={(e) => setSelectedLibraryId(e.target.value)}
                  >
                    {projectLibraries.map((lib) => (
                      <option key={lib.artifact.library_id} value={lib.artifact.library_id}>
                        {lib.artifact.filename} ({lib.artifact.record_count} mols)
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="quiet-button"
                    disabled={!selectedLibraryId || uploading}
                    onClick={() => void handleSnapshotLibrary()}
                  >
                    Snapshot project library
                  </button>
                </>
              ) : null}
            </div>
          </details>

          <button
            type="button"
            className="primary-button"
            disabled={!selectedCatalogId || searching}
            onClick={() => void handleRunOfflineSearch()}
          >
            {searching ? "Searching offline catalog…" : "Run offline similarity search"}
          </button>
        </div>
      ) : (
        <div className="analog-step-card">
          <h4>1. Explicit Opt-In External Similarity Lookup (IP Consent Gate)</h4>
          <p className="field-note">
            Ankora never sends structures off your machine silently. First preview the exact
            canonical SMILES and cryptographic consent digest, then confirm transmission.
          </p>
          <div className="analog-form-grid">
            <label>
              External provider
              <select
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value as ExternalAnalogProvider);
                  setConsentPreview(null);
                  setIpConsentChecked(false);
                }}
              >
                <option value="pubchem_pug_rest">PubChem PUG-REST (fastsimilarity_2d POST)</option>
                <option value="chembl_rest">ChEMBL REST (/similarity)</option>
              </select>
            </label>
            <label>
              Provider min similarity (0.4–1.0)
              <input
                type="number"
                min={0.4}
                max={1.0}
                step={0.05}
                value={providerMinSim}
                onChange={(e) => setProviderMinSim(e.target.value)}
              />
            </label>
            <label>
              Local RDKit Tanimoto cutoff
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={minTanimoto}
                onChange={(e) => setMinTanimoto(e.target.value)}
              />
            </label>
            <label>
              Max candidates (&lt;= 500)
              <input
                type="number"
                min={1}
                max={500}
                step={1}
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
              />
            </label>
          </div>

          <button
            type="button"
            className="quiet-button"
            disabled={consentLoading}
            onClick={() => void handlePreviewConsent()}
          >
            {consentLoading
              ? "Resolving query SMILES…"
              : "Review IP disclosure & query SMILES"}
          </button>

          {consentPreview ? (
            <div className="analog-ip-consent-box" role="alert">
              <strong>IP &amp; Confidentiality Disclosure</strong>
              <p>{consentPreview.disclosure_message}</p>
              <dl>
                <div>
                  <dt>Target endpoint</dt>
                  <dd><code>{consentPreview.endpoint_url}</code></dd>
                </div>
                <div>
                  <dt>Exact query SMILES (from ADR-016 chemical state)</dt>
                  <dd><code>{consentPreview.query_canonical_isomeric_smiles}</code></dd>
                </div>
                <div>
                  <dt>Consent payload SHA-256</dt>
                  <dd><code>{consentPreview.consent_payload_sha256}</code></dd>
                </div>
              </dl>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={ipConsentChecked}
                  onChange={(e) => setIpConsentChecked(e.target.checked)}
                />
                <span>
                  I explicitly authorize transmitting this canonical SMILES to{" "}
                  <code>{consentPreview.provider}</code> and understand it may disclose
                  confidential intellectual property.
                </span>
              </label>
              <button
                type="button"
                className="primary-button"
                disabled={!ipConsentChecked || searching}
                onClick={() => void handleRunOnlineSearch()}
              >
                {searching ? "Querying provider & recalculating RDKit…" : "Run opt-in online search"}
              </button>
            </div>
          ) : null}
        </div>
      )}

      {/* Step 2: Explicit Curation -> Derived Mini-Library */}
      {searchResult ? (
        <div className="analog-step-card">
          <h4>
            2. Curate Analog Hits ({searchResult.hits.length} candidates · RDKit{" "}
            {searchResult.rdkit_version})
          </h4>
          {searchResult.warnings.length > 0 ? (
            <ul className="field-note">
              {searchResult.warnings.map((w, idx) => (
                <li key={`${w.code}-${idx}`}>
                  <strong>{w.code}:</strong> {w.message}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="analog-hit-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Keep</th>
                  <th>Role</th>
                  <th>Identifier</th>
                  <th>Local RDKit Tanimoto</th>
                  <th>Provider sim.</th>
                  <th>Heavy atoms</th>
                  <th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {searchResult.hits.map((hit) => (
                  <tr key={hit.hit_id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${hit.identifier}`}
                        checked={Boolean(selectedHitIds[hit.hit_id])}
                        onChange={(e) =>
                          setSelectedHitIds((prev) => ({
                            ...prev,
                            [hit.hit_id]: e.target.checked,
                          }))
                        }
                      />
                    </td>
                    <td>
                      <code>{hit.role}</code>
                    </td>
                    <td>
                      <strong>{hit.identifier}</strong>
                      {hit.provider_compound_id ? (
                        <small> · {hit.provider_compound_id}</small>
                      ) : null}
                    </td>
                    <td>{formatScientificNumber(hit.local_rdkit_tanimoto, 3)}</td>
                    <td>
                      {hit.provider_similarity !== null
                        ? formatScientificNumber(hit.provider_similarity, 3)
                        : "—"}
                    </td>
                    <td>{hit.heavy_atom_count}</td>
                    <td>
                      {[
                        hit.had_multiple_fragments ? "multi-fragment/salt" : null,
                        hit.undefined_stereocenter_count > 0
                          ? `${hit.undefined_stereocenter_count} undef. stereo`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="analog-form-grid">
            <label>
              Derived mini-library name
              <input
                type="text"
                value={derivedLibraryName}
                onChange={(e) => setDerivedLibraryName(e.target.value)}
              />
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={includeSeedControl}
                onChange={(e) => setIncludeSeedControl(e.target.checked)}
              />
              <span>Include parent seed_control for mandatory in-box re-docking</span>
            </label>
            {!includeSeedControl ? (
              <label>
                Required justification for excluding seed_control
                <input
                  type="text"
                  value={seedExclusionReason}
                  onChange={(e) => setSeedExclusionReason(e.target.value)}
                  placeholder="Explain why seed_control is omitted"
                />
              </label>
            ) : null}
          </div>

          <button
            type="button"
            className="primary-button"
            disabled={
              curating ||
              chosenCount === 0 ||
              (!includeSeedControl && !seedExclusionReason.trim())
            }
            onClick={() => void handleCreateSelection()}
          >
            {curating
              ? "Creating derived mini-library…"
              : `Create derived mini-library (${chosenCount} selected)`}
          </button>

          {selectionResult ? (
            <div className="state-resolved-note" role="status">
              <strong>
                Derived mini-library created ({selectionResult.selected_count} compounds):
              </strong>{" "}
              <code>{selectionResult.derived_library_id}</code> · SHA-256{" "}
              <code>{selectionResult.derived_library_sha256.slice(0, 12)}…</code>. Open the{" "}
              <strong>Ligand</strong> workspace to complete explicit ADR-016 microstate curation
              before docking.
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Step 3: Derive POSE_FOCUSED Binding Site */}
      <div className="analog-step-card">
        <h4>3. Derive Immutable POSE_FOCUSED Binding Site (or keep parent box)</h4>
        <p className="field-note">
          Shrinking the box around this pose creates a new immutable <code>POSE_FOCUSED</code>{" "}
          site without altering prior campaigns. Scores from a narrowed box are not directly
          comparable to the parent wide box (ADR-030 E4), and AutoGrid4 maps must be regenerated
          for the new box (E7).
        </p>
        <div className="analog-form-grid">
          <label>
            Padding around pose heavy atoms (Å)
            <input
              type="number"
              min={0}
              max={50}
              step={0.5}
              value={paddingInput}
              onChange={(e) => setPaddingInput(e.target.value)}
            />
          </label>
          <label>
            FlexRes interior containment margin (Å)
            <input
              type="number"
              min={0}
              max={20}
              step={0.5}
              value={flexMarginInput}
              onChange={(e) => setFlexMarginInput(e.target.value)}
            />
          </label>
        </div>
        <div className="analog-inline-actions">
          <button
            type="button"
            className="quiet-button"
            disabled={siteBusy}
            onClick={() => void handlePoseFocusedSite(false)}
          >
            Preview POSE_FOCUSED box
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={siteBusy}
            onClick={() => void handlePoseFocusedSite(true)}
          >
            {siteBusy ? "Validating geometry & FlexRes…" : "Save POSE_FOCUSED binding site"}
          </button>
        </div>

        {sitePreview ? (
          <div className="state-resolved-note" role="status">
            <strong>Preview box:</strong> center ({formatScientificNumber(sitePreview.box.center_x, 2)}
            , {formatScientificNumber(sitePreview.box.center_y, 2)},{" "}
            {formatScientificNumber(sitePreview.box.center_z, 2)}) Å · size (
            {formatScientificNumber(sitePreview.box.size_x, 2)},{" "}
            {formatScientificNumber(sitePreview.box.size_y, 2)},{" "}
            {formatScientificNumber(sitePreview.box.size_z, 2)}) Å
            {sitePreview.pose_focused_evidence
              ? ` · ${sitePreview.pose_focused_evidence.heavy_atom_count} heavy atoms`
              : ""}
          </div>
        ) : null}

        {savedSite ? (
          <div className="state-resolved-note" role="status">
            <strong>Saved immutable POSE_FOCUSED site:</strong>{" "}
            <code>{savedSite.binding_site_id}</code> · ready to select in Docking / AutoGrid4.
          </div>
        ) : null}
      </div>
    </section>
  );
}
