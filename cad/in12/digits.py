"""Cathode numeral paths for the IN-12B.

Centrelines, not outlines. A nixie cathode is a bent wire of constant diameter,
so what a digit is is a path; sweeping a circle along it is then exact and
matches how the part is made. This is also why no font would have served -
a glyph is a filled contour, and recovering a centreline from one is
skeletonisation, which is lossy and ugly at junctions.

Coordinates are millimetres about the digit's own centre, x across the tube's
narrow face and y along its long one. The box is 18 tall, which the datasheet
dimensions and a photograph of a tube confirms, by about 10.3 wide, measured
off the same photograph.

These shapes are AUTHORED, not traced. Ten wire numerals at 1.1 mm pitch
overlap into a thicket in every photograph taken through the face; the front
digit - a 3, which agrees with both the published stack order and the
datasheet's own face view - is the only one legible. The rest are drawn in the
same style at the measured proportions. Treat their proportions as real and
their details as plausible.

One detail is not invention: the 5 is an upside-down 2. Two independent sources
say so, and it is the sort of economy a manufacturer takes, so it is built that
way here rather than drawn twice.

A digit is a list of paths, because not every numeral is one wire - a 4 has a
welded junction and a 0 is a closed loop.
"""

import math

H = 9.0  # half the 18 mm digit height
W = 4.0  # half the glyph width; the 10.3 box allows a little side bearing
R = 4.0  # bowl radius, which sets the whole style


def _arc(cx, cy, r, a0, a1, steps=10):
    """Points along a circular arc, degrees, signed sweep.

    Sparse on purpose. These points become the poles of the interpolated
    spine, the swept pipe inherits them, and the mesher follows the pipe -
    so sampling an arc at 24 points rather than 10 costs nothing in shape at
    a 0.32 wire and triples the exported mesh.
    """
    a0, a1 = math.radians(a0), math.radians(a1)
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / steps),
             cy + r * math.sin(a0 + (a1 - a0) * k / steps))
            for k in range(steps + 1)]


def _line(x0, y0, x1, y1, steps=1):
    return [(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
            for k in range(steps + 1)]


def _join(*runs):
    """Concatenate runs, dropping the duplicated point at each seam."""
    out = list(runs[0])
    for run in runs[1:]:
        out.extend(run[1:])
    return out


def _turn(paths):
    """The same wire rotated half a turn - how a 5 is made from a 2."""
    return [[(-x, -y) for x, y in path] for path in paths]


# The foot is a bend, not a corner. Drawn as a corner the interpolated
# centreline turns inside the wire's own radius there, and the swept pipe
# self-intersects rather than closing - which is also what real wire does, so
# the 1.0 bend that fixes it is the honest shape and not a workaround.
_TWO = [_join(
    _arc(0, H - R, R, 200, -30),          # over the top and down the right
    _line(3.46, 3.00, -3.27, -7.50, steps=6),   # the diagonal
    _arc(-2.40, -8.00, 1.00, 150, 270, steps=8),  # roll onto the foot
    _line(-2.40, -H, W, -H, steps=3),     # the base bar
)]

PATHS = {
    0: [_join(_arc(0, H - R, R, 0, 180),
              _line(-R, H - R, -R, -(H - R), steps=4),
              _arc(0, -(H - R), R, 180, 360),
              _line(R, -(H - R), R, H - R, steps=4))],

    1: [_join(_line(-2.4, H - 3.0, 1.3, H, steps=2),
              _line(1.3, H, 1.3, -H, steps=8))],

    2: _TWO,

    3: [_join(_arc(0, 4.6, 4.4, 170, -75),
              _arc(0, -4.6, 4.4, 75, -170))],

    # A junction: the stem is welded across the diagonal and the bar.
    4: [_join(_line(1.6, H, -W, -1.6, steps=6),
              _line(-W, -1.6, W, -1.6, steps=3)),
        _line(1.6, H, 1.6, -H, steps=8)],

    5: _turn(_TWO),

    # The tail is placed by hand rather than struck as an arc: every radius
    # that reaches from the top of the box down to the bowl also reaches past
    # the 4.2 the glyph is allowed, so it is drawn as points and left to the
    # interpolation, which is what a bent wire is anyway.
    # Two pieces: an open tail, and the bowl as a closed loop it runs into.
    # Drawn as one path the wire doubles back over itself where the bowl
    # closes, and an offset cannot be taken through that.
    6: [[(2.9, 8.6), (0.9, 8.1), (-1.4, 6.6), (-3.1, 4.2), (-3.9, 1.2), (-4.15, -1.9)],
        _arc(0, -4.6, 4.2, 0, 360, steps=28)],

    7: [_join(_line(-W, H, W, H, steps=3),
              _line(W, H, -1.4, -H, steps=8))],

    8: [_arc(0, H - R - 0.4, R - 0.4, 0, 360),
        _arc(0, -(H - R - 0.4), R - 0.4, 0, 360)],

    9: _turn([[(2.9, 8.6), (0.9, 8.1), (-1.4, 6.6), (-3.1, 4.2), (-3.9, 1.2),
               (-4.15, -1.9)],
              _arc(0, -4.6, 4.2, 0, 360, steps=28)]),
}

# The decimal point sits low and outboard of the digits, on its own cathode.
DP = [_arc(0, 0, 0.62, 0, 360)]
DP_AT = (-6.4, -7.0)
