# Windows release artifact contract

Date: 2026-09-10

## Scope

This record closes the release-artifact portion of the Windows packaging gate.
It covers how Ankora assembles, indexes, verifies, attests, signs, and publishes
the already implemented self-contained NSIS installer. It does not claim that
two independent builds are bit-for-bit identical.

## Artifact set

`scripts/prepare_windows_release.py prepare` creates a new output directory and
refuses to reuse one. The directory contains exactly:

- `Ankora_<version>_x64-setup.exe`;
- Ankora's license, source-availability statement, third-party inventory, and
  consolidated third-party notices;
- `release-manifest.json`, recording the Git commit and tree, version/tag
  relationship, immutable-input hashes, file sizes and hashes, and observed
  Authenticode signer/timestamp evidence;
- `SHA256SUMS`, indexing the installer, legal files, and manifest.

The manifest contains repository-relative names only. It deliberately omits a
generation timestamp and machine path so the same source identity and artifact
bytes produce the same evidence. The index does not hash itself.

`scripts/prepare_windows_release.py verify` independently enforces the exact
file set and hashes, cross-checks every manifest artifact entry, and asks
Windows for the current Authenticode evidence again. Unknown or invalid
signature states are rejected. `--require-signed` additionally requires a
matching version tag, a `Valid` signer certificate, and a timestamp certificate.

## Signing boundary

The build script accepts a certificate thumbprint and HTTPS timestamp URL only
as a pair. It gives these to Tauri during the build so both the application and
installer follow Tauri's Windows signing path; it never modifies the installer
after checksum generation.

The manual `Windows release` workflow reads a PFX only from the protected
`windows-release` GitHub environment:

- `WINDOWS_CERTIFICATE_BASE64`
- `WINDOWS_CERTIFICATE_PASSWORD`
- `WINDOWS_TIMESTAMP_URL`

All three must be present. The PFX is decoded only below the ephemeral runner
temporary directory, imported into the current user's certificate store, and
deleted before the build step. The password and PFX never become build
arguments or repository files. Ankora does not provide or invent a signing
identity; the repository owner controls the certificate and secrets.

When no identity is configured, the workflow explicitly creates an unsigned
candidate. It may be downloaded and checksum/attestation verified, but setting
`publish_release=true` causes the run to fail. An unsigned candidate must never
be presented as an Ankora public release.

## Publication boundary

The workflow is manual only. The requested `v<version>` tag must already exist
and point to the checked-out commit. Publication never creates, moves, or
rewrites a tag and never rebuilds or regenerates files after signing.

Every action used by the release workflow is pinned to a full commit SHA. The
workflow gives the build job only read/attestation permissions, indexes every
artifact through `SHA256SUMS`, creates GitHub artifact attestations from that
index, and uploads the exact verified directory. The separate publication job
downloads and verifies the signed set again, creates a draft release with all
assets attached, then publishes it. It refuses to replace an existing release.

Before the first public release, enable GitHub's immutable-releases repository
setting. This administrative setting is intentionally not mutated by the
workflow.

## Local verification

The release assembler has synthetic-fixture tests for deterministic evidence,
path privacy, tamper detection, unsigned-publication rejection, and the manual,
SHA-pinned workflow contract. A local candidate also exercises Windows'
Authenticode inspection against the real installer built in the preceding
packaging unit. Its checksum is evidence for those exact bytes, not proof of an
independent bit-identical rebuild.

The accepted local candidate assembled from packaging commit
`2c86df415abdc076e2db31199afe125e1366a5cd` passed prepare and independent
verify on Windows. Its evidence recorded:

- installer size: 103,492,506 bytes;
- installer SHA-256:
  `cc7a2feba3ee2d3a75bbc4b6cb29d1f0053451482c58d934d862d0455066b283`;
- release-manifest SHA-256:
  `769e8ce802dbc732b07e7e93de9c0c30e972a6944c0384af8c0619569f67da2e`;
- Authenticode status: `NotSigned`;
- tag verified: false; publication ready: false.

That final state is intentional: no user-controlled signing certificate or
release tag was configured for this local acceptance run. It proves the
unsigned-candidate path and does not authorize publication.

The repository-wide acceptance gate then passed with 515 backend tests, Ruff,
strict mypy over 118 source files, 245 frontend tests in 34 files, TypeScript,
the production web build, Rust formatting, Clippy, native tests, and the
release-mode Tauri application build.

## Primary references

- Tauri Windows code signing:
  https://v2.tauri.app/distribute/sign/windows/
- Tauri GitHub Actions pipeline guidance:
  https://v2.tauri.app/distribute/pipelines/github/
- GitHub artifact attestations:
  https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- GitHub immutable releases:
  https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases
