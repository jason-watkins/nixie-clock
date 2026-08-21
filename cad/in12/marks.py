"""Glass markings for the IN-12B: the quality mark and the type and date.

The mark is the USSR State Quality Mark - a pentagon with a stylised K inside.
Its outline is taken off the reference model, which draws it as four flat
polygons (an outer pentagon and three holes) and gets it close enough that
redrawing it by eye would only be worse. The loops below are that geometry,
normalised so the mark's larger span is 1.0, so MARK_SIZE alone scales it.

Nothing else here comes from the reference: the lettering is set in PT Serif,
which the design analysis already carries and which has a full Cyrillic set,
and the layout is off photographs of tubes in hand.

Coordinates are (across, up) on the glass - across the tube's long axis, up its
height - and the marks are wrapped onto the real surface in in12.py rather than
being laid flat, so they follow the curve where the side stops being straight.
"""

# The mark as the reference draws it: the front skin's own triangles,
# normalised so the larger span is 1.0, so MARK_SIZE alone scales it. Kept as
# triangles rather than as outlines because chaining the mesh edges into loops
# merges pairs of holes through the vertex they share, and the near-degenerate
# pinch that leaves cannot be cut cleanly.
QUALITY_MARK = [
    ((-0.5000, +0.0961), (-0.3894, +0.1086), (-0.4192, +0.1189)),
    ((-0.5000, +0.0961), (-0.3177, -0.4669), (-0.2797, -0.4130)),
    ((-0.5000, +0.0961), (+0.0000, +0.4106), (+0.0000, +0.4669)),
    ((-0.3177, -0.4669), (-0.2459, -0.4414), (-0.2328, -0.4228)),
    ((-0.3177, -0.4669), (+0.3177, -0.4669), (+0.2328, -0.4228)),
    ((-0.3177, -0.4669), (-0.2459, -0.4414), (-0.2797, -0.4130)),
    ((-0.5000, +0.0961), (-0.2797, -0.4130), (-0.4347, +0.0737)),
    ((-0.5000, +0.0961), (-0.3894, +0.1086), (+0.0000, +0.4106)),
    ((+0.5000, +0.0961), (+0.0000, +0.4669), (+0.0000, +0.4106)),
    ((-0.3177, -0.4669), (+0.2328, -0.4228), (-0.2328, -0.4228)),
    ((-0.2797, -0.4130), (-0.2459, -0.4414), (+0.0000, -0.2466)),
    ((-0.5000, +0.0961), (-0.4347, +0.0737), (-0.4192, +0.1189)),
    ((+0.5000, +0.0961), (+0.0000, +0.4106), (+0.3894, +0.1086)),
    ((-0.4347, +0.0737), (+0.0000, +0.0757), (-0.4192, +0.1189)),
    ((-0.4347, +0.0737), (+0.0000, -0.0752), (+0.0000, +0.0757)),
    ((+0.3177, -0.4669), (+0.2328, -0.4228), (+0.2459, -0.4414)),
    ((+0.5000, +0.0961), (+0.2797, -0.4130), (+0.3177, -0.4669)),
    ((+0.3177, -0.4669), (+0.2797, -0.4130), (+0.2459, -0.4414)),
    ((-0.2797, -0.4130), (+0.0000, -0.2466), (+0.0000, -0.0772)),
    ((+0.4347, +0.0737), (+0.4192, +0.1189), (+0.0000, +0.0757)),
    ((+0.4347, +0.0737), (+0.0000, +0.0757), (+0.0000, -0.0752)),
    ((+0.2797, -0.4130), (+0.0000, -0.2466), (+0.2459, -0.4414)),
    ((+0.5000, +0.0961), (+0.4347, +0.0737), (+0.2797, -0.4130)),
    ((+0.2797, -0.4130), (+0.0000, -0.0772), (+0.0000, -0.2466)),
    ((+0.5000, +0.0961), (+0.4192, +0.1189), (+0.4347, +0.0737)),
    ((+0.5000, +0.0961), (+0.4192, +0.1189), (+0.3894, +0.1086)),
]
# Sans with a real Cyrillic set. A face without one renders С, Р, И and Б as
# notdef slashes - and reports them as glyphs while doing it, so only looking at
# the result catches it.
#
# First that exists wins, and a bare name is looked for among the repo's own
# fonts. Calibri Light draws a 1 with no foot bar, which is what the tubes have,
# at about the right weight; it is a Windows font, so it is referenced where it
# lies rather than copied in, which would not be permitted anyway. It is wanted
# only to generate the WRL and that is committed, so nobody else needs it.
#
# There is deliberately no fallback. A second face would still generate, but it
# would set the lettering differently - heavier, and with a foot on the 1 - and
# a render that quietly changed would read as a regression rather than as a
# substitution. Better to stop and say so.
FONTS = ("C:/Windows/Fonts/calibril.ttf",)

# The quality mark, on one side. Sized and placed off tubes in hand: its foot
# runs level with the bottom plate and its head with the front digit.
MARK_SIZE = 12.00
MARK_AT = (0.0, 15.60)

# СССР sits in the white triangle above the stylised K, not on the band below
# it - measured off a photograph as a fraction of the mark, so it tracks
# MARK_SIZE rather than having to be re-placed if that changes.
MARK_TEXT = "СССР"
MARK_TEXT_H = 0.120 * MARK_SIZE
MARK_TEXT_AT = (MARK_AT[0], MARK_AT[1] + 0.170 * MARK_SIZE)
# The lettering arches, and each letter leans to follow it. Off the photograph:
# about 0.38 of rise over a 7.5 chord, which is this radius.
MARK_TEXT_ARC = 1.55 * MARK_SIZE

# Type and date, on the other side.
#
# Whatever prints these is not accurate, and tubes in hand carry the lettering
# at very nearly any height that will physically fit - so the layout's internal
# proportions are what matter and its overall size is a judgement. STAMP is
# that judgement and the only number to touch; everything below is a fraction
# of it, so the block scales as a piece.
#
# Heights here are the letters' own, not a font size: _text_faces measures what
# the font gives and rescales, so a circle asked to match them really does.
STAMP = 1.35
STAMP_AT = 15.60  # block centre, level with the quality mark's on the far side
STAMP_ROWS = 4.00 * STAMP  # between the two lines' centres

TYPE_TEXT = "ИН-12Б"  # IN-12B
TYPE_H = 2.15 * STAMP
TYPE_AT = (0.0, STAMP_AT + STAMP_ROWS / 2)

DATE_LEFT = "08"
DATE_RIGHT = "82"
DATE_H = 2.15 * STAMP
DATE_AT = (0.0, STAMP_AT - STAMP_ROWS / 2)
DATE_GAP = 3.60 * STAMP  # centre to centre of the two numbers
DOT_R_OUTER = DATE_H / 2  # the circle stands as tall as the letters
DOT_R_RING = 0.14 * STAMP
DOT_R_INNER = 0.44 * STAMP  # twice the reference's, as the tubes have it

INK = 0.030  # how far the marking stands off the glass
