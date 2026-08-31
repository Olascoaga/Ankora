import type { ViewerContact } from "./adapter";

export interface InteractionFocusSphere {
  center: [number, number, number];
  radius: number;
}

const MINIMUM_INTERACTION_RADIUS_ANGSTROM = 5.5;

/**
 * Bound the exact contact endpoints recorded by the interaction detector.
 *
 * The minimum radius leaves enough room for the rest of the ligand and the
 * contacted side chains without inventing any additional scientific contact.
 */
export function interactionFocusSphere(
  contacts: ViewerContact[],
): InteractionFocusSphere | null {
  if (!contacts.length) return null;

  const points = contacts.flatMap((contact) => [
    contact.ligandPoint,
    contact.proteinPoint,
  ]);
  const minimum = [...points[0]] as [number, number, number];
  const maximum = [...points[0]] as [number, number, number];
  for (const point of points.slice(1)) {
    for (let axis = 0; axis < 3; axis += 1) {
      minimum[axis] = Math.min(minimum[axis], point[axis]);
      maximum[axis] = Math.max(maximum[axis], point[axis]);
    }
  }

  const center: [number, number, number] = [
    (minimum[0] + maximum[0]) / 2,
    (minimum[1] + maximum[1]) / 2,
    (minimum[2] + maximum[2]) / 2,
  ];
  const radius = Math.max(
    MINIMUM_INTERACTION_RADIUS_ANGSTROM,
    ...points.map((point) => Math.hypot(
      point[0] - center[0],
      point[1] - center[1],
      point[2] - center[2],
    )),
  );
  return { center, radius };
}
