import { describe, expect, it } from "vitest";

import type { BindingBox } from "../types/api";
import {
  axisConstraintPlaneNormal,
  beginAxisMove,
  beginAxisResize,
  beginScreenMove,
  computeDraggedBox,
  type DockingRay,
} from "../viewer/dockingBoxMath";

const box: BindingBox = {
  center_x: 0,
  center_y: 0,
  center_z: 0,
  size_x: 20,
  size_y: 10,
  size_z: 8,
};

describe("docking-box drag math", () => {
  it("moves the complete box in the camera-facing plane without changing its size", () => {
    const startRay = ray([0, 0, 20], [0, 0, -1]);
    const drag = beginScreenMove(box, startRay, [0, 0, 1], 100, 0.1);
    expect(drag).not.toBeNull();

    const moved = computeDraggedBox(
      drag!,
      ray([0, 0, 20], [2, -3, -20]),
      100,
    );

    expect(moved).toMatchObject({
      center_x: 2,
      center_y: -3,
      center_z: 0,
      size_x: 20,
      size_y: 10,
      size_z: 8,
    });
  });

  it("constrains translation to the selected world axis", () => {
    const startRay = ray([0, 0, 20], [14, 0, -20]);
    const drag = beginAxisMove(box, 0, startRay, [0, 0, 1], 50, 0.1);
    const moved = computeDraggedBox(drag, ray([0, 0, 20], [18, 7, -20]), 50);

    expect(moved?.center_x).toBeCloseTo(4);
    expect(moved?.center_y).toBe(0);
    expect(moved?.center_z).toBe(0);
  });

  it("moves one face while keeping the opposite face fixed", () => {
    const startRay = ray([0, 0, 20], [10, 0, -20]);
    const drag = beginAxisResize(box, 0, 1, startRay, [0, 0, 1], 50, 0.1);
    const resized = computeDraggedBox(drag, ray([0, 0, 20], [14, 0, -20]), 50);

    expect(resized?.size_x).toBeCloseTo(24);
    expect(resized?.center_x).toBeCloseTo(2);
    expect((resized!.center_x - resized!.size_x / 2)).toBeCloseTo(-10);
  });

  it("uses a stable vertical-screen fallback when an axis points at the camera", () => {
    expect(axisConstraintPlaneNormal(2, [0, 0, 1])).toBeNull();
    const drag = beginAxisMove(
      box,
      2,
      ray([0, 0, 20], [10, 0, -20]),
      [0, 0, 1],
      100,
      0.25,
    );
    const moved = computeDraggedBox(drag, ray([0, 0, 20], [0, 0, -1]), 92);

    expect(moved?.center_z).toBeCloseTo(2);
    expect(moved?.center_x).toBe(0);
    expect(moved?.center_y).toBe(0);
  });

  it("clamps a face before it crosses the fixed opposite face", () => {
    const drag = beginAxisResize(
      box,
      0,
      1,
      ray([0, 0, 20], [0, 0, -1]),
      [0, 0, 1],
      0,
      1,
    );
    const resized = computeDraggedBox(drag, ray([0, 0, 20], [-50, 0, -20]), 0);

    expect(resized?.size_x).toBeCloseTo(0.1);
    expect(resized?.center_x).toBeCloseTo(-9.95);
  });
});

function ray(origin: [number, number, number], toward: [number, number, number]): DockingRay {
  const magnitude = Math.hypot(toward[0], toward[1], toward[2]);
  return {
    origin,
    direction: [toward[0] / magnitude, toward[1] / magnitude, toward[2] / magnitude],
  };
}
