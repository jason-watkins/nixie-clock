"""Regenerate shoulder_profile.py from the source STEP.

Run with FreeCAD's interpreter when the source or the band definitions change:

    "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/ins1/sample_shoulder.py

The shoulder is the one region of the envelope we cannot build. It is a
rolling-ball fillet whose topology changes part way round - the press stops
being wider than the barrel - and OCCT's fillet will not make it at any radius,
on either edge set, however the press is sized. SolidWorks, which produced the
source, got the whole thing from Parasolid in one operation.

Three reconstructions were tried and all three failed on the ribs. A
press-to-circle morph drags them 0.40 mm outward where the source pulls them
in; a sharp union of the growing disc with the press leaves a 0.99 mm notch;
rolling-ball rounding inside the section plane fixes neither, because the
erosion is caused by the ball traveling in Z and a 2D operation cannot see it.

So it is measured. Each section is sliced from the source, walked by arc length
from where it crosses +x, averaged over its four quadrants, and written out as
one quarter of the points. ins1_glass mirrors them back.

This file is the only thing in the project that reads the STEP.
"""

import math
import os
import sys

import FreeCAD as App
import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ins1_glass as G  # noqa: E402

SOURCE_STEP = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "pcb", "lib", "nixie_clock.3dshapes", "INS1.STEP"))
STEP_Z_OFFSET = 10.60  # the source's origin sits this far below ours

STATION = 0.10  # station spacing; the loft is stable well past this
DECIMALS = 5

_source = None


def source_glass():
    """The outer glass solid from the source STEP, imported once."""
    global _source
    if _source is None:
        if not os.path.exists(SOURCE_STEP):
            raise RuntimeError(f"source STEP not found: {SOURCE_STEP}")
        import Import
        doc = App.newDocument("_ins1_source")
        Import.insert(SOURCE_STEP, doc.Name)
        solids = [o.Shape for o in doc.Objects if o.TypeId == "Part::Feature"]
        _source = max(solids, key=lambda s: s.Volume).copy()  # glass, not the inlay
        App.closeDocument(doc.Name)
    return _source


def resample(points, n_pts):
    """Respace a closed polygon evenly by arc length."""
    closed = points + [points[0]]
    run = [0.0]
    for i in range(1, len(closed)):
        run.append(run[-1] + math.hypot(closed[i][0] - closed[i - 1][0],
                                        closed[i][1] - closed[i - 1][1]))
    out, j = [], 0
    for k in range(n_pts):
        target = run[-1] * k / n_pts
        while j < len(run) - 2 and run[j + 1] < target:
            j += 1
        step = run[j + 1] - run[j]
        f = (target - run[j]) / step if step > 1e-15 else 0.0
        a, b = closed[j], closed[j + 1]
        out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
    return out


def section_at(z, n_pts, grid=720):
    """One symmetrized section of the source at our height z."""
    section = source_glass().slice(App.Vector(0, 1, 0), z - STEP_Z_OFFSET)
    if len(section) != 1 or not section[0].isClosed():
        raise RuntimeError(f"source section at z={z} is not one closed wire")
    wire = section[0]  # already ordered; re-sorting it splits it into chains

    # Arc length, not polar angle - the ribs occupy a couple of degrees and
    # sampling by angle loses 0.15 mm off the thickness right there. The
    # source's axis is Y, so its (x, z) is our (x, y).
    dense = [(p.x, p.z) for p in wire.discretize(Number=grid)]
    if dense[0] == dense[-1]:
        dense.pop()
    n = len(dense)

    area = sum(dense[i][0] * dense[(i + 1) % n][1] - dense[(i + 1) % n][0] * dense[i][1]
               for i in range(n))
    if area < 0:
        dense.reverse()

    # Start exactly where the outline crosses +x, so every section is indexed
    # from the same place as the press and the loft has nothing to twist.
    cut = None
    for i in range(n):
        a, b = dense[i], dense[(i + 1) % n]
        if a[1] > 0.0 or b[1] < 0.0:
            continue
        span = b[1] - a[1]
        f = 0.0 if abs(span) < 1e-15 else (0.0 - a[1]) / span
        x = a[0] + f * (b[0] - a[0])
        if x > 0.0:
            cut = (i, (x, 0.0))
            break
    if cut is None:
        raise RuntimeError(f"no +x crossing in the source section at z={z}")
    i, p0 = cut
    pts = resample([p0] + dense[i + 1:] + dense[: i + 1], n_pts)

    # Average the four quadrants. The source is hand-modeled and out of true by
    # up to 0.05 mm - ribs at 0.975 on one side and 1.025 on the other - and
    # because that error varies with height it prints ripples around the
    # finished shoulder.
    out = []
    for k in range(n_pts):
        a, b = pts[k], pts[(n_pts // 2 - k) % n_pts]
        c, d = pts[(n_pts - k) % n_pts], pts[(n_pts // 2 + k) % n_pts]
        out.append((0.25 * (a[0] - b[0] + c[0] - d[0]),
                    0.25 * (a[1] + b[1] - c[1] - d[1])))
    return out


def main():
    steps = int(round((G.Z_SHOULDER_END - G.Z_SHOULDER) / STATION))
    zs = [round(G.Z_SHOULDER + k * STATION, 6) for k in range(1, steps)]
    quarter = G.SECTION_POINTS // 4

    rows = []
    for z in zs:
        pts = section_at(z, G.SECTION_POINTS)
        rows.append((z, pts[: quarter + 1]))
        print(f"  z={z:.4f}  width {2 * max(x for x, _ in pts):.4f}  "
              f"thickness {2 * max(abs(y) for _, y in pts):.4f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "shoulder_profile.py")
    with open(out, "w") as f:
        f.write('"""Shoulder sections measured off INS1.STEP. Generated - do not edit.\n\n')
        f.write("Regenerate with sample_shoulder.py, which explains why this region\n")
        f.write("is measured rather than modeled.\n\n")
        f.write(f"One quarter of each section, {quarter + 1} points running counter-\n")
        f.write("clockwise from +x to +y. ins1_glass.shoulder_points mirrors them.\n")
        f.write('"""\n\n')
        f.write(f"SECTION_POINTS = {G.SECTION_POINTS}\n\n")
        f.write("# (height, [(x, y), ...])\n")
        f.write("SECTIONS = [\n")
        for z, pts in rows:
            f.write(f"    ({z:.4f}, [\n")
            for i in range(0, len(pts), 3):
                f.write("        " + " ".join(
                    f"({x:.{DECIMALS}f}, {y:.{DECIMALS}f})," for x, y in pts[i:i + 3]) + "\n")
            f.write("    ]),\n")
        f.write("]\n")
    print(f"wrote {out}: {len(rows)} sections x {quarter + 1} points")


main()
