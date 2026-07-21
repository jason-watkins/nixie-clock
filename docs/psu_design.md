# HV flyback design — LM5155 + Coilcraft DA2032-AL

Input: USB-C PD, negotiated 12 V (9 V fallback) → design window **8.5–13 V**.
Output: **+170V net, trimmed 175 V nominal** (NOS strike margin), load 13.4 mA
(4 digits × 3 mA + colon 2 × 0.7 mA), designed for 15 mA.
Constants from LM5155 datasheet (SNVSB75E): V_REF = 1.000 V ±1 %,
V_CS-limit = 100 mV ±7 %, RT 220 kΩ ↔ 100 kHz, UVLO pin 1.5 V rising with
5 µA hysteresis current, I_SS = 10 µA, VCC = 6.85 V.

## 1. Operating point

- P_out = 175 V × 15 mA = 2.63 W. Assume η ≈ 0.85 → **P_in ≈ 3.1 W**
  (≈ 360 mA at 9 V — trivial for any PD source).
- Transformer: 1:10, L_pri = 10 µH, I_pk rating 3 A, L_leak ≤ 0.15 µH.
- Reflected output voltage at the primary: 175 V / 10 = **17.5 V**.

**Mode choice: DCM (discontinuous conduction).** Rationale: at 3 W a 10 µH
primary empties easily each cycle; DCM eliminates the diode reverse-recovery
loss that hurt the reference blog's CCM attempt, simplifies compensation
(no sub-harmonic issue, benign RHP zero), and regulates predictably.

**Switching frequency: 150 kHz** (RT = 147 kΩ, from f ≈ 100 kHz × 220k/RT).
Rationale: energy per cycle E = P_in/f_sw = 20.6 µJ →
I_pk = √(2E/L) = **2.03 A**. At 120 kHz I_pk would be 2.27 A (less margin to
the 3 A core rating and the current limit); above ~200 kHz, gate/switching
losses of a big TO-220 FET start to matter. 150 kHz balances both.

**DCM check (worst case V_in = 8.5 V):**
t_on = L·I_pk/V_in = 2.39 µs; secondary demag t_dis = (L_sec·I_pk/10)/V_out
= (1 mH × 0.203 A)/175 V = 1.16 µs. Sum 3.55 µs < T = 6.67 µs → deep DCM
with 47 % idle margin. At 13 V: sum 2.72 µs. Confirmed DCM everywhere.

## 2. Current sense — R_CS = 39 mΩ, 1 %

Constraints: limit_min = 93 mV/R_CS must exceed I_pk (2.03 A) with margin;
limit_max = 107 mV/R_CS must stay below the transformer's 3 A rating.
39 mΩ → limit = 2.38–2.74 A: 17 % above worst-case operating peak, 9 %
below core rating. Dissipation: I_rms = I_pk·√(D/3) ≈ 0.70 A →
0.70² × 0.039 = **19 mW** — any 1 % sense resistor works; use a 4-terminal
or at least Kelvin-routed 2512/through-hole shunt.

## 3. MOSFET — IRL540N (TO-220)

Stress: V_DS = V_in(max) + V_reflected + leakage spike
= 13 + 17.5 + spike. With the snubber clamping the spike (below), total
≈ 48 V worst case.

Choice rationale (through-hole preference honored):
- **IRL540N**: 100 V, logic-level (specified at V_GS = 5 V; our gate drive is
  6.85 V), TO-220. The 100 V rating gives >2× margin over the clamped stress —
  it lets the snubber run relaxed and tolerates surprises.
- Losses at our point: R_DS(on) ≈ 77 mΩ → conduction ≈ 0.70² × 0.08 ≈ 40 mW;
  gate ≈ Q_g(71 nC) × 6.85 V × 150 kHz ≈ 73 mW; switching ≈ tens of mW in
  DCM (turn-on at zero current). Total ≈ 0.15 W — no heatsink, and the ~2 %
  efficiency cost vs. a modern SMD FET is invisible at 3 W.
- SMD alternative if ever needed: 60 V, Q_g < 15 nC, R_DS < 30 mΩ @ 4.5 V
  (class of BSC-series PowerPAK parts, per the reference blog's method:
  prioritize low Q_g over lowest R_DS for clean edges).
- 10 Ω gate resistor in series: damps gate ringing, slows edges slightly
  (kinder EMI); cheap insurance.

## 4. Output rectifier — UF4005 (axial)

Reverse stress: V_R = V_out + n·V_in(max) = 175 + 130 = 305 V → 600 V part.
Must be *ultrafast* (t_rr ≈ 75 ns): at 150 kHz a standard 1N4007 (µs-class
recovery) would burn watts and ring. Current is trivial (15 mA avg, 0.2 A
peak). UF4005 is the through-hole classic for exactly this slot.

## 5. Output capacitor — 4.7 µF 250 V polymer + 100 nF 250 V film

**Part: Kemet A759KS475M2EAAE496** (8 × 13 mm can, LS 3.5 mm, footprint
`Capacitor_THT:CP_Radial_D8.0mm_P3.50mm`). Solid polymer, not wet
electrolytic — no dry-out wear mechanism; ~1M-hour projection at board temp.
Datasheet (KEM_A4072_A759) verified: rated 250 V is a *continuous* rating
over −55…125 °C, no derating clause; surge = 287.5 V. Trim ceiling 196 V →
32 % below rated. Ripple: ours ≈ 46 mA vs 650 mA @ 100 kHz rating.
ESR 496 mΩ adds ~100 mV spikes (0.06 % of rail) — the 100 nF film bypass
absorbs the edges.
**Film bypass part: Panasonic ECQ-E2104KB** (100 nF ±10 %, 250 VDC,
metallized polyester box, LS 5.0 mm, footprint
`nixie_clock:C_Rect_L7.9mm_W5.9mm_P5.00mm_ECQE`). Ripple between demag pulses: ΔV = I_out·T/C
= 15 mA × 6.67 µs / 4.7 µF ≈ 21 mV — capacitance is not the constraint.
The can is the deliberate "vintage can in the power corner" aesthetic piece.

## 6. Bleeder — 470 kΩ across +170V

Dual duty: (1) safety — drains 175 V to <50 V in ~3 s after unplug
(τ = 470k × 4.7 µF = 2.2 s); (2) minimum preload (0.37 mA) so regulation
never runs dry. Dissipation 65 mW. Use a 250 V-rated 0207 metal film
(MRS25-class); ordinary tiny SMD resistors have 50–75 V element ratings.

## 7. Feedback divider — 2 × 866 kΩ + (8.87 kΩ + 2 kΩ trimmer)

V_out = V_REF × (R_top/R_bot + 1). Choose divider current ≈ 100 µA
(low waste, still stiff against noise/bias): R_top = 1.732 MΩ as **two 866 kΩ
in series** — splitting halves the per-resistor voltage (87 V each, inside
any 0207's rating) and is standard HV practice. Bottom leg 8.87 kΩ fixed +
2 kΩ multiturn trimmer → V_out adjustable ≈ **160–196 V**, mid-range ≈ 175 V.
Rationale for the trim: NOS tube strike voltage is the one spec we could not
verify from datasheets; the trimmer converts that risk into a screwdriver
adjustment. Route the divider tap (FB) away from the switch node.

## 8. UVLO divider — 143 kΩ / 32.4 kΩ

Goal: converter enables only on a successful PD negotiation; a dumb 5 V
charger must yield a cleanly dark supply, not a brownout struggle.
Turn-on: V_on = 1.5 V × (143k + 32.4k)/32.4k = **8.1 V** (9 V PD min ✓,
5 V ✗). Hysteresis: the 5 µA pin current through 143 kΩ adds ≈ 0.7 V →
turn-off ≈ 7.4 V. This makes graceful 5 V failure *intrinsic* — the CH224K
power-good gate becomes a belt-and-suspenders extra, not load-bearing.

## 9. Snubber — RCD clamp: 27 kΩ 0.5 W + 10 nF 100 V film + UF4004

Leakage energy: ½ × 0.15 µH × 2.03² = 0.31 µJ/cycle → 46 mW raw.
Clamp target 45 V above V_in (comfortably inside the IRL540N's 100 V):
P_R = 46 mW × V_cl/(V_cl − V_refl) = 46 × 45/27.5 ≈ 75 mW →
R = 45²/0.075 ≈ 27 kΩ (0.5 W part for margin). C: ripple ≈ 2–3 V →
10 nF film. Diode: fast, ≥100 V → UF4004. Rationale for RCD over TVS/RC:
dissipative but deterministic clamp voltage; with only 0.15 µH of leakage
this snubber loafs.

## 10. Housekeeping

- **RT = 147 kΩ 1 %** → ≈150 kHz.
- **SS = 47 nF** → t_ss = C·V_REF/I_SS ≈ 4.7 ms; graceful HV ramp.
- **BIAS** ← VBUS direct (8.5–13 V « 45 V rating); 1 µF X7R at pin.
- **VCC**: 2.2 µF X7R 50 V at pin (gate-drive reservoir).
  **Part: Kemet C322C225K5R5TA** (Goldmax radial dipped X7R, LS 5.08 mm,
  footprint `nixie_clock:C_Rect_L5.1mm_W3.2mm_P5.08mm_Goldmax`). Not the
  Z5U variant — Z5U is +10…85 °C only and loses >50 % capacitance cold.
- **Input bulk**: 100 µF 25 V polymer + 4.7 µF X7R — the 2 A triangular
  primary pulses must come from local capacitance, not the cable.
  **Part: Kemet A750KK107M1EAAE040** (8 × 9 mm can, LS 3.5 mm, footprint
  `Capacitor_THT:CP_Radial_D8.0mm_P3.50mm`). Polymer, not wet electrolytic:
  4.5 A @ 100 kHz ripple rating vs ≈ 0.6 A demand, ESR 40 mΩ, no dry-out
  wear mechanism (≈ 256k-hour projection at board temp).
- **PGOOD**: 100 kΩ pullup to VCC; broken out for the future MCU.
- **Compensation (COMP→AGND): 10 kΩ + 100 nF, 220 pF HF cap** — starting
  values: DCM current-mode flyback is a single-pole system (load pole ≈6 Hz
  with 4.7 µF); this places the zero ≈160 Hz and crosses over ~1 kHz.
  Marked for bench verification with a load-step test — compensation is the
  one section where calculation only gets you to the starting line.

## 11. Layout rules (order of importance)

1. **Primary hot loop**: input ceramic → primary bus → FET drain; FET source
   → R_CS → back to ceramic ground. Minimize enclosed area; all on F.Cu.
2. **Secondary hot loop**: secondary pin → UF4005 → output caps → back.
   Compact; entire loop is HV netclass (0.8 mm).
3. **Kelvin the sense resistor**: CS trace taps the resistor pad itself, not
   the FET source trace; PGND pin returns to the R_CS ground pad directly.
4. **Ground strategy**: AGND island under the IC (RT/SS/COMP/FB/UVLO
   grounds), joined to PGND at exactly one point at the EP, per datasheet.
5. **Switch node (drain + primary bottom bus + snubber) = smallest possible
   copper**; it swings 48 V at 150 kHz and is the board's EMI antenna. Keep
   FB and CS routing away from it; keep it away from the BCD lines.
6. Snubber directly across the primary pins; gate loop (GATE→R_g→gate,
   source→PGND) short.
7. The diode-anode node swings ≈ ±175 V — label it `HV_SEC`, HV netclass.
8. 7805 + colon of caps near the logic; flyback block near the display's
   +170V entry; USB-C/CH224K at the rear edge.

## 12. Schematic reference — mapping the datasheet figures to this design

Draw from **Figure 10-12 (Typical Non-Isolated Flyback, p. 33)** — our exact
topology (shared ground, direct FB divider, no optocoupler). Use **Figure 10-1
(boost, p. 27)** as the completeness checklist for the optional support parts
that 10-12 omits. Ignore 10-10 (isolated/optocoupler) and 10-11 (primary-side
regulation) — different regulation schemes.

Transformer hookup (replaces L_M): primary windings paralleled —
**pins 7/8/9/10 (dots) → VBUS, pins 3/4/5/6 → FET drain (switch node)**.
Secondary: **pin 1 (dot) → GND, pin 12 → UF4005 anode**. On-time drives all
dots positive → pin 12 below ground → diode blocks while energy is stored;
off-time reverses polarity → diode conducts into the output cap. A reversed
dot makes the diode conduct during on-time (short). Cross-check against the
DA2032 datasheet application figure when drawing.

| Fig 10-1 designator | This design | Notes |
|---|---|---|
| C_IN | 100 µF 25 V electrolytic + 4.7 µF X7R | input bulk, near primary loop |
| R_UVLOT / R_UVLOB | 143 kΩ / 32.4 kΩ | §8 |
| R_UVLOS, C_UVLO | — omit | optional hysteresis/filter extras |
| R_BIAS / C_BIAS | — / 1 µF X7R | BIAS direct from VBUS |
| C_VCC | 2.2 µF X7R 16 V | at pin |
| L_M | DA2032-AL | flyback primary, hookup above |
| R_G | 10 Ω | gate damping |
| D_G | — omit | turn-off speedup; unneeded at 150 kHz |
| Q1 | IRL540N | §3 |
| R_S | R_CS = 39 mΩ 1 % | §2, Kelvin-routed |
| R_SL | — omit | slope comp is a CCM need; we are DCM |
| R_F / C_F | 100 Ω / 470 pF | CS leading-edge spike filter — keep |
| R_SNB / C_SNB (across D1) | — replaced | primary RCD clamp 27 kΩ/10 nF/UF4004, §9 |
| D1 | UF4005 | on the secondary; blocks 305 V, §4 |
| C_OUT1 / C_OUT2 | 100 nF 250 V film / 4.7 µF 250 V electro | §5 |
| R_LOAD (dashed) | bleeder 470 kΩ | §6 — not in the TI design: their dashed R_LOAD just denotes the attached load. Our added part: 175 V safety discharge + guaranteed preload for socketed (removable) tubes |
| R_FBT | 2 × 866 kΩ in series | HV split, §7 |
| R_FBB | 8.87 kΩ + 2 kΩ trimmer | §7 |
| R_PG | 100 kΩ → VCC | PGOOD broken out for MCU |
| R_T | 147 kΩ 1 % | 150 kHz |
| C_SS | 47 nF | ≈4.7 ms ramp |
| R_COMP / C_COMP / C_HF | 10 kΩ / 100 nF / 220 pF | starting values, bench-verify |

## Open items

- [ ] Compensation values → bench load-step verification
- [ ] Thermal check of 7805 at 12 V input (0.7 W, bare TO-220 ≈ +35 °C)
- [ ] CH224K detail design (config resistor, CC ESD, PG wiring)
- [ ] Netclass patterns for PSU-sheet local HV nets (`HV_SEC`, switch node)

## Glossary

### Topology & operating concepts

- **Flyback** — isolated converter that stores energy in a transformer's
  primary during the switch on-time, then dumps it to the secondary during
  off-time. Enables large step-up from a low input.
- **Boost** — non-isolated step-up converter (single inductor). The rejected
  alternative; a flyback's turns ratio shares the step-up burden with duty
  cycle, lowering switch voltage stress.
- **CCM** — Continuous Conduction Mode: transformer current never reaches zero
  within a cycle. Higher power density, but adds a right-half-plane zero and
  diode reverse-recovery loss.
- **DCM** — Discontinuous Conduction Mode: transformer fully de-energizes each
  cycle (current returns to zero with idle time to spare). Chosen here for
  simpler compensation and no reverse-recovery loss.
- **RHP zero** — Right-Half-Plane zero: a control-loop artifact of CCM boost
  and flyback converters that makes them harder to stabilize. DCM's RHP zero
  sits at high frequency and is benign.
- **Duty cycle (D)** — fraction of the switching period the FET is on.
- **Demagnetization / demag (t_dis)** — the off-time interval during which the
  secondary delivers stored energy to the output; transformer flux "resets."
- **Reflected voltage (V_refl)** — output voltage as seen from the primary,
  divided by the turns ratio (here 175 V / 10 = 17.5 V). Adds to V_in as
  switch-off stress on the FET.
- **RCD snubber** — Resistor-Capacitor-Diode network across the primary that
  captures the leakage-inductance spike at switch-off and clamps it to a safe
  level. Contrast **RC** (resistor-capacitor damping) and **TVS** (a clamping
  diode).
- **Soft-start (SS)** — controlled ramp of the output at power-up to avoid
  inrush and overshoot.
- **UVLO** — Under-Voltage Lockout: the controller stays off until its input
  rises above a programmed threshold (and turns off again below a lower one —
  the **hysteresis**). Here it gates the converter to PD voltages only.
- **PD** — USB Power Delivery: the negotiation protocol that requests voltages
  above the default 5 V over the USB-C **CC** (Configuration Channel) lines.
- **NOS** — New Old Stock: unused vintage components (the Soviet tubes),
  whose exact strike voltage we could not verify — hence the output trimmer.

### Electrical quantities (subscript symbols)

- **V_IN / V_OUT** — converter input / output voltage.
- **V_REF** — the LM5155's internal 1.000 V feedback reference.
- **P_IN / P_OUT** — input / output power; **η** (eta) — efficiency, P_out/P_in.
- **f_sw** — switching frequency; **T** — its period (1/f_sw).
- **t_on** — FET on-time per cycle.
- **L_pri / L_sec** — primary / secondary winding inductance;
  **L_leak** — leakage inductance (the imperfectly-coupled fraction).
- **I_pk** — peak primary current each cycle; **I_rms** — root-mean-square
  (heating-equivalent) current.
- **E** — energy transferred per switching cycle.
- **τ** (tau) — RC time constant (resistance × capacitance), in seconds.
- **V_DS / V_GS** — MOSFET drain-source / gate-source voltage.
- **R_DS(on)** — MOSFET on-state drain-source resistance.
- **Q_g** — total gate charge (sets gate-drive loss and speed).
- **V_R** — diode reverse (blocking) voltage; **t_rr** — reverse-recovery time.
- **R_CS** — current-sense resistor; **V_CS-limit** — the sense voltage at
  which the LM5155 terminates the pulse (its current-limit threshold).
- **V_cl** — snubber clamp voltage.
- **ESR** — Equivalent Series Resistance: a capacitor's internal resistance,
  which turns ripple current into heat and voltage ripple.
- **EMI / HF** — Electromagnetic Interference / High Frequency.
- **ESD** — Electrostatic Discharge (the CC lines need protection against it).

### LM5155 pins & parts

- **BIAS** — external supply input for the controller's internal LDO.
- **VCC** — the controller's ~6.85 V internal rail; also the gate-drive supply.
- **GATE** — MOSFET gate-drive output.
- **CS** — Current-Sense input (reads the R_CS voltage).
- **COMP** — Compensation pin: the loop's error-amplifier output; the
  R-C network here sets loop stability.
- **FB** — Feedback: the divided-down output sensed against V_REF.
- **RT** — timing Resistor pin; its value sets f_sw.
- **PGOOD / PG** — Power-Good open-drain status flag.
- **AGND / PGND** — Analog Ground (quiet, IC reference) / Power Ground (noisy,
  switch-current return). Joined at one point to keep switching noise out of
  the sensing.
- **EP** — Exposed Pad: the thermal/ground pad under the package.
- **VBUS** — the USB-C bus voltage rail feeding the converter.
- **7805** — the classic 5 V linear regulator generating the logic rail.
- **CH224K** — the USB-C PD sink controller that negotiates 9–13 V.
- **MOSFET** — Metal-Oxide-Semiconductor Field-Effect Transistor (the switch);
  **IC** — Integrated Circuit; **BCD** — Binary-Coded Decimal (the tube
  driver's input encoding).

### Packages, footprints & materials

- **TO-220** — the common three-lead through-hole power package (FET, 7805).
- **SMD** — Surface-Mount Device; **2512 / 0805 / 0207** — package size codes
  (2512/0805 are SMD imperial sizes; 0207 is a through-hole resistor body
  length in mm).
- **X7R** — a ceramic-capacitor dielectric class: stable, good for bypass/bulk.
- **MRS25** — a 0.6 W metal-film through-hole resistor series (250 V-rated).
- **Kelvin connection** — a 4-terminal sensing scheme where the measurement
  taps a component's own pads, excluding trace/solder resistance from the
  reading. Critical for R_CS accuracy.
- **F.Cu** — KiCad's front copper layer.
- **HV netclass** — this project's design rule group for high-voltage nets
  (wider clearance/track); `HV_SEC` is the secondary/rectifier HV node.
- **SNVSB75E** — TI's document number for the LM5155 datasheet.
