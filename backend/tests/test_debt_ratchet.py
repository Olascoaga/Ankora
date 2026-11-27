"""Dual-OS CI anti-regression technical-debt ratchet (D10).

Enforces the monotonic ceilings recorded in ``environment/debt-ratchet.json``
using only Python 3.12 stdlib (AST/regex/hashlib) plus the already-locked
``ruff`` CLI invoked via ``sys.executable -m ruff`` so the gate runs
identically on Windows (``verify``) and Linux (``verify-linux``) with zero
extra dependencies.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RATCHET_PATH = REPO_ROOT / "environment" / "debt-ratchet.json"
BACKEND_SRC = REPO_ROOT / "backend" / "src"
SCRIPTS_DIR = REPO_ROOT / "scripts"
TS_SRC = REPO_ROOT / "apps" / "desktop" / "src"
RUST_SRC = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "src"

_TS_ANY_RE = re.compile(r"\b(?:as\s+any|:\s*any\b|<any>)")
_TS_EMPTY_CATCH_RE = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*(?://[^\n]*)?\}")
_RUST_UNSAFE_RE = re.compile(r"\bunsafe\b")


def _load_ratchet() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RATCHET_PATH.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1
    return data


def _iter_py_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def _cyclomatic_complexity(node: ast.AST) -> int:
    cc = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.IfExp,
                ast.Assert,
            ),
        ):
            cc += 1
        elif isinstance(child, ast.BoolOp):
            cc += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            cc += 1 + len(child.ifs)
        elif hasattr(ast, "MatchCase") and isinstance(child, ast.match_case):
            cc += 1
    return cc


def _is_broad_or_bare_except(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name) and handler.type.id in {
        "Exception",
        "BaseException",
    }:
        return True
    if isinstance(handler.type, ast.Tuple):
        return any(
            isinstance(elt, ast.Name) and elt.id in {"Exception", "BaseException"}
            for elt in handler.type.elts
        )
    return False


def _run_ruff_json(target: Path, select_rules: list[str]) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--select",
            ",".join(select_rules),
            "--output-format",
            "json",
            str(target),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in (0, 1), (
        f"ruff failed unexpectedly (exit {proc.returncode}): {proc.stderr}"
    )
    parsed: list[dict[str, Any]] = json.loads(proc.stdout or "[]")
    return parsed


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def test_frozen_scientific_adapter_invariants() -> None:
    """Frozen baseline adapters (e.g., vina.py) must remain byte-for-byte intact."""
    ratchet = _load_ratchet()
    for name, spec in ratchet["frozen_invariants"].items():
        target = REPO_ROOT / spec["path"]
        assert target.is_file(), f"Frozen invariant {name} missing at {spec['path']}"
        actual_sha = sha256(target.read_bytes()).hexdigest()
        assert actual_sha == spec["sha256"], (
            f"Frozen invariant {name} ({spec['path']}) changed: "
            f"expected {spec['sha256']}, got {actual_sha}"
        )


def test_backend_src_ruff_debt_ratchet() -> None:
    """Ruff zero-tolerance and capped rules in backend/src must not regress."""
    ratchet = _load_ratchet()["backend_src"]
    zero_rules: dict[str, int] = ratchet["ruff_zero_rules"]
    capped_rules: dict[str, int] = ratchet["ruff_capped_rules"]

    # Include B009 and S608 alongside BLE001 so RUF100 validates active noqa
    # directives against the exact rules they suppress.
    all_rules = sorted({*zero_rules, *capped_rules, "B009", "S608"})
    diagnostics = _run_ruff_json(BACKEND_SRC, all_rules)
    counts = Counter(str(item.get("code", "")) for item in diagnostics)

    failures: list[str] = []
    for code, ceiling in {**zero_rules, **capped_rules}.items():
        observed = counts.get(code, 0)
        if observed > ceiling:
            samples = [
                f"{_rel(Path(item['filename']))}:{item['location']['row']}"
                for item in diagnostics
                if item.get("code") == code
            ][:8]
            failures.append(
                f"{code}: observed {observed} > ceiling {ceiling} (samples: {', '.join(samples)})"
            )
    assert not failures, "backend/src ruff debt ratchet exceeded:\n" + "\n".join(failures)


def test_backend_src_ast_and_suppression_debt_ratchet() -> None:
    """Broad excepts, # type: ignore, and extreme function size/complexity must not grow."""
    ratchet = _load_ratchet()["backend_src"]

    type_ignore_sites: list[str] = []
    broad_except_sites: list[str] = []
    gt_300_sites: list[str] = []
    ge_400_sites: list[str] = []
    cc_ge_50_sites: list[str] = []
    cc_ge_100_sites: list[str] = []

    for path in _iter_py_files(BACKEND_SRC):
        rel = _rel(path)
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "# type: ignore" in line:
                type_ignore_sites.append(f"{rel}:{lineno}")

        tree = ast.parse(text, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_broad_or_bare_except(node):
                broad_except_sites.append(f"{rel}:{node.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno:
                length = node.end_lineno - node.lineno + 1
                if length > 300:
                    gt_300_sites.append(f"{rel}:{node.lineno} {node.name} ({length}L)")
                if length >= 400:
                    ge_400_sites.append(f"{rel}:{node.lineno} {node.name} ({length}L)")
                cc = _cyclomatic_complexity(node)
                if cc >= 50:
                    cc_ge_50_sites.append(f"{rel}:{node.lineno} {node.name} (CC={cc})")
                if cc >= 100:
                    cc_ge_100_sites.append(f"{rel}:{node.lineno} {node.name} (CC={cc})")

    checks = [
        ("max_type_ignore", type_ignore_sites),
        ("max_broad_or_bare_except", broad_except_sites),
        ("max_functions_gt_300_lines", gt_300_sites),
        ("max_functions_ge_400_lines", ge_400_sites),
        ("max_functions_cc_ge_50", cc_ge_50_sites),
        ("max_functions_cc_ge_100", cc_ge_100_sites),
    ]
    failures = [
        f"{key}: observed {len(sites)} > ceiling {ratchet[key]} ({', '.join(sites[:8])})"
        for key, sites in checks
        if len(sites) > ratchet[key]
    ]
    assert not failures, "backend/src AST debt ratchet exceeded:\n" + "\n".join(failures)


def test_scripts_ruff_debt_ratchet() -> None:
    """High-signal hygiene rules in scripts/ must remain at zero."""
    zero_rules: dict[str, int] = _load_ratchet()["scripts"]["ruff_zero_rules"]
    diagnostics = _run_ruff_json(SCRIPTS_DIR, sorted(zero_rules))
    counts = Counter(str(item.get("code", "")) for item in diagnostics)

    failures: list[str] = []
    for code, ceiling in zero_rules.items():
        observed = counts.get(code, 0)
        if observed > ceiling:
            samples = [
                f"{_rel(Path(item['filename']))}:{item['location']['row']}"
                for item in diagnostics
                if item.get("code") == code
            ][:8]
            failures.append(
                f"{code}: observed {observed} > ceiling {ceiling} (samples: {', '.join(samples)})"
            )
    assert not failures, "scripts/ ruff debt ratchet exceeded:\n" + "\n".join(failures)


def test_typescript_frontend_debt_ratchet() -> None:
    """Non-test desktop TS/TSX must keep zero any escapes, suppressions, and empty catches."""
    ratchet = _load_ratchet()["typescript_frontend"]
    any_sites: list[str] = []
    suppression_sites: list[str] = []
    empty_catch_sites: list[str] = []

    for path in sorted(TS_SRC.rglob("*")):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        rel_from_ts = path.relative_to(TS_SRC)
        if "tests" in rel_from_ts.parts or path.name.endswith((".test.ts", ".test.tsx")):
            continue
        rel = _rel(path)
        text = path.read_text(encoding="utf-8")
        for match in _TS_EMPTY_CATCH_RE.finditer(text):
            lineno = text[: match.start()].count("\n") + 1
            empty_catch_sites.append(f"{rel}:{lineno}")
        for lineno, line in enumerate(text.splitlines(), start=1):
            code_part = line.split("//", 1)[0]
            if _TS_ANY_RE.search(code_part):
                any_sites.append(f"{rel}:{lineno}")
            if "@ts-ignore" in line or "@ts-expect-error" in line or "eslint-disable" in line:
                suppression_sites.append(f"{rel}:{lineno}")

    checks = [
        ("max_any_escapes", any_sites),
        ("max_suppressions", suppression_sites),
        ("max_empty_catch_blocks", empty_catch_sites),
    ]
    failures = [
        f"{key}: observed {len(sites)} > ceiling {ratchet[key]} ({', '.join(sites[:8])})"
        for key, sites in checks
        if len(sites) > ratchet[key]
    ]
    assert not failures, "TypeScript debt ratchet exceeded:\n" + "\n".join(failures)


def test_rust_shell_debt_ratchet() -> None:
    """Non-test Rust/Tauri shell code must keep zero unwrap(), expect(), and unsafe."""
    ratchet = _load_ratchet()["rust_shell"]
    unwrap_sites: list[str] = []
    expect_sites: list[str] = []
    unsafe_sites: list[str] = []

    for path in sorted(RUST_SRC.rglob("*.rs")):
        rel = _rel(path)
        in_test_mod = False
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if "#[cfg(test)]" in stripped:
                in_test_mod = True
            if in_test_mod:
                continue
            if ".unwrap(" in stripped:
                unwrap_sites.append(f"{rel}:{lineno}")
            if ".expect(" in stripped:
                expect_sites.append(f"{rel}:{lineno}")
            if _RUST_UNSAFE_RE.search(stripped):
                unsafe_sites.append(f"{rel}:{lineno}")

    checks = [
        ("max_non_test_unwrap", unwrap_sites),
        ("max_non_test_expect", expect_sites),
        ("max_non_test_unsafe", unsafe_sites),
    ]
    failures = [
        f"{key}: observed {len(sites)} > ceiling {ratchet[key]} ({', '.join(sites[:8])})"
        for key, sites in checks
        if len(sites) > ratchet[key]
    ]
    assert not failures, "Rust shell debt ratchet exceeded:\n" + "\n".join(failures)
