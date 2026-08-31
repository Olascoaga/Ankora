import type { RefObject } from "react";

import {
  FAMILY_COLOR,
  FAMILY_LEGEND,
  interactionFamily,
  shortInteractionType,
} from "./interactionFamilies";
export { interactionFamily } from "./interactionFamilies";

import type {
  InteractionAnalysisRecord,
  InteractionContact,
  LigandDiagramAtom,
  LigandDiagramBond,
} from "../../types/api";

interface InteractionDiagramProps {
  analysis: InteractionAnalysisRecord;
  selectedContactId: string | null;
  onSelect: (contact: InteractionContact) => void;
  /** Handed out so a figure export serializes this exact drawing. */
  svgRef?: RefObject<SVGSVGElement | null>;
}

interface Point { x: number; y: number }

/**
 * The figure is self-contained: caption, drawing and legend are all inside the
 * SVG rather than around it in HTML. Exported, it has to explain itself to a
 * reader who never saw the screen - including why a skeletal ligand shows no
 * carbons, which otherwise reads as a molecule with atoms missing.
 */
const WIDTH = 760;
const HEIGHT = 524;
const CAPTION_BASELINE = 26;
const PLOT_TOP = 38;
const PLOT_BOTTOM = 470;
const LEGEND_BASELINE = 502;
const CENTRE = { x: WIDTH / 2, y: (PLOT_TOP + PLOT_BOTTOM) / 2 };
// A residue node holds two lines of text, so its size is set by the widest
// label rather than chosen. It is an ellipse because the labels need width and
// the ring has width to spare: `Hydrophobic x2` is about 85 units at 11, which
// a 44-unit circle cannot hold but a 58-unit half-width can.
const NODE_RX = 58;
const NODE_RY = 42;
// The residue ring, and the space it leaves free in the middle for the ligand.
const RING_X = 292;
const RING_Y = 172;
const LIGAND_HALF_WIDTH = 175;
const LIGAND_HALF_HEIGHT = 88;

export const DIAGRAM_ASPECT_RATIO = WIDTH / HEIGHT;

export function InteractionDiagram({
  analysis,
  selectedContactId,
  onSelect,
  svgRef,
}: InteractionDiagramProps) {
  const heavyAtoms = analysis.ligand_diagram.atoms.filter((atom) => atom.element !== "H");
  const atomPoints = fitLigand(heavyAtoms);
  const groups = groupContacts(analysis.contacts);
  const residuePoints = placeResidues(groups, atomPoints, analysis);

  return (
    <figure className="interaction-diagram">
      <figcaption>Select a contact to focus it in the 3D view.</figcaption>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="2D pose interaction diagram"
      >
        <text className="interaction-figure-caption" x={16} y={CAPTION_BASELINE}>
          {analysis.contacts.length} geometric contacts in {groups.length} residue/type
          {" "}groups · skeletal ligand, carbons and hydrogens implicit
        </text>

        {groups.map((group) => {
          const residuePoint = residuePoints.get(group.key)!;
          const anchor = contactAnchor(group.contacts, atomPoints, analysis);
          const selected = group.contacts.some((item) => item.contact_id === selectedContactId);
          return (
            <g
              key={group.key}
              className={`interaction-edge${selected ? " selected" : ""}`}
              style={{ stroke: FAMILY_COLOR[interactionFamily(group.contacts[0].detector_type)] }}
              role="button"
              tabIndex={0}
              aria-label={`${group.contacts[0].display_type} with ${residueLabel(group.contacts[0])}`}
              onClick={() => onSelect(group.contacts[0])}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(group.contacts[0]);
              }}
            >
              <line x1={anchor.x} y1={anchor.y} x2={residuePoint.x} y2={residuePoint.y} />
              <ellipse cx={residuePoint.x} cy={residuePoint.y} rx={NODE_RX} ry={NODE_RY} />
              <text x={residuePoint.x} y={residuePoint.y - 4}>{residueLabel(group.contacts[0])}</text>
              <text className="interaction-node-type" x={residuePoint.x} y={residuePoint.y + 14}>
                {shortInteractionType(group.contacts[0].detector_type)}{group.contacts.length > 1 ? ` ×${group.contacts.length}` : ""}
              </text>
            </g>
          );
        })}

        <g className="ligand-diagram-bonds">
          {analysis.ligand_diagram.bonds
            .filter((bond) => atomPoints.has(bond.begin_atom_index) && atomPoints.has(bond.end_atom_index))
            .map((bond, index) => (
              <BondGlyph
                key={`${bond.begin_atom_index}-${bond.end_atom_index}-${index}`}
                bond={bond}
                start={atomPoints.get(bond.begin_atom_index)!}
                end={atomPoints.get(bond.end_atom_index)!}
              />
            ))}
        </g>
        <g className="ligand-diagram-atoms">
          {heavyAtoms.filter((atom) => shouldLabelAtom(atom, analysis)).map((atom) => {
            const point = atomPoints.get(atom.atom_index)!;
            return (
              <g key={atom.atom_index} className={`element-${atom.element.toLowerCase()}`}>
                <text x={point.x} y={point.y + 5}>{atom.element}</text>
              </g>
            );
          })}
        </g>

        <g className="interaction-figure-legend" aria-label="Interaction legend">
          {legendPositions().map(({ entry, x }) => (
            <g key={entry.family}>
              <circle cx={x + 6} cy={LEGEND_BASELINE - 5} r={6} fill={FAMILY_COLOR[entry.family]} />
              <text x={x + 19} y={LEGEND_BASELINE}>{entry.label}</text>
            </g>
          ))}
        </g>
      </svg>
    </figure>
  );
}

function BondGlyph({ bond, start, end }: {
  bond: LigandDiagramBond;
  start: Point;
  end: Point;
}) {
  const offsets = bond.order >= 2.8
    ? [-3.4, 0, 3.4]
    : bond.order >= 1.8
      ? [-2.4, 2.4]
      : bond.order > 1.2
        ? [0, 3.2]
        : [0];
  const length = Math.hypot(end.x - start.x, end.y - start.y) || 1;
  const normal = {
    x: -(end.y - start.y) / length,
    y: (end.x - start.x) / length,
  };
  const aromatic = bond.order > 1.2 && bond.order < 1.8;
  return (
    <g className={`ligand-bond bond-order-${bond.order}${aromatic ? " aromatic" : ""}`}>
      {offsets.map((offset, index) => (
        <line
          key={offset}
          className={aromatic && index === 1 ? "aromatic-inner" : undefined}
          x1={start.x + normal.x * offset}
          y1={start.y + normal.y * offset}
          x2={end.x + normal.x * offset}
          y2={end.y + normal.y * offset}
        />
      ))}
    </g>
  );
}

function fitLigand(atoms: LigandDiagramAtom[]): Map<number, Point> {
  if (!atoms.length) return new Map();
  const xs = atoms.map((atom) => atom.x);
  const ys = atoms.map((atom) => atom.y);
  const minX = Math.min(...xs); const maxX = Math.max(...xs);
  const minY = Math.min(...ys); const maxY = Math.max(...ys);
  // Fitted to the space the residue ring actually leaves, rather than to a
  // fixed 190px box that left this molecule a sliver in the middle of the
  // figure - measured at 190x87 inside a 640x390 canvas.
  const scale = Math.min(
    (LIGAND_HALF_WIDTH * 2) / Math.max(maxX - minX, 1),
    (LIGAND_HALF_HEIGHT * 2) / Math.max(maxY - minY, 1),
  );
  const sourceCentreX = (minX + maxX) / 2;
  const sourceCentreY = (minY + maxY) / 2;
  return new Map(atoms.map((atom) => [atom.atom_index, {
    x: CENTRE.x + (atom.x - sourceCentreX) * scale,
    y: CENTRE.y - (atom.y - sourceCentreY) * scale,
  }]));
}

/**
 * Each residue on the side of the ligand its contact actually comes from.
 *
 * Placed by list order instead, a contact anchored on the right of the
 * molecule could be drawn to a node on the left, and its line would cut
 * straight across the structure - which is what made the figure read as a
 * sliced molecule rather than an annotated one. Sorting by the anchor's
 * direction keeps the edges from crossing each other or the ligand, and the
 * ring is rotated to the first anchor so the layout follows the chemistry
 * rather than a fixed starting angle.
 */
/**
 * Legend entries spaced by how long their labels are.
 *
 * An equal share each is only right when the labels are the same length, and
 * `π-stacking / cation–π` is four times `Ionic`: at a readable size it ran
 * straight into its neighbour. Character count is a coarse proxy for width,
 * but it is the one available without measuring text that is not on screen yet.
 */
function legendPositions(): { entry: (typeof FAMILY_LEGEND)[number]; x: number }[] {
  const MARGIN = 18;
  const SWATCH = 25;
  const available = WIDTH - MARGIN * 2 - SWATCH * FAMILY_LEGEND.length;
  const characters = FAMILY_LEGEND.reduce((sum, item) => sum + item.label.length, 0);
  let cursor = MARGIN;
  return FAMILY_LEGEND.map((entry) => {
    const x = cursor;
    cursor += SWATCH + (available * entry.label.length) / characters;
    return { entry, x };
  });
}

function placeResidues(
  groups: { key: string; contacts: InteractionContact[] }[],
  atomPoints: Map<number, Point>,
  analysis: InteractionAnalysisRecord,
): Map<string, Point> {
  const anchored = groups.map((group) => {
    const anchor = contactAnchor(group.contacts, atomPoints, analysis);
    return {
      key: group.key,
      angle: Math.atan2(anchor.y - CENTRE.y, anchor.x - CENTRE.x),
    };
  });
  anchored.sort((left, right) => left.angle - right.angle);
  const start = anchored[0]?.angle ?? -Math.PI / 2;
  const placed = new Map<string, Point>();
  anchored.forEach((group, index) => {
    const angle = start + (index * Math.PI * 2) / Math.max(anchored.length, 1);
    placed.set(group.key, {
      x: CENTRE.x + Math.cos(angle) * RING_X,
      y: CENTRE.y + Math.sin(angle) * RING_Y,
    });
  });
  return placed;
}

function contactAnchor(
  contacts: InteractionContact[],
  points: Map<number, Point>,
  analysis: InteractionAnalysisRecord,
): Point {
  const indices = [...new Set(contacts.flatMap((contact) => contact.ligand_atom_indices))];
  const selected = indices
    .map((index) => points.get(index) ?? bondedHeavyPoint(index, points, analysis.ligand_diagram.bonds))
    .filter((point): point is Point => Boolean(point));
  if (!selected.length) return CENTRE;
  return {
    x: selected.reduce((sum, point) => sum + point.x, 0) / selected.length,
    y: selected.reduce((sum, point) => sum + point.y, 0) / selected.length,
  };
}

function bondedHeavyPoint(
  atomIndex: number,
  points: Map<number, Point>,
  bonds: LigandDiagramBond[],
): Point | undefined {
  for (const bond of bonds) {
    if (bond.begin_atom_index === atomIndex && points.has(bond.end_atom_index)) {
      return points.get(bond.end_atom_index);
    }
    if (bond.end_atom_index === atomIndex && points.has(bond.begin_atom_index)) {
      return points.get(bond.begin_atom_index);
    }
  }
  return undefined;
}

function shouldLabelAtom(atom: LigandDiagramAtom, analysis: InteractionAnalysisRecord): boolean {
  if (atom.element !== "C") return true;
  const atoms = new Map(analysis.ligand_diagram.atoms.map((item) => [item.atom_index, item]));
  const hasHeavyNeighbour = analysis.ligand_diagram.bonds.some((bond) => {
    if (bond.begin_atom_index === atom.atom_index) {
      return atoms.get(bond.end_atom_index)?.element !== "H";
    }
    if (bond.end_atom_index === atom.atom_index) {
      return atoms.get(bond.begin_atom_index)?.element !== "H";
    }
    return false;
  });
  return !hasHeavyNeighbour;
}

function groupContacts(contacts: InteractionContact[]) {
  const grouped = new Map<string, InteractionContact[]>();
  for (const contact of contacts) {
    const family = interactionFamily(contact.detector_type);
    const residue = contact.residue;
    const key = `${residue.chain_id}:${residue.sequence_number}:${residue.insertion_code}:${family}`;
    grouped.set(key, [...(grouped.get(key) ?? []), contact]);
  }
  return [...grouped.entries()].map(([key, groupedContacts]) => ({ key, contacts: groupedContacts }));
}

function residueLabel(contact: InteractionContact): string {
  const residue = contact.residue;
  return `${residue.residue_name} ${residue.chain_id || "∅"}:${residue.sequence_number}${residue.insertion_code}`;
}
