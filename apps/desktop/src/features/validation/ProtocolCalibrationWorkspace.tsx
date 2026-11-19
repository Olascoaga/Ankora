import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type {
  BiasPropertyName,
  CalibrationCompoundInput,
  CalibrationConfirmRequest,
  CalibrationRunRecord,
  CalibrationSelectRequest,
  CalibrationSplitPolicy,
  CalibrationRunStatus,
  PairedBootstrapDelta,
  ProtocolEvaluationSummary,
  ScoreObservation,
  StructuredWarning,
} from "../../types/api";
import { INSUFFICIENT_EVIDENCE_TEXT } from "../../types/api";
import {
  formatApplicationTimestamp,
  formatScientificNumber,
  formatSignedScientificNumber,
} from "../../utils/format";
import "./redocking.css";

/**
 * Out-of-sample protocol calibration (M2c, `ADR-031` §3).
 *
 * The discipline this workspace exists to make visible is that a protocol is
 * chosen on the Calibration split *only*, sealed by a hash, and only then is
 * the locked Confirmation split opened — once. So the three stages are shown as
 * three separate, explicitly gated steps rather than one form: Confirmation
 * cannot be reached before a sealed selection exists, and once consumed it is
 * gone, with no re-run control left on screen to invite a second look.
 *
 * Nothing here softens a null result. When the paired interval does not exclude
 * zero, the recorded verdict text is the exact `ADR-031` phrase and it is
 * displayed verbatim, in the same prominent place a preference would be.
 */

interface ProtocolCalibrationWorkspaceProps {
  /** Pre-filled from the Validation context when one is open; editable otherwise. */
  receptorId?: string | null;
  bindingSiteId?: string | null;
  modeSwitch?: ReactNode;
}

const STAGE_STATUS_LABEL: Record<CalibrationRunStatus, string> = {
  split_locked: "Split locked",
  calibration_selected: "Calibration sealed · Confirmation locked",
  confirmation_completed: "Confirmation consumed (immutable)",
};

const VERDICT_LABEL: Record<string, string> = {
  preferred_over_baseline: "Preferred over baseline",
  insufficient_evidence_to_prefer_over_baseline: "Insufficient evidence",
  baseline_retained_by_one_se: "Baseline retained by the 1-SE rule",
};

const BIAS_PROPERTY_LABEL: Record<BiasPropertyName, string> = {
  molecular_weight: "MW",
  clogp: "cLogP",
  hbd: "HBD",
  hba: "HBA",
  rotatable_bonds: "RotBonds",
  formal_charge: "formal_charge",
};

/** The two codes that qualify every enrichment number read on this split. */
const AUDIT_WARNING_CODES = new Set([
  "CALIBRATION_DECOY_PROPERTY_BIAS",
  "CALIBRATION_CONFIRMATION_UNDERPOWERED",
]);

const DEFAULT_POLICY: CalibrationSplitPolicy = {
  grouping_strategy: "parent_and_murcko_scaffold",
  calibration_fraction: 0.6,
  split_seed: 20261119,
  min_confirmation_actives: 10,
  bedroc_alpha: 20,
  top_fraction: 0.01,
  bootstrap_replicates: 2000,
  bootstrap_seed: 20261119,
  confidence_level: 0.95,
};

interface PolicyFields {
  calibration_fraction: string;
  split_seed: string;
  min_confirmation_actives: string;
  bedroc_alpha: string;
  bootstrap_replicates: string;
}

const DEFAULT_POLICY_FIELDS: PolicyFields = {
  calibration_fraction: String(DEFAULT_POLICY.calibration_fraction),
  split_seed: String(DEFAULT_POLICY.split_seed),
  min_confirmation_actives: String(DEFAULT_POLICY.min_confirmation_actives),
  bedroc_alpha: String(DEFAULT_POLICY.bedroc_alpha),
  bootstrap_replicates: String(DEFAULT_POLICY.bootstrap_replicates),
};

export function ProtocolCalibrationWorkspace({
  receptorId,
  bindingSiteId,
  modeSwitch,
}: ProtocolCalibrationWorkspaceProps) {
  const [runs, setRuns] = useState<CalibrationRunRecord[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setHistoryError(null);
    void ankoraApi.listCalibrations()
      .then((next) => {
        if (disposed) return;
        // A split created in this session may be recorded before this initial
        // history request returns; it must not be dropped by the response.
        setRuns((current) => [
          ...(current ?? []).filter(
            (item) => !next.some((run) => run.calibration_id === item.calibration_id),
          ),
          ...next,
        ]);
        setSelectedId((current) => current ?? next[0]?.calibration_id ?? null);
      })
      .catch((reason: unknown) => {
        if (!disposed) setHistoryError(message(reason, "Calibration runs could not be read."));
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [reload]);

  function record(next: CalibrationRunRecord) {
    setRuns((current) => [
      next,
      ...(current ?? []).filter((run) => run.calibration_id !== next.calibration_id),
    ]);
    setSelectedId(next.calibration_id);
  }

  const selected = runs?.find((run) => run.calibration_id === selectedId) ?? null;

  return (
    <>
      <section
        className="workspace docking-workspace redocking-workspace calibration-workspace"
        aria-label="Protocol calibration workspace"
      >
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">07 / Validation</span>
            <h2>Out-of-sample protocol calibration</h2>
          </div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">M2c · ADR-031 §3</span>
          </div>
        </div>

        {historyError ? (
          <div className="structure-error" role="alert">
            {historyError}{" "}
            <button type="button" onClick={() => setReload((n) => n + 1)}>
              Retry calibration runs
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="operation-progress" role="progressbar" aria-label="Reading calibration runs">
            <span /><p>Reading recorded calibration runs</p>
          </div>
        ) : null}

        <CreateCalibrationSplit
          receptorId={receptorId ?? ""}
          bindingSiteId={bindingSiteId ?? ""}
          onCreated={record}
        />

        {!loading && runs?.length === 0 ? (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message">
              <div className="molecule-glyph">⌾</div>
              <h3>No calibration run recorded yet</h3>
              <p>
                A calibration run freezes a scaffold-grouped split before any
                comparison number exists. It docks and scores nothing itself.
              </p>
            </div>
          </div>
        ) : null}

        {selected ? (
          <div className="calibration-stages">
            <StageOneSplit run={selected} />
            <StageTwoSelection run={selected} onSealed={record} />
            <StageThreeConfirmation run={selected} onEvaluated={record} />
          </div>
        ) : null}
      </section>

      <aside className="inspector docking-inspector" aria-label="Protocol calibration inspector">
        <div className="inspector-heading">
          <span className="section-label">Calibration</span>
          <h2>Why the split is locked</h2>
          <p className="inspector-subtitle">
            A verdict chosen by looking at the data it is measured on is
            optimistically biased. Locking is what makes the number mean
            anything.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>Three stages, in one direction</span></div>
          <p className="field-note">
            The split is frozen first, the protocol is chosen on{" "}
            <strong>Calibration only</strong> and sealed by a hash, and the
            locked <strong>Confirmation</strong> split is opened once. No stage
            can be revisited after the next one begins, which is the whole point
            of recording them separately.
          </p>
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>The 1-SE parsimony rule</span></div>
          <p className="field-note">
            Among protocols within one standard error of the best observed
            <code>BEDROC_20</code>, the <strong>simplest</strong> is selected —
            rigid before <code>FlexRes</code>, fewer flexible residues, fewer
            fitted parameters, fewer engines, empirical before neural. A noisier
            complex protocol does not displace a baseline on a difference inside
            the noise.
          </p>
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>A null result is a result</span></div>
          <p className="field-note">
            When the paired parent-bootstrap interval does not exclude zero, the
            verdict is recorded as{" "}
            <strong>&ldquo;{INSUFFICIENT_EVIDENCE_TEXT}&rdquo;</strong> and
            published as it stands. It is not a failed run to repeat with other
            settings.
          </p>
        </section>
        {runs && runs.length > 0 ? (
          <section className="receptor-section">
            <div className="filter-heading"><span>Recorded calibration runs</span></div>
            <div className="campaign-history-list" role="group" aria-label="Recorded calibration runs">
              {runs.map((run) => (
                <button
                  key={run.calibration_id}
                  type="button"
                  className={run.calibration_id === selectedId
                    ? "campaign-history-entry selected"
                    : "campaign-history-entry"}
                  aria-current={run.calibration_id === selectedId ? "true" : undefined}
                  onClick={() => setSelectedId(run.calibration_id)}
                >
                  <span className="campaign-history-when">
                    <b>{run.receptor_id} · {run.binding_site_id}</b>
                    <small>
                      {formatApplicationTimestamp(run.created_at)}
                      {" · "}
                      {STAGE_STATUS_LABEL[run.status]}
                    </small>
                  </span>
                  <span className="campaign-history-best">
                    <b>{run.split.calibration_parent_ids.length}</b>
                    <small>calibration parents</small>
                  </span>
                </button>
              ))}
            </div>
            <p className="field-note">
              Reopening a run is read-only. A sealed selection and a consumed
              Confirmation split are never editable again.
            </p>
          </section>
        ) : null}
      </aside>
    </>
  );
}

/* --- Stage 1 -------------------------------------------------------------- */

function CreateCalibrationSplit({ receptorId, bindingSiteId, onCreated }: {
  receptorId: string;
  bindingSiteId: string;
  onCreated: (run: CalibrationRunRecord) => void;
}) {
  const [receptor, setReceptor] = useState(receptorId);
  const [site, setSite] = useState(bindingSiteId);
  const [compoundText, setCompoundText] = useState("");
  const [policy, setPolicy] = useState<PolicyFields>(DEFAULT_POLICY_FIELDS);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  function updatePolicy(key: keyof PolicyFields, value: string) {
    setPolicy((current) => ({ ...current, [key]: value }));
  }

  async function create() {
    setError(null);
    let compounds: CalibrationCompoundInput[];
    try {
      compounds = parseCompounds(compoundText);
    } catch (reason: unknown) {
      setError(message(reason, "The compound rows could not be read."));
      return;
    }
    const resolved = resolvePolicy(policy);
    if (typeof resolved === "string") {
      setError(resolved);
      return;
    }
    setCreating(true);
    try {
      onCreated(await ankoraApi.createCalibrationSplit({
        receptor_id: receptor.trim(),
        binding_site_id: site.trim(),
        compounds,
        policy: resolved,
      }));
      setCompoundText("");
    } catch (reason: unknown) {
      setError(message(reason, "The calibration split could not be created."));
    } finally {
      setCreating(false);
    }
  }

  const ready = receptor.trim() && site.trim() && compoundText.trim() && !creating;

  return (
    <section className="redocking-setup calibration-setup" aria-label="Create calibration split">
      <h3>Stage 1 — Scaffold-grouped split and decoy bias audit</h3>
      <p>
        Grouping is by parent compound <em>and</em> Bemis&ndash;Murcko scaffold,
        so no parent and no scaffold can appear on both sides. The split is
        constructed before any comparison number exists, and creating it locks
        the Confirmation side.
      </p>
      <fieldset>
        <label>
          Receptor
          <input
            type="text"
            value={receptor}
            onChange={(event) => setReceptor(event.target.value)}
            placeholder="receptor id"
          />
        </label>
        <label>
          Binding site
          <input
            type="text"
            value={site}
            onChange={(event) => setSite(event.target.value)}
            placeholder="binding site id"
          />
        </label>
        <label>
          Compound rows (parent_id, canonical_smiles, active/inactive)
          <textarea
            value={compoundText}
            onChange={(event) => setCompoundText(event.target.value)}
            rows={6}
            spellCheck={false}
            placeholder={"CHEMBL1, c1ccccc1C(=O)O, active\nDECOY1, c1ccncc1CC, inactive"}
          />
        </label>
        <p className="field-note">
          CSV or TSV rows, or a JSON array of{" "}
          <code>{"{ parent_id, canonical_smiles, is_active }"}</code>. Enumerated
          microstates stay bound to their parent through <code>state_ids</code>;
          the ranking unit is always the parent compound.
        </p>
        <div className="calibration-policy-grid">
          <label>
            Calibration fraction
            <input
              type="number" step="0.05" min="0.4" max="0.8"
              value={policy.calibration_fraction}
              onChange={(event) => updatePolicy("calibration_fraction", event.target.value)}
            />
          </label>
          <label>
            Split seed
            <input
              type="number" step="1"
              value={policy.split_seed}
              onChange={(event) => updatePolicy("split_seed", event.target.value)}
            />
          </label>
          <label>
            Minimum confirmation actives
            <input
              type="number" step="1" min="1"
              value={policy.min_confirmation_actives}
              onChange={(event) => updatePolicy("min_confirmation_actives", event.target.value)}
            />
          </label>
          <label>
            BEDROC alpha
            <input
              type="number" step="1" min="0.0001"
              value={policy.bedroc_alpha}
              onChange={(event) => updatePolicy("bedroc_alpha", event.target.value)}
            />
          </label>
          <label>
            Bootstrap replicates
            <input
              type="number" step="100" min="100"
              value={policy.bootstrap_replicates}
              onChange={(event) => updatePolicy("bootstrap_replicates", event.target.value)}
            />
          </label>
        </div>
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
        <div>
          <button type="button" className="primary-button" disabled={!ready} onClick={create}>
            {creating ? "Freezing split…" : "Create split and lock Confirmation"}
          </button>
        </div>
      </fieldset>
    </section>
  );
}

function StageOneSplit({ run }: { run: CalibrationRunRecord }) {
  const { split } = run;
  const auditWarnings = (run.warnings ?? []).filter((warning) => AUDIT_WARNING_CODES.has(warning.code));
  return (
    <section className="calibration-stage" aria-label="Calibration split and bias audit">
      <header className="calibration-stage-heading">
        <div>
          <span className="eyebrow">Stage 1</span>
          <h3>Scaffold-grouped split</h3>
        </div>
        <span className={`calibration-stage-pill status-${run.status}`}>
          {STAGE_STATUS_LABEL[run.status]}
        </span>
      </header>

      {auditWarnings.length ? <AuditAlert warnings={auditWarnings} /> : null}

      <div className="calibration-split-columns">
        <dl className="ligand-plan">
          <div><dt>Side</dt><dd>Calibration</dd></div>
          <div><dt>Parents</dt><dd>{split.calibration_parent_ids.length}</dd></div>
          <div><dt>Scaffolds</dt><dd>{split.calibration_scaffolds.length}</dd></div>
          <div><dt>Actives</dt><dd>{split.calibration_active_count}</dd></div>
          <div><dt>Inactives</dt><dd>{split.calibration_inactive_count}</dd></div>
        </dl>
        <dl className="ligand-plan">
          <div><dt>Side</dt><dd>Locked Confirmation</dd></div>
          <div><dt>Parents</dt><dd>{split.confirmation_parent_ids.length}</dd></div>
          <div><dt>Scaffolds</dt><dd>{split.confirmation_scaffolds.length}</dd></div>
          <div><dt>Actives</dt><dd>{split.confirmation_active_count}</dd></div>
          <div><dt>Inactives</dt><dd>{split.confirmation_inactive_count}</dd></div>
        </dl>
      </div>
      <p className="field-note">
        Parent and scaffold sets are disjoint by construction: no parent compound
        and no Bemis&ndash;Murcko scaffold appears on both sides.
      </p>

      <div className="calibration-identity" role="status">
        <strong>Split identity SHA-256</strong>
        <code>{split.split_identity_sha256.slice(0, 12)}…</code>
      </div>
      <details className="calibration-details">
        <summary>Full split membership and identity</summary>
        <dl className="ligand-plan">
          <div><dt>Split ID</dt><dd><code>{split.split_id}</code></dd></div>
          <div>
            <dt>Identity</dt>
            <dd><code>{split.split_identity_sha256}</code></dd>
          </div>
          <div><dt>Grouping</dt><dd>{split.policy.grouping_strategy}</dd></div>
          <div>
            <dt>Policy</dt>
            <dd>
              fraction {formatScientificNumber(split.policy.calibration_fraction, 2)} ·
              seed {split.policy.split_seed} ·
              BEDROC alpha {formatScientificNumber(split.policy.bedroc_alpha, 0)} ·
              {" "}{split.policy.bootstrap_replicates} replicates ·
              {" "}{formatScientificNumber(split.policy.confidence_level * 100, 0)}% CI
            </dd>
          </div>
          <div>
            <dt>Calibration parents</dt>
            <dd><code>{split.calibration_parent_ids.join(", ")}</code></dd>
          </div>
          <div>
            <dt>Confirmation parents</dt>
            <dd><code>{split.confirmation_parent_ids.join(", ")}</code></dd>
          </div>
          <div>
            <dt>Calibration scaffolds</dt>
            <dd><code>{split.calibration_scaffolds.join(", ")}</code></dd>
          </div>
          <div>
            <dt>Confirmation scaffolds</dt>
            <dd><code>{split.confirmation_scaffolds.join(", ")}</code></dd>
          </div>
        </dl>
      </details>

      <div className="calibration-bias-audit">
        <div className="filter-heading"><span>Physicochemical decoy bias audit</span></div>
        <p className="field-note">
          {split.bias_audit.active_count} actives against{" "}
          {split.bias_audit.inactive_count} inactives. A decoy set separable on
          simple properties inflates enrichment without any binding-mode
          evidence, so this audit travels with the split and qualifies every
          number read from it.
        </p>
        <div className="docking-results-scroll" tabIndex={0} aria-label="Scrollable decoy bias audit">
          <table>
            <thead>
              <tr>
                <th>Property</th>
                <th>Active median (IQR)</th>
                <th>Inactive median (IQR)</th>
                <th>SMD</th>
                <th>KS stat</th>
                <th>KS p-value</th>
                <th>Flagged</th>
              </tr>
            </thead>
            <tbody>
              {split.bias_audit.metrics.map((metric) => (
                <tr
                  key={metric.property_name}
                  className={metric.flagged_bias ? "best-ranked" : ""}
                >
                  <td>{BIAS_PROPERTY_LABEL[metric.property_name] ?? metric.property_name}</td>
                  <td>
                    {formatScientificNumber(metric.active_median, 2)}
                    {" ("}{formatScientificNumber(metric.active_iqr, 2)}{")"}
                  </td>
                  <td>
                    {formatScientificNumber(metric.inactive_median, 2)}
                    {" ("}{formatScientificNumber(metric.inactive_iqr, 2)}{")"}
                  </td>
                  <td>{formatSignedScientificNumber(metric.standardized_mean_difference, 2)}</td>
                  <td>{formatScientificNumber(metric.ks_statistic, 3)}</td>
                  <td>{formatScientificNumber(metric.ks_p_value, 4)}</td>
                  <td>{metric.flagged_bias ? "Property bias" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="calibration-lock-notice" role="status">
        <strong>
          {run.confirmation_consumed
            ? "Confirmation consumed — permanently immutable"
            : "Confirmation is locked"}
        </strong>
        <small>
          {run.confirmation_consumed
            ? "The locked Confirmation split was opened once and cannot be evaluated again."
            : run.status === "calibration_selected"
              ? "The Calibration selection is sealed, so the single-use Confirmation evaluation in Stage 3 is now available."
              : "It cannot be unlocked until the Calibration selection is sealed in Stage 2."}
        </small>
        {split.confirmation_underpowered ? (
          <small>
            Confirmation actives ({split.confirmation_active_count}) are below the
            recorded minimum of {split.policy.min_confirmation_actives}: this
            split is underpowered and its verdict interval will be wide.
          </small>
        ) : null}
      </div>
    </section>
  );
}

function AuditAlert({ warnings }: { warnings: StructuredWarning[] }) {
  return (
    <div className="structure-error calibration-audit-alert" role="alert">
      <strong>Recorded calibration warnings</strong>
      <ul>
        {warnings.map((warning, index) => (
          <li key={`${warning.code}-${index}`}>
            <code>{warning.code}</code> {warning.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* --- Stage 2 -------------------------------------------------------------- */

function StageTwoSelection({ run, onSealed }: {
  run: CalibrationRunRecord;
  onSealed: (run: CalibrationRunRecord) => void;
}) {
  const [requestText, setRequestText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const selection = run.calibration_selection ?? null;

  async function submit() {
    setError(null);
    let request: CalibrationSelectRequest;
    try {
      request = parseSelectRequest(requestText);
    } catch (reason: unknown) {
      setError(message(reason, "The calibration selection request could not be read."));
      return;
    }
    setSubmitting(true);
    try {
      onSealed(await ankoraApi.selectCalibrationProtocol(run.calibration_id, request));
      setRequestText("");
    } catch (reason: unknown) {
      setError(message(reason, "The calibration selection could not be sealed."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="calibration-stage" aria-label="Calibration evaluation and selection">
      <header className="calibration-stage-heading">
        <div>
          <span className="eyebrow">Stage 2</span>
          <h3>Calibration evaluation and 1-SE parsimony selection</h3>
        </div>
        {selection ? (
          <span className="calibration-stage-pill status-calibration_selected">Selection sealed</span>
        ) : null}
      </header>

      {selection ? (
        <>
          <div className="calibration-selection-summary">
            <div className="calibration-highlight">
              <strong>Best point BEDROC</strong>
              <code>{selection.best_point_protocol_id}</code>
              <small>Highest point estimate on Calibration.</small>
            </div>
            <div className="calibration-highlight selected">
              <strong>Selected protocol</strong>
              <code>{selection.selected_protocol_id}</code>
              <small>
                {selection.selected_by_one_se_parsimony
                  ? "Chosen by the 1-SE parsimony rule, not by the highest point estimate."
                  : "The best point estimate is also the simplest protocol within 1 SE."}
              </small>
            </div>
          </div>
          {selection.selected_by_one_se_parsimony ? (
            <p className="calibration-parsimony-note" role="status">
              The <strong>1-SE parsimony rule retained the simpler protocol</strong>{" "}
              <code>{selection.selected_protocol_id}</code> over the noisier
              higher-scoring candidate <code>{selection.best_point_protocol_id}</code>.
              {selection.selected_protocol_id === selection.baseline_protocol_id
                ? " The rigid baseline was retained: a FlexRes or otherwise more complex candidate did not displace it on a difference inside the noise."
                : " A more complex candidate did not displace it on a difference inside the noise."}
            </p>
          ) : null}

          <EvaluationTable
            evaluations={selection.evaluations}
            bestProtocolId={selection.best_point_protocol_id}
            selectedProtocolId={selection.selected_protocol_id}
            baselineProtocolId={selection.baseline_protocol_id}
            label="Calibration protocol evaluations"
          />

          <DeltaTable
            deltas={selection.deltas_vs_best}
            label="Paired delta BEDROC against the best point protocol"
            referenceLabel={`vs best point (${selection.best_point_protocol_id})`}
          />
          <DeltaTable
            deltas={selection.deltas_vs_baseline}
            label="Paired delta BEDROC against the baseline protocol"
            referenceLabel={`vs baseline (${selection.baseline_protocol_id})`}
          />

          <div className="calibration-identity" role="status">
            <strong>Selection identity SHA-256 (sealed)</strong>
            <code>{selection.selection_identity_sha256.slice(0, 12)}…</code>
          </div>
          <details className="calibration-details">
            <summary>Full sealed selection identity</summary>
            <dl className="ligand-plan">
              <div>
                <dt>Sealed at</dt>
                <dd>{formatApplicationTimestamp(selection.selected_at)}</dd>
              </div>
              <div>
                <dt>Selection</dt>
                <dd><code>{selection.selection_identity_sha256}</code></dd>
              </div>
              <div>
                <dt>Split</dt>
                <dd><code>{selection.split_identity_sha256}</code></dd>
              </div>
            </dl>
          </details>
        </>
      ) : run.status === "split_locked" ? (
        <>
          <p className="field-note">
            Every candidate protocol is pre-declared and evaluated on the
            Calibration split only. Paste the recorded selection request —
            baseline protocol, candidate protocols, and the{" "}
            <code>ScoreObservation</code> records per protocol. Ankora evaluates
            and seals the choice; it does not pick candidates for you.
          </p>
          <label className="calibration-json-label">
            Calibration selection request (JSON)
            <textarea
              value={requestText}
              onChange={(event) => setRequestText(event.target.value)}
              rows={8}
              spellCheck={false}
              placeholder={
                "{\n  \"baseline_protocol_id\": \"rigid-vina\",\n"
                + "  \"candidates\": [ … ],\n"
                + "  \"observations_by_protocol\": { \"rigid-vina\": [ … ] }\n}"
              }
            />
          </label>
          {error ? <div className="structure-error" role="alert">{error}</div> : null}
          <button
            type="button"
            className="primary-button"
            disabled={!requestText.trim() || submitting}
            onClick={submit}
          >
            {submitting ? "Sealing calibration selection…" : "Evaluate Calibration and seal selection"}
          </button>
        </>
      ) : (
        <p className="field-note">No sealed calibration selection is recorded for this run.</p>
      )}
    </section>
  );
}

function EvaluationTable({ evaluations, bestProtocolId, selectedProtocolId, baselineProtocolId, label }: {
  evaluations: ProtocolEvaluationSummary[];
  bestProtocolId: string | null;
  selectedProtocolId: string | null;
  baselineProtocolId: string | null;
  label: string;
}) {
  const alpha = evaluations[0]?.metrics.bedroc_alpha ?? 20;
  const topFraction = evaluations[0]?.metrics.top_fraction ?? 0.01;
  return (
    <div className="docking-results-scroll" tabIndex={0} aria-label={label}>
      <table>
        <caption className="visually-quiet">{label}</caption>
        <thead>
          <tr>
            <th>Protocol</th>
            <th>{bedrocLabel(alpha)} (95% CI)</th>
            <th>Bootstrap SE</th>
            <th>{enrichmentLabel(topFraction)}</th>
            <th>ROC-AUC</th>
            <th>PR-AUC</th>
            <th>Scored actives / failed</th>
            <th>Scored inactives / failed</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {evaluations.map((item) => (
            <tr
              key={item.protocol_id}
              className={item.protocol_id === selectedProtocolId ? "best-ranked" : ""}
            >
              <td>
                <strong>{item.label}</strong>
                <br /><code>{item.protocol_id}</code>
              </td>
              <td>
                {formatScientificNumber(item.metrics.bedroc, 4)}
                {" ["}{formatScientificNumber(item.bedroc_ci_lower, 4)}
                {", "}{formatScientificNumber(item.bedroc_ci_upper, 4)}{"]"}
              </td>
              <td>{formatScientificNumber(item.bedroc_bootstrap_se, 4)}</td>
              <td>
                {formatScientificNumber(item.metrics.enrichment_factor, 2)}
                {item.ef_small_sample_caution ? (
                  <span className="calibration-caution-badge" title="Small-sample caution">
                    small-sample caution
                  </span>
                ) : null}
              </td>
              <td>{formatScientificNumber(item.metrics.roc_auc, 4)}</td>
              <td>{formatScientificNumber(item.metrics.pr_auc, 4)}</td>
              <td>
                {item.failure_census.scored_active_count} / {item.failure_census.failed_active_count}
              </td>
              <td>
                {item.failure_census.scored_inactive_count} / {item.failure_census.failed_inactive_count}
              </td>
              <td>
                {[
                  item.protocol_id === selectedProtocolId ? "Selected" : null,
                  item.protocol_id === bestProtocolId ? "Best point" : null,
                  item.protocol_id === baselineProtocolId ? "Baseline" : null,
                ].filter(Boolean).join(" · ") || "Candidate"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeltaTable({ deltas, label, referenceLabel }: {
  deltas: PairedBootstrapDelta[];
  label: string;
  referenceLabel: string;
}) {
  return (
    <div className="calibration-delta-block">
      <div className="filter-heading"><span>{referenceLabel}</span></div>
      <p className="field-note">
        Paired parent bootstrap, resampled over parent compounds. The sign
        convention is <code>candidate − reference</code>.
      </p>
      <div className="docking-results-scroll" tabIndex={0} aria-label={label}>
        <table>
          <caption className="visually-quiet">{label}</caption>
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Reference</th>
              <th>Δ {bedrocLabel(deltas[0]?.bedroc_alpha ?? 20)}</th>
              <th>Bootstrap SE</th>
              <th>95% CI</th>
              <th>Separates from zero</th>
              <th>Within 1 SE</th>
            </tr>
          </thead>
          <tbody>
            {deltas.map((delta) => (
              <tr key={`${delta.candidate_protocol_id}-${delta.reference_protocol_id}`}>
                <td><code>{delta.candidate_protocol_id}</code></td>
                <td><code>{delta.reference_protocol_id}</code></td>
                <td>{formatSignedScientificNumber(delta.point_delta, 4)}</td>
                <td>{formatScientificNumber(delta.bootstrap_se, 4)}</td>
                <td>
                  {"["}{formatSignedScientificNumber(delta.ci_lower, 4)}
                  {", "}{formatSignedScientificNumber(delta.ci_upper, 4)}{"]"}
                </td>
                <td>{delta.excludes_zero_positively ? "Excludes zero positively" : "Includes zero"}</td>
                <td>{delta.within_one_se_of_reference ? "Within 1 SE" : "Outside 1 SE"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* --- Stage 3 -------------------------------------------------------------- */

function StageThreeConfirmation({ run, onEvaluated }: {
  run: CalibrationRunRecord;
  onEvaluated: (run: CalibrationRunRecord) => void;
}) {
  const [requestText, setRequestText] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const confirmation = run.confirmation_evaluation ?? null;
  const unlockable = run.status === "calibration_selected" && !run.confirmation_consumed;

  async function submit() {
    setError(null);
    let request: CalibrationConfirmRequest;
    try {
      request = parseConfirmRequest(requestText);
    } catch (reason: unknown) {
      setError(message(reason, "The confirmation observations could not be read."));
      return;
    }
    setSubmitting(true);
    try {
      onEvaluated(await ankoraApi.confirmCalibration(run.calibration_id, request));
      setRequestText("");
      setAcknowledged(false);
    } catch (reason: unknown) {
      setError(message(reason, "The locked confirmation split could not be evaluated."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="calibration-stage" aria-label="Locked confirmation evaluation">
      <header className="calibration-stage-heading">
        <div>
          <span className="eyebrow">Stage 3</span>
          <h3>Single-use locked Confirmation</h3>
        </div>
        {run.confirmation_consumed ? (
          <span className="calibration-stage-pill status-confirmation_completed">
            Confirmation consumed (immutable)
          </span>
        ) : (
          <span className="calibration-stage-pill status-split_locked">
            {unlockable ? "Unlock available · single use" : "Locked"}
          </span>
        )}
      </header>

      {confirmation ? (
        <ConfirmationVerdictView run={run} />
      ) : unlockable ? (
        <>
          <div className="calibration-single-use-warning" role="alert">
            <strong>Confirmation is single-use and permanently consumed once evaluated.</strong>
            <small>
              Evaluating it records one verdict against the sealed selection,
              including a null verdict, and no second evaluation of this split is
              possible afterwards.
            </small>
          </div>
          <label className="calibration-json-label">
            Confirmation observations (JSON)
            <textarea
              value={requestText}
              onChange={(event) => { setRequestText(event.target.value); setAcknowledged(false); }}
              rows={6}
              spellCheck={false}
              placeholder={"{\n  \"observations_by_protocol\": { \"rigid-vina\": [ … ] }\n}"}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>
              <strong>I understand this consumes the locked Confirmation split permanently.</strong>
              <small>The verdict is recorded and published whichever way it falls.</small>
            </span>
          </label>
          {error ? <div className="structure-error" role="alert">{error}</div> : null}
          <button
            type="button"
            className="primary-button"
            disabled={!acknowledged || !requestText.trim() || submitting}
            onClick={submit}
          >
            {submitting
              ? "Evaluating locked Confirmation…"
              : "Unlock and evaluate Confirmation (single use)"}
          </button>
        </>
      ) : (
        <p className="field-note">
          Stage 3 stays locked until the Calibration selection is sealed in
          Stage 2. The Confirmation split cannot be read before a protocol has
          been chosen on Calibration alone.
        </p>
      )}
    </section>
  );
}

function ConfirmationVerdictView({ run }: { run: CalibrationRunRecord }) {
  const confirmation = run.confirmation_evaluation;
  if (!confirmation) return null;
  const delta = confirmation.paired_delta_vs_baseline;
  const audit = confirmation.all_candidate_audit_evaluations ?? [];
  const nullVerdict = confirmation.verdict === "insufficient_evidence_to_prefer_over_baseline";
  return (
    <>
      <div className="calibration-consumed-badge" role="status">
        <strong>Confirmation consumed — immutable</strong>
        <small>
          This locked split was opened once, on{" "}
          {formatApplicationTimestamp(confirmation.evaluated_at)}. No further
          Confirmation evaluation of this run is possible.
        </small>
      </div>

      <div
        className={nullVerdict ? "calibration-verdict null-result" : "calibration-verdict"}
        role="status"
        aria-label="Confirmation verdict"
      >
        <span className="eyebrow">{VERDICT_LABEL[confirmation.verdict] ?? confirmation.verdict}</span>
        {/* Verbatim recorded text: ADR-031 fixes the null phrase exactly. */}
        <p className="calibration-verdict-text">{confirmation.verdict_text}</p>
        <small>
          Recorded verdict code <code>{confirmation.verdict}</code>, comparing{" "}
          <code>{confirmation.selected_protocol_id}</code> against baseline{" "}
          <code>{confirmation.baseline_protocol_id}</code>.
        </small>
      </div>

      <dl className="ligand-plan calibration-verdict-delta">
        <div>
          <dt>Δ {bedrocLabel(delta.bedroc_alpha)}</dt>
          <dd>{formatSignedScientificNumber(delta.point_delta, 4)}</dd>
        </div>
        <div>
          <dt>Bootstrap SE</dt>
          <dd>{formatScientificNumber(delta.bootstrap_se, 4)}</dd>
        </div>
        <div>
          <dt>{formatScientificNumber(delta.confidence_level * 100, 0)}% CI</dt>
          <dd>
            {"["}{formatSignedScientificNumber(delta.ci_lower, 4)}
            {", "}{formatSignedScientificNumber(delta.ci_upper, 4)}{"]"}
          </dd>
        </div>
        <div>
          <dt>Separates from zero</dt>
          <dd>
            {delta.excludes_zero_positively
              ? "Excludes zero positively"
              : "Includes zero"}
          </dd>
        </div>
        <div>
          <dt>Resampling</dt>
          <dd>
            {delta.replicates} paired parent replicates · seed {delta.bootstrap_seed}
          </dd>
        </div>
      </dl>

      <EvaluationTable
        evaluations={[confirmation.selected_evaluation, confirmation.baseline_evaluation]}
        bestProtocolId={null}
        selectedProtocolId={confirmation.selected_protocol_id}
        baselineProtocolId={confirmation.baseline_protocol_id}
        label="Confirmation evaluations of the selected and baseline protocols"
      />

      {audit.length ? (
        <>
          <div className="filter-heading"><span>All-candidate Confirmation audit</span></div>
          <p className="field-note">
            Recorded for transparency only. These rows did not and cannot change
            the selection, which was sealed on Calibration before this split was
            opened.
          </p>
          <EvaluationTable
            evaluations={audit}
            bestProtocolId={null}
            selectedProtocolId={confirmation.selected_protocol_id}
            baselineProtocolId={confirmation.baseline_protocol_id}
            label="All-candidate confirmation audit evaluations"
          />
        </>
      ) : null}

      <details className="calibration-details">
        <summary>Full sealed confirmation identity</summary>
        <dl className="ligand-plan">
          <div>
            <dt>Confirmation</dt>
            <dd><code>{confirmation.confirmation_identity_sha256}</code></dd>
          </div>
          <div>
            <dt>Selection</dt>
            <dd><code>{confirmation.selection_identity_sha256}</code></dd>
          </div>
          <div>
            <dt>Split</dt>
            <dd><code>{confirmation.split_identity_sha256}</code></dd>
          </div>
        </dl>
      </details>
    </>
  );
}

/* --- Parsing and labels --------------------------------------------------- */

function bedrocLabel(alpha: number): string {
  return `BEDROC_${formatScientificNumber(alpha, { maximumFractionDigits: 2 })}`;
}

function enrichmentLabel(topFraction: number): string {
  return `EF${formatScientificNumber(topFraction * 100, { maximumFractionDigits: 2 })}%`;
}

const ACTIVE_LABELS = new Set(["active", "actives", "1", "true", "yes", "y"]);
const INACTIVE_LABELS = new Set(["inactive", "inactives", "decoy", "0", "false", "no", "n"]);

/**
 * Read the offered parents from CSV/TSV rows or a structured JSON array.
 *
 * A row whose class label is not one of the recorded vocabularies is rejected
 * rather than defaulted: silently filing an ambiguous row as a decoy would
 * change the denominator of every enrichment number computed afterwards.
 */
function parseCompounds(text: string): CalibrationCompoundInput[] {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("At least one compound row is required.");

  const compounds: CalibrationCompoundInput[] = trimmed.startsWith("[")
    ? parseCompoundJson(trimmed)
    : parseCompoundRows(trimmed);

  if (compounds.length < 4) {
    throw new Error("A grouped split needs at least four parent compounds.");
  }
  const identifiers = new Set(compounds.map((item) => item.parent_id));
  if (identifiers.size !== compounds.length) {
    throw new Error("Parent compound identifiers must be unique.");
  }
  if (!compounds.some((item) => item.is_active)) {
    throw new Error("At least one parent compound must be labelled active.");
  }
  if (!compounds.some((item) => !item.is_active)) {
    throw new Error("At least one parent compound must be labelled inactive.");
  }
  return compounds;
}

function parseCompoundJson(text: string): CalibrationCompoundInput[] {
  const parsed: unknown = JSON.parse(text);
  if (!Array.isArray(parsed)) throw new Error("A JSON compound set must be an array.");
  return parsed.map((item, index) => {
    const row = item as Partial<CalibrationCompoundInput>;
    if (!row || typeof row.parent_id !== "string" || typeof row.canonical_smiles !== "string") {
      throw new Error(`Row ${index + 1} needs a parent_id and a canonical_smiles.`);
    }
    if (typeof row.is_active !== "boolean") {
      throw new Error(`Row ${index + 1} needs an explicit boolean is_active.`);
    }
    return {
      parent_id: row.parent_id.trim(),
      canonical_smiles: row.canonical_smiles.trim(),
      is_active: row.is_active,
      ...(row.state_ids?.length ? { state_ids: row.state_ids } : {}),
    };
  });
}

function parseCompoundRows(text: string): CalibrationCompoundInput[] {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const rows = lines[0]?.toLowerCase().startsWith("parent_id") ? lines.slice(1) : lines;
  return rows.map((line, index) => {
    const cells = line.split(/[\t,;]/).map((cell) => cell.trim());
    if (cells.length < 3) {
      throw new Error(`Row ${index + 1} needs parent_id, canonical_smiles and a class label.`);
    }
    const [parentId, smiles, label, ...states] = cells;
    const normalized = label.toLowerCase();
    if (!ACTIVE_LABELS.has(normalized) && !INACTIVE_LABELS.has(normalized)) {
      throw new Error(`Row ${index + 1} has an unrecognized class label "${label}".`);
    }
    if (!parentId || !smiles) {
      throw new Error(`Row ${index + 1} needs a parent_id and a canonical_smiles.`);
    }
    const stateIds = states.filter(Boolean);
    return {
      parent_id: parentId,
      canonical_smiles: smiles,
      is_active: ACTIVE_LABELS.has(normalized),
      ...(stateIds.length ? { state_ids: stateIds } : {}),
    };
  });
}

function resolvePolicy(fields: PolicyFields): CalibrationSplitPolicy | string {
  const fraction = Number(fields.calibration_fraction);
  const seed = Number(fields.split_seed);
  const minimumActives = Number(fields.min_confirmation_actives);
  const alpha = Number(fields.bedroc_alpha);
  const replicates = Number(fields.bootstrap_replicates);

  if (!(fraction >= 0.4 && fraction <= 0.8)) {
    return "The calibration fraction must be between 0.4 and 0.8.";
  }
  if (!Number.isInteger(seed)) return "The split seed must be a whole number.";
  if (!Number.isInteger(minimumActives) || minimumActives < 1) {
    return "The minimum confirmation actives must be a whole number of at least 1.";
  }
  if (!(alpha > 0)) return "The BEDROC alpha must be greater than 0.";
  if (!Number.isInteger(replicates) || replicates < 100) {
    return "The bootstrap replicates must be a whole number of at least 100.";
  }
  return {
    ...DEFAULT_POLICY,
    calibration_fraction: fraction,
    split_seed: seed,
    min_confirmation_actives: minimumActives,
    bedroc_alpha: alpha,
    bootstrap_replicates: replicates,
  };
}

function parseSelectRequest(text: string): CalibrationSelectRequest {
  const parsed = JSON.parse(text) as Partial<CalibrationSelectRequest>;
  if (!parsed || typeof parsed.baseline_protocol_id !== "string" || !parsed.baseline_protocol_id) {
    throw new Error("A calibration selection needs a baseline_protocol_id.");
  }
  if (!Array.isArray(parsed.candidates) || parsed.candidates.length === 0) {
    throw new Error("A calibration selection needs its pre-declared candidates.");
  }
  const observations = observationMap(parsed.observations_by_protocol);
  return {
    baseline_protocol_id: parsed.baseline_protocol_id,
    candidates: parsed.candidates,
    observations_by_protocol: observations,
  };
}

function parseConfirmRequest(text: string): CalibrationConfirmRequest {
  const parsed = JSON.parse(text) as Record<string, unknown>;
  // Accepted either as the documented request envelope or as the bare map, so
  // the exact recorded observations can be pasted without being reshaped.
  const candidate = "observations_by_protocol" in (parsed ?? {})
    ? parsed.observations_by_protocol
    : parsed;
  return { observations_by_protocol: observationMap(candidate) };
}

function observationMap(value: unknown): Record<string, ScoreObservation[]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("observations_by_protocol must map each protocol to its observations.");
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) {
    throw new Error("observations_by_protocol must map each protocol to its observations.");
  }
  for (const [protocolId, observations] of entries) {
    if (!Array.isArray(observations) || observations.length === 0) {
      throw new Error(`Protocol ${protocolId} carries no score observations.`);
    }
  }
  return Object.fromEntries(entries) as Record<string, ScoreObservation[]>;
}

function message(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
