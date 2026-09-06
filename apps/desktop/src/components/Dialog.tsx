import {
  useLayoutEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

interface DialogProps {
  children: ReactNode;
  labelledBy: string;
  describedBy?: string;
  onClose: () => void;
  className?: string;
  backdropClassName?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  fallbackFocusRef?: RefObject<HTMLElement | null>;
  dismissible?: boolean;
}

interface BackgroundState {
  element: HTMLElement;
  inert: boolean;
  ariaHidden: string | null;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "summary",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/**
 * Ankora's modal-dialog boundary.
 *
 * Dialogs are portalled beside the application root so the root can be made
 * inert and hidden from the accessibility tree. Focus never escapes while the
 * dialog is mounted, Escape follows the caller's dismissibility rule, and
 * closing returns focus to the opener or a stable caller-provided fallback.
 */
export function Dialog({
  children,
  labelledBy,
  describedBy,
  onClose,
  className = "",
  backdropClassName = "dialog-backdrop",
  initialFocusRef,
  fallbackFocusRef,
  dismissible = true,
}: DialogProps) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const restoreTargetRef = useRef<HTMLElement | null>(null);
  const restoreTimerRef = useRef<number | null>(null);
  const closeRef = useRef(onClose);
  const dismissibleRef = useRef(dismissible);
  closeRef.current = onClose;
  dismissibleRef.current = dismissible;

  useLayoutEffect(() => {
    if (restoreTimerRef.current !== null) {
      window.clearTimeout(restoreTimerRef.current);
      restoreTimerRef.current = null;
    }

    const dialog = dialogRef.current;
    const backdrop = backdropRef.current;
    if (!dialog || !backdrop) return undefined;

    const active = document.activeElement;
    if (active instanceof HTMLElement && !dialog.contains(active)) {
      restoreTargetRef.current = active;
    }

    const background = [...document.body.children]
      .filter((element): element is HTMLElement => (
        element instanceof HTMLElement && element !== backdrop
      ))
      .map((element): BackgroundState => ({
        element,
        inert: Boolean(element.inert),
        ariaHidden: element.getAttribute("aria-hidden"),
      }));

    for (const state of background) {
      state.element.inert = true;
      state.element.setAttribute("aria-hidden", "true");
    }

    const requestedInitialFocus = initialFocusRef?.current;
    const firstFocusable = getFocusableElements(dialog)[0];
    (requestedInitialFocus ?? firstFocusable ?? dialog).focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && dismissibleRef.current) {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = getFocusableElements(dialog!);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog!.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const current = document.activeElement;
      const focusIsOnDialogControl = current instanceof HTMLElement && focusable.includes(current);
      if (event.shiftKey && (current === first || !focusIsOnDialogControl)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !focusIsOnDialogControl)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      for (const state of background) {
        state.element.inert = state.inert;
        if (state.ariaHidden === null) state.element.removeAttribute("aria-hidden");
        else state.element.setAttribute("aria-hidden", state.ariaHidden);
      }

      restoreTimerRef.current = window.setTimeout(() => {
        restoreTimerRef.current = null;
        const activeBackdrop = document.querySelector('[data-dialog-backdrop="true"]');
        if (activeBackdrop && activeBackdrop !== backdrop) return;
        const previous = restoreTargetRef.current;
        const fallback = fallbackFocusRef?.current;
        if (canReceiveRestoredFocus(previous)) previous.focus();
        else if (canReceiveRestoredFocus(fallback)) fallback.focus();
      }, 0);
    };
  }, []);

  return createPortal(
    <div ref={backdropRef} className={backdropClassName} data-dialog-backdrop="true">
      <section
        ref={dialogRef}
        className={className}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
      >
        {children}
      </section>
    </div>,
    document.body,
  );
}

function getFocusableElements(dialog: HTMLElement): HTMLElement[] {
  return [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)].filter(
    (element) => element.getAttribute("aria-hidden") !== "true",
  );
}

function canReceiveRestoredFocus(element: HTMLElement | null | undefined): element is HTMLElement {
  return Boolean(
    element?.isConnected &&
      element !== document.body &&
      element !== document.documentElement &&
      !element.hasAttribute("disabled"),
  );
}
