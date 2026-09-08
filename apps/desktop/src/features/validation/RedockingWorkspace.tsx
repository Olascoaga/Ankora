import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type { RedockingRunRecord } from "../../types/api";
import { formatScientificNumber } from "../../utils/format";

/**
 * Redocking validation (M7).
 *
 * The question is narrow and the answer has two halves, because on this
 * project's own reference case they disagreed: AutoDock4 recovered the 7AQF/RV2
 * pose to 0.490 Å and then ranked a 3.139 Å pose above it.
 *
 * So this workspace never shows one pass/fail. It shows whether the search
 * *found* the crystallographic pose and whether the scoring function *chose*
 * it, and says which is which. A green tick over "validated" would be the most
 * misleading thing it could display.
 */

interface RedockingWorkspaceProps {
  modeSwitch?: ReactNode;
}

const OUTCOME_LABEL: Record<string, string> = {
  recovered_and_ranked: "Recovered and ranked first",
  recovered_but_misranked: "Recovered, but ranked below another pose",
  not_recovered: "Not recovered",
};

export function RedockingWorkspace({ modeSwitch }: RedockingWorkspaceProps) {
  const [runs, setRuns] = useState<RedockingRunRecord[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    void ankoraApi.listRedockingValidations()
      .then((next) => {
        if (disposed) return;
        setRuns(next);
        setSelectedId((current) => current ?? next[0]?.validation_id ?? null);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(reason instanceof Error ? reason.message : "Validations could not be read.");
        }
      });
    return () => { disposed = true; };
  }, []);

  const selected = runs?.find((run) => run.validation_id === selectedId) ?? null;

  return (
    <>
      <section className="workspace docking-workspace" aria-label="Redocking validation workspace">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">07 / Validation</span>
            <h2>Redocking against a known pose</h2>
          </div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">M7 · Redocking</span>
          </div>
        </div>
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
        {runs === null ? (
          <div className="operation-progress" role="progressbar" aria-label="Reading validations">
            <span /><p>Reading recorded validations</p>
          </div>
        ) : runs.length === 0 ? (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message">
              <div className="molecule-glyph">⌾</div>
              <h3>No redocking validation recorded yet</h3>
              <p>
                A validation measures a docking result you already have against a
                crystallographic pose Ankora preserved. It docks nothing itself.
              </p>
            </div>
          </div>
        ) : selected ? (
          <RedockingResults run={selected} />
        ) : null}
      </section>
      <aside className="inspector docking-inspector" aria-label="Redocking validation inspector">
        <div className="inspector-heading">
          <span className="section-label">Validation</span>
          <h2>What a pass means</h2>
          <p className="inspector-subtitle">
            That this configuration recovered this reference pose, under the stated
            threshold. Nothing more.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>Two verdicts, not one</span></div>
          <p className="field-note">
            <strong>Sampling</strong> asks whether the search found the crystallographic
            pose at all. <strong>Ranking</strong> asks whether the scoring function put it
            first. They can disagree, and on this project&apos;s own reference case they
            did — the pose was recovered to 0.490 Å and then ranked second. A single
            pass or fail would have had to misreport one of them.
          </p>
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>How the RMSD is measured</span></div>
          <p className="field-note">
            Symmetry-aware, heavy atoms only, and computed <strong>in place</strong> — the
            pose is never superimposed on the reference first. Superimposing asks whether
            the shapes match, which a completely wrong binding mode passes easily: one
            pose here sits 10.7 Å from the crystal and measures 1.3 Å once aligned.
          </p>
        </section>
        {runs && runs.length > 0 ? (
          <section className="receptor-section">
            <div className="filter-heading"><span>Recorded validations</span></div>
            <div className="campaign-history-list" role="group" aria-label="Recorded validations">
              {runs.map((run) => (
                <button
                  key={run.validation_id}
                  type="button"
                  className={run.validation_id === selectedId ? "campaign-history-entry selected" : "campaign-history-entry"}
                  aria-current={run.validation_id === selectedId ? "true" : undefined}
                  onClick={() => setSelectedId(run.validation_id)}
                >
                  <span className="campaign-history-when">
                    <b>{run.engine} {run.engine_version}</b>
                    <small>
                      {run.reference_case ?? "reference pose"}
                      {" · "}
                      {OUTCOME_LABEL[run.metrics.outcome] ?? run.metrics.outcome}
                    </small>
                  </span>
                  <span className="campaign-history-best">
                    <b>{formatScientificNumber(run.metrics.top1_rmsd_angstrom, 2)}</b>
                    <small>Top-1 RMSD Å</small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : null}
      </aside>
    </>
  );
}

function RedockingResults({ run }: { run: RedockingRunRecord }) {
  const { metrics } = run;
  return (
    <section className="docking-results library-docking-results" aria-label="Redocking validation results">
      <div className="docking-results-heading">
        <div>
          <span className="eyebrow">{run.reference_case ?? "Reference pose"}</span>
          <h3>{run.engine} {run.engine_version}</h3>
        </div>
        <p>
          {OUTCOME_LABEL[metrics.outcome] ?? metrics.outcome}, at a{" "}
          {formatScientificNumber(metrics.threshold_angstrom, 1)} Å threshold. RMSD is symmetry-aware,
          heavy-atom, and measured in place against the preserved crystallographic pose.
        </p>
      </div>

      <div className="redocking-verdicts">
        <Verdict
          label="Sampling"
          question="Did the search find the crystallographic pose?"
          passed={metrics.sampling_success}
        />
        <Verdict
          label="Ranking"
          question="Did the scoring function put it first?"
          passed={metrics.ranking_success}
        />
      </div>

      <dl className="ligand-plan redocking-metrics">
        <div><dt>Top-1</dt><dd>{formatScientificNumber(metrics.top1_rmsd_angstrom, 3)} Å</dd></div>
        <div><dt>Best of top 5</dt><dd>{formatScientificNumber(metrics.best_top5_rmsd_angstrom, 3)} Å</dd></div>
        <div><dt>Best overall</dt><dd>{formatScientificNumber(metrics.best_overall_rmsd_angstrom, 3)} Å</dd></div>
        <div>
          <dt>First recovering</dt>
          <dd>
            {metrics.first_recovering_rank === null
              ? "No pose reached the threshold"
              : `Rank ${metrics.first_recovering_rank} of ${metrics.pose_count}`}
          </dd>
        </div>
        <div><dt>Recovered</dt><dd>{metrics.recovered_pose_count} of {metrics.pose_count} poses</dd></div>
        <div>
          <dt>Repeatable</dt>
          <dd>{run.bitwise_reproducible ? "Bit-identical on a repeat" : "Not from its seed"}</dd>
        </div>
      </dl>

      <div className="docking-results-scroll" tabIndex={0} aria-label="Scrollable pose RMSD table">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Run</th>
              <th>Binding energy (kcal/mol)</th>
              <th>RMSD (Å)</th>
              <th>Recovered</th>
            </tr>
          </thead>
          <tbody>
            {run.poses.map((pose) => (
              <tr key={pose.rank} className={pose.recovered ? "best-ranked" : ""}>
                <td>{pose.rank}</td>
                <td>Run {pose.run}</td>
                <td>{formatScientificNumber(pose.binding_energy_kcal_mol, 2)}</td>
                <td>{formatScientificNumber(pose.rmsd_angstrom, 3)}</td>
                <td>{pose.recovered ? "Within threshold" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Verdict({ label, question, passed }: {
  label: string;
  question: string;
  passed: boolean;
}) {
  return (
    <div className={passed ? "redocking-verdict passed" : "redocking-verdict failed"}>
      <strong>{label}</strong>
      {/* The word carries the verdict; the colour only reinforces it. */}
      <b>{passed ? "Passed" : "Failed"}</b>
      <small>{question}</small>
    </div>
  );
}
