import type { GninaDockingParameters } from "../../types/api";

/**
 * The GNINA search protocol, shared by the single-ligand workspace and the
 * library campaign.
 *
 * A campaign applies one protocol to every molecule, and the backend contract
 * takes the single-job parameters unchanged, so there is deliberately nothing
 * campaign-shaped here - no concurrency setting in particular. The existing
 * GNINA service runs one job at a time.
 *
 * `cnn_scoring`, `cnn_model`, `hydrogen_handling` and `pose_sort_order` are
 * fixed to the recorded, validated policy of ADR-027 rather than offered as
 * knobs: each alternative needs its own recorded semantics first.
 */
export function defaultGninaParameters(): GninaDockingParameters {
  return {
    compute: "cpu",
    device_index: 0,
    cpu_threads: 2,
    seed: 20261029,
    exhaustiveness: 8,
    num_modes: 9,
    min_rmsd_filter_angstrom: 1,
    timeout_minutes: 360,
    cnn_scoring: "rescore",
    cnn_model: "dense_1_3",
    hydrogen_handling: "prepared_pdbqt_no_add_no_strip",
    pose_sort_order: "cnn_score_descending",
  };
}

export type GninaNumericParameter =
  | "cpu_threads"
  | "seed"
  | "exhaustiveness"
  | "num_modes"
  | "min_rmsd_filter_angstrom"
  | "timeout_minutes";

export interface GninaNumericField {
  key: GninaNumericParameter;
  label: string;
  min: number;
  max: number;
  step: number;
}

/** The bounds the backend enforces, so an out-of-range value never leaves here. */
export const GNINA_NUMERIC_FIELDS: readonly GninaNumericField[] = [
  { key: "cpu_threads", label: "CPU threads", min: 1, max: 256, step: 1 },
  { key: "seed", label: "Seed", min: 1, max: 2147483647, step: 1 },
  { key: "exhaustiveness", label: "Exhaustiveness", min: 1, max: 128, step: 1 },
  { key: "num_modes", label: "Maximum poses", min: 1, max: 100, step: 1 },
  { key: "min_rmsd_filter_angstrom", label: "Minimum RMSD (Å)", min: 0, max: 20, step: 0.1 },
  { key: "timeout_minutes", label: "Timeout (minutes)", min: 1, max: 2880, step: 1 },
];

export function gninaParametersValid(parameters: GninaDockingParameters): boolean {
  return GNINA_NUMERIC_FIELDS.every(({ key, min, max, step }) => {
    const value = parameters[key];
    if (!Number.isFinite(value) || value < min || value > max) return false;
    // A fractional step is the only field that is not a whole number.
    return step === 1 ? Number.isInteger(value) : true;
  });
}
