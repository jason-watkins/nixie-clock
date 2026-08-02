"""Read a KiCad VRML model, materials included.

KiCad ships some 3D models only as .wrl, and its STEP exporter cannot use them:
VRML is a shaded mesh, not a solid, so those parts are silently absent from an
exported board. IN-12B.wrl is the one that matters here - the nixie tubes.

Loading it directly is the way to get them, and it is also the only way to get
what makes a nixie tube look like one. A STEP twin would carry the geometry and
throw away the glass; the VRML carries `transparency` per material, and the tube
is authored as several: GLASS2 at 0.75, GLASS3 at 0.59, BRASS for the anode
mesh, BLACK for the base, pink for the digits.

The file this was written against is Wings3D output with a flat structure - one
top-level Transform holding a list of Shape nodes, no nesting, no per-node
placement - so the reader is deliberately simple. Materials are DEF'd on first
use and USE'd afterwards, which is the one piece of VRML indirection it does
handle. Anything more elaborate is not supported and will read as untextured
geometry rather than failing quietly, so check the material count.

Coordinates are scaled by 2.54: KiCad authors VRML in tenths of an inch.
"""

import re

SCALE = 2.54
FLOAT = r"-?[\d.]+(?:[eE][-+]?\d+)?"


class Material:
    """A VRML material, reduced to what a view provider can show."""

    def __init__(self, name: str, rgb: tuple, transparency: float):
        self.name = name
        self.rgb = rgb
        self.transparency = transparency

    def __repr__(self):
        return (f"Material({self.name!r}, rgb={self.rgb}, "
                f"transparency={self.transparency:.2f})")


def _material(block: str, name: str) -> Material:
    def grab(key, count, default):
        m = re.search(key + r"\s+" + r"\s+".join([f"({FLOAT})"] * count), block)
        return tuple(float(g) for g in m.groups()) if m else default

    rgb = grab("diffuseColor", 3, (0.8, 0.8, 0.8))
    return Material(name, rgb, grab("transparency", 1, (0.0,))[0])


def _facets(block: str, base: int) -> list:
    """Triangulate the coordIndex of one IndexedFaceSet, offset into a pool."""
    m = re.search(r"coordIndex\s*\[(.*?)\]", block, re.S)
    if not m:
        return []
    out, poly = [], []
    for token in re.findall(r"-?\d+", m.group(1)):
        i = int(token)
        if i < 0:
            # fan from the first vertex; these are convex faces
            out += [(base + poly[0], base + poly[k], base + poly[k + 1])
                    for k in range(1, len(poly) - 1)]
            poly = []
        else:
            poly.append(i)
    return out


def load(path: str, scale: float = SCALE) -> list:
    """[(Material, points, facets)] - one entry per material, meshes merged.

    Merging by material is what makes this usable: 208 Shape nodes become a
    handful of objects, each of which can carry one colour and one transparency.
    """
    text = open(path, "r", errors="replace").read()
    known, groups, order = {}, {}, []

    for block in re.split(r"\bShape\s*\{", text)[1:]:
        dm = re.search(r"material\s+DEF\s+(\w+)\s+Material\s*\{", block)
        um = re.search(r"material\s+USE\s+(\w+)", block)
        if dm:
            name = dm.group(1)
            known[name] = _material(block, name)
        elif um:
            name = um.group(1)
        else:
            name = "default"
            known.setdefault(name, Material(name, (0.8, 0.8, 0.8), 0.0))
        material = known.get(name) or Material(name, (0.8, 0.8, 0.8), 0.0)

        pm = re.search(r"point\s*\[(.*?)\]", block, re.S)
        if not pm:
            continue
        pts = [(float(a) * scale, float(b) * scale, float(c) * scale)
               for a, b, c in re.findall(
                   f"({FLOAT})\\s+({FLOAT})\\s+({FLOAT})", pm.group(1))]
        if not pts:
            continue

        if name not in groups:
            groups[name] = (material, [], [])
            order.append(name)
        _, pool, faces = groups[name]
        faces += _facets(block, len(pool))
        pool += pts

    return [groups[n] for n in order]


def summary(path: str) -> str:
    """One line per material, for checking a file reads the way it should."""
    rows = []
    for material, pts, faces in load(path):
        rows.append(f"  {material.name:<18}rgb {material.rgb[0]:.2f},"
                    f"{material.rgb[1]:.2f},{material.rgb[2]:.2f}"
                    f"   transparency {material.transparency:.2f}"
                    f"   {len(pts):>6} pts {len(faces):>6} tris")
    return "\n".join(rows)
