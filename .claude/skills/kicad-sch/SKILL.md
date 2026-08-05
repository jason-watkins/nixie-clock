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
**`--board {main|hv|face}` is required** on every netlist-based subcommand,
and goes *after* the subcommand: `sch_tool.py refs --board main U3`. Only
`pdf` takes no board.

There is no autodetection, by design. The repo holds three board projects
(`pcb/main`, `pcb/hv`, `pcb/face`) plus the drawing-only figure set under
`docs/design_analysis/schematics`, which uses its own reference designators
and carries no real connectivity. A tool that guesses will eventually hand
back a confident, fully-formed analysis of the wrong hardware — which is
exactly what it did before this argument existed.

## Subcommands

| Command | Purpose |
|---|---|
| `components` | List every component: ref, value, `MFG Part No`, library part, footprint; plus a `NOTE:` line wherever the symbol carries a `Note` field |
| `nets [REGEX ...]` | Print nets with pin-level nodes (`R1.2`, `U1.8(EN)`); optional net-name regex filters |
| `refs REF [REF ...]` | Print every net touching the given components — the fast way to audit one part's connectivity |
| `pins REF` | Pin table (number, name, electrical type) for one component's library symbol, with its `Note` field if set |
| `erc` | Run KiCad ERC, print all violations with severity and involved items |
| `diff` | Net-level changes since the previous export — run after the user edits the schematic to verify exactly what changed |
| `pdf FILE KW [KW ...]` | Extract a PDF's text (cached) and print context around regex keyword hits, each tagged `[pN]` with its page — for datasheet spec lookups that must cite a page |

Netlist-based subcommands re-export the netlist on every run, so output always
reflects the last *saved* schematic. If results look stale, the user likely has
unsaved changes open in KiCad — say so rather than re-running repeatedly.

## Typical workflows

- **Verify the user's latest edits**: `diff --board main` (shows added/removed
  nodes per net), then `refs` on the touched components for full context.
- **Trace a subsystem**: `refs --board main U1 L1 J1` or
  `nets --board hv VDD VOUT 'LED\d+'`.
- **Check a symbol import**: `pins --board main U1` for pin numbers/names/types.
- **Datasheet lookup**: `pdf tps51375.pdf 'hysteresis' 'Absolute' 'V_?EN'`
  (regexes, case-insensitive; tune `--before/--after/--max-hits` for context).

## Notes

- `diff` compares against the snapshot taken by the previous run of any
  netlist-based subcommand, keyed to the schematic path — so each board keeps
  its own snapshot and they never cross-contaminate.
- The orderable part number lives in the `MFG Part No` field, not in `value` —
  `value` carries the electrical value (10k, 100nF). Check anything against a
  datasheet using the field, never the value.
- A `Note` field on a symbol records why a part is what it is: a derating
  expectation, a pinout caveat, a value that looks wrong but isn't. Read it
  before questioning a part choice — C104/C107 carry one explaining that their
  1 µF is specified against its derated value, not its nominal.
- kicad-cli is autodetected from PATH or `C:\Program Files\KiCad\<ver>\bin`;
  override with the `KICAD_CLI` env var.
- `pdf` needs `pypdf` and `cryptography` (both installed for this user's
  Python); the latter decrypts AES-encrypted datasheets (e.g. Panasonic).
