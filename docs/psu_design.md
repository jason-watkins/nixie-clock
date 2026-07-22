# Power system design

## Summary

The clock runs from a USB-C Power Delivery adapter. A resistor-configured
sink controller negotiates 12 V (9 V fallback) and gates it through a
back-to-back PFET load switch. Three converters hang off the switched rail:

- a 150 kHz flyback producing the nominal 170 V tube-anode rail,
  trimmable 160-196 V
- a fixed 5 V buck for the four K155ID1 binary-coded-decimal drivers
- a fixed 3.3 V buck for the MCU (ESP32 class)

Total draw is about 3 W, dominated by 15 mA at 175 V. The board uses a
single unified ground net.

The high-voltage converter is designed to match the nixie tube aesthetic.
While it is a modern flyback for efficiency, its supporting parts are
primarily through-hole, the chunkier the better, to give the converter a
somewhat retro look. The USB-C and buck sections make no such attempt;
USB-C is anachronistic on this board by definition, so those sections
follow current SMD practice.

Where SMD parts are used, the design is meant to remain hand-solderable.
As a rule of thumb, all SMD components are 0805 or larger. Hand soldering
is the requirement, not necessarily the plan: having the fab populate the
basic parts is an equally valid build path.

## USB-PD input

### Goal and strategy

Accept any Power Delivery adapter without firmware or a host processor.
The controller is configured entirely by resistor straps: it requests 12 V
when offered, falls back to 9 V, and rejects anything else. Downstream
circuits see no voltage until a contract exists, because the output passes
through a load switch the controller only closes after negotiation. On a
plain 5 V charger the board stays off rather than browning out;
the flyback's undervoltage lockout enforces this independently of the
controller. Hot-plugging is the normal operating procedure, so the
connector lines carry dedicated electrostatic-discharge protection. A
single red LED reports faults; there is no power-good indicator because
the display itself shows normal operation.

### Driving part: CYPD3176

The CYPD3176 (Infineon EZ-PD BCR-Plus) does all Power Delivery work in
hardware. Configuration:

| Strap | Setting | Divider (from VDDD) |
|---|---|---|
| VBUS_MIN | 9 V | 5.1 k / 1 k |
| VBUS_MAX | 12 V | 5.1 k / 2.4 k |
| ISNK_COARSE | 1 A | 5.1 k / 1 k |
| ISNK_FINE | +0 mA | strap to ground |
| CHARGING_MODE | float | enables all legacy charger protocols |

The strap dividers source from the chip's own VDDD pin, not the 3.3 V
rail: the pins are read ratiometrically against VDDD (canceling its
tolerance), and the 3.3 V buck sits downstream of the load switch, which
closes only after the contract the straps configure. D+ and D− route from
the connector to the chip because the legacy-protocol support uses them
for charger handshakes; the signaling is quasi-static, so they need no
differential-pair treatment. The connector's duplicate D+/D− pins are
commoned at the receptacle.

The sink-side current trip (CSP pin) is disabled by tying it to VSS.
Recovering from that trip requires an I2C host command, and this board has
no host; a trip would latch the supply off until power cycle. Overcurrent
coverage comes from the adapter's own limit, the chip's overvoltage and
undervoltage monitors, and each converter's cycle-by-cycle current limit.

FAULT drives the indicator LED. It asserts on any failed or lost contract
(no agreement, voltage out of window, insufficient offered current).

### Load switch

Two P-channel MOSFETs share a common gate, sources tied together, so
their body diodes oppose and block in both directions when off. The
chip's VBUS_CTRL output drives the gate with a microamp-class controlled
slew, which is the inrush limiter for the downstream capacitor bank. Gate
network: 1 kΩ series from VBUS_CTRL, 49.9 kΩ gate-source, 10 kΩ gate
pull-up to the raw bus for default-off, two 1 µF ramp capacitors, and a
10 V gate-source zener to protect the gate oxide during surge clamping.

Part requirements: dual PFET, drain-source rating of −30 V so the TVS
clamp voltage (about 24 V) lands inside it, gate-source rating of ±20 V
because the driver swings the gate the full rail, and on-resistance under
100 mΩ per device (the DMP3085LSD class fits). Switching speed is
irrelevant.

### Protection and support sizing

**Bus transient suppressor.** Three voltages define it: standoff at or
above the 13 V maximum rail so it never conducts in operation, breakdown
above standoff, and clamp below every victim rating downstream (the
−30 V switch pair, the flyback controller's 45 V BIAS pin, 25 V
capacitors). A 15 V-standoff unidirectional part clamping near 24 V
satisfies all three.

**Line protection.** One 5 V-standoff unidirectional
electrostatic-discharge diode per line on CC1, CC2, D+, and D−, placed in
the trace path at the connector. These cover discharge strikes only;
VBUS-to-CC cable faults are within the CC pins' 22 V rating.

**Fault LED.** 220 Ω from the FAULT pin. At the pin's guaranteed drive
point (4 mA at VDDD − 0.6 V, roughly 150 Ω effective pin impedance) the
LED runs near 4 mA; a shorted LED draws 9 mA against a 25 mA pin limit.
The LED must be red: only about 2.7 V of drive is guaranteed, which rules
out higher-forward-voltage colors.

**Bypass.** 4.7 µF plus 1 µF on the raw bus at the connector (inside the
USB-C spec's 1-10 µF attach window; capacitance behind the load switch
does not count against it), 1 µF plus two 100 nF on VDDD, 1 µF on VCCD.

## HV flyback converter

### Goal and strategy

Produce the tube-anode rail: nominally 175 V at up to 15 mA (four digits
at 3 mA plus two colon lamps at 0.7 mA is 13.4 mA). The output is
adjustable 160-196 V with a multiturn trimmer to account for unreliable
strike voltage in new-old-stock Soviet tubes.

The converter is a current-mode flyback running in discontinuous
conduction, meaning the transformer transfers all stored energy to the
output every cycle and idles at zero current before the next one. The
mode simplifies the control loop and eliminates diode reverse-recovery
loss. The design window for input is 8.5-13 V,
covering both negotiated voltages with margin.

The converter enables only above 8.1 V input, so a non-Power-Delivery
source leaves the high-voltage section cleanly off.

### Driving parts and configuration

**LM5155** (TI current-mode boost/flyback controller): 1.000 V feedback
reference, 100 mV current-limit sense threshold, 6.85 V internal
gate-drive rail, 45 V-rated BIAS input fed directly from the bus.
Configured for 150 kHz (RT = 147 kΩ), 4.7 ms soft-start (47 nF),
undervoltage lockout via a 143 kΩ / 32.4 kΩ divider (on at 8.1 V, off
near 7.4 V from the pin's 5 µA hysteresis current). PGOOD is pulled up to
VCC through 100 kΩ and broken out for the MCU.

**DA2032-AL** (Coilcraft flyback transformer): 1:10 ratio, 10 µH primary,
3 A peak rating, 0.15 µH maximum leakage. Primary windings paralleled;
secondary returns to the common ground (non-isolated use, shared-ground
feedback). The output reflects 17.5 V onto the primary during
demagnetization.

### Key sizing

**Operating point.** P_out = 2.63 W; at an assumed 85 % efficiency,
P_in ≈ 3.1 W (360 mA at 9 V). Energy per cycle 20.6 µJ gives a 2.0 A
primary peak. Worst-case conduction check at 8.5 V input: 2.39 µs on-time
plus 1.16 µs demagnetization is 3.55 µs of the 6.67 µs period, deep in
discontinuous conduction everywhere.

**Current sense.** 39 mΩ, 1 %. The controller's 100 mV ±7 % threshold
puts the current limit at 2.38-2.74 A: 17 % above the operating peak,
9 % under the core's 3 A rating. Dissipation 19 mW. The sense connection
is Kelvin-routed: the sense trace taps the resistor's own pads so trace
and solder resistance stay out of the measurement.

**Switch.** Off-state stress is input plus reflected voltage plus the
clamped leakage spike, about 48 V worst case. A 100 V logic-level TO-220
FET (IRL540N fits) leaves better than 2× margin. Losses total roughly
0.15 W (conduction 40 mW, gate 73 mW, small switching loss since turn-on
happens at zero current), no heat sink. A 10 Ω series gate resistor damps
the gate loop; turn-on at zero current means the slower edge adds no loss.

**Rectifier.** Reverse stress is V_out plus the turns ratio times maximum
input: 175 + 130 = 305 V, so a 600 V part. It must be ultra fast (about
75 ns recovery); a standard-recovery rectifier at 150 kHz would dissipate
watts. Average current is trivial. A UF4005-class axial part fills the
slot.

**Snubber.** Leakage inductance dumps 0.31 µJ per cycle (46 mW) at
switch-off. A resistor-capacitor-diode clamp across the primary holds the
spike 45 V above the input rail: 27 kΩ (0.5 W part), 10 nF film, and a
fast 100 V diode. The clamp voltage is deterministic, and at this leakage
energy the parts run well inside their ratings.

**Output capacitance.** 4.7 µF 250 V solid polymer plus 100 nF 250 V
film. Droop between demagnetization pulses is 21 mV; capacitance is not
the constraint. The polymer part's equivalent series resistance (its
internal resistance, about 0.5 Ω) lets through 100 mV edges, which the
film bypass absorbs. Polymer rather than wet electrolytic eliminates the
dry-out wear mechanism; the 250 V rating keeps 32 % margin at the trim
ceiling.

**Input capacitance.** 100 µF polymer plus 4.7 µF ceramic at the primary
loop. The 2 A triangular primary pulses must come from local capacitance,
not the cable; ripple demand is about 0.6 A against a multi-amp rating.

**Feedback divider.** Sized for about 100 µA of divider current. The top
leg is two 866 kΩ resistors in series so each body sees 87 V, inside the
element rating of a standard through-hole resistor (small chip resistors
are rated 50-75 V per element, so the divider is through-hole).
Bottom leg 8.87 kΩ plus a 2 kΩ multiturn trimmer spans 160-196 V.

**Bleeder.** 470 kΩ across the output serves two purposes: it discharges
the rail below 50 V within about 3 s of unplugging (2.2 s time constant),
and its 0.37 mA is a minimum load that keeps the loop in regulation with
the tubes unplugged from their sockets. 65 mW, 250 V-rated body.

**Compensation.** The error-amplifier network is 10 kΩ and 100 nF with a
220 pF high-frequency capacitor cancelling the output capacitor's
equivalent-series-resistance zero. Against the roughly 6 Hz load pole
this places the loop zero near 160 Hz and crossover near 1 kHz.

### Bench tuning

The compensation values are starting values. To verify: step the load
between blanked and full display (or switch a resistive dummy load) while
watching the rail. The target is monotonic
recovery with no ringing. If the response rings, increase the 100 nF or
reduce the 10 kΩ; if it is sluggish and margin allows, raise the 10 kΩ.

Two other bench checks. Strike voltage: raise the
trimmer until every digit of the actual tube stock strikes reliably, then
set the rail about 10 V above that point. Lockout: on a 5 V source the
converter must remain completely off.

## LV buck converters

### Goal and strategy

Two copies of one synchronous buck block, identical except for the
regulator: 5 V for the binary-coded-decimal drivers (about 0.1 A, nearly
static), 3.3 V for the MCU (ESP32-class Wi-Fi bursts of 300-500 mA). Identical blocks keep the bill of materials to one set of
support parts. Both rails are switched rather than linear: at 12 V input
a linear 5 V regulator dissipates more power than it delivers, and the
3.3 V rail must supply Wi-Fi bursts without sagging.

The K155ID1 drivers are TTL, which accepts 3.3 V CMOS logic levels
directly (2.0 V input-high threshold), so the rails need no level
shifting between them.

Both bucks switch at 1.1 MHz, two decades above the flyback; the
converters do not interact.

### Driving parts and configuration

AP63205 (5 V) and AP63203 (3.3 V): fixed-output synchronous bucks,
TSOT-26, 2 A rated, internally compensated, 1.1 MHz, built-in 4 ms
soft-start, 22 µA quiescent. Per block: feedback pin tied directly to the
output (fixed-output variants), enable tied to input (auto-start;
sequencing is handled upstream by the load switch), 100 nF bootstrap
capacitor between BST and SW.

### Key sizing

**Inductor.** 4.7 µH, the same part on both rails. Ripple at
12 V input is 0.56 A on the 5 V rail and 0.46 A on 3.3 V, 23-28 % of the
2 A rating. Saturation current must exceed the regulator's worst-case
3.1 A cycle-by-cycle limit (not the load), since the limit is ineffective
once the inductor saturates; the part is specified at 4 A. Shielded or semi-shielded construction, placed away from
the Configuration Channel lines and feedback nets.

**Input capacitor.** 10 µF, 25 V, X7R per block. At 12 V bias a
small-case ceramic delivers roughly half its rated capacitance;
acceptable at these loads with the attach capacitance on the same rail
upstream.

**Output capacitors.** Two 22 µF, 25 V per block. After bias derating
the banks deliver about 26 µF effective at 5 V and 33 µF at 3.3 V,
against a load-transient requirement of 9.5 µF and 21 µF respectively at
the full 2 A rating, inside the recommended 22-68 µF window.
The 25 V rating preserves the capacitance: derating scales with the
fraction of rated voltage in use.
