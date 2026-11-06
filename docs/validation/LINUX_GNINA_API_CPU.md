# GNINA CPU API engineering check

## Predeclared protocol

Copy the previously prepared 1HSG/MK1 exploratory project into a new isolated
directory, verify the recorded GNINA binary and input hashes, and leave the
source project unchanged. Through Ankora's real in-process HTTP API, explicitly
request a CPU GNINA job with two threads, seed 20261029, exhaustiveness 1 and
two poses. Poll the typed job endpoint; retrieve every published pose through
the API and compare its bytes with the recorded SHA-256. Require successful
completion, recorded execution and released resources. Save failure evidence
as-is. This is an engineering smoke on WSL, not GUI, scientific validation,
CUDA API validation, or native workstation acceptance.

## Observed run: api-cpu-01

The isolated WSL run completed through the real HTTP API. Every returned pose
was retrieved through its content endpoint and its bytes matched the recorded
SHA-256. Original project files remained unchanged and resources were released.
Evidence SHA-256:
`6f5837cc7777bbe92a146572e23ebeaf5f024a455357eb5eb67447f4fe094335`.
This result does not establish GUI, CUDA API, native workstation or general
scientific validity.
