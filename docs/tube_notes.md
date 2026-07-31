# Nixie tube design values

Extracted from the scans in `datasheets/` (vendored from Dieter's Nixie
Tube Data Archive, tube-tester.com, and GRA & AFCH). The Soviet originals
are image scans with no embedded text, so the numbers this design relies
on are transcribed here.

## IN-12B (ИН-12Б): digit tubes NX1–NX4

Source: `IN-12A_IN-12B.pdf` (original scan), `IN-12_english_gra-afch.pdf` (English summary).

| Parameter | Value |
|---|---|
| Typical maintaining (plate) voltage | ~145 V |
| Cathode current, digits | 2.5–3.5 mA |
| Decimal point (LHDP) current | 0.3–0.7 mA |
| Digit height | 18 mm |

**Ballast (digit anodes):** R = (170 − 145) / 3 mA ≈ 8.2 kΩ.
At 2.5 mA use 10 kΩ. Dissipation ≈ 75 mW → 0.25 W part is fine.

## INS-1 (ИНС-1): colon dots NX5–NX6

Source: `INS-1.pdf` (original label sheet, ODO.334.095 TU).

**Two electrodes**: lead 1 = anode (A, the small cylinder), lead 2 = cathode
(K, the large cylinder, the one the glow forms on). Count leads from the
indicator dot.

| Parameter | Value |
|---|---|
| Striking voltage | 65–90 V |
| Maintaining voltage | ≤ 55 V (no minimum given) |
| Optimal indication current | 0.5 mA |

No rated operating-current band, no maximum switching frequency, and no
envelope dimensions are given.

**Ballast (colon anodes):** cathodes go straight to ground, so there is no
driver drop: R = (177.5 − 55) / 0.5 mA = 245 kΩ → **240 kΩ**, sized at the
middle of the 170–185 V trim range. That passes 0.48–0.54 mA across it and
0.46–0.57 mA across the wider achieved range. Dissipation ≈ 78 mW worst case.
One resistor per tube; never share ballast between gas tubes.

## Supply-rail note

IN-12 ignition worst case may approach the +170 V rail (some sources quote
up to ~200 V for aged/dark tubes). The HV rail is trimmable 160–196 V for
this reason: strike is calibrated against the actual tube stock, then the
rail is set about 10 V above. INS-1 strikes at ≤90 V and is not a concern.
