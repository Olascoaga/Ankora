# Illustrated user-guide review - 2026-10-06

## Scope and verdict

Reviewed the pending Markdown guide, PDF builder and screenshots against
current source code, the accepted installer records and the frozen
`reference_cases/SERPINE1_7AQF_RV2.md` evidence matrix. The guide is a reviewed
**draft**, not a completed fresh-installation acceptance test.

The scientist requires a full scientific installer: ADR-024 records this
accepted product boundary and its implementation/acceptance sequence. The
September backend-only installer remains historical evidence, not fulfillment
of the new requirement. No installer, engine payload, signing artifact or
scientific output was built or changed by this documentation unit.

## Corrections

- Removed the claim that the current installer already includes independent
  engines; separated the required complete experience from the existing
  candidate. Removed instructions to bypass Windows security warnings.
- Distinguished neutral RV2 in the historical CPU run from anionic RV2 in
  the Vina/GPU runs. Those results are not a matched-input engine comparison
  or a promise that a new walkthrough reproduces every number.
- Added explicit residue/protonation review, corrected restrained-coordinate
  movement and AutoGrid interval/node terminology, and removed an unsupported
  aligned-RMSD numerical comparison.
- Made reproducibility statements case-specific and retained the absent
  Vina RMSD verdict as an explicit gap.
- Corrected Results access to Methods for single-ligand jobs, separated
  vector 2D export from raster 3D export, and limited bundle-content claims
  to what the export service writes.
- Identified the Methods screenshots as an illustrative library campaign,
  not the RV2 single-ligand protocol. Normalized figure numbering/captions.
- Excluded one Export screenshot containing personal filesystem paths; the
  seven remaining images were visually inspected. Private originals and QA
  renders are not publication inputs.

## PDF build checks

- Browser discovery uses PATH/environment-based installation locations, not
  hardcoded absolute machine roots. A disposable isolated browser profile
  avoids reusing the scientist's browsing session.
- Headings now have targets for the guide's contents links. Missing/outside
  documentation images are rejected before printing.
- PDF generation stages a complete candidate and atomically replaces the
  previous file only on success. Process failure, timeout, incomplete output
  and locked destinations retain the old artifact. A transient viewer lock
  is retried within a bounded deadline.
- Eleven focused tests cover these behaviors, including real-guide contents
  links, escaped markup, duplicate headings, browser discovery and successful
  replacement. Synthetic PDF fixtures contain no scientific claims.
- The real Edge-generated output has 15 A4 pages. All pages were rendered and
  visually reviewed; seven captions and six pending-figure notices are
  present. Extracted text contains no personal/absolute filesystem paths;
  the 15 PDF link annotations contain no local `file:` destinations. The
  seven embedded source screenshots were checked separately, since text
  extraction cannot establish that an image is sanitized.

## Verification limits

The 11 documentation-build regressions and focused Ruff check pass. TypeScript
and both public-path/validation-status checks pass. The frontend rerun has
246 passing tests and one existing long M2 integration test exceeding the
default 5-second test budget; it also times out with one/two workers. Its
isolated file passes all seven tests when invoked with a diagnostic 15-second
budget (the M2 test took 4.973 seconds in that run). No assertions, project
timeout or frontend code were changed. This is recorded timing sensitivity,
not a claim that the default full frontend gate passed. The previous UI units
retain their separately recorded acceptance evidence; remote CI must assess
the published tree independently.

## Still required before expert/community distribution

1. Complete ADR-024 payload, private discovery and redistribution review.
2. Run the full installed workflow on clean Windows without external tools;
   record the exact candidate and its scientific/runtime versions.
3. Capture the six missing figures from that walkthrough and recheck labels,
   timing and output interpretation against its own retained records.
4. Complete signing/release checks and a bounded usability pilot. The guide
   and existing screenshots are not evidence that those gates have passed.

No user projects were modified and no archived experiment was restored or
rerun to fill a documentation gap.
