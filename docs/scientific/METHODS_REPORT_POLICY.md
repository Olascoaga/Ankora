# Methods report policy

- Status: accepted
- Date: 2026-09-06
- Scope: one recorded campaign, rendered as the Methods prose that campaign supports
- Implementation: `backend/src/ankora_backend/services/methods_report.py`
- Interface: Export workspace (M8), "Write the Methods section"

## Scientific meaning

A Methods section is the part of a paper a reader trusts to be literal. It is
the claim that these steps, with these parameters, produced these numbers. Every
other section may argue; this one only reports.

Ankora already holds that report. Which chains were kept, which residues were
repaired, at what pH, from which box, under which filter rules, with which
seeds — each decision was recorded as it was made, scattered across the
artifacts that made it. This renderer gathers that chain and writes it as prose.

It is a transcription, not a composition. The output is a draft the author must
read and take responsibility for, never text to paste unread. What the renderer
guarantees is narrower and more useful than fluency: that nothing in it was
invented.

## Three rules, in order of precedence

**1. Nothing is asserted that was not recorded.** A missing artifact becomes a
visible `[not recorded: …]` marker in the prose and an entry in `gaps`. It never
becomes a sentence that sounds verified. The output goes into a paper; an
obvious hole is better than a plausible invention, because a reader can see the
hole.

**2. A docking score is never described as an affinity**, and no sentence claims
a biological result. The section describes what was done. Interpretation is the
author's, and it belongs in another section.

**3. Reproducibility is stated only when exact repeats were compared.** Engine
identity and the presence of a seed are never treated as repeat evidence.

Rule 1 outranks the others because it is the one that fails silently. A score
described as an affinity is visible to any reviewer; a parameter quietly
invented to fill a sentence is not.

## Sections rendered

Seven, always in this order, each from the campaign's own records:

1. **Protein preparation** — source entry and resolution, chains retained, water
   action, components removed, side-chain repair, restrained relaxation with its
   measured maximum displacement, protonation pH and force field, PDBQT
   conversion.
2. **Binding site definition** — the box source (co-crystallized ligand, selected
   residues, manual coordinates, blind, or detected pocket), its padding, the
   centre and dimensions in the prepared receptor's frame, and the AutoGrid map
   spacing and interval counts when maps were used.
3. **Ligand preparation** — import counts and parse failures, the filter rules
   actually applied, structural-alert and duplicate policies with their match
   counts, the compound census, the embedding and minimization protocol, PDBQT
   conversion and charge model, and the chemical-state lineage of the prepared
   ligands.
4. **Molecular docking** — the engine, its version, the recorded executable
   SHA-256, the device, and the complete search protocol in that engine's own
   vocabulary.
5. **Results and reproducibility** — submitted, succeeded and failed counts, the
   ranking quantity named as what it is, and the reproducibility assessment.
6. **Software** — a table of every tool that acted, with the version that ran,
   the role it played, and the numbers of the references behind it.
7. **References** — the published works those tools' authors ask to be cited,
   numbered in the order the table introduces them.

The compound census names all three outcomes in one sentence and states that
they are mutually exclusive, so the numbers close on the page. Eligible plus
excluded does not equal the total; the compounds awaiting an explicit
chemical-state decision are the third bucket, and a reader who adds must not be
left with an unexplained remainder.

## Gaps

`gaps` is a list of what could not be stated. It is not a diagnostic log: each
entry corresponds to a `[not recorded: …]` marker the reader will meet in the
prose.

The interface must show the gaps **above** the text, not leave them to be found
by reading. A marker is easy to miss inside five paragraphs of otherwise
finished prose, and the whole protection is worthless if the author does not
notice it. When there are none, the interface must say so explicitly rather than
stay silent — silence reads the same either way.

A gap is never filled by inference from a sibling record, a default value, or
the way Ankora usually works.

## Explicit negatives

Absence of a step is a fact about the campaign, and it is reported as one.

Where the whole pipeline was recorded, the renderer still states what was *not*
done when the omission would otherwise be read as the standard practice:

> No pH-based ligand protonation enumeration was recorded.

> No ligand tautomer enumeration was recorded.

These sentences exist because of a specific failure. The receptor section states
a protonation pH; the ligand section, when nothing was enumerated, used to say
nothing at all. A reader who saw pH 7.4 for the receptor and an ordinary
preparation for the ligands would reasonably assume the ligands were ionized at
the same pH. Unless the scientist explicitly selected protonation or tautomer
microstates (ADR-016), they were not: each compound was docked in the state it
was imported or explicitly resolved with. The omission was asymmetric and it
flattered the work.

The lineage sentence that precedes them carries the positive case, naming the
enumerating tool, the pH, the candidate chosen out of how many, and the bounds
that produced them — and stating that the candidate order was unranked, because
neither Dimorphite-DL nor RDKit tautomer enumeration supplies a population
model that would justify reading the order as a preference.

A silence the reader will fill with the conventional answer is not neutral. Any
future step that a reader would assume by default must be reported when it did
not happen.

These are true statements about the campaign, not defects in the draft. An
author must not delete them to make the section read more conventionally.

## Reproducibility

Three states, and the difference between them is load-bearing:

- **Measured and reproducible** — exactly comparable recorded executions were
  compared and their parsed scientific outputs and retained pose-artifact bytes
  were identical.
- **Measured and variable** — the same comparison found at least two differing
  fingerprints. The reported values are stated to belong to that one recorded
  execution.
- **Not assessed** — no exact repeat exists for this combination of inputs,
  recorded tool identity and protocol. The prose says so, and adds that recorded
  seeds support an exact rerun request but do not establish that its outputs
  will match.

Both measured verdicts carry their evidence: the comparison protocol, the input
fingerprint, the scope compared, and every execution's catalog identity and
output fingerprint. A verdict without that evidence is not reportable.

The third state must never be collapsed into either of the others. "We did not
check" and "we checked and it varies" are different claims, and an engine's
documented behaviour is not a measurement of this campaign. Ankora previously
derived this flag from a per-engine constant; that constant was correct for the
engines it covered and would have silently mislabelled the first engine or
configuration it did not.

## Engines are never merged

A Vina score and an AutoDock4 binding energy are different quantities from
different scoring functions. The renderer names whichever applies and never
produces a combined value, a pooled ranking, or a sentence that compares the two
as if they shared a scale.

## References

Ankora supplies the reference each tool's authors ask to be cited, because it
already knows exactly which tools and versions acted.

Every entry in `tool_citations.py` was resolved against Crossref rather than
recalled: author list, journal, year, volume, issue and pages come from the
DOI's own registered metadata. This is not optional rigour. A fabricated
sentence is visible to a careful reader; a fabricated citation looks correct
until someone follows it, which makes it the more dangerous of the two.

Where a tool's authors ask for more than one paper, all are listed — AutoDock
Vina asks for both the 1.2.0 paper and the original. Method papers attach to the
tool that runs the method: the prose names ETKDGv3 and MMFF94s, so those
references appear alongside the RDKit software citation rather than being
folded into it.

A tool Ankora holds no verified reference for is **named as such**. It never
borrows a neighbour's citation. That absence is not a `gaps` entry: the
campaign's records are complete and it is Ankora's map that is short, and
conflating the two would tell the author to go looking through their own
records for something that was never there.

A software citation states no publication year, because the version that ran is
what identifies it and that already appears in the Software table.

## What the author must still do

Restyle the references to the target journal's convention, and cite Ankora
itself — the generated section says both.

The author must also resolve every gap from their own records, keep the explicit
negatives, and write the interpretation — what the numbers mean, whether the
result supports the claim, and what the limitations are. None of that is
transcription, and none of it is Ankora's to write.

## Acceptance criteria

- Every number in the output traces to a stored artifact of that campaign.
- No sentence describes a score as a measured affinity or a biological result.
- A missing artifact yields a marker in the prose and a matching `gaps` entry;
  it never yields a default, an inference, or an omission.
- A campaign with no missing artifacts reports an empty `gaps` list, and that
  claim is true of every section including ligand preparation — a section that
  renders nothing must not report itself complete.
- The compound census closes on the page.
- Reproducibility is reported in one of three states, and the measured ones
  carry their comparison evidence.
- Single-ligand and screening campaigns both render a complete ligand
  preparation lineage; neither returns early.
- The markdown is what reaches the clipboard, unaltered by the preview.
- Every reference rendered traces to a DOI whose registered metadata matches the
  fields printed; a tool without one is reported as having none.
- The engine is named from its record's key, never parsed out of a display
  label written for the interface.
