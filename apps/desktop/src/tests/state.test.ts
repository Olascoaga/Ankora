import { createInitialApplicationState } from "../app/state";

it("starts in an explicit checking state without invented scientific data", () => {
  expect(createInitialApplicationState()).toEqual({
    connection: "checking",
    health: null,
    system: null,
    tools: null,
    error: null,
    structure: null,
    structureOperation: "idle",
    structureError: null,
  });
});
