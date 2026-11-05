# Linux GNINA redocking integration check

The predeclared `scripts/validate_linux_gnina_redocking.py` copies the previously
recorded WSL CUDA job into an isolated project. It verifies selection of the
matching original crystallographic ligand, pose hashes, native CNN rank and
score axes; compares API RMSDs with direct in-place calculations using Ankora's
same RMSD adapter; reopens the validation; and checks the source remains intact.
No docking is rerun. This is one-case integration evidence using the same
algorithm on both sides, not an independent scientific benchmark, proof of
predictive performance, or native Linux workstation acceptance.
