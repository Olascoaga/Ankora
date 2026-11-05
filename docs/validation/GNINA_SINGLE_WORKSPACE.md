# GNINA single-ligand workspace

On Linux, the docking experiment selector offers GNINA for one prepared ligand.
The interface sends an explicit CPU or CUDA selection and the recorded
`dense_1_3` CNN rescoring and PDBQT hydrogen policy to the backend. GNINA
version and executable identity are checked by the backend at launch. CUDA is
restricted to the validated single-device policy in ADR-027; unsupported device
configurations fail explicitly. No scientific executable is launched by the UI.

The live pose table preserves the order returned by GNINA: higher CNN score
first, not the lowest minimized affinity. CNN affinity and minimized affinity
are reported separately as predictions, not measured affinities. CNN affinity
is a predicted pK (higher indicates stronger predicted affinity), while the
minimized affinity is in kcal/mol. See the [GNINA maintainer's explanation](https://github.com/gnina/gnina/issues/259).
Selecting a
pose loads the backend's hash-verified PDBQT coordinates into the viewer; it
does not recompute or alter the artifact. The exact command and raw output are
visible. The UI remembers the last job identifier for the same selected inputs
in the local browser and reloads the durable project-scoped job when returning;
the backend remains the authority, and input identities are checked on reload.

## Verification and limits

Frontend tests use explicitly synthetic jobs: Linux-only availability, exact
CPU/CUDA request semantics, engine order even when energy order differs, pose
selection, input validation, cancellation, and matching-job restoration.
CPU/CUDA backend and API engineering evidence is recorded separately in
`LINUX_GNINA_API_CPU.md` and `LINUX_GNINA_API_CUDA.md`. This workspace is
single-ligand only. GNINA single-job results and their exact poses can also be
reopened from the project Results catalog. Exact GNINA poses can be analyzed with
ProLIF after checking the docking receptor, prepared ligand, conformer and pose
identities; CNN scores remain distinct from minimized affinity. A GNINA result
can also write the Methods section its own record supports; see
`GNINA_METHODS.md`. A completed GNINA job is accepted by the backend redocking
measurement; see `GNINA_REDOCKING.md`. A completed single job can be exported
with its preserved inputs, poses and recorded evidence; see `GNINA_EXPORT.md`.
Multi-ligand screening is not yet implemented; native Linux workstation
acceptance remains pending.
Browser storage may be cleared independently of the durable backend job record.
