"""Observe the exact GNINA process on an NVIDIA GPU; absence is not CPU proof."""

import subprocess
import threading
from importlib import import_module
from pathlib import Path
from typing import Any


class GninaGpuObserver:
    def __init__(self, executable: Path, directory: Path) -> None:
        self._executable = executable.resolve()
        self._directory = directory.resolve()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.observation: str | None = None

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
                                return
                        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                            continue
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._stop.wait(0.15)
