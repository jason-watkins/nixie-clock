#!/usr/bin/env python3
"""Produce fabrication outputs (gerbers, drill, BOM, pick-and-place) for
the KiCad board projects in this repository.

The design is several independently fabricated boards, one KiCad project
each, discovered as pcb/<name>/<name>.kicad_pro. Each board carries its
own revision and is released on its own schedule.

An export is identified by two project text variables (Board Setup -> Text
Variables). REV is the design revision, bumped when the board is respun.
STEP is a positive integer counting the exports of that revision, because a
revision gets sent out several times while it is brought up. Together they
name the export: rev C step 2 is "C2", which becomes fab/<name>/revC2/ and
the tag <name>-revC2. Title blocks and silkscreen should render ${REV} and
${STEP} so a board in hand names the commit it was built from.

An export requires ERC and DRC to pass, its sources to be committed, and
its step to be unspent. Unspent means no <name>-rev<REV><STEP> tag exists
at a different commit; if one does, the export fails, because two different
sets of files would otherwise carry one name. Bump STEP, commit, rerun.
Rerunning at the tagged commit rebuilds the same export, which is the only
case where an existing directory is overwritten.

--step does the bumping: it moves each board past every step already tagged
for its revision, or leaves it alone if the current one is still free. It
runs ahead of every gate and needs no clean tree, because the point in the
workflow where a step is spent is the point where the tree is mid-edit.

It answers for the commit you are about to make, not the one you are on. A
step tagged at HEAD is reusable only because rebuilding there reproduces the
same files, so any pending change to that board's sources -- its own
directory, pcb/lib/, or this script -- retires it: the commit that carries
those changes moves HEAD off the tag. Bumping in that case is what stops the
export from failing on a board that looked settled a moment earlier.

"Sources committed" is scoped to the board rather than to the repository:
its project directory, the shared library directory pcb/lib/, and this
script -- everything whose content can change the exported files. Work in
progress on the design document, on another board, or on an unrelated
script cannot reach these outputs and does not block them.

The design-analysis LaTeX document (docs/design_analysis/) covers all the
boards at once, so it records every board's revision. Those come from a
small generated file (docs/design_analysis/revision.tex) rather than being
hand-maintained: one \\Rev<Name> macro per board, plus \\DesignRev, which
collapses to a bare revision letter while the boards agree and expands to
a per-board list once they diverge. These carry REV alone: the document
describes a revision of the design, not one export of it, so STEP does not
appear there and bumping it never disturbs the document. An export fails if
that file does not match the current revisions of every board -- not only
the one being exported -- so the document can never describe a board it has
fallen behind. Run --sync-doc-rev to regenerate it, commit, and rerun.
Between respins the document keeps showing the previous revisions, which is
expected. The document separately stamps its own compile date via LaTeX's
\\today, independent of this script.

Usage:
    python scripts/make_release.py --check         # evaluate all gates, write nothing
    python scripts/make_release.py                 # release every board
    python scripts/make_release.py main            # release one board
    python scripts/make_release.py main hv         # release a subset
    python scripts/make_release.py --step          # bump spent STEPs, exit
    python scripts/make_release.py --sync-doc-rev  # regenerate revision.tex, exit
    python scripts/make_release.py --no-tag --output ../scratch   # trial run

Output tree (rooted at --output, default fab/):
    <root>/<name>/rev<REV><STEP>/
        erc.rpt, drc.rpt                  reports from the export checks
        <name>-rev<REV><STEP>-board.stl   bare board mesh, no components
        <fab>/
            gerbers/                      gerber and drill files
            <name>-rev<REV><STEP>-<fab>-gerbers.zip   upload this to the fab
            bom.csv                       assembly BOM, fab column format
            positions.csv                 pick-and-place, fab column format

ERC and DRC check the design rather than any one fab, so they run once per
board and their reports sit above the per-fab directories. The board mesh
sits there for the same reason: it is the board itself, in a format no fab
is sent, so it belongs to the revision rather than to any one house.

Fab-specific settings live in FabProfile instances, collected in PROFILES.
Every profile is exported by default; --profile narrows that to a subset.
To add a fab, copy the JLCPCB definition, adjust the kicad-cli arguments
and CSV mappings, and add it to PROFILES -- nothing else needs to change.

Limitations:

* Pick-and-place data uses KiCad's footprint zero for both position and
  rotation, and the fab's library part may be anchored elsewhere. Rotation
  zeros differ for some packages; origins differ whenever a footprint's
  pads are not symmetric about its anchor, because KiCad centres the
  footprint on the body while a fab may centre it on the pad centroid. The
  ESP32-S3-WROOM-1 is the worst case here at 3.7 mm, its antenna end
  carrying no pads. The fab resolves this during DFM review by aligning its
  model to the gerber copper, so the CSV should keep describing the
  footprint honestly rather than carrying a fab-specific offset. Check both
  position and orientation in the fab's DFM viewer before ordering
  assembly.
* The BOM part-number column reads the LCSC symbol field if set, falling
  back to the MFG Part No field. JLCPCB does not assemble rows with an
  empty part number.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Sibling script, importable because this one runs out of scripts/. It owns
# the ballast and divider design space; the parts order offers every value it
# reports so a build can be tuned without a second order.
import ballast_trim_sweep


class ReleaseError(Exception):
    """An unmet release requirement."""


# --------------------------------------------------------------------------
# Fab profiles
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FabProfile:
    """Everything one fab house expects that differs from KiCad defaults.

    Each output is produced only if the profile describes it, so a profile
    that leaves gerber_layer_patterns, bom_columns or pos_columns empty
    simply does not emit that file. A parts-order profile -- a distributor
    rather than a fab -- is the degenerate case: purchase_columns alone.

    Attributes:
        name:          Key used on the command line (``--profile name``).
        gerber_layer_patterns: Suffixes (or exact names) matched against
                       the board's enabled layers to select what to plot.
                       Every pattern must match at least one layer.
        gerber_args:   Extra ``kicad-cli pcb export gerbers`` arguments.
        drill_args:    Extra ``kicad-cli pcb export drill`` arguments.
        pos_args:      Extra ``kicad-cli pcb export pos`` arguments.
        bom_part_fields: Symbol fields tried in order for the BOM
                       part-number column; the first non-empty value per
                       part wins.
        bom_comment_fields: Same, for the BOM comment column. The fab shows
                       this on rows whose part number it cannot resolve, so
                       it should identify the part, not describe it.
        bom_value_prefixes: Designator prefixes exempt from the above: their
                       comment stays the Value, because "10k" reads better
                       than an order code for parts identified by value.
        bom_columns:   The assembly BOM's columns, as (output header, source)
                       pairs in output order. Sources are named in
                       BOM_SOURCES; fabs disagree about both which columns
                       they want and what to call them, so the whole shape
                       is stated per profile rather than only its labels.
        purchase_columns: Same, for a parts-order BOM listing what to buy,
                       or () for a fab that procures the parts itself. This
                       file stays out of the gerber archive: it is for the
                       distributor, not the fab.
        include_alternates: Append SELECTION_KITS values the board is not
                       built with. True for a shopping list, false for a
                       consignment manifest -- the parts shipped to an
                       assembly house must be only the parts it places.
        board_qty:     Boards per order, the quantity the parts-order BOM
                       multiplies by. The fab's usual minimum unless there
                       is a reason to build more.
        overage_rules: (footprint-name pattern, extra pieces) pairs, first
                       match wins. A consigning fab loses parts to feeder
                       setup and tuning, so it demands spares on top of the
                       board count. Empty when the fab buys the parts.
        overage_default: Extra pieces for a part no rule matches.
        zip_extras:    Generated file names to put in the gerber archive
                       alongside the gerbers, for fabs that want one upload.
        mount_type_names: KiCad's footprint attribute -> the fab's word for
                       it. Every house names these differently ("SMT" and
                       "Surface mount" for the same parts), and the column
                       is read by a person, so it uses their vocabulary.
        pos_shift_fields: (x, y) symbol field names holding per-part
                       placement corrections in mm, stated in KiCad's
                       board coordinates (+Y down the screen).
        pos_rotate_field: Symbol field holding a rotation correction in
                       degrees, added to KiCad's rotation.
        bom_strip_lib_prefix: Rewrite BOM "Footprint" cells from
                       ``Library:Name`` to bare ``Name`` (fabs want the
                       package name, not KiCad's library path).
        pos_columns:   Ordered mapping of output CSV header -> KiCad pos
                       CSV header: the columns to keep and their output
                       names.
        pos_side_names: Mapping of KiCad's Side values -> fab's vocabulary.
        upload_notes:  Printed after a successful release.
    """

    name: str
    gerber_layer_patterns: tuple[str, ...]
    gerber_args: tuple[str, ...]
    drill_args: tuple[str, ...]
    pos_args: tuple[str, ...]
    bom_part_fields: tuple[str, ...]
    bom_comment_fields: tuple[str, ...]
    bom_value_prefixes: tuple[str, ...]
    bom_columns: tuple[tuple[str, str], ...]
    purchase_columns: tuple[tuple[str, str], ...]
    include_alternates: bool
    board_qty: int
    overage_rules: tuple[tuple[str, int], ...]
    overage_default: int
    zip_extras: tuple[str, ...]
    mount_type_names: dict[str, str]
    pos_shift_fields: tuple[str, str]
    pos_rotate_field: str
    bom_strip_lib_prefix: bool
    pos_columns: dict[str, str]
    pos_side_names: dict[str, str]
    upload_notes: str


JLCPCB = FabProfile(
    name="jlcpcb",
    # Matched against the board's enabled layers: all copper (inner layers
    # of a four-layer board match automatically), silk, mask, outline.
    gerber_layer_patterns=(".Cu", ".SilkS", ".Mask", "Edge.Cuts"),
    gerber_args=(
        # RS-274X without X2 attributes, per JLC's KiCad guide.
        "--no-x2",
        # Netlist attributes are not needed for fabrication.
        "--no-netlist",
        # Clip silkscreen where it would print over exposed copper.
        "--subtract-soldermask",
        # Protel file extensions (.GTL/.GBO/...) are the kicad-cli default.
    ),
    drill_args=(
        # kicad-cli defaults, stated explicitly so profiles diff cleanly.
        "--format",
        "excellon",
        "--excellon-units",
        "mm",
        "--excellon-zeros-format",
        "decimal",
        # Separate PTH/NPTH files keep plating unambiguous.
        "--excellon-separate-th",
        # Absolute origin, matching the gerbers (which get no origin flag).
        "--drill-origin",
        "absolute",
    ),
    pos_args=(
        "--format",
        "csv",
        "--units",
        "mm",
        "--side",
        "both",
        # Exclude DNP parts from placement.
        "--exclude-dnp",
    ),
    # LCSC when set (JLC cost tuning), else the canonical MFG Part No.
    bom_part_fields=("LCSC", "MFG Part No"),
    # JLC shows the comment for rows whose part number it cannot resolve, and
    # those get matched by hand. The MFG Part No identifies exactly one part;
    # Value may be an electrical value, a function label ("Boot"), or an
    # unedited library symbol name, so it is the fallback rather than the
    # first choice. Swap the order to put values on passives instead.
    bom_comment_fields=("MFG Part No", "Value"),
    # Parts identified by value rather than by order code. "10k" is what a
    # human wants to read here; the order code is already in its own column.
    bom_value_prefixes=("C", "L", "R"),
    # JLC maps columns by header rather than by position, so the quantity
    # column it would otherwise derive from the designator list is harmless
    # to state, and stating it lets the same file feed a distributor's
    # list-import tool, which requires a quantity column and derives nothing.
    bom_columns=(
        ("Comment", "comment"),
        ("Designator", "designator"),
        ("Footprint", "footprint"),
        ("LCSC Part #", "part"),
        ("Quantity", "quantity"),
    ),
    # Turnkey: JLC buys the parts, so there is nothing to order separately
    # and no overage to carry.
    purchase_columns=(),
    include_alternates=False,
    board_qty=5,
    overage_rules=(),
    overage_default=0,
    # JLC takes the BOM and placement file as separate uploads on the order
    # page, so the archive stays gerbers-only.
    zip_extras=(),
    # No type column on this BOM: JLC resolves parts from the LCSC code.
    mount_type_names={},
    # Per-part placement corrections, for packages whose JLC library model is
    # anchored or oriented differently from the KiCad footprint.
    pos_shift_fields=("shift_x", "shift_y"),
    pos_rotate_field="rotate",
    bom_strip_lib_prefix=True,
    # KiCad pos CSV -> JLC CPL.  KiCad emits Ref,Val,Package,PosX,PosY,Rot,Side.
    pos_columns={
        "Designator": "Ref",
        "Mid X": "PosX",
        "Mid Y": "PosY",
        "Layer": "Side",
        "Rotation": "Rot",
    },
    pos_side_names={"top": "Top", "front": "Top", "bottom": "Bottom", "back": "Bottom"},
    upload_notes=(
        "JLCPCB order:\n"
        "  1. Upload the gerbers zip on the quote page.\n"
        "  2. For assembly, upload bom.csv and positions.csv when asked.\n"
        "  3. Review part orientations in their DFM viewer (rotation zeros\n"
        "     differ from KiCad for some packages).\n"
        "  4. Rows with an empty 'LCSC Part #' will not be assembled."
    ),
)

PCBUNLIMITED = FabProfile(
    name="pcbunlimited",
    gerber_layer_patterns=(".Cu", ".SilkS", ".Mask", ".Paste", "Edge.Cuts"),
    gerber_args=("--no-x2", "--no-netlist", "--subtract-soldermask"),
    drill_args=(
        "--format", "excellon",
        "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal",
        "--excellon-separate-th",
        "--drill-origin", "absolute",
    ),
    pos_args=("--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp"),
    # Consigned assembly: the parts are bought here and shipped to them, so
    # the LCSC code has no meaning in this file. No fallback either -- a row
    # reaching them with an empty part number is a part nobody can identify,
    # and a blank cell says that plainly where a stray order code would not.
    bom_part_fields=("MFG Part No",),
    bom_comment_fields=("MFG Part No", "Value"),
    bom_value_prefixes=("C", "L", "R"),
    # Their checklist names the columns it wants: reference designators,
    # quantity, manufacturer part number, part description, type and package.
    bom_columns=(
        ("Reference Designators", "designator"),
        ("Quantity", "quantity"),
        ("Manufacturer Part Number", "part"),
        ("Description", "description"),
        ("Type", "type"),
        ("Package", "footprint"),
    ),
    # What to buy, including their overage. Manufacturer part number and
    # quantity lead, because those are the two columns a distributor's
    # list-import tool needs; the rest is there to check the order by eye.
    purchase_columns=(
        ("Manufacturer Part Number", "part"),
        ("Quantity", "order_qty"),
        ("Description", "comment"),
        ("Package", "footprint"),
        ("Per Board", "quantity"),
        ("Reference Designators", "designator"),
    ),
    # This file is the kit shipped to them. An alternate ballast is a part
    # they have no placement for, and a loose part in a kit is a question.
    include_alternates=False,
    # Their stated minimum on the assembly quote form.
    board_qty=4,
    # "Extra parts will be required on small builds (1 to 25 boards) as
    # follows: 0201 to 0603 size: Minimum extra quantity 50 plus required
    # quantity. 0805 to 1206 size: Minimum extra quantity 25 plus required
    # quantity." Flat counts, not per board -- the loss is in feeder setup,
    # which happens once. Elsewhere on the same page the figures are given
    # as 25 and 10; these are the larger pair, since arriving short stops
    # the build and arriving long costs a few dollars of passives.
    overage_rules=(
        (r"_(0201|0402|0603)_", 50),
        (r"_(0805|1206)_", 25),
    ),
    # "Larger components: 1-2 extra parts sufficient", which also covers
    # every through-hole part.
    overage_default=2,
    # They ask for gerbers, centroid and BOM as a single archive.
    zip_extras=("bom.csv", "positions.csv"),
    # Their checklist's vocabulary: "Type (SMT, Thru-Hole, Fine-pitch, BGA,
    # etc.)". The finer two are not derivable from the footprint attribute
    # and no part on these boards is either.
    mount_type_names={"smd": "SMT", "through_hole": "Thru-Hole"},
    pos_shift_fields=("shift_x", "shift_y"),
    pos_rotate_field="rotate",
    bom_strip_lib_prefix=True,
    pos_columns={
        "Designator": "Ref",
        "Mid X": "PosX",
        "Mid Y": "PosY",
        "Layer": "Side",
        "Rotation": "Rot",
    },
    pos_side_names={"top": "Top", "front": "Top", "bottom": "Bottom", "back": "Bottom"},
    upload_notes=(
        "PCB Unlimited order (consigned assembly):\n"
        "  1. Upload the single gerbers zip; it already carries bom.csv and\n"
        "     positions.csv, which they want in the same archive.\n"
        "  2. Buy the parts from parts-order.csv and ship them the kit. The\n"
        "     quantities there already include their overage.\n"
        "  3. Passives must arrive on continuous strip or reel, not loose\n"
        "     and not in cut segments.\n"
        "  4. DNP parts are excluded from the BOM rather than flagged in a\n"
        "     column, so every row listed is a row to populate."
    ),
)

PCBWAY = FabProfile(
    name="pcbway",
    # They ask for silkscreen, copper and solder paste as a minimum.
    gerber_layer_patterns=(".Cu", ".SilkS", ".Mask", ".Paste", "Edge.Cuts"),
    # RS-274X, which is what --no-x2 leaves.
    gerber_args=("--no-x2", "--no-netlist", "--subtract-soldermask"),
    drill_args=(
        "--format", "excellon",
        "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal",
        "--excellon-separate-th",
        "--drill-origin", "absolute",
    ),
    pos_args=("--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp"),
    # Turnkey: they source from Digi-Key, Mouser and Arrow, none of which
    # know an LCSC code.
    bom_part_fields=("MFG Part No",),
    bom_comment_fields=("MFG Part No", "Value"),
    bom_value_prefixes=("C", "L", "R"),
    # Their file-requirements page names these columns verbatim. Two more
    # that page lists for turnkey orders are absent here: "Manufacturers
    # Name" and "Distributors Part Number". No symbol field holds either,
    # and an empty column reads as missing data rather than as a question
    # their sourcing team can answer from the part number.
    bom_columns=(
        ("Line#", "line"),
        ("Quantity Per Part Number", "quantity"),
        ("Reference Designator", "designator"),
        ("Part Number", "part"),
        ("Part Description", "description"),
        ("Package", "footprint"),
        ("Type (Surface mount, Thru-hole or Hybrid)", "type"),
    ),
    purchase_columns=(),
    include_alternates=False,
    # Their quantity ladder for assembly starts at 5.
    board_qty=5,
    overage_rules=(),
    overage_default=0,
    zip_extras=(),
    mount_type_names={"smd": "Surface mount", "through_hole": "Thru-hole"},
    pos_shift_fields=("shift_x", "shift_y"),
    pos_rotate_field="rotate",
    bom_strip_lib_prefix=True,
    pos_columns={
        "Designator": "Ref",
        "Mid X": "PosX",
        "Mid Y": "PosY",
        "Layer": "Side",
        "Rotation": "Rot",
    },
    pos_side_names={"top": "Top", "front": "Top", "bottom": "Bottom", "back": "Bottom"},
    upload_notes=(
        "PCBWay order (turnkey):\n"
        "  1. Upload the gerbers zip, then bom.csv and positions.csv as\n"
        "     separate files on the assembly page.\n"
        "  2. The centroid lists through-hole parts as well as SMD ones, so\n"
        "     it agrees designator for designator with the BOM.\n"
        "  3. DNP parts are excluded from both files rather than flagged."
    ),
)

DIGIKEY = FabProfile(
    name="digikey",
    gerber_layer_patterns=(),
    gerber_args=(),
    drill_args=(),
    pos_args=(),
    bom_columns=(),
    pos_columns={},
    zip_extras=(),
    # Digi-Key matches on manufacturer part number; an LCSC code resolves to
    # nothing in their catalogue, so there is no fallback to fall back to.
    bom_part_fields=("MFG Part No",),
    bom_comment_fields=("MFG Part No", "Value"),
    bom_value_prefixes=("C", "L", "R"),
    # Headers Digi-Key's list import recognizes, so the upload maps itself.
    # Designators ride in Customer Reference, which is what puts a line item
    # back on a board once the order arrives.
    purchase_columns=(
        ("Manufacturer Part Number", "part"),
        ("Quantity", "order_qty"),
        ("Customer Reference", "designator"),
        ("Description", "comment"),
        ("Package", "footprint"),
    ),
    # The shopping list, so it carries the values still to be chosen between.
    include_alternates=True,
    # One board's worth, with no spares. Multiplying for a build and padding
    # for attrition are both things their site does after upload, and doing
    # either here would fight it.
    board_qty=1,
    overage_rules=(),
    overage_default=0,
    mount_type_names={},
    pos_shift_fields=("", ""),
    pos_rotate_field="",
    bom_strip_lib_prefix=True,
    pos_side_names={},
    upload_notes=(
        "Digi-Key parts order:\n"
        "  1. My Lists -> Create New List -> upload parts-order.csv. The\n"
        "     headers match their importer, so the columns map themselves.\n"
        "  2. Quantities are for one board. Set the build multiplier and any\n"
        "     attrition on their side.\n"
        "  3. Rows with an empty part number are parts with no MFG Part No\n"
        "     set; they will not match and have to be sourced by hand."
    ),
)

# Every profile here is exported by default, each into its own subdirectory of
# the revision, so one commit can be quoted at several houses without a rerun.
# Definition order is the order they run in.
PROFILES: dict[str, FabProfile] = {
    p.name: p for p in (JLCPCB, PCBUNLIMITED, PCBWAY, DIGIKEY)
}


# --------------------------------------------------------------------------
# Environment discovery
# --------------------------------------------------------------------------

def _version_key(path: Path) -> list[int]:
    """Numeric sort key for install directories named like '10.0' or '9.0'.

    Sorting these as strings puts '9.0' above '10.0', which picks an older
    CLI than the one installed and then fails to read files written by the
    newer one. Non-numeric components sort last."""
    return [int(part) if part.isdigit() else -1 for part in path.name.split(".")]


def find_kicad_cli(explicit: str | None) -> str:
    """Locate kicad-cli: --kicad-cli flag, KICAD_CLI env, the platform's
    standard install location, then PATH.

    The standard install is preferred over PATH so that installing a new
    KiCad takes effect without also having to fix a stale PATH entry. Windows
    keeps versions side by side under C:\\Program Files\\KiCad\\<version>\\,
    so that one is picked by newest version; macOS's installer instead
    overwrites a single KiCad.app in place, and does not put its
    Contents/MacOS/ on PATH."""
    for candidate in (explicit, os.environ.get("KICAD_CLI")):
        if candidate:
            return candidate
    if sys.platform == "win32":
        base = Path(r"C:\Program Files\KiCad")
        if base.is_dir():
            installs = [p for p in base.iterdir() if p.is_dir()]
            for version_dir in sorted(installs, key=_version_key, reverse=True):
                cli = version_dir / "bin" / "kicad-cli.exe"
                if cli.is_file():
                    return str(cli)
    elif sys.platform == "darwin":
        cli = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
        if cli.is_file():
            return str(cli)
    found = shutil.which("kicad-cli")
    if found:
        return found
    raise ReleaseError("kicad-cli not found: install KiCad or set KICAD_CLI")


def run(cmd: list[str], cwd: Path | None = None, ok_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    """Run a command and return the completed process. Raises ReleaseError
    with the captured output if the exit code is not in ok_codes."""
    proc = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode not in ok_codes:
        detail = (proc.stderr.strip() or proc.stdout.strip())[-2000:]
        raise ReleaseError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{detail}")
    return proc


@dataclass(frozen=True)
class Project:
    """One board's KiCad project files plus the git root."""
    root: Path        # git repository root
    name: str         # board name, from the project directory
    pro: Path         # .kicad_pro
    pcb: Path         # .kicad_pcb
    sch: Path         # root .kicad_sch


def find_boards(wanted: list[str] | None = None) -> list[Project]:
    """Discover board projects as pcb/<name>/<name>.kicad_pro.

    Requiring the project to be named after its directory is what keeps
    this from picking up the reference schematics under docs/, or a
    superseded project left at the top of pcb/. Names must be alphabetic
    so they can form LaTeX macro names in revision.tex.

    With `wanted` given, return those boards in that order; otherwise
    every board found, alphabetically."""
    root = Path(run(["git", "rev-parse", "--show-toplevel"]).stdout.strip())
    found: dict[str, Project] = {}
    for pro in sorted((root / "pcb").glob("*/*.kicad_pro")):
        name = pro.parent.name
        if pro.stem != name:
            continue
        if not name.isalpha():
            raise ReleaseError(
                f"board directory {name!r} is not alphabetic; revision.tex "
                f"derives a LaTeX macro name from it"
            )
        pcb, sch = pro.with_suffix(".kicad_pcb"), pro.with_suffix(".kicad_sch")
        for f in (pcb, sch):
            if not f.is_file():
                raise ReleaseError(f"project file missing: {f}")
        found[name] = Project(root=root, name=name, pro=pro, pcb=pcb, sch=sch)
    if not found:
        raise ReleaseError("no board projects found; expected pcb/<name>/<name>.kicad_pro")
    if wanted is None:
        return list(found.values())
    unknown = [n for n in wanted if n not in found]
    if unknown:
        raise ReleaseError(
            f"unknown board(s): {', '.join(unknown)}; "
            f"available: {', '.join(sorted(found))}"
        )
    return [found[n] for n in wanted]


def _within(path: Path, root: Path) -> bool:
    """True if path is root or sits beneath it. Both must be resolved."""
    return path == root or root in path.parents


def _display_path(path: Path, root: Path) -> Path:
    """Repo-relative when the path is inside the repo, absolute otherwise:
    --output can point anywhere on the filesystem."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


# --------------------------------------------------------------------------
# Release gates.  Each returns None on success or raises ReleaseError.
# --------------------------------------------------------------------------

LIB_URI_RE = re.compile(r'\(\s*uri\s+"([^"]*)"\s*\)')

# The vendored symbol and footprint libraries every board draws on.
SHARED_LIB_DIR = Path("pcb/lib")


def gate_lib_scope(project: Project) -> None:
    """Refuse a lib table pointing at an in-repo library that export_sources
    does not cover."""
    root = project.root.resolve()
    proj_dir = project.pro.parent.resolve()
    lib_dir = (root / SHARED_LIB_DIR).resolve()
    for table in ("fp-lib-table", "sym-lib-table"):
        table_file = proj_dir / table
        if not table_file.is_file():
            continue
        for uri in LIB_URI_RE.findall(table_file.read_text(encoding="utf-8")):
            if "${KIPRJMOD}" not in uri:
                continue  # a global library is not this repository's to vouch for
            target = Path(uri.replace("${KIPRJMOD}", str(proj_dir)))
            if not target.exists():
                continue
            target = target.resolve()
            if not _within(target, root):
                continue  # outside the repository: no commit to hold it to
            if _within(target, proj_dir) or _within(target, lib_dir):
                continue
            raise ReleaseError(
                f"board {project.name!r}: {table} points at "
                f"{_display_path(target, root)}, which the source-cleanliness "
                f"check does not cover.\nMove the library under "
                f"{SHARED_LIB_DIR.as_posix()}/ or widen export_sources()."
            )


def export_sources(project: Project) -> list[Path]:
    """Every path whose content decides this board's exported files: the
    board's project directory, the shared library directory, and this script."""
    root = project.root.resolve()
    found = [project.pro.parent.resolve(),
             (root / SHARED_LIB_DIR).resolve(),
             Path(__file__).resolve(),
             # Imported to compute the parts order's alternate values, so its
             # content reaches the outputs exactly as this script's does.
             Path(ballast_trim_sweep.__file__).resolve()]
    return [p for p in found if p.exists() and _within(p, root)]


def dirty_sources(project: Project) -> list[str]:
    """git status lines for the paths that decide this board's outputs.

    Empty means the board's next export would come from HEAD as it stands.
    Both the cleanliness gate and the step allocator ask this: one to refuse
    an export, the other to predict the commit an export will land on."""
    paths = [str(p) for p in export_sources(project)]
    status = run(["git", "status", "--porcelain", "--", *paths],
                 cwd=project.root).stdout
    return [line for line in status.splitlines() if line.strip()]


def gate_git_clean(project: Project) -> None:
    """Require this board's sources to be committed, so its tag names a
    commit that reproduces the exported files."""
    gate_lib_scope(project)
    lines = dirty_sources(project)
    if lines:
        listing = "\n".join(lines[:10])
        raise ReleaseError(
            f"board {project.name!r} has uncommitted changes in its sources; "
            f"commit or stash first:\n{listing}"
        )


def read_text_var(project: Project, name: str) -> str:
    """One project text variable (Board Setup -> Text Variables)."""
    text_vars = json.loads(project.pro.read_text(encoding="utf-8")).get("text_variables", {})
    return text_vars.get(name, "").strip()


def read_rev(project: Project) -> str:
    """The REV text variable: the design revision, bumped when the board is
    respun."""
    rev = read_text_var(project, "REV")
    if not rev:
        raise ReleaseError(
            f"text variable 'REV' is not set on board {project.name!r}.\n"
            "Define it in Board Setup -> Text Variables (e.g. REV = A); the\n"
            "silkscreen and title blocks should reference it as ${REV}."
        )
    if not rev.replace(".", "").isalnum():
        raise ReleaseError(
            f"board {project.name!r}: REV {rev!r} contains characters "
            f"unsuitable for a tag name"
        )
    return rev


def read_step(project: Project) -> str:
    """The STEP text variable: which export of this revision is being built."""
    step = read_text_var(project, "STEP")
    if not step:
        raise ReleaseError(
            f"text variable 'STEP' is not set on board {project.name!r}.\n"
            "Define it in Board Setup -> Text Variables (e.g. STEP = 1); the\n"
            "silkscreen and title blocks should reference it as ${REV}${STEP}."
        )
    if not step.isdigit() or step != str(int(step)) or int(step) < 1:
        raise ReleaseError(
            f"board {project.name!r}: STEP {step!r} is not a positive integer "
            f"without leading zeros ('1' and '01' would name two exports)."
        )
    return step


def read_export_id(project: Project) -> str:
    """REV and STEP joined, e.g. 'C2'. Names the output directory and tag."""
    return read_rev(project) + read_step(project)


STEP_VAR_RE = re.compile(r'("STEP"\s*:\s*")([^"]*)(")')


def write_step(project: Project, step: str) -> None:
    """Set the STEP text variable in place."""
    text = project.pro.read_text(encoding="utf-8")
    new_text, count = STEP_VAR_RE.subn(
        lambda m: m.group(1) + step + m.group(3), text)
    if count != 1:
        raise ReleaseError(
            f"expected one 'STEP' text variable in {project.pro.name}, found {count}"
        )
    project.pro.write_text(new_text, encoding="utf-8")


def spent_steps(project: Project, rev: str) -> dict[int, str]:
    """Step numbers already tagged for this revision -> the commit each names.

    Read from tags rather than from the output tree, so a fab directory that
    was deleted or never synced does not make a spent step look free."""
    prefix = release_tag(project, rev)
    listing = run(["git", "tag", "--list", f"{prefix}*"], cwd=project.root).stdout
    spent: dict[int, str] = {}
    for tag in listing.split():
        suffix = tag[len(prefix):]
        # Skips the pre-step tags, whose suffix is empty.
        if suffix.isdigit():
            spent[int(suffix)] = run(["git", "rev-list", "-n1", tag],
                                     cwd=project.root).stdout.strip()
    return spent


def next_step(project: Project, rev: str, step: str) -> tuple[str | None, str]:
    """The step this board must move to and why, or (None, reason) if the
    current one is free.

    Free means untagged, or tagged at HEAD with nothing uncommitted that
    could change this board's output."""
    spent = spent_steps(project, rev)
    if int(step) not in spent:
        return None, "unspent"
    head = run(["git", "rev-parse", "HEAD"], cwd=project.root).stdout.strip()
    tagged = spent[int(step)]
    if tagged != head:
        return str(max(spent) + 1), f"tagged at {tagged[:10]}"
    pending = dirty_sources(project)
    if not pending:
        return None, "tagged at HEAD, nothing pending: a rebuild of itself"
    return (
        str(max(spent) + 1),
        f"tagged at HEAD, but {len(pending)} pending source change(s) will move HEAD off it",
    )


def bump_steps(boards: list[Project]) -> list[Project]:
    """Advance STEP on every board whose current one is already spent.

    Reports each board either way, because "nothing to do" and "bumped" look
    the same in a diff once the commit is made."""
    bumped: list[Project] = []
    for board in boards:
        rev, step = read_rev(board), read_step(board)
        target, why = next_step(board, rev, step)
        if target is None:
            print(f"  {board.name:6} rev {rev}{step}: left alone -- {why}")
            continue
        write_step(board, target)
        print(f"  {board.name:6} rev {rev}{step}: {why}\n"
              f"  {'':6} -> STEP now {target} (rev {rev}{target})")
        bumped.append(board)
    return bumped


def read_revs(boards: list[Project]) -> dict[str, str]:
    """Every board's REV, keyed by board name.

    REV alone, without STEP: this feeds the design document, which describes
    a revision of the design rather than one export of it."""
    return {b.name: read_rev(b) for b in boards}


DOC_REVISION_FILE = Path("docs/design_analysis/revision.tex")


def _doc_revision_content(revs: dict[str, str]) -> str:
    """One \\Rev<Name> macro per board, plus \\DesignRev for the title block.

    \\DesignRev is the bare revision while every board agrees, and a
    per-board list once they diverge, so the common case reads as
    "Rev B" rather than as a catalogue."""
    lines = ["% Generated by scripts/make_release.py --sync-doc-rev -- do not hand-edit.\n"]
    for name, rev in sorted(revs.items()):
        lines.append(f"\\newcommand{{\\Rev{name.capitalize()}}}{{{rev}}}\n")
    distinct = set(revs.values())
    combined = (distinct.pop() if len(distinct) == 1
                else " / ".join(f"{n}~{r}" for n, r in sorted(revs.items())))
    lines.append(f"\\newcommand{{\\DesignRev}}{{{combined}}}\n")
    return "".join(lines)


def gate_doc_revision(root: Path, revs: dict[str, str]) -> None:
    """The design-analysis document's revision macros must match every
    board, not just the one being released: the document describes all of
    them, so it is stale the moment any board moves ahead of it.

    This is a content check, not a git-dirty check: a stale file can be
    fully committed if a REV was bumped without re-running --sync-doc-rev."""
    path = root / DOC_REVISION_FILE
    actual = path.read_text(encoding="utf-8") if path.is_file() else None
    if actual != _doc_revision_content(revs):
        listing = ", ".join(f"{n}={r}" for n, r in sorted(revs.items()))
        raise ReleaseError(
            f"{DOC_REVISION_FILE} does not match the current revisions ({listing}).\n"
            "Run: python scripts/make_release.py --sync-doc-rev, then commit, then rerun."
        )


def sync_doc_rev(root: Path, revs: dict[str, str]) -> Path:
    """Regenerate the design-analysis document's revision macros."""
    path = root / DOC_REVISION_FILE
    path.write_text(_doc_revision_content(revs), encoding="utf-8")
    return path


def release_tag(project: Project, export_id: str) -> str:
    """Tags are per board, so boards can be respun independently."""
    return f"{project.name}-rev{export_id}"


def gate_ledger(project: Project, export_id: str) -> None:
    """Fail if this export identifier was already spent at another commit.

    STEP is what moves here. The tag binds REV+STEP to one commit, so
    exporting changed sources under the same STEP would give two different
    sets of files the same name -- which is the thing the step number
    exists to prevent."""
    tag = release_tag(project, export_id)
    probe = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
                cwd=project.root, ok_codes=(0, 1))
    if probe.returncode == 1:
        return  # tag absent: this step is unspent
    tagged, head = probe.stdout.strip(), run(["git", "rev-parse", "HEAD"], cwd=project.root).stdout.strip()
    if tagged != head:
        raise ReleaseError(
            f"{project.name} rev {export_id} was already exported "
            f"(tag {tag} -> {tagged[:10]}).\n"
            f"Bump STEP in Board Setup -> Text Variables, commit, and rerun."
        )
    # Tag points at HEAD: rebuilding the same export is fine.


def gate_erc(kicad_cli: str, project: Project, report: Path) -> None:
    """Schematic must be free of error-level ERC violations (warnings pass)."""
    proc = run([kicad_cli, "sch", "erc", "--severity-error", "--exit-code-violations",
                "-o", str(report), str(project.sch)], ok_codes=(0, 5))
    if proc.returncode != 0:
        raise ReleaseError(f"ERC has error-level violations; see {report}")


def gate_drc(kicad_cli: str, project: Project, report: Path) -> None:
    """Board must pass DRC errors and schematic parity (warnings pass)."""
    proc = run([kicad_cli, "pcb", "drc", "--severity-error", "--exit-code-violations",
                "--schematic-parity", "-o", str(report), str(project.pcb)], ok_codes=(0, 5))
    if proc.returncode != 0:
        raise ReleaseError(f"DRC has error-level violations; see {report}")


# --------------------------------------------------------------------------
# Fab output generation
# --------------------------------------------------------------------------

def board_layers(project: Project) -> list[str]:
    """Enabled layer names from the board file's layer table."""
    text = project.pcb.read_text(encoding="utf-8")
    return re.findall(
        r'\(\s*\d+\s+"([^"]+)"\s+(?:signal|power|mixed|jumper|user)\b', text
    )


def select_layers(project: Project, profile: FabProfile) -> str:
    """Match the profile's layer patterns against the board's enabled
    layers. A pattern that matches nothing is an error: it means the
    profile and the board disagree about layer naming."""
    enabled = board_layers(project)
    selected: list[str] = []
    for pattern in profile.gerber_layer_patterns:
        matched = [n for n in enabled if n == pattern or n.endswith(pattern)]
        if not matched:
            raise ReleaseError(
                f"no enabled board layer matches {pattern!r}; "
                f"enabled: {', '.join(enabled)}"
            )
        selected += [n for n in matched if n not in selected]
    return ",".join(selected)


def export_gerbers_and_drill(kicad_cli: str, project: Project, profile: FabProfile,
                             gerber_dir: Path) -> None:
    gerber_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            kicad_cli,
            "pcb",
            "export",
            "gerbers",
            "-o",
            str(gerber_dir),
            "-l",
            select_layers(project, profile),
            *profile.gerber_args,
            str(project.pcb),
        ]
    )
    run([kicad_cli, "pcb", "export", "drill",
         "-o", str(gerber_dir) + os.sep,  # kicad-cli requires a trailing separator here
         *profile.drill_args, str(project.pcb)])


BOARD_MODEL_SUFFIX = "-board.stl"


def export_board_model(kicad_cli: str, project: Project, out_stl: Path) -> None:
    """Export the bare board as a printable mesh: outline, cutouts and holes,
    with nothing mounted on it.

    A solid of the board is what a fit check is made against -- print it and
    the enclosure, or cut one from the other in CAD -- and none of that wants
    the components, which --board-only drops.

    Nothing else is asked for, so the solid is the dielectric core alone and
    measures 1.510 rather than the stackup's 1.600. Copper and mask are
    separately exportable and would make up the difference, at the price of
    dragging 10 um and 35 um features into a mesh meant for a printer. Ninety
    microns is the wrong ninety microns to chase.

    Via holes stay closed for the same reason: at 0.3 mm they are below what
    a printer resolves, so cutting them would add several hundred perimeters
    that come out as blemishes. The pad drills and mounting holes are cut,
    which is what a fit check is actually looking at.

    The origin is the board file's, matching the gerbers. cad/test_base
    re-exports on its own terms when it needs a board taken about its centre.

    The file is named for the board and the export rather than sitting under
    a generic name, because unlike the reports beside it this one is meant to
    be opened somewhere else, where three files called board.stl are three
    chances to print the wrong one."""
    run([kicad_cli, "pcb", "export", "stl", "--board-only", "--force",
         "-o", str(out_stl), str(project.pcb)])


# kicad-cli's pos CSV column names. These are KiCad's, not the fab's, so they
# are fixed here rather than in the profile.
POS_SRC_X, POS_SRC_Y, POS_SRC_ROT = "PosX", "PosY", "Rot"


def _correction(text: str) -> float:
    """Parse a correction field. Blank means none; a 'mm' or 'deg' suffix is
    tolerated so the schematic can carry readable values."""
    t = text.strip().lower()
    for suffix in ("mm", "deg", "°"):
        t = t.removesuffix(suffix).strip()
    if not t:
        return 0.0
    try:
        return float(t)
    except ValueError as exc:
        raise ReleaseError(f"placement correction {text!r} is not a number") from exc


def read_placement_corrections(kicad_cli: str, project: Project,
                               profile: FabProfile) -> dict[str, tuple[float, float, float]]:
    """Per-designator (dx, dy, drot) placement corrections from schematic fields.

    A fab places its own library model at the coordinate this script reports,
    and that model may be anchored or oriented differently from the KiCad
    footprint -- most visibly on parts whose pads are not symmetric about the
    footprint anchor. These fields carry the measured correction per part.
    Only symbols that set at least one of the fields appear in the result."""
    wanted = [f for f in (*profile.pos_shift_fields, profile.pos_rotate_field) if f]
    if not wanted:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "corrections.csv"
        # No --group-by: one row per symbol, so corrections stay per-designator
        # even when two parts are otherwise identical.
        run([kicad_cli, "sch", "export", "bom", "-o", str(raw),
             "--fields", ",".join(["Reference", *wanted]),
             "--labels", ",".join(["Reference", *wanted]),
             "--ref-range-delimiter", "",
             str(project.sch)])
        rows = list(csv.DictReader(raw.open(encoding="utf-8")))
    out: dict[str, tuple[float, float, float]] = {}
    fx, fy = profile.pos_shift_fields
    for row in rows:
        vals = (_correction(row.get(fx, "")), _correction(row.get(fy, "")),
                _correction(row.get(profile.pos_rotate_field, "")))
        if any(vals):
            for ref in row["Reference"].split(","):
                if ref.strip():
                    out[ref.strip()] = vals
    return out


def export_positions(kicad_cli: str, project: Project, profile: FabProfile,
                     out_csv: Path, assembled: set[str] | None = None) -> None:
    """Export the position file, then rewrite it into the fab's CPL format.

    ``assembled`` is the designator set the BOM offers. KiCad keeps "exclude
    from BOM" and "exclude from position files" as separate per-symbol flags,
    so a part dropped from one still appears in the other -- and the assembly
    house rejects every placement row it cannot find a BOM line for. Filtering
    to the BOM here makes the two files agree by construction, rather than
    relying on both checkboxes being set on every mounting hole, test point
    and hand-fitted connector.

    Per-part corrections from profile.pos_shift_fields / pos_rotate_field are
    applied on the way out. Both are stated the way KiCad states them, so a
    correction can be read straight off the board editor: shifts are in board
    coordinates (+Y is down the screen, which this negates on the way into the
    CSV), and the rotation is a delta added to KiCad's, so it describes the
    fab's model rather than one placement and survives the part being
    moved or re-rotated."""
    corrections = read_placement_corrections(kicad_cli, project, profile)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "pos.csv"
        run([kicad_cli, "pcb", "export", "pos", "-o", str(raw),
             *profile.pos_args, str(project.pcb)])
        rows = list(csv.DictReader(raw.open(encoding="utf-8")))
    if rows:
        missing = [src for src in profile.pos_columns.values() if src not in rows[0]]
        if missing:
            raise ReleaseError(
                f"kicad-cli pos CSV lacks expected columns {missing}; "
                f"got {list(rows[0])}. Update profile.pos_columns to match."
            )
    ref_src = profile.pos_columns["Designator"]
    placed = {row[ref_src] for row in rows}
    applied: set[str] = set()
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(profile.pos_columns.keys())
        for row in rows:
            ref = row[ref_src]
            if assembled is not None and ref not in assembled:
                continue
            if ref in corrections:
                dx, dy, drot = corrections[ref]
                row[POS_SRC_X] = f"{float(row[POS_SRC_X]) + dx:.6f}"
                # Corrections are stated in KiCad's board coordinates, where Y
                # grows downward; kicad-cli emits Y negated, so it subtracts.
                row[POS_SRC_Y] = f"{float(row[POS_SRC_Y]) - dy:.6f}"
                row[POS_SRC_ROT] = f"{(float(row[POS_SRC_ROT]) + drot) % 360:.6f}"
                applied.add(ref)
            record = [row[src] for src in profile.pos_columns.values()]
            side_index = list(profile.pos_columns).index("Layer")
            record[side_index] = profile.pos_side_names.get(
                record[side_index].lower(), record[side_index])
            writer.writerow(record)
    # A correction that never reached a row is worse than no correction: the
    # schematic says the part is being fixed up and nothing happens. Usually a
    # typo'd designator, or a field set on a part the CPL excludes.
    unused = sorted(set(corrections) - applied)
    if unused:
        raise ReleaseError(
            f"placement corrections set on {', '.join(unused)} were never "
            "applied: those designators are not in the placement file."
        )
    # The reverse mismatch is the dangerous one: a part the BOM offers with no
    # placement row is silently left unassembled rather than warned about.
    if assembled is not None:
        orphans = sorted(assembled - placed)
        if orphans:
            raise ReleaseError(
                "BOM lists parts with no placement row: "
                f"{', '.join(orphans)}. They are in the BOM but excluded from "
                "position files, so the assembler cannot place them."
            )


FOOTPRINT_BLOCK_RE = re.compile(r'\n\s*\(footprint\s')
FOOTPRINT_ATTR_RE = re.compile(r'\(attr\s+([^)]*)\)')
FOOTPRINT_REF_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')

# KiCad's footprint attributes that state how a part is mounted.
MOUNT_ATTRS = ("smd", "through_hole")


def footprint_types(project: Project) -> dict[str, str]:
    """KiCad's mounting attribute per designator, read from the board.

    KiCad records this on every footprint as (attr smd) or (attr
    through_hole), which is the same flag its own SMD/THT filters use, so
    the board answers the question directly and no symbol field has to
    restate it. A footprint carrying neither -- KiCad's "other" type -- is
    left out rather than guessed at.

    The values are KiCad's; profile.mount_type_names turns them into the
    words a given fab uses. This does not distinguish the finer categories
    some fabs list, such as fine-pitch or BGA: those need pad geometry, and
    no part on these boards is either."""
    text = project.pcb.read_text(encoding="utf-8")
    types: dict[str, str] = {}
    for block in FOOTPRINT_BLOCK_RE.split(text)[1:]:
        ref = FOOTPRINT_REF_RE.search(block)
        attr = FOOTPRINT_ATTR_RE.search(block)
        if not ref or not attr:
            continue
        for flag in attr.group(1).split():
            if flag in MOUNT_ATTRS:
                types[ref.group(1)] = flag
                break
    return types


def overage(profile: FabProfile, footprint: str) -> int:
    """Spare pieces the fab wants beyond the boards being built."""
    for pattern, extra in profile.overage_rules:
        if re.search(pattern, footprint):
            return extra
    return profile.overage_default


def yageo_code(ohms: float) -> str:
    """Yageo's through-hole resistance code, where the multiplier letter
    stands in for the decimal point: 8.2k -> 8K2, 9.09k -> 9K09, 10k -> 10K,
    82 ohm -> 82R. Significant figures follow the value, so an E24 part gets
    a two-digit code and an E96 part a three-digit one, which is what the
    catalogue does."""
    for limit, unit in ((1e6, "M"), (1e3, "K"), (1.0, "R")):
        if ohms >= limit:
            whole, _, frac = f"{ohms / limit:.10g}".partition(".")
            return f"{whole}{unit}{frac}"
    raise ReleaseError(f"resistance {ohms} is below 1 ohm; no code for it")


def value_text(ohms: float) -> str:
    """The value as a schematic would write it: 7500 -> '7.5k'."""
    for limit, unit in ((1e6, "M"), (1e3, "k"), (1.0, "")):
        if ohms >= limit:
            return f"{ohms / limit:g}{unit}"
    return f"{ohms:g}"


@dataclass(frozen=True)
class SelectionKit:
    """Values a board can be tuned to, beyond the one it is built with.

    The ballast sets digit current and the divider sets the rail that feeds
    it; both are chosen against real tubes, whose maintaining voltage the
    datasheets do not bound. Ordering the whole candidate set with the build
    turns that choice into a swap on the bench instead of a second order and
    a week's wait.

    These reach the parts order only. An assembly house is never handed a
    part it is not meant to place.

    Attributes:
        board:      Board whose parts order gains the alternates.
        fitted:     Designator already carrying one of the candidate values.
                    Its part number and package are the pattern the rest are
                    built from, so the alternates match what was specified
                    rather than a series named twice.
        column:     ballast_trim_sweep.build_table() key holding the values.
        per_board:  Pieces one board takes of whichever value wins.
        label:      What the row is, for the reference column.
    """

    board: str
    fitted: str
    column: str
    per_board: int
    label: str


SELECTION_KITS = (
    SelectionKit(board="face", fitted="R1", column="r_a", per_board=4,
                 label="digit ballast"),
    SelectionKit(board="hv", fitted="R13", column="r205", per_board=1,
                 label="feedback divider"),
)


def kit_candidates(kit: SelectionKit) -> list[int]:
    """The kit's distinct values in ohms, ascending. Several table rows can
    name one value -- two ballasts may share a divider -- so this dedupes."""
    table = ballast_trim_sweep.build_table()
    return sorted({round(row[kit.column] * 1000) for row in table})


def alternate_records(project: Project, profile: FabProfile,
                      records: list[dict[str, str]],
                      start_line: int) -> list[dict[str, str]]:
    """Parts-order rows for the values a board is not built with.

    The fitted part's number is decomposed by finding which candidate's code
    it ends with, which pins down both the series prefix and the value that
    is already on the order. That doubles as the check on this whole
    construction: if the code for the fitted value did not rebuild its actual
    part number, every alternate built from the same prefix would be wrong
    too, so it fails here rather than on the order.

    The match is exact, including case. A miscased multiplier letter is
    reported as its own error rather than waved through, because the
    alternates are built canonically and would otherwise ship in a different
    style from the part they were derived from."""
    extra: list[dict[str, str]] = []
    for kit in SELECTION_KITS:
        if kit.board != project.name:
            continue
        fitted = next((r for r in records if kit.fitted in _refs(r["designator"])), None)
        if fitted is None:
            raise ReleaseError(
                f"selection kit for board {kit.board!r} names {kit.fitted}, "
                f"which is not on the BOM"
            )
        candidates = kit_candidates(kit)
        part = fitted["part"]
        matched = [ohms for ohms in candidates
                   if part.endswith("-" + yageo_code(ohms))]
        if len(matched) != 1:
            # A resistance code's only letter is its multiplier, and the
            # catalogue writes it uppercase. Miscased, it still names the
            # right part to a human and to a distributor's search, so the
            # generic "matches none of the candidates" reads as though the
            # value were wrong and sends the fix in the wrong direction.
            miscased = [ohms for ohms in candidates
                        if part.upper().endswith("-" + yageo_code(ohms))]
            if len(miscased) == 1:
                code = yageo_code(miscased[0])
                raise ReleaseError(
                    f"{kit.fitted} on board {kit.board!r} is {part!r}, which is "
                    f"{value_text(miscased[0])} with a lowercase multiplier "
                    f"letter.\nThe catalogue writes it {code!r}: set 'MFG Part "
                    f"No' to {part[:-len(code)] + code!r}."
                )
            tried = ", ".join(f"{value_text(o)} ({yageo_code(o)})" for o in candidates)
            raise ReleaseError(
                f"{kit.fitted} on board {kit.board!r} is {part!r}, whose part "
                f"number matches {len(matched)} of the {kit.label} candidates.\n"
                f"Tried: {tried}.\n"
                "The fitted part must be one of them, so the alternates can copy "
                "its series and packaging."
            )
        prefix = fitted["part"][: -len(yageo_code(matched[0]))]
        for ohms in candidates:
            if ohms == matched[0]:
                continue  # already on the order, as the part actually fitted
            value = value_text(ohms)
            extra.append({
                "line": str(start_line + len(extra)),
                "comment": value,
                "designator": f"alt {kit.fitted} {value}",
                "footprint": fitted["footprint"],
                "part": prefix + yageo_code(ohms),
                "quantity": str(kit.per_board),
                "description": f"{kit.label} candidate, {value}; not fitted, "
                               f"ordered for bench selection",
                "type": fitted["type"],
                "order_qty": str(kit.per_board * profile.board_qty
                                 + overage(profile, fitted["footprint"])),
            })
    return extra


def _refs(cell: str) -> list[str]:
    """Split a BOM row's designator cell. One row carries many designators;
    --ref-range-delimiter "" in export_bom guarantees they are spelled out
    rather than collapsed into ranges, so a plain split counts parts."""
    return [ref.strip() for ref in cell.split(",") if ref.strip()]


# Values a profile may put in a BOM column, as named in bom_columns and
# purchase_columns. Keeping the vocabulary closed means a typo in a profile
# fails at the gate rather than writing a column of blanks.
BOM_SOURCES = {
    "line": "1-based row number, for fabs that want the BOM numbered",
    "comment": "identifying text, for a row the fab has to match by hand",
    "designator": "every reference designator on the row, comma separated",
    "footprint": "package name",
    "part": "first non-empty of profile.bom_part_fields",
    "quantity": "designators on this row, i.e. pieces per board",
    "description": "the symbol's Description field",
    "type": "SMT or Thru-Hole, read from the board",
    "order_qty": "pieces to buy: quantity x board_qty, plus overage",
}

PURCHASE_BOM = "parts-order.csv"


def _write_columns(path: Path, columns: tuple[tuple[str, str], ...],
                   records: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([header for header, _ in columns])
        for record in records:
            writer.writerow([record[source] for _, source in columns])


def export_bom(kicad_cli: str, project: Project, profile: FabProfile,
               out_csv: Path | None, purchase_csv: Path | None = None) -> set[str]:
    """Export the assembly BOM, and the parts-order BOM if the fab consigns.

    Either output may be absent: out_csv is None for a distributor profile
    that only needs a parts order, and purchase_csv is unused by a fab that
    buys the parts itself.

    One row per part type. The part-number column tries
    profile.bom_part_fields in order and keeps the first non-empty value.
    The part fields are included in the grouping so parts that differ only
    in part number stay on separate rows.

    The comment column works the same way from profile.bom_comment_fields.
    It matters only on rows the fab cannot resolve automatically -- those are
    matched by hand, and the comment is the only search key the operator
    sees, so a generic library symbol name there ("Q_Dual_PMOS_...") wastes
    the one chance to identify the part.

    Both files are built from one pass over the same rows, so the parts
    ordered and the parts placed can never describe different boards.

    Returns every designator the BOM offers, which export_positions uses to
    hold the placement file to the same set."""
    wanted = {source for _, source in profile.bom_columns + profile.purchase_columns}
    unknown = sorted(wanted - set(BOM_SOURCES))
    if unknown:
        raise ReleaseError(
            f"profile {profile.name!r} asks for unknown BOM column(s) {unknown}; "
            f"known sources: {', '.join(sorted(BOM_SOURCES))}"
        )
    part_fields = list(profile.bom_part_fields)
    comment_fields = list(profile.bom_comment_fields)
    # Value is always exported (it is the fallback for both text columns); the
    # rest are whatever the priority lists and the column specs ask for.
    extra = [f for f in dict.fromkeys(
        part_fields + comment_fields + (["Description"] if "description" in wanted else [])
    ) if f != "Value"]
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "bom.csv"
        run(
            [
                kicad_cli, "sch", "export", "bom", "-o", str(raw),
                "--fields", ",".join(["Value", "Reference", "Footprint"] + extra),
                "--labels", ",".join(["Comment", "Designator", "Footprint"] + extra),
                "--group-by", ",".join(["Value", "Footprint"] + extra),
                "--exclude-dnp",
                # Spell every reference out. kicad-cli defaults to collapsing
                # runs into ranges ("C1-C3"), which an assembly house reads as
                # one literal designator matching nothing in the placement
                # file, so those parts silently go unassembled.
                "--ref-range-delimiter", "",
                str(project.sch),
            ]
        )
        rows = list(csv.reader(raw.open(encoding="utf-8")))
    header, body = rows[0], rows[1:]
    # "Value" is exported under the label "Comment", so it is column 0.
    col = {"Value": 0}
    col.update({f: header.index(f) for f in extra})
    fp_col = header.index("Footprint")
    types = footprint_types(project) if "type" in wanted else {}

    records: list[dict[str, str]] = []
    for line, row in enumerate(body, start=1):
        footprint = row[fp_col].split(":")[-1] if profile.bom_strip_lib_prefix else row[fp_col]
        refs = _refs(row[1])

        def first(fields, _row=row):
            return next((_row[col[f]] for f in fields
                         if f in col and _row[col[f]].strip()), "")

        # Grouping keys include Value and the part fields, so every designator
        # on a row is the same part type and the first one's prefix speaks for
        # all of them.
        prefix = re.match(r"[A-Za-z]+", refs[0]) if refs else None
        if prefix and prefix.group(0) in profile.bom_value_prefixes:
            comment = row[col["Value"]].strip() or first(comment_fields)
        else:
            comment = first(comment_fields)
        records.append({
            "line": str(line),
            "comment": comment,
            "designator": row[1],
            "footprint": footprint,
            "part": first(part_fields),
            "quantity": str(len(refs)),
            "description": row[col["Description"]] if "Description" in col else "",
            "type": profile.mount_type_names.get(types.get(refs[0], ""), "") if refs else "",
            "order_qty": str(len(refs) * profile.board_qty
                             + overage(profile, footprint)),
        })

    if "type" in wanted:
        # An assembly house routes SMT and through-hole down different lines,
        # so a blank here is a question they have to come back and ask. It
        # means a footprint set to KiCad's "other" type; fix it in the
        # footprint properties rather than in this file.
        untyped = [r["designator"] for r in records if not r["type"]]
        if untyped:
            raise ReleaseError(
                f"board {project.name!r}: no SMD or through-hole attribute on "
                f"the footprint(s) for {', '.join(untyped)}.\n"
                "Set the footprint type in Footprint Properties so the BOM can "
                "state it."
            )
    if profile.bom_columns and out_csv is not None:
        _write_columns(out_csv, profile.bom_columns, records)
    if profile.purchase_columns and purchase_csv is not None:
        # Alternates go on the parts order only, never into `records`: they
        # have no designators, so they must not reach bom.csv, the returned
        # designator set, or the placement file held against it.
        ordered = records + (
            alternate_records(project, profile, records, len(records) + 1)
            if profile.include_alternates else []
        )
        _write_columns(purchase_csv, profile.purchase_columns, ordered)
    return {ref for record in records for ref in _refs(record["designator"])}


def make_zip(gerber_dir: Path, zip_path: Path, extras: tuple[Path, ...] = ()) -> None:
    """Archive the gerbers, plus any files a fab wants in the same upload."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(gerber_dir.iterdir()):
            zf.write(f, f.name)
        for f in extras:
            zf.write(f, f.name)


def create_tag(project: Project, export_id: str) -> None:
    """Tag the commit this export was built from.

    The message names no fab: the tag pins a commit, and a later export for
    a second fab reuses this same tag rather than replacing it, so anything
    it said about which fabs had run would go stale. The directory listing
    answers that question."""
    tag = release_tag(project, export_id)
    exists = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                 cwd=project.root, ok_codes=(0, 1))
    if exists.returncode == 0:
        return  # tag already points at HEAD (same-commit rebuild)
    run(["git", "tag", "-a", tag, "-m",
         f"Fab export {project.name} rev {export_id}"],
        cwd=project.root)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def _report(label: str, check, note: str = "") -> bool:
    try:
        check()
        print(f"  [pass] {label}{note}")
        return True
    except ReleaseError as err:
        print(f"  [FAIL] {label}: {err}")
        return False


def preflight(kicad_cli: str, boards: list[Project], all_boards: list[Project]) -> bool:
    """Run every gate and print each result; return overall pass/fail.

    A release stops at the first failure; preflight reports all of them.
    The document-revision gate reads every board, not just the ones being
    released; every other gate is per board."""
    root = all_boards[0].root
    try:
        revs = read_revs(all_boards)
        passed = _report("doc rev in sync", lambda: gate_doc_revision(root, revs))
    except ReleaseError as err:
        passed = False
        print(f"  [FAIL] doc rev in sync: {err}")

    with tempfile.TemporaryDirectory() as tmp:
        for board in boards:
            try:
                export_id = read_export_id(board)
            except ReleaseError as err:
                passed = False
                print(f"\n{board.name}:\n  [FAIL] REV/STEP defined: {err}")
                continue
            print(f"\n{board.name} (rev {export_id}):")
            passed &= _report("sources committed", lambda b=board: gate_git_clean(b))
            passed &= _report("step unspent",
                              lambda b=board, e=export_id: gate_ledger(b, e))
            passed &= _report("ERC clean", lambda b=board:
                              gate_erc(kicad_cli, b, Path(tmp) / f"{b.name}-erc.rpt"))
            passed &= _report("DRC clean", lambda b=board:
                              gate_drc(kicad_cli, b, Path(tmp) / f"{b.name}-drc.rpt"))
    print("\npreflight: " + ("ready to release" if passed
                             else "not ready; fix the items above"))
    return passed


def profile_stages(kicad_cli: str, project: Project, profile: FabProfile,
                   out_dir: Path, export_id: str) -> list[tuple[str, object]]:
    """The labelled steps that fill one fab's directory.

    The gerber zip carries the fab name because it is the one file that
    leaves this directory: three identically named archives in a downloads
    folder is a good way to send a board to the wrong house."""
    gerber_dir = out_dir / "gerbers"
    assembled: set[str] = set()
    written = [name for name, wanted in (("bom.csv", profile.bom_columns),
                                         (PURCHASE_BOM, profile.purchase_columns)) if wanted]
    stages: list[tuple[str, object]] = []
    if profile.gerber_layer_patterns:
        stages.append((
            f"{profile.name}: gerbers + drill",
            lambda: export_gerbers_and_drill(kicad_cli, project, profile, gerber_dir),
        ))
    # The BOM runs before the placement file: it decides which designators
    # are offered for assembly, and the placement file is held to that set.
    # Both BOMs come out of this one call, so the parts ordered and the parts
    # placed can never describe different boards.
    if written:
        stages.append((
            f"{profile.name}: {' + '.join(written)}",
            lambda: assembled.update(
                export_bom(kicad_cli, project, profile,
                           out_dir / "bom.csv" if profile.bom_columns else None,
                           out_dir / PURCHASE_BOM)
            ),
        ))
    if profile.pos_columns:
        stages.append((
            f"{profile.name}: positions.csv",
            lambda: export_positions(
                kicad_cli, project, profile, out_dir / "positions.csv", assembled
            ),
        ))
    # Last, so the files a fab wants bundled already exist. The parts-order
    # BOM is never among them: it is for the distributor, not the fab.
    if profile.gerber_layer_patterns:
        stages.append((
            f"{profile.name}: zip",
            lambda: make_zip(
                gerber_dir,
                out_dir / f"{project.name}-rev{export_id}-{profile.name}-gerbers.zip",
                tuple(out_dir / name for name in profile.zip_extras),
            ),
        ))
    return stages


def release(kicad_cli: str, project: Project, profiles: list[FabProfile],
            revs: dict[str, str], out_root: Path, tag: bool = True) -> None:
    """Export one board for every fab profile, under
    out_root/<name>/rev<REV><STEP>/<fab>/.

    Each step gets its own directory and its own tag, so repeated exports of
    one revision accumulate side by side instead of overwriting each other.
    The only directory this rebuilds in place is the one whose tag already
    points at HEAD, where the rebuild reproduces what it replaces.

    ERC and DRC run once for the board, not once per fab: they check the
    design, and their reports sit at the revision directory above the
    per-fab ones. The board mesh joins them there, being the board rather
    than any house's view of it. Only the profiles being exported are
    cleared, so quoting a second fab later leaves the first one's files where
    they are -- they describe the same commit and are still current."""
    export_id = read_export_id(project)
    gate_doc_revision(project.root, revs)
    gate_git_clean(project)
    gate_ledger(project, export_id)

    rev_dir = out_root / project.name / f"rev{export_id}"
    rev_dir.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        fab_dir = rev_dir / profile.name
        if fab_dir.exists():
            shutil.rmtree(fab_dir)  # same-commit rebuild: start from scratch
        fab_dir.mkdir()

    stages = [
        ("ERC", lambda: gate_erc(kicad_cli, project, rev_dir / "erc.rpt")),
        (
            "DRC + schematic parity",
            lambda: gate_drc(kicad_cli, project, rev_dir / "drc.rpt"),
        ),
        (
            "board model (STL)",
            lambda: export_board_model(
                kicad_cli, project,
                rev_dir / f"{project.name}-rev{export_id}{BOARD_MODEL_SUFFIX}",
            ),
        ),
    ]
    for profile in profiles:
        stages += profile_stages(kicad_cli, project, profile,
                                 rev_dir / profile.name, export_id)
    if tag:
        stages.append((f"git tag {release_tag(project, export_id)}",
                       lambda: create_tag(project, export_id)))
    total = len(stages)
    for i, (label, stage) in enumerate(stages, start=1):
        print(f"  [{i}/{total}] {label}")
        stage()

    tag_note = "" if tag else "  (no tag created)"
    fabs = ", ".join(p.name for p in profiles)
    print(f"\nexported {project.name} rev {export_id} for {fabs} -> "
          f"{_display_path(rev_dir, project.root)}{tag_note}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produce fab outputs (gerbers/BOM/placement) with revision checks.",
        epilog="--check reports every unmet release condition at once.",
    )
    parser.add_argument("boards", nargs="*", metavar="BOARD",
                        help="board name(s) to act on (default: every board)")
    parser.add_argument("--profile", nargs="+", metavar="NAME",
                        default=list(PROFILES), choices=sorted(PROFILES),
                        help="fab house output formats to export "
                             f"(default: all of {', '.join(PROFILES)})")
    parser.add_argument("--check", action="store_true",
                        help="preflight only: evaluate all release gates, produce no outputs")
    parser.add_argument("--no-tag", action="store_true",
                        help="skip the git tag step; requires --output, since an "
                             "untagged export may not enter fab/")
    parser.add_argument("--output", metavar="DIR", default=None,
                        help="root for the exported tree (default: fab/); "
                             "outputs land in DIR/<board>/rev<REV><STEP>/")
    parser.add_argument("--step", action="store_true",
                        help="bump STEP on any board whose step is already tagged "
                             "elsewhere, then exit; run before committing")
    parser.add_argument("--sync-doc-rev", action="store_true",
                        help="regenerate docs/design_analysis/revision.tex from REV, then exit")
    parser.add_argument("--kicad-cli", default=None,
                        help="path to kicad-cli (default: autodetect)")
    args = parser.parse_args()

    try:
        all_boards = find_boards()
        boards = find_boards(args.boards) if args.boards else all_boards
        root = all_boards[0].root

        # Deliberately ahead of every gate, and of the kicad-cli lookup: this
        # is what a blocked export sends you to, and at that point the tree
        # is mid-edit by definition. It only reads tags and writes .kicad_pro.
        if args.step:
            bumped = bump_steps(boards)
            if not bumped:
                print("\nno step needed; every board's step is free at this commit")
                return 0
            # Forward slashes: git takes them on every platform, and the hint
            # is meant to be pasted into whichever shell is to hand.
            files = " ".join(b.pro.relative_to(root).as_posix() for b in bumped)
            print(f"\nCommit the bumped step(s), then export:\n"
                  f"  git add {files}\n"
                  f"  git commit -m \"Bump export step\"\n"
                  f"Reload the project if KiCad has it open; the silkscreen and\n"
                  f"title block render ${{STEP}} and still show the old number.")
            return 0

        # revision.tex always covers every board, whatever subset is released.
        if args.sync_doc_rev:
            revs = read_revs(all_boards)
            path = sync_doc_rev(root, revs)
            listing = ", ".join(f"{n}={r}" for n, r in sorted(revs.items()))
            print(f"wrote {path.relative_to(root)} ({listing})")
            return 0

        kicad_cli = find_kicad_cli(args.kicad_cli)
        if args.check:
            return 0 if preflight(kicad_cli, boards, all_boards) else 1

        fab_root = (root / "fab").resolve()
        out_root = Path(args.output).resolve() if args.output else fab_root
        # Every directory under fab/ is meant to be reachable from a tag that
        # names the commit it was built from. An untagged export there would
        # break that, so it has to go somewhere else. Checked after --check,
        # which writes nothing and so needs no destination.
        untagged = args.no_tag or out_root != fab_root
        if untagged and _within(out_root, fab_root):
            raise ReleaseError(
                "--no-tag may not write into fab/: every export there is "
                "reachable from a tag naming its commit.\n"
                "Pass --output with a directory outside the fab tree."
            )
        if untagged:
            print("no tag will be created "
                  f"({'--no-tag' if args.no_tag else '--output'})")

        # dict.fromkeys: a repeated --profile must not export twice.
        profiles = [PROFILES[n] for n in dict.fromkeys(args.profile)]
        revs = read_revs(all_boards)
        for board in boards:
            print(f"\n{board.name}:")
            release(kicad_cli, board, profiles, revs, out_root, tag=not untagged)
        if not untagged:
            for profile in profiles:
                print("\n" + profile.upload_notes)
        return 0
    except ReleaseError as err:
        print(f"\nexport blocked: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
