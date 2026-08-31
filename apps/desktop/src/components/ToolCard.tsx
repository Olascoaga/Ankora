import type { ToolStatus } from "../types/api";

interface ToolCardProps {
  name: string;
  status: ToolStatus | null;
  category?: string;
  note?: string;
}

export function ToolCard({ name, status, category = "Docking engine", note = "Discovery only. Ankora has not run this tool." }: ToolCardProps) {
  const detected = status?.available === true;
  const stateLabel = status === null ? "Checking" : detected ? "Detected" : "Not found";

  return (
    <article className="tool-card">
      <div>
        <span className="eyebrow">{category}</span>
        <h3>{name}</h3>
      </div>
      <span className={`availability ${detected ? "available" : "unavailable"}`}>{stateLabel}</span>
      {detected && status.path ? <p className="tool-path" title={status.path}>{status.path}</p> : null}
      <p className="tool-note">{note}</p>
    </article>
  );
}
