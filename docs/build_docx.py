"""Build the Word deliverables (docs/*.docx) from their markdown sources.

Mermaid fences are rendered to PNG first (Word can't draw Mermaid), then Pandoc converts
the rewritten markdown to .docx.

Usage:
    python docs/build_docx.py            # build every document
    python docs/build_docx.py brd        # build one (guide | brd)
Requires: pandoc on PATH (or installed to %LOCALAPPDATA%\\Pandoc), Node/npx for mermaid-cli.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
BUILD = DOCS / "_build"

DOCUMENTS: dict[str, dict[str, str]] = {
    "guide": {
        "source": "APPLICATION_GUIDE.md",
        "output": "APPLICATION_GUIDE.docx",
        "title": "OV Exception - AI Root Cause & Prevention POC",
        "subtitle": "Complete Application Guide (Functional + Technical)",
    },
    "brd": {
        "source": "BRD.md",
        "output": "BRD.docx",
        "title": "RootIQ - Business Requirements Document",
        "subtitle": "OV Exception - AI Root Cause & Prevention (Proof of Concept)",
    },
}

MERMAID_BLOCK = re.compile(r"^```mermaid\n(.*?)^```\n", re.DOTALL | re.MULTILINE)

# mermaid-cli renders via headless Chromium; --no-sandbox keeps it working on locked-down hosts.
PUPPETEER_CONFIG = '{"args": ["--no-sandbox", "--disable-setuid-sandbox"]}'


def find_pandoc() -> str:
    found = shutil.which("pandoc")
    if found:
        return found
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Pandoc" / "pandoc.exe",
        Path("C:/Program Files/Pandoc/pandoc.exe"),
    ):
        if candidate.exists():
            return str(candidate)
    sys.exit("pandoc not found. Install it: winget install --id JohnMacFarlane.Pandoc")


def npx() -> str:
    found = shutil.which("npx") or shutil.which("npx.cmd")
    if not found:
        sys.exit("npx not found - Node.js is required to render the Mermaid diagrams.")
    return found


def render_diagrams(markdown: str, prefix: str) -> str:
    """Replace each ```mermaid fence with an image reference, rendering the PNG as we go."""
    config = BUILD / "puppeteer.json"
    config.write_text(PUPPETEER_CONFIG, encoding="utf-8")
    index = 0

    def replace(match: re.Match) -> str:
        nonlocal index
        index += 1
        mmd = BUILD / f"{prefix}-diagram-{index}.mmd"
        png = BUILD / f"{prefix}-diagram-{index}.png"
        mmd.write_text(match.group(1), encoding="utf-8")
        print(f"  rendering diagram {index} ...", flush=True)
        subprocess.run(
            [
                npx(), "-y", "@mermaid-js/mermaid-cli@11",
                "-i", str(mmd), "-o", str(png),
                "-b", "white", "-s", "3",
                "--puppeteerConfigFile", str(config),
            ],
            check=True,
            capture_output=True,
        )
        return f"![Diagram {index}]({png.name})\n"

    return MERMAID_BLOCK.sub(replace, markdown)


def build(name: str) -> None:
    spec = DOCUMENTS[name]
    source = DOCS / spec["source"]
    output = DOCS / spec["output"]
    if not source.exists():
        sys.exit(f"Source not found: {source}")

    BUILD.mkdir(exist_ok=True)
    print(f"[{name}] rendering Mermaid diagrams ...")
    rewritten = render_diagrams(source.read_text(encoding="utf-8"), name)

    staged = BUILD / f"{name}.md"
    staged.write_text(rewritten, encoding="utf-8")

    print(f"[{name}] converting to .docx ...")
    subprocess.run(
        [
            find_pandoc(),
            str(staged),
            "-f", "gfm",
            "-o", str(output),
            # No --toc: Word renders a pandoc TOC as a field that stays blank until the reader
            # refreshes it. The hand-written contents list becomes real bookmarks instead.
            "--resource-path", str(BUILD),
            "--metadata", f"title={spec['title']}",
            "--metadata", f"subtitle={spec['subtitle']}",
        ],
        check=True,
    )
    print(f"[{name}] done -> {output}  ({output.stat().st_size // 1024} KB)")


def main() -> None:
    targets = sys.argv[1:] or list(DOCUMENTS)
    unknown = [t for t in targets if t not in DOCUMENTS]
    if unknown:
        sys.exit(f"Unknown document(s): {', '.join(unknown)}. Choose from: {', '.join(DOCUMENTS)}")
    for name in targets:
        build(name)


if __name__ == "__main__":
    main()
