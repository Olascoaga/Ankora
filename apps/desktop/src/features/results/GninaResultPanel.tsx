import { useEffect, useMemo, useState } from "react";

import { ankoraApi } from "../../api/client";
import type { CatalogEntry, CompoundRow, GninaDockingJobRecord, ReceptorPreparationRecord } from "../../types/api";
import { formatScientificNumber } from "../../utils/format";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { ViewerSource } from "../../viewer/adapter";

export function GninaResultPanel({ entry, molecule, onClose }: { entry: CatalogEntry; molecule: CompoundRow; onClose: () => void }) {
  const [job, setJob] = useState<GninaDockingJobRecord | null>(null);
  const [receptor, setReceptor] = useState<ReceptorPreparationRecord | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [receptorError, setReceptorError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    setJob(null); setReceptor(null); setSelected(null); setError(null); setReceptorError(null);
    void ankoraApi.getGninaDockingJob(entry.record_id).then((result) => {
      if (disposed) return;
      if (result.engine !== "gnina" || result.job_id !== entry.record_id || result.request.ligand_id !== molecule.ligand_id || result.request.receptor_id !== entry.receptor_id || result.request.binding_site_id !== entry.binding_site_id || result.status !== "completed") throw new Error("The saved GNINA job does not match this result or is not complete.");
      setJob(result); setSelected(result.poses[0]?.mode ?? null);
      void ankoraApi.getReceptor(result.request.receptor_id).then((context) => {
        if (disposed) return;
        if (context.receptor_id !== result.request.receptor_id) throw new Error("The receptor identity does not match this GNINA job.");
        const docking = context.outputs.find((output) => output.artifact_id === result.receptor_output_artifact_id);
        if (!docking || docking.sha256 !== result.receptor_sha256) throw new Error("The receptor record does not match this GNINA job.");
        const display = context.outputs.find((output) => output.artifact_id === context.display_output_artifact_id);
        if (display?.format !== "pdb") throw new Error("The prepared receptor display artifact is unavailable.");
        setReceptor(context);
      }).catch((reason: unknown) => { if (!disposed) setReceptorError(reason instanceof Error ? reason.message : "Receptor context unavailable."); });
    }).catch((reason: unknown) => { if (!disposed) setError(reason instanceof Error ? reason.message : "GNINA poses could not be loaded."); });
    return () => { disposed = true; };
  }, [entry.record_id, entry.receptor_id, entry.binding_site_id, molecule.ligand_id]);

  const sources = useMemo<ViewerSource[]>(() => {
    const result: ViewerSource[] = [];
    const display = receptor?.outputs.find((item) => item.artifact_id === receptor.display_output_artifact_id);
    if (display?.format === "pdb") result.push({ id: display.artifact_id, url: ankoraApi.receptorOutputUrl(display.content_url), format: "pdb", label: `Prepared receptor context · ${display.filename}` });
    const pose = job?.poses.find((item) => item.mode === selected);
    if (job && pose) result.push({ id: pose.artifact.artifact_id, url: ankoraApi.gninaPoseUrl(job.job_id, pose.artifact.artifact_id), format: "pdb", label: `GNINA pose ${pose.mode}` });
    return result;
  }, [job, receptor, selected]);

  return <section className="docking-results" aria-label="GNINA recorded poses">
    <div className="docking-results-heading"><div><span className="eyebrow">Recorded GNINA poses</span><h3>{molecule.name}</h3></div><button type="button" className="quiet-button" onClick={onClose}>Close</button></div>
    <p className="field-note">Higher CNNscore ranks poses first. CNN affinity is predicted pK; minimized affinity is in kcal/mol. These are predictions, not measured affinities. Interaction analysis is not yet available for GNINA.</p>
    {error ? <div className="structure-error" role="alert">{error}</div> : null}
    {receptorError ? <div className="structure-error" role="alert">Receptor context unavailable: {receptorError}</div> : null}
    {sources.length ? <MolecularViewer sources={sources} selection={null} dockingBox={job?.box ?? null} /> : null}
    {job ? <div className="docking-results-scroll"><table><thead><tr><th>Pose</th><th>CNN score</th><th>CNN affinity (pK)</th><th>Minimized affinity (kcal/mol)</th><th>Artifact</th></tr></thead><tbody>{job.poses.map((pose) => <tr key={pose.mode} className={selected === pose.mode ? "selected" : ""}><td><button type="button" className="pose-select" aria-pressed={selected === pose.mode} onClick={() => setSelected(pose.mode)}>Pose {pose.mode}</button></td><td>{formatScientificNumber(pose.cnn_score, 4)}</td><td>{formatScientificNumber(pose.cnn_affinity, 3)}</td><td>{formatScientificNumber(pose.minimized_affinity_kcal_mol, 3)}</td><td><code>{pose.artifact.sha256.slice(0, 12)}…</code></td></tr>)}</tbody></table></div> : !error ? <p className="field-note">Reading GNINA poses…</p> : null}
  </section>;
}
