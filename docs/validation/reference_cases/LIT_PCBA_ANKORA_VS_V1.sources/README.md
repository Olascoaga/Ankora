# Frozen microstate source evidence

These are byte-for-byte Git blobs from commit
`56a1b918a72aa3551e82e46ccc23583bca8091fe` (2026-09-03), not active modules or
copies to keep synchronized. The already-published sensitivity plan binds their
exact sizes and SHA-256 hashes. They allow its historical verification in a
shallow clone even after unrelated runtime fixes change the working source.

- `ligands.py.txt`: original `backend/src/ankora_backend/schemas/ligands.py`,
  24,761 bytes, SHA-256 `abfae450688932b4de2aa34908bb0d0b78b1ef7ea3f31ef7dae4e4a190457ad9`.
- `ligand_microstates.py.txt`: original `backend/src/ankora_backend/services/ligand_microstates.py`,
  12,213 bytes, SHA-256 `2afc7a5a12214b4a6e879c947670835515e01dc475afcaa567987dd490088f1e`.

Adding this source evidence changes no plan, score, metric, seed, molecular
choice or validation conclusion. Verification of a historical plan is not
authorization to run a future sensitivity campaign with changed code: its
executor must bind the implementation actually used and refuse identity drift.
