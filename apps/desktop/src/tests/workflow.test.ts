import { canNavigateTo, workflowSteps } from "../app/workflow";

it("unlocks Receptor only after a structure is available", () => {
  // Results and Export are reachable from an empty session on purpose: both
  // read what the project already holds and need no inputs, so a scientist
  // reopening Ankora can find last week's campaigns and the bundles made from
  // them without reloading a structure first.
  expect(workflowSteps.filter((step) => canNavigateTo(step))).toEqual([
    "Structure",
    "Results",
    "Export",
  ]);
  expect(workflowSteps.filter((step) => canNavigateTo(step, true))).toEqual([
    "Structure",
    "Receptor",
    "Results",
    "Export",
  ]);
  expect(workflowSteps.filter((step) => canNavigateTo(step, true, true))).toEqual([
    "Structure",
    "Receptor",
    "Ligand",
    "Binding site",
    "Results",
    "Export",
  ]);
  expect(workflowSteps.filter((step) => canNavigateTo(step, true, true, true))).toEqual([
    "Structure",
    "Receptor",
    "Ligand",
    "Binding site",
    "Docking",
    "Results",
    // Validation measures results already recorded rather than producing them,
    // so it opens with the search space those results would belong to - not
    // only after a docking run has happened in this session.
    "Validation",
    "Export",
  ]);
});
