"""Write the KiCad model files for the INS-1.

Run with FreeCAD's interpreter whenever the model or its appearance changes:

    "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/ins1/export_kicad.py

WRL only, deliberately. KiCad would substitute a STEP of the same basename when
exporting a board model, but the lamp is worth more as VRML: a substituted solid
arrives grey, and the glass and the lit dot are material properties a STEP
cannot carry at all. cad/test_base/base_plate.py reads this file directly, the
same way it reads IN-12B.wrl. Shipping a STEP twin as well would put the lamp in
the model twice, once here and once through the board export.

Leads are cut for the recessed footprint, which sinks the lamp until the board
sits at z = 9.74 and solders them to pads on the back, so they have to reach
through. A flush mounting would want a second variant cut near z = -2.

VRML units here are 0.1 inch, which is what KiCad expects and what IN-12B.wrl
uses - its 8.0 x 12.0 unit envelope is a 20 x 30 mm tube. The footprint's own
offset stays in millimetres regardless.

Meshing goes through MeshPart rather than Shape.tessellate, which takes a
linear tolerance only. The shoulder is a B-spline surface of 128 by 23 poles
and its triangle count follows the poles, not the curvature, so a linear
tolerance alone puts 1.6 million triangles on this lamp. An angular tolerance
is what actually bounds it. Shape.tessellate also caches its result on the
shape and hands the same mesh back whatever tolerance you ask for next, which
makes it look as though the setting does nothing.

Normals are averaged per vertex, but only across facets meeting at less than
CREASE. The lamp needs both behaviours: the barrel runs into the dome and the
shoulder into both tangentially and must not show a seam, while the cathode rim
and the mica faces are real edges and have to stay hard.
"""

import math
import os
import sys

import FreeCAD as App
import MeshPart

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ins1 as G  # noqa: E402

OUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "pcb", "lib", "nixie_clock.3dshapes"))

WRL_UNIT = 2.54  # mm per VRML unit
LINEAR = 0.01  # chord tolerance, mm - 40 facets round the barrel
# Radians, ~23 degrees. This is what bounds the spline faces; the barrel and
# the other analytic surfaces stay on the linear tolerance, so the silhouette
# does not move with it. Tightening to 0.25 costs a third more triangles and
# changes nothing you can see, 0.60 saves only a further 6 per cent.
ANGULAR = 0.40
CREASE = math.radians(30)  # smooth across joins shallower than this

# Opaque first, glass last: a renderer blending transparency needs whatever is
# behind the glass already drawn.
ORDER = ("Wires", "Micas", "Anode", "Cathode", "Glow", "Glass")

# Not "below the board" - on this footprint the blade passes through the slot,
# so the board's front face is at z = 9.74 and its back copper at 8.14, while
# the leads leave the press underside at 4.60, already 3.54 behind the board.
# They are then formed forward onto the pads, which a straight lead cannot show;
# 2.00 leaves a visible 2.60 of wire past the press and stays shallower than the
# pip at 0.00, which is what actually sets the clearance behind the board.
VARIANTS = {
    "INS1_Recessed": 2.00,
}


def _mesh(shape):
    """(points, triangles, normals, normal indices), in millimetres.

    MeshPart welds the mesh, so a vertex on a real edge is shared by facets
    facing different ways. Normals are therefore per corner rather than per
    vertex - VRML indexes them separately from the coordinates for exactly this
    - and a corner averages only the facets within CREASE of its own.

    Corner normals are then pooled, because most of them repeat: every corner
    around a cylinder at one angle shares a normal. Written out one per corner
    they are about half the file.
    """
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=LINEAR,
                                  AngularDeflection=ANGULAR, Relative=False)
    points, triangles = mesh.Topology

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


def _vrml_material(spec: dict) -> str:
    mat = G._material(**spec)
    ambient = sum(mat.AmbientColor[:3]) / 3

    def rgb(c):
        return f"{c[0]:.6f} {c[1]:.6f} {c[2]:.6f}"

    return (f"          diffuseColor {rgb(mat.DiffuseColor)}\n"
            f"          emissiveColor {rgb(mat.EmissiveColor)}\n"
            f"          specularColor {rgb(mat.SpecularColor)}\n"
            f"          ambientIntensity {ambient:.6f}\n"
            f"          transparency {mat.Transparency:.6f}\n"
            f"          shininess {mat.Shininess:.6f}\n")


def _vrml_shape(name: str, mesh: tuple) -> str:
    points, triangles, normals, corners = mesh
    k = 1.0 / WRL_UNIT

    def block(rows, tail):
        return ",\n".join(f"          {r}" for r in rows) + f" {tail}"

    corners = [tuple(corners[3 * i:3 * i + 3]) for i in range(len(triangles))]

    return (
        f"DEF {name} Transform {{\n"
        f"  children [\n"
        f"    Shape {{\n"
        f"      appearance Appearance {{\n"
        # DEF'd, not anonymous. cad/test_base/vrml.py keys materials off the
        # name, as IN-12B.wrl carries them, and reads an unnamed one as the
        # default grey - which silently collapses all six parts into one.
        f"        material DEF {name} Material {{\n"
        f"{_vrml_material(G.APPEARANCE[name])}"
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


def write_wrl(path: str, parts: dict) -> tuple:
    meshes = {name: _mesh(parts[name]) for name in ORDER}
    with open(path, "w", encoding="utf-8") as out:
        out.write("#VRML V2.0 utf8\n")
        out.write("# INS-1 neon indicator, generated by cad/ins1/export_kicad.py\n")
        out.write(f"# 0.1 inch units; {LINEAR} mm and {ANGULAR} rad deflection\n\n")
        out.write("\n".join(_vrml_shape(name, meshes[name]) for name in ORDER))
    return os.path.getsize(path), sum(len(m[1]) for m in meshes.values())


def main():
    for stem, lead_bottom in VARIANTS.items():
        G.build(lead_bottom=lead_bottom)
        doc = App.getDocument(G.DOC_NAME)
        parts = {name: doc.getObject(name).Shape for name in ORDER}

        wrl = os.path.join(OUT_DIR, f"{stem}.wrl")
        size, triangles = write_wrl(wrl, parts)
        print(f"  {stem}.wrl   {size / 1024:8.1f} kB  {triangles} triangles")


# No __main__ guard: freecadcmd imports the script rather than running it, so
# __name__ is this file's stem and the usual guard never fires.
main()
