"""INS-1 holder - a rigid collar, printed in PETG, that steadies the two colon lamps.

The recessed footprint seats each lamp on the edge of a milled slot and nothing
above the board holds it: 18 mm of glass stands on a 4.2 mm wide seat. This
part is glued to the front of the board over both lamps and takes the side
loads. It slides down over the lamps after they are soldered, so every opening
in it passes the barrel and the dome, and nothing in it touches the pinch or
the shoulder.

Frame: the FaceBoard VarSet frame. Origin midway between the two lamps on the
board's front face; X along the board (the pinch blade's wide axis, and the
direction of the IN-12 neighbours), Y up the board (the lamps sit at
+-PITCH/2), Z the lamp axis out of the board. The lamp's own frame has its
origin at the exhaust pip and the lamp seats where its section first fills the
slot, so lamp z = holder z + Z_BOARD with Z_BOARD = ins1.seat_height(). The
frame is also the print orientation: plate on the bed, bores vertical.

    plate     rounded rectangle, the glue face, cornered like the slots
    collar    over both lamps, waisted between them: two circles joined by
              concave arcs tangent to both; its top edge is a ruled loft to
              an inset outline, a chamfer with no chamfer operation
    per lamp  counterbore over the shoulder, bore over the barrel, four crush
              ribs standing proud of the bore, a lead-in cone at the mouth

Fits are for a hard plastic. The bore clears the barrel by BORE_CLEAR a side;
the ribs are what touch the glass, at RIB_CLEAR on a nominal barrel and
crushing on an oversize one, and they are 0.8 wide so a slicer keeps them. The
counterbore clears the 7.00 wide blade section by SHOULDER_CLEAR a side over
the height where the section is wider than the barrel, and runs a little past
it.

Sources: the lamp's sections and seat from ins1.py, measured off the vendor
model; the slot from washer.py, which took it from the INS-1_Recessed
footprint; the lamp pitch and the IN-12 positions from the face board through
boards.py. The footprint's 3D model offset (-9.74) assumed a 0.85 washer under
the lamp; without one the lamp sits at the slot's own seat, 10.59, and that is
what this part is built to.

Run headless to build, report and write the STL for the slicer:

    python .claude/skills/freecad/scripts/fc_tool.py run cad/ins1-holder/ins1_holder.py

In the GUI, build() shows the holder over both lamps and a stub of board.
"""

import importlib
import math
import os
import sys

import FreeCAD as App
import Part

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.normpath(os.path.join(HERE, ".."))
for _sub in ("ins1", "case"):
    _path = os.path.join(CAD, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
import ins1 as G  # noqa: E402
import washer as W  # noqa: E402  (the slot, and rounded_rect)
import boards  # noqa: E402

# A reload of this module in the GUI does not reload these.
importlib.reload(G)
importlib.reload(W)
importlib.reload(boards)

try:
    from FreeCAD import Gui
except ImportError:
    Gui = None

DOC_NAME = "INS1_Holder"

# --- the board, through boards.py (pcb/face/face.kicad_pcb) --------------
_FACE = boards.board_values(boards.BOARDS["face"])
_ENV = boards.envelope_values()
LAMP_Y = (_FACE["colon1_y"], _FACE["colon2_y"])  # upper first: +6.00, -6.00
PITCH = LAMP_Y[0] - LAMP_Y[1]  # 12.00
IN12_X = min(
    abs(_FACE["tube2_x"]), abs(_FACE["tube3_x"])
)  # 18.00, the nearest digit's axis
IN12_R = _ENV["tube_w"] / 2  # 10.50, the digit's stadium end radius (in12.BODY_X)
IN12_STRAIGHT = (
    _ENV["tube_h"] - _ENV["tube_w"]
)  # 10.00, its straight run (in12.BODY_Y - BODY_X)
BOARD_T = _FACE["board_t"]  # 1.60
SLOT_W, SLOT_H, SLOT_R = W.SLOT_W, W.SLOT_H, W.SLOT_R  # 7.60 x 4.20, R1.00

# --- the lamp, from ins1.py ------------------------------------------------
Z_BOARD = G.seat_height()  # 10.59, the board's front face in the lamp frame
BARREL_R = G.BARREL_R  # 3.25
PRESS_HALF = G.PRESS_W  # 3.50, half of the 7.00 blade
Z_ROUND = G.Z_SHOULDER_END - Z_BOARD  # 1.01, section is the round barrel above here
Z_NARROW = (
    G.Z_W_BAND_END - Z_BOARD
)  # 0.67, section is no wider than the barrel above here
Z_APEX = G.Z_APEX - Z_BOARD  # 18.01, the lens

# --- fits, per side, for PETG ---------------------------------------------
BORE_CLEAR = 0.25  # bore radius over the barrel; the tube never rides on the bore
RIB_STAND = 0.20  # ribs stand this proud of the bore ...
RIB_CLEAR = BORE_CLEAR - RIB_STAND  # ... so they clear a nominal barrel by 0.05
RIB_W = 0.80  # two extrusion lines; a 0.4 rib is one line and slicers drop it
RIB_N = 4
RIB_ANGLE0 = 45.0  # first rib, off the X axis; the section is round where they are
SHOULDER_CLEAR = 0.30  # counterbore radius over the 7.00 blade width
SHOULDER_MARGIN = 0.30  # counterbore runs this far above Z_ROUND

# --- the part --------------------------------------------------------------
PLATE_W = 12.60  # across X; the IN-12 glass is at 7.55 either side, see _report
PLATE_R = (
    4.00  # corner radius; the slots are R1.00 on 4.20, this is the same look at 12.60
)
PLATE_T = 2.00
COLLAR_D = 10.40  # round the lamps: bore 7.00 plus a 1.70 wall
WAIST_W = 5.00  # across X between the lamps; the concave arcs never come nearer a
#                 bore than the collar wall does, see _report
HEIGHT = 9.00  # above the board; the lens stands 9.0 clear of it
TOP_CHAMFER = 0.60
BORE_LEAD = 0.50  # 45 deg mouth, so the dome finds the bore
RIB_MARGIN = 0.40  # ribs stop this short of the counterbore and the mouth
RIB_BURY = 0.30  # ribs reach this far into the wall, so the fuse has something to hold
OVER = 0.01  # cutters run past the faces they open on

R_BORE = BARREL_R + BORE_CLEAR  # 3.50
R_RIB = R_BORE - RIB_STAND  # 3.30
R_CBORE = PRESS_HALF + SHOULDER_CLEAR  # 3.80
Z_CBORE = Z_ROUND + SHOULDER_MARGIN  # 1.31
PLATE_L = PITCH + PLATE_W  # along Y
RIB_Z0 = Z_CBORE + RIB_MARGIN
RIB_Z1 = HEIGHT - BORE_LEAD - RIB_MARGIN
RIB_RAMP = RIB_STAND  # 45 deg at both ends


# =========================================================================
# outlines
# =========================================================================
def _v(x, y, z):
    return App.Vector(x, y, z)


class Peanut:
    """Two circles of radius R about (0, +-c), joined by concave arcs of radius r
    about (+-d, 0) tangent to both, so the outline is w wide at the waist.

    From w: (d, 0) is R + r from (0, c) and d = w/2 + r, which gives r. Offsetting
    the outline inward by t keeps every centre, shrinks R by t and grows r by t,
    so one class describes the collar and its chamfer's top.
    """

    def __init__(self, big_r: float, waist_w: float, pitch: float):
        self.R = big_r
        self.c = pitch / 2
        w = waist_w / 2
        self.r = (w * w + self.c**2 - big_r**2) / (2 * (big_r - w))
        self.d = w + self.r
        # tangent point in the first quadrant: on the upper circle, toward (d, 0)
        ux, uy = self.d, -self.c
        norm = math.hypot(ux, uy)
        self.tx, self.ty = big_r * ux / norm, self.c + big_r * uy / norm

    def inset(self, t: float) -> "Peanut":
        p = Peanut.__new__(Peanut)
        p.R, p.c, p.r, p.d = self.R - t, self.c, self.r + t, self.d
        ux, uy = p.d, -p.c
        norm = math.hypot(ux, uy)
        p.tx, p.ty = p.R * ux / norm, p.c + p.R * uy / norm
        return p

    @property
    def waist(self) -> float:
        return 2 * (self.d - self.r)

    def wire(self, z: float) -> Part.Wire:
        R, c, r, d, tx, ty = self.R, self.c, self.r, self.d, self.tx, self.ty
        edges = [
            Part.Arc(_v(tx, ty, z), _v(0, c + R, z), _v(-tx, ty, z)).toShape(),
            Part.Arc(_v(-tx, ty, z), _v(-(d - r), 0, z), _v(-tx, -ty, z)).toShape(),
            Part.Arc(_v(-tx, -ty, z), _v(0, -c - R, z), _v(tx, -ty, z)).toShape(),
            Part.Arc(_v(tx, -ty, z), _v(d - r, 0, z), _v(tx, ty, z)).toShape(),
        ]
        return Part.Wire(edges)

    def area(self) -> float:
        """Closed form: the chord rectangle, plus the big segments, less the concave ones."""
        R, c, r, d, tx, ty = self.R, self.c, self.r, self.d, self.tx, self.ty
        chords = 2 * tx * 2 * ty
        big = math.pi - 2 * math.atan2(ty - c, tx)  # atan2 is negative: span over pi
        concave = 2 * math.atan2(ty, d - tx)
        return (
            chords
            + 2 * (R * R / 2) * (big - math.sin(big))
            - 2 * (r * r / 2) * (concave - math.sin(concave))
        )


COLLAR = Peanut(COLLAR_D / 2, WAIST_W, PITCH)


def rounded_rect_area(w: float, h: float, r: float) -> float:
    return w * h - (4 - math.pi) * r * r


def prism(wire: Part.Wire, height: float) -> Part.Shape:
    return Part.Face(wire).extrude(_v(0, 0, height))


# =========================================================================
# geometry
# =========================================================================
def plate() -> Part.Shape:
    return prism(W.rounded_rect(PLATE_W, PLATE_L, PLATE_R, 0.0), PLATE_T)


def collar() -> Part.Shape:
    """The waisted collar, with its top edge chamfered by a ruled loft to an inset outline."""
    body = prism(COLLAR.wire(PLATE_T), HEIGHT - TOP_CHAMFER - PLATE_T)
    cap = Part.makeLoft(
        [COLLAR.wire(HEIGHT - TOP_CHAMFER), COLLAR.inset(TOP_CHAMFER).wire(HEIGHT)],
        True,
        True,
    )
    return body.fuse([cap])


def counterbore(y0: float) -> Part.Shape:
    """Clearance over the shoulder, where the section is still 7.00 wide."""
    return Part.makeCylinder(R_CBORE, Z_CBORE + OVER, _v(0, y0, -OVER))


def bore(y0: float) -> Part.Shape:
    return Part.makeCylinder(R_BORE, HEIGHT + 2 * OVER, _v(0, y0, -OVER))


def lead_in(y0: float) -> Part.Shape:
    """A 45 deg cone at the mouth, half of it above the top face."""
    return Part.makeCone(
        R_BORE,
        R_BORE + 2 * BORE_LEAD,
        2 * BORE_LEAD,
        _v(0, y0, HEIGHT - BORE_LEAD),
        _v(0, 0, 1),
    )


def rib(y0: float, angle: float) -> Part.Shape:
    """One crush rib: a flat-faced bar on the bore wall, ramped 45 deg at both ends.

    Drawn in the r-z plane along +X, extruded across Y, then turned to its
    angle. Its back is buried RIB_BURY into the wall.
    """
    profile = [
        (R_BORE + RIB_BURY, RIB_Z0),
        (R_BORE, RIB_Z0),
        (R_RIB, RIB_Z0 + RIB_RAMP),
        (R_RIB, RIB_Z1 - RIB_RAMP),
        (R_BORE, RIB_Z1),
        (R_BORE + RIB_BURY, RIB_Z1),
    ]
    points = [_v(r, -RIB_W / 2, z) for r, z in profile]
    face = Part.Face(Part.makePolygon(points + [points[0]]))
    shape = face.extrude(_v(0, RIB_W, 0))
    shape.rotate(_v(0, 0, 0), _v(0, 0, 1), angle)
    shape.translate(_v(0, y0, 0))
    return shape


def holder() -> Part.Shape:
    shape = plate().fuse([collar()])
    for y0 in LAMP_Y:
        for tool in (counterbore(y0), bore(y0), lead_in(y0)):
            shape = shape.cut(tool)
    for y0 in LAMP_Y:
        for k in range(RIB_N):
            shape = shape.fuse([rib(y0, RIB_ANGLE0 + 360.0 * k / RIB_N)])
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("holder is not a single valid solid")
    return shape


# --- the neighbours, for the document and the report ---------------------
def lamp(y0: float) -> Part.Shape:
    """The lamp's outer glass, seated on its slot."""
    shape = G.outer_glass()
    shape.translate(_v(0, y0, -Z_BOARD))
    return shape


def board_stub() -> Part.Shape:
    slab = prism(W.rounded_rect(30.0, 30.0, 1.0, -BOARD_T), BOARD_T)
    for y0 in LAMP_Y:
        slot = prism(W.slot_rect(0.0, -BOARD_T - OVER), BOARD_T + 2 * OVER)
        slot.translate(_v(0, y0, 0))
        slab = slab.cut(slot)
    return slab


def in12_edge(y: float) -> float:
    """X of the nearest IN-12 glass at height y up the board.

    The digit's outline in the board plane is a stadium, IN12_R end radius on
    an IN12_STRAIGHT run, so past the straight the edge curves away.
    """
    dy = max(0.0, abs(y) - IN12_STRAIGHT / 2)
    return IN12_X - math.sqrt(IN12_R**2 - dy**2)


# =========================================================================
# report
# =========================================================================
def _mm(value: float) -> str:
    text = f"{value:.3f}"
    return "0.000" if text == "-0.000" else text


def _prismoid(h: float, a0: float, am: float, a1: float) -> float:
    return h / 6 * (a0 + 4 * am + a1)


def target_volume() -> float:
    """The holder's volume from its dimensions, independent of the booleans."""
    body = rounded_rect_area(PLATE_W, PLATE_L, PLATE_R) * PLATE_T
    body += COLLAR.area() * (HEIGHT - TOP_CHAMFER - PLATE_T)
    body += _prismoid(
        TOP_CHAMFER,
        COLLAR.area(),
        COLLAR.inset(TOP_CHAMFER / 2).area(),
        COLLAR.inset(TOP_CHAMFER).area(),
    )
    cbore_area = math.pi * R_CBORE**2
    bore_area = math.pi * R_BORE**2
    r2 = R_BORE + BORE_LEAD
    mouth = (
        math.pi / 3 * BORE_LEAD * (R_BORE**2 + R_BORE * r2 + r2**2)
        - bore_area * BORE_LEAD
    )
    per_lamp = cbore_area * Z_CBORE + bore_area * (HEIGHT - Z_CBORE) + mouth
    ribs = RIB_N * RIB_STAND * (RIB_Z1 - RIB_Z0 - RIB_RAMP) * RIB_W
    return body - len(LAMP_Y) * (per_lamp - ribs)


def _section_extents(shape: Part.Shape, z: float, y0: float) -> tuple:
    """(half-width in X, half-height in Y) of shape's section about the axis at (0, y0)."""
    hx = hy = 0.0
    for wire in shape.slice(_v(0, 0, 1), z):
        for p in wire.discretize(Distance=0.05):
            hx = max(hx, abs(p.x))
            hy = max(hy, abs(p.y - y0))
    return hx, hy


def _wires_at(shape: Part.Shape, z: float) -> list:
    return sorted(shape.slice(_v(0, 0, 1), z), key=lambda w: Part.Face(w).Area)


def _opening(shape: Part.Shape, z: float, y0: float) -> tuple:
    """The holder's opening around (0, y0) at height z: (half X, half Y, min radius)."""
    axis = Part.Vertex(_v(0, y0, z))
    for wire in _wires_at(shape, z)[:-1]:  # every wire but the outer one
        bb = wire.BoundBox
        if bb.XMin < 0 < bb.XMax and bb.YMin < y0 < bb.YMax:
            return (bb.XLength / 2, bb.YLength / 2, wire.distToShape(axis)[0])
    return None


def _outer_width_at(shape: Part.Shape, z: float, y: float) -> float:
    """Width in X of the outermost section at height z along the line y."""
    outer = _wires_at(shape, z)[-1]
    xs = [p.x for p in outer.discretize(Distance=0.02) if abs(p.y - y) < 0.03]
    return max(xs) - min(xs) if xs else float("nan")


def _report(shape: Part.Shape, glass=None):
    try:
        bop = "clean" if not shape.check(True) else "errors"
    except ValueError:
        bop = "errors"
    box = shape.optimalBoundingBox()
    target = target_volume()
    zc = (PLATE_T + HEIGHT - TOP_CHAMFER) / 2  # mid-height of the collar's straight run

    rows = [
        ("solids / valid", f"{len(shape.Solids)}, {shape.isValid()}", "1, True"),
        ("bop check", bop, "clean"),
        ("volume mm3", _mm(shape.Volume), f"{_mm(target)} closed form"),
        ("volume error", f"{(shape.Volume / target - 1) * 100:+.3f}%", "within 0.3%"),
        (
            "envelope",
            f"{_mm(box.XLength)} x {_mm(box.YLength)} x {_mm(box.ZLength)}",
            f"{_mm(PLATE_W)} x {_mm(PLATE_L)} x {_mm(HEIGHT)}",
        ),
        ("lamp pitch", _mm(PITCH), "12.000, face board"),
        (
            "lamp seat, lamp frame",
            _mm(Z_BOARD),
            "ins1.seat_height(); footprint model assumes 9.740",
        ),
        ("collar at lamp", _mm(_outer_width_at(shape, zc, LAMP_Y[0])), _mm(COLLAR_D)),
        (
            "collar at waist",
            _mm(_outer_width_at(shape, zc, 0.0)),
            f"{_mm(WAIST_W)}, concave R {_mm(COLLAR.r)}",
        ),
        (
            "collar top at waist",
            _mm(_outer_width_at(shape, HEIGHT - 0.001, 0.0)),
            _mm(COLLAR.inset(TOP_CHAMFER).waist),
        ),
    ]
    for z, what in (
        (Z_CBORE / 2, "counterbore"),
        (5.0, "bore"),
        (HEIGHT - BORE_LEAD / 2, "mouth"),
    ):
        o = _opening(shape, z, LAMP_Y[0])
        if o:
            rows.append(
                (
                    f"{what} at z {z:.2f}",
                    f"{_mm(2 * o[0])} x {_mm(2 * o[1])}, min r {_mm(o[2])}",
                    "-",
                )
            )
    rows += [
        (
            "rib face",
            f"dia {_mm(2 * R_RIB)}",
            f"barrel {_mm(2 * BARREL_R)} + {_mm(2 * RIB_CLEAR)}",
        ),
        (
            "blade width",
            _mm(2 * PRESS_HALF),
            f"counterbore {_mm(2 * R_CBORE)} to z {_mm(Z_CBORE)}",
        ),
        ("section round above", _mm(Z_ROUND), f"< ribs start {_mm(RIB_Z0)}"),
        ("lens above holder", _mm(Z_APEX - HEIGHT), "> 0"),
        (
            "IN-12 glass at lamp",
            _mm(in12_edge(LAMP_Y[0])),
            f"plate edge {_mm(PLATE_W / 2)}, gap {_mm(in12_edge(LAMP_Y[0]) - PLATE_W / 2)}",
        ),
        ("wall, collar", _mm(COLLAR_D / 2 - R_BORE), "> 1.2, three lines"),
        # the concave arcs are centred R + r from each lamp, so they come no
        # nearer a bore than the round part of the collar does
        (
            "wall, waist to bore",
            _mm(math.hypot(COLLAR.d, COLLAR.c) - COLLAR.r - R_BORE),
            f"= collar wall {_mm(COLLAR_D / 2 - R_BORE)}",
        ),
        ("wall, plate to bore", _mm(PLATE_W / 2 - R_CBORE), "> 1.2"),
        ("bridge, counterbore step", _mm(R_CBORE - R_BORE), "short"),
    ]
    if glass is not None:
        for z in (0.10, Z_NARROW, Z_CBORE - 0.1, RIB_Z0 + RIB_RAMP + 0.1, 5.0, RIB_Z1):
            lx, ly = _section_extents(glass, z, LAMP_Y[0])
            o = _opening(shape, z, LAMP_Y[0])
            if o:
                rows.append(
                    (
                        f"lamp at z {z:.2f}",
                        f"{_mm(2 * lx)} x {_mm(2 * ly)} in {_mm(2 * o[0])} x {_mm(2 * o[1])}",
                        f"gap {_mm(min(o[0] - lx, o[1] - ly))} axes, {_mm(o[2] - max(lx, ly))} ribs",
                    )
                )
        inter = shape.common(glass)
        rows.append(("glass in holder", f"{inter.Volume:.4f} mm3", "0"))
    for label, value, note in rows:
        print(f"    {label:<26}{value:<40}{note}")


# =========================================================================
# document
# =========================================================================
MANAGED = ("Holder", "LampUpper", "LampLower", "Board")
APPEARANCE = {
    "Holder": {"ShapeColor": (0.85, 0.45, 0.15)},
    "LampUpper": {"ShapeColor": (0.85, 0.90, 0.90), "Transparency": 70},
    "LampLower": {"ShapeColor": (0.85, 0.90, 0.90), "Transparency": 70},
    "Board": {"ShapeColor": (0.10, 0.35, 0.18), "Transparency": 40},
}


def _document():
    docs = App.listDocuments()
    doc = App.getDocument(DOC_NAME) if DOC_NAME in docs else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    return doc


def _place(doc, name: str, shape: Part.Shape):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject("Part::Feature", name)
        view = getattr(obj, "ViewObject", None)
        if view is not None:
            for prop, value in APPEARANCE.get(name, {}).items():
                if hasattr(view, prop):
                    setattr(view, prop, value)
    obj.Shape = shape
    return obj


def _reconcile(doc):
    for obj in list(doc.Objects):
        if obj.Name not in MANAGED and obj.Name.startswith(
            ("Washer", "Lamp", "Holder", "Board")
        ):
            doc.removeObject(obj.Name)


def build(report: bool = True) -> Part.Shape:
    """Show the holder over both lamps and a stub of board."""
    doc = _document()
    shape = holder()
    _place(doc, "Holder", shape)
    upper = lamp(LAMP_Y[0])
    _place(doc, "LampUpper", upper)
    _place(doc, "LampLower", lamp(LAMP_Y[1]))
    _place(doc, "Board", board_stub())
    _reconcile(doc)
    doc.recompute()
    if report:
        _report(shape, upper)
    if Gui is not None:
        Gui.SendMsgToActiveView("ViewFit")
    return shape


# =========================================================================
# print
# =========================================================================
PRINT_DIR = os.path.join(HERE, "print")
STL_PATH = os.path.join(PRINT_DIR, "ins1_holder.stl")
STL_LINEAR = 0.01
STL_ANGULAR = 0.15  # rad; 0.017 mm chord error on the 7.00 bore


def export_stl(shape: Part.Shape = None, path: str = STL_PATH) -> tuple:
    """Write the holder as it prints: plate down, which is the model's own frame."""
    import MeshPart

    shape = shape if shape is not None else holder()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=STL_LINEAR,
        AngularDeflection=STL_ANGULAR,
        Relative=False,
    )
    mesh.write(path)
    return path, mesh.CountFacets, os.path.getsize(path)


def main() -> int:
    shape = holder()
    print("  INS-1 holder")
    _report(shape, lamp(LAMP_Y[0]))
    path, facets, size = export_stl(shape)
    print(
        f"    {'written':<26}{os.path.relpath(path, CAD):<40}{facets} facets, {size / 1024:.1f} kB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
