from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import generate_third_party_notices as notices

ROOT = Path(__file__).resolve().parents[2]
LEGAL_ROOT = ROOT / "apps" / "desktop" / "src-tauri" / "resources" / "legal"


def test_tracked_legal_payload_matches_dependency_manifests() -> None:
    notices.verify_static_inventory(LEGAL_ROOT)


def test_inventory_is_machine_neutral_and_excludes_external_tools() -> None:
    inventory_text = (LEGAL_ROOT / "THIRD_PARTY_INVENTORY.json").read_text(
        encoding="utf-8"
    )
    inventory = json.loads(inventory_text)

    assert ":\\Users\\" not in inventory_text
    assert "/home/" not in inventory_text
    assert set(inventory["excluded_external_tools"]) == set(notices.EXTERNAL_TOOLS)
    assert {component["category"] for component in inventory["components"]} == {
        "installer",
        "native-runtime",
        "python",
        "rust",
        "web",
    }


def test_external_tool_cannot_be_claimed_as_bundled() -> None:
    component = notices.Component(
        category="python",
        name="AutoDock Vina",
        version="1.2.7",
        license="Apache-2.0",
        source_url="https://example.invalid/vina",
    )

    with pytest.raises(RuntimeError, match="incorrectly inventoried"):
        notices.validate_components([component])
