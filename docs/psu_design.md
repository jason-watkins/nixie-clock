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

## 13. USB-C PD front end — CYPD3176 (EZ-PD BCR-PLUS)

Style ruling for this whole section: **modern SMD, no retro-styling** — USB-C
is anachronistic on this board by definition, so it is built to current
industry practice. Hand-solder floor: 0805 passives (prefer 1206 for anything
with a job), no 0402/0603.

- **Connector: JAE DX07S016JA1R1500** (16-pin USB-C receptacle; stock
  footprint `Connector_USB:USB_C_Receptacle_JAE_DX07S016JA1R1500`, symbol
  `Connector:USB_C_Receptacle_USB2.0_16P`). D+/D− wired to the BCR for legacy
  fast-charge protocols. Buy 3 (practice/spare).
- **Controller: CYPD3176** (`nixie_clock:CYPD3176` symbol, vendored QFN-24
  footprint with fixed 3D model). Resistor-configured, no firmware.
- **Negotiation window: 9–12 V** — VBUS_MIN = 9 V, VBUS_MAX = 12 V; BCR takes
  the highest offer in-window (12 V when available, 9 V fallback — matches the
  flyback's 8.5–13 V design envelope exactly). 12 V is the PD-optional rung;
  9 V is effectively universal, so every ≥15 W adapter works.
- **Config straps** (Table 2/3/4, dividers from VDDD 3.3 V, 1206 1 %).
  All divider tops tie to the **VDDD pin (23)** — the figures' "VDDIO" label
  means this pin. It must NOT be the AP63203 rail: (a) straps are read
  ratiometrically against VDDD, so sourcing from VDDD cancels its tolerance;
  (b) fatal sequencing — the 3.3 V buck is downstream of the load switch,
  which closes only after the contract the straps configure. VDDD is alive
  from raw 5 V VBUS during negotiation.
  | Pin | Setting | Pull-up | Pull-down |
  |---|---|---|---|
  | VBUS_MIN | 9 V | 5.1 kΩ | 1 kΩ |
  | VBUS_MAX | 12 V | 5.1 kΩ | 2.4 kΩ |
  | ISNK_COARSE | 1 A | 5.1 kΩ | 1 kΩ |
  | ISNK_FINE | +0 mA | open | 0 Ω (strap to GND) |
  | CHARGING_MODE | float | — | — (enables all legacy protocols) |
  | DATAMODE/FLIP | no-data app | 1 kΩ to VDDD | — |
- **Load switch: populated** (modern practice; slew-limited gate driver =
  inrush control into the 100 µF bank; fast disconnect on OVP/UVP).
  Back-to-back PFET pair on VBUS_CTRL per Fig. 4 (series gate R + 49.9 kΩ
  G-S R; sources tied at mid-node, gates common, body diodes opposed).
  Criteria: dual PMOS SO-8, **V_DS −30 V required** (SMAJ15A clamps at
  24.4 V across the off pair — 20 V parts sit inside the clamp window),
  **V_GS abs max ±20 V** (Table 20: gate driver pulls gate to ground with
  source at VBUS → V_GS up to −12.6 V; excludes ±8/±12 V parts; logic-level
  threshold NOT required — full-rail drive), R_DS(on) ≤ 100 mΩ @ −4.5 V
  (two in series ≤ 0.1 V @ 0.5 A). Gate charge/speed irrelevant (µA
  slew-controlled drive is the inrush-control feature).
  **SAFE_PWR branch: unpopulated** (exists to power
  notification logic we don't have); SAFE_PWR_EN unconnected.
- **CSP: tied directly to VSS — shunt omitted, sink OCP disabled by design.**
  The reference's 5 mΩ sits in the ground return (the only reason its
  TYPE-C_GND/SYSTEM_GND split exists), and OCP recovery requires an I2C host
  command we have no host to send — a tripped OCP would latch the board dark
  until power-cycle. Protection is redundant anyway: fixed characterized load,
  adapter OCP, BCR OVP/UVP (via VBUS_IN_DIS, unaffected), flyback
  cycle-by-cycle limit. Single unified GND net preserved.
- **Protection:** SMAJ15A unidirectional TVS across VBUS at the connector
  (15 V standoff > 13 V max rail; clamp ~24 V < 45 V BIAS / 25 V cap limits);
  **4 × ST ESDA051 (SOD-323, 5 V standoff, uni, 12.8 V clamp)** — one each on
  CC1, CC2, D+, D−. Hot-plug is this board's normal operating procedure.
  USBLC6-2SC6 was **rejected**: its pin-5 "VBUS" rail carries an internal
  6 V zener (DS4260 §1 V_BR row) — fatal on a 9–12 V PD rail — and no rail
  on this board satisfies it (+5 V is dead during the D± handshake and would
  load it via the steering diodes; VDDD sits at zero margin vs its clamp).
  CC-line scope note: 5 V-standoff parts cover ESD only; VBUS-to-CC cable
  faults are handled on-chip (22 V-rated CC pins + built-in short protection).
- **Bypass** (X7R 0805): VDDD 1 µF + 2×100 nF, VCCD 1 µF, VBUS_IN_DIS
  3.3 µF + 1 µF (≥25 V on VBUS-side caps).
- **Indicator: single FAULT LED** — red 1206 + 220 Ω from FAULT pin
  (sized at the GPIO's guaranteed 4 mA / V_OH = VDDD−0.6 V spec point with
  ~150 Ω pin impedance included; worst-case shorted-LED current 9 mA vs
  25 mA pin abs-max — inherently safe). Red is electrically mandatory:
  only ~2.7 V guaranteed drive. FAULT → 220 Ω → anode; cathode → GND
  (drives high on: no contract, no in-window voltage, insufficient current,
  VBUS out of limits, sink OCP). Deliberately *bright*: it only lights in
  alarm states. Silk `PD FAULT`. No "PD OK" pilot — the tubes are the pilot
  light. HPI_INT/SDA/SCL unconnected (no SOC).
- **D+/D−: wired, not NC** — they carry the legacy fast-charge handshake
  (the reason the 3176 was chosen over the 3177). Common the connector's
  duplicate pairs (A6+B6, A7+B7) at the receptacle, route to pins 5/6.
  Not USB data — quasi-static signaling, no diff-pair discipline.
- **DC_OUT_DIS** wires to the switched (output) side of the FET pair — the
  chip's output-voltage monitor.

### 13.1 Front-end BOM summary

| Item | Package | Role | Status |
|---|---|---|---|
| JAE DX07S016JA1R1500 | USB-C 16P | connector (buy 3) | PN final |
| CYPD3176-24LQXQ | QFN-24 | PD sink controller | PN final |
| SMAJ15A (Littelfuse) | SMA | VBUS TVS | PN final |
| MM3Z10 (onsemi) 10 V ±2 % zener | SOD-323 | load-switch G-S clamp (conducts ~0.9 mA continuously at 12 V contracts — by design) | PN final |
| ST ESDA051 ×4 | SOD-323 | CC1/CC2/D+/D− ESD | PN final (note exact suffix) |
| dual PFET **DMP3085LSD-13** (Diodes) −30 V, V_GSS ±20 V, 95 mΩ max @ −4.5 V (≈50–70 mΩ at our −9 V drive) | SO-8 | load switch | PN final |
| ~~5 mΩ shunt~~ | — | ~~CSP sense~~ — CSP tied to VSS, OCP disabled | deleted |
| red LED | 1206 | PD FAULT | PN pending |
| 5.1 kΩ ×3, 1 kΩ ×3, 2.4 kΩ, 0 Ω, 680 Ω | 1206 | straps/LED | commodity |
| 49.9 kΩ + series gate R (verify vs Fig. 4) | 1206 | FET gate network | verify |
| 3.3 µF ≥25 V; 1 µF ×3; 100 nF ×2 | 1206/0805 X7R | bypass | commodity |

## 14. Logic rails — twin bucks (5 V and 3.3 V)

Linear 7805 dropped (0.4–0.7 W input-dependent loss) in favor of two copies
of one synchronous-buck block, identical except the IC:

- **+5 V: AP63205** (fixed 5 V, TSOT-26, 2 A capable) — feeds the four
  K155ID1s and nothing else. **No level shifters needed for the MCU phase**:
  the K155ID1 is standard TTL (V_IH = 2.0 V absolute), so 3.3 V CMOS GPIO
  drives the BCD inputs directly (GPIO sinks ~1.6 mA per input low —
  trivial). Verify V_IH on the К155ИД1 datasheet at MCU-phase start.
  Load profile: ~0.1 A, static (digit changes are tens-of-mA steps at 1 Hz)
  — a single 22 µF output cap would suffice; we keep 2×22 for twin-block
  BOM symmetry with the 3.3 V rail, whose ESP32-class burst load
  (300–500 mA, sub-ms) genuinely needs both caps.
- **+3.3 V: AP63203** (same family/footprint/support parts) — feeds the
  future MCU section; retires the dangling `+3V3` net (R206 PGOOD pullup).
  Chosen over an LDO-from-5V so the rail survives any MCU choice including
  Wi-Fi-class burst loads.
- Support per block, **verified against AP632XX.pdf** (Fig. 1/21 typical
  application, both blocks identical):
  - **L = 4.7 µH** shielded SMD (datasheet window 2.2–10 µH; spec
    I_sat ≥ 2.5 A — sized to the chip's 2 A capability, not our load, so the
    BOM line survives any future loading; low DCR for efficiency)
  - **C_IN = 10 µF** X7R ≥25 V 1206 (input is up to 13 V V_BUS)
  - **C_OUT = 2 × 22 µF** X7R 16 V 1206 (datasheet calls for two — cap count
    scales with ripple current, and the vendor sized for the full 2 A)
  - **C_BST = 100 nF** 0805 between BST and SW
  - **FB ties directly to VOUT** (fixed-output variants — no divider)
  - **EN: leave open or tie to VIN** (auto-start; the 1.18 V precision
    threshold is for optional UVLO we don't need — sequencing is handled
    upstream by the BCR's load switch)
  - Built-in 4 ms soft-start (no inrush interaction with the BCR's
    slew-limited FET turn-on); 22 µA quiescent.
- **No library work:** stock symbols `Regulator_Switching:AP63203WU` /
  `AP63205WU` + stock TSOT-23-6 footprint.
- Both bucks run ~1.1 MHz — two decades from the flyback's 150 kHz, no
  interaction. TTL K155ID1s are indifferent to switcher ripple.

## Open items

- [ ] Compensation values → bench load-step verification (flyback COMP network)
- [ ] Source pending PNs: red LED,
      buck inductor (4.7 µH, I_sat ≥ 2.5 A, shielded)
- [x] Gate network confirmed from Fig. 4: 1 kΩ series (VBUS_CTRL→gates),
      49.9 kΩ gate–source, 10 kΩ gate→VBUS_C default-off pull-up, 1 µF
      gate→VBUS_C + 1 µF gate→V_BUS (ramp integrator), MM3Z10 G-S clamp
- [ ] Draw the input-power sheet (BCR + protection + load switch + twin bucks)
- [ ] Verify netclass patterns cover input-sheet nets (raw V_BUS at connector
      vs. switched V_{BUS}; new sheet-path prefixes)
- [ ] MCU phase: verify К155ИД1 V_IH = 2.0 V (enables direct 3.3 V GPIO
      drive, no level shifters); wire 16 dangling BCD labels; +3V3 loads

Resolved since first written: ~~7805 thermal check~~ (7805 replaced by twin
bucks, §14); ~~CH224K detail design~~ (CYPD3176 selected and designed, §13).

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
- **TVS** — Transient Voltage Suppressor: an avalanche diode optimized for
  absorbing brief high-energy surges (loose voltage tolerance, huge peak
  power) rather than precision. Invisible below its standoff voltage; clamps
  hard above breakdown. Contrast zener (precision, milliwatts).
- **Buck (converter)** — step-down switching regulator; *synchronous* means
  both switches are FETs (no diode), raising efficiency.
- **LDO** — Low-DropOut linear regulator: quiet, simple, dissipates
  (V_in − V_out) × I as heat. The rejected alternative for the 3.3 V rail.
- **PFET / PMOS** — P-channel MOSFET; conducts when its gate is pulled below
  its source. Used back-to-back (sources tied) as a load switch so the two
  body diodes block in both directions when off.
- **OVP / UVP / OCP** — Over-Voltage / Under-Voltage / Over-Current
  Protection.
- **BCR** — Barrel Connector Replacement: Infineon's name for the CYPD317x
  family (a PD sink that turns USB-C into a plain DC rail).

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
- **QFN** — Quad Flat No-lead: leadless SMD package with pads under the body
  edges plus an exposed pad (CYPD3176). **SOT-23 / TSOT-26** — small
  gull-wing SMD transistor/IC packages, ~0.95 mm pitch, hand-solderable
  (AP6320x bucks). **SO-8 / SOIC-8** — 8-pin gull-wing SMD, 1.27 mm pitch
  (the dual-PFET load switch).
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
