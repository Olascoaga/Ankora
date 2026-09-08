import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

import type { BindingBox } from "../types/api";
import { formatScientificNumber } from "../utils/format";
import type {
  DockingBoxInteractionFeedback,
  DockingBoxInteractionMode,
  MolecularViewerAdapter,
  ViewerContact,
  ViewerResidueSelection,
  ViewerSelection,
  ViewerSource,
} from "./adapter";

/** What a workspace can ask of a mounted viewer, beyond setting props. */
export interface MolecularViewerHandle {
  captureImage(options: {
    width: number;
    height: number;
    transparent: boolean;
  }): Promise<string>;
  focusInteractionRegion(): void;
}

interface MolecularViewerProps {
  sources: ViewerSource[];
  selection: ViewerSelection | null;
  dockingBox?: BindingBox | null;
  dockingBoxInteractionMode?: DockingBoxInteractionMode;
  residueSelectionEnabled?: boolean;
  residueSelectionClearSignal?: number;
  /** Contacts as the detector positioned them; the viewer only draws them. */
  interactionContacts?: ViewerContact[];
  selectedContactId?: string | null;
  handleRef?: RefObject<MolecularViewerHandle | null>;
  onDockingBoxChange?: (box: BindingBox) => void;
  onResidueSelectionChange?: (residues: ViewerResidueSelection[]) => void;
}

export function MolecularViewer({
  sources,
  selection,
  dockingBox = null,
  dockingBoxInteractionMode = "move",
  residueSelectionEnabled = false,
  residueSelectionClearSignal = 0,
  interactionContacts,
  selectedContactId = null,
  handleRef,
  onDockingBoxChange,
  onResidueSelectionChange,
}: MolecularViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<MolecularViewerAdapter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [interaction, setInteraction] = useState<DockingBoxInteractionFeedback | null>(null);

  // Mol*'s own mount is async, so the adapter may not exist yet the first
  // time a prop-driven effect runs; this ref lets the handler registered
  // once mounting finishes always call through to the latest callback,
  // rather than needing to re-run (React setState setters like the ones
  // passed here are referentially stable, so an effect keyed on the
  // callback itself would otherwise never fire again after that first miss).
  const onDockingBoxChangeRef = useRef(onDockingBoxChange);
  const onResidueSelectionChangeRef = useRef(onResidueSelectionChange);
  const dockingBoxRef = useRef(dockingBox);
  const dockingBoxInteractionModeRef = useRef(dockingBoxInteractionMode);
  const residueSelectionEnabledRef = useRef(residueSelectionEnabled);
  const selectionRef = useRef(selection);
  const contactsRef = useRef(interactionContacts);
  const selectedContactIdRef = useRef(selectedContactId);
  useEffect(() => {
    onDockingBoxChangeRef.current = onDockingBoxChange;
  }, [onDockingBoxChange]);

  useEffect(() => {
    onResidueSelectionChangeRef.current = onResidueSelectionChange;
  }, [onResidueSelectionChange]);

  useEffect(() => {
    dockingBoxRef.current = dockingBox;
    void adapterRef.current?.setDockingBox(dockingBox)
      .catch((reason: unknown) => setError(viewerErrorMessage(reason)));
  }, [dockingBox]);

  useEffect(() => {
    dockingBoxInteractionModeRef.current = dockingBoxInteractionMode;
    void adapterRef.current?.setDockingBoxInteractionMode(dockingBoxInteractionMode)
      .catch((reason: unknown) => setError(viewerErrorMessage(reason)));
  }, [dockingBoxInteractionMode]);

  useEffect(() => {
    residueSelectionEnabledRef.current = residueSelectionEnabled;
    adapterRef.current?.setResidueSelectionMode(residueSelectionEnabled);
  }, [residueSelectionEnabled]);

  useEffect(() => {
    contactsRef.current = interactionContacts;
    selectedContactIdRef.current = selectedContactId;
    void adapterRef.current?.setInteractionContacts(interactionContacts ?? [], selectedContactId)
      .catch((reason: unknown) => setError(viewerErrorMessage(reason)));
  }, [interactionContacts, selectedContactId]);

  useEffect(() => {
    if (interactionContacts?.length) {
      adapterRef.current?.focusInteractionRegion(interactionContacts);
    }
  }, [interactionContacts]);

  useEffect(() => {
    if (!handleRef) return undefined;
    handleRef.current = {
      captureImage: async (options) => {
        const adapter = adapterRef.current;
        if (!adapter) throw new Error("The 3D view is not ready to be captured.");
        return adapter.captureImage(options);
      },
      focusInteractionRegion: () => {
        const adapter = adapterRef.current;
        const contacts = contactsRef.current ?? [];
        if (!adapter || !contacts.length) return;
        adapter.focusInteractionRegion(contacts, true);
      },
    };
    return () => { handleRef.current = null; };
  }, [handleRef]);

  useEffect(() => {
    if (residueSelectionClearSignal > 0) adapterRef.current?.clearResidueSelection();
  }, [residueSelectionClearSignal]);

  useEffect(() => {
    if (import.meta.env.MODE === "test" || !containerRef.current) return undefined;
    let active = true;

    const container = containerRef.current;
    void import("./molstarAdapter")
      .then(({ MolstarViewerAdapter }) => {
        const adapter = new MolstarViewerAdapter();
        if (!active) {
          adapter.dispose();
          return null;
        }
        adapterRef.current = adapter;
        return adapter.mount(container).then(() => adapter);
      })
      .then(async (adapter) => {
        if (!adapter) return;
        adapter.onDockingBoxChange((box) => onDockingBoxChangeRef.current?.(box));
        adapter.onDockingBoxInteraction((feedback) => {
          if (active) setInteraction(feedback);
        });
        adapter.onResidueSelectionChange((residues) => {
          if (active) onResidueSelectionChangeRef.current?.(residues);
        });
        adapter.onError((message) => {
          if (active) setError(message);
        });
        await adapter.setDockingBoxInteractionMode(dockingBoxInteractionModeRef.current);
        await adapter.loadStructures(sources);
        adapter.setResidueSelectionMode(residueSelectionEnabledRef.current);
        await adapter.setDockingBox(dockingBoxRef.current);
        await adapter.setInteractionContacts(
          contactsRef.current ?? [], selectedContactIdRef.current,
        );
        if (contactsRef.current?.length) {
          adapter.focusInteractionRegion(contactsRef.current);
        }
        adapter.select(selectionRef.current);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Mol* could not display the structure");
      });

    return () => {
      active = false;
      adapterRef.current?.dispose();
      adapterRef.current = null;
    };
  }, [sources]);

  useEffect(() => {
    selectionRef.current = selection;
    adapterRef.current?.select(selection);
  }, [selection]);

  useEffect(() => {
    const adapter = adapterRef.current;
    if (!adapter) return;

    function applyTheme() {
      const currentTheme = document.documentElement.dataset.theme as "light" | "dark" | "blue" | "amethyst" | "system" | undefined;
      if (currentTheme) adapter?.setTheme(currentTheme);
    }
    
    // Apply initially
    applyTheme();

    // Listen for theme changes on the html element
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.attributeName === "data-theme") applyTheme();
      }
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    return () => observer.disconnect();
  }, []);

  return (
    <div className="viewer-live" data-testid="molecular-viewer">
      <div ref={containerRef} className="molstar-host" />
      {interaction ? <div className="docking-box-readout" role="status" aria-live="polite">{formatInteraction(interaction)}</div> : null}
      {error ? <div className="viewer-error">{error}</div> : null}
    </div>
  );
}

function formatInteraction(feedback: DockingBoxInteractionFeedback): string {
  if (feedback.action === "move-screen") {
    return `Move in view plane · center (${formatScientificNumber(feedback.box.center_x, 2)}, ${formatScientificNumber(feedback.box.center_y, 2)}, ${formatScientificNumber(feedback.box.center_z, 2)}) Å`;
  }
  const axis = feedback.axis?.toUpperCase() ?? "";
  if (feedback.action === "move-axis") {
    const center = feedback.axis === "x"
      ? feedback.box.center_x
      : feedback.axis === "y"
        ? feedback.box.center_y
        : feedback.box.center_z;
    return `Move ${axis} · center ${axis} ${formatScientificNumber(center, 2)} Å`;
  }
  const size = feedback.axis === "x"
    ? feedback.box.size_x
    : feedback.axis === "y"
      ? feedback.box.size_y
      : feedback.box.size_z;
  return `Resize ${axis}${feedback.direction === 1 ? "+" : "−"} · size ${axis} ${formatScientificNumber(size, 2)} Å`;
}

function viewerErrorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Mol* could not update the docking-box editor.";
}
