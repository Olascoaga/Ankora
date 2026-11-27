import type { LigandFlexibilitySpec, MacrocyclePolicy } from "../../types/api";

/**
 * The editable form of one `--rigidify_bonds_smarts` row.
 *
 * Atom indices stay as strings while being typed so a half-entered field reads
 * as empty rather than as a spurious index, and so the inline validation can
 * explain what is wrong instead of silently coercing it.
 */
export interface SmartsRigidificationDraft {
  smarts: string;
  firstAtom: string;
  secondAtom: string;
}

export interface LigandFlexibilityDraft {
  macrocyclePolicy: MacrocyclePolicy;
  rigidifications: SmartsRigidificationDraft[];
  flexibleAmides: boolean;
}

/**
 * Meeko's own default: macrocycles are opened with glue pseudoatoms, no bond
 * is rigidified, and amides stay planar. Matching it exactly is what lets a
 * default preparation keep sending no `flexibility` at all.
 */
export const DEFAULT_MACROCYCLE_POLICY: MacrocyclePolicy = "flexible_pseudoatoms";

export function emptyLigandFlexibilityDraft(): LigandFlexibilityDraft {
  return { macrocyclePolicy: DEFAULT_MACROCYCLE_POLICY, rigidifications: [], flexibleAmides: false };
}

export function emptySmartsRigidification(): SmartsRigidificationDraft {
  return { smarts: "", firstAtom: "", secondAtom: "" };
}

/** Whether this draft still describes exactly the frozen v0.1 preparation. */
export function isDefaultLigandFlexibility(draft: LigandFlexibilityDraft): boolean {
  return draft.macrocyclePolicy === DEFAULT_MACROCYCLE_POLICY
    && draft.rigidifications.length === 0
    && !draft.flexibleAmides;
}

export interface SmartsRowValidation {
  /** Keyed by row index; absent means the row is usable. */
  errors: Map<number, string>;
}

/**
 * Validate the SMARTS rows against the recorded backend contract.
 *
 * The backend enforces all of this with a 422; checking here means the
 * scientist is told which row is wrong and why, before a preparation is spent.
 * The rules are the contract's own: one bond pair per pattern, both indices
 * 1-based and positive, the two indices distinct, and no repeated pair.
 */
export function validateSmartsRigidifications(
  rows: readonly SmartsRigidificationDraft[],
): SmartsRowValidation {
  const errors = new Map<number, string>();
  const seenPairs = new Set<string>();
  rows.forEach((row, index) => {
    const smarts = row.smarts.trim();
    if (!smarts) {
      errors.set(index, "Enter a SMARTS pattern, or remove this row.");
      return;
    }
    const first = Number(row.firstAtom);
    const second = Number(row.secondAtom);
    if (!row.firstAtom.trim() || !row.secondAtom.trim()
        || !Number.isInteger(first) || !Number.isInteger(second)) {
      errors.set(index, "Each pattern needs exactly one bond, given as two whole atom indices.");
      return;
    }
    if (first < 1 || second < 1) {
      errors.set(index, "Atom indices are 1-based, so the lowest valid index is 1.");
      return;
    }
    if (first === second) {
      errors.set(index, "A bond needs two distinct atoms.");
      return;
    }
    const pair = [Math.min(first, second), Math.max(first, second)].join("-");
    if (seenPairs.has(pair)) {
      errors.set(index, `Bond ${pair.replace("-", "–")} is already rigidified by another row.`);
      return;
    }
    seenPairs.add(pair);
  });
  return { errors };
}

/**
 * Build the request spec, or `null` when nothing was customized.
 *
 * Returning `null` is what preserves the exact v0.1 payload: an untouched
 * control sends no `flexibility` key rather than an explicit copy of the
 * defaults, so already-validated preparations keep their recorded request
 * shape. Returns `undefined` when the draft is customized but not yet valid,
 * so an invalid selection can never be submitted as a silent default.
 */
export function buildLigandFlexibilitySpec(
  draft: LigandFlexibilityDraft,
): LigandFlexibilitySpec | null | undefined {
  if (isDefaultLigandFlexibility(draft)) return null;
  const { errors } = validateSmartsRigidifications(draft.rigidifications);
  if (errors.size) return undefined;
  return {
    macrocycle_policy: draft.macrocyclePolicy,
    rigidified_smarts: draft.rigidifications.map((row) => row.smarts.trim()),
    rigidified_bond_indices: draft.rigidifications.map(
      (row) => [Number(row.firstAtom), Number(row.secondAtom)] as [number, number],
    ),
    flexible_amides: draft.flexibleAmides,
    // `--local_only` is a docking-time derivative of an already recorded pose,
    // not a preparation setting, so it is never enabled from this control.
    local_only_refinement: false,
  };
}
