import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ankoraApi } from "../../api/client";
import { formatApplicationDateTime, formatScientificNumber } from "../../utils/format";
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
import { displayedContacts, groupContacts, residueKey } from "./interactionPresentation";
import type { InteractionDetail } from "./interactionPresentation";

interface PoseInteractionPanelProps {
  entry: CatalogEntry;
  molecule: CompoundRow;
  onClose: () => void;
}

interface LocalRefinementSummary {
  refinementId: string;
  engine: "vina" | "gnina";
  headline: { label: string; value: number; unit: string };
  breakdown: { label: string; value: number | null | undefined }[];
  poseComplexIdentitySha256: string | null;
}

export function PoseInteractionPanel({ entry, molecule, onClose }: PoseInteractionPanelProps) {
  const [inventory, setInventory] = useState<PoseInventory | null>(null);
  const [selectedPoseId, setSelectedPoseId] = useState<string | null>(null);
  const [analyses, setAnalyses] = useState<InteractionAnalysisRecord[]>([]);
  const [analysis, setAnalysis] = useState<InteractionAnalysisRecord | null>(null);
  const [selectedContact, setSelectedContact] = useState<InteractionContact | null>(null);
  const [contactType, setContactType] = useState("");
  const [detail, setDetail] = useState<InteractionDetail>("summary");
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Off by default: the coupled complex is the honest single picture of a
  // flexible pose, and the overlay is an explicit comparison against it.
  const [overlayCrystalRotamers, setOverlayCrystalRotamers] = useState(false);
  const [refinement, setRefinement] = useState<LocalRefinementSummary | null>(null);
  const [refining, setRefining] = useState(false);
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
    setRefinement(null);
    setOverlayCrystalRotamers(false);
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

  // Reset before the new analysis can be painted or clicked. A deferred effect
  // could otherwise overwrite a user's choice immediately after it appeared.
  useLayoutEffect(() => {
    setContactType("");
    setDetail("summary");
  }, [analysis?.analysis_id]);

  const visibleContacts = useMemo(
    () => (analysis?.contacts ?? []).filter((contact) => !contactType || contact.detector_type === contactType),
    [analysis, contactType],
  );
  const visibleSelectedContact = selectedContact && visibleContacts.some(
    (contact) => contact.contact_id === selectedContact.contact_id,
  ) ? selectedContact : null;
  const positionedContacts = useMemo(
    () => visibleContacts.filter((contact) => contact.ligand_point && contact.protein_point),
    [visibleContacts],
  );
  const contactTypes = useMemo(() => {
    const types = new Map<string, { label: string; count: number }>();
    for (const contact of analysis?.contacts ?? []) {
      const previous = types.get(contact.detector_type);
      types.set(contact.detector_type, { label: contact.display_type, count: (previous?.count ?? 0) + 1 });
    }
    return [...types].sort(([left], [right]) => left.localeCompare(right));
  }, [analysis]);

  const pose = inventory?.poses.find((item) => item.artifact_id === selectedPoseId) ?? null;
  const coupledFlexPose = isCoupledFlexPose(pose);
  const localRefinementEngine: "vina" | "gnina" | null =
    entry.engine_key === "vina_job"
      ? "vina"
      : entry.engine_key === "gnina_job"
        ? "gnina"
        : null;
  const viewerSources = useMemo(
    () => sourcesFor(inventory, pose, {
      catalogId: entry.catalog_id,
      ligandId: molecule.ligand_id,
      overlayCrystalRotamers: overlayCrystalRotamers && coupledFlexPose,
    }),
    [inventory, pose, entry.catalog_id, molecule.ligand_id, overlayCrystalRotamers, coupledFlexPose],
  );
  /**
   * The contacts the viewer draws, positioned by the detector rather than here.
   *
   * An analysis recorded before Ankora kept 3D endpoints has none, and no
   * endpoint is guessed for it: the panel says so instead.
   */
  const viewerContacts: ViewerContact[] = useMemo(
    () => displayedContacts(positionedContacts, detail, visibleSelectedContact?.contact_id ?? null).flatMap((contact) => {
      if (!contact.ligand_point || !contact.protein_point) return [];
      return [{
        contactId: contact.contact_id,
        family: interactionFamily(contact.detector_type),
        label: `${contact.display_type} · ${residueLabel(contact)}`
          + (contact.distance_angstrom === null
            ? ""
            : ` · ${formatScientificNumber(contact.distance_angstrom, 2)} Å`),
        ligandPoint: [
          contact.ligand_point.x, contact.ligand_point.y, contact.ligand_point.z,
        ] as [number, number, number],
        proteinPoint: [
          contact.protein_point.x, contact.protein_point.y, contact.protein_point.z,
        ] as [number, number, number],
      }];
    }),
    [positionedContacts, detail, visibleSelectedContact?.contact_id],
  );
  const contactsWithoutGeometry = visibleContacts.length - positionedContacts.length;

  const viewerSelection: ViewerSelection | null = visibleSelectedContact ? {
    kind: "residue",
    residue: {
      chainId: visibleSelectedContact.residue.chain_id,
      residueName: visibleSelectedContact.residue.residue_name,
      sequenceNumber: visibleSelectedContact.residue.sequence_number,
      insertionCode: visibleSelectedContact.residue.insertion_code,
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

  /**
   * Create one `--local_only` refinement derivative of this exact pose.
   *
   * This is a create-only action (ADR-004 / ADR-005): the parent job and the
   * parent pose keep their recorded coordinates and scores, and the result is
   * a new record with its own identity. A local minimization is not a new
   * search, so its energy must not be read as a re-docking result.
   */
  async function refineLocalOnly() {
    if (!pose || !localRefinementEngine) return;
    setRefining(true);
    setError(null);
    try {
      const request = { parent_job_id: entry.record_id, parent_pose_artifact_id: pose.artifact_id };
      if (localRefinementEngine === "vina") {
        const record = await ankoraApi.refineVinaPoseLocalOnly(request);
        setRefinement({
          refinementId: record.refinement_id,
          engine: "vina",
          headline: {
            label: "Minimized free energy",
            value: record.estimated_free_energy_kcal_mol,
            unit: "kcal/mol",
          },
          breakdown: [
            { label: "Intermolecular", value: record.intermolecular_kcal_mol },
            { label: "Total internal", value: record.total_internal_kcal_mol },
            { label: "Torsional free energy", value: record.torsional_free_energy_kcal_mol },
            { label: "Unbound system", value: record.unbound_system_energy_kcal_mol },
          ],
          poseComplexIdentitySha256: record.refined_pose.pose_complex_identity_sha256 ?? null,
        });
      } else {
        const record = await ankoraApi.refineGninaPoseLocalOnly(request);
        setRefinement({
          refinementId: record.refinement_id,
          engine: "gnina",
          headline: {
            label: "Minimized affinity",
            value: record.minimized_affinity_kcal_mol,
            unit: "kcal/mol",
          },
          breakdown: [
            { label: "CNN score", value: record.cnn_score },
            { label: "CNN affinity", value: record.cnn_affinity },
            { label: "CNN VS", value: record.cnn_vs },
          ],
          poseComplexIdentitySha256: record.refined_pose.pose_complex_identity_sha256 ?? null,
        });
      }
    } catch (reason: unknown) {
      setError(message(reason, "The local-only refinement could not be created."));
    } finally {
      setRefining(false);
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
                  {item.label} · {item.kind === "gnina_mode" ? `CNN score ${formatScientificNumber(item.cnn_score ?? null, 4)} · CNN affinity ${formatScientificNumber(item.cnn_affinity_pk ?? null, 3)} pK · minimized affinity ` : ""}{formatScientificNumber(item.result_kcal_mol, 3)} kcal/mol
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
                    {formatApplicationDateTime(item.created_at)} · {item.detector.name} {item.detector.version}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button type="button" className="primary-button" disabled={!pose || analyzing} onClick={analyze}>
            {analyzing ? "Analyzing with ProLIF…" : analysis ? "Create another analysis" : "Analyze this pose with ProLIF"}
          </button>
          {localRefinementEngine ? (
            <button
              type="button"
              className="quiet-button"
              disabled={!pose || refining}
              onClick={refineLocalOnly}
            >
              {refining ? "Refining locally (--local_only)…" : "Refine locally (--local_only)"}
            </button>
          ) : null}
          {coupledFlexPose ? (
            <label className="check-row pose-flex-overlay-toggle">
              <input
                type="checkbox"
                checked={overlayCrystalRotamers}
                onChange={(event) => setOverlayCrystalRotamers(event.target.checked)}
              />
              <span>
                <strong>Overlay crystal rotamers (translucent reference)</strong>
                <small>
                  Default view shows the coupled FlexRes complex with moved side chains; enable
                  this toggle to compare against the original prepared crystal rotamers.
                </small>
              </span>
            </label>
          ) : null}
        </div>
      ) : null}

      {coupledFlexPose && pose ? (
        <div className="pose-flex-identity-banner" role="status">
          <strong>Coupled FlexRes complex (E8)</strong>
          {pose.pose_complex_identity_sha256 ? (
            <span>Complex SHA-256 <code>{pose.pose_complex_identity_sha256.slice(0, 12)}…</code></span>
          ) : null}
          {pose.pose_flex_sidechains_sha256 ? (
            <span>Moved side chains <code>{pose.pose_flex_sidechains_sha256.slice(0, 12)}…</code></span>
          ) : null}
        </div>
      ) : null}

      {refinement ? (
        <div className="local-refinement-result" role="status" aria-label="Local-only refinement derivative">
          <strong>
            Create-only --local_only derivative ({refinement.engine === "vina" ? "AutoDock Vina" : "GNINA"})
          </strong>
          <p className="field-note">
            Parent job and pose remain immutable. A local minimization is not a new search and
            must not be compared as a re-docked global pose.
          </p>
          <dl>
            <div><dt>Derivative ID</dt><dd><code>{refinement.refinementId}</code></dd></div>
            <div>
              <dt>{refinement.headline.label}</dt>
              <dd>{formatScientificNumber(refinement.headline.value, 3)} {refinement.headline.unit}</dd>
            </div>
            {refinement.breakdown
              .filter((item) => item.value !== null && item.value !== undefined)
              .map((item) => (
                <div key={item.label}>
                  <dt>{item.label}</dt>
                  <dd>{formatScientificNumber(item.value ?? null, 3)}</dd>
                </div>
              ))}
            {refinement.poseComplexIdentitySha256 ? (
              <div>
                <dt>Coupled complex SHA-256</dt>
                <dd><code>{refinement.poseComplexIdentitySha256.slice(0, 12)}…</code></dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}

      {analysis ? (
        <div className="interaction-presentation-controls" role="region" aria-label="Interaction display">
          <div className="interaction-display-counts" role="status">
            <strong>{visibleContacts.length} / {analysis.contacts.length} atom contacts</strong>
            <span>{new Set(visibleContacts.map(residueKey)).size} residues · {groupContacts(visibleContacts).length} residue/subtype groups</span>
          </div>
          <label>
            Interaction type
            <select value={contactType} onChange={(event) => {
              setContactType(event.target.value);
              setSelectedContact(null);
            }}>
              <option value="">All types ({analysis.contacts.length})</option>
              {contactTypes.map(([type, item]) => <option key={type} value={type}>{item.label} ({item.count})</option>)}
            </select>
          </label>
          <div className="interaction-detail-switch" role="group" aria-label="Contact detail">
            <button type="button" aria-pressed={detail === "summary"} onClick={() => setDetail("summary")}>Residue summary</button>
            <button type="button" aria-pressed={detail === "all"} onClick={() => setDetail("all")}>All atom contacts</button>
          </div>
          <p>
            {detail === "summary"
              ? "2D and 3D show one recorded contact per residue/subtype: the shortest distance, or the selected contact. ×N counts retain every atom contact."
              : "2D and 3D draw every recorded atom contact; coincident lines can overlap."}
            {" "}The table lists every contact matching the type filter. These are geometric contacts, not independent bonds or an affinity score.
          </p>
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
                    ? `${viewerContacts.length} displayed / ${positionedContacts.length} positioned contacts · receptor shown as context`
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
                selectedContactId={visibleSelectedContact?.contact_id ?? null}
                handleRef={viewerHandleRef}
              />
            </div>
            <div className="pose-interaction-saving">
              <div className="filter-heading"><span>Save this view</span></div>
              {analysis && contactsWithoutGeometry > 0 ? (
                <p className="field-note">
                  {contactsWithoutGeometry} of {visibleContacts.length} filtered contacts were
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
                  contacts={visibleContacts}
                  detail={detail}
                  selectedContactId={visibleSelectedContact?.contact_id ?? null}
                  onSelect={setSelectedContact}
                  svgRef={diagramSvgRef}
                />
                <InteractionTable
                  contacts={visibleContacts}
                  filtered={!!contactType}
                  selectedContactId={visibleSelectedContact?.contact_id ?? null}
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
                    {analysis.pose_flex_sidechains_sha256 ? (
                      <div><dt>Moved side-chains SHA-256</dt><dd><code>{analysis.pose_flex_sidechains_sha256}</code></dd></div>
                    ) : null}
                    {analysis.pose_complex_identity_sha256 ? (
                      <div><dt>Coupled complex SHA-256</dt><dd><code>{analysis.pose_complex_identity_sha256}</code></dd></div>
                    ) : null}
                    {analysis.materialized_coupled_receptor_sha256 ? (
                      <div><dt>Materialized receptor PDB SHA-256</dt><dd><code>{analysis.materialized_coupled_receptor_sha256}</code></dd></div>
                    ) : null}
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

function InteractionTable({ contacts, filtered, selectedContactId, onSelect }: {
  contacts: InteractionContact[];
  filtered: boolean;
  selectedContactId: string | null;
  onSelect: (contact: InteractionContact) => void;
}) {
  const [sort, setSort] = useState<InteractionSort>({ key: "residue", direction: "asc" });
  if (contacts.length === 0) {
    return (
      <div className="state-resolved-note">
        <strong>{filtered ? "No contacts match this view filter." : "No supported contacts met this recorded profile."}</strong>
        <small>{filtered ? "Choose All types to see the full record." : "This does not mean the ligand has no interactions."}</small>
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
              <td>{contact.distance_angstrom === null ? "—" : `${formatScientificNumber(contact.distance_angstrom, 2)} Å`}</td>
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
  return entries
    .map(([key, value]) => `${key.replaceAll("_", " ")} ${formatScientificNumber(value, 1)}°`)
    .join(" · ");
}

/** A pose produced against a FlexRes receptor carries moved side chains. */
export function isCoupledFlexPose(pose: PoseReference | null): boolean {
  return Boolean(pose?.pose_flex_sidechains_sha256);
}

interface PoseSourceOptions {
  catalogId: string;
  ligandId: string;
  /** Show the crystal rotamers behind the moved side chains (ADR-032 §4 E8). */
  overlayCrystalRotamers: boolean;
}

/**
 * The structures the viewer loads for one pose.
 *
 * A rigid pose keeps the frozen v0.1 pairing: prepared receptor as context
 * plus the ligand pose. A flexible pose is a *coupled complex*, so by default
 * it loads the deterministically materialized complex — the rigid receptor,
 * the moved side chains and the ligand as one document — rather than drawing
 * the ligand against a receptor whose pocket rotamers it never had. Showing
 * only the rigid crystal receptor there would misstate the result.
 */
function sourcesFor(
  inventory: PoseInventory | null,
  pose: PoseReference | null,
  options: PoseSourceOptions,
): ViewerSource[] {
  if (!inventory || !pose) return [];
  const crystalReceptor = inventory.receptor_content_url && inventory.receptor_artifact_id
    ? {
      id: inventory.receptor_artifact_id,
      url: ankoraApi.receptorOutputUrl(inventory.receptor_content_url),
      format: "pdb" as const,
      label: "Exact prepared receptor",
    }
    : null;
  // PDBQT retains PDB coordinate columns; Mol* uses the compatible parser only for display.
  const ligandPose: ViewerSource = {
    id: pose.artifact_id,
    url: ankoraApi.dockingPoseUrl(pose.content_url),
    format: "pdb",
    label: pose.label,
    appearance: "interaction-ligand",
  };

  if (!isCoupledFlexPose(pose)) {
    return crystalReceptor
      ? [{ ...crystalReceptor, appearance: "interaction-context" }, ligandPose]
      : [ligandPose];
  }

  if (options.overlayCrystalRotamers) {
    // Crystal rotamers translucent behind the moved side chains, so what the
    // search actually moved — and how far — is visible rather than inferred.
    return [
      ...(crystalReceptor
        ? [{
          ...crystalReceptor,
          label: "Crystal rotamers (reference)",
          appearance: "flex-crystal-reference" as const,
        }]
        : []),
      ...(pose.flex_content_url
        ? [{
          id: `${pose.artifact_id}-flex`,
          url: ankoraApi.dockingPoseUrl(pose.flex_content_url),
          format: "pdb" as const,
          label: "Moved side chains",
          appearance: "flex-moved-sidechains" as const,
        }]
        : []),
      ligandPose,
    ];
  }

  return [{
    id: `${pose.artifact_id}-complex`,
    url: ankoraApi.poseComplexUrl(options.catalogId, options.ligandId, pose.artifact_id),
    format: "pdb",
    label: "Coupled FlexRes complex",
  }];
}

export function residueLabel(contact: InteractionContact): string {
  const residue = contact.residue;
  return `${residue.residue_name} ${residue.chain_id || "∅"}:${residue.sequence_number}${residue.insertion_code}`;
}

function message(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
