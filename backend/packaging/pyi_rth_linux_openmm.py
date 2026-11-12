"""Bind OpenMM plugin loading exclusively to Ankora's frozen Linux bundle."""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _plugin_dir = Path(sys._MEIPASS) / "openmm_plugins"
    if _plugin_dir.is_dir():
        os.environ["OPENMM_PLUGIN_DIR"] = str(_plugin_dir)
