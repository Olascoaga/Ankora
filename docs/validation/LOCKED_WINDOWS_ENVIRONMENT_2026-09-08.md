# Locked Windows scientific environment — 2026-09-08

## Risk closed

The accepted scientific workflows had been exercised in one named Conda
environment, but `environment.yml` specified only broad Python/PDBFixer inputs
and the backend used compatible version ranges. Recreating that environment at
a later date could therefore select different numerical, cheminformatics,
parser, API, or test packages while still appearing supported.

## Contract

Ankora now keeps three deliberately different artifacts:

1. `environment.yml` is the readable direct development specification and pins
   the validated Python, NumPy, SciPy, OpenMM, PDBFixer, and pip versions.
2. `environment/windows-64.conda.lock` is an `@EXPLICIT` win-64 lock of 36
   native packages. Every HTTPS channel artifact includes its channel-reported
   SHA-256.
3. `requirements/windows-py312.lock` contains 74 exact CPython 3.12 Windows
   wheel selections. Binary-only and hash-required modes are part of the file,
   and each requirement has exactly one selected-wheel SHA-256.

The input file `requirements/windows-py312.in` records direct requirements plus
the transitive constraints needed to preserve the environment that passed the
existing Windows validations. A dependency upgrade is therefore a visible lock
change that requires revalidation rather than an ambient package-resolution
event.

`scripts/verify_windows_environment_lock.py` fails closed when:

- a required file is absent;
- a Conda URL is not HTTPS or does not belong to one of the declared channels;
- any Conda package or Python wheel lacks a 64-character SHA-256;
- a pip input pin is missing or differs from the resolved lock;
- the readable environment and explicit lock disagree on load-bearing versions;
- any lock contains a `file:` reference, drive-qualified path, or UNC path; or
- `--runtime` finds the wrong OS, architecture, Python, environment ownership,
  missing package, or version drift.

`scripts/bootstrap-locked-windows.ps1` creates a new `ankora-locked`
environment by default. It refuses to mutate any existing environment, installs
the two external lock layers first, installs the local Ankora backend with
`--no-deps`, and then runs the complete runtime check.

## Recorded verification

On Windows 11 x86-64, the repository checker reported:

```text
Windows environment locks verified: 36 Conda packages, 74 Python packages.
```

The active `ankora-dev` environment matched CPython 3.12.13 and every locked
Python distribution after normalizing PDBFixer's Conda version `1.12` to its
Python metadata version `1.12.0`. Four contract tests cover the accepted files,
a damaged Conda hash, an unhashed wheel, and a machine-local path.
The bootstrap was also invoked against the already-existing `ankora-dev` name;
it exited before any create/install command and reported that locked
environments are not mutated.

This unit locks the environment inputs only. Native executable smokes,
installer/runtime composition, third-party redistribution review, and signing
remain separate Gate E units so none can be implied by a successful dependency
lock check.
