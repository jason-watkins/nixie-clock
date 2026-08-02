# Project libraries

Symbols in `nixie_clock.kicad_sym`, footprints in `nixie_clock.pretty/`,
3D models in `nixie_clock.3dshapes/`.

## Imported from judge2005's Eagle-and-KiCAD-Nixie-Libs

Source: <https://github.com/judge2005/Eagle-and-KiCAD-Nixie-Libs>
(no license stated; used with attribution)

- K155ID1 symbol and DIP16 footprint (nixiemisc collection)

Local changes: pin electrical types set to passive, courtyard added. DIP16 carries the stock KiCad
`DIP-16_W7.62mm` model, rotated to suit this footprint's horizontal, centre-origin pin layout.

## Imported from laurivosandi's nixiesp12

Source: <https://github.com/laurivosandi/nixiesp12>
(no license stated; used with attribution)

- `IN-12B.wrl` tube model, attached to the IN-12-DSUB footprint. That
  project credits miniwatt.info as the origin of its 3D models; that site is
  no longer online.

The model's' pins sit on a 1.27 mm grid rather than the tube's 11.5 x 18 mm oval, so in the 3D view
they stand off centre in their holes by up to 0.7 mm. Only the twelve and six o'clock pins land
concentric.

## Copied from the KiCad 9 stock library, then modified

- `WSON-12-1EP...ThermalVias` (LM5155): exposed-pad stack set to solid zone
  connection, TI STEP model attached
- `QFN-24-1EP_4x4mm...ThermalVias` (CYPD3176): same exposed-pad change,
  model path corrected to the STEP that ships with KiCad
- `USB_C_Receptacle_JAE_DX07S016JA1R1500`: JAE STEP attached and calibrated,
  ground pads A12/B1 set to solid zone connection

## Drawn for this project

- IN-12B symbol and IN-12-DSUB footprint, the tube socketed on D-SUB machined
  pins.
- INS-1 symbol and footprint. The label sheet in `docs/datasheets/INS-1.pdf`
  carries no mechanical drawing, so the 6.8 mm envelope diameter comes from
  distributor listings and the lead diameter, about 0.3 mm, from a photograph
  scaled against that envelope. The leads are soft wire on no fixed pitch, so
  the footprint sets it at 2.54 mm on 0.7 mm holes. The model draws its leads
  5.5 mm apart, so they stand outside the holes in the 3D view.
- INS-1_Recessed, the same lamp sunk through the board so its lens clears the
  IN-12 faces by a few millimetres instead of standing 6 mm above them. The
  milled 8.0 x 5.0 mm slot on Edge.Cuts passes the 7.0 x 4.0 mm pinch blade
  and keys its rotation so the leads exit along X; the wider flare above the
  blade seats the lamp. A printed TPU top-hat washer lines the slot and its
  flange sets the height. Leads land on pads on the back of the board.
- CYPD3176 symbol, pins arranged to match the datasheet's application figure
- Kemet GoldMax radial dipped MLCC footprints: C315, C317, C320, C322, C330
  case sizes
- Panasonic ECQ-E film capacitor footprint (7.9 x 5.9 mm, 5.0 mm pitch), and
  `ECQ-E.stp` with it. Panasonic's own model for ECQ-E2104KB is a plain box 14
  mm tall, which is H max for the crimped lead form; this part has straight
  leads and stands 9. The replacement is built in `cad/ecqe/ecqe2104kb.py` from
  the three outlines on the catalogue drawing.
- Bourns SRN5040TA inductor footprint, land pattern per the datasheet's
  recommended layout, and `L_Bourns_SRN5040TA.step` with it. Bourns publish no
  model; the part is built in `cad/srn5040/srn5040ta.py` from the dimensioned
  terminal and envelope sizes, with the flange-and-waist profile taken off the
  catalogue render.
- DA2032-AL flyback transformer, land pattern from the Coilcraft drawing

## Imported from GrabCAD

- `INS1.STEP`, attached to the INS-1 footprint. Uploaded there in December
  2020 by Patrick Simon.

Apart from the IN-12B tube, the INS-1 lamp, the ECQ-E capacitor and the
SRN5040TA inductor, 3D models come from the part manufacturers (Kemet, TI, JAE,
Coilcraft).
