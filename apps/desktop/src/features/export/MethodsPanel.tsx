import { type ReactElement, useEffect, useState } from "react";

import { ankoraApi } from "../../api/client";
import type { MethodsReport } from "../../types/api";

/**
 * The Methods section a campaign's own records support, read before it is used.
 *
 * The generator already refuses to assert anything a record does not hold: a
 * missing artifact becomes a visible `[not recorded: …]` marker in the prose
 * and an entry in `gaps`. That only protects the author if they see it, so the
 * gaps are shown above the text rather than left to be found by reading — a
 * Methods section is the part of a paper a reader trusts to be literal.
 *
 * What leaves here is the markdown verbatim. The preview renders it so the
 * author can read what they are about to paste; the clipboard gets the source,
 * because that is what a manuscript takes.
 */

export function MethodsPanel({ catalogId }: { catalogId: string }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="receptor-section methods-section">
      <div className="filter-heading"><span>Methods</span></div>
      <p className="field-note">
        The Methods section this campaign can support, written from its own
        records — receptor, site, ligand rules, engine parameters and outcome.
      </p>
      <button type="button" className="secondary-action" onClick={() => setOpen(true)}>
        Write the Methods section
      </button>
      {open ? <MethodsDialog catalogId={catalogId} onClose={() => setOpen(false)} /> : null}
    </section>
  );
}

function MethodsDialog({ catalogId, onClose }: { catalogId: string; onClose: () => void }) {
  const [report, setReport] = useState<MethodsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let disposed = false;
    void ankoraApi.campaignMethods(catalogId)
      .then((next) => { if (!disposed) setReport(next); })
      .catch((reason: unknown) => {
        if (disposed) return;
        setError(reason instanceof Error ? reason.message : "The Methods section could not be written.");
      });
    return () => { disposed = true; };
  }, [catalogId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = async () => {
    if (!report) return;
    const written = await copyText(report.markdown);
    setCopied(written);
  };

  return (
    <div className="results-delete-backdrop">
      <section
        className="results-delete-dialog methods-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="methods-title"
      >
        <div>
          <span className="section-label">Export · Methods</span>
          <h2 id="methods-title">Methods section</h2>
          {report ? (
            <p className="inspector-subtitle">
              {report.engine_label} · {report.software.length} tools cited
            </p>
          ) : null}
        </div>

        {error ? <div className="structure-error" role="alert">{error}</div> : null}

        {!report && !error ? (
          <div className="operation-progress" role="progressbar" aria-label="Writing the Methods section">
            <span /><p>Reading what this campaign recorded</p>
          </div>
        ) : null}

        {report ? (
          <>
            {report.gaps.length ? (
              <div className="methods-gaps" role="alert">
                <strong>
                  {report.gaps.length} {report.gaps.length === 1 ? "statement" : "statements"} this
                  campaign cannot support
                </strong>
                <p>
                  Each appears in the text below as a marker. Ankora will not write a
                  plausible sentence in its place — complete them from your own records
                  before submitting.
                </p>
                <ul>{report.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
              </div>
            ) : (
              <p className="field-note methods-complete">
                Every sentence below is rendered from a stored record. Nothing is missing.
              </p>
            )}

            <div className="methods-preview" aria-label="Methods preview">
              {renderMarkdown(report.markdown)}
            </div>
          </>
        ) : null}

        <div className="methods-actions">
          <button type="button" className="quiet-button" onClick={onClose}>Close</button>
          <button
            type="button"
            className="primary-action"
            disabled={!report}
            onClick={() => void copy()}
          >
            {copied ? "Copied as Markdown" : "Copy to clipboard"}
          </button>
        </div>
        <small className="field-note">
          References are the ones each tool&apos;s authors ask to be cited, with their
          details taken from the DOI&apos;s registered metadata. Restyle them to your
          journal, and cite Ankora itself separately.
        </small>
      </section>
    </div>
  );
}

/**
 * The four shapes the generator emits, and nothing else.
 *
 * Built as elements rather than injected as HTML: the prose carries receptor
 * names and filenames that came from files someone else wrote, so there is no
 * path here for markup in a record to become markup on the screen.
 */
function renderMarkdown(markdown: string) {
  const blocks: ReactElement[] = [];
  const lines = markdown.split("\n");
  let paragraph: string[] = [];
  let table: string[] = [];
  let list: string[] = [];
  let ordered = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const text = paragraph.join(" ");
    blocks.push(
      <p key={`p${blocks.length}`} className={text.startsWith("*") ? "methods-aside" : undefined}>
        {text.replace(/^\*(.*)\*$/, "$1")}
      </p>,
    );
    paragraph = [];
  };

  const flushTable = () => {
    if (!table.length) return;
    const rows = table
      .filter((row) => !/^\|[\s|:-]+\|$/.test(row))
      .map((row) => row.split("|").slice(1, -1).map((cell) => cell.trim()));
    const [head, ...body] = rows;
    if (!head) {
      // Nothing but separators is not a table. Rendering the lines as text
      // keeps whatever the campaign recorded on screen; throwing here would
      // blank the whole workbench, since nothing above catches it.
      table.forEach((row) => paragraph.push(row));
      table = [];
      flushParagraph();
      return;
    }
    blocks.push(
      <table key={`t${blocks.length}`} className="methods-table">
        <thead><tr>{head.map((cell) => <th key={cell}>{cell}</th>)}</tr></thead>
        <tbody>
          {body.map((row) => (
            <tr key={row.join("|")}>{row.map((cell, index) => <td key={index}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>,
    );
    table = [];
  };

  // Lineage groups arrive as `- …` bullets and the reference list as `1. …`.
  // Without this they were folded into one paragraph, running every reference
  // together into a block no author could read or check.
  const flushList = () => {
    if (!list.length) return;
    const items = list.map((item, index) => <li key={index}>{item}</li>);
    blocks.push(
      ordered
        ? <ol key={`l${blocks.length}`} className="methods-list">{items}</ol>
        : <ul key={`l${blocks.length}`} className="methods-list">{items}</ul>,
    );
    list = [];
  };

  const flushAll = () => { flushTable(); flushList(); flushParagraph(); };

  for (const line of lines) {
    if (line.startsWith("|")) {
      flushList();
      flushParagraph();
      table.push(line);
      continue;
    }
    flushTable();
    const bullet = /^- (.*)$/.exec(line);
    const numbered = /^\d+\. (.*)$/.exec(line);
    if (bullet || numbered) {
      const wantsOrdered = numbered !== null;
      if (list.length && ordered !== wantsOrdered) flushList();
      flushParagraph();
      ordered = wantsOrdered;
      list.push((bullet ?? numbered)![1].trim());
      continue;
    }
    flushList();
    if (line.startsWith("## ")) {
      flushParagraph();
      blocks.push(<h3 key={`h${blocks.length}`}>{line.slice(3)}</h3>);
    } else if (line.trim() === "") {
      flushParagraph();
    } else {
      paragraph.push(line.trim());
    }
  }
  flushAll();
  return blocks;
}

/** True when the text reached the clipboard, so the button only claims what happened. */
async function copyText(value: string): Promise<boolean> {
  if (!value || !navigator.clipboard) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    // Clipboard access can be disabled in restricted WebViews.
    return false;
  }
}
