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

## IN-6 (ИН-6): colon dots NX5–NX6

Source: `IN-6.pdf` (original label sheet, GOST 17821-75).

**Three electrodes**:
lead 1 = anode (A), lead 2 = indicator cathode (K), lead 3 = auxiliary
priming cathode (KA). Lead 1 is the physically separate one; count from it.

| Parameter | Value |
|---|---|
| Ignition voltage (either gap) | ≤ 140 V |
| Maintaining voltage @ 0.7 mA | ≤ 88–90 V |
| Permissible anode current | 0.6–0.85 mA |
| Indication current, min | 0.25 mA |
| Factory reference circuit | 200 kΩ from +180 V |

**Ballast (colon anodes):** R = (170 − 88) / 0.7 mA ≈ 117 kΩ → **120 kΩ**
gives ~0.68 mA, mid-range of permissible. Dissipation ≈ 56 mW.
One resistor per tube; never share ballast between gas tubes.

**KA handling:** auxiliary cathode exists to prime fast switching; unused in
always-on service. Leave NC (no-connect flag). Alternative if the third lead
is unwanted: clip it at the tube and leave the KA pad empty.

## Supply-rail note

IN-12 ignition worst case may approach the +170 V rail (some sources quote
up to ~200 V for aged/dark tubes). The HV rail is trimmable 160–196 V for
this reason: strike is calibrated against the actual tube stock, then the
rail is set about 10 V above. IN-6 strikes at ≤140 V and is not a concern.
