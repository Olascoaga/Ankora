"""Repository entry point for the Windows native scientific-tool smoke matrix."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

main = importlib.import_module("ankora_backend.validation.native_tool_smoke").main


if __name__ == "__main__":
    raise SystemExit(main())
