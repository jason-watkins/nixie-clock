"""Write a KiCad VRML model from FreeCAD shapes.

Shared by the parts under cad/ that ship as .wrl. KiCad reads appearance from
VRML and cad/test_base/vrml.py reads the same file back, so this is the only
artifact a glass part needs; see cad/ins1/export_kicad.py on why no STEP twin
goes with it.

Units are 0.1 inch, which is what KiCad expects. A footprint's own offset stays
in millimetres regardless.

Meshing goes through MeshPart rather than Shape.tessellate, which takes a linear
tolerance only. A lofted B-spline's triangle count follows its poles rather than
its curvature, so a linear tolerance alone put 1.6 million triangles on the
INS-1; an angular tolerance is what actually bounds it. Shape.tessellate also
caches its result on the shape and hands the same mesh back whatever tolerance
you ask for next, which makes it look as though the setting does nothing.

Normals are averaged per vertex, but only across facets meeting at less than
CREASE. Both behaviours are needed: surfaces that run into each other
tangentially must not show a seam, while a rim or a flat face is a real edge and
has to stay hard.
"""

import math
import os

import FreeCAD as App
import MeshPart

WRL_UNIT = 2.54  # mm per VRML unit
LINEAR = 0.01  # chord tolerance, mm - 40 facets round a 6.5 dia barrel
# Radians, ~23 degrees. This is what bounds spline faces; analytic ones stay on
# the linear tolerance, so a silhouette does not move with it. Tightening to
# 0.25 cost a third more triangles on the INS-1 and changed nothing visible.
ANGULAR = 0.40
CREASE = math.radians(30)  # smooth across joins shallower than this


def mesh(shape, linear=None, angular=None):
    """(points, triangles, normals, normal indices) for one part, in mm.

    MeshPart welds the mesh, so a vertex on a real edge is shared by facets
    facing different ways. Normals are therefore per corner rather than per
    vertex - VRML indexes them separately from the coordinates for exactly this
    - and a corner averages only the facets within CREASE of its own.

    Corner normals are then pooled, because most of them repeat: every corner
    around a cylinder at one angle shares a normal. Written out one per corner
    they are about half the file.
    """
    built = MeshPart.meshFromShape(Shape=shape,
                                   LinearDeflection=LINEAR if linear is None else linear,
                                   AngularDeflection=ANGULAR if angular is None else angular,
                                   Relative=False)
    points, triangles = built.Topology

    weighted, incident = [], [[] for _ in points]
    for index, (a, b, c) in enumerate(triangles):
        # Length is twice the area, so this weights by facet size on its own.
        weighted.append((points[b] - points[a]).cross(points[c] - points[a]))
        for corner in (a, b, c):
            incident[corner].append(index)

    limit = math.cos(CREASE)
    unit = [v.normalize() if v.Length > 1e-12 else App.Vector(0, 0, 1)
            for v in weighted]

    pool, normals, corners = {}, [], []
    for index, triangle in enumerate(triangles):
        for corner in triangle:
            total = App.Vector()
            for other in incident[corner]:
                if unit[other].dot(unit[index]) >= limit:
                    total += weighted[other]
            n = total.normalize() if total.Length > 1e-12 else unit[index]
            key = (round(n.x, 4), round(n.y, 4), round(n.z, 4))
            slot = pool.get(key)
            if slot is None:
                slot = pool[key] = len(normals)
                normals.append(n)
            corners.append(slot)
    return points, triangles, normals, corners


def material(spec: dict, build) -> str:
    """One VRML material block, from an APPEARANCE entry and its part's
    _material factory, so the file says exactly what the GUI shows."""
    mat = build(**spec)
    ambient = sum(mat.AmbientColor[:3]) / 3

    def rgb(c):
        return f"{c[0]:.6f} {c[1]:.6f} {c[2]:.6f}"

    return (f"          diffuseColor {rgb(mat.DiffuseColor)}\n"
            f"          emissiveColor {rgb(mat.EmissiveColor)}\n"
            f"          specularColor {rgb(mat.SpecularColor)}\n"
            f"          ambientIntensity {ambient:.6f}\n"
            f"          transparency {mat.Transparency:.6f}\n"
            f"          shininess {mat.Shininess:.6f}\n")


def _shape_node(name: str, built: tuple, spec: dict, factory) -> str:
    points, triangles, normals, corners = built
    k = 1.0 / WRL_UNIT

    def block(rows, tail):
        return ",\n".join(f"          {r}" for r in rows) + f" {tail}"

    corners = [tuple(corners[3 * i:3 * i + 3]) for i in range(len(triangles))]

    return (
        f"DEF {name} Transform {{\n"
        f"  children [\n"
        f"    Shape {{\n"
        f"      appearance Appearance {{\n"
        f"        material DEF {name} Material {{\n"
        f"{material(spec, factory)}"
        f"        }}\n"
        f"      }}\n"
        f"      geometry IndexedFaceSet {{\n"
        f"        normalPerVertex TRUE\n"
        f"        coord Coordinate {{ point [\n"
        + block([f"{p.x * k:.5f} {p.y * k:.5f} {p.z * k:.5f}" for p in points],
                "] }") + "\n"
        f"        coordIndex [\n"
        + block([f"{a}, {b}, {c}, -1" for a, b, c in triangles], "]") + "\n"
        f"        normal Normal {{ vector [\n"
        + block([f"{n.x:.5f} {n.y:.5f} {n.z:.5f}" for n in normals], "] }") + "\n"
        f"        normalIndex [\n"
        + block([f"{a}, {b}, {c}, -1" for a, b, c in corners], "]") + "\n"
        f"      }}\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )


def write(path: str, title: str, parts: dict, order, appearance: dict,
          factory, deflection: dict = None) -> tuple:
    """Write one .wrl. parts maps name -> Shape; order is the write order.

    Materials are DEF'd by part name, not left anonymous: cad/test_base/vrml.py
    keys off the name and reads an unnamed one as the default grey, which
    silently collapses every part of a model into one.

    Order opaque first and glass last, so a renderer blending transparency has
    whatever is behind the glass already drawn.
    """
    # Per-part tolerances, because one number cannot serve a 10.5 mm glass
    # radius and a 0.16 mm wire at once. The glass needs 0.01 to keep its
    # silhouette; held to the same figure the swept numerals alone came to
    # 146,000 triangles, nine tenths of the file, for detail no one can see
    # through 0.8 of glass.
    deflection = deflection or {}
    meshes = {name: mesh(parts[name], *deflection.get(name, (None, None)))
              for name in order}
    with open(path, "w", encoding="utf-8") as out:
        out.write("#VRML V2.0 utf8\n")
        out.write(f"# {title}, generated by cad/kicad_wrl.py\n")
        out.write(f"# 0.1 inch units; {LINEAR} mm and {ANGULAR} rad deflection\n\n")
        out.write("\n".join(
            _shape_node(name, meshes[name], appearance[name], factory)
            for name in order))
    return os.path.getsize(path), sum(len(m[1]) for m in meshes.values())
