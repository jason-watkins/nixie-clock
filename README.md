[![CC BY-SA 4.0][cc-by-sa-shield]][cc-by-sa]

# Nixie Clock

USB-C powered nixie tube clock, designed in KiCad 9. Four IN-12B digits, two IN-6 colon lamps,
K155ID1 (Soviet 74141) BCD decoder/drivers.

## Power

A CYPD3176 USB-PD sink negotiates 9-12 V from the charger and gates it through a back-to-back PFET
load switch. Three converters hang off that rail:

- LM5155 flyback boost: 170 V for the tube anodes
- AP63205 buck: 5 V for the BCD drivers
- AP63203 buck: 3.3 V for the MCU (ESP32 class)

## Repository layout

- `pcb/` KiCad project. Sheets: root (display), PWR (USB-PD input and bucks), HV (flyback)
- `pcb/lib/` project libraries; origins and local changes in [pcb/lib/README.md](pcb/lib/README.md)
- `docs/` design doc and vendor datasheets
- `scripts/` [make_release.py](scripts/make_release.py), fab exports with enforced revision bookkeeping

## Status

Rev A, layout in progress, nothing fabricated yet, MCU section not yet designed. This board is a
bench validation unit, which is also why it has no mounting holes. The finished clock gets respun
onto separate boards once the circuits are proven.

## Fab files

    python scripts/make_release.py --check
    python scripts/make_release.py

Writes JLCPCB-ready gerbers, BOM, and placement files under `fab/` and tags the commit. The script's
docstring explains the revision rules it enforces.

## Credits

The IN-12B and IN-6 symbols and footprints started as imports from
[judge2005's Eagle-and-KiCAD-Nixie-Libs](https://github.com/judge2005/Eagle-and-KiCAD-Nixie-Libs)
and were modified here. Full library inventory: [pcb/lib/README.md](pcb/lib/README.md).

## AI use

AI assistance is used to write and edit documentation, build symbols/footprints, and as a sounding
board for design work. All schematic drawing and PCB layout is done by hand.

## License

This work is licensed under a
[Creative Commons Attribution-ShareAlike 4.0 International License][cc-by-sa].

[![CC BY-SA 4.0][cc-by-sa-image]][cc-by-sa]

[cc-by-sa]: http://creativecommons.org/licenses/by-sa/4.0/
[cc-by-sa-image]: https://licensebuttons.net/l/by-sa/4.0/88x31.png
[cc-by-sa-shield]: https://img.shields.io/badge/License-CC%20BY--SA%204.0-lightgrey.svg
