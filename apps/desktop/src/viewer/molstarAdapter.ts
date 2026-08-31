import { Viewer } from "molstar/lib/apps/viewer/app";
import { OrderedSet } from "molstar/lib/mol-data/int";
import { Mesh } from "molstar/lib/mol-geo/geometry/mesh/mesh";
import { MeshBuilder } from "molstar/lib/mol-geo/geometry/mesh/mesh-builder";
import { addCylinder } from "molstar/lib/mol-geo/geometry/mesh/builder/cylinder";
import { addSphere } from "molstar/lib/mol-geo/geometry/mesh/builder/sphere";
import { BoxCage } from "molstar/lib/mol-geo/primitive/box";
import { Box3D, Sphere3D } from "molstar/lib/mol-math/geometry";
import { Ray3D } from "molstar/lib/mol-math/geometry/primitives/ray3d";
import { Mat4, Vec3 } from "molstar/lib/mol-math/linear-algebra";
import { Shape, ShapeGroup } from "molstar/lib/mol-model/shape";
import { StructureElement, StructureProperties, Unit } from "molstar/lib/mol-model/structure";
import { PluginStateObject as SO, PluginStateTransform } from "molstar/lib/mol-plugin-state/objects";
import { StateTransforms } from "molstar/lib/mol-plugin-state/transforms";
import type { Representation } from "molstar/lib/mol-repr/representation";
import { StateTransformer, type StateObjectSelector } from "molstar/lib/mol-state";
import { Task } from "molstar/lib/mol-task";
import { Color } from "molstar/lib/mol-util/color";
import { ColorNames } from "molstar/lib/mol-util/color/names";
import { ParamDefinition as PD } from "molstar/lib/mol-util/param-definition";

import { FAMILY_COLOR } from "../features/results/interactionFamilies";
import type { BindingBox } from "../types/api";
import type {
  DockingBoxInteractionFeedback,
  DockingBoxInteractionMode,
  InteractionFamily,
  MolecularViewerAdapter,
  ViewerContact,
  ViewerSelection,
  ViewerResidueSelection,
  ViewerSource,
} from "./adapter";
import {
  beginAxisMove,
  beginAxisResize,
  beginScreenMove,
  computeDraggedBox,
  type AxisIndex,
  type DockingBoxDrag,
  type DockingRay,
  type Vector3,
} from "./dockingBoxMath";
import { interactionFocusSphere } from "./interactionFocus";

const HandleGroup = {
  frame: 0,
  first: 1,
  second: 2,
  third: 3,
  fourth: 4,
  fifth: 5,
  sixth: 6,
} as const;

type BoxHit =
  | { kind: "move-screen" }
  | { kind: "move-axis"; axis: AxisIndex }
  | { kind: "resize-axis"; axis: AxisIndex; direction: 1 | -1 };

interface PendingRender {
  box: BindingBox | null;
  mode: DockingBoxInteractionMode;
}

const DockingBoxGizmoParams = {
  center: PD.Vec3(Vec3()),
  size: PD.Vec3(Vec3.create(20, 20, 20)),
  mode: PD.Select<DockingBoxInteractionMode>("move", [
    ["move", "Move"],
    ["resize", "Resize"],
  ]),
};

const DockingBoxGizmo3D = PluginStateTransform.BuiltIn({
  name: "ankora-docking-box-gizmo-3d",
  display: "Ankora docking-box editor",
  from: SO.Root,
  to: SO.Shape.Provider,
  params: DockingBoxGizmoParams,
})({
  canAutoUpdate() {
    return true;
  },
  apply({ params }) {
    return Task.create("Ankora docking-box editor", async () => new SO.Shape.Provider({
      label: "Docking search space",
      data: params,
      params: Mesh.Params,
      getShape: (_, data, __, previousShape) => {
        const mesh = buildDockingBoxGizmo(
          data.center,
          data.size,
          data.mode,
          previousShape?.geometry,
        );
        return Shape.create(
          "Ankora docking-box editor",
          data,
          mesh,
          (groupId) => handleColor(groupId, data.mode),
          () => 1,
          (groupId) => handleLabel(groupId, data.mode),
        );
      },
      geometryUtils: Mesh.Utils,
    }, { label: "Docking search space" }));
  },
  update({ b, newParams }) {
    // Keep the provider stable and its state-tree parameters synchronized.
    // _commitGizmo refreshes the existing child representation explicitly.
    b.data.data = newParams;
    return StateTransformer.UpdateResult.Updated;
  },
});

// Read from the diagram's own palette rather than restated here: a contact
// that is amber in one picture and blue in the other is two different claims
// about one measurement.
const CONTACT_COLOR = Object.fromEntries(
  Object.entries(FAMILY_COLOR).map(([family, hex]) => [family, parseInt(hex.slice(1), 16)]),
) as Record<InteractionFamily, number>;

// A dashed line reads as a contact rather than a bond, which is what these are.
const DASH_LENGTH = 0.42;
const DASH_GAP = 0.34;
const CONTACT_RADIUS = 0.055;
const SELECTED_RADIUS = 0.13;
const ANCHOR_RADIUS = 0.16;

const InteractionContactsParams = {
  contacts: PD.Value<ViewerContact[]>([], { isHidden: true }),
  selected: PD.Value<string | null>(null, { isHidden: true }),
};

const InteractionContacts3D = PluginStateTransform.BuiltIn({
  name: "ankora-pose-interaction-contacts-3d",
  display: "Ankora pose interactions",
  from: SO.Root,
  to: SO.Shape.Provider,
  params: InteractionContactsParams,
})({
  canAutoUpdate() {
    return true;
  },
  apply({ params }) {
    return Task.create("Ankora pose interactions", async () => new SO.Shape.Provider({
      label: "Pose interactions",
      data: params,
      params: Mesh.Params,
      getShape: (_, data, __, previousShape) => {
        const contacts: ViewerContact[] = data.contacts;
        return Shape.create(
          "Ankora pose interactions",
          data,
          buildContactMesh(contacts, data.selected, previousShape?.geometry),
          (groupId) => Color(CONTACT_COLOR[contacts[groupId]?.family ?? "special"]),
          () => 1,
          (groupId) => contacts[groupId]?.label ?? "Interaction",
        );
      },
      geometryUtils: Mesh.Utils,
    }, { label: "Pose interactions" }));
  },
  update({ b, newParams }) {
    b.data.data = newParams;
    return StateTransformer.UpdateResult.Updated;
  },
});

function buildContactMesh(
  contacts: ViewerContact[],
  selectedContactId: string | null,
  previous?: Mesh,
): Mesh {
  const builder = MeshBuilder.createState(1024, 512, previous);
  contacts.forEach((contact, index) => {
    builder.currentGroup = index;
    const start = Vec3.create(...contact.ligandPoint);
    const end = Vec3.create(...contact.proteinPoint);
    const selected = contact.contactId === selectedContactId;
    const radius = selected ? SELECTED_RADIUS : CONTACT_RADIUS;
    const span = Vec3.distance(start, end);
    if (span < 1e-3) return;

    // Drawn as discrete dashes rather than one cylinder with a dash texture,
    // so the gap pattern survives every zoom level the scientist uses.
    const direction = Vec3.sub(Vec3(), end, start);
    Vec3.scale(direction, direction, 1 / span);
    const stride = DASH_LENGTH + DASH_GAP;
    for (let offset = 0; offset < span; offset += stride) {
      const from = Vec3.scaleAndAdd(Vec3(), start, direction, offset);
      const to = Vec3.scaleAndAdd(
        Vec3(), start, direction, Math.min(offset + DASH_LENGTH, span),
      );
      addCylinder(builder, from, to, 1, {
        radiusTop: radius,
        radiusBottom: radius,
        topCap: true,
        bottomCap: true,
        radialSegments: 8,
      });
    }
    // Anchors, so it is visible which atoms the contact was measured between.
    addSphere(builder, start, selected ? ANCHOR_RADIUS : ANCHOR_RADIUS * 0.7, 1);
    addSphere(builder, end, selected ? ANCHOR_RADIUS : ANCHOR_RADIUS * 0.7, 1);
  });
  return MeshBuilder.getMesh(builder);
}

export class MolstarViewerAdapter implements MolecularViewerAdapter {
  private viewer: Viewer | null = null;
  private gizmoShapeRef: StateObjectSelector<SO.Shape.Provider> | null = null;
  private contactsShapeRef: StateObjectSelector<SO.Shape.Provider> | null = null;
  private contactsRepresentationRef: StateObjectSelector<SO.Shape.Representation3D> | null = null;
  private gizmoRepresentationRef: StateObjectSelector<SO.Shape.Representation3D> | null = null;
  private currentBox: BindingBox | null = null;
  private interactionMode: DockingBoxInteractionMode = "move";
  private boxChangeHandler: ((box: BindingBox) => void) | null = null;
  private interactionHandler: ((feedback: DockingBoxInteractionFeedback | null) => void) | null = null;
  private residueSelectionHandler: ((residues: ViewerResidueSelection[]) => void) | null = null;
  private residueSelectionEnabled = false;
  private errorHandler: ((message: string) => void) | null = null;
  private dragState: DockingBoxDrag | null = null;
  private activeHit: BoxHit | null = null;
  private pendingRender: PendingRender | null = null;
  private renderDrain: Promise<void> | null = null;
  private detachInteraction: (() => void) | null = null;
  private currentSources: ViewerSource[] = [];

  async mount(container: HTMLElement): Promise<void> {
    const currentTheme = document.documentElement.dataset.theme as "light" | "dark" | "blue" | "amethyst" | "system" | undefined;
    const isLight = currentTheme === "light" || (currentTheme === "system" && !window.matchMedia("(prefers-color-scheme: dark)").matches);
    const isBlue = currentTheme === "blue";
    const isAmethyst = currentTheme === "amethyst";
    const bgColor = isLight ? "#ffffff" : isBlue ? "#090e1a" : isAmethyst ? "#0a0910" : "#090f14";

    this.viewer = await Viewer.create(container, {
      layoutIsExpanded: false,
      layoutShowControls: false,
      layoutShowSequence: false,
      layoutShowLog: false,
      layoutShowLeftPanel: false,
      viewportShowExpand: false,
      viewportShowSelectionMode: true,
      viewportShowAnimation: true,
      viewportBackgroundColor: bgColor,
      illumination: true,
    });
    this._setupBoxInteraction(container);
  }

  async loadStructures(sources: ViewerSource[]): Promise<void> {
    if (!this.viewer) throw new Error("Mol* viewer has not been mounted");
    await this._awaitRenderDrain();
    await this.viewer.plugin.clear();
    this.gizmoShapeRef = null;
    this.gizmoRepresentationRef = null;
    this.currentSources = sources;

    const currentTheme = document.documentElement.dataset.theme as "light" | "dark" | "blue" | "amethyst" | "system" | undefined;
    const isLight = currentTheme === "light" || (currentTheme === "system" && !window.matchMedia("(prefers-color-scheme: dark)").matches);
    const isBlue = currentTheme === "blue";
    const isAmethyst = currentTheme === "amethyst";
    const accentColor = Color(isLight ? 0x14b8a6 : isBlue ? 0x3b82f6 : isAmethyst ? 0xc084fc : 0x60d6a6);

    for (const source of sources) {
      await this.viewer.loadStructureFromUrl(
        source.url,
        source.format,
        false,
        { label: source.label },
      );
    }
    
    this._applyStructureThemes(accentColor);

    if (this.currentBox) await this._requestRender(this.currentBox, this.interactionMode);
  }

  setTheme(theme: "light" | "dark" | "blue" | "amethyst" | "system"): void {
    if (!this.viewer?.plugin.canvas3d) return;
    const isLight = theme === "light" || (theme === "system" && !window.matchMedia("(prefers-color-scheme: dark)").matches);
    const isBlue = theme === "blue";
    const isAmethyst = theme === "amethyst";
    const bgColor = Color(isLight ? 0xffffff : isBlue ? 0x090e1a : isAmethyst ? 0x0a0910 : 0x090f14);
    // For light theme, #00796b can look too dark in 3D with shadows. #14b8a6 (a lighter teal) looks better.
    const accentColor = Color(isLight ? 0x14b8a6 : isBlue ? 0x3b82f6 : isAmethyst ? 0xc084fc : 0x60d6a6);

    this.viewer.plugin.canvas3d.setProps({ renderer: { backgroundColor: bgColor } });

    this._applyStructureThemes(accentColor);
  }

  select(selection: ViewerSelection | null): void {
    if (!this.viewer) return;
    if (!selection) {
      this.viewer.structureInteractivity({ action: ["select", "highlight"] });
      return;
    }
    if (selection.kind === "chain") {
      this.viewer.structureInteractivity({ elements: { auth_asym_id: selection.chainId }, action: ["select", "focus"] });
      return;
    }
    if (selection.kind === "residue") {
      this.viewer.structureInteractivity({
        elements: {
          auth_asym_id: selection.residue.chainId,
          auth_comp_id: selection.residue.residueName,
          auth_seq_id: selection.residue.sequenceNumber,
          ...(selection.residue.insertionCode ? { pdbx_PDB_ins_code: selection.residue.insertionCode } : {}),
        },
        action: ["select", "focus"],
      });
      return;
    }
    const residue = selection.heterogen;
    this.viewer.structureInteractivity({
      elements: {
        auth_asym_id: residue.chain_id,
        auth_comp_id: residue.name,
        ...(residue.sequence_number === null ? {} : { auth_seq_id: residue.sequence_number }),
        ...(residue.insertion_code ? { pdbx_PDB_ins_code: residue.insertion_code } : {}),
      },
      action: ["select", "focus"],
    });
  }

  async setDockingBox(box: BindingBox | null): Promise<void> {
    if (this.dragState) return;
    this.currentBox = box;
    await this._requestRender(box, this.interactionMode);
  }

  async setInteractionContacts(
    contacts: ViewerContact[],
    selectedContactId: string | null,
  ): Promise<void> {
    const plugin = this.viewer?.plugin;
    if (!plugin) return;
    if (contacts.length === 0) {
      if (this.contactsShapeRef) {
        await plugin.build().delete(this.contactsShapeRef).commit();
      }
      this.contactsShapeRef = null;
      this.contactsRepresentationRef = null;
      return;
    }
    const params = { contacts, selected: selectedContactId };
    if (this.contactsShapeRef) {
      await plugin.build().to(this.contactsShapeRef).update(params).commit();
      const representation = this.contactsRepresentationRef?.data?.repr;
      // ShapeRepresentation keeps the original GPU-facing ValueCells, so this
      // rebuilds into the existing Mesh instead of replacing it.
      if (representation) {
        await representation.createOrUpdate(representation.props, params).run();
      }
      return;
    }
    const shape = await plugin.build().toRoot().apply(InteractionContacts3D, params).commit();
    this.contactsRepresentationRef = await plugin.build().to(shape)
      .apply(StateTransforms.Representation.ShapeRepresentation3D)
      .commit();
    this.contactsShapeRef = shape;
  }

  focusInteractionRegion(contacts: ViewerContact[], animate = false): void {
    const focus = interactionFocusSphere(contacts);
    const manager = this.viewer?.plugin.managers.camera;
    if (!focus || !manager) return;
    manager.focusSphere(
      Sphere3D.create(Vec3.create(...focus.center), focus.radius),
      { extraRadius: 2.5, minRadius: 5.5, durationMs: animate ? 250 : 0 },
    );
  }

  async captureImage(options: {
    width: number;
    height: number;
    transparent: boolean;
  }): Promise<string> {
    const helper = this.viewer?.plugin.helpers.viewportScreenshot;
    if (!helper) throw new Error("The 3D view is not ready to be captured.");
    // Mol* renders on animation frames, and a hidden document gets none:
    // measured at zero frames per 1.5 s with the window out of view. The
    // capture would simply never resolve, so it says why instead of hanging.
    if (document.hidden) {
      throw new Error(
        "The 3D view only renders while its window is visible. Bring the window "
        + "to the front and save again.",
      );
    }
    const previous = helper.values;
    helper.behaviors.values.next({
      ...previous,
      resolution: {
        name: "custom",
        params: { width: options.width, height: options.height },
      },
      format: { name: "png", params: {} },
      transparent: options.transparent,
    });
    try {
      // A backstop for anything else that stops the render loop mid-capture.
      return await Promise.race([
        helper.getImageDataUri(),
        new Promise<string>((_, reject) => setTimeout(
          () => reject(new Error("The 3D view did not finish rendering this image.")),
          120_000,
        )),
      ]);
    } finally {
      helper.behaviors.values.next(previous);
    }
  }

  async setDockingBoxInteractionMode(mode: DockingBoxInteractionMode): Promise<void> {
    if (this.dragState || mode === this.interactionMode) return;
    await this._awaitRenderDrain();
    if (this.gizmoShapeRef && this.viewer) {
      await this.viewer.plugin.build().delete(this.gizmoShapeRef).commit();
      this.gizmoShapeRef = null;
      this.gizmoRepresentationRef = null;
    }
    this.interactionMode = mode;
    await this._requestRender(this.currentBox, mode);
  }

  setResidueSelectionMode(enabled: boolean): void {
    const plugin = this.viewer?.plugin;
    if (!plugin || enabled === this.residueSelectionEnabled) return;
    this.residueSelectionEnabled = enabled;
    plugin.selectionMode = enabled;
    if (enabled) {
      plugin.managers.interactivity.setProps({ granularity: "residue" });
      this._emitSelectedResidues();
    } else {
      plugin.managers.interactivity.lociSelects.deselectAll();
    }
  }

  clearResidueSelection(): void {
    this.viewer?.plugin.managers.interactivity.lociSelects.deselectAll();
  }

  onDockingBoxChange(handler: ((box: BindingBox) => void) | null): void {
    this.boxChangeHandler = handler;
  }

  onDockingBoxInteraction(
    handler: ((feedback: DockingBoxInteractionFeedback | null) => void) | null,
  ): void {
    this.interactionHandler = handler;
  }

  onResidueSelectionChange(
    handler: ((residues: ViewerResidueSelection[]) => void) | null,
  ): void {
    this.residueSelectionHandler = handler;
    if (handler) this._emitSelectedResidues();
  }

  onError(handler: ((message: string) => void) | null): void {
    this.errorHandler = handler;
  }

  private _requestRender(
    box: BindingBox | null,
    mode: DockingBoxInteractionMode,
  ): Promise<void> {
    this.pendingRender = { box: box ? { ...box } : null, mode };
    if (!this.renderDrain) {
      const drain = this._drainRenderQueue();
      this.renderDrain = drain;
      void drain
        .catch((reason: unknown) => this._reportError(reason))
        .finally(() => {
          if (this.renderDrain === drain) this.renderDrain = null;
          if (this.pendingRender) void this._requestRender(
            this.pendingRender.box,
            this.pendingRender.mode,
          );
        });
    }
    return this.renderDrain;
  }

  private async _drainRenderQueue(): Promise<void> {
    while (this.pendingRender) {
      const next = this.pendingRender;
      this.pendingRender = null;
      await this._commitGizmo(next.box, next.mode);
    }
  }

  private async _awaitRenderDrain(): Promise<void> {
    if (this.renderDrain) await this.renderDrain;
  }

  private async _commitGizmo(
    box: BindingBox | null,
    mode: DockingBoxInteractionMode,
  ): Promise<void> {
    if (!this.viewer) return;
    const plugin = this.viewer.plugin;
    if (!box) {
      if (this.gizmoShapeRef) await plugin.build().delete(this.gizmoShapeRef).commit();
      this.gizmoShapeRef = null;
      this.gizmoRepresentationRef = null;
      return;
    }

    const params = {
      center: Vec3.create(box.center_x, box.center_y, box.center_z),
      size: Vec3.create(box.size_x, box.size_y, box.size_z),
      mode,
    };
    if (this.gizmoShapeRef) {
      await plugin.build().to(this.gizmoShapeRef).update(params).commit();
      const representation = this.gizmoRepresentationRef?.data?.repr;
      if (representation) {
        // ShapeRepresentation keeps the original GPU-facing ValueCells, so
        // getShape rebuilds into its prior Mesh instead of replacing it.
        await representation.createOrUpdate(representation.props, params).run();
      }
      return;
    }

    const shape = await plugin.build().toRoot().apply(DockingBoxGizmo3D, params).commit();
    const representation = await plugin.build().to(shape)
      .apply(StateTransforms.Representation.ShapeRepresentation3D)
      .commit();
    this.gizmoShapeRef = shape;
    this.gizmoRepresentationRef = representation;
  }

  private _setupBoxInteraction(container: HTMLElement): void {
    let activeRect: DOMRect | null = null;
    let activePointerId: number | null = null;

    const onPointerDown = (event: PointerEvent) => {
      const canvas3d = this.viewer?.plugin.canvas3d;
      const canvas = container.querySelector("canvas");
      if (!canvas3d || !canvas || !this.currentBox || !this.boxChangeHandler) return;
      const rect = canvas.getBoundingClientRect();
      const ray = screenPointToRay(canvas3d, rect, event.clientX, event.clientY);
      const hit = this._pickedHandle(ray);
      if (!hit) return;
      const drag = this._beginDrag(hit, ray, event.clientY);
      if (!drag) return;

      event.preventDefault();
      event.stopPropagation();
      activeRect = rect;
      activePointerId = event.pointerId;
      this.dragState = drag;
      this.activeHit = hit;
      container.style.cursor = "grabbing";
      if (typeof container.setPointerCapture === "function") {
        try {
          container.setPointerCapture(event.pointerId);
        } catch {
          // Window-level listeners still preserve the drag outside the canvas.
        }
      }
    };

    const onPointerMove = (event: PointerEvent) => {
      const canvas3d = this.viewer?.plugin.canvas3d;
      if (
        !this.dragState
        || !canvas3d
        || !activeRect
        || (activePointerId !== null && event.pointerId !== activePointerId)
      ) return;
      event.preventDefault();
      event.stopPropagation();
      const ray = screenPointToRay(canvas3d, activeRect, event.clientX, event.clientY);
      const nextBox = computeDraggedBox(this.dragState, toDockingRay(ray), event.clientY);
      if (!nextBox) return;
      this.currentBox = nextBox;
      void this._requestRender(nextBox, this.interactionMode);
      this.boxChangeHandler?.(nextBox);
      this.interactionHandler?.(interactionFeedback(this.activeHit, nextBox));
    };

    const finishDrag = (event: PointerEvent) => {
      if (!this.dragState || (activePointerId !== null && event.pointerId !== activePointerId)) return;
      event.preventDefault();
      event.stopPropagation();
      this.dragState = null;
      this.activeHit = null;
      activeRect = null;
      activePointerId = null;
      container.style.cursor = "";
      this.interactionHandler?.(null);
      void this._requestRender(this.currentBox, this.interactionMode);
    };

    const cancelDrag = (event?: PointerEvent | KeyboardEvent) => {
      if (!this.dragState) return;
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      const original = this.dragState.boxAtStart;
      this.dragState = null;
      this.activeHit = null;
      this.currentBox = original;
      activeRect = null;
      activePointerId = null;
      container.style.cursor = "";
      this.interactionHandler?.(null);
      this.boxChangeHandler?.(original);
      void this._requestRender(original, this.interactionMode);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancelDrag(event);
    };

    const blockMouseEventDuringDrag = (event: MouseEvent) => {
      if (!this.dragState) return;
      event.preventDefault();
      event.stopPropagation();
    };

    const hoverSubscription = this.viewer?.plugin.canvas3d?.interaction.hover.subscribe(({ current }) => {
      if (this.dragState) return;
      container.style.cursor = this._handleFromLoci(current) ? "grab" : "";
    });
    const residueSelectionSubscription = this.viewer?.plugin.managers.structure.selection.events.changed
      .subscribe(() => this._emitSelectedResidues());

    container.addEventListener("pointerdown", onPointerDown, { capture: true });
    window.addEventListener("pointermove", onPointerMove, { capture: true });
    window.addEventListener("pointerup", finishDrag, { capture: true });
    window.addEventListener("pointercancel", cancelDrag, { capture: true });
    window.addEventListener("keydown", onKeyDown, { capture: true });
    container.addEventListener("mousedown", blockMouseEventDuringDrag, { capture: true });
    window.addEventListener("mousemove", blockMouseEventDuringDrag, { capture: true });
    window.addEventListener("mouseup", blockMouseEventDuringDrag, { capture: true });
    this.detachInteraction = () => {
      hoverSubscription?.unsubscribe();
      residueSelectionSubscription?.unsubscribe();
      container.removeEventListener("pointerdown", onPointerDown, { capture: true });
      window.removeEventListener("pointermove", onPointerMove, { capture: true });
      window.removeEventListener("pointerup", finishDrag, { capture: true });
      window.removeEventListener("pointercancel", cancelDrag, { capture: true });
      window.removeEventListener("keydown", onKeyDown, { capture: true });
      container.removeEventListener("mousedown", blockMouseEventDuringDrag, { capture: true });
      window.removeEventListener("mousemove", blockMouseEventDuringDrag, { capture: true });
      window.removeEventListener("mouseup", blockMouseEventDuringDrag, { capture: true });
      container.style.cursor = "";
    };
  }

  private _emitSelectedResidues(): void {
    if (!this.residueSelectionHandler || !this.viewer) return;
    const residues = new Map<string, ViewerResidueSelection>();
    this.viewer.plugin.managers.structure.selection.entries.forEach((entry) => {
      StructureElement.Loci.forEachLocation(entry.selection, (location) => {
        if (!Unit.isAtomic(location.unit)) return;
        // Prepared PDB/PQR bridge files do not always carry a chemical
        // component dictionary, so chem_comp_type can be "other" even for a
        // real amino acid. ATOM records are the stable distinction here;
        // solvent, ions, and retained small molecules remain HETATM records.
        if (StructureProperties.residue.group_PDB(location) !== "ATOM") return;
        const residue: ViewerResidueSelection = {
          chain_id: StructureProperties.chain.auth_asym_id(location),
          residue_name: StructureProperties.residue.auth_comp_id(location),
          sequence_number: StructureProperties.residue.auth_seq_id(location),
          insertion_code: StructureProperties.residue.pdbx_PDB_ins_code(location).trim(),
        };
        const key = [
          residue.chain_id,
          residue.residue_name,
          residue.sequence_number,
          residue.insertion_code,
        ].join("|");
        residues.set(key, residue);
      });
    });
    this.residueSelectionHandler(
      [...residues.values()].sort((first, second) => (
        first.chain_id.localeCompare(second.chain_id)
        || first.sequence_number - second.sequence_number
        || first.insertion_code.localeCompare(second.insertion_code)
      )),
    );
  }

  private _pickedHandle(ray: Ray3D): BoxHit | null {
    const canvas3d = this.viewer?.plugin.canvas3d;
    if (!canvas3d) return null;
    const pick = canvas3d.identify(ray);
    return this._handleFromLoci(canvas3d.getLoci(pick?.id));
  }

  private _handleFromLoci(current: Representation.Loci): BoxHit | null {
    const expectedRepresentation = this.gizmoRepresentationRef?.obj?.data.repr;
    if (!expectedRepresentation || current.repr !== expectedRepresentation) return null;
    if (!ShapeGroup.isLoci(current.loci) || current.loci.groups.length !== 1) return null;
    const ids = current.loci.groups[0].ids;
    if (OrderedSet.size(ids) !== 1) return null;
    return hitFromGroup(OrderedSet.getAt(ids, 0), this.interactionMode);
  }

  private _beginDrag(hit: BoxHit, ray: Ray3D, pointerY: number): DockingBoxDrag | null {
    const box = this.currentBox;
    const canvas3d = this.viewer?.plugin.canvas3d;
    if (!box || !canvas3d) return null;
    const camera = canvas3d.camera;
    const viewDirection = vec3ToTuple(Vec3.sub(Vec3(), camera.position, camera.target));
    const boxCenter = Vec3.create(box.center_x, box.center_y, box.center_z);
    const worldUnitsPerCssPixel = camera.getPixelSize(boxCenter) * canvas3d.webgl.pixelRatio;
    const dockingRay = toDockingRay(ray);
    if (hit.kind === "move-screen") {
      return beginScreenMove(box, dockingRay, viewDirection, pointerY, worldUnitsPerCssPixel);
    }
    if (hit.kind === "move-axis") {
      return beginAxisMove(
        box,
        hit.axis,
        dockingRay,
        viewDirection,
        pointerY,
        worldUnitsPerCssPixel,
      );
    }
    return beginAxisResize(
      box,
      hit.axis,
      hit.direction,
      dockingRay,
      viewDirection,
      pointerY,
      worldUnitsPerCssPixel,
    );
  }

  async clear(): Promise<void> {
    this.pendingRender = null;
    await this._awaitRenderDrain();
    await this.viewer?.plugin.clear();
    this.gizmoShapeRef = null;
    this.gizmoRepresentationRef = null;
    this.contactsShapeRef = null;
    this.contactsRepresentationRef = null;
    this.currentBox = null;
    this.currentSources = [];
  }

  dispose(): void {
    this.detachInteraction?.();
    this.detachInteraction = null;
    this.pendingRender = null;
    this.dragState = null;
    this.activeHit = null;
    this.viewer?.dispose();
    this.viewer = null;
    this.gizmoShapeRef = null;
    this.gizmoRepresentationRef = null;
    this.contactsShapeRef = null;
    this.contactsRepresentationRef = null;
    this.currentBox = null;
    this.currentSources = [];
    this.residueSelectionHandler = null;
    this.residueSelectionEnabled = false;
  }

  private _reportError(reason: unknown): void {
    const message = reason instanceof Error
      ? reason.message
      : "Mol* could not update the docking-box editor.";
    this.errorHandler?.(message);
  }

  private _applyStructureThemes(accentColor: Color): void {
    const manager = this.viewer?.plugin.managers.structure;
    if (!manager) return;
    const structures = manager.hierarchy.current.structures;
    structures.forEach((structure, index) => {
      const appearance = this.currentSources[index]?.appearance ?? "default";
      if (appearance === "interaction-ligand") {
        void manager.component.updateRepresentationsTheme(
          structure.components,
          { color: "element-symbol" },
        );
        return;
      }
      const value = appearance === "interaction-context"
        ? mutedInteractionContextColor(accentColor)
        : accentColor;
      void manager.component.updateRepresentationsTheme(
        structure.components,
        { color: "uniform", colorParams: { value } },
      );
    });
  }
}

function mutedInteractionContextColor(accentColor: Color): Color {
  const red = (accentColor >> 16) & 0xff;
  const green = (accentColor >> 8) & 0xff;
  const blue = accentColor & 0xff;
  const muted = (channel: number) => Math.round(channel * 0.58 + 44 * 0.42);
  return Color((muted(red) << 16) | (muted(green) << 8) | muted(blue));
}

export function buildDockingBoxGizmo(
  center: Vec3,
  size: Vec3,
  mode: DockingBoxInteractionMode,
  reusableMesh?: Mesh,
): Mesh {
  const state = MeshBuilder.createState(2048, 1024, reusableMesh);
  const minimumDimension = Math.min(size[0], size[1], size[2]);
  const handleRadius = Math.min(1.6, Math.max(0.55, minimumDimension * 0.075));
  const edgeRadius = Math.min(0.28, Math.max(0.12, handleRadius * 0.18));
  const halfSize = Vec3.scale(Vec3(), size, 0.5);
  const box = Box3D.create(
    Vec3.sub(Vec3(), center, halfSize),
    Vec3.add(Vec3(), center, halfSize),
  );

  state.currentGroup = HandleGroup.frame;
  const transform = Mat4.mul3(
    Mat4(),
    Mat4.fromTranslation(Mat4(), box.min),
    Mat4.fromScaling(Mat4(), size),
    Mat4.fromTranslation(Mat4(), Vec3.create(0.5, 0.5, 0.5)),
  );
  MeshBuilder.addCage(state, transform, BoxCage(), edgeRadius, 2, 20);

  const protrusion = handleRadius * 2.8;
  if (mode === "move") {
    state.currentGroup = HandleGroup.first;
    addSphere(state, center, handleRadius * 1.15, 2);
    for (const axis of [0, 1, 2] as AxisIndex[]) {
      const endpoint = Vec3.clone(center);
      endpoint[axis] += halfSize[axis] + protrusion;
      state.currentGroup = [HandleGroup.second, HandleGroup.third, HandleGroup.fourth][axis];
      addCylinder(state, center, endpoint, 1, {
        radiusTop: handleRadius * 0.18,
        radiusBottom: handleRadius * 0.18,
        radialSegments: 20,
      });
      addSphere(state, endpoint, handleRadius * 0.72, 2);
    }
  } else {
    const groups = [
      [HandleGroup.first, HandleGroup.second],
      [HandleGroup.third, HandleGroup.fourth],
      [HandleGroup.fifth, HandleGroup.sixth],
    ] as const;
    for (const axis of [0, 1, 2] as AxisIndex[]) {
      for (const direction of [1, -1] as const) {
        const face = Vec3.clone(center);
        face[axis] += direction * halfSize[axis];
        const handle = Vec3.clone(face);
        handle[axis] += direction * protrusion;
        state.currentGroup = direction === 1 ? groups[axis][0] : groups[axis][1];
        addCylinder(state, face, handle, 1, {
          radiusTop: handleRadius * 0.15,
          radiusBottom: handleRadius * 0.15,
          radialSegments: 20,
        });
        addSphere(state, handle, handleRadius, 2);
      }
    }
  }

  const mesh = MeshBuilder.getMesh(state);
  const expandedHalf = Vec3.addScalar(Vec3(), halfSize, protrusion + handleRadius);
  mesh.setBoundingSphere(Sphere3D.create(center, Vec3.magnitude(expandedHalf)));
  return mesh;
}

function handleColor(groupId: number, mode: DockingBoxInteractionMode) {
  if (groupId === HandleGroup.frame) return ColorNames.orange;
  if (mode === "move") {
    if (groupId === HandleGroup.first) return ColorNames.white;
    if (groupId === HandleGroup.second) return ColorNames.red;
    if (groupId === HandleGroup.third) return ColorNames.green;
    return ColorNames.blue;
  }
  if (groupId === HandleGroup.first || groupId === HandleGroup.second) return ColorNames.red;
  if (groupId === HandleGroup.third || groupId === HandleGroup.fourth) return ColorNames.green;
  return ColorNames.blue;
}

function handleLabel(groupId: number, mode: DockingBoxInteractionMode): string {
  if (groupId === HandleGroup.frame) return "Docking search-space box";
  const moveLabels = [
    "Docking search-space box",
    "Move in the current view plane",
    "Move along X",
    "Move along Y",
    "Move along Z",
  ];
  const resizeLabels = [
    "Docking search-space box",
    "Resize X+",
    "Resize X−",
    "Resize Y+",
    "Resize Y−",
    "Resize Z+",
    "Resize Z−",
  ];
  return (mode === "move" ? moveLabels : resizeLabels)[groupId] ?? "Docking-box control";
}

function hitFromGroup(groupId: number, mode: DockingBoxInteractionMode): BoxHit | null {
  if (mode === "move") {
    if (groupId === HandleGroup.first) return { kind: "move-screen" };
    if (groupId === HandleGroup.second) return { kind: "move-axis", axis: 0 };
    if (groupId === HandleGroup.third) return { kind: "move-axis", axis: 1 };
    if (groupId === HandleGroup.fourth) return { kind: "move-axis", axis: 2 };
    return null;
  }
  const resizeHits: BoxHit[] = [
    { kind: "resize-axis", axis: 0, direction: 1 },
    { kind: "resize-axis", axis: 0, direction: -1 },
    { kind: "resize-axis", axis: 1, direction: 1 },
    { kind: "resize-axis", axis: 1, direction: -1 },
    { kind: "resize-axis", axis: 2, direction: 1 },
    { kind: "resize-axis", axis: 2, direction: -1 },
  ];
  return resizeHits[groupId - 1] ?? null;
}

function interactionFeedback(
  hit: BoxHit | null,
  box: BindingBox,
): DockingBoxInteractionFeedback | null {
  if (!hit) return null;
  if (hit.kind === "move-screen") return { action: hit.kind, axis: null, direction: null, box };
  if (hit.kind === "move-axis") {
    return { action: hit.kind, axis: axisName(hit.axis), direction: null, box };
  }
  return {
    action: hit.kind,
    axis: axisName(hit.axis),
    direction: hit.direction,
    box,
  };
}

function axisName(axis: AxisIndex): "x" | "y" | "z" {
  return ["x", "y", "z"][axis] as "x" | "y" | "z";
}

function screenPointToRay(
  canvas3d: NonNullable<Viewer["plugin"]["canvas3d"]>,
  rect: DOMRect,
  clientX: number,
  clientY: number,
): Ray3D {
  canvas3d.handleResize();
  canvas3d.camera.update();
  const dpr = canvas3d.webgl.pixelRatio || window.devicePixelRatio || 1;
  const viewport = canvas3d.camera.viewport;
  const canvasX = (clientX - rect.left) * dpr;
  const canvasYFromTop = (clientY - rect.top) * dpr;
  const x = viewport.x + canvasX;
  const y = viewport.y + (viewport.height - canvasYFromTop);
  const ray = Ray3D();
  canvas3d.camera.getRay(ray, x, y);
  return ray;
}

function toDockingRay(ray: Ray3D): DockingRay {
  return {
    origin: vec3ToTuple(ray.origin),
    direction: vec3ToTuple(ray.direction),
  };
}

function vec3ToTuple(vector: Vec3): Vector3 {
  return [vector[0], vector[1], vector[2]];
}
