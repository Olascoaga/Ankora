import { useEffect, useMemo, useState } from "react";

import { ankoraApi } from "../../api/client";
import type { DiagnosticStatus, PoseQualityRecord } from "../../types/api";
import {
  formatApplicationDateTime,
  formatScientificNumber,
  formatSignedScientificNumber,
} from "../../utils/format";

interface PoseQualitySectionProps {
  catalogId: string;
  ligandId: string;
  poseArtifactId: string;
}

const STATUS_LABEL: Record<DiagnosticStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  not_applicable: "Not applicable",
  not_evaluable: "Not evaluable",
};

/**
 * Coupled physical plausibility & dual MMFF94s conformational strain (M3).
 *
 * Strictly opt-in and read-only on docking outputs (`mutated_original_pose:
 * false`): Ankora reports every individual PoseBusters, FlexRes geometry, and
 * MMFF94s strain check across four honest states rather than collapsing to a
 * single pass/fail tick or silently discarding poses.
 */
export function PoseQualitySection({
  catalogId,
  ligandId,
  poseArtifactId,
}: PoseQualitySectionProps) {
  const [records, setRecords] = useState<PoseQualityRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [includeStrain, setIncludeStrain] = useState(true);
  const [conformerBudget, setConformerBudget] = useState("50");
  const [conformerSeed, setConformerSeed] = useState("20261119");
  const [strainThreshold, setStrainThreshold] = useState("10");
  const [statusFilter, setStatusFilter] = useState<"" | DiagnosticStatus>("");

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    setRecords([]);
    setSelectedId(null);
    void ankoraApi
      .listPoseQualityAssessments(catalogId, ligandId, poseArtifactId)
      .then((next) => {
        if (disposed) return;
        setRecords((current) => (next.length ? next : current));
        setSelectedId((current) => current ?? next[0]?.assessment_id ?? null);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Prior pose quality assessments could not be read.",
          );
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [catalogId, ligandId, poseArtifactId]);

  const activeRecord =
    records.find((item) => item.assessment_id === selectedId) ?? records[0] ?? null;

  const filteredChecks = useMemo(() => {
    const checks = activeRecord?.assessment.checks ?? [];
    if (!statusFilter) return checks;
    return checks.filter((item) => item.status === statusFilter);
  }, [activeRecord, statusFilter]);

  async function runAssessment() {
    setError(null);
    const budget = Number(conformerBudget);
    const seed = Number(conformerSeed);
    const threshold = Number(strainThreshold);
    if (includeStrain) {
      if (!Number.isInteger(budget) || budget < 1 || budget > 200) {
        setError("Conformer budget must be a whole number between 1 and 200.");
        return;
      }
      if (!Number.isInteger(seed) || seed < 1) {
        setError("Conformer seed must be a positive whole number.");
        return;
      }
      if (!Number.isFinite(threshold) || threshold <= 0) {
        setError("Advisory strain threshold must be greater than 0 kcal/mol.");
        return;
      }
    }
    setRunning(true);
    try {
      const created = await ankoraApi.assessPoseQuality(
        catalogId,
        ligandId,
        poseArtifactId,
        {
          include_strain: includeStrain,
          ...(includeStrain
            ? {
                conformer_budget: budget,
                conformer_seed: seed,
                strain_flag_threshold_kcal_mol: threshold,
              }
            : {}),
        },
      );
      setRecords((current) => [
        created,
        ...current.filter((item) => item.assessment_id !== created.assessment_id),
      ]);
      setSelectedId(created.assessment_id);
      setStatusFilter("");
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The pose quality assessment could not be completed.",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <section
      className="pose-quality-panel"
      aria-label="Pose physical plausibility (PoseBusters and MMFF94s)"
    >
      <div className="pose-quality-header">
        <div>
          <strong>Physical plausibility &amp; conformational strain (M3)</strong>
          <p className="field-note">
            Evaluates PoseBusters <code>dock</code> checks against the exact coupled
            receptor complex (<code>receptor_rigid + moved FlexRes</code> when flexible)
            plus optional dual <code>MMFF94s</code> strain. Read-only annotation: poses
            are never silently deleted and docking scores are never altered.
          </p>
        </div>
        {records.length > 1 ? (
          <label>
            Recorded assessment
            <select
              value={activeRecord?.assessment_id ?? ""}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {records.map((item) => (
                <option key={item.assessment_id} value={item.assessment_id}>
                  {formatApplicationDateTime(item.created_at)} · PoseBusters{" "}
                  {item.posebusters_version} ({STATUS_LABEL[item.assessment.overall_status]})
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <div className="pose-quality-controls">
        <label className="pose-quality-checkbox">
          <input
            type="checkbox"
            checked={includeStrain}
            disabled={running}
            onChange={(event) => setIncludeStrain(event.target.checked)}
          />
          <span>Include dual MMFF94s conformational strain</span>
        </label>
        {includeStrain ? (
          <div className="pose-quality-params">
            <label>
              ETKDGv3 conformers (N)
              <input
                type="number"
                min="1"
                max="200"
                step="1"
                value={conformerBudget}
                disabled={running}
                onChange={(event) => setConformerBudget(event.target.value)}
              />
            </label>
            <label>
              Conformer seed
              <input
                type="number"
                min="1"
                step="1"
                value={conformerSeed}
                disabled={running}
                onChange={(event) => setConformerSeed(event.target.value)}
              />
            </label>
            <label>
              Strain flag (kcal/mol)
              <input
                type="number"
                min="0.5"
                step="0.5"
                value={strainThreshold}
                disabled={running}
                onChange={(event) => setStrainThreshold(event.target.value)}
              />
            </label>
          </div>
        ) : null}
        <div>
          <button
            type="button"
            className="primary-button"
            disabled={running}
            onClick={() => void runAssessment()}
          >
            {running
              ? "Assessing pose quality…"
              : "Assess pose quality (PoseBusters + MMFF94s)"}
          </button>
        </div>
      </div>

      {loading ? <p className="field-note">Reading recorded quality assessments…</p> : null}
      {error ? (
        <div className="structure-error" role="alert">
          {error}
        </div>
      ) : null}

      {activeRecord ? (
        <div className="pose-quality-result" role="region" aria-label="Pose quality results">
          <div className="pose-quality-summary">
            <span
              className={`pose-quality-pill status-${activeRecord.assessment.overall_status}`}
              role="status"
            >
              Overall: {STATUS_LABEL[activeRecord.assessment.overall_status]}
            </span>
            <span className="pose-quality-counts">
              {activeRecord.passed_count} pass · {activeRecord.failed_count} fail ·{" "}
              {activeRecord.not_applicable_count} N/A ·{" "}
              {activeRecord.not_evaluable_count} not evaluable
            </span>
            <span className="pose-quality-tool">
              PoseBusters {activeRecord.posebusters_version}
            </span>
          </div>

          <p className="field-note">
            Read-only annotation (<code>mutated_original_pose: false</code>). Failed or
            non-evaluable checks warn and retain the pose; Ankora never silently deletes
            poses or modifies docking scores.
          </p>

          {activeRecord.materialized_coupled_receptor_sha256 ? (
            <div className="pose-quality-coupled-note" role="status">
              <strong>Evaluated on coupled FlexRes complex (E8):</strong> receptor PDB
              SHA-256{" "}
              <code>{activeRecord.materialized_coupled_receptor_sha256.slice(0, 12)}…</code>{" "}
              (includes moved side-chain coordinates and covalent geometry audit).
            </div>
          ) : null}

          {activeRecord.warnings.length > 0 ? (
            <div className="structure-error pose-quality-warnings" role="alert">
              <strong>Recorded quality warnings</strong>
              <ul>
                {activeRecord.warnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`}>
                    <code>{warning.code}</code> {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {activeRecord.assessment.strain ? (
            <div
              className="pose-quality-strain-card"
              role="region"
              aria-label="Dual MMFF94s conformational strain"
            >
              <strong>Dual MMFF94s conformational strain (diagnostic flag only)</strong>
              <dl className="pose-quality-strain-grid">
                <div>
                  <dt>ΔE_ref</dt>
                  <dd>
                    {formatSignedScientificNumber(
                      activeRecord.assessment.strain.delta_e_ref_kcal_mol,
                      2,
                    )}{" "}
                    kcal/mol
                  </dd>
                </div>
                <div>
                  <dt>Pose relaxed (heavy tethered)</dt>
                  <dd>
                    {formatScientificNumber(
                      activeRecord.assessment.strain.pose_restrained_energy_kcal_mol,
                      2,
                    )}{" "}
                    kcal/mol
                  </dd>
                </div>
                <div>
                  <dt>Lowest free conformer</dt>
                  <dd>
                    {formatScientificNumber(
                      activeRecord.assessment.strain.lowest_free_conformer_energy_kcal_mol,
                      2,
                    )}{" "}
                    kcal/mol
                  </dd>
                </div>
                <div>
                  <dt>Reference ensemble</dt>
                  <dd>
                    N = {activeRecord.assessment.strain.conformer_budget} · seed{" "}
                    {activeRecord.assessment.strain.conformer_seed}
                  </dd>
                </div>
              </dl>
              <p className="field-note">
                Diagnostic flag only — finite conformer budget does not claim a global
                minimum, and strain is never added to or subtracted from any docking
                score. Hydrogen policy:{" "}
                <code>{activeRecord.assessment.strain.hydrogen_policy}</code>.
              </p>
            </div>
          ) : null}

          <div className="pose-quality-filter-bar">
            <label>
              Filter checks by status
              <select
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(event.target.value as "" | DiagnosticStatus)
                }
              >
                <option value="">
                  All checks ({activeRecord.assessment.checks.length})
                </option>
                <option value="fail">Fail ({activeRecord.failed_count})</option>
                <option value="not_evaluable">
                  Not evaluable ({activeRecord.not_evaluable_count})
                </option>
                <option value="pass">Pass ({activeRecord.passed_count})</option>
                <option value="not_applicable">
                  Not applicable ({activeRecord.not_applicable_count})
                </option>
              </select>
            </label>
          </div>

          <div className="pose-quality-table-scroll">
            <table aria-label="Pose quality diagnostic checks">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Tool</th>
                  <th>Status</th>
                  <th>Value</th>
                  <th>Threshold</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {filteredChecks.map((check) => (
                  <tr key={check.check_id} className={`status-row-${check.status}`}>
                    <td>
                      <code>{check.check_id}</code>
                    </td>
                    <td>
                      {check.tool_name} {check.tool_version}
                    </td>
                    <td>
                      <span className={`pose-quality-pill status-${check.status}`}>
                        {STATUS_LABEL[check.status]}
                      </span>
                    </td>
                    <td>
                      {check.value !== null && check.value !== undefined
                        ? formatScientificNumber(check.value, 4)
                        : "—"}
                    </td>
                    <td>
                      {check.threshold !== null && check.threshold !== undefined
                        ? formatScientificNumber(check.threshold, 4)
                        : "—"}
                    </td>
                    <td>{check.message ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}
