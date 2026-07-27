#!/usr/bin/env python3
"""Render the design-analysis document's schematic figures.

The reference schematics under docs/design_analysis/schematics/ are a KiCad
project of their own. Nothing instantiates them from pcb/pcb.kicad_sch, so
they are invisible to the board's ERC, netlist, BOM, and PCB -- they exist
only to be drawn. Each sheet other than the project root becomes one figure.

Each figure is plotted black and white with no drawing sheet, then cropped
to its ink with pdfcrop, since KiCad plots to a full page and leaves the
drawing adrift in margin. Output goes to docs/design_analysis/figures/ under
the sheet's own file name, so a figure is renamed by renaming its sheet.

The exported PDF keeps an invisible text layer for search, and draws visible
text as stroked paths. That is KiCad's doing, not a plotting option, and it
means figure labels stay searchable inside the compiled document.

Because text is stroked, its weight is a pen width rather than a font weight,
and KiCad defaults it to the same width it draws wires with. At figure scale
that reads heavy and flattens the drawing, so each sheet is plotted from a
copy with an explicit, lighter text thickness. Doing it here rather than in the
schematic keeps weight a property of the rendering, leaves the sources
canonical, and survives new text added in the GUI.

Usage:
    python scripts/build_figures.py            # rebuild every figure
    python scripts/build_figures.py --check    # report stale figures, write nothing
    python scripts/build_figures.py 3v3        # rebuild named sheets only
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[1]
SCH_DIR = REPO / "docs" / "design_analysis" / "schematics"
FIG_DIR = REPO / "docs" / "design_analysis" / "figures"
CROP_MARGIN = 6  # pt of whitespace left around the ink

# Stroke width for text, in mm. KiCad's default is 0.1524, the same pen it
# draws wires with; this sets annotation below the circuit so the two read as
# different layers. KiCad clamps to about 1/15 of the text height, roughly
# 0.085 mm at the usual 1.27 mm, so there is little room below this.
TEXT_THICKNESS = 0.10

FONT_BLOCK = re.compile(r"(\(font\n(\s*)\(size [\d.]+ [\d.]+\)\n)")

PLOT_FLAGS = [
    "--black-and-white",
    "--exclude-drawing-sheet",
    "--no-background-color",
    # An embedded figure has no use for KiCad's interactive layers, and
    # they bloat the document and confuse text extraction.
    "--exclude-pdf-property-popups",
    "--exclude-pdf-hierarchical-links",
    "--exclude-pdf-metadata",
]


def find_kicad_cli() -> str:
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    found = shutil.which("kicad-cli")
    if found:
        return found
    base = Path(r"C:\Program Files\KiCad")
    if base.is_dir():
        for ver in sorted(base.iterdir(), reverse=True):
            cli = ver / "bin" / "kicad-cli.exe"
            if cli.is_file():
                return str(cli)
    sys.exit("kicad-cli not found: install KiCad or set KICAD_CLI")


def find_pdfcrop() -> str:
    found = shutil.which("pdfcrop")
    if not found:
        sys.exit("pdfcrop not found: it ships with TeX Live and MiKTeX, "
                 "and needs Ghostscript on PATH")
    return found


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        sys.exit(f"failed ({proc.returncode}): {Path(cmd[0]).name}")


def figure_sheets() -> list[Path]:
    """Every sheet except the project root, which only carries sheet symbols."""
    if not SCH_DIR.is_dir():
        sys.exit(f"no reference schematics at {SCH_DIR}")
    roots = {p.stem for p in SCH_DIR.glob("*.kicad_pro")}
    return sorted(
        p for p in SCH_DIR.glob("*.kicad_sch")
        if p.stem not in roots and not p.name.startswith("~")
    )


def is_stale(sheet: Path, figure: Path) -> bool:
    return not figure.is_file() or sheet.stat().st_mtime > figure.stat().st_mtime


def lighten_text(src: Path, dst: Path) -> int:
    """Copy a sheet with an explicit text thickness on every font block.

    Font blocks that already carry a thickness are left as the author set
    them. Each sheet embeds the symbols it uses, so the copy plots correctly
    from anywhere and needs no project context.
    """
    text = src.read_text(encoding="utf-8")
    out, last, n = [], 0, 0
    for m in FONT_BLOCK.finditer(text):
        if "(thickness" in text[m.end():m.end() + 40]:
            continue
        out.append(text[last:m.end()])
        out.append(f"{m.group(2)}(thickness {TEXT_THICKNESS})\n")
        last, n = m.end(), n + 1
    out.append(text[last:])
    dst.write_text("".join(out), encoding="utf-8", newline="")
    return n


def build(sheet: Path, figure: Path, kicad_cli: str, pdfcrop: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / sheet.name
        n = lighten_text(sheet, staged)
        raw = Path(tmp) / f"{sheet.stem}.pdf"
        run([kicad_cli, "sch", "export", "pdf", *PLOT_FLAGS,
             "-o", str(raw), str(staged)])
        run([pdfcrop, "--margins", str(CROP_MARGIN), str(raw), str(figure)])
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sheets", nargs="*", metavar="NAME",
                    help="sheet names to rebuild; default all")
    ap.add_argument("--check", action="store_true",
                    help="report stale figures and exit nonzero if any")
    args = ap.parse_args()

    sheets = figure_sheets()
    if args.sheets:
        wanted = set(args.sheets)
        unknown = wanted - {s.stem for s in sheets}
        if unknown:
            sys.exit(f"no such sheet(s): {', '.join(sorted(unknown))}")
        sheets = [s for s in sheets if s.stem in wanted]
    if not sheets:
        sys.exit(f"no figure sheets found in {SCH_DIR}")

    if args.check:
        stale = [s for s in sheets if is_stale(s, FIG_DIR / f"{s.stem}.pdf")]
        for s in stale:
            print(f"stale: {s.stem}")
        print(f"-- {len(stale)} of {len(sheets)} figure(s) stale")
        return 1 if stale else 0

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    kicad_cli, pdfcrop = find_kicad_cli(), find_pdfcrop()
    for sheet in sheets:
        figure = FIG_DIR / f"{sheet.stem}.pdf"
        n = build(sheet, figure, kicad_cli, pdfcrop)
        size = figure.stat().st_size
        print(f"{sheet.name} -> {figure.relative_to(REPO).as_posix()} "
              f"({size // 1024} kB, {n} text block(s) at "
              f"{TEXT_THICKNESS} mm)")
    print(f"-- {len(sheets)} figure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
