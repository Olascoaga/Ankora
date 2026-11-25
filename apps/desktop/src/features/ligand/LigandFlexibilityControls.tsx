import type { Dispatch, SetStateAction } from "react";

import type { LigandPdbqtRecord, MacrocyclePolicy } from "../../types/api";
import {
  emptySmartsRigidification,
  isDefaultLigandFlexibility,
  validateSmartsRigidifications,
  type LigandFlexibilityDraft,
} from "./ligandFlexibility";

interface LigandFlexibilityControlsProps {
  draft: LigandFlexibilityDraft;
  setDraft: Dispatch<SetStateAction<LigandFlexibilityDraft>>;
  pdbqt: LigandPdbqtRecord | null;
  busy: boolean;
}

/**
 * Explicit semi-flexible ligand control (ADR-032 §1).
 *
 * Collapsed by default and summarized as "Meeko defaults" until something is
 * changed, so the common preparation stays uncluttered and an untouched
 * control provably sends no `flexibility` at all. Every option here changes
 * which engines can read the result or which internal coordinates are allowed
 * to move, so each one states that consequence next to itself rather than in
 * documentation.
 */
export function LigandFlexibilityControls({
  draft, setDraft, pdbqt, busy,
}: LigandFlexibilityControlsProps) {
  const { errors } = validateSmartsRigidifications(draft.rigidifications);
  const customized = !isDefaultLigandFlexibility(draft);
  const outcomes = pdbqt?.smarts_rigidification_outcomes ?? [];
  const unmatched = outcomes.filter((outcome) => outcome.match_count === 0);
  const flexibilityWarnings = (pdbqt?.warnings ?? []).filter((warning) => warning.code.startsWith("LIG_"));

  function updateRow(index: number, patch: Partial<LigandFlexibilityDraft["rigidifications"][number]>) {
    setDraft((current) => ({
      ...current,
      rigidifications: current.rigidifications.map(
        (row, position) => (position === index ? { ...row, ...patch } : row),
      ),
    }));
  }

  return (
    <details className="ligand-flexibility-controls" open={customized}>
      <summary>
        Semi-flexible ligand control (Meeko)
        <small>{customized ? "Customized" : "Meeko defaults"}</small>
      </summary>

      <fieldset className="ligand-macrocycle-policy">
        <legend>Macrocycle policy</legend>
        <label className="check-row">
          <input
            type="radio" name="macrocycle-policy" value="flexible_pseudoatoms"
            checked={draft.macrocyclePolicy === "flexible_pseudoatoms"} disabled={busy}
            onChange={(event) => setDraft((current) => ({
              ...current, macrocyclePolicy: event.target.value as MacrocyclePolicy,
            }))}
          />
          <span>
            <strong>Flexible pseudoatoms (Meeko default)</strong>
            <small>
              Opens macrocyclic rings with <code>CG0</code>/<code>G0</code> glue pseudoatoms so ring
              conformations are sampled during docking. Usable with Vina and GNINA; AutoDock4
              cannot type these pseudoatoms and rejects the ligand.
            </small>
          </span>
        </label>
        <label className="check-row">
          <input
            type="radio" name="macrocycle-policy" value="rigid_input_conformation"
            checked={draft.macrocyclePolicy === "rigid_input_conformation"} disabled={busy}
            onChange={(event) => setDraft((current) => ({
              ...current, macrocyclePolicy: event.target.value as MacrocyclePolicy,
            }))}
          />
          <span>
            <strong>Rigid input conformation</strong>
            <small>
              Keeps the prepared ring conformation exactly as embedded and emits no pseudoatoms, so
              the ligand works across Vina, AutoDock4, AutoDock-GPU and GNINA. The ring conformation
              is then an input assumption that docking cannot correct, not a sampled degree of freedom.
            </small>
          </span>
        </label>
      </fieldset>

      <fieldset className="ligand-smarts-rigidification">
        <legend>Bond rigidification by SMARTS</legend>
        <p className="field-note">
          Each pattern freezes exactly one bond, named by two 1-based atom indices within the
          pattern. Meeko exits successfully on a pattern that matches nothing, so Ankora reports the
          match count after preparation rather than leaving an ineffective restraint invisible.
        </p>
        {draft.rigidifications.map((row, index) => (
          <div className="smarts-rigidification-row" key={index}>
            <label className="numeric-field">
              <span>SMARTS</span>
              <input
                aria-label={`Rigidification SMARTS ${index + 1}`} value={row.smarts} disabled={busy}
                onChange={(event) => updateRow(index, { smarts: event.target.value })}
              />
            </label>
            <label className="numeric-field">
              <span>Atom i</span>
              <input
                aria-label={`Rigidified bond first atom ${index + 1}`} type="number" min={1}
                value={row.firstAtom} disabled={busy}
                onChange={(event) => updateRow(index, { firstAtom: event.target.value })}
              />
            </label>
            <label className="numeric-field">
              <span>Atom j</span>
              <input
                aria-label={`Rigidified bond second atom ${index + 1}`} type="number" min={1}
                value={row.secondAtom} disabled={busy}
                onChange={(event) => updateRow(index, { secondAtom: event.target.value })}
              />
            </label>
            <button
              type="button" disabled={busy}
              aria-label={`Remove rigidification row ${index + 1}`}
              onClick={() => setDraft((current) => ({
                ...current,
                rigidifications: current.rigidifications.filter((_, position) => position !== index),
              }))}
            >Remove</button>
            {errors.has(index)
              ? <p className="protonation-blocker" role="alert">{errors.get(index)}</p>
              : null}
          </div>
        ))}
        <button
          type="button" className="link-action" disabled={busy}
          onClick={() => setDraft((current) => ({
            ...current,
            rigidifications: [...current.rigidifications, emptySmartsRigidification()],
          }))}
        >Add SMARTS bond rigidification</button>
      </fieldset>

      <label className="check-row">
        <input
          type="checkbox" checked={draft.flexibleAmides} disabled={busy}
          onChange={(event) => setDraft((current) => ({
            ...current, flexibleAmides: event.target.checked,
          }))}
        />
        <span>
          <strong>Allow amide bonds to rotate (<code>--flexible_amides</code>)</strong>
          <small>Treats amide C–N bonds as rotatable torsions instead of planar.</small>
        </span>
      </label>
      {draft.flexibleAmides ? (
        <div className="protonation-blocker ligand-amide-planarity-warning" role="alert">
          <strong>LIG_FLEXIBLE_AMIDES_PLANARITY</strong>
          <p>
            Amide bonds are planar by conjugation. Rotating them lets the search produce
            non-planar amide geometries that are not chemically reasonable ground states, and a
            pose scored in such a geometry is not comparable to one from a planar-amide run.
            Enable this only for a deliberate, documented reason.
          </p>
        </div>
      ) : null}

      {pdbqt ? (
        <div className="ligand-flexibility-evidence" role="status" aria-label="Recorded ligand flexibility">
          <span className="ligand-torsdof-badge">
            effective TORSDOF {pdbqt.effective_torsdof ?? "not recorded"}
          </span>
          {pdbqt.flexibility ? (
            <span>
              {pdbqt.flexibility.macrocycle_policy.replaceAll("_", " ")}
              {pdbqt.flexibility.flexible_amides ? " · flexible amides" : ""}
            </span>
          ) : <span>Meeko defaults · no flexibility spec recorded</span>}
          {outcomes.length ? (
            <ul className="smarts-rigidification-outcomes">
              {outcomes.map((outcome, index) => (
                <li
                  key={`${outcome.smarts}-${index}`}
                  className={outcome.match_count === 0 ? "warning" : ""}
                >
                  <code>{outcome.smarts}</code> · bond {outcome.bond_indices.join("–")} ·{" "}
                  {outcome.match_count} match{outcome.match_count === 1 ? "" : "es"} ·{" "}
                  {outcome.applied ? "applied" : "not applied"}
                </li>
              ))}
            </ul>
          ) : null}
          {unmatched.length ? (
            <div className="protonation-blocker" role="alert">
              <strong>LIG_RIGIDIFY_SMARTS_NO_MATCH</strong>
              <p>
                {unmatched.length} pattern{unmatched.length === 1 ? "" : "s"} matched no bond in this
                molecule, so {unmatched.length === 1 ? "that restraint" : "those restraints"} had no
                effect. The recorded TORSDOF above is what was actually docked.
              </p>
              <ul>{unmatched.map((outcome, index) => <li key={`${outcome.smarts}-${index}`}><code>{outcome.smarts}</code></li>)}</ul>
            </div>
          ) : null}
          {flexibilityWarnings.map((warning) => (
            <p className="field-note" key={warning.code}>{warning.code} — {warning.message}</p>
          ))}
        </div>
      ) : null}
    </details>
  );
}
