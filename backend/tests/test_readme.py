"""Repository presentation checks; no synthetic scientific results are used."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
DOCS_PORTAL = ROOT / "docs" / "README.md"
DEVELOPMENT = ROOT / "docs" / "DEVELOPMENT.md"
DEVELOPMENT_LINUX = ROOT / "docs" / "DEVELOPMENT_LINUX.md"
PLATFORM_JSON = ROOT / "docs" / "product" / "PLATFORM_STATUS.json"
PLATFORM_MD = ROOT / "docs" / "product" / "PLATFORM_STATUS.md"


def _headings(content: str) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for raw_heading in re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE):
        cleaned = re.sub(r"`([^`]+)`", r"\1", raw_heading.strip())
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        slug = re.sub(r"[^\w\s-]", "", cleaned.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
        raw_slug = re.sub(r"[^\w\s-]", "", raw_heading.strip().lower()).replace(" ", "-")
        anchors.add(raw_slug)
    return anchors


@pytest.mark.parametrize(
    "document",
    [
        README,
        DOCS_PORTAL,
        DEVELOPMENT,
        DEVELOPMENT_LINUX,
        PLATFORM_MD,
        ROOT / "docs/images/README.md",
    ],
    ids=[
        "readme",
        "docs-portal",
        "development-windows",
        "development-linux",
        "platform-status",
        "image-provenance",
    ],
)
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
        assert path.exists(), f"{document.name} -> {target}"
        if parsed.fragment and path.suffix == ".md":
            assert parsed.fragment in _headings(path.read_text(encoding="utf-8")), (
                f"{document.name} -> {target}"
            )


def test_readme_uses_current_ci_and_honest_multiplatform_badges() -> None:
    content = README.read_text(encoding="utf-8")
    assert (ROOT / ".github/workflows/ci.yml").is_file()
    assert "actions/workflows/ci.yml/badge.svg" in content
    assert "status-private%20beta%20%C2%B7%20Linux%20RC" in content
    assert "platforms-Windows%2011%20x64%20%7C%20Linux%20x86__64" in content
    assert "license-MIT" in content
    assert "/releases/latest/download/" not in content
    assert "there is not yet a signed public installer release" in content


def test_readme_aligns_with_platform_status_and_separates_source_setup() -> None:
    content = README.read_text(encoding="utf-8")
    status = json.loads(PLATFORM_JSON.read_text(encoding="utf-8"))
    for engine in status["engines"]:
        assert engine["version"] in content
    assert "GNINA `1.3.3`" in content
    assert "CNN_VS" in content
    assert "Spearman" in content

    installation = content.split("## Installation\n", 1)[1].split("\n## ", 1)[0]
    assert "No separate Python, Conda, Java or scientific-tool installation" in installation
    assert "**unsigned**" in installation
    assert "Ankora_0.1.0_x64-setup.exe" in installation
    assert "Ankora_0.1.0_amd64.deb" in installation
    assert "Ankora_0.1.0_linux_x86_64.tar.zst" in installation
    assert "Ankora_0.1.0_gnina-cuda12-pack.tar.zst" in installation
    assert "Gate `D6`" in installation
    assert "macOS is out of scope" in installation
    assert "vendor" in installation and "driver" in installation
    assert "conda env create" not in installation
    assert "conda create" not in installation
    assert "Source\ndevelopment also requires configuring" in content or (
        "Source development also requires configuring" in content
    )
    assert "not redistributed by Ankora" not in DEVELOPMENT.read_text(encoding="utf-8")


def test_readme_shows_current_7aqf_workflow_captures() -> None:
    content = README.read_text(encoding="utf-8")
    for name in ("readme-receptor.jpg", "readme-binding-site.jpg"):
        assert name in content
    assert "guide03-receptor.jpg" not in content
    assert "guide06-binding-site.jpg" not in content
    assert "not interface mockups" in content
    assert "Contacts describe geometry—not measured affinity" in content
    assert "Completed evidence is not synonymous with a successful recovery" in content


def test_readme_current_captures_have_explicit_provenance() -> None:
    content = README.read_text(encoding="utf-8")
    provenance = (ROOT / "docs/images/README.md").read_text(encoding="utf-8")
    for name in (
        "readme-obsidian-interactions.jpg",
        "readme-receptor.jpg",
        "readme-binding-site.jpg",
    ):
        assert name in content
        assert name in provenance
        image = ROOT / "docs/images" / name
        assert image.read_bytes().startswith(b"\xff\xd8\xff")
        assert image.stat().st_size < 1_000_000
    assert "read-only" in content
    assert "20" in provenance
    assert "not a new calculation" in content
    assert "source development" in content


def test_readme_focuses_on_scientific_workflow_not_theme_or_splash() -> None:
    content = README.read_text(encoding="utf-8")
    assert "## A workbench you can inspect" in content
    assert "Obsidian Instrument" not in content
    assert "Anchoring" not in content
    assert "readme-obsidian-startup.jpg" not in content
    assert "Midnight Laboratory" not in content
    assert "theme" not in content.lower()


def test_readme_describes_current_redocking_without_overclaiming() -> None:
    content = README.read_text(encoding="utf-8")
    normalized = " ".join(content.split())
    assert "Current redocking review is read-only" not in normalized
    assert "existing saved poses" in normalized
    assert "not superposed" in normalized
    assert "Library campaigns are not individual redocking inputs" in normalized
    assert "REDOCKING_WORKFLOW_2026-10-20.md" in content


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
    for document in (
        README,
        DOCS_PORTAL,
        DEVELOPMENT,
        DEVELOPMENT_LINUX,
        PLATFORM_MD,
        ROOT / "docs/images/readme-banner.svg",
        ROOT / "docs/images/README.md",
    ):
        content = document.read_text(encoding="utf-8")
        assert not re.search(r"(?<![A-Za-z0-9])[A-Z]:[\\/]", content)
        assert not re.search(r"/(?:home|Users)/[^/\s]+", content)
