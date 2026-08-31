"""Collect non-sensitive local runtime metadata."""

import os
import platform
import sys
from pathlib import Path

from ankora_backend.schemas.system import SystemResponse


def _normalized_architecture(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    return normalized


def collect_system_info() -> SystemResponse:
    platform_name = platform.system().lower()
    return SystemResponse(
        platform=platform_name,
        architecture=_normalized_architecture(platform.machine()),
        python_version=platform.python_version() or sys.version.split()[0],
        python_environment=os.getenv("CONDA_DEFAULT_ENV")
        or Path(sys.prefix).name
        or "system",
        app_mode=os.getenv("ANKORA_APP_MODE", "development"),
    )
