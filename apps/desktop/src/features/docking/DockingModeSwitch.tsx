export type DockingMode =
  | "single"
  | "screening"
  | "autodock4"
  | "autodock4-screening"
  | "gnina"
  | "gnina-screening"
  | "comparison";

interface DockingModeSwitchProps {
  mode: DockingMode;
  hasLibrary: boolean;
  showGnina?: boolean;
  onChange: (mode: DockingMode) => void;
}

/**
 * One selector for the whole docking experiment, not separate engine and scope
 * controls.
 *
 * Both engines now run either a single ligand or a screening library, but the
 * combinations are still listed directly rather than split into engine and
 * scope controls: the two are chosen together, and a screening option only
 * exists once a library is loaded. Every option names its engine, because a
 * score only means something next to the engine that produced it.
 *
 * Labels are kept terse deliberately: the workspace heading is only ~492px wide
 * at a 1280px window, and longer wording pushed this control onto a second row.
 *
 * GNINA is Linux-only, so both of its options appear only where it exists; its
 * screening option additionally needs an applied library selection, like the
 * other screening options.
 */
export function DockingModeSwitch({ mode, hasLibrary, showGnina = false, onChange }: DockingModeSwitchProps) {
  return (
    <div className="workspace-mode-switch docking-mode-switch" aria-label="Docking experiment">
      <button
        type="button"
        className={mode === "single" ? "selected" : ""}
        aria-pressed={mode === "single"}
        onClick={() => onChange("single")}
      >
        Vina · single
      </button>
      {showGnina ? <button type="button" className={mode === "gnina" ? "selected" : ""} aria-pressed={mode === "gnina"} onClick={() => onChange("gnina")}>GNINA · single</button> : null}
      {showGnina && hasLibrary ? <button type="button" className={mode === "gnina-screening" ? "selected" : ""} aria-pressed={mode === "gnina-screening"} onClick={() => onChange("gnina-screening")}>GNINA · screening</button> : null}
      {hasLibrary ? (
        <button
          type="button"
          className={mode === "screening" ? "selected" : ""}
          aria-pressed={mode === "screening"}
          onClick={() => onChange("screening")}
        >
          Vina · screening
        </button>
      ) : null}
      <button
        type="button"
        className={mode === "autodock4" ? "selected" : ""}
        aria-pressed={mode === "autodock4"}
        onClick={() => onChange("autodock4")}
      >
        AutoDock4 · single
      </button>
      {hasLibrary ? (
        <button
          type="button"
          className={mode === "autodock4-screening" ? "selected" : ""}
          aria-pressed={mode === "autodock4-screening"}
          onClick={() => onChange("autodock4-screening")}
        >
          AutoDock4 · screening
        </button>
      ) : null}
      {hasLibrary ? (
        <button
          type="button"
          className={mode === "comparison" ? "selected" : ""}
          aria-pressed={mode === "comparison"}
          onClick={() => onChange("comparison")}
        >
          Compare engines
        </button>
      ) : null}
    </div>
  );
}
