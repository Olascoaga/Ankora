# Distinguishable campaign bundles — 2026-09-07

## Problem

Repeated exports of the same recorded campaign could appear identical outside
Ankora. Their human title, minute-resolution timestamp, folder contents, and
fixed `campaign_bundle.zip` filename did not expose which campaign, inputs, or
export event a scientist was handling. The internal UUID prevented overwrites
but did not make two manuscript-side bundles distinguishable.

## Accepted boundary

New campaign manifests use export format 3 and record three separate identities:

- `catalog_id` identifies the immutable source campaign.
- `input_identity_sha256` is a canonical SHA-256 over the exact receptor,
  receptor artifact, binding site/search box, map set, library/filter run, and
  selection manifest identities recorded by that campaign.
- `bundle_identity_sha256` is a canonical SHA-256 over the export protocol,
  export UUID, exact UTC timestamp, campaign identity, optional display name,
  and input identity.

An optional scientist-assigned display name is presentation metadata only. It
does not rename, mutate, or become evidence inside the source campaign. Empty,
control-character, or overlong names are rejected before an export record is
created.

The external folder and portable archive include a readable campaign label,
source identity, short input hash, second-resolution timestamp, and short
bundle hash. Full identities remain in `manifest.json` and `README.txt`; short
hashes are navigation aids rather than substitutes for the full values.

## Compatibility and safety

- Historical format-2 manifests remain catalog-readable.
- Historical `campaign_bundle.zip` files remain downloadable.
- A format-3 archive is served only when its plain `.zip` filename is recorded
  inside the bundle manifest; path components are rejected.
- Export still copies existing scientific records and figures. It does not run
  a docking engine, interaction detector, or renderer.

## Verification

- Directed backend coverage proves format-3 identity, repeated-export
  distinction, optional-name normalization, rejection before record creation,
  unique external names, dynamic archive serving, and format-2 compatibility.
- Directed frontend coverage proves the optional name reaches the API and that
  campaign/input/bundle identities, second-resolution time, and the unique ZIP
  are visible in both the export result and catalog.
- The authoritative gate passes 498 backend tests, Ruff, strict mypy over 116
  source files, 235 frontend tests over 33 files, strict TypeScript, the
  production web build, Rust formatting/Clippy/unit/doc tests, the optimized
  native Windows build, and the public-path check.
