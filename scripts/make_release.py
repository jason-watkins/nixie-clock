#!/usr/bin/env python3
"""Produce fabrication outputs (gerbers, drill, BOM, pick-and-place) for
this KiCad project.

A release requires a clean git tree, passing ERC and DRC, and a revision
with no existing release tag. The revision is the project text variable
REV (Board Setup -> Text Variables); title blocks and silkscreen render it
as ${REV}. A release exports to fab/rev<REV>/ and tags HEAD as rev<REV>.
If that tag exists at another commit, the release fails: bump REV, commit,
rerun. Rerunning at the tagged commit rebuilds the same release.

Usage:
    python scripts/make_release.py --check   # evaluate all gates, write nothing
    python scripts/make_release.py           # release (default profile: jlcpcb)
    python scripts/make_release.py --no-tag  # export only; repeatable test runs

Output tree:
    fab/rev<REV>/
        gerbers/                         gerber and drill files
        <project>-rev<REV>-gerbers.zip   upload this to the fab
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

def find_kicad_cli(explicit: str | None) -> str:
    """Locate kicad-cli: --kicad-cli flag, KICAD_CLI env, PATH, then the
    newest version under C:\\Program Files\\KiCad."""
    for candidate in (explicit, os.environ.get("KICAD_CLI"), shutil.which("kicad-cli")):
        if candidate:
            return candidate
    base = Path(r"C:\Program Files\KiCad")
    if base.is_dir():
        for version_dir in sorted(base.iterdir(), reverse=True):
            cli = version_dir / "bin" / "kicad-cli.exe"
            if cli.is_file():
                return str(cli)
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
    """KiCad project files plus the git root."""
    root: Path        # git repository root
    pro: Path         # .kicad_pro
    pcb: Path         # .kicad_pcb
    sch: Path         # root .kicad_sch


def find_project() -> Project:
    """Locate the single KiCad project: exactly one .kicad_pro under the
    git root, with .kicad_pcb and .kicad_sch siblings."""
    root = Path(run(["git", "rev-parse", "--show-toplevel"]).stdout.strip())
    candidates = [p for p in root.rglob("*.kicad_pro") if "fab" not in p.parts]
    if len(candidates) != 1:
        names = ", ".join(str(p.relative_to(root)) for p in candidates) or "none"
        raise ReleaseError(f"expected exactly one .kicad_pro in the repo, found: {names}")
    pro = candidates[0]
    pcb, sch = pro.with_suffix(".kicad_pcb"), pro.with_suffix(".kicad_sch")
    for f in (pcb, sch):
        if not f.is_file():
            raise ReleaseError(f"project file missing: {f}")
    return Project(root=root, pro=pro, pcb=pcb, sch=sch)


# --------------------------------------------------------------------------
# Release gates.  Each returns None on success or raises ReleaseError.
# --------------------------------------------------------------------------

def gate_git_clean(project: Project) -> None:
    """Require a clean working tree so the release is reproducible from a
    commit."""
    status = run(["git", "status", "--porcelain"], cwd=project.root).stdout
    if status.strip():
        listing = "\n".join(status.splitlines()[:10])
        raise ReleaseError("working tree is not clean; commit or stash first:\n" + listing)


def read_rev(project: Project) -> str:
    """Read the REV text variable that the silkscreen and title blocks show."""
    text_vars = json.loads(project.pro.read_text(encoding="utf-8")).get("text_variables", {})
    rev = text_vars.get("REV", "").strip()
    if not rev:
        raise ReleaseError(
            "project text variable 'REV' is not set.\n"
            "Define it in Board Setup -> Text Variables (e.g. REV = A); the\n"
            "silkscreen and title blocks should reference it as ${REV}."
        )
    if not rev.replace(".", "").isalnum():
        raise ReleaseError(f"REV {rev!r} contains characters unsuitable for a tag name")
    return rev


def gate_ledger(project: Project, rev: str) -> None:
    """Fail if this revision was already released from a different commit."""
    tag = f"rev{rev}"
    probe = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
                cwd=project.root, ok_codes=(0, 1))
    if probe.returncode == 1:
        return  # tag absent: rev unreleased
    tagged, head = probe.stdout.strip(), run(["git", "rev-parse", "HEAD"], cwd=project.root).stdout.strip()
    if tagged != head:
        raise ReleaseError(
            f"rev {rev} was already released (tag {tag} -> {tagged[:10]}).\n"
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
    tag = f"rev{rev}"
    exists = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                 cwd=project.root, ok_codes=(0, 1))
    if exists.returncode == 0:
        return  # tag already points at HEAD (same-commit rebuild)
    run(["git", "tag", "-a", tag, "-m", f"Fab release rev {rev} ({profile.name})"],
        cwd=project.root)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def preflight(kicad_cli: str, project: Project) -> bool:
    """Run every gate and print each result; return overall pass/fail.

    A release stops at the first failure; preflight reports all of them."""
    passed = True
    rev = None
    with tempfile.TemporaryDirectory() as tmp:
        checks = [
            ("git tree clean", lambda: gate_git_clean(project)),
            ("REV defined", lambda: read_rev(project)),
            ("rev unspent", lambda: gate_ledger(project, read_rev(project))),
            ("ERC clean", lambda: gate_erc(kicad_cli, project, Path(tmp) / "erc.rpt")),
            ("DRC clean", lambda: gate_drc(kicad_cli, project, Path(tmp) / "drc.rpt")),
        ]
        for label, check in checks:
            try:
                result = check()
                rev = result or rev
                print(f"  [pass] {label}" + (f"  (REV = {rev})" if label == "REV defined" else ""))
            except ReleaseError as err:
                passed = False
                print(f"  [FAIL] {label}: {err}")
    print("\npreflight: " + ("ready to release" if passed else "not ready; fix the items above"))
    return passed


def release(kicad_cli: str, project: Project, profile: FabProfile,
            tag: bool = True) -> None:
    gate_git_clean(project)
    rev = read_rev(project)
    gate_ledger(project, rev)

    out_dir = project.root / "fab" / f"rev{rev}"
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
                gerber_dir, out_dir / f"{project.pro.stem}-rev{rev}-gerbers.zip"
            ),
        ),
    ]
    if tag:
        steps.append((f"git tag rev{rev}", lambda: create_tag(project, rev, profile)))
    total = len(steps)
    for i, (label, step) in enumerate(steps, start=1):
        print(f"  [{i}/{total}] {label}")
        step()

    tag_note = "" if tag else "  (no tag created)"
    print(f"\nreleased rev {rev} -> {out_dir}{tag_note}\n")
    print(profile.upload_notes)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produce fab outputs (gerbers/BOM/placement) with revision checks.",
        epilog="--check reports every unmet release condition at once.",
    )
    parser.add_argument("--profile", default="jlcpcb", choices=sorted(PROFILES),
                        help="fab house output format (default: %(default)s)")
    parser.add_argument("--check", action="store_true",
                        help="preflight only: evaluate all release gates, produce no outputs")
    parser.add_argument("--no-tag", action="store_true",
                        help="skip the git tag step, for repeatable test runs")
    parser.add_argument("--kicad-cli", default=None,
                        help="path to kicad-cli (default: autodetect)")
    args = parser.parse_args()

    try:
        kicad_cli = find_kicad_cli(args.kicad_cli)
        project = find_project()
        if args.check:
            return 0 if preflight(kicad_cli, project) else 1
        release(kicad_cli, project, PROFILES[args.profile], tag=not args.no_tag)
        return 0
    except ReleaseError as err:
        print(f"\nrelease blocked: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
