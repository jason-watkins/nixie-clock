# Rev A part discrepancies

`docs/design_analysis/` derives what each subsystem's components must
satisfy from first principles and datasheets; it does not reference
any specific populated board. This file is the companion record of
the opposite exercise: checking the actual Rev A schematic against
those derived requirements. It exists because that check has already
been done once, part by part, while the design-analysis document was
being written, and the result is worth keeping rather than discarding
— but it belongs in a separate file with a separate lifetime, updated
only when a board is actually populated and checked, not every time
the derivation itself is revised.

Each entry cites the design-analysis section it checks against by
label (e.g. `sec:hv-load`) and section number, and states the derived
requirement, the Rev A populated value, and the verdict. This is a
snapshot as of Rev A; nothing here is re-verified automatically when
the design-analysis document changes.

## 170 V flyback converter (design_analysis §5, `sec:hv-converter`)

| Parameter | Derived requirement | Rev A populated | Verdict |
|---|---|---|---|
| Digit ballast R1–R4 | 6.4–9.0 kΩ at 170 V; 9.3–13 kΩ at 180 V | 8.2 kΩ | Match at 170 V; **flagged** at 180 V |
| Colon ballast R5–R6 | 91–129 kΩ (170 V); 103–146 kΩ (180 V) | 120 kΩ | Match |
| Output setpoint | 180 V (10 V ignition margin) | 170 V nameplate; trim 160.3–196.3 V | **Flagged tension** — see below |
| Trim range | must span 170–185 V | 160.3–196.3 V | Match |
| R203/R204 element stress | < 250 V each | 97.7 V max each (DIN0207) | Match |
| $R_T$ | 146.4 kΩ for 150 kHz | 147 kΩ → 149.4 kHz | Match |
| Sense resistor R201 | window 37.4–39.9 mΩ | 39 mΩ | Match, thin margins on both sides |
| Current limit vs. need | $I_{lim}^{min}=2.36$ A vs. 2.33 A required (1% margin) | — | **Flagged margin** |
| Clamped peak vs. saturation | ≤2.91 A vs. 3.0 A rating (3% margin) | — | **Flagged margin** |
| Q201 $V_{DS}$ | ≤63 V incl. clamp | IRL540N, 100 V rating | Match (37%) |
| Q201 dissipation | 0.48 W, ΔT ≈ 30 K | TO-220, no heatsink | Match; R211 flagged as an efficiency lever (turn-off overlap is the dominant loss term) |
| D201 stress | $V_R<350$ V; 16 mA avg | UF4005 (600 V, 1 A) | Match |
| Clamp voltage | $V_{cl}=48.6$ V (2.7× reflected) | R212 27 kΩ / C209 10 nF | Match |
| D202 (snubber diode) | fast, ≥100 V | UF4005 (600 V) — deliberate substitution for a prior "fast 100 V diode" note, sharing the D201 line item | Match |
| Bleeder R202 | preload ≥27 mW; discharge in a few seconds | 470 kΩ: 78 mW, <3 s to 42 V | Match |
| Compensation (R210/C207/C208) | zero near $f_c$; phase margin ≥45° | $f_c\approx210$ Hz, $\varphi_m\approx54°$ | Match |
| Soft start C206 | ramp 4.7 ms; rail rise 20–30 ms (current-limited) | 47 nF | Match; approximation, bench-verify |
| UVLO R207/R208 | enable ≈8.1 V, below 8.5 V min input | on 8.12 V / off 7.14 V | Match |
| PGOOD pull-up R206 | ≥10 kΩ, ≤18 V, ≤1 mA | 100 kΩ to +3V3 (33 µA) | Match |
| VCC capacitor C201 | 1–4.7 µF | 2.2 µF | Match |
| Input bulk C202 | ≥0.67 A ripple capability | 100 µF radial (series unrecorded — assumed polymer, e.g. KEMET A759) | Match if polymer; **confirm series at BOM release** |
| Output caps C204/C205 | ripple met by 4.8 µF; rating ≥250 V (trim ceiling 196.3 V) | 4.7 µF + 100 nF (ratings unrecorded) | Sizing match; **rating unconfirmed** |
| DA2032 operating frequency | characterized only at 100 kHz | operated at 149.4 kHz | **Extrapolation, not directly characterized** |

**Ballast/trim tension (flagged).** At a 170 V setpoint the digit
ballast has zero ignition margin against the IN-12B's guaranteed
170 V strike voltage; at 180 V (the margin the ignition-budget
analysis calls for) the populated 8.2 kΩ ballast pushes digit current
past the tube's 3.5 mA maximum. The two requirements are mutually
inconsistent with the populated ballast value: correct tube current
wants ~170 V, adequate ignition margin wants ~180 V, and 8.2 kΩ cannot
satisfy both at once. A ballast of 10–11 kΩ resolves both
simultaneously (2.9–3.3 mA at 180 V, full margin) and needs no
topology change — a component-value change for the next board run.
Until then, trimming to 175 V with the populated 8.2 kΩ ballast is a
partial mitigation (~5 V margin, current still grazing the 3.5 mA
ceiling).

**USB-PD contract voltage (flagged, recommendation).** The nominal-point
efficiency comparison in design_analysis (`sec:hv-op-nominal`) finds a 12 V
negotiated input less efficient (η=0.840) than the 9 V contract (η=0.849),
because turn-off loss scales with the commutation voltage
$V_{BUS}+V_{refl}$ and dominates the loss budget: the shorter on-time and
lower RMS conduction current a higher input voltage otherwise gives are not
enough to offset it. Unless turn-off loss is reduced enough to stop
dominating the budget — unlikely without a topology change beyond the
D203/R214 network already adopted — a wider negotiated range buys no
efficiency benefit and should not be requested. This is a CYPD3176
sink-policy configuration item, not a component value; **confirm the
populated sink-policy configuration and narrow it to the 9 V contract only**
if it currently accepts higher voltages.

## 5 V converter (design_analysis §7, `sec:5v-converter`)

Populated: U401 (AP63205WU), L401 (4.7 µH), C401 (10 µF input), C402
(100 nF BST), C403/C404 (2×22 µF output), R401 (5.1 kΩ) + D401
(power-indicator LED on the +5V rail).

| Parameter | Derived requirement | Rev A populated | Verdict |
|---|---|---|---|
| Load current | 4× $I_{CC}$ (64/100 mA) + D401 indicator (0.59 mA via R401): 65 mA typ / 101 mA max, static | — | Derived |
| Inductance L401 | 2.8–4.7 µH window at 13 V; datasheet 5 V BOM value 4.7 µH | 4.7 µH | Match — reference BOM followed exactly |
| Inductor $I_{sat}$ | ≥0.45 A normal; ≥3.1 A covers fault peak | 6045-class, part/rating unrecorded (assumed ≥3 A) | Match under assumption; **confirm part** |
| Output capacitance C403/C404 | 22–68 µF (≥1.5 µF transient bound) | 2×22 µF (= BOM example) | Match |
| Rail accuracy at load | K155ID1 requires 4.75–5.25 V | 4.94–5.06 V incl. ripple | Match (~190 mV margin both sides) |
| Input capacitor C401 | ≥10 µF ceramic; RMS ≥49 mA | 10 µF (= BOM example; rating unrecorded) | Match; **confirm ≥16 V rating** |
| BST capacitor C402 | 100 nF SW-to-BST | 100 nF | Match |
| EN configuration | EN = VIN valid always-on | EN tied to $V_{BUS}$ | Match |
| Converter dissipation | 88 mW, ΔT ≈ 8 K vs. 125°C target | TSOT26, $\theta_{JA}=89$ °C/W | Match, large margin |
| Bypass C1–C4 | 100 nF per TTL package, standard practice | 100 nF × 4 | Match |

No populated value on this rail is flagged as a mismatch. The two
open items are unrecorded ratings (L401 saturation current, C401
voltage rating), not wrong values.

## 3.3 V converter (design_analysis §8, `sec:3v3-converter`)

Populated: U411 (AP63203WU), L411 (4.7 µH — the 5 V rail's part
reused rather than the variant-specific 3.9 µH BOM value), C411
(10 µF input), C412 (100 nF BST), C413/C414 (2×22 µF output), D411
(Schottky OR diode from $V_{BUS}$), D412 (Schottky OR diode from
`VCC_UART`), R411 (1.5 kΩ) + D413 (rail-indicator LED, value field
mislabeled "RX"), R501/C503 (ESP32 EN network), R502/R503 (1.5 kΩ,
UART activity LEDs D501/D502), R206 (100 kΩ, PGOOD pull-up).

| Parameter | Derived requirement | Rev A populated | Verdict |
|---|---|---|---|
| Load current | 355 mA MCU + ≤4 mA housekeeping ≈ 0.36 A sustained; capability ≥0.5 A (Espressif's own sizing requirement) | 2 A-rated AP63203 | Match (4×) |
| Inductance L411 | 2.2–3.7 µH window; Table-2 BOM value 3.9 µH | 4.7 µH (5 V rail's part reused) | Acceptable deviation — ripple 19–24%, benign; deliberate cross-rail part-sharing, not the per-variant BOM value |
| Inductor $I_{sat}$ | ≥0.68 A (rule at 0.5 A point); fault ≤3.1 A | 6045-class, rating unrecorded (assumed ≥3 A) | Match under assumption; **confirm part** |
| Output capacitance C413/C414 | ≥5.0 µF transient bound; 22–68 µF recommended | 2×22 µF (+ C502 at module) | Match |
| Input capacitor C411 | ≥10 µF; RMS ≥0.18 A; ≥16 V rating | 10 µF (= BOM example; rating unrecorded) | Match; **confirm rating** |
| BST capacitor C412 | 100 nF SW-to-BST | 100 nF | Match |
| D412 reverse rating | ≥16 V (blocks 12.8 V) | generic Schottky, part unrecorded | Match under assumption; **confirm part** |
| D411 forward path | $I_F$ avg ≤0.24 A, 96 mW | generic SOD-123 Schottky | Match under assumption |
| PGOOD pull-up R206 | load 33 µA, not-good windows only | 100 kΩ to +3V3 | Match; negligible |
| EN pull-up R501 | transient only (330 µA pk, τ=10 ms) | 10 kΩ (= Espressif's own reference circuit, matches R501/C503 exactly) | Match; negligible |
| Indicator LEDs R411/R502/R503 | 0.87 mA continuous + ≤1.6 mA UART activity | 1.5 kΩ each | Negligible; **D413's value field is mislabeled "RX"** — fix at BOM/silkscreen |
| Module decoupling C501/C502 | load-local second decoupling stage at a burst load | 100 nF + 22 µF | Match (role inferred from placement, not labeled in netlist) |
| Converter dissipation | ≤0.29 W, ΔT ≤26 K vs. 125°C target | TSOT26, $\theta_{JA}=89$ °C/W | Match, large margin |
| PSRAM active-mode current adder | unquantified above 355 mA if PSRAM-equipped | module SKU unrecorded on schematic | Open item, absorbed by the 4× current-capability headroom |

**UART header adapter-voltage requirement (flagged, operational, not a
component mismatch).** The diode-OR input path only regulates when
the UART adapter's VCC is set to 5 V; a 3.3 V-VCC adapter leaves the
node below the buck's UVLO and the rail dead whenever USB-C power is
absent. This is a real Rev A behavior, driven by the specific diode
drops and UVLO threshold on this board, not a component discrepancy
to fix — it is a use-and-documentation item for whichever
user-facing guide eventually covers the flashing/console procedure.

## 170 V driving components (design_analysis §4) — substitutions and extrapolations

- **DA2032-AL operating frequency.** Characterized by Coilcraft only
  at a 100 kHz test point; this design switches at 149.4 kHz. Carried
  as an extrapolation with a core-loss allowance, not a directly
  verified figure.

## BCD decoder/driver (design_analysis §3) — part substitution

- **K155ID1 → SN74141.** No datasheet for the actual populated part
  (K155ID1, Soviet-made) could be located. All figures in §3 are
  transcribed from the TI SN74141 datasheet instead, on the recorded
  assumption that the two are electrically equivalent functional
  clones. Not independently verified against a K155ID1 source.
- **Off-state cathode voltage.** The SN74141's guaranteed off-state
  output voltage is 60 V; this board's unselected cathodes see up to
  ~196 V today, and the §5 ballast/trim rework in progress is pushing
  the design voltage higher still — 2.5–3.3×+ the guaranteed figure.
  This is the standard topology for amateur Nixie clocks in this
  voltage range with a long field-reliability track record, but it is
  not covered by the datasheet guarantee. The robust fix — a
  high-voltage buffer transistor per output (~40 transistors plus
  interface components), isolating the driver entirely from the anode
  rail — was scoped during the §5 rework and set aside as a Rev-B-scale
  topology change, not a value tweak. `design_analysis` proceeds on
  the assumption that the existing direct-drive topology tolerates
  whatever voltage the design ultimately settles on; this is a
  deliberate, accepted risk for the current design pass, not an
  oversight. Open pending either a K155ID1 source datasheet or the
  buffer-transistor redesign.

## Notes

- This file does not track schematic churn automatically. The
  component inventories above (refdes, values) reflect the netlist as
  read while each corresponding design-analysis section was written;
  re-check against the current schematic before relying on any row
  here.
- "Confirm at BOM release" items above (capacitor/inductor/diode
  ratings not recorded on the schematic) are open regardless of this
  file's freshness — they were never verified from the schematic in
  the first place, only assumed from commodity-part norms.
