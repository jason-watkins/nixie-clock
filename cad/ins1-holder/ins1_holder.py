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
the ribs are what touch the glass, and they are 0.8 wide so a slicer keeps
them. The tubes in hand measure TUBE_D_MEASURED across the barrel, wider than
the model's 6.50 and spread by 0.03, and the ribs crush to take up that
spread and whatever the printer adds to it. FITS lists the
variants, one STL each, and each names the press it wants on the smallest
tube as printed; the rib diameter is drawn from that, PRINT_UNDER larger,
because a printed bore comes out that much under its drawing. The report
states the press on the largest tube too. The counterbore clears the 7.00 wide
blade section by SHOULDER_CLEAR a side over the height where the section is
wider than the barrel, and runs a little past it.

Sources: the lamp's sections and seat from ins1.py, measured off the vendor
model; the slot from washer.py, which took it from the INS-1_Recessed
footprint; the lamp pitch and the IN-12 positions from the face board through
boards.py. The footprint's 3D model offset (-9.74) assumed a 0.85 washer under
the lamp; without one the lamp sits at the slot's own seat, 10.59, and that is
what this part is built to.

The tall variant
----------------

holder_tall() lifts the lamps so that only the pip and the leads pass the
board: the flat underside of the press stands on the holder's floor, T_PLATE_T
above the board, and the floor is pierced only for the dia 3.00 pip and the two
leads. The lens then stands T_LENS above the board rather than Z_APEX - Z_BOARD.
Nothing seats in the slot, so the slot's corners are free, and four tabs under
the plate key the holder into them, clear of the pip and the leads.

The tube goes in leads first from the top, with the blade along X as the slot
will demand anyway. That sets two things: the bore is drawn to pass the blade's
flank corners, T_BLADE_CLEAR a side as printed, so the ribs stand taller than
in the short variant; and the ribs sit at 45 deg, where the blade's outline is
2.7 from the axis and never near them. Below the ribs the cavity is a plain
cylinder T_CAVITY_CLEAR clear of those corners: nothing there touches glass.
The ribs are the same FITS as the short variant and are all that holds the
tube up; the floor is what holds it down.

Run headless to build, report and write the STLs for the slicer, one per
variant and fit:

    python .claude/skills/freecad/scripts/fc_tool.py run cad/ins1-holder/ins1_holder.py

In the GUI, build() shows a holder over both lamps and a stub of board;
build(variant="tall") the tall one.
"""

import importlib
import math
import os
import sys
from typing import NamedTuple

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
TUBE_D_MEASURED = (6.57, 6.60)  # calipers across six barrels, smallest and largest; one
#                                 tube at 6.70 was a clear outlier and is left out
TUBE_D_OVER = sum(TUBE_D_MEASURED) / 2 - 2 * G.BARREL_R  # 0.135 over the model's 6.50
BARREL_R = G.BARREL_R + TUBE_D_OVER / 2  # 3.3175, the mean tube; sizes the bore and collar
PRINT_UNDER = 0.15  # a printed bore under its drawing, on the diameter. Ribs drawn at
#                     6.60 were a hard press on the 6.57 tube, which puts them near
#                     6.45 as printed; refine from the next pair
PRESS_HALF = G.PRESS_W  # 3.50, half of the 7.00 blade
Z_ROUND = G.Z_SHOULDER_END - Z_BOARD  # 1.01, section is the round barrel above here
Z_NARROW = (
    G.Z_W_BAND_END - Z_BOARD
)  # 0.67, section is no wider than the barrel above here
Z_APEX = G.Z_APEX - Z_BOARD  # 18.01, the lens

# --- fits, per side, for PETG ---------------------------------------------
BORE_CLEAR = 0.25  # bore radius over the barrel; the tube never rides on the bore


class Fit(NamedTuple):
    """The press wanted on the smallest measured tube, per side, as printed:
    positive is interference, zero a slip. Larger tubes press harder by half
    their extra diameter, and the ribs crush to take it."""

    press_min: float
    note: str


# Names are for the slicer's file list.
FITS = {
    "close": Fit(0.03, "0.03 a side on the smallest tube, 0.045 on the largest; printed good"),
    "loose": Fit(0.015, "0.015 a side on the smallest tube; a slip at 0.00 printed with no grip"),
}
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

R_BORE = BARREL_R + BORE_CLEAR  # 3.60
R_CBORE = PRESS_HALF + SHOULDER_CLEAR  # 3.80
Z_CBORE = Z_ROUND + SHOULDER_MARGIN  # 1.31
PLATE_L = PITCH + PLATE_W  # along Y
RIB_Z0 = Z_CBORE + RIB_MARGIN
RIB_Z1 = HEIGHT - BORE_LEAD - RIB_MARGIN


def r_rib(fit: Fit) -> float:
    """Radius of the rib faces as drawn: the smallest tube less the press, plus
    what the printer takes off, all on the diameter."""
    return (TUBE_D_MEASURED[0] - 2 * fit.press_min + PRINT_UNDER) / 2


def press_on(fit: Fit, tube_d: float) -> float:
    """Interference per side on a tube of diameter tube_d, as printed; negative is clearance."""
    return (tube_d - (2 * r_rib(fit) - PRINT_UNDER)) / 2


# --- the tall variant -------------------------------------------------------
def _blade_points() -> list:
    """The blade's outline at the press, as (angle deg, radius) about the lamp axis."""
    out = []
    for p in G.press_outline(0.0).discretize(Distance=0.02):
        out.append((math.degrees(math.atan2(p.y, p.x)) % 360.0, math.hypot(p.x, p.y)))
    return out


_BLADE = _blade_points()
BLADE_R_MAX = max(r for _, r in _BLADE)  # 3.65, the flank corners; what the bore must pass


def blade_r_near(angle: float, half_span: float) -> float:
    """The blade's greatest radius within half_span degrees of angle: what a rib there meets."""
    return max((r for a, r in _BLADE if abs((a - angle + 180.0) % 360.0 - 180.0) <= half_span),
               default=0.0)


T_PLATE_T = 1.60  # floor; the press's flat underside stands on its top face
T_LAMP_Z0 = G.Z_FACE - T_PLATE_T  # 3.00: lamp z at the board's front face
T_LENS = G.Z_APEX - T_LAMP_Z0  # 25.60 above the board
T_PIP_CLEAR = 0.30  # floor hole over the dia 3.00 pip, per side
T_LEAD_CLEAR = 0.45  # floor slot over the dia 0.50 leads, per side and past their ends
T_BLADE_CLEAR = 0.30  # bore over the blade's corners, per side, as printed; the tube goes
#                       in blade first and the corners are the vendor model's, not measured
T_CAVITY_CLEAR = 0.55  # cavity radius over the blade's corners; nothing touches down there
T_COLLAR_D = 11.00  # wider than the short variant's, for the wall round the cavity
T_RIB_LEN = 6.00  # grip on the barrel
T_TAB_DEPTH = 1.20  # into the 1.60 board
T_TAB_FIT = 0.15  # tab to the milled slot, per side
T_TAB_CLEAR = 0.45  # tab to a lead's surface, and to the pip's

T_R_PIP_HOLE = G.R_PIP + T_PIP_CLEAR  # 1.80
T_LEAD_SLOT_L = 2 * (G.LEAD_PITCH / 2 + G.LEAD_R + T_LEAD_CLEAR)  # 6.90
T_LEAD_SLOT_W = 2 * (G.LEAD_R + T_LEAD_CLEAR)  # 1.40
T_R_BORE = BLADE_R_MAX + T_BLADE_CLEAR + PRINT_UNDER / 2  # 3.92 drawn
T_R_CAVITY = BLADE_R_MAX + T_CAVITY_CLEAR  # 4.20
T_Z_CAVITY_TOP = G.Z_SHOULDER_END - T_LAMP_Z0  # 8.60, the section is round above here
T_RIB_Z0 = T_Z_CAVITY_TOP + RIB_MARGIN
T_RIB_Z1 = T_RIB_Z0 + T_RIB_LEN
T_HEIGHT = T_RIB_Z1 + RIB_MARGIN + BORE_LEAD  # 15.90
T_TAB_Y0 = G.LEAD_R + T_TAB_CLEAR  # 0.70, the tab's inner edge, off the lead
T_TAB_X0 = math.sqrt((G.R_PIP + T_TAB_CLEAR) ** 2 - T_TAB_Y0 ** 2)  # 1.82, off the pip


def rib_stand(fit: Fit) -> float:
    """How far the ribs stand proud of the bore; the 45 deg ramps are this long too."""
    return R_BORE - r_rib(fit)


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
T_COLLAR = Peanut(T_COLLAR_D / 2, WAIST_W, PITCH)


def rounded_rect_area(w: float, h: float, r: float) -> float:
    return w * h - (4 - math.pi) * r * r


def prism(wire: Part.Wire, height: float) -> Part.Shape:
    return Part.Face(wire).extrude(_v(0, 0, height))


# =========================================================================
# geometry
# =========================================================================
def plate(t: float = PLATE_T) -> Part.Shape:
    return prism(W.rounded_rect(PLATE_W, PLATE_L, PLATE_R, 0.0), t)


def collar(outline: Peanut = COLLAR, plate_t: float = PLATE_T, height: float = HEIGHT) -> Part.Shape:
    """The waisted collar, with its top edge chamfered by a ruled loft to an inset outline."""
    body = prism(outline.wire(plate_t), height - TOP_CHAMFER - plate_t)
    cap = Part.makeLoft(
        [outline.wire(height - TOP_CHAMFER), outline.inset(TOP_CHAMFER).wire(height)],
        True,
        True,
    )
    return body.fuse([cap])


def counterbore(y0: float) -> Part.Shape:
    """Clearance over the shoulder, where the section is still 7.00 wide."""
    return Part.makeCylinder(R_CBORE, Z_CBORE + OVER, _v(0, y0, -OVER))


def bore(y0: float, r: float = R_BORE, z0: float = 0.0, height: float = HEIGHT) -> Part.Shape:
    return Part.makeCylinder(r, height - z0 + 2 * OVER, _v(0, y0, z0 - OVER))


def lead_in(y0: float, r: float = R_BORE, height: float = HEIGHT) -> Part.Shape:
    """A 45 deg cone at the mouth, half of it above the top face."""
    return Part.makeCone(
        r,
        r + 2 * BORE_LEAD,
        2 * BORE_LEAD,
        _v(0, y0, height - BORE_LEAD),
        _v(0, 0, 1),
    )


def rib(y0: float, angle: float, fit: Fit, r_bore: float = R_BORE,
        z0: float = RIB_Z0, z1: float = RIB_Z1) -> Part.Shape:
    """One crush rib: a flat-faced bar on the bore wall, ramped 45 deg at both ends.

    Drawn in the r-z plane along +X, extruded across Y, then turned to its
    angle. Its back is buried RIB_BURY into the wall.
    """
    face_r = r_rib(fit)
    ramp = r_bore - face_r
    profile = [
        (r_bore + RIB_BURY, z0),
        (r_bore, z0),
        (face_r, z0 + ramp),
        (face_r, z1 - ramp),
        (r_bore, z1),
        (r_bore + RIB_BURY, z1),
    ]
    points = [_v(r, -RIB_W / 2, z) for r, z in profile]
    face = Part.Face(Part.makePolygon(points + [points[0]]))
    shape = face.extrude(_v(0, RIB_W, 0))
    shape.rotate(_v(0, 0, 0), _v(0, 0, 1), angle)
    shape.translate(_v(0, y0, 0))
    return shape


def holder(fit: Fit) -> Part.Shape:
    shape = plate().fuse([collar()])
    for y0 in LAMP_Y:
        for tool in (counterbore(y0), bore(y0), lead_in(y0)):
            shape = shape.cut(tool)
    for y0 in LAMP_Y:
        for k in range(RIB_N):
            shape = shape.fuse([rib(y0, RIB_ANGLE0 + 360.0 * k / RIB_N, fit)])
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("holder is not a single valid solid")
    return shape


# --- the tall variant -------------------------------------------------------
def floor_opening(y0: float) -> Part.Shape:
    """What passes the floor: the pip, and the two leads with room to be a little bent."""
    hole = Part.makeCylinder(T_R_PIP_HOLE, T_PLATE_T + 2 * OVER, _v(0, y0, -OVER))
    slot = prism(W.rounded_rect(T_LEAD_SLOT_L, T_LEAD_SLOT_W, T_LEAD_SLOT_W / 2 - 1e-3, -OVER),
                 T_PLATE_T + 2 * OVER)
    slot.translate(_v(0, y0, 0))
    return hole.fuse([slot])


def cavity(y0: float) -> Part.Shape:
    """Room for the blade and the shoulder above the floor, up to where the section is round."""
    return Part.makeCylinder(T_R_CAVITY, T_Z_CAVITY_TOP - T_PLATE_T + OVER, _v(0, y0, T_PLATE_T))


def tab(y0: float, sx: float, sy: float) -> Part.Shape:
    """One keying tab under the plate, in one corner of the board's slot.

    The slot outline shrunk by the fit, kept only where it is clear of the pip
    and the nearer lead: x past T_TAB_X0 and y past T_TAB_Y0, signs sx, sy.
    """
    outline = prism(W.slot_rect(-T_TAB_FIT, -T_TAB_DEPTH), T_TAB_DEPTH + OVER)
    keep = Part.makeBox(SLOT_W, SLOT_H, T_TAB_DEPTH + 2 * OVER,
                        _v(T_TAB_X0 if sx > 0 else -T_TAB_X0 - SLOT_W,
                           T_TAB_Y0 if sy > 0 else -T_TAB_Y0 - SLOT_H,
                           -T_TAB_DEPTH - OVER))
    shape = outline.common(keep)
    shape.translate(_v(0, y0, 0))
    return shape


def holder_tall(fit: Fit) -> Part.Shape:
    shape = plate(T_PLATE_T).fuse([collar(T_COLLAR, T_PLATE_T, T_HEIGHT)])
    for y0 in LAMP_Y:
        for tool in (floor_opening(y0), cavity(y0),
                     bore(y0, T_R_BORE, T_PLATE_T, T_HEIGHT), lead_in(y0, T_R_BORE, T_HEIGHT)):
            shape = shape.cut(tool)
    for y0 in LAMP_Y:
        for k in range(RIB_N):
            shape = shape.fuse([rib(y0, RIB_ANGLE0 + 360.0 * k / RIB_N, fit,
                                    T_R_BORE, T_RIB_Z0, T_RIB_Z1)])
        for sx in (1, -1):
            for sy in (1, -1):
                shape = shape.fuse([tab(y0, sx, sy)])
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("tall holder is not a single valid solid")
    return shape


VARIANTS = {
    "": (holder, lambda: Z_BOARD),
    "tall": (holder_tall, lambda: T_LAMP_Z0),
}


# --- the neighbours, for the document and the report ---------------------
def lamp(y0: float, lamp_z0: float = Z_BOARD) -> Part.Shape:
    """The lamp's outer glass, with lamp z = lamp_z0 at the board's front face."""
    shape = G.outer_glass()
    shape.translate(_v(0, y0, -lamp_z0))
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


def target_volume(fit: Fit) -> float:
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
    stand = rib_stand(fit)
    ribs = RIB_N * stand * (RIB_Z1 - RIB_Z0 - stand) * RIB_W
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


def _report(shape: Part.Shape, fit: Fit, glass=None):
    try:
        bop = "clean" if not shape.check(True) else "errors"
    except ValueError:
        bop = "errors"
    box = shape.optimalBoundingBox()
    target = target_volume(fit)
    zc = (PLATE_T + HEIGHT - TOP_CHAMFER) / 2  # mid-height of the collar's straight run

    rows = [
        ("fit", fit.note, ""),
        ("tubes measured", f"{_mm(TUBE_D_MEASURED[0])} to {_mm(TUBE_D_MEASURED[1])}",
         f"model {_mm(2 * G.BARREL_R)}; bore and collar sized to the mean {_mm(2 * BARREL_R)}"),
        ("ribs drawn / printed", f"dia {_mm(2 * r_rib(fit))} / {_mm(2 * r_rib(fit) - PRINT_UNDER)}",
         f"PRINT_UNDER {_mm(PRINT_UNDER)}"),
        ("press, smallest tube", f"{_mm(press_on(fit, TUBE_D_MEASURED[0]))} a side", "as printed"),
        ("press, largest tube", f"{_mm(press_on(fit, TUBE_D_MEASURED[1]))} a side", "as printed"),
        ("bore, largest tube", f"{_mm((2 * R_BORE - PRINT_UNDER - TUBE_D_MEASURED[1]) / 2)} a side clear",
         "as printed; the tube never rides on the bore"),
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
        ("rib face", f"dia {_mm(2 * r_rib(fit))}, stands {_mm(rib_stand(fit))}", "> 0.15, or it is not a rib"),
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
        for z in (0.10, Z_NARROW, Z_CBORE - 0.1, RIB_Z0 + rib_stand(fit) + 0.1, 5.0, RIB_Z1):
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


def target_volume_tall(fit: Fit) -> float:
    """The tall holder's volume from its dimensions, independent of the booleans."""
    body = rounded_rect_area(PLATE_W, PLATE_L, PLATE_R) * T_PLATE_T
    body += T_COLLAR.area() * (T_HEIGHT - TOP_CHAMFER - T_PLATE_T)
    body += _prismoid(TOP_CHAMFER, T_COLLAR.area(),
                      T_COLLAR.inset(TOP_CHAMFER / 2).area(),
                      T_COLLAR.inset(TOP_CHAMFER).area())
    # floor opening: a circle and a stadium, overlapping in the band |y| < w/2
    r, hw = T_R_PIP_HOLE, T_LEAD_SLOT_W / 2
    band = 2 * (r * r * math.asin(hw / r) + hw * math.sqrt(r * r - hw * hw))
    opening = math.pi * r * r + rounded_rect_area(T_LEAD_SLOT_L, T_LEAD_SLOT_W, hw) - band
    per_lamp = opening * T_PLATE_T
    per_lamp += math.pi * T_R_CAVITY ** 2 * (T_Z_CAVITY_TOP - T_PLATE_T)
    bore_area = math.pi * T_R_BORE ** 2
    per_lamp += bore_area * (T_HEIGHT - T_Z_CAVITY_TOP)
    r2 = T_R_BORE + BORE_LEAD
    per_lamp += math.pi / 3 * BORE_LEAD * (T_R_BORE ** 2 + T_R_BORE * r2 + r2 ** 2) - bore_area * BORE_LEAD
    stand = T_R_BORE - r_rib(fit)
    ribs = RIB_N * stand * (T_RIB_Z1 - T_RIB_Z0 - stand) * RIB_W
    tabs = 4 * Part.Face(W.slot_rect(-T_TAB_FIT, 0.0)).common(
        Part.Face(Part.makePolygon([_v(T_TAB_X0, T_TAB_Y0, 0), _v(9, T_TAB_Y0, 0),
                                    _v(9, 9, 0), _v(T_TAB_X0, 9, 0), _v(T_TAB_X0, T_TAB_Y0, 0)]))
    ).Area * T_TAB_DEPTH
    return body - len(LAMP_Y) * (per_lamp - ribs - tabs)


def _report_tall(shape: Part.Shape, fit: Fit, glass=None):
    try:
        bop = "clean" if not shape.check(True) else "errors"
    except ValueError:
        bop = "errors"
    box = shape.optimalBoundingBox()
    target = target_volume_tall(fit)
    stand = T_R_BORE - r_rib(fit)
    bore_printed = 2 * T_R_BORE - PRINT_UNDER
    rib_printed = 2 * r_rib(fit) - PRINT_UNDER
    half_span = math.degrees(RIB_W / 2 / r_rib(fit))
    blade_at_ribs = max(blade_r_near(RIB_ANGLE0 + 360.0 * k / RIB_N, half_span) for k in range(RIB_N))
    # the press's underside on the floor: its outline less what the floor opening takes
    press = Part.Face(G.press_outline(0.0))
    opening = Part.Face(W.rounded_rect(T_LEAD_SLOT_L, T_LEAD_SLOT_W, T_LEAD_SLOT_W / 2 - 1e-3, 0.0)) \
        .fuse(Part.Face(Part.Wire(Part.makeCircle(T_R_PIP_HOLE))))
    seat_area = press.Area - press.common(opening).Area

    rows = [
        ("fit", fit.note, ""),
        ("tubes measured", f"{_mm(TUBE_D_MEASURED[0])} to {_mm(TUBE_D_MEASURED[1])}", ""),
        ("solids / valid", f"{len(shape.Solids)}, {shape.isValid()}", "1, True"),
        ("bop check", bop, "clean"),
        ("volume mm3", _mm(shape.Volume), f"{_mm(target)} closed form"),
        ("volume error", f"{(shape.Volume / target - 1) * 100:+.3f}%", "within 0.3%"),
        ("envelope", f"{_mm(box.XLength)} x {_mm(box.YLength)} x {_mm(box.ZLength)}",
         f"{_mm(PLATE_W)} x {_mm(PLATE_L)} x {_mm(T_HEIGHT + T_TAB_DEPTH)}, tabs included"),
        ("press underside at", f"z {_mm(T_PLATE_T)}", "the floor's top face"),
        ("seat area", f"{seat_area:.2f} mm2", "press outline on the floor round the opening"),
        ("lens above board", _mm(T_LENS), f"short variant {_mm(Z_APEX)}"),
        ("pip tip below board", _mm(T_LAMP_Z0), f"board is {_mm(BOARD_T)} thick"),
        ("ribs drawn / printed", f"dia {_mm(2 * r_rib(fit))} / {_mm(rib_printed)}, stand {_mm(stand)}",
         f"PRINT_UNDER {_mm(PRINT_UNDER)}"),
        ("press, smallest tube", f"{_mm(press_on(fit, TUBE_D_MEASURED[0]))} a side", "as printed"),
        ("press, largest tube", f"{_mm(press_on(fit, TUBE_D_MEASURED[1]))} a side", "as printed"),
        ("bore drawn / printed", f"dia {_mm(2 * T_R_BORE)} / {_mm(bore_printed)}",
         f"blade corners at r {_mm(BLADE_R_MAX)}: {_mm(bore_printed / 2 - BLADE_R_MAX)} a side to pass"),
        ("blade under the ribs", f"r {_mm(blade_at_ribs)} within {half_span:.1f} deg of a rib",
         f"rib face r {_mm(rib_printed / 2)} printed: {_mm(rib_printed / 2 - blade_at_ribs)} to pass"),
        ("cavity", f"dia {_mm(2 * T_R_CAVITY)} to z {_mm(T_Z_CAVITY_TOP)}",
         f"{_mm(T_R_CAVITY - BLADE_R_MAX)} over the blade corners"),
        ("floor opening", f"pip dia {_mm(2 * T_R_PIP_HOLE)}, leads {_mm(T_LEAD_SLOT_L)} x {_mm(T_LEAD_SLOT_W)}",
         f"pip {_mm(2 * G.R_PIP)}, leads {_mm(2 * G.LEAD_R)} at {_mm(G.LEAD_PITCH)} pitch"),
        ("tab, each slot corner",
         f"x {_mm(T_TAB_X0)}..{_mm(SLOT_W / 2 - T_TAB_FIT)}, y {_mm(T_TAB_Y0)}..{_mm(SLOT_H / 2 - T_TAB_FIT)}",
         f"{_mm(T_TAB_DEPTH)} deep; {_mm(T_TAB_FIT)} to the slot, {_mm(T_TAB_CLEAR)} to lead and pip"),
        ("wall, collar at cavity", _mm(T_COLLAR_D / 2 - T_R_CAVITY), "> 1.2"),
        ("wall, collar at bore", _mm(T_COLLAR_D / 2 - T_R_BORE), "> 1.2"),
        ("wall, waist to cavity", _mm(math.hypot(T_COLLAR.d, T_COLLAR.c) - T_COLLAR.r - T_R_CAVITY),
         "= collar wall at cavity"),
        ("IN-12 glass at lamp", _mm(in12_edge(LAMP_Y[0])),
         f"plate edge {_mm(PLATE_W / 2)}, gap {_mm(in12_edge(LAMP_Y[0]) - PLATE_W / 2)}"),
    ]
    if glass is not None:
        for z in (T_PLATE_T + 0.1, (T_PLATE_T + T_Z_CAVITY_TOP) / 2, T_Z_CAVITY_TOP - 0.1,
                  T_RIB_Z0 + stand + 0.1, (T_RIB_Z0 + T_RIB_Z1) / 2, T_RIB_Z1):
            lx, ly = _section_extents(glass, z, LAMP_Y[0])
            o = _opening(shape, z, LAMP_Y[0])
            if o:
                rows.append((f"lamp at z {z:.2f}",
                             f"{_mm(2 * lx)} x {_mm(2 * ly)} in {_mm(2 * o[0])} x {_mm(2 * o[1])}",
                             f"gap {_mm(min(o[0] - lx, o[1] - ly))} axes, {_mm(o[2] - max(lx, ly))} ribs"))
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


def build(report: bool = True, fit: str = "close", variant: str = "") -> Part.Shape:
    """Show one variant and fit over both lamps and a stub of board."""
    make, lamp_z0 = VARIANTS[variant]
    doc = _document()
    shape = make(FITS[fit])
    _place(doc, "Holder", shape)
    upper = lamp(LAMP_Y[0], lamp_z0())
    _place(doc, "LampUpper", upper)
    _place(doc, "LampLower", lamp(LAMP_Y[1], lamp_z0()))
    _place(doc, "Board", board_stub())
    _reconcile(doc)
    doc.recompute()
    if report:
        (_report_tall if variant == "tall" else _report)(shape, FITS[fit], upper)
    if Gui is not None:
        Gui.SendMsgToActiveView("ViewFit")
    return shape


# =========================================================================
# print
# =========================================================================
PRINT_DIR = os.path.join(HERE, "print")
STL_LINEAR = 0.01
STL_ANGULAR = 0.15  # rad; 0.017 mm chord error on the 7.00 bore


def stl_path(name: str, variant: str = "") -> str:
    tag = f"_{variant}" if variant else ""
    return os.path.join(PRINT_DIR, f"ins1_holder{tag}_{name}.stl")


def export_stl(name: str, shape: Part.Shape = None, variant: str = "") -> tuple:
    """Write one holder in the model's own frame: plate down, tabs (if any) below z = 0."""
    import MeshPart

    shape = shape if shape is not None else VARIANTS[variant][0](FITS[name])
    path = stl_path(name, variant)
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
    for variant, (make, lamp_z0) in VARIANTS.items():
        glass = lamp(LAMP_Y[0], lamp_z0())
        report = _report_tall if variant == "tall" else _report
        for name, fit in FITS.items():
            shape = make(fit)
            print(f"\n  INS-1 holder{' ' + variant if variant else ''}, {name}")
            report(shape, fit, glass)
            path, facets, size = export_stl(name, shape, variant)
            print(
                f"    {'written':<26}{os.path.relpath(path, CAD):<40}{facets} facets, {size / 1024:.1f} kB"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
