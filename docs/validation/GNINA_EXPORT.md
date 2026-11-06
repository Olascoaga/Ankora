# GNINA single-job portable export

A completed Linux GNINA job can be exported from Results or Export as a CSV,
manifest, Methods report and ZIP. Each CSV row is one pose in the engine's
recorded CNN order. Dimensionless CNNscore, predicted CNNaffinity in pK and
minimized affinity in kcal/mol remain separate; these are not measured affinity.
The export does not imply a virtual-screening campaign or assessed repeatability.

The ZIP carries the recorded receptor, prepared ligand, conformer, original raw
poses, each published pose, execution output, job record, and matching recorded
interaction analyses, figures and redocking validations where available. A
matching crystallographic reference is included only if its recorded identity,
size and SHA-256 verify; an unavailable or altered reference produces an explicit
manifest warning. Required source artifacts and execution logs must match the
record or export fails. Raw pose content is checked against the recorded pose
data. A digest calculated at export time is identified as such; it does not
establish a historical hash. Raw logs and command records may contain local
paths and should be reviewed before sharing.

Synthetic regression tests cover source integrity and the distinction between
the score axes. Two predeclared checks used an existing 1HSG/MK1 WSL CUDA job
and preserved evidence without rerunning the docking. The original check and
the subsequent crystallographic-reference check are documented separately in
`LINUX_GNINA_EXPORT.md` and `LINUX_GNINA_EXPORT_REFERENCE.md`. These checks do
not establish scientific performance or acceptance on a native Linux workstation.
