"""The clock's boards, each as a VarSet the hand-built case model reads.

Source: pcb/<board>/<board>.kicad_pcb, with REV and STEP from the matching
.kicad_pro. The KiCad projects are the source of truth and no board dimension
here is typed in. The face board also carries its tube envelopes, which come
from the part models (cad/in12, cad/ins1) that hold the manufacturer drawings.

One VarSet per board, named by BOARDS below (FaceBoard, MainBoard, HvBoard),
all in the same frame convention:

    origin at the centre of the board's Edge.Cuts, X as KiCad draws it,
    Y negated (KiCad's grows downward), Z = 0 on the F.Cu face, +Z toward
    the components on that face. For the face board that is out of the clock.

`kicad-cli pcb export step --user-origin=<origin_x>x<origin_y>mm` writes the
same X and Y with Z = 0 on the underside, so such an export sits at
Z = -board_t in this frame.

Each VarSet encodes a topology, and values() asserts it before it writes a
number:

    Edge.Cuts   four axis-parallel lines and four equal quarter arcs, one
                closed loop: a rounded rectangle
    holes       four MountingHole footprints in a rectangle centred on the
                board, one drilled pad each, one drill size
    face only   four IN-12 at rotation 0 or 180, two INS-1

Anything else stops the update. A fifth hole or a cutout is a change to the
case, made on purpose, and the property tables below are where it starts.

Properties, by group, on every board:

    Board    board_w board_h corner_r board_t
    Holes    hole_dx hole_dy hole_d
    Source   origin_x origin_y       KiCad coordinates of this frame's origin
             source_file source_rev source_step source_sha

and on FaceBoard:

    Tubes    tube1..4_x tube1..4_y   ordered by x, left to right seen from
                                     the front
             tube_w tube_h           envelope at rotation 0: in12.BODY_X,
                                     in12.BODY_Y
             colon1..2_x colon1..2_y upper first
             colon_d                 2 * ins1.BARREL_R

Positions are App::PropertyDistance, which carries a sign; sizes are
App::PropertyLength. A sketch constraint binds to one with an expression such
as `MainBoard.hole_dx / 2`.

update() changes values in place and only ever adds properties. It never
deletes or recreates a VarSet: expressions bind to it by name, and a
recreated object leaves every one of them dangling. A value the user edited by
hand is written back and shows in the printed table as a change.

Board bodies
------------

update() also carries the bare board of each project into the document, as a
Part::Feature named <VarSet>Body (FaceBoardBody, MainBoardBody, HvBoardBody):
outline, mounting holes and pad drills, plus the 3D models of the components
listed in BOARDS (`components`, reference designators, kicad-cli wildcards
allowed), which is how MainBoardBody carries J101 for the USB slot and nothing
else. The solid is `kicad-cli pcb export step --user-origin=<origin>` with
`--board-only`, or `--component-filter` for a board with a component list,
written to cad/case/bodies/<project>.step (gitignored) beside a .cmd file
holding the arguments; it is re-exported whenever the .kicad_pcb is newer or
the arguments changed. The board is the dielectric core alone, 1.51 thick
against the stackup's 1.60; the whole shape is shifted so the board's F.Cu
face lies on Z = 0 of the VarSet frame, and its underside therefore sits 0.09
short of -board_t. Components ride on top in their footprint positions.

The object's Placement is yours. It is identity on creation and untouched on
every later update, which replaces the Shape only, so put the board where it
sits in the case through the Placement (expressions allowed). In FaceFrame,
whose sketches lie on XZ with the front toward -Y, the face board goes to

    Placement = App.Placement(App.Vector(0, -VarSet.face_depth, 0),
                              App.Rotation(App.Vector(1, 0, 0), 90))

i.e. rotate the VarSet frame 90 deg about X (its +Z, out of the clock, becomes
-Y) and translate to the pocket floor. The board color is set on creation
only; component faces are tinted gray on every update, since they follow the
shape.

The export is an independent read of the same .kicad_pcb, so update() checks
it against the VarSet: the board solid (the largest by volume) has extents
board_w x board_h about the origin, and its cylindrical faces of drill hole_d
number four. A disagreement stops the update.

GUI, with the case document active:

    import importlib, sys
    SRC = "C:/Code/nixe_clock/cad/case"
    SRC in sys.path or sys.path.insert(0, SRC)
    import boards
    importlib.reload(boards)
    boards.update()                      # every board, VarSets and bodies
    boards.update(boards=["main"])       # one of them
    boards.update(bodies=False)          # VarSets only, no kicad-cli

Headless:

    python .claude/skills/freecad/scripts/fc_tool.py run cad/case/boards.py [BOARD ...]
        prints the values it would write, for every board or the ones named
    python .claude/skills/freecad/scripts/fc_tool.py run cad/case/boards.py DOC.FCStd [BOARD ...]
        opens DOC (or creates it), updates the VarSets and bodies, saves
"""

import glob
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from typing import NamedTuple

CAD = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPO = os.path.normpath(os.path.join(CAD, ".."))

if CAD not in sys.path:
    sys.path.insert(0, CAD)
import kicad_sexpr

# A reload of this module in the GUI does not reload its imports; do it here
# so the macro's single reload is enough.
importlib.reload(kicad_sexpr)

TOL = 1e-3  # mm, for the topology checks; KiCad writes six decimals
BODY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bodies")
BODY_TOL = 0.05  # mm, export extents against the VarSet; STEP is written to 1e-6
BODY_COLOR = (0.08, 0.36, 0.20)  # solder mask green, applied on creation only
PART_COLOR = (0.60, 0.60, 0.58)  # component models, applied on every update

LENGTH = "App::PropertyLength"
DISTANCE = "App::PropertyDistance"
STRING = "App::PropertyString"


class Board(NamedTuple):
    """A KiCad project and the VarSet that mirrors it."""

    project: str  # pcb/<project>/<project>.kicad_pcb
    varset: str  # the VarSet's Name, which expressions reference
    tubes: bool  # carries the IN-12 and INS-1 positions and envelopes
    components: tuple = ()  # reference designators whose 3D models ride on the body


BOARDS = {
    "face": Board("face", "FaceBoard", tubes=True),
    "main": Board("main", "MainBoard", tubes=False, components=("J101",)),  # USB-C, for the slot
    "hv": Board("hv", "HvBoard", tubes=False),
}


def _tube_properties() -> tuple:
    props = []
    for i in range(1, 5):
        ordinal = f"IN-12 {i} of 4, left to right seen from the front"
        props.append((f"tube{i}_x", DISTANCE, "Tubes", f"{ordinal}: footprint origin X"))
        props.append((f"tube{i}_y", DISTANCE, "Tubes", f"{ordinal}: footprint origin Y"))
    props.append(("tube_w", LENGTH, "Tubes",
                  "IN-12 glass envelope along X at rotation 0 (in12.BODY_X)"))
    props.append(("tube_h", LENGTH, "Tubes",
                  "IN-12 glass envelope along Y at rotation 0 (in12.BODY_Y)"))
    for i, place in ((1, "upper"), (2, "lower")):
        props.append((f"colon{i}_x", DISTANCE, "Tubes", f"INS-1 {place}: footprint origin X"))
        props.append((f"colon{i}_y", DISTANCE, "Tubes", f"INS-1 {place}: footprint origin Y"))
    props.append(("colon_d", LENGTH, "Tubes", "INS-1 barrel diameter (2 * ins1.BARREL_R)"))
    return tuple(props)


# (name, property type, group, tooltip)
BOARD_PROPERTIES = (
    ("board_w", LENGTH, "Board", "Edge.Cuts extent along X"),
    ("board_h", LENGTH, "Board", "Edge.Cuts extent along Y"),
    ("corner_r", LENGTH, "Board", "Edge.Cuts corner radius"),
    ("board_t", LENGTH, "Board", "Board thickness, (general (thickness)) in the .kicad_pcb"),
    ("hole_dx", LENGTH, "Holes", "Mounting hole pitch along X"),
    ("hole_dy", LENGTH, "Holes", "Mounting hole pitch along Y"),
    ("hole_d", LENGTH, "Holes", "Mounting hole drill"),
)
TUBE_PROPERTIES = _tube_properties()
SOURCE_PROPERTIES = (
    ("origin_x", LENGTH, "Source",
     "KiCad X of this frame's origin: the --user-origin for a kicad-cli export"),
    ("origin_y", LENGTH, "Source",
     "KiCad Y of this frame's origin: the --user-origin for a kicad-cli export"),
    ("source_file", STRING, "Source", "The .kicad_pcb these values were read from"),
    ("source_rev", STRING, "Source", "REV text variable of the KiCad project"),
    ("source_step", STRING, "Source", "STEP text variable of the KiCad project"),
    ("source_sha", STRING, "Source", "SHA-256 of the .kicad_pcb, first 12 hex digits"),
)


def properties(board: Board) -> tuple:
    """The property table of one board's VarSet, in display order."""
    extra = TUBE_PROPERTIES if board.tubes else ()
    return BOARD_PROPERTIES + extra + SOURCE_PROPERTIES


def pcb_path(board: Board) -> str:
    return os.path.join(REPO, "pcb", board.project, f"{board.project}.kicad_pcb")


def pro_path(board: Board) -> str:
    return os.path.join(REPO, "pcb", board.project, f"{board.project}.kicad_pro")


def body_path(board: Board) -> str:
    return os.path.join(BODY_DIR, f"{board.project}.step")


def body_name(board: Board) -> str:
    return f"{board.varset}Body"


class BoardError(ValueError):
    """The board does not have the topology this module encodes."""


def _expect(cond: bool, message: str):
    if not cond:
        raise BoardError(message)


# =========================================================================
# reading a board
# =========================================================================
def _xy(node) -> tuple:
    return float(node[1]), float(node[2])


def _layer(item):
    layer = kicad_sexpr.kid(item, "layer")
    return layer[1] if layer else None


def _corner_radius(s, m, e) -> float:
    """Radius of an axis-aligned quarter arc from s to e through m.

    The endpoints are exact in the file and sit one radius apart along each
    axis; the midpoint is what KiCad rounded, so it only checks the arc.
    """
    r = abs(e[0] - s[0])
    _expect(abs(abs(e[1] - s[1]) - r) < TOL,
            f"Edge.Cuts arc {s} to {e} is not an axis-aligned quarter circle")
    centres = ((e[0], s[1]), (s[0], e[1]))
    _expect(any(abs(math.hypot(m[0] - cx, m[1] - cy) - r) < TOL for cx, cy in centres),
            f"Edge.Cuts arc {s} to {e} does not pass through its midpoint {m} as a quarter circle")
    return r


def _outline(root) -> dict:
    """Extents and corner radius of Edge.Cuts, checked to be a rounded rectangle."""
    lines, arcs, other = [], [], []
    for item in root[1:]:
        if not isinstance(item, list) or not item or not str(item[0]).startswith("gr_"):
            continue
        if _layer(item) != "Edge.Cuts":
            continue
        if item[0] == "gr_line":
            lines.append((_xy(kicad_sexpr.kid(item, "start")),
                          _xy(kicad_sexpr.kid(item, "end"))))
        elif item[0] == "gr_arc":
            arcs.append((_xy(kicad_sexpr.kid(item, "start")),
                         _xy(kicad_sexpr.kid(item, "mid")),
                         _xy(kicad_sexpr.kid(item, "end"))))
        else:
            other.append(item[0])
    _expect(not other, f"Edge.Cuts carries {sorted(set(other))}; only gr_line and gr_arc are read")
    _expect(len(lines) == 4 and len(arcs) == 4,
            f"Edge.Cuts has {len(lines)} lines and {len(arcs)} arcs; a rounded rectangle has 4 and 4")
    for a, b in lines:
        _expect(abs(a[0] - b[0]) < TOL or abs(a[1] - b[1]) < TOL,
                f"Edge.Cuts line {a} to {b} is not axis-parallel")

    ends = [a for a, _ in lines] + [b for _, b in lines]
    ends += [s for s, _, _ in arcs] + [e for _, _, e in arcs]
    used = Counter((round(x, 3), round(y, 3)) for x, y in ends)
    _expect(len(used) == 8 and all(n == 2 for n in used.values()),
            "Edge.Cuts is not one closed loop of lines and arcs")

    radii = [_corner_radius(s, m, e) for s, m, e in arcs]
    _expect(max(radii) - min(radii) < TOL, f"Edge.Cuts corner radii differ: {radii}")

    xs = [x for x, _ in ends]
    ys = [y for _, y in ends]
    return {"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "r": radii[0]}


def _drill(pad) -> float:
    drill = kicad_sexpr.kid(pad, "drill")
    _expect(drill is not None and len(drill) > 1 and drill[1] != "oval",
            "mounting hole pad has no round drill")
    return float(drill[1])


def _footprints(root) -> list:
    out = []
    for fp in kicad_sexpr.kids(root, "footprint"):
        lib, _, name = str(fp[1]).partition(":")
        at = kicad_sexpr.kid(fp, "at")
        ref = next((p[2] for p in kicad_sexpr.kids(fp, "property")
                    if len(p) > 2 and p[1] == "Reference"), "?")
        out.append({
            "ref": ref, "lib": lib, "name": name,
            "x": float(at[1]), "y": float(at[2]),
            "rot": float(at[3]) if len(at) > 3 else 0.0,
            "pads": kicad_sexpr.kids(fp, "pad"),
        })
    return out


def _holes(fps: list, cx: float, cy: float) -> dict:
    """Mounting hole pitch and drill, checked to be a centred rectangle."""
    holes = [f for f in fps if f["name"].startswith("MountingHole")]
    _expect(len(holes) == 4,
            f"{len(holes)} MountingHole footprints ({[h['ref'] for h in holes]}); 4 expected")
    drills = []
    for h in holes:
        _expect(len(h["pads"]) == 1, f"{h['ref']} has {len(h['pads'])} pads; one expected")
        drills.append(_drill(h["pads"][0]))
    _expect(max(drills) - min(drills) < TOL, f"mounting hole drills differ: {drills}")

    dx = sorted({round(h["x"] - cx, 3) for h in holes})
    dy = sorted({round(h["y"] - cy, 3) for h in holes})
    corners = {(round(h["x"] - cx, 3), round(h["y"] - cy, 3)) for h in holes}
    _expect(len(dx) == 2 and len(dy) == 2 and len(corners) == 4
            and abs(dx[0] + dx[1]) < TOL and abs(dy[0] + dy[1]) < TOL,
            "mounting holes are not a rectangle centred on the board")
    return {"dx": dx[1] - dx[0], "dy": dy[1] - dy[0], "d": drills[0]}


def _tubes(fps: list, cx: float, cy: float) -> tuple:
    """(tubes, colons) as lists of (x, y) in this module's frame."""
    tubes = [f for f in fps if f["name"].startswith("IN-12")]
    colons = [f for f in fps if f["name"].startswith("INS-1")]
    _expect(len(tubes) == 4, f"{len(tubes)} IN-12 footprints; 4 expected")
    _expect(len(colons) == 2, f"{len(colons)} INS-1 footprints; 2 expected")
    for t in tubes:
        _expect(abs(math.remainder(t["rot"], 180.0)) < 1e-6,
                f"{t['ref']} is rotated {t['rot']}; tube_w and tube_h assume 0 or 180")
    tubes.sort(key=lambda f: f["x"])
    colons.sort(key=lambda f: f["y"])  # KiCad y ascending is frame y descending: upper first
    frame = lambda f: (f["x"] - cx, cy - f["y"])
    return [frame(t) for t in tubes], [frame(c) for c in colons]


def _source(pcb: str, pro: str) -> dict:
    with open(pro, encoding="utf-8") as f:
        text_vars = json.load(f).get("text_variables", {})
    with open(pcb, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()[:12]
    return {
        "file": os.path.relpath(pcb, REPO).replace(os.sep, "/"),
        "rev": text_vars.get("REV", ""),
        "step": text_vars.get("STEP", ""),
        "sha": sha,
    }


def board_values(board: Board) -> dict:
    """Every property that comes from the KiCad project. Needs no FreeCAD."""
    pcb, pro = pcb_path(board), pro_path(board)
    try:
        with open(pcb, encoding="utf-8") as f:
            root = kicad_sexpr.parse(f.read())
        thickness = kicad_sexpr.kidval(kicad_sexpr.kid(root, "general"), "thickness")
        _expect(thickness != "", "no (general (thickness ...)) in the board")

        o = _outline(root)
        cx, cy = (o["x0"] + o["x1"]) / 2, (o["y0"] + o["y1"]) / 2
        fps = _footprints(root)
        h = _holes(fps, cx, cy)
        s = _source(pcb, pro)

        v = {
            "board_w": o["x1"] - o["x0"], "board_h": o["y1"] - o["y0"],
            "corner_r": o["r"], "board_t": float(thickness),
            "hole_dx": h["dx"], "hole_dy": h["dy"], "hole_d": h["d"],
        }
        if board.tubes:
            tubes, colons = _tubes(fps, cx, cy)
            for i, (x, y) in enumerate(tubes, 1):
                v[f"tube{i}_x"], v[f"tube{i}_y"] = x, y
            for i, (x, y) in enumerate(colons, 1):
                v[f"colon{i}_x"], v[f"colon{i}_y"] = x, y
        v.update({
            "origin_x": cx, "origin_y": cy,
            "source_file": s["file"], "source_rev": s["rev"],
            "source_step": s["step"], "source_sha": s["sha"],
        })
    except BoardError as e:
        raise BoardError(f"{board.project}: {e}") from None
    return v


def envelope_values() -> dict:
    """Tube envelopes from the part models, which carry the drawings. Needs FreeCAD."""
    for part in ("in12", "ins1"):
        path = os.path.join(CAD, part)
        if path not in sys.path:
            sys.path.insert(0, path)
    import in12
    import ins1
    importlib.reload(in12)
    importlib.reload(ins1)
    return {"tube_w": in12.BODY_X, "tube_h": in12.BODY_Y, "colon_d": 2 * ins1.BARREL_R}


def values(board: Board) -> dict:
    """Everything one board's VarSet carries, keyed by property name."""
    v = board_values(board)
    if board.tubes:
        v.update(envelope_values())
    names = {p[0] for p in properties(board)}
    _expect(set(v) == names,
            f"{board.project}: properties() and values() disagree: {sorted(set(v) ^ names)}")
    return v


def select(names=None) -> list:
    """The Board entries for the given keys of BOARDS, or all of them."""
    if not names:
        return list(BOARDS.values())
    unknown = [n for n in names if n not in BOARDS]
    if unknown:
        raise KeyError(f"unknown board(s) {unknown}; have {sorted(BOARDS)}")
    return [BOARDS[n] for n in names]


# =========================================================================
# the board bodies
# =========================================================================
def kicad_cli() -> str:
    """Locate kicad-cli: KICAD_CLI, then PATH, then the newest Program Files install.

    Version directories compare as numbers; as strings "9.0" beats "10.0",
    and KiCad 9 cannot read a KiCad 10 board.
    """
    if os.environ.get("KICAD_CLI"):
        return os.environ["KICAD_CLI"]
    found = shutil.which("kicad-cli")
    if found:
        return found
    candidates = glob.glob(r"C:\Program Files\KiCad\*\bin\kicad-cli.exe")
    if not candidates:
        raise RuntimeError("kicad-cli not found; set the KICAD_CLI environment variable")

    def version(path):
        m = re.search(r"KiCad[\\/]([0-9.]+)[\\/]", path)
        return tuple(int(n) for n in m.group(1).split(".")) if m else (0,)

    return max(candidates, key=version)


def export_args(board: Board, origin: tuple) -> list:
    """The kicad-cli arguments after `pcb export step`, without the paths."""
    ox, oy = origin
    args = ["--force", f"--user-origin={ox}x{oy}mm"]
    if board.components:
        args += ["--no-dnp", "--no-unspecified", "--subst-models",
                 f"--component-filter={','.join(board.components)}"]
    else:
        args.append("--board-only")
    return args


def export_body(board: Board, origin: tuple, force: bool = False) -> bool:
    """Write the board's STEP about origin if it is missing, older than the .kicad_pcb,
    or was made with different arguments (a .cmd file beside it records them).

    Returns True when kicad-cli ran.
    """
    src, dst = pcb_path(board), body_path(board)
    args = export_args(board, origin)
    cmd_file = dst + ".cmd"
    cmd = " ".join(args)
    current = (os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src)
               and os.path.exists(cmd_file)
               and open(cmd_file, encoding="utf-8").read().strip() == cmd)
    if current and not force:
        return False
    os.makedirs(BODY_DIR, exist_ok=True)
    run = subprocess.run([kicad_cli(), "pcb", "export", "step", *args, "-o", dst, src],
                         capture_output=True, text=True)
    if run.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError(f"kicad-cli failed on {board.project}:\n{run.stdout}\n{run.stderr}")
    with open(cmd_file, "w", encoding="utf-8") as f:
        f.write(cmd + "\n")
    return True


def body_shape(board: Board, vals: dict):
    """The exported board as a Part.Shape in the VarSet frame, checked against vals.

    The export has Z = 0 on the underside; the shape comes back shifted so its
    F.Cu face is on Z = 0. Extents and hole count must agree with the parsed
    values, since the two are independent reads of the same file.
    """
    import FreeCAD as App
    import Part
    shape = Part.read(body_path(board))
    expected = 1 + len(board.components)
    _expect(shape.isValid() and len(shape.Solids) >= 1,
            f"{board.project}: export holds no valid solid")
    if len(shape.Solids) != expected:
        print(f"  note: {board.project} export holds {len(shape.Solids)} solids;"
              f" expected {expected} (board plus {list(board.components)})")
    pcb = max(shape.Solids, key=lambda s: s.Volume)  # the board dwarfs any component
    bb = pcb.BoundBox
    _expect(abs(bb.XLength - vals["board_w"]) < BODY_TOL
            and abs(bb.YLength - vals["board_h"]) < BODY_TOL
            and abs(bb.XMin + bb.XMax) < BODY_TOL and abs(bb.YMin + bb.YMax) < BODY_TOL,
            f"{board.project}: exported board spans x[{bb.XMin:.3f}, {bb.XMax:.3f}] "
            f"y[{bb.YMin:.3f}, {bb.YMax:.3f}], not {vals['board_w']} x {vals['board_h']} "
            f"about the origin; was the export taken about ({vals['origin_x']}, {vals['origin_y']})?")
    r = vals["hole_d"] / 2
    centres = set()
    for f in pcb.Faces:
        s = f.Surface
        if isinstance(s, Part.Cylinder) and abs(s.Radius - r) < BODY_TOL \
                and abs(abs(s.Axis.z) - 1) < 1e-6:
            centres.add((round(s.Center.x, 2), round(s.Center.y, 2)))
    _expect(len(centres) == 4,
            f"{board.project}: exported board has {len(centres)} holes of {vals['hole_d']}, not 4")
    # Bake the shift into the geometry. Shape.translate() only moves the
    # shape's Location, which assigning the Shape turns into the object's
    # Placement, and the Placement is the user's.
    shift = App.Matrix()
    shift.move(App.Vector(0, 0, -bb.ZMax))
    shape = shape.transformGeometry(shift)
    _expect(shape.isValid(), f"{board.project}: shifting the exported body failed")
    return shape


def _part_faces(shape) -> list:
    """Indices of the faces that belong to solids other than the board."""
    pcb = max(shape.Solids, key=lambda s: s.Volume)
    board_faces = {f.hashCode() for f in pcb.Faces}
    return [i for i, f in enumerate(shape.Faces) if f.hashCode() not in board_faces]


def update_body(doc, board: Board, vals: dict, quiet: bool = False):
    """Create or refresh one board's body in doc. Placement and appearance are the user's."""
    exported = export_body(board, (vals["origin_x"], vals["origin_y"]))
    shape = body_shape(board, vals)
    name = body_name(board)
    obj = doc.getObject(name)
    created = obj is None
    if created:
        obj = doc.addObject("Part::Feature", name)
        obj.Label = name
    placement = obj.Placement  # assigning Shape overwrites it with the shape's own
    obj.Shape = shape
    obj.Placement = placement
    if obj.ViewObject is not None:
        if created:
            obj.ViewObject.ShapeColor = BODY_COLOR
        parts = _part_faces(shape) if board.components else []
        if parts:
            # Per-face colors follow the shape, so they are redone on every update;
            # the board keeps whatever ShapeColor the user has set.
            colors = [obj.ViewObject.ShapeColor[:3]] * len(shape.Faces)
            for i in parts:
                colors[i] = PART_COLOR
            obj.ViewObject.DiffuseColor = colors
    if not quiet:
        bb = max(shape.Solids, key=lambda s: s.Volume).BoundBox
        state = "created" if created else "updated"
        source = "exported now" if exported else "export current"
        extra = f", with {', '.join(board.components)}" if board.components else ""
        print(f"{name} {state}, {source}: board {bb.XLength:.3f} x {bb.YLength:.3f} x {bb.ZLength:.3f},"
              f" F.Cu face on Z = 0, 4 holes of {vals['hole_d']}{extra}")
    return obj


# =========================================================================
# the VarSets
# =========================================================================
def _plain(value):
    """A property value as a Python number or string."""
    return value.Value if hasattr(value, "Value") else value


def _differs(old, new) -> bool:
    if isinstance(new, str):
        return old != new
    return abs(float(old) - float(new)) > 1e-9


def _fmt(value) -> str:
    if isinstance(value, str):
        return value
    text = f"{float(value):.3f}"
    return "0.000" if text == "-0.000" else text


def update_one(doc, board: Board, quiet: bool = False):
    """Create or refresh one board's VarSet in doc.

    Values change in place. Properties are added when missing and never
    removed, so expressions bound to the VarSet survive every update.
    """
    vals = values(board)
    vs = doc.getObject(board.varset)
    created = vs is None
    if created:
        vs = doc.addObject("App::VarSet", board.varset)

    rows = []
    for name, ptype, group, tooltip in properties(board):
        if name in vs.PropertiesList:
            old = _plain(getattr(vs, name))
        else:
            vs.addProperty(ptype, name, group, tooltip)
            old = None
        new = vals[name]
        changed = old is None or _differs(old, new)
        if changed:
            setattr(vs, name, new)
        rows.append((name, old, new, changed))

    if not quiet:
        n = sum(1 for r in rows if r[3])
        state = "created" if created else f"updated, {n} of {len(rows)} changed"
        print(f"{board.varset} {state} from {vals['source_file']}"
              f" rev {vals['source_rev']} step {vals['source_step']} sha {vals['source_sha']}")
        for name, old, new, changed in rows:
            if not (created or changed):
                continue
            was = "" if old is None else f"  was {_fmt(old)}"
            print(f"  {name:<12} {_fmt(new):>14}{was}")
    return vs


def update(doc=None, boards=None, quiet: bool = False, bodies: bool = True) -> dict:
    """Create or refresh the VarSets, and the board bodies, in doc (default: the active document).

    boards: keys of BOARDS to update; default all. bodies=False skips the
    kicad-cli export and the body objects. Returns {key: VarSet}.
    """
    import FreeCAD as App
    doc = doc or App.ActiveDocument
    if doc is None:
        raise RuntimeError("no active document: open the case document, then update()")
    done = {}
    for board in select(boards):
        vs = update_one(doc, board, quiet)
        if bodies:
            vals = {name: _plain(getattr(vs, name)) for name, _, _, _ in properties(board)}
            update_body(doc, board, vals, quiet)
        done[board.project] = vs
    doc.recompute()
    return done


def main(argv: list) -> int:
    doc_path = None
    if argv and argv[0].lower().endswith(".fcstd"):
        doc_path, argv = argv[0], argv[1:]
    boards = select(argv)

    if doc_path is None:
        for board in boards:
            vals = values(board)
            print(f"{board.varset} from {vals['source_file']}")
            for name, _, group, _ in properties(board):
                print(f"  {group:<7} {name:<12} {_fmt(vals[name]):>14}")
        return 0

    import FreeCAD as App
    path = os.path.abspath(doc_path).replace("\\", "/")
    if os.path.exists(path):
        doc = App.openDocument(path)
    else:
        doc = App.newDocument(os.path.splitext(os.path.basename(path))[0])
        doc.FileName = path
    update(doc, [b.project for b in boards])
    doc.save()
    print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
