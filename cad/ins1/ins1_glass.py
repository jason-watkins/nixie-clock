"""INS-1 neon indicator - outer glass envelope.

Dimensions are taken from pcb/lib/nixie_clock.3dshapes/INS1.STEP, which is the
only mechanical source we have; the datasheet is electrical only.

The axis is +Z with the origin at the tip of the exhaust pip, so every height in
this file is the height above the board in the through-hole footprint.

Built the way the lamp is made, and the way you would draw it: a glass tube
closed at the top with a dome, pinched flat at the bottom around the lead
wires, and drawn down to an exhaust pip.

    pip       hemisphere, stem and the flare under the press - one revolve
    press     the blade profile padded, bottom edge rounded over
    shoulder  lofted, press -> barrel
    barrel    cylinder
    dome      revolved semi-ellipsoid

Everything except the shoulder is an exact primitive. The press section is
drawn as arcs and lines exactly as measured off the source, so the part of the
lamp whose dimensions matter - the 7.00 x 3.35 blade that has to pass the
milled slot - is not an approximation of anything.

The shoulder is the one region we cannot build. It is a rolling-ball fillet
whose topology changes part way round, and OCCT will not make it; the source
came out of SolidWorks, where Parasolid did the whole thing in one operation.
Its sections are measured instead and live in shoulder_profile.py - see
sample_shoulder.py, which is the only file here that reads the STEP.
"""

import math

import FreeCAD as App
import Part

import shoulder_profile

try:
    from FreeCAD import Gui
except ImportError:
    Gui = None


DOC_NAME = "INS1_Glass"

# --- heights -------------------------------------------------------------
Z_PIP_CENTRE = 1.50  # hemisphere centre; pip stem starts here
Z_SHOULDER = 9.60  # press starts opening out into the barrel
W_BAND_START = 10.2937  # press stops being wider than the barrel
Z_DOME = 27.85  # dome springs from the barrel
Z_APEX = 28.60

R_PIP = 1.50  # pip is dia 3.00
BARREL_R = 3.25  # barrel is dia 6.50
DOME_RISE = 0.75
BLEND_R = 1.00  # rolling-ball radius of the shoulder blends

# --- press section, measured off the source at y = -3 --------------------
# Quarter profile running counter-clockwise from (3.50, 0) to (0, 1.25):
# up the flank, over a rib, down into a jaw flat, and up onto the bead where
# the exhaust tube runs through the middle of the seal.
PRESS_W = 3.50  # half-width, 7.00 across
PRESS_BEAD = 1.25  # bead half-thickness, 2.50 across
PRESS_RIB = 1.675  # rib crest, 3.35 across - the slot dimension

_FLANK = (3.50, 1.025)
_RIB_C, _RIB_R = (2.85, 1.025), 0.65
_RIB_END = (2.3256, 1.4091)
_JAW_R = 1.00
_JAW_OUT_C, _JAW_OUT_P = (1.5189, 2.0), (1.5189, 1.0)
_JAW_IN_C, _JAW_IN_P = (1.0308, 2.0), (1.0308, 1.0)
_BEAD_J = (0.5727, 1.1111)

PRESS_QUARTER = [
    ("line", (PRESS_W, 0.0), _FLANK, None, None),
    ("arc", _FLANK, _RIB_END, _RIB_C, _RIB_R),
    ("arc", _RIB_END, _JAW_OUT_P, _JAW_OUT_C, _JAW_R),
    ("line", _JAW_OUT_P, _JAW_IN_P, None, None),
    ("arc", _JAW_IN_P, _BEAD_J, _JAW_IN_C, _JAW_R),
    ("arc", _BEAD_J, (0.0, PRESS_BEAD), (0.0, 0.0), PRESS_BEAD),
]

# --- underside -----------------------------------------------------------
# As the source has it: a flat face with the press rounded over into it and
# the exhaust tube coming up through the middle.
#
# The tube necks on its way in. It is dia 3.00 below and the bead it becomes
# inside the seal is dia 2.50, and that is the whole reason this closes: a
# straight dia 3.00 stem is wider than the middle of the press and comes out
# through it. Necking so that PIP_NECK + PIP_FILLET is exactly the bead less
# the round-over lands the tube's fillet and the press's round-over on each
# other tangentially at the centerline. Outboard of there the press is thicker
# and the flat face opens into the two crescents the source has.
Z_FACE = 4.60  # flat underside of the press
PRESS_ROUND = 0.05  # round-over on the bottom edge of the press
PIP_FILLET = 0.05  # tube into that face
PIP_NECK = PRESS_BEAD - PRESS_ROUND - PIP_FILLET  # 1.15
NECK_R = 0.30  # rolling-ball radius of the neck itself
PRESS_OVERLAP = 0.01  # see press_solid

# --- interior ------------------------------------------------------------
WALL = 0.75
Z_CAVITY_FLOOR = 11.60
CAVITY_R = BARREL_R - WALL
CAVITY_FILLET = 1.00
CAVITY_DOME_RISE = 0.60

SECTION_POINTS = shoulder_profile.SECTION_POINTS

# Every piece meets its neighbor on a face the two share exactly - the same
# wire, or the same exact circle - so the fuses need no fuzzy tolerance. Reach
# for one only if that stops being true; a fuzzy tolerance is global, and it
# was quietly damaging geometry millimetres away from the join that needed it.


# =========================================================================
# scalar helpers
# =========================================================================
def smoother_step(t: float) -> float:
    """Smooth 0 -> 1 with zero first and second derivative at both ends."""
    x = t**3 * ((6 * t**2) - (15 * t) + 10)
    return max(0.0, min(1.0, x))


def s_curve_span(v0: float, v1: float, r: float) -> float:
    """Height a two-arc blend of radius r needs to carry v0 to v1.

    Fixed by the value change and the radius; it is not a free choice, and a
    band of any other height leaves the blend non-tangent at its ends.
    """
    delta = abs(v1 - v0)
    if delta > 4 * r:
        raise ValueError(f"blend of {delta} needs radius > {delta / 4}, got {r}")
    theta = math.acos(max(-1.0, min(1.0, 1 - delta / (2 * r))))
    return 2 * r * math.sin(theta)


def s_curve(z: float, z0: float, v0: float, v1: float, r: float) -> float:
    """Two tangent arcs of radius r carrying v0 at z0 to v1 at z0 + span.

    Leaves both ends with zero slope, so the blend meets the prismatic regions
    either side without a crease.
    """
    span = s_curve_span(v0, v1, r)
    if z <= z0:
        return v0
    z1 = z0 + span
    if z >= z1:
        return v1

    sign = 1.0 if v1 > v0 else -1.0
    if z <= (z0 + z1) / 2:
        return v0 + sign * (r - math.sqrt(max(0.0, r**2 - (z - z0) ** 2)))
    return v1 - sign * (r - math.sqrt(max(0.0, r**2 - (z1 - z) ** 2)))


# Band ends are derived rather than typed in, because the span is fixed by the
# value change and the radius. The bead carries the whole shoulder; the width
# only starts moving once the press stops being wider than the barrel. These
# two curves describe the measured shoulder and _report checks it still obeys
# them: the section is a circular arc of radius s_curve(bead) over the middle
# and reaches s_curve(width) at the flanks.
Z_SHOULDER_END = Z_SHOULDER + s_curve_span(PRESS_BEAD, BARREL_R, BLEND_R)
Z_W_BAND_END = W_BAND_START + s_curve_span(PRESS_W, BARREL_R, BLEND_R)


# =========================================================================
# the press section
# =========================================================================
def _arc_midpoint(centre, radius, p0, p1):
    a0 = math.atan2(p0[1] - centre[1], p0[0] - centre[0])
    a1 = math.atan2(p1[1] - centre[1], p1[0] - centre[0])
    sweep = a1 - a0
    while sweep > math.pi:
        sweep -= 2 * math.pi
    while sweep < -math.pi:
        sweep += 2 * math.pi
    mid = a0 + sweep / 2
    return (centre[0] + radius * math.cos(mid), centre[1] + radius * math.sin(mid))


def _mirror(segments, sx, sy):
    """Reflect a run of segments and reverse it, so it still runs end to end."""
    out = []
    for kind, p0, p1, c, r in reversed(segments):
        out.append((kind,
                    (sx * p1[0], sy * p1[1]),
                    (sx * p0[0], sy * p0[1]),
                    None if c is None else (sx * c[0], sy * c[1]),
                    r))
    return out


def press_outline(z: float = 0.0) -> Part.Wire:
    """The press section as drawn: 24 exact arcs and lines, closed and G1."""
    half = PRESS_QUARTER + _mirror(PRESS_QUARTER, -1, 1)
    segments = half + _mirror(half, 1, -1)

    edges = []
    for kind, p0, p1, centre, radius in segments:
        v0 = App.Vector(p0[0], p0[1], z)
        v1 = App.Vector(p1[0], p1[1], z)
        if kind == "line":
            edges.append(Part.LineSegment(v0, v1).toShape())
        else:
            mx, my = _arc_midpoint(centre, radius, p0, p1)
            edges.append(Part.Arc(v0, App.Vector(mx, my, z), v1).toShape())
    return Part.Wire(edges)


def press_points(n_pts: int = SECTION_POINTS) -> list:
    """n_pts points evenly spaced by arc length around the press section.

    Even spacing matters: the jaw flats and the ribs occupy a narrow band of
    polar angle, so sampling by angle starves the features that give the seal
    its shape. discretize() spaces by curvilinear abscissa, which is what we
    want, and the last point repeats the first, so drop it.
    """
    return [(p.x, p.y) for p in press_outline().discretize(Number=n_pts + 1)[:-1]]


def spline_wire(points, z: float) -> Part.Wire:
    """A closed periodic B-spline through 2D points, placed at height z.

    Every section fed to a loft must be a single edge with the same pole count,
    or the loft produces a self-intersecting mess rather than failing.
    """
    curve = Part.BSplineCurve()
    # PeriodicFlag closes the curve; repeating the first point at the end
    # instead raises OCCError: BSplCLib::Interpolate.
    curve.interpolate(Points=[App.Vector(x, y, z) for x, y in points],
                      PeriodicFlag=True)
    return Part.Wire([curve.toShape()])


def press_wire(z: float) -> Part.Wire:
    """The press section as a single spline edge, for padding and lofting.

    The pad and the shoulder share this one representation so their common
    faces are identical rather than merely coincident.
    """
    return spline_wire(press_points(), z)


# =========================================================================
# shoulder sections
# =========================================================================
def _from_quarter(quarter: list) -> list:
    """Expand a stored quarter section back to the full ring.

    Stored counter-clockwise from +x to +y, so index k mirrors about the y
    axis, then the origin, then the x axis.
    """
    q = len(quarter) - 1
    out = []
    for k in range(4 * q):
        if k <= q:
            x, y = quarter[k]
        elif k <= 2 * q:
            x, y = quarter[2 * q - k]
            x = -x
        elif k <= 3 * q:
            x, y = quarter[k - 2 * q]
            x, y = -x, -y
        else:
            x, y = quarter[4 * q - k]
            y = -y
        out.append((x, y))
    return out


HOLD = 0.02  # length of the flat run at each end of a loft


def shoulder_stations() -> list:
    """(height, section) up the shoulder, pinned to its neighbors at both ends.

    The end sections are repeated a hair inside. makeLoft uses a free end
    condition, so without that the skin leaves its first station on a slope -
    12 to 17 degrees here - and creases against the prism or cylinder it is
    supposed to continue. Two identical sections in a row force it vertical.
    """
    barrel = [(BARREL_R * math.cos(2 * math.pi * k / SECTION_POINTS),
               BARREL_R * math.sin(2 * math.pi * k / SECTION_POINTS))
              for k in range(SECTION_POINTS)]
    press = press_points()  # identical to the pad below
    return ([(Z_SHOULDER, press), (Z_SHOULDER + HOLD, press)]
            + [(z, _from_quarter(q)) for z, q in shoulder_profile.SECTIONS]
            + [(Z_SHOULDER_END - HOLD, barrel), (Z_SHOULDER_END, barrel)])


def _smooth_stations(sections: list, passes: int = 1) -> list:
    """Binomial-filter each point's path up the stack, ends held fixed.

    Slicing the source leaves a few microns of jitter per station, which the
    loft turns into ripples running around the shoulder - and, because the
    spline reaches outward between wavy stations, into 0.04 mm of extra width.
    Smoothing along Z removes both without touching the section shapes.
    """
    out = [list(s) for s in sections]
    for _ in range(passes):
        prev = [list(s) for s in out]
        for i in range(1, len(out) - 1):
            for k in range(len(out[i])):
                out[i][k] = tuple(
                    0.25 * prev[i - 1][k][a] + 0.5 * prev[i][k][a]
                    + 0.25 * prev[i + 1][k][a] for a in (0, 1))
    return out


def shoulder_points(z: float) -> list:
    """The section nearest height z, for measurement rather than lofting."""
    return min(shoulder_stations(), key=lambda r: abs(r[0] - z))[1]


def blend_points(points, radius: float, mx: float, my: float) -> list:
    """Morph a section towards a circle, x and y weighted separately.

    Point k is paired with the point the same fraction of the way round the
    circle. Both shapes are symmetric about both axes, so the four extremes
    stay paired and each silhouette can be steered on its own.
    """
    n = len(points)
    return [((1 - mx) * px + mx * radius * math.cos(2 * math.pi * k / n),
             (1 - my) * py + my * radius * math.sin(2 * math.pi * k / n))
            for k, (px, py) in enumerate(points)]


def _stations(lo: float, hi: float, step: float) -> list:
    count = math.ceil((hi - lo) / step - 1e-9)
    return [min(lo + k * step, hi) for k in range(count + 1)]


# =========================================================================
# solids
# =========================================================================
def _refine(shape: Part.Shape) -> Part.Shape:
    """removeSplitter, but only if it leaves the solid alone.

    It merges coplanar and co-surface faces, which tidies the seams between
    the fused pieces. On this shape it sometimes merges faces it should not
    and silently returns a solid of 1128 mm3 in place of one of 714, still
    reporting isValid(). Losing a seam is much cheaper than losing the solid.
    """
    try:
        refined = shape.removeSplitter()
    except Exception:
        return shape
    if not refined.isValid() or len(refined.Solids) != len(shape.Solids):
        return shape
    if abs(refined.Volume - shape.Volume) > 1e-6 * abs(shape.Volume):
        return shape
    return refined


def _loft(wires) -> Part.Shape:
    shape = Part.makeLoft(wires, True, False, False, 3)
    # A diverged loft still reports isValid(), so check the envelope instead.
    # Booleans against a self-intersecting solid run for many minutes before
    # giving up, which is a far worse way to find out.
    bb = shape.BoundBox
    if shape.Volume < 0 or bb.XLength > 2 * PRESS_W + 0.5:
        raise RuntimeError(
            f"loft diverged: volume {shape.Volume:.1f}, "
            f"bbox {bb.XLength:.1f} x {bb.YLength:.1f} - use closer stations")
    return shape


def _point(r, z):
    return App.Vector(r, 0.0, z)


def _line(p0, p1):
    return Part.LineSegment(p0, p1).toShape()


def _spline(points):
    curve = Part.BSplineCurve()
    curve.interpolate(Points=[_point(r, z) for r, z in points])
    return curve.toShape()


def revolve(edges) -> Part.Shape:
    """Revolve a closed profile about Z. Edges may be given in any order."""
    wire = Part.Wire(Part.sortEdges(edges)[0])
    return Part.Face(wire).revolve(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 360)


def ellipse_arc(a: float, b: float, z0: float, points: int = 33) -> list:
    """Quarter ellipse from (a, z0) to (0, z0 + b), as (radius, height) pairs."""
    return [(a * math.cos(math.pi / 2 * k / (points - 1)),
             z0 + b * math.sin(math.pi / 2 * k / (points - 1)))
            for k in range(points)]


def _circle_wire(radius: float, z: float) -> Part.Wire:
    """An exact circle, for a face that has to mate with a primitive."""
    return Part.Wire([Part.makeCircle(radius, _point(0, z), App.Vector(0, 0, 1))])


NECK_SPAN = s_curve_span(R_PIP, PIP_NECK, NECK_R)
Z_NECK_TOP = Z_FACE - PIP_FILLET
Z_NECK_BOT = Z_NECK_TOP - NECK_SPAN


def pip_solid() -> Part.Shape:
    """Tip, stem, the neck into the seal, and the flat face it lands on."""
    tip_mid = (R_PIP * math.sin(math.pi / 4),
               Z_PIP_CENTRE - R_PIP * math.cos(math.pi / 4))
    neck = [(s_curve(Z_NECK_BOT + NECK_SPAN * k / 32, Z_NECK_BOT,
                     R_PIP, PIP_NECK, NECK_R),
             Z_NECK_BOT + NECK_SPAN * k / 32) for k in range(33)]
    d = PIP_FILLET * math.sin(math.pi / 4)
    return revolve([
        Part.Arc(_point(0.0, 0.0), _point(*tip_mid),
                 _point(R_PIP, Z_PIP_CENTRE)).toShape(),
        _line(_point(R_PIP, Z_PIP_CENTRE), _point(R_PIP, Z_NECK_BOT)),
        _spline(neck),
        Part.Arc(_point(PIP_NECK, Z_NECK_TOP),
                 _point(PIP_NECK + PIP_FILLET - d, Z_NECK_TOP + d),
                 _point(PIP_NECK + PIP_FILLET, Z_FACE)).toShape(),
        # Carry straight on for PRESS_OVERLAP above the face, so the fuse has
        # a volume rather than a shared plane. The stem is exactly the bead
        # less the round-over, so it stays inside the press all the way.
        _line(_point(PIP_NECK + PIP_FILLET, Z_FACE),
              _point(PIP_NECK + PIP_FILLET, Z_FACE + PRESS_OVERLAP)),
        _line(_point(PIP_NECK + PIP_FILLET, Z_FACE + PRESS_OVERLAP),
              _point(0, Z_FACE + PRESS_OVERLAP)),
        _line(_point(0, Z_FACE + PRESS_OVERLAP), _point(0, 0.0)),
    ])


def press_solid() -> Part.Shape:
    """The pinch seal: the drawn section padded, bottom edge rounded over.

    The bottom edge round-over is what the flat underside blends through; the
    tube's fillet lands tangent to that same plane, and pip_solid carries the
    overlap the fuse needs.
    """
    base = Z_FACE
    pad = Part.Face(press_wire(base)).extrude(
        App.Vector(0, 0, Z_SHOULDER - base))
    bottom = [e for e in pad.Edges
              if abs(e.BoundBox.ZMin - base) < 1e-6
              and abs(e.BoundBox.ZMax - base) < 1e-6]
    return pad.makeFillet(PRESS_ROUND, bottom)


def shoulder_solid() -> Part.Shape:
    """Press to barrel, from the measured sections.

    The top section is an exact circle rather than a spline through points on
    one. A spline circle misses a true one by about a micron, and that is
    enough that fusing the barrel onto it passes isValid() while failing a BOP
    check - and every boolean after it inherits the damage. The bottom section
    needs no such treatment because it is the same wire the pad was made from.
    """
    rows = shoulder_stations()
    smoothed = _smooth_stations([pts for _, pts in rows])
    wires = [spline_wire(pts, z) for (z, _), pts in zip(rows, smoothed)]
    wires[0] = press_wire(Z_SHOULDER)
    wires[1] = press_wire(Z_SHOULDER + HOLD)
    wires[-2] = _circle_wire(BARREL_R, Z_SHOULDER_END - HOLD)
    wires[-1] = _circle_wire(BARREL_R, Z_SHOULDER_END)
    return _loft(wires)


def _bulb() -> Part.Shape:
    """Press, shoulder, barrel and dome - everything the cavity reaches.

    Folded in one at a time. Handing all the pieces to a single fuse returns a
    solid of 1116 mm3 in place of one of 714 while still reporting it valid.
    """
    barrel = Part.makeCylinder(BARREL_R, Z_DOME - Z_SHOULDER_END,
                               _point(0, Z_SHOULDER_END))
    dome = revolve([
        _spline(ellipse_arc(BARREL_R, DOME_RISE, Z_DOME)),
        _line(_point(0, Z_APEX), _point(0, Z_DOME)),
        _line(_point(0, Z_DOME), _point(BARREL_R, Z_DOME)),
    ])
    shape = press_solid()
    for piece in (shoulder_solid(), barrel, dome):
        shape = shape.fuse([piece])
    return _refine(shape)


def outer_glass() -> Part.Shape:
    """The complete outer surface, as one solid."""
    # see glass() on not refining here
    shape = _bulb().fuse([pip_solid()])
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("outer glass is not a single valid solid")
    return shape


def cavity() -> Part.Shape:
    """The evacuated interior: a flat-floored well with a domed ceiling."""
    corner = CAVITY_R - CAVITY_FILLET
    fillet_top = Z_CAVITY_FLOOR + CAVITY_FILLET
    diag = CAVITY_FILLET * math.sin(math.pi / 4)
    dome_start = Z_APEX - CAVITY_DOME_RISE - WALL

    return revolve([
        _line(_point(0, Z_CAVITY_FLOOR), _point(corner, Z_CAVITY_FLOOR)),
        Part.Arc(_point(corner, Z_CAVITY_FLOOR),
                 _point(corner + diag, fillet_top - diag),
                 _point(CAVITY_R, fillet_top)).toShape(),
        _line(_point(CAVITY_R, fillet_top), _point(CAVITY_R, dome_start)),
        _spline(ellipse_arc(CAVITY_R, CAVITY_DOME_RISE, dome_start)),
        _line(_point(0, dome_start + CAVITY_DOME_RISE), _point(0, Z_CAVITY_FLOOR)),
    ])


def glass() -> Part.Shape:
    # Cut the cavity before the pip goes on, so the cut only ever sees the
    # part of the solid it actually reaches.
    #
    # Do not refine after the pip. removeSplitter on the finished shape runs
    # for minutes and then returns a solid of 1122 mm3 in place of one of 401,
    # still reporting it valid. What it would have bought is a few merged
    # seams around the pip, which carry no dihedral and cost nothing to keep.
    hollow = _refine(_bulb().cut(cavity()))
    shape = hollow.fuse([pip_solid()])
    if not shape.isValid() or len(shape.Solids) != 1:
        raise RuntimeError("cavity cut did not leave a single valid solid")
    return shape


# =========================================================================
# document
# =========================================================================
# What this script owns. Anything else in the document is left alone, so you
# can park sketches, sections or an imported source next to the model without
# a rebuild eating them.
MANAGED = ("Glass", "Sections")

# Applied once, when a part is first created. After that the document wins, so
# anything you change in the GUI survives a rebuild - which matters because
# KiCad takes its appearance from the WRL, and the WRL takes it from here.
APPEARANCE = {
    "Glass": {"ShapeColor": (0.85, 0.90, 0.90), "Transparency": 82},
}


def _document():
    docs = App.listDocuments()
    doc = App.getDocument(DOC_NAME) if DOC_NAME in docs else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    return doc


def _place(doc, name: str, shape: Part.Shape):
    """Create or update one part, keeping whatever the document already says.

    Assigning to Shape replaces the geometry in place, so colour, transparency
    and visibility ride through a rebuild. Deleting and re-showing - which is
    what Part.show does, suffixing the name if one is already there - throws
    all of that away every run.
    """
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


def _reconcile(doc, built: dict):
    """Drop only the parts we own that this run did not produce."""
    for obj in [*doc.Objects]:
        if obj.Name in MANAGED and obj.Name not in built:
            doc.removeObject(obj.Name)


def seat_height() -> float:
    """Height at which the section first fills the 4.2 mm recessed slot.

    By the time the section is this thick the rising bead has long overtaken
    the ribs, so the thickest part of it is the bead and the seat is just
    where that S-curve reaches 2.1. Solved rather than read off the stations,
    which are 0.1 apart and would quantize the answer by 0.02; _report checks
    the stations really do follow the curve.
    """
    lo, hi = Z_SHOULDER, Z_SHOULDER_END
    for _ in range(60):
        mid = (lo + hi) / 2
        if 2 * s_curve(mid, Z_SHOULDER, PRESS_BEAD, BARREL_R, BLEND_R) < 4.20:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _report(shape):
    section = press_wire(0.0)  # the spline the pad is actually built from
    bb = shape.optimalBoundingBox()  # BoundBox on a spline solid reads wide
    ob = section.BoundBox
    for label, value, target in [
        ("solids", len(shape.Solids), 1),
        ("valid", shape.isValid(), True),
        ("volume mm3", f"{shape.Volume:.2f}", "~400 hollow"),
        ("height", f"{bb.ZMin:.4f} - {bb.ZMax:.4f}", "0.0000 - 28.6000"),
        ("press width", f"{ob.XLength:.4f}", "7.0000"),
        ("press thickness", f"{ob.YLength:.4f}", "3.3500"),
        ("widest section", f"{bb.XLength:.4f}", "7.0000"),
        ("barrel dia", f"{bb.YLength:.4f}", "6.5000"),
        ("seat height", f"{seat_height():.4f}", "10.5887"),
    ]:
        print(f"  {label:<18}{value!s:<22}{target}")

    # The measured shoulder should still obey the two S-curves that describe
    # it. If it drifts, the source or the band definitions moved.
    worst_w = worst_b = 0.0
    for z, pts in shoulder_stations()[1:-1]:
        worst_w = max(worst_w, abs(max(x for x, _ in pts)
                                   - s_curve(z, W_BAND_START, PRESS_W, BARREL_R, BLEND_R)))
        worst_b = max(worst_b, abs(max(abs(y) for x, y in pts if abs(x) < 0.05)
                                   - s_curve(z, Z_SHOULDER, PRESS_BEAD, BARREL_R, BLEND_R)))
    print(f"  {'shoulder anchors':<18}"
          f"{f'width {worst_w:.4f}, bead {worst_b:.4f}':<22}both < 0.01")


def build(show_sections: bool = False):
    doc = _document()

    if show_sections:
        built = {"Sections": Part.makeCompound(
            [spline_wire(pts, z) for z, pts in shoulder_stations()])}
    else:
        built = {"Glass": glass()}

    for name, shape in built.items():
        _place(doc, name, shape)
    _reconcile(doc, built)
    doc.recompute()

    if show_sections:
        print(f"  {len(shoulder_stations())} shoulder sections")
    else:
        _report(built["Glass"])

    if Gui is not None:
        Gui.SendMsgToActiveView("ViewFit")
