import type { VinaDockingParameters } from "../../types/api";

export type VinaSamplingProtocol = NonNullable<VinaDockingParameters["sampling_protocol"]>;

interface VinaSamplingFields {
  sampling_protocol?: VinaSamplingProtocol | null;
  exhaustiveness: number;
  num_modes: number;
  min_rmsd_angstrom: number;
  energy_range_kcal_mol: number;
}

const PRESETS: Record<Exclude<VinaSamplingProtocol, "custom">, Omit<VinaSamplingFields, "sampling_protocol">> = {
  screening: {
    exhaustiveness: 8,
    num_modes: 9,
    min_rmsd_angstrom: 1,
    energy_range_kcal_mol: 3,
  },
  pose_refinement: {
    exhaustiveness: 32,
    num_modes: 20,
    min_rmsd_angstrom: 1,
    energy_range_kcal_mol: 5,
  },
};

export function applyVinaSamplingProtocol<T extends VinaSamplingFields>(
  parameters: T,
  protocol: VinaSamplingProtocol,
): T {
  if (protocol === "custom") return { ...parameters, sampling_protocol: protocol };
  return { ...parameters, ...PRESETS[protocol], sampling_protocol: protocol };
}

export function isVinaSamplingParameter(name: string): boolean {
  return ["exhaustiveness", "num_modes", "min_rmsd_angstrom", "energy_range_kcal_mol"].includes(name);
}

export function vinaSamplingProtocolLabel(
  protocol: VinaSamplingProtocol | null | undefined,
): string {
  if (protocol === "screening") return "Screening";
  if (protocol === "pose_refinement") return "Pose refinement";
  if (protocol === "custom") return "Custom";
  return "Unlabelled historical";
}

interface VinaSamplingProtocolControlProps {
  protocol: VinaSamplingProtocol;
  disabled: boolean;
  onChange: (protocol: VinaSamplingProtocol) => void;
}

export function VinaSamplingProtocolControl({
  protocol,
  disabled,
  onChange,
}: VinaSamplingProtocolControlProps) {
  const description = protocol === "screening"
    ? "Throughput-oriented starting values: exhaustiveness 8, 9 modes, 1 Å separation, and a 3 kcal/mol range."
    : protocol === "pose_refinement"
      ? "Deeper starting values for a focused shortlist: exhaustiveness 32, 20 modes, 1 Å separation, and a 5 kcal/mol range."
      : "The exact sampling values below are scientist-edited and retained as a custom protocol.";

  return (
    <div className="vina-protocol-control">
      <div className="source-tabs sampling-protocol-tabs" role="group" aria-label="Vina sampling purpose">
        <button type="button" className={protocol === "screening" ? "selected" : ""} aria-pressed={protocol === "screening"} disabled={disabled} onClick={() => onChange("screening")}>Screening</button>
        <button type="button" className={protocol === "pose_refinement" ? "selected" : ""} aria-pressed={protocol === "pose_refinement"} disabled={disabled} onClick={() => onChange("pose_refinement")}>Pose refinement</button>
        <button type="button" className={protocol === "custom" ? "selected" : ""} aria-pressed={protocol === "custom"} disabled={disabled} onClick={() => onChange("custom")}>Custom</button>
      </div>
      <p className="field-note">{description} This purpose label is a starting protocol, not evidence of convergence or publication suitability.</p>
    </div>
  );
}
