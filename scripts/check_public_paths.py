"""Reject machine-specific absolute filesystem paths in tracked text files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


WINDOWS_ABSOLUTE_PATH = re.compile(rb"(?<![A-Za-z0-9])[A-Z]:[\\/]")
POSIX_PERSONAL_PATH = re.compile(rb"(?<![A-Za-z0-9])/(?:home|Users)/[^/\s\"']+")


def _tracked_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return tuple(
        Path(raw.decode("utf-8"))
        for raw in result.stdout.split(b"\0")
        if raw
    )


def _line_number(content: bytes, offset: int) -> int:
    return content.count(b"\n", 0, offset) + 1


def main() -> int:
    violations: list[str] = []
    for path in _tracked_files():
        try:
            content = path.read_bytes()
        except OSError as error:
            violations.append(f"{path}: unavailable ({error})")
            continue
        if b"\0" in content:
            continue
        for pattern in (WINDOWS_ABSOLUTE_PATH, POSIX_PERSONAL_PATH):
            for match in pattern.finditer(content):
                violations.append(f"{path}:{_line_number(content, match.start())}")

    if violations:
        print("Tracked absolute filesystem paths are not publishable:")
        for violation in sorted(set(violations)):
            print(f"- {violation}")
        return 1
    print("Public-path check passed: no tracked absolute filesystem paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
