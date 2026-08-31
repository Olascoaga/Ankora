import { useEffect, useMemo, useRef, useState } from "react";

import { ankoraApi } from "../../api/client";
import type {
  CatalogEntry,
  CompoundRow,
  InteractionAnalysisRecord,
  InteractionContact,
  PoseInventory,
  PoseReference,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { MolecularViewerHandle } from "../../viewer/MolecularViewer";
import type { ViewerContact, ViewerSelection, ViewerSource } from "../../viewer/adapter";
import { FigureExportControls } from "./FigureExportControls";
import { PoseComplexExportControls } from "./PoseComplexExportControls";
import {
  DIAGRAM_ASPECT_RATIO,
  InteractionDiagram,
  interactionFamily,
} from "./InteractionDiagram";
import { inlineSvg } from "./figureRendering";

interface PoseInteractionPanelProps {
  entry: CatalogEntry;
  molecule: CompoundRow;
  onClose: () => void;
}

export function PoseInteractionPanel({ entry, molecule, onClose }: PoseInteractionPanelProps) {
  const [inventory, setInventory] = useState<PoseInventory | null>(null);
  const [selectedPoseId, setSelectedPoseId] = useState<string | null>(null);
  const [analyses, setAnalyses] = useState<InteractionAnalysisRecord[]>([]);
  const [analysis, setAnalysis] = useState<InteractionAnalysisRecord | null>(null);
  const [selectedContact, setSelectedContact] = useState<InteractionContact | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const analysisGeneration = useRef(0);
  const diagramSvgRef = useRef<SVGSVGElement | null>(null);
  const viewerHandleRef = useRef<MolecularViewerHandle | null>(null);
  const viewerHostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    setInventory(null);
    setAnalyses([]);
    setAnalysis(null);
    setSelectedContact(null);
    void ankoraApi.listResultPoses(entry.catalog_id, molecule.ligand_id)
      .then((next) => {
        if (disposed) return;
        setInventory(next);
        setSelectedPoseId(next.poses[0]?.artifact_id ?? null);
      })
      .catch((reason: unknown) => {
        if (!disposed) setError(message(reason, "The preserved poses could not be read."));
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [entry.catalog_id, molecule.ligand_id]);

  useEffect(() => {
    if (!selectedPoseId) return;
    let disposed = false;
    const generation = ++analysisGeneration.current;
    setAnalyses([]);
    setAnalysis(null);
    setSelectedContact(null);
    setError(null);
    void ankoraApi.listPoseInteractionAnalyses(
      entry.catalog_id, molecule.ligand_id, selectedPoseId,
    ).then((records) => {
      if (!disposed && generation === analysisGeneration.current) {
        // A history request can finish in the same event turn as creation.
        // An empty history response must never erase the newly created record.
        setAnalyses((current) => records.length ? records : current);
        setAnalysis((current) => records[0] ?? current);
      }
    }).catch((reason: unknown) => {
      if (!disposed) setError(message(reason, "Prior interaction analyses could not be read."));
    });
    return () => { disposed = true; };
  }, [entry.catalog_id, molecule.ligand_id, selectedPoseId]);

  const pose = inventory?.poses.find((item) => item.artifact_id === selectedPoseId) ?? null;
  const viewerSources = useMemo(
    () => sourcesFor(inventory, pose),
    [inventory, pose],
  );
  /**
   * The contacts the viewer draws, positioned by the detector rather than here.
   *
   * An analysis recorded before Ankora kept 3D endpoints has none, and no
   * endpoint is guessed for it: the panel says so instead.
   */
  const viewerContacts: ViewerContact[] = useMemo(
    () => (analysis?.contacts ?? []).flatMap((contact) => {
      if (!contact.ligand_point || !contact.protein_point) return [];
      return [{
        contactId: contact.contact_id,
        family: interactionFamily(contact.detector_type),
        label: `${contact.display_type} · ${residueLabel(contact)}`
          + (contact.distance_angstrom === null
            ? ""
            : ` · ${contact.distance_angstrom.toFixed(2)} Å`),
        ligandPoint: [
          contact.ligand_point.x, contact.ligand_point.y, contact.ligand_point.z,
        ] as [number, number, number],
        proteinPoint: [
          contact.protein_point.x, contact.protein_point.y, contact.protein_point.z,
        ] as [number, number, number],
      }];
    }),
    [analysis],
  );
  const contactsWithoutGeometry = analysis
    ? analysis.contacts.length - viewerContacts.length
    : 0;

  const viewerSelection: ViewerSelection | null = selectedContact ? {
    kind: "residue",
    residue: {
      chainId: selectedContact.residue.chain_id,
      residueName: selectedContact.residue.residue_name,
      sequenceNumber: selectedContact.residue.sequence_number,
      insertionCode: selectedContact.residue.insertion_code,
    },
  } : null;

  function renderDiagramSvg(): string {
    const element = diagramSvgRef.current;
    if (!element) throw new Error("The diagram is not on screen to be saved.");
    // Painted onto the surface it is currently drawn on, so the exported file
    // is the figure that was approved rather than dark text on nothing.
    const surface = getComputedStyle(document.body).backgroundColor;
    return inlineSvg(element, { background: surface || "#ffffff" });
  }

  function viewerAspectRatio(): number {
    const host = viewerHostRef.current;
    if (!host || !host.clientHeight) return 16 / 10;
    return host.clientWidth / host.clientHeight;
  }

  async function captureViewer(
    geometry: { widthPx: number; heightPx: number },
  ): Promise<string> {
    const handle = viewerHandleRef.current;
    if (!handle) throw new Error("The 3D view is not ready to be saved.");
    return handle.captureImage({
      width: geometry.widthPx,
      height: geometry.heightPx,
      transparent: false,
    });
  }

  async function analyze() {
    if (!pose) return;
    // A slower history request for the same pose must not replace the new
    // immutable record after this action completes.
    analysisGeneration.current += 1;
    setAnalyzing(true);
    setError(null);
    try {
      const next = await ankoraApi.analyzePoseInteractions(
        entry.catalog_id, molecule.ligand_id, pose.artifact_id,
      );
      setAnalyses((current) => [next, ...current.filter((item) => item.analysis_id !== next.analysis_id)]);
      setAnalysis(next);
      setSelectedContact(next.contacts[0] ?? null);
    } catch (reason: unknown) {
      setError(message(reason, "The pose interaction analysis could not be completed."));
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <section className="pose-interaction-panel" aria-label={`Pose interactions for ${molecule.name}`}>
      <header className="pose-interaction-heading">
        <div>
          <span className="eyebrow">Pose interaction analysis</span>
          <h3>{molecule.name}</h3>
          <p>Geometric contacts for one exact preserved pose — not measured affinity.</p>
        </div>
        <button type="button" className="quiet-button" onClick={onClose}>Close</button>
      </header>

      {loading ? <p className="field-note">Reading preserved poses…</p> : null}
      {error ? <div className="structure-error" role="alert">{error}</div> : null}
      {inventory && inventory.poses.length === 0 ? (
        <div className="state-resolved-note">
          <strong>No pose artifact is available.</strong>
          <small>The molecule remains in the result record, but there is no geometry to analyze.</small>
        </div>
      ) : null}

      {inventory?.poses.length ? (
        <div className="pose-interaction-controls">
          <label>
            Exact pose / run
            <select
              value={selectedPoseId ?? ""}
              onChange={(event) => setSelectedPoseId(event.target.value)}
            >
              {inventory.poses.map((item) => (
                <option key={item.artifact_id} value={item.artifact_id}>
                  {item.label} · {item.result_kcal_mol.toFixed(3)} kcal/mol
                </option>
              ))}
            </select>
          </label>
          <div className="pose-interaction-identity">
            <span>{inventory.engine_label}</span>
            <code>{pose?.sha256.slice(0, 12)}…</code>
          </div>
          {analyses.length ? (
            <label>
              Recorded analysis
              <select
                value={analysis?.analysis_id ?? ""}
                onChange={(event) => {
                  const next = analyses.find((item) => item.analysis_id === event.target.value) ?? null;
                  setAnalysis(next);
                  setSelectedContact(next?.contacts[0] ?? null);
                }}
              >
                {analyses.map((item) => (
                  <option key={item.analysis_id} value={item.analysis_id}>
                    {new Date(item.created_at).toLocaleString()} · {item.detector.name} {item.detector.version}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button type="button" className="primary-button" disabled={!pose || analyzing} onClick={analyze}>
            {analyzing ? "Analyzing with ProLIF…" : analysis ? "Create another analysis" : "Analyze this pose with ProLIF"}
          </button>
        </div>
      ) : null}

      {pose && viewerSources.length ? (
        <div className="pose-interaction-review-grid">
          <div className="pose-interaction-viewer-column">
            <div className="pose-interaction-viewer-heading">
              <div>
                <strong>3D interaction site</strong>
                <small>
                  {viewerContacts.length
                    ? `${viewerContacts.length} recorded contact${viewerContacts.length === 1 ? "" : "s"} · receptor shown as context`
                    : "Exact pose with the prepared receptor"}
                </small>
              </div>
              <button
                type="button"
                className="quiet-button"
                disabled={!viewerContacts.length}
                onClick={() => viewerHandleRef.current?.focusInteractionRegion()}
              >
                Center on interaction site
              </button>
            </div>
            <div
              className="pose-interaction-viewer"
              aria-label="Selected pose in 3D"
              ref={viewerHostRef}
            >
              <MolecularViewer
                sources={viewerSources}
                selection={viewerSelection}
                interactionContacts={viewerContacts}
                selectedContactId={selectedContact?.contact_id ?? null}
                handleRef={viewerHandleRef}
              />
            </div>
            <div className="pose-interaction-saving">
              <div className="filter-heading"><span>Save this view</span></div>
              {analysis && contactsWithoutGeometry > 0 ? (
                <p className="field-note">
                  {contactsWithoutGeometry} of {analysis.contacts.length} contacts were
                  recorded before Ankora kept their 3D positions, so they are listed but
                  not drawn. Running the analysis again records them.
                </p>
              ) : null}
              <FigureExportControls
                source="pose_view_3d"
                aspectRatio={viewerAspectRatio()}
                captureRaster={(geometry) => captureViewer(geometry)}
                catalogId={entry.catalog_id}
                ligandId={molecule.ligand_id}
                moleculeName={molecule.name}
                poseArtifactId={pose.artifact_id}
                poseLabel={pose.label}
                analysisId={analysis?.analysis_id ?? null}
              />
              <PoseComplexExportControls
                catalogId={entry.catalog_id}
                ligandId={molecule.ligand_id}
                moleculeName={molecule.name}
                poseArtifactId={pose.artifact_id}
              />
            </div>
          </div>
          <div className="pose-interaction-evidence">
            {analysis ? (
              <>
                <InteractionDiagram
                  analysis={analysis}
                  selectedContactId={selectedContact?.contact_id ?? null}
                  onSelect={setSelectedContact}
                  svgRef={diagramSvgRef}
                />
                <InteractionTable
                  contacts={analysis.contacts}
                  selectedContactId={selectedContact?.contact_id ?? null}
                  onSelect={setSelectedContact}
                />
                <footer className="pose-interaction-provenance">
                  <span>{analysis.detector.name} {analysis.detector.version}</span>
                  <span>{analysis.profile.profile_id}</span>
                  <code>{analysis.analysis_id}</code>
                </footer>
                {analysis.warnings.length ? (
                  <div className="interaction-warnings" role="status">
                    <strong>Analysis warnings</strong>
                    <ul>{analysis.warnings.map((warning, index) => (
                      <li key={`${warning.code}-${index}`}>{warning.message}</li>
                    ))}</ul>
                  </div>
                ) : null}
                <div className="pose-interaction-saving">
                  <div className="filter-heading"><span>Save this diagram</span></div>
                  <FigureExportControls
                    source="interaction_diagram"
                    aspectRatio={DIAGRAM_ASPECT_RATIO}
                    renderSvg={renderDiagramSvg}
                    catalogId={entry.catalog_id}
                    ligandId={molecule.ligand_id}
                    moleculeName={molecule.name}
                    poseArtifactId={pose.artifact_id}
                    poseLabel={pose.label}
                    analysisId={analysis.analysis_id}
                  />
                </div>
                <details className="pose-interaction-technical">
                  <summary>Exact analysis evidence</summary>
                  <dl>
                    <div><dt>Analysis</dt><dd><code>{analysis.analysis_id}</code></dd></div>
                    <div><dt>Pose SHA-256</dt><dd><code>{analysis.pose.sha256}</code></dd></div>
                    <div><dt>Docking receptor SHA-256</dt><dd><code>{analysis.docking_receptor_sha256}</code></dd></div>
                    <div><dt>Analysis receptor SHA-256</dt><dd><code>{analysis.analysis_receptor_sha256}</code></dd></div>
                    <div><dt>Conformer SHA-256</dt><dd><code>{analysis.conformer_sha256}</code></dd></div>
                    <div><dt>Detector profile</dt><dd>{analysis.profile.profile_id} · {analysis.profile.vicinity_cutoff_angstrom} Å vicinity</dd></div>
                  </dl>
                </details>
              </>
            ) : (
              <div className="viewer-placeholder interaction-placeholder">
                <div className="viewer-message">
                  <div className="molecule-glyph">⌬</div>
                  <h3>No analysis recorded for {pose.label}</h3>
                  <p>
                    Ankora will validate the exact receptor, minimized conformer, and pose
                    hashes before ProLIF calculates supported geometric contacts.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function InteractionTable({ contacts, selectedContactId, onSelect }: {
  contacts: InteractionContact[];
  selectedContactId: string | null;
  onSelect: (contact: InteractionContact) => void;
}) {
  const [sort, setSort] = useState<InteractionSort>({ key: "residue", direction: "asc" });
  if (contacts.length === 0) {
    return (
      <div className="state-resolved-note">
        <strong>No supported contacts met this recorded profile.</strong>
        <small>This does not mean the ligand has no interactions.</small>
      </div>
    );
  }
  const ordered = [...contacts].sort((left, right) => compareContacts(left, right, sort));
  const header = (label: string, key: InteractionSortKey) => (
    <button type="button" onClick={() => setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }))}>
      {label}{sort.key === key ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}
    </button>
  );
  return (
    <div className="interaction-table-scroll" role="region" tabIndex={0} aria-label="Pose interaction evidence">
      <table>
        <thead><tr>
          <th>{header("Type", "type")}</th>
          <th>{header("Residue", "residue")}</th>
          <th>{header("Distance", "distance")}</th>
          <th>{header("Angle", "angle")}</th>
          <th>{header("Ligand atoms", "ligandAtoms")}</th>
          <th>{header("Protein atoms", "proteinAtoms")}</th>
        </tr></thead>
        <tbody>
          {ordered.map((contact) => (
            <tr
              key={contact.contact_id}
              className={contact.contact_id === selectedContactId ? "selected" : ""}
              onClick={() => onSelect(contact)}
            >
              <td><button type="button" onClick={() => onSelect(contact)}>{contact.display_type}</button></td>
              <td>{residueLabel(contact)}</td>
              <td>{contact.distance_angstrom === null ? "—" : `${contact.distance_angstrom.toFixed(2)} Å`}</td>
              <td>{angleLabel(contact)}</td>
              <td>{contact.ligand_atom_labels.join(", ") || "—"}</td>
              <td>{contact.protein_atom_labels.join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type InteractionSortKey = "type" | "residue" | "distance" | "angle" | "ligandAtoms" | "proteinAtoms";
interface InteractionSort { key: InteractionSortKey; direction: "asc" | "desc" }

function compareContacts(left: InteractionContact, right: InteractionContact, sort: InteractionSort): number {
  const values: Record<InteractionSortKey, [string | number, string | number]> = {
    type: [left.display_type, right.display_type],
    residue: [residueLabel(left), residueLabel(right)],
    distance: [left.distance_angstrom ?? Number.POSITIVE_INFINITY, right.distance_angstrom ?? Number.POSITIVE_INFINITY],
    angle: [firstAngle(left) ?? Number.POSITIVE_INFINITY, firstAngle(right) ?? Number.POSITIVE_INFINITY],
    ligandAtoms: [left.ligand_atom_labels.join(", "), right.ligand_atom_labels.join(", ")],
    proteinAtoms: [left.protein_atom_labels.join(", "), right.protein_atom_labels.join(", ")],
  };
  const [a, b] = values[sort.key];
  const compared = typeof a === "number" && typeof b === "number"
    ? a - b
    : String(a).localeCompare(String(b), undefined, { numeric: true });
  return sort.direction === "asc" ? compared : -compared;
}

function angleEntries(contact: InteractionContact): [string, number][] {
  return Object.entries(contact.geometry)
    .filter(([key]) => key.toLowerCase().includes("angle"))
    .sort(([left], [right]) => left.localeCompare(right));
}

function firstAngle(contact: InteractionContact): number | null {
  return angleEntries(contact)[0]?.[1] ?? null;
}

function angleLabel(contact: InteractionContact): string {
  const entries = angleEntries(contact);
  if (!entries.length) return "—";
  return entries.map(([key, value]) => `${key.replaceAll("_", " ")} ${value.toFixed(1)}°`).join(" · ");
}

function sourcesFor(inventory: PoseInventory | null, pose: PoseReference | null): ViewerSource[] {
  if (!inventory || !pose) return [];
  const sources: ViewerSource[] = [];
  if (inventory.receptor_content_url && inventory.receptor_artifact_id) {
    sources.push({
      id: inventory.receptor_artifact_id,
      url: ankoraApi.receptorOutputUrl(inventory.receptor_content_url),
      format: "pdb",
      label: "Exact prepared receptor",
      appearance: "interaction-context",
    });
  }
  sources.push({
    id: pose.artifact_id,
    url: ankoraApi.dockingPoseUrl(pose.content_url),
    // PDBQT retains PDB coordinate columns; Mol* uses the compatible parser only for display.
    format: "pdb",
    label: pose.label,
    appearance: "interaction-ligand",
  });
  return sources;
}

export function residueLabel(contact: InteractionContact): string {
  const residue = contact.residue;
  return `${residue.residue_name} ${residue.chain_id || "∅"}:${residue.sequence_number}${residue.insertion_code}`;
}

function message(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
