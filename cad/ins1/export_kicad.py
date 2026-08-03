"""Write the KiCad model files for the INS-1.

Run with FreeCAD's interpreter whenever the model or its appearance changes:

    "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/ins1/export_kicad.py

KiCad takes appearance from the WRL and mechanical geometry from a STEP of the
same basename, and picks the STEP up on its own when exporting a board model,
so the two ship together and the footprint points at the WRL.

Two variants, differing only in where the leads are cut. The flush footprint
stands the lamp on the board, so its leads want trimming just below it; the
recessed one sinks the lamp until the board sits at z = 9.74 and solders the
leads to pads on the back, so they have to reach through.

VRML units here are 0.1 inch, which is what KiCad expects and what IN-12B.wrl
uses - its 8.0 x 12.0 unit envelope is a 20 x 30 mm tube. The footprint's own
offset stays in millimetres regardless.

Normals come from the real surface rather than from the triangles, so a face is
smooth however coarsely it is tessellated, and two faces meeting tangentially -
the barrel into the dome, the shoulder into either - agree exactly across the
seam instead of showing it as a crease.
"""

import os
import sys

import FreeCAD as App
import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ins1 as G  # noqa: E402

OUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "pcb", "lib", "nixie_clock.3dshapes"))

WRL_UNIT = 2.54  # mm per VRML unit
DEVIATION = 0.01  # tessellation chord tolerance, mm

# Opaque first, glass last: a renderer blending transparency needs whatever is
# behind the glass already drawn.
ORDER = ("Wires", "Micas", "Anode", "Cathode", "Glow", "Glass")

VARIANTS = {
    "INS1": G.LEAD_BOTTOM,
    "INS1_Recessed": 7.74,  # 2.00 below a board sitting at 9.74
}


def _tessellate(shape: Part.Shape, deviation: float = DEVIATION):
    """(points, normals, triangles) for one solid, in millimetres.

    Tessellated a face at a time, because a face is the largest patch over
    which the surface normal is continuous. Winding is taken from the normal
    rather than trusted, so back-face culling cannot turn a part inside out.
    """
    points, normals, triangles = [], [], []
    for face in shape.Faces:
        pts, tris = face.tessellate(deviation)
        base = len(points)
        surface = face.Surface
        for p in pts:
            points.append(p)
            try:
                normals.append(face.normalAt(*surface.parameter(p)))
            except Exception:
                normals.append(None)  # filled in from the triangles below
        for tri in tris:
            a, b, c = (base + i for i in tri)
            geometric = (points[b] - points[a]).cross(points[c] - points[a])
            reference = next((normals[i] for i in (a, b, c)
                              if normals[i] is not None), None)
            if reference is not None and geometric.dot(reference) < 0:
                a, c = c, a
                geometric = -geometric
            triangles.append((a, b, c))
            for i in (a, b, c):
                if normals[i] is None:
                    normals[i] = geometric
    # Anything the projection could not place falls back to its facet normal.
    for i, n in enumerate(normals):
        normals[i] = (n or App.Vector(0, 0, 1)).normalize()
    return points, normals, triangles


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
    points, normals, triangles = mesh
    k = 1.0 / WRL_UNIT

    def block(rows, tail):
        return ",\n".join(f"          {r}" for r in rows) + f" {tail}"

    return (
        f"DEF {name} Transform {{\n"
        f"  children [\n"
        f"    Shape {{\n"
        f"      appearance Appearance {{\n"
        f"        material Material {{\n"
        f"{_vrml_material(G.APPEARANCE[name])}"
        f"        }}\n"
        f"      }}\n"
        f"      geometry IndexedFaceSet {{\n"
        f"        normalPerVertex TRUE\n"
        f"        coord Coordinate {{ point [\n"
        + block([f"{p.x * k:.6f} {p.y * k:.6f} {p.z * k:.6f}" for p in points],
                "] }") + "\n"
        f"        coordIndex [\n"
        + block([f"{a}, {b}, {c}, -1" for a, b, c in triangles], "]") + "\n"
        f"        normal Normal {{ vector [\n"
        + block([f"{n.x:.6f} {n.y:.6f} {n.z:.6f}" for n in normals], "] }") + "\n"
        f"        normalIndex [\n"
        + block([f"{a}, {b}, {c}, -1" for a, b, c in triangles], "]") + "\n"
        f"      }}\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )


def write_wrl(path: str, parts: dict) -> tuple:
    meshes = {name: _tessellate(parts[name]) for name in ORDER}
    with open(path, "w", encoding="utf-8") as out:
        out.write("#VRML V2.0 utf8\n")
        out.write("# INS-1 neon indicator, generated by cad/ins1/export_kicad.py\n")
        out.write(f"# 0.1 inch units, {DEVIATION} mm tessellation\n\n")
        out.write("\n".join(_vrml_shape(name, meshes[name]) for name in ORDER))
    return os.path.getsize(path), sum(len(m[2]) for m in meshes.values())


def write_step(path: str, doc, parts: dict) -> int:
    import Import
    objects = [doc.getObject(name) for name in ORDER]
    Import.export(objects, path)
    return os.path.getsize(path)


def main():
    for stem, lead_bottom in VARIANTS.items():
        G.build(lead_bottom=lead_bottom)
        doc = App.getDocument(G.DOC_NAME)
        parts = {name: doc.getObject(name).Shape for name in ORDER}

        wrl = os.path.join(OUT_DIR, f"{stem}.wrl")
        step = os.path.join(OUT_DIR, f"{stem}.step")
        size, triangles = write_wrl(wrl, parts)
        print(f"  {stem}.wrl   {size / 1024:8.1f} kB  {triangles} triangles")
        print(f"  {stem}.step  {write_step(step, doc, parts) / 1024:8.1f} kB")


# No __main__ guard: freecadcmd imports the script rather than running it, so
# __name__ is this file's stem and the usual guard never fires.
main()
