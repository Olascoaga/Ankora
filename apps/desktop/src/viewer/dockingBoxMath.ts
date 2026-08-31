import type { BindingBox } from "../types/api";

export type AxisIndex = 0 | 1 | 2;
export type Vector3 = readonly [number, number, number];

export interface DockingRay {
  origin: Vector3;
  direction: Vector3;
}

interface DragBase {
  boxAtStart: BindingBox;
  startPointerY: number;
  worldUnitsPerCssPixel: number;
}

export interface ScreenMoveDrag extends DragBase {
  kind: "move-screen";
  grabPoint: Vector3;
  planeNormal: Vector3;
}

export interface AxisMoveDrag extends DragBase {
  kind: "move-axis";
  axis: AxisIndex;
  planePoint: Vector3;
  planeNormal: Vector3 | null;
  startAxisCoordinate: number;
}

export interface AxisResizeDrag extends DragBase {
  kind: "resize-axis";
  axis: AxisIndex;
  direction: 1 | -1;
  fixedAxisCoordinate: number;
  planePoint: Vector3;
  planeNormal: Vector3 | null;
  startAxisCoordinate: number;
}

export type DockingBoxDrag = ScreenMoveDrag | AxisMoveDrag | AxisResizeDrag;

export const MIN_BOX_SIZE_ANGSTROM = 0.1;
export const MAX_BOX_SIZE_ANGSTROM = 200;

const EPSILON = 1e-6;
const AXIS_VIEW_EPSILON = 1e-3;

export function beginScreenMove(
  box: BindingBox,
  startRay: DockingRay,
  viewDirection: Vector3,
  startPointerY: number,
  worldUnitsPerCssPixel: number,
): ScreenMoveDrag | null {
  const planeNormal = normalized(viewDirection);
  if (!planeNormal) return null;
  const planePoint = boxCenter(box);
  const grabPoint = rayPlaneIntersection(startRay, planePoint, planeNormal);
  if (!grabPoint) return null;
  return {
    kind: "move-screen",
    boxAtStart: box,
    grabPoint,
    planeNormal,
    startPointerY,
    worldUnitsPerCssPixel,
  };
}

export function beginAxisMove(
  box: BindingBox,
  axis: AxisIndex,
  startRay: DockingRay,
  viewDirection: Vector3,
  startPointerY: number,
  worldUnitsPerCssPixel: number,
): AxisMoveDrag {
  const planePoint = boxCenter(box);
  const planeNormal = axisConstraintPlaneNormal(axis, viewDirection);
  const intersection = planeNormal
    ? rayPlaneIntersection(startRay, planePoint, planeNormal)
    : null;
  return {
    kind: "move-axis",
    axis,
    boxAtStart: box,
    planePoint,
    planeNormal,
    startAxisCoordinate: intersection?.[axis] ?? planePoint[axis],
    startPointerY,
    worldUnitsPerCssPixel,
  };
}

export function beginAxisResize(
  box: BindingBox,
  axis: AxisIndex,
  direction: 1 | -1,
  startRay: DockingRay,
  viewDirection: Vector3,
  startPointerY: number,
  worldUnitsPerCssPixel: number,
): AxisResizeDrag {
  const center = boxCenter(box);
  const sizes = boxSizes(box);
  const planePoint: Vector3 = withAxis(center, axis, center[axis] + direction * sizes[axis] / 2);
  const planeNormal = axisConstraintPlaneNormal(axis, viewDirection);
  const intersection = planeNormal
    ? rayPlaneIntersection(startRay, planePoint, planeNormal)
    : null;
  return {
    kind: "resize-axis",
    axis,
    direction,
    boxAtStart: box,
    fixedAxisCoordinate: center[axis] - direction * sizes[axis] / 2,
    planePoint,
    planeNormal,
    startAxisCoordinate: intersection?.[axis] ?? planePoint[axis],
    startPointerY,
    worldUnitsPerCssPixel,
  };
}

export function computeDraggedBox(
  state: DockingBoxDrag,
  currentRay: DockingRay,
  currentPointerY: number,
): BindingBox | null {
  if (state.kind === "move-screen") {
    const current = rayPlaneIntersection(currentRay, state.grabPoint, state.planeNormal);
    if (!current) return null;
    const delta = subtract(current, state.grabPoint);
    return {
      ...state.boxAtStart,
      center_x: state.boxAtStart.center_x + delta[0],
      center_y: state.boxAtStart.center_y + delta[1],
      center_z: state.boxAtStart.center_z + delta[2],
    };
  }

  const axisDelta = constrainedAxisDelta(state, currentRay, currentPointerY);
  if (state.kind === "move-axis") {
    const centerKeys = ["center_x", "center_y", "center_z"] as const;
    return {
      ...state.boxAtStart,
      [centerKeys[state.axis]]: state.boxAtStart[centerKeys[state.axis]] + axisDelta,
    };
  }

  const draggedAxisCoordinate = state.startAxisCoordinate + axisDelta;
  const rawExtent = (draggedAxisCoordinate - state.fixedAxisCoordinate) * state.direction;
  const extent = clamp(rawExtent, MIN_BOX_SIZE_ANGSTROM, MAX_BOX_SIZE_ANGSTROM);
  const centerAxisCoordinate = state.fixedAxisCoordinate + state.direction * extent / 2;
  const sizeKeys = ["size_x", "size_y", "size_z"] as const;
  const centerKeys = ["center_x", "center_y", "center_z"] as const;
  return {
    ...state.boxAtStart,
    [sizeKeys[state.axis]]: extent,
    [centerKeys[state.axis]]: centerAxisCoordinate,
  };
}

export function axisConstraintPlaneNormal(
  axis: AxisIndex,
  viewDirection: Vector3,
): Vector3 | null {
  const projected: Vector3 = withAxis(viewDirection, axis, 0);
  if (length(projected) < AXIS_VIEW_EPSILON) return null;
  return normalized(projected);
}

function constrainedAxisDelta(
  state: AxisMoveDrag | AxisResizeDrag,
  currentRay: DockingRay,
  currentPointerY: number,
): number {
  if (state.planeNormal) {
    const intersection = rayPlaneIntersection(currentRay, state.planePoint, state.planeNormal);
    if (intersection) return intersection[state.axis] - state.startAxisCoordinate;
  }
  return -(currentPointerY - state.startPointerY) * state.worldUnitsPerCssPixel;
}

function rayPlaneIntersection(
  ray: DockingRay,
  planePoint: Vector3,
  planeNormal: Vector3,
): Vector3 | null {
  const denominator = dot(planeNormal, ray.direction);
  if (Math.abs(denominator) < EPSILON) return null;
  const distance = dot(planeNormal, subtract(planePoint, ray.origin)) / denominator;
  if (distance < 0) return null;
  return addScaled(ray.origin, ray.direction, distance);
}

function boxCenter(box: BindingBox): Vector3 {
  return [box.center_x, box.center_y, box.center_z];
}

function boxSizes(box: BindingBox): Vector3 {
  return [box.size_x, box.size_y, box.size_z];
}

function withAxis(vector: Vector3, axis: AxisIndex, value: number): Vector3 {
  const result: [number, number, number] = [vector[0], vector[1], vector[2]];
  result[axis] = value;
  return result;
}

function normalized(vector: Vector3): Vector3 | null {
  const magnitude = length(vector);
  if (magnitude < EPSILON) return null;
  return [vector[0] / magnitude, vector[1] / magnitude, vector[2] / magnitude];
}

function length(vector: Vector3): number {
  return Math.hypot(vector[0], vector[1], vector[2]);
}

function dot(left: Vector3, right: Vector3): number {
  return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

function subtract(left: Vector3, right: Vector3): Vector3 {
  return [left[0] - right[0], left[1] - right[1], left[2] - right[2]];
}

function addScaled(origin: Vector3, direction: Vector3, scale: number): Vector3 {
  return [
    origin[0] + direction[0] * scale,
    origin[1] + direction[1] * scale,
    origin[2] + direction[2] * scale,
  ];
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
