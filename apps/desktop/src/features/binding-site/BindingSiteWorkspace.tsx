import { useEffect, useMemo, useRef, useState } from "react";

import { ankoraApi, ApiError } from "../../api/client";
import type {
  BindingBox,
  BindingSiteRequest,
  BindingSiteRecord,
  HeterogenSummary,
  PocketDetectionReport,
  ReceptorPreparationRecord,
  ResidueLocator,
  StructureRecord,
  ToolsResponse,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { DockingBoxInteractionMode, ViewerResidueSelection, ViewerSource } from "../../viewer/adapter";
import { formatScientificNumber } from "../../utils/format";
import { VinaSamplingGuidance } from "../docking/VinaSamplingGuidance";

interface BindingSiteWorkspaceProps {
  structure: StructureRecord;
  receptor: ReceptorPreparationRecord;
  tools: ToolsResponse | null;
  record: BindingSiteRecord | null;
  onRecordChange: (record: BindingSiteRecord) => void;
  onContinue: (record: BindingSiteRecord) => void;
}

type BindingSiteUiSource = "co_crystallized_ligand" | "selected_residues" | "manual" | "full_protein_blind" | "pocket_detected";

export function BindingSiteWorkspace({ structure, receptor, tools, record, onRecordChange, onContinue }: BindingSiteWorkspaceProps) {
  const candidates = structure.metadata.heterogens.filter(
    (item) => item.kind === "ligand" && item.sequence_number !== null,
  );
  const [source, setSource] = useState<BindingSiteUiSource>(record?.decisions.source ?? "full_protein_blind");
  const [selectedHeterogen, setSelectedHeterogen] = useState<HeterogenSummary | null>(
    candidates.length === 1 ? candidates[0] : null,
  );
  const [paddingAngstrom, setPaddingAngstrom] = useState(5.0);
  const [residuePaddingAngstrom, setResiduePaddingAngstrom] = useState(
    record?.decisions.residue_selection?.padding_angstrom ?? 5.0,
  );
  const [selectedResidues, setSelectedResidues] = useState<ResidueLocator[]>(
    record?.decisions.residue_selection?.residues ?? [],
  );
  const [residueSelectionClearSignal, setResidueSelectionClearSignal] = useState(0);
  const [blindMarginAngstrom, setBlindMarginAngstrom] = useState(
    record?.decisions.source === "full_protein_blind" ? record.decisions.blind_margin_angstrom : 6.0,
  );
  const [draftBox, setDraftBox] = useState<BindingBox | null>(record?.box ?? null);
  const [previewRequest, setPreviewRequest] = useState<BindingSiteRequest | null>(record?.decisions ?? null);
  const [previewParentRecordId, setPreviewParentRecordId] = useState<string | null>(record?.binding_site_id ?? null);
  const [pocketReport, setPocketReport] = useState<PocketDetectionReport | null>(null);
  const [selectedPocketId, setSelectedPocketId] = useState<string | null>(null);
  const [boxInteractionMode, setBoxInteractionMode] = useState<DockingBoxInteractionMode>("move");
  const [operation, setOperation] = useState<"previewing" | "finalizing" | "detecting" | null>(null);
  const [fullProteinAcknowledged, setFullProteinAcknowledged] = useState(
    record?.decisions.source === "full_protein_blind",
  );
  const [error, setError] = useState<Error | null>(null);
  const initialPreviewReceptor = useRef<string | null>(null);

  const selectedCandidate = pocketReport?.candidates.find((item) => item.pocket_id === selectedPocketId) ?? null;

  useEffect(() => {
    if (record) {
      setSource(record.decisions.source);
      setDraftBox(record.box);
      setPreviewRequest(record.decisions);
      setPreviewParentRecordId(record.binding_site_id);
      setFullProteinAcknowledged(record.decisions.source === "full_protein_blind");
      if (record.decisions.residue_selection) {
        setSelectedResidues(record.decisions.residue_selection.residues);
        setResiduePaddingAngstrom(record.decisions.residue_selection.padding_angstrom);
      }
    }
  }, [record]);

  useEffect(() => {
    if (record || initialPreviewReceptor.current === receptor.receptor_id) return;
    initialPreviewReceptor.current = receptor.receptor_id;
    void previewFullProtein(6.0);
  }, [receptor.receptor_id, record]);

  useEffect(() => {
    if (!selectedCandidate || !pocketReport) return;
    setDraftBox(selectedCandidate.box);
    setPreviewRequest(pocketRequest(pocketReport.report_id, selectedCandidate.pocket_id));
    setPreviewParentRecordId(null);
  }, [pocketReport, selectedCandidate]);

  const displayOutput = receptor.outputs.find((item) => item.artifact_id === receptor.display_output_artifact_id);
  const viewerSources = useMemo<ViewerSource[]>(() => {
    if (!displayOutput || displayOutput.format !== "pdb") return [];
    return [{
      id: displayOutput.artifact_id,
      url: ankoraApi.receptorOutputUrl(displayOutput.content_url),
      format: "pdb",
      label: `Prepared · ${displayOutput.filename}`,
    }];
  }, [displayOutput]);

  const fullProteinAcknowledgementRequired = Boolean(
    previewRequest?.source === "full_protein_blind" && !previewParentRecordId,
  );
  const canFinalize = Boolean(
    draftBox
    && (previewRequest || previewParentRecordId)
    && (!fullProteinAcknowledgementRequired || fullProteinAcknowledged),
  );

  async function suggestFromHeterogen() {
    if (!selectedHeterogen || selectedHeterogen.sequence_number === null) return;
    await previewBox(
      {
        source: "co_crystallized_ligand",
        ligand_origin: {
          heterogen: {
            chain_id: selectedHeterogen.chain_id,
            residue_name: selectedHeterogen.name,
            sequence_number: selectedHeterogen.sequence_number,
            insertion_code: selectedHeterogen.insertion_code,
          },
          padding_angstrom: paddingAngstrom,
        },
        residue_selection: null,
        manual_box: null,
        blind_margin_angstrom: 6.0,
        pocket_selection: null,
        parent_binding_site_id: null,
      },
      "The box could not be previewed from this ligand.",
    );
  }

  async function createFromSelectedResidues() {
    if (!selectedResidues.length) return;
    await previewBox(
      {
        source: "selected_residues",
        ligand_origin: null,
        residue_selection: {
          residues: selectedResidues,
          padding_angstrom: residuePaddingAngstrom,
        },
        manual_box: null,
        blind_margin_angstrom: 6.0,
        pocket_selection: null,
        parent_binding_site_id: null,
      },
      "The box could not be previewed from these residues.",
    );
  }

  async function previewFullProtein(margin = blindMarginAngstrom) {
    setFullProteinAcknowledged(false);
    await previewBox(
      {
        source: "full_protein_blind",
        ligand_origin: null,
        residue_selection: null,
        manual_box: null,
        blind_margin_angstrom: margin,
        acknowledge_exploratory_full_protein: false,
        pocket_selection: null,
        parent_binding_site_id: null,
      },
      "The full-protein search-space box could not be previewed.",
    );
  }

  async function runPocketDetection() {
    setOperation("detecting");
    setError(null);
    try {
      const next = await ankoraApi.detectPockets(receptor.receptor_id);
      setPocketReport(next);
      setSelectedPocketId(next.candidates[0]?.pocket_id ?? null);
    } catch (reason: unknown) {
      setError(asError(reason, "Pocket detection could not be completed."));
    } finally {
      setOperation(null);
    }
  }

  async function previewBox(request: BindingSiteRequest, fallback: string) {
    setOperation("previewing");
    setError(null);
    try {
      const preview = await ankoraApi.previewBindingSite(receptor.receptor_id, request);
      setDraftBox(preview.box);
      setPreviewRequest(request);
      setPreviewParentRecordId(null);
    } catch (reason: unknown) {
      setError(asError(reason, fallback));
    } finally {
      setOperation(null);
    }
  }

  async function finalizeBindingSite() {
    if (!draftBox) return;
    setOperation("finalizing");
    setError(null);
    try {
      let finalRecord: BindingSiteRecord;
      if (record && previewParentRecordId === record.binding_site_id) {
        finalRecord = boxesEqual(draftBox, record.box)
          ? record
          : await ankoraApi.createBindingSite(
            receptor.receptor_id,
            manualRequest(draftBox, record.binding_site_id),
          );
      } else if (previewRequest?.source === "manual") {
        finalRecord = await ankoraApi.createBindingSite(
          receptor.receptor_id,
          manualRequest(draftBox, null),
        );
      } else if (previewRequest) {
        const confirmedRequest = previewRequest.source === "full_protein_blind"
          ? { ...previewRequest, acknowledge_exploratory_full_protein: true }
          : previewRequest;
        const sourceRecord = await ankoraApi.createBindingSite(receptor.receptor_id, confirmedRequest);
        finalRecord = boxesEqual(draftBox, sourceRecord.box)
          ? sourceRecord
          : await ankoraApi.createBindingSite(
            receptor.receptor_id,
            manualRequest(draftBox, sourceRecord.binding_site_id),
          );
      } else {
        return;
      }
      onRecordChange(finalRecord);
      onContinue(finalRecord);
    } catch (reason: unknown) {
      setError(asError(reason, "The final binding site could not be written."));
    } finally {
      setOperation(null);
    }
  }

  function selectSource(next: BindingSiteUiSource) {
    setSource(next);
    setError(null);
    if (next === "manual") {
      setDraftBox((current) => current ?? DEFAULT_MANUAL_BOX);
      setPreviewRequest(manualRequest(draftBox ?? DEFAULT_MANUAL_BOX, null));
      setPreviewParentRecordId(record?.binding_site_id ?? null);
      return;
    }
    setPreviewParentRecordId(null);
    if (next === "full_protein_blind") {
      void previewFullProtein();
      return;
    }
    if (next === "pocket_detected" && selectedCandidate && pocketReport) {
      setDraftBox(selectedCandidate.box);
      setPreviewRequest(pocketRequest(pocketReport.report_id, selectedCandidate.pocket_id));
      return;
    }
    setPreviewRequest(null);
  }

  function updateDraft(change: Partial<BindingBox>) {
    setDraftBox((current) => ({ ...(current ?? DEFAULT_MANUAL_BOX), ...change }));
  }

  return (
    <>
      <section className="workspace" aria-label="Binding site workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">04 / Binding site</span><h2>Define the docking search space</h2></div>
          <div className="workspace-actions"><span className="read-only-badge">M4 · explicit definition</span></div>
        </div>
        {error ? <div className="structure-error" role="alert">{error.message}</div> : null}
        {viewerSources.length ? (
          <MolecularViewer
            sources={viewerSources}
            selection={null}
            dockingBox={draftBox}
            dockingBoxInteractionMode={boxInteractionMode}
            residueSelectionEnabled={source === "selected_residues"}
            residueSelectionClearSignal={residueSelectionClearSignal}
            onDockingBoxChange={setDraftBox}
            onResidueSelectionChange={(residues: ViewerResidueSelection[]) => setSelectedResidues(residues)}
          />
        ) : (
          <div className="viewer-placeholder ligand-placeholder"><div className="viewer-message"><div className="molecule-glyph">⬚</div><h3>Prepared receptor unavailable</h3><p>This receptor has no PDB-format prepared output to display.</p></div></div>
        )}
      </section>
      <aside className="inspector binding-site-inspector" aria-label="Binding site inspector">
        <div className="inspector-heading"><span className="section-label">Binding site</span><h2>Docking search space</h2><p className="inspector-subtitle">The box is computed in the same coordinate frame as the immutable original structure.</p></div>

        <section className="receptor-section binding-site-source-section">
          <div className="filter-heading"><span>Source</span></div>
          <div className="source-tabs">
            <button type="button" className={source === "co_crystallized_ligand" ? "selected" : ""} onClick={() => selectSource("co_crystallized_ligand")}>Co-crystallized ligand</button>
            <button type="button" className={source === "selected_residues" ? "selected" : ""} onClick={() => selectSource("selected_residues")}>Selected residues</button>
            <button type="button" className={source === "full_protein_blind" ? "selected" : ""} onClick={() => selectSource("full_protein_blind")}>Full protein (blind)</button>
            <button type="button" className={source === "pocket_detected" ? "selected" : ""} onClick={() => selectSource("pocket_detected")}>Detected pocket</button>
            <button type="button" className={source === "manual" ? "selected" : ""} onClick={() => selectSource("manual")}>Manual coordinates</button>
          </div>
          {source === "co_crystallized_ligand" ? <>
            <p className="field-note">Choose the originally co-crystallized ligand. Ankora proposes a box centered on its bounding box, padded on every side — nothing is guessed for you.</p>
            {candidates.length ? <div className="selection-list compact-list">{candidates.map((candidate, index) => {
              const selected = selectedHeterogen === candidate;
              return (
                <button type="button" key={`${candidate.chain_id}-${candidate.name}-${candidate.sequence_number ?? index}`} className={selected ? "selected" : ""} onClick={() => setSelectedHeterogen(candidate)}>
                  <span className="heterogen-dot ligand" /><span><strong>{candidate.name} {candidate.chain_id}:{candidate.sequence_number}</strong><small>{candidate.atom_count} observed atoms</small></span>
                </button>
              );
            })}</div> : <p className="empty-list">No ligand-class heterogen is available in this structure.</p>}
            <label className="numeric-field"><span>Padding around the ligand (Å)</span><input aria-label="Padding around the ligand in angstroms" type="number" min={0} max={20} step={0.5} value={paddingAngstrom} onChange={(event) => setPaddingAngstrom(clampDecimal(event.target.value, 0, 20))} /></label>
            <button type="button" className="apply-plan" disabled={!selectedHeterogen || Boolean(operation)} onClick={() => void suggestFromHeterogen()}>Preview box from this ligand</button>
          </> : null}
          {source === "selected_residues" ? <>
            <p className="field-note">Residue picking is active in the 3D viewer. Click an amino acid to add it; click it again to remove it. Ankora fits the box to every atom of the exact selected residues in the docking-ready receptor.</p>
            <div className="residue-selection-summary" aria-live="polite">
              <div><strong>{selectedResidues.length} selected {selectedResidues.length === 1 ? "residue" : "residues"}</strong><small>{selectedResidues.length ? "Click another amino acid to extend the selection." : "Select at least one amino acid in the viewer."}</small></div>
              {selectedResidues.length ? <div className="selected-residue-chips">{selectedResidues.map((residue) => <span key={residueKey(residue)}>{formatResidue(residue)}</span>)}</div> : null}
            </div>
            <div className="bulk-actions"><button type="button" disabled={!selectedResidues.length} onClick={() => {
              setSelectedResidues([]);
              setResidueSelectionClearSignal((current) => current + 1);
            }}>Clear selection</button></div>
            <label className="numeric-field"><span>Padding around selected residues (Å)</span><input aria-label="Padding around selected residues in angstroms" type="number" min={0} max={20} step={0.5} value={residuePaddingAngstrom} onChange={(event) => setResiduePaddingAngstrom(clampDecimal(event.target.value, 0, 20))} /></label>
            <button type="button" className="apply-plan" disabled={!selectedResidues.length || Boolean(operation)} onClick={() => void createFromSelectedResidues()}>Preview box from selection</button>
          </> : null}
          {source === "full_protein_blind" ? <>
            <p className="field-note protonation-blocker">Searches the entire prepared receptor surface instead of a specific pocket. This is exploratory: the search space — and therefore docking time, especially across multiple engines — grows accordingly. Prefer the co-crystallized ligand or a detected pocket when the binding site is already known.</p>
            <label className="numeric-field"><span>Margin around the receptor (Å)</span><input aria-label="Margin around the receptor in angstroms" type="number" min={0} max={20} step={0.5} value={blindMarginAngstrom} onChange={(event) => setBlindMarginAngstrom(clampDecimal(event.target.value, 0, 20))} /></label>
            <button type="button" className="apply-plan" disabled={Boolean(operation)} onClick={() => void previewFullProtein()}>{operation === "previewing" ? "Computing full-protein box…" : "Recompute full-protein box"}</button>
          </> : null}
          {source === "pocket_detected" ? <>
            <p className="field-note">Runs P2Rank against the prepared receptor and ranks candidate pockets by predicted druggability. Picking one only positions the box — it stays the same editable box as manual mode, and nothing is created until you confirm.</p>
            {!tools?.p2rank?.available ? <p className="protonation-blocker">P2Rank is not configured on this Windows system.</p> : null}
            <button type="button" className="apply-plan" disabled={!tools?.p2rank?.available || Boolean(operation)} onClick={() => void runPocketDetection()}>{operation === "detecting" ? "Detecting pockets…" : pocketReport ? "Detect pockets again" : "Detect pockets with P2Rank"}</button>
            {pocketReport ? (
              pocketReport.candidates.length ? <div className="selection-list compact-list pocket-candidate-list">{pocketReport.candidates.map((candidate) => {
                const selected = candidate.pocket_id === selectedPocketId;
                return (
                  <button type="button" key={candidate.pocket_id} className={selected ? "selected" : ""} onClick={() => setSelectedPocketId(candidate.pocket_id)}>
                    <span>
                      <strong>Pocket {candidate.rank}</strong>
                      <small>{candidate.druggability_score !== null ? `${Math.round(candidate.druggability_score * 100)}% druggability` : "score unavailable"} · {candidate.lining_residues.length} lining residues</small>
                      {candidate.druggability_score !== null ? (
                        <span
                          className="pocket-druggability"
                          data-band={druggabilityBand(candidate.druggability_score)}
                          aria-hidden="true"
                        >
                          <span style={{ width: `${Math.max(2, Math.round(candidate.druggability_score * 100))}%` }} />
                        </span>
                      ) : null}
                    </span>
                  </button>
                );
              })}</div> : <p className="empty-list">P2Rank did not find any candidate pockets on this receptor.</p>
            ) : null}
            <button type="button" className="apply-plan" disabled={!selectedCandidate || Boolean(operation)} onClick={() => {
              if (!selectedCandidate || !pocketReport) return;
              setDraftBox(selectedCandidate.box);
              setPreviewRequest(pocketRequest(pocketReport.report_id, selectedCandidate.pocket_id));
              setPreviewParentRecordId(null);
            }}>Preview this pocket</button>
          </> : null}
          {source === "manual" ? (
            <p className="field-note">Set the box explicitly by center and size, in the same coordinate frame as the immutable original structure. Adjust the numbers below — the view updates live — then create the binding site.</p>
          ) : null}
        </section>

        <section className="receptor-section binding-box-editor-section">
          {record ? <div className="state-resolved-note"><strong>Binding site defined</strong><small>{formatScientificNumber(record.box.size_x, 1)} × {formatScientificNumber(record.box.size_y, 1)} × {formatScientificNumber(record.box.size_z, 1)} Å centered at ({formatScientificNumber(record.box.center_x, 1)}, {formatScientificNumber(record.box.center_y, 1)}, {formatScientificNumber(record.box.center_z, 1)}) · {describeSource(record.decisions.source)}.</small></div> : null}
          <div className="binding-box-mode" role="group" aria-label="Docking box interaction mode">
            <button type="button" className={boxInteractionMode === "move" ? "selected" : ""} aria-pressed={boxInteractionMode === "move"} onClick={() => setBoxInteractionMode("move")}>Move</button>
            <button type="button" className={boxInteractionMode === "resize" ? "selected" : ""} aria-pressed={boxInteractionMode === "resize"} onClick={() => setBoxInteractionMode("resize")}>Resize</button>
          </div>
          <p className="field-note">{boxInteractionMode === "move" ? "Drag the white center to move in the current view plane, or drag the red X, green Y, and blue Z axes for an exact Cartesian translation. Press Esc to cancel a drag." : "Drag any colored ±X, ±Y, or ±Z face handle. The opposite face stays fixed, so center and size update together. Press Esc to cancel a drag."}</p>
          <div className="binding-box-editor">
            <label className="numeric-field"><span>Center X</span><input aria-label="Box center X in angstroms" type="number" step={0.5} value={draftBox?.center_x ?? 0} onChange={(event) => updateDraft({ center_x: Number(event.target.value) })} /></label>
            <label className="numeric-field"><span>Center Y</span><input aria-label="Box center Y in angstroms" type="number" step={0.5} value={draftBox?.center_y ?? 0} onChange={(event) => updateDraft({ center_y: Number(event.target.value) })} /></label>
            <label className="numeric-field"><span>Center Z</span><input aria-label="Box center Z in angstroms" type="number" step={0.5} value={draftBox?.center_z ?? 0} onChange={(event) => updateDraft({ center_z: Number(event.target.value) })} /></label>
            <label className="numeric-field"><span>Size X</span><input aria-label="Box size X in angstroms" type="number" min={0.1} step={0.5} value={draftBox?.size_x ?? 0} onChange={(event) => updateDraft({ size_x: clampDecimal(event.target.value, 0.1, 200) })} /></label>
            <label className="numeric-field"><span>Size Y</span><input aria-label="Box size Y in angstroms" type="number" min={0.1} step={0.5} value={draftBox?.size_y ?? 0} onChange={(event) => updateDraft({ size_y: clampDecimal(event.target.value, 0.1, 200) })} /></label>
            <label className="numeric-field"><span>Size Z</span><input aria-label="Box size Z in angstroms" type="number" min={0.1} step={0.5} value={draftBox?.size_z ?? 0} onChange={(event) => updateDraft({ size_z: clampDecimal(event.target.value, 0.1, 200) })} /></label>
          </div>
          {draftBox ? <div className="binding-box-volume"><span>Search volume</span><strong>{formatVolume(draftBox)} Å³</strong></div> : null}
          {draftBox ? <VinaSamplingGuidance box={draftBox} /> : null}
          {fullProteinAcknowledgementRequired ? (
            <label className="docking-acknowledgement">
              <input
                type="checkbox"
                checked={fullProteinAcknowledged}
                onChange={(event) => setFullProteinAcknowledged(event.target.checked)}
              />
              <span>
                <strong>Acknowledge exploratory full-protein search</strong>
                <small>I understand that this initial whole-receptor box is a blind exploratory search space, not a validated binding-site definition.</small>
              </span>
            </label>
          ) : null}
          <div className="state-resolved-note binding-site-final-note">
            <strong>Final scientific decision</strong>
            <small>This action writes the selected source and exact displayed box as immutable provenance, then opens Docking. Previewing or editing the box does not finalize it.</small>
          </div>
          <button type="button" className="apply-plan" disabled={!canFinalize || Boolean(operation)} onClick={() => void finalizeBindingSite()}>{operation === "finalizing" ? "Writing binding site…" : "Define this binding site and continue to Docking"}</button>
        </section>
      </aside>
    </>
  );
}

const DEFAULT_MANUAL_BOX: BindingBox = { center_x: 0, center_y: 0, center_z: 0, size_x: 20, size_y: 20, size_z: 20 };


/**
 * Four steps of one hue, light to saturated, for P2Rank's druggability.
 *
 * Deliberately not a traffic light. Red-green is the one pairing about eight
 * percent of men cannot separate, and this list is ordered by exactly the value
 * being encoded - they would lose it where it matters most. A red band would
 * also assert a verdict the number does not support: P2Rank's probability ranks
 * candidates against each other, and the best pocket on a hard target can be
 * low-scoring and still be the right one.
 *
 * So the ramp encodes magnitude and nothing else. The percentage stays in text
 * beside it, so the value is never carried by colour alone.
 */
function druggabilityBand(score: number): "low" | "modest" | "fair" | "high" {
  if (score >= 0.5) return "high";
  if (score >= 0.25) return "fair";
  if (score >= 0.1) return "modest";
  return "low";
}
function manualRequest(box: BindingBox, parentBindingSiteId: string | null): BindingSiteRequest {
  return {
    source: "manual",
    ligand_origin: null,
    residue_selection: null,
    manual_box: box,
    blind_margin_angstrom: 6.0,
    pocket_selection: null,
    parent_binding_site_id: parentBindingSiteId,
  };
}

function pocketRequest(reportId: string, pocketId: string): BindingSiteRequest {
  return {
    source: "pocket_detected",
    ligand_origin: null,
    residue_selection: null,
    manual_box: null,
    blind_margin_angstrom: 6.0,
    pocket_selection: { report_id: reportId, pocket_id: pocketId },
    parent_binding_site_id: null,
  };
}

function describeSource(source: BindingSiteRecord["decisions"]["source"]): string {
  if (source === "co_crystallized_ligand") return "from co-crystallized ligand";
  if (source === "selected_residues") return "from selected residues";
  if (source === "full_protein_blind") return "blind search over the full receptor";
  if (source === "pocket_detected") return "from a detected pocket";
  return "manually defined";
}

function residueKey(residue: ResidueLocator): string {
  return `${residue.chain_id}|${residue.residue_name}|${residue.sequence_number}|${residue.insertion_code}`;
}

function formatResidue(residue: ResidueLocator): string {
  return `${residue.residue_name} ${residue.chain_id}:${residue.sequence_number}${residue.insertion_code}`;
}

function boxesEqual(a: BindingBox | null, b: BindingBox | null): boolean {
  if (!a || !b) return a === b;
  return (
    a.center_x === b.center_x
    && a.center_y === b.center_y
    && a.center_z === b.center_z
    && a.size_x === b.size_x
    && a.size_y === b.size_y
    && a.size_z === b.size_z
  );
}

function formatVolume(box: BindingBox): string {
  return formatScientificNumber(box.size_x * box.size_y * box.size_z, {
    maximumFractionDigits: 1,
    groupThousands: true,
  });
}

function asError(reason: unknown, fallback: string): Error {
  if (reason instanceof ApiError) return reason;
  return reason instanceof Error ? reason : new Error(fallback);
}

function clampDecimal(value: string, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
}
