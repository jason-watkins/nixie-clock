#!/usr/bin/env python3
"""KiCad footprint analysis helper for this repo.

All read-only with respect to the project: outputs (DRC report) go to a cache
folder under the system temp directory.

Subcommands:
  libs                     list footprint libraries visible to this repo
  list [LIB]               list footprints (pad counts, description)
  pads FP                  pad table for one footprint
  extents FP               bounding boxes per layer group (copper, courtyard, silk, fab)
  compare FP1 FP2          pad-level diff between two footprints
  symcheck SYM FP          cross-check symbol pin numbers vs footprint pad names
  board                    list footprints placed on the .kicad_pcb
  drc                      run KiCad DRC on the board, print all violations
  netlen [PAT...]          per-net copper length (segments + true arc lengths),
                           widths, layers; filter by net-name regexes
  vias [PAT...] [--bbox]   list vias with net names and free flag
  zones                    list zones: net, layer, priority, bbox, keepout rules,
                           teardrop names

FP/SYM are "libname:partname", a bare part name (searched across libraries),
or a path to a .kicad_mod file. Libraries are found via project fp-lib-table /
sym-lib-table files plus any loose .pretty / .kicad_sym under the repo.
"""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


# ---------- s-expression parsing ----------

def parse_sexpr(text):
    i, n = 0, len(text)
    stack = [[]]
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            stack[-1].append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            stack[-1].append(text[i:j])
            i = j
    if len(stack) != 1 or not stack[0]:
        sys.exit("malformed s-expression input")
    return stack[0][0]


def kids(node, tag):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def kid(node, tag):
    k = kids(node, tag)
    return k[0] if k else None


def kidval(node, tag, default=""):
    k = kid(node, tag)
    return k[1] if k and len(k) > 1 else default


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]


# ---------- library discovery ----------

def _iter_files(pattern):
    for p in Path(".").glob(pattern):
        if "backups" not in p.parts and not p.name.startswith("~"):
            yield p


def discover_libs(table_name, table_tag, loose_glob, want_dir):
    libs = {}
    for table in _iter_files(f"**/{table_name}"):
        try:
            root = parse_sexpr(table.read_text(encoding="utf-8"))
        except Exception:
            continue
        if root[0] != table_tag:
            continue
        for lib in kids(root, "lib"):
            name, uri = kidval(lib, "name"), kidval(lib, "uri")
            uri = uri.replace("${KIPRJMOD}", str(table.parent.resolve()))
            p = Path(uri)
            if (p.is_dir() if want_dir else p.is_file()):
                libs.setdefault(name, p)
    for p in _iter_files(loose_glob):
        if (p.is_dir() if want_dir else p.is_file()):
            libs.setdefault(p.stem, p)
    return libs


def fp_libs():
    return discover_libs("fp-lib-table", "fp_lib_table", "**/*.pretty", True)


def sym_libs():
    return discover_libs("sym-lib-table", "sym_lib_table", "**/*.kicad_sym", False)


def resolve_fp(spec):
    """Return (display_name, parsed footprint node)."""
    if spec.lower().endswith(".kicad_mod"):
        p = Path(spec)
        if not p.is_file():
            sys.exit(f"footprint file not found: {p}")
        return p.stem, parse_sexpr(p.read_text(encoding="utf-8"))
    libs = fp_libs()
    if ":" in spec:
        libname, part = spec.split(":", 1)
        if libname not in libs:
            sys.exit(f"unknown footprint library {libname!r}; have: {', '.join(sorted(libs)) or '(none)'}")
        p = libs[libname] / f"{part}.kicad_mod"
        if not p.is_file():
            sys.exit(f"footprint {part!r} not in {libname} ({libs[libname]})")
        return spec, parse_sexpr(p.read_text(encoding="utf-8"))
    hits = [(name, d / f"{spec}.kicad_mod") for name, d in libs.items()
            if (d / f"{spec}.kicad_mod").is_file()]
    if not hits:
        sys.exit(f"footprint {spec!r} not found in any library")
    if len(hits) > 1:
        sys.exit(f"ambiguous footprint {spec!r}: " + ", ".join(f"{n}:{spec}" for n, _ in hits))
    return f"{hits[0][0]}:{spec}", parse_sexpr(hits[0][1].read_text(encoding="utf-8"))


# ---------- pad extraction ----------

def pad_info(p):
    at = kid(p, "at") or ["at", "0", "0"]
    size = kid(p, "size") or ["size", "0", "0"]
    drill = kid(p, "drill")
    dstr = ""
    if drill:
        vals = [t for t in drill[1:] if not isinstance(t, list)]
        if vals and vals[0] == "oval":
            dstr = f"oval {vals[1]}x{vals[2]}"
        elif vals:
            dstr = vals[0]
    layers = kid(p, "layers")
    return {
        "name": p[1] if len(p) > 1 else "",
        "type": p[2] if len(p) > 2 else "",
        "shape": p[3] if len(p) > 3 else "",
        "x": float(at[1]), "y": float(at[2]),
        "rot": float(at[3]) if len(at) > 3 else 0.0,
        "sx": float(size[1]), "sy": float(size[2]),
        "drill": dstr,
        "layers": " ".join(layers[1:]) if layers else "",
    }


def fp_pads(root):
    return [pad_info(p) for p in kids(root, "pad")]


# ---------- subcommands ----------

def cmd_libs(args):
    for name, path in sorted(fp_libs().items()):
        n = len(list(path.glob("*.kicad_mod")))
        print(f"{name:24} {n:4} footprints  {path}")


def cmd_list(args):
    libs = fp_libs()
    if args.lib:
        if args.lib not in libs:
            sys.exit(f"unknown library {args.lib!r}; have: {', '.join(sorted(libs)) or '(none)'}")
        libs = {args.lib: libs[args.lib]}
    for name, path in sorted(libs.items()):
        for f in sorted(path.glob("*.kicad_mod"), key=lambda p: natkey(p.stem)):
            root = parse_sexpr(f.read_text(encoding="utf-8"))
            pads = fp_pads(root)
            th = sum(1 for p in pads if p["type"] == "thru_hole")
            smd = sum(1 for p in pads if p["type"] == "smd")
            npth = sum(1 for p in pads if p["type"] == "np_thru_hole")
            descr = kidval(root, "descr")
            print(f"{name}:{f.stem:24} {len(pads):3} pads ({th} th, {smd} smd, {npth} npth)  {descr}")


def cmd_pads(args):
    disp, root = resolve_fp(args.fp)
    pads = fp_pads(root)
    print(f"{disp}  ({len(pads)} pads, units mm)")
    print(f"  {'pad':>6}  {'type':12} {'shape':10} {'x':>8} {'y':>8} {'rot':>5} {'size':>13} {'drill':>10}  layers")
    for p in sorted(pads, key=lambda p: (p["name"] == "", natkey(p["name"]), p["x"], p["y"])):
        size = f"{p['sx']:g}x{p['sy']:g}"
        name = p["name"] or '""'
        print(f"  {name:>6}  {p['type']:12} {p['shape']:10} {p['x']:8.3f} {p['y']:8.3f} {p['rot']:5g} {size:>13} {p['drill']:>10}  {p['layers']}")
    drills = sorted({p["drill"] for p in pads if p["drill"]}, key=natkey)
    if drills:
        print("  drill sizes:", ", ".join(drills))


LAYER_GROUPS = [("copper", ".Cu"), ("courtyard", "CrtYd"), ("silk", "SilkS"),
                ("fab", "Fab"), ("edge", "Edge.Cuts")]


def _group_of(layer_str):
    for gname, frag in LAYER_GROUPS:
        if frag in layer_str:
            return gname
    return "other"


def _item_points(item):
    tag = item[0]
    if tag in ("fp_line", "fp_rect"):
        s, e = kid(item, "start"), kid(item, "end")
        return [(float(s[1]), float(s[2])), (float(e[1]), float(e[2]))]
    if tag == "fp_circle":
        c, e = kid(item, "center"), kid(item, "end")
        cx, cy = float(c[1]), float(c[2])
        r = math.dist((cx, cy), (float(e[1]), float(e[2])))
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if tag == "fp_arc":
        return [(float(k[1]), float(k[2]))
                for k in (kid(item, "start"), kid(item, "mid"), kid(item, "end")) if k]
    if tag == "fp_poly":
        pts = kid(item, "pts")
        return [(float(xy[1]), float(xy[2])) for xy in kids(pts, "xy")] if pts else []
    return []


def cmd_extents(args):
    disp, root = resolve_fp(args.fp)
    boxes = {}

    def grow(group, x0, y0, x1, y1):
        b = boxes.get(group)
        boxes[group] = (min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3])) if b \
            else (x0, y0, x1, y1)

    for item in root[1:]:
        if not isinstance(item, list):
            continue
        if item[0] == "pad":
            p = pad_info(item)
            sx, sy = (p["sy"], p["sx"]) if p["rot"] % 180 == 90 else (p["sx"], p["sy"])
            if p["rot"] % 90 != 0:  # arbitrary angle: use worst-case envelope
                sx = sy = math.hypot(p["sx"], p["sy"])
            grow("copper", p["x"] - sx / 2, p["y"] - sy / 2, p["x"] + sx / 2, p["y"] + sy / 2)
            continue
        pts = _item_points(item)
        if not pts:
            continue
        layer = kidval(item, "layer") or " ".join((kid(item, "layers") or [""])[1:])
        stroke = kid(item, "stroke")
        w = float(kidval(stroke, "width", "0")) if stroke else float(kidval(item, "width", "0"))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        grow(_group_of(layer), min(xs) - w / 2, min(ys) - w / 2, max(xs) + w / 2, max(ys) + w / 2)

    print(f"{disp}  (units mm; arcs approximated by start/mid/end)")
    allb = None
    for group, b in sorted(boxes.items()):
        print(f"  {group:10} x [{b[0]:8.3f} .. {b[2]:8.3f}]  y [{b[1]:8.3f} .. {b[3]:8.3f}]  "
              f"{b[2] - b[0]:.3f} x {b[3] - b[1]:.3f}")
        allb = (min(allb[0], b[0]), min(allb[1], b[1]), max(allb[2], b[2]), max(allb[3], b[3])) \
            if allb else b
    if allb:
        print(f"  {'overall':10} {allb[2] - allb[0]:.3f} x {allb[3] - allb[1]:.3f}")


def cmd_compare(args):
    disp1, root1 = resolve_fp(args.fp1)
    disp2, root2 = resolve_fp(args.fp2)

    def by_name(pads):
        d = {}
        for p in pads:
            d.setdefault(p["name"], []).append(p)
        for v in d.values():
            v.sort(key=lambda p: (p["x"], p["y"]))
        return d

    a, b = by_name(fp_pads(root1)), by_name(fp_pads(root2))
    fields = ["type", "shape", "x", "y", "rot", "sx", "sy", "drill", "layers"]
    same = True
    for name in sorted(set(a) | set(b), key=natkey):
        pa, pb = a.get(name, []), b.get(name, [])
        for i in range(max(len(pa), len(pb))):
            label = f"pad {name or chr(34) * 2}" + (f"#{i + 1}" if max(len(pa), len(pb)) > 1 else "")
            if i >= len(pa):
                print(f"only in {disp2}: {label}")
                same = False
            elif i >= len(pb):
                print(f"only in {disp1}: {label}")
                same = False
            else:
                diffs = [f"{f}: {pa[i][f]!r} -> {pb[i][f]!r}" for f in fields if pa[i][f] != pb[i][f]]
                if diffs:
                    print(f"{label}: " + "; ".join(diffs))
                    same = False
    if same:
        print(f"pads identical between {disp1} and {disp2}")


def collect_pin_numbers(node, out):
    for c in node[1:]:
        if isinstance(c, list):
            if c[0] == "pin":
                out.append(kidval(c, "number"))
            else:
                collect_pin_numbers(c, out)
    return out


def cmd_symcheck(args):
    libs = sym_libs()
    spec = args.sym
    if ":" in spec:
        libname, part = spec.split(":", 1)
        if libname not in libs:
            sys.exit(f"unknown symbol library {libname!r}; have: {', '.join(sorted(libs)) or '(none)'}")
        paths = [libs[libname]]
    else:
        part, paths = spec, list(libs.values())
    sym = None
    for path in paths:
        root = parse_sexpr(path.read_text(encoding="utf-8"))
        for s in kids(root, "symbol"):
            if s[1] == part:
                sym = s
                break
        if sym:
            break
    if not sym:
        sys.exit(f"symbol {part!r} not found")
    pins = collect_pin_numbers(sym, [])
    disp, root = resolve_fp(args.fp)
    pads = fp_pads(root)
    padnames = {p["name"] for p in pads if p["name"]}
    mech = [p for p in pads if not p["name"]]
    print(f"symbol {part}: {len(pins)} pins; footprint {disp}: {len(pads)} pads"
          + (f" ({len(mech)} unnamed/mechanical)" if mech else ""))
    missing_pads = sorted(set(pins) - padnames, key=natkey)
    missing_pins = sorted(padnames - set(pins), key=natkey)
    dup = sorted(n for n in set(pins) if pins.count(n) > 1)
    for n in missing_pads:
        print(f"  pin {n}: NO matching pad")
    for n in missing_pins:
        print(f"  pad {n}: no matching symbol pin")
    if dup:
        print(f"  note: duplicated pin numbers in symbol (multi-unit/stacked): {', '.join(dup)}")
    if not missing_pads and not missing_pins:
        print("  OK: every pin has a pad and vice versa")


def find_pcb(arg):
    if arg:
        p = Path(arg)
        if not p.is_file():
            sys.exit(f"board not found: {p}")
        return p
    cands = [c for c in _iter_files("**/*.kicad_pcb")]
    if not cands:
        sys.exit("no .kicad_pcb found under current directory")
    for c in cands:
        if c.with_suffix(".kicad_pro").exists():
            return c
    return cands[0]


def cmd_board(args):
    root = parse_sexpr(find_pcb(args.pcb).read_text(encoding="utf-8"))
    fps = kids(root, "footprint")
    if not fps:
        print("no footprints on board")
        return
    rows = []
    for fp in fps:
        ref = ""
        for prop in kids(fp, "property"):
            if len(prop) > 2 and prop[1] == "Reference":
                ref = prop[2]
        if not ref:
            for t in kids(fp, "fp_text"):
                if len(t) > 2 and t[1] == "reference":
                    ref = t[2]
        at = kid(fp, "at") or ["at", "?", "?"]
        rot = at[3] if len(at) > 3 else "0"
        rows.append((ref, fp[1], f"({at[1]}, {at[2]}) rot {rot}", kidval(fp, "layer")))
    for ref, fpid, pos, layer in sorted(rows, key=lambda r: natkey(r[0])):
        print(f"{ref:8} {fpid:36} {pos:28} {layer}")


def _net_table(root):
    nets = {}
    for n in kids(root, "net"):
        if len(n) >= 3:
            nets[str(n[1])] = str(n[2])
    return nets


def _arc_length(x1, y1, xm, ym, x2, y2):
    d = 2 * (x1 * (ym - y2) + xm * (y2 - y1) + x2 * (y1 - ym))
    if abs(d) < 1e-9:
        return math.hypot(x2 - x1, y2 - y1)
    q1 = x1 * x1 + y1 * y1
    qm = xm * xm + ym * ym
    q2 = x2 * x2 + y2 * y2
    ux = (q1 * (ym - y2) + qm * (y2 - y1) + q2 * (y1 - ym)) / d
    uy = (q1 * (x2 - xm) + qm * (x1 - x2) + q2 * (xm - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1 = math.atan2(y1 - uy, x1 - ux)
    am = math.atan2(ym - uy, xm - ux)
    a2 = math.atan2(y2 - uy, x2 - ux)
    sweep = (a2 - a1) % (2 * math.pi)
    if (am - a1) % (2 * math.pi) > sweep:
        sweep = 2 * math.pi - sweep
    return r * sweep


def cmd_netlen(args):
    root = parse_sexpr(find_pcb(args.pcb).read_text(encoding="utf-8"))
    nets = _net_table(root)
    pats = [re.compile(p) for p in args.patterns] if args.patterns else None
    stats = {}
    for tag in ("segment", "arc"):
        for s in kids(root, tag):
            name = nets.get(kidval(s, "net"), "?")
            if pats and not any(p.search(name) for p in pats):
                continue
            st, en = kid(s, "start"), kid(s, "end")
            x1, y1, x2, y2 = float(st[1]), float(st[2]), float(en[1]), float(en[2])
            if tag == "arc":
                m = kid(s, "mid")
                ln = _arc_length(x1, y1, float(m[1]), float(m[2]), x2, y2)
            else:
                ln = math.hypot(x2 - x1, y2 - y1)
            e = stats.setdefault(name, [0.0, set(), set(), 0])
            e[0] += ln
            e[1].add(kidval(s, "width"))
            e[2].add(kidval(s, "layer"))
            e[3] += 1
    if not stats:
        print("no matching tracks")
        return
    for name, (ln, ws, ls, n) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
        print(f"{name:40s} {ln:8.1f} mm  items={n:3d}  "
              f"w={sorted(ws, key=float)}  {sorted(ls)}")


def cmd_vias(args):
    root = parse_sexpr(find_pcb(args.pcb).read_text(encoding="utf-8"))
    nets = _net_table(root)
    pats = [re.compile(p) for p in args.patterns] if args.patterns else None
    count = 0
    for v in kids(root, "via"):
        at = kid(v, "at")
        x, y = float(at[1]), float(at[2])
        if args.bbox:
            x1, y1, x2, y2 = args.bbox
            if not (min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)):
                continue
        name = nets.get(kidval(v, "net"), "?")
        if pats and not any(p.search(name) for p in pats):
            continue
        free = "  free" if kid(v, "free") else ""
        count += 1
        print(f"({x:8.2f}, {y:8.2f})  {kidval(v, 'size')}/{kidval(v, 'drill')}  "
              f"{name}{free}")
    print(f"-- {count} via(s)")


def cmd_zones(args):
    root = parse_sexpr(find_pcb(args.pcb).read_text(encoding="utf-8"))
    for z in kids(root, "zone"):
        name = kidval(z, "net_name")
        tname = kidval(z, "name")
        layers = kid(z, "layers") or kid(z, "layer")
        lay = " ".join(str(t) for t in layers[1:]) if layers else "?"
        prio = kidval(z, "priority", "-")
        ko = kid(z, "keepout")
        kostr = ""
        if ko:
            rules = [f"{t[0]}={t[1]}" for t in ko[1:] if isinstance(t, list) and len(t) > 1]
            kostr = "  KEEPOUT[" + " ".join(rules) + "]"
        xs, ys = [], []
        poly = kid(z, "polygon")
        if poly:
            pts = kid(poly, "pts")
            for xy in kids(pts, "xy") if pts else []:
                xs.append(float(xy[1]))
                ys.append(float(xy[2]))
        bbox = (f"x[{min(xs):.1f}..{max(xs):.1f}] y[{min(ys):.1f}..{max(ys):.1f}]"
                if xs else "?")
        extra = f" name='{tname}'" if tname else ""
        print(f"net='{name}' layer={lay} prio={prio} {bbox}{extra}{kostr}")


def find_kicad_cli():
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    found = shutil.which("kicad-cli")
    if found:
        return found
    base = Path(r"C:\Program Files\KiCad")
    if base.is_dir():
        for ver in sorted(base.iterdir(), reverse=True):
            cli = ver / "bin" / "kicad-cli.exe"
            if cli.is_file():
                return str(cli)
    sys.exit("kicad-cli not found: install KiCad or set KICAD_CLI")


def cmd_drc(args):
    pcb = find_pcb(args.pcb)
    tag = hashlib.md5(str(pcb.resolve()).lower().encode()).hexdigest()[:10]
    d = Path(tempfile.gettempdir()) / "kicad_fp_analysis" / tag
    d.mkdir(parents=True, exist_ok=True)
    out = d / "drc.json"
    if out.exists():
        out.unlink()
    proc = subprocess.run(
        [find_kicad_cli(), "pcb", "drc", "--format", "json",
         "--severity-all", "-o", str(out), str(pcb)],
        capture_output=True, text=True)
    if not out.exists():
        sys.exit(proc.stderr.strip() or proc.stdout.strip() or "kicad-cli drc failed")
    data = json.loads(out.read_text(encoding="utf-8"))
    total = 0
    for section in ("violations", "unconnected_items", "schematic_parity"):
        for v in data.get(section, []):
            total += 1
            items = "; ".join(i.get("description", "") for i in v.get("items", []))
            print(f"[{v.get('severity')}] {v.get('type')}: {v.get('description')} || {items}")
    print(f"-- {total} violation(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcb", help="path to .kicad_pcb (default: autodetect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("libs").set_defaults(func=cmd_libs)

    p = sub.add_parser("list")
    p.add_argument("lib", nargs="?", help="library nickname (default: all)")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("pads")
    p.add_argument("fp", help="footprint: lib:name, bare name, or .kicad_mod path")
    p.set_defaults(func=cmd_pads)

    p = sub.add_parser("extents")
    p.add_argument("fp")
    p.set_defaults(func=cmd_extents)

    p = sub.add_parser("compare")
    p.add_argument("fp1")
    p.add_argument("fp2")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("symcheck")
    p.add_argument("sym", help="symbol: lib:name or bare name")
    p.add_argument("fp", help="footprint: lib:name, bare name, or .kicad_mod path")
    p.set_defaults(func=cmd_symcheck)

    sub.add_parser("board").set_defaults(func=cmd_board)
    sub.add_parser("drc").set_defaults(func=cmd_drc)

    p = sub.add_parser("netlen")
    p.add_argument("patterns", nargs="*", help="net-name regexes (default: all)")
    p.set_defaults(func=cmd_netlen)

    p = sub.add_parser("vias")
    p.add_argument("patterns", nargs="*", help="net-name regexes (default: all)")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("X1", "Y1", "X2", "Y2"),
                   help="only vias inside this rectangle (mm)")
    p.set_defaults(func=cmd_vias)

    sub.add_parser("zones").set_defaults(func=cmd_zones)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
