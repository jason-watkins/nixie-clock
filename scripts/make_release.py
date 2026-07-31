#!/usr/bin/env python3
"""Produce fabrication outputs (gerbers, drill, BOM, pick-and-place) for
the KiCad board projects in this repository.

The design is several independently fabricated boards, one KiCad project
each, discovered as pcb/<name>/<name>.kicad_pro. Each board carries its
own revision and is released on its own schedule.

A release requires a clean git tree, passing ERC and DRC, and a revision
with no existing release tag. The revision is the project text variable
REV (Board Setup -> Text Variables); title blocks and silkscreen render it
as ${REV}. A release exports to fab/<name>/rev<REV>/ and tags HEAD as
<name>-rev<REV>. If that tag exists at another commit, the release fails:
bump REV, commit, rerun. Rerunning at the tagged commit rebuilds the same
release.

The design-analysis LaTeX document (docs/design_analysis/) covers all the
boards at once, so it records every board's revision. Those come from a
small generated file (docs/design_analysis/revision.tex) rather than being
hand-maintained: one \\Rev<Name> macro per board, plus \\DesignRev, which
collapses to a bare revision letter while the boards agree and expands to
a per-board list once they diverge. A release fails if that file does not
match the current revisions of every board -- not only the one being
released -- so the document can never describe a board it has fallen
behind. Run --sync-doc-rev to regenerate it, commit, and rerun. Between
releases the document keeps showing the previous revisions, which is
expected. The document separately stamps its own compile date via LaTeX's
\\today, independent of this script.

Usage:
    python scripts/make_release.py --check         # evaluate all gates, write nothing
    python scripts/make_release.py                 # release every board
    python scripts/make_release.py main            # release one board
    python scripts/make_release.py main hv         # release a subset
    python scripts/make_release.py --no-tag         # export only; repeatable test runs
    python scripts/make_release.py --sync-doc-rev  # regenerate revision.tex, exit

Output tree:
    fab/<name>/rev<REV>/
        gerbers/                         gerber and drill files
        <name>-rev<REV>-gerbers.zip      upload this to the fab
        bom.csv                          assembly BOM, fab column format
        positions.csv                    pick-and-place, fab column format
        erc.rpt, drc.rpt                 reports from the release checks

Fab-specific settings live in FabProfile instances. To add a fab, copy the
JLCPCB definition, adjust the kicad-cli arguments and CSV mappings, and
add it to PROFILES.

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


class ReleaseError(Exception):
    """An unmet release requirement."""


# --------------------------------------------------------------------------
# Fab profiles
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FabProfile:
    """Everything one fab house expects that differs from KiCad defaults.

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
        bom_part_label: Output header for the part-number column.
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
    bom_part_label: str
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
    bom_part_label="LCSC Part #",
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

PROFILES: dict[str, FabProfile] = {p.name: p for p in (JLCPCB,)}


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
    """Locate kicad-cli: --kicad-cli flag, KICAD_CLI env, the newest version
    under C:\\Program Files\\KiCad, then PATH.

    The versioned install is preferred over PATH so that installing a new
    KiCad takes effect without also having to fix a stale PATH entry."""
    for candidate in (explicit, os.environ.get("KICAD_CLI")):
        if candidate:
            return candidate
    base = Path(r"C:\Program Files\KiCad")
    if base.is_dir():
        installs = [p for p in base.iterdir() if p.is_dir()]
        for version_dir in sorted(installs, key=_version_key, reverse=True):
            cli = version_dir / "bin" / "kicad-cli.exe"
            if cli.is_file():
                return str(cli)
    found = shutil.which("kicad-cli")
    if found:
        return found
    raise ReleaseError("kicad-cli not found: install KiCad or set KICAD_CLI")


def run(cmd: list[str], cwd: Path | None = None, ok_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    """Run a command and return the completed process. Raises ReleaseError
    with the captured output if the exit code is not in ok_codes."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
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


# --------------------------------------------------------------------------
# Release gates.  Each returns None on success or raises ReleaseError.
# --------------------------------------------------------------------------

def gate_git_clean(root: Path) -> None:
    """Require a clean working tree so the release is reproducible from a
    commit. Repo-wide, so it is checked once rather than per board."""
    status = run(["git", "status", "--porcelain"], cwd=root).stdout
    if status.strip():
        listing = "\n".join(status.splitlines()[:10])
        raise ReleaseError("working tree is not clean; commit or stash first:\n" + listing)


def read_rev(project: Project) -> str:
    """Read the REV text variable that the silkscreen and title blocks show."""
    text_vars = json.loads(project.pro.read_text(encoding="utf-8")).get("text_variables", {})
    rev = text_vars.get("REV", "").strip()
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


def read_revs(boards: list[Project]) -> dict[str, str]:
    """Every board's REV, keyed by board name."""
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


def release_tag(project: Project, rev: str) -> str:
    """Tags are per board, so boards can be respun independently."""
    return f"{project.name}-rev{rev}"


def gate_ledger(project: Project, rev: str) -> None:
    """Fail if this board's revision was already released from a different
    commit."""
    tag = release_tag(project, rev)
    probe = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
                cwd=project.root, ok_codes=(0, 1))
    if probe.returncode == 1:
        return  # tag absent: rev unreleased
    tagged, head = probe.stdout.strip(), run(["git", "rev-parse", "HEAD"], cwd=project.root).stdout.strip()
    if tagged != head:
        raise ReleaseError(
            f"{project.name} rev {rev} was already released (tag {tag} -> {tagged[:10]}).\n"
            f"Bump REV in Board Setup -> Text Variables, commit, and rerun."
        )
    # Tag points at HEAD: rebuilding the same release is fine.


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


def export_bom(kicad_cli: str, project: Project, profile: FabProfile,
               out_csv: Path) -> set[str]:
    """Export the BOM in the fab's column format.

    One row per part type. The part-number column tries
    profile.bom_part_fields in order and keeps the first non-empty value.
    The part fields are included in the grouping so parts that differ only
    in part number stay on separate rows.

    The comment column works the same way from profile.bom_comment_fields.
    It matters only on rows the fab cannot resolve automatically -- those are
    matched by hand, and the comment is the only search key the operator
    sees, so a generic library symbol name there ("Q_Dual_PMOS_...") wastes
    the one chance to identify the part.

    Returns every designator the BOM offers, which export_positions uses to
    hold the placement file to the same set."""
    part_fields = list(profile.bom_part_fields)
    comment_fields = list(profile.bom_comment_fields)
    # Value is always exported (it is the fallback for both columns); the
    # rest are whatever the two priority lists between them ask for.
    extra = [f for f in dict.fromkeys(part_fields + comment_fields) if f != "Value"]
    run(
        [
            kicad_cli,
            "sch",
            "export",
            "bom",
            "-o",
            str(out_csv),
            "--fields",
            ",".join(["Value", "Reference", "Footprint"] + extra),
            "--labels",
            ",".join(["Comment", "Designator", "Footprint"] + extra),
            "--group-by",
            ",".join(["Value", "Footprint"] + extra),
            "--exclude-dnp",
            # Spell every reference out. kicad-cli defaults to collapsing
            # runs into ranges ("C1-C3"), which an assembly house reads as
            # one literal designator matching nothing in the placement file,
            # so those parts silently go unassembled.
            "--ref-range-delimiter",
            "",
            str(project.sch),
        ]
    )
    rows = list(csv.reader(out_csv.open(encoding="utf-8")))
    header, body = rows[0], rows[1:]
    # "Value" is exported under the label "Comment", so it is column 0.
    col = {"Value": 0}
    col.update({f: header.index(f) for f in extra})
    fp_col = header.index("Footprint")
    out_rows = [["Comment", "Designator", "Footprint", profile.bom_part_label]]
    for row in body:
        if profile.bom_strip_lib_prefix:
            row[fp_col] = row[fp_col].split(":")[-1]

        def first(fields, _row=row):
            return next((_row[col[f]] for f in fields
                         if f in col and _row[col[f]].strip()), "")

        # Grouping keys include Value and the part fields, so every designator
        # on a row is the same part type and the first one's prefix speaks for
        # all of them.
        prefix = re.match(r"[A-Za-z]+", row[1].split(",")[0].strip())
        if prefix and prefix.group(0) in profile.bom_value_prefixes:
            comment = row[col["Value"]].strip() or first(comment_fields)
        else:
            comment = first(comment_fields)
        out_rows.append([comment, row[1], row[fp_col], first(part_fields)])
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(out_rows)
    # One BOM row carries many designators; --ref-range-delimiter "" above
    # guarantees they are spelled out rather than collapsed into ranges.
    return {ref.strip() for row in out_rows[1:]
            for ref in row[1].split(",") if ref.strip()}


def make_zip(gerber_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(gerber_dir.iterdir()):
            zf.write(f, f.name)


def create_tag(project: Project, rev: str, profile: FabProfile) -> None:
    tag = release_tag(project, rev)
    exists = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                 cwd=project.root, ok_codes=(0, 1))
    if exists.returncode == 0:
        return  # tag already points at HEAD (same-commit rebuild)
    run(["git", "tag", "-a", tag, "-m",
         f"Fab release {project.name} rev {rev} ({profile.name})"],
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
    The repo-wide gates are evaluated once. The document-revision gate
    reads every board, not just the ones being released."""
    root = all_boards[0].root
    passed = _report("git tree clean", lambda: gate_git_clean(root))
    try:
        revs = read_revs(all_boards)
        passed &= _report("doc rev in sync", lambda: gate_doc_revision(root, revs))
    except ReleaseError as err:
        passed = False
        print(f"  [FAIL] doc rev in sync: {err}")

    with tempfile.TemporaryDirectory() as tmp:
        for board in boards:
            try:
                rev = read_rev(board)
            except ReleaseError as err:
                passed = False
                print(f"\n{board.name}:\n  [FAIL] REV defined: {err}")
                continue
            print(f"\n{board.name} (REV = {rev}):")
            passed &= _report("rev unspent", lambda b=board, r=rev: gate_ledger(b, r))
            passed &= _report("ERC clean", lambda b=board:
                              gate_erc(kicad_cli, b, Path(tmp) / f"{b.name}-erc.rpt"))
            passed &= _report("DRC clean", lambda b=board:
                              gate_drc(kicad_cli, b, Path(tmp) / f"{b.name}-drc.rpt"))
    print("\npreflight: " + ("ready to release" if passed else "not ready; fix the items above"))
    return passed


def release(kicad_cli: str, project: Project, profile: FabProfile,
            revs: dict[str, str], tag: bool = True) -> None:
    rev = revs[project.name]
    gate_doc_revision(project.root, revs)
    gate_git_clean(project.root)
    gate_ledger(project, rev)

    out_dir = project.root / "fab" / project.name / f"rev{rev}"
    gerber_dir = out_dir / "gerbers"
    if out_dir.exists():
        shutil.rmtree(out_dir)  # same-commit re-release: rebuild from scratch
    out_dir.mkdir(parents=True)

    assembled: set[str] = set()
    steps = [
        ("ERC", lambda: gate_erc(kicad_cli, project, out_dir / "erc.rpt")),
        (
            "DRC + schematic parity",
            lambda: gate_drc(kicad_cli, project, out_dir / "drc.rpt"),
        ),
        (
            "gerbers + drill",
            lambda: export_gerbers_and_drill(kicad_cli, project, profile, gerber_dir),
        ),
        # The BOM runs first: it decides which designators are offered for
        # assembly, and the placement file is then held to that same set.
        (
            "bom.csv",
            lambda: assembled.update(
                export_bom(kicad_cli, project, profile, out_dir / "bom.csv")
            ),
        ),
        (
            "positions.csv",
            lambda: export_positions(
                kicad_cli, project, profile, out_dir / "positions.csv", assembled
            ),
        ),
        (
            "zip",
            lambda: make_zip(
                gerber_dir, out_dir / f"{project.name}-rev{rev}-gerbers.zip"
            ),
        ),
    ]
    if tag:
        steps.append((f"git tag {release_tag(project, rev)}",
                      lambda: create_tag(project, rev, profile)))
    total = len(steps)
    for i, (label, step) in enumerate(steps, start=1):
        print(f"  [{i}/{total}] {label}")
        step()

    tag_note = "" if tag else "  (no tag created)"
    print(f"\nreleased {project.name} rev {rev} -> "
          f"{out_dir.relative_to(project.root)}{tag_note}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produce fab outputs (gerbers/BOM/placement) with revision checks.",
        epilog="--check reports every unmet release condition at once.",
    )
    parser.add_argument("boards", nargs="*", metavar="BOARD",
                        help="board name(s) to act on (default: every board)")
    parser.add_argument("--profile", default="jlcpcb", choices=sorted(PROFILES),
                        help="fab house output format (default: %(default)s)")
    parser.add_argument("--check", action="store_true",
                        help="preflight only: evaluate all release gates, produce no outputs")
    parser.add_argument("--no-tag", action="store_true",
                        help="skip the git tag step, for repeatable test runs")
    parser.add_argument("--sync-doc-rev", action="store_true",
                        help="regenerate docs/design_analysis/revision.tex from REV, then exit")
    parser.add_argument("--kicad-cli", default=None,
                        help="path to kicad-cli (default: autodetect)")
    args = parser.parse_args()

    try:
        all_boards = find_boards()
        boards = find_boards(args.boards) if args.boards else all_boards
        root = all_boards[0].root

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

        revs = read_revs(all_boards)
        for board in boards:
            print(f"\n{board.name}:")
            release(kicad_cli, board, PROFILES[args.profile], revs,
                    tag=not args.no_tag)
        print("\n" + PROFILES[args.profile].upload_notes)
        return 0
    except ReleaseError as err:
        print(f"\nrelease blocked: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
