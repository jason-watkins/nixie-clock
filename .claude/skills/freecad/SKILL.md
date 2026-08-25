---
name: freecad
description: Build, verify and export the FreeCAD part models under cad/ (INS-1, IN-12B, ECQ-E, SRN5040, the test base). Runs scripts under freecadcmd with real tracebacks, regenerates a part's KiCad model, reads a .wrl back to check its materials, a STEP to check its solids and colors, or an STL to check it is closed and count its holes, measures dimensions off a datasheet drawing, and carries the modeling conventions and OCCT traps learned on this project. Use for any FreeCAD, 3D-model, WRL/STEP/STL export, kicad-cli board-body export, KiCad 3D-appearance or package-drawing measurement question.
---

# FreeCAD part models

All tool operations go through one script so a single Bash permission rule
covers them:

```
python .claude/skills/freecad/scripts/fc_tool.py <subcommand> [args]
```

Invoke it exactly like that, relative to the repo root, and never `cd` in a
Bash call: the tool's working directory persists across calls, and every
later relative invocation then fails. Write a probe script with the Write
tool rather than a shell heredoc; a heredoc holding quotes and backslashes
can die in the shell layer (`unexpected EOF while looking for matching
quote`) before anything runs. `run`, `export`, `step` and `mesh` spawn
`freecadcmd.exe` (`FREECADCMD`, else PATH, else the newest
`C:/Program Files/FreeCAD*`); `wrl`, `parts` and `drawing` are plain Python.

| Command | Purpose |
|---|---|
| `run [--gui] SCRIPT [ARGS...]` | Run a Python file under freecadcmd as `__main__`, by path, with the real traceback and exit status. `--gui` starts FreeCADGui offscreen first, which colored STEP export needs. |
| `export PART` | Regenerate `cad/PART`'s KiCad model: `export_kicad.py` if the part has one (WRL parts), else the module's `export()` under `--gui` (STEP parts). A STEP whose geometry and colors match the file it replaces is put back as it was, so `git status` shows a regenerated STEP only when something moved. |
| `step [--brief] PATH...` | Read STEP files back under freecadcmd: products, `COLOUR_RGB` entries, and per solid the optimal bounding box, volume, face count, `isValid` and the BOP check. `--brief` is one line per file, for scanning a stock KiCad family: `step --brief "C:/Program Files/KiCad/10.0/share/kicad/3dmodels/Capacitor_THT.3dshapes/C_Rect_*.step"`. A basename resolves under `nixie_clock.3dshapes`; globs are expanded. |
| `mesh [--brief] PATH...` | Read STL (or OBJ, PLY, OFF, 3MF) meshes back under freecadcmd: facets, extents, volume; closed, manifold, one orientation, no self-intersections; shell count; and for one closed shell its genus, which is its through-hole count. The check on a board body from kicad-cli or a part meshed for the printer. `--brief` is one line per file. A basename resolves under `fab/<board>/rev*/`; globs are expanded. |
| `wrl PATH` | Read a `.wrl` back through `cad/test_base/vrml.py`: materials by name, counts, extents in mm. A basename is looked up in `nixie_clock.3dshapes`. |
| `parts` | List the part directories under `cad/`, their modules and what they ship. |
| `drawing PDF PAGE [--clip X0 Y0 X1 Y1] [--dpi N] [--words] [--vectors] [--x PX0 PX1 MM] [--y PY0 PY1 MM] [--row MM...] [--col MM...]` | Measure a datasheet drawing. Renders the page, or a clip of it in PDF points (origin top left, 72 per inch), to a PNG under `%TEMP%\fc_tool\` for the Read tool; says whether the clip holds vector paths and text or only a raster; lists the long horizontal and vertical lines in pixels and points; and with `--x`/`--y` (two pixels a known distance apart, 0 mm at their midpoint, `--origin PX PY` to override) scans rows and columns for ink runs and reports them in mm. Needs PyMuPDF and numpy, both in the system Python. |

## Why `run` exists

Bare `freecadcmd script.py` has five behaviors that cost hours on this project:

1. It **imports the script as a module**. `__name__` is the file's stem, so an
   `if __name__ == "__main__":` guard never fires, and a script named like a
   standard-library module (`profile.py`, `imp.py`) is silently shadowed by the
   stdlib and does nothing, with no error.
2. An exception comes back as one line, `Exception while processing file: ...
   [message]`, with no traceback.
3. Any `--option` after the script is rejected by freecadcmd's own parser, and
   `--pass` forwards exactly one token.
4. Three banner lines precede every run, and with the GUI up some 48 kB of Qt
   style-sheet complaints. OCCT's STEP writer adds a statistics block of its
   own in the middle of the script's output.
5. Through a pipe its stdout is cp1252, and the embedded interpreter ignores
   `PYTHONIOENCODING` and `PYTHONDONTWRITEBYTECODE`. A print of any character
   outside that code page (an ohm sign, an arrow, a less-or-equal) raises
   `UnicodeEncodeError`, and the traceback quoting the line dies the same way.

`run` hands the request (script, arguments, GUI flag) to the child through the
`FC_TOOL_REQUEST` environment variable, executes the file in a namespace named
`__main__`, prints tracebacks, puts both ends of the pipe on UTF-8, switches
bytecode writing off (so a build leaves no `__pycache__` in the part
directories), drops the banner, the Qt chatter and the `(N %)` progress that
Mesh's topology checks stream through the C++ console, shows only what the
script itself prints, and returns the script's status. The script's namespace
is not installed as `sys.modules["__main__"]`, on purpose: `FreeCADGuiInit.py`
runs in whatever `__main__` is and expects the `App`, `Log`, `Msg` names that
`FreeCADInit.py` left in the real one, so under `runpy` a script that started
the GUI itself (a module's `_gui()`) failed with `Cannot create main window`
over a `NameError`. Probe scripts still work best when they also write their
findings to a file in the scratchpad, since a long build can be interrupted.

The STEP parts build, report and export in a few seconds. The glass parts are
slow: a full INS-1 build with its report is 30 to 60 s, and anything calling
`distToShape` against the 136-face envelope is 20 s per part. Set a Bash
timeout of several minutes and never poll. `mesh` is quick: a 17,000-facet
board body checks, self-intersections included, in under 0.1 s.

## Where things live

```
cad/kicad_wrl.py              shared VRML writer: mesh(), material(), write()
cad/<part>/<part>.py          the model: constants, geometry, document, build()
cad/in12/export_kicad.py      builds, then kicad_wrl.write()
cad/ins1/export_kicad.py      builds, then its own older copy of that writer
cad/<part>/*.py               supporting data and tools: digits.py, marks.py,
                              shoulder_profile.py, washer.py (the INS-1 grommet)
cad/test_base/                the fixture that holds the three boards; vrml.py reads WRLs
cad/test_base/boards/*.step   kicad-cli exports the fixture places (gitignored;
                              base_plate.export_boards() refreshes stale ones)
cad/test_base/print/*.step    the fixture's printed parts, laid flat by
                              base_plate.export(); STEP so the slicer keeps
                              the hex flats exact
fab/<board>/rev<ID>/<board>-rev<ID>-board.stl
                              the bare board of a tagged export, written by
                              scripts/make_release.py (gitignored; never
                              written by hand)
pcb/lib/nixie_clock.3dshapes/ what KiCad loads
pcb/lib/README.md             provenance of every model; keep it current
```

Two families of part, by what they ship:

| | ships | exporter | why |
|---|---|---|---|
| ins1, in12 | `.wrl` only | `export_kicad.py` (in12 through `kicad_wrl`; ins1 carries its own copy of the same writer) | glass, emissive glow: material properties STEP cannot carry; `test_base` reads the WRL directly |
| ecqe, srn5040 | colored `.step` | module `export()` via `ImportGui` | opaque parts; KiCad's board STEP export picks them up |

A new WRL part goes through `kicad_wrl.write()`; the copy in
`cad/ins1/export_kicad.py` predates the shared module.

Do not ship a STEP twin beside a glass part's WRL. `kicad-cli pcb export step
--subst-models` would substitute it, the part would arrive gray, and
`test_base` (which inserts WRLs itself) would then hold it twice.

## The part-module shape

Every model module follows `cad/ins1/ins1.py` and `cad/in12/in12.py`:

- **Module docstring** states the sources, the frame (axis, origin, what X and
  Y mean), and the build decomposition as a short indented list.
- **Constants block**, one per measured dimension, each with a comment naming
  where the number came from and its tolerance where the drawing gives one
  (`BODY_H = 28.00  # glass, base plane to apex, drawn 28-2`). Derived values
  are computed, never retyped (`RADIUS = BODY_X / 2`). A number on judgment
  says so and says how to pin it down.
- **Geometry functions** returning `Part.Shape`, one per physical piece, named
  for the piece (`glass()`, `pins_solid()`, `cathodes_solid()`).
- **Document section**: `DOC_NAME`, `MANAGED`, `APPEARANCE`, `_material()`,
  `_document()`, `_place()`, `_reconcile()`, `_report()`, `build()`.
- `build(reapply_appearance=False, ...)` updates objects **in place** by
  assigning `.Shape`, so appearance and visibility set in the GUI ride through
  a rebuild. `APPEARANCE` is applied only when an object is first created;
  `reapply_appearance=True` is the explicit override and discards GUI edits.
  `_reconcile` removes only `MANAGED` names this run did not produce, so the
  user can park sketches or an imported reference in the same document.
- `_report()` prints a table of `label / measured / target`. Targets are
  **independent closed forms**: volume from the dimensions, flat-face area as
  a stadium, wall thickness shell to shell, pin ring less the pin diameter.
  A boolean that silently ate something shows up there, where the render
  would hide it.
- Parts stay **separate objects, never fused into each other**: a WRL carries
  one material per shape, and a renderer needs a distinct object to bind a
  material to. Fuse only the pieces of one physical part.
- Supporting modules imported by the model must be `importlib.reload`ed inside
  it, or the user's single reload of the model in the GUI leaves them stale.

The STEP parts (`cad/ecqe/ecqe2104kb.py`, `cad/srn5040/srn5040ta.py`) carry
the same docstring, constants block, geometry functions and `_report()`, and
a shorter document section: a `PARTS = {name: (maker, color)}` table,
`_gui()`, `_document()`, `_show()`, `build()` and `export(path=STEP_PATH)`.
`_gui()` starts FreeCADGui offscreen itself, so the module exports from a bare
`freecadcmd` and from `run` as well as from `export PART`; under `--gui` the
GUI is already up and `_gui()` finds it. Their solids stay disjoint too: the
terminals are cut out of the body rather than overlapped, which is what lets
each carry its own color into the STEP. `_report()` rows are named as the
drawing names them (`L max`, `F`, `od`) so a reader can find each number on
the sheet, and go through `_mm()`, which suppresses the `-0.0000` a boolean
leaves on a face that was at zero.

## Sources of truth, in order

1. The manufacturer drawing (`docs/datasheets/`). The IN-12 pasport has a full
   dimensioned drawing; the INS-1 sheet is electrical only. `kicad-sch pdf`
   finds text in a datasheet; `drawing` measures its figures.
2. The footprint's own hole pattern (`kicad-fp pads`). It independently
   confirmed all five IN-12 pin dimensions to 0.002 mm.
3. Parts in hand, measured or eyeballed, stated as such in the comment.
4. A third-party model, last, and only for regions nothing else covers. Say so
   in the file, credit the source where the derived data lives
   (`shoulder_profile.py`), and never make the build read it: sample once, bake
   the numbers in, and keep the sampler as the only file that touches it.
   Measure it against the drawing before trusting any of it. The old IN-12B.wrl
   was 5.4 mm short with pins on a 1.27 grid; the INS-1 STEP had its mica
   passing through its own glass and its anode shorted to its cathode.

When two sources disagree, the number you cannot measure without destroying the
part (a bore, a wall) is the one to distrust.

**A vendor model can be for the wrong variant.** Panasonic's ECQ-E STEP was a
box 14 mm tall: H max for the crimped-lead form, on a part number whose blank
lead-form position means straight, which stands 9. Decode the part number
against the datasheet's ordering table and read the model with `step` before
trusting it.

**Vendor drawings are not all to scale, view by view.** On the SRN5040TA sheet
the top view scales; the front elevation is drawn at half its labeled height;
and the bottom view is drawn to the terminal, so on the terminal's own 4.2 x
1.3 its body outline reads 4.63 across, the base width, against the 4.95 the
top view gives at the flange. Read a drawing with `drawing`, in three steps:

1. The whole page at 150 dpi with `--words`. Read the PNG for the layout; the
   Read tool's own render of a PDF page is too coarse to read a package
   drawing. When the text is vector, the word list places every dimension
   label in points, which locates each view for a clip.
2. The view clipped at 1200 dpi. A vector drawing lists its lines in points
   under `--vectors`, exact and with no pixel work; a raster one (Toshiba's
   package page) reports zero paths, and the long-line list, body outlines
   and extension lines at 8 px thick, is what there is.
3. `--x PX0 PX1 MM --y PY0 PY1 MM` off two long lines a dimensioned distance
   apart in the same view, then `--row` and `--col` at mm positions inside the
   features (a row through a terminal, a column down the body). Take the run
   midpoints; a line is 0.03 mm wide at that scale. Confirm the scale on a
   second dimension before reading anything undimensioned: a scale off a
   SOT-1118's 2.0 body reproduced its 0.65 pitch, 0.95 land pitch and 0.9 land
   height to 0.005 mm, and on the SRN5040 the second terminal landed 3.714 from
   the first against 3.7 REF. Extension lines cross a scan too; the vector
   list or their length tells them from outline.

Identify an unlabeled view by what it draws against numbers already in hand:
4.2 x 1.3 hatched under a recommended land of 4.2 x 1.5 was the terminal, which
named that view the bottom and put the body's 4.60 at the base rather than at
its widest.

**A catalog render is a source for what nothing dimensions** (the SRN5040
waist and flange thicknesses), measured against a dimensioned feature standing
beside it in the same image. The constants block says so.

**A `max` with no nominal is not drawn.** The ECQ-E's `1.0 max` of epoxy down
the leads can put the seated part at 10.0 rather than the body's 9.0. The
model stands 9.0; the worst case goes in the footprint `descr` and in
`_report()` as a row of its own.

## Modeling conventions

**Build the way the part is made, from exact primitives.** Revolve, extrude,
sweep a disc along a line, cut. A stadium-section body is a capsule of
revolution swept along a line: two capped ends plus the silhouette extruded
between, every face a plane, cylinder, torus or sphere, and the cavity a true
offset. Reach for a loft or a fitted spline only when a primitive cannot
express the shape, and say why in the docstring.

**Intersect the views instead of filleting.** A dipped body (ECQ-E) is the
intersection of its three outlines, each a rounded rectangle extruded along
the axis it is drawn on, every prism run past the other two so no extrusion
end cuts the result. Every face then comes from an outline, so the model
cannot silhouette wrong from any of the three directions, there is no fillet
for OCCT to fail on, and the three corner radii are the only judgment calls.
`rounded_face(corners, radii, into)` in `ecqe2104kb.py` draws such an outline
in any plane and handles a radius large enough that two arcs meet with no
straight between them.

**Fuse across a crease.** A loft through every section rounds a crease off.
The SRN5040 waist is lofted alone, the flanges are prisms off the exact
section wire the loft starts and ends on, and the three are fused; the shared
faces make the fuse clean and the joins sharp.

**One section generator, scaled.** Sections for a loft that are all the same
outline scaled (`section(z)` in `srn5040ta.py`, where the corner radius sweeps
with the width) keep the same edge count and the loft is a taper; sections
built two ways make it a rebuild.

**Pieces meet on faces they share exactly.** The same wire for a pad and the
loft that continues it; `_circle_wire()` (an exact `Part.makeCircle`) where a
loft meets a cylinder, because a spline through points on a circle misses it
by a micron, passes `isValid()`, fails the BOP check, and poisons every
boolean downstream. With shared faces no fuzzy tolerance is needed; a fuzzy
tolerance is **global** and damages geometry far from the join.

**Fold booleans one at a time.** `a.fuse([b, c, d])` returned 1116 mm3 where
sequential fusing gave 714, both reporting valid. Cut the cavity before fusing
small appendages, so the cut only sees what it reaches.

**Guard `removeSplitter`.** It sometimes merges faces it should not and hands
back a solid of three times the volume, still `isValid()`, after running for
minutes. Wrap it: revert if the volume moves more than 1e-6 relative or the
solid count changes, and skip it after the final small fuse.

**Interpolate section splines with uniform `Parameters`** when several feed a
loft. Left to chord length each section gets its own knot vector, the loft
unifies them by knot union, and the skin carries 688,000 poles and a 63 MB
STEP instead of 3,000 poles and 6 MB. Points already spaced by arc length
reproduce to 1e-15 either way.

**Sample sections by arc length.** Narrow features (the INS-1 ribs) occupy a
couple of degrees, and sampling by polar angle loses 0.15 mm off them.
`Wire.discretize(Number=n)` spaces by curvilinear abscissa; drop the repeated
last point.

**Blends are two tangent arcs.** `s_curve_span(v0, v1, r)` fixes the height a
blend of radius `r` needs; `s_curve_radius(delta, span)` is its inverse for a
bend whose ends are both known (a lead wire). A band of any other height is
non-tangent at its ends.

**Hold the ends of a loft.** `makeLoft` uses a free end condition and leaves
its first station on a 12 to 17 degree slope. Repeat the end section a hair
inside (`HOLD = 0.02`) to force it vertical.

**Offset and extrude a flat wire.** A flat wire along a planar path is its
centerline offset both ways in that plane (`makeOffset2D`, or walk the normals
for a closed loop) and extruded; `makePipeShell` + `MakeSolid` fails on every
such path. A round wire does sweep: `path.makePipeShell([circle], True, False)`
with the circle on the spine's start, square to it.

**Author centerlines.** A cathode numeral is a bent wire; a font glyph is a
filled contour, and recovering a centerline from one is lossy. Sample arcs
sparsely (10 points): the swept pipe inherits the poles and the mesher follows
the pipe.

**Nothing inside may reach the bore.** Trim internals to the cavity's actual
section (`_reach`, `_span` in in12.py) rather than drawing them square.
Coincident surfaces z-fight in a renderer; bury one 0.01 into the other.

## FreeCAD and OCCT traps

- `isValid()` lies. Use `shape.check(True)` (the BOP check) as well; a diverged
  loft with a 646 mm bounding box reports valid.
- `Shape.BoundBox` on a spline solid is pole-based and reads wide. Use
  `optimalBoundingBox()` for any dimension you report.
- `Shape.tessellate(tol)` caches its result on the shape and returns the same
  mesh whatever tolerance you pass next. It also takes a linear tolerance
  only, and a spline's triangle count follows its poles rather than its
  curvature (1.6 million triangles on the INS-1). Use `MeshPart.meshFromShape`
  with `LinearDeflection`, `AngularDeflection`, `Relative=False`.
- `Mesh.Mesh((points, facets))` access-violates in FreeCAD 1.1; the
  triangle-list constructor (`Mesh.Mesh([[v0, v1, v2], ...])`) does not. See
  `base_plate.glassware()`.
- `Part.sortEdges` on a slice's wire splits it into chains; `slice()` returns
  wires already ordered, so use `section[0]` directly.
- `makeFillet` will not fillet an edge whose blend changes topology part way
  round (the INS-1 press into its barrel). Parasolid does it in one click; OCCT
  will not at any radius on any edge subset. Measure the source instead.
- Horizontal chord across a curved wall overstates its thickness; measure
  shell to shell or along the normal.
- `Part.BSplineCurve.interpolate` with `PeriodicFlag=True` closes the curve;
  repeating the first point raises `BSplCLib::Interpolate`. With `Parameters`
  given, supply one more parameter than points for a periodic curve.
- `distToShape` against a large spline envelope costs about 20 s per call. For
  a clearance to a cylindrical bore, compute it from the points instead.
- `Part.Ellipse(p_major, p_minor, center)` lands in the plane of its two
  endpoints; `ArcOfEllipse(e, 0, pi/2)` needs no rotation into place.
- Windows paths in Python: `"C:\Code\nixe_clock\...\test_base"` turns `\n`
  into a newline and `\t` into a tab. Use forward slashes. OCC reports the
  result as a bare `Writing of STEP failed`, which reads like a geometry
  problem; `base_plate._writable()` checks a path for this first.
- `Part.Vector` does not exist; it is `FreeCAD.Vector` (`App.Vector`).
- A boolean leaves `-0.0000` and `-5.6e-17` on faces that were at zero. Format
  reported numbers through a helper (`_mm`) rather than `:.4f` directly.
- The BOP check fails on a STEP read back that passed when built. The ECQ-E
  body passes `check(True)` fresh and after every pairwise intersection, and
  fails after a round trip through either STEP writer, `Part.exportStep` or
  `ImportGui.export`, with `BOPAlgo_InvalidCurveOnSurface` on its blend edges;
  `fix()` does not clear it. The file carries no pcurves (zero `PCURVE` and
  `SURFACE_CURVE` entities) and the reader reconstructs them. FreeCAD 1.1.3
  has no switch for this: the `WriteSurfaceCurveMode` key under
  `Mod/Part/General` in user.cfg is read by no FreeCAD binary, and OCCT's
  `write.surfacecurve.mode` is not reachable from Python. `step` reports the
  BOP check on the read-back shape, so judge a model's BOP health in its build
  and the file by `isValid`, solid count, extents and colors.

## Appearance

Appearance lives on `obj.ViewObject.ShapeAppearance`, a **tuple** of
`App.Material` (diffuse, specular, emissive, ambient, shininess,
transparency). The physical Material library (density, FEM) is a different
thing and does nothing for rendering. `Material.Transparency` is a 0-1 float;
`ViewObject.Transparency` is a 0-100 int; they shadow each other, so every
part module uses the fraction throughout. `Material.set("Glass")` is not a
valid preset name and silently leaves the default.

Headless, `ViewObject` is `None`; `_place` checks for that. `Import.export`
(headless) writes an uncolored STEP. Colored STEP needs `ImportGui`, which
needs `FreeCADGui.showMainWindow()` under `QT_QPA_PLATFORM=offscreen`;
`setupWithoutGUI()` attaches no view providers. `run --gui` does this.

STEP parts color through `ViewObject.ShapeColor`, one per object, which is
why each physical piece is its own object. One face of a different color (the
ground ferrite face on top of the SRN5040) is `ViewObject.DiffuseColor` set to
a per-face list, found by surface type and position (`_top_faces`). ImportGui
writes each as its own `COLOUR_RGB`; `step` lists them back, and KiCad's
raytracer and board STEP export both honor per-face color. Lead and terminal
color is the stock KiCad tinned gray, `(0.824, 0.820, 0.781)`.

Starting values that render well in KiCad, taken from the vendor IN-12B.wrl's
`GLASS2` (deleted in 69275d5) and now held in `in12.APPEARANCE["Glass"]`:
diffuse and specular white, ambient white, shininess 0.03 (a broad highlight;
the glassiness comes from transparency 0.75 to 0.78 and full white specular).
`emissiveColor` is flat self-illumination and is how a lit cathode reads as
lit; KiCad's raytracer does not cast it onto neighbors. Tune in the GUI
(right-click, Appearance), then read `ShapeAppearance[0]` back into
`APPEARANCE`.

## KiCad export

`cad/kicad_wrl.py` writes VRML in **0.1 inch units** (KiCad's convention:
divide mm by 2.54), one `DEF <Name> Transform` per part, materials **DEF'd by
part name**. `cad/test_base/vrml.py` keys materials off that DEF and reads an
anonymous one as default gray, collapsing every part into one; `wrl` warns
when it sees that. Write opaque parts first and glass last so a renderer
blending transparency has what is behind the glass already drawn.

Per-vertex normals are averaged only across facets within `CREASE` (30
degrees), so tangent surfaces show no seam while rims stay hard; they are
pooled because most repeat. Per-part deflection (`FINE` in
in12/export_kicad.py) keeps 0.16 mm wire from costing 146,000 triangles.

A re-export is not byte-stable: the same sources give the same groups,
counts and extents but differ in the last decimal of a couple of thousand
coordinates, and git treats `.wrl` as binary. Judge a regenerated model by
`wrl` output against the committed file, and do not commit a re-export whose
`wrl` summary is unchanged.

A model authored Z-up with its origin at the board plane needs `rotate 0 0 0`
and `offset 0 0 0` in the footprint; a recessed variant carries the board
height with the sign flipped (`0 0 -9.74`). Lead trim is per footprint: on the
recessed INS-1 the glass itself passes the slot and the leads leave the press
already 3.5 mm behind the board, so "2 mm below the board" describes nothing;
the trim leaves visible wire past the press and stays shallower than the pip
at z = 0, which is what sets the clearance behind the board.

`base_plate.py` places WRLs from its `GLASSWARE` table: path, the footprint's
model offset as written, and `(reference, x, z)` derived from the board
placement as `x = boardX - originX`, `z = originY - boardY`. Verify a placement
by checking one reference lands on the board's known center. The boards
themselves come from `kicad-cli pcb export step --force --no-dnp
--no-unspecified --subst-models --user-origin=<cx>x<cy>mm` (`135x87.5mm`),
which `base_plate.export_boards()` reruns whenever a `.kicad_pcb` is newer
than its STEP; `_centred()` warns when an export was not taken about the
board's center, which no clearance figure would otherwise catch.

### Board bodies

`kicad-cli pcb export step --board-only` (or `stl`) writes the bare board:
outline, slots, every pad drill and NPTH cut, one solid, no components. With
the same `--user-origin` as the populated export it lands in the fixture's
frame, so it serves as a boolean tool against a printed part or as a print of
its own. The frame is KiCad's X, Y negated, Z up from the board's underside.

The body is the dielectric core alone and reads 1.510 thick. The stackup is
1.6 (0.010 mask, 0.035 copper, 1.510 core, 0.035, 0.010); `PCB_T` in
`base_plate.py` carries that number, and the export is not evidence of it.
`--include-tracks --include-pads --include-zones --include-soldermask
--include-silkscreen` add the layers as thin solids and flat faces, at ten
times the file size, for features no printer resolves. Vias stay closed
unless `--cut-vias-in-body` is given, which suits a print: 0.3 mm holes come
out as blemishes.

kicad-cli 10 writes the STL as ASCII (`solid` header), 1.5 to 4.5 MB per
board here; `Mesh.Mesh` reads it. Check it with `mesh`: closed, manifold, one
shell, genus equal to the through-hole count, which the drill file or
`kicad-fp pads` gives independently. The STEP form reads back with `step` as
one valid, BOP-clean solid carrying the mask color. The populated exports
are 2 to 8 MB with every component in them; `--brief` those.

`scripts/make_release.py` writes `<board>-rev<REV><STEP>-board.stl` beside
`erc.rpt` in every release directory, so the printable board of a tagged
export is already there. Regenerate it by rerunning the release; nothing is
written into `fab/` by hand.

The fixture's own parts leave as STEP (`base_plate.export()`): slicers take
STEP directly and it keeps the hex flats exact. Mesh a part only when a mesh
is the deliverable, through `MeshPart.meshFromShape` with explicit
deflections, and read it back with `mesh` before it goes anywhere.

### STEP parts

A THT model follows the stock library's frame: origin on pad 1, +X toward pad
2, Z = 0 the board top, so a centered body is placed by `offset (-pitch/2 0 0)`
and nothing else. An SMD model sits on the footprint origin with `offset 0 0
0`. Leads end where the stock family the footprint would otherwise use ends
them, read with `step --brief` on that family: every `C_Rect_*` stops at Z =
-1.9, `R_Axial_*` at -3.0, `CP_Radial_*` at -2.0. Read the family's number
rather than reusing one.

Replacing a vendor model resets the frame. Panasonic's ECQ-E started 0.1 above
its own origin and the footprint lifted it a further 0.5; the redraw puts Z =
0 on the board and the offset went to 0. The `.kicad_pcb` carries its own copy
of every placed footprint with its own `model` path, `offset` and `descr`, so
the same edit goes there, and a grep for the old text is what confirms it.

A STEP re-export is not byte-stable either: the `FILE_NAME` timestamp moves,
and the styling entities at the end come out in a different order with
different numbers from one run to the next. `export` compares the two files
with the timestamp removed, entity numbers stripped and entities sorted, and
keeps the previous file when geometry and color match, so a regenerated STEP
that shows in `git status` has really changed. Do the same by hand before
committing one regenerated any other way.

## GUI workflow for the user

The user drives FreeCAD by macro; supply this shape, forward slashes, reload:

```python
import importlib, sys
SRC = "C:/Code/nixe_clock/cad/in12"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import in12
importlib.reload(in12)
in12.build()
```

Autocomplete comes from `.typings` (freecad-stubs) plus the FreeCAD `bin`,
`lib`, `Mod` paths in `.vscode/settings.json`. Sketcher advice given on this
project: center a rectangle with Symmetric on two diagonal corners about the
origin (a snapped corner is Coincident and not centered); fillet rectangle
corners on the solid rather than in the sketch, since the sketch fillet
deletes the corner and its constraints; prefer expressions off named
constraints to external geometry for offsets from a centered feature.

## Verification checklist for a new or changed part

1. `_report()` targets all hit: one solid, valid, BOP clean, closed-form volume,
   every drawn dimension, ring pitches less the wire diameter.
2. Section against its ideal (`slice` at a height, `discretize`, compare to
   the stadium or circle) reads 0.000000.
3. Wall shell to shell equals `WALL`.
4. Nothing inside reaches the bore; nothing outside pokes through the seal
   (`wires.cut(outer_glass())` leaves exactly the exposed leads).
5. `export PART`, then `wrl` or `step` on the output: one named material or
   one colored solid per part, extents equal to the drawing, z range equal to
   the footprint's expectation (lead tips at the stock family's trim).
6. `pcb/lib/README.md` names the new file and its provenance; no stale model
   path, `offset` or `descr` remains (`grep` the `.kicad_mod`, `.kicad_pcb`,
   `.kicad_sym`, `.kicad_sch`; the board carries its own copy of the footprint).
7. A board body or a print mesh: `mesh` reads closed, manifold, one shell,
   genus equal to the hole count.
