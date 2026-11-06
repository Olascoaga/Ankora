"""Observe the exact GNINA process on an NVIDIA GPU; absence is not CPU proof."""

import os
import re
import subprocess
import threading
from importlib import import_module
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError


def single_gpu_identity(device_index: int) -> str:
    """Conservatively resolve CUDA 0 only when one unmapped physical GPU exists."""
    if (
        device_index != 0
        or any(key in os.environ for key in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"))
        or any(key.startswith("CUDA_MPS_") for key in os.environ)
    ):
        raise AnkoraDomainError(
            code="GNINA_GPU_MAPPING_UNSUPPORTED",
            stage="gnina_docking",
            message="GNINA CUDA currently requires one unmapped GPU and device index 0.",
            status_code=422,
        )
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid,mig.mode.current", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        lines = result.stdout.splitlines()
        fields = [part.strip() for part in lines[0].split(",")] if len(lines) == 1 else []
        if (
            len(fields) != 2
            or not re.fullmatch(r"GPU-[0-9a-fA-F-]{36}", fields[0])
            or fields[1].lower() not in {"disabled", "[n/a]", "n/a"}
        ):
            raise ValueError("GPU enumeration or MIG mode is not unambiguous")
        return fields[0]
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise AnkoraDomainError(
            code="GNINA_GPU_MAPPING_UNSUPPORTED",
            stage="gnina_docking",
            message="GNINA CUDA requires one identifiable GPU without MIG.",
            status_code=422,
            details={"reason": type(error).__name__},
        ) from error


class GninaGpuObserver:
    def __init__(self, executable: Path, directory: Path) -> None:
        self._executable = executable.resolve()
        self._directory = directory.resolve()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.observation: str | None = None
        self.gpu_uuid: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._poll, name="gnina-gpu-observer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4)

    def _poll(self) -> None:
        psutil: Any = import_module("psutil")
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid,gpu_uuid",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        fields = [part.strip() for part in line.split(",")]
                        if len(fields) != 2 or not fields[0].isdigit():
                            continue
                        try:
                            process = psutil.Process(int(fields[0]))
                            if (
                                Path(process.exe()).resolve() == self._executable
                                and Path(process.cwd()).resolve() == self._directory
                            ):
                                self.observation = f"PID {fields[0]}; GPU UUID {fields[1]}"
                                self.gpu_uuid = fields[1]
                                return
                        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                            continue
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._stop.wait(0.15)
