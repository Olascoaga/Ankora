"""Render docs/USER_GUIDE.md to a print-ready PDF.

Printing goes through an installed Edge or Chrome in headless mode. This is a
documentation-maintainer tool, not an end-user installation requirement. The
Markdown subset handled here is exactly the one the guide uses; it is not a
general converter.

    python scripts/build_user_guide_pdf.py
"""

import html as html_mod
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "USER_GUIDE.md"
TARGET = ROOT / "docs" / "Ankora-User-Guide.pdf"
PDF_WAIT_SECONDS = 30.0


def find_browser() -> pathlib.Path | None:
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return pathlib.Path(found)
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if not root:
            continue
        for relative in (
            "Microsoft/Edge/Application/msedge.exe",
            "Google/Chrome/Application/chrome.exe",
        ):
            candidate = pathlib.Path(root) / relative
            if candidate.is_file():
                return candidate
    return None

CSS = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }
:root { --ink:#15202b; --muted:#5a6b78; --line:#d7dee4; --accent:#0d7a5f; --soft:#f4f7f8; }
* { box-sizing: border-box; }
body { margin:0; color:var(--ink); background:#fff;
  font: 10.5pt/1.58 "Segoe UI", -apple-system, system-ui, sans-serif; }
h1 { font-size: 23pt; margin: 0 0 4pt; letter-spacing:-.01em; }
h2 { font-size: 14pt; margin: 20pt 0 6pt; padding-top: 6pt;
  border-top: 1px solid var(--line); page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 13pt 0 4pt; color:#0b3b30; page-break-after: avoid; }
p { margin: 0 0 7pt; }
a { color: var(--accent); text-decoration: none; }
ul, ol { margin: 0 0 8pt; padding-left: 17pt; }
li { margin-bottom: 3pt; }
code { font: 9.2pt/1.4 "Cascadia Mono", Consolas, monospace; background: var(--soft);
  padding: 1px 4px; border-radius: 3px; }
blockquote { margin: 9pt 0; padding: 8pt 11pt; background: var(--soft);
  border-left: 3px solid var(--accent); page-break-inside: avoid; }
blockquote p:last-child { margin-bottom: 0; }
table { width:100%; border-collapse: collapse; margin: 8pt 0 11pt; font-size: 9.5pt;
  page-break-inside: avoid; }
th, td { border-bottom: 1px solid var(--line); padding: 4pt 6pt; text-align: left;
  vertical-align: top; }
th { background: var(--soft); font-weight: 600; }
hr { border: 0; border-top: 1px solid var(--line); margin: 16pt 0; }
figure { margin: 10pt 0 13pt; page-break-inside: avoid; }
figure img { width: 100%; border: 1px solid var(--line); border-radius: 5px; display:block; }
figure em { display:block; margin-top: 4pt; font-size: 8.8pt; color: var(--muted);
  font-style: normal; }
.cover { page-break-after: always; padding-top: 55mm; }
.cover .sub { font-size: 12pt; color: var(--muted); margin-top: 6pt; }
.cover .meta { margin-top: 32mm; font-size: 9.5pt; color: var(--muted); }
strong { font-weight: 600; }
"""

BULLET_PREFIXES = ("- ", "* ")
BLOCK_STARTS = ("#", "|", ">", "- ", "* ", "![", "---")


def inline(text: str) -> str:
    text = html_mod.escape(text, quote=True)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _table(lines: list[str], index: int, out: list[str]) -> int:
    rows = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        rows.append(lines[index].strip())
        index += 1
    cells = [
        [c.strip() for c in row.strip("|").split("|")]
        for row in rows
        if not re.fullmatch(r"\|[\s|:-]+\|", row)
    ]
    if cells:
        head, *body = cells
        out.append(
            "<table><thead><tr>"
            + "".join(f"<th>{inline(c)}</th>" for c in head)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                for row in body
            )
            + "</tbody></table>"
        )
    return index


def _list(lines: list[str], index: int, out: list[str]) -> int:
    ordered = bool(re.match(r"^\d+\.\s", lines[index].strip()))
    items: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if ordered and re.match(r"^\d+\.\s", stripped):
            items.append(re.sub(r"^\d+\.\s", "", stripped))
        elif not ordered and stripped.startswith(BULLET_PREFIXES):
            items.append(stripped[2:])
        elif stripped and items and not stripped.startswith(("#", "|", ">")):
            items[-1] += " " + stripped
        else:
            break
        index += 1
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
    return index


def convert(markdown: str) -> str:
    out: list[str] = []
    heading_counts: dict[str, int] = {}
    lines = markdown.split("\n")
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()

        if not stripped:
            index += 1
        elif stripped.startswith("!["):
            caption = ""
            if index + 2 < len(lines) and lines[index + 2].strip().startswith("*"):
                caption = lines[index + 2].strip().strip("*")
                index += 2
            tail = f"<em>{inline(caption)}</em>" if caption else ""
            out.append(f"<figure>{inline(stripped)}{tail}</figure>")
            index += 1
        elif stripped.startswith("|"):
            index = _table(lines, index, out)
        elif stripped.startswith(">"):
            block = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                block.append(re.sub(r"^>\s?", "", lines[index].strip()))
                index += 1
            paragraphs = [p for p in "\n".join(block).split("\n\n") if p.strip()]
            body = "".join(f"<p>{inline(p)}</p>" for p in paragraphs)
            out.append(f"<blockquote>{body}</blockquote>")
        elif re.match(r"^\d+\.\s", stripped) or stripped.startswith(BULLET_PREFIXES):
            index = _list(lines, index, out)
        elif stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped.lstrip("#").strip()
            slug = re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
            count = heading_counts.get(slug, 0)
            heading_counts[slug] = count + 1
            anchor = f"{slug}-{count}" if count else slug
            out.append(f'<h{level} id="{anchor}">{inline(heading)}</h{level}>')
            index += 1
        elif set(stripped) <= {"-", "*", "_"} and len(stripped) >= 3:
            out.append("<hr>")
            index += 1
        else:
            paragraph = [stripped]
            index += 1
            while index < len(lines):
                nxt = lines[index].strip()
                if not nxt or nxt.startswith(BLOCK_STARTS) or re.match(r"^\d+\.\s", nxt):
                    break
                paragraph.append(nxt)
                index += 1
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(out)


def build_pdf(source: pathlib.Path, target: pathlib.Path, browser: pathlib.Path) -> None:
    cover = (
        '<div class="cover"><h1>Ankora</h1>'
        '<div class="sub">User guide &mdash; version 0.1.0 &middot; Windows</div>'
        '<p>Review draft &middot; 6 October 2026</p>'
        '<div class="meta">A guided docking campaign, from a PDB accession to a '
        'citable record.<br>MIT licence &middot; github.com/Olascoaga/Ankora</div></div>'
    )
    body = convert(source.read_text(encoding="utf-8"))

    def local_image(match: re.Match[str]) -> str:
        path = (source.parent / html_mod.unescape(match.group(1))).resolve()
        if not path.is_relative_to(source.parent.resolve()) or not path.is_file():
            raise ValueError("Guide image must exist inside the documentation directory")
        return f'src="{html_mod.escape(path.as_uri(), quote=True)}"'

    body = re.sub(r'src="([^"]+)"', local_image, body)
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Ankora User Guide</title><style>{CSS}</style></head>"
        f"<body>{cover}{body}</body></html>"
    )
    # Same filesystem for atomic replacement. Never remove a previous good PDF
    # until the browser has successfully produced a complete candidate.
    with (
        tempfile.TemporaryDirectory(prefix="ankora-guide-", dir=target.parent) as scratch,
        # Edge may briefly retain profile cache locks after completing the PDF.
        # Keep that disposable browser profile outside the publication tree.
        tempfile.TemporaryDirectory(
            prefix="ankora-guide-browser-", ignore_cleanup_errors=True
        ) as profile,
    ):
        temporary = pathlib.Path(scratch)
        staged = temporary / "guide.html"
        candidate = temporary / "guide.pdf"
        staged.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [
                str(browser), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                f"--user-data-dir={profile}", "--no-first-run",
                f"--print-to-pdf={candidate}", staged.as_uri(),
            ],
            check=True, capture_output=True, timeout=240, shell=False,
        )
        # Windows browser launchers may return before their print worker exits.
        deadline = time.monotonic() + PDF_WAIT_SECONDS
        while True:
            try:
                payload = candidate.read_bytes()
            except (FileNotFoundError, PermissionError):
                payload = b""
            if payload.startswith(b"%PDF-") and payload.rstrip().endswith(b"%%EOF"):
                break
            if time.monotonic() >= deadline:
                detail = result.stderr.decode("utf-8", errors="replace")[-1500:]
                raise ValueError(f"Browser did not produce a complete PDF. {detail}")
            time.sleep(0.25)
        while True:
            try:
                candidate.replace(target)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)


def main() -> int:
    if not SOURCE.is_file():
        print("missing docs/USER_GUIDE.md")
        return 1
    browser = find_browser()
    if browser is None:
        print("no Edge or Chrome available for printing")
        return 1
    try:
        build_pdf(SOURCE, TARGET, browser)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"PDF build failed; previous PDF retained: {error}")
        return 1
    print(f"{TARGET.name}  {TARGET.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
