# ADR-024: A complete scientific Windows installer

- Date: 2026-10-06
- Status: Accepted product requirement; implementation and clean-machine acceptance pending
- Supersedes: the end-user acquisition boundary of the September 2026
  installer/redistribution records, not their historical acceptance evidence

## Decision

Installing Ankora must make the supported scientific workflow ready to run.
End users must not install engines separately, install Python/Conda/Java, edit
PATH, set environment variables, or locate executables. Bundling only the
Python backend does not meet this requirement. The scientist explicitly
confirmed this boundary on 2026-10-06.

The full Windows installer must contain the supported engine payloads and
their runtime dependencies. A download wizard that asks the scientist to
acquire tools elsewhere is not a substitute. Scientific inputs fetched from
RCSB/AlphaFold are a separate, explicitly requested network operation.

Required payload:

- The frozen Python backend and the complete preparation, filtering,
  minimization, validation, interaction-analysis and figure-export runtime.
- AutoDock Vina 1.2.7, AutoGrid4/AutoDock4 4.2.6 and AutoDock-GPU 1.6, with
  their exact native runtime dependencies and required data files.
- P2Rank 2.5.1 with its models and a private compatible Java runtime.
- An embedded offline Evergreen WebView2 installer for machines lacking that
  runtime; existing compatible installations may be reused. Browser security
  updates remain Microsoft's responsibility, not a frozen browser fork.
- Applicable notices, license texts and corresponding-source material or
  other version-specific fulfillment required for each redistributed component.

These are currently supported scientific versions, not permission to update
engines or modify scientific defaults. GNINA remains deferred; completeness
means every supported capability, not an unimplemented new engine.

## Hardware and scientific boundaries

The package includes the AutoDock-GPU program, not a promise that every PC has
a compatible GPU. Ankora checks the device/runtime and makes CPU docking
available when GPU execution is unavailable. It must never silently reroute a
requested GPU calculation to another backend, change its protocol, or relabel
results. Switching backend requires an explicit user choice.

Do not silently install system GPU drivers, disable application-control or
antivirus policies, change system PATH, or require administrator permissions
for Ankora's own current-user installation. Clearly explain a device or OS
policy limitation in the UI; it must not prevent use of the CPU workflow.
Any unavoidable OS prerequisite prompt must be documented and tested.

## Implementation sequence and acceptance

1. **Freeze the complete payload.** Inventory exact upstream artifacts,
   versions, architecture, SHA-256, dependencies, models, license texts and
   source obligations. Review the complete dependency closure, not only each
   top-level project's license. Do not copy an arbitrary developer tools
   directory or claim redistribution compliance from an executable alone.
2. **Build and resolve private tools.** Acquire only pinned verified payloads
   during the build, stage them under versioned application resources, and
   resolve packaged executables without discovery on user PATH. Keep developer
   external-tool support separate. Record actual executed versions and hashes.
3. **Integrate complete packaging and readiness.** Update the legal inventory,
   package configuration, adapters (including private Java), startup health
   checks and installer tests together. The existing external-tool exclusion
   checks stay active until replaced by stricter allowlisted payload checks;
   deleting those safeguards alone is not implementation.
4. **Prove it on clean Windows.** With no development tools, no external
   scientific executables, no Java on PATH and network disconnected after
   downloading the full installer: install, prepare a supplied small reference
   receptor/ligand, detect a pocket, run Vina and AutoDock4, inspect interactions
   and save a figure/complex. Test GPU separately on compatible hardware and
   the visible unavailable-GPU path without it. Include paths with spaces and
   non-ASCII characters, standard-user installation, laptop display scaling,
   restart, upgrade and uninstall with scientific data preserved.
5. **Release gate.** Record artifact hashes, clean-machine results and the
   matching walkthrough/screenshots. Sign and verify the release artifacts
   through the existing release pipeline before a general community release.
   No release/tag publication or expert outreach is authorized by this ADR.

Each implementation unit requires focused tests, recorded evidence and a
bounded commit. No expensive scientific benchmark rerun is needed merely to
package unchanged tools; the clean-machine end-to-end smoke is still required.

## Current status and upstream starting points

The existing installer only satisfies the Python-backend subset. Its September
acceptance records remain accurate for that narrower artifact; it is not the
complete installer defined here. The user guide must identify this gap until
the new acceptance test passes.

Start the per-version review from the official sources, not a generic
open-source assumption: [Vina](https://vina.scripps.edu/license/),
[AutoDock4/AutoGrid](https://ccsb.scripps.edu/autodocksuite/autodock4/),
[AutoDock-GPU](https://github.com/ccsb-scripps/AutoDock-GPU),
[P2Rank](https://github.com/rdk/p2rank),
[Temurin](https://adoptium.net/temurin/releases/) and
[WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).
This decision is not a completed legal review of their redistribution terms.
