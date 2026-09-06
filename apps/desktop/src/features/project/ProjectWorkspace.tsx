import { useEffect, useState } from "react";

import type {
  ProjectCatalog,
  ProjectDependencyGraph,
  ProjectDependencyNode,
  ProjectRecord,
} from "../../types/api";

interface ProjectWorkspaceProps {
  catalog: ProjectCatalog;
  graph: ProjectDependencyGraph | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
  onActivate: (project: ProjectRecord) => Promise<void>;
  onMarkStale: (node: ProjectDependencyNode, reason: string) => Promise<void>;
  onLoadMore: () => Promise<void>;
}

export function ProjectWorkspace({
  catalog,
  graph,
  busy,
  error,
  onClose,
  onCreate,
  onActivate,
  onMarkStale,
  onLoadMore,
}: ProjectWorkspaceProps) {
  const [name, setName] = useState("");
  const [staleTarget, setStaleTarget] = useState<ProjectDependencyNode | null>(null);
  const [reason, setReason] = useState("");
  const active = catalog.projects.find((item) => item.project_id === catalog.active_project_id);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onClose]);

  return (
    <div className="project-workspace-backdrop" role="presentation">
      <section
        className="project-workspace-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-workspace-title"
      >
        <header>
          <div>
            <span className="eyebrow">Project workspace</span>
            <h2 id="project-workspace-title">{active?.name ?? "Current project"}</h2>
            <p>Each project owns an independent chain of immutable scientific evidence.</p>
          </div>
          <button type="button" onClick={onClose} disabled={busy}>Close</button>
        </header>

        {error ? <p className="project-workspace-error" role="alert">{error}</p> : null}

        <div className="project-workspace-columns">
          <section className="project-list" aria-label="Projects">
            <h3>Projects</h3>
            <ul>
              {catalog.projects.map((project) => {
                const isActive = project.project_id === catalog.active_project_id;
                return (
                  <li key={project.project_id} className={isActive ? "active" : ""}>
                    <div>
                      <strong>{project.name}</strong>
                      <small>{project.migrated_legacy ? "Migrated evidence" : "Independent project"}</small>
                    </div>
                    <button
                      type="button"
                      disabled={busy || isActive}
                      onClick={() => void onActivate(project)}
                    >
                      {isActive ? "Open" : "Switch"}
                    </button>
                  </li>
                );
              })}
            </ul>
            <form onSubmit={(event) => {
              event.preventDefault();
              if (!name.trim()) return;
              void onCreate(name.trim()).then(() => setName(""));
            }}>
              <label htmlFor="new-project-name">New project</label>
              <div>
                <input
                  id="new-project-name"
                  value={name}
                  maxLength={80}
                  placeholder="e.g. PIK3CD screening"
                  onChange={(event) => setName(event.target.value)}
                  disabled={busy}
                />
                <button type="submit" disabled={busy || !name.trim()}>Create & open</button>
              </div>
            </form>
          </section>

          <section className="dependency-graph" aria-label="Dependency and stale graph">
            <div className="dependency-summary">
              <div><strong>{graph?.total_nodes ?? 0}</strong><span>records</span></div>
              <div><strong>{graph?.stale_count ?? 0}</strong><span>stale</span></div>
              <div><strong>{graph?.unresolved_reference_count ?? 0}</strong><span>external links</span></div>
            </div>
            <p>
              Stale state is explicit and flows only to dependent records. Alternatives and older
              results remain valid evidence.
            </p>
            <div className="dependency-table-wrap">
              <table>
                <thead><tr><th>Record</th><th>Kind</th><th>Parents</th><th>Status</th></tr></thead>
                <tbody>
                  {graph?.nodes.map((node) => (
                    <tr key={node.node_id} className={node.stale ? "stale" : ""}>
                      <td><strong>{node.label}</strong><small>{node.node_id}</small></td>
                      <td>{node.kind.replaceAll("_", " ")}</td>
                      <td>{node.parent_ids.length}</td>
                      <td>
                        {node.stale
                          ? <><span>Stale</span><small>{node.stale_reasons.at(-1)}</small></>
                          : <button type="button" disabled={busy} onClick={() => {
                            setStaleTarget(node);
                            setReason("");
                          }}>Mark stale…</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {graph && graph.nodes.length < graph.total_nodes ? (
              <button type="button" className="load-dependencies" disabled={busy} onClick={() => void onLoadMore()}>
                Load more records
              </button>
            ) : null}
          </section>
        </div>

        {staleTarget ? (
          <section className="stale-confirmation" aria-label="Confirm stale state">
            <div>
              <strong>Mark {staleTarget.label} stale?</strong>
              <p>Its descendants will also be shown as stale. No evidence will be edited or deleted.</p>
            </div>
            <input
              aria-label="Reason for stale state"
              value={reason}
              maxLength={240}
              placeholder="Scientific reason for replacing this input"
              onChange={(event) => setReason(event.target.value)}
            />
            <button type="button" onClick={() => setStaleTarget(null)} disabled={busy}>Cancel</button>
            <button
              type="button"
              className="danger-action"
              disabled={busy || !reason.trim()}
              onClick={() => void onMarkStale(staleTarget, reason.trim()).then(() => {
                setStaleTarget(null);
                setReason("");
              })}
            >
              Confirm stale state
            </button>
          </section>
        ) : null}
      </section>
    </div>
  );
}
