import { classifyWorkbenchLayout } from "../app/workbenchLayout";

describe("workbench layout contract", () => {
  it.each([
    [960, 680, "small"],
    [1280, 800, "medium"],
    [1920, 1080, "medium"],
    [2560, 1440, "wide"],
  ] as const)("classifies a %ix%i CSS viewport as %s", (width, height, expected) => {
    expect(classifyWorkbenchLayout({ width, height })).toBe(expected);
  });

  it.each([
    [1920, 1080, 1.25, "medium"],
    [1920, 1080, 1.5, "medium"],
    [2560, 1440, 1.25, "wide"],
    [2560, 1440, 1.5, "medium"],
  ] as const)(
    "classifies %ix%i at %sx Windows scaling from effective CSS pixels",
    (physicalWidth, physicalHeight, scale, expected) => {
      expect(classifyWorkbenchLayout({
        width: physicalWidth / scale,
        height: physicalHeight / scale,
      })).toBe(expected);
    },
  );

  it("requires both dimensions before entering a larger composition", () => {
    expect(classifyWorkbenchLayout({ width: 1799, height: 1440 })).toBe("medium");
    expect(classifyWorkbenchLayout({ width: 2560, height: 1099 })).toBe("medium");
    expect(classifyWorkbenchLayout({ width: 1920, height: 699 })).toBe("small");
  });
});
