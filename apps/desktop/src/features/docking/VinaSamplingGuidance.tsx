import type { BindingBox } from "../../types/api";

export const VINA_SEARCH_VOLUME_WARNING_ANGSTROM3 = 27_000;

export function vinaSearchVolume(box: BindingBox): number {
  return box.size_x * box.size_y * box.size_z;
}

interface VinaSamplingGuidanceProps {
  box: BindingBox;
  exhaustiveness?: number;
  showWithinBoundary?: boolean;
}

export function VinaSamplingGuidance({
  box,
  exhaustiveness,
  showWithinBoundary = false,
}: VinaSamplingGuidanceProps) {
  const volume = vinaSearchVolume(box);
  const large = volume > VINA_SEARCH_VOLUME_WARNING_ANGSTROM3;
  if (!large && !showWithinBoundary) return null;

  const formattedVolume = Math.round(volume).toLocaleString("en-US");
  const ratio = (volume / VINA_SEARCH_VOLUME_WARNING_ANGSTROM3).toFixed(1);
  const unchanged = exhaustiveness === undefined
    ? "Finalizing this site keeps the exact displayed box."
    : `The selected exhaustiveness is ${exhaustiveness}; Ankora has not changed it.`;

  return (
    <div
      className={large ? "protonation-blocker vina-sampling-guidance" : "state-resolved-note vina-sampling-guidance"}
      role="status"
      aria-label="AutoDock Vina search-space guidance"
    >
      <strong>{large ? "Vina large search-space warning" : "Vina search-space sampling"}</strong>
      <small>
        {large
          ? `This box is ${formattedVolume} Å³ (${ratio}× Vina's 27,000 Å³ warning boundary). Larger spaces are harder to sample. `
          : `This box is ${formattedVolume} Å³, within Vina's 27,000 Å³ warning boundary. `}
        {unchanged} {exhaustiveness === undefined
          ? ""
          : "Use a narrower scientifically justified box when possible, or test increasing exhaustiveness in a recorded sensitivity series before treating the search as converged."}
      </small>
    </div>
  );
}
