"""INS-1 retaining washer - the TPU grommet between the lamp and the board.

    "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/ins1/washer.py

The recessed footprint mills a 7.60 x 4.20 slot on Edge.Cuts and passes the
lamp's 7.00 x 3.35 pinch blade through it. That leaves 0.30 a side in X and
0.425 in Y, and nothing holding the lamp but friction against milled FR4. This
part fills that gap: it lines the slot so glass never touches the board, its
flange sets how far the lens stands proud, and it grips both.

Built in the lamp's own frame - origin at the tip of the exhaust pip, +Z toward
the lens - because every dimension that matters is a comparison against the
lamp. The board's front face sits at Z_BOARD, which is the footprint's model
offset with its sign flipped. print_ready() moves it onto the bed.

    flange   Z_BOARD .. Z_BOARD + FLANGE_T, bore is the slot outline
    barrel   the board thickness, bore grips the blade
    lip      snaps out behind the board and holds the washer captive

Where the lamp stops is set by the flange, and the section it stops on is not
the obvious one. Above the blade the ribs fade faster than the bead grows, so
the lamp gets *thinner* first - 3.3465 at 9.60 down to 3.1105 at 10.20 - before
climbing steeply to 4.50 by 10.60. The lamp slides past that waist and seats on
the way back up, which is also why the seat barely moves with the opening: 3.35
seats at 10.4182 and 4.20 at 10.5887, so 0.85 of opening buys 0.17 of height.
A flange bore equal to the slot puts the seat at 10.5887, and FLANGE_T is then
what the footprint's 9.74 offset already assumes.

TPU rather than a rigid print, and that changes three things. Fits are
interference, not clearance, because the material takes up the error instead of
jamming on it. The lip can be a plain snap - pushed through the slot and sprung
back - where a rigid part would need a split or a second piece. And the thin
walls this geometry forces are a feature: at 0.40 and 0.525 they are one or two
perimeters, and they want to be compliant.
"""

import math
import os
import sys
from typing import NamedTuple

import FreeCAD as App
import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ins1 as G  # noqa: E402

try:
    from FreeCAD import Gui
except ImportError:
    Gui = None

DOC_NAME = "INS1_Washer"

# --- the board, from INS-1_Recessed.kicad_mod ----------------------------
# The slot is drawn as four lines and four arcs about centres 1.00 in from each
# corner - a 2 mm router bit, which is what a fab will cut it with anyway.
SLOT_W, SLOT_H, SLOT_R = 7.60, 4.20, 1.00
BOARD_T = 1.60  # 0.010 mask + 0.035 copper + 1.510 core + 0.035 + 0.010
Z_BOARD = 9.74  # front face, in the lamp's frame: the model offset, negated

# --- fits ----------------------------------------------------------------
# The wall this geometry allows is 0.30 + squeeze + grip, so an allowance moves
# it one for one. That is the whole argument for printing this in TPU: an
# interference fit makes the wall thicker than the gap it has to live in, where
# a clearance fit makes it thinner, and there is only 0.30 a side to start with.
#
# The PLA variant is a gauge, not a part. It is there to check that the blade
# passes, that the washer drops into the slot, and that the lens lands where it
# should; it gives up wall section to do it and it has no lip, because a rigid
# one cannot deflect through the slot and would simply snap off.
class Fit(NamedTuple):
    """Signed per side: positive is interference, negative is clearance."""

    grip: float  # bore against the blade
    squeeze: float  # barrel against the slot
    lip: float  # snap behind the board, 0 for none
    note: str


FITS = {
    "tpu": Fit(0.05, 0.05, 0.30, "the part: squeezed both ways, snap lip"),
    "pla": Fit(-0.05, -0.05, 0.00, "the gauge: drops together, no lip"),
}

# --- the part ------------------------------------------------------------
# The flange's bore is what the lamp seats on, and it has to sit inside the
# barrel's outer by enough to hold on to it. Sizing it to the slot instead - the
# obvious choice, since the flange is then a continuation of it - leaves the two
# overlapping only across the squeeze, 0.05 for TPU, and for a clearance fit the
# barrel comes out smaller than the flange's hole and they separate into two
# solids. CONNECT is that band, taken off the slot on every side.
CONNECT = 0.20
FLANGE_BORE_W = SLOT_W - 2 * CONNECT
FLANGE_BORE_H = SLOT_H - 2 * CONNECT
FLANGE_MARGIN = 1.50  # brim beyond the slot, clear of the pads at x = 6.50


def seat_for(opening: float) -> float:
    """Height at which the lamp's section first fills a given opening.

    Solved rather than read off the stations, which are 0.1 apart. Above the
    blade the bead is the thickest part of the section, so this is just where
    its S-curve reaches half the opening.
    """
    lo, hi = G.Z_SHOULDER, G.Z_SHOULDER_END
    for _ in range(60):
        mid = (lo + hi) / 2
        if 2 * G.s_curve(mid, G.Z_SHOULDER, G.PRESS_BEAD,
                         G.BARREL_R, G.BLEND_R) < opening:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# Derived, not chosen: the flange is exactly as thick as the gap between the
# board's front face and the height the lamp seats at through its own bore, so
# its top face and the seat are the same plane and the lens lands where the
# footprint's offset says it does - whatever CONNECT is set to.
FLANGE_T = seat_for(FLANGE_BORE_H) - Z_BOARD
LIP_T = 0.40  # length of the ramp up to the snap
LEAD_IN = 0.25  # chamfer at the bore entry, so the blade cannot catch

Z_FLANGE_TOP = Z_BOARD + FLANGE_T
Z_BOARD_BACK = Z_BOARD - BOARD_T


def bottom(fit: Fit) -> float:
    """Where the part ends. Without a lip it stops at the board's back face."""
    return Z_BOARD_BACK - LIP_T if fit.lip > 0 else Z_BOARD_BACK


# =========================================================================
# outlines
# =========================================================================
def _v(point, z):
    return App.Vector(point[0], point[1], z)


def rounded_rect(width: float, height: float, radius: float, z: float) -> Part.Wire:
    """A rounded rectangle centred on the axis, as the slot is drawn."""
    cx, cy = width / 2 - radius, height / 2 - radius
    corners = ((cx, cy, 0.0), (-cx, cy, 90.0), (-cx, -cy, 180.0), (cx, -cy, 270.0))

    edges = []
    for index, (ox, oy, start) in enumerate(corners):
        a0 = math.radians(start)
        arc = [(ox + radius * math.cos(a0 + step), oy + radius * math.sin(a0 + step))
               for step in (0.0, math.pi / 4, math.pi / 2)]
        edges.append(Part.Arc(_v(arc[0], z), _v(arc[1], z), _v(arc[2], z)).toShape())

        nx, ny, nstart = corners[(index + 1) % 4]
        a1 = math.radians(nstart)
        nxt = (nx + radius * math.cos(a1), ny + radius * math.sin(a1))
        edges.append(Part.LineSegment(_v(arc[2], z), _v(nxt, z)).toShape())
    return Part.Wire(edges)


def slot_rect(grow: float, z: float) -> Part.Wire:
    """The milled slot, optionally inflated. Corners grow with it."""
    return rounded_rect(SLOT_W + 2 * grow, SLOT_H + 2 * grow, SLOT_R + grow, z)


def bore_wire(grow: float, z: float) -> Part.Wire:
    """The blade's own section, offset. This is what makes it a press fit.

    Taken from the lamp rather than approximated by a rounded rectangle, so the
    bore carries the ribs and the jaw flats and fits on all of them. A printer
    will round the 0.65 rib arcs off somewhat; on the TPU part that costs a
    little interference exactly where there is most of it, which is the
    harmless direction.

    ins1.press_outline does the offset off the drawn segments. See press_offset
    for why Part.Wire.makeOffset2D cannot be used for it.
    """
    return G.press_outline(z, grow)


# =========================================================================
# the solid
# =========================================================================
def _prism(wire: Part.Wire, height: float) -> Part.Shape:
    return Part.Face(wire).extrude(App.Vector(0, 0, height))


def _taper(lower: Part.Wire, upper: Part.Wire) -> Part.Shape:
    return Part.makeLoft([lower, upper], True, True, False)


def outer(fit: Fit) -> Part.Shape:
    """Flange, barrel and - where the material can flex - a snap lip."""
    flange = _prism(
        rounded_rect(SLOT_W + 2 * FLANGE_MARGIN, SLOT_H + 2 * FLANGE_MARGIN,
                     SLOT_R + FLANGE_MARGIN, Z_BOARD),
        FLANGE_T)
    barrel = _prism(slot_rect(fit.squeeze, Z_BOARD_BACK), BOARD_T)
    shape = flange.fuse([barrel])
    if fit.lip > 0:
        # Ramped on the way in and square on the way out, so it pushes through
        # the slot and then will not come back. Printed flange down, the ramp is
        # the self-supporting face and the square one is a 0.30 bridge.
        shape = shape.fuse([_taper(
            slot_rect(fit.squeeze, bottom(fit)),
            slot_rect(fit.squeeze + fit.lip, Z_BOARD_BACK))])
    return shape


def _mouth(fit: Fit) -> Part.Shape:
    """The chamfer at the bore entry, so the blade cannot catch on its way in.

    A plain rounded rectangle, not the blade's profile. Two attempts at keeping
    the profile failed: offsetting it changes the edge count - 28 against 42, the
    concave jaw arcs splitting differently at each distance - and a ruled loft
    between mismatched sections will not build at all, while scaling it keeps the
    count and builds a solid that passes isValid() and fails a BOP check, the
    scaled concave arcs crossing the unscaled ones between the sections.

    Eight edges at each end has neither problem. It cuts wider than the profile
    would over the jaw and the bead, but only between Z_LIP_BOT and LEAD_IN
    above it, which is inside the lip and below the board - nowhere near the run
    that grips. The blade meets a ramp at the flanks and the ribs, which are the
    only places it could catch, and clearance everywhere else.
    """
    span = bore_wire(-fit.grip, 0.0).BoundBox
    base = bottom(fit)
    return _taper(
        rounded_rect(span.XLength + 2 * LEAD_IN, span.YLength + 2 * LEAD_IN,
                     SLOT_R, base - 0.01),
        rounded_rect(span.XLength, span.YLength, SLOT_R, base + LEAD_IN))


def bore(fit: Fit) -> Part.Shape:
    """What gets cut away: the seat above, the grip below, a chamfer to enter.

    The flange's bore is the slot outline itself, at nominal for every fit, so
    the flange is a continuation of the slot and the lamp seats on its top edge.
    Leaving it nominal is what makes the gauge worth printing: it measures the
    seat the real part will give, not the seat its own allowance would give.
    """
    base = bottom(fit)
    seat = _prism(rounded_rect(FLANGE_BORE_W, FLANGE_BORE_H,
                               SLOT_R - CONNECT, Z_BOARD),
                  FLANGE_T + 1.0)  # runs past the top face
    grip = _prism(bore_wire(-fit.grip, base + LEAD_IN), Z_BOARD - base - LEAD_IN)
    return seat.fuse([grip]).fuse([_mouth(fit)])


def washer(fit: Fit = None) -> Part.Shape:
    fit = fit or FITS["tpu"]
    shape = outer(fit).cut(bore(fit))
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("washer is not a single valid solid")
    return shape


def print_ready(fit: Fit, shape: Part.Shape = None) -> Part.Shape:
    """The same part with the seat face on the bed, flange down.

    Flange down puts the face the lamp seats against on the build plate, leaves
    the lip's ramp self-supporting, and reduces its retaining face to a 0.30
    bridge. It also runs the layers across the barrel rather than along it, so
    the hoop that has to stretch over the blade is not pulling a layer seam.
    """
    shape = (shape if shape is not None else washer(fit)).copy()
    shape.translate(App.Vector(0, 0, -Z_FLANGE_TOP))
    shape.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 180)
    return shape


PRINT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "print")
STL_LINEAR = 0.005  # this part is 10 mm across; it can afford a fine mesh
STL_ANGULAR = 0.20


def export_stl(name: str, fit: Fit) -> tuple:
    """Write one variant, oriented for the bed."""
    import MeshPart

    if not os.path.isdir(PRINT_DIR):
        os.makedirs(PRINT_DIR)
    path = os.path.join(PRINT_DIR, f"washer_{name}.stl")
    mesh = MeshPart.meshFromShape(Shape=print_ready(fit),
                                  LinearDeflection=STL_LINEAR,
                                  AngularDeflection=STL_ANGULAR, Relative=False)
    mesh.write(path)
    return path, mesh.CountFacets, os.path.getsize(path)


# =========================================================================
# document
# =========================================================================
MANAGED = ("Washer", "Lamp", "Board")
APPEARANCE = {
    "Washer": {"ShapeColor": (0.20, 0.22, 0.26)},
    "Lamp": {"ShapeColor": (0.85, 0.90, 0.90), "Transparency": 80},
    "Board": {"ShapeColor": (0.10, 0.35, 0.18), "Transparency": 40},
}


def _document():
    docs = App.listDocuments()
    doc = App.getDocument(DOC_NAME) if DOC_NAME in docs else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    return doc


def _place(doc, name, shape):
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


def _report(name: str, fit: Fit, shape: Part.Shape):
    box = shape.optimalBoundingBox()

    # Wall as printed, then as installed. Only the interference fit is squeezed
    # back; a clearance fit prints at its own size and stays there.
    printed_x = (SLOT_W + 2 * fit.squeeze - (2 * G.PRESS_W - 2 * fit.grip)) / 2
    printed_y = (SLOT_H + 2 * fit.squeeze - (2 * G.PRESS_RIB - 2 * fit.grip)) / 2
    fitted_x = min(printed_x, (SLOT_W - 2 * G.PRESS_W) / 2)
    fitted_y = min(printed_y, (SLOT_H - 2 * G.PRESS_RIB) / 2)

    blade = Part.Face(G.press_outline(0.0))
    hole = Part.Face(bore_wire(-fit.grip, 0.0))
    inside = abs(blade.common(hole).Area - hole.Area) < 1e-6
    try:
        bop = "clean" if not shape.check(True) else "errors"
    except ValueError:
        bop = "errors"

    print(f"\n  {name} - {fit.note}")
    rows = [
        ("solids / valid", f"{len(shape.Solids)}, {shape.isValid()}", "1, True"),
        ("bop check", bop, "clean"),
        ("volume mm3", f"{shape.Volume:.2f}", "-"),
        ("envelope",
         f"{box.XLength:.2f} x {box.YLength:.2f} x {box.ZLength:.2f}", "-"),
        ("height", f"{box.ZMin:.4f} - {box.ZMax:.4f}",
         f"{bottom(fit):.4f} - {Z_FLANGE_TOP:.4f}"),
        ("wall printed", f"{printed_x:.3f} x, {printed_y:.3f} y",
         "one bead, 0.4 nozzle"),
        ("wall installed", f"{fitted_x:.3f} x, {fitted_y:.3f} y", "-"),
        # An elastomer face seal is designed on 15 to 30 per cent squeeze; below
        # that it lets go, above it takes a set and creeps out of the joint.
        ("squeeze",
         f"{(printed_x - fitted_x) / printed_x * 100:.0f}%",
         "15 - 30% for TPU, 0 for a gauge"),
        ("bore vs blade",
         f"{'interference' if fit.grip > 0 else 'clearance'} {abs(fit.grip):.2f}/side",
         "-"),
        ("bore inside blade", str(inside), "True only when it grips"),
        ("lens proud of board", f"{G.Z_APEX - Z_BOARD:.4f}", "18.86"),
        ("seat", f"{seat_for(FLANGE_BORE_H):.4f}",
         f"{Z_FLANGE_TOP:.4f}, the flange top"),
        # The flange has to hold on to the barrel across a real band, and the
        # lamp is 7.00 wide right through the flange, so its bore cannot close
        # in on that either.
        ("flange to barrel",
         f"{(SLOT_W + 2 * fit.squeeze - FLANGE_BORE_W) / 2:.3f} x, "
         f"{(SLOT_H + 2 * fit.squeeze - FLANGE_BORE_H) / 2:.3f} y", "> 0.10"),
        ("flange bore to lamp", f"{(FLANGE_BORE_W - 2 * G.PRESS_W) / 2:.3f} x", "> 0"),
    ]
    if fit.lip > 0:
        half = (SLOT_W + 2 * (fit.squeeze + fit.lip)) / 2
        rows.append(("lip to pad", f"{6.50 - 1.25 - half:.3f} mm",
                     "> 0, pads at x 6.50"))
    for label, value, target in rows:
        print(f"    {label:<20}{value!s:<28}{target}")


def build(name: str = "tpu"):
    """Show one variant in the document, with the lamp and a stub of board."""
    fit = FITS[name]
    doc = _document()
    shape = washer(fit)
    _place(doc, "Washer", shape)
    _place(doc, "Lamp", G.glass())
    board = _prism(rounded_rect(24.0, 14.0, 1.0, Z_BOARD_BACK), BOARD_T)
    _place(doc, "Board", board.cut(_prism(slot_rect(0.0, Z_BOARD_BACK), BOARD_T)))
    doc.recompute()
    _report(name, fit, shape)
    if Gui is not None:
        Gui.SendMsgToActiveView("ViewFit")


def main():
    for name, fit in FITS.items():
        shape = washer(fit)
        _report(name, fit, shape)
        path, facets, size = export_stl(name, fit)
        print(f"    {'written':<20}{os.path.basename(path):<28}"
              f"{facets} facets, {size / 1024:.1f} kB")
