import { useEffect, useMemo, useState } from "react";

import { ankoraApi, ApiError } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import { formatScientificNumber } from "../../utils/format";
import type {
  ComponentAction,
  ProtonationOverride,
  ReceptorDecisionAction,
  ReceptorInspectionReport,
  ReceptorIssue,
  ReceptorPreparationRecord,
  ReceptorPreparationRequest,
  ReceptorProtonationAnalysis,
  ResidueLocator,
  StructureRecord,
  TerminalHeavyAtomAddition,
  ToolsResponse,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { ViewerSelection, ViewerSource } from "../../viewer/adapter";

type ViewMode = "original" | "prepared" | "overlay";
type IssueFilter = "all" | "near" | "blocking" | "undecided" | "affected";

interface LocalIssueDecision {
  action?: ReceptorDecisionAction;
  selectedAltloc?: string;
}

interface ReceptorWorkspaceProps {
  structure: StructureRecord;
  initialRecord: ReceptorPreparationRecord | null;
  tools: ToolsResponse | null;
  selection: ViewerSelection | null;
  onSelect: (selection: ViewerSelection | null) => void;
  onRecordChange: (record: ReceptorPreparationRecord | null) => void;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
}

export function ReceptorWorkspace({
  structure,
  initialRecord,
  tools,
  selection,
  onSelect,
  onRecordChange,
  onActivityChange,
}: ReceptorWorkspaceProps) {
  const [report, setReport] = useState<ReceptorInspectionReport | null>(null);
  const restoredRecord = initialRecord?.source_artifact_id === structure.artifact.artifact_id ? initialRecord : null;
  const [referenceComponentId, setReferenceComponentId] = useState<string | null>(restoredRecord?.decisions.reference_component_id ?? null);
  const [selectedChains, setSelectedChains] = useState<string[]>(restoredRecord?.decisions.selected_chains ?? []);
  const [waterAction, setWaterAction] = useState<ComponentAction | null>(restoredRecord?.decisions.water_action ?? null);
  const [componentActions, setComponentActions] = useState<Record<string, ComponentAction>>(() => componentDecisionMap(restoredRecord));
  const [issueDecisions, setIssueDecisions] = useState<Record<string, LocalIssueDecision>>(() => issueDecisionMap(restoredRecord));
  const [relax, setRelax] = useState(restoredRecord?.decisions.relaxation.enabled ?? false);
  const [restraintForceConstant, setRestraintForceConstant] = useState(
    restoredRecord?.decisions.relaxation.restraint_force_constant_kcal_mol_a2 ?? 50.0,
  );
  const [relaxationMaxIterations, setRelaxationMaxIterations] = useState(
    restoredRecord?.decisions.relaxation.max_iterations ?? 200,
  );
  const [protonate, setProtonate] = useState(restoredRecord?.decisions.protonation.enabled ?? false);
  const [ph, setPh] = useState(restoredRecord?.decisions.protonation.ph ?? 7.4);
  const [authorizedTerminalAdditions, setAuthorizedTerminalAdditions] = useState<TerminalHeavyAtomAddition[]>(
    restoredRecord?.decisions.protonation.authorized_terminal_heavy_atom_additions ?? [],
  );
  const [generatePdbqt, setGeneratePdbqt] = useState(restoredRecord?.decisions.generate_pdbqt ?? false);
  const [protonationPreview, setProtonationPreview] = useState<{
    signature: string;
    analysis: ReceptorProtonationAnalysis;
  } | null>(() => restoredProtonationPreview(restoredRecord));
  const [protonationOverrides, setProtonationOverrides] = useState<Record<string, string>>(
    () => protonationOverrideMap(restoredRecord),
  );
  const [record, setRecord] = useState<ReceptorPreparationRecord | null>(restoredRecord);
  const [operation, setOperation] = useState<"inspecting" | "idle" | "analyzing" | "applying">("inspecting");
  const [error, setError] = useState<Error | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(restoredRecord ? "prepared" : "original");
  const [issueFilter, setIssueFilter] = useState<IssueFilter>("all");

  useEffect(() => {
    const restored = initialRecord?.source_artifact_id === structure.artifact.artifact_id ? initialRecord : null;
    setSelectedChains(restored?.decisions.selected_chains ?? []);
    setWaterAction(restored?.decisions.water_action ?? null);
    setComponentActions(componentDecisionMap(restored));
    setIssueDecisions(issueDecisionMap(restored));
    setReferenceComponentId(restored?.decisions.reference_component_id ?? null);
    setRelax(restored?.decisions.relaxation.enabled ?? false);
    setRestraintForceConstant(restored?.decisions.relaxation.restraint_force_constant_kcal_mol_a2 ?? 50.0);
    setRelaxationMaxIterations(restored?.decisions.relaxation.max_iterations ?? 200);
    setProtonate(restored?.decisions.protonation.enabled ?? false);
    setPh(restored?.decisions.protonation.ph ?? 7.4);
    setAuthorizedTerminalAdditions(
      restored?.decisions.protonation.authorized_terminal_heavy_atom_additions ?? [],
    );
    setGeneratePdbqt(restored?.decisions.generate_pdbqt ?? false);
    setProtonationPreview(restoredProtonationPreview(restored));
    setProtonationOverrides(protonationOverrideMap(restored));
    setRecord(restored);
    setViewMode(restored ? "prepared" : "original");
    onRecordChange(restored);
  }, [initialRecord, structure.artifact.artifact_id, onRecordChange]);

  useEffect(() => {
    let active = true;
    setOperation("inspecting");
    setError(null);
    void ankoraApi.inspectReceptor(structure.artifact.artifact_id, referenceComponentId)
      .then((nextReport) => {
        if (active) {
          setReport(nextReport);
          setOperation("idle");
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason : new Error("Receptor inspection failed"));
          setOperation("idle");
        }
      });
    return () => { active = false; };
  }, [referenceComponentId, structure.artifact.artifact_id]);

  useEffect(() => {
    if (meekoAffectedResidues(error).length) setIssueFilter("affected");
  }, [error]);

  useEffect(() => {
    if (!onActivityChange) return;
    if (operation === "idle") onActivityChange(null);
    else onActivityChange({
      title: operation === "inspecting"
        ? "Inspecting receptor"
        : operation === "analyzing"
          ? "Analyzing protonation"
          : "Preparing receptor",
      detail: operation === "inspecting"
        ? "Building the read-only component and structural-issue report."
        : operation === "analyzing"
          ? "Running the exact structural plan through PROPKA for residue-level review."
        : "Applying the confirmed plan and preserving every generated artifact.",
    });
    return () => onActivityChange(null);
  }, [onActivityChange, operation]);

  const selectedComponents = report?.components.filter((item) => selectedChains.includes(item.chain_id)) ?? [];
  const selectedIssues = report?.issues.filter((item) => selectedChains.includes(item.residue.chain_id)) ?? [];
  const plannedRepairCount = selectedIssues.filter((issue) => issueDecisions[issue.issue_id]?.action === "repair").length;
  const protonationBlockingIssues = protonate ? selectedIssues.filter((issue) => {
    const action = issueDecisions[issue.issue_id]?.action;
    return action === "leave" && ["missing_atoms", "alternate_location", "nonstandard_residue"].includes(issue.kind);
  }) : [];
  const repairableProtonationBlockers = protonationBlockingIssues.filter((issue) => (
    issue.kind === "missing_atoms" && issue.allowed_actions.includes("repair")
  ));
  const removableProtonationBlockers = protonationBlockingIssues.filter((issue) => issue.allowed_actions.includes("remove"));
  const affectedResidues = meekoAffectedResidues(error);
  const proposedTerminalAdditions = terminalHeavyAtomAdditions(error);
  const meekoAffectedIssues = selectedIssues.filter((issue) => (
    issue.allowed_actions.includes("remove")
    && affectedResidues.some((residue) => sameResidue(issue.residue, residue))
  ));
  const affectedIssueIds = new Set(meekoAffectedIssues.map((issue) => issue.issue_id));
  const filteredIssues = selectedIssues.filter((issue) => {
    if (issueFilter === "near") return issue.severity === "near_reference";
    if (issueFilter === "blocking") return protonationBlockingIssues.some((item) => item.issue_id === issue.issue_id);
    if (issueFilter === "undecided") {
      const action = issueDecisions[issue.issue_id]?.action;
      return !action || action === "manual_review";
    }
    if (issueFilter === "affected") return affectedIssueIds.has(issue.issue_id);
    return true;
  });
  const meekoRecoveryApplied = meekoAffectedIssues.length > 0
    && meekoAffectedIssues.every((issue) => issueDecisions[issue.issue_id]?.action === "remove");
  const structuralPlanComplete = selectedChains.length > 0
    && waterAction !== null
    && selectedComponents.every((item) => componentActions[item.component_id] !== undefined)
    && selectedIssues.every((issue) => {
      const decision = issueDecisions[issue.issue_id];
      if (!decision?.action || decision.action === "manual_review") return false;
      return issue.kind !== "alternate_location"
        || decision.action !== "repair"
        || Boolean(decision.selectedAltloc);
    })
    && protonationBlockingIssues.length === 0
    && (!relax || plannedRepairCount > 0);

  function buildRequest(overrides: ProtonationOverride[]): ReceptorPreparationRequest | null {
    if (!report || !waterAction || !structuralPlanComplete) return null;
    return {
      selected_chains: selectedChains,
      water_action: waterAction,
      component_decisions: selectedComponents.map((component) => ({
        component_id: component.component_id,
        action: componentActions[component.component_id],
      })),
      issue_decisions: selectedIssues.map((issue) => ({
        issue_id: issue.issue_id,
        action: issueDecisions[issue.issue_id].action!,
        selected_altloc: issueDecisions[issue.issue_id].selectedAltloc ?? null,
      })),
      reference_component_id: referenceComponentId,
      relaxation: {
        enabled: relax,
        restraint_force_constant_kcal_mol_a2: restraintForceConstant,
        max_iterations: relaxationMaxIterations,
      },
      protonation: {
        enabled: protonate,
        ph,
        force_field: "AMBER",
        authorized_terminal_heavy_atom_additions: authorizedTerminalAdditions,
        overrides,
      },
      generate_pdbqt: protonate && generatePdbqt,
    };
  }

  const unsignedRequest = buildRequest([]);
  const protonationSignature = unsignedRequest ? protonationPlanSignature(unsignedRequest) : null;
  const activeProtonationAnalysis = protonationPreview?.signature === protonationSignature
    ? protonationPreview.analysis
    : null;
  const planComplete = structuralPlanComplete && (!protonate || activeProtonationAnalysis !== null);

  const displayOutput = record?.outputs.find((item) => item.artifact_id === record.display_output_artifact_id);
  const removedIssueCount = record?.decisions.issue_decisions.filter((item) => item.action === "remove").length ?? 0;
  const repairedIssueCount = record?.decisions.issue_decisions.filter((item) => item.action === "repair").length ?? 0;
  const removedComponentCount = record?.decisions.component_decisions.filter((item) => item.action === "remove").length ?? 0;
  const viewerSources = useMemo<ViewerSource[]>(() => {
    const original: ViewerSource = {
      id: structure.artifact.artifact_id,
      url: ankoraApi.structureContentUrl(structure),
      format: structure.artifact.format,
      label: `Original · ${structure.artifact.original_filename}`,
    };
    if (!displayOutput || displayOutput.format !== "pdb" || viewMode === "original") return [original];
    const prepared: ViewerSource = {
      id: displayOutput.artifact_id,
      url: ankoraApi.receptorOutputUrl(displayOutput.content_url),
      format: "pdb",
      label: `Prepared · ${displayOutput.filename}`,
    };
    return viewMode === "prepared" ? [prepared] : [original, prepared];
  }, [displayOutput, structure, viewMode]);

  function toggleChain(chainId: string) {
    setSelectedChains((current) => current.includes(chainId)
      ? current.filter((item) => item !== chainId)
      : [...current, chainId]);
  }

  function setAllIssues(action: ReceptorDecisionAction) {
    setIssueDecisions((current) => {
      const next = { ...current };
      for (const issue of selectedIssues) next[issue.issue_id] = { action };
      return next;
    });
  }

  function resolveProtonationBlockers(issueIds: string[], action: "repair" | "remove") {
    const selectedIssueIds = new Set(issueIds);
    setIssueDecisions((current) => {
      const next = { ...current };
      for (const issue of protonationBlockingIssues) {
        if (selectedIssueIds.has(issue.issue_id)) next[issue.issue_id] = { action };
      }
      return next;
    });
  }

  function removeMeekoAffectedResidues() {
    setIssueDecisions((current) => {
      const next = { ...current };
      for (const issue of meekoAffectedIssues) next[issue.issue_id] = { action: "remove" };
      return next;
    });
  }

  function authorizeProposedTerminalAdditions() {
    setAuthorizedTerminalAdditions((current) => {
      const byIdentity = new Map(
        current.map((item) => [terminalAdditionIdentity(item), item]),
      );
      for (const item of proposedTerminalAdditions) {
        byIdentity.set(terminalAdditionIdentity(item), item);
      }
      return [...byIdentity.values()];
    });
  }

  async function applyPlan() {
    if (!planComplete || !activeProtonationAnalysis && protonate) return;
    const overrides = activeProtonationAnalysis?.proposals.flatMap((proposal) => {
      const state = protonationOverrides[proposal.proposal_id] ?? proposal.default_state;
      return state === proposal.default_state ? [] : [{ residue: proposal.residue, state }];
    }) ?? [];
    const request = buildRequest(overrides);
    if (!request) return;
    setOperation("applying");
    setError(null);
    try {
      const nextRecord = await ankoraApi.prepareReceptor(structure.artifact.artifact_id, request);
      setRecord(nextRecord);
      onRecordChange(nextRecord);
      setViewMode("prepared");
      if (nextRecord.protonation_analysis) {
        setProtonationPreview({
          signature: protonationPlanSignature(nextRecord.decisions),
          analysis: nextRecord.protonation_analysis,
        });
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason : new Error("Receptor preparation failed"));
    } finally {
      setOperation("idle");
    }
  }

  async function analyzeProtonation() {
    if (!structuralPlanComplete) return;
    const request = buildRequest([]);
    if (!request || !protonationSignature) return;
    setOperation("analyzing");
    setError(null);
    try {
      const analysis = await ankoraApi.previewReceptorProtonation(
        structure.artifact.artifact_id,
        request,
      );
      setProtonationOverrides({});
      setProtonationPreview({ signature: protonationSignature, analysis });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason : new Error("Protonation analysis failed"));
    } finally {
      setOperation("idle");
    }
  }

  return (
    <>
      <section className="workspace" aria-label="Receptor workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">02 / Receptor</span><h2>Inspect, decide, apply, review</h2></div>
          <div className="workspace-actions">
            <span className="read-only-badge">M2 · explicit preparation</span>
            {displayOutput ? <div className="view-switch" aria-label="Receptor comparison mode">
              {(["original", "prepared", "overlay"] as const).map((mode) => (
                <button
                  type="button"
                  key={mode}
                  className={viewMode === mode ? "selected" : ""}
                  title={viewModeTitle(mode)}
                  onClick={() => setViewMode(mode)}
                >{mode[0].toUpperCase() + mode.slice(1)}</button>
              ))}
            </div> : null}
          </div>
        </div>
        {operation !== "idle" ? <div className="operation-progress" role="progressbar"><span /><p>{operation === "inspecting" ? "Building the read-only receptor report…" : operation === "analyzing" ? "Computing residue-level pKa proposals for review…" : "Applying explicit decisions and preserving every output…"}</p></div> : null}
        {error ? <ReceptorErrorNotice
          error={error}
          affectedIssues={meekoAffectedIssues}
          recoveryApplied={meekoRecoveryApplied}
          onRemoveAffected={removeMeekoAffectedResidues}
          proposedTerminalAdditions={proposedTerminalAdditions}
          authorizedTerminalAdditions={authorizedTerminalAdditions}
          onAuthorizeTerminalAdditions={authorizeProposedTerminalAdditions}
        /> : null}
        <div className="scientific-workbench receptor-workbench">
          <div className="viewer-pane">
            {displayOutput ? <div className={`viewer-mode-notice ${viewMode}`} role="status">
              <strong>{viewModeLabel(viewMode)}</strong>
              <span>{viewModeDescription(viewMode, displayOutput.filename)}</span>
            </div> : null}
            <MolecularViewer sources={viewerSources} selection={selection} />
          </div>
          <section className="data-panel receptor-issues-panel" aria-label="Structural issues workbench">
            <div className="data-panel-heading">
              <div><span className="section-label">Structural issues</span><strong>{selectedIssues.length} selected-chain observations</strong></div>
              <div className="issue-summary-chips"><span className="danger">{selectedIssues.filter((item) => item.severity === "near_reference").length} near pocket</span><span className="warning">{protonationBlockingIssues.length} blocking</span><span>{selectedIssues.filter((item) => !issueDecisions[item.issue_id]?.action || issueDecisions[item.issue_id]?.action === "manual_review").length} unresolved</span></div>
            </div>
            <div className="data-panel-toolbar">
              <div className="filter-tabs" aria-label="Issue filters">
                {(["all", "near", "blocking", "undecided", "affected"] as const).map((filter) => <button type="button" key={filter} className={issueFilter === filter ? "selected" : ""} disabled={filter === "affected" && !affectedIssueIds.size} onClick={() => setIssueFilter(filter)}>{issueFilterLabel(filter)}</button>)}
              </div>
              <div className="bulk-actions"><button type="button" onClick={() => setAllIssues("leave")}>Explicitly leave all</button><button type="button" onClick={() => setAllIssues("manual_review")}>Mark all for review</button></div>
            </div>
            <div className="receptor-table-scroll">
              <table className="receptor-issues-table">
                <thead><tr><th>Residue</th><th>Issue</th><th>Distance</th><th>Severity</th><th>Decision</th></tr></thead>
                <tbody>{filteredIssues.map((issue) => {
                  const decision = issueDecisions[issue.issue_id] ?? {};
                  return <tr key={issue.issue_id} className={`${issue.severity}${affectedIssueIds.has(issue.issue_id) ? " connectivity-failure" : ""}`}>
                    <td><button type="button" className="residue-focus" onClick={() => onSelect({ kind: "residue", residue: { chainId: issue.residue.chain_id, residueName: issue.residue.residue_name, sequenceNumber: issue.residue.sequence_number, insertionCode: issue.residue.insertion_code } })}><strong>{issue.residue.residue_name}</strong><span>{issue.residue.chain_id}:{issue.residue.sequence_number}{issue.residue.insertion_code}</span></button></td>
                    <td><strong>{issue.kind.replaceAll("_", " ")}</strong><small>{issue.message}</small></td>
                    <td>{formatDistanceCompact(issue.distance_to_reference_angstrom)}</td>
                    <td><span className={`severity-badge ${issue.severity}`}>{severityLabel(issue.severity)}</span></td>
                    <td><select aria-label={`Decision for ${issue.residue.residue_name} ${issue.residue.sequence_number}`} value={decision.action ?? ""} onChange={(event) => setIssueDecisions((current) => ({ ...current, [issue.issue_id]: { action: event.target.value as ReceptorDecisionAction } }))}>
                      <option value="">Decision required</option>
                      {issue.allowed_actions.map((action) => <option key={action} value={action}>{decisionLabel(action, issue.kind)}</option>)}
                    </select>{issue.kind === "alternate_location" && decision.action === "repair" ? <div className="altloc-actions">{issue.alternate_locations.map((label) => <button type="button" key={label} className={decision.selectedAltloc === label ? "selected" : ""} onClick={() => setIssueDecisions((current) => ({ ...current, [issue.issue_id]: { action: "repair", selectedAltloc: label } }))}>Use {label}</button>)}</div> : null}</td>
                  </tr>;
                })}</tbody>
              </table>
              {!filteredIssues.length ? <div className="data-panel-empty">No structural issues match this filter.</div> : null}
            </div>
          </section>
        </div>
      </section>

      <aside className="inspector receptor-inspector" aria-label="Receptor inspector">
        <div className="inspector-heading"><span className="section-label">Receptor plan</span><h2>{structure.metadata.entry_id ?? structure.artifact.original_filename}</h2><p className="inspector-subtitle">No decision is applied until you confirm the complete plan.</p></div>
        {!report ? <p className="empty-list">Generating inspection report…</p> : <>
          <ReceptorSection title="1 · Pocket reference">
            <label className="field-label" htmlFor="reference-component">Reference component</label>
            <select id="reference-component" value={referenceComponentId ?? ""} onChange={(event) => setReferenceComponentId(event.target.value || null)}>
              <option value="">None · distances unassessed</option>
              {report.components.map((component) => <option value={component.component_id} key={component.component_id}>{component.name} {component.chain_id}:{component.sequence_number ?? "?"}</option>)}
            </select>
            <p className="field-note">A reference only classifies distances; it does not define a docking box.</p>
          </ReceptorSection>

          <ReceptorSection title="2 · Polymer chains">
            <div className="decision-grid">{report.candidate_chains.map((chainId) => <button type="button" key={chainId} className={selectedChains.includes(chainId) ? "selected" : ""} onClick={() => { toggleChain(chainId); onSelect({ kind: "chain", chainId }); }}>Chain {chainId || "∅"}</button>)}</div>
          </ReceptorSection>

          <ReceptorSection title="3 · Components">
            <DecisionRow label={`Resolved waters (${report.water_count})`} value={waterAction} onChange={setWaterAction} />
            {selectedComponents.map((component) => <DecisionRow key={component.component_id} label={`${component.name} ${component.chain_id}:${component.sequence_number ?? "?"} · ${component.kind}`} value={componentActions[component.component_id] ?? null} onChange={(action) => setComponentActions((current) => ({ ...current, [component.component_id]: action }))} />)}
            {!selectedChains.length ? <p className="empty-list">Choose at least one chain to inspect its components.</p> : null}
          </ReceptorSection>

          <ReceptorSection title={`4 · Structural issues (${selectedIssues.length})`}>
            <div className="issue-plan-summary"><div><strong>{selectedIssues.length - selectedIssues.filter((item) => !issueDecisions[item.issue_id]?.action || issueDecisions[item.issue_id]?.action === "manual_review").length}</strong><span>decided</span></div><div><strong>{selectedIssues.filter((item) => !issueDecisions[item.issue_id]?.action || issueDecisions[item.issue_id]?.action === "manual_review").length}</strong><span>unresolved</span></div><div><strong>{protonationBlockingIssues.length}</strong><span>blocking</span></div></div>
            <p className="field-note">Use the workbench table beneath the molecular viewer to filter, inspect in 3D, and decide every residue.</p>
          </ReceptorSection>

          <ReceptorSection title="5 · Relax reconstructed atoms">
            <p className="field-note">PDBFixer places missing side-chain atoms from ideal geometry, without checking for steric overlap with neighbors. This optional step relaxes only the newly-added atoms against a repulsive potential; every previously observed atom stays restrained within 0.5 Å of its original position.</p>
            <label className="check-row"><input type="checkbox" checked={relax} disabled={!plannedRepairCount} onChange={(event) => setRelax(event.target.checked)} /><span><strong>Relax repaired residues with OpenMM</strong><small>{toolLabel(tools?.pdbfixer)}</small></span></label>
            {!plannedRepairCount ? <p className="field-note">No residue is marked Repair yet — nothing to relax until one is.</p> : null}
            {relax ? <>
              <label className="numeric-field">Restraint force constant (kcal/mol/Å²)<input type="number" min="1" step="1" value={restraintForceConstant} onChange={(event) => setRestraintForceConstant(Number(event.target.value))} /></label>
              <label className="numeric-field">Maximum iterations<input type="number" min="1" max="5000" step="10" value={relaxationMaxIterations} onChange={(event) => setRelaxationMaxIterations(Number(event.target.value))} /></label>
            </> : null}
          </ReceptorSection>

          <ReceptorSection title="6 · Hydrogens & docking format">
            <label className="check-row"><input type="checkbox" checked={protonate} onChange={(event) => { setProtonate(event.target.checked); if (!event.target.checked) { setGeneratePdbqt(false); setAuthorizedTerminalAdditions([]); } }} /><span><strong>Run PDB2PQR + PROPKA</strong><small>{toolLabel(tools?.pdb2pqr)} · {toolLabel(tools?.propka)}</small></span></label>
            {protonate ? <label className="numeric-field">Target pH<input type="number" min="0" max="14" step="0.1" value={ph} onChange={(event) => setPh(Number(event.target.value))} /></label> : null}
            {authorizedTerminalAdditions.length ? <div className="protonation-blocker authorized-terminal-additions" role="status">
              <strong>{authorizedTerminalAdditions.length} exact terminal heavy-atom addition{authorizedTerminalAdditions.length === 1 ? "" : "s"} authorized.</strong>
              <ul>{authorizedTerminalAdditions.map((item) => <li key={terminalAdditionIdentity(item)}>{item.atom_name} · {item.residue_name} {item.chain_id}:{item.sequence_number}{item.insertion_code}</li>)}</ul>
              <small>Only these identities may be added by PDB2PQR; every other heavy-atom change remains a hard failure.</small>
            </div> : null}
            <label className="check-row"><input type="checkbox" checked={generatePdbqt} disabled={!protonate} onChange={(event) => setGeneratePdbqt(event.target.checked)} /><span><strong>Generate receptor PDBQT with Meeko</strong><small>{toolLabel(tools?.meeko)}</small></span></label>
            <p className="field-note">PDBFixer is invoked only for residues explicitly marked Repair. {toolLabel(tools?.pdbfixer)}</p>
            {protonationBlockingIssues.length ? <div className="protonation-blocker" role="alert">
              <strong>{protonationBlockingIssues.length} observed residue issue{protonationBlockingIssues.length === 1 ? "" : "s"} must be resolved before protonation.</strong>
              <p>Choose an explicit bulk action below, edit residues individually, or disable protonation to preserve “Leave unchanged”. Bulk actions only fill the plan; nothing is applied until you confirm it.</p>
              <ul>{protonationBlockingIssues.slice(0, 6).map((issue) => <li key={issue.issue_id}>{issue.residue.residue_name} {issue.residue.chain_id}:{issue.residue.sequence_number} · {issue.kind.replaceAll("_", " ")}</li>)}</ul>
              {protonationBlockingIssues.length > 6 ? <small>+ {protonationBlockingIssues.length - 6} more</small> : null}
              <div className="protonation-blocker-actions">
                {repairableProtonationBlockers.length ? <button type="button" onClick={() => resolveProtonationBlockers(repairableProtonationBlockers.map((issue) => issue.issue_id), "repair")}>Repair {repairableProtonationBlockers.length} missing-atom residue{repairableProtonationBlockers.length === 1 ? "" : "s"} with PDBFixer</button> : null}
                {removableProtonationBlockers.length ? <button type="button" className="remove" onClick={() => resolveProtonationBlockers(removableProtonationBlockers.map((issue) => issue.issue_id), "remove")}>Remove {removableProtonationBlockers.length} blocking residue{removableProtonationBlockers.length === 1 ? "" : "s"}</button> : null}
                <button type="button" onClick={() => { setProtonate(false); setGeneratePdbqt(false); }}>Disable protonation</button>
              </div>
            </div> : null}
            {protonate && !protonationBlockingIssues.length ? <>
              <button
                type="button"
                className="protonation-analysis-action"
                disabled={!structuralPlanComplete || operation !== "idle"}
                onClick={() => void analyzeProtonation()}
              >{activeProtonationAnalysis ? "Refresh pKa proposals" : "Analyze pKa proposals"}</button>
              <p className="field-note">This review runs the exact chain, component, repair, relaxation, force-field, and pH plan in an isolated workspace. The final derivative reruns and records its own evidence.</p>
            </> : null}
            {protonate && activeProtonationAnalysis ? <div className="protonation-analysis" role="region" aria-label="PROPKA protonation proposals">
              <div className="protonation-analysis-summary">
                <strong>{activeProtonationAnalysis.proposals.length} pKa proposals</strong>
                <span>{activeProtonationAnalysis.proposals.filter((item) => item.near_reference).length} near reference</span>
                <span>{activeProtonationAnalysis.proposals.filter((item) => item.nearby_metals.length).length} near metals</span>
                <span>{Object.keys(protonationOverrides).length} overrides</span>
              </div>
              <p className="field-note">PROPKA predicts; the selected state is Ankora's recorded decision. Amber-incompatible states remain visible as warnings but cannot be selected.</p>
              <div className="protonation-proposal-list">
                {activeProtonationAnalysis.proposals.map((proposal) => {
                  const selectedState = protonationOverrides[proposal.proposal_id] ?? proposal.default_state;
                  return <article className={`protonation-proposal ${proposal.warnings.length ? "attention" : ""}`} key={proposal.proposal_id}>
                    <div className="protonation-proposal-heading">
                      <button type="button" className="residue-focus" onClick={() => onSelect({ kind: "residue", residue: { chainId: proposal.residue.chain_id, residueName: proposal.residue.residue_name, sequenceNumber: proposal.residue.sequence_number, insertionCode: proposal.residue.insertion_code } })}>
                        <strong>{proposal.group_label}</strong>
                        <span>pKa {formatScientificNumber(proposal.predicted_pka, 2)} · pH {formatScientificNumber(activeProtonationAnalysis.target_ph, 1)}</span>
                      </button>
                      <span className="protonation-prediction">PROPKA {protonationStateLabel(proposal.predicted_state)}</span>
                    </div>
                    <select
                      aria-label={`Protonation decision for ${proposal.group_label}`}
                      value={selectedState}
                      disabled={proposal.allowed_states.length < 2}
                      onChange={(event) => setProtonationOverrides((current) => {
                        const next = { ...current };
                        if (event.target.value === proposal.default_state) delete next[proposal.proposal_id];
                        else next[proposal.proposal_id] = event.target.value;
                        return next;
                      })}
                    >
                      {proposal.allowed_states.map((state) => <option value={state} key={state}>{state === proposal.default_state ? "Use tool default · " : "Override · "}{protonationStateLabel(state)}</option>)}
                    </select>
                    <div className="protonation-proposal-flags">
                      {proposal.default_state !== proposal.predicted_state ? <span className="warning">Amber limitation</span> : null}
                      {proposal.near_reference ? <span>Near reference · {formatDistanceCompact(proposal.distance_to_reference_angstrom)}</span> : null}
                      {proposal.nearby_metals.map((metal) => <span className="warning" key={metal.component_id}>Near {metal.name} · {formatScientificNumber(metal.distance_angstrom, 1)} Å</span>)}
                      {proposal.warnings.includes("PKA_NEAR_TARGET_PH") ? <span className="warning">pKa near target pH</span> : null}
                      {proposal.coupled_group ? <span>Coupled · {proposal.coupled_group}</span> : null}
                    </div>
                  </article>;
                })}
              </div>
              <small className="protonation-evidence">{activeProtonationAnalysis.tool_version} · input {activeProtonationAnalysis.input_sha256.slice(0, 12)}…</small>
            </div> : null}
          </ReceptorSection>

          <button type="button" className="apply-plan" disabled={!planComplete || operation !== "idle"} onClick={() => void applyPlan()}>{record ? "Create another immutable derivative" : "Apply explicit preparation plan"}</button>
          {!structuralPlanComplete && protonationBlockingIssues.length === 0 && (!relax || plannedRepairCount > 0) ? <p className="plan-status">Complete every chain, component, and residue decision to continue.</p> : null}
          {structuralPlanComplete && protonate && !activeProtonationAnalysis ? <p className="plan-status">Review the PROPKA pKa proposals before creating the receptor derivative.</p> : null}
          {!planComplete && relax && plannedRepairCount === 0 ? <p className="plan-status">Relaxation is enabled but no residue is marked Repair. Mark one, or disable relaxation, to continue.</p> : null}
          {record ? <section className="prepared-summary">
            <strong>{record.status.replaceAll("_", " ")}</strong>
            <span>Chain{record.decisions.selected_chains.length === 1 ? "" : "s"} {record.decisions.selected_chains.join(", ")} · waters {record.decisions.water_action === "remove" ? "removed" : "kept"}</span>
            <span>{removedComponentCount} component{removedComponentCount === 1 ? "" : "s"} removed · {removedIssueCount} residue{removedIssueCount === 1 ? "" : "s"} removed · {repairedIssueCount} repaired</span>
            <span>{record.outputs.length} immutable outputs · {record.receptor_id.slice(0, 8)}…</span>
          </section> : null}
        </>}
      </aside>
    </>
  );
}

function ReceptorSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="receptor-section"><h3>{title}</h3>{children}</section>;
}

function ReceptorErrorNotice({
  error,
  affectedIssues,
  recoveryApplied,
  onRemoveAffected,
  proposedTerminalAdditions,
  authorizedTerminalAdditions,
  onAuthorizeTerminalAdditions,
}: {
  error: Error;
  affectedIssues: ReceptorIssue[];
  recoveryApplied: boolean;
  onRemoveAffected: () => void;
  proposedTerminalAdditions: TerminalHeavyAtomAddition[];
  authorizedTerminalAdditions: TerminalHeavyAtomAddition[];
  onAuthorizeTerminalAdditions: () => void;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const proposedAuthorized = proposedTerminalAdditions.length > 0
    && proposedTerminalAdditions.every((item) => authorizedTerminalAdditions.some(
      (authorized) => terminalAdditionIdentity(authorized) === terminalAdditionIdentity(item),
    ));
  return <div className="structure-error receptor-error" role="alert">
    <strong>{error.message}</strong>
    {apiError?.code ? <span>{apiError.code} · {apiError.stage ?? "unknown stage"}</span> : null}
    {apiError?.code === "MEEKO_CONNECTIVITY_FAILURE" && affectedIssues.length ? <section className="meeko-recovery">
      <p>Invalid connectivity remained in these repaired residues:</p>
      <ul>{affectedIssues.map((issue) => <li key={issue.issue_id}><strong>{issue.residue.residue_name} {issue.residue.chain_id}:{issue.residue.sequence_number}{issue.residue.insertion_code}</strong><span>{formatDistance(issue.distance_to_reference_angstrom)}</span></li>)}</ul>
      <button type="button" disabled={recoveryApplied} onClick={onRemoveAffected}>{recoveryApplied ? `${affectedIssues.length} affected residue${affectedIssues.length === 1 ? "" : "s"} marked for removal` : `Mark ${affectedIssues.length} affected residue${affectedIssues.length === 1 ? "" : "s"} for removal`}</button>
      <small>This updates the visible plan only. Review the affected menu{affectedIssues.length === 1 ? "" : "s"} and press Apply again to create a new immutable derivative.</small>
    </section> : null}
    {apiError?.code === "PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE" && proposedTerminalAdditions.length ? <section className="meeko-recovery terminal-addition-recovery">
      <p>PDB2PQR proposed exact terminal oxygen completion:</p>
      <ul>{proposedTerminalAdditions.map((item) => <li key={terminalAdditionIdentity(item)}><strong>{item.atom_name} · {item.residue_name} {item.chain_id}:{item.sequence_number}{item.insertion_code}</strong><span>terminal heavy atom</span></li>)}</ul>
      <button type="button" disabled={proposedAuthorized} onClick={onAuthorizeTerminalAdditions}>{proposedAuthorized ? `${proposedTerminalAdditions.length} terminal addition${proposedTerminalAdditions.length === 1 ? "" : "s"} authorized` : `Authorize ${proposedTerminalAdditions.length} exact terminal OXT addition${proposedTerminalAdditions.length === 1 ? "" : "s"}`}</button>
      <small>This updates the visible plan only. Ankora will verify that each OXT belongs to the final polymer residue and will still reject every other heavy-atom change.</small>
    </section> : null}
    {apiError ? <details><summary>Technical evidence</summary><pre>{JSON.stringify(apiError.details, null, 2)}</pre></details> : null}
  </div>;
}

function meekoAffectedResidues(error: Error | null): ResidueLocator[] {
  if (!(error instanceof ApiError) || error.code !== "MEEKO_CONNECTIVITY_FAILURE") return [];
  const value = error.details.affected_residues;
  if (!Array.isArray(value)) return [];
  return value.filter(isResidueLocator);
}

function terminalHeavyAtomAdditions(error: Error | null): TerminalHeavyAtomAddition[] {
  if (!(error instanceof ApiError) || error.code !== "PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE") return [];
  const value = error.details.added_heavy_atoms;
  if (!Array.isArray(value)) return [];
  const additions: TerminalHeavyAtomAddition[] = [];
  for (const raw of value) {
    if (typeof raw !== "string") continue;
    const [chainId, residueName, sequenceText, insertionCode, atomName, ...extra] = raw.split("|");
    const sequenceNumber = Number(sequenceText);
    if (extra.length || !chainId || !residueName || !Number.isInteger(sequenceNumber) || atomName !== "OXT") continue;
    additions.push({
      chain_id: chainId,
      residue_name: residueName,
      sequence_number: sequenceNumber,
      insertion_code: insertionCode,
      atom_name: "OXT",
    });
  }
  return additions;
}

function terminalAdditionIdentity(item: TerminalHeavyAtomAddition): string {
  return [item.chain_id, item.residue_name, item.sequence_number, item.insertion_code, item.atom_name].join("|");
}

function isResidueLocator(value: unknown): value is ResidueLocator {
  if (typeof value !== "object" || value === null) return false;
  const residue = value as Record<string, unknown>;
  return typeof residue.chain_id === "string"
    && typeof residue.residue_name === "string"
    && typeof residue.sequence_number === "number"
    && typeof residue.insertion_code === "string";
}

function sameResidue(left: ResidueLocator, right: ResidueLocator): boolean {
  return left.chain_id === right.chain_id
    && left.residue_name === right.residue_name
    && left.sequence_number === right.sequence_number
    && left.insertion_code === right.insertion_code;
}

function DecisionRow({ label, value, onChange }: { label: string; value: ComponentAction | null; onChange: (action: ComponentAction) => void }) {
  return <div className="decision-row"><span>{label}</span><div><button type="button" className={value === "keep" ? "selected" : ""} onClick={() => onChange("keep")}>Keep</button><button type="button" className={value === "remove" ? "selected remove" : ""} onClick={() => onChange("remove")}>Remove</button></div></div>;
}

function decisionLabel(action: ReceptorDecisionAction, kind: string): string {
  if (action === "leave") return "Leave unchanged";
  if (action === "repair") return kind === "alternate_location" ? "Choose conformation" : "Repair with PDBFixer";
  if (action === "remove") return "Remove residue";
  return "Manual review";
}

function formatDistance(distance: number | null): string {
  return distance === null ? "distance unassessed" : `${formatScientificNumber(distance, 1)} Å from reference`;
}

function formatDistanceCompact(distance: number | null): string {
  return distance === null ? "Unassessed" : `${formatScientificNumber(distance, 1)} Å`;
}

function issueFilterLabel(filter: IssueFilter): string {
  if (filter === "all") return "All";
  if (filter === "near") return "Near pocket";
  if (filter === "blocking") return "Blocking";
  if (filter === "undecided") return "Unresolved";
  return "Meeko affected";
}

function severityLabel(severity: ReceptorIssue["severity"]): string {
  return severity === "near_reference" ? "Near pocket" : "Remote";
}

function viewModeTitle(mode: ViewMode): string {
  if (mode === "original") return "Show the immutable original structure only";
  if (mode === "prepared") return "Show the prepared receptor only";
  return "Show original and prepared structures together";
}

function viewModeLabel(mode: ViewMode): string {
  if (mode === "original") return "Original structure";
  if (mode === "prepared") return "Prepared receptor";
  return "Comparison overlay";
}

function viewModeDescription(mode: ViewMode, preparedFilename: string): string {
  if (mode === "original") return "No preparation decisions are visible in this view.";
  if (mode === "prepared") return `${preparedFilename} only. Removed waters, components, chains, and residues are hidden.`;
  return "Original and prepared structures are both visible. Removed waters and components from the original remain visible for comparison.";
}

function toolLabel(tool: { available: boolean; version: string | null } | null | undefined): string {
  if (!tool?.available) return "not configured";
  return tool.version ? `available · ${tool.version}` : "available";
}

function componentDecisionMap(record: ReceptorPreparationRecord | null): Record<string, ComponentAction> {
  return Object.fromEntries(record?.decisions.component_decisions.map((item) => [item.component_id, item.action]) ?? []);
}

function issueDecisionMap(record: ReceptorPreparationRecord | null): Record<string, LocalIssueDecision> {
  return Object.fromEntries(record?.decisions.issue_decisions.map((item) => [item.issue_id, {
    action: item.action,
    selectedAltloc: item.selected_altloc ?? undefined,
  }]) ?? []);
}

function protonationPlanSignature(request: ReceptorPreparationRequest): string {
  return JSON.stringify({
    ...request,
    component_decisions: [...request.component_decisions].sort((left, right) => left.component_id.localeCompare(right.component_id)),
    issue_decisions: [...request.issue_decisions].sort((left, right) => left.issue_id.localeCompare(right.issue_id)),
    protonation: {
      ...request.protonation,
      overrides: [],
    },
    generate_pdbqt: false,
  });
}

function restoredProtonationPreview(record: ReceptorPreparationRecord | null): {
  signature: string;
  analysis: ReceptorProtonationAnalysis;
} | null {
  if (!record?.protonation_analysis) return null;
  return {
    signature: protonationPlanSignature(record.decisions),
    analysis: record.protonation_analysis,
  };
}

function protonationOverrideMap(record: ReceptorPreparationRecord | null): Record<string, string> {
  if (!record?.protonation_analysis) return {};
  const overrides = record.decisions.protonation.overrides ?? [];
  return Object.fromEntries(overrides.flatMap((override) => {
    const proposal = record.protonation_analysis?.proposals.find((candidate) => (
      sameResidue(candidate.residue, override.residue)
      && candidate.allowed_states.includes(override.state)
    ));
    return proposal ? [[proposal.proposal_id, override.state]] : [];
  }));
}

function protonationStateLabel(state: string): string {
  const labels: Record<string, string> = {
    ARG: "ARG · protonated",
    AR0: "ARG · neutral",
    ASP: "ASP · deprotonated",
    ASH: "ASH · protonated",
    CYS: "CYS · neutral",
    CYM: "CYM · deprotonated",
    GLU: "GLU · deprotonated",
    GLH: "GLH · protonated",
    HIP: "HIP · doubly protonated",
    HIS_NEUTRAL_AUTO: "HIS · neutral tautomer optimized",
    LYS: "LYS · protonated",
    LYN: "LYN · neutral",
    TYR: "TYR · neutral",
    TYM: "TYR · deprotonated",
    NTERM_CHARGED: "N-terminus · charged",
    NTERM_NEUTRAL: "N-terminus · neutral",
    CTERM_CHARGED: "C-terminus · charged",
    CTERM_NEUTRAL: "C-terminus · neutral",
  };
  return labels[state] ?? state.replaceAll("_", " ").toLowerCase();
}
