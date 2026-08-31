export const workflowSteps = [
  "Structure",
  "Receptor",
  "Ligand",
  "Binding site",
  "Docking",
  "Results",
  "Validation",
  "Export",
] as const;

export type WorkflowStep = (typeof workflowSteps)[number];

export function canNavigateTo(
  step: WorkflowStep,
  hasStructure = false,
  hasReceptor = false,
  hasBindingSite = false,
): boolean {
  return step === "Structure"
    || (step === "Receptor" && hasStructure)
    || (step === "Ligand" && hasStructure && hasReceptor)
    || (step === "Binding site" && hasStructure && hasReceptor)
    || (step === "Docking" && hasStructure && hasReceptor && hasBindingSite)
    // Results reads what the project already holds and needs no inputs at all,
    // so it opens the way Structure does. A scientist reopening Ankora has to
    // be able to find last week's campaigns without reloading a structure to
    // unlock the screen that lists them.
    || step === "Results"
    // Export lists what the project has already sent out. Like Results it
    // reads records rather than producing them, so it opens without inputs -
    // and unlike before, it opens at all.
    || step === "Export"
    // Validation measures results already recorded, so it stays reachable
    // once there is a search space those results could belong to.
    || (step === "Validation" && hasStructure && hasReceptor && hasBindingSite);
}
