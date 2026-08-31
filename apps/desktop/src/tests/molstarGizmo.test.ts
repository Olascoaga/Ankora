import { Vec3 } from "molstar/lib/mol-math/linear-algebra";
import { describe, expect, it } from "vitest";

import { buildDockingBoxGizmo } from "../viewer/molstarAdapter";

describe("Mol* docking-box gizmo geometry", () => {
  it.each(["move", "resize"] as const)("builds visible %s geometry", (mode) => {
    const mesh = buildDockingBoxGizmo(
      Vec3.create(35.4, -3, -0.8),
      Vec3.create(21.6, 19.9, 19.3),
      mode,
    );

    expect(mesh.vertexCount).toBeGreaterThan(0);
    expect(mesh.triangleCount).toBeGreaterThan(0);
  });

  it("reuses the active mesh so drag updates reach the existing render object", () => {
    const mesh = buildDockingBoxGizmo(
      Vec3.create(35.4, -3, -0.8),
      Vec3.create(21.6, 19.9, 19.3),
      "move",
    );
    const initialVertices = Array.from(mesh.vertexBuffer.ref.value.slice(0, 24));

    const updated = buildDockingBoxGizmo(
      Vec3.create(46.4, -3, -0.8),
      Vec3.create(21.6, 19.9, 19.3),
      "move",
      mesh,
    );

    expect(updated).toBe(mesh);
    expect(Array.from(updated.vertexBuffer.ref.value.slice(0, 24))).not.toEqual(initialVertices);
    expect(updated.boundingSphere.center[0]).toBeCloseTo(46.4);
  });
});
