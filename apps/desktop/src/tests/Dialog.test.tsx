import { useRef, useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Dialog } from "../components/Dialog";

function DialogHarness({ dismissible = true }: { dismissible?: boolean }) {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement>(null);
  const initialFocusRef = useRef<HTMLButtonElement>(null);

  return (
    <main data-testid="background-content">
      <button ref={openerRef} type="button" onClick={() => setOpen(true)}>Open dialog</button>
      {open ? (
        <Dialog
          labelledBy="test-dialog-title"
          onClose={() => setOpen(false)}
          initialFocusRef={initialFocusRef}
          dismissible={dismissible}
        >
          <h2 id="test-dialog-title">Accessible dialog</h2>
          <button ref={initialFocusRef} type="button">Safe first action</button>
          <button type="button">Last action</button>
          <button type="button" onClick={() => setOpen(false)}>Close dialog</button>
        </Dialog>
      ) : null}
    </main>
  );
}

it("moves initial focus into the dialog and isolates the application background", () => {
  const { container } = render(<DialogHarness />);
  fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));

  expect(screen.getByRole("button", { name: "Safe first action" })).toHaveFocus();
  expect(container).toHaveAttribute("aria-hidden", "true");
  expect(container.inert).toBe(true);
  expect(screen.getByRole("dialog", { name: "Accessible dialog" })).toHaveAttribute("aria-modal", "true");
});

it("traps forward and reverse Tab movement inside the dialog", () => {
  render(<DialogHarness />);
  fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
  const dialog = screen.getByRole("dialog", { name: "Accessible dialog" });
  const first = screen.getByRole("button", { name: "Safe first action" });
  const last = screen.getByRole("button", { name: "Close dialog" });

  last.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(first).toHaveFocus();

  first.focus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();

  dialog.focus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
});

it("closes on Escape, restores background semantics, and returns focus to the opener", async () => {
  const { container } = render(<DialogHarness />);
  const opener = screen.getByRole("button", { name: "Open dialog" });
  opener.focus();
  fireEvent.click(opener);

  fireEvent.keyDown(document, { key: "Escape" });

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(container).not.toHaveAttribute("aria-hidden");
  expect(container.inert).toBe(false);
  await waitFor(() => expect(opener).toHaveFocus());
});

it("honors a temporarily non-dismissible operation", () => {
  render(<DialogHarness dismissible={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));

  fireEvent.keyDown(document, { key: "Escape" });

  expect(screen.getByRole("dialog", { name: "Accessible dialog" })).toBeInTheDocument();
});
