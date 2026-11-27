import type { ReceptorOutputArtifact, ResidueLocator } from "../../types/api";

/**
 * The ADR-032 §2.1 / §2.2 FlexRes selection rules, in one place.
 *
 * These are the scientific boundaries of a side-chain flexibility selection,
 * so they are stated once and read by the picker, the docking banners, and the
 * tests rather than being retyped at each site. The backend enforces the same
 * rules with a 422; this exists so the scientist sees why a residue is refused
 * before a request is spent, never to replace the server-side guard.
 */

/**
 * Residues that cannot be freed at all — a hard rejection, never a warning and
 * never a silent drop (ADR-032 §2.1, probed in §A3):
 *
 * - `GLY` has no rotatable side chain, and Meeko emits its *backbone* instead.
 * - `ALA` has no chi torsion, and Meeko writes no flex file whatsoever.
 * - `PRO`'s side chain is covalently closed onto the backbone, so freeing it is
 *   not a side-chain rotation; Meeko again emits backbone atoms.
 * - `CYX` is a disulfide-bonded cysteine; moving it breaks a recorded bond.
 *
 * Meeko exits 0 in the first three cases, which is exactly why the guard has to
 * run before it is invoked rather than after.
 */
export const DISALLOWED_FLEX_RESIDUE_NAMES = ["GLY", "ALA", "PRO", "CYX"] as const;

/** Recommended, not enforced: exceeding either budget warns and proceeds. */
export const RECOMMENDED_MAX_FLEX_RESIDUES = 4;
export const RECOMMENDED_MAX_FLEX_CHI_TORSIONS = 12;

/** The structured advisory emitted when either recommended budget is exceeded. */
export const FLEXRES_DOF_HIGH_CODE = "DOCKING_FLEXRES_DOF_HIGH";

/** Why a residue cannot be freed, or null when it can. */
export function flexResidueRejection(residueName: string): string | null {
  const name = residueName.trim().toUpperCase();
  if (name === "GLY") return "GLY has no rotatable side chain to free.";
  if (name === "ALA") return "ALA has no chi torsion to free.";
  if (name === "PRO") {
    return "PRO's side chain is covalently closed onto the backbone, so freeing it is not a side-chain rotation.";
  }
  if (name === "CYX") {
    return "CYX is a disulfide-bonded cysteine; moving it would break a recorded covalent bond.";
  }
  return null;
}

/**
 * A residue's position, without its name.
 *
 * Duplicates are rejected by position because one position cannot be freed
 * twice, whatever name the selection source reported for it.
 */
export function flexResiduePositionKey(residue: ResidueLocator): string {
  return [residue.chain_id, residue.sequence_number, residue.insertion_code].join("|");
}

export function flexResidueLabel(residue: ResidueLocator): string {
  return `${residue.residue_name} ${residue.chain_id || "∅"}:${residue.sequence_number}${residue.insertion_code}`;
}

/**
 * Whether this selection exceeds a recommended budget (ADR-032 §2.2).
 *
 * Added side-chain torsions multiply the search space against a fixed
 * exhaustiveness, so the same sampling budget spread over more degrees of
 * freedom is a *less* converged search. Ankora never truncates the selection
 * to fit, and never raises effort to compensate (ADR-018 / ADR-019).
 */
export function exceedsFlexDofBudget(
  residueCount: number,
  addedChiTorsionCount: number | null = null,
): boolean {
  return residueCount > RECOMMENDED_MAX_FLEX_RESIDUES
    || (addedChiTorsionCount !== null && addedChiTorsionCount > RECOMMENDED_MAX_FLEX_CHI_TORSIONS);
}

/** One refused candidate, carrying the reason the scientist has to be shown. */
export interface FlexResidueRejection {
  residue: ResidueLocator;
  reason: string;
}

export interface FlexResidueAdmission {
  accepted: ResidueLocator[];
  rejections: FlexResidueRejection[];
}

/**
 * Admit a batch of candidate residues, keeping every refusal explicit.
 *
 * Both selection sources — 3D picking and the structured add control — pass
 * through here, so a pick that lands on a `GLY` is reported rather than
 * quietly producing a selection that would emit backbone atoms. Nothing is
 * dropped silently: everything refused comes back in `rejections`.
 */
export function admitFlexResidues(candidates: ResidueLocator[]): FlexResidueAdmission {
  const accepted: ResidueLocator[] = [];
  const rejections: FlexResidueRejection[] = [];
  const seen = new Set<string>();
  for (const residue of candidates) {
    const reason = flexResidueRejection(residue.residue_name);
    if (reason) {
      rejections.push({ residue, reason });
      continue;
    }
    const key = flexResiduePositionKey(residue);
    if (seen.has(key)) {
      rejections.push({
        residue,
        reason: `${flexResidueLabel(residue)} is already selected; one position cannot be freed twice.`,
      });
      continue;
    }
    seen.add(key);
    accepted.push(residue);
  }
  return { accepted, rejections };
}

/**
 * The receptor PDBQT every docking engine reads as its rigid input.
 *
 * A rigid preparation records one `pdbqt`; a `sidechain_flex` one records the
 * `pdbqt_rigid` half of the Meeko split instead (ADR-032 §2). Both are valid
 * docking inputs, so readiness is decided here once rather than at each engine
 * workspace — a flexible receptor must never read as "not prepared".
 */
export function findDockingReceptorPdbqt(
  outputs: readonly ReceptorOutputArtifact[],
): ReceptorOutputArtifact | undefined {
  return outputs.find((item) => item.stage === "pdbqt" || item.stage === "pdbqt_rigid");
}

/** The moving half of the split, present only under `sidechain_flex`. */
export function findFlexReceptorPdbqt(
  outputs: readonly ReceptorOutputArtifact[],
): ReceptorOutputArtifact | undefined {
  return outputs.find((item) => item.stage === "pdbqt_flex");
}
