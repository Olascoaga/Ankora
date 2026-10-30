# Cross-platform diagnostic for the frozen primary Vina metrics — 2026-10-28

## Scope

This adds a separately named, strictly additive **diagnostic**:
`ankora_backend.validation.screening_benchmark_primary_metrics_diagnostic.diagnose_primary_metrics_manifest`.

It is not a verifier and gives no acceptance. The following are unchanged:

- `verify_primary_metrics_manifest`, its callers and defaults;
- `compute_primary_metrics`;
- every frozen manifest, hash, historical result, threshold and benchmark.

No existing test was edited, and the six strict reproduction tests that fail on
Linux still fail (see below). No docking or scientific run was started.

## Question it answers

When the strict exact recomputation fails on a host, the diagnostic asks:

- after the same identity and upstream-evidence checks, do the recomputed
  metrics differ from the frozen manifest **only** in BEDROC floating-point
  leaves, by at most a fixed amount?
- or is there any other exact discrepancy?

Its output always carries the statement: *diagnostic comparison only, not
strict verification, not acceptance and not evidence of scientific
equivalence; the cause of any difference is not established*.

## Behaviour

1. **Anchor.** The caller must supply the exact SHA-256 of the manifest's file
   bytes. A malformed anchor, or bytes that differ, is rejected. The anchor
   proves only that the bytes are the ones the caller chose. Trust in the
   result therefore depends on selecting that SHA-256 independently — for
   example, from a reviewed tracked record such as this note — and never by
   hashing the file being diagnosed.
2. **Strict parse and identity.** The manifest is parsed as UTF-8 JSON.
   `NaN`/`Infinity` and duplicate object keys are rejected. The schema version
   must match, and the content must match its own recorded `manifest_sha256`,
   using the same canonical digest as the strict module. Edited content that was
   not re-hashed is rejected.
3. **Upstream evidence.** The existing strict `verify_vina_campaign_manifest`
   checks the result and plan manifests, and its errors propagate unchanged.
   The manifest's two source identities must name that verified evidence.
4. **Recomputation.** The expected metrics come from the unchanged
   `compute_primary_metrics`. Non-finite numbers in either the recorded or the
   recomputed manifest are rejected.
5. **Comparison.** All fields except the top-level `manifest_sha256` are
   compared leaf by leaf.
   - **Rejected outright:** any type difference (`int`/`float`/`bool`/`str`
     are distinct), missing or extra fields, and list-length differences.
   - **Bounded BEDROC difference:** a float leaf whose absolute difference is at
     most the tolerance and whose path exactly matches one of these known schema
     paths, where `N` is a canonical non-negative index (`0` or no leading zero):
     - `estimate.targets[N].point.bedroc`;
     - `estimate.targets[N].intervals.bedroc.lower` and `.upper`;
     - `estimate.macro_point.bedroc`;
     - `estimate.macro_intervals.bedroc.lower` and `.upper`.

     Nothing else is eligible, including other containers below `estimate`
     (such as `estimate.other.bedroc` or `estimate.targets[0].extra.bedroc`),
     nested or misleading continuations, malformed or negative indices,
     `bedroc_alpha`, and anything outside `estimate`.
   - **Exact discrepancy:** every other value difference, including a BEDROC
     leaf beyond the tolerance.
   - The difference between the recorded and recomputed digests is reported as
     a consequence of these content differences, never as a separate pass.
6. **Classification:**
   - `identical`;
   - `bounded_bedroc_float_differences_only`;
   - `exact_discrepancy`.

   The result also records both digests, the file anchor, the tolerance and
   every difference.

## Tolerance (diagnostic, not scientific)

The tolerance is `DIAGNOSTIC_BEDROC_ABSOLUTE_TOLERANCE = 2**-52`
(`2.220446049250313e-16`), fixed and finite, and not a parameter.

- It is a **fixed absolute diagnostic bound**, not a fixed number of units in
  the last place (ULP). Floating-point spacing shrinks towards zero, so for
  small BEDROC values the same absolute bound spans many more ULP than for
  values near 1.
- The six Linux differences observed for the current frozen manifest were 1–4
  ULP of their own values, the largest `8.326672684688674e-17` (`3 * 2**-55`);
  the bound is about 2.7 times that. This observation applies only to those six
  entries, not to BEDROC values in general.
- It only marks small absolute differences at the exact BEDROC paths as
  "bounded", as distinct from any other difference.
- It is not an acceptance threshold, and it says nothing about scientific
  equivalence.

## Observed output on Linux (Ubuntu 24.04 WSL2, locked Python 3.12.13)

The diagnostic was run read-only against the frozen evidence, anchored on
manifest file SHA-256
`47397d0581dc40b355c0d773677b4743f11069ecdf6a70539af09585a5ccff44`:

```text
classification: bounded_bedroc_float_differences_only
recorded manifest_sha256:   30da8aebc3bc601204146416c51d3a17227229b96c3efd7b41087074d6e0f873
recomputed manifest_sha256: c0f0db22be537d2f7102008fdea98f6e7ad314a99caafbb776c40b219bd3310c
tolerance: 2.220446049250313e-16
estimate.macro_intervals.bedroc.lower      0.09259120965803064  0.09259120965803062  1.3877787807814457e-17
estimate.targets[0].intervals.bedroc.lower 0.09552549906105087  0.09552549906105082  5.551115123125783e-17
estimate.targets[0].intervals.bedroc.upper 0.21066492341943546  0.21066492341943538  8.326672684688674e-17
estimate.targets[0].point.bedroc           0.1502787046452803   0.15027870464528026  2.7755575615628914e-17
estimate.targets[1].intervals.bedroc.lower 0.055959500029785385 0.05595950002978537  1.3877787807814457e-17
estimate.targets[1].point.bedroc           0.1502587312674721   0.15025873126747208  2.7755575615628914e-17
exact discrepancies: ()
```

The columns are path, recorded, recomputed and absolute difference. This
reproduces the previously reported six differences and their maximum. All
other leaves were exactly equal.

**This is not a pass:** the strict verifier still fails on Linux, and the frozen
manifest remains the Windows-produced evidence.

## Cause: not established

In these six entries, every recomputed value is slightly smaller than the
recorded one, by 1 to 4 units in the last place of that value. That is
consistent with platform floating-point differences, for example in summation
order or the math library. The diagnostic did not test any such hypothesis, and
no cause is claimed. A Windows host running the same comparison is expected to
report `identical`; that is not demonstrated here.

## Tests

`backend/tests/test_screening_benchmark_primary_metrics_diagnostic.py` has 65
tests. Synthetic fixtures carry no scientific meaning. They cover:

- **Classification:** identical; an ULP-scale BEDROC difference reported while
  the unchanged strict verifier still raises "do not reproduce"; larger BEDROC
  differences, `bedroc_alpha`, a non-BEDROC float at the tolerance's magnitude,
  and a string change all reported as exact discrepancies.
- **Rejections:** wrong or malformed anchor; bytes changed after anchoring;
  tampering without a re-hash; NaN and ±Infinity, recorded or recomputed;
  `int`/`float`/`bool`/`str` type mismatches; extra or missing fields; list
  length; a mismatched source identity; duplicate keys; strict upstream failure
  propagating.
- **Path predicate (review follow-up):**
  - 6 tests accept exactly the six known schema paths, including a multi-digit
    target index.
  - 32 tests reject:
    - unknown containers (`estimate.other.bedroc`,
      `estimate.targets[0].extra.bedroc`);
    - nested or misleading continuations;
    - surrounding whitespace or prefixes;
    - malformed or negative indices (`[-1]`, `[01]`, `[+1]`, `[]`, `[a]`,
      `[1.0]`, `[0][1]`, `.0`);
    - `bedroc_alpha` and other fields.
  - One end-to-end test puts a misleading `estimate.other.bedroc` field, with
    the same structure, on both sides. An ULP-scale difference there is
    reported as an exact discrepancy, not a bounded one.
- **Constants:** a tolerance that is finite and fixed.
- **Real evidence:** one read-only test against the frozen manifest, with its
  independently recorded anchor. It checks that the input bytes are unchanged,
  that there are no exact discrepancies, and that every difference is a BEDROC
  leaf within the tolerance. It does not assert that Linux reproduces the
  manifest.

## Checks

- **Diagnostic tests plus the existing strict metric tests:** 68 passed in 16 s
  (65 diagnostic and 3 unchanged strict). The first commit had 30 (27 and 3).
- **Unchanged strict side:** `git diff` against `71c9038` is empty for
  `screening_benchmark_primary_metrics.py`, its tests, the protocol and
  sensitivity tests, and `docs/validation/reference_cases/`.
- **The six known strict tests,** still failing as before with "The primary
  metrics do not reproduce from the exact Vina result manifest":
  `test_screening_benchmark_protocol.py::test_primary_vina_metrics_reproduce_from_the_closed_campaign`
  and the five in `test_screening_benchmark_sensitivity_plan.py`. None is
  skipped.
- **`ruff check backend`:** passed. `ruff format --check` on the new files:
  passed.
- **Strict mypy** (`backend/pyproject.toml`, `src` plus the new test, locked
  environment): no issues in 143 files.

## Limitations

- A Linux diagnostic result of `bounded_bedroc_float_differences_only` does not
  close the numerical-portability gate, change any frozen evidence, or allow
  strict tests to be skipped.
- Only the six exact BEDROC schema paths are eligible. Any future difference
  elsewhere — EF, ROC-AUC, PR-AUC, counts, identities, or any new or renamed
  field — is an exact discrepancy by design.
- The fixed absolute bound is not a ULP bound. For BEDROC values much nearer
  zero than the current ones it would admit many more ULP; the 1–4 ULP
  observation describes only the current six entries.
- The result is only as trustworthy as the independently chosen SHA-256
  anchor.
- No Windows run of the diagnostic is recorded here.

## Independent Windows regression — 2026-10-28

The 65 diagnostic tests and three unchanged strict metric unit tests also
passed together on native Windows 11 with Python 3.12.13 from the existing
scientific environment. These tests ran against the integrated Linux-port
source, with an isolated test directory. This establishes that this focused
test set passes on both hosts; it does not imply bitwise parity of every
scientific calculation or a green hosted CI run.
