---
name: kicad-fp
description: Analyze this repo's KiCad footprints and board — pad tables with drill/size details, layer extents, footprint-vs-footprint diffs, symbol-pin-vs-pad cross-checks, board footprint listing, and DRC. Use for any footprint geometry or land-pattern verification question instead of ad-hoc shell pipelines.
---

# KiCad footprint analysis

All operations go through one script so a single Bash permission rule covers them:

```
python .claude/skills/kicad-fp/scripts/fp_tool.py <subcommand> [args]
```

Always invoke it exactly like that, relative to the repo root, so the
allowlist rule matches. The script is read-only with respect to the project;
the DRC report is cached under the system temp directory. Footprint and symbol
libraries are autodetected from project `fp-lib-table` / `sym-lib-table` files
(with `${KIPRJMOD}` expansion) plus any loose `.pretty` dirs or `.kicad_sym`
files in the repo. The board is autodetected (the `.kicad_pcb` with a
`.kicad_pro` sibling); override with `--pcb <path>` placed *before* the
subcommand.

`FP` and `SYM` arguments accept `libname:partname`, a bare part name (searched
across all libraries, errors if ambiguous), or — for footprints — a direct
path to a `.kicad_mod` file (useful for comparing against un-imported
upstream libraries outside the repo).

## Subcommands

| Command | Purpose |
|---|---|
| `libs` | List footprint libraries visible to the repo, with footprint counts |
| `list [LIB]` | List footprints: pad counts by type (th/smd/npth) and description |
| `pads FP` | Full pad table: name, type, shape, position, rotation, size, drill, layers; plus a drill-size summary |
| `extents FP` | Bounding box per layer group (copper, courtyard, silk, fab, edge) and overall size — for spacing/clearance planning |
| `compare FP1 FP2` | Pad-level diff: added/removed pads and per-field changes (position, size, drill, …) |
| `symcheck SYM FP` | Cross-check a symbol's pin numbers against a footprint's pad names; flags pins without pads and vice versa |
| `board` | List footprints placed on the PCB: ref, footprint ID, position, layer |
| `drc` | Run KiCad DRC (including unconnected items and schematic parity), print all violations |
| `netlen [PAT...]` | Per-net routed copper length (segments + true arc lengths), widths, layers, item count; optional net-name regex filters, sorted longest-first |
| `vias [PAT...] [--bbox X1 Y1 X2 Y2]` | List vias with position, size/drill, net name, and free-via flag; filter by net regex and/or region |
| `tracks [PAT...] [--bbox X1 Y1 X2 Y2] [--layer L]` | List individual track segments/arcs: layer, endpoints, width, length, net — for congestion and plane-cut analysis |
| `zones` | List all zones: net, layer, priority, polygon bbox, keepout rule flags, teardrop names |

## Typical workflows

- **Vet an imported footprint**: `pads nixie_clock:IN-12-DSUB` for hole sizes,
  then `extents` for the physical envelope before placing parts.
- **Verify a symbol/footprint pairing**: `symcheck nixie_clock:IN-12B nixie_clock:IN-12-DSUB` —
  run this whenever a new symbol or footprint enters the vendored library.
- **Check a footprint edit or variant**: `compare nixie_clock:IN-12-DSUB path/to/upstream.kicad_mod`.
- **Tube spacing / board planning**: `extents` on each footprint gives
  courtyard and copper envelopes; digit pitch must exceed the wider of the two.
- **After layout edits**: `board` to confirm what is actually placed, `drc`
  for violations.
- **Layout review**: `netlen 'V_\{SW\}' GATE CS` to audit critical-net lengths
  and widths; `vias GND --bbox ...` to audit ground stitching in a region;
  `zones` to verify keepouts and find teardrop zones. Prefer these over ad-hoc
  Python parsing of the .kicad_pcb.

## Notes

- All dimensions are millimeters. Extents treat arcs as their
  start/mid/end points and arbitrary pad rotations as worst-case envelopes —
  fine for planning, not for gerber-exact outlines.
- Unnamed pads (e.g. the IN-12 base's 5 mm locating hole) are mechanical:
  `symcheck` ignores them, `pads` prints them as `""`.
- `compare` matches pads by name; duplicate names (stacked/thermal pads) pair
  off in position order.
- kicad-cli (needed only for `drc`) is autodetected from PATH or
  `C:\Program Files\KiCad\<ver>\bin`; override with the `KICAD_CLI` env var.
