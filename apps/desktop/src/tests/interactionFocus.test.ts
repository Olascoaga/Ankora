import { describe, expect, it } from "vitest";

import type { ViewerContact } from "../viewer/adapter";
import { interactionFocusSphere } from "../viewer/interactionFocus";

function contact(
  contactId: string,
  ligandPoint: [number, number, number],
  proteinPoint: [number, number, number],
): ViewerContact {
  return {
    contactId,
    family: "hydrogen",
    label: contactId,
    ligandPoint,
    proteinPoint,
  };
}

describe("interaction-site camera framing", () => {
  it("bounds every detector-recorded endpoint around the pocket", () => {
    const focus = interactionFocusSphere([
      contact("one", [30, -4, -2], [38, 2, 4]),
      contact("two", [34, -2, 1], [42, 6, 7]),
    ]);

    expect(focus?.center).toEqual([36, 1, 2.5]);
    expect(focus?.radius).toBeCloseTo(Math.hypot(6, 5, 4.5));
  });

  it("keeps a useful local field around a single short contact", () => {
    expect(interactionFocusSphere([
      contact("short", [1, 2, 3], [2, 2, 3]),
    ])?.radius).toBe(5.5);
  });

  it("does not invent a focus region without recorded geometry", () => {
    expect(interactionFocusSphere([])).toBeNull();
  });
});
