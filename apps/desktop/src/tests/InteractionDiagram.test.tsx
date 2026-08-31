import { render, screen } from "@testing-library/react";

import { InteractionDiagram } from "../features/results/InteractionDiagram";
import { FAMILY_COLOR, FAMILY_LEGEND } from "../features/results/interactionFamilies";
import { CARRIED, inlineSvg, portableColor } from "../features/results/figureRendering";
import type { InteractionAnalysisRecord } from "../types/api";

/**
 * A wide, flat ligand — the shape that exposed the fit: 15 Å across and under
 * 7 Å tall, which the old fixed 190px box squeezed into a sliver.
 */
function ligand() {
  const atoms = Array.from({ length: 12 }, (_, index) => ({
    atom_index: index,
    element: index % 4 === 0 ? "O" : "C",
    label: `A${index}`,
    x: -7.5 + index * 1.36,
    y: index % 2 === 0 ? -3.4 : 3.4,
  }));
  const bonds = atoms.slice(1).map((atom) => ({
    begin_atom_index: atom.atom_index - 1,
    end_atom_index: atom.atom_index,
    order: 1,
  }));
  return { atoms, bonds };
}

const analysis = {
  analysis_id: "analysis-1",
  created_at: "2026-08-27T10:00:00Z",
  catalog_id: "vina_job:job-1",
  engine_key: "vina_job",
  record_id: "job-1",
  engine_label: "AutoDock Vina 1.2.7",
  ligand_id: "ligand-1",
  ligand_preparation_id: "prep-1",
  conformer_id: "conformer-1",
  conformer_sha256: "b".repeat(64),
  pose: {
    artifact_id: "pose-1", kind: "vina_mode", ordinal: 1, label: "Mode 1",
    result_kcal_mol: -8.1, value_label: "Vina score", cluster_rank: null,
    sub_rank: null, rmsd_lower_bound_angstrom: null, rmsd_upper_bound_angstrom: null,
    cluster_rmsd_angstrom: null, reference_rmsd_angstrom: null,
    sha256: "a".repeat(64), content_url: "/pose",
  },
  receptor_id: "receptor-1",
  docking_receptor_artifact_id: "receptor-pdbqt",
  docking_receptor_sha256: "c".repeat(64),
  analysis_receptor_artifact_id: "receptor-pdb",
  analysis_receptor_sha256: "d".repeat(64),
  analysis_receptor_content_url: "/receptor",
  detector: { name: "ProLIF", version: "2.2.1" },
  profile: { profile_id: "ankora-default-v1", vicinity_cutoff_angstrom: 6, interactions: [] },
  contacts: [
    {
      contact_id: "contact-1", detector_type: "Hydrophobic", display_type: "Hydrophobic",
      residue: { chain_id: "A", residue_name: "TRP", sequence_number: 139, insertion_code: "" },
      ligand_atom_indices: [1], protein_atom_indices: [10],
      ligand_atom_labels: ["A1"], protein_atom_labels: ["CZ2"],
      distance_angstrom: 3.7, geometry: { distance: 3.7 },
      ligand_point: null, protein_point: null,
    },
  ],
  ligand_diagram: ligand(),
  warnings: [],
  provenance: {
    event_id: "event-1", event_type: "pose_interactions_analyzed",
    timestamp: "2026-08-27T10:00:00Z", input_artifacts: [], output_artifacts: [],
    tool: { name: "ProLIF", version: "2.2.1" }, parameters: {},
  },
} as unknown as InteractionAnalysisRecord;

function draw() {
  render(
    <InteractionDiagram analysis={analysis} selectedContactId={null} onSelect={() => {}} />,
  );
  return screen.getByRole("img", { name: "2D pose interaction diagram" }) as unknown as SVGSVGElement;
}

function bondSpan(svg: SVGSVGElement): { width: number; height: number } {
  const lines = [...svg.querySelectorAll(".ligand-diagram-bonds line")];
  const xs = lines.flatMap((l) => [Number(l.getAttribute("x1")), Number(l.getAttribute("x2"))]);
  const ys = lines.flatMap((l) => [Number(l.getAttribute("y1")), Number(l.getAttribute("y2"))]);
  return { width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
}

it("draws the ligand across the space the residue ring leaves free", () => {
  // It used to be fitted to a fixed 190px box inside a 640px canvas, which put
  // a 15 Å molecule in an 87px-tall sliver and read as a cut-off drawing.
  const svg = draw();

  const span = bondSpan(svg);
  const box = svg.getAttribute("viewBox")!.split(" ").map(Number);
  expect(span.width / box[2]).toBeGreaterThan(0.4);
});

it("keeps the ligand out from under the residue nodes", () => {
  // The other half of the fit: room taken from the nodes is room the labels
  // needed, and a bond running beneath a node is unreadable either way.
  const svg = draw();
  const nodes = [...svg.querySelectorAll(".interaction-edge ellipse")].map((node) => ({
    x: Number(node.getAttribute("cx")),
    y: Number(node.getAttribute("cy")),
    rx: Number(node.getAttribute("rx")),
    ry: Number(node.getAttribute("ry")),
  }));
  const points = [...svg.querySelectorAll(".ligand-diagram-bonds line")].flatMap((line) => [
    { x: Number(line.getAttribute("x1")), y: Number(line.getAttribute("y1")) },
    { x: Number(line.getAttribute("x2")), y: Number(line.getAttribute("y2")) },
  ]);

  expect(nodes.length).toBeGreaterThan(0);
  for (const node of nodes) {
    for (const point of points) {
      const inside =
        ((point.x - node.x) / node.rx) ** 2 + ((point.y - node.y) / node.ry) ** 2;
      expect(inside).toBeGreaterThan(1);
    }
  }
});

it("spaces the legend so no entry runs into the next", () => {
  // Equal shares only work when the labels are the same length, and
  // `π-stacking / cation–π` is four times `Ionic`.
  const svg = draw();
  const entries = [...svg.querySelectorAll(".interaction-figure-legend text")].map(
    (node) => ({ x: Number(node.getAttribute("x")), text: node.textContent ?? "" }),
  );

  for (let index = 0; index < entries.length - 1; index += 1) {
    const gap = entries[index + 1].x - entries[index].x;
    // 15px Inter runs about 0.52 units per character, plus the next swatch.
    expect(gap).toBeGreaterThan(entries[index].text.length * 0.52 * 15 + 19);
  }
  const last = entries[entries.length - 1];
  const box = svg.getAttribute("viewBox")!.split(" ").map(Number);
  expect(last.x + last.text.length * 0.52 * 15).toBeLessThan(box[2]);
});

it("keeps every bond inside the frame it is exported at", () => {
  const svg = draw();
  const box = svg.getAttribute("viewBox")!.split(" ").map(Number);
  const lines = [...svg.querySelectorAll("line")];
  const xs = lines.flatMap((l) => [Number(l.getAttribute("x1")), Number(l.getAttribute("x2"))]);
  const ys = lines.flatMap((l) => [Number(l.getAttribute("y1")), Number(l.getAttribute("y2"))]);

  expect(Math.min(...xs)).toBeGreaterThanOrEqual(box[0]);
  expect(Math.max(...xs)).toBeLessThanOrEqual(box[0] + box[2]);
  expect(Math.min(...ys)).toBeGreaterThanOrEqual(box[1]);
  expect(Math.max(...ys)).toBeLessThanOrEqual(box[1] + box[3]);
});

it("carries its legend inside the drawing, not beside it", () => {
  // The legend used to be an HTML sibling of the <svg>, so an exported figure
  // showed five colours and explained none of them.
  const svg = draw();

  const legend = svg.querySelector(".interaction-figure-legend")!;
  const labels = [...legend.querySelectorAll("text")].map((node) => node.textContent);
  expect(labels).toEqual(FAMILY_LEGEND.map((entry) => entry.label));

  const swatches = [...legend.querySelectorAll("circle")].map((n) => n.getAttribute("fill"));
  expect(swatches).toEqual(FAMILY_LEGEND.map((entry) => FAMILY_COLOR[entry.family]));
});

it("says inside the drawing why no carbons are labelled", () => {
  // "It is missing atoms" is the reasonable reading of a skeletal formula that
  // does not say it is one.
  const svg = draw();

  const caption = svg.querySelector(".interaction-figure-caption")!;
  expect(caption.textContent).toContain("1 geometric contacts");
  expect(caption.textContent).toContain("carbons and hydrogens implicit");
});

it("survives export with its legend and caption intact", () => {
  const svg = draw();

  const exported = inlineSvg(svg, { background: "#101418" });

  for (const entry of FAMILY_LEGEND) expect(exported).toContain(entry.label);
  expect(exported).toContain("carbons and hydrogens implicit");
  expect(exported).toContain(FAMILY_COLOR.hydrogen);
});

it("colours a contact from the palette the 3D view reads", () => {
  const svg = draw();

  const edge = svg.querySelector(".interaction-edge") as SVGGElement;
  expect(edge.style.stroke).toBe(FAMILY_COLOR.hydrophobic);
});

// --- the heteroatoms have to survive the export ------------------------------

it("carries the property that keeps the halo under the atom label", () => {
  // The coloured letters are drawn with a 5px halo and `paint-order: stroke
  // fill`. Left behind, SVG paints the halo last and every O, N and Cl
  // vanishes inside its own outline - the exported figure looked like a bare
  // skeleton with no heteroatoms at all.
  //
  // Asserted on the carried list rather than on an export: jsdom does not
  // implement `paint-order`, so `getComputedStyle` reports nothing for it here.
  // The rendered result is checked in the running browser instead.
  expect(CARRIED).toContain("paint-order");
  expect(CARRIED).toContain("fill");
  expect(CARRIED).toContain("stroke-width");
});

it("writes colours every SVG renderer can read", () => {
  // Chrome resolves the app's color-mix() halo to CSS Color 4 syntax, which
  // Inkscape and Illustrator do not parse.
  expect(portableColor("color(srgb 1 1 1)")).toBe("rgb(255, 255, 255)");
  expect(portableColor("color(srgb 0 0.5 0.25)")).toBe("rgb(0, 128, 64)");
  expect(portableColor("color(srgb 1 0 0 / 0.5)")).toBe("rgba(255, 0, 0, 0.5)");
  // Anything already portable is left exactly as it was.
  expect(portableColor("rgb(79, 163, 255)")).toBe("rgb(79, 163, 255)");
  expect(portableColor("#4fa3ff")).toBe("#4fa3ff");
});
