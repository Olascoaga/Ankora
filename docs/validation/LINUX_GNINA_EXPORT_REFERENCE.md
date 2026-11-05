# GNINA exported redocking reference check

The predeclared `scripts/validate_linux_gnina_export_reference.py` reruns the
isolated portable-export integration check with a distinct output directory.
In addition to the inputs, poses, raw output and associated analysis records,
it requires the crystallographic reference from the saved redocking validation
to occur byte-for-byte in the archive, with the same recorded SHA-256. This is
an engineering check using preserved WSL evidence, not a new docking run or a
claim of scientific validation across systems.

The check completed against the retained WSL CUDA case; the evidence SHA-256 is
`eeba2d1dfcd99d540edf0534a84fa83370828c91d856a0bc03c57d8cc036eea1`.
The archive included the original crystallographic reference byte-for-byte.
