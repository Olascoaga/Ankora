# Linux GNINA redocking integration check

The predeclared `scripts/validate_linux_gnina_redocking.py` copies the previously
recorded WSL CUDA job into an isolated project. It verifies selection of the
matching original crystallographic ligand, pose hashes, native CNN rank and
score axes; compares API RMSDs with direct in-place calculations using Ankora's
same RMSD adapter; reopens the validation; and checks the source remains intact.
No docking is rerun. This is one-case integration evidence using the same
algorithm on both sides, not an independent scientific benchmark, proof of
predictive performance, or native Linux workstation acceptance.

The check completed against the previously recorded 1HSG/MK1 GNINA 1.3.3 CUDA
job (exhaustiveness 1, two modes), with a 2 Å threshold. The first-ranked pose
measured 3.685 Å and the second 0.938 Å: sampling recovered this reference, while
ranking did not put the recovering pose first. The original project and evidence
remained unchanged. This single low-exhaustiveness engineering run does not
establish performance across targets or protocols. SHA-256 of the private
evidence record:
`7696efa2f3aa405d3991fd241f4dcb206a0bd5afbf23ec129162addbe70bdfea`.
