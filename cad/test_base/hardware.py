"""M3 hardware from the two kits, as parametric solids.

These are stand-ins, not detail models. Threads are plain cylinders, and
deliberately mismatched: a screw's thread is drawn a little under nominal and
the tapped bore of a standoff or a nut a little over, so a screw sitting in one
does not read as an interference. Everything that is genuinely a fit - a hex
across flats in a printed pocket, a head in a counterbore, a stud in a bore - is
drawn at its real size, because those are the ones worth checking.

Every part is built along +Z with its datum at the origin, where the datum is
the face that seats: the bearing face under a screw head, the bearing face of a
nut, the bottom of a standoff. `oriented` then puts it where it goes. That
convention is what makes placement one line per fastener instead of a rotation
puzzle.

Kit contents, from the two assortments:

    standoffs   F/F  6, 10, 15, 20            hex, brass
                M/F  6, 10, 15, 20 plus a 6 mm stud
    nuts        M3, 5.5 across flats, 2.4 thick
    screws      socket cap 6, 8, 10, 12, 16, 20, 25, 30
                pan head 6, in the standoff kit
"""

import math

import FreeCAD as App
import Part

# --- kit -----------------------------------------------------------------
STANDOFF_LENGTHS = (6, 10, 15, 20)
STUD_L = 6.00  # the male end of an M/F standoff
CAP_LENGTHS = (6, 8, 10, 12, 16, 20, 25, 30)

# --- dimensions ----------------------------------------------------------
AF = 5.50  # hex across flats, standoff and nut alike
NUT_T = 2.40
HEAD_D = 5.50  # ISO 4762 socket cap
HEAD_H = 3.00
SOCKET_AF = 2.50
SOCKET_DEPTH = 1.30
THREAD_D = 2.90  # drawn under nominal
BORE_D = 3.05  # drawn over, so a screw inside one is not a clash


def hex_prism(af: float, length: float, z: float = 0.0,
              phase: float = 0.0) -> Part.Shape:
    """A hexagonal prism of across-flats af, from z along +Z.

    Vertices on the X axis by default, matching the pockets in the printed
    parts, so a standoff drops into a register without being turned. `phase`
    rolls it, which matters only where a pocket is drawn to a different clock -
    a hex rotated from +Z onto another axis does not keep its vertex up, and a
    nut going into a vertex-up pocket wants phase 30 to land right. Physically a
    nut has six ways in and any of them works; the phase is only so the model
    reads true.
    """
    r = af / math.sqrt(3.0)
    pts = [App.Vector(r * math.cos(math.radians(phase + 60 * k)),
                      r * math.sin(math.radians(phase + 60 * k)), z)
           for k in range(6)]
    face = Part.Face(Part.makePolygon(pts + [pts[0]]))
    return face.extrude(App.Vector(0.0, 0.0, length))


def standoff(length: float, stud: float = 0.0) -> Part.Shape:
    """A hex standoff, datum at its bottom face.

    stud = 0 gives female/female, the kit's plain set. Any other value gives
    male/female with a stud of that length off the top, which is how the +6 set
    is drawn.
    """
    if length not in STANDOFF_LENGTHS:
        raise ValueError(f"no {length} mm standoff in the kit {STANDOFF_LENGTHS}")
    body = hex_prism(AF, length)
    body = body.cut(Part.makeCylinder(BORE_D / 2, length + 2.0,
                                      App.Vector(0, 0, -1.0)))
    if stud:
        body = body.fuse(Part.makeCylinder(THREAD_D / 2, stud,
                                           App.Vector(0, 0, length)))
    return body.removeSplitter()


def cap_screw(length: float) -> Part.Shape:
    """A socket cap screw, datum at the bearing face under the head.

    The head therefore hangs below the datum and the thread runs above it,
    which is how a joint is actually dimensioned: from the face it pulls
    against.
    """
    if length not in CAP_LENGTHS:
        raise ValueError(f"no M3 x {length} in the kit {CAP_LENGTHS}")
    head = Part.makeCylinder(HEAD_D / 2, HEAD_H, App.Vector(0, 0, -HEAD_H))
    socket = hex_prism(SOCKET_AF, SOCKET_DEPTH + 0.01, -HEAD_H)
    return head.cut(socket).fuse(
        Part.makeCylinder(THREAD_D / 2, length)).removeSplitter()


def nut(phase: float = 0.0) -> Part.Shape:
    """An M3 hex nut, datum at its bearing face, body along +Z."""
    body = hex_prism(AF, NUT_T, phase=phase)
    return body.cut(Part.makeCylinder(BORE_D / 2, NUT_T + 2.0,
                                      App.Vector(0, 0, -1.0))).removeSplitter()


def oriented(shape: Part.Shape, at: tuple, axis: tuple = (0, 0, 1)) -> Part.Shape:
    """Put a part built along +Z at `at`, pointing `axis`."""
    target = App.Vector(*axis)
    placed = shape.copy()
    if target.getAngle(App.Vector(0, 0, 1)) > 1e-9:
        placed.rotate(App.Vector(0, 0, 0),
                      App.Vector(0, 0, 1).cross(target)
                      if abs(target.z) < 1.0 - 1e-9 else App.Vector(1, 0, 0),
                      math.degrees(target.getAngle(App.Vector(0, 0, 1))))
    placed.translate(App.Vector(*at))
    return placed
