import { useEffect, useRef, useState } from "react";

import { ankoraApi } from "../../api/client";
import type { CatalogEntry, CatalogPage, RedockingReferencePage, RedockingRunRecord,
  RedockingValidationRequest } from "../../types/api";

type SourceKind = RedockingValidationRequest["source_kind"];
const supported = new Set(["vina_job", "autodock4_job", "autodock_gpu_job"]);
const message = (reason: unknown) => reason instanceof Error ? reason.message : "Validation could not be completed.";

/** This form measures preserved outputs; it never submits a docking job. */
export function CreateRedockingValidation({ onCreated }: { onCreated: (run: RedockingRunRecord) => void }) {
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [source, setSource] = useState<CatalogEntry | null>(null);
  const [references, setReferences] = useState<RedockingReferencePage | null>(null);
  const [referenceOffset, setReferenceOffset] = useState(0);
  const [referenceReload, setReferenceReload] = useState(0);
  const [referenceId, setReferenceId] = useState("");
  const [threshold, setThreshold] = useState("2.0");
  const [confirmed, setConfirmed] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    let disposed = false;
    setPage(null); setCatalogError(null);
    void ankoraApi.listResultCampaigns({ mode: "single_ligand", status: "completed", offset, limit: 25 })
      .then((next) => { if (!disposed) setPage(next); })
      .catch((reason: unknown) => { if (!disposed) setCatalogError(message(reason)); });
    return () => { disposed = true; };
  }, [offset, reload]);

  useEffect(() => {
    let disposed = false;
    setReferences(null); setReferenceError(null);
    if (source) void ankoraApi.redockingReferences(source.engine_key as SourceKind, source.record_id, referenceOffset)
      .then((next) => { if (!disposed) setReferences(next); })
      .catch((reason: unknown) => { if (!disposed) setReferenceError(message(reason)); });
    return () => { disposed = true; };
  }, [source, referenceOffset, referenceReload]);

  const numericThreshold = Number(threshold);
  const validThreshold = threshold.trim() !== "" && Number.isFinite(numericThreshold)
    && numericThreshold > 0 && numericThreshold <= 20;
  const validReference = references?.references.some((item) => item.ligand_id === referenceId) ?? false;

  async function submit() {
    if (pending.current || !source || !validReference || !validThreshold || !confirmed) return;
    pending.current = true; setBusy(true); setSaveError(null); setSavedId(null);
    try {
      const record = await ankoraApi.validateRedocking({
        source_kind: source.engine_key as SourceKind, source_id: source.record_id,
        reference_ligand_id: referenceId, threshold_angstrom: numericThreshold,
      });
      if (mounted.current) { onCreated(record); setConfirmed(false); setSavedId(record.validation_id); }
    } catch (reason) {
      if (mounted.current) setSaveError(message(reason));
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <section className="redocking-setup" aria-label="Create redocking validation">
    <h3>Validate an existing docking result</h3>
    <p>First dock the reference ligand individually in Docking. Then measure its preserved poses here.
      Screening campaigns are not individual redocking experiments. This step launches no docking.</p>
    {catalogError ? <div role="alert">{catalogError} <button type="button" onClick={() => setReload((n) => n + 1)}>Retry docking results</button></div> : null}
    {!page && !catalogError ? <p role="status">Reading completed docking results…</p> : null}
    <fieldset disabled={busy}>
      <label>1 · Completed docking result
        <select aria-label="Completed docking result" value={source?.catalog_id ?? ""} onChange={(event) => {
          setSource(page?.entries.find((item) => item.catalog_id === event.target.value) ?? null);
          setReferenceOffset(0); setReferenceId(""); setReferences(null); setConfirmed(false); setSaveError(null);
        }}>
          <option value="">Choose an individual result</option>
          {page?.entries.filter((item) => supported.has(item.engine_key)).map((item) => <option key={item.catalog_id} value={item.catalog_id}>
            {item.engine_label} · {item.best_molecule ?? "Ligand"} · {new Date(item.created_at).toLocaleString()} · {item.record_id.slice(0, 8)}
          </option>)}
        </select>
      </label>
      {page && page.total === 0 ? <p>No completed individual results. Run a single-ligand docking first.</p> : null}
      {page && page.total > page.limit ? <div className="redocking-pagination" aria-label="Docking result pages">
        <button type="button" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 25)); setSource(null); setReferenceId(""); setConfirmed(false); }}>Previous results</button>
        <span>{offset + 1}–{Math.min(offset + page.limit, page.total)} of {page.total}</span>
        <button type="button" disabled={offset + page.limit >= page.total} onClick={() => { setOffset(offset + 25); setSource(null); setReferenceId(""); setConfirmed(false); }}>Next results</button>
      </div> : null}
      {source ? <>
        {referenceError ? <div role="alert">{referenceError} <button type="button" onClick={() => setReferenceReload((n) => n + 1)}>Retry references</button></div> : null}
        {!references && !referenceError ? <p role="status">Reading crystallographic references…</p> : null}
        <label>2 · Original crystallographic reference
          <select aria-label="Crystallographic reference" value={referenceId} onChange={(event) => {
            setReferenceId(event.target.value); setConfirmed(false); setSaveError(null);
          }}>
            <option value="">Choose the matching crystal ligand</option>
            {references?.references.map((item) => <option key={item.ligand_id} value={item.ligand_id}>
              {item.name} · {item.locator.component_name} {item.locator.chain_id}:{item.locator.sequence_number}{item.locator.insertion_code} · {item.heavy_atom_count} heavy atoms · {item.ligand_id.slice(0, 8)}
            </option>)}
          </select>
        </label>
        {references?.total === 0 ? <p>No original 3D crystal ligand is available in this receptor’s source coordinate frame.
          Extract the reference ligand from that original structure in Ligand, then <button type="button" onClick={() => setReferenceReload((n) => n + 1)}>Refresh references</button>.</p> : null}
        {references && references.total > references.limit ? <div className="redocking-pagination">
          <button type="button" disabled={referenceOffset === 0} onClick={() => { setReferenceOffset(Math.max(0, referenceOffset - 100)); setReferenceId(""); setConfirmed(false); }}>Previous references</button>
          <span>{referenceOffset + 1}–{Math.min(referenceOffset + references.limit, references.total)} of {references.total}</span>
          <button type="button" disabled={referenceOffset + references.limit >= references.total} onClick={() => { setReferenceOffset(referenceOffset + 100); setReferenceId(""); setConfirmed(false); }}>Next references</button>
        </div> : null}
        <p className="field-note">Choose the same molecule, not a prepared or minimized conformer. Ankora checks
          original-structure identity, file fingerprints and heavy-atom compatibility; it does not align the poses.</p>
      </> : null}
      <label>3 · Recovery threshold (Å)
        <input aria-label="Recovery threshold (Å)" type="number" min="0.001" max="20" step="any" value={threshold}
          onChange={(event) => { setThreshold(event.target.value); setConfirmed(false); setSaveError(null); }} />
      </label>
      {!validThreshold ? <p role="alert">Enter a threshold greater than 0 and no more than 20 Å.</p> : null}
      <label className="redocking-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        I confirm this result and crystal reference form the same redocking experiment.</label>
      <button type="button" className="primary-button" disabled={!source || !validReference || !validThreshold || !confirmed || busy} onClick={() => void submit()}>
        {busy ? "Measuring and saving…" : "Calculate RMSD and save validation"}
      </button>
    </fieldset>
    {savedId ? <p role="status">Validation {savedId.slice(0, 8)} saved. Review the sampling, ranking and per-pose RMSD below.</p> : null}
    {saveError ? <div className="structure-error" role="alert">{saveError}</div> : null}
  </section>;
}
