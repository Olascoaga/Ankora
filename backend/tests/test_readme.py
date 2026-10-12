"""Repository presentation checks; no synthetic scientific results are used."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
DEVELOPMENT = ROOT / "docs" / "DEVELOPMENT.md"


def _headings(content: str) -> set[str]:
    return {
        re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
        for heading in re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
    }


@pytest.mark.parametrize("document", [README, DEVELOPMENT], ids=["readme", "development"])
def test_presentation_local_links_and_images_resolve(document: Path) -> None:
    content = document.read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)\s]+)\)", content)
    targets += re.findall(r'(?:src|href)="([^"]+)"', content)
    assert targets, "The presentation must link to documentation and actual image assets."
    for target in targets:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        path = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
        assert path.is_relative_to(ROOT), target
        assert path.exists(), target
        if parsed.fragment and path.suffix == ".md":
            assert parsed.fragment in _headings(path.read_text(encoding="utf-8")), target


def test_readme_uses_current_ci_and_honest_beta_badges() -> None:
    content = README.read_text(encoding="utf-8")
    assert (ROOT / ".github/workflows/ci.yml").is_file()
    assert "actions/workflows/ci.yml/badge.svg?branch=main" in content
    assert "status-private%20beta" in content
    assert "platform-Windows%2011%20x64" in content
    assert "license-MIT" in content
    assert "/releases/latest/download/" not in content
    assert "there is not yet a public installer release" in content


def test_readme_separates_bundled_installation_from_source_setup() -> None:
    content = README.read_text(encoding="utf-8")
    installation = content.split("## Installation\n", 1)[1].split("\n## ", 1)[0]
    assert "No separate Python, Conda, Java or scientific-tool installation" in installation
    assert "**unsigned**" in installation
    assert "vendor\ndriver" in installation
    assert "Linux and macOS are not accepted release platforms yet" in installation
    assert "conda env create" not in installation
    assert "Source development also requires configuring" in content
    assert "not redistributed by Ankora" not in DEVELOPMENT.read_text(encoding="utf-8")


def test_readme_reuses_real_verified_7aqf_figures() -> None:
    content = README.read_text(encoding="utf-8")
    guide = (ROOT / "docs/USER_GUIDE.md").read_text(encoding="utf-8")
    for name in ("guide11-interactions.jpg", "guide03-receptor.jpg", "guide06-binding-site.jpg"):
        assert name in content
        assert name in guide
    assert "not interface mockups" in content
    assert "Contacts describe geometry—not measured affinity" in content
    assert "Completed evidence is not synonymous with a successful recovery" in content


def test_readme_banner_is_accessible_self_contained_svg() -> None:
    banner = ROOT / "docs/images/readme-banner.svg"
    content = banner.read_text(encoding="utf-8")
    svg = ET.fromstring(content)
    namespace = "{http://www.w3.org/2000/svg}"
    assert svg.tag == f"{namespace}svg"
    assert svg.attrib["viewBox"] == "0 0 1200 280"
    assert svg.find(f"{namespace}title") is not None
    assert svg.find(f"{namespace}desc") is not None
    forbidden = {f"{namespace}script", f"{namespace}foreignObject"}
    assert all(node.tag not in forbidden for node in svg.iter())
    assert not re.search(r'(?:href|src)="(?:https?:|file:)', content)


def test_presentation_has_no_personal_absolute_paths() -> None:
    for document in (README, DEVELOPMENT, ROOT / "docs/images/readme-banner.svg"):
        content = document.read_text(encoding="utf-8")
        assert not re.search(r"(?<![A-Za-z0-9])[A-Z]:[\\/]", content)
        assert not re.search(r"/(?:home|Users)/[^/\s]+", content)
