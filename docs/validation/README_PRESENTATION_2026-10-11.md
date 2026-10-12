# Private-beta README presentation — 11 October 2026

## Scope

Documentation-only refresh: README, native SVG header, relocated development
instructions and presentation regressions. No scientific implementation,
dependencies, original project records, manual PDF or installer changes.

## Presentation and accuracy

- Reuse the verified manual's `guide11-interactions.jpg`,
  `guide03-receptor.jpg` and `guide06-binding-site.jpg`. These are real 7AQF/RV2
  views, not mockups or new scientific calculations. Captions distinguish
  contact geometry from affinity and link to full-resolution images.
- Use the current molecular mark and graphite/mineral-green/cyan identity
  in a self-contained accessible SVG. No external SVG resources or scripts.
- Use a live Windows CI badge, plus explicitly labeled private-beta,
  Windows 11 x64 and MIT badges. No static passing claim, public-release
  download button, fabricated download count or unsupported-platform badge.
- Correct the stale source-development statement that engines are not
  redistributed: the complete private beta bundles reviewed tools; source
  contributors configure them separately. Preserve detailed development,
  environment-lock, native-smoke, packaging and signing instructions in
  `docs/DEVELOPMENT.md`.
- Keep the generated public validation block unchanged. State unsigned-beta,
  release-acceptance, optional GPU-driver, redocking-review and scoring limits.

## Verification

- 25 documentation tests pass: seven README presentation cases, four public
  validation-status checks and fourteen illustrated-guide/PDF regressions.
- Ruff passes for the new test module. The public validation index remains
  synchronized: two frozen cases, one completed independent case.
- Local GitHub-flavored Markdown preview rendered in isolated headless Edge
  at 1280, 768 and 390 CSS pixels. All four local images and all four remote
  badges loaded at each size; no document-level horizontal overflow.
  Wide/narrow header and gallery captures were visually inspected.
- Badge endpoints returned SVG successfully. Read-only GitHub API inspection
  found no public release; the README therefore directs invited testers to
  their beta distribution channel rather than inventing a release download.
- The latest public Windows CI run, `38183052706` at commit `67eb30d`,
  completed with failure in **Run backend tests**. The live badge reflects
  this state; passing focused documentation tests is not a claim that the
  full CI is passing. CI remediation is outside this presentation unit.
- Existing guide PDF SHA-256 remains
  `a1065e0feb4de038e5d9de462a52d63e4b25b943a746bfb1c8eb1838793ae24e`.

Local preview artifacts remain under ignored `build/user-guide-readme-qa/`.
The preview approximates GitHub's Markdown styling; it is not a claim of
pixel-identical GitHub rendering. No application services or scientific jobs
were started. Full scientific/runtime/installer acceptance was not rerun for
this documentation-only unit.
