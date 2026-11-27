import { Fragment, useEffect, useMemo, useState, type FormEvent } from "react";

import { ankoraApi } from "../../api/client";
import { AnalogExpansionPanel } from "../expansion/AnalogExpansionPanel";
import {
  DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM,
  FROZEN_ECR_TAU,
  type AutoDock4RescoreBackend,
  type CalibrationRunRecord,
  type CatalogEntry,
  type ConsensusExport,
  type ConsensusParentDetail,
  type ConsensusRunRecord,
  type ConsensusVariantId,
  type MedoidConsensusBreakdown,
  type PairedBootstrapDelta,
  type PcL2ModelArtifact,
  type RankingEntry,
  type ScoreObservationFamily,
  type ScoringFunctionId,
} from "../../types/api";
import {
  formatApplicationDateTime,
  formatScientificNumber,
  formatSignedScientificNumber,
} from "../../utils/format";

interface ConsensusWorkspaceProps {
  campaigns: CatalogEntry[];
}

const FAMILY_META: ReadonlyArray<{
  family: ScoreObservationFamily;
  label: string;
  shortLabel: string;
  barClass: string;
}> = [
  {
    family: "vina_vinardo",
    label: "Vina / Vinardo",
    shortLabel: "Vina",
    barClass: "consensus-bar-vina",
  },
  {
    family: "autodock4",
    label: "AutoDock4",
    shortLabel: "AD4",
    barClass: "consensus-bar-ad4",
  },
  {
    family: "gnina_neural",
    label: "GNINA Neural",
    shortLabel: "GNINA",
    barClass: "consensus-bar-gnina",
  },
];

const FUNCTION_META: Record<ScoringFunctionId, { label: string; unit: string }> = {
  vina: { label: "Vina", unit: "kcal/mol" },
  vinardo: { label: "Vinardo", unit: "kcal/mol" },
  autodock4: { label: "AutoDock4", unit: "kcal/mol" },
  gnina_cnn_score: { label: "GNINA CNNscore", unit: "dimensionless" },
  gnina_cnn_affinity: { label: "GNINA CNNaffinity", unit: "pK" },
  gnina_cnn_vs: { label: "GNINA CNN_VS", unit: "pK" },
  gnina_minimized_affinity: { label: "GNINA minimizedAffinity", unit: "kcal/mol" },
};

const HIGH_DISAGREEMENT_THRESHOLD = 40.0;

function shortHash(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 12 ? value.slice(0, 12) : value;
}

function selectedMedoidForParent(detail: ConsensusParentDetail): MedoidConsensusBreakdown | null {
  if (detail.medoids.length === 0) return null;
  if (detail.selected_medoid_cluster_id) {
    const exact = detail.medoids.find(
      (item) => item.cluster_id === detail.selected_medoid_cluster_id,
    );
    if (exact) return exact;
  }
  return detail.medoids[0] ?? null;
}

export function ConsensusWorkspace({ campaigns }: ConsensusWorkspaceProps) {
  const [runs, setRuns] = useState<ConsensusRunRecord[]>([]);
  const [selectedConsensusId, setSelectedConsensusId] = useState<string | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Create form state — k_max starts intentionally blank (`ADR-030 E2`: no silent default).
  const [createOpen, setCreateOpen] = useState(false);
  const [runName, setRunName] = useState("");
  const [variantId, setVariantId] = useState<ConsensusVariantId>("pcq-core-v1");
  const [selectedCatalogIds, setSelectedCatalogIds] = useState<string[]>([]);
  const [autogridMapSetId, setAutogridMapSetId] = useState("");
  const [autodock4Backend, setAutodock4Backend] =
    useState<AutoDock4RescoreBackend>("autodock4_epdb");
  const [includeVinardo, setIncludeVinardo] = useState(true);
  const [gninaFunction, setGninaFunction] = useState<ScoringFunctionId>("gnina_cnn_vs");
  const [kMaxInput, setKMaxInput] = useState("");
  const [rmsdThresholdInput, setRmsdThresholdInput] = useState(
    String(DEFAULT_CLUSTER_RMSD_THRESHOLD_ANGSTROM),
  );
  const [referencePanelId, setReferencePanelId] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Expandable parent rows for inspecting medoids & native-unit scores.
  const [expandedParents, setExpandedParents] = useState<Record<string, boolean>>({});

  // Opt-in gated PC-L2 calibration state (`ADR-030 §3`).
  const [pcL2Open, setPcL2Open] = useState(false);
  const [calibrations, setCalibrations] = useState<CalibrationRunRecord[] | null>(null);
  const [calibrationsError, setCalibrationsError] = useState<string | null>(null);
  const [calibrationIdInput, setCalibrationIdInput] = useState("");
  const [l2RegInput, setL2RegInput] = useState("1.0");
  const [fittingPcL2, setFittingPcL2] = useState(false);
  const [pcL2Error, setPcL2Error] = useState<string | null>(null);

  // Opt-in Export v5 state (`M6c`).
  const [exportingBundle, setExportingBundle] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportedBundle, setExportedBundle] = useState<ConsensusExport | null>(null);

  useEffect(() => {
    let disposed = false;
    setLoadingRuns(true);
    setLoadError(null);
    void ankoraApi
      .listConsensusRuns()
      .then((response) => {
        if (disposed) return;
        setRuns(response.runs);
        setSelectedConsensusId((current) => {
          if (current && response.runs.some((r) => r.consensus_id === current)) return current;
          return response.runs[0]?.consensus_id ?? null;
        });
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        setRuns([]);
        setLoadError(
          reason instanceof Error ? reason.message : "Consensus runs could not be loaded.",
        );
      })
      .finally(() => {
        if (!disposed) setLoadingRuns(false);
      });
    return () => {
      disposed = true;
    };
  }, []);

  // Load calibration runs lazily only when the scientist opens the opt-in PC-L2 panel.
  useEffect(() => {
    if (!pcL2Open || calibrations !== null) return;
    let disposed = false;
    setCalibrationsError(null);
    void ankoraApi
      .listCalibrations()
      .then((items) => {
        if (disposed) return;
        setCalibrations(items);
        if (!calibrationIdInput && items.length > 0) {
          setCalibrationIdInput(items[0].calibration_id);
        }
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        setCalibrations([]);
        setCalibrationsError(
          reason instanceof Error
            ? reason.message
            : "Calibration runs could not be loaded; enter a calibration run ID manually.",
        );
      });
    return () => {
      disposed = true;
    };
  }, [pcL2Open, calibrations, calibrationIdInput]);

  const selectedRun = useMemo(
    () => runs.find((run) => run.consensus_id === selectedConsensusId) ?? runs[0] ?? null,
    [runs, selectedConsensusId],
  );

  const completedCampaigns = useMemo(
    () => campaigns.filter((entry) => entry.status === "completed"),
    [campaigns],
  );

  const knownPanels = useMemo(() => {
    const seen = new Map<string, { panelId: string; sha: string; runName: string }>();
    for (const run of runs) {
      if (!seen.has(run.reference_panel.panel_id)) {
        seen.set(run.reference_panel.panel_id, {
          panelId: run.reference_panel.panel_id,
          sha: run.reference_panel.reference_panel_sha256,
          runName: run.name,
        });
      }
    }
    return [...seen.values()];
  }, [runs]);

  const detailsByParent = useMemo(() => {
    const map = new Map<string, ConsensusParentDetail>();
    if (!selectedRun) return map;
    for (const detail of selectedRun.parent_details) {
      map.set(detail.parent_compound_id, detail);
    }
    return map;
  }, [selectedRun]);

  const fullProfileEntries = useMemo<RankingEntry[]>(
    () => selectedRun?.ranking.entries.filter((e) => e.tier === "full_profile") ?? [],
    [selectedRun],
  );

  const partialEntries = useMemo<RankingEntry[]>(
    () => selectedRun?.ranking.entries.filter((e) => e.tier === "partial_or_unscored") ?? [],
    [selectedRun],
  );

  const showCoreColumn = Boolean(
    selectedRun && (selectedRun.variant_id === "pcq-neural-v1" || selectedRun.core_ranking),
  );

  function toggleCampaignSource(entry: CatalogEntry) {
    setSelectedCatalogIds((current) => {
      const exists = current.includes(entry.catalog_id);
      const next = exists
        ? current.filter((id) => id !== entry.catalog_id)
        : [...current, entry.catalog_id];
      if (!exists && entry.map_set_id && !autogridMapSetId.trim()) {
        setAutogridMapSetId(entry.map_set_id);
      }
      return next;
    });
  }

  function toggleExpandedParent(parentId: string) {
    setExpandedParents((current) => ({
      ...current,
      [parentId]: !current[parentId],
    }));
  }

  async function handleCreateSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);

    const trimmedName = runName.trim();
    if (!trimmedName) {
      setCreateError("Provide a descriptive name for this immutable consensus run.");
      return;
    }
    if (selectedCatalogIds.length === 0) {
      setCreateError("Select at least one completed campaign sharing the same receptor and box.");
      return;
    }
    const trimmedMapSet = autogridMapSetId.trim();
    if (!trimmedMapSet) {
      setCreateError(
        "AutoGrid4 map set ID is required so every medoid is cross-scored on the exact same maps.",
      );
      return;
    }
    const parsedKMax = Number.parseInt(kMaxInput.trim(), 10);
    if (!kMaxInput.trim() || !Number.isInteger(parsedKMax) || parsedKMax < 1) {
      setCreateError(
        "Explicit K_max (integer >= 1) is required by ADR-030 E2; no silent default is assumed.",
      );
      return;
    }
    const parsedRmsd = Number.parseFloat(rmsdThresholdInput.trim());
    if (!Number.isFinite(parsedRmsd) || parsedRmsd <= 0 || parsedRmsd > 5.0) {
      setCreateError("Complete-linkage RMSD threshold must be between 0 and 5.0 A.");
      return;
    }

    setCreating(true);
    try {
      const created = await ankoraApi.createCampaignConsensus({
        name: trimmedName,
        variant_id: variantId,
        sources: selectedCatalogIds.map((catalog_id) => ({ catalog_id })),
        autogrid_map_set_id: trimmedMapSet,
        autodock4_backend: autodock4Backend,
        include_vinardo: includeVinardo,
        gnina_function: variantId === "pcq-neural-v1" ? gninaFunction : undefined,
        k_max: parsedKMax,
        rmsd_threshold_angstrom: parsedRmsd,
        reference_panel_id: referencePanelId.trim() || null,
      });
      setRuns((current) => [created, ...current]);
      setSelectedConsensusId(created.consensus_id);
      setCreateOpen(false);
      setRunName("");
      setKMaxInput("");
    } catch (reason: unknown) {
      setCreateError(
        reason instanceof Error ? reason.message : "Consensus run could not be created.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleFitPcL2(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRun) return;
    setPcL2Error(null);

    const trimmedCal = calibrationIdInput.trim();
    if (!trimmedCal) {
      setPcL2Error("Select or enter a Calibration run ID before fitting gated PC-L2.");
      return;
    }
    const parsedL2 = Number.parseFloat(l2RegInput.trim());
    if (!Number.isFinite(parsedL2) || parsedL2 <= 0) {
      setPcL2Error("L2 regularization (lambda) must be a positive finite number.");
      return;
    }

    setFittingPcL2(true);
    try {
      const derivative = await ankoraApi.fitConsensusPcL2(selectedRun.consensus_id, {
        calibration_id: trimmedCal,
        l2_regularization: parsedL2,
      });
      setRuns((current) => [derivative, ...current]);
      setSelectedConsensusId(derivative.consensus_id);
      setPcL2Open(false);
    } catch (reason: unknown) {
      setPcL2Error(reason instanceof Error ? reason.message : "PC-L2 calibration failed.");
    } finally {
      setFittingPcL2(false);
    }
  }

  async function handleExportBundle() {
    if (!selectedRun) return;
    setExportError(null);
    setExportingBundle(true);
    try {
      const result = await ankoraApi.exportConsensusRun(selectedRun.consensus_id, {
        displayName: selectedRun.name.slice(0, 80),
      });
      setExportedBundle(result);
    } catch (reason: unknown) {
      setExportError(
        reason instanceof Error ? reason.message : "Consensus Export v5 bundle could not be written.",
      );
    } finally {
      setExportingBundle(false);
    }
  }

  return (
    <div className="consensus-workspace" aria-label="PC-Q rank-space consensus workspace">
      <div className="consensus-banner">
        <div>
          <strong>ADR-030 Pose-Concordant Quantile Consensus (PC-Q)</strong>
          <p className="field-note">
            Fixed published family weights (no user weight sliders). Every retained pose medoid is
            evaluated in place on the exact same coupled geometry via <code>--score_only</code>.{" "}
            <strong>PC-Q (0–100)</strong> is dimensionless inter-family concordance, never binding
            free energy (ΔG); <strong>PC-ECR (τ = {FROZEN_ECR_TAU})</strong> remains on its
            separate <code>1/σ</code> scale.
          </p>
        </div>
        <div className="consensus-banner-actions">
          <button
            type="button"
            className="primary-action"
            onClick={() => {
              setCreateError(null);
              setCreateOpen((open) => !open);
            }}
          >
            {createOpen ? "Close builder" : "New consensus run"}
          </button>
        </div>
      </div>

      {createOpen ? (
        <form
          className="consensus-form"
          aria-label="Create consensus run"
          onSubmit={(e) => void handleCreateSubmit(e)}
          noValidate
        >
          <div className="consensus-form-header">
            <h3>Create immutable consensus run</h3>
            <p className="field-note">
              Clusters saved poses per parent compound at complete-linkage{" "}
              <code>d_joint &lt;= RMSD</code>, caps retained clusters at explicit{" "}
              <code>K_max</code>, cross-scores medoids in place, and locks an immutable{" "}
              <code>ReferencePanelArtifact</code>.
            </p>
          </div>

          {createError ? (
            <div className="structure-error" role="alert">
              {createError}
            </div>
          ) : null}

          <div className="consensus-form-grid">
            <label>
              Run name
              <input
                type="text"
                value={runName}
                onChange={(e) => setRunName(e.target.value)}
                placeholder="e.g. EGFR rigid Vina + AD4 consensus"
              />
            </label>

            <label>
              Published variant (fixed weights)
              <select
                value={variantId}
                onChange={(e) => setVariantId(e.target.value as ConsensusVariantId)}
              >
                <option value="pcq-core-v1">
                  pcq-core-v1 · Vina/Vinardo (0.50) + AutoDock4 (0.50)
                </option>
                <option value="pcq-neural-v1">
                  pcq-neural-v1 · Vina/Vinardo (1/3) + AutoDock4 (1/3) + GNINA (1/3)
                </option>
              </select>
            </label>

            <label>
              Explicit K_max per parent (required)
              <input
                type="number"
                min={1}
                step={1}
                value={kMaxInput}
                onChange={(e) => setKMaxInput(e.target.value)}
                placeholder="Required (e.g. 5)"
              />
            </label>

            <label>
              Complete-linkage RMSD threshold (Å)
              <input
                type="number"
                min={0.1}
                max={5.0}
                step={0.1}
                value={rmsdThresholdInput}
                onChange={(e) => setRmsdThresholdInput(e.target.value)}
              />
            </label>

            <label>
              AutoGrid4 map set ID
              <input
                type="text"
                value={autogridMapSetId}
                onChange={(e) => setAutogridMapSetId(e.target.value)}
                placeholder="Shared AutoGrid4 map_set_id"
              />
            </label>

            <label>
              AutoDock4 score-only backend
              <select
                value={autodock4Backend}
                onChange={(e) => setAutodock4Backend(e.target.value as AutoDock4RescoreBackend)}
              >
                <option value="autodock4_epdb">AutoDock4 4.2.6 epdb (canonical)</option>
                <option value="vina_ad4_maps">Vina --scoring ad4 --maps</option>
              </select>
            </label>

            {variantId === "pcq-neural-v1" ? (
              <label>
                GNINA neural scoring function
                <select
                  value={gninaFunction}
                  onChange={(e) => setGninaFunction(e.target.value as ScoringFunctionId)}
                >
                  <option value="gnina_cnn_vs">gnina_cnn_vs (pK)</option>
                  <option value="gnina_cnn_score">gnina_cnn_score (dimensionless)</option>
                  <option value="gnina_cnn_affinity">gnina_cnn_affinity (pK)</option>
                </select>
              </label>
            ) : null}

            <label>
              Reference panel (optional reuse · E1)
              <select
                value={referencePanelId}
                onChange={(e) => setReferencePanelId(e.target.value)}
              >
                <option value="">Seal new ReferencePanelArtifact from this run</option>
                {knownPanels.map((panel) => (
                  <option key={panel.panelId} value={panel.panelId}>
                    Reuse {shortHash(panel.sha)} · {panel.runName}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="consensus-checkbox-inline">
            <input
              type="checkbox"
              checked={includeVinardo}
              onChange={(e) => setIncludeVinardo(e.target.checked)}
            />
            <span>
              Include Vinardo inside the Vina/Vinardo family block (0.50/0.50 within-block average,
              zero double-voting)
            </span>
          </label>

          <fieldset className="consensus-campaign-picker">
            <legend>Source campaigns (must share exact receptor &amp; binding box · E4)</legend>
            {completedCampaigns.length === 0 ? (
              <p className="field-note">
                No completed campaigns are loaded in the catalog yet. Complete at least one docking
                campaign first.
              </p>
            ) : (
              <div className="consensus-campaign-list">
                {completedCampaigns.map((entry) => {
                  const checked = selectedCatalogIds.includes(entry.catalog_id);
                  return (
                    <label key={entry.catalog_id} className="consensus-campaign-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleCampaignSource(entry)}
                      />
                      <span>
                        <strong>{entry.engine_label}</strong> · {entry.catalog_id} ·{" "}
                        {entry.succeeded_count}/{entry.selected_count} compounds
                        {entry.map_set_id ? ` · map ${shortHash(entry.map_set_id)}` : ""}
                        {entry.stale ? (
                          <em
                            className="results-card-warning"
                            title={entry.stale_reasons?.join("; ") || "Stale lineage"}
                          >
                            {" "}· stale lineage
                          </em>
                        ) : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
            {completedCampaigns.some(
              (entry) => selectedCatalogIds.includes(entry.catalog_id) && entry.stale,
            ) ? (
              <p className="protonation-blocker" role="alert">
                One or more selected source campaigns have stale upstream lineage (ADR-011).
                Review or refresh before presenting consensus rankings as current.
              </p>
            ) : null}
          </fieldset>

          <div className="consensus-form-actions">
            <button type="submit" className="primary-action" disabled={creating}>
              {creating ? "Running cross-engine consensus…" : "Run PC-Q consensus"}
            </button>
            <button
              type="button"
              className="quiet-button"
              disabled={creating}
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      {loadError ? (
        <div className="structure-error" role="alert">
          {loadError}
        </div>
      ) : null}

      {loadingRuns ? (
        <div className="operation-progress" role="progressbar" aria-label="Loading consensus runs">
          <span />
          <p>Loading saved consensus runs</p>
        </div>
      ) : runs.length === 0 ? (
        <div className="viewer-placeholder ligand-placeholder">
          <div className="viewer-message">
            <div className="molecule-glyph">◈</div>
            <h3>No consensus runs recorded yet</h3>
            <p>
              Create an opt-in PC-Q run to cluster poses in joint (ligand, flex) space and combine
              independent scoring families strictly in rank-quantile space without mixing native
              units.
            </p>
          </div>
        </div>
      ) : selectedRun ? (
        <div className="consensus-detail">
          <div className="consensus-run-selector">
            <label>
              Saved consensus run
              <select
                value={selectedRun.consensus_id}
                onChange={(e) => {
                  setSelectedConsensusId(e.target.value);
                  setExpandedParents({});
                  setPcL2Error(null);
                  setExportedBundle(null);
                  setExportError(null);
                }}
              >
                {runs.map((run) => (
                  <option key={run.consensus_id} value={run.consensus_id}>
                    {run.name} · {run.variant_id} · {run.ranking.full_profile_count}/
                    {run.ranking.total_parents} full-profile
                    {run.pc_l2_model ? " · PC-L2" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className="field-note">
              Created {formatApplicationDateTime(selectedRun.created_at)}
            </span>
            <button
              type="button"
              className="quiet-button"
              disabled={exportingBundle}
              onClick={() => void handleExportBundle()}
            >
              {exportingBundle ? "Exporting consensus bundle…" : "Export consensus bundle"}
            </button>
          </div>

          {exportError ? (
            <div className="structure-error" role="alert">
              {exportError}
            </div>
          ) : null}

          {exportedBundle && exportedBundle.source_id === selectedRun.consensus_id ? (
            <div
              className="consensus-provenance"
              role="status"
              aria-label={`Export v${exportedBundle.ankora_export_format} consensus bundle`}
            >
              <div className="consensus-chip-row">
                <span className="read-only-badge">Export v{exportedBundle.ankora_export_format}</span>
                <span className="read-only-badge" title={exportedBundle.input_identity_sha256}>
                  Inputs {shortHash(exportedBundle.input_identity_sha256)}
                </span>
                <span className="read-only-badge" title={exportedBundle.bundle_identity_sha256}>
                  Bundle {shortHash(exportedBundle.bundle_identity_sha256)}
                </span>
              </div>
              {exportedBundle.stale ? (
                <p className="protonation-blocker" role="alert">
                  Stale lineage:{" "}
                  {exportedBundle.stale_reasons?.join("; ") ||
                    "Upstream artifact changed after this consensus run was created."}
                </p>
              ) : null}
              <div className="export-files">
                {exportedBundle.files.map((filename) => (
                  <a
                    key={filename}
                    href={ankoraApi.exportContentUrl(
                      `/exports/${exportedBundle.export_id}/${filename}`,
                    )}
                    download={filename}
                  >
                    {filename}
                  </a>
                ))}
              </div>
            </div>
          ) : null}

          <section className="consensus-provenance" aria-label="Consensus provenance">
            <div className="consensus-chip-row">
              <span className="read-only-badge">{selectedRun.variant_id}</span>
              <span className="read-only-badge">K_max = {selectedRun.k_max}</span>
              <span className="read-only-badge">
                RMSD &lt;= {formatScientificNumber(selectedRun.rmsd_threshold_angstrom, 1)} Å
              </span>
              <span
                className="read-only-badge"
                title={selectedRun.reference_panel.reference_panel_sha256}
              >
                Panel {shortHash(selectedRun.reference_panel.reference_panel_sha256)} (N_R ={" "}
                {selectedRun.reference_panel.total_panel_parents})
              </span>
              <span className="read-only-badge">
                {selectedRun.receptor_flex_spec.mode === "sidechain_flex"
                  ? `FlexRes coupled (${selectedRun.receptor_flex_spec.flex_residues.length} residues · E8)`
                  : "Rigid receptor"}
              </span>
              <span className="read-only-badge">
                Denominator: {selectedRun.ranking.full_profile_count} ranked +{" "}
                {selectedRun.ranking.partial_or_unscored_count} partial/unscored ={" "}
                {selectedRun.ranking.total_parents} total
              </span>
            </div>

            <div className="consensus-weights-strip">
              <span className="consensus-weights-label">Fixed published block weights:</span>
              {FAMILY_META.filter((m) => selectedRun.block_weights[m.family] !== undefined).map(
                (meta) => (
                  <span key={meta.family} className="consensus-weight-pill">
                    {meta.label}:{" "}
                    {formatScientificNumber(
                      (selectedRun.block_weights[meta.family] ?? 0) * 100,
                      1,
                    )}
                    %
                  </span>
                ),
              )}
            </div>

            {selectedRun.warnings.length > 0 ? (
              <ul className="consensus-warning-list" aria-label="Consensus warnings">
                {selectedRun.warnings.map((warning, idx) => (
                  <li key={`${warning.code}-${idx}`} className="consensus-warning-item">
                    <strong>{warning.code}</strong>: {warning.message}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="consensus-tier-section" aria-label="Tier 1 full-profile rankings">
            <div className="consensus-section-heading">
              <h3>
                Tier 1 · Full-profile ranked parents ({selectedRun.ranking.full_profile_count} /{" "}
                {selectedRun.ranking.total_parents})
              </h3>
              <p className="field-note">
                Dimensionless concordance only. Search Convergence is reported independently from
                scoring concordance; click a parent row to inspect medoids and native-unit scores.
              </p>
            </div>

            {fullProfileEntries.length === 0 ? (
              <p className="field-note">
                Zero parents achieved a complete scoring profile across all enabled families.
              </p>
            ) : (
              <div className="consensus-table-scroll">
                <table className="consensus-table">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Parent</th>
                      <th>PC-Q (0–100)</th>
                      {showCoreColumn ? <th>PC-Q Core (0–100)</th> : null}
                      <th>PC-ECR (τ={selectedRun.ecr_tau}, 1/σ scale)</th>
                      <th>D_ic</th>
                      <th>Family block quantiles (Q_icb)</th>
                      <th>Search convergence</th>
                      <th>RotBonds</th>
                      {selectedRun.pc_l2_model ? (
                        <th>
                          PC-L2 (logit ·{" "}
                          {selectedRun.pc_l2_model.promoted ? "Promoted" : "Unpromoted"})
                        </th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {fullProfileEntries.map((entry) => {
                      const detail = detailsByParent.get(entry.parent_compound_id);
                      const medoid = detail ? selectedMedoidForParent(detail) : null;
                      const expanded = Boolean(expandedParents[entry.parent_compound_id]);
                      const highDisagreement =
                        (entry.inter_family_disagreement ?? 0) >= HIGH_DISAGREEMENT_THRESHOLD;
                      const colCount =
                        8 + (showCoreColumn ? 1 : 0) + (selectedRun.pc_l2_model ? 1 : 0);

                      return (
                        <Fragment key={entry.parent_compound_id}>
                          <tr>
                            <td className="numeric-cell">#{entry.rank}</td>
                            <td>
                              <button
                                type="button"
                                className="consensus-parent-toggle"
                                aria-expanded={expanded}
                                onClick={() => toggleExpandedParent(entry.parent_compound_id)}
                              >
                                <span>{expanded ? "▾" : "▸"}</span>
                                <strong>{entry.parent_compound_id}</strong>
                              </button>
                              <div className="consensus-sublabel">
                                {entry.parent_state_id}
                                {detail
                                  ? ` · ${detail.retained_cluster_count}/${detail.total_clusters_found} clusters`
                                  : ""}
                              </div>
                            </td>
                            <td className="numeric-cell">
                              <strong>{formatScientificNumber(entry.score_value, 2)}</strong>
                            </td>
                            {showCoreColumn ? (
                              <td className="numeric-cell">
                                {formatScientificNumber(detail?.pcq_core_score, 2)}
                              </td>
                            ) : null}
                            <td className="numeric-cell">
                              <span>{formatScientificNumber(detail?.pc_ecr_score, 4)}</span>
                              <div className="consensus-sublabel">1/σ scale</div>
                            </td>
                            <td
                              className={
                                highDisagreement
                                  ? "numeric-cell consensus-disagreement-high"
                                  : "numeric-cell"
                              }
                            >
                              {formatScientificNumber(entry.inter_family_disagreement, 1)}
                            </td>
                            <td>
                              {medoid ? (
                                <FamilyBlockBars
                                  blockQuantiles={medoid.block_quantiles}
                                  activeFamilies={FAMILY_META.filter(
                                    (m) => selectedRun.block_weights[m.family] !== undefined,
                                  )}
                                />
                              ) : (
                                "—"
                              )}
                            </td>
                            <td>
                              {entry.search_convergence_count !== null &&
                              entry.search_convergence_count !== undefined &&
                              entry.search_engine_count !== null &&
                              entry.search_engine_count !== undefined ? (
                                <span
                                  className="consensus-convergence-badge"
                                  title="Independent search-engine pose convergence (never mixed into PC-Q)"
                                >
                                  {entry.search_convergence_count}/{entry.search_engine_count}{" "}
                                  engines
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="numeric-cell">
                              {detail?.rotatable_bond_count !== null &&
                              detail?.rotatable_bond_count !== undefined
                                ? detail.rotatable_bond_count
                                : "—"}
                            </td>
                            {selectedRun.pc_l2_model ? (
                              <td className="numeric-cell">
                                {formatSignedScientificNumber(detail?.pc_l2_score, 3)}
                              </td>
                            ) : null}
                          </tr>

                          {expanded && detail ? (
                            <tr className="consensus-medoid-row">
                              <td colSpan={colCount}>
                                <MedoidDrawer detail={detail} run={selectedRun} />
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {partialEntries.length > 0 ? (
            <section
              className="consensus-tier-partial"
              aria-label="Tier 2 partial or unscored parents"
            >
              <div className="consensus-section-heading">
                <h3>
                  Tier 2 · Partial or unscored parents ({partialEntries.length} retained unranked ·
                  E6)
                </h3>
                <p className="field-note">
                  Retained explicitly in the campaign denominator (
                  {selectedRun.ranking.total_parents} parents) with zero score imputation and no
                  consensus rank.
                </p>
              </div>
              <div className="consensus-table-scroll">
                <table className="consensus-table">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Parent</th>
                      <th>State</th>
                      <th>Input poses</th>
                      <th>Failure / exclusion codes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {partialEntries.map((entry) => {
                      const detail = detailsByParent.get(entry.parent_compound_id);
                      return (
                        <tr key={entry.parent_compound_id}>
                          <td>
                            <span className="read-only-badge">Unranked · no imputation</span>
                          </td>
                          <td>
                            <strong>{entry.parent_compound_id}</strong>
                          </td>
                          <td>{entry.parent_state_id}</td>
                          <td className="numeric-cell">{detail?.total_input_poses ?? 0}</td>
                          <td>
                            <div className="consensus-code-list">
                              {entry.failure_or_exclusion_codes.map((code) => (
                                <code key={code} className="consensus-failure-code">
                                  {code}
                                </code>
                              ))}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          <section className="consensus-pcl2-section" aria-label="Gated PC-L2 calibration">
            <div className="consensus-section-heading">
              <div>
                <h3>Optional gated PC-L2 calibration (ADR-030 §3)</h3>
                <p className="field-note">
                  Strictly convex non-negative L2 logistic regression fit exclusively on a sealed
                  Calibration split and gated on its locked Confirmation split against every single
                  scoring function. Creates a new immutable derivative run.
                </p>
              </div>
              <button
                type="button"
                className="quiet-button"
                onClick={() => {
                  setPcL2Error(null);
                  setPcL2Open((open) => !open);
                }}
              >
                {pcL2Open ? "Close PC-L2 form" : "Fit gated PC-L2 derivative"}
              </button>
            </div>

            {pcL2Open ? (
              <form
                className="consensus-pcl2-form"
                onSubmit={(e) => void handleFitPcL2(e)}
                noValidate
              >
                {pcL2Error ? (
                  <div className="structure-error" role="alert">
                    {pcL2Error}
                  </div>
                ) : null}
                {calibrationsError ? (
                  <p className="protonation-blocker" role="alert">
                    {calibrationsError}
                  </p>
                ) : null}
                <div className="consensus-form-grid">
                  <label>
                    Calibration run ID (M2)
                    {calibrations && calibrations.length > 0 ? (
                      <select
                        value={calibrationIdInput}
                        onChange={(e) => setCalibrationIdInput(e.target.value)}
                      >
                        {calibrations.map((cal) => (
                          <option key={cal.calibration_id} value={cal.calibration_id}>
                            {cal.calibration_id} · {cal.status}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={calibrationIdInput}
                        onChange={(e) => setCalibrationIdInput(e.target.value)}
                        placeholder="Calibration run UUID"
                      />
                    )}
                  </label>
                  <label>
                    L2 regularization (λ &gt; 0)
                    <input
                      type="number"
                      min={0.001}
                      step={0.1}
                      value={l2RegInput}
                      onChange={(e) => setL2RegInput(e.target.value)}
                    />
                  </label>
                </div>
                <div className="consensus-form-actions">
                  <button type="submit" className="primary-action" disabled={fittingPcL2}>
                    {fittingPcL2 ? "Fitting PC-L2…" : "Fit & gate on Confirmation"}
                  </button>
                </div>
              </form>
            ) : null}

            {selectedRun.pc_l2_model ? (
              <PcL2AuditCard model={selectedRun.pc_l2_model} />
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function FamilyBlockBars({
  blockQuantiles,
  activeFamilies,
}: {
  blockQuantiles: Partial<Record<ScoreObservationFamily, number>>;
  activeFamilies: ReadonlyArray<(typeof FAMILY_META)[number]>;
}) {
  return (
    <div className="consensus-block-bars" aria-label="Family block quantiles">
      {activeFamilies.map((meta) => {
        const value = blockQuantiles[meta.family];
        const widthPct =
          value !== undefined && Number.isFinite(value)
            ? Math.max(0, Math.min(100, value))
            : 0;
        return (
          <div key={meta.family} className="consensus-block-bar-row">
            <span className="consensus-block-bar-label">{meta.shortLabel}</span>
            <div className="consensus-block-bar-track" aria-hidden="true">
              <div
                className={`consensus-block-bar-fill ${meta.barClass}`}
                style={{ width: `${widthPct}%` }}
              />
            </div>
            <span className="consensus-block-bar-val">
              {formatScientificNumber(value, 1)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function parseMedoidPoseRef(
  medoidPoseId: string,
): { catalogId: string; ligandId: string; poseArtifactId: string } | null {
  const parts = medoidPoseId.split(":");
  if (parts.length < 4) return null;
  return {
    catalogId: `${parts[0]}:${parts[1]}`,
    ligandId: parts[2],
    poseArtifactId: parts.slice(3).join(":"),
  };
}

function MedoidDrawer({
  detail,
  run,
}: {
  detail: ConsensusParentDetail;
  run: ConsensusRunRecord;
}) {
  const [expandingClusterId, setExpandingClusterId] = useState<string | null>(null);
  return (
    <div className="consensus-medoid-drawer">
      <div className="consensus-medoid-drawer-title">
        <strong>Retained pose-cluster medoids ({detail.medoids.length})</strong>
        <span className="field-note">
          Native scores stay strictly paired with their native unit and are never averaged across
          families.
        </span>
      </div>
      <div className="consensus-medoid-cards">
        {detail.medoids.map((medoid) => {
          const isSelected = medoid.cluster_id === detail.selected_medoid_cluster_id;
          const poseRef = parseMedoidPoseRef(medoid.medoid_pose_id);
          const isExpanding = expandingClusterId === medoid.cluster_id;
          return (
            <div
              key={medoid.cluster_id}
              className={
                isSelected ? "consensus-medoid-card consensus-medoid-selected" : "consensus-medoid-card"
              }
            >
              <div className="consensus-medoid-card-head">
                <strong>
                  {medoid.cluster_id}
                  {isSelected ? " · selected medoid c*" : ""}
                </strong>
                <span className="field-note">
                  {medoid.member_count} pose{medoid.member_count === 1 ? "" : "s"} · max diameter{" "}
                  {formatScientificNumber(medoid.max_intra_cluster_rmsd_angstrom, 2)} Å · engines:{" "}
                  {medoid.search_engines_present.join(", ")}
                </span>
              </div>
              <dl className="consensus-native-score-grid">
                {(Object.entries(medoid.native_scores) as Array<[ScoringFunctionId, number]>).map(
                  ([fnId, rawVal]) => {
                    const meta = FUNCTION_META[fnId];
                    const qVal = medoid.function_quantiles[fnId];
                    return (
                      <div key={fnId}>
                        <dt>{meta?.label ?? fnId}</dt>
                        <dd>
                          {formatScientificNumber(rawVal, 3)}{" "}
                          <span className="consensus-unit">{meta?.unit ?? ""}</span>
                          {qVal !== undefined ? (
                            <span className="consensus-sublabel">
                              {" "}
                              (q = {formatScientificNumber(qVal, 1)})
                            </span>
                          ) : null}
                        </dd>
                      </div>
                    );
                  },
                )}
              </dl>
              {poseRef ? (
                <div className="analog-medoid-action">
                  <button
                    type="button"
                    className="quiet-button"
                    aria-expanded={isExpanding}
                    onClick={() =>
                      setExpandingClusterId(isExpanding ? null : medoid.cluster_id)
                    }
                  >
                    {isExpanding ? "Hide analog expansion" : "Expand analogs from medoid (ADR-033)"}
                  </button>
                  {isExpanding ? (
                    <AnalogExpansionPanel
                      sourceCatalogId={poseRef.catalogId}
                      sourceLigandId={poseRef.ligandId}
                      sourcePoseArtifactId={poseRef.poseArtifactId}
                      receptorId={run.receptor_id}
                      parentBindingSiteId={run.binding_site_id}
                      sourceConsensusId={run.consensus_id}
                      sourceClusterId={medoid.cluster_id}
                      seedLabel={detail.parent_compound_id}
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PcL2AuditCard({ model }: { model: PcL2ModelArtifact }) {
  const deltaRows: Array<{ id: string; label: string; isCode: boolean; delta: PairedBootstrapDelta }> = [
    ...Object.entries(model.confirmation_deltas_vs_single_engines).map(([baselineId, delta]) => ({
      id: baselineId,
      label: baselineId,
      isCode: true,
      delta,
    })),
    ...(model.confirmation_delta_vs_pcq
      ? [
          {
            id: "pcq_consensus",
            label: "PC-Q (zero-fit consensus)",
            isCode: false,
            delta: model.confirmation_delta_vs_pcq,
          },
        ]
      : []),
  ];
  return (
    <div
      className={
        model.promoted
          ? "consensus-pcl2-card consensus-pcl2-promoted"
          : "consensus-pcl2-card consensus-pcl2-unpromoted"
      }
    >
      <div className="consensus-pcl2-header">
        <div>
          <span className="read-only-badge">
            {model.promoted ? "PC-L2 Promoted" : "PC-L2 Unpromoted (audit only)"}
          </span>
          <strong className="consensus-pcl2-verdict">{model.promotion_verdict_text}</strong>
        </div>
        <span className="field-note">
          {model.solver_name} · {model.iterations} iters · λ ={" "}
          {formatScientificNumber(model.l2_regularization, 3)} · intercept ={" "}
          {formatSignedScientificNumber(model.intercept, 3)}
        </span>
      </div>

      <div className="consensus-pcl2-weights">
        <span className="consensus-weights-label">Non-negative weights (w_j &gt;= 0):</span>
        {model.feature_functions.map((fnId) => (
          <span key={fnId} className="consensus-weight-pill">
            {FUNCTION_META[fnId]?.label ?? fnId}:{" "}
            {formatScientificNumber(model.weights[fnId], 4)}
          </span>
        ))}
      </div>

      {deltaRows.length > 0 ? (
        <div className="consensus-table-scroll">
          <table className="consensus-table">
            <thead>
              <tr>
                <th>Confirmation baseline</th>
                <th>Confirmation Δ BEDROC_20</th>
                <th>95% paired parent-bootstrap CI</th>
                <th>SE</th>
                <th>Gate</th>
              </tr>
            </thead>
            <tbody>
              {deltaRows.map(({ id, label, isCode, delta }) => (
                <tr key={id}>
                  <td>
                    {isCode ? <code>{label}</code> : <strong>{label}</strong>}
                  </td>
                  <td className="numeric-cell">
                    {formatSignedScientificNumber(delta.point_delta, 4)}
                  </td>
                  <td className="numeric-cell">
                    [{formatSignedScientificNumber(delta.ci_lower, 4)},{" "}
                    {formatSignedScientificNumber(delta.ci_upper, 4)}]
                  </td>
                  <td className="numeric-cell">
                    {formatScientificNumber(delta.bootstrap_se, 4)}
                  </td>
                  <td>
                    <span className="read-only-badge">
                      {delta.excludes_zero_positively ? "CI > 0 (pass)" : "Includes 0"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
