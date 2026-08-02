"""Panasonic ECQ-E2104KB - 0.10 uF 250 V DC metallized polyester film capacitor.

Drawn to replace the manufacturer's own STEP file, which is a plain box 7.9 x
5.9 x 14.0 on two wires. The 14.0 gives it away: that is H max for the crimped
lead form, and this part number has no lead-form suffix, so it is the straight
one at 9.0. The box was 5 mm too tall and the wrong shape.

The part number decodes off page 1 of docs/datasheets/ABD0000C180.pdf, which
splits it into twelve positions:

    EC        product code
    QE        dielectric and construction
    2         250 V DC
    104       0.10 uF
    K         +-10 %
    B         series suffix, carried by every part in the series
    -         lead form, and this one is blank, which means straight

The ratings table on page 3 lists the part as ECQE2104(tol)B(form) and gives,
for the straight form:

    L max   7.9   body length
    T max   5.9   body thickness
    H max   9.0   body height
    F       5.0   lead spacing
    od      0.5   lead diameter, copper-clad steel
    20 min        lead length

There is one more dimension on the page 2 outline, 1.0 max, which is how far
the epoxy may run down the leads below the body. It is a maximum with no
nominal, so it is not drawn; the consequence is that a part pushed all the way
down can stand 10.0 rather than 9.0 above the board, and that is the figure to
use for clearance, not this model's height.

The body is the intersection of the three views. Each one is a rounded
rectangle swept along the axis it is drawn on:

    front, in XZ   7.9 x 9.0, 1.8 on the top corners   ->  swept through Y
    side,  in YZ   5.9 x 9.0, top a 2.95 half round    ->  swept through X
    plan,  in XY   7.9 x 5.9, 1.2 on all four corners  ->  swept through Z

and all three take a 0.4 round along the bottom. That is the shape a dipped
part actually has - a loaf, flat on the two large faces where the winding is,
rounded everywhere the epoxy was free to pull itself round - and it comes out
of three prisms and no fillets, so there is no blend for OCCT to fail on. Each
view is the outline as drawn, so the model cannot silhouette wrong from any of
the three directions.

The frame is KiCad's for this family: origin on lead 1, +X toward lead 2, Z = 0
the top of the board. The leads are cut at Z = -1.9, which is where all 177
C_Rect models in the stock Capacitor_THT library end theirs, rather than at the
20 mm the part is really supplied with.
"""

import math
import os

import FreeCAD as App
import Part

try:
    from FreeCAD import Gui
except ImportError:
    Gui = None

WINDOWED = Gui is not None
DOC_NAME = "ECQE2104KB"

# --- datasheet, straight lead form ---------------------------------------
L = 7.90  # body length
T = 5.90  # body thickness
H = 9.00  # body height
F = 5.00  # lead spacing
D_LEAD = 0.50
RUNOFF = 1.00  # epoxy down the leads, max; see the docstring

# --- shape, read off the page 2 outlines and the product photograph -------
R_END = 1.80  # front view, top corners
R_TOP = T / 2  # side view, top: a full half round
R_PLAN = 1.20  # plan view, all four corners
R_BOT = 0.40  # the bottom edge, all round

# --- frame ---------------------------------------------------------------
X_MID = F / 2  # the body is centred between the leads
Z_TIP = -1.90  # lead ends, KiCad's C_Rect convention

# --- colour --------------------------------------------------------------
EPOXY = (0.52, 0.22, 0.16)  # the brown of the flame-retardant coating
TINNED_STEEL = (0.824, 0.820, 0.781)  # as the stock KiCad leads

try:
    STEP_PATH = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "pcb", "lib", "nixie_clock.3dshapes", "ECQ-E.stp"))
except NameError:  # pasted into the console rather than run as a file
    STEP_PATH = ""


def rounded_face(corners, radii, into) -> Part.Face:
    """A planar face through corners, each rounded to its own radius.

    corners are (u, v) pairs in the plane's own coordinates and `into` maps a
    pair to a point in space, which is what lets the same routine draw all
    three views. Corners are taken in order and closed back to the first.

    A radius may be large enough that its two tangent points meet its
    neighbour's - the half round on top of the side view is two quarter arcs
    with nothing between them - so the straight run between consecutive arcs is
    emitted only when it has length.
    """
    pts = [App.Vector(u, v, 0.0) for u, v in corners]
    n = len(pts)
    arcs = []
    for i, cur in enumerate(pts):
        d1 = (pts[i - 1] - cur).normalize()
        d2 = (pts[(i + 1) % n] - cur).normalize()
        r = radii[i]
        if r <= 0.0:
            arcs.append((cur, None, cur))
            continue
        half = d1.getAngle(d2) / 2.0
        t1, t2 = cur + d1 * (r / math.tan(half)), cur + d2 * (r / math.tan(half))
        centre = cur + (d1 + d2).normalize() * (r / math.sin(half))
        mid = centre + ((t1 - centre) + (t2 - centre)).normalize() * r
        arcs.append((t1, mid, t2))

    edges = []
    for i, (t1, mid, t2) in enumerate(arcs):
        if mid is not None:
            edges.append(Part.Arc(into(t1.x, t1.y), into(mid.x, mid.y),
                                  into(t2.x, t2.y)).toShape())
        nxt = arcs[(i + 1) % n][0]
        if (nxt - t2).Length > 1e-9:
            edges.append(Part.LineSegment(into(t2.x, t2.y),
                                          into(nxt.x, nxt.y)).toShape())
    return Part.Face(Part.Wire(edges))


def body() -> Part.Shape:
    """The epoxy body: the three views intersected.

    Each prism is swept a millimetre past the body at both ends, so no sweep
    end ever cuts the result and every face of it comes from an outline. Where
    two outlines describe the same face - the bottom, the two ends, the two
    large faces - they are drawn to the same numbers, which is what carries the
    0.4 round the whole way round the bottom edge.
    """
    x0, x1 = X_MID - L / 2, X_MID + L / 2

    front = rounded_face(
        [(x0, 0.0), (x1, 0.0), (x1, H), (x0, H)],
        [R_BOT, R_BOT, R_END, R_END],
        lambda u, v: App.Vector(u, -(T / 2 + 1.0), v),
    ).extrude(App.Vector(0.0, T + 2.0, 0.0))

    side = rounded_face(
        [(-T / 2, 0.0), (T / 2, 0.0), (T / 2, H), (-T / 2, H)],
        [R_BOT, R_BOT, R_TOP, R_TOP],
        lambda u, v: App.Vector(x0 - 1.0, u, v),
    ).extrude(App.Vector(L + 2.0, 0.0, 0.0))

    plan = rounded_face(
        [(x0, -T / 2), (x1, -T / 2), (x1, T / 2), (x0, T / 2)],
        [R_PLAN] * 4,
        lambda u, v: App.Vector(u, v, -1.0),
    ).extrude(App.Vector(0.0, 0.0, H + 2.0))

    return front.common(side).common(plan)


def leads() -> Part.Shape:
    """Both leads, cut off flush at Z_TIP and butted to the body's underside."""
    return Part.makeCompound([
        Part.makeCylinder(D_LEAD / 2, -Z_TIP, App.Vector(x, 0.0, Z_TIP))
        for x in (0.0, F)
    ])


PARTS = {"Body": (body, EPOXY), "Leads": (leads, TINNED_STEEL)}


# =========================================================================
# document
# =========================================================================
def _gui():
    """FreeCADGui, started offscreen when this is run under freecadcmd.

    Colour is a property of the view provider rather than of the shape, and
    ImportGui is the only STEP writer that reads it, so a build with no window
    still has to bring the Gui module up or the file comes out untinted.
    setupWithoutGUI() is not enough - it loads the module but attaches no view
    provider, so every object comes back with ViewObject None. showMainWindow()
    does attach them, and Qt's offscreen platform keeps it from putting a
    window on the screen. It complains on the way up about the OpenGL widget
    and its fonts, neither of which anything here uses.
    """
    global Gui
    if Gui is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import FreeCADGui
        FreeCADGui.showMainWindow()
        Gui = FreeCADGui
    return Gui


def _document():
    _gui()
    docs = App.listDocuments()
    doc = App.getDocument(DOC_NAME) if DOC_NAME in docs else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    for obj in [*doc.Objects]:
        doc.removeObject(obj.Name)
    return doc


def _show(shape: Part.Shape, name: str, color: tuple):
    Part.show(shape, name)
    obj = App.ActiveDocument.ActiveObject
    obj.Label = name
    obj.ViewObject.ShapeColor = color
    return obj


def _mm(value: float) -> str:
    """Four places, and no -0.0000 off the far side of a boolean."""
    return f"{value if abs(value) > 5e-5 else 0.0:.4f}"


def _report(shape: Part.Shape):
    bb = shape.BoundBox
    solid, *tips = shape.Solids
    sb, t0, t1 = solid.BoundBox, tips[0].BoundBox, tips[1].BoundBox
    for label, value, target in [
        ("solids", len(shape.Solids), 3),
        ("valid", shape.isValid(), True),
        ("body length", _mm(sb.XLength), f"{L:.2f} L max"),
        ("body thickness", _mm(sb.YLength), f"{T:.2f} T max"),
        ("body height", f"{_mm(sb.ZMin)} - {_mm(sb.ZMax)}", f"0.00 - {H:.2f} H max"),
        ("body centred on", _mm((sb.XMin + sb.XMax) / 2), f"{X_MID:.2f} between the leads"),
        ("lead spacing", _mm(t1.XMin - t0.XMin), f"{F:.2f} F"),
        ("lead diameter", _mm(t0.XLength), f"{D_LEAD:.2f} od"),
        ("lead tips", _mm(bb.ZMin), f"{Z_TIP:.2f} KiCad C_Rect"),
        ("seated worst case", _mm(H + RUNOFF), "10.00, body plus the runoff"),
    ]:
        print(f"  {label:<18}{value!s:<24}{target}")


def build():
    doc = _document()
    for name, (maker, color) in PARTS.items():
        _show(maker(), name, color)
    doc.recompute()
    _report(Part.makeCompound([o.Shape for o in doc.Objects]))
    if WINDOWED:
        Gui.SendMsgToActiveView("ViewFit")
    return doc


def export(path: str = STEP_PATH):
    """Write the coloured STEP KiCad attaches to the ECQ-E footprint."""
    doc = build()
    import ImportGui  # only importable once _gui() has run

    ImportGui.export([doc.getObject(n) for n in PARTS], path)
    print(f"\n  wrote {path}")
