"""Bourns SRN5040TA - 5 x 5 x 4 mm semi-shielded SMD power inductor.

The package for L121 (SRN5040TA-1R5M) and L131 (SRN5040TA-2R2M). Both value
codes fall in the R60M-through-100M band, so both are 3.9 mm tall; nothing else
about the part changes with inductance except the marking, which is not drawn.

Drawn from docs/datasheets/srn5040ta.pdf, whose page 1 carries three views -
top, bottom and a front elevation - and these dimensions:

    4.95 +-0.2   across, given once each way
    3.9  +-0.2   height, R60M through 100M; 150M through 101K are 3.8
    4.2  +-0.2   terminal, the long way
    1.3  +-0.2   terminal, the short way
    3.7  REF     terminal pitch

The two terminal figures are what identify the bottom view for what it is:
4.2 x 1.3 under a recommended land of 4.2 x 1.5 is a land drawn over a terminal
with a tenth of a millimetre to spare each side, and no other pair of features
on the part stands in that relation. The rest of that view is the body outline
with the two terminals lying on it at opposite edges, hatched because they are
metal, and the top view is that same outline again with the terminals lying
past its edge - which is why the second 4.95 is dimensioned on the terminals
and not on the body. Which of the two the 4.95 belongs to across that axis the
drawing never says; it is taken here as the flange, so the terminals finish
flush with it rather than standing proud, and the envelope is the same either
way.

Nothing on the page dimensions the part's profile; the front elevation is drawn
to no scale in either direction. The shape here is off the catalogue render,
which shows a drum: a ferrite flange top and bottom, both to the full 4.95
across and both keeping the octagonal plan the top view draws, and between them
the coated winding, pulled in to a rounded waist that is nowhere near either
flange's outline. The two creases where the waist leaves the flanges are sharp
in the render and are built sharp here.

Off that render, against the flange it stands beside:

    waist   4.30 across at its narrowest, and rounded, not chamfered - it is
            epoxy over wire, and the only part of the outside that was never
            ground flat
    flanges 0.60 on top, 1.45 underneath
    terminal thickness 0.35

The plan outline is a square with its corners cut off, 1.0 mm on the leg
measured in the top view, the one view that scales. Every section is that
octagon scaled and its corners rounded - barely, on the flanges, where they
read as the ground edges they are, and hard through the waist.

The frame is KiCad's for SMD: origin on the footprint origin, terminals
straddling X to match pads 1 and 2, Z = 0 the top of the board.
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
DOC_NAME = "SRN5040TA"

# --- datasheet -----------------------------------------------------------
W = 4.95  # across, at the flanges
H = 3.90  # overall height
TERM_L = 4.20  # terminal, along Y
TERM_W = 1.30  # terminal, across X
TERM_PITCH_REF = 3.70  # terminal centres, REF

# --- off the top view ----------------------------------------------------
CHAMFER = 1.00  # corner cut, on the leg, at the full 4.95 section

# --- off the catalogue render --------------------------------------------
W_WAIST = 4.30  # across at the narrowest
Z_BASE = 1.45  # top of the bottom flange
Z_TOP = H - 0.60  # bottom of the top flange
R_FLANGE = 0.10  # corners of a ground flange, eased only enough to see
R_WAIST = 1.35  # corners through the waist, where nothing was ground
TERM_T = 0.35
SECTIONS = 9  # sections lofted through the waist

# --- colour --------------------------------------------------------------
COATING = (0.14, 0.11, 0.10)  # magnetic epoxy over the winding
FERRITE = (0.29, 0.27, 0.25)  # the ground core face on top
TINNED = (0.824, 0.820, 0.781)  # as the stock KiCad terminals

try:
    STEP_PATH = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "pcb", "lib", "nixie_clock.3dshapes", "L_Bourns_SRN5040TA.step"))
except NameError:  # pasted into the console rather than run as a file
    STEP_PATH = ""


def waist(z: float) -> float:
    """How far into the waist height z is, 0 at either flange and 1 at the pinch."""
    if z <= Z_BASE or z >= Z_TOP:
        return 0.0
    return math.sin(math.pi * (z - Z_BASE) / (Z_TOP - Z_BASE))


def across(z: float) -> float:
    """Across-flats at height z."""
    return W - (W - W_WAIST) * waist(z)


def corner(z: float) -> float:
    """Corner radius at height z: a ground edge at the flanges, round in between."""
    return R_FLANGE + (R_WAIST - R_FLANGE) * waist(z)


def section(z: float) -> Part.Wire:
    """The plan outline at height z: the octagon, scaled, corners rounded off.

    One generator for every section, so all of them carry the same eight flats
    and eight corners and the loft between any two of them is a taper rather
    than a rebuild. The rounding is what separates the waist from the flanges
    as much as the width is - the flanges were ground, the waist is epoxy that
    set the shape it wanted.
    """
    a, r = across(z), corner(z)
    h, c = a / 2, CHAMFER * a / W
    pts = [(h - c, -h), (h, -h + c), (h, h - c), (h - c, h),
           (-h + c, h), (-h, h - c), (-h, -h + c), (-h + c, -h)]
    v = [App.Vector(x, y, z) for x, y in pts]
    n = len(v)

    arcs = []
    for i, cur in enumerate(v):
        d1 = (v[i - 1] - cur).normalize()
        d2 = (v[(i + 1) % n] - cur).normalize()
        half = d1.getAngle(d2) / 2.0
        t1 = cur + d1 * (r / math.tan(half))
        t2 = cur + d2 * (r / math.tan(half))
        centre = cur + (d1 + d2).normalize() * (r / math.sin(half))
        mid = centre + ((t1 - centre) + (t2 - centre)).normalize() * r
        arcs.append((t1, mid, t2))

    edges = []
    for i, (t1, mid, t2) in enumerate(arcs):
        edges.append(Part.Arc(t1, mid, t2).toShape())
        nxt = arcs[(i + 1) % n][0]
        if (nxt - t2).Length > 1e-9:
            edges.append(Part.LineSegment(t2, nxt).toShape())
    return Part.Wire(edges)


def terminals() -> Part.Shape:
    """Both terminals, sat on the board under the bottom flange's X edges.

    Their outer faces are flush with the flange rather than on the 3.7 REF
    pitch, which would stand them 0.025 mm proud of it. Flush is the physical
    constraint; 3.7 is a reference dimension.
    """
    x_out, x_in = W / 2, W / 2 - TERM_W
    return Part.makeCompound([
        Part.makeBox(TERM_W, TERM_L, TERM_T, App.Vector(x, -TERM_L / 2, 0.0))
        for x in (x_in, -x_out)
    ])


def drum() -> Part.Shape:
    """The whole body: bottom flange, waist, top flange.

    Three solids fused rather than one loft through the lot, because the join
    at each flange is a crease and a loft would round it off. The flanges are
    prisms off the same section the waist starts and ends on, so the faces meet
    exactly and the fuse leaves nothing behind.
    """
    zs = [Z_BASE + (Z_TOP - Z_BASE) * i / (SECTIONS - 1) for i in range(SECTIONS)]
    return (Part.Face(section(0.0)).extrude(App.Vector(0.0, 0.0, Z_BASE))
            .fuse(Part.makeLoft([section(z) for z in zs], True, False))
            .fuse(Part.Face(section(Z_TOP)).extrude(App.Vector(0.0, 0.0, H - Z_TOP)))
            .removeSplitter())


def body() -> Part.Shape:
    """The drum with the terminals taken back out of it.

    Cutting them rather than letting them overlap keeps the three solids
    disjoint, which is what makes the two colours read cleanly where they meet.
    """
    return drum().cut(terminals())


PARTS = {"Body": (body, COATING), "Terminals": (terminals, TINNED)}


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


def _top_faces(shape: Part.Shape) -> list:
    """Indices of the faces that make up the flat top - the exposed ferrite."""
    return [i for i, f in enumerate(shape.Faces)
            if isinstance(f.Surface, Part.Plane)
            and abs(f.CenterOfMass.z - H) < 1e-6]


def _show(shape: Part.Shape, name: str, color: tuple):
    Part.show(shape, name)
    obj = App.ActiveDocument.ActiveObject
    obj.Label = name
    obj.ViewObject.ShapeColor = color
    tops = _top_faces(shape)
    if tops:
        # Per-face colour, so the ground core face on top reads as ferrite
        # against the coating everywhere else.
        faces = [color] * len(shape.Faces)
        for i in tops:
            faces[i] = FERRITE
        obj.ViewObject.DiffuseColor = faces
    return obj


def _mm(value: float) -> str:
    """Four places, and no -0.0000 off the far side of a boolean."""
    return f"{value if abs(value) > 5e-5 else 0.0:.4f}"


def _slab(solid: Part.Shape, z: float) -> float:
    """Across-flats of a solid at height z.

    optimalBoundingBox, not BoundBox: the waist is spline faces off the loft,
    and a plain BoundBox on a spline is taken off the control polygon and reads
    a good tenth of a millimetre wide.
    """
    cut = solid.common(Part.makeBox(20.0, 20.0, 0.01, App.Vector(-10.0, -10.0, z)))
    return cut.optimalBoundingBox().XLength if cut.Faces else 0.0


def _report(shape: Part.Shape):
    bb = shape.BoundBox
    solid, *tips = shape.Solids
    t0, t1 = tips[0].BoundBox, tips[1].BoundBox
    pinch = (Z_BASE + Z_TOP) / 2
    for label, value, target in [
        ("solids", len(shape.Solids), 3),
        ("valid", shape.isValid(), True),
        ("envelope", f"{_mm(bb.XLength)} x {_mm(bb.YLength)} x {_mm(bb.ZLength)}",
         f"{W:.2f} x {W:.2f} x {H:.2f}"),
        ("top flange", _mm(_slab(solid, H - 0.011)), f"{W:.2f} across"),
        ("bottom flange", _mm(_slab(drum(), Z_BASE - 0.011)), f"{W:.2f} across"),
        ("waist", _mm(_slab(solid, pinch)), f"{W_WAIST:.2f} across"),
        ("waist runs", f"{_mm(Z_BASE)} to {_mm(Z_TOP)}",
         f"{Z_TOP - Z_BASE:.2f} of the {H:.2f}"),
        ("terminal", f"{_mm(t0.XLength)} x {_mm(t0.YLength)} x {_mm(t0.ZLength)}",
         f"{TERM_W:.2f} x {TERM_L:.2f} x {TERM_T:.2f}"),
        ("terminal pitch", _mm(abs(t1.XMin + t1.XMax - t0.XMin - t0.XMax) / 2),
         f"{W - TERM_W:.2f}, against {TERM_PITCH_REF:.2f} REF"),
        ("terminals flush", _mm(max(t0.XMax, t1.XMax) - W / 2),
         "0.00 with the flanges"),
        ("sits on", _mm(bb.ZMin), "0.00, the board"),
    ]:
        print(f"  {label:<18}{value!s:<26}{target}")


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
    """Write the coloured STEP KiCad attaches to the SRN5040TA footprint."""
    doc = build()
    import ImportGui  # only importable once _gui() has run

    ImportGui.export([doc.getObject(n) for n in PARTS], path)
    print(f"\n  wrote {path}")
