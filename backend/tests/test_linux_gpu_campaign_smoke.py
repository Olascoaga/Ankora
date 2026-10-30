"""Synthetic tests for the isolated GPU engineering smoke runner."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "gpu_campaign_smoke", ROOT / "scripts" / "validate_linux_gpu_campaign.py"
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_reference_lookup_ignores_events_without_response_body() -> None:
    events = [
        {"stage": "receptor_preparation", "body": {"receptor_id": "synthetic-receptor"}},
        {"stage": "pose_content", "sha256": "not-an-api-response"},
        {"stage": "binding_site", "body": {"binding_site_id": "synthetic-site"}},
    ]
    assert runner.reference_ids(events) == ("synthetic-receptor", "synthetic-site")
