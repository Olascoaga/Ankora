import type { Dispatch, SetStateAction } from "react";

import type {
  LigandChemicalStateRecord,
  LigandConformerRecord,
  LigandForceField,
  LigandInspection,
  LigandPdbqtRecord,
  LigandProtonationOptions,
  LigandProtonationRecord,
} from "../../types/api";

/**
 * One ligand, one action.
 *
 * Preparing a single ligand used to be five stages and seven buttons, when the
 * scientist only ever owns two decisions: which chemical species this molecule
 * is, and which ionization state to dock. Everything after that - embedding,
 * minimizing, converting to PDBQT - follows from those decisions and from
 * parameters that are stated on screen before the click.
 *
 * So this card states the whole plan and runs it as one chain. Rigor is not in
 * the number of clicks; it is in what the click is documented to do, in the
 * gates it cannot cross, and in every step still writing its own immutable
 * derivative. Nothing here decides anything on the scientist's behalf: when a
 * decision genuinely exists, the chain stops and asks.
 */

/** Which step of the chain is running, for progress the scientist can read. */
export type PreparationStep = "protonation" | "conformer" | "pdbqt" | null;

interface SingleLigandPreparationProps {
  inspection: LigandInspection;
  activeState: LigandChemicalStateRecord | null;
  activeProtonation: LigandProtonationRecord | null;
  protonationOptions: LigandProtonationOptions | null;
  protonationCandidateIndex: number | null;
  onCandidateChange: (index: number) => void;
  protonationSkipped: boolean;
  protonationError: string | null;
  onSkipProtonation: () => void;
  onReconsiderProtonation: () => void;
  phMin: number;
  phMax: number;
  phPrecision: number;
  onPhChange: (next: { min?: number; max?: number; precision?: number }) => void;
  forceField: LigandForceField;
  setForceField: Dispatch<SetStateAction<LigandForceField>>;
  maxIterations: number;
  setMaxIterations: Dispatch<SetStateAction<number>>;
  randomSeed: number;
  setRandomSeed: Dispatch<SetStateAction<number>>;
  /** False embeds a fresh conformer; true minimizes the source coordinates. */
  useSourceGeometry: boolean;
  setUseSourceGeometry: Dispatch<SetStateAction<boolean>>;
  acknowledged: boolean;
  setAcknowledged: Dispatch<SetStateAction<boolean>>;
  conformer: LigandConformerRecord | null;
  pdbqt: LigandPdbqtRecord | null;
  meekoAvailable: boolean;
  blocked: boolean;
  step: PreparationStep;
  busy: boolean;
  onPrepare: () => void;
}

const STEP_LABEL: Record<Exclude<PreparationStep, null>, string> = {
  protonation: "1 / 3 · resolving protonation",
  conformer: "2 / 3 · embedding and minimizing",
  pdbqt: "3 / 3 · converting with Meeko",
};

export function SingleLigandPreparation({
  inspection,
  activeState,
  activeProtonation,
  protonationOptions,
  protonationCandidateIndex,
  onCandidateChange,
  protonationSkipped,
  protonationError,
  onSkipProtonation,
  onReconsiderProtonation,
  phMin,
  phMax,
  phPrecision,
  onPhChange,
  forceField,
  setForceField,
  maxIterations,
  setMaxIterations,
  randomSeed,
  setRandomSeed,
  useSourceGeometry,
  setUseSourceGeometry,
  acknowledged,
  setAcknowledged,
  conformer,
  pdbqt,
  meekoAvailable,
  blocked,
  step,
  busy,
  onPrepare,
}: SingleLigandPreparationProps) {
  const candidates = protonationOptions?.candidates ?? [];
  // A choice only exists when more than one state survived enumeration. One
  // state is a fact to report, not a question to ask.
  const protonationDecisionPending =
    !activeProtonation && !protonationSkipped && candidates.length > 1
    && protonationCandidateIndex === null;
  const nonConverged = conformer !== null && !conformer.minimization.converged;
  const ready = pdbqt !== null;

  const canPrepare = acknowledged && !busy && !blocked && !protonationDecisionPending;

  return (
    <section className="receptor-section ligand-preparation-card" aria-label="Ligand preparation">
      <div className="filter-heading">
        <span>Prepare for docking</span>
        <small>{ready ? "PDBQT ready" : nonConverged ? "Review needed" : "Pending"}</small>
      </div>

      <dl className="ligand-plan">
        <div>
          <dt>Species</dt>
          <dd>
            {activeState
              ? `Component ${activeState.selection.component_index + 1}${
                activeState.selection.stereoisomer_index === null
                  ? " · stereochemistry defined"
                  : ` · stereoisomer ${activeState.selection.stereoisomer_index + 1}`}`
              : "As inspected · no ambiguity to resolve"}
          </dd>
        </div>
        <div>
          <dt>Ionization</dt>
          <dd>
            <ProtonationSummary
              applied={activeProtonation}
              skipped={protonationSkipped}
              error={protonationError}
              candidates={candidates.length}
              formalCharge={inspection.formal_charge}
              phMin={phMin}
              phMax={phMax}
            />
          </dd>
        </div>
        <div>
          <dt>Geometry</dt>
          <dd>
            {useSourceGeometry
              ? `Source coordinates · ${forceField} ≤${maxIterations} iterations`
              : `ETKDGv3 seed ${randomSeed} · ${forceField} ≤${maxIterations} iterations`}
          </dd>
        </div>
        <div>
          <dt>Docking format</dt>
          <dd>
            {meekoAvailable
              ? "Meeko · Gasteiger partial charges"
              : "Meeko not configured — the chain stops at the conformer"}
          </dd>
        </div>
      </dl>

      {!activeProtonation && !protonationSkipped ? (
        <div className="ligand-protonation-choice">
          <div className="ligand-ph-row">
            <label className="numeric-field">
              <span>pH min</span>
              <input
                aria-label="Minimum pH" type="number" step={0.1} min={0} max={14}
                value={phMin} disabled={busy}
                onChange={(event) => onPhChange({ min: Number(event.target.value) })}
              />
            </label>
            <label className="numeric-field">
              <span>pH max</span>
              <input
                aria-label="Maximum pH" type="number" step={0.1} min={0} max={14}
                value={phMax} disabled={busy}
                onChange={(event) => onPhChange({ max: Number(event.target.value) })}
              />
            </label>
            <button
              type="button" className="link-action" disabled={busy}
              onClick={() => onPhChange({ min: 7.4, max: 7.4 })}
            >
              Physiological point 7.4
            </button>
          </div>
          <p className="field-note">
            Dimorphite-DL enumerates every state plausible across this window, so a wider
            window means more states to choose between. Asking for the single pH you are
            modelling usually leaves nothing to decide.
          </p>
          {candidates.length > 1 ? (
            <>
              <label className="field-label" htmlFor="ligand-protonation-candidate">
                {candidates.length} states at this pH — choose the one to dock
              </label>
              <select
                id="ligand-protonation-candidate"
                value={protonationCandidateIndex ?? ""}
                disabled={busy}
                onChange={(event) => onCandidateChange(Number(event.target.value))}
              >
                <option value="" disabled>Choose one protonation state</option>
                {groupByCharge(candidates).map(([charge, group]) => (
                  <optgroup key={charge} label={`formal charge ${signed(charge)}`}>
                    {group.map((candidate) => (
                      <option key={candidate.index} value={candidate.index}>
                        {candidate.canonical_smiles}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </>
          ) : null}
          <button type="button" className="link-action" disabled={busy} onClick={onSkipProtonation}>
            Skip — dock the as-drawn state
          </button>
        </div>
      ) : null}

      {protonationSkipped ? (
        <div className="protonation-blocker" role="alert">
          <p>
            Protonation was skipped. The as-drawn formal charge{" "}
            {signed(inspection.formal_charge)} is used for 3D generation and docking.
          </p>
          <div className="protonation-blocker-actions">
            <button type="button" onClick={onReconsiderProtonation} disabled={busy}>Reconsider</button>
          </div>
        </div>
      ) : null}

      <label className="check-row">
        <input
          type="checkbox" checked={acknowledged} disabled={busy}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        <span>
          <strong>Use exactly this species, ionization and settings</strong>
          <small>
            Confirms the formal charge, bond orders, component and stereochemistry above.
            Each step writes its own immutable derivative; nothing is substituted silently.
          </small>
        </span>
      </label>

      <button
        type="button" className="apply-plan ligand-prepare-action"
        disabled={!canPrepare} onClick={onPrepare}
      >
        {busy
          ? "Preparing…"
          : ready
            ? "Prepare again with these settings"
            : meekoAvailable
              ? "Prepare ligand for docking"
              : "Prepare conformer (Meeko unavailable)"}
      </button>

      {step ? (
        <div className="operation-progress" role="progressbar" aria-label="Preparing ligand">
          <span /><p>{STEP_LABEL[step]}</p>
        </div>
      ) : null}

      {protonationDecisionPending ? (
        <p className="field-note">
          Choose a protonation state above, narrow the pH, or skip it before preparing.
        </p>
      ) : null}
      {blocked ? (
        <p className="protonation-blocker">
          Resolve the chemical state above before preparing this ligand.
        </p>
      ) : null}
      {!meekoAvailable ? (
        <p className="protonation-blocker">
          Meeko ligand preparation is not configured, so this stops after minimization.
          The conformer is still produced and recorded; docking needs the PDBQT.
        </p>
      ) : null}
      {nonConverged ? (
        <p className="protonation-blocker" role="alert">
          {conformer.minimization.conformer_selection_policy
            === "lowest_energy_nonconverged_fallback"
            && conformer.minimization.conformer_pool_size
            ? `None of the ${conformer.minimization.conformer_pool_size} embedded conformers converged. The lowest-energy nonconverged outcome was preserved for review, and Meeko was not run on it.`
            : "Minimization reached the iteration limit without converging, so Meeko was not run on it."}
          {" "}Raise the iteration limit below and prepare again, or review the recorded
          energy change before accepting this geometry.
        </p>
      ) : null}

      <details className="ligand-advanced">
        <summary>Advanced settings</summary>
        <label className="field-label" htmlFor="ligand-force-field">Force field</label>
        <select
          id="ligand-force-field" value={forceField} disabled={busy}
          onChange={(event) => setForceField(event.target.value as LigandForceField)}
        >
          <option value="MMFF94s">MMFF94s</option>
          <option value="MMFF94">MMFF94</option>
        </select>
        <label className="numeric-field">
          <span>Maximum iterations</span>
          <input
            aria-label="Maximum minimization iterations" type="number" min={1} max={10000}
            value={maxIterations} disabled={busy}
            onChange={(event) => setMaxIterations(clamp(event.target.value, 1, 10000))}
          />
        </label>
        <label className="numeric-field">
          <span>ETKDG random seed</span>
          <input
            aria-label="ETKDG random seed" type="number" min={0} max={2147483647}
            value={randomSeed} disabled={busy || useSourceGeometry}
            onChange={(event) => setRandomSeed(clamp(event.target.value, 0, 2147483647))}
          />
        </label>
        <label className="numeric-field">
          <span>pKa precision (σ)</span>
          <input
            aria-label="pKa precision in standard deviations" type="number"
            step={0.1} min={0.1} max={5} value={phPrecision} disabled={busy}
            onChange={(event) => onPhChange({ precision: Number(event.target.value) })}
          />
        </label>
        {inspection.has_3d_coordinates ? (
          <label className="check-row">
            <input
              type="checkbox" checked={useSourceGeometry} disabled={busy}
              onChange={(event) => setUseSourceGeometry(event.target.checked)}
            />
            <span>
              <strong>Minimize the source geometry instead</strong>
              <small>
                Keeps the experimentally observed coordinates and only relaxes them. Docking
                samples torsions but not ring conformations, so this choice carries through
                to the pose. Independent ETKDGv3 generation is the default because it does
                not carry the source pose into the search.
              </small>
            </span>
          </label>
        ) : null}
      </details>
    </section>
  );
}

function ProtonationSummary({
  applied, skipped, error, candidates, formalCharge, phMin, phMax,
}: {
  applied: LigandProtonationRecord | null;
  skipped: boolean;
  error: string | null;
  candidates: number;
  formalCharge: number;
  phMin: number;
  phMax: number;
}) {
  if (applied) {
    return <>
      Dimorphite-DL pH {applied.selection.ph_min}–{applied.selection.ph_max} · candidate{" "}
      {applied.selection.candidate_index + 1} of {applied.selection.candidate_count} ·
      formal charge {signed(formalCharge)}
    </>;
  }
  if (skipped) return <>As drawn · formal charge {signed(formalCharge)}</>;
  if (error) return <>Could not enumerate — {error}</>;
  const window = phMin === phMax ? `pH ${phMin}` : `pH ${phMin}–${phMax}`;
  if (candidates === 0) return <>Dimorphite-DL {window} · reading states…</>;
  if (candidates === 1) return <>Dimorphite-DL {window} · single state, nothing to decide</>;
  return <>Dimorphite-DL {window} · {candidates} states, one must be chosen</>;
}

function groupByCharge(
  candidates: LigandProtonationOptions["candidates"],
): [number, LigandProtonationOptions["candidates"]][] {
  // Formal charge is what changes the AutoDock typing and the Gasteiger charges,
  // so it is the axis worth grouping a long list of SMILES by.
  const groups = new Map<number, LigandProtonationOptions["candidates"]>();
  for (const candidate of candidates) {
    const group = groups.get(candidate.formal_charge);
    if (group) group.push(candidate);
    else groups.set(candidate.formal_charge, [candidate]);
  }
  return [...groups.entries()].sort((left, right) => left[0] - right[0]);
}

function signed(value: number): string {
  // A neutral molecule is charge 0, never "+0".
  if (value === 0) return "0";
  return value > 0 ? `+${value}` : `${value}`;
}

function clamp(raw: string, min: number, max: number): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return min;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}
