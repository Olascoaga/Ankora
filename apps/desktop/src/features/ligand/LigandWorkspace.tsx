import { type ChangeEvent, type ReactNode, useEffect, useMemo, useState } from "react";

import { ankoraApi, ApiError } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type {
  HeterogenSummary,
  LigandChemicalStateRecord,
  LigandConformerRecord,
  LigandCustomFilterRule,
  LigandCustomRuleDescriptor,
  LigandCustomRuleOperator,
  LigandDockingInput,
  LigandForceField,
  LigandLibraryFilterPlan,
  LigandLibraryFilterPreview,
  LigandLibraryFilterRun,
  LigandLibraryDockingInput,
  LigandLibraryRecord,
  LigandLibrarySummary,
  LigandMicrostateOptions,
  LigandMicrostatePlan,
  LigandMicrostateRecord,
  LigandPdbqtRecord,
  LigandPreparationStatus,
  LigandProtonationOptions,
  LigandProtonationRecord,
  LigandRecord,
  LigandStateResolutionOptions,
  StructureRecord,
  ToolsResponse,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import { SingleLigandPreparation } from "./SingleLigandPreparation";
import type { PreparationStep } from "./SingleLigandPreparation";
import type { ViewerSource } from "../../viewer/adapter";
import {
  LigandLibraryTable,
  type LigandBatchResult,
} from "./LigandLibraryTable";
import {
  isTerminalLigandBatchStatus,
  summarizeLigandLibraryStatus,
  type LigandLibraryStatusSummary,
} from "./libraryProgress";

interface LigandWorkspaceProps {
  structure: StructureRecord;
  record: LigandRecord | null;
  tools: ToolsResponse | null;
  onRecordChange: (record: LigandRecord) => void;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
  onLibraryStatusChange?: (status: LigandLibraryStatusSummary | null) => void;
  onLibraryDockingInputChange?: (input: LigandLibraryDockingInput | null) => void;
  dockingInput?: LigandDockingInput | null;
  onDockingInputChange?: (input: LigandDockingInput | null) => void;
}

type LigandViewMode = "reference" | "minimized" | "overlay";
type LigandSourceMode = "crystallographic" | "local";
type Operation =
  | "extracting"
  | "importing"
  | "resolving"
  | "bulk-resolving"
  | "enumerating-microstates"
  | "selecting-microstate"
  | "minimizing"
  | "generating"
  | "preparing-pdbqt"
  | "filtering"
  | "applying-filter"
  | "batch-preparing"
  | null;

const DEFAULT_FILTER_PLAN: LigandLibraryFilterPlan = {
  preset: "general_oral",
  require_lipinski: true,
  max_lipinski_violations: 1,
  require_veber: true,
  require_ghose: false,
  require_muegge: false,
  minimum_qed: null,
  pains_policy: "review",
  brenk_policy: "review",
  duplicate_policy: "exclude",
  custom_rules: [],
};

const DEFAULT_MICROSTATE_PLAN: LigandMicrostatePlan = {
  mode: "exact_imported_state",
  ph_min: 7.4,
  ph_max: 7.4,
  precision: 1.0,
  max_tautomers_per_protomer: 8,
  max_microstates_per_parent: 16,
};

export function LigandWorkspace({
  structure,
  record,
  tools,
  onRecordChange,
  onActivityChange,
  onLibraryStatusChange,
  onLibraryDockingInputChange,
  dockingInput,
  onDockingInputChange,
}: LigandWorkspaceProps) {
  const matchingDockingInput = dockingInput
    && dockingInput.ligand_id === record?.artifact.ligand_id
    ? dockingInput
    : null;
  const candidates = structure.metadata.heterogens.filter(
    (item) => item.kind === "ligand" && item.sequence_number !== null,
  );
  const [sourceMode, setSourceMode] = useState<LigandSourceMode>("crystallographic");
  const [workspaceMode, setWorkspaceMode] = useState<"single" | "screening">("single");
  const [selected, setSelected] = useState<HeterogenSummary | null>(
    candidates.length === 1 ? candidates[0] : null,
  );
  const [operation, setOperation] = useState<Operation>(null);
  const [error, setError] = useState<Error | null>(null);
  const [library, setLibrary] = useState<LigandLibraryRecord | null>(null);
  const [libraries, setLibraries] = useState<LigandLibrarySummary[]>([]);
  const [filterPlan, setFilterPlan] = useState<LigandLibraryFilterPlan>(DEFAULT_FILTER_PLAN);
  const [filterPreview, setFilterPreview] = useState<LigandLibraryFilterPreview | null>(null);
  const [filterRun, setFilterRun] = useState<LigandLibraryFilterRun | null>(null);
  const [filterConfirmed, setFilterConfirmed] = useState(false);
  const [resolvedStates, setResolvedStates] = useState<Record<string, LigandChemicalStateRecord>>({});
  const [microstatePlan, setMicrostatePlan] = useState<LigandMicrostatePlan>(DEFAULT_MICROSTATE_PLAN);
  const [microstateStates, setMicrostateStates] = useState<Record<string, LigandMicrostateRecord>>({});
  const [microstateOptions, setMicrostateOptions] = useState<LigandMicrostateOptions | null>(null);
  const [microstateCandidateIndex, setMicrostateCandidateIndex] = useState<number | null>(null);
  const [microstateAcknowledged, setMicrostateAcknowledged] = useState(false);
  const [protonationStates, setProtonationStates] = useState<Record<string, LigandProtonationRecord>>({});
  const [protonationOptions, setProtonationOptions] = useState<LigandProtonationOptions | null>(null);
  const [protonationCandidateIndex, setProtonationCandidateIndex] = useState<number | null>(null);
  const [protonationSkipped, setProtonationSkipped] = useState(false);
  // Docking models one pH, so Ankora asks Dimorphite-DL for one pH. The
  // tool's own 6.4-8.4 default enumerates every state plausible anywhere in
  // that window, which left a genuine choice to make on 83% of a real
  // screening library; a single physiological point leaves 58% with nothing
  // to decide. Both bounds stay editable, and the window is recorded on the
  // derivative either way.
  const [phMin, setPhMin] = useState(7.4);
  const [phMax, setPhMax] = useState(7.4);
  const [phPrecision, setPhPrecision] = useState(1.0);
  const [batchResults, setBatchResults] = useState<Record<string, LigandBatchResult>>({});
  const [batchConfirmed, setBatchConfirmed] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ completed: 0, total: 0, workers: 1 });
  const [resolution, setResolution] = useState<LigandStateResolutionOptions | null>(null);
  const [componentIndex, setComponentIndex] = useState<number | null>(null);
  const [stereoisomerIndex, setStereoisomerIndex] = useState<number | null>(null);
  const [conformer, setConformer] = useState<LigandConformerRecord | null>(() =>
    matchingDockingInput?.conformer ?? null,
  );
  const [pdbqt, setPdbqt] = useState<LigandPdbqtRecord | null>(() =>
    matchingDockingInput?.pdbqt ?? null,
  );
  const [viewMode, setViewMode] = useState<LigandViewMode>("reference");
  const [forceField, setForceField] = useState<LigandForceField>("MMFF94s");
  const [maxIterations, setMaxIterations] = useState(500);
  const [randomSeed, setRandomSeed] = useState(20260819);
  const [stateConfirmed, setStateConfirmed] = useState(false);
  const [protonationError, setProtonationError] = useState<string | null>(null);
  const [useSourceGeometry, setUseSourceGeometry] = useState(false);
  const [preparationStep, setPreparationStep] = useState<PreparationStep>(null);

  useEffect(() => {
    if (!onActivityChange) return;
    if (!operation) onActivityChange(null);
    else onActivityChange({
      title: operation === "batch-preparing" ? "Preparing ligand library" : "Processing ligand",
      detail: operationLabel(operation, forceField),
      current: operation === "batch-preparing" ? batchProgress.completed : undefined,
      total: operation === "batch-preparing" ? batchProgress.total : undefined,
      workers: operation === "batch-preparing" ? batchProgress.workers : undefined,
    });
    return () => onActivityChange(null);
  }, [batchProgress.completed, batchProgress.total, batchProgress.workers, forceField, onActivityChange, operation]);

  useEffect(() => {
    if (!onDockingInputChange) return;
    if (!record) {
      onDockingInputChange(null);
      return;
    }
    const ligandId = record.artifact.ligand_id;
    onDockingInputChange({
      ligand_id: ligandId,
      conformer: conformer?.artifact.ligand_id === ligandId ? conformer : null,
      pdbqt: pdbqt?.artifact.ligand_id === ligandId ? pdbqt : null,
    });
  }, [conformer, onDockingInputChange, pdbqt, record]);

  useEffect(() => {
    const libraryId = library?.artifact.library_id;
    if (!libraryId) return;
    let active = true;
    void ankoraApi.getLigandLibraryPreparation(libraryId).then((status) => {
      if (!active) return;
      setBatchResults((current) => {
        const next = { ...current };
        for (const entry of Object.values(status.entries)) {
          if (next[entry.ligand_id]) continue;
          next[entry.ligand_id] = {
            status: batchStatusFromPreparation(entry.status),
            chemicalStateId: entry.chemical_state_id,
            initialEnergyKcalMol: entry.initial_energy_kcal_mol ?? undefined,
            finalEnergyKcalMol: entry.final_energy_kcal_mol ?? undefined,
            error: entry.error_message ?? undefined,
            conformerId: entry.conformer_id,
            pdbqtPreparationId: entry.pdbqt_preparation_id,
          };
        }
        return next;
      });
    }).catch(() => undefined);
    return () => { active = false; };
  }, [library?.artifact.library_id]);

  useEffect(() => {
    if (!filterRun) {
      onLibraryStatusChange?.(null);
      return;
    }
    const status = summarizeLigandLibraryStatus(
      filterRun.selected_ligand_ids,
      (id) => batchResults[id]?.status,
    );
    onLibraryStatusChange?.(status);
    if (library && onLibraryDockingInputChange) {
      onLibraryDockingInputChange({
        library_id: library.artifact.library_id,
        library_name: library.artifact.filename,
        filter_run_id: filterRun.artifact.filter_run_id,
        selection_manifest_sha256: filterRun.artifact.sha256,
        selected_count: status.total,
        prepared_count: status.prepared,
      });
    }
  }, [filterRun, batchResults, library, onLibraryDockingInputChange, onLibraryStatusChange]);

  const currentBatchResult = record ? batchResults[record.artifact.ligand_id] : undefined;

  useEffect(() => {
    setResolution(null);
    setComponentIndex(null);
    setStereoisomerIndex(null);
    setProtonationOptions(null);
    setProtonationCandidateIndex(null);
    setProtonationSkipped(false);
    setMicrostateOptions(null);
    setMicrostateCandidateIndex(null);
    setMicrostateAcknowledged(false);
    const savedResult = record ? batchResults[record.artifact.ligand_id] : undefined;
    setConformer(savedResult?.conformer ?? null);
    setPdbqt(savedResult?.pdbqt ?? null);
    setViewMode("reference");
    // If this ligand already has a conformer - fresh from this session or
    // hydrated from persisted preparation status - its chemical state was
    // already explicitly acknowledged to generate it, whether that happened
    // through this checkbox or through the batch pipeline sending the same
    // acknowledgement. Showing "Review" for an already-completed ligand is
    // not honest reporting - the decision genuinely already happened.
    setStateConfirmed(Boolean(savedResult?.conformer ?? savedResult?.conformerId));
    setError(null);
    if (
      record?.state
      && (record.inspection.fragment_count > 1 || record.inspection.undefined_stereocenter_count > 0)
    ) {
      void loadResolutionOptions(record, null);
    }
  }, [record?.artifact.ligand_id]);

  // Separate from the reset above: this must also fire when persisted
  // preparation status hydrates *after* a ligand is already selected (the
  // common case - a library's first ligand auto-selects on import, before
  // the hydration fetch has resolved), not only when the selection itself
  // changes.
  useEffect(() => {
    if (!record || !currentBatchResult) return;
    const needsConformer = !currentBatchResult.conformer && currentBatchResult.conformerId;
    const needsPdbqt = !currentBatchResult.pdbqt && currentBatchResult.pdbqtPreparationId;
    if (!needsConformer && !needsPdbqt) return;
    const ligandId = record.artifact.ligand_id;
    let active = true;
    void (async () => {
      const conformerRecord = needsConformer
        ? await ankoraApi.getLigandConformer(ligandId, currentBatchResult.conformerId!).catch(() => null)
        : null;
      const pdbqtRecord = needsPdbqt
        ? await ankoraApi.getLigandPdbqt(ligandId, currentBatchResult.pdbqtPreparationId!).catch(() => null)
        : null;
      if (!active || (!conformerRecord && !pdbqtRecord)) return;
      setBatchResults((current) => ({
        ...current,
        [ligandId]: {
          ...current[ligandId],
          conformer: conformerRecord ?? current[ligandId]?.conformer,
          pdbqt: pdbqtRecord ?? current[ligandId]?.pdbqt,
        },
      }));
      if (record?.artifact.ligand_id === ligandId) {
        if (conformerRecord) { setConformer(conformerRecord); setStateConfirmed(true); }
        if (pdbqtRecord) setPdbqt(pdbqtRecord);
      }
    })();
    return () => { active = false; };
  }, [record?.artifact.ligand_id, currentBatchResult]);

  const activeMicrostate = record ? microstateStates[record.artifact.ligand_id] ?? null : null;
  const activeProtonation = record ? protonationStates[record.artifact.ligand_id] ?? null : null;
  const activeState = record ? resolvedStates[record.artifact.ligand_id] ?? null : null;
  const inspection = activeMicrostate?.inspection ?? activeProtonation?.inspection ?? activeState?.inspection ?? record?.inspection ?? null;
  const baseStateId = activeState?.artifact.state_id ?? record?.state?.state_id ?? null;
  const activeStateId = activeMicrostate?.artifact.state_id
    ?? activeProtonation?.artifact.state_id
    ?? activeState?.artifact.state_id
    ?? record?.state?.state_id
    ?? null;
  const activeContentUrl = activeMicrostate?.content_url ?? activeProtonation?.content_url ?? activeState?.content_url ?? record?.content_url ?? null;
  const blockers = inspection
    ? inspection.undefined_stereocenter_count + (inspection.fragment_count > 1 ? 1 : 0)
    : 0;

  const viewerSources = useMemo<ViewerSource[]>(() => {
    if (!record || !inspection || !activeContentUrl) return [];
    const reference: ViewerSource = {
      id: activeStateId ?? record.artifact.ligand_id,
      url: ankoraApi.ligandContentUrl(activeContentUrl),
      format: "sdf",
      label: activeMicrostate
        ? `${inspection.name} · explicitly selected screening microstate`
        : activeProtonation
        ? `${inspection.name} · explicitly protonated state`
        : activeState
        ? `${inspection.name} · explicitly resolved state`
        : record.artifact.source === "crystallographic"
          ? `${inspection.name} · observed crystallographic state`
          : `${inspection.name} · imported inspected state`,
    };
    if (!conformer || viewMode === "reference") return [reference];
    const minimized: ViewerSource = {
      id: conformer.artifact.conformer_id,
      url: ankoraApi.ligandContentUrl(conformer.content_url),
      format: "sdf",
      label: conformer.minimization.independent_from_source_coordinates
        ? `${inspection.name} · independent ETKDGv3 + ${conformer.minimization.force_field}`
        : `${inspection.name} · source geometry + ${conformer.minimization.force_field}`,
    };
    return viewMode === "minimized" ? [minimized] : [reference, minimized];
  }, [activeContentUrl, activeMicrostate, activeProtonation, activeState, activeStateId, conformer, inspection, record, viewMode]);

  async function extract() {
    if (!selected || selected.sequence_number === null) return;
    await runSourceOperation("extracting", () => ankoraApi.extractLigand(
      structure.artifact.artifact_id,
      {
        component_name: selected.name,
        chain_id: selected.chain_id,
        sequence_number: selected.sequence_number as number,
        insertion_code: selected.insertion_code,
      },
    ));
  }

  function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void importLibrary(file);
  }

  useEffect(() => {
    let disposed = false;
    void ankoraApi.listLigandLibraries({ limit: 200 })
      .then((page) => { if (!disposed) setLibraries(page.libraries); })
      // A catalog that cannot be read must not stop an import from working.
      .catch(() => { if (!disposed) setLibraries([]); });
    return () => { disposed = true; };
  }, [library]);

  async function importLibrary(file: File) {
    setOperation("importing");
    setError(null);
    try {
      const next = await ankoraApi.importLigandLibrary(file);
      setWorkspaceMode(next.imported_count > 1 ? "screening" : "single");
      setLibrary(next);
      setFilterPlan(DEFAULT_FILTER_PLAN);
      setMicrostatePlan(DEFAULT_MICROSTATE_PLAN);
      setFilterRun(null);
      onLibraryDockingInputChange?.(null);
      setFilterConfirmed(false);
      setResolvedStates({});
      setMicrostateStates({});
      setBatchResults({});
      setBatchConfirmed(false);
      const first = next.entries.find((entry) => entry.ligand)?.ligand;
      if (first) {
        onRecordChange(first);
        const preview = await ankoraApi.previewLigandLibraryFilters(next.artifact.library_id, {
          plan: DEFAULT_FILTER_PLAN,
          microstate_plan: DEFAULT_MICROSTATE_PLAN,
          state_overrides: {},
        });
        setFilterPreview(preview);
      }
      else setError(new Error("No molecular record in this library could be imported."));
    } catch (reason: unknown) {
      setError(asError(reason, "Ligand library import failed"));
    } finally {
      setOperation(null);
    }
  }

  /**
   * Reopen a library this project already holds, with its applied selection.
   *
   * The same file was imported 33 times in this project because nothing could
   * list what was already there. Restoring the latest filter run matters as
   * much as the library: a screen resumes at the selection it was actually
   * run with, rather than at an unfiltered library that looks the same.
   */
  async function openLibrary(libraryId: string) {
    setOperation("importing");
    setError(null);
    try {
      const next = await ankoraApi.getLigandLibrary(libraryId);
      setWorkspaceMode("screening");
      setLibrary(next);
      setFilterPlan(DEFAULT_FILTER_PLAN);
      setMicrostatePlan(DEFAULT_MICROSTATE_PLAN);
      setFilterRun(null);
      onLibraryDockingInputChange?.(null);
      setFilterConfirmed(false);
      setResolvedStates({});
      setMicrostateStates({});
      setBatchResults({});
      setBatchConfirmed(false);
      const first = next.entries.find((entry) => entry.ligand)?.ligand;
      if (first) onRecordChange(first);
      try {
        const run = await ankoraApi.latestLigandLibraryFilterRun(libraryId);
        setFilterRun(run);
        setFilterPlan(run.plan);
        setMicrostatePlan(run.microstate_plan ?? DEFAULT_MICROSTATE_PLAN);
        setFilterPreview({
          library_id: run.artifact.library_id,
          plan: run.plan,
          microstate_plan: run.microstate_plan ?? DEFAULT_MICROSTATE_PLAN,
          evaluations: run.evaluations,
          summary: run.summary,
          rdkit_version: run.rdkit_version,
          worker_count: run.worker_count,
        });
      } catch {
        // A library with no applied selection reopens unfiltered, which is
        // exactly what it was.
        const preview = await ankoraApi.previewLigandLibraryFilters(libraryId, {
          plan: DEFAULT_FILTER_PLAN,
          microstate_plan: DEFAULT_MICROSTATE_PLAN,
          state_overrides: {},
        });
        setFilterPreview(preview);
      }
    } catch (reason: unknown) {
      setError(asError(reason, "That library could not be reopened"));
    } finally {
      setOperation(null);
    }
  }

  async function runSourceOperation(
    nextOperation: Operation,
    action: () => Promise<LigandRecord>,
  ) {
    setOperation(nextOperation);
    setError(null);
    try {
      const next = await action();
      setWorkspaceMode("single");
      setLibrary(null);
      setFilterPreview(null);
      setFilterRun(null);
      onLibraryDockingInputChange?.(null);
      setResolvedStates({});
      setMicrostateStates({});
      setBatchResults({});
      onRecordChange(next);
    } catch (reason: unknown) {
      setError(asError(reason, "Ligand operation failed"));
    } finally {
      setOperation(null);
    }
  }

  async function loadResolutionOptions(
    sourceRecord: LigandRecord,
    selectedComponent: number | null,
  ) {
    if (!sourceRecord.state) return;
    setError(null);
    try {
      const next = await ankoraApi.ligandStateResolutionOptions(
        sourceRecord.artifact.ligand_id,
        sourceRecord.state.state_id,
        selectedComponent,
      );
      setResolution(next);
      setComponentIndex(next.selected_component_index);
      setStereoisomerIndex(null);
    } catch (reason: unknown) {
      setError(asError(reason, "Chemical-state options could not be inspected"));
    }
  }

  async function chooseComponent(nextIndex: number) {
    if (!record) return;
    setComponentIndex(nextIndex);
    setStereoisomerIndex(null);
    await loadResolutionOptions(record, nextIndex);
  }

  async function resolveState() {
    if (!record?.state || componentIndex === null) return;
    setOperation("resolving");
    setError(null);
    try {
      const next = await ankoraApi.resolveLigandState(record.artifact.ligand_id, {
        parent_state_id: record.state.state_id,
        component_index: componentIndex,
        stereoisomer_index: stereoisomerIndex,
      });
      const nextResolvedStates = {
        ...resolvedStates,
        [record.artifact.ligand_id]: next,
      };
      const nextMicrostateStates = { ...microstateStates };
      delete nextMicrostateStates[record.artifact.ligand_id];
      setResolvedStates(nextResolvedStates);
      setMicrostateStates(nextMicrostateStates);
      if (library) {
        // Refresh the preview so this ligand's updated descriptors are reflected,
        // but keep the already-applied filter run and batch confirmation intact -
        // resolving one ambiguous ligand should not force re-applying filters and
        // re-confirming the batch for every other ligand already in progress.
        const preview = await ankoraApi.previewLigandLibraryFilters(
          library.artifact.library_id,
          filterRequest(filterPlan, microstatePlan, nextResolvedStates, nextMicrostateStates),
        );
        setFilterPreview(preview);
      } else {
        setFilterRun(null);
        setFilterConfirmed(false);
        setBatchConfirmed(false);
      }
      setStateConfirmed(false);
      setProtonationOptions(null);
      setProtonationCandidateIndex(null);
      setProtonationSkipped(false);
      setConformer(null);
      setPdbqt(null);
      setViewMode("reference");
    } catch (reason: unknown) {
      setError(asError(reason, "Chemical-state resolution failed"));
    } finally {
      setOperation(null);
    }
  }

  async function bulkKeepLargestFragment(ligandIds: string[]) {
    if (!library) return;
    const targets = ligandIds.flatMap((ligandId) => {
      if (resolvedStates[ligandId]) return [];
      const entryLigand = library.entries.find(
        (entry) => entry.ligand?.artifact.ligand_id === ligandId,
      )?.ligand;
      return entryLigand?.state && entryLigand.inspection.fragment_count > 1 ? [entryLigand] : [];
    });
    if (!targets.length) {
      // A silent no-op here is indistinguishable from a broken button - this
      // action only ever applies to multi-fragment (salt) ligands; anything
      // needs-decision purely for undefined stereochemistry has nothing for
      // it to do, and that must be said out loud, not left to guesswork.
      setError(new Error(
        "None of the selected ligands are multi-fragment - this action only resolves salts/co-crystallized "
        + "fragments. Ligands needing a decision for undefined stereochemistry have no safe automatic default; "
        + "resolve them individually in the table, or use \"Exclude\" instead.",
      ));
      return;
    }
    setOperation("bulk-resolving");
    setError(null);
    try {
      const nextResolvedStates = { ...resolvedStates };
      let nextIndex = 0;
      async function resolveOne(ligand: LigandRecord) {
        try {
          const stateId = ligand.state!.state_id;
          const options = await ankoraApi.ligandStateResolutionOptions(
            ligand.artifact.ligand_id, stateId, null,
          );
          if (!options.component_options.length) return;
          const largest = options.component_options.reduce(
            (best, option) => (option.heavy_atom_count > best.heavy_atom_count ? option : best),
          );
          const withLargest = await ankoraApi.ligandStateResolutionOptions(
            ligand.artifact.ligand_id, stateId, largest.index,
          );
          // A safe generic default only exists for which fragment to keep, not
          // which stereoisomer to keep - leave that one for individual review.
          if (withLargest.stereoisomer_selection_required) return;
          const resolved = await ankoraApi.resolveLigandState(ligand.artifact.ligand_id, {
            parent_state_id: stateId,
            component_index: largest.index,
            stereoisomer_index: null,
          });
          nextResolvedStates[ligand.artifact.ligand_id] = resolved;
        } catch {
          // One ligand failing to resolve (network hiccup, transient error)
          // must not abort the rest of the selected group - it just stays
          // needs-decision for individual review, same as any other case a
          // bulk default cannot safely cover.
        }
      }
      async function worker() {
        while (nextIndex < targets.length) {
          const ligand = targets[nextIndex];
          nextIndex += 1;
          await resolveOne(ligand);
        }
      }
      await Promise.all(Array.from({ length: libraryWorkerCount(targets.length) }, worker));
      setResolvedStates(nextResolvedStates);
      const preview = await ankoraApi.previewLigandLibraryFilters(
        library.artifact.library_id,
        filterRequest(filterPlan, microstatePlan, nextResolvedStates, microstateStates),
      );
      setFilterPreview(preview);
    } catch (reason: unknown) {
      setError(asError(reason, "Bulk fragment resolution failed"));
    } finally {
      setOperation(null);
    }
  }

  function bulkExclude(ligandIds: string[]) {
    setBatchResults((current) => {
      const next = { ...current };
      for (const ligandId of ligandIds) next[ligandId] = { status: "excluded" };
      return next;
    });
  }

  useEffect(() => {
    if (library || !record || !activeStateId) return;
    if (protonationSkipped || activeProtonation || blockers) return;
    let disposed = false;
    setProtonationError(null);
    void ankoraApi.ligandProtonationOptions(
      record.artifact.ligand_id, activeStateId, phMin, phMax, phPrecision,
    )
      .then((next) => {
        if (disposed) return;
        setProtonationOptions(next);
        setProtonationCandidateIndex(next.candidates.length === 1 ? 0 : null);
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        setProtonationOptions(null);
        setProtonationCandidateIndex(null);
        setProtonationError(
          reason instanceof Error ? reason.message : "Dimorphite-DL could not enumerate states.",
        );
      });
    return () => { disposed = true; };
  }, [
    library, record?.artifact.ligand_id, activeStateId, protonationSkipped,
    activeProtonation, blockers, phMin, phMax, phPrecision,
  ]);

  async function enumerateProtonation() {
    if (!record || !activeStateId) return;
    setError(null);
    try {
      const next = await ankoraApi.ligandProtonationOptions(
        record.artifact.ligand_id,
        activeStateId,
        phMin,
        phMax,
        phPrecision,
      );
      setProtonationOptions(next);
      setProtonationCandidateIndex(next.candidates.length === 1 ? 0 : null);
    } catch (reason: unknown) {
      setError(asError(reason, "Protonation states could not be enumerated"));
    }
  }

  async function applyProtonation() {
    if (!record || !protonationOptions || protonationCandidateIndex === null) return;
    setOperation("resolving");
    setError(null);
    try {
      const next = await ankoraApi.resolveLigandProtonation(record.artifact.ligand_id, {
        parent_state_id: protonationOptions.parent_state_id,
        ph_min: protonationOptions.ph_min,
        ph_max: protonationOptions.ph_max,
        precision: protonationOptions.precision,
        candidate_index: protonationCandidateIndex,
      });
      setProtonationStates((current) => ({ ...current, [record.artifact.ligand_id]: next }));
      setProtonationOptions(null);
      setProtonationCandidateIndex(null);
      setConformer(null);
      setPdbqt(null);
      setViewMode("reference");
    } catch (reason: unknown) {
      setError(asError(reason, "Protonation state could not be applied"));
    } finally {
      setOperation(null);
    }
  }

  function skipProtonation() {
    setProtonationSkipped(true);
    setProtonationOptions(null);
    setProtonationCandidateIndex(null);
  }

  async function createConformer(
    independent: boolean, stateIdOverride?: string,
  ): Promise<LigandConformerRecord | null> {
    const stateId = stateIdOverride ?? activeStateId;
    if (!record || !stateId) return null;
    setOperation(independent ? "generating" : "minimizing");
    setError(null);
    setPdbqt(null);
    const common = {
      force_field: forceField,
      max_iterations: maxIterations,
      acknowledge_current_chemical_state: stateConfirmed,
      state_id: stateId,
    };
    let resultRecord: LigandConformerRecord | null = null;
    try {
      const next = independent
        ? await ankoraApi.generateLigandConformer(record.artifact.ligand_id, {
          ...common,
          random_seed: randomSeed,
        })
        : await ankoraApi.minimizeLigand(record.artifact.ligand_id, common);
      setConformer(next);
      setViewMode("minimized");
      resultRecord = next;
      setBatchResults((current) => ({
        ...current,
        [record.artifact.ligand_id]: {
          status: next.minimization.converged ? "minimized" : "nonconverged",
          conformer: next,
        },
      }));
    } catch (reason: unknown) {
      setError(asError(reason, "Conformer preparation failed"));
    } finally {
      setOperation(null);
    }
    return resultRecord;
  }

  async function preparePdbqt(
    conformerOverride?: LigandConformerRecord,
  ): Promise<LigandPdbqtRecord | null> {
    const source = conformerOverride ?? conformer;
    if (!record || !source) return null;
    setOperation("preparing-pdbqt");
    setError(null);
    let prepared: LigandPdbqtRecord | null = null;
    try {
      const next = await ankoraApi.prepareLigandPdbqt(
        record.artifact.ligand_id,
        source.artifact.conformer_id,
        { charge_model: "gasteiger" },
      );
      setPdbqt(next);
      prepared = next;
      setBatchResults((current) => ({
        ...current,
        [record.artifact.ligand_id]: {
          status: "prepared",
          conformer: source,
          pdbqt: next,
        },
      }));
    } catch (reason: unknown) {
      setError(asError(reason, "Ligand PDBQT preparation failed"));
    } finally {
      setOperation(null);
    }
    return prepared;
  }

  async function prepareForDocking() {
    if (!record || !activeStateId) return;
    setError(null);

    // 1 - Ionization. Only writes a record when a state was actually chosen;
    // a skipped or already-applied protonation leaves the state untouched.
    let stateId = activeStateId;
    if (
      !activeProtonation && !protonationSkipped
      && protonationOptions && protonationCandidateIndex !== null
    ) {
      setPreparationStep("protonation");
      setOperation("resolving");
      try {
        const applied = await ankoraApi.resolveLigandProtonation(record.artifact.ligand_id, {
          parent_state_id: protonationOptions.parent_state_id,
          ph_min: protonationOptions.ph_min,
          ph_max: protonationOptions.ph_max,
          precision: protonationOptions.precision,
          candidate_index: protonationCandidateIndex,
        });
        setProtonationStates((current) => ({ ...current, [record.artifact.ligand_id]: applied }));
        setProtonationOptions(null);
        setProtonationCandidateIndex(null);
        stateId = applied.artifact.state_id;
      } catch (reason: unknown) {
        setError(asError(reason, "Protonation state could not be applied"));
        setPreparationStep(null);
        setOperation(null);
        return;
      } finally {
        setOperation(null);
      }
    }

    // 2 - Geometry.
    setPreparationStep("conformer");
    const nextConformer = await createConformer(!useSourceGeometry, stateId);
    if (!nextConformer) {
      setPreparationStep(null);
      return;
    }
    // Hard gate: Meeko never runs on a geometry that did not converge. The
    // conformer is kept and shown so the scientist can judge it.
    if (!nextConformer.minimization.converged) {
      setPreparationStep(null);
      return;
    }

    // 3 - Docking format. Meeko gates only this last step: without it the
    // scientist still keeps a resolved, minimized, recorded conformer.
    if (!tools?.meeko_ligand.available) {
      setPreparationStep(null);
      return;
    }
    setPreparationStep("pdbqt");
    await preparePdbqt(nextConformer);
    setPreparationStep(null);
  }

  function changePh(next: { min?: number; max?: number; precision?: number }) {
    // Any pH change invalidates the enumeration it produced, so the card never
    // shows states belonging to a window that is no longer on screen.
    setProtonationOptions(null);
    setProtonationCandidateIndex(null);
    if (next.min !== undefined) setPhMin(clampDecimal(String(next.min), 0, 14));
    if (next.max !== undefined) setPhMax(clampDecimal(String(next.max), 0, 14));
    if (next.precision !== undefined) setPhPrecision(clampDecimal(String(next.precision), 0.1, 5));
  }

  function changeMicrostatePlan(change: Partial<LigandMicrostatePlan>) {
    setMicrostatePlan((current) => ({ ...current, ...change }));
    setMicrostateStates({});
    setMicrostateOptions(null);
    setMicrostateCandidateIndex(null);
    setMicrostateAcknowledged(false);
    setFilterPreview(null);
    setFilterRun(null);
    onLibraryDockingInputChange?.(null);
    setFilterConfirmed(false);
    setBatchConfirmed(false);
  }

  async function enumerateMicrostates() {
    if (!record || !baseStateId || blockers || microstatePlan.mode !== "enumerated_selection") return;
    setOperation("enumerating-microstates");
    setError(null);
    try {
      const next = await ankoraApi.ligandMicrostateOptions(
        record.artifact.ligand_id,
        baseStateId,
        microstatePlan,
      );
      setMicrostateOptions(next);
      // Candidate order is deterministic provenance, not a population or
      // desirability ranking. Even one candidate therefore needs a click.
      setMicrostateCandidateIndex(null);
      setMicrostateAcknowledged(false);
    } catch (reason: unknown) {
      setError(asError(reason, "Screening microstates could not be enumerated"));
    } finally {
      setOperation(null);
    }
  }

  async function selectMicrostate() {
    if (
      !record || !microstateOptions || microstateCandidateIndex === null
      || !microstateAcknowledged
    ) return;
    setOperation("selecting-microstate");
    setError(null);
    try {
      const next = await ankoraApi.resolveLigandMicrostate(record.artifact.ligand_id, {
        parent_state_id: microstateOptions.parent_state_id,
        plan: microstateOptions.plan,
        candidate_index: microstateCandidateIndex,
        acknowledge_bounded_enumeration: true,
      });
      const nextMicrostateStates = {
        ...microstateStates,
        [record.artifact.ligand_id]: next,
      };
      setMicrostateStates(nextMicrostateStates);
      setMicrostateOptions(null);
      setMicrostateCandidateIndex(null);
      setMicrostateAcknowledged(false);
      setFilterRun(null);
      onLibraryDockingInputChange?.(null);
      setFilterConfirmed(false);
      setBatchConfirmed(false);
      setBatchResults((current) => {
        const updated = { ...current };
        delete updated[record.artifact.ligand_id];
        return updated;
      });
      if (library) {
        const preview = await ankoraApi.previewLigandLibraryFilters(
          library.artifact.library_id,
          filterRequest(filterPlan, microstatePlan, resolvedStates, nextMicrostateStates),
        );
        setFilterPreview(preview);
      }
      setConformer(null);
      setPdbqt(null);
      setViewMode("reference");
    } catch (reason: unknown) {
      setError(asError(reason, "The selected screening microstate could not be recorded"));
    } finally {
      setOperation(null);
    }
  }

  async function prepareLibrary() {
    if (!library || !filterRun || !batchConfirmed) return;
    const appliedRun = filterRun;
    const selectedIds = new Set(appliedRun.selected_ligand_ids);
    const selectedStates = new Map(
      appliedRun.evaluations.map((evaluation) => [evaluation.ligand_id, evaluation.state_id]),
    );
    const ligands = library.entries.flatMap((entry) => (
      entry.ligand
      && selectedIds.has(entry.ligand.artifact.ligand_id)
      && !(
        batchResults[entry.ligand.artifact.ligand_id]?.status === "prepared"
        && batchResults[entry.ligand.artifact.ligand_id]?.chemicalStateId
          === selectedStates.get(entry.ligand.artifact.ligand_id)
      )
      && batchResults[entry.ligand.artifact.ligand_id]?.status !== "excluded"
        ? [entry.ligand]
        : []
    ));
    if (!ligands.length) return;
    const workerCount = libraryWorkerCount(ligands.length);
    setOperation("batch-preparing");
    setError(null);
    setBatchProgress({ completed: 0, total: ligands.length, workers: workerCount });
    let nextIndex = 0;
    let completed = 0;

    async function prepareOne(ligand: LigandRecord) {
      const ligandId = ligand.artifact.ligand_id;
      const evaluation = appliedRun.evaluations.find((item) => item.ligand_id === ligandId);
      const stateId = evaluation?.state_id ?? null;
      if (!stateId || evaluation?.disposition !== "eligible") {
        setBatchResults((current) => ({
          ...current,
          [ligandId]: { status: "needs-decision", chemicalStateId: stateId },
        }));
        return;
      }
        setBatchResults((current) => ({
          ...current,
          [ligandId]: { status: "generating", chemicalStateId: stateId },
      }));
      try {
        const nextConformer = await ankoraApi.generateLigandConformer(ligandId, {
          force_field: forceField,
          max_iterations: maxIterations,
          acknowledge_current_chemical_state: true,
          state_id: stateId,
          random_seed: randomSeed,
          client_concurrency_hint: workerCount,
        });
        let result: LigandBatchResult = {
          status: nextConformer.minimization.converged ? "minimized" : "nonconverged",
          chemicalStateId: stateId,
          conformer: nextConformer,
        };
        if (nextConformer.minimization.converged && tools?.meeko_ligand.available) {
          const nextPdbqt = await ankoraApi.prepareLigandPdbqt(
            ligandId,
            nextConformer.artifact.conformer_id,
            { charge_model: "gasteiger", client_concurrency_hint: workerCount },
          );
          result = { status: "prepared", chemicalStateId: stateId, conformer: nextConformer, pdbqt: nextPdbqt };
        }
        setBatchResults((current) => ({ ...current, [ligandId]: result }));
        if (record?.artifact.ligand_id === ligandId) {
          setConformer(nextConformer);
          setPdbqt(result.pdbqt ?? null);
          setViewMode("minimized");
        }
      } catch (reason: unknown) {
        const failure = asError(reason, "Ligand preparation failed");
        setBatchResults((current) => ({
          ...current,
          [ligandId]: { status: "failed", chemicalStateId: stateId, error: failure.message },
        }));
      }
    }

    async function worker() {
      while (nextIndex < ligands.length) {
        const index = nextIndex;
        nextIndex += 1;
        await prepareOne(ligands[index]);
        completed += 1;
        setBatchProgress({ completed, total: ligands.length, workers: workerCount });
      }
    }

    try {
      await Promise.all(Array.from({ length: workerCount }, () => worker()));
    } finally {
      setOperation(null);
    }
  }

  function changeFilterPlan(change: Partial<LigandLibraryFilterPlan>) {
    setFilterPlan((current) => ({ ...current, ...change, preset: "custom" }));
    setFilterPreview(null);
    setFilterRun(null);
    onLibraryDockingInputChange?.(null);
    setFilterConfirmed(false);
    setBatchConfirmed(false);
  }

  function resetFilterPlan() {
    setFilterPlan(DEFAULT_FILTER_PLAN);
    setFilterPreview(null);
    setFilterRun(null);
    onLibraryDockingInputChange?.(null);
    setFilterConfirmed(false);
    setBatchConfirmed(false);
  }

  async function previewFilters() {
    if (!library) return;
    setOperation("filtering");
    setError(null);
    try {
      const next = await ankoraApi.previewLigandLibraryFilters(
        library.artifact.library_id,
        filterRequest(filterPlan, microstatePlan, resolvedStates, microstateStates),
      );
      setFilterPreview(next);
      setFilterRun(null);
      onLibraryDockingInputChange?.(null);
      setFilterConfirmed(false);
      setBatchConfirmed(false);
    } catch (reason: unknown) {
      setError(asError(reason, "Library filters could not be evaluated"));
    } finally {
      setOperation(null);
    }
  }

  async function applyFilters() {
    if (!library || !filterPreview || !filterConfirmed) return;
    setOperation("applying-filter");
    setError(null);
    try {
      const next = await ankoraApi.applyLigandLibraryFilters(
        library.artifact.library_id,
        {
          ...filterRequest(filterPlan, microstatePlan, resolvedStates, microstateStates),
          acknowledge_selection: true,
        },
      );
      setFilterRun(next);
      setFilterPreview({
          library_id: next.artifact.library_id,
          plan: next.plan,
          microstate_plan: next.microstate_plan ?? microstatePlan,
        evaluations: next.evaluations,
        summary: next.summary,
        rdkit_version: next.rdkit_version,
        worker_count: next.worker_count,
      });
      // Deliberately not clearing batchResults here: a ligand already
      // prepared in an earlier apply is still genuinely prepared - its
      // PDBQT artifact still exists - regardless of whether a later filter
      // change or a newly-resolved needs-decision ligand changes who else
      // is in the selection. Wiping it would hide real completed work.
      setBatchConfirmed(false);
    } catch (reason: unknown) {
      setError(asError(reason, "Filtered library selection could not be applied"));
    } finally {
      setOperation(null);
    }
  }

  function selectLibraryLigand(ligandId: string) {
    const next = library?.entries.find(
      (entry) => entry.ligand?.artifact.ligand_id === ligandId,
    )?.ligand;
    if (next) onRecordChange(next);
  }

  const notice = viewerNotice(record, Boolean(activeMicrostate || activeState), conformer, viewMode);
  const stereoChoiceRequired = resolution?.stereoisomer_selection_required ?? false;
  const canResolve = componentIndex !== null
    && (!stereoChoiceRequired || stereoisomerIndex !== null);
  const libraryPreparationAllowed = !library || Boolean(
    record && filterRun?.selected_ligand_ids.includes(record.artifact.ligand_id),
  );
  const selectedCount = filterRun?.selected_ligand_ids.length ?? 0;
  const selectedStateIds = new Map(
    filterRun?.evaluations.map((evaluation) => [evaluation.ligand_id, evaluation.state_id]) ?? [],
  );
  const resultMatchesSelection = (id: string) => (
    batchResults[id]?.chemicalStateId === selectedStateIds.get(id)
  );
  const preparedCount = filterRun
    ? filterRun.selected_ligand_ids.filter((id) => (
        batchResults[id]?.status === "prepared" && resultMatchesSelection(id)
      )).length
    : 0;
  const excludedCount = filterRun
    ? filterRun.selected_ligand_ids.filter((id) => batchResults[id]?.status === "excluded").length
    : 0;
  const terminalCount = filterRun
    ? filterRun.selected_ligand_ids.filter((id) => (
        isTerminalLigandBatchStatus(batchResults[id]?.status) && resultMatchesSelection(id)
      )).length
    : 0;
  const pendingCount = selectedCount - terminalCount;
  const retryableCount = filterRun
    ? filterRun.selected_ligand_ids.filter((id) => {
        const status = batchResults[id]?.status;
        return resultMatchesSelection(id)
          && (status === "failed" || status === "minimized" || status === "nonconverged");
      }).length
    : 0;
  const processableCount = pendingCount + retryableCount;
  const libraryLigandsById = useMemo(() => new Map(
    library?.entries.flatMap((entry) => (entry.ligand ? [[entry.ligand.artifact.ligand_id, entry.ligand] as const] : [])) ?? [],
  ), [library]);
  // Needs-decision ligands live entirely outside filterRun - source them
  // from the filter preview instead, so this is known as soon as a preview
  // exists, before the user ever applies or prepares anything.
  const needsDecisionIds = filterPreview
    ? filterPreview.evaluations.filter((evaluation) => {
        if (evaluation.disposition !== "needs_decision") return false;
        if (batchResults[evaluation.ligand_id]?.status === "excluded") return false;
        const ligand = libraryLigandsById.get(evaluation.ligand_id);
        if (!ligand) return true;
        // Re-check the ligand's actual current state rather than trusting a
        // preview that may predate a resolution already applied this
        // session - the preview is refreshed after resolving, but only
        // asynchronously.
        const inspected = resolvedStates[evaluation.ligand_id]?.inspection ?? ligand.inspection;
        return inspected.fragment_count > 1 || inspected.undefined_stereocenter_count > 0;
      }).map((evaluation) => evaluation.ligand_id)
    : [];
  const needsDecisionCount = needsDecisionIds.length;
  // "Keep largest fragment" only ever touches multi-fragment (salt)
  // ligands - label it with the count it will actually affect, not the
  // full needs-decision count, so a click never looks like it did nothing.
  const fragmentDecisionCount = needsDecisionIds.filter((id) => {
    const ligand = libraryLigandsById.get(id);
    const inspected = resolvedStates[id]?.inspection ?? ligand?.inspection;
    return (inspected?.fragment_count ?? 0) > 1;
  }).length;
  const missingMicrostateCount = microstatePlan.mode === "enumerated_selection" && filterPreview
    ? filterPreview.evaluations.filter((evaluation) => (
        evaluation.disposition === "eligible" && !microstateStates[evaluation.ligand_id]
      )).length
    : 0;

  return <>
    <section className="workspace" aria-label="Ligand workspace">
      <div className="workspace-heading">
        <div><span className="eyebrow">03 / Ligand</span><h2>{workspaceMode === "screening" ? "Filter and prepare a virtual-screening library" : "Resolve and prepare one docking ligand"}</h2></div>
        <div className="workspace-actions">
          <div className="workspace-mode-switch" aria-label="Ligand workspace mode"><button type="button" className={workspaceMode === "single" ? "selected" : ""} onClick={() => setWorkspaceMode("single")}>Single ligand</button><button type="button" className={workspaceMode === "screening" ? "selected" : ""} onClick={() => { setWorkspaceMode("screening"); setSourceMode("local"); }}>Virtual screening</button></div>
          {conformer ? <div className="view-switch" aria-label="Ligand view">
            {(["reference", "minimized", "overlay"] as const).map((mode) => <button key={mode} type="button" className={viewMode === mode ? "selected" : ""} onClick={() => setViewMode(mode)}>{mode}</button>)}
          </div> : null}
        </div>
      </div>
      {operation ? <div
        className="operation-progress"
        role="progressbar"
        aria-valuemin={operation === "batch-preparing" ? 0 : undefined}
        aria-valuemax={operation === "batch-preparing" ? batchProgress.total : undefined}
        aria-valuenow={operation === "batch-preparing" ? batchProgress.completed : undefined}
      ><span className={operation === "batch-preparing" ? "determinate" : ""} style={operation === "batch-preparing" ? { width: `${batchProgress.total ? (batchProgress.completed / batchProgress.total) * 100 : 0}%` } : undefined} /><p>{operationLabel(operation, forceField)}{operation === "batch-preparing" ? ` ${batchProgress.completed}/${batchProgress.total} · ${batchProgress.workers} parallel workers` : ""}</p></div> : null}
      {error ? <ErrorBanner error={error} /> : null}
      {filterPreview && needsDecisionCount > 0 ? (
        <div className="protonation-blocker needs-decision-notice" role="alert">
          <p><strong>{needsDecisionCount} ligand{needsDecisionCount === 1 ? "" : "s"} need{needsDecisionCount === 1 ? "s" : ""} a decision.</strong> Their component/stereochemistry is ambiguous, so they are never included in a filtered selection - resolving or excluding them now, before applying filters, is what gets them into the batch. Resolve each individually in the table below, or act on all {needsDecisionCount} at once:</p>
          <div className="protonation-blocker-actions">
            {fragmentDecisionCount > 0 ? (
              <button type="button" disabled={operation === "bulk-resolving"} onClick={() => void bulkKeepLargestFragment(needsDecisionIds)}>Keep largest fragment for {fragmentDecisionCount} multi-fragment</button>
            ) : null}
            <button type="button" disabled={operation === "bulk-resolving"} onClick={() => bulkExclude(needsDecisionIds)}>Exclude all {needsDecisionCount}</button>
          </div>
        </div>
      ) : null}
      {library ? <div className="scientific-workbench ligand-workbench">
        <div className="viewer-pane">{record ? <><div className={`viewer-mode-notice ${viewMode === "overlay" ? "overlay" : "prepared"}`} role="status"><strong>{notice[0]}</strong><span>{notice[1]}</span></div><MolecularViewer sources={viewerSources} selection={null} /></> : <div className="viewer-placeholder ligand-placeholder"><div className="viewer-message"><h3>Select a molecule</h3><p>Choose a library row to inspect its preserved chemical state.</p></div></div>}</div>
        <LigandLibraryTable
          library={library}
          preview={filterPreview}
          selectedLigandId={record?.artifact.ligand_id ?? null}
          results={batchResults}
          onSelect={selectLibraryLigand}
          onBulkKeepLargestFragment={(ids) => void bulkKeepLargestFragment(ids)}
          onBulkExclude={bulkExclude}
          bulkActionPending={operation === "bulk-resolving"}
        />
      </div> : record ? <><div className={`viewer-mode-notice ${viewMode === "overlay" ? "overlay" : "prepared"}`} role="status"><strong>{notice[0]}</strong><span>{notice[1]}</span></div><MolecularViewer sources={viewerSources} selection={null} /></> : <div className="viewer-placeholder ligand-placeholder"><div className="viewer-message"><div className="molecule-glyph">⌬</div><h3>{workspaceMode === "screening" ? "Open a compound library" : "Choose a ligand source"}</h3><p>{workspaceMode === "screening" ? "Import SDF, SD-style MOL, SMI, or SMILES with multiple records. Ankora preserves source order and invalid-record evidence." : "Extract a crystallographic component or import one local ligand. Ankora preserves the original before creating a chemical state."}</p></div></div>}
    </section>
    <aside className="inspector ligand-inspector" aria-label="Ligand inspector">
      <div className="inspector-heading"><span className="section-label">Ligand preparation</span><h2>{inspection?.name ?? structure.metadata.entry_id ?? "New ligand"}</h2><p className="inspector-subtitle">Every decision creates a linked derivative; the original never changes.</p></div>
      <SourceSection candidates={candidates} selected={selected} sourceMode={sourceMode} operation={operation} hasRecord={Boolean(record)} screening={workspaceMode === "screening"} onModeChange={setSourceMode} onSelect={setSelected} onExtract={() => void extract()} onImport={importFile} libraries={libraries} onOpenLibrary={(id) => void openLibrary(id)} />
      {library ? <LibraryFilterControls
        plan={filterPlan}
        preview={filterPreview}
        run={filterRun}
        confirmed={filterConfirmed}
        operation={operation}
        missingMicrostateCount={missingMicrostateCount}
        onPlanChange={changeFilterPlan}
        onResetPlan={resetFilterPlan}
        onConfirmedChange={setFilterConfirmed}
        onPreview={() => void previewFilters()}
        onApply={() => void applyFilters()}
      /> : null}
      {library ? <InspectorStage title="3 · Library preparation" className="ligand-batch-controls" defaultOpen={Boolean(filterRun)} summary={filterRun ? `${filterRun.selected_ligand_ids.length} selected` : "Apply filters first"}>
        <p className="field-note">{filterRun ? `${filterRun.selected_ligand_ids.length} explicitly selected molecules are ready for 3D preparation.` : "Apply the filter preview first. No molecule is minimized from a provisional selection."}</p>
        <label className="check-row"><input type="checkbox" checked={batchConfirmed} disabled={!filterRun} onChange={(event) => setBatchConfirmed(event.target.checked)} /><span><strong>Prepare the applied filtered subset</strong><small>Generate independent ETKDGv3 coordinates, minimize with {forceField}, and create PDBQT when Meeko is available.</small></span></label>
        <p className="field-note">Batch preparation uses the exact chemical-state ID recorded by the applied manifest. {filterRun?.microstate_plan?.mode === "enumerated_selection" ? "Every included parent compound therefore carries one explicitly selected bounded protonation/tautomer state." : "The exact submitted or component-resolved state is retained; no protonation or tautomer is selected silently."}</p>
        {filterRun && selectedCount > 0 && terminalCount === selectedCount ? (
          <>
            <p className="prepared-summary"><strong>Batch complete</strong><span>{preparedCount}/{selectedCount} ligands are PDBQT-ready{selectedCount - preparedCount ? ` · ${selectedCount - preparedCount} retained without docking-ready output` : ""}{excludedCount ? ` · ${excludedCount} explicitly excluded` : ""}. Ankora will continue to Binding site; every unsuccessful outcome remains recorded.</span></p>
            {retryableCount > 0 ? <button type="button" className="secondary-action" disabled={!batchConfirmed || Boolean(operation)} onClick={() => void prepareLibrary()}>Retry {retryableCount} unsuccessful ligand{retryableCount === 1 ? "" : "s"}</button> : null}
          </>
        ) : processableCount > 0 ? (
          <button type="button" className="apply-plan" disabled={!filterRun || !batchConfirmed || Boolean(operation) || processableCount === 0} onClick={() => void prepareLibrary()}>
            {preparedCount > 0 || excludedCount > 0 || retryableCount > 0 ? `Process ${processableCount} remaining ligands` : `Process ${processableCount} selected ligands`}
          </button>
        ) : null}
      </InspectorStage> : null}
      {record && inspection ? <>
        <LigandSummary record={record} inspection={inspection} resolved={Boolean(activeState) || Boolean(activeProtonation) || Boolean(activeMicrostate)} />
        {library || blockers || activeState ? <>
        <InspectorStage title={`${library ? "4" : "2"} · Chemical state`} className="ligand-state-controls" defaultOpen={!stateConfirmed} summary={stateConfirmed ? "Confirmed" : blockers ? "Decision required" : "Review"}>
          {blockers && !activeState ? <>
            <p className="protonation-blocker">This state needs an explicit component and/or stereochemistry decision before 3D generation.</p>
            {resolution ? <>
              <label className="field-label" htmlFor="ligand-component">Component to retain</label>
              <select id="ligand-component" value={componentIndex ?? ""} onChange={(event) => void chooseComponent(Number(event.target.value))}>
                <option value="" disabled>Choose one component</option>
                {resolution.component_options.map((option) => <option key={option.index} value={option.index}>{option.formula} · charge {option.formal_charge >= 0 ? "+" : ""}{option.formal_charge} · {option.heavy_atom_count} heavy atoms</option>)}
              </select>
              {componentIndex !== null ? <small className="state-smiles">{resolution.component_options.find((item) => item.index === componentIndex)?.canonical_smiles}</small> : null}
              {resolution.stereoisomer_selection_required ? <>
                <label className="field-label" htmlFor="ligand-stereoisomer">Defined stereoisomer</label>
                <select id="ligand-stereoisomer" value={stereoisomerIndex ?? ""} onChange={(event) => setStereoisomerIndex(Number(event.target.value))}>
                  <option value="" disabled>Choose one stereoisomer</option>
                  {resolution.stereoisomer_options.map((option) => <option key={option.index} value={option.index}>Isomer {option.index + 1} · {option.canonical_isomeric_smiles}</option>)}
                </select>
              </> : null}
              <button type="button" className="apply-plan" disabled={!canResolve || Boolean(operation)} onClick={() => void resolveState()}>Create explicitly resolved state</button>
            </> : <p className="field-note">Inspecting state alternatives…</p>}
          </> : <>
            {activeState ? <div className="state-resolved-note"><strong>Explicit state created</strong><small>Component {activeState.selection.component_index + 1}; {activeState.selection.stereoisomer_index === null ? "stereochemistry already defined" : `stereoisomer ${activeState.selection.stereoisomer_index + 1}`}.</small></div> : null}
            {library ? <label className="check-row"><input type="checkbox" checked={stateConfirmed} onChange={(event) => setStateConfirmed(event.target.checked)} /><span><strong>Use this exact inspected state</strong><small>Confirm formal charge, bond orders, component, and stereochemistry. No alternative is selected silently.</small></span></label> : null}
          </>}
        </InspectorStage>
        </> : null}
        {library ? <>
        <InspectorStage
          title="5 · Screening microstate"
          className="ligand-protonation-controls"
          defaultOpen={microstatePlan.mode === "enumerated_selection" && !activeMicrostate}
          summary={microstatePlan.mode === "exact_imported_state" ? "Exact supplied state" : activeMicrostate ? "Selected" : "Selection required"}
        >
          <label className="field-label" htmlFor="library-microstate-policy">Screening chemical-state policy</label>
          <select
            id="library-microstate-policy"
            value={microstatePlan.mode}
            onChange={(event) => changeMicrostatePlan({ mode: event.target.value as LigandMicrostatePlan["mode"] })}
          >
            <option value="exact_imported_state">Use exact supplied/resolved state</option>
            <option value="enumerated_selection">Enumerate, then explicitly select one state per parent</option>
          </select>
          {microstatePlan.mode === "exact_imported_state" ? (
            <div className="state-resolved-note">
              <strong>Exact-state policy</strong>
              <small>Ankora filters and prepares the submitted or explicitly component-resolved state. Protonation and tautomer alternatives are not generated.</small>
            </div>
          ) : <>
            <div className="filter-policy-grid">
              <label><span>pH min</span><input aria-label="Screening minimum pH" type="number" step={0.1} min={0} max={14} value={microstatePlan.ph_min} onChange={(event) => changeMicrostatePlan({ ph_min: clampDecimal(event.target.value, 0, 14) })} /></label>
              <label><span>pH max</span><input aria-label="Screening maximum pH" type="number" step={0.1} min={0} max={14} value={microstatePlan.ph_max} onChange={(event) => changeMicrostatePlan({ ph_max: clampDecimal(event.target.value, 0, 14) })} /></label>
              <label><span>pKa precision</span><input aria-label="Screening pKa precision" type="number" step={0.1} min={0.1} max={5} value={microstatePlan.precision} onChange={(event) => changeMicrostatePlan({ precision: clampDecimal(event.target.value, 0.1, 5) })} /></label>
              <label><span>Tautomers / protomer</span><input aria-label="Maximum tautomers per protomer" type="number" min={1} max={32} value={microstatePlan.max_tautomers_per_protomer} onChange={(event) => changeMicrostatePlan({ max_tautomers_per_protomer: clampNumber(event.target.value, 1, 32) })} /></label>
              <label><span>States / parent</span><input aria-label="Maximum microstates per parent" type="number" min={1} max={64} value={microstatePlan.max_microstates_per_parent} onChange={(event) => changeMicrostatePlan({ max_microstates_per_parent: clampNumber(event.target.value, 1, 64) })} /></label>
            </div>
            <p className="field-note">Dimorphite-DL proposes protonation states and RDKit enumerates tautomers inside these recorded bounds. Candidate order is deterministic but is not a population, probability, or preference ranking.</p>
            {blockers ? <p className="protonation-blocker">Resolve the component and stereochemistry above before enumerating this parent compound.</p> : activeMicrostate ? (
              <div className="state-resolved-note">
                <strong>Selected microstate recorded</strong>
                <small>Candidate {activeMicrostate.selection.candidate_index + 1} of {activeMicrostate.selection.candidate_count} · formal charge {activeMicrostate.inspection.formal_charge >= 0 ? "+" : ""}{activeMicrostate.inspection.formal_charge}{activeMicrostate.selection.enumeration_truncated ? " · bounded set was truncated" : ""}</small>
              </div>
            ) : null}
            <button type="button" className="apply-plan" disabled={Boolean(operation) || Boolean(blockers)} onClick={() => void enumerateMicrostates()}>{activeMicrostate ? "Enumerate again for this parent" : "Enumerate this parent compound"}</button>
            {microstateOptions ? <>
              <p className={microstateOptions.truncated ? "protonation-blocker" : "field-note"}>{microstateOptions.candidates.length} retained candidate{microstateOptions.candidates.length === 1 ? "" : "s"} from {microstateOptions.protonation_candidate_count} protonation proposal{microstateOptions.protonation_candidate_count === 1 ? "" : "s"}.{microstateOptions.truncated ? " The configured bound truncated the enumerated set." : ""}</p>
              <label className="field-label" htmlFor="ligand-microstate-candidate">Exact state to carry forward</label>
              <select id="ligand-microstate-candidate" value={microstateCandidateIndex ?? ""} onChange={(event) => { setMicrostateCandidateIndex(Number(event.target.value)); setMicrostateAcknowledged(false); }}>
                <option value="" disabled>Choose one unranked candidate</option>
                {microstateOptions.candidates.map((candidate) => <option key={candidate.microstate_key} value={candidate.index}>charge {candidate.formal_charge >= 0 ? "+" : ""}{candidate.formal_charge} · protomer {candidate.protonation_candidate_index + 1} · tautomer {candidate.tautomer_index + 1}{candidate.matches_parent_state ? " · matches parent" : ""} · {candidate.canonical_isomeric_smiles}</option>)}
              </select>
              <label className="check-row"><input type="checkbox" checked={microstateAcknowledged} onChange={(event) => setMicrostateAcknowledged(event.target.checked)} /><span><strong>Select this exact bounded candidate</strong><small>I understand that omitted states may exist and that the list is not ranked by biological population or docking suitability.</small></span></label>
              <button type="button" className="apply-plan" disabled={microstateCandidateIndex === null || !microstateAcknowledged || Boolean(operation)} onClick={() => void selectMicrostate()}>Record selected screening microstate</button>
            </> : null}
          </>}
        </InspectorStage>
        <InspectorStage title={`${library ? "6" : "4"} · 3D conformer + minimization`} className="minimization-controls" defaultOpen={stateConfirmed && !conformer} summary={conformer ? conformer.minimization.converged ? "Converged" : "Review" : "Pending"}>
          {conformer ? (
            <div className="state-resolved-note"><strong>Conformer already generated</strong><small>{conformer.minimization.converged ? "Minimization converged." : "The iteration limit was reached before convergence — review below."} See the recorded result below. Regenerating creates a separate derivative, it never overwrites this one.</small></div>
          ) : null}
          <details className="minimization-regenerate" open={!conformer}>
            {conformer ? <summary>Regenerate with different settings</summary> : null}
            <label className="field-label" htmlFor="ligand-force-field">Force field</label>
            <select id="ligand-force-field" value={forceField} onChange={(event) => setForceField(event.target.value as LigandForceField)}><option value="MMFF94s">MMFF94s</option><option value="MMFF94">MMFF94</option></select>
            <label className="numeric-field"><span>Maximum iterations</span><input aria-label="Maximum minimization iterations" type="number" min={1} max={10000} value={maxIterations} onChange={(event) => setMaxIterations(clampNumber(event.target.value, 1, 10000))} /></label>
            <label className="numeric-field"><span>ETKDG random seed</span><input aria-label="ETKDG random seed" type="number" min={0} max={2147483647} value={randomSeed} onChange={(event) => setRandomSeed(clampNumber(event.target.value, 0, 2147483647))} /></label>
            <p className="field-note">Independent generation removes source coordinates, embeds with ETKDGv3, adds explicit hydrogens, and minimizes with the selected MMFF variant.</p>
            {!libraryPreparationAllowed ? <p className="protonation-blocker">Apply a filter selection that includes this molecule before generating or minimizing its 3D conformer.</p> : null}
            <div className="conformer-actions">
              {inspection.has_3d_coordinates ? <button type="button" disabled={!libraryPreparationAllowed || !stateConfirmed || Boolean(blockers) || Boolean(operation)} onClick={() => void createConformer(false)}>Minimize source geometry</button> : null}
              <button type="button" className="primary" disabled={!libraryPreparationAllowed || !stateConfirmed || Boolean(blockers) || Boolean(operation)} onClick={() => void createConformer(true)}>Generate independent 3D + minimize</button>
            </div>
          </details>
        </InspectorStage>
        </> : <SingleLigandPreparation
          inspection={inspection}
          activeState={activeState}
          activeProtonation={activeProtonation}
          protonationOptions={protonationOptions}
          protonationCandidateIndex={protonationCandidateIndex}
          onCandidateChange={setProtonationCandidateIndex}
          protonationSkipped={protonationSkipped}
          protonationError={protonationError}
          onSkipProtonation={skipProtonation}
          onReconsiderProtonation={() => setProtonationSkipped(false)}
          phMin={phMin}
          phMax={phMax}
          phPrecision={phPrecision}
          onPhChange={changePh}
          forceField={forceField}
          setForceField={setForceField}
          maxIterations={maxIterations}
          setMaxIterations={setMaxIterations}
          randomSeed={randomSeed}
          setRandomSeed={setRandomSeed}
          useSourceGeometry={useSourceGeometry}
          setUseSourceGeometry={setUseSourceGeometry}
          acknowledged={stateConfirmed}
          setAcknowledged={setStateConfirmed}
          conformer={conformer}
          pdbqt={pdbqt}
          meekoAvailable={Boolean(tools?.meeko_ligand.available)}
          blocked={Boolean(blockers) && !activeState}
          step={preparationStep}
          busy={Boolean(operation)}
          onPrepare={() => void prepareForDocking()}
        />}
        {conformer ? <ConformerResult conformer={conformer} /> : null}
        {library ? <>
        <InspectorStage title={`${library ? "7" : "5"} · Docking format`} className="ligand-pdbqt-controls" defaultOpen={Boolean(conformer) && !pdbqt} summary={pdbqt ? "PDBQT ready" : "Pending"}>
          {pdbqt ? (
            <div className="state-resolved-note"><strong>PDBQT already generated</strong><small>Gasteiger partial charges with Meeko {pdbqt.tool.version}. See the recorded output below — nothing left to do here.</small></div>
          ) : <>
            <div className="state-resolved-note"><strong>Gasteiger partial charges</strong><small>Meeko preparation is explicit and does not alter the accepted conformer SDF.</small></div>
            {!tools?.meeko_ligand.available ? <p className="protonation-blocker">Meeko ligand preparation is not configured.</p> : null}
            <button type="button" className="apply-plan" disabled={!conformer?.minimization.converged || !tools?.meeko_ligand.available || Boolean(operation)} onClick={() => void preparePdbqt()}>Generate ligand PDBQT with Meeko</button>
          </>}
        </InspectorStage>
        </> : null}
        {pdbqt ? <section className="minimization-result converged ligand-pdbqt-result">
          <strong>Docking ligand prepared</strong>
          <dl><div><dt>Tool</dt><dd>Meeko {pdbqt.tool.version}</dd></div><div><dt>Charges</dt><dd>{pdbqt.charge_model}</dd></div><div><dt>Size</dt><dd>{pdbqt.artifact.size_bytes.toLocaleString()} bytes</dd></div></dl>
          <small>PDBQT SHA-256 · {pdbqt.artifact.sha256.slice(0, 16)}…</small>
          <details><summary>Recorded command and raw output</summary><pre>{JSON.stringify({ command: pdbqt.command, stdout: pdbqt.stdout, stderr: pdbqt.stderr }, null, 2)}</pre></details>
        </section> : null}
      </> : null}
    </aside>
  </>;
}

interface SourceSectionProps {
  candidates: HeterogenSummary[];
  selected: HeterogenSummary | null;
  sourceMode: LigandSourceMode;
  operation: Operation;
  hasRecord: boolean;
  screening: boolean;
  onModeChange: (mode: LigandSourceMode) => void;
  onSelect: (candidate: HeterogenSummary) => void;
  onExtract: () => void;
  onImport: (event: ChangeEvent<HTMLInputElement>) => void;
  /** Libraries already in the project, so one need not be imported twice. */
  libraries: LigandLibrarySummary[];
  onOpenLibrary: (libraryId: string) => void;
}

/**
 * The libraries this project already holds.
 *
 * Ankora recorded 38 library imports of only 4 distinct files - one of them
 * imported 33 times - because a library was addressable by id but nothing
 * could list them. Reopening one restores its applied selection too, so a
 * screen resumes where it was rather than at an unfiltered library.
 */
function LibraryShelf({ libraries, busy, onOpen }: {
  libraries: LigandLibrarySummary[];
  busy: boolean;
  onOpen: (libraryId: string) => void;
}) {
  if (!libraries.length) return null;
  return (
    <div className="library-shelf">
      <div className="filter-heading"><span>Already in this project</span></div>
      <div className="library-shelf-list" role="list" aria-label="Imported libraries">
        {libraries.map((entry) => (
          <button
            type="button"
            role="listitem"
            key={entry.artifact.library_id}
            disabled={busy}
            onClick={() => onOpen(entry.artifact.library_id)}
          >
            <strong>{entry.artifact.filename}</strong>
            <small>
              {entry.artifact.record_count} records · {formatImported(entry.artifact.created_at)}
              {entry.filter_run_count
                ? ` · ${entry.filter_run_count} applied selection${entry.filter_run_count === 1 ? "" : "s"}`
                : " · no selection applied"}
            </small>
          </button>
        ))}
      </div>
    </div>
  );
}

function formatImported(value: string): string {
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return value;
  return moment.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

interface LibraryFilterControlsProps {
  plan: LigandLibraryFilterPlan;
  preview: LigandLibraryFilterPreview | null;
  run: LigandLibraryFilterRun | null;
  confirmed: boolean;
  operation: Operation;
  missingMicrostateCount: number;
  onPlanChange: (change: Partial<LigandLibraryFilterPlan>) => void;
  onResetPlan: () => void;
  onConfirmedChange: (confirmed: boolean) => void;
  onPreview: () => void;
  onApply: () => void;
}

function InspectorStage({ title, summary, className = "", defaultOpen, children }: { title: string; summary: string; className?: string; defaultOpen: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => { if (defaultOpen) setOpen(true); }, [defaultOpen]);
  return <details className={`receptor-section inspector-stage ${className}`} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary><span>{title}</span><small>{summary}</small></summary>
    <div className="inspector-stage-body">{children}</div>
  </details>;
}

function LibraryFilterControls(props: LibraryFilterControlsProps) {
  const summary = props.preview?.summary;
  return <InspectorStage title="2 · Library filters" className="ligand-filter-controls" defaultOpen={!props.run} summary={summary ? `${summary.eligible_count} eligible` : "Preview required"}>
    <div className="filter-heading"><span>Filter policy</span><div><span>{props.plan.preset === "general_oral" ? "General oral default" : "Custom"}</span>{props.plan.preset === "custom" ? <button type="button" onClick={props.onResetPlan}>Reset</button> : null}</div></div>
    <p className="field-note">Lipinski and Veber control default eligibility. QED ranks compounds; Ghose and Muegge stay informative unless enabled.</p>
    <div className="filter-rule-controls">
      <label className="filter-toggle"><input type="checkbox" checked={props.plan.require_lipinski} onChange={(event) => props.onPlanChange({ require_lipinski: event.target.checked })} /><span><strong>Lipinski</strong><small>Required · allow up to</small></span><input aria-label="Maximum Lipinski violations" type="number" min={0} max={4} disabled={!props.plan.require_lipinski} value={props.plan.max_lipinski_violations} onChange={(event) => props.onPlanChange({ max_lipinski_violations: clampNumber(event.target.value, 0, 4) })} /></label>
      <label className="filter-toggle"><input type="checkbox" checked={props.plan.require_veber} onChange={(event) => props.onPlanChange({ require_veber: event.target.checked })} /><span><strong>Veber</strong><small>Required by default</small></span></label>
      <label className="filter-toggle"><input type="checkbox" checked={props.plan.require_ghose} onChange={(event) => props.onPlanChange({ require_ghose: event.target.checked })} /><span><strong>Ghose</strong><small>{props.plan.require_ghose ? "Required" : "Informative"}</small></span></label>
      <label className="filter-toggle"><input type="checkbox" checked={props.plan.require_muegge} onChange={(event) => props.onPlanChange({ require_muegge: event.target.checked })} /><span><strong>Muegge</strong><small>{props.plan.require_muegge ? "Required" : "Informative"}</small></span></label>
      <label className="filter-toggle"><input type="checkbox" checked={props.plan.minimum_qed !== null} onChange={(event) => props.onPlanChange({ minimum_qed: event.target.checked ? 0.5 : null })} /><span><strong>Minimum QED</strong><small>{props.plan.minimum_qed === null ? "Rank only" : "Required"}</small></span><input aria-label="Minimum QED" type="number" min={0} max={1} step={0.05} disabled={props.plan.minimum_qed === null} value={props.plan.minimum_qed ?? 0.5} onChange={(event) => props.onPlanChange({ minimum_qed: clampDecimal(event.target.value, 0, 1) })} /></label>
    </div>
    <div className="filter-policy-grid">
      <label><span>PAINS</span><select aria-label="PAINS policy" value={props.plan.pains_policy} onChange={(event) => props.onPlanChange({ pains_policy: event.target.value as LigandLibraryFilterPlan["pains_policy"] })}><option value="review">Flag for review</option><option value="exclude">Exclude</option><option value="ignore">Record only</option></select></label>
      <label><span>Brenk</span><select aria-label="Brenk policy" value={props.plan.brenk_policy} onChange={(event) => props.onPlanChange({ brenk_policy: event.target.value as LigandLibraryFilterPlan["brenk_policy"] })}><option value="review">Flag for review</option><option value="exclude">Exclude</option><option value="ignore">Record only</option></select></label>
      <label><span>Duplicates</span><select aria-label="Duplicate policy" value={props.plan.duplicate_policy} onChange={(event) => props.onPlanChange({ duplicate_policy: event.target.value as LigandLibraryFilterPlan["duplicate_policy"] })}><option value="exclude">Exclude repeats</option><option value="review">Flag for review</option><option value="keep">Keep all</option></select></label>
    </div>
    <div className="filter-heading"><span>Custom rules</span></div>
    <p className="field-note">Build additional rules from already-computed descriptors. Required rules exclude a molecule on failure; informative rules are only recorded.</p>
    {props.plan.custom_rules.length ? <ul className="custom-rule-list">
      {props.plan.custom_rules.map((rule) => <li key={rule.rule_id} className="custom-rule-row">
        <span><strong>{rule.label}</strong><small>{describeCustomRule(rule)} · {rule.required ? "Required" : "Informative"}</small></span>
        <button type="button" className="link-action" onClick={() => props.onPlanChange({ custom_rules: props.plan.custom_rules.filter((item) => item.rule_id !== rule.rule_id) })}>Remove</button>
      </li>)}
    </ul> : null}
    <CustomRuleBuilder onAdd={(rule) => props.onPlanChange({ custom_rules: [...props.plan.custom_rules, rule] })} />
    <button type="button" disabled={Boolean(props.operation)} onClick={props.onPreview}>{props.preview ? "Recalculate filter preview" : "Preview filters"}</button>
    {summary ? <div className="filter-summary" aria-label="Filter summary">
      <span><strong>{summary.eligible_count}</strong> eligible</span><span><strong>{summary.excluded_count}</strong> excluded</span><span><strong>{summary.needs_decision_count}</strong> decisions</span><span><strong>{summary.pains_match_count + summary.brenk_match_count}</strong> alerts</span>
    </div> : <p className="filter-preview-stale">Filter settings changed. Recalculate before applying.</p>}
    {props.preview ? <>
      {props.missingMicrostateCount ? <p className="protonation-blocker" role="alert"><strong>{props.missingMicrostateCount} eligible parent compound{props.missingMicrostateCount === 1 ? "" : "s"} still need{props.missingMicrostateCount === 1 ? "s" : ""} an explicit microstate.</strong> Select each compound in the table and record one bounded candidate before applying this enumerated-state policy.</p> : null}
      <label className="check-row"><input type="checkbox" checked={props.confirmed} onChange={(event) => props.onConfirmedChange(event.target.checked)} /><span><strong>Apply this exact selection</strong><small>Create an immutable manifest containing every descriptor, rule result, alert, exclusion, and selected ligand ID.</small></span></label>
      <button type="button" className="apply-plan" disabled={!props.confirmed || Boolean(props.operation) || props.missingMicrostateCount > 0} onClick={props.onApply}>Apply filtered subset</button>
    </> : null}
    {props.run ? <div className="filter-run-note"><strong>Selection manifest applied</strong><small>{props.run.selected_ligand_ids.length} ligands · {props.run.worker_count} filter workers · RDKit {props.run.rdkit_version} · SHA-256 {props.run.artifact.sha256.slice(0, 12)}…</small></div> : null}
  </InspectorStage>;
}

const CUSTOM_RULE_DESCRIPTORS: { value: LigandCustomRuleDescriptor; label: string; unit: string }[] = [
  { value: "molecular_weight_g_mol", label: "Molecular weight", unit: "g/mol" },
  { value: "clogp", label: "cLogP", unit: "" },
  { value: "hydrogen_bond_donors", label: "H-bond donors", unit: "" },
  { value: "hydrogen_bond_acceptors", label: "H-bond acceptors", unit: "" },
  { value: "tpsa_angstrom2", label: "TPSA", unit: "Å²" },
  { value: "rotatable_bonds", label: "Rotatable bonds", unit: "" },
  { value: "molar_refractivity", label: "Molar refractivity", unit: "" },
  { value: "total_atom_count_with_hydrogens", label: "Total atoms (with H)", unit: "" },
  { value: "carbon_atom_count", label: "Carbon atoms", unit: "" },
  { value: "hetero_atom_count", label: "Heteroatoms", unit: "" },
  { value: "ring_count", label: "Ring count", unit: "" },
  { value: "qed", label: "QED", unit: "" },
];

const CUSTOM_RULE_OPERATORS: { value: LigandCustomRuleOperator; label: string }[] = [
  { value: "lt", label: "< less than" },
  { value: "lte", label: "≤ at most" },
  { value: "gt", label: "> greater than" },
  { value: "gte", label: "≥ at least" },
  { value: "eq", label: "= equal to" },
  { value: "between", label: "between" },
];

function describeCustomRule(rule: LigandCustomFilterRule): string {
  const descriptor = CUSTOM_RULE_DESCRIPTORS.find((item) => item.value === rule.descriptor);
  const name = descriptor?.label ?? rule.descriptor;
  const unit = descriptor?.unit ? ` ${descriptor.unit}` : "";
  if (rule.operator === "between") {
    return `${name} between ${rule.value}${unit} and ${rule.value_upper ?? rule.value}${unit}`;
  }
  const symbol = CUSTOM_RULE_OPERATORS.find((item) => item.value === rule.operator)?.label.slice(0, 1) ?? rule.operator;
  return `${name} ${symbol} ${rule.value}${unit}`;
}

function CustomRuleBuilder({ onAdd }: { onAdd: (rule: LigandCustomFilterRule) => void }) {
  const [descriptor, setDescriptor] = useState<LigandCustomRuleDescriptor>("molecular_weight_g_mol");
  const [operator, setOperator] = useState<LigandCustomRuleOperator>("lt");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("500");
  const [valueUpper, setValueUpper] = useState("600");
  const [required, setRequired] = useState(true);

  const parsedValue = Number(value);
  const parsedUpper = Number(valueUpper);
  const canAdd =
    Number.isFinite(parsedValue) &&
    (operator !== "between" || (Number.isFinite(parsedUpper) && parsedUpper >= parsedValue));

  function add() {
    if (!canAdd) return;
    const descriptorMeta = CUSTOM_RULE_DESCRIPTORS.find((item) => item.value === descriptor);
    onAdd({
      rule_id: `custom-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      label: label.trim() || descriptorMeta?.label || descriptor,
      descriptor,
      operator,
      value: parsedValue,
      value_upper: operator === "between" ? parsedUpper : null,
      required,
    });
    setLabel("");
  }

  return <div className="custom-rule-builder">
    <div className="custom-rule-fields">
      <label>
        <span className="field-label">Descriptor</span>
        <select aria-label="Custom rule descriptor" value={descriptor} onChange={(event) => setDescriptor(event.target.value as LigandCustomRuleDescriptor)}>
          {CUSTOM_RULE_DESCRIPTORS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label>
        <span className="field-label">Condition</span>
        <select aria-label="Custom rule condition" value={operator} onChange={(event) => setOperator(event.target.value as LigandCustomRuleOperator)}>
          {CUSTOM_RULE_OPERATORS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label>
        <span className="field-label">{operator === "between" ? "Lower bound" : "Value"}</span>
        <input aria-label="Custom rule value" type="number" value={value} onChange={(event) => setValue(event.target.value)} />
      </label>
      {operator === "between" ? <label>
        <span className="field-label">Upper bound</span>
        <input aria-label="Custom rule upper bound" type="number" value={valueUpper} onChange={(event) => setValueUpper(event.target.value)} />
      </label> : null}
    </div>
    <label>
      <span className="field-label">Label (optional)</span>
      <input aria-label="Custom rule label" type="text" placeholder={CUSTOM_RULE_DESCRIPTORS.find((item) => item.value === descriptor)?.label} value={label} onChange={(event) => setLabel(event.target.value)} />
    </label>
    <label className="filter-toggle"><input type="checkbox" checked={required} onChange={(event) => setRequired(event.target.checked)} /><span><strong>{required ? "Required" : "Informative"}</strong><small>{required ? "Excludes on failure" : "Recorded only"}</small></span></label>
    <button type="button" disabled={!canAdd} onClick={add}>Add rule</button>
  </div>;
}

function SourceSection(props: SourceSectionProps) {
  return <InspectorStage title="1 · Source" className="ligand-source-section" defaultOpen={!props.hasRecord} summary={props.hasRecord ? props.screening ? "Library loaded" : "Ligand selected" : "Required"}>
    {!props.screening ? <div className="source-tabs"><button type="button" className={props.sourceMode === "crystallographic" ? "selected" : ""} onClick={() => props.onModeChange("crystallographic")}>Crystallographic</button><button type="button" className={props.sourceMode === "local" ? "selected" : ""} onClick={() => props.onModeChange("local")}>Local file</button></div> : null}
    {!props.screening && props.sourceMode === "crystallographic" ? <><div className="selection-list compact-list">{props.candidates.map((candidate) => <button type="button" key={`${candidate.chain_id}-${candidate.name}-${candidate.sequence_number}`} className={props.selected === candidate ? "selected" : ""} onClick={() => props.onSelect(candidate)}><span className="heterogen-dot ligand" /><span><strong>{candidate.name} {candidate.chain_id}:{candidate.sequence_number}</strong><small>{candidate.atom_count} observed atoms</small></span></button>)}</div>{!props.candidates.length ? <p className="empty-list">No ligand-class component is available in this structure.</p> : null}<button type="button" className="apply-plan" disabled={!props.selected || Boolean(props.operation)} onClick={props.onExtract}>{props.hasRecord ? "Extract another immutable reference" : `Extract ${props.selected?.name ?? "selected ligand"}`}</button></> : <label className={`ligand-file-action ${props.operation ? "disabled" : ""}`}><strong>{props.screening ? "Open compound library" : "Open local ligand"}</strong><small>SDF, MOL, SMI, or SMILES · {props.screening ? "up to 10,000 records" : "single or multi-record input"} · max 100 MB</small><input type="file" accept=".sdf,.mol,.smi,.smiles,chemical/x-mdl-sdfile,chemical/x-daylight-smiles" disabled={Boolean(props.operation)} onChange={props.onImport} /></label>}
    {props.screening ? <LibraryShelf libraries={props.libraries} busy={Boolean(props.operation)} onOpen={props.onOpenLibrary} /> : null}
  </InspectorStage>;
}

function LigandSummary({ record, inspection, resolved }: { record: LigandRecord; inspection: LigandRecord["inspection"]; resolved: boolean }) {
  return <section className="ligand-summary">
    <strong>{inspection.name} · {inspection.formula}</strong>
    <small className="source-line">{resolved ? "Explicitly resolved chemical state" : record.artifact.source === "local" ? `Local ${record.artifact.format.toUpperCase()} preserved` : "Crystallographic reference preserved"}</small>
    <dl><div><dt>Molecular weight</dt><dd>{formatMetric(inspection.molecular_weight_g_mol, 3)} g/mol</dd></div><div><dt>Exact mass</dt><dd>{formatMetric(inspection.exact_mass_da, 4)} Da</dd></div><div><dt>Formal charge</dt><dd>{inspection.formal_charge}</dd></div><div><dt>Heavy atoms</dt><dd>{inspection.heavy_atom_count}</dd></div><div><dt>Fragments</dt><dd>{inspection.fragment_count}</dd></div><div><dt>Rotatable bonds</dt><dd>{inspection.rotatable_bond_count}</dd></div><div><dt>Stereocenters</dt><dd>{inspection.stereocenter_count}</dd></div><div><dt>Undefined stereo</dt><dd>{inspection.undefined_stereocenter_count}</dd></div><div><dt>Source geometry</dt><dd>{inspection.has_3d_coordinates ? "3D" : "No 3D"}</dd></div></dl>
    <small>Original SHA-256 · {record.artifact.sha256.slice(0, 16)}…</small>
  </section>;
}

function ConformerResult({ conformer }: { conformer: LigandConformerRecord }) {
  const pool = conformer.minimization.conformer_pool_size;
  const delta = conformer.minimization.final_energy_kcal_mol - conformer.minimization.initial_energy_kcal_mol;
  return <section className={`minimization-result ${conformer.minimization.converged ? "converged" : "warning"}`}>
    <strong>{conformer.minimization.converged ? "Conformer preparation converged" : "Iteration limit reached"}</strong>
    <dl>
      <div><dt>Origin</dt><dd>{conformer.minimization.embedding_method ? `${conformer.minimization.embedding_method} · seed ${conformer.minimization.random_seed}` : "Source geometry"}</dd></div>
      {pool ? <div><dt>Conformer pool</dt><dd>Best of {pool}</dd></div> : null}
      <div><dt>Method</dt><dd>{conformer.minimization.force_field}</dd></div>
      <div><dt>Energy change (QC)</dt><dd>{delta > 0 ? "+" : ""}{delta.toFixed(3)} kcal/mol</dd></div>
      <div><dt>Initial energy</dt><dd>{conformer.minimization.initial_energy_kcal_mol.toFixed(3)} kcal/mol</dd></div>
      <div><dt>Final energy</dt><dd>{conformer.minimization.final_energy_kcal_mol.toFixed(3)} kcal/mol</dd></div>
    </dl>
    <small>MMFF energies describe this prepared geometry only; do not compare them across compounds.</small>
    <small>Derivative SHA-256 · {conformer.artifact.sha256.slice(0, 16)}…</small>
  </section>;
}

function ErrorBanner({ error }: { error: Error }) {
  const apiError = error instanceof ApiError ? error : null;
  return <div className="structure-error receptor-error" role="alert"><strong>{error.message}</strong>{apiError?.code ? <span>{apiError.code}</span> : null}{apiError && Object.keys(apiError.details).length ? <details><summary>Technical evidence</summary><pre>{JSON.stringify(apiError.details, null, 2)}</pre></details> : null}</div>;
}

function viewerNotice(record: LigandRecord | null, hasResolvedState: boolean, conformer: LigandConformerRecord | null, mode: LigandViewMode): [string, string] {
  if (conformer && mode === "minimized") return [conformer.minimization.independent_from_source_coordinates ? "Independent minimized conformer" : "Minimized source geometry", "Explicit-hydrogen MMFF derivative. The imported/reference state remains unchanged."];
  if (conformer && mode === "overlay") return ["Comparison overlay", "Accepted state and prepared 3D conformer are both visible."];
  if (hasResolvedState) return ["Explicitly resolved state", "The selected chemical state is recorded in a new immutable SDF."];
  if (record?.artifact.source === "local") return ["Imported inspected state", record.inspection.has_3d_coordinates ? "The local original is preserved; this canonical SDF retains its supplied 3D coordinates." : "The local original is preserved. This connectivity preview has no authoritative 3D geometry."];
  return ["Crystallographic reference", "Observed coordinates and deposited mmCIF topology. This immutable state is never overwritten."];
}

function operationLabel(operation: Exclude<Operation, null>, forceField: LigandForceField): string {
  if (operation === "extracting") return "Extracting observed coordinates and mmCIF topology…";
  if (operation === "importing") return "Preserving and inspecting the local ligand…";
  if (operation === "resolving") return "Writing the explicitly selected chemical state…";
  if (operation === "bulk-resolving") return "Keeping the largest fragment for each selected ligand…";
  if (operation === "enumerating-microstates") return "Enumerating a bounded protonation and tautomer set…";
  if (operation === "selecting-microstate") return "Recording the explicitly selected screening microstate…";
  if (operation === "generating") return `Generating ETKDGv3 coordinates and minimizing with ${forceField}…`;
  if (operation === "preparing-pdbqt") return "Preparing the converged conformer with Meeko…";
  if (operation === "filtering") return "Evaluating descriptors, rules, alerts, and duplicates…";
  if (operation === "applying-filter") return "Recording the immutable filtered selection…";
  if (operation === "batch-preparing") return "Preparing ligand library…";
  return `Minimizing source coordinates with ${forceField}…`;
}

function asError(reason: unknown, fallback: string): Error {
  return reason instanceof Error ? reason : new Error(fallback);
}

function batchStatusFromPreparation(status: LigandPreparationStatus): LigandBatchResult["status"] {
  return status === "needs_decision" ? "needs-decision" : status;
}

function formatMetric(value: number | null, decimals: number): string {
  return value === null ? "Not recorded" : value.toFixed(decimals);
}

function clampNumber(value: string, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Number(value) || minimum));
}

function clampDecimal(value: string, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
}

function libraryWorkerCount(total: number): number {
  const logicalCores = navigator.hardwareConcurrency || 2;
  return Math.max(1, Math.min(total, logicalCores > 1 ? logicalCores - 1 : 1));
}

function filterRequest(
  plan: LigandLibraryFilterPlan,
  microstatePlan: LigandMicrostatePlan,
  states: Record<string, LigandChemicalStateRecord>,
  microstates: Record<string, LigandMicrostateRecord>,
) {
  return {
    plan,
    microstate_plan: microstatePlan,
    state_overrides: Object.fromEntries(
      [...Object.entries(states), ...Object.entries(microstates)]
        .map(([ligandId, state]) => [ligandId, state.artifact.state_id]),
    ),
  };
}
