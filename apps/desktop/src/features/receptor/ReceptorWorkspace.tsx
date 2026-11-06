import { useEffect, useMemo, useRef, useState } from "react";

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
  ReceptorProtonationProposal,
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
  const inspectionMethod = restoredRecord?.decisions.inspection_method ?? (restoredRecord ? "reported_only" : "templates_v1");
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
  const [errorPlanSignature, setErrorPlanSignature] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(restoredRecord ? "prepared" : "original");
  const [issueFilter, setIssueFilter] = useState<IssueFilter>("all");
  const [uiMode, setUiMode] = useState<"guided" | "advanced">("guided");
  const [guidedStep, setGuidedStep] = useState(restoredRecord ? 2 : 0);
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [repairMethod, setRepairMethod] = useState<"legacy" | "topology_guard_v3">(
    restoredRecord?.decisions.repair_method ?? (restoredRecord ? "legacy" : "topology_guard_v3"),
  );
  const [repairSeed, setRepairSeed] = useState(restoredRecord?.decisions.repair_seed ?? 20261014);
  const [proposalFilter, setProposalFilter] = useState<"all" | "attention">("all");
  const nextStepRef = useRef<HTMLElement>(null);

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
    setProposalFilter("all");
    setGuidedStep(restored ? 2 : 0);
    setReviewConfirmed(false);
    setRepairMethod(restored?.decisions.repair_method ?? (restored ? "legacy" : "topology_guard_v3"));
    setRepairSeed(restored?.decisions.repair_seed ?? 20261014);
    setRecord(restored);
    setError(null);
    setErrorPlanSignature(null);
    setViewMode(restored ? "prepared" : "original");
    onRecordChange(restored);
  }, [initialRecord, structure.artifact.artifact_id, onRecordChange]);

  useEffect(() => {
    let active = true;
    setOperation("inspecting");
    // A changed distance reference must not discard evidence from the last
    // attempted preparation. Its decision snapshot will label it as previous.
    if (errorPlanSignature === null) setError(null);
    void ankoraApi.inspectReceptor(structure.artifact.artifact_id, referenceComponentId, inspectionMethod)
      .then((nextReport) => {
        if (active) {
          setReport(nextReport);
          setOperation("idle");
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason : new Error("Receptor inspection failed"));
          setErrorPlanSignature(null);
          setOperation("idle");
        }
      });
    return () => { active = false; };
  }, [referenceComponentId, structure.artifact.artifact_id, inspectionMethod]);

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
  const selectedChainIssues = report?.issues.filter((item) => selectedChains.includes(item.residue.chain_id)) ?? [];
  const selectedIssues = selectedChainIssues.filter((issue) => !selectedComponents.some((component) => (
    componentActions[component.component_id] === "remove"
    && component.chain_id === issue.residue.chain_id
    && component.name === issue.residue.residue_name
    && component.sequence_number === issue.residue.sequence_number
    && component.insertion_code === issue.residue.insertion_code
  )));
  const excludedComponentIssueCount = selectedChainIssues.length - selectedIssues.length;
  const unsupportedMissingAtomIssues = selectedIssues.filter((issue) => issue.kind === "missing_atoms"
    && !issue.allowed_actions.includes("repair"));
  const retainedComponents = selectedComponents.filter((component) => componentActions[component.component_id] === "keep");
  const plannedRepairCount = selectedIssues.filter((issue) => issue.kind === "missing_atoms"
    && issueDecisions[issue.issue_id]?.action === "repair").length;
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
  const terminalCandidates = (report?.terminal_oxygen_candidates ?? []).filter(
    (item) => selectedChains.includes(item.chain_id),
  );
  const terminalAuthorizationsValid = authorizedTerminalAdditions.every((item) => (
    selectedChains.includes(item.chain_id)
    && !selectedIssues.some((issue) => sameResidue(issue.residue, item)
      && issueDecisions[issue.issue_id]?.action === "remove")
  ));
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
  const numericParametersValid = Number.isFinite(ph) && ph >= 0 && ph <= 14
    && Number.isInteger(repairSeed) && repairSeed >= 1 && repairSeed <= 2147483647
    && Number.isFinite(restraintForceConstant) && restraintForceConstant > 0
    && Number.isInteger(relaxationMaxIterations) && relaxationMaxIterations >= 1 && relaxationMaxIterations <= 5000;
  const structuralPlanComplete = numericParametersValid && terminalAuthorizationsValid && selectedChains.length > 0
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
      ...(repairMethod !== "legacy" ? { repair_method: repairMethod, repair_seed: repairSeed } : {}),
      ...(inspectionMethod !== "reported_only" ? { inspection_method: inspectionMethod } : {}),
    };
  }

  const unsignedRequest = buildRequest([]);
  const protonationSignature = unsignedRequest ? protonationPlanSignature(unsignedRequest) : null;
  const activeProtonationAnalysis = protonationPreview?.signature === protonationSignature
    ? protonationPreview.analysis
    : null;
  const planComplete = structuralPlanComplete && (!protonate || activeProtonationAnalysis !== null);
  const applyReady = planComplete && (uiMode === "advanced" || (reviewConfirmed && protonate && generatePdbqt));
  const systemComplete = selectedChains.length > 0 && waterAction !== null
    && selectedComponents.every((item) => componentActions[item.component_id] !== undefined);
  const showSystem = uiMode === "advanced" || guidedStep === 0;
  const showRepairs = uiMode === "advanced" || guidedStep === 1;
  const showPreparation = uiMode === "advanced" || guidedStep === 2;
  const overrideSignature = JSON.stringify(Object.entries(protonationOverrides).sort());
  useEffect(() => { setReviewConfirmed(false); }, [protonationSignature, overrideSignature, generatePdbqt]);
  const undecidedIssues = selectedIssues.filter((issue) => {
    const action = issueDecisions[issue.issue_id]?.action;
    return !action || action === "manual_review";
  });
  const incompleteAltlocs = selectedIssues.filter((issue) => issue.kind === "alternate_location"
    && issueDecisions[issue.issue_id]?.action === "repair" && !issueDecisions[issue.issue_id]?.selectedAltloc);
  const unresolvedComponents = selectedComponents.filter((item) => componentActions[item.component_id] === undefined);
  const bulkRepairIssues = selectedIssues.filter((issue) => issue.kind === "missing_atoms"
    && issue.allowed_actions.includes("repair")
    && [undefined, "manual_review", "leave"].includes(issueDecisions[issue.issue_id]?.action));
  const bulkMissingResidues = undecidedIssues.filter((issue) => issue.kind === "missing_residue"
    && issue.allowed_actions.includes("leave"));
  const attentionProposals = activeProtonationAnalysis?.proposals.filter(proposalNeedsAttention) ?? [];
  const visibleProposals = proposalFilter === "attention" ? attentionProposals : activeProtonationAnalysis?.proposals ?? [];
  const draftBlockers = [
    ...(!numericParametersValid ? ["Enter valid pH and advanced numerical parameters."] : []),
    ...(!selectedChains.length ? ["Choose at least one polymer chain."] : []),
    ...(waterAction === null ? ["Choose whether to keep or remove waters."] : []),
    ...(unresolvedComponents.length ? [`Decide ${unresolvedComponents.length} component(s): ligands, cofactors or ions.`] : []),
    ...(undecidedIssues.length ? [`Resolve ${undecidedIssues.length} undecided or manual-review residue issue(s).`] : []),
    ...(incompleteAltlocs.length ? [`Choose a conformation for ${incompleteAltlocs.length} alternate-location issue(s).`] : []),
    ...(protonationBlockingIssues.length ? [`Repair or remove ${protonationBlockingIssues.length} incomplete/ambiguous residue issue(s), or disable protonation.`] : []),
    ...(relax && !plannedRepairCount ? ["Disable relaxation or explicitly mark missing atoms for repair."] : []),
    ...(!terminalAuthorizationsValid ? ["Clear terminal oxygen authorizations for deselected chains or removed residues."] : []),
  ];
  // Capture attempted decisions even when later edits make the plan incomplete.
  const decisionSignature = JSON.stringify({
    source: structure.artifact.artifact_id, referenceComponentId,
    selectedChains: [...selectedChains].sort(), waterAction,
    componentActions: Object.entries(componentActions).sort(),
    issueDecisions: Object.entries(issueDecisions).sort(),
    relax, restraintForceConstant, relaxationMaxIterations, protonate, ph,
    repairMethod, repairSeed,
    authorizedTerminalAdditions, generatePdbqt,
    protonationOverrides: Object.entries(protonationOverrides).sort(),
  });
  const errorFromPreviousPlan = errorPlanSignature !== null && errorPlanSignature !== decisionSignature;

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

  function fillIssueDraft(issues: ReceptorIssue[], action: "repair" | "leave") {
    setIssueDecisions((current) => {
      const next = { ...current };
      for (const issue of issues) next[issue.issue_id] = { action };
      return next;
    });
  }

  function focusNextStep() {
    nextStepRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    nextStepRef.current?.focus({ preventScroll: true });
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
    if (!applyReady || !activeProtonationAnalysis && protonate) return;
    const overrides = activeProtonationAnalysis?.proposals.flatMap((proposal) => {
      const state = protonationOverrides[proposal.proposal_id] ?? proposal.default_state;
      return state === proposal.default_state ? [] : [{ residue: proposal.residue, state }];
    }) ?? [];
    const request = buildRequest(overrides);
    if (!request) return;
    setOperation("applying");
    setError(null);
    setErrorPlanSignature(null);
    try {
      const nextRecord = await ankoraApi.prepareReceptor(structure.artifact.artifact_id, request);
      setRecord(nextRecord);
      onRecordChange(nextRecord);
      setViewMode("prepared");
      setGuidedStep(2);
      if (nextRecord.protonation_analysis) {
        setProtonationPreview({
          signature: protonationPlanSignature(nextRecord.decisions),
          analysis: nextRecord.protonation_analysis,
        });
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason : new Error("Receptor preparation failed"));
      setErrorPlanSignature(decisionSignature);
    } finally {
      setOperation("idle");
    }
  }

  async function analyzeProtonation() {
    if (!structuralPlanComplete) return;
    const request = buildRequest([]);
    if (!request || !protonationSignature) return;
    setOperation("analyzing");
    setGuidedStep(2);
    setError(null);
    setErrorPlanSignature(null);
    try {
      const analysis = await ankoraApi.previewReceptorProtonation(
        structure.artifact.artifact_id,
        request,
      );
      setProtonationOverrides({});
      setProposalFilter(uiMode === "guided" ? "attention" : "all");
      setProtonationPreview({ signature: protonationSignature, analysis });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason : new Error("Protonation analysis failed"));
      setErrorPlanSignature(decisionSignature);
    } finally {
      setOperation("idle");
    }
  }

  const errorNotice = error ? <ReceptorErrorNotice
    error={error}
    affectedIssues={meekoAffectedIssues}
    recoveryApplied={meekoRecoveryApplied}
    onRemoveAffected={removeMeekoAffectedResidues}
    proposedTerminalAdditions={proposedTerminalAdditions}
    authorizedTerminalAdditions={authorizedTerminalAdditions}
    onAuthorizeTerminalAdditions={authorizeProposedTerminalAdditions}
    fromPreviousPlan={errorFromPreviousPlan}
    relaxationEnabled={relax}
    canEnableRelaxation={plannedRepairCount > 0 && operation === "idle"}
    onEnableRelaxation={() => setRelax(true)}
    onDisableRelaxation={() => setRelax(false)}
    onInspectResidue={(residue) => { setViewMode("original"); onSelect({ kind: "residue", residue: {
      chainId: residue.chain_id, residueName: residue.residue_name,
      sequenceNumber: residue.sequence_number, insertionCode: residue.insertion_code,
    } }); }}
  /> : null;

  return (
    <>
      <section className="workspace receptor-workspace" aria-label="Receptor workspace">
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
        {report ? <section className="receptor-next-step" aria-label="Preparation next step" tabIndex={-1} ref={nextStepRef}>
          <div>
            <span className="section-label">Current draft · next step</span>
            <strong>{!structuralPlanComplete ? "1 · Complete the structural decisions"
              : uiMode === "guided" && (!protonate || !generatePdbqt) ? "3 · Choose hydrogens and docking output"
              : protonate && !activeProtonationAnalysis ? "2 · Review protonation for this plan"
              : uiMode === "guided" && !reviewConfirmed ? "3 · Confirm your reviewed plan"
              : "3 · Ready for explicit preparation"}</strong>
            {!structuralPlanComplete ? <ul>{draftBlockers.map((message) => <li key={message}>{message}</li>)}</ul>
              : protonate && !activeProtonationAnalysis ? <p>{protonationPreview
                ? "Your structural plan changed. Recalculate and review the pKa proposals for these exact decisions before preparing the receptor."
                : "Calculate the pKa proposals, review the selected states, then prepare the receptor. Nothing is accepted automatically."}</p>
              : <p>{protonate ? `${activeProtonationAnalysis?.proposals.length ?? 0} proposals available · ${attentionProposals.length} need focused review. Inspect the selected states before confirming.`
                : uiMode === "guided" ? "Open Prepare, select Prepare for docking, and review the predicted protonation states before confirming."
                : "The explicit plan is complete. Protonation is off; this creates a structural derivative, not a docking-ready receptor."}</p>}
          </div>
          {structuralPlanComplete && protonate && !activeProtonationAnalysis ? <button type="button" className="apply-plan" disabled={operation !== "idle"} onClick={() => void analyzeProtonation()}>Analyze pKa proposals</button>
            : <button type="button" className="apply-plan" disabled={!applyReady || operation !== "idle"} onClick={() => void applyPlan()}>Prepare this receptor</button>}
          {uiMode === "guided" && !showPreparation && structuralPlanComplete ? <button type="button" onClick={() => setGuidedStep(2)}>Review and prepare</button> : null}
        </section> : null}
        {errorNotice && errorFromPreviousPlan && meekoRecoveryApplied
          ? <details className="previous-receptor-attempt"><summary>Previous attempt evidence · affected residues marked for removal in the draft</summary>{errorNotice}</details>
          : errorNotice}
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
              {uiMode === "advanced" ? <div className="bulk-actions"><button type="button" onClick={() => setAllIssues("leave")}>Explicitly leave all</button><button type="button" onClick={() => setAllIssues("manual_review")}>Mark all for review</button></div> : null}
            </div>
            {uiMode === "advanced" && (bulkRepairIssues.length || bulkMissingResidues.length) ? <div className="receptor-draft-actions">
              <small>Fill the draft only; no calculation or removal. Existing Repair/Remove choices are preserved.</small>
              {bulkRepairIssues.length ? <button type="button" disabled={operation !== "idle"} onClick={() => fillIssueDraft(bulkRepairIssues, "repair")}>Mark {bulkRepairIssues.length} missing-atom residue(s) for repair</button> : null}
              {bulkMissingResidues.length ? <button type="button" disabled={operation !== "idle"} onClick={() => fillIssueDraft(bulkMissingResidues, "leave")}>Leave {bulkMissingResidues.length} missing residue(s) unmodelled</button> : null}
            </div> : null}
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
                    <td><select aria-label={`Decision for ${issue.residue.residue_name} ${issue.residue.sequence_number}${issue.residue.insertion_code}`} value={decision.action ?? ""} onChange={(event) => setIssueDecisions((current) => ({ ...current, [issue.issue_id]: { action: event.target.value as ReceptorDecisionAction } }))}>
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
          <div className="view-switch" aria-label="Receptor preparation mode">
            <button type="button" aria-pressed={uiMode === "guided"} onClick={() => setUiMode("guided")}>Guided preparation</button>
            <button type="button" aria-pressed={uiMode === "advanced"} onClick={() => setUiMode("advanced")}>Advanced controls</button>
          </div>
          {uiMode === "guided" ? <>
            <nav className="receptor-steps" aria-label="Receptor preparation steps">
              {["Choose system", "Review repairs", "Prepare"].map((label, index) => <button type="button" key={label}
                aria-current={guidedStep === index ? "step" : undefined}
                disabled={(index > 0 && !systemComplete) || (index === 2 && !structuralPlanComplete)}
                onClick={() => setGuidedStep(index)}>{index + 1} · {label}</button>)}
            </nav>
            <p className="field-note">{guidedStep === 0 ? "Choose the protein chains and what to keep. Nothing is removed automatically."
              : guidedStep === 1 ? "Rebuild missing side-chain atoms, keep gaps unmodelled, and inspect unusual residues."
              : "Add hydrogens, review the predicted protonation states, then confirm your preparation."}</p>
          </> : null}
          <div hidden={!showSystem}>
          <ReceptorSection title={uiMode === "guided" ? "Distance reference · optional" : "1 · Pocket reference"}>
            <label className="field-label" htmlFor="reference-component">Reference component</label>
            <select id="reference-component" value={referenceComponentId ?? ""} onChange={(event) => setReferenceComponentId(event.target.value || null)}>
              <option value="">None · distances unassessed</option>
              {report.components.map((component) => <option value={component.component_id} key={component.component_id}>{component.name} {component.chain_id}:{component.sequence_number ?? "?"}</option>)}
            </select>
            <p className="field-note">A reference only classifies distances; it does not define a docking box.</p>
          </ReceptorSection>

          <ReceptorSection title={uiMode === "guided" ? "Protein chains" : "2 · Polymer chains"}>
            <div className="decision-grid">{report.candidate_chains.map((chainId) => <button type="button" key={chainId} className={selectedChains.includes(chainId) ? "selected" : ""} onClick={() => { toggleChain(chainId); onSelect({ kind: "chain", chainId }); }}>Chain {chainId || "∅"}</button>)}</div>
          </ReceptorSection>

          <ReceptorSection title={uiMode === "guided" ? "What to keep" : "3 · Components"}>
            <DecisionRow label={`Resolved waters (${report.water_count})`} value={waterAction} onChange={setWaterAction} />
            {selectedComponents.map((component) => <DecisionRow key={component.component_id} label={`${component.name} ${component.chain_id}:${component.sequence_number ?? "?"}${component.insertion_code} · ${component.kind}`} value={componentActions[component.component_id] ?? null} onChange={(action) => setComponentActions((current) => ({ ...current, [component.component_id]: action }))} />)}
            {retainedComponents.length ? <p className="field-note">Retained ligands and metals may require specific protonation and charge parameters. Keeping a component is not evidence that the protein preparation tools support it. Review its role in your system.</p> : null}
            {!selectedChains.length ? <p className="empty-list">Choose at least one chain to inspect its components.</p> : null}
          </ReceptorSection>

          {uiMode === "guided" ? <button type="button" className="apply-plan" disabled={!systemComplete} onClick={() => setGuidedStep(1)}>Next · review repairs</button> : null}
          </div>
          <div hidden={!showRepairs}>

          <ReceptorSection title={`${uiMode === "advanced" ? "4 · " : ""}Structural issues (${selectedIssues.length})`}>
            <p className="field-note">{inspectionMethod === "templates_v1"
              ? "Source reports plus standard amino-acid heavy-atom templates. Hydrogens and terminal OXT are not inferred; alternate conformations still need review."
              : "Historical source-reported inspection preserved for this record."}</p>
            {excludedComponentIssueCount ? <p className="field-note">{excludedComponentIssueCount} observation(s) excluded by your component-removal choices. The imported structure is unchanged.</p> : null}
            {unsupportedMissingAtomIssues.length ? <div className="protonation-blocker" role="alert">
              <strong>{unsupportedMissingAtomIssues.length} incomplete component(s) need individual review.</strong>
              <p>The protein repair tool cannot reconstruct these missing atoms. Prepare the component with an appropriate external workflow, or exclude it only if justified for your experiment. Nothing is removed automatically.</p>
              <ul>{unsupportedMissingAtomIssues.map((issue) => <li key={issue.issue_id}>{issue.residue.residue_name} {issue.residue.chain_id}:{issue.residue.sequence_number}{issue.residue.insertion_code}</li>)}</ul>
              {uiMode === "guided" ? <button type="button" onClick={() => setGuidedStep(0)}>Review component choices</button> : null}
            </div> : null}
            {uiMode === "guided" ? <div className="receptor-draft-actions">
              {bulkRepairIssues.length ? <button type="button" onClick={() => fillIssueDraft(bulkRepairIssues, "repair")}>Repair {bulkRepairIssues.length} incomplete {bulkRepairIssues.some((issue) => issue.missing_atoms.some((atom) => ["N", "CA", "C", "O"].includes(atom))) ? "residue(s)" : "side-chain(s)"}</button> : null}
              {bulkMissingResidues.length ? <button type="button" onClick={() => fillIssueDraft(bulkMissingResidues, "leave")}>Keep {bulkMissingResidues.length} gap(s) unmodelled</button> : null}
              <p className="field-note">These choices fill the plan only. Alternate conformations and nonstandard residues still need individual review in the table.</p>
            </div> : null}
            <div className="issue-plan-summary"><div><strong>{selectedIssues.length - selectedIssues.filter((item) => !issueDecisions[item.issue_id]?.action || issueDecisions[item.issue_id]?.action === "manual_review").length}</strong><span>decided</span></div><div><strong>{selectedIssues.filter((item) => !issueDecisions[item.issue_id]?.action || issueDecisions[item.issue_id]?.action === "manual_review").length}</strong><span>unresolved</span></div><div><strong>{protonationBlockingIssues.length}</strong><span>blocking</span></div></div>
            <p className="field-note">Use the workbench table beneath the molecular viewer to filter, inspect in 3D, and decide every residue.</p>
          </ReceptorSection>

          <ReceptorSection title="Repair geometry">
            <p className="field-note">{repairMethod === "topology_guard_v3" ? "Topology-guarded repair: rebuild selected atoms while keeping observed atoms fixed. Connectivity and rebuilt stereochemistry are checked before protonation." : "Legacy PDBFixer repair: preserved for older records. It does not use the new geometry guard."}</p>
            {uiMode === "advanced" ? <>
              <label className="field-label">Repair method<select value={repairMethod} onChange={(event) => setRepairMethod(event.target.value as typeof repairMethod)}>
                <option value="topology_guard_v3">Topology-guarded repair</option><option value="legacy">Legacy PDBFixer</option>
              </select></label>
              <label className="numeric-field">Repair random seed<input type="number" min="1" max="2147483647" disabled={repairMethod === "legacy"} value={repairSeed} onChange={(event) => setRepairSeed(Number(event.target.value))} /></label>
            </> : null}
          </ReceptorSection>

          <div hidden={uiMode === "guided"}>
          <ReceptorSection title="5 · Relax reconstructed atoms">
            <p className="field-note">Optional clash relief after explicit missing-atom repairs. Newly added atoms interact with their neighbors while observed atoms have elastic positional restraints, not frozen coordinates. Ankora rejects the result if any observed heavy atom moves more than 0.5 Å; this is not a full protein energy minimization.</p>
            <label className="check-row"><input type="checkbox" checked={relax} disabled={!plannedRepairCount && !relax} onChange={(event) => setRelax(event.target.checked)} /><span><strong>Relax repaired residues with OpenMM</strong><small>PDBFixer worker · {toolLabel(tools?.pdbfixer)}</small></span></label>
            {!plannedRepairCount ? <p className="field-note">No residue is marked Repair yet — nothing to relax until one is.</p> : null}
            {relax ? <details className="relaxation-advanced"><summary>Advanced relaxation parameters</summary>
              <label className="numeric-field">Restraint force constant (kcal/mol/Å²)<input type="number" min="1" step="1" value={restraintForceConstant} onChange={(event) => setRestraintForceConstant(Number(event.target.value))} /></label>
              <label className="numeric-field">Maximum iterations<input type="number" min="1" max="5000" step="10" value={relaxationMaxIterations} onChange={(event) => setRelaxationMaxIterations(Number(event.target.value))} /></label>
            </details> : null}
          </ReceptorSection>
          </div>
          {uiMode === "guided" && relax ? <p className="field-note">Optional relaxation is enabled in this plan. Its parameters remain in Advanced controls.</p> : null}

          {uiMode === "guided" ? <button type="button" className="apply-plan" disabled={!structuralPlanComplete} onClick={() => setGuidedStep(2)}>Next · hydrogens and preparation</button> : null}
          </div>
          <div hidden={!showPreparation}>

          <ReceptorSection title={uiMode === "guided" ? "Hydrogens and docking file" : "6 · Hydrogens & docking format"}>
            {uiMode === "guided" ? <label className="check-row"><input type="checkbox" checked={protonate && generatePdbqt} onChange={(event) => {
              setProtonate(event.target.checked); setGeneratePdbqt(event.target.checked);
              if (!event.target.checked) setAuthorizedTerminalAdditions([]);
            }} /><span><strong>Prepare for docking</strong><small>Add hydrogens at the selected pH and create the receptor docking file.</small></span></label> : null}
            <label className="check-row" hidden={uiMode === "guided"}><input type="checkbox" checked={protonate} onChange={(event) => { setProtonate(event.target.checked); if (!event.target.checked) { setGeneratePdbqt(false); setAuthorizedTerminalAdditions([]); } }} /><span><strong>Run PDB2PQR + PROPKA</strong><small>{toolLabel(tools?.pdb2pqr)} · {toolLabel(tools?.propka)}</small></span></label>
            {protonate ? <label className="numeric-field">Target pH<input type="number" min="0" max="14" step="0.1" value={ph} onChange={(event) => setPh(Number(event.target.value))} /></label> : null}
            {protonate && terminalCandidates.length ? <div className="protonation-blocker terminal-oxygen-candidates" role="region" aria-label="Terminal oxygen review">
              <strong>Review possible terminal oxygen completion</strong>
              <p>These observed chain ends have no OXT atom. This does not establish a biological terminus or guarantee that PDB2PQR will add one. Decide individually whether to permit completion; nothing is added now.</p>
              {terminalCandidates.map((item) => {
                const identity = terminalAdditionIdentity(item);
                const authorized = authorizedTerminalAdditions.some((value) => terminalAdditionIdentity(value) === identity);
                const removed = selectedIssues.some((issue) => sameResidue(issue.residue, item)
                  && issueDecisions[issue.issue_id]?.action === "remove");
                return <label className="check-row" key={identity}>
                  <input type="checkbox" checked={authorized} disabled={removed && !authorized} onChange={(event) => setAuthorizedTerminalAdditions((current) => event.target.checked
                    ? [...current.filter((value) => terminalAdditionIdentity(value) !== identity), item]
                    : current.filter((value) => terminalAdditionIdentity(value) !== identity))} />
                  <span><strong>Allow OXT · {item.residue_name} {item.chain_id}:{item.sequence_number}{item.insertion_code}</strong><small>{removed ? "This residue is marked for removal; clear its authorization." : "Optional; the final prepared chain is checked again."}</small></span>
                </label>;
              })}
              <small>Removing residues or changing chains can change the final chain end. Ankora rejects all unapproved heavy-atom changes.</small>
            </div> : null}
            {authorizedTerminalAdditions.length ? <div className="protonation-blocker authorized-terminal-additions" role="status">
              <strong>{authorizedTerminalAdditions.length} exact terminal heavy-atom addition{authorizedTerminalAdditions.length === 1 ? "" : "s"} authorized.</strong>
              <ul>{authorizedTerminalAdditions.map((item) => <li key={terminalAdditionIdentity(item)}>{item.atom_name} · {item.residue_name} {item.chain_id}:{item.sequence_number}{item.insertion_code}</li>)}</ul>
              <small>Only these identities may be added by PDB2PQR; every other heavy-atom change remains a hard failure.</small>
              <button type="button" onClick={() => setAuthorizedTerminalAdditions([])}>Clear terminal oxygen authorizations</button>
            </div> : null}
            <label className="check-row" hidden={uiMode === "guided"}><input type="checkbox" checked={generatePdbqt} disabled={!protonate} onChange={(event) => setGeneratePdbqt(event.target.checked)} /><span><strong>Generate receptor PDBQT with Meeko</strong><small>{toolLabel(tools?.meeko)}</small></span></label>
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
            {protonate && activeProtonationAnalysis ? <>
              <button
                type="button"
                className="protonation-analysis-action"
                disabled={!structuralPlanComplete || operation !== "idle"}
                onClick={() => void analyzeProtonation()}
              >Refresh pKa proposals</button>
              <p className="field-note">This review runs the exact chain, component, repair, relaxation, force-field, and pH plan in an isolated workspace. The final derivative reruns and records its own evidence.</p>
            </> : null}
            {protonate && activeProtonationAnalysis ? <div className="protonation-analysis" role="region" aria-label="PROPKA protonation proposals">
              <div className="protonation-analysis-summary">
                <strong>{activeProtonationAnalysis.proposals.length} pKa proposals</strong>
                <span>{activeProtonationAnalysis.proposals.filter((item) => item.near_reference).length} near reference</span>
                <span>{activeProtonationAnalysis.proposals.filter((item) => item.nearby_metals.length).length} near metals</span>
                <span>{Object.keys(protonationOverrides).length} overrides</span>
              </div>
              <p className="field-note">PROPKA predicts; the selected state is Ankora's recorded decision. For histidine, Ankora also verifies the tautomer actually written to both PDB and PQR. Amber-incompatible states remain visible but cannot be selected.</p>
              <div className="filter-tabs" aria-label="Protonation proposal filters">
                <button type="button" aria-pressed={proposalFilter === "all"} onClick={() => setProposalFilter("all")}>All proposals ({activeProtonationAnalysis.proposals.length})</button>
                <button type="button" aria-pressed={proposalFilter === "attention"} onClick={() => setProposalFilter("attention")}>Needs attention ({attentionProposals.length})</button>
              </div>
              <div className="protonation-proposal-list">
                {visibleProposals.map((proposal) => {
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
                      {proposal.output_state ? <span>Written output · {protonationStateLabel(proposal.output_state)}</span> : null}
                      {proposal.near_reference ? <span>Near reference · {formatDistanceCompact(proposal.distance_to_reference_angstrom)}</span> : null}
                      {proposal.nearby_metals.map((metal) => <span className="warning" key={metal.component_id}>Near {metal.name} · {formatScientificNumber(metal.distance_angstrom, 1)} Å</span>)}
                      {proposal.warnings.includes("PKA_NEAR_TARGET_PH") ? <span className="warning">pKa near target pH</span> : null}
                      {proposal.coupled_group ? <span>Coupled · {proposal.coupled_group}</span> : null}
                    </div>
                  </article>;
                })}
                {!visibleProposals.length ? <p className="field-note">No proposals match this filter. All selected states remain part of the plan.</p> : null}
              </div>
              <small className="protonation-evidence">{activeProtonationAnalysis.tool_version} · input {activeProtonationAnalysis.input_sha256.slice(0, 12)}…</small>
            </div> : null}
          </ReceptorSection>

          {uiMode === "guided" ? <section className="prepared-summary" aria-label="Preparation confirmation">
            <strong>Review this exact plan</strong>
            <span>Chain(s) {selectedChains.join(", ")} · waters {waterAction} · {plannedRepairCount} missing-atom repairs</span>
            {selectedComponents.map((component) => <span key={component.component_id}>{component.name} {component.chain_id}:{component.sequence_number ?? "?"}{component.insertion_code} · {componentActions[component.component_id]}</span>)}
            <span>{selectedIssues.filter((issue) => issueDecisions[issue.issue_id]?.action === "remove").length} residue(s) marked for removal · {protonate ? `pH ${formatScientificNumber(ph, 1)} · AMBER charges` : "No hydrogens or docking file"}</span>
            <label className="check-row"><input type="checkbox" checked={reviewConfirmed} disabled={!planComplete || !protonate || !generatePdbqt} onChange={(event) => setReviewConfirmed(event.target.checked)} /><span>I reviewed the system, repairs and selected protonation states.</span></label>
            {!protonate || !generatePdbqt ? <p className="field-note">Select Prepare for docking to complete this guided workflow. Advanced controls also allow a structure-only derivative.</p> : null}
          </section> : null}
          <button type="button" className="apply-plan" disabled={!applyReady || operation !== "idle"} onClick={() => void applyPlan()}>{record ? "Create another immutable derivative" : "Apply explicit preparation plan"}</button>
          {protonate && !activeProtonationAnalysis ? <button type="button" className="protonation-analysis-action" onClick={focusNextStep}>Go to preparation next step</button> : null}
          {!structuralPlanComplete && protonationBlockingIssues.length === 0 && (!relax || plannedRepairCount > 0) ? <p className="plan-status">Complete every chain, component, and residue decision to continue.</p> : null}
          {structuralPlanComplete && protonate && !activeProtonationAnalysis ? <p className="plan-status">Review the PROPKA pKa proposals before creating the receptor derivative.</p> : null}
          {!planComplete && relax && plannedRepairCount === 0 ? <p className="plan-status">Relaxation is enabled but no residue is marked Repair. Mark one, or disable relaxation, to continue.</p> : null}
          {record ? <section className="prepared-summary">
            <strong>{record.status.replaceAll("_", " ")}</strong>
            <span>Chain{record.decisions.selected_chains.length === 1 ? "" : "s"} {record.decisions.selected_chains.join(", ")} · waters {record.decisions.water_action === "remove" ? "removed" : "kept"}</span>
            <span>{removedComponentCount} component{removedComponentCount === 1 ? "" : "s"} removed · {removedIssueCount} residue{removedIssueCount === 1 ? "" : "s"} removed · {repairedIssueCount} repaired</span>
            <span>{record.outputs.length} immutable outputs · {record.receptor_id.slice(0, 8)}…</span>
          </section> : null}
          </div>
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
  fromPreviousPlan,
  relaxationEnabled,
  onDisableRelaxation,
  canEnableRelaxation,
  onEnableRelaxation,
  onInspectResidue,
}: {
  error: Error;
  affectedIssues: ReceptorIssue[];
  recoveryApplied: boolean;
  onRemoveAffected: () => void;
  proposedTerminalAdditions: TerminalHeavyAtomAddition[];
  authorizedTerminalAdditions: TerminalHeavyAtomAddition[];
  onAuthorizeTerminalAdditions: () => void;
  fromPreviousPlan: boolean;
  relaxationEnabled: boolean;
  onDisableRelaxation: () => void;
  canEnableRelaxation: boolean;
  onEnableRelaxation: () => void;
  onInspectResidue: (residue: ResidueLocator) => void;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const anchorConflicts = repairedAnchorConflicts(error);
  const displacedAtoms = relaxationDisplacedAtoms(error);
  const proposedAuthorized = proposedTerminalAdditions.length > 0
    && proposedTerminalAdditions.every((item) => authorizedTerminalAdditions.some(
      (authorized) => terminalAdditionIdentity(authorized) === terminalAdditionIdentity(item),
    ));
  return <div className={`structure-error receptor-error${fromPreviousPlan ? " previous-plan" : ""}`} role={fromPreviousPlan ? "status" : "alert"}>
    <strong>{fromPreviousPlan ? "Previous attempt · your updated plan has not run" : error.message}</strong>
    {fromPreviousPlan ? <span>{error.message}</span> : null}
    {apiError?.code ? <span>{apiError.code} · {apiError.stage ?? "unknown stage"}</span> : null}
    {fromPreviousPlan ? <p role="status">This failure belongs to a previous plan. Current decisions have changed; no new calculation has run. The original technical evidence is retained below.</p> : null}
    {apiError?.code === "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED" ? <section className="meeko-recovery relaxation-recovery">
      <p>The attempted relaxed receptor was not accepted. Inspect the original residue in 3D before changing its preparation decision.</p>
      {displacedAtoms.length ? <ul>{displacedAtoms.slice(0, 12).map((atom) => <li key={[atom.residue.chain_id, atom.residue.residue_name, atom.residue.sequence_number, atom.residue.insertion_code, atom.atom_name].join("|")}>
        <button type="button" onClick={() => onInspectResidue(atom.residue)}>Inspect {atom.residue.residue_name} {atom.residue.chain_id}:{atom.residue.sequence_number}{atom.residue.insertion_code} · {atom.atom_name} in 3D</button>
        <span>{formatScientificNumber(atom.displacement_angstrom, 3)} Å displacement</span>
      </li>)}</ul> : <p>This older error does not identify individual atoms. Its measured displacement remains in Technical evidence; no residue is inferred.</p>}
      {displacedAtoms.length > 12 ? <small>Showing 12 of {displacedAtoms.length} displaced atoms. All identities and coordinates are retained in Technical evidence.</small> : null}
      <button type="button" disabled={!relaxationEnabled} onClick={onDisableRelaxation}>Disable relaxation in the plan</button>
      <small>This only changes the draft. Skipping relaxation does not prove reconstructed geometry is acceptable; review it before a new explicit calculation. No residue is removed automatically.</small>
    </section> : null}
    {apiError && ["MEEKO_CONNECTIVITY_FAILURE", "RECEPTOR_REPAIRED_GEOMETRY_INVALID"].includes(apiError.code ?? "") && affectedIssues.length ? <section className="meeko-recovery">
      <p>{apiError.code === "MEEKO_CONNECTIVITY_FAILURE" ? "Meeko reported connectivity problems in these residues of the attempted receptor:" : "The repaired-atom geometry check rejected these residues before protonation:"}</p>
      <ul>{affectedIssues.map((issue) => <li key={issue.issue_id}><button type="button" onClick={() => onInspectResidue(issue.residue)}>Inspect {issue.residue.residue_name} {issue.residue.chain_id}:{issue.residue.sequence_number}{issue.residue.insertion_code} in 3D</button><span>{formatDistance(issue.distance_to_reference_angstrom)}</span></li>)}</ul>
      {anchorConflicts.map((conflict, index) => <p key={index}>
        Observed {conflict.observed_atoms.join("–")} atoms in {conflict.residue.residue_name} {conflict.residue.chain_id}:{conflict.residue.sequence_number}{conflict.residue.insertion_code} are {formatScientificNumber(conflict.observed_distance_angstrom, 3)} Å apart; the two template bonds through missing {conflict.reconstructed_atom} total {formatScientificNumber(conflict.template_bond_sum_angstrom, 3)} Å. This cannot be rebuilt with normal bond lengths while keeping those observed atoms fixed. Review the original coordinates; no atom is moved or removed automatically.
      </p>)}
      {apiError.code === "MEEKO_CONNECTIVITY_FAILURE" && canEnableRelaxation && !relaxationEnabled ? <>
        <button type="button" onClick={onEnableRelaxation}>Enable clash relief for repaired atoms in the plan</button>
        <small>This optional stage tries to separate reconstructed atoms; it is not full protein minimization and can still fail the 0.5 Å observed-atom safety limit. Review protonation again before a new explicit preparation.</small>
      </> : null}
      <button type="button" disabled={recoveryApplied} onClick={onRemoveAffected}>{recoveryApplied ? `${affectedIssues.length} affected residue${affectedIssues.length === 1 ? "" : "s"} marked for removal` : `Mark ${affectedIssues.length} affected residue${affectedIssues.length === 1 ? "" : "s"} for removal`}</button>
      <small>Removal is one possible scientific choice, not a chemical repair. It can create chain gaps, even far from the reference. This edits the draft only. Review the residues, then follow Current draft · next step; changing residues requires a fresh protonation review when protonation is enabled.</small>
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
  if (!(error instanceof ApiError) || !["MEEKO_CONNECTIVITY_FAILURE", "RECEPTOR_REPAIRED_GEOMETRY_INVALID"].includes(error.code ?? "")) return [];
  const value = error.details.affected_residues;
  if (!Array.isArray(value)) return [];
  return value.filter(isResidueLocator);
}

interface RepairedAnchorConflict {
  residue: ResidueLocator;
  reconstructed_atom: string;
  observed_atoms: string[];
  observed_distance_angstrom: number;
  template_bond_sum_angstrom: number;
}

function repairedAnchorConflicts(error: Error): RepairedAnchorConflict[] {
  if (!(error instanceof ApiError) || error.code !== "RECEPTOR_REPAIRED_GEOMETRY_INVALID") return [];
  const residues = error.details.affected_residues;
  if (!Array.isArray(residues)) return [];
  return residues.flatMap((residue: unknown) => {
    if (!isResidueLocator(residue)) return [];
    const conflicts: unknown = (residue as unknown as Record<string, unknown>).fixed_anchor_conflicts;
    if (!Array.isArray(conflicts)) return [];
    return conflicts.flatMap((raw: unknown) => {
      if (typeof raw !== "object" || raw === null) return [];
      const item = raw as Record<string, unknown>;
      if (typeof item.reconstructed_atom !== "string" || !Array.isArray(item.observed_atoms)
        || item.observed_atoms.length !== 2 || !item.observed_atoms.every((name) => typeof name === "string")
        || typeof item.observed_distance_angstrom !== "number" || !Number.isFinite(item.observed_distance_angstrom)
        || typeof item.template_bond_sum_angstrom !== "number" || !Number.isFinite(item.template_bond_sum_angstrom)) return [];
      return [{ residue, reconstructed_atom: item.reconstructed_atom, observed_atoms: item.observed_atoms as string[],
        observed_distance_angstrom: item.observed_distance_angstrom, template_bond_sum_angstrom: item.template_bond_sum_angstrom }];
    });
  });
}

interface RelaxationDisplacedAtom {
  residue: ResidueLocator;
  atom_name: string;
  displacement_angstrom: number;
}

function relaxationDisplacedAtoms(error: Error | null): RelaxationDisplacedAtom[] {
  if (!(error instanceof ApiError) || error.code !== "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED") return [];
  const value = error.details.displaced_atoms;
  if (!Array.isArray(value)) return [];
  return value.filter((raw): raw is RelaxationDisplacedAtom => {
    if (typeof raw !== "object" || raw === null) return false;
    const atom = raw as Record<string, unknown>;
    return isResidueLocator(atom.residue) && Number.isInteger(atom.residue.sequence_number)
      && typeof atom.atom_name === "string" && atom.atom_name.length > 0
      && typeof atom.displacement_angstrom === "number"
      && Number.isFinite(atom.displacement_angstrom) && atom.displacement_angstrom > 0;
  });
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
  return "Geometry affected";
}

function severityLabel(severity: ReceptorIssue["severity"]): string {
  if (severity === "near_reference") return "Near pocket";
  return severity === "remote" ? "Remote" : "Unassessed";
}

function proposalNeedsAttention(proposal: ReceptorProtonationProposal): boolean {
  return proposal.near_reference || proposal.nearby_metals.length > 0
    || proposal.warnings.length > 0 || Boolean(proposal.coupled_group)
    || proposal.default_state !== proposal.predicted_state;
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
    HID: "HID · neutral, ND1 protonated",
    HIE: "HIE · neutral, NE2 protonated",
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
