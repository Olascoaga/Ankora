import type { ReceptorPreparationRecord } from "../../types/api";
import {
  exceedsFlexDofBudget,
  flexResidueLabel,
  flexResiduePositionKey,
  FLEXRES_DOF_HIGH_CODE,
  RECOMMENDED_MAX_FLEX_CHI_TORSIONS,
} from "../receptor/flexResidues";

/**
 * Which engine family is reading this receptor.
 *
 * AutoGrid4 is the only consumer that needs the atom-type union stated up
 * front, because its maps are computed before docking and a type present only
 * in the moving side chains has no map unless it was requested (ADR-032 §3 /
 * the `E7` union guard).
 */
export type FlexResEngineFamily = "vina" | "autodock4" | "gnina";

interface ActiveFlexResBannerProps {
  receptor: ReceptorPreparationRecord;
  engineFamily: FlexResEngineFamily;
}

/**
 * A read-only statement of the FlexRes split this docking run will use.
 *
 * The split is a property of the already-prepared receptor, so nothing here is
 * editable: changing it means preparing another receptor derivative. This
 * exists so a scientist configuring a run cannot mistake a flexible receptor
 * for the rigid baseline, and renders nothing at all for a rigid receptor so
 * the frozen v0.1 screens stay unchanged.
 */
export function ActiveFlexResBanner({ receptor, engineFamily }: ActiveFlexResBannerProps) {
  const spec = receptor.flex_spec;
  if (!spec || spec.mode !== "sidechain_flex") return null;
  const atomTypes = receptor.flex_atom_types ?? [];
  const dofHigh = exceedsFlexDofBudget(spec.flex_residues.length, spec.added_chi_torsion_count);
  return <section className="flexres-active-banner" role="status" aria-label="Active FlexRes split">
    <strong>Active FlexRes split</strong>
    <p>
      This receptor was prepared with flexible side chains, so every pose from this run is a
      coupled complex of the ligand and the moved side chains rather than a ligand pose against a
      fixed receptor.
    </p>
    <ul className="flexres-active-residues">
      {spec.flex_residues.map((residue) => <li key={flexResiduePositionKey(residue)}>{flexResidueLabel(residue)}</li>)}
    </ul>
    <span>{spec.added_chi_torsion_count} added chi torsion{spec.added_chi_torsion_count === 1 ? "" : "s"}</span>
    <span>receptor_rigid.pdbqt · {spec.receptor_rigid_sha256.slice(0, 12)}…</span>
    {spec.receptor_flex_sha256 ? <span>receptor_flex.pdbqt · {spec.receptor_flex_sha256.slice(0, 12)}…</span> : null}
    {engineFamily === "autodock4" ? <p className="flexres-autogrid-requirement">
      AutoGrid4 must compute maps for the union of the rigid receptor and flexible side-chain atom
      types{atomTypes.length ? <> — flexible types <strong>{atomTypes.join(" ")}</strong></> : null}.
      A ligand or side-chain type without a map is a hard failure, not a silently skipped atom.
    </p> : null}
    {dofHigh ? <p className="flexres-dof-advisory warning">
      <strong>{FLEXRES_DOF_HIGH_CODE}</strong> — this split exceeds the recommended budget
      (≤ {RECOMMENDED_MAX_FLEX_CHI_TORSIONS} added chi torsions). The run is not blocked, but the
      same sampling effort now spans a larger search space and is therefore less converged.
    </p> : null}
  </section>;
}
