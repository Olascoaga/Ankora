# GNINA CUDA API engineering check

## Predeclared protocol

Copy the previously prepared 1HSG/MK1 project to a new isolated directory and
verify declared executable and input hashes. Through Ankora's real in-process
HTTP API, explicitly request GNINA CUDA device 0 with two CPU threads, seed
20261029, exhaustiveness 1 and two poses. Start only when no unrelated GPU
compute process is active. Require a completed job, an observed GPU process
whose UUID matches the independently enumerated unambiguous device, successful
topology validation, pose retrieval and recorded hash verification. Check that
resources are released and original inputs are unchanged. Preserve failures as
evidence. This is a bounded WSL engineering check, not GUI or native workstation
acceptance and not a scientific benchmark.

## Observed run: api-cuda-01

The isolated WSL API job completed with a matching requested and observed GPU
UUID. Its topology-checked poses were retrieved through the API and matched
their recorded hashes. The original inputs remained unchanged and resources
were released. Evidence SHA-256:
`9723f62c4e1b1dd968c14bb65ebea88e548d6d0097f4cf2a65029339f1e9fd9c`.
This does not establish GUI, native workstation or general scientific validity.
