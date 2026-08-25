"""The face board's geometry, as a VarSet the hand-built case model reads.

Source: pcb/face/face.kicad_pcb, with REV and STEP from face.kicad_pro. The
KiCad project is the source of truth and no board dimension here is typed in.
The tube envelopes come from the part models (cad/in12, cad/ins1), which carry
the manufacturer drawings.

Frame: origin at the centre of Edge.Cuts, X as KiCad draws it, Y negated
(KiCad's grows downward), Z = 0 on the front face, the F.Cu side where the
tubes stand, +Z out of the clock. `kicad-cli pcb export step
--user-origin=<origin_x>x<origin_y>mm` writes the same X and Y with Z = 0 on
the underside, so such an export sits at Z = -board_t in this frame.

The VarSet encodes a topology, and values() asserts it before it writes a
number:

    Edge.Cuts   four axis-parallel lines and four equal quarter arcs, one
                closed loop: a rounded rectangle
    holes       four MountingHole footprints in a rectangle centred on the
                board, one drilled pad each, one drill size
    tubes       four IN-12 at rotation 0 or 180, two INS-1

Anything else stops the update. A fifth hole or a cutout is a change to the
case, made on purpose, and PROPERTIES below is where it starts.

Properties, by group:

    Board    board_w board_h corner_r board_t
    Holes    hole_dx hole_dy hole_d
    Tubes    tube1..4_x tube1..4_y   ordered by x, left to right seen from
                                     the front
             tube_w tube_h           envelope at rotation 0: in12.BODY_X,
                                     in12.BODY_Y
             colon1..2_x colon1..2_y upper first
             colon_d                 2 * ins1.BARREL_R
    Source   origin_x origin_y       KiCad coordinates of this frame's origin
             source_file source_rev source_step source_sha

Positions are App::PropertyDistance, which carries a sign; sizes are
App::PropertyLength. A sketch constraint binds to one with an expression such
as `FaceBoard.hole_dx / 2`.

update() changes values in place and only ever adds properties. It never
deletes or recreates the VarSet: expressions bind to it by name, and a
recreated object leaves every one of them dangling. A value the user edited by
hand is written back and shows in the printed table as a change.

GUI, with the case document active:

    import importlib, sys
    SRC = "C:/Code/nixe_clock/cad/case"
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    import face_board
    importlib.reload(face_board)
    face_board.update()

Headless:

    python .claude/skills/freecad/scripts/fc_tool.py run cad/case/face_board.py
        prints the values it would write
    python .claude/skills/freecad/scripts/fc_tool.py run cad/case/face_board.py DOC.FCStd
        opens DOC (or creates it), updates the VarSet, saves
"""

import hashlib
import importlib
import json
import math
import os
import sys
from collections import Counter

CAD = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPO = os.path.normpath(os.path.join(CAD, ".."))
PCB = os.path.join(REPO, "pcb", "face", "face.kicad_pcb")
PRO = os.path.join(REPO, "pcb", "face", "face.kicad_pro")

if CAD not in sys.path:
    sys.path.insert(0, CAD)
import kicad_sexpr

# A reload of this module in the GUI does not reload its imports; do it here
# so the macro's single reload is enough.
importlib.reload(kicad_sexpr)

NAME = "FaceBoard"  # the VarSet's Name, which expressions reference
TOL = 1e-3  # mm, for the topology checks; KiCad writes six decimals

LENGTH = "App::PropertyLength"
DISTANCE = "App::PropertyDistance"
STRING = "App::PropertyString"


def _tube_properties():
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
PROPERTIES = (
    ("board_w", LENGTH, "Board", "Edge.Cuts extent along X"),
    ("board_h", LENGTH, "Board", "Edge.Cuts extent along Y"),
    ("corner_r", LENGTH, "Board", "Edge.Cuts corner radius"),
    ("board_t", LENGTH, "Board", "Board thickness, (general (thickness)) in the .kicad_pcb"),
    ("hole_dx", LENGTH, "Holes", "Mounting hole pitch along X"),
    ("hole_dy", LENGTH, "Holes", "Mounting hole pitch along Y"),
    ("hole_d", LENGTH, "Holes", "Mounting hole drill"),
) + _tube_properties() + (
    ("origin_x", LENGTH, "Source",
     "KiCad X of this frame's origin: the --user-origin for a kicad-cli export"),
    ("origin_y", LENGTH, "Source",
     "KiCad Y of this frame's origin: the --user-origin for a kicad-cli export"),
    ("source_file", STRING, "Source", "The .kicad_pcb these values were read from"),
    ("source_rev", STRING, "Source", "REV text variable of the KiCad project"),
    ("source_step", STRING, "Source", "STEP text variable of the KiCad project"),
    ("source_sha", STRING, "Source", "SHA-256 of the .kicad_pcb, first 12 hex digits"),
)


class BoardError(ValueError):
    """The board does not have the topology this module encodes."""


def _expect(cond: bool, message: str):
    if not cond:
        raise BoardError(message)


# =========================================================================
# reading the board
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


def board_values(pcb: str = PCB, pro: str = PRO) -> dict:
    """Every property that comes from the KiCad project. Needs no FreeCAD."""
    with open(pcb, encoding="utf-8") as f:
        root = kicad_sexpr.parse(f.read())
    thickness = kicad_sexpr.kidval(kicad_sexpr.kid(root, "general"), "thickness")
    _expect(thickness != "", "no (general (thickness ...)) in the board")

    o = _outline(root)
    cx, cy = (o["x0"] + o["x1"]) / 2, (o["y0"] + o["y1"]) / 2
    fps = _footprints(root)
    h = _holes(fps, cx, cy)
    tubes, colons = _tubes(fps, cx, cy)
    s = _source(pcb, pro)

    v = {
        "board_w": o["x1"] - o["x0"], "board_h": o["y1"] - o["y0"],
        "corner_r": o["r"], "board_t": float(thickness),
        "hole_dx": h["dx"], "hole_dy": h["dy"], "hole_d": h["d"],
    }
    for i, (x, y) in enumerate(tubes, 1):
        v[f"tube{i}_x"], v[f"tube{i}_y"] = x, y
    for i, (x, y) in enumerate(colons, 1):
        v[f"colon{i}_x"], v[f"colon{i}_y"] = x, y
    v.update({
        "origin_x": cx, "origin_y": cy,
        "source_file": s["file"], "source_rev": s["rev"],
        "source_step": s["step"], "source_sha": s["sha"],
    })
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


def values(pcb: str = PCB, pro: str = PRO) -> dict:
    """Everything the VarSet carries, keyed by property name."""
    v = board_values(pcb, pro)
    v.update(envelope_values())
    names = {p[0] for p in PROPERTIES}
    _expect(set(v) == names,
            f"PROPERTIES and values() disagree: {sorted(set(v) ^ names)}")
    return v


# =========================================================================
# the VarSet
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


def update(doc=None, quiet: bool = False):
    """Create or refresh the FaceBoard VarSet in doc (default: the active one).

    Values change in place. Properties are added when missing and never
    removed, so expressions bound to the VarSet survive every update.
    """
    import FreeCAD as App
    doc = doc or App.ActiveDocument
    if doc is None:
        raise RuntimeError("no active document: open the case document, then update()")
    vals = values()
    vs = doc.getObject(NAME)
    created = vs is None
    if created:
        vs = doc.addObject("App::VarSet", NAME)

    rows = []
    for name, ptype, group, tooltip in PROPERTIES:
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
    doc.recompute()

    if not quiet:
        n = sum(1 for r in rows if r[3])
        state = "created" if created else f"updated, {n} of {len(rows)} changed"
        print(f"{NAME} {state} from {vals['source_file']}"
              f" rev {vals['source_rev']} step {vals['source_step']} sha {vals['source_sha']}")
        for name, old, new, changed in rows:
            if not (created or changed):
                continue
            was = "" if old is None else f"  was {_fmt(old)}"
            print(f"  {name:<12} {_fmt(new):>14}{was}")
    return vs


def main(argv: list) -> int:
    if not argv:
        vals = values()
        print(f"{PCB}")
        for name, _, group, _ in PROPERTIES:
            print(f"  {group:<7} {name:<12} {_fmt(vals[name]):>14}")
        return 0
    import FreeCAD as App
    path = os.path.abspath(argv[0]).replace("\\", "/")
    if os.path.exists(path):
        doc = App.openDocument(path)
    else:
        doc = App.newDocument(os.path.splitext(os.path.basename(path))[0])
        doc.FileName = path
    update(doc)
    doc.save()
    print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
