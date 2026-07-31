#!/usr/bin/env python3
"""KiCad schematic analysis helper for this repo.

All read-only with respect to the project: outputs (netlist XML, ERC report,
extracted PDF text) go to a cache folder under the system temp directory.

Subcommands:
  components            list components (ref, value, part, footprint)
  nets [REGEX ...]      print nets with pin-level nodes; filter by net-name regex
  refs REF [REF ...]    print every net touching any of the given refs
  pins REF              pin table (number, name, type) for one component
  erc                   run ERC, print all violations
  diff                  net-level changes since the previous netlist export
  pdf FILE KW [KW ...]  search a PDF's text, print context around each keyword

Every netlist-based command re-exports the netlist first, so results always
reflect the saved schematic. Use --sch to override schematic autodetection.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _version_key(path):
    """Numeric sort key for install directories named like '10.0' or '9.0'.

    Sorting these as strings puts '9.0' above '10.0', which picks an older
    CLI than the one installed and then fails to read files written by the
    newer one. Non-numeric components sort last."""
    return [int(part) if part.isdigit() else -1 for part in path.name.split(".")]


def find_kicad_cli():
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    base = Path(r"C:\Program Files\KiCad")
    if base.is_dir():
        installs = [p for p in base.iterdir() if p.is_dir()]
        for ver in sorted(installs, key=_version_key, reverse=True):
            cli = ver / "bin" / "kicad-cli.exe"
            if cli.is_file():
                return str(cli)
    found = shutil.which("kicad-cli")
    if found:
        return found
    sys.exit("kicad-cli not found: install KiCad or set KICAD_CLI")


def find_sch(arg):
    if arg:
        p = Path(arg)
        if not p.is_file():
            sys.exit(f"schematic not found: {p}")
        return p
    cands = [
        c for c in Path(".").glob("**/*.kicad_sch")
        if "backups" not in c.parts and not c.name.startswith("~")
    ]
    if not cands:
        sys.exit("no .kicad_sch found under current directory")
    for c in cands:
        if c.with_suffix(".kicad_pro").exists():
            return c
    return cands[0]


def cache_dir(sch):
    tag = hashlib.md5(str(Path(sch).resolve()).lower().encode()).hexdigest()[:10]
    d = Path(tempfile.gettempdir()) / "kicad_sch_analysis" / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cli(args_list):
    proc = subprocess.run(args_list, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(proc.stderr.strip() or proc.stdout.strip()
                 or f"kicad-cli failed ({proc.returncode})")
    return proc


def export_netlist(sch):
    d = cache_dir(sch)
    cur, prev = d / "netlist.xml", d / "netlist_prev.xml"
    if cur.exists():
        shutil.copy2(cur, prev)
        cur.unlink()
    run_cli([find_kicad_cli(), "sch", "export", "netlist",
             "--format", "kicadxml", "-o", str(cur), str(sch)])
    return cur, prev


def parse_netlist(path):
    root = ET.parse(path).getroot()
    pinmeta = {}
    libparts = root.find("libparts")
    if libparts is not None:
        for lp in libparts:
            pins = {}
            plist = lp.find("pins")
            if plist is not None:
                for p in plist:
                    pins[p.get("num")] = (p.get("name") or "", p.get("type") or "")
            pinmeta[(lp.get("lib"), lp.get("part"))] = pins
    comps = {}
    for c in root.find("components") or []:
        ls = c.find("libsource")
        # The orderable part number lives in a user field, not in "value";
        # "value" carries the electrical value (10k, 100nF) instead. Anything
        # that has to be checked against a datasheet needs the field.
        fields = {f.get("name"): (f.text or "")
                  for f in (c.find("fields") or [])}
        comps[c.get("ref")] = {
            "value": c.findtext("value") or "",
            "footprint": c.findtext("footprint") or "",
            "libpart": (ls.get("lib"), ls.get("part")) if ls is not None else None,
            "fields": fields,
            "mpn": fields.get("MFG Part No", ""),
        }
    nets = {}
    for net in root.find("nets") or []:
        nodes = []
        for n in net:
            ref, pin = n.get("ref"), n.get("pin")
            comp = comps.get(ref, {})
            pname = pinmeta.get(comp.get("libpart"), {}).get(pin, ("", ""))[0]
            nodes.append((ref, pin, pname))
        nets[net.get("name")] = nodes
    return comps, nets, pinmeta


def fmt_node(node):
    ref, pin, pname = node
    return f"{ref}.{pin}({pname})" if pname else f"{ref}.{pin}"


def print_net(name, nodes):
    body = " ".join(sorted(fmt_node(n) for n in nodes))
    print(f"{name} [{len(nodes)}]: {body}")


def cmd_components(args):
    comps, _, _ = parse_netlist(export_netlist(find_sch(args.sch))[0])
    for ref in sorted(comps, key=lambda r: (re.sub(r"\d+$", "", r), int(re.search(r"(\d+)$", r).group(1)) if re.search(r"(\d+)$", r) else 0)):
        c = comps[ref]
        part = c["libpart"][1] if c["libpart"] else ""
        mpn = c.get("mpn") or "-"
        print(f"{ref:6} {c['value']:18} {mpn:24} {part:24} {c['footprint']}")
        # A "Note" field records why a part is what it is -- a derating
        # expectation, a pinout caveat, a value that looks wrong but isn't.
        # It goes on its own line because it is prose and would otherwise
        # destroy the column alignment above.
        note = c["fields"].get("Note", "").strip()
        if note:
            print(f"       NOTE: {note}")


def cmd_nets(args):
    _, nets, _ = parse_netlist(export_netlist(find_sch(args.sch))[0])
    pats = [re.compile(p, re.I) for p in args.patterns]
    for name in sorted(nets):
        if not pats or any(p.search(name) for p in pats):
            print_net(name, nets[name])


def cmd_refs(args):
    _, nets, _ = parse_netlist(export_netlist(find_sch(args.sch))[0])
    want = {r.upper() for r in args.refs}
    for name in sorted(nets):
        if any(ref.upper() in want for ref, _, _ in nets[name]):
            print_net(name, nets[name])


def cmd_pins(args):
    comps, _, pinmeta = parse_netlist(export_netlist(find_sch(args.sch))[0])
    comp = comps.get(args.ref)
    if not comp:
        sys.exit(f"no component {args.ref}")
    print(f"{args.ref}  {comp['value']}  {comp['footprint']}")
    note = comp["fields"].get("Note", "").strip()
    if note:
        print(f"  NOTE: {note}")
    pins = pinmeta.get(comp["libpart"], {})
    for num in sorted(pins, key=lambda n: int(n) if n.isdigit() else 999):
        name, ptype = pins[num]
        print(f"  {num:>3}  {name:16} {ptype}")


def cmd_erc(args):
    sch = find_sch(args.sch)
    out = cache_dir(sch) / "erc.json"
    if out.exists():
        out.unlink()
    run_cli([find_kicad_cli(), "sch", "erc", "--format", "json",
             "-o", str(out), "--severity-all", str(sch)])
    data = json.loads(out.read_text(encoding="utf-8"))
    total = 0
    for sheet in data.get("sheets", []):
        for v in sheet.get("violations", []):
            total += 1
            items = "; ".join(i.get("description", "") for i in v.get("items", []))
            print(f"[{v.get('severity')}] {v.get('type')}: {v.get('description')} || {items}")
    print(f"-- {total} violation(s)")


def cmd_diff(args):
    cur, prev = export_netlist(find_sch(args.sch))
    if not prev.exists():
        sys.exit("no previous netlist snapshot yet; run any command again after editing")
    _, old, _ = parse_netlist(prev)
    _, new, _ = parse_netlist(cur)
    old_sets = {k: {fmt_node(n) for n in v} for k, v in old.items()}
    new_sets = {k: {fmt_node(n) for n in v} for k, v in new.items()}
    changed = False
    for name in sorted(set(old_sets) | set(new_sets)):
        o, n = old_sets.get(name), new_sets.get(name)
        if o == n:
            continue
        changed = True
        if o is None:
            print(f"NEW net {name}: {' '.join(sorted(n))}")
        elif n is None:
            print(f"REMOVED net {name} (was: {' '.join(sorted(o))})")
        else:
            for node in sorted(n - o):
                print(f"{name}: + {node}")
            for node in sorted(o - n):
                print(f"{name}: - {node}")
    if not changed:
        print("no net changes since previous export")


def cmd_pdf(args):
    try:
        import pypdf
    except ImportError:
        sys.exit("pypdf not installed: pip install pypdf")
    pdf = Path(args.file)
    if not pdf.is_file():
        sys.exit(f"file not found: {pdf}")
    cache = Path(tempfile.gettempdir()) / "kicad_sch_analysis" / (
        hashlib.md5(str(pdf.resolve()).lower().encode()).hexdigest()[:10] + ".txt")
    # A form feed separates pages in the cache, so a hit's page number is just
    # a count of the separators before it. Datasheet citations in the design
    # document carry a page, so every lookup needs one.
    if cache.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime:
        text = cache.read_text(encoding="utf-8")
    else:
        reader = pypdf.PdfReader(str(pdf))
        text = "\f".join((p.extract_text() or "") for p in reader.pages)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")

    def page_of(pos):
        return text.count("\f", 0, pos) + 1

    for kw in args.keywords:
        print(f"\n===== {kw} =====")
        seen = set()
        hits = 0
        for m in re.finditer(kw, text, re.I):
            start = max(0, m.start() - args.before)
            end = min(len(text), m.end() + args.after)
            snippet = " ".join(text[start:end].split())
            key = snippet[:60]
            if key in seen:
                continue
            seen.add(key)
            hits += 1
            print(" >>> [p%d]" % page_of(m.start()), snippet)
            if hits >= args.max_hits:
                print(f" ... (capped at {args.max_hits} hits)")
                break
        if hits == 0:
            print(" (no match)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sch", help="path to .kicad_sch (default: autodetect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("components").set_defaults(func=cmd_components)

    p = sub.add_parser("nets")
    p.add_argument("patterns", nargs="*", help="net-name regexes (default: all nets)")
    p.set_defaults(func=cmd_nets)

    p = sub.add_parser("refs")
    p.add_argument("refs", nargs="+", help="component references, e.g. U1 J6")
    p.set_defaults(func=cmd_refs)

    p = sub.add_parser("pins")
    p.add_argument("ref", help="component reference, e.g. U1")
    p.set_defaults(func=cmd_pins)

    sub.add_parser("erc").set_defaults(func=cmd_erc)
    sub.add_parser("diff").set_defaults(func=cmd_diff)

    p = sub.add_parser("pdf")
    p.add_argument("file", help="PDF path, e.g. a datasheet")
    p.add_argument("keywords", nargs="+", help="regex keywords to search")
    p.add_argument("--before", type=int, default=150, help="context chars before hit")
    p.add_argument("--after", type=int, default=250, help="context chars after hit")
    p.add_argument("--max-hits", type=int, default=12, help="max hits per keyword")
    p.set_defaults(func=cmd_pdf)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
