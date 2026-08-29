# Project libraries

Symbols in `nixie_clock.kicad_sym`, footprints in `nixie_clock.pretty/`,
3D models in `nixie_clock.3dshapes/`.

## Imported from judge2005's Eagle-and-KiCAD-Nixie-Libs

Source: <https://github.com/judge2005/Eagle-and-KiCAD-Nixie-Libs>
(no license stated; used with attribution)

- K155ID1 symbol and DIP16 footprint (nixiemisc collection)

Local changes: pin electrical types set to passive, courtyard added. DIP16 carries the stock KiCad
`DIP-16_W7.62mm` model, rotated to suit this footprint's horizontal, centre-origin pin layout.

## Copied from the KiCad 9 stock library, then modified

- `WSON-12-1EP...ThermalVias` (LM5155): exposed-pad stack set to solid zone
  connection, TI STEP model attached
- `QFN-24-1EP_4x4mm...ThermalVias` (CYPD3176): same exposed-pad change,
  model path corrected to the STEP that ships with KiCad
- `USB_C_Receptacle_JAE_DX07S016JA1R1500`: JAE STEP attached and calibrated,
  ground pads A12/B1 set to solid zone connection

## Drawn for this project

- IN-12B symbol and IN-12-DSUB footprint. The name is historical: the footprint now takes twelve Mill-Max
  0327-0-15-15-34-27-10-0 pin receptacles (2.0 mm plated holes, 2.8 mm pads).
- `IN12B.wrl`, built in `cad/in12/` and written by `cad/in12/export_kicad.py`. Dimensions come from
  the dimensioned drawing in `docs/datasheets/IN-12A_IN-12B.pdf`, from the footprint's own hole
  pattern, and from tubes in hand; the electrode stack and the glass markings are off photographs
  of those tubes.
- INS-1 symbol and INS-1_Recessed footprint, the lamp sunk through the board so its lens clears the
  IN-12 faces by a few millimeters instead of standing 6 mm above them. Leads land on pads on the
  back of the board. The label sheet in `docs/datasheets/INS-1.pdf` carries no mechanical drawing,
  so the envelope dimensions are the ones measured for the model below: a 6.50 mm barrel over a
  7.00 x 3.35 mm pinch blade, on 0.5 mm leads 5.5 mm apart.
- `INS1_Recessed.wrl`, built in `cad/ins1/` and written by `cad/ins1/export_kicad.py`. Dimensions
  are measured off a third-party model of the lamp, credited in `cad/ins1/shoulder_profile.py`,
  which holds the one region of the envelope that is sampled from the original model because
  FreeCAD can't handle the fillets. No STEP twin, deliberately: KiCad would substitute it and the
  lamp would arrive grey, where the VRML carries the glass and the lit dot. `cad/test_base` reads
  this file directly for that reason, as it does the tube.
- CYPD3176 symbol, pins arranged to match the datasheet's application figure
- Kemet GoldMax radial dipped MLCC footprints: C315, C317, C320, C322, C330 case sizes
- Panasonic ECQ-E film capacitor footprint, and `ECQ-E.stp` with it. Built in
  `cad/ecqe/ecqe2104kb.py` from the three outlines on the catalogue drawing.
- Bourns SRN5040TA inductor footprint, land pattern per the datasheet's recommended layout, and
  `L_Bourns_SRN5040TA.step` with it; built in `cad/srn5040/srn5040ta.py` from the dimensioned
  terminal and envelope sizes, with the flange-and-waist profile taken off the catalogue render.
- DA2032-AL flyback transformer, land pattern from the Coilcraft drawing

Other 3D models come from the part manufacturers.
