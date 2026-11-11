import type {
  GninaCnnModelSelector,
  GninaDockingParameters,
} from "../../types/api";

/**
 * The GNINA search protocol, shared by the single-ligand workspace and the
 * library campaign (ADR-027 + ADR-028).
 *
 * A campaign applies one protocol to every molecule, and the backend contract
 * takes the single-job parameters unchanged, so there is deliberately nothing
 * campaign-shaped here - no concurrency setting in particular. The existing
 * GNINA service runs one job at a time.
 *
 * `cnn_scoring` offers empirical+CNN rescoring (`rescore`) or combined 3D CNN +
 * empirical gradient local optimization (`refinement`, CUDA-only, >= 10 min
 * timeout). `cnn_model` offers single-network `dense_1_3` or the built-in
 * ensembles `default_1_3_ensemble` (3 models, `--cnn` omitted) and `default1.0`
 * (5 models, `--cnn default1.0`).
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

export const GNINA_CNN_MODEL_MEMBERS: Record<GninaCnnModelSelector, readonly string[]> = {
  dense_1_3: ["dense_1_3"],
  default_1_3_ensemble: [
    "dense_1_3",
    "dense_1_3_PT_KD_3",
    "crossdock_default2018_KD_4",
  ],
  "default1.0": [
    "dense",
    "general_default2018_3",
    "dense_3",
    "crossdock_default2018",
    "redock_default2018_2",
  ],
};

export function applyGninaParameterUpdate<K extends keyof GninaDockingParameters>(
  current: GninaDockingParameters,
  name: K,
  value: GninaDockingParameters[K],
): GninaDockingParameters {
  const next: GninaDockingParameters = { ...current, [name]: value };
  if (name === "cnn_scoring" && value === "refinement" && next.timeout_minutes < 10) {
    next.timeout_minutes = 10;
  }
  return next;
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
  if (parameters.cnn_scoring === "refinement") {
    if (parameters.compute === "cpu") return false;
    if (!Number.isFinite(parameters.timeout_minutes) || parameters.timeout_minutes < 10) {
      return false;
    }
  }
  return GNINA_NUMERIC_FIELDS.every(({ key, min, max, step }) => {
    const value = parameters[key];
    if (!Number.isFinite(value) || value < min || value > max) return false;
    // A fractional step is the only field that is not a whole number.
    return step === 1 ? Number.isInteger(value) : true;
  });
}
