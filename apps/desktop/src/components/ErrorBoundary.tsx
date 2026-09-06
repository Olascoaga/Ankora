import {
  Component,
  useState,
  type ErrorInfo,
  type ReactNode,
} from "react";

export interface RenderFailureEvidence {
  kind: "react_render_failure";
  scope: string;
  error_name: string;
  message: string;
  component_stack: string | null;
  javascript_stack: string | null;
}

interface BoundaryProps {
  children: ReactNode;
  scope: string;
  level: "application" | "workspace";
  resetKey?: string;
  onLeaveWorkspace?: () => void;
}

interface BoundaryState {
  error: Error | null;
  componentStack: string | null;
}

const EMPTY_STATE: BoundaryState = {
  error: null,
  componentStack: null,
};

/**
 * Contains React render/lifecycle failures without treating display recovery
 * as permission to repeat scientific work. Workspace navigation resets the
 * local boundary; the application boundary remains the last-resort shell.
 */
export class ErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = EMPTY_STATE;

  static getDerivedStateFromError(error: unknown): Partial<BoundaryState> {
    return { error: normalizeError(error) };
  }

  componentDidCatch(_error: Error, info: ErrorInfo) {
    this.setState({ componentStack: info.componentStack?.trim() || null });
  }

  componentDidUpdate(previousProps: BoundaryProps) {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) {
      this.setState(EMPTY_STATE);
    }
  }

  private retry = () => {
    this.setState(EMPTY_STATE);
  };

  private leaveWorkspace = () => {
    this.props.onLeaveWorkspace?.();
    this.setState(EMPTY_STATE);
  };

  private reloadApplication = () => {
    window.location.reload();
  };

  render() {
    const { children, level, scope } = this.props;
    const { componentStack, error } = this.state;
    if (!error) return children;

    const evidence = createRenderFailureEvidence(scope, error, componentStack);
    if (level === "application") {
      return (
        <main className="application-failure" role="alert" aria-labelledby="application-failure-title">
          <div className="application-failure-card">
            <span className="eyebrow">Display recovery</span>
            <h1 id="application-failure-title">Ankora could not draw the application</h1>
            <p>
              The interface stopped safely. This display failure did not rerun a scientific
              tool or modify recorded artifacts.
            </p>
            <div className="render-failure-actions">
              <button type="button" className="primary-action" onClick={this.retry}>Try again</button>
              <button type="button" onClick={this.reloadApplication}>Reload Ankora</button>
            </div>
            <TechnicalEvidencePanel evidence={evidence} />
          </div>
        </main>
      );
    }

    return (
      <>
        <section className="workspace workspace-failure" role="alert" aria-labelledby="workspace-failure-title">
          <div className="workspace-failure-card">
            <span className="eyebrow">Workspace recovery</span>
            <h2 id="workspace-failure-title">This workspace could not be displayed</h2>
            <p>
              The surrounding workbench is still available. No scientific command was
              repeated and no recorded artifact was changed by this rendering failure.
            </p>
            <div className="render-failure-actions">
              <button type="button" className="primary-action" onClick={this.retry}>Try this workspace again</button>
              {this.props.onLeaveWorkspace ? (
                <button type="button" onClick={this.leaveWorkspace}>Return to Structure</button>
              ) : null}
            </div>
            <TechnicalEvidencePanel evidence={evidence} />
          </div>
        </section>
        <aside className="inspector workspace-failure-inspector" aria-label="Workspace recovery status">
          <span className="eyebrow">Display status</span>
          <h2>Workspace contained</h2>
          <p>Navigation and saved evidence remain available while you recover this view.</p>
        </aside>
      </>
    );
  }
}

export function createRenderFailureEvidence(
  scope: string,
  error: Error,
  componentStack: string | null,
): RenderFailureEvidence {
  return {
    kind: "react_render_failure",
    scope,
    error_name: error.name || "Error",
    message: error.message || "Unknown rendering failure",
    component_stack: componentStack,
    javascript_stack: error.stack ?? null,
  };
}

export function TechnicalEvidencePanel({ evidence }: { evidence: RenderFailureEvidence }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const serialized = JSON.stringify(evidence, null, 2);

  async function copyEvidence() {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard access is unavailable");
      await navigator.clipboard.writeText(serialized);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <details className="technical-evidence-panel">
      <summary>Technical evidence</summary>
      <p>
        Include this report when requesting support. Development builds may include local
        file paths in the JavaScript stack.
      </p>
      <pre>{serialized}</pre>
      <div className="technical-evidence-actions">
        <button type="button" onClick={() => void copyEvidence()}>Copy technical evidence</button>
        <span role="status" aria-live="polite">
          {copyState === "copied" ? "Copied" : copyState === "failed" ? "Clipboard unavailable — select the text above" : ""}
        </span>
      </div>
    </details>
  );
}

function normalizeError(error: unknown): Error {
  if (error instanceof Error) return error;
  if (typeof error === "string") return new Error(error);
  return new Error("Unknown rendering failure");
}
