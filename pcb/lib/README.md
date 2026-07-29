# Project libraries

Symbols in `nixie_clock.kicad_sym`, footprints in `nixie_clock.pretty/`,
3D models in `nixie_clock.3dshapes/`.

## Imported from judge2005's Eagle-and-KiCAD-Nixie-Libs

Source: <https://github.com/judge2005/Eagle-and-KiCAD-Nixie-Libs>
(no license stated; used with attribution)

- IN-12B symbol and IN-12-DSUB footprint
- IN-6 symbol and footprint
- K155ID1 symbol and DIP16 footprint (nixiemisc collection)

Local changes: pin electrical types set to passive, courtyards added, IN-6
corrected to three electrodes (anode, cathode, auxiliary priming cathode)
per the GOST datasheet. DIP16 carries the stock KiCad `DIP-16_W7.62mm`
model, rotated to suit this footprint's horizontal, centre-origin pin
layout.

## Imported from laurivosandi's nixiesp12

Source: <https://github.com/laurivosandi/nixiesp12>
(no license stated; used with attribution)

- `IN-12B.wrl` tube model, attached to the IN-12-DSUB footprint. That
  project credits miniwatt.info as the origin of its 3D models; that site is
  no longer online.

The model is authored in the VRML convention of one unit per 0.1 inch and
carries no units of its own, so it is attached at scale 1 with the seating
plane already at the board surface. Its pins sit on a 1.27 mm grid rather
than the tube's 11.5 x 18 mm oval, so in the 3D view they stand off centre
in their holes by up to 0.7 mm. Only the twelve and six o'clock pins land
concentric.

## Copied from the KiCad 9 stock library, then modified

- `WSON-12-1EP...ThermalVias` (LM5155): exposed-pad stack set to solid zone
  connection, TI STEP model attached
- `QFN-24-1EP_4x4mm...ThermalVias` (CYPD3176): same exposed-pad change,
  model path corrected to the STEP that ships with KiCad
- `USB_C_Receptacle_JAE_DX07S016JA1R1500`: JAE STEP attached and calibrated,
  ground pads A12/B1 set to solid zone connection

## Drawn for this project

- CYPD3176 symbol, pins arranged to match the datasheet's application figure
- Kemet GoldMax radial dipped MLCC footprints: C315, C317, C320, C322, C330
  case sizes
- Panasonic ECQ-E film capacitor footprint (7.9 x 5.9 mm, 5.0 mm pitch)
- DA2032-AL flyback transformer, land pattern from the Coilcraft drawing

Except for the IN-12B tube, 3D models come from the part manufacturers
(Kemet, Panasonic, TI, JAE, Coilcraft).
