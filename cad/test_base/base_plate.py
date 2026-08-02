"""Bench test base - a flat plate that carries the clock boards on standoffs.

This is a bring-up fixture, not part of the product. It holds the boards at a
fixed spacing so the interconnects can be made up once and left alone, and so
nothing shorts against the bench. Two printed parts: the plate, and a riser that
stands under the hv board's standoffs.

The frame is the fixture as it sits in front of you: +X to the right, +Y away
from you, +Z up, origin at the centre of the plate's top face. That is a top
view with Y increasing upward, so a KiCad point maps in as (x, -y) and a board
turned one quarter clockwise on the bench is turns=1 in the table below.

The boards are stacked, not laid out side by side. main sits low at the back;
hv sits half a main board forward of it and high enough to pass over it. That
only works because hv is turned broadside: landscape its hole pitch is 75 mm
across and main is 65 mm wide, so all four hv columns rise clear of main's
outline. Turn hv the other way and its rear columns land inside main's board.

    main   turns=1   65 x 70   USB-C (J101) to the back, J5 right, J4 front
    hv     turns=2   85 x 55   J1 in on the right beside main's J5, J2 out left

Five millimeters of X is all the room there is beside main, so the riser steps:
full diameter below main's underside where it does the structural work, reduced
above it where it has to squeeze past the board edge. straddle() prints what is
actually left.

A main mounting point is a through fitting:

    z = 5      top face, mouth of the hex pocket
    z = 4      pocket floor - the standoff's bottom face seats here
    z = 2      ceiling of the head counterbore; the screw head bears here
    z = 0      bottom face

An hv mounting point is not: it is a blind recess that the riser drops into,
with no fastener to the plate at all. The hv column is held down by its own
board tying the four risers together, and located by 1.5 mm of recess.

The hex pockets only register. They are 1 mm deep, enough to stop a standoff
turning while a screw is run into it, and no deeper - clamping is the screw's
job. That matters because the screws are 6 mm: through 2 mm of web, a base
screw still takes 4 mm of thread.

The riser carries its own captive screw, loaded head-first up a bore from the
bottom before the riser goes anywhere near the plate. The bore is oversize for
the head all the way down, so a long hex key reaches the screw with the riser in
your hand: fit the standoff to the riser first, then set the pair in the recess.
Above the head the bore necks to clearance for 2 mm, and the screw's head pulls
up against that shoulder, leaving 4 mm of thread standing out of the top.

The riser's top face is plain, with no hex register. There is no room for one -
a 5.6 mm hex needs 6.47 mm across corners, which would leave 0.77 mm of wall in
the reduced section - and none is needed: both threads are right hand, so
driving the board screw down into the standoff from above tightens the standoff
onto the riser's screw rather than backing it off.

Print both parts with the plate's top face down and the riser standing up. Every
feature is then a vertical wall or an inward taper: the pockets and recesses
become first-layer voids, the lead-in chamfers close inward as they rise, the
riser's step is a 45 degree cone, and the only overhangs are the bridges across
the pocket and recess floors.
"""

import glob
import math
import os
import re
import shutil
import subprocess
from typing import NamedTuple

import FreeCAD as App
import Part

import hardware as hw
import vrml

try:
    from FreeCAD import Gui
except ImportError:
    Gui = None


DOC_NAME = "Bench_Base"

# --- plate ---------------------------------------------------------------
PLATE_T = 5.00  # POCKET_D + web + HEAD_D
CORNER_R = 6.00
MARGIN = 2.00  # rim beyond the outermost thing the plate has to carry

# --- mounting ------------------------------------------------------------
POCKET_D = 1.00  # hex register; deep enough to stop rotation, no more
POCKET_AF = 5.60  # across flats; the standoffs measure 5.3, nominal M3 is 5.5
POCKET_LEADIN = 0.30  # 45 deg mouth chamfer, so the hex drops in
SCREW_D = 3.40  # M3 clearance
SCREW_KIT = (6, 8, 10, 12, 16, 20, 25, 30)  # lengths on hand
ENGAGE = 5.00  # thread wanted in a standoff, comfortably over 1.5 D
STACK_GAP = 1.00  # air left between the two screws inside one standoff
HEAD_D = 6.40  # clears an M3 socket cap, button, or pan head
HEAD_DEPTH = 2.00  # counterbore in the bottom face
# Socket cap throughout, and not by preference: the riser's head bore is 5.8,
# which clears a 5.5 cap and fouls a 5.7 button. Washers go unused - at roughly
# 7 mm across they will not enter a 6.4 counterbore.

# --- riser ---------------------------------------------------------------
RISER_H = 20.00
RISER_D = 12.00  # below main's board, where there is room
RISER_D_TOP = 8.00  # past main's edge, where there is not
RISER_STEP = 9.00  # top of the cone, above the riser's own base
RISER_TAPER = 2.00  # 45 deg, so it prints without support
RISER_BORE = 5.80  # clearance for the screw head, and for a hex key
RISER_SHOULDER = 2.00  # what the head pulls up against
RISER_CHAMFER = 0.60
RECESS_D = RISER_D + 0.40
RECESS_DEPTH = 1.50
RECESS_LEADIN = 0.50

# --- face bracket --------------------------------------------------------
# The face board stands vertically in front of everything, as it will in the
# clock. It goes in exactly as KiCad draws it: J1 and J2 are on the min-Y edge
# and that edge is up, so KiCad +y reads downward and no rotation is needed.
FACE_SIZE = (140.00, 70.00)  # Edge.Cuts extents
FACE_HOLES = (130.00, 60.00)

# The board sits as far back as its own connectors allow: J1's shroud stands
# 9.19 off the back of the board, and that has to clear hv's front edge.
FACE_Y = -52.50

BLADE_W = 12.00  # upright, across
BLADE_D = 10.00  # upright, front to back
BLADE_H = 72.00
GUSSET_D = 34.00
GUSSET_H = 45.00

# Rounding. The profile corners are filleted on the extruded prism, where the
# edges all run in X and can be picked by the corner they sit on; the inside of
# each upright and the gusset's toe are blended to the sole afterwards, once
# they are one solid and those corners have turned concave. Nothing is filleted
# on the outboard face or the front - both are flush, with no material to spare.
TOP_R = 3.00  # over the top of a blade
GUSSET_R = 4.00  # slope meeting the straight back
INSIDE_R = 4.00  # upright meeting the sole

# The sole rides on top of the plate rather than under it. Above, it is simply
# bolted down and the whole assembly stands on the plate's own four feet, so
# there is nothing left to rock and no need for anti-tip pads. Its lateral
# location comes free: the front pair of hv risers pass up through it.
SOLE_T = 5.00
SOLE_X = 71.00  # flush with the outer face of the blades
# No corner rounding. The front corners are the blades' own corners and have no
# material to give; the back two land inside the toe blend's run-out, and two
# fillets fighting over the same corner is what OCC refuses to build.
SOLE_R = 0.00
WINDOW = (36.00, 30.00)  # lightening cut through the sole
WINDOW_R = 4.00  # its inside corners
RISER_FIT = 0.80  # clearance for a column passing through the sole
TIE = ((25.00, -32.00), (25.00, -42.00))  # mirrored in X

FACE_Z = PLATE_T + SOLE_T  # the sole's top, where the board's bottom edge sits

# The sole stops where the toe blend does. A rolling-ball fillet between two
# planes at interior angle a runs out R / tan(a/2) along each, and the gusset
# leans only 62 degrees off the sole, so the blend reaches 2.40 rather than its
# own 4 mm radius. Sizing the sole off the radius would leave a step.
#
# The margin is not cosmetic. Ending the face exactly on the blend's tangent
# leaves the fillet no run-out at all and OCC declines to build it - it wants
# somewhere to land.
TOE_MARGIN = 0.50
TOE_RUNOUT = INSIDE_R / math.tan(math.radians(
    (180.0 - math.degrees(math.atan2(GUSSET_H, GUSSET_D - BLADE_D))) / 2))
SOLE_BACK = FACE_Y + GUSSET_D + TOE_RUNOUT + TOE_MARGIN

NUT_AF = 5.50  # M3 hex nut
NUT_T = 2.40
NUT_FIT = 0.30
NUT_DEPTH = 2.60
FOOT_FIT = 0.40  # slip fit of a plate foot through the sole

# --- feet ----------------------------------------------------------------
FOOT_D = 10.00
FOOT_H = 6.00  # must clear the screw heads; a socket cap stands 1.0 proud
FOOT_CHAMFER = 1.00  # bench end, for first-layer adhesion
FOOT_FILLET = 1.00  # where the foot meets the plate

# --- stack ---------------------------------------------------------------
# None of this cuts geometry. It is here because the plate is only half the
# fixture: the column heights are the other half, and they are what decides
# whether the boards actually clear each other.
# 1.6 is the real board: the stackup reads 0.010 mask + 0.035 copper + 1.510
# core + 0.035 copper + 0.010 mask. The STEP export draws only the dielectric,
# so an imported board body measures 1.510 and is not evidence of anything.
PCB_T = 1.60
CLEARANCE = 2.00  # working gap between one board's tallest part and the next
RIBBON = 11.00  # an IDC socket and its strain relief, above J4's shroud

# --- imported boards -----------------------------------------------------
# Real KiCad geometry, when it has been exported. Regenerate with:
#
#   kicad-cli pcb export step --force --no-dnp --no-unspecified --subst-models \
#       --user-origin=<centre of the board's Edge.Cuts, in mm> -o boards/<n>.step
#
# The origin is what makes this painless. Set to the board's own centre, the
# export frame is exactly this file's frame at turns=0 - X as drawn, Y negated,
# Z zero at the underside - so placing a board is a quarter turn and a shift.
REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# The IN-12 tubes exist only as VRML, so KiCad's STEP export drops them and they
# have to be inserted here. Worth the trouble twice over: it is the only way to
# get the tubes at all, and the only way to get the glass, which is a material
# property a STEP twin could not carry. See vrml.py.
TUBE_WRL = os.path.join(REPO, "pcb", "lib", "nixie_clock.3dshapes", "IN-12B.wrl")
TUBE_OFFSET = (3.819, -7.620, 0.0)  # the footprint's model offset, as written
TUBE_SEAT = 1.510  # model origin rides on the board's top face, as exported
TUBE_AT = ((-44.0, 0.0), (-18.0, 0.0), (18.0, 0.0), (44.0, 0.0))  # NX1..NX4
BOARD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boards")
BOARD_ORIGIN = {"main": (135.0, 87.5), "hv": (147.5, 102.5), "face": (150.0, 90.0)}

# --- view ----------------------------------------------------------------
BRASS = (0.85, 0.68, 0.25)
BLACK_OXIDE = (0.13, 0.13, 0.14)  # the 12.9 alloy screws and their nuts

WEB_T = PLATE_T - POCKET_D - HEAD_DEPTH


class Board(NamedTuple):
    """A board as KiCad draws it, plus how it sits on the fixture."""

    name: str
    size: tuple  # Edge.Cuts extents (x, y)
    holes: tuple  # M3 hole pitch (x, y)
    turns: int  # quarter turns clockwise from the KiCad top view
    y: float  # centre, forward of the first board's centre
    riser: float  # riser height under its standoffs, 0 for a plate mount
    standoff: float  # length of the four standoffs
    tallest: float  # tallest top-side part, above the board's top face
    underside: float  # furthest anything protrudes below the board


# tallest / underside are Z extents read off the KiCad 3D models: main's J4
# shroud stands 9.10 and its J5 leads hang 3.40. hv is almost all through-hole,
# so 3.50 covers its leads.
BOARDS = (
    Board("main", (70.00, 65.00), (60.00, 55.00), 1, 0.00, 0.00, 10.00, 9.10, 3.40),
    # hv sits 20 forward of main, not 35. The extra 15 is bought clearance:
    # anything less and hv's rear column stands in front of main's J5 and its
    # plug cannot go on. plug_clearance() is the number that governs it.
    Board("hv", (85.00, 55.00), (75.00, 45.00), 2, -20.00, RISER_H, 20.00, 0.00, 3.50),
)


# =========================================================================
# layout
# =========================================================================
def turned(pair: tuple, turns: int) -> tuple:
    """An (x, y) pair as it reads after a whole number of quarter turns."""
    return (pair[1], pair[0]) if turns % 2 else pair


def extent() -> tuple:
    """Back and front of the boards taken together, in table coordinates."""
    edges = [(b.y - turned(b.size, b.turns)[1] / 2,
              b.y + turned(b.size, b.turns)[1] / 2) for b in BOARDS]
    return min(lo for lo, _ in edges), max(hi for _, hi in edges)


def depth() -> float:
    """Depth the boards occupy taken together."""
    lo, hi = extent()
    return hi - lo


def stations() -> list:
    """Y of each board's centre once the stack is centred on the plate."""
    lo, hi = extent()
    return [b.y - (lo + hi) / 2 for b in BOARDS]


def mounts() -> list:
    """(board, x, y) for every column position."""
    out = []
    for board, yc in zip(BOARDS, stations()):
        px, py = turned(board.holes, board.turns)
        for sy in (1, -1):
            for sx in (-1, 1):
                out.append((board, sx * px / 2, yc + sy * py / 2))
    return out


def mount_reach(board: Board) -> float:
    """How far a mounting feature spreads from its own centre.

    A riser seat is the widest thing on the plate, wider than the hv board it
    carries, so this is what ends up setting the plate's size.
    """
    if board.riser:
        return RECESS_D / 2 + RECESS_LEADIN
    return max(HEAD_D / 2, (POCKET_AF + 2 * POCKET_LEADIN) / math.sqrt(3.0))


def feet() -> list:
    """(x, y) of each foot centre.

    The front pair sits on the front riser seats, so the tallest load path runs
    straight down a column, through the plate, into a foot. The back pair
    mirrors them, which lands it level with main's rear standoffs and a little
    wider - the plate is deeper than it is broad, so the wider track is the one
    worth having.
    """
    front = min(y for board, _, y in mounts() if board is BOARDS[-1])
    xs = sorted({x for board, x, y in mounts()
                 if board is BOARDS[-1] and y == front})
    return [(x, sy * front) for sy in (-1, 1) for x in xs]


def ties() -> list:
    """(x, y) where a screw pulls the sole down onto the plate.

    Four rather than two. The sole reaches 25 mm outboard of the plate on each
    side to meet the uprights, so it works as a cantilever and the extra pair
    shortens the span it has to carry.
    """
    return [(sx * x, y) for x, y in TIE for sx in (-1, 1)]


def face_mounts() -> list:
    """(x, z) of the face board's four holes, z above the plate's underside.

    The board's bottom edge rests on the sole, and its holes are the usual 5 mm
    in from the outline.
    """
    px, pz = FACE_HOLES
    return [(sx * px / 2, FACE_Z + FACE_SIZE[1] / 2 + sz * pz / 2)
            for sz in (1, -1) for sx in (-1, 1)]


def reach() -> tuple:
    """Half width and half depth the plate has to cover, before MARGIN.

    Everything it carries: board outlines, mounting features, tie screws, and
    feet with their fillets. Taken symmetrically, because the plate is a
    rectangle centred on the layout. The face bracket is not in here - it bolts
    underneath and reaches past the plate on its own.
    """
    xs, ys = [], []
    for board, yc in zip(BOARDS, stations()):
        w, d = turned(board.size, board.turns)
        xs.append(w / 2)
        ys.append(abs(yc) + d / 2)
    for board, x, y in mounts():
        xs.append(abs(x) + mount_reach(board))
        ys.append(abs(y) + mount_reach(board))
    for x, y in ties():
        xs.append(abs(x) + HEAD_D / 2)
        ys.append(abs(y) + HEAD_D / 2)
    for x, y in feet():
        xs.append(abs(x) + FOOT_D / 2 + FOOT_FILLET)
        ys.append(abs(y) + FOOT_D / 2 + FOOT_FILLET)
    return max(xs), max(ys)


PLATE_W = 2 * (reach()[0] + MARGIN)
PLATE_D = 2 * (reach()[1] + MARGIN)


def seat(board: Board) -> float:
    """Z of a board's underside above the plate's top face.

    A standoff on the plate sinks POCKET_D into its hex register. A standoff on
    a riser sits on the riser's plain top face and sinks into nothing.
    """
    if board.riser:
        return board.riser - RECESS_DEPTH + board.standoff
    return board.standoff - POCKET_D


# =========================================================================
# solids
# =========================================================================
def hex_wire(af: float, z: float) -> Part.Wire:
    """Closed wire: a regular hexagon of across-flats af, at height z.

    Vertices sit on the X axis, so the flats face front and back. Which way it
    lands does not matter for a hex, but fixing it keeps the pockets identical.
    """
    r = af / math.sqrt(3.0)
    pts = [App.Vector(r * math.cos(math.radians(60 * k)),
                      r * math.sin(math.radians(60 * k)), z) for k in range(6)]
    return Part.makePolygon(pts + [pts[0]])


def pocket_cutter(top: float) -> Part.Shape:
    """The hex register and its lead-in, as one solid to subtract from top.

    Ruled loft rather than a chamfer on the finished part: identical cutters are
    cheaper and more predictable than picking mouth edges out of a filleted,
    multiply-drilled solid.
    """
    return Part.makeLoft([
        hex_wire(POCKET_AF + 2 * POCKET_LEADIN, top),
        hex_wire(POCKET_AF, top - POCKET_LEADIN),
        hex_wire(POCKET_AF, top - POCKET_D),
    ], True, True)


def recess_cutter(top: float) -> Part.Shape:
    """The blind seat a riser drops into, lead-in included."""
    mouth = Part.makeCone(RECESS_D / 2 + RECESS_LEADIN, RECESS_D / 2,
                          RECESS_LEADIN, App.Vector(0, 0, top - RECESS_LEADIN))
    bore = Part.makeCylinder(RECESS_D / 2, RECESS_DEPTH - RECESS_LEADIN,
                             App.Vector(0, 0, top - RECESS_DEPTH))
    return mouth.fuse(bore)


def plate() -> Part.Shape:
    """The bare plate: a rounded rectangle, PLATE_T thick, sitting on z = 0."""
    box = Part.makeBox(PLATE_W, PLATE_D, PLATE_T,
                       App.Vector(-PLATE_W / 2, -PLATE_D / 2, 0.0))
    vertical = [e for e in box.Edges
                if len(e.Vertexes) == 2
                and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-9
                and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-9]
    return box.makeFillet(CORNER_R, vertical)


def foot(x: float, y: float) -> Part.Shape:
    """One foot, hanging below the plate, chamfered at its bench end."""
    cyl = Part.makeCylinder(FOOT_D / 2, FOOT_H, App.Vector(x, y, -FOOT_H))
    bench = [e for e in cyl.Edges if abs(e.CenterOfMass.z + FOOT_H) < 1e-6]
    return cyl.makeChamfer(FOOT_CHAMFER, bench)


def base() -> Part.Shape:
    """The plate, with its feet, pockets, and riser recesses.

    Feet are fused and blended before anything is cut. Filleting a plain solid
    is far more reliable than asking OCC to blend around eight pockets, and the
    blend clears the nearest counterbore either way.
    """
    shape = plate()
    for x, y in feet():
        shape = shape.fuse(foot(x, y))
    shape = shape.removeSplitter()

    joints = [e for e in shape.Edges
              if abs(e.BoundBox.ZLength) < 1e-9 and abs(e.BoundBox.ZMin) < 1e-9
              and abs(e.Length - math.pi * FOOT_D) < 1e-6]
    if len(joints) != len(feet()):
        raise RuntimeError(f"found {len(joints)} foot joints, expected {len(feet())}")
    shape = shape.makeFillet(FOOT_FILLET, joints)

    hexes = pocket_cutter(PLATE_T)
    seats = recess_cutter(PLATE_T)
    for board, x, y in mounts():
        at = App.Vector(x, y, 0.0)
        if board.riser:
            shape = shape.cut(seats.translated(at))
            continue
        shape = shape.cut(Part.makeCylinder(SCREW_D / 2, PLATE_T, at))
        shape = shape.cut(Part.makeCylinder(HEAD_D / 2, HEAD_DEPTH, at))
        shape = shape.cut(hexes.translated(at))

    # Tie screws enter from below like the mounting screws, but carry on up
    # into a nut captured in the sole sitting on top.
    for x, y in ties():
        at = App.Vector(x, y, 0.0)
        shape = shape.cut(Part.makeCylinder(SCREW_D / 2, PLATE_T, at))
        shape = shape.cut(Part.makeCylinder(HEAD_D / 2, HEAD_DEPTH, at))

    return shape.removeSplitter()


def riser() -> Part.Shape:
    """One riser, standing on z = 0, four needed.

    Sized by two constraints pulling opposite ways: it wants to be fat for
    stiffness and for wall thickness around the head bore, and it has to fit
    through the 5 mm of X between the hv hole pitch and main's board edge. The
    step is the compromise, and it sits below main's underside.

    It cannot widen again above main's board either. main's J5 courtyard stands
    6.10 mm off the board and reaches to within 5.30 mm of the column axis, so
    the reduced section has to run all the way to the top.
    """
    body = Part.makeCylinder(RISER_D / 2, RISER_STEP - RISER_TAPER)
    body = body.fuse(Part.makeCone(
        RISER_D / 2, RISER_D_TOP / 2, RISER_TAPER,
        App.Vector(0, 0, RISER_STEP - RISER_TAPER)))
    body = body.fuse(Part.makeCylinder(
        RISER_D_TOP / 2, RISER_H - RISER_STEP, App.Vector(0, 0, RISER_STEP)))

    bench = [e for e in body.Edges if abs(e.CenterOfMass.z) < 1e-6]
    body = body.makeChamfer(RISER_CHAMFER, bench)

    body = body.cut(Part.makeCylinder(RISER_BORE / 2, shoulder_z()))
    body = body.cut(Part.makeCylinder(SCREW_D / 2, RISER_H))
    return body.removeSplitter()


def shoulder_z() -> float:
    """Z of the shoulder the captive screw head pulls up against."""
    return RISER_H - RISER_SHOULDER


# =========================================================================
# face bracket
# =========================================================================
def blade_nut(x: float, z: float) -> Part.Shape:
    """Captive nut in an upright's BACK face, with the screw's clearance bore.

    The back face, not the front. A pocket in the front face clamps nothing: the
    screw would draw the nut forward out of its recess until it met the board,
    leaving the blade merely trapped between the two and free to slide out. Put
    the nut behind the blade and the stack becomes board, blade, nut, which is a
    joint. It is also what makes the nut captive - once the board is on, the nut
    cannot get out of the pocket.

    It is cut as a hex channel running all the way out the back, not a blind
    pocket. A blind one works for the upper nut, where the blade's back face is
    open air, but the lower nut sits at the height of the gusset - so the same
    cut buried it inside solid material with no way in short of pausing the
    print. Running the hex out the back gives the nut a path in at both heights.
    It still seats on the front of the channel when the screw pulls up, which is
    what sets the joint; the rest is only access.

    Vertex up. The roof is then two faces 60 degrees off horizontal, which the
    printer walks up unsupported; a flat-topped hex would want a bridge in the
    middle of a vertical wall, which is exactly where bridging goes wrong.
    """
    seat = FACE_Y + BLADE_D - NUT_DEPTH  # the face the nut pulls up against
    r = (NUT_AF + NUT_FIT) / math.sqrt(3.0)
    pts = [App.Vector(x + r * math.cos(math.radians(90 + 60 * k)), seat,
                      z + r * math.sin(math.radians(90 + 60 * k)))
           for k in range(6)]
    channel = Part.Face(Part.makePolygon(pts + [pts[0]]))
    channel = channel.extrude(App.Vector(0.0, GUSSET_D + 1.0, 0.0))
    bore = Part.makeCylinder(SCREW_D / 2, BLADE_D + 1.0,
                             App.Vector(x, FACE_Y - 0.5, z),
                             App.Vector(0, 1, 0))
    return channel.fuse(bore)


def sole_nut(x: float, y: float) -> Part.Shape:
    """Captive nut for a tie screw, opening into the sole's top face.

    The screw comes up from under the plate, so the nut is the far end of the
    joint and the pocket has to open upward - which is also the face that is
    reachable while the sole is off the fixture.
    """
    pocket = Part.Face(hex_wire(NUT_AF + NUT_FIT, FACE_Z - NUT_DEPTH))
    pocket = pocket.extrude(App.Vector(0.0, 0.0, NUT_DEPTH))
    bore = Part.makeCylinder(SCREW_D / 2, SOLE_T, App.Vector(0, 0, PLATE_T))
    return pocket.fuse(bore).translated(App.Vector(x, y, 0.0))


def column_socket(board: Board, x: float, y: float) -> Part.Shape:
    """Clearance for whatever rises through the sole at a mounting position.

    An hv riser is a plain cylinder; main carries a bare standoff, so there the
    hole is sized off the hex's across-corners rather than its across-flats -
    the corner is what actually has to pass. Two of these over the front pair of
    risers also locate the sole in X and Y, leaving the ties only to hold it
    down.
    """
    r = (RISER_D + RISER_FIT) / 2 if board.riser \
        else POCKET_AF / math.sqrt(3.0) + RISER_FIT / 2
    return Part.makeCylinder(r, SOLE_T, App.Vector(x, y, PLATE_T))


def _fillet_corners(shape: Part.Shape, corners: list, radius: float) -> Part.Shape:
    """Fillet the edges running in X that sit on the given (y, z) corners.

    The uprights are prisms, so every profile corner is one edge parallel to X.
    Picking them by position is far steadier than asking OCC for edges by index,
    and it keeps working when the profile changes shape.
    """
    edges = []
    for e in shape.Edges:
        if len(e.Vertexes) != 2:
            continue
        p, q = e.Vertexes[0].Point, e.Vertexes[1].Point
        if abs(p.y - q.y) > 1e-9 or abs(p.z - q.z) > 1e-9:
            continue
        if any(abs(p.y - cy) < 1e-6 and abs(p.z - cz) < 1e-6 for cy, cz in corners):
            edges.append(e)
    return shape.makeFillet(radius, edges) if edges else shape


def upright(sx: int) -> Part.Shape:
    """One blade and its gusset, rising from the sole at x = sx * 65.

    Built as a single prism from the whole outline rather than a box fused to a
    wedge, because then every corner that wants rounding is one edge of one
    solid. The gusset falls away backwards as it rises, so nothing overhangs.
    """
    x0 = sx * FACE_HOLES[0] / 2 - BLADE_W / 2
    front, back = FACE_Y, FACE_Y + BLADE_D
    pts = [(front, FACE_Z),
           (front, FACE_Z + BLADE_H),
           (back, FACE_Z + BLADE_H),
           (back, FACE_Z + GUSSET_H),
           (FACE_Y + GUSSET_D, FACE_Z)]
    wire = Part.makePolygon([App.Vector(x0, y, z) for y, z in pts]
                            + [App.Vector(x0, *pts[0])])
    shape = Part.Face(wire).extrude(App.Vector(BLADE_W, 0.0, 0.0))

    # The toe is deliberately left sharp here. Rounding it on the profile puts a
    # convex round-over on the gusset's point, which lifts it off the sole; what
    # it wants is a concave blend into the sole, and that edge does not exist
    # until the upright and the sole are one solid. See face_bracket.
    shape = _fillet_corners(shape, [(front, FACE_Z + BLADE_H),
                                    (back, FACE_Z + BLADE_H)], TOP_R)
    return _fillet_corners(shape, [(back, FACE_Z + GUSSET_H)], GUSSET_R)


def face_bracket() -> Part.Shape:
    """The face support: one part, both uprights, tied under the plate's front.

    It sits on the plate's top face and is bolted down through it, so the whole
    fixture stands on the plate's own four feet and there is nothing extra
    touching the bench to rock on. The front pair of hv risers pass up through
    it, which is what locates it - the tie screws only hold it down.

    The sole is trimmed to the uprights: flush with their front faces, flush
    with their outboard faces, and stopping at the back exactly where the toe
    blend runs out. Only the back two corners are rounded - the front pair sit
    on the blades' own corners, and rounding them would eat into the blade.
    """
    sole = Part.makeBox(2 * SOLE_X, SOLE_BACK - FACE_Y, SOLE_T,
                        App.Vector(-SOLE_X, FACE_Y, PLATE_T))
    corners = [e for e in sole.Edges
               if len(e.Vertexes) == 2
               and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-9
               and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-9
               and abs(e.Vertexes[0].Point.y - SOLE_BACK) < 1e-6]
    shape = sole.makeFillet(SOLE_R, corners) if SOLE_R > 0 else sole

    for sx in (-1, 1):
        shape = shape.fuse(upright(sx))
    shape = shape.removeSplitter()

    # Blend each upright into the sole where it meets it, now that they are one
    # solid and the corners are concave. Two of the four sides only: not the
    # front, because the face board's bottom edge rests on the sole right there
    # and a fillet would hold it off the blade, and not the outboard face, which
    # is flush with the sole's edge and has nothing to blend into.
    inner = FACE_HOLES[0] / 2 - BLADE_W / 2
    toe = FACE_Y + GUSSET_D
    roots = []
    for e in shape.Edges:
        if len(e.Vertexes) != 2:
            continue
        p, q = e.Vertexes[0].Point, e.Vertexes[1].Point
        if abs(p.z - FACE_Z) > 1e-6 or abs(q.z - FACE_Z) > 1e-6:
            continue
        # Must run in Y. Testing only that both ends sit at |x| = inner also
        # matches the sole's front edge, which spans -inner to +inner - and that
        # is the one edge here that must stay sharp.
        if abs(p.x - q.x) < 1e-9 and abs(abs(p.x) - inner) < 1e-6:
            roots.append(e)  # inboard face
        elif abs(p.y - toe) < 1e-6 and abs(q.y - toe) < 1e-6:
            roots.append(e)  # the gusset's toe
    if roots:
        shape = shape.makeFillet(INSIDE_R, roots)

    # Rounded on the cutter rather than on the finished sole: filleting a hole
    # after the fact means picking four edges out of a solid that by then has
    # sockets and nut pockets in it, where rounding the tool is unambiguous.
    window = Part.makeBox(WINDOW[0], WINDOW[1], SOLE_T,
                          App.Vector(-WINDOW[0] / 2,
                                     (FACE_Y + SOLE_BACK - WINDOW[1]) / 2,
                                     PLATE_T))
    corners = [e for e in window.Edges
               if len(e.Vertexes) == 2
               and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-9
               and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-9]
    shape = shape.cut(window.makeFillet(WINDOW_R, corners))

    for board, x, y in mounts():
        if FACE_Y < y < SOLE_BACK:  # whatever the sole covers
            shape = shape.cut(column_socket(board, x, y))
    for x, y in ties():
        shape = shape.cut(sole_nut(x, y))
    for x, z in face_mounts():
        shape = shape.cut(blade_nut(x, z))

    return shape.removeSplitter()


# =========================================================================
# checks
# =========================================================================
def foot_clearance() -> float:
    """Flat left on the bottom face between a head counterbore and a foot blend.

    Negative means the fillet runs into the counterbore. Driver access is the
    looser test and is reported separately. Riser seats are exempt: nothing
    reaches them from underneath.
    """
    return min(math.hypot(x - fx, y - fy) - HEAD_D / 2 - FOOT_D / 2 - FOOT_FILLET
               for board, x, y in mounts() if not board.riser
               for fx, fy in feet())


def driver_clearance() -> float:
    """Room beside a screw head before a foot gets in the way of the driver."""
    return min(math.hypot(x - fx, y - fy) - FOOT_D / 2
               for board, x, y in mounts() if not board.riser
               for fx, fy in feet())


def screw(minimum: float) -> int:
    """Shortest length in the kit that reaches at least `minimum`."""
    for length in SCREW_KIT:
        if length >= minimum - 1e-9:
            return length
    raise ValueError(f"no kit screw reaches {minimum:.2f}")


def board_screw_reach(board: Board) -> float:
    """How far a board's own screw runs into the top of its standoff."""
    return SCREW_KIT[0] - PCB_T


def fit_screw(crossed: float, want: float, available: float) -> int:
    """Shortest kit length giving `want` of thread without exceeding `available`.

    Every standoff here is entered from both ends - a screw up from the plate or
    the riser, and the board's own screw down from above - so thread is not free
    to be as long as it likes. Wanting the longer screw is how the two ends meet
    in the middle and neither ever pulls tight.
    """
    best = None
    for length in SCREW_KIT:
        if length - crossed > available + 1e-9:
            break
        best = length
        if length - crossed >= want - 1e-9:
            return length
    if best is None:
        raise ValueError(f"nothing in the kit fits {crossed:.2f} + {available:.2f}")
    return best


def joints() -> list:
    """(what, needs, kit length, what it gets) for every screwed joint.

    Two kinds. Into a standoff, more thread is simply better and the figure is
    engagement. Into a captive nut, the nut is 2.4 thick and that is all the
    thread there is to have, so the figure is how much of the nut is used and
    the interesting number is instead how far the tip runs past it.
    """
    rows = []

    for board, crossed in ((BOARDS[0], (PLATE_T - POCKET_D) - HEAD_DEPTH),
                           (BOARDS[1], RISER_SHOULDER)):
        room = board.standoff - board_screw_reach(board) - STACK_GAP
        length = fit_screw(crossed, min(ENGAGE, room), room)
        label = "plate mount, from below" if not board.riser else "riser, captive"
        rows.append((label, crossed + min(ENGAGE, room), length,
                     f"{length - crossed:.1f} into a {board.standoff:.0f} standoff"))

    # up through the plate, on through the sole, into a nut in the sole's top
    through = (PLATE_T - HEAD_DEPTH) + (SOLE_T - NUT_DEPTH)
    length = screw(through + NUT_T)
    rows.append(("sole tie, from below", through + NUT_T, length,
                 (f"{min(NUT_T, length - through):.1f} of nut, "
                  f"{length - through - NUT_T:.1f} past")))

    through = PCB_T + BLADE_D - NUT_DEPTH
    length = screw(through + NUT_T)
    rows.append(("face board, from front", through + NUT_T, length,
                 (f"{min(NUT_T, length - through):.1f} of nut, "
                  f"{length - through - NUT_T:.1f} past")))
    return rows


def standoff_share() -> list:
    """(board, air) left inside each standoff between the screws in either end.

    Negative means they meet in the middle and neither joint can pull tight.
    """
    length = {row[0]: row[2] for row in joints()}
    out = []
    for board, crossed, key in ((BOARDS[0], (PLATE_T - POCKET_D) - HEAD_DEPTH,
                                 "plate mount, from below"),
                                (BOARDS[1], RISER_SHOULDER, "riser, captive")):
        used = (length[key] - crossed) + board_screw_reach(board)
        out.append((f"{board.name}, {board.standoff:.0f} mm standoff",
                    board.standoff - used))
    return out


J1_SHROUD = 9.19  # measured off the exported face board, behind B.Cu
# main's J5 courtyard about main's own centre, x0, x1, y0, y1, board turned.
J5_BOX = (19.69, 32.20, -24.70, -6.30)


def plug_clearance() -> float:
    """Room beside main's J5 for its mating plug to go on.

    J5 is a side-entry JST on main's right-hand edge, so its plug sweeps
    straight outboard over the plate - into exactly the band an hv column
    occupies. The column cannot be moved out of the way, because the hv hole
    pattern puts it there, and it cannot be made thinner, because it is already
    down to a 1.1 mm wall squeezing past main's edge. The only thing that buys
    clearance is where the hv board sits front to back.
    """
    x0, x1, y0, y1 = J5_BOX
    lo, hi = stations()[0] + y0, stations()[0] + y1
    r = RISER_D_TOP / 2
    return min(max(lo - (y + r), (y - r) - hi)
               for board, x, y in mounts() if board.riser and x > 0)


def ribbon_gap() -> float:
    """Gap between the face board's IDC shroud and hv's front edge.

    This is what decides how far back the face board can go, and the further
    back it goes the better the fixture balances. Negative means the shroud is
    trying to occupy the same air as the hv board.
    """
    hv = BOARDS[-1]
    front = stations()[-1] - turned(hv.size, hv.turns)[1] / 2
    return front - (FACE_Y + J1_SHROUD)


def blade_crown() -> float:
    """Material above the top nut pocket, at the crown of the hex.

    Vertex up buys printability at the cost of reaching higher than the flats
    do, so this is what decides how far the blade has to stand over the board.
    """
    corner = (NUT_AF + NUT_FIT) / math.sqrt(3.0)
    return (FACE_Z + BLADE_H) - max(z for _, z in face_mounts()) - corner


def window_clearance() -> float:
    """Material left between the sole's lightening cut and a tie nut pocket.

    The pocket is a hexagon with vertices on the X axis, so its corner reaches
    further than the across-flats figure suggests; sizing the window off the
    flats is how you silently breach it.
    """
    corner = (NUT_AF + NUT_FIT) / math.sqrt(3.0)
    return min(abs(x) - corner - WINDOW[0] / 2 for x, _ in ties())


def column_radius(z: float, board: Board) -> float:
    """Half-width of a board's supporting column, z above the plate's top face."""
    if not board.riser:
        return POCKET_AF / math.sqrt(3.0)
    local = z + RECESS_DEPTH  # the riser's own base sits in the recess
    if local <= RISER_STEP - RISER_TAPER:
        return RISER_D / 2
    if local <= RISER_STEP:
        t = (local - RISER_STEP + RISER_TAPER) / RISER_TAPER
        return (RISER_D + t * (RISER_D_TOP - RISER_D)) / 2
    if local <= board.riser:
        return RISER_D_TOP / 2
    return POCKET_AF / math.sqrt(3.0)  # the standoff above the riser


def straddle() -> list:
    """(what, gap) for every column that has to pass a lower board.

    This is the clearance the overlapping layout rests on. The column is sampled
    over the z band the lower board's PCB occupies, and the widest section in
    that band is the one that has to fit.
    """
    ys = stations()
    rows = []
    for k in range(1, len(BOARDS)):
        lower, upper = BOARDS[k - 1], BOARDS[k]
        y_lower = ys[k - 1]
        half_w, half_d = (d / 2 for d in turned(lower.size, lower.turns))
        lo, hi = seat(lower), seat(lower) + PCB_T
        widest = max(column_radius(lo + (hi - lo) * n / 20.0, upper)
                     for n in range(21))
        for board, x, y in mounts():
            if board.name != upper.name:
                continue
            dx = max(abs(x) - half_w, 0.0)
            dy = max(abs(y - y_lower) - half_d, 0.0)
            rows.append((f"{upper.name} column at ({x:+.1f}, {y:+.1f}) past {lower.name}",
                         math.hypot(dx, dy) - widest))
    return rows


def hardware() -> list:
    """(name, solid) for every fastener, placed where it goes.

    None of this cuts geometry, and that is the point: it is a bill of materials
    that happens to be solid, so the screw schedule can be checked rather than
    asserted. A length that is wrong shows up either as a thread stopping short
    of the part it is meant to hold or as one poking out somewhere it should
    not, and both are visible in an interference run.
    """
    length = {row[0]: row[2] for row in joints()}
    out = []

    for board, x, y in mounts():
        if board.riser:
            floor = PLATE_T - RECESS_DEPTH  # the riser's own base
            out.append(("riser screw", hw.oriented(
                hw.cap_screw(length["riser, captive"]),
                (x, y, floor + shoulder_z()))))
            out.append(("hv standoff", hw.oriented(
                hw.standoff(board.standoff), (x, y, floor + board.riser))))
        else:
            out.append(("plate screw", hw.oriented(
                hw.cap_screw(length["plate mount, from below"]),
                (x, y, HEAD_DEPTH))))
            out.append(("main standoff", hw.oriented(
                hw.standoff(board.standoff), (x, y, PLATE_T - POCKET_D))))
        out.append((f"{board.name} board screw", hw.oriented(
            hw.cap_screw(SCREW_KIT[0]),
            (x, y, PLATE_T + seat(board) + PCB_T), (0, 0, -1))))

    for x, y in ties():
        out.append(("tie screw", hw.oriented(
            hw.cap_screw(length["sole tie, from below"]), (x, y, HEAD_DEPTH))))
        out.append(("tie nut", hw.oriented(
            hw.nut(), (x, y, FACE_Z - NUT_DEPTH))))

    for x, z in face_mounts():
        out.append(("face screw", hw.oriented(
            hw.cap_screw(length["face board, from front"]),
            (x, FACE_Y - PCB_T, z), (0, 1, 0))))
        # phase 30: the pocket is vertex up, and a hex swung from +Z onto +Y
        # lands flat top, so the nut has to be clocked to match the model.
        out.append(("face nut", hw.oriented(
            hw.nut(phase=30.0), (x, FACE_Y + BLADE_D - NUT_DEPTH, z), (0, 1, 0))))
    return out


def board_step(name: str) -> str:
    """Path to an exported board, whether or not it is there yet."""
    return os.path.join(BOARD_DIR, f"{name}.step")


def board_source(name: str) -> str:
    """The .kicad_pcb an exported board comes from."""
    return os.path.join(REPO, "pcb", name, f"{name}.kicad_pcb")


def kicad_cli() -> str:
    """Locate kicad-cli, newest version first.

    The version directories have to be compared as numbers. Sorted as strings
    "9.0" beats "10.0", and 9.0 cannot read a KiCad 10 board - it fails with a
    bare "Failed to load board" that says nothing about the version.
    """
    if os.environ.get("KICAD_CLI"):
        return os.environ["KICAD_CLI"]
    found = shutil.which("kicad-cli")
    if found:
        return found
    candidates = glob.glob(r"C:\Program Files\KiCad\*\bin\kicad-cli.exe")
    if not candidates:
        raise RuntimeError("kicad-cli not found; set the KICAD_CLI env var")

    def version(path):
        m = re.search(r"KiCad[\\/]([0-9.]+)[\\/]", path)
        return tuple(int(n) for n in m.group(1).split(".")) if m else (0,)

    return max(candidates, key=version)


def export_boards(force: bool = False) -> list:
    """Re-export any board whose STEP is missing or older than its .kicad_pcb.

    Keyed on modification time so an assembly always shows the boards as they
    are now. Exporting all three costs about six seconds, which is worth paying
    only when something actually changed.
    """
    made = []
    os.makedirs(BOARD_DIR, exist_ok=True)
    for name, (ox, oy) in BOARD_ORIGIN.items():
        src, dst = board_source(name), board_step(name)
        if not os.path.exists(src):
            continue
        if not force and os.path.exists(dst) \
                and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        subprocess.run([kicad_cli(), "pcb", "export", "step", "--force",
                        "--no-dnp", "--no-unspecified", "--subst-models",
                        f"--user-origin={ox}x{oy}mm", "-o", dst, src],
                       check=True, capture_output=True)
        made.append(name)
    return made


def _centred(name: str, shape: Part.Shape, tol: float = 2.0):
    """Check an export really was taken about its board's centre.

    The whole placement rests on --user-origin having been the centre of
    Edge.Cuts. Get that wrong and the board silently lands somewhere plausible
    but incorrect, which no clearance number would catch. A model taken about
    the right origin sits within a couple of millimeters of centred; parts
    overhanging an edge are what the tolerance is for.
    """
    c = shape.BoundBox.Center
    if abs(c.x) > tol or abs(c.y) > tol:
        print(f"  WARNING {name}.step is off centre by ({c.x:+.2f}, {c.y:+.2f});"
              f" re-export with --user-origin={BOARD_ORIGIN[name][0]}"
              f"x{BOARD_ORIGIN[name][1]}mm")


def models() -> list:
    """(name, solid) for each board KiCad has been asked to export.

    Placed by the same numbers that place the slabs, because the export frame
    and this file's frame agree by construction - see BOARD_DIR. main and hv
    take a quarter turn about Z and drop onto their standoffs. face stands up
    instead: a quarter turn about X carries the export's +Z, which runs from
    B.Cu to F.Cu, onto -Y, which is the direction the tubes face.

    Boards that have not been exported are simply absent, so an assembly built
    without them still works.
    """
    out = []
    for board, yc in zip(BOARDS, stations()):
        path = board_step(board.name)
        if not os.path.exists(path):
            continue
        shape = Part.Shape()
        shape.read(path)
        _centred(board.name, shape)
        shape.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), -90.0 * board.turns)
        shape.translate(App.Vector(0.0, yc, PLATE_T + seat(board)))
        out.append((board.name, shape))

    path = board_step("face")
    if os.path.exists(path):
        shape = Part.Shape()
        shape.read(path)
        _centred("face", shape)
        shape.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 90.0)
        shape.translate(App.Vector(0.0, FACE_Y, FACE_Z + FACE_SIZE[1] / 2))
        out.append(("face", shape))
    return out


def tubes() -> list:
    """(name, Material, mesh) for the four IN-12s, placed on the face board.

    The tube's axis is the model's Z - glass toward +Z, leads toward -Z - and it
    has to end up along the fixture's -Y so the digits face the front and the
    leads go back through the board. VRML is authored Y up, so that is a quarter
    turn about X: model +Z lands on -Y and model +Y stands up onto +Z.

    The footprint's model offset is applied in the model's own frame, before the
    turn, which is why it is rotated here rather than added to the translation.
    Its 3.819 is exactly what centres the model on its pads.
    """
    if not os.path.exists(TUBE_WRL):
        return []
    import Mesh

    turn = App.Rotation(App.Vector(1, 0, 0), 90)
    offset = turn.multVec(App.Vector(*TUBE_OFFSET))
    out = []
    for material, pts, faces in vrml.load(TUBE_WRL):
        # The (points, facets) constructor access-violates in FreeCAD 1.1; the
        # triangle-list one does not. Built once per material, copied per tube.
        master = Mesh.Mesh([[App.Vector(*pts[i]) for i in f] for f in faces])
        for n, (px, py) in enumerate(TUBE_AT):
            mesh = master.copy()
            mesh.Placement = App.Placement(
                offset + App.Vector(px, FACE_Y - TUBE_SEAT,
                                    FACE_Z + FACE_SIZE[1] / 2 + py),
                turn)
            out.append((f"NX{n + 1}_{material.name}", material, mesh))
    return out


def slabs() -> list:
    """The three PCBs as plain rectangles, for looking at rather than building.

    They carry no detail. Their only job is to show what the fixture is holding
    and where it leaves room.
    """
    out = []
    for board, yc in zip(BOARDS, stations()):
        w, d = turned(board.size, board.turns)
        slab = Part.makeBox(w, d, PCB_T,
                            App.Vector(-w / 2, yc - d / 2, PLATE_T + seat(board)))
        for other, x, y in mounts():
            if other is board:
                slab = slab.cut(Part.makeCylinder(
                    SCREW_D / 2, PCB_T, App.Vector(x, y, PLATE_T + seat(board))))
        out.append((board.name, slab))

    w, h = FACE_SIZE
    slab = Part.makeBox(w, PCB_T, h, App.Vector(-w / 2, FACE_Y - PCB_T, FACE_Z))
    for x, z in face_mounts():
        slab = slab.cut(Part.makeCylinder(SCREW_D / 2, PCB_T,
                                          App.Vector(x, FACE_Y - PCB_T, z),
                                          App.Vector(0, 1, 0)))
    out.append(("face", slab))
    return out


def levels() -> list:
    """(label, z) up the stack, from the plate's top face."""
    out = [("plate top face", 0.0)]
    for board in BOARDS:
        if board.riser:
            out.append((f"{board.name} riser top", board.riser - RECESS_DEPTH))
        under = seat(board)
        out.append((f"{board.name} lowest lead", under - board.underside))
        out.append((f"{board.name} board underside", under))
        out.append((f"{board.name} top face", under + PCB_T))
        if board.tallest:
            out.append((f"{board.name} tallest part", under + PCB_T + board.tallest))
    return out


def headroom(ribbon: float = 0.0) -> list:
    """(what, gap) between each board's tallest part and the next board up."""
    rows = []
    for k in range(1, len(BOARDS)):
        lower, upper = BOARDS[k - 1], BOARDS[k]
        top = seat(lower) + PCB_T + lower.tallest + ribbon
        rows.append((f"{lower.name} to {upper.name}",
                     seat(upper) - upper.underside - top))
    return rows


# =========================================================================
# document
# =========================================================================
def finish(name: str) -> tuple:
    """Colour for a fastener: brass for the standoffs, black oxide for steel."""
    return BRASS if "standoff" in name else BLACK_OXIDE


def _show(shape: Part.Shape, name: str, color: "tuple | None" = None):
    """Part.show, plus a colour when there is a view provider to take it.

    freecadcmd builds documents with no ViewObject at all, so the colour has to
    be conditional rather than assumed - setting it unconditionally raises
    there and takes the headless build down with it.
    """
    Part.show(shape, name)
    obj = App.ActiveDocument.ActiveObject
    if color is not None and getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.ShapeColor = color
    return obj


def _document():
    docs = App.listDocuments()
    doc = App.getDocument(DOC_NAME) if DOC_NAME in docs else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    for obj in [*doc.Objects]:
        doc.removeObject(obj.Name)
    return doc


def _report(shape, part):
    bb = shape.BoundBox
    rows = [
        ("solids", len(shape.Solids), 1),
        ("valid", shape.isValid(), True),
    ]
    if part == "base":
        rows += [
            ("plate", f"{PLATE_W:.1f} x {PLATE_D:.1f} x {PLATE_T:.1f}",
             "92.4 x 104.9 x 5.0"),
            ("overall height", f"{bb.ZMax - bb.ZMin:.1f}", f"{PLATE_T + FOOT_H:.1f}"),
            ("web under pocket", f"{WEB_T:.2f}", "2.00"),
            ("rim beyond a seat", f"{MARGIN:.2f}", "the seats set the size"),
            ("pockets / recesses",
             (f"{sum(1 for b, _, _ in mounts() if not b.riser)}"
              f" / {sum(1 for b, _, _ in mounts() if b.riser)}"), "4 / 4"),
            ("counterbore to blend", f"{foot_clearance():.2f}", "> 0"),
            ("driver beside a head", f"{driver_clearance():.2f}", "> 3.0"),
        ]
    elif part == "riser":
        rows += [
            ("riser", f"dia {RISER_D:.1f} to {RISER_D_TOP:.1f} x {RISER_H:.1f}",
             "4 needed"),
            ("head bore", f"dia {RISER_BORE:.1f} x {shoulder_z():.1f} deep",
             "loads from the bottom"),
            ("wall at the head bore", f"{(RISER_D_TOP - RISER_BORE) / 2:.2f}", "> 1.0"),
            ("wall at the shoulder", f"{(RISER_D_TOP - SCREW_D) / 2:.2f}", "> 2.0"),
            ("thread standing out", f"{joints()[1][2] - RISER_SHOULDER:.2f}",
             "into the standoff"),
        ]
    else:
        rows += [
            ("sole", (f"{2 * SOLE_X:.1f} x {SOLE_BACK - FACE_Y:.1f}"
                      f" x {SOLE_T:.1f}"), "1 needed"),
            ("toe blend run-out", f"{TOE_RUNOUT:.2f}", "sets the back edge"),
            ("overall", f"{bb.XLength:.1f} x {bb.YLength:.1f} x {bb.ZLength:.1f}",
             "-"),
            ("board plane", f"{FACE_Y:.1f}", "back face, in front of the plate"),
            ("board edge sits at", f"{FACE_Z:.2f}", "on the sole, over the plate"),
            ("J1 shroud to hv edge", f"{ribbon_gap():.2f}", "> 1"),
            ("nut behind the web", f"{BLADE_D - NUT_DEPTH:.2f}",
             "board, blade, nut - a joint"),
            ("window to nut", f"{window_clearance():.2f}", "> 0"),
            ("wall over a nut", f"{blade_crown():.2f}", "> 2.0"),
        ]
    rows.append(("volume cm3", f"{shape.Volume / 1000:.1f}", "-"))
    for label, value, target in rows:
        print(f"  {label:<22}{value!s:<24}{target}")

    if part != "base":
        return

    print()
    print(f"  {'board':<6}{'size':<12}{'centre Y':>10}{'back':>8}{'front':>8}"
          f"{'riser':>8}{'standoff':>10}{'underside':>11}")
    for board, yc in zip(BOARDS, stations()):
        w, d = turned(board.size, board.turns)
        print(f"  {board.name:<6}{f'{w:.0f} x {d:.0f}':<12}{yc:>10.2f}"
              f"{yc + d / 2:>8.2f}{yc - d / 2:>8.2f}"
              f"{board.riser:>8.1f}{board.standoff:>10.1f}{seat(board):>11.2f}")

    print()
    for board, x, y in mounts():
        kind = "recess" if board.riser else "pocket"
        print(f"  {board.name:<6}{x:>9.2f}{y:>9.2f}   {kind}")

    print()
    for label, z in levels():
        print(f"  {label:<26}{z:>8.2f}")

    print()
    print(f"  {'face board':<26}{'x':>8}{'z':>8}")
    for x, z in face_mounts():
        print(f"  {'hole':<26}{x:>8.2f}{z:>8.2f}")
    for label, kx, ky in [("J1 ribbon", 134.24, 66.0), ("J2 hv in", 176.0, 64.0)]:
        print(f"  {label:<26}{kx - 150:>8.2f}"
              f"{FACE_Z + FACE_SIZE[1] / 2 - (ky - 90):>8.2f}")

    print()
    for label, gap in straddle():
        print(f"  {label:<44}{gap:>8.2f}")
    print(f"  {'hv column beside main J5, for its plug':<44}"
          f"{plug_clearance():>8.2f}")
    for label, gap in headroom():
        print(f"  {label + ', J4 bare':<44}{gap:>8.2f}")
    for label, gap in headroom(RIBBON):
        print(f"  {label + ', ribbon mated':<44}{gap:>8.2f}")

    print()
    print(f"  {'joint':<26}{'needs':>7}{'kit':>5}   gets")
    for label, need, length, gets in joints():
        print(f"  {label:<26}{need:>7.2f}{length:>5}   {gets}")

    print()
    for label, air in standoff_share():
        print(f"  {'air between screws in ' + label:<44}{air:>8.2f}")

    print()
    tally = {}
    for name, _ in hardware():
        tally[name] = tally.get(name, 0) + 1
    for name, count in sorted(tally.items()):
        print(f"  {count:>3} x {name}")
    for board in BOARDS:
        if board.standoff not in hw.STANDOFF_LENGTHS:
            print(f"  WARNING {board.name} wants a {board.standoff:.0f} mm"
                  f" standoff, kit has {hw.STANDOFF_LENGTHS}")


PARTS = {"base": base, "riser": riser, "face": face_bracket}


def build(part: str = "all"):
    """Show one part, all three, or the whole thing standing up.

    'assembly' places the risers at their seats and adds the three boards as
    plain slabs, which is the only view that shows whether the stack makes
    sense. The parts themselves are modelled where they sit, so nothing has to
    be moved to assemble them.
    """
    doc = _document()

    if part == "assembly":
        # Refresh any board KiCad has moved on from. A missing kicad-cli is not
        # fatal: the assembly falls back to slabs and says so.
        try:
            fresh = export_boards()
            if fresh:
                print(f"  re-exported {', '.join(fresh)} from KiCad")
        except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
            print(f"  no board export ({exc}); using slabs")

        _show(base(), "Base")
        for n, (board, x, y) in enumerate(m for m in mounts() if m[0].riser):
            _show(riser().translated(App.Vector(x, y, PLATE_T - RECESS_DEPTH)),
                  f"Riser{n + 1}")
        _show(face_bracket(), "FaceBracket")
        for n, (name, shape) in enumerate(hardware()):
            _show(shape, f"{name.title().replace(' ', '')}_{n + 1}", finish(name))
        real = dict(models())
        for name, slab in slabs():
            _show(real.get(name, slab), name.capitalize())
        for name, material, mesh in tubes():
            obj = doc.addObject("Mesh::Feature", name)
            obj.Mesh = mesh
            if getattr(obj, "ViewObject", None) is not None:
                obj.ViewObject.ShapeColor = material.rgb
                obj.ViewObject.Transparency = int(material.transparency * 100)
        if real:
            print(f"\n  using exported KiCad geometry for {', '.join(sorted(real))}")
        doc.recompute()
        _report(base(), "base")
    else:
        # Laid out in a row rather than where they assemble: a riser drawn at
        # its own origin sits inside the plate and cannot be seen at all.
        pitch = 0.0
        for name in ([part] if part in PARTS else PARTS):
            shape = PARTS[name]()
            if part not in PARTS:
                pitch += shape.BoundBox.XLength / 2 + 15.0
                shape = shape.translated(App.Vector(pitch, 0, 0))
                pitch += shape.BoundBox.XLength / 2
            _show(shape, name.capitalize())
            doc.recompute()
            _report(PARTS[name](), name)
            print()

    if Gui is not None:
        Gui.SendMsgToActiveView("ViewFit")


QUANTITY = {"base": 1, "riser": 4, "face": 1}
PRINT_TURN = {"base": 180.0}  # degrees about X to get a part print side down


def export(directory: str, oriented: bool = True):
    """Write every part as STEP, laid out the way it wants to be printed.

    The plate is modelled top face up because that is how it assembles, but it
    prints top face down - that is what turns every pocket into a first-layer
    recess and keeps the feet off support. Exporting it in assembly orientation
    is a quiet invitation to print it upside down, so it is turned over here.
    The riser and the face bracket already stand the right way up.

    Each part is then dropped onto z = 0. Slicers take STEP directly and it
    keeps the hex flats exact, where an STL would facet them.
    """
    directory = _writable(directory)
    for name, maker in PARTS.items():
        shape = maker().copy()
        if oriented:
            if name in PRINT_TURN:
                shape.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0),
                             PRINT_TURN[name])
            shape = shape.translated(App.Vector(0, 0, -shape.BoundBox.ZMin))
        path = os.path.join(directory, f"{name}.step")
        shape.exportStep(path)
        bb = shape.BoundBox
        print(f"  {name:<6} x{QUANTITY[name]}  {bb.XLength:6.1f} x"
              f" {bb.YLength:6.1f} x {bb.ZLength:6.1f} mm"
              f"   {shape.Volume / 1000:5.1f} cm3   {path}")


def _writable(directory: str) -> str:
    """Resolve an export directory, or explain why it cannot be one.

    OCC reports every failure to create a file as a bare "Writing of STEP
    failed", which reads like a geometry problem and is almost never one. The
    usual cause on Windows is a path written without a raw string: this project
    lives under \\nixe_clock\\...\\test_base, where the \\n is a newline and the
    \\t is a tab, so the path is mangled long before OCC sees it.
    """
    resolved = os.path.abspath(os.path.expanduser(directory))
    for bad, what in (("\n", "newline"), ("\t", "tab"), ("\r", "return")):
        if bad in resolved:
            raise ValueError(
                f"export path contains a {what}, so it was written without a "
                f"raw string: {resolved!r}. Use r\"...\" or double the "
                f"backslashes.")
    try:
        os.makedirs(resolved, exist_ok=True)
        probe = os.path.join(resolved, ".write-probe")
        with open(probe, "w") as fh:
            fh.write("")
        os.remove(probe)
    except OSError as exc:
        raise ValueError(f"cannot write to {resolved!r}: {exc}") from exc
    return resolved
