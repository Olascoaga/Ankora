import type { BindingBox, HeterogenSummary, ResidueLocator, StructureFormat } from "../types/api";

export type ViewerSelection =
  | { kind: "chain"; chainId: string }
  | { kind: "heterogen"; heterogen: HeterogenSummary }
  | {
    kind: "residue";
    residue: {
      chainId: string;
      residueName: string;
      sequenceNumber: number;
      insertionCode: string;
    };
  };

export interface ViewerSource {
  id: string;
  url: string;
  format: StructureFormat | "sdf";
  label: string;
  /** Optional visual role; it changes presentation only, never molecular data. */
  appearance?: "default" | "interaction-context" | "interaction-ligand";
}

/** The five families the 2D legend uses, so both pictures agree. */
export type InteractionFamily =
  | "hydrogen"
  | "hydrophobic"
  | "aromatic"
  | "ionic"
  | "special";

/**
 * One contact, positioned by the detector rather than by the viewer.
 *
 * Both endpoints come from the analysis record, which took them from the very
 * atoms ProLIF matched. The viewer draws the line; it never decides where the
 * line goes.
 */
export interface ViewerContact {
  contactId: string;
  family: InteractionFamily;
  label: string;
  ligandPoint: [number, number, number];
  proteinPoint: [number, number, number];
}

export type DockingBoxInteractionMode = "move" | "resize";

export type ViewerResidueSelection = ResidueLocator;

export interface DockingBoxInteractionFeedback {
  action: "move-screen" | "move-axis" | "resize-axis";
  axis: "x" | "y" | "z" | null;
  direction: 1 | -1 | null;
  box: BindingBox;
}

export interface MolecularViewerAdapter {
  mount(container: HTMLElement): Promise<void>;
  loadStructures(sources: ViewerSource[]): Promise<void>;
  setTheme(theme: "light" | "dark" | "blue" | "amethyst" | "system"): void;
  select(selection: ViewerSelection | null): void;
  setDockingBox(box: BindingBox | null): Promise<void>;
  setInteractionContacts(
    contacts: ViewerContact[],
    selectedContactId: string | null,
  ): Promise<void>;
  /** Frame the exact detector-recorded ligand/protein contact endpoints. */
  focusInteractionRegion(contacts: ViewerContact[], animate?: boolean): void;
  /** A PNG data URI of the current view, at the requested pixel size. */
  captureImage(options: {
    width: number;
    height: number;
    transparent: boolean;
  }): Promise<string>;
  setDockingBoxInteractionMode(mode: DockingBoxInteractionMode): Promise<void>;
  setResidueSelectionMode(enabled: boolean): void;
  clearResidueSelection(): void;
  onDockingBoxChange(handler: ((box: BindingBox) => void) | null): void;
  onDockingBoxInteraction(handler: ((feedback: DockingBoxInteractionFeedback | null) => void) | null): void;
  onResidueSelectionChange(handler: ((residues: ViewerResidueSelection[]) => void) | null): void;
  onError(handler: ((message: string) => void) | null): void;
  clear(): Promise<void>;
  dispose(): void;
}
