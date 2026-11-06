# Native-smoke evidence writer: fixture identity across hosts — 2026-10-28

## Problem

`test_native_tool_smoke.py::test_evidence_writer_preserves_raw_output_commands_and_fixture_hashes`
wrote its synthetic fixture with `write_text("…\n")` and expected the SHA-256
`d853…`. On Windows, text mode writes CRLF, so the file contains
`b"explicitly synthetic fixture\r\n"`. Linux writes LF and correctly produces a
different digest (`1acc…`). The failure came from the test fixture depending on
the platform; the writer was not at fault.

## Change (test only)

The test now supplies two explicitly synthetic, exact byte fixtures through
`write_bytes`: an LF fixture and a CRLF fixture. Each manifest entry must equal
`hashlib.sha256` of the bytes actually supplied, its `size_bytes`, and the
unchanged file bytes.

The CRLF digest must still equal the historical Windows constant `d853…`, and
the LF digest must differ from it. Line endings are therefore part of the
identity, not normalized away.

Captured stdout and stderr are now compared as exact bytes (`b"…\n"`) rather
than through decoded text. `EvidenceWriter` and the production evidence
contract are unchanged.

## Checks (Ubuntu 24.04 WSL2, Python 3.12.3, this checkout's `backend/src`)

- `pytest backend/tests/test_native_tool_smoke.py`: 3 passed.
- `ruff check` and `ruff format --check` on the test: passed.

No tool or scientific smoke was executed; the fixtures are synthetic contract
data. The Windows run of this test is not re-executed here.
