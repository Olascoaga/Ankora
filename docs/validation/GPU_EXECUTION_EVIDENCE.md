# AutoDock-GPU execution evidence and repeatability

## What is recorded

For new completed single-ligand jobs and terminal batch jobs, provenance stores
the runtime and device **reported by the actual tool output**, separately from
the device identified by the earlier preflight probe. The report records
whether both names match. If the output contains no unambiguous device report
or the names differ, a structured warning tells the scientist to inspect the
retained raw output. Matching text is evidence of what the process reported;
it is not independent proof of physical GPU usage. Results and logs are not
discarded automatically when the two reports disagree.

Missing and conflicting reports remain explicit rather than being replaced by
the probe's answer. Existing records and their original warning codes are not
rewritten. The established conservative `bitwise_reproducible: false` field
means no exact-repeatability guarantee; it is not a measurement of an
individual run.

## Repeatability warning

New jobs state that a seed alone does not establish repeatability. Six prior
Windows/OpenCL repeats are described as a historical example, not a measured
spread or guaranteed outcome for the current device, platform, or inputs.
Both single-ligand and screening interfaces use the same qualified language.
Exact-repeat evidence must come from the specific recorded executions.

## Checks and limits

The actual retained WSL CUDA output from the 1STP engineering smoke produced
`runtime=CUDA`, the reported RTX 5050 device, and a matching probe name. The
original output was read without rerunning the engine. Synthetic tests cover
matching, mismatched, missing and ambiguous output and both single/batch
provenance; the mismatch warning is preserved alongside results. Eighty-seven
focused GPU/schema/discovery tests passed on Linux and 53 GPU/schema tests
passed on Windows; 25 frontend docking-panel tests passed. Ruff, backend mypy
and frontend type checking passed.

Linux GPU discovery remains disabled. This unit does not certify a CUDA device,
compare CUDA against Windows/OpenCL, change historical results, package a
runtime, or substitute for an actual Ankora GPU service run or native Linux
workstation acceptance.
