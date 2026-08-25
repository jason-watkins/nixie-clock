"""FreeCAD part-model tooling for this repo.

    python .claude/skills/freecad/scripts/fc_tool.py <subcommand> [args]

run      Run a Python file under freecadcmd, properly. freecadcmd imports a
         script as a module: __name__ is the file's stem, so a __main__ guard
         never fires and a script called profile.py or imp.py silently shadows
         the standard library; an exception comes back as one line with no
         traceback; three banner lines precede every run; and through a pipe
         its stdout is cp1252, so printing an ohm sign or an arrow raises
         UnicodeEncodeError. This loads the file by path as __main__, prints
         the real traceback, strips the banner and the Qt chatter, puts both
         ends of the pipe on UTF-8 and returns the script's exit status.
         --gui brings FreeCADGui up offscreen first, which ImportGui (colored
         STEP export) needs.
export   Regenerate a part's KiCad model: cad/<part>/export_kicad.py if it has
         one (the WRL parts), else the module's export() under --gui (the
         STEP parts). A STEP whose geometry and colors match the file it
         replaces (only the timestamp and the numbering of entities moved) is
         put back as it was, so git does not see a change that is not one.
step     Read one or more STEP files back under freecadcmd: products,
         colors, and per solid the optimal bounding box, volume and validity.
         --brief gives one line per file, which is how to scan a stock KiCad
         family for its lead-trim convention. A basename is looked up in
         nixie_clock.3dshapes; globs are expanded.
mesh     Read STL (or OBJ, PLY, OFF, 3MF) meshes back under freecadcmd:
         facets, extents, volume, whether the mesh is closed and manifold
         with one orientation and no self-intersections, its shell count,
         and for one closed shell its genus, which is its through-hole
         count. The check on a board body from kicad-cli or a part meshed
         for the printer. --brief gives one line per file. A basename is
         looked up under fab/<board>/rev*/; globs are expanded.
wrl      Read a .wrl back through cad/test_base/vrml.py and summarize it:
         materials by name, counts, extents in mm. The check that a model
         will render with its materials rather than as one gray lump.
parts    List the part directories under cad/ and what each ships.
drawing  Measure a datasheet drawing. Renders one page, or a clip of it given
         in PDF points, to a PNG to look at; reports whether the clip holds
         vector paths and text or only a raster; lists the long horizontal
         and vertical lines (body outlines, in pixels); and, once --x and --y
         name two pixels a known distance apart on each axis, scans rows and
         columns for dark runs and reports them in millimeters. Plain Python:
         PyMuPDF and numpy.

freecadcmd is found at FREECADCMD, else on PATH, else under
C:/Program Files/FreeCAD*, newest version first.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "..", ".."))
CAD = os.path.join(REPO, "cad")
SHAPES = os.path.join(REPO, "pcb", "lib", "nixie_clock.3dshapes")
TRAILER = "__FC_TOOL_EXIT__"
STARTED = "__FC_TOOL_START__"
# freecadcmd parses every --option itself and --pass forwards only one
# token, so the request goes to the child through the environment.
REQUEST = "FC_TOOL_REQUEST"
MODEL_EXT = (".wrl", ".step", ".stp")


# =========================================================================
# inside freecadcmd
# =========================================================================
def _bootstrap(request: dict):
    """Runs under freecadcmd, on the request the parent put in the environment."""
    import traceback

    gui = request["gui"]
    inline = request.get("inline")
    script = os.path.abspath(request["script"]) if request.get("script") else None
    args = request["args"]

    # freecadcmd's embedded Python ignores PYTHONIOENCODING and
    # PYTHONDONTWRITEBYTECODE, so both are settled here, in process. Through
    # a pipe its stdout is cp1252, and a print of any character outside that
    # page (an ohm sign, an arrow) raises UnicodeEncodeError; the traceback
    # reporting it, which quotes the line, then dies the same way. Bytecode is
    # off so a build does not leave __pycache__ in every part directory.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.dont_write_bytecode = True

    status = 0
    try:
        if gui:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import FreeCADGui
            FreeCADGui.showMainWindow()
        # Everything before this line is FreeCAD's own start-up chatter - with
        # the GUI up, some 48 kB of Qt style-sheet complaints - and is dropped.
        print(STARTED, flush=True)
        if inline is not None:
            exec(compile(inline, "<fc_tool>", "exec"),
                 {"__name__": "__main__", "ARGS": args})
        else:
            sys.argv = [script, *args]
            sys.path.insert(0, os.path.dirname(script))
            # A namespace of its own that calls itself __main__, so the
            # script's guard fires, but no runpy: runpy swaps
            # sys.modules["__main__"] for the script's namespace, and
            # FreeCADGuiInit.py runs in whatever __main__ is, expecting the
            # App, Log, Msg... names FreeCADInit.py left in the real one. A
            # script that started the GUI itself (a module's _gui()) failed
            # under the swap with "Cannot create main window" over a
            # NameError there.
            with open(script, encoding="utf-8") as fh:
                code = compile(fh.read(), script, "exec")
            exec(code, {"__name__": "__main__", "__file__": script})
    except SystemExit as exc:
        if exc.code is None:
            status = 0
        elif isinstance(exc.code, int):
            status = exc.code
        else:
            print(exc.code)
            status = 1
    except BaseException:
        traceback.print_exc(file=sys.stdout)
        status = 1
    sys.stdout.flush()
    print(f"{TRAILER} {status}", flush=True)


# =========================================================================
# outside
# =========================================================================
def _freecadcmd() -> str:
    env = os.environ.get("FREECADCMD")
    if env and os.path.exists(env):
        return env
    found = shutil.which("freecadcmd")
    if found:
        return found
    hits = glob.glob("C:/Program Files/FreeCAD*/bin/freecadcmd.exe")
    if not hits:
        sys.exit("freecadcmd.exe not found; set FREECADCMD")

    def version(path):
        # As numbers: sorted as strings, "9.0" would beat "10.0".
        m = re.search(r"FreeCAD ([0-9.]+)[\\/]", path)
        return tuple(int(n) for n in m.group(1).split(".")) if m else (0,)

    return max(hits, key=version)


# What OCCT's STEP writer prints between a script's own lines, and what Qt
# prints when a script brings the GUI up itself (a module's _gui()) after the
# start marker has passed. None of it is the script's, and the one line that
# carries information (the path written) is one the script prints itself.
NOISE = ("****", "** WorkSession", " Step File Name :",
         "Not detached all observers yet",
         "Requested non-existent style parameter token",
         "QOpenGLWidget", "QFontDatabase:", "Note that Qt no longer ships fonts",
         "This plugin does not support", "Main window restored",
         "Show main window", "Toolbars restored")
# The start-up banner goes through the C++ stream, which is not flushed until
# something else writes to it. Without a GUI that is usually the STEP writer,
# so the banner can surface in the middle of a script's output.
BANNER = re.compile(r"^(FreeCAD \d+\.\d+|\(C\) \d{4}-\d{4} FreeCAD contributors"
                    r"|FreeCAD is free and open-source software)", re.I)
# Mesh's topology and self-intersection checks stream their progress through
# the C++ console: a "Checking ......" line, then "(N %)" per percent on
# carriage-returned lines, which universal newlines turn into a line each. The
# last one carries the script's next print on its tail, so the prefix is
# stripped rather than the line dropped. One tab follows each "(N %)"; eating
# more would take the script's own indent with it.
PROGRESS = re.compile(r"^\s*(?:\(\d{1,3} %\)\t?)+")
CHECKING = re.compile(r"^Checking .*\.{3,}\s*$")


def _run_under_freecad(script, args, gui: bool, inline: str = None) -> int:
    env = dict(os.environ)
    env[REQUEST] = json.dumps({"gui": gui, "inline": inline, "args": list(args),
                               "script": os.path.abspath(script) if script else None})
    proc = subprocess.Popen([_freecadcmd(), os.path.abspath(__file__)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            cwd=os.getcwd(), env=env)
    # Only what the script itself prints is shown: everything before STARTED
    # is FreeCAD's start-up chatter (with the GUI up, some 48 kB of Qt
    # style-sheet complaints), everything after TRAILER its shutdown.
    status, started, blank = None, False, True
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith(STARTED):
            started = True
        elif line.startswith(TRAILER):
            status, started = int(line.split()[1]), False
        elif started and not (line.startswith(NOISE) or BANNER.match(line)):
            line = PROGRESS.sub("", line)
            if CHECKING.match(line):
                continue
            # The writer's chatter is fenced by blank lines; with it
            # gone they would run together.
            if line.strip() or not blank:
                print(line, flush=True)
            blank = not line.strip()
    proc.wait()
    if status is None:
        print("  (freecadcmd ended without running the script to completion)")
        return proc.returncode or 1
    return status


def cmd_run(args):
    if not os.path.exists(args.script):
        sys.exit(f"no such file: {args.script}")
    return _run_under_freecad(args.script, args.args, args.gui)


def _part_dirs():
    """Directories under cad/ that hold Python: the parts and the fixture.
    A directory of documents alone (the gitignored cad/boards/) is not one."""
    return sorted(d for d in os.listdir(CAD)
                  if os.path.isdir(os.path.join(CAD, d))
                  and not d.startswith(("_", "."))
                  and any(f.endswith(".py")
                          for f in os.listdir(os.path.join(CAD, d))))


def _part_dir(name: str) -> str:
    path = os.path.join(CAD, name)
    if not os.path.isdir(path):
        sys.exit(f"no part directory cad/{name}; have: {', '.join(_part_dirs())}")
    return path


def _part_info(path: str) -> dict:
    """What a part directory holds: its modules and what it ships."""
    modules = sorted(f[:-3] for f in os.listdir(path)
                     if f.endswith(".py") and f != "export_kicad.py"
                     and not f.startswith("_"))
    info = {"modules": modules, "exporter": None, "ships": []}
    exporter = os.path.join(path, "export_kicad.py")
    if os.path.exists(exporter):
        info["exporter"] = "export_kicad.py"
        src = open(exporter, encoding="utf-8").read()
        stem = re.search(r'^STEM\s*=\s*"([^"]+)"', src, re.M)
        if stem:
            info["ships"].append(stem.group(1) + ".wrl")
        variants = re.search(r"^VARIANTS\s*=\s*\{(.*?)\}", src, re.M | re.S)
        if variants:
            info["ships"] += [name + ".wrl" for name in
                              re.findall(r'"([^"]+)"\s*:', variants.group(1))]
    for mod in modules:
        src = open(os.path.join(path, mod + ".py"), encoding="utf-8").read()
        if "\ndef export(" in src and "ImportGui" in src:
            info["exporter"] = info["exporter"] or f"{mod}.export()"
        for line in src.splitlines():
            if "nixie_clock.3dshapes" not in line:
                continue
            tail = line.split("nixie_clock.3dshapes", 1)[1]
            for ch in "\"'(),":
                tail = tail.replace(ch, " ")
            info["ships"] += [t for t in tail.split() if t.lower().endswith(MODEL_EXT)]
    return info


def cmd_parts(args):
    for name in _part_dirs():
        info = _part_info(os.path.join(CAD, name))
        print(f"  {name:<10} modules: {', '.join(info['modules']) or '-'}")
        print(f"  {'':<10} export:  {info['exporter'] or '-'}")
        if info["ships"]:
            print(f"  {'':<10} ships:   {'; '.join(info['ships'])}")
    return 0


def cmd_export(args):
    path = _part_dir(args.part)
    exporter = os.path.join(path, "export_kicad.py")
    if os.path.exists(exporter):
        return _run_under_freecad(exporter, [], gui=False)
    info = _part_info(path)
    if not info["exporter"]:
        sys.exit(f"cad/{args.part} has neither export_kicad.py nor an export()")
    mod = info["exporter"].split(".")[0]
    targets = [os.path.join(SHAPES, name) for name in info["ships"]]
    before = {t: open(t, "rb").read() for t in targets if os.path.exists(t)}
    shim = os.path.join(path, "__fc_export__.py")
    with open(shim, "w", encoding="utf-8") as f:
        f.write(f"import {mod}\n{mod}.export()\n")
    try:
        status = _run_under_freecad(shim, [], gui=True)
    finally:
        os.remove(shim)
    for target, old in before.items():
        new = open(target, "rb").read()
        if new != old and _step_body(new) == _step_body(old):
            open(target, "wb").write(old)
            print(f"  {os.path.basename(target)}: same geometry and colors "
                  f"as the previous export; previous file kept")
    return status


def _step_body(data: bytes) -> list:
    """A STEP file reduced to what a re-export can change.

    Two exports of the same shape differ in the FILE_NAME timestamp, and in
    the order and numbering of the styling entities at the end (the colour
    blocks for two objects came out swapped between one run and the next).
    Entity numbers are stripped and the entities sorted, so what is left
    differs only when geometry or colour does.
    """
    text = data.decode("latin-1")
    text = re.sub(r"FILE_NAME\([^;]*;", "", text, count=1, flags=re.S)
    entities = [re.sub(r"\s+", "", e) for e in text.split(";")]
    return sorted(re.sub(r"#\d+", "#", e) for e in entities)


# --- step ------------------------------------------------------------------
# Runs inside freecadcmd. ARGS[0] is "1" for --brief, the rest are paths.
STEP_PROBE = r"""
import os
import re

import Part


def fmt(b):
    # round() first: a boolean leaves -5.6e-17 on a face that was at zero,
    # and "%8.3f" alone prints that as -0.000.
    v = [round(x, 3) + 0.0
         for x in (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)]
    return "X %8.3f..%8.3f  Y %8.3f..%8.3f  Z %8.3f..%8.3f" % tuple(v)


brief = ARGS[0] == "1"
for path in ARGS[1:]:
    shape = Part.Shape()
    try:
        shape.read(path)
    except Exception as exc:
        print("  %s: %s" % (os.path.basename(path), exc))
        continue
    # optimalBoundingBox, not BoundBox: on a spline solid the plain one is
    # taken off the control polygon and reads wide.
    whole = shape.optimalBoundingBox()
    if brief:
        print("  %-54s %d solid(s)  %s"
              % (os.path.basename(path), len(shape.Solids), fmt(whole)))
        continue
    text = open(path, "rb").read().decode("latin-1")
    products = re.findall(r"PRODUCT\('([^']*)'", text)
    colours = re.findall(r"COLOUR_RGB\('[^']*',\s*([-\d.E+]+),\s*([-\d.E+]+),"
                         r"\s*([-\d.E+]+)\s*\)", text, re.S)
    print("  %s: %d solid(s), %d face(s), %.0f kB"
          % (os.path.basename(path), len(shape.Solids), len(shape.Faces),
             os.path.getsize(path) / 1024))
    print("  products: %s" % (", ".join(products) or "none"))
    print("  colors:   %s" % ("; ".join(
        "(%.2f, %.2f, %.2f)" % tuple(float(c) for c in rgb) for rgb in colours)
        or "none"))
    for i, solid in enumerate(shape.Solids):
        try:
            bop = solid.check(True) is None
        except Exception:
            bop = False
        print("  [%d] %s  vol %9.3f  faces %3d  valid %s  bop %s"
              % (i, fmt(solid.optimalBoundingBox()), solid.Volume,
                 len(solid.Faces), solid.isValid(), bop))
    print("  all %s" % fmt(whole))
"""


def cmd_step(args):
    paths = []
    for pattern in args.paths:
        hits = glob.glob(pattern)
        if not hits:
            alt = os.path.join(SHAPES, pattern)
            hits = glob.glob(alt)
        if not hits:
            sys.exit(f"no such file: {pattern}")
        paths += hits
    paths = [os.path.abspath(p).replace("\\", "/") for p in sorted(paths)]
    return _run_under_freecad(None, ["1" if args.brief else "0", *paths],
                              gui=False, inline=STEP_PROBE)


# --- mesh ------------------------------------------------------------------
# Runs inside freecadcmd. ARGS[0] is "1" for --brief, the rest are paths.
MESH_PROBE = r"""
import os

import Mesh


def fmt(b):
    v = [round(x, 3) + 0.0
         for x in (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)]
    return "X %8.3f..%8.3f  Y %8.3f..%8.3f  Z %8.3f..%8.3f" % tuple(v)


brief = ARGS[0] == "1"
for path in ARGS[1:]:
    try:
        m = Mesh.Mesh(path)
    except Exception as exc:
        print("  %s: %s" % (os.path.basename(path), exc))
        continue
    closed = m.isSolid()
    manifold = not m.hasNonManifolds()
    oriented = not m.hasNonUniformOrientedFacets()
    clean = not m.hasSelfIntersections()
    shells = len(m.getSeparateComponents())
    # V - E + F is 2 - 2g for one closed shell, so g counts its through-holes:
    # a board body's genus is its drill count. It means nothing for an open
    # or multi-shell mesh, so it is shown only when it does.
    chi = m.CountPoints - m.CountEdges + m.CountFacets
    genus = ((2 - chi) // 2 if closed and manifold and shells == 1 else None)
    verdict = ", ".join(
        [("closed" if closed else "OPEN")]
        + ([] if manifold else ["NON-MANIFOLD"])
        + ([] if oriented else ["MIXED ORIENTATION"])
        + ([] if clean else ["SELF-INTERSECTING"]))
    shown = "-" if genus is None else str(genus)
    if brief:
        print("  %-40s %7d facets  %-8s genus %-4s %s"
              % (os.path.basename(path), m.CountFacets, verdict, shown,
                 fmt(m.BoundBox)))
        continue
    print("  %s: %d facets, %d points, %d edges, %.0f kB"
          % (os.path.basename(path), m.CountFacets, m.CountPoints,
             m.CountEdges, os.path.getsize(path) / 1024))
    print("  %s" % fmt(m.BoundBox))
    print("  %s; %d shell(s); genus %s" % (verdict, shells, shown))
    print("  volume %.3f mm3  area %.3f mm2" % (m.Volume, m.Area))
"""


def cmd_mesh(args):
    paths = []
    for pattern in args.paths:
        hits = glob.glob(pattern)
        if not hits:
            # The board bodies make_release.py writes live one level down
            # in every release directory.
            hits = glob.glob(os.path.join(REPO, "fab", "*", "*", pattern))
        if not hits:
            sys.exit(f"no such file: {pattern}")
        paths += hits
    paths = [os.path.abspath(p).replace("\\", "/") for p in sorted(paths)]
    return _run_under_freecad(None, ["1" if args.brief else "0", *paths],
                              gui=False, inline=MESH_PROBE)


def cmd_wrl(args):
    sys.path.insert(0, os.path.join(CAD, "test_base"))
    import vrml  # noqa: E402

    path = args.path
    if not os.path.exists(path):
        alt = os.path.join(SHAPES, path)
        if not os.path.exists(alt):
            have = sorted(f for f in os.listdir(SHAPES)
                          if f.lower().endswith(".wrl"))
            sys.exit(f"no such file: {args.path}; in nixie_clock.3dshapes: "
                     f"{', '.join(have)}")
        path = alt
    groups = vrml.load(path)
    xs, ys, zs = [], [], []
    print(f"  {os.path.basename(path)}: {len(groups)} material group(s), "
          f"{os.path.getsize(path) / 1024:.0f} kB")
    print(f"  {'material':<16}{'rgb':<20}{'transp':>7}{'points':>8}{'faces':>8}"
          f"   z range (mm)")
    for mat, pts, faces in groups:
        gz = [p[2] for p in pts]
        rgb = ", ".join(f"{c:.2f}" for c in mat.rgb)
        print(f"  {mat.name:<16}{rgb:<20}{mat.transparency:>7.2f}{len(pts):>8}"
              f"{len(faces):>8}   {min(gz):7.2f} .. {max(gz):7.2f}")
        for p in pts:
            xs.append(p[0])
            ys.append(p[1])
            zs.append(p[2])
    print(f"  extents mm: x {min(xs):.3f}..{max(xs):.3f} ({max(xs) - min(xs):.3f})  "
          f"y {min(ys):.3f}..{max(ys):.3f} ({max(ys) - min(ys):.3f})  "
          f"z {min(zs):.3f}..{max(zs):.3f} ({max(zs) - min(zs):.3f})")
    unnamed = sum(1 for m, _, _ in groups if m.name in ("default", ""))
    if unnamed:
        print(f"  WARNING: {unnamed} group(s) carry no DEF name; vrml.py reads "
              f"them as default gray")
    return 0


# --- drawing ---------------------------------------------------------------
DRAWING_DPI = 600
INK = 128  # gray level below which a pixel is ink


def _runs(mask) -> list:
    """(start, end) index pairs of consecutive True in a 1-D bool array."""
    import numpy as np
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def _long_lines(dark, axis: int, frac: float) -> list:
    """(center px, thickness px, longest run px) of each line across `axis`.

    A drawn line is a band of consecutive rows (axis 0) or columns (axis 1)
    each inked across more than `frac` of the clip. The band is reported
    once, at its center, which is the coordinate to scale from: a 20 px line
    at 1200 dpi is 0.4 mm of paper and its edges are not the dimension.
    """
    counts = dark.sum(axis=1 - axis)
    limit = frac * dark.shape[1 - axis]
    return [((a + b - 1) / 2, b - a, int(counts[a:b].max()))
            for a, b in _runs(counts > limit)]


class _Axis:
    """Pixel index <-> millimeter along one image axis."""

    def __init__(self, per_mm: float, origin):
        self.per_mm = per_mm
        self.origin = origin  # pixel index of 0 mm, None if not yet known

    @classmethod
    def from_pair(cls, p0: float, p1: float, mm: float):
        """Two pixels a known distance apart; the origin is their midpoint,
        which for a body's two edges is the body's center."""
        return cls(abs(p1 - p0) / mm, (p0 + p1) / 2)

    def mm(self, px: float) -> float:
        return (px - self.origin) / self.per_mm

    def px(self, mm: float) -> int:
        return int(round(self.origin + mm * self.per_mm))


def _scan(dark, axis, along, across, index: int, label: str, floor: int = 2):
    """Print the ink runs along one row (axis 0) or column (axis 1), in mm."""
    if not 0 <= index < dark.shape[axis]:
        print(f"  {label}: pixel {index} is outside the clip")
        return
    line = dark[index, :] if axis == 0 else dark[:, index]
    print(f"  {label} (px {index}):")
    for a, b in _runs(line):
        if b - a < floor:
            continue
        print(f"    {'x' if axis == 0 else 'y'} {along.mm(a):+.3f} .. "
              f"{along.mm(b - 1):+.3f}  mid {along.mm((a + b - 1) / 2):+.4f}"
              f"  (w {(b - a) / along.per_mm:.3f}, {b - a} px)")


def cmd_drawing(args):
    try:
        import fitz  # PyMuPDF
        import numpy as np
    except ImportError as exc:
        sys.exit(f"drawing needs PyMuPDF and numpy in this Python: {exc}")
    if not os.path.exists(args.pdf):
        sys.exit(f"no such file: {args.pdf}")
    doc = fitz.open(args.pdf)
    if not 1 <= args.page <= len(doc):
        sys.exit(f"{os.path.basename(args.pdf)} has {len(doc)} page(s)")
    page = doc[args.page - 1]
    clip = (fitz.Rect(*args.clip) if args.clip else page.rect) & page.rect
    if clip.is_empty:
        sys.exit("the clip lies outside the page")
    k = args.dpi / 72.0  # px per point

    pix = page.get_pixmap(clip=clip, dpi=args.dpi, colorspace=fitz.csGRAY,
                          alpha=False)
    png = args.png or os.path.join(
        tempfile.gettempdir(), "fc_tool",
        f"{os.path.splitext(os.path.basename(args.pdf))[0]}_p{args.page}.png")
    os.makedirs(os.path.dirname(os.path.abspath(png)), exist_ok=True)
    pix.save(png)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    dark = gray < INK

    print(f"  {os.path.basename(args.pdf)} page {args.page} of {len(doc)}: "
          f"{page.rect.width:.0f} x {page.rect.height:.0f} pt")
    print(f"  clip ({clip.x0:.1f}, {clip.y0:.1f})-({clip.x1:.1f}, {clip.y1:.1f}) pt"
          f"  ->  {pix.width} x {pix.height} px at {args.dpi} dpi "
          f"({k:.3f} px/pt); image x right, y down")
    print(f"  png: {png}")

    # Vector content decides the method: paths and words give exact
    # coordinates in points; a drawing that is an embedded image gives
    # nothing here and has to be measured off the pixels.
    paths = [d for d in page.get_drawings()
             if fitz.Rect(d["rect"]).intersects(clip)]
    words = [w for w in page.get_text("words")
             if fitz.Rect(w[:4]).intersects(clip)]
    print(f"  vector content in the clip: {len(paths)} path(s), "
          f"{len(words)} word(s)"
          + ("" if paths else "  - a raster drawing; measure the pixels"))
    if args.words:
        for x0, y0, x1, y1, text, *_ in words:
            print(f"    ({x0:7.1f}, {y0:7.1f})-({x1:7.1f}, {y1:7.1f}) pt  {text}")
    if args.vectors:
        for d in paths:
            for item in d["items"]:
                kind = item[0]
                if kind == "l":
                    a, b = item[1], item[2]
                    print(f"    line ({a.x:7.2f}, {a.y:7.2f})-({b.x:7.2f}, {b.y:7.2f}) pt")
                elif kind == "re":
                    r = item[1]
                    print(f"    rect ({r.x0:7.2f}, {r.y0:7.2f})-({r.x1:7.2f}, {r.y1:7.2f}) pt")
                elif kind == "c":
                    a, b = item[1], item[4]
                    print(f"    curve ({a.x:7.2f}, {a.y:7.2f})-({b.x:7.2f}, {b.y:7.2f}) pt")
                else:
                    r = fitz.Rect(d["rect"])
                    print(f"    {kind} within ({r.x0:7.2f}, {r.y0:7.2f})-"
                          f"({r.x1:7.2f}, {r.y1:7.2f}) pt")

    x_axis = _Axis.from_pair(*args.x) if args.x else None
    y_axis = _Axis.from_pair(*args.y) if args.y else None
    # One --x or --y serves both axes at the same px/mm; the other origin
    # then has to come from --origin.
    if x_axis and not y_axis:
        y_axis = _Axis(x_axis.per_mm, None)
    if y_axis and not x_axis:
        x_axis = _Axis(y_axis.per_mm, None)
    if args.origin and x_axis:
        x_axis.origin, y_axis.origin = args.origin
    if x_axis:
        print(f"  scale: x {x_axis.per_mm:.1f} px/mm, y {y_axis.per_mm:.1f} px/mm; "
              f"origin px ({x_axis.origin}, {y_axis.origin})")

    if args.lines > 0:
        for axis, name in ((0, "horizontal"), (1, "vertical")):
            found = _long_lines(dark, axis, args.lines)
            print(f"  {name} lines inked over {args.lines:.0%} of the clip: "
                  f"{len(found)}")
            coord = "y" if axis == 0 else "x"
            ref = y_axis if axis == 0 else x_axis
            for center, thick, length in found:
                pt = (clip.y0 if axis == 0 else clip.x0) + center / k
                mm = (f"   {coord} {ref.mm(center):+.3f} mm"
                      if ref and ref.origin is not None else "")
                print(f"    {coord} px {center:8.1f}  ({pt:7.2f} pt)  "
                      f"{thick:3d} px thick, {length} px long{mm}")

    if (args.row or args.col) and not (x_axis and y_axis
                                       and x_axis.origin is not None
                                       and y_axis.origin is not None):
        sys.exit("--row/--col need the scale: --x PX0 PX1 MM and --y PY0 PY1 MM "
                 "(or one of them plus --origin PX PY)")
    for y in args.row:
        _scan(dark, 0, x_axis, y_axis, y_axis.px(y), f"row y = {y:+.3f} mm")
    for x in args.col:
        _scan(dark, 1, y_axis, x_axis, x_axis.px(x), f"column x = {x:+.3f} mm")
    return 0


def main():
    if REQUEST in os.environ:
        _bootstrap(json.loads(os.environ[REQUEST]))
        return
    # The child prints UTF-8 now; this end of the pipe has to take it, and
    # under the harness this stdout is a cp1252 pipe too.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a script under freecadcmd")
    p.add_argument("--gui", action="store_true",
                   help="start FreeCADGui offscreen first (ImportGui needs it)")
    p.add_argument("script")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("export", help="regenerate a part's KiCad model")
    p.add_argument("part", help="directory name under cad/")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("step", help="read STEP files back: solids, extents, colors")
    p.add_argument("--brief", action="store_true", help="one line per file")
    p.add_argument("paths", nargs="+",
                   help="files or globs, or basenames under nixie_clock.3dshapes")
    p.set_defaults(func=cmd_step)

    p = sub.add_parser("mesh", help="read STL/OBJ/PLY meshes back: closed, "
                                    "manifold, genus, extents")
    p.add_argument("--brief", action="store_true", help="one line per file")
    p.add_argument("paths", nargs="+",
                   help="files or globs, or a basename under fab/<board>/rev*/")
    p.set_defaults(func=cmd_mesh)

    p = sub.add_parser("wrl", help="summarize a .wrl via cad/test_base/vrml.py")
    p.add_argument("path", help="file, or a basename under nixie_clock.3dshapes")
    p.set_defaults(func=cmd_wrl)

    sub.add_parser("parts", help="list part directories").set_defaults(func=cmd_parts)

    p = sub.add_parser("drawing",
                       help="measure a datasheet drawing (PyMuPDF and numpy)")
    p.add_argument("pdf")
    p.add_argument("page", type=int, help="1-based page number")
    p.add_argument("--clip", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"),
                   help="region in PDF points (72 per inch, origin top left)")
    p.add_argument("--dpi", type=int, default=DRAWING_DPI,
                   help=f"render resolution (default {DRAWING_DPI})")
    p.add_argument("--png", help="where to write the render "
                                 "(default: <temp>/fc_tool/<pdf>_p<page>.png)")
    p.add_argument("--lines", type=float, default=0.25, metavar="FRAC",
                   help="list rows and columns inked over this fraction of the "
                        "clip (default 0.25; 0 skips)")
    p.add_argument("--words", action="store_true",
                   help="list the vector text in the clip, with positions")
    p.add_argument("--vectors", action="store_true",
                   help="list the vector paths in the clip, in points")
    p.add_argument("--x", nargs=3, type=float, metavar=("PX0", "PX1", "MM"),
                   help="two x pixels a known MM apart; 0 mm is their midpoint")
    p.add_argument("--y", nargs=3, type=float, metavar=("PY0", "PY1", "MM"),
                   help="the same along y")
    p.add_argument("--origin", nargs=2, type=float, metavar=("PX", "PY"),
                   help="pixel of the mm origin, overriding the midpoints")
    p.add_argument("--row", nargs="+", type=float, default=[], metavar="MM",
                   help="scan these rows (y, mm) for ink runs")
    p.add_argument("--col", nargs="+", type=float, default=[], metavar="MM",
                   help="scan these columns (x, mm) for ink runs")
    p.set_defaults(func=cmd_drawing)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


# freecadcmd imports this file as a module (__name__ == "fc_tool"), so the
# bootstrap branch has to be reachable without the guard.
if __name__ == "__main__" or REQUEST in os.environ:
    main()
