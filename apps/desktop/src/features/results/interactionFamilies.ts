import type { InteractionFamily } from "../../viewer/adapter";

/**
 * One classification and one palette, for every picture of a contact.
 *
 * The same contact is drawn twice — flat in the diagram and in space in the
 * viewer — and a bond that is amber in one and blue in the other is two
 * different claims about one measurement. Both read the family and the colour
 * from here, and the exported figure's legend reads them from here too, so a
 * reader who only ever sees the SVG is told the same thing.
 */

export const FAMILY_COLOR: Record<InteractionFamily, string> = {
  hydrogen: "#4fa3ff",
  hydrophobic: "#e4a43a",
  aromatic: "#b783ff",
  ionic: "#ff7383",
  special: "#40c9d0",
};

/** What each colour means, in the order the legend reads. */
export const FAMILY_LEGEND: { family: InteractionFamily; label: string }[] = [
  { family: "hydrogen", label: "Hydrogen bond" },
  { family: "hydrophobic", label: "Hydrophobic" },
  { family: "aromatic", label: "π-stacking / cation–π" },
  { family: "ionic", label: "Ionic" },
  { family: "special", label: "Halogen / metal" },
];

/** Which family a ProLIF detector type belongs to. */
export function interactionFamily(type: string): InteractionFamily {
  if (type.startsWith("HB")) return "hydrogen";
  if (type === "Hydrophobic") return "hydrophobic";
  if (["FaceToFace", "EdgeToFace", "CationPi", "PiCation"].includes(type)) return "aromatic";
  if (["Anionic", "Cationic"].includes(type)) return "ionic";
  return "special";
}

/** The short name shown on a residue node. */
export function shortInteractionType(type: string): string {
  const labels: Record<string, string> = {
    HBDonor: "H-donor", HBAcceptor: "H-acceptor", Hydrophobic: "Hydrophobic",
    FaceToFace: "π face", EdgeToFace: "π edge", CationPi: "Cation–π", PiCation: "π–cation",
    Anionic: "Anionic", Cationic: "Cationic", XBAcceptor: "X-acceptor", XBDonor: "X-donor",
    MetalAcceptor: "Metal acceptor", MetalDonor: "Metal donor",
  };
  return labels[type] ?? type;
}
