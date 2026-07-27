#!/usr/bin/env python3
"""Hide pin numbers on symbols in a KiCad schematic or symbol library.

Unlike sch_tool.py this script *writes* to the file it is given, which is
why it lives apart from it: sch_tool is read-only with respect to the
project and that contract is worth keeping.

Pin-number visibility is a property of the symbol definition, not of a
placed instance, so there is no per-sheet toggle in the GUI. Every
.kicad_sch carries its own copy of each symbol it uses in its lib_symbols
block, and that copy is what renders. Editing the schematic therefore hides
numbers on one sheet only, leaving both the shared project library and
KiCad's stock libraries untouched -- the right move for a reference drawing
that borrows symbols it does not own. Editing a .kicad_sym instead changes
the symbol everywhere it is used.

Note that `Tools > Update Symbols from Library` re-copies definitions into
the schematic and so undoes the .kicad_sch form.

Usage:
    hide_pin_numbers.py FILE                 # every symbol in the file
    hide_pin_numbers.py FILE NAME [NAME ...] # named symbols only
    hide_pin_numbers.py FILE --list          # report state, write nothing

Symbol names are as they appear in the file, library prefix included, e.g.
"nixie_clock:TPS63070" in a schematic but "TPS63070" in a library.
"""

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BLOCK = "(pin_numbers\n{i}\t(hide yes)\n{i})\n"


def symbol_pattern(path):
    """Symbol definitions sit one tab deeper inside a schematic's
    lib_symbols block than at the top level of a library. Sub-units
    (NAME_0_1, NAME_1_1) are one deeper again in both and must be left
    alone: the flag belongs on the parent."""
    depth = 2 if path.suffix == ".kicad_sch" else 1
    return depth, re.compile(r'^\t{%d}\(symbol "([^"]+)"\n' % depth, re.M)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", type=Path, help=".kicad_sch or .kicad_sym")
    ap.add_argument("names", nargs="*", help="symbols to affect; default all")
    ap.add_argument("--list", action="store_true",
                    help="report each symbol's state and exit")
    args = ap.parse_args()

    if args.file.suffix not in (".kicad_sch", ".kicad_sym"):
        sys.exit(f"expected .kicad_sch or .kicad_sym, got {args.file.suffix}")
    src = args.file.read_text(encoding="utf-8")
    depth, pat = symbol_pattern(args.file)
    wanted = set(args.names)

    out, last, changed, already = [], 0, [], []
    for m in pat.finditer(src):
        name = m.group(1)
        hidden = src[m.end():m.end() + 200].lstrip().startswith("(pin_numbers")
        if args.list:
            print(f"  {'hidden' if hidden else 'shown ':6}  {name}")
            continue
        if wanted and name not in wanted:
            continue
        if hidden:
            already.append(name)
            continue
        out.append(src[last:m.end()])
        out.append("\t" * (depth + 1) + BLOCK.format(i="\t" * (depth + 1)))
        last = m.end()
        changed.append(name)

    if args.list:
        return 0
    unknown = wanted - set(changed) - set(already)
    if unknown:
        sys.exit(f"no such symbol(s): {', '.join(sorted(unknown))}")
    if changed:
        out.append(src[last:])
        args.file.write_text("".join(out), encoding="utf-8", newline="")
    print(f"hidden: {', '.join(changed) or '(none)'}")
    if already:
        print(f"already hidden: {', '.join(already)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
