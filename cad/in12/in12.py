"""IN-12B nixie indicator - glass envelope, base and pins.

Dimensions come from the 1988 Reflector pasport, docs/datasheets/IN-12A_IN-12B.pdf,
which carries a fully dimensioned drawing, from the footprint's own hole pattern,
and from tubes in hand. Nothing here is measured off anybody else's model - the
one that used to sit alongside this was a poor guide anyway: its glass ran 22.63
tall where the drawing says 28, its section was snapped to whole tenths of an
inch, and its pins sat on a 1.27 grid, up to 0.91 off the real ring.

The axis is +Z with the origin at the centre of the glass base, so z is height
above the board in the through-hole footprint and the pins run negative. X is
across the narrow 21 face, Y along the wide 31 one, matching the footprint.

The envelope is one idea. Its section is a stadium, which is a disc swept along
a line; so the whole body is a capsule of revolution - a cylinder closed by a
half-spheroid - swept along that same line. That decomposes into two capped ends
and the silhouette extruded between them, and every face is then a plane, a
cylinder, a spheroid or an elliptical cylinder. Nothing is approximated and the
pieces meet on surfaces they share exactly, so the fuses need no tolerance.

    glass   the envelope, hollowed, with the exhaust tip under the base
    pins    twelve, on the drawing's 11.5 x 18 ring
"""

import importlib
import math
import os

import FreeCAD as App
import Part

import digits
import marks

# Reloading this module does not reload these: its own import statements are a
# no-op once they are in sys.modules, so an edited numeral or marking would go
# on being the old one until FreeCAD restarted - and a constant that came and
# went between edits reads as missing. Reload them here, so the macro's single
# reload of this module is enough.
importlib.reload(digits)
importlib.reload(marks)

try:
    from FreeCAD import Gui
except ImportError:
    Gui = None


DOC_NAME = "IN12"

# --- envelope, all off the drawing --------------------------------------
BODY_X = 21.00  # across the narrow face, drawn 21-2
BODY_Y = 31.00  # across the wide face, drawn 31-2
BODY_H = 28.00  # glass, base plane to apex, drawn 28-2
# 28 + 7 = 35, which is the drawing's stated maximum overall, so the two
# dimensions are consistent and the base plane is where they meet.
PIN_LEN = 7.00  # below the base plane, drawn 7-0.5
PIN_D = 1.00  # drawn 1 +0.03/-0.07
TIP_D = 3.50  # exhaust tip at the base centre, drawn 3.5 max

RADIUS = BODY_X / 2  # 10.50, the stadium's end radius
STRAIGHT = BODY_Y - BODY_X  # 10.00, the straight run between those ends

# The only two envelope numbers the drawing does not dimension.
#
# The face is flat, not domed - checked against tubes in hand. At the scan's
# resolution a generous fillet on a flat face reads as a dome, and it was read
# that way first. A flat face also explains why the drawing can dimension 28-2
# with a plain arrow: there is a face there to measure to.
#
# FILLET_R is the roll from the side wall into that face, off tubes in hand and
# the loosest number here: a constant curve gives calipers nothing to sit on, so
# it is a scale-and-eye reading, good to perhaps half a millimetre. It did read
# the same on both the 21 and the 31 face, which is what says a single radius
# describes the roll at all. The flat it leaves is 13 x 23, clear of the 18 mm
# digits, so they are not read through curved glass at their edges.
FILLET_R = 4.00
# The tip length only has to stay inside the pins; the drawing gives it none,
# and the pins are what the tube stands on.
TIP_LEN = 5.00

TANGENT = BODY_H - FILLET_R  # 23.00, where the side wall stops being straight

WALL = 0.80
BASE_T = 2.00  # solid glass below the cavity, where the pins seal through
# The pins do not stop at the glass - they carry on well up inside it, which
# both the side photographs and the reference model show, the latter running
# them to about a quarter of the envelope's height.
PIN_INSIDE = 6.50

# The ring, from the drawing's 11.5 x 18 oval and its 8 / 9 / 16 intermediates.
# The footprint's holes agree with all five to 0.002. Numbering runs clockwise
# from the anode, seen from below - note 2 of the drawing, counting from the
# indicator arrow - and pin 12 is the decimal point on the B, unconnected on
# the A.
PINS = (
    (4.00, 8.00),    # 1   anode
    (5.75, 4.50),    # 2   cathode 0
    (5.75, 0.00),    # 3   cathode 9
    (5.75, -4.50),   # 4   cathode 8
    (4.00, -8.00),   # 5   cathode 7
    (0.00, -9.00),   # 6   cathode 6
    (-4.00, -8.00),  # 7   cathode 5
    (-5.75, -4.50),  # 8   cathode 4
    (-5.75, 0.00),   # 9   cathode 3
    (-5.75, 4.50),   # 10  cathode 2
    (-4.00, 8.00),   # 11  cathode 1
    (0.00, 9.00),    # 12  cathode "запятая", the decimal point
)


# --- electrode stack -----------------------------------------------------
# Off photographs of tubes in hand, scaled against the envelope's known 21 and
# 31.
#
# The digits are sized so their top and bottom edges just touch the rods the
# spacers ride on, which is what tubes in hand show. That works out at a half
# height of 10.89 - and the anode's gridded area, taken independently off the
# AnodeRoughSketch, ends at 10.893. The grid covers the digits exactly, which
# is what a grid is for, and is the check on this.
#
# It does leave the character about 21.8 tall where the datasheet says 18. The
# two cannot both be about the same thing; the geometry here follows the parts. The stack order is published and corroborated
# twice: 3 at the face, 1 at the back.
#
# Pitch is the one number with real slack in it. Ten layers resolve edge-on
# over about 10.3 mm in the side view, and the reference model says 0.95 to
# 1.00; 1.10 splits them.
STACK_ORDER = (3, 8, 9, 4, 0, 5, 7, 2, 6, 1)  # front to back
STACK_PITCH = 1.10
# Flat wire, not round: sharply defined, as wide face-on as the round wire was
# and half as deep. A stamped ribbon, which is what it looks like at this size.
CATHODE_W = 0.32  # across, in the plane of the digit
CATHODE_T = 0.16  # through, along the tube's axis

# A spacer is what holds one cathode off the next, so its thickness is the
# pitch less the ribbon rather than a number of its own.
SPACER_T = STACK_PITCH - CATHODE_T
DIGIT_Z = 21.10  # the front digit's plane

# The anode is a single grid across the face - there is no cage. Its outline is
# the same family as the base plate's: straight sides meeting arced ends at real
# corners. Numbers are off the AnodeRoughSketch in IN12.FCStd; the arc there is
# R 15.500 about (0, -3.689), which meets the sides at y 9.68 and peaks at 11.81.
#
# Outboard of ANODE_SOLID_Y the sheet is solid rather than gridded, except for a
# rectangular hole at each end that the spacer rod passes through - which leaves
# the four roughly triangular solid corners.
ANODE_T = 0.14
# The anode is spaced off the front digit the same way every digit is spaced
# off the next, so its height follows from the stack rather than being set.
ANODE_Z = DIGIT_Z + CATHODE_T / 2 + SPACER_T
ANODE_X = 7.84
ANODE_ARC_R = 15.50
ANODE_ARC_C = -3.689  # arc centre, for the +Y end
ANODE_SOLID_Y = 10.893
ANODE_HOLE_X = 1.093
ANODE_HOLE_Y = 11.771
MESH_WIRE = 0.14
ANODE_BORDER = 2 * MESH_WIRE  # the rim, twice the wire
# Eight wires across the opening, so ten lines counting the rim either side.
# That fixes the pitch rather than leaving it to be guessed, and the grid is
# square, so the same pitch runs the other way.
ANODE_ACROSS = 8
ANODE_INNER = ANODE_X - ANODE_BORDER
MESH_PITCH = 2 * ANODE_INNER / (ANODE_ACROSS + 1)

# The insulators are a stacked column, not a pair of beads: one bead per
# cathode threaded on each support rod, twelve of them - ten digits, the point,
# and one more closing the bottom. Two columns, which is why they read as a
# single disc top and bottom when seen face on. The reference carries exactly
# 24 of them, twelve a side, which corroborates the count independently.
SPACER_COUNT = 12
SPACER_R = 0.85
SPACER_Y = 11.30

# The shield, read off the reference model's own geometry - see cad/in12/ref,
# extracted once - and re-dimensioned here against our bore and the photographs,
# because the reference's scale is not trustworthy. Its form is:
#
#   back      one flat plate behind everything
#   ends      four curved pieces, two at each end of the long axis, each pair
#             split by a slot the spacer column runs through
#   bars      one strap down each side, wrapping over the ends it joins
#
# The curvature is not a stylisation: the reference carries those end pieces as
# sixteen facet strips stepped from y 11.0 to 12.5 with x narrowing at each
# step, which is an arc. They follow the tube, and so does the base plate.
#
# The bars are steel on real tubes where the rest is dark, so they are their
# own part with their own material.
SHIELD_R = 9.00  # the bar path, which does follow the tube
SHIELD_T = 0.40
SHIELD_Z0 = 10.20
SHIELD_Z1 = 21.60
SHIELD_GAP = 1.20  # half the slot the spacer columns pass through
BACK_T = 0.50

# The end pieces reach as far out as the spacers do, and are flatter than the
# tube. Fitting a circle to the reference's own end-piece extremes - (1.2, 12.5)
# and (7.82, 11.2) - gives 23.6, against a bore of about 9.8, so they are much
# flatter than the glass they sit behind and are not a section of it.
SHIELD_END_Y = SPACER_Y + SPACER_R  # 12.15, the spacers' outer edge
SHIELD_ARC_R = 22.00

# The straps do follow the tube, and stop about 1.5 past where they first cross
# an end piece rather than carrying on round to meet at the middle.
BAR_Z0, BAR_Z1 = 15.25, 16.35  # centred on the getter
BAR_T = 0.35
BAR_OVERLAP = 1.50

# So the digits just reach the rods' inner surface at 11.05. Scaling the drawn
# box would say 1.21, but the interpolated centreline bulges a little past the
# points it is drawn through, and the built digits then overshoot by 0.28.
DIGIT_SCALE = 1.18

ROD_R = 0.25
ROD_TOP = ANODE_Z + ANODE_T + SPACER_T + 0.30  # past the last bead

# The plate under the numerals, immediately behind the shield's back plate.
# Curved to the tube, unlike the reference's flat rectangle, but carrying the
# teeth the reference does have and real tubes do too: four at each end, tips
# at x -4.81, -1.73, 1.70 and 4.99 on a roughly 3.2 pitch, standing about 3
# beyond the plate's own edge. The body is drawn back to PLATE_R so the teeth
# have somewhere to project from; the bore then trims their tips.
# It has distinct corners, so it is not a section of the glass: straight sides
# meeting arced ends on the same flat radius the shield's end pieces use. The
# reference agrees - an arc through its end edge, (0, 11.94) to (7.82, 10.99),
# comes out at 32.7 against a bore of about 9.8 - and its corners land exactly
# on its own bore, so they bear on the glass and locate the plate.
PLATE_T = 0.50
# The lowest spacer stands on the plate, so the plate's top face is where that
# spacer starts and the plate's height follows from the stack too.
PLATE_Z = (DIGIT_Z - 9 * STACK_PITCH - CATHODE_T / 2 - SPACER_T) - PLATE_T
PLATE_X = 8.00
PLATE_TEETH_X = (-4.85, -1.70, 1.70, 4.85)
PLATE_TOOTH_W = 0.95   # half width
PLATE_TOOTH_Y = 11.60  # where the tooth starts to point
PLATE_TOOTH_TIP = 15.40  # generous, the bore cuts it back

# A getter disc lying flat against the wall, on the centreline. The reference
# has it 5.08 across and 1.27 thick, which is 2 and 0.5 tenths of an inch and
# so snapped like everything else of its; the shape is a disc either way.
GETTER_R = 2.30
GETTER_T = 1.20
GETTER_Z = 15.80

# Note 1 of the drawing counts the pins from an indicator arrow, and it is
# moulded into the underside of the base glass pointing at pin 1, the anode.
ARROW_TIP = 5.00
ARROW_TAIL = 2.60
ARROW_W = 1.70
ARROW_RISE = 0.35


# =========================================================================
# geometry
# =========================================================================
def _point(x, z):
    return App.Vector(x, 0.0, z)


def _line(p0, p1):
    return Part.LineSegment(p0, p1).toShape()


def _fillet_arc(radius: float, z_top: float, fillet: float,
                sign: float) -> Part.Shape:
    """The quarter roll from the side wall onto the flat face, in XZ.

    From (sign*radius, z_top - fillet) to (sign*(radius - fillet), z_top),
    about a centre inboard of the wall. Revolved this is a torus and swept it
    is a cylinder, both exact - and a torus offsets to a torus, so the cavity
    built the same way keeps a truly constant wall.
    """
    corner = sign * (radius - fillet)
    mid = fillet * math.sin(math.pi / 4)
    return Part.Arc(_point(sign * radius, z_top - fillet),
                    _point(corner + sign * mid, z_top - fillet + mid),
                    _point(corner, z_top)).toShape()


def envelope(radius: float, z0: float, z_top: float,
             fillet: float) -> Part.Shape:
    """A stadium prism with a flat face, rolled into it by fillet.

    Swept, not lofted: the two ends are the body of revolution - a cylinder,
    a torus and a disc - and the middle is its silhouette extruded along the
    sweep. That the union of those three is the swept body is not an
    approximation; for a convex body the sweep spans one interval in Y at
    every (x, z), and the three pieces cover it without a gap.
    """
    half = STRAIGHT / 2
    flat = radius - fillet
    profile = Part.Wire(Part.sortEdges([
        _line(_point(0, z0), _point(radius, z0)),
        _line(_point(radius, z0), _point(radius, z_top - fillet)),
        _fillet_arc(radius, z_top, fillet, 1.0),
        _line(_point(flat, z_top), _point(0, z_top)),
        _line(_point(0, z_top), _point(0, z0)),
    ])[0])
    cap = Part.Face(profile).revolve(App.Vector(0, 0, 0),
                                     App.Vector(0, 0, 1), 360)

    silhouette = Part.Wire(Part.sortEdges([
        _line(_point(-radius, z0), _point(radius, z0)),
        _line(_point(radius, z0), _point(radius, z_top - fillet)),
        _fillet_arc(radius, z_top, fillet, 1.0),
        _line(_point(flat, z_top), _point(-flat, z_top)),
        _fillet_arc(radius, z_top, fillet, -1.0),
        _line(_point(-radius, z_top - fillet), _point(-radius, z0)),
    ])[0])
    middle = Part.Face(silhouette).extrude(App.Vector(0, STRAIGHT, 0))

    shape = cap.translated(App.Vector(0, -half, 0))
    for piece in (middle.translated(App.Vector(0, -half, 0)),
                  cap.translated(App.Vector(0, half, 0))):
        shape = shape.fuse([piece])
    return shape


def tip_solid() -> Part.Shape:
    """The exhaust tip under the base centre: a stub with a rounded end."""
    r = TIP_D / 2
    nose = -TIP_LEN + r
    profile = Part.Wire(Part.sortEdges([
        _line(_point(0, 0), _point(r, 0)),
        _line(_point(r, 0), _point(r, nose)),
        Part.Arc(_point(r, nose), _point(r * math.sin(math.pi / 4),
                                         nose - r * math.cos(math.pi / 4)),
                 _point(0, -TIP_LEN)).toShape(),
        _line(_point(0, -TIP_LEN), _point(0, 0)),
    ])[0])
    return Part.Face(profile).revolve(App.Vector(0, 0, 0),
                                      App.Vector(0, 0, 1), 360)


def glass() -> Part.Shape:
    """The envelope, hollowed, with the exhaust tip fused under its base."""
    # The cavity is the true offset, not an approximation of one: a cylinder
    # offsets to a cylinder, a torus to a torus of radius less the wall, and a
    # plane to a plane, so the wall is exactly WALL everywhere including the
    # roll. The elliptical dome this replaced could only be offset approximately.
    hollow = envelope(RADIUS, 0.0, BODY_H, FILLET_R).cut(
        envelope(RADIUS - WALL, BASE_T, BODY_H - WALL, FILLET_R - WALL))
    shape = hollow.fuse([tip_solid()]).fuse([arrow_solid()])
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("glass is not a single valid solid")
    return shape


def pins_solid() -> Part.Shape:
    """Twelve wires through the base, as one compound - they share a material."""
    out = [Part.makeCylinder(PIN_D / 2, PIN_LEN + PIN_INSIDE,
                             App.Vector(x, y, -PIN_LEN))
           for x, y in PINS]
    # The two support rods the spacer columns thread onto. In the reference
    # they are the pair at x = 0 running most of the height, and they are what
    # actually carries the stack; the pins only reach the bottom of it.
    out += [Part.makeCylinder(ROD_R, ROD_TOP - PIN_INSIDE + 1.0,
                              App.Vector(0, sy * SPACER_Y, PIN_INSIDE - 1.0))
            for sy in (-1.0, 1.0)]
    return Part.makeCompound(out)


# =========================================================================
# electrode stack
# =========================================================================
def _sweep(points, z: float) -> Part.Shape:
    """A flat ribbon bent along a planar path, centred on height z.

    Not swept. A flat wire lying in a plane is just its centreline offset both
    ways in that same plane and then given thickness, which is exact, cheap,
    and cannot twist. Sweeping a rectangle along the spine is the obvious way
    and OCCT will not do it - MakeSolid fails on every one of these paths.
    """
    closed = (abs(points[0][0] - points[-1][0]) < 1e-9
              and abs(points[0][1] - points[-1][1]) < 1e-9)
    base = z - CATHODE_T / 2
    pts = [App.Vector(x, y, base) for x, y in (points[:-1] if closed else points)]
    curve = Part.BSplineCurve()
    curve.interpolate(Points=pts, PeriodicFlag=closed)
    wire = Part.Wire([curve.toShape()])
    # An open path offsets both ways and fills straight to a band. A closed
    # one does not - offsetting it just gives a larger loop - so that case is
    # the outer offset less the inner. The flag reads backwards from its own
    # documentation: openResult False is what gives the double-sided band.
    if closed:
        # makeOffset2D will not take a closed loop inward at all, so the two
        # edges are built by walking the points along their own normals. These
        # loops are all smooth and convex enough for that to be exact.
        count = len(pts)
        rims = []
        for side in (1.0, -1.0):
            ring = []
            for i, point in enumerate(pts):
                before, after = pts[i - 1], pts[(i + 1) % count]
                tangent = App.Vector(after.x - before.x, after.y - before.y, 0.0)
                if tangent.Length < 1e-12:
                    tangent = App.Vector(1, 0, 0)
                tangent.normalize()
                normal = App.Vector(-tangent.y, tangent.x, 0.0)
                ring.append(point + normal * (side * CATHODE_W / 2))
            loop = Part.BSplineCurve()
            loop.interpolate(Points=ring, PeriodicFlag=True)
            rims.append(Part.Face(Part.Wire([loop.toShape()])))
        band = rims[0].cut(rims[1]) if rims[0].Area > rims[1].Area             else rims[1].cut(rims[0])
    else:
        band = wire.makeOffset2D(CATHODE_W / 2, 0, True, False)
    return band.extrude(App.Vector(0, 0, CATHODE_T))


def cathodes_solid() -> Part.Shape:
    """The ten numerals and the decimal point, stacked front to back."""
    parts = []
    for index, digit in enumerate(STACK_ORDER):
        z = DIGIT_Z - index * STACK_PITCH
        for path in digits.PATHS[digit]:
            parts.append(_sweep([(x * DIGIT_SCALE, y * DIGIT_SCALE)
                                 for x, y in path], z))
    # The point rides with the back of the stack on the B, and is simply absent
    # on the A, whose pin 12 is unconnected.
    z = DIGIT_Z - (len(STACK_ORDER) - 1) * STACK_PITCH
    for path in digits.DP:
        moved = [((x + digits.DP_AT[0]) * DIGIT_SCALE,
                  (y + digits.DP_AT[1]) * DIGIT_SCALE) for x, y in path]
        parts.append(_sweep(moved, z))
    return Part.makeCompound(parts)


# Nothing inside may reach the bore. The cavity is a stadium, so a rectangle
# does not fit one: at y = 11.75 the bore is only 6.97 across, not the 7.8 a
# 15.6-wide cage wants, and its corners come out through the glass. Everything
# below is therefore trimmed to the stadium rather than drawn square - which is
# also what reconciles the side views, one reading the shield 20 long and the
# other 24.3. Only about 20.3 will go in.
FIT = 0.35  # clearance from the bore


def _reach(across: float) -> float:
    """Half-length available along Y at offset `across` from the axis."""
    r = RADIUS - WALL - FIT
    return STRAIGHT / 2 + math.sqrt(max(0.0, r * r - across * across))


def _span(along: float) -> float:
    """Half-width available along X at offset `along` from the centre."""
    r = RADIUS - WALL - FIT
    over = max(0.0, abs(along) - STRAIGHT / 2)
    return math.sqrt(max(0.0, r * r - over * over))


def _refine(shape: Part.Shape) -> Part.Shape:
    """removeSplitter, reverted if it moves the solid - see ins1.py."""
    try:
        out = shape.removeSplitter()
    except Exception:
        return shape
    if not out.isValid() or abs(out.Volume - shape.Volume) > 1e-6 * shape.Volume:
        return shape
    return out


def _slab(x0, x1, y0, y1, z0, z1) -> Part.Shape:
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, App.Vector(x0, y0, z0))


def _stadium_prism(radius: float, z0: float, z1: float) -> Part.Shape:
    """A plain stadium prism - the tube's own section, at any radius."""
    half = STRAIGHT / 2
    edges = [
        Part.Arc(App.Vector(radius, -half, z0), App.Vector(0, -half - radius, z0),
                 App.Vector(-radius, -half, z0)).toShape(),
        Part.LineSegment(App.Vector(-radius, -half, z0),
                         App.Vector(-radius, half, z0)).toShape(),
        Part.Arc(App.Vector(-radius, half, z0), App.Vector(0, half + radius, z0),
                 App.Vector(radius, half, z0)).toShape(),
        Part.LineSegment(App.Vector(radius, half, z0),
                         App.Vector(radius, -half, z0)).toShape(),
    ]
    wire = Part.Wire(Part.sortEdges(edges)[0])
    return Part.Face(wire).extrude(App.Vector(0, 0, z1 - z0))


def _shell(r_out: float, thickness: float, z0: float, z1: float) -> Part.Shape:
    """A band of the tube's own section, so it curves with the glass."""
    return _stadium_prism(r_out, z0, z1).cut(
        _stadium_prism(r_out - thickness, z0 - 1.0, z1 + 1.0))


def _anode_outline(z: float) -> Part.Wire:
    """The grid's boundary: straight sides, arced ends, as sketched."""
    shoulder = ANODE_ARC_C + math.sqrt(ANODE_ARC_R**2 - ANODE_X**2)
    apex = ANODE_ARC_C + ANODE_ARC_R
    edges = []
    for sy in (-1.0, 1.0):
        edges.append(Part.Arc(
            App.Vector(-sy * ANODE_X, sy * shoulder, z),
            App.Vector(0, sy * apex, z),
            App.Vector(sy * ANODE_X, sy * shoulder, z)).toShape())
    for sx in (-1.0, 1.0):
        edges.append(Part.LineSegment(
            App.Vector(sx * ANODE_X, -sx * shoulder, z),
            App.Vector(sx * ANODE_X, sx * shoulder, z)).toShape())
    return Part.Wire(Part.sortEdges(edges)[0])


def anode_solid() -> Part.Shape:
    """One grid across the face: solid corners, rod holes, mesh between.

    Real wires for the mesh, because it is the first thing seen through the
    glass. There is nothing on the sides - the earlier cage was my invention,
    read into an oblique photograph.
    """
    z0, z1 = ANODE_Z, ANODE_Z + ANODE_T
    sheet = Part.Face(_anode_outline(z0)).extrude(App.Vector(0, 0, ANODE_T))
    far = 40.0
    out = []
    for sy in (-1.0, 1.0):
        band = sheet.common(_slab(-far, far,
                                  min(sy * ANODE_SOLID_Y, sy * far),
                                  max(sy * ANODE_SOLID_Y, sy * far), z0, z1))
        # The slot stops on the rim, which is what closes it. The sketch takes
        # it to 11.771 against an apex of 11.811 - 0.04 of metal is not a
        # bridge - but the border is, so the slot runs up to its inner edge and
        # the four corners are separate from each other and joined by the rim.
        top = ANODE_ARC_C + ANODE_ARC_R - ANODE_BORDER
        band = band.cut(_slab(-ANODE_HOLE_X, ANODE_HOLE_X,
                              min(sy * ANODE_SOLID_Y, sy * top),
                              max(sy * ANODE_SOLID_Y, sy * top),
                              z0 - 1.0, z1 + 1.0))
        for piece in band.Solids:
            out.append(piece)

    # A rim right round the outline, which the wires weld onto.
    outline = _anode_outline(z0)
    try:
        inner = outline.makeOffset2D(-ANODE_BORDER)
        out.extend(sheet.cut(Part.Face(inner).extrude(
            App.Vector(0, 0, ANODE_T))).Solids)
    except Exception:
        pass

    grid = sheet.common(_slab(-far, far, -ANODE_SOLID_Y, ANODE_SOLID_Y, z0, z1))
    r, zc = MESH_WIRE / 2, (z0 + z1) / 2
    rods = []
    for k in range(1, ANODE_ACROSS + 1):
        x = -ANODE_INNER + k * MESH_PITCH
        rods.append(Part.makeCylinder(r, 2 * ANODE_SOLID_Y + 2,
                                      App.Vector(x, -ANODE_SOLID_Y - 1, zc),
                                      App.Vector(0, 1, 0)))
    # The same pitch the other way, straddling the centreline, and it runs out
    # just where the solid bands begin - so those act as the last two lines.
    k = 0
    while (k + 0.5) * MESH_PITCH < ANODE_SOLID_Y:
        for sy in (-1.0, 1.0):
            rods.append(Part.makeCylinder(
                r, 2 * ANODE_X + 2,
                App.Vector(-ANODE_X - 1, sy * (k + 0.5) * MESH_PITCH, zc),
                App.Vector(1, 0, 0)))
        k += 1
    for rodshape in rods:
        piece = rodshape.common(grid)
        if piece.Volume > 1e-9:
            out.extend(piece.Solids)
    return Part.makeCompound(out)


def shields_solid() -> Part.Shape:
    """Back plate and the four end pieces, split by the spacer slots."""
    reach = SHIELD_R + 4.0
    out = []
    for sy in (-1.0, 1.0):
        centre = sy * (SHIELD_END_Y - SHIELD_ARC_R)
        band = Part.makeCylinder(
            SHIELD_ARC_R, SHIELD_Z1 - SHIELD_Z0,
            App.Vector(0, centre, SHIELD_Z0)).cut(Part.makeCylinder(
                SHIELD_ARC_R - SHIELD_T, SHIELD_Z1 - SHIELD_Z0 + 2.0,
                App.Vector(0, centre, SHIELD_Z0 - 1.0)))
        # Keep the arc on this end, then let the bore trim how far round it
        # reaches - which it does long before the arc would close.
        band = band.common(_slab(-reach * 4, reach * 4,
                                 min(sy * 2.0, sy * reach * 6),
                                 max(sy * 2.0, sy * reach * 6),
                                 SHIELD_Z0, SHIELD_Z1))
        for sx in (-1.0, 1.0):
            piece = band.common(_slab(min(sx * SHIELD_GAP, sx * reach),
                                      max(sx * SHIELD_GAP, sx * reach),
                                      -reach * 6, reach * 6,
                                      SHIELD_Z0, SHIELD_Z1))
            piece = piece.common(_stadium_prism(RADIUS - WALL - FIT,
                                                SHIELD_Z0 - 1.0, SHIELD_Z1 + 1.0))
            if piece.Volume > 1e-6:
                out.append(piece)
    half = min(SHIELD_R + STRAIGHT / 2 - 0.4, _reach(SHIELD_R - 1.0))
    out.append(_slab(-(SHIELD_R - 1.0), SHIELD_R - 1.0, -half, half,
                     SHIELD_Z0, SHIELD_Z0 + BACK_T))
    return Part.makeCompound(out)


def bars_solid() -> Part.Shape:
    """One strap down each side, lapping onto the end pieces and stopping.

    It follows the tube where the end pieces do not, so it is cut from a band
    of the envelope's own section lying just outside the shell. Ending it at
    the spacers' outer edge laps it about BAR_OVERLAP past where it first
    crosses an end piece, which is where the two are welded.
    """
    band = _shell(SHIELD_R + BAR_T, BAR_T, BAR_Z0, BAR_Z1)
    reach = SHIELD_R + 4.0
    stop = SHIELD_END_Y
    return Part.makeCompound([
        band.common(_slab(min(0.0, sx * reach), max(0.0, sx * reach),
                          -stop, stop, BAR_Z0, BAR_Z1))
        for sx in (-1.0, 1.0)])


def plate_solid() -> Part.Shape:
    """The plate under the numerals: straight sides, arced ends, teeth.

    The corners sit just inside the bore, which is what locates it, and the
    ends carry the shields' flat radius rather than the glass's - so the shape
    has real corners where a section of the tube would have none.
    """
    corner = _reach(PLATE_X) - 0.10
    # centre of the end arc, from the corner and the radius
    centre = corner - math.sqrt(max(0.0, SHIELD_ARC_R**2 - PLATE_X**2))
    apex = centre + SHIELD_ARC_R
    edges = []
    for sy in (-1.0, 1.0):
        edges.append(Part.Arc(
            App.Vector(-sy * PLATE_X, sy * corner, PLATE_Z),
            App.Vector(0, sy * apex, PLATE_Z),
            App.Vector(sy * PLATE_X, sy * corner, PLATE_Z)).toShape())
    for sx in (-1.0, 1.0):
        edges.append(Part.LineSegment(
            App.Vector(sx * PLATE_X, -sx * corner, PLATE_Z),
            App.Vector(sx * PLATE_X, sx * corner, PLATE_Z)).toShape())
    body = Part.Face(Part.Wire(Part.sortEdges(edges)[0])).extrude(
        App.Vector(0, 0, PLATE_T))

    for sy in (-1.0, 1.0):
        for xt in PLATE_TEETH_X:
            corners = [(xt - PLATE_TOOTH_W, 0.0),
                       (xt + PLATE_TOOTH_W, 0.0),
                       (xt + PLATE_TOOTH_W, sy * PLATE_TOOTH_Y),
                       (xt, sy * PLATE_TOOTH_TIP),
                       (xt - PLATE_TOOTH_W, sy * PLATE_TOOTH_Y)]
            wire = Part.makePolygon(
                [App.Vector(x, y, PLATE_Z) for x, y in corners]
                + [App.Vector(corners[0][0], corners[0][1], PLATE_Z)])
            body = body.fuse([Part.Face(wire).extrude(
                App.Vector(0, 0, PLATE_T))])
    return _refine(body).common(
        _stadium_prism(RADIUS - WALL - FIT - 0.05,
                       PLATE_Z - 1.0, PLATE_Z + PLATE_T + 1.0))


def _flat_to_side(shape: Part.Shape) -> Part.Shape:
    """Move a profile drawn in (across, up) into the tube's YZ plane."""
    m = App.Matrix()
    m.A11, m.A12, m.A13 = 0.0, 0.0, 1.0
    m.A21, m.A22, m.A23 = 1.0, 0.0, 0.0
    m.A31, m.A32, m.A33 = 0.0, 1.0, 0.0
    return shape.transformGeometry(m)


def _wrap(faces, sign: float, z0: float, z1: float) -> Part.Shape:
    """Lay flat profiles onto the glass, following it where it curves.

    The profile is pushed straight through the tube and then met with a thin
    skin of the outside surface, so what survives is exactly the part of the
    marking that lies on the glass - and it wraps round the ends of the section
    on its own, without anything having to be projected.
    """
    # Seen from outside, the far face reads back to front, so a profile bound
    # for it is mirrored first. The quality mark is near enough symmetric not
    # to show it; the lettering very much does.
    if sign < 0:
        flip = App.Matrix()
        flip.A11 = -1.0
        faces = [f.transformGeometry(flip) for f in faces]
    skin = _stadium_prism(RADIUS + marks.INK, z0, z1).cut(
        _stadium_prism(RADIUS, z0 - 1.0, z1 + 1.0))
    reach = RADIUS + 4.0
    side = _slab(min(0.0, sign * reach), max(0.0, sign * reach),
                 -reach * 4, reach * 4, z0, z1)
    out = []
    for face in faces:
        solid = _flat_to_side(face).extrude(App.Vector(2 * reach, 0, 0))
        solid.translate(App.Vector(-reach, 0, 0))
        piece = solid.common(skin).common(side)
        out.extend(piece.Solids)
    return out


def _font() -> str:
    """The first of marks.FONTS that is actually installed.

    A bare name is looked for among the repo's own fonts; a full path is taken
    as given, so a face that cannot be redistributed can still be used to
    generate with without being copied into the tree.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for name in marks.FONTS:
        path = name if os.path.isabs(name) else os.path.join(
            here, "..", "..", "docs", "design_analysis", "fonts", name)
        path = os.path.normpath(path)
        if os.path.exists(path):
            return path
    raise RuntimeError(
        "no font found for the glass markings; tried "
        + ", ".join(marks.FONTS)
        + ". Install it, or point marks.FONTS at another sans with Cyrillic - "
        "note that a different face will set the lettering differently.")


def _text_faces(text: str, height: float, centre, arc: float = 0.0) -> list:
    """Filled glyphs, that many mm tall, centred on (across, up).

    height is the letters' own height, not the font size makeWireString takes -
    those differ by better than two to one and by a different factor in every
    face. The string is set once at a nominal size, measured, and scaled, so
    asking a circle to match the lettering actually matches it.

    arc, if given, is the radius of a baseline curving up over its middle. Each
    letter is placed along it and leaned to suit, rather than the string being
    bent as one piece.
    """
    path = _font()
    glyphs = []
    for group in Part.makeWireString(text, path, 10.0):
        if not group:
            continue
        outer = max(group, key=lambda w: w.BoundBox.DiagonalLength)
        face = Part.Face(outer)
        for w in group:
            if w is not outer:
                face = face.cut(Part.Face(w))
        glyphs.append(face)
    if not glyphs:
        return []

    box = Part.makeCompound(glyphs).BoundBox
    scale = height / box.YLength
    m = App.Matrix()
    m.scale(scale, scale, 1.0)
    glyphs = [g.transformGeometry(m) for g in glyphs]

    box = Part.makeCompound(glyphs).BoundBox
    mid = ((box.XMin + box.XMax) / 2, (box.YMin + box.YMax) / 2)
    out = []
    for glyph in glyphs:
        gb = glyph.BoundBox
        own = ((gb.XMin + gb.XMax) / 2, (gb.YMin + gb.YMax) / 2)
        if arc <= 0.0:
            glyph.translate(App.Vector(centre[0] - mid[0], centre[1] - mid[1], 0))
        else:
            theta = (own[0] - mid[0]) / arc
            glyph.rotate(App.Vector(own[0], own[1], 0.0),
                         App.Vector(0, 0, 1), -math.degrees(theta))
            glyph.translate(App.Vector(
                centre[0] + arc * math.sin(theta) - own[0],
                centre[1] + arc * (math.cos(theta) - 1.0) - (own[1] - mid[1])
                - mid[1] + mid[1] - mid[1],
                0.0))
        out.extend(glyph.Faces)
    return out


def _polygon(points, size: float, centre) -> Part.Face:
    corners = [App.Vector(centre[0] + x * size, centre[1] + y * size, 0.0)
               for x, y in points]
    return Part.Face(Part.makePolygon(corners + [corners[0]]))


def marks_solid() -> Part.Shape:
    """What is printed on the glass: the quality mark one side, type the other.

    The date is 08 82 with the circle and dot between it, the dot at twice the
    radius the reference draws, both to match the tubes in hand.
    """
    out = []

    # The quality mark, one triangle at a time. They abut rather than overlap,
    # and they all carry the same material, so there is nothing to be gained by
    # fusing them first and a boolean to go wrong.
    mark = [_polygon(tri, marks.MARK_SIZE, marks.MARK_AT)
            for tri in marks.QUALITY_MARK]
    mark += _text_faces(marks.MARK_TEXT, marks.MARK_TEXT_H, marks.MARK_TEXT_AT,
                        marks.MARK_TEXT_ARC)
    lo = marks.MARK_AT[1] - marks.MARK_SIZE
    hi = marks.MARK_AT[1] + marks.MARK_SIZE
    out += _wrap(mark, -1.0, lo, hi)

    # type and date on the other side
    other = []
    other += _text_faces(marks.TYPE_TEXT, marks.TYPE_H, marks.TYPE_AT)
    across, up = marks.DATE_AT
    other += _text_faces(marks.DATE_LEFT, marks.DATE_H,
                         (across - marks.DATE_GAP, up))
    other += _text_faces(marks.DATE_RIGHT, marks.DATE_H,
                         (across + marks.DATE_GAP, up))
    centre = App.Vector(across, up, 0.0)
    ring = Part.Face(Part.Wire([Part.makeCircle(marks.DOT_R_OUTER, centre)])).cut(
        Part.Face(Part.Wire([Part.makeCircle(
            marks.DOT_R_OUTER - marks.DOT_R_RING, centre)])))
    other += ring.Faces
    other += Part.Face(Part.Wire([Part.makeCircle(
        marks.DOT_R_INNER, centre)])).Faces
    reach = marks.STAMP_ROWS + 4.0 * marks.STAMP
    out += _wrap(other, 1.0, marks.STAMP_AT - reach,
                 marks.STAMP_AT + reach)
    return Part.makeCompound(out)


def getter_solid() -> Part.Shape:
    """The disc lying flat against the wall, on the long centreline."""
    x = -(RADIUS - WALL - FIT - 0.15)
    return Part.makeCylinder(GETTER_R, GETTER_T, App.Vector(x, 0, GETTER_Z),
                             App.Vector(1, 0, 0))


def spacer_heights() -> list:
    """The underside of each bead, from the back of the stack forward.

    One between every pair of things it has to hold apart: the plate and the
    last digit, each digit and the next, the front digit and the anode - and
    one more on top of the anode. Twelve, which is the count on the tubes.
    """
    out = [DIGIT_Z - k * STACK_PITCH - CATHODE_T / 2 - SPACER_T
           for k in range(10)]                      # under each digit
    out.append(DIGIT_Z + CATHODE_T / 2)             # front digit to anode
    out.append(ANODE_Z + ANODE_T)                   # on top of the anode
    return sorted(out)


def spacers_solid() -> Part.Shape:
    """Two columns of beads, one at every separation in the stack."""
    return Part.makeCompound([
        Part.makeCylinder(SPACER_R, SPACER_T,
                          App.Vector(0, sy * SPACER_Y, z))
        for sy in (-1.0, 1.0) for z in spacer_heights()])


def arrow_solid() -> Part.Shape:
    """The indicator arrow moulded under the base, aimed at pin 1.

    Raised on the outside of the base glass, so it survives the cavity cut and
    reads from below - which is where you count pins from.
    """
    ax, ay = PINS[0]
    angle = math.atan2(ay, ax)
    ux, uy = math.cos(angle), math.sin(angle)
    px, py = -uy, ux
    corners = [(ARROW_TIP * ux, ARROW_TIP * uy),
               (ARROW_TAIL * ux + px * ARROW_W / 2,
                ARROW_TAIL * uy + py * ARROW_W / 2),
               (ARROW_TAIL * ux - px * ARROW_W / 2,
                ARROW_TAIL * uy - py * ARROW_W / 2)]
    wire = Part.makePolygon([App.Vector(x, y, 0.0) for x, y in corners]
                            + [App.Vector(corners[0][0], corners[0][1], 0.0)])
    return Part.Face(wire).extrude(App.Vector(0, 0, -ARROW_RISE))


# =========================================================================
# document
# =========================================================================
MANAGED = ("Glass", "Pins", "Anode", "Cathodes", "Shields", "Bars",
           "Plate", "Spacers", "Getter", "Marks")

APPEARANCE = {
    "Glass": dict(diffuse=(1.00, 1.00, 1.00), specular=(1.00, 1.00, 1.00),
                  ambient=(1.00, 1.00, 1.00), shininess=0.03, transparency=0.78),
    "Pins": dict(diffuse=(0.72, 0.72, 0.74), specular=(0.98, 0.98, 0.98),
                 shininess=0.30),
    "Anode": dict(diffuse=(0.62, 0.63, 0.66), specular=(0.90, 0.90, 0.90),
                  shininess=0.25),
    "Cathodes": dict(diffuse=(0.78, 0.78, 0.80), specular=(0.95, 0.95, 0.95),
                     shininess=0.35),
    "Shields": dict(diffuse=(0.20, 0.19, 0.19), specular=(0.30, 0.30, 0.30),
                    shininess=0.12),
    "Bars": dict(diffuse=(0.74, 0.75, 0.77), specular=(0.95, 0.95, 0.95),
                 shininess=0.35),
    "Plate": dict(diffuse=(0.20, 0.19, 0.19), specular=(0.30, 0.30, 0.30),
                  shininess=0.12),
    "Spacers": dict(diffuse=(0.82, 0.68, 0.76), specular=(0.35, 0.35, 0.35),
                    shininess=0.15),
    "Getter": dict(diffuse=(0.55, 0.56, 0.58), specular=(0.85, 0.85, 0.85),
                   shininess=0.30),
    "Marks": dict(diffuse=(0.10, 0.10, 0.11), specular=(0.20, 0.20, 0.20),
                  shininess=0.10),
}


def _material(diffuse, specular=(0.53, 0.53, 0.53), emissive=(0.0, 0.0, 0.0),
              ambient=(0.33, 0.33, 0.33), shininess=0.90, transparency=0.0):
    """Colours are RGB 0-1, as is transparency - see ins1.py on the two of it."""
    mat = App.Material()
    mat.DiffuseColor = (*diffuse, 1.0)
    mat.SpecularColor = (*specular, 1.0)
    mat.EmissiveColor = (*emissive, 1.0)
    mat.AmbientColor = (*ambient, 1.0)
    mat.Shininess = shininess
    mat.Transparency = transparency
    return mat


def _document():
    docs = App.listDocuments()
    doc = App.getDocument(DOC_NAME) if DOC_NAME in docs else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    return doc


def _place(doc, name: str, shape: Part.Shape, reapply: bool = False):
    """Update in place, so appearance set in the GUI rides through a rebuild."""
    obj = doc.getObject(name)
    fresh = obj is None
    if fresh:
        obj = doc.addObject("Part::Feature", name)
    if fresh or reapply:
        view = getattr(obj, "ViewObject", None)  # None when headless
        spec = APPEARANCE.get(name)
        if view is not None and spec is not None and hasattr(view, "ShapeAppearance"):
            view.ShapeAppearance = (_material(**spec),)
    obj.Shape = shape
    return obj


def _reconcile(doc, built: dict):
    for obj in [*doc.Objects]:
        if obj.Name in MANAGED and obj.Name not in built:
            doc.removeObject(obj.Name)


def _report(built: dict):
    glass_shape = built["Glass"]
    bb = glass_shape.optimalBoundingBox()
    pins = built["Pins"]
    pb = pins.optimalBoundingBox()

    # Solid glass, less the cavity, plus the tip - closed form, so a boolean
    # that quietly ate something shows up here rather than in the render.
    #
    # The cap is the integral of the stadium area over the fillet. With
    # u = radius - fillet and L the straight run, a section at height t into
    # the roll has end radius u + sqrt(r^2 - t^2), and integrating
    # pi*rho^2 + 2*L*rho over t from 0 to r gives the five terms below. At
    # r = radius it collapses to the half-spheroid this replaced, which is the
    # check that it is the same family of shape.
    def volume(radius, straight_h, fillet):
        u, L = radius - fillet, STRAIGHT
        prism = (math.pi * radius**2 + 2 * radius * L) * straight_h
        cap = (math.pi * u**2 * fillet
               + math.pi**2 * u * fillet**2 / 2
               + (2 / 3) * math.pi * fillet**3
               + 2 * L * u * fillet
               + math.pi * L * fillet**2 / 2)
        return prism + cap

    want = (volume(RADIUS, TANGENT, FILLET_R)
            - volume(RADIUS - WALL, TANGENT - BASE_T, FILLET_R - WALL)
            + math.pi * (TIP_D / 2) ** 2 * (TIP_LEN - TIP_D / 2)
            + (2 / 3) * math.pi * (TIP_D / 2) ** 3
            + 0.5 * ARROW_W * (ARROW_TIP - ARROW_TAIL) * ARROW_RISE)

    for label, value, target in [
        ("solids", len(glass_shape.Solids), 1),
        ("valid", glass_shape.isValid(), True),
        ("bop clean", not glass_shape.check(True), True),
        ("glass mm3", f"{glass_shape.Volume:.1f}", f"{want:.1f} closed form"),
        ("body x", f"{bb.XLength:.4f}", f"{BODY_X:.4f}"),
        ("body y", f"{bb.YLength:.4f}", f"{BODY_Y:.4f}"),
        ("height", f"{bb.ZMin:.4f} - {bb.ZMax:.4f}", f"{-TIP_LEN:.4f} - {BODY_H:.4f}"),
        ("pins", len(pins.Solids), "12 + 2 rods"),
        # From the table, not the bounding box: the support rods share this
        # compound and stand outboard of the ring in Y.
        ("pin ring x", f"{max(x for x, _ in PINS) - min(x for x, _ in PINS):.4f}",
         "11.5000"),
        ("pin ring y", f"{max(y for _, y in PINS) - min(y for _, y in PINS):.4f}",
         "18.0000"),
        ("pin reach", f"{pb.ZMin:.4f}", f"{-PIN_LEN:.4f}"),
        ("overall", f"{bb.ZMax - pb.ZMin:.4f}", "35.0000 max"),
    ]:
        print(f"  {label:<14}{value!s:<24}{target}")


def build(reapply_appearance: bool = False):
    doc = _document()
    built = {"Glass": glass(), "Pins": pins_solid(),
             "Anode": anode_solid(), "Cathodes": cathodes_solid(),
             "Shields": shields_solid(), "Bars": bars_solid(),
             "Plate": plate_solid(),
             "Spacers": spacers_solid(), "Getter": getter_solid(),
             "Marks": marks_solid()}
    for name, shape in built.items():
        _place(doc, name, shape, reapply_appearance)
    _reconcile(doc, built)
    doc.recompute()
    _report(built)
    if Gui is not None:
        Gui.SendMsgToActiveView("ViewFit")
