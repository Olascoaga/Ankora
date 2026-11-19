import { useEffect, useMemo, useState } from "react";

import { ankoraApi } from "../../api/client";
import type {
  DiagnosticStatus,
  IfpBit,
  InteractionAnalysisRecord,
  InteractionContact,
  InteractionRuleClause,
  InteractionRuleEvaluationRecord,
  InteractionRuleKind,
  InteractionRuleSetRecord,
  InteractionTarget,
} from "../../types/api";
import { formatApplicationDateTime, formatScientificNumber } from "../../utils/format";

interface InteractionRulesSectionProps {
  catalogId: string;
  ligandId: string;
  poseArtifactId: string;
  receptorId: string;
  currentAnalysis: InteractionAnalysisRecord | null;
  onFocusContact?: (contact: InteractionContact) => void;
}

const STATUS_LABEL: Record<DiagnosticStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  not_applicable: "Not applicable",
  not_evaluable: "Not evaluable",
};

const KIND_LABEL: Record<InteractionRuleKind, string> = {
  required: "REQUIRED (AND)",
  alternative_or: "ALTERNATIVE_OR",
  forbidden: "FORBIDDEN (NOT)",
};

const PROLIF_TYPES = [
  "HBDonor",
  "HBAcceptor",
  "Hydrophobic",
  "FaceToFace",
  "EdgeToFace",
  "CationPi",
  "PiCation",
  "Anionic",
  "Cationic",
  "XBAcceptor",
  "XBDonor",
  "MetalAcceptor",
  "MetalDonor",
] as const;

interface DraftClause {
  id: string;
  label: string;
  kind: InteractionRuleKind;
  chainId: string;
  residueName: string;
  sequenceNumber: string;
  interactionType: string;
  secondChainId: string;
  secondResidueName: string;
  secondSequenceNumber: string;
  secondInteractionType: string;
  maxDistance: string;
  minSatisfied: string;
}

function emptyDraftClause(index: number): DraftClause {
  return {
    id: `clause-${index}`,
    label: "",
    kind: "required",
    chainId: "A",
    residueName: "",
    sequenceNumber: "",
    interactionType: "HBDonor",
    secondChainId: "A",
    secondResidueName: "",
    secondSequenceNumber: "",
    secondInteractionType: "Hydrophobic",
    maxDistance: "",
    minSatisfied: "1",
  };
}

function formatBit(bit: IfpBit): string {
  const icode = bit.residue.insertion_code ? bit.residue.insertion_code : "";
  return `${bit.residue.residue_name} ${bit.residue.chain_id}:${bit.residue.sequence_number}${icode} · ${bit.interaction_type}`;
}

/**
 * Declarative ProLIF pharmacophoric rules & Tanimoto IFP evaluation (M4).
 *
 * Strictly opt-in and read-only on docking outputs (`mutated_original_pose:
 * false`): rule sets are validated against the prepared receptor's protonated
 * PDB and sealed by `rule_set_identity_sha256` before Protocol Confirmation.
 * Every pose evaluation runs directly on the coupled FlexRes complex (`E8`).
 */
export function InteractionRulesSection({
  catalogId,
  ligandId,
  poseArtifactId,
  receptorId,
  currentAnalysis,
  onFocusContact,
}: InteractionRulesSectionProps) {
  const [ruleSets, setRuleSets] = useState<InteractionRuleSetRecord[]>([]);
  const [selectedRuleSetId, setSelectedRuleSetId] = useState<string>("");
  const [evaluations, setEvaluations] = useState<InteractionRuleEvaluationRecord[]>([]);
  const [selectedEvaluationId, setSelectedEvaluationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [creating, setCreating] = useState(false);
  const [builderOpen, setBuilderOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Builder state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [draftClauses, setDraftClauses] = useState<DraftClause[]>([emptyDraftClause(1)]);
  const [useCurrentPoseAsReference, setUseCurrentPoseAsReference] = useState(false);
  const [minTanimoto, setMinTanimoto] = useState("");

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    setEvaluations([]);
    setSelectedEvaluationId(null);
    void Promise.all([
      ankoraApi.listInteractionRuleSets(receptorId),
      ankoraApi.listPoseInteractionRuleEvaluations(catalogId, ligandId, poseArtifactId),
    ])
      .then(([loadedRuleSets, loadedEvaluations]) => {
        if (disposed) return;
        setRuleSets(loadedRuleSets);
        setSelectedRuleSetId((current) =>
          loadedRuleSets.some((item) => item.rule_set_id === current)
            ? current
            : (loadedRuleSets[0]?.rule_set_id ?? ""),
        );
        setEvaluations((current) => (loadedEvaluations.length ? loadedEvaluations : current));
        setSelectedEvaluationId(
          (current) => current ?? loadedEvaluations[0]?.evaluation_id ?? null,
        );
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Pharmacophore rule sets or evaluations could not be read.",
          );
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [catalogId, ligandId, poseArtifactId, receptorId]);

  const activeEvaluation =
    evaluations.find((item) => item.evaluation_id === selectedEvaluationId) ??
    evaluations[0] ??
    null;

  const selectedRuleSet =
    ruleSets.find((item) => item.rule_set_id === selectedRuleSetId) ?? null;

  const uniqueDetectedSuggestions = useMemo(() => {
    const seen = new Set<string>();
    const items: InteractionContact[] = [];
    for (const contact of currentAnalysis?.contacts ?? []) {
      const key = `${contact.residue.chain_id}:${contact.residue.residue_name}:${contact.residue.sequence_number}:${contact.detector_type}`;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push(contact);
    }
    return items.slice(0, 8);
  }, [currentAnalysis]);

  function updateDraft(index: number, patch: Partial<DraftClause>) {
    setDraftClauses((current) =>
      current.map((item, idx) => (idx === index ? { ...item, ...patch } : item)),
    );
  }

  function addDraftFromContact(contact: InteractionContact, kind: InteractionRuleKind) {
    setBuilderOpen(true);
    setDraftClauses((current) => {
      const next: DraftClause = {
        id: `clause-${current.length + 1}`,
        label: `${contact.residue.residue_name} ${contact.residue.chain_id}:${contact.residue.sequence_number} ${contact.detector_type}`,
        kind,
        chainId: contact.residue.chain_id,
        residueName: contact.residue.residue_name,
        sequenceNumber: String(contact.residue.sequence_number),
        interactionType: contact.detector_type,
        secondChainId: contact.residue.chain_id,
        secondResidueName: "",
        secondSequenceNumber: "",
        secondInteractionType: "Hydrophobic",
        maxDistance: "",
        minSatisfied: "1",
      };
      if (
        current.length === 1 &&
        !current[0].residueName.trim() &&
        !current[0].sequenceNumber.trim()
      ) {
        return [{ ...next, id: "clause-1" }];
      }
      return [...current, next];
    });
  }

  async function createRuleSet() {
    setError(null);
    if (!name.trim()) {
      setError("A rule set name is required.");
      return;
    }

    const builtClauses: InteractionRuleClause[] = [];
    for (let idx = 0; idx < draftClauses.length; idx += 1) {
      const item = draftClauses[idx];
      const hasFirst = Boolean(item.residueName.trim() || item.sequenceNumber.trim());
      if (!hasFirst) {
        if (useCurrentPoseAsReference && draftClauses.length === 1) {
          continue;
        }
        setError(`Clause ${idx + 1} requires a residue name and sequence number.`);
        return;
      }
      const seq1 = Number(item.sequenceNumber);
      if (!Number.isInteger(seq1)) {
        setError(`Clause ${idx + 1} sequence number must be a whole number.`);
        return;
      }
      const maxDist = item.maxDistance.trim() ? Number(item.maxDistance) : null;
      if (maxDist !== null && (!Number.isFinite(maxDist) || maxDist <= 0 || maxDist > 20)) {
        setError(`Clause ${idx + 1} max distance must be between 0 and 20 Å.`);
        return;
      }

      const targets: InteractionTarget[] = [
        {
          residue: {
            chain_id: item.chainId.trim() || "A",
            residue_name: item.residueName.trim().toUpperCase(),
            sequence_number: seq1,
            insertion_code: "",
          },
          interaction_types: [item.interactionType],
          ...(maxDist !== null ? { max_distance_angstrom: maxDist } : {}),
        },
      ];

      let minSatisfied: number | null = null;
      if (item.kind === "alternative_or") {
        const seq2 = Number(item.secondSequenceNumber);
        if (!item.secondResidueName.trim() || !Number.isInteger(seq2)) {
          setError(
            `ALTERNATIVE_OR clause ${idx + 1} requires a second residue name and sequence number.`,
          );
          return;
        }
        targets.push({
          residue: {
            chain_id: item.secondChainId.trim() || "A",
            residue_name: item.secondResidueName.trim().toUpperCase(),
            sequence_number: seq2,
            insertion_code: "",
          },
          interaction_types: [item.secondInteractionType],
          ...(maxDist !== null ? { max_distance_angstrom: maxDist } : {}),
        });
        const parsedMin = Number(item.minSatisfied || "1");
        if (!Number.isInteger(parsedMin) || parsedMin < 1 || parsedMin > targets.length) {
          setError(`Clause ${idx + 1} min_satisfied must be between 1 and ${targets.length}.`);
          return;
        }
        minSatisfied = parsedMin;
      }

      const clauseLabel =
        item.label.trim() ||
        `${item.residueName.trim().toUpperCase()} ${item.chainId.trim() || "A"}:${seq1} ${item.interactionType}`;
      builtClauses.push({
        clause_id: item.id,
        label: clauseLabel,
        kind: item.kind,
        targets,
        ...(minSatisfied !== null ? { min_satisfied: minSatisfied } : {}),
      });
    }

    const parsedTanimoto = minTanimoto.trim() ? Number(minTanimoto) : null;
    if (parsedTanimoto !== null) {
      if (!useCurrentPoseAsReference) {
        setError("Enable 'Use current pose as Tanimoto IFP reference' to set a Tanimoto threshold.");
        return;
      }
      if (!Number.isFinite(parsedTanimoto) || parsedTanimoto < 0 || parsedTanimoto > 1) {
        setError("Min Tanimoto similarity must be between 0 and 1.");
        return;
      }
    }
    if (builtClauses.length === 0 && !useCurrentPoseAsReference) {
      setError("Add at least one clause or enable the current pose as Tanimoto IFP reference.");
      return;
    }

    setCreating(true);
    try {
      const created = await ankoraApi.createInteractionRuleSet({
        name: name.trim(),
        description: description.trim(),
        receptor_id: receptorId,
        clauses: builtClauses,
        ...(useCurrentPoseAsReference
          ? {
              reference_pose: {
                catalog_id: catalogId,
                ligand_id: ligandId,
                pose_artifact_id: poseArtifactId,
              },
            }
          : {}),
        ...(parsedTanimoto !== null ? { min_tanimoto_similarity: parsedTanimoto } : {}),
      });
      setRuleSets((current) => [
        created,
        ...current.filter((item) => item.rule_set_id !== created.rule_set_id),
      ]);
      setSelectedRuleSetId(created.rule_set_id);
      setBuilderOpen(false);
      setName("");
      setDescription("");
      setDraftClauses([emptyDraftClause(1)]);
      setUseCurrentPoseAsReference(false);
      setMinTanimoto("");
    } catch (reason: unknown) {
      setError(
        reason instanceof Error ? reason.message : "The interaction rule set could not be created.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function evaluateSelectedRuleSet() {
    if (!selectedRuleSetId) return;
    setError(null);
    setEvaluating(true);
    try {
      const matchingAnalysisId =
        currentAnalysis &&
        selectedRuleSet &&
        currentAnalysis.profile.profile_id === selectedRuleSet.profile.profile_id &&
        currentAnalysis.profile.vicinity_cutoff_angstrom ===
          selectedRuleSet.profile.vicinity_cutoff_angstrom
          ? currentAnalysis.analysis_id
          : undefined;
      const created = await ankoraApi.evaluatePoseInteractionRules(
        catalogId,
        ligandId,
        poseArtifactId,
        {
          rule_set_id: selectedRuleSetId,
          ...(matchingAnalysisId ? { analysis_id: matchingAnalysisId } : {}),
        },
      );
      setEvaluations((current) => [
        created,
        ...current.filter((item) => item.evaluation_id !== created.evaluation_id),
      ]);
      setSelectedEvaluationId(created.evaluation_id);
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The pharmacophoric rule evaluation could not be completed.",
      );
    } finally {
      setEvaluating(false);
    }
  }

  function focusContactById(contactId: string) {
    if (!onFocusContact) return;
    const fromAnalysis = currentAnalysis?.contacts.find((c) => c.contact_id === contactId);
    const fromEval = activeEvaluation?.contacts.find((c) => c.contact_id === contactId);
    const target = fromAnalysis ?? fromEval;
    if (target) {
      onFocusContact(target);
    }
  }

  return (
    <section
      className="interaction-rules-panel"
      aria-label="Declarative pharmacophoric interaction rules (ProLIF PIC)"
    >
      <div className="interaction-rules-header">
        <div>
          <strong>Pharmacophoric rules &amp; Tanimoto IFP (M4 · ProLIF PIC)</strong>
          <p className="field-note">
            Define immutable <code>REQUIRED</code>, <code>ALTERNATIVE_OR</code>, and{" "}
            <code>FORBIDDEN</code> residue-contact rules validated against the prepared
            receptor&apos;s protonated PDB and evaluated directly on the coupled{" "}
            <code>PoseComplex</code> (<code>ADR-032 E8</code>). Poses failing rules remain
            in the campaign denominator and docking scores are never altered.
          </p>
        </div>
        <button
          type="button"
          className="quiet-button"
          aria-expanded={builderOpen}
          onClick={() => setBuilderOpen((open) => !open)}
        >
          {builderOpen ? "Close rule builder" : "New sealed rule set"}
        </button>
      </div>

      {error ? (
        <div className="structure-error" role="alert">
          {error}
        </div>
      ) : null}

      {uniqueDetectedSuggestions.length > 0 ? (
        <div className="interaction-rules-suggestions">
          <span className="field-note">Quick-add from detected contacts:</span>
          <div className="interaction-rules-chip-row">
            {uniqueDetectedSuggestions.map((item) => (
              <button
                key={item.contact_id}
                type="button"
                className="quiet-button interaction-rules-chip"
                onClick={() => addDraftFromContact(item, "required")}
              >
                + Required: {item.residue.residue_name} {item.residue.chain_id}:
                {item.residue.sequence_number} · {item.detector_type}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {builderOpen ? (
        <div
          className="interaction-rules-builder"
          role="region"
          aria-label="Create sealed interaction rule set"
        >
          <div className="interaction-rules-builder-meta">
            <label>
              Rule set name
              <input
                type="text"
                placeholder="e.g. Hinge H-bond + gatekeeper check"
                value={name}
                disabled={creating}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              Scientific hypothesis note (optional)
              <input
                type="text"
                placeholder="Sealed before Protocol Confirmation"
                value={description}
                disabled={creating}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
          </div>

          <div className="interaction-rules-clauses">
            {draftClauses.map((clause, index) => (
              <div key={clause.id} className="interaction-rules-clause-editor">
                <div className="interaction-rules-clause-row">
                  <label>
                    Operator
                    <select
                      aria-label={`Clause ${index + 1} operator`}
                      value={clause.kind}
                      disabled={creating}
                      onChange={(event) =>
                        updateDraft(index, {
                          kind: event.target.value as InteractionRuleKind,
                        })
                      }
                    >
                      <option value="required">REQUIRED (AND)</option>
                      <option value="alternative_or">ALTERNATIVE_OR (k-of-n)</option>
                      <option value="forbidden">FORBIDDEN (NOT)</option>
                    </select>
                  </label>
                  <label>
                    Label
                    <input
                      type="text"
                      aria-label={`Clause ${index + 1} label`}
                      placeholder="Hinge H-bond"
                      value={clause.label}
                      disabled={creating}
                      onChange={(event) => updateDraft(index, { label: event.target.value })}
                    />
                  </label>
                  <label>
                    Chain
                    <input
                      type="text"
                      aria-label={`Clause ${index + 1} chain`}
                      value={clause.chainId}
                      disabled={creating}
                      onChange={(event) => updateDraft(index, { chainId: event.target.value })}
                    />
                  </label>
                  <label>
                    Residue
                    <input
                      type="text"
                      aria-label={`Clause ${index + 1} residue`}
                      placeholder="SER"
                      value={clause.residueName}
                      disabled={creating}
                      onChange={(event) =>
                        updateDraft(index, { residueName: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Seq #
                    <input
                      type="number"
                      aria-label={`Clause ${index + 1} sequence number`}
                      placeholder="5"
                      value={clause.sequenceNumber}
                      disabled={creating}
                      onChange={(event) =>
                        updateDraft(index, { sequenceNumber: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    ProLIF type
                    <select
                      aria-label={`Clause ${index + 1} interaction type`}
                      value={clause.interactionType}
                      disabled={creating}
                      onChange={(event) =>
                        updateDraft(index, { interactionType: event.target.value })
                      }
                    >
                      {PROLIF_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Max Å (opt.)
                    <input
                      type="number"
                      step="0.1"
                      aria-label={`Clause ${index + 1} max distance`}
                      placeholder="3.5"
                      value={clause.maxDistance}
                      disabled={creating}
                      onChange={(event) =>
                        updateDraft(index, { maxDistance: event.target.value })
                      }
                    />
                  </label>
                </div>

                {clause.kind === "alternative_or" ? (
                  <div className="interaction-rules-clause-row">
                    <label>
                      Alt. chain
                      <input
                        type="text"
                        aria-label={`Clause ${index + 1} alternative chain`}
                        value={clause.secondChainId}
                        disabled={creating}
                        onChange={(event) =>
                          updateDraft(index, { secondChainId: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      Alt. residue
                      <input
                        type="text"
                        aria-label={`Clause ${index + 1} alternative residue`}
                        placeholder="TYR"
                        value={clause.secondResidueName}
                        disabled={creating}
                        onChange={(event) =>
                          updateDraft(index, { secondResidueName: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      Alt. seq #
                      <input
                        type="number"
                        aria-label={`Clause ${index + 1} alternative sequence number`}
                        placeholder="12"
                        value={clause.secondSequenceNumber}
                        disabled={creating}
                        onChange={(event) =>
                          updateDraft(index, { secondSequenceNumber: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      Alt. ProLIF type
                      <select
                        aria-label={`Clause ${index + 1} alternative interaction type`}
                        value={clause.secondInteractionType}
                        disabled={creating}
                        onChange={(event) =>
                          updateDraft(index, { secondInteractionType: event.target.value })
                        }
                      >
                        {PROLIF_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Min satisfied
                      <input
                        type="number"
                        min="1"
                        max="2"
                        aria-label={`Clause ${index + 1} min satisfied`}
                        value={clause.minSatisfied}
                        disabled={creating}
                        onChange={(event) =>
                          updateDraft(index, { minSatisfied: event.target.value })
                        }
                      />
                    </label>
                  </div>
                ) : null}

                {draftClauses.length > 1 ? (
                  <button
                    type="button"
                    className="quiet-button"
                    disabled={creating}
                    onClick={() =>
                      setDraftClauses((current) => current.filter((_, idx) => idx !== index))
                    }
                  >
                    Remove clause
                  </button>
                ) : null}
              </div>
            ))}
          </div>

          <div className="interaction-rules-builder-actions">
            <button
              type="button"
              className="quiet-button"
              disabled={creating}
              onClick={() =>
                setDraftClauses((current) => [...current, emptyDraftClause(current.length + 1)])
              }
            >
              Add clause
            </button>
            <label className="pose-quality-checkbox">
              <input
                type="checkbox"
                checked={useCurrentPoseAsReference}
                disabled={creating}
                onChange={(event) => setUseCurrentPoseAsReference(event.target.checked)}
              />
              <span>Use current pose as Tanimoto IFP reference</span>
            </label>
            {useCurrentPoseAsReference ? (
              <label>
                Min Tanimoto (0–1, optional)
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  aria-label="Min Tanimoto similarity"
                  placeholder="0.50"
                  value={minTanimoto}
                  disabled={creating}
                  onChange={(event) => setMinTanimoto(event.target.value)}
                />
              </label>
            ) : null}
            <button
              type="button"
              className="primary-button"
              disabled={creating}
              onClick={() => void createRuleSet()}
            >
              {creating ? "Sealing rule set…" : "Create sealed rule set"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="interaction-rules-eval-bar">
        <label>
          Sealed rule set
          <select
            aria-label="Sealed interaction rule set"
            value={selectedRuleSetId}
            disabled={loading || evaluating || ruleSets.length === 0}
            onChange={(event) => setSelectedRuleSetId(event.target.value)}
          >
            {ruleSets.length === 0 ? (
              <option value="">No rule sets sealed for this receptor yet</option>
            ) : (
              ruleSets.map((item) => (
                <option key={item.rule_set_id} value={item.rule_set_id}>
                  {item.name} · {item.clauses.length} clause(s) · SHA{" "}
                  {item.rule_set_identity_sha256.slice(0, 10)}…
                </option>
              ))
            )}
          </select>
        </label>
        <button
          type="button"
          className="primary-button"
          disabled={evaluating || !selectedRuleSetId}
          onClick={() => void evaluateSelectedRuleSet()}
        >
          {evaluating ? "Evaluating ProLIF rules…" : "Evaluate pose against rule set"}
        </button>
        {evaluations.length > 1 ? (
          <label>
            Recorded evaluation
            <select
              value={activeEvaluation?.evaluation_id ?? ""}
              onChange={(event) => setSelectedEvaluationId(event.target.value)}
            >
              {evaluations.map((item) => (
                <option key={item.evaluation_id} value={item.evaluation_id}>
                  {formatApplicationDateTime(item.created_at)} · {item.rule_set_name} (
                  {STATUS_LABEL[item.overall_status]})
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      {loading ? <p className="field-note">Reading pharmacophoric rule sets…</p> : null}

      {activeEvaluation ? (
        <div
          className="interaction-rules-result"
          role="region"
          aria-label="Pharmacophoric rule evaluation results"
        >
          <div className="pose-quality-summary">
            <span className={`pose-quality-pill status-${activeEvaluation.overall_status}`}>
              Overall: {STATUS_LABEL[activeEvaluation.overall_status]}
            </span>
            <span className="pose-quality-counts">
              {activeEvaluation.passed_clause_count} passed ·{" "}
              {activeEvaluation.failed_clause_count} failed
            </span>
            <span className="pose-quality-tool">
              {activeEvaluation.detector.name} {activeEvaluation.detector.version} · Rule SHA{" "}
              <code>{activeEvaluation.rule_set_identity_sha256.slice(0, 12)}…</code> ·{" "}
              <code>mutated_original_pose: {String(activeEvaluation.mutated_original_pose)}</code>
            </span>
          </div>

          {activeEvaluation.materialized_coupled_receptor_sha256 ? (
            <div className="pose-quality-coupled-note" role="status">
              <strong>Evaluated on coupled FlexRes complex (E8):</strong> receptor PDB{" "}
              <code>{activeEvaluation.materialized_coupled_receptor_sha256.slice(0, 12)}…</code>{" "}
              (includes moved side chains for this exact pose).
            </div>
          ) : null}

          {activeEvaluation.warnings.length > 0 ? (
            <div className="pose-quality-warnings" role="alert">
              <strong>Warnings ({activeEvaluation.warnings.length})</strong>
              <ul>
                {activeEvaluation.warnings.map((warning, idx) => (
                  <li key={`${warning.code}-${idx}`}>
                    <code>{warning.code}</code>: {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {activeEvaluation.tanimoto ? (
            <div
              className="pose-quality-strain-card"
              role="region"
              aria-label="Tanimoto IFP similarity"
            >
              <strong>
                Reference Tanimoto IFP similarity{" "}
                <span className={`pose-quality-pill status-${activeEvaluation.tanimoto.status}`}>
                  {STATUS_LABEL[activeEvaluation.tanimoto.status]}
                </span>
              </strong>
              <dl className="pose-quality-strain-grid">
                <div>
                  <dt>Tanimoto |A ∩ B| / |A ∪ B|</dt>
                  <dd>
                    {activeEvaluation.tanimoto.similarity !== null &&
                    activeEvaluation.tanimoto.similarity !== undefined
                      ? formatScientificNumber(activeEvaluation.tanimoto.similarity, 3)
                      : "Not evaluable (0 / 0 empty union)"}
                  </dd>
                </div>
                <div>
                  <dt>Shared / Union bits</dt>
                  <dd>
                    {activeEvaluation.tanimoto.intersection_count} /{" "}
                    {activeEvaluation.tanimoto.union_count}
                  </dd>
                </div>
                {activeEvaluation.tanimoto.min_threshold !== null &&
                activeEvaluation.tanimoto.min_threshold !== undefined ? (
                  <div>
                    <dt>Sealed min threshold</dt>
                    <dd>{formatScientificNumber(activeEvaluation.tanimoto.min_threshold, 2)}</dd>
                  </div>
                ) : null}
                <div>
                  <dt>Reference IFP SHA-256</dt>
                  <dd>
                    <code>
                      {activeEvaluation.tanimoto.reference_fingerprint_sha256.slice(0, 12)}…
                    </code>
                  </dd>
                </div>
              </dl>
              {activeEvaluation.tanimoto.shared_bits.length > 0 ? (
                <p className="field-note">
                  <strong>Shared:</strong>{" "}
                  {activeEvaluation.tanimoto.shared_bits.map(formatBit).join("; ")}
                </p>
              ) : null}
              {activeEvaluation.tanimoto.reference_only_bits.length > 0 ? (
                <p className="field-note">
                  <strong>Missing from pose:</strong>{" "}
                  {activeEvaluation.tanimoto.reference_only_bits.map(formatBit).join("; ")}
                </p>
              ) : null}
              {activeEvaluation.tanimoto.pose_only_bits.length > 0 ? (
                <p className="field-note">
                  <strong>Pose-only contacts:</strong>{" "}
                  {activeEvaluation.tanimoto.pose_only_bits.map(formatBit).join("; ")}
                </p>
              ) : null}
            </div>
          ) : null}

          {activeEvaluation.clause_results.length > 0 ? (
            <div className="pose-quality-table-scroll">
              <table aria-label="Pharmacophoric clause evaluation">
                <thead>
                  <tr>
                    <th>Clause</th>
                    <th>Operator</th>
                    <th>Status</th>
                    <th>Explanation</th>
                    <th>2D / 3D contacts</th>
                  </tr>
                </thead>
                <tbody>
                  {activeEvaluation.clause_results.map((clause) => (
                    <tr key={clause.clause_id}>
                      <td>
                        <strong>{clause.label}</strong>
                        <div>
                          <code>{clause.clause_id}</code>
                        </div>
                      </td>
                      <td>{KIND_LABEL[clause.kind]}</td>
                      <td>
                        <span className={`pose-quality-pill status-${clause.status}`}>
                          {STATUS_LABEL[clause.status]}
                        </span>
                      </td>
                      <td>{clause.explanation}</td>
                      <td>
                        {clause.matched_contact_ids.length > 0 ? (
                          <div className="interaction-rules-chip-row">
                            {clause.matched_contact_ids.map((cid) => (
                              <button
                                key={cid}
                                type="button"
                                className="quiet-button interaction-rules-chip"
                                onClick={() => focusContactById(cid)}
                              >
                                Focus {cid}
                              </button>
                            ))}
                          </div>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
