---
name: kicad-sch
description: Analyze this repo's KiCad schematic — trace connections via exported netlists, run ERC, diff net changes after edits, list components/pins, and keyword-search datasheet PDFs. Use for any schematic connectivity or verification question instead of ad-hoc shell pipelines.
---

# KiCad schematic analysis

All operations go through one script so a single Bash permission rule covers them:

```
python .claude/skills/kicad-sch/scripts/sch_tool.py <subcommand> [args]
```

Always invoke it exactly like that, relative to the repo root, so the
allowlist rule matches. The script is read-only with respect to the project:
netlist/ERC/PDF-text artifacts are cached under the system temp directory.
The schematic is autodetected (the `.kicad_sch` with a `.kicad_pro` sibling);
override with `--sch <path>` placed *before* the subcommand.

## Subcommands

| Command | Purpose |
|---|---|
| `components` | List every component: ref, value, library part, footprint |
| `nets [REGEX ...]` | Print nets with pin-level nodes (`R1.2`, `U1.8(EN)`); optional net-name regex filters |
| `refs REF [REF ...]` | Print every net touching the given components — the fast way to audit one part's connectivity |
| `pins REF` | Pin table (number, name, electrical type) for one component's library symbol |
| `erc` | Run KiCad ERC, print all violations with severity and involved items |
| `diff` | Net-level changes since the previous export — run after the user edits the schematic to verify exactly what changed |
| `pdf FILE KW [KW ...]` | Extract a PDF's text (cached) and print context around regex keyword hits, each tagged `[pN]` with its page — for datasheet spec lookups that must cite a page |

Netlist-based subcommands re-export the netlist on every run, so output always
reflects the last *saved* schematic. If results look stale, the user likely has
unsaved changes open in KiCad — say so rather than re-running repeatedly.

## Typical workflows

- **Verify the user's latest edits**: `diff` (shows added/removed nodes per net),
  then `refs` on the touched components for full context.
- **Trace a subsystem**: `refs U1 L1 J1` or `nets VDD VOUT 'LED\d+'`.
- **Check a symbol import**: `pins U1` to see pin numbers/names/types.
- **Datasheet lookup**: `pdf tps51375.pdf 'hysteresis' 'Absolute' 'V_?EN'`
  (regexes, case-insensitive; tune `--before/--after/--max-hits` for context).

## Notes

- `diff` compares against the snapshot taken by the previous run of any
  netlist-based subcommand in this repo, keyed to the schematic path.
- kicad-cli is autodetected from PATH or `C:\Program Files\KiCad\<ver>\bin`;
  override with the `KICAD_CLI` env var.
- `pdf` needs `pypdf` and `cryptography` (both installed for this user's
  Python); the latter decrypts AES-encrypted datasheets (e.g. Panasonic).
