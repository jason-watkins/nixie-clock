"""Write the KiCad model file for the IN-12B.

    "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/in12/export_kicad.py

WRL only. See cad/kicad_wrl.py for the writer and cad/ins1/export_kicad.py for
why a STEP twin would be worth less than nothing here.
"""

import os
import sys

import FreeCAD as App

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import in12 as T  # noqa: E402
import kicad_wrl  # noqa: E402

OUT_DIR = os.path.normpath(os.path.join(
    HERE, "..", "..", "pcb", "lib", "nixie_clock.3dshapes"))

ORDER = ("Pins", "Spacers", "Plate", "Getter", "Shields", "Bars", "Anode",
         "Cathodes", "Marks", "Glass")
STEM = "IN12B"

# The internals are wire, a tenth the size of anything on the envelope.
FINE = {name: (0.05, 0.60)
        for name in ("Pins", "Spacers", "Plate", "Getter", "Shields", "Bars",
                     "Anode", "Cathodes", "Marks")}


def main():
    T.build()
    doc = App.getDocument(T.DOC_NAME)
    parts = {name: doc.getObject(name).Shape for name in ORDER}
    path = os.path.join(OUT_DIR, f"{STEM}.wrl")
    size, triangles = kicad_wrl.write(path, "IN-12B nixie indicator", parts,
                                      ORDER, T.APPEARANCE, T._material, FINE)
    print(f"  {STEM}.wrl   {size / 1024:8.1f} kB  {triangles} triangles")


# No __main__ guard: freecadcmd imports the script rather than running it, so
# __name__ is this file's stem and the usual guard never fires.
main()
