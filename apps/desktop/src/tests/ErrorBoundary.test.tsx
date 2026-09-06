import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary, createRenderFailureEvidence } from "../components/ErrorBoundary";

function BrokenView({ shouldThrow = true }: { shouldThrow?: boolean }) {
  if (shouldThrow) throw new Error("Synthetic workspace render failure");
  return <p>Recovered workspace</p>;
}

describe("ErrorBoundary", () => {
  it("contains a workspace failure while the surrounding shell remains usable", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <>
        <button type="button">Workflow navigation</button>
        <ErrorBoundary level="workspace" scope="default / Results" resetKey="default:Results">
          <BrokenView />
        </ErrorBoundary>
        <p>Status bar remains</p>
      </>,
    );

    expect(screen.getByRole("heading", { name: "This workspace could not be displayed" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Workflow navigation" })).toBeEnabled();
    expect(screen.getByText("Status bar remains")).toBeInTheDocument();
    expect(screen.getByText(/No scientific command was repeated/)).toBeInTheDocument();
  });

  it("retries only the failed display and exposes copyable technical evidence", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    let shouldThrow = true;

    function ControlledView() {
      return <BrokenView shouldThrow={shouldThrow} />;
    }

    render(
      <ErrorBoundary level="workspace" scope="project-alpha / Docking" resetKey="project-alpha:Docking">
        <ControlledView />
      </ErrorBoundary>,
    );

    fireEvent.click(screen.getByText("Technical evidence"));
    expect(screen.getByText(/Synthetic workspace render failure/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy technical evidence" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledOnce());
    expect(writeText.mock.calls[0][0]).toContain('"scope": "project-alpha / Docking"');
    expect(screen.getByRole("status")).toHaveTextContent("Copied");

    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Try this workspace again" }));
    expect(screen.getByText("Recovered workspace")).toBeInTheDocument();
  });

  it("resets workspace containment when navigation changes the reset key", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(
      <ErrorBoundary level="workspace" scope="default / Ligand" resetKey="default:Ligand">
        <BrokenView />
      </ErrorBoundary>,
    );
    expect(screen.getByText("This workspace could not be displayed")).toBeInTheDocument();

    rerender(
      <ErrorBoundary level="workspace" scope="default / Binding site" resetKey="default:Binding site">
        <BrokenView shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(await screen.findByText("Recovered workspace")).toBeInTheDocument();
  });

  it("leaves a failed workspace without retrying its scientific screen", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    function TestShell() {
      const [step, setStep] = useState("Docking");
      return (
        <ErrorBoundary
          level="workspace"
          scope={`default / ${step}`}
          resetKey={`default:${step}`}
          onLeaveWorkspace={() => setStep("Structure")}
        >
          {step === "Docking" ? <BrokenView /> : <p>Structure workspace</p>}
        </ErrorBoundary>
      );
    }

    render(<TestShell />);
    fireEvent.click(screen.getByRole("button", { name: "Return to Structure" }));

    expect(await screen.findByText("Structure workspace")).toBeInTheDocument();
  });

  it("provides a last-resort application fallback without claiming scientific recovery", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ErrorBoundary level="application" scope="application shell">
        <BrokenView />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("heading", { name: "Ankora could not draw the application" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload Ankora" })).toBeInTheDocument();
    expect(screen.getByText(/did not rerun a scientific tool/)).toBeInTheDocument();
  });
});

describe("createRenderFailureEvidence", () => {
  it("serializes stable diagnostic fields without inventing scientific context", () => {
    const error = new TypeError("Synthetic evidence failure");
    error.stack = "TypeError: Synthetic evidence failure\n at BrokenView";

    expect(createRenderFailureEvidence("default / Receptor", error, "at BrokenView")).toEqual({
      kind: "react_render_failure",
      scope: "default / Receptor",
      error_name: "TypeError",
      message: "Synthetic evidence failure",
      component_stack: "at BrokenView",
      javascript_stack: "TypeError: Synthetic evidence failure\n at BrokenView",
    });
  });
});
