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

* Pick-and-place rotations use KiCad's footprint zero, which differs from
  JLCPCB's zero for some packages. Check orientations in the fab's DFM
  viewer before ordering assembly.
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
        bom_part_label: Output header for the part-number column.
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
    bom_part_label: str
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
    bom_part_label="LCSC Part #",
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


def export_positions(kicad_cli: str, project: Project, profile: FabProfile,
                     out_csv: Path) -> None:
    """Export the position file, then rewrite it into the fab's CPL format."""
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
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(profile.pos_columns.keys())
        for row in rows:
            record = [row[src] for src in profile.pos_columns.values()]
            side_index = list(profile.pos_columns).index("Layer")
            record[side_index] = profile.pos_side_names.get(
                record[side_index].lower(), record[side_index])
            writer.writerow(record)


def export_bom(kicad_cli: str, project: Project, profile: FabProfile, out_csv: Path) -> None:
    """Export the BOM in the fab's column format.

    One row per part type. The part-number column tries
    profile.bom_part_fields in order and keeps the first non-empty value.
    The part fields are included in the grouping so parts that differ only
    in part number stay on separate rows."""
    part_fields = list(profile.bom_part_fields)
    run(
        [
            kicad_cli,
            "sch",
            "export",
            "bom",
            "-o",
            str(out_csv),
            "--fields",
            ",".join(["Value", "Reference", "Footprint"] + part_fields),
            "--labels",
            ",".join(["Comment", "Designator", "Footprint"] + part_fields),
            "--group-by",
            ",".join(["Value", "Footprint"] + part_fields),
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
    part_cols = [header.index(f) for f in part_fields]
    fp_col = header.index("Footprint")
    out_rows = [["Comment", "Designator", "Footprint", profile.bom_part_label]]
    for row in body:
        if profile.bom_strip_lib_prefix:
            row[fp_col] = row[fp_col].split(":")[-1]
        part = next((row[c] for c in part_cols if row[c].strip()), "")
        out_rows.append([row[0], row[1], row[fp_col], part])
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(out_rows)


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
        (
            "positions.csv",
            lambda: export_positions(
                kicad_cli, project, profile, out_dir / "positions.csv"
            ),
        ),
        (
            "bom.csv",
            lambda: export_bom(kicad_cli, project, profile, out_dir / "bom.csv"),
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
