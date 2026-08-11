"""
170 V flyback converter loss-model / efficiency convergence, reproducing the
iterative procedure in docs/design_analysis/sections/05_hv_converter.tex
sec:hv-op onward (guess eta, compute P_in and I_pk, evaluate each loss
mechanism, recompute eta, repeat to convergence), plus the dependent
downstream figures (RCD clamp voltage, DCM demag time, secondary RMS
current, etc).

Input window is 4.75-13 V: the 5 V USB-PD contract at -5% through the 12 V
contract at +5%. The bottom of that window is below the LM5155's VCC regulator
dropout, so BIAS is fed by the charge pump modeled in pump_bias() rather than
directly from V_BUS; converge(pump=False) reproduces the alternative, in which
the gate rail sags with the input and turn-off overlap runs away.

Turn-off overlap (T_OVL) is derived, not assumed: the IRL540N datasheet
(docs/datasheets/infineon-irl540n-datasheet-en.pdf) gives Q_gd only as a
guaranteed max (38 nC, no typical) and separately gives a resistive-load
switching-time characterization (t_f = 62 ns typical at V_DD=50V, I_D=18A,
R_G=5.0 ohm external, V_GS pulse=5.0V) plus a gate-charge curve showing the
Miller plateau at V_GS ~= 3.0V. Cross-calibrating: the datasheet's own test
implies a typical Q_gd of ~62ns * (5.0-3.0)/5.0ohm ~= 25 nC (consistent with
the plateau-current model).

The gate-drive loop resistance includes the LM5155's own internal driver
pull-down resistance, R_INT: the datasheet (lm5155.pdf, Section 8.5,
"MOSFET DRIVER") gives "low-state voltage drop" = 0.15V at 100mA sourcing,
implying R_INT ~= 1.5 ohm for the pull-down (turn-off) path -- the reading
is that this row characterizes the pull-down FET by forcing an external
test current INTO the pin while the driver holds it low. (The companion
"high-state voltage drop" = 0.25V at 100mA sinking, implying ~2.5 ohm, is
read the same way for the pull-up/turn-on path; the two figures are not
identical, so this is the best available reading of a mildly ambiguous
datasheet table, not a certainty.)

Turn-off is sped up relative to turn-on by D203 (SB240S-E3/54, through-hole
DO-41 Schottky, VF ~= 0.5V estimated at these currents from its single
tabulated point of 0.55V at 2A) in series with R214 (3.3 ohm), bypassing
R211 (10 ohm, which still governs turn-on only) -- see sec:hv-op-losses and
sec:hv-switch. R214 was sized so the *initial* (pre-Miller-plateau) gate
discharge current, drawn from the fully-enhanced ~6.85V gate through
R214+R_INT+VF_diode, stays under the LM5155's own stated 1.5A peak
driver-current capability (lm5155.pdf Sec 9.3.12) with some margin, not by
the (looser) Miller-plateau current alone. Turn-on remains governed by
R211+R_INT ~= 11.5 ohm, unaffected by D203 (reverse-biased during turn-on).
Total turn-off loop resistance is R214 + R_INT ~= 4.8 ohm, which rescales
the drive rail (6.85V), plateau voltage (~3.0V), and diode drop (~0.5V) to
T_OVL_TYP ~= 36 ns and, at the guaranteed-max charge, T_OVL_MAX ~= 54 ns.

Run: python scripts/hv_loss_model.py
"""

# ---------------------------------------------------------------------------
# Fixed converter constants (unaffected by the ballast/divider rework)
# ---------------------------------------------------------------------------

F_SW = 149_400.0            # Hz, converged switching frequency (sec:hv-fsw)
V_BUS_MIN = 4.75             # V, 5 V USB-PD contract at -5% (sec:hv-converter)
V_BUS_MAX = 13.0             # V, 12 V USB-PD contract at +5%
N_TURNS = 10.0               # primary:secondary turns ratio
V_F_RECT = 1.0                # V, rectifier forward drop assumption
L_P = 10e-6                   # H, nominal primary inductance
L_LK = 0.150e-6                # H, leakage inductance (max, sec:da2032)
R_201 = 0.039                 # ohm, current-sense resistor
R_DCR_PRI = 0.013             # ohm, primary winding DCR
R_SEC_DCR = 1.60              # ohm, secondary winding DCR
THETA_JA_Q201 = 62.0           # K/W, IRL540N junction-to-ambient (datasheet max)

# IRL540N R_DS(on), derived self-consistently rather than assumed. The
# datasheet gives only two V_GS points, both maxima at T_J=25C:
# 53 mOhm @ V_GS=5.0V, 44 mOhm @ V_GS=10V (infineon-irl540n-datasheet-en.pdf
# p.2). Linearly interpolating to our actual 6.85V gate rail gives the cold
# (25C) value; the datasheet's own temperature-derating curve
# (p.3, Fig 4, "Normalized On-Resistance vs Temperature", V_GS=10V) is read
# qualitatively as ~1.0x at 25C rising to ~2.4x at 175C -- no intermediate
# points are tabulated, so a local linear read between those two anchors is
# used, which should be a reasonable approximation over the modest (12-18K)
# junction rise this design actually sees. T_AMBIENT is an assumption (no
# enclosure/thermal spec exists for this bench board); solve_r_dson() below
# iterates R_DSON against T_J self-consistently with the loss it causes.
R_DSON_5V_MAX = 0.053           # ohm, datasheet max @ V_GS=5.0V, T_J=25C
R_DSON_10V_MAX = 0.044          # ohm, datasheet max @ V_GS=10V, T_J=25C
V_GATE_DRIVE_RDSON = 6.85       # V, same gate rail used for R_DSON interpolation
R_DSON_COLD = R_DSON_5V_MAX - (V_GATE_DRIVE_RDSON - 5.0) / (10.0 - 5.0) * (R_DSON_5V_MAX - R_DSON_10V_MAX)
T_AMBIENT = 25.0                # C, assumption (bench environment, matches datasheet reference temp)

def r_dson_temp_factor(t_j):
    """Normalized R_DS(on) vs T_J, linear read of datasheet Fig 4 between its 25C and 175C anchors."""
    return 1.0 + (t_j - 25.0) * (2.4 - 1.0) / (175.0 - 25.0)

# Turn-off overlap, derived from the IRL540N datasheet gate-charge/switching
# data (see module docstring) rather than assumed.
Q_GD_TYP = 25e-9               # C, typical Miller charge (back-derived from t_f)
Q_GD_MAX = 38e-9               # C, datasheet-guaranteed max Miller charge
V_PLATEAU = 3.0                # V, Miller plateau voltage (datasheet Fig 6)
V_GATE_DRIVE = 6.85            # V, LM5155 gate-driver rail (sec:hv-house-vcc)
R211 = 10.0                    # ohm, gate-drive resistor, turn-on only (sec:hv-switch)
R_INT = 1.5                    # ohm, LM5155 internal driver pull-down resistance (lm5155.pdf Sec 8.5)
R214 = 3.3                     # ohm, turn-off speedup resistor, in series with D203 (sec:hv-switch)
VF_D203 = 0.5                  # V, SB240S-E3/54 forward drop estimated at these currents (datasheet gives only 0.55V @ 2A)


def gate_currents(v_gate=None):
    """Turn-on/turn-off gate currents and turn-off overlap at a given gate rail.

    Everything the switching loss depends on is a function of the gate rail, so
    the rail is a parameter rather than a constant: the case for the bias charge
    pump rests entirely on what these become when the rail is allowed to sag
    with the input.
    """
    v_gate = V_GATE_DRIVE if v_gate is None else v_gate
    i_on = (v_gate - V_PLATEAU) / (R211 + R_INT)
    i_off = (v_gate - V_PLATEAU - VF_D203) / (R214 + R_INT)
    i_peak = (v_gate - VF_D203) / (R214 + R_INT)
    return {
        "v_gate": v_gate, "i_on": i_on, "i_off": i_off, "i_peak": i_peak,
        "t_ovl_typ": Q_GD_TYP / i_off, "t_ovl_max": Q_GD_MAX / i_off,
    }


def r_dson_cold(v_gate=None):
    """Datasheet R_DS(on) at 25 C, interpolated (or extrapolated) to a gate rail."""
    v_gate = V_GATE_DRIVE if v_gate is None else v_gate
    return R_DSON_5V_MAX - (v_gate - 5.0) / 5.0 * (R_DSON_5V_MAX - R_DSON_10V_MAX)


_g = gate_currents()
I_GATE_ON = _g["i_on"]                  # A, turn-on plateau current (unaffected by D203)
I_GATE = _g["i_off"]                    # A, turn-off plateau current, via D203+R214
I_GATE_PEAK_INITIAL = _g["i_peak"]      # A, pre-plateau turn-off peak, vs the 1.5 A driver rating
T_OVL_TYP = _g["t_ovl_typ"]             # s, typical turn-off overlap (~36 ns)
T_OVL_MAX = _g["t_ovl_max"]             # s, worst-case turn-off overlap (~54 ns)

Q_G = 40e-9                    # C, gate charge at the 6.85 V VCC rail
I_Q = 580e-6                   # A, BIAS operating current, max (lm5156h.pdf p.5)

# ---------------------------------------------------------------------------
# Auxiliary bias charge pump (sec:hv-house-pump)
#
# The internal VCC regulator's 6.85 V output is specified at V_BIAS = 8 V. Tied
# straight to V_BUS, BIAS falls to 4.75 V at the bottom of the input window, the
# regulator drops out, and the gate rail follows the input -- which triples
# turn-off overlap, the converter's largest single loss. A capacitive charge
# pump off the switch node holds BIAS above the regulator's dropout across the
# whole window.
#
#   drain --C_PUMP-- Y --R_PUMP-- X --D_PUMP--> BIAS -- C_BIAS -- GND
#                                 |             ^
#                            D_RESET to GND     +-- D_START (Schottky) from V_BUS
#
# On-time: the drain sits near ground, D_RESET clamps X at -VF, and C_PUMP
# resets to V_C = V_DS(on) + VF_RESET ~= 0.9 V.
# Off-time: the drain steps to the reflected shelf V_BUS + V_refl, carrying Y
# with it; D_PUMP conducts until X falls to BIAS + VF_PUMP.
#
# Per-cycle charge demand is fixed by the controller, not by the pump:
#   Q_BIAS = Q_G + I_Q/f_sw
# so the pump self-regulates. Its equilibrium output is
#   BIAS = V_shelf - V_C_RESET - VF_PUMP - Q_BIAS/(k*C_PUMP)
# with k = 1 - exp(-t_dem/(R_PUMP*C_PUMP)) the fraction of the packet actually
# delivered inside the demagnetization window.
#
# NOTE ON EFFICIENCY: C_PUMP does not affect the pump's loss. The charge is
# drawn from the switch node at V_shelf and leaves at the 6.85 V VCC rail, so
# the overhead is Q_BIAS*f_sw*(V_shelf - 6.85) whatever C_PUMP is; a smaller
# C_PUMP merely moves loss out of the internal LDO and into R_PUMP. Relative to
# feeding BIAS from V_BUS the pump therefore costs I_BIAS * V_refl, flat across
# the input window. C_PUMP is sized for delivery margin at the worst corner, and
# BIAS is kept low to bound the controller's own internal dissipation, not to
# save power.
C_PUMP = 4.7e-9                # F, pump coupling capacitor (C0G)
R_PUMP = 82.0                  # ohm, spike-rejection / peak-current-limit resistor
V_C_RESET = 0.9                # V, C_PUMP voltage at the end of the on-time
VF_PUMP = 0.7                  # V, D_PUMP forward drop
VF_START = 0.4                 # V, D_START Schottky forward drop
V_BIAS_DROPOUT = 8.0           # V, datasheet's specification point for the 6.85 V VCC output
V_VCC = 6.85                   # V, regulated gate rail
V_LDO_DROPOUT = 0.15           # V, assumed VCC regulator dropout once V_BIAS falls below its spec point

Q_BIAS = Q_G + I_Q / F_SW      # C, charge the controller draws from BIAS each cycle
I_BIAS = Q_BIAS * F_SW         # A


def pump_bias(v_bus, v_refl, t_dem, c_pump=C_PUMP, q_bias=None):
    """Equilibrium BIAS voltage, and whether the pump or D_START is the source."""
    q_bias = Q_BIAS if q_bias is None else q_bias
    v_shelf = v_bus + v_refl
    k = 1.0 - 2.718281828459045 ** (-t_dem / (R_PUMP * c_pump))
    v_pump = v_shelf - V_C_RESET - VF_PUMP - q_bias / (k * c_pump)
    v_start = v_bus - VF_START
    if v_pump > v_start:
        return v_pump, "pump", v_shelf, k
    return v_start, "D_START", v_shelf, k
R212 = 30_000.0               # ohm, clamp resistor (sec:hv-clamp, sized for 20% switch-voltage margin at the current-limit corner)
ESR_IN = 0.04                  # ohm, input bulk capacitor ESR
ESR_OUT = 0.496                # ohm, C204 (KEMET A759KS475M2EAAE496) ESR @ 100kHz/20C
CORE_LOSS = 0.050              # W, fixed core-loss allowance

# ---------------------------------------------------------------------------
# Ballast/divider-derived load currents (sec:hv-load, sec:hv-divider)
# ---------------------------------------------------------------------------

V_M_DIGIT = 145.0             # IN-12B maintaining voltage, typical
V_K_EXPECTED = 1.0            # K155ID1 expected on-drop
V_K_DRIVER_MAX = 2.5          # K155ID1 datasheet max on-drop (spec'd at 7 mA)
R_A_DIGIT = 10.00e3           # specified digit ballast (ohm)

# INS-1 colon lamps. The datasheet gives maintaining voltage only as a ceiling
# (<= 55 V), which is the pessimistic choice for the computed current, and no
# rated current band at all -- only a 0.5 mA brightness optimum. Their cathodes
# return directly to ground, so no driver drop enters (sec:hv-load-colon).
V_M_COLON = 55.0              # INS-1 maintaining-voltage ceiling
R_A_COLON = 240e3             # specified colon ballast (ohm)

R_BLEEDER = 1.5e6              # R202, sized in sec:hv-bleeder for 1.8s to 60V (IEC 62368-1 ES1)
R_DIVIDER = 1.69e6 + 8.87e3   # R203+R204+R205 at the specified row's nominal point (approx, upper leg dominates)
V_REF = 1.0

def digit_current(v_out):
    """Per-tube digit cathode current (A) at v_out (V), specified 10 kOhm ballast."""
    return (v_out - V_M_DIGIT - V_K_EXPECTED) / R_A_DIGIT

def colon_current(v_out):
    """Per-tube colon anode current (A) at v_out (V), specified 240 kOhm ballast."""
    return (v_out - V_M_COLON) / R_A_COLON

def bleeder_current(v_out):
    return v_out / R_BLEEDER

def divider_current(v_out):
    return (v_out - V_REF) / R_DIVIDER

def total_output(v_out, digit_current_override=None, colon_current_override=None):
    """
    Total load current/power at v_out. digit_current_override lets the
    design-max point force every digit tube to its own rated maximum
    (3.5 mA/tube), the design-max envelope's defining condition. The colons
    have no rated maximum to force, so they follow their ballast at v_out;
    colon_current_override exists only for sensitivity checks against a
    maintaining voltage below the datasheet's 55 V ceiling.
    """
    i_digit = digit_current_override if digit_current_override is not None else digit_current(v_out)
    i_colon = colon_current_override if colon_current_override is not None else colon_current(v_out)
    i_bleed = bleeder_current(v_out)
    i_div = divider_current(v_out)
    i_out = 4 * i_digit + 2 * i_colon + i_bleed + i_div
    p_out = v_out * i_out
    return {
        "i_digit_total": 4 * i_digit,
        "i_colon_total": 2 * i_colon,
        "i_bleed": i_bleed,
        "i_div": i_div,
        "i_out": i_out,
        "p_out": p_out,
    }

# ---------------------------------------------------------------------------
# Loss-model convergence (sec:hv-op-losses / sec:hv-op-converge)
# ---------------------------------------------------------------------------

def clamp_voltage(i_pk, v_refl):
    """Solve V_cl^2 - v_refl*V_cl - E_lk*f_sw*R212 = 0 (sec:hv-clamp)."""
    e_lk_fsw = 0.5 * L_LK * i_pk ** 2 * F_SW
    return (v_refl + (v_refl ** 2 + 4 * e_lk_fsw * R212) ** 0.5) / 2

def converge(p_out, v_bus, v_out, t_ovl=None, r_dson=None, eta0=0.85,
             iterations=8, pump=True, v_gate=None):
    """Converge the loss model at one operating point.

    v_gate defaults to the regulated 6.85 V rail. Passing pump=False without a
    v_gate models the rail the internal regulator actually produces when BIAS is
    fed from V_BUS through D_START and the regulator drops out.
    """
    if v_gate is None:
        v_gate = V_GATE_DRIVE if pump else min(V_GATE_DRIVE,
                                               v_bus - VF_START - V_LDO_DROPOUT)
    g = gate_currents(v_gate)
    if t_ovl is None:
        t_ovl = g["t_ovl_typ"]
    if r_dson is None:
        r_dson = r_dson_cold(v_gate)
    q_g = Q_G * v_gate / V_GATE_DRIVE          # gate charge scales with the rail
    i_bias = q_g * F_SW + I_Q

    eta = eta0
    v_bias = v_bus - VF_START
    bias_source = "D_START"
    k_deliver = 0.0
    for _ in range(iterations):
        p_in = p_out / eta
        e_cyc = p_in / F_SW
        i_pk = (2 * e_cyc / L_P) ** 0.5
        t_on = L_P * i_pk / v_bus
        duty = t_on * F_SW
        i_rms_pri = i_pk * (duty / 3) ** 0.5

        v_refl = (v_out + V_F_RECT) / N_TURNS
        t_dem = N_TURNS * L_P * i_pk / (v_out + V_F_RECT)
        i_s_rms = (i_pk / N_TURNS) * ((t_dem * F_SW) / 3) ** 0.5

        v_com = v_bus + v_refl
        e_off = 0.5 * i_pk * v_com * t_ovl
        p_ovl = e_off * F_SW

        p_cond_pri = i_rms_pri ** 2 * (r_dson + R_201 + R_DCR_PRI)

        # Bias charge is drawn from whichever source wins the diode OR. Through
        # the pump it enters at the switch node's shelf potential, so that, not
        # V_BUS, is what the controller's draw is charged against.
        if pump:
            v_bias, bias_source, v_shelf, k_deliver = pump_bias(
                v_bus, v_refl, t_dem, q_bias=q_g + I_Q / F_SW)
        else:
            v_bias, bias_source, v_shelf, k_deliver = v_bus - VF_START, "D_START", v_bus + v_refl, 0.0
        v_bias_src = v_shelf if bias_source == "pump" else v_bus
        p_gate = i_bias * v_bias_src

        v_cl = clamp_voltage(i_pk, v_refl)
        p_clamp = v_cl ** 2 / R212

        p_rect = V_F_RECT * (p_out / v_out)
        p_sec = i_s_rms ** 2 * R_SEC_DCR

        i_in_avg = p_in / v_bus
        ripple_sq = max(i_rms_pri ** 2 - i_in_avg ** 2, 0.0)
        p_cap_in = ripple_sq * ESR_IN
        p_cap_out = i_s_rms ** 2 * ESR_OUT

        p_loss = (p_cond_pri + p_ovl + p_gate + p_clamp + p_rect
                  + p_sec + p_cap_in + p_cap_out + CORE_LOSS)
        eta = p_out / (p_out + p_loss)

    return {
        "eta": eta, "p_in": p_in, "i_pk": i_pk, "t_on": t_on, "duty": duty,
        "i_rms_pri": i_rms_pri, "v_refl": v_refl, "t_dem": t_dem,
        "i_s_rms": i_s_rms, "v_cl": v_cl, "v_com": v_com,
        "p_ovl": p_ovl, "p_clamp": p_clamp, "p_cond_pri": p_cond_pri,
        "p_gate": p_gate, "p_core": CORE_LOSS, "p_cap": p_cap_in + p_cap_out,
        "p_rect": p_rect, "p_sec": p_sec, "p_loss": p_loss, "r_dson": r_dson,
        "v_bias": v_bias, "bias_source": bias_source, "k_deliver": k_deliver,
        "t_idle": 1 / F_SW - t_on - t_dem, "v_gate": v_gate, "t_ovl": t_ovl,
        "i_gate_peak": g["i_peak"], "q_g": q_g,
    }

# ---------------------------------------------------------------------------
# Current-sense margin (sec:hv-cs-sense), worst-case-additive and RSS
# ---------------------------------------------------------------------------

CS_THRESH_MIN = 0.093    # V, LM5155 current-limit threshold, min
CS_THRESH_TYP = 0.100    # V
R201_TOL = 0.01           # 1%
L_P_MIN = 9e-6            # H, -10% tolerance corner
I_OVS = 0.14               # A, CS-filter delay + comparator overshoot

def cs_margin(e_cyc_typ):
    """Worst-case-additive and RSS current-sense margin at the design-max point."""
    i_pk_lmin = (2 * e_cyc_typ / L_P_MIN) ** 0.5
    i_lim_min = CS_THRESH_MIN / (R_201 * (1 + R201_TOL))
    m_nom = CS_THRESH_TYP / R_201 - (2 * e_cyc_typ / L_P) ** 0.5

    d_threshold = (CS_THRESH_MIN / R_201) - (CS_THRESH_TYP / R_201)
    d_r201 = (CS_THRESH_TYP / (R_201 * (1 + R201_TOL))) - (CS_THRESH_TYP / R_201)
    d_lp = (2 * e_cyc_typ / L_P_MIN) ** 0.5 * -1 - (-(2 * e_cyc_typ / L_P) ** 0.5)
    m_wc = m_nom + d_threshold + d_r201 + d_lp
    m_rss = m_nom - (d_threshold ** 2 + d_r201 ** 2 + d_lp ** 2) ** 0.5
    return {
        "i_pk_lmin": i_pk_lmin, "i_lim_min": i_lim_min, "m_nom": m_nom,
        "d_threshold": d_threshold, "d_r201": d_r201, "d_lp": d_lp,
        "m_wc": m_wc, "m_rss": m_rss,
    }

# ---------------------------------------------------------------------------
# R_DSON self-consistency: R_DS(on) depends on T_J, T_J depends on Q201's own
# dissipation, which depends on R_DS(on). Solved against the typical
# operating point (T_OVL_TYP); the same converged r_dson is then reused for
# the worst-case-T_OVL thermal check too, since the R_DS(on) temperature
# effect is second-order next to that check's own T_OVL margin.
# ---------------------------------------------------------------------------

def solve_r_dson(p_out, v_bus, v_out, iterations=6):
    r_dson = R_DSON_COLD
    r = None
    for _ in range(iterations):
        r = converge(p_out=p_out, v_bus=v_bus, v_out=v_out, r_dson=r_dson)
        q201_diss = r["p_cond_pri"] * (r_dson / (r_dson + R_201 + R_DCR_PRI)) + r["p_ovl"]
        t_j = T_AMBIENT + q201_diss * THETA_JA_Q201
        r_dson = R_DSON_COLD * r_dson_temp_factor(t_j)
    return r_dson, r, t_j

# ---------------------------------------------------------------------------
# Switching-frequency bracket (sec:hv-fsw-choice)
#
# Both bounds move with the load, so they are solved rather than assumed: DCM
# margin closes from above (the conducting fraction grows as sqrt(f_sw)) and the
# sense-resistor window closes from below (the power-delivery ceiling
# 93mV/I_pk(Lmin) rises as sqrt(f_sw) toward the fixed 37.4 mOhm core-protection
# floor). converge() reads F_SW from module scope, so the sweep sets it.
# ---------------------------------------------------------------------------

L_P_MAX = 11e-6           # H, +10% tolerance corner (binding for DCM)
R_S_FLOOR = 0.0374        # ohm, core-protection floor (sec:hv-cs-sense)

def _at_freq(f, p_out, v_out, r_dson):
    global F_SW
    f_save = F_SW
    F_SW = f
    try:
        return converge(p_out=p_out, v_bus=V_BUS_MIN, v_out=v_out, r_dson=r_dson)
    finally:
        F_SW = f_save

def dcm_idle_fraction(f, p_out, v_out, r_dson, l_p=L_P_MAX):
    """Idle fraction of the period at the binding DCM corner (L+10%, V_BUS min)."""
    r = _at_freq(f, p_out, v_out, r_dson)
    e_cyc = r["p_in"] / f
    i_pk = (2 * e_cyc / l_p) ** 0.5
    t_on = l_p * i_pk / V_BUS_MIN
    t_dem = N_TURNS * l_p * i_pk / (v_out + V_F_RECT)
    return 1 - (t_on + t_dem) * f

def rs_ceiling(f, p_out, v_out, r_dson):
    """Power-delivery ceiling on R_HVCS, 93 mV / I_pk at minimum inductance."""
    r = _at_freq(f, p_out, v_out, r_dson)
    return CS_THRESH_MIN / (2 * (r["p_in"] / f) / L_P_MIN) ** 0.5

def _solve(fn, target, lo, hi, iterations=60):
    """Bisect a monotonically increasing fn for fn(x) = target."""
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if fn(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def freq_bracket(p_out, v_out, r_dson):
    """The four frequencies that bracket the switching-frequency choice."""
    idle = lambda f: -dcm_idle_fraction(f, p_out, v_out, r_dson)
    ceil = lambda f: rs_ceiling(f, p_out, v_out, r_dson)
    return {
        "f_dcm_fail": _solve(idle, 0.0, 100e3, 300e3),
        "f_idle_5pct": _solve(idle, -0.05, 100e3, 300e3),
        "f_rs_floor": _solve(ceil, R_S_FLOOR, 60e3, 300e3),
        "f_rs_specified": _solve(ceil, R_201, 60e3, 300e3),
    }

# ---------------------------------------------------------------------------
# Gate-rail bound (sec:hv-house-pump): the rail below which the loss/peak-current
# loop pushes the commanded peak at minimum inductance past the guaranteed
# minimum current limit, so the converter cannot deliver its rated load.
# ---------------------------------------------------------------------------

def i_pk_lmin_at_gate(v_gate, p_out, v_out):
    r = converge(p_out=p_out, v_bus=V_BUS_MIN, v_out=v_out, pump=False, v_gate=v_gate)
    return (2 * (r["p_in"] / F_SW) / L_P_MIN) ** 0.5

def gate_rail_bound(p_out, v_out):
    i_lim_min = CS_THRESH_MIN / (R_201 * (1 + R201_TOL))
    v_gate = _solve(lambda v: -i_pk_lmin_at_gate(v, p_out, v_out), -i_lim_min, 3.6, 6.85)
    r = converge(p_out=p_out, v_bus=V_BUS_MIN, v_out=v_out, pump=False, v_gate=v_gate)
    return {"v_gate": v_gate, "t_ovl": r["t_ovl"], "i_lim_min": i_lim_min,
            "v_drive_above_plateau": v_gate - V_PLATEAU - VF_D203}

# ---------------------------------------------------------------------------
# Shape of the efficiency curve (sec:hv-op-curve): loss splits into a term
# rising with the commutation voltage, a term falling with duty, and a
# peak-current term flat in line. Fitting A(V_BUS+V_refl) + B/V_BUS + C locates
# the minimum-loss input voltage.
# ---------------------------------------------------------------------------

def loss_shape(p_out, v_out, r_dson, v_bus_points=(4.75, 7.0, 9.0, 11.0, 13.0)):
    rows = []
    for vb in v_bus_points:
        r = converge(p_out=p_out, v_bus=vb, v_out=v_out, r_dson=r_dson)
        rows.append({
            "v_bus": vb, "duty": r["duty"], "eta": r["eta"], "p_loss": r["p_loss"],
            "rising": r["p_ovl"] + r["p_gate"],
            "falling": r["p_cond_pri"] + r["p_cap"],
            "flat": r["p_clamp"] + r["p_core"] + r["p_rect"] + r["p_sec"],
            "v_com": r["v_com"],
        })
    # least-squares fit of each group to its own functional form
    a = (sum(x["rising"] * x["v_com"] for x in rows)
         / sum(x["v_com"] ** 2 for x in rows))
    b = (sum(x["falling"] / x["v_bus"] for x in rows)
         / sum(1 / x["v_bus"] ** 2 for x in rows))
    return rows, a, b, (b / a) ** 0.5

# ---------------------------------------------------------------------------
# Output bleed-down (sec:hv-bleeder-discharge)
#
# After shutdown the tubes discharge C_out themselves while they still conduct,
# each behaving as its ballast in series with its own maintaining voltage, so
# each group's branch pulls the rail toward that maintaining voltage and stops.
# The INS-1's 55 V ceiling sits below the 60 V IEC 62368-1 ES1 limit, so the
# colon branch carries the rail under ES1 on its own; the resistive path only
# sets how fast. Both phases are single-pole decays toward the branch's own
# asymptote.
# ---------------------------------------------------------------------------

def _decay_time(v_start, v_end, v_inf, tau):
    from math import log
    return tau * log((v_start - v_inf) / (v_end - v_inf))

def bleed_down(c_out, r_resistive, v_start=170.0, v_target=60.0,
               n_digit=4, r_digit=R_A_DIGIT, v_m_digit=V_M_DIGIT + V_K_DRIVER_MAX,
               n_colon=2, r_colon=R_A_COLON, v_m_colon=V_M_COLON):
    """Time from shutdown to the ES1 limit, in the two phases the loads impose.

    The digit extinction point carries the K155ID1's drop; the colon cathodes
    return straight to ground, so the colon branch stops at the tube's own
    maintaining voltage.
    """
    g_res = 1 / r_resistive
    g_digit, g_colon = n_digit / r_digit, n_colon / r_colon
    # Phase 1: digits conducting, until the rail reaches their extinction point.
    # The colon and resistive branches pull the asymptote below that point, so
    # the digits do extinguish rather than approach it forever.
    g1 = g_digit + g_colon + g_res
    v_inf1 = (g_digit * v_m_digit + g_colon * v_m_colon) / g1
    tau1, v_ext_digit = c_out / g1, v_m_digit
    t1 = _decay_time(v_start, v_ext_digit, v_inf1, tau1)
    # Phase 2: colons only, down through the ES1 limit.
    g2 = g_colon + g_res
    v_inf2 = g_colon * v_m_colon / g2
    tau2 = c_out / g2
    t2 = _decay_time(v_ext_digit, v_target, v_inf2, tau2)
    return {"t_digit_phase": t1, "v_digit_ext": v_ext_digit, "tau_colon": tau2,
            "v_inf_colon": v_inf2, "t_colon_phase": t2, "t_total": t1 + t2,
            "tau_resistive_only": c_out * r_resistive}

def bleed_down_resistive_only(c_out, r_resistive, v_start=170.0, v_target=60.0):
    """Same discharge with no tubes installed -- the resistive path alone."""
    return _decay_time(v_start, v_target, 0.0, c_out * r_resistive)

# ---------------------------------------------------------------------------
# Soft start (sec:hv-ss): t_rise nominal and at its own worst case
# ---------------------------------------------------------------------------

def t_rise(c_out, eta, v_out=170.0, i_lim=None):
    i_lim = 0.100 / R_201 if i_lim is None else i_lim
    return (0.5 * c_out * v_out ** 2) / (0.5 * L_P * i_lim ** 2 * F_SW * eta)

# ---------------------------------------------------------------------------
# Operating points
# ---------------------------------------------------------------------------

def main():
    print("=== Turn-off overlap, D203+R214 network (SB240S-E3/54, R214=3.3 ohm) ===")
    print(f"  I_gate_on (turn-on, via R211) = {I_GATE_ON*1000:.0f} mA")
    print(f"  I_gate (turn-off plateau, via D203+R214) = {I_GATE*1000:.0f} mA")
    print(f"  I_gate_peak_initial (turn-off, pre-plateau) = {I_GATE_PEAK_INITIAL*1000:.0f} mA "
          f"vs LM5155 1.5A driver rating ({I_GATE_PEAK_INITIAL/1.5*100:.0f}%)")
    print(f"  T_OVL_TYP = {T_OVL_TYP*1e9:.1f} ns")
    print(f"  T_OVL_MAX = {T_OVL_MAX*1e9:.1f} ns")
    print()

    print("=== R_DS(on) self-consistency (V_GS=6.85V interpolation + T_J feedback) ===")
    print(f"  R_DSON_COLD (25C, 6.85V, interpolated) = {R_DSON_COLD*1000:.1f} mOhm")
    print()

    print("=== Design-max envelope: V_out = 191.5 V, V_BUS = 4.75 V, typical T_OVL ===")
    budget = total_output(191.5, digit_current_override=3.5e-3)
    for k, v in budget.items():
        unit = "A" if k.startswith("i_") else "W"
        print(f"  {k} = {v*1000:.2f} m{unit}")
    r_dson_converged, r, t_j_converged = solve_r_dson(p_out=budget["p_out"], v_bus=V_BUS_MIN, v_out=191.5)
    print(f"  R_DSON converged = {r_dson_converged*1000:.1f} mOhm at T_J = {t_j_converged:.0f} C "
          f"(factor {r_dson_temp_factor(t_j_converged):.3f}x cold)")
    print(f"  eta={r['eta']:.3f}, P_in={r['p_in']:.3f} W, I_pk={r['i_pk']:.2f} A")
    print(f"  t_on={r['t_on']*1e6:.2f} us, duty={r['duty']:.3f}, "
          f"I_rms_pri={r['i_rms_pri']:.2f} A")
    print(f"  v_refl={r['v_refl']:.2f} V, t_dem={r['t_dem']*1e6:.2f} us, "
          f"I_s_rms={r['i_s_rms']*1000:.1f} mA")
    print(f"  V_cl={r['v_cl']:.1f} V ({r['v_cl']/r['v_refl']:.1f}x v_refl), "
          f"V_com={r['v_com']:.1f} V")
    print(f"  BIAS={r['v_bias']:.2f} V via {r['bias_source']} "
          f"(delivery fraction k={r['k_deliver']:.3f}), t_idle={r['t_idle']*1e6:.2f} us")
    print("  Loss breakdown (mW):")
    for k in ("p_ovl", "p_clamp", "p_cond_pri", "p_gate", "p_core", "p_cap",
              "p_rect", "p_sec"):
        print(f"    {k}: {r[k]*1000:.0f}")
    print(f"    total: {r['p_loss']*1000:.0f}")
    q201_diss_typ = r["p_cond_pri"] * (r_dson_converged / (r_dson_converged + R_201 + R_DCR_PRI)) + r["p_ovl"]
    print(f"  Q201 dissipation (typ T_OVL) = {q201_diss_typ*1000:.0f} mW, "
          f"dT = {q201_diss_typ*THETA_JA_Q201:.0f} K")
    print()

    print("=== Design-max envelope: WORST-CASE T_OVL (switch thermal check) ===")
    r_wc = converge(p_out=budget["p_out"], v_bus=V_BUS_MIN, v_out=191.5, t_ovl=T_OVL_MAX, r_dson=r_dson_converged)
    print(f"  eta={r_wc['eta']:.3f}, I_pk={r_wc['i_pk']:.2f} A, p_ovl={r_wc['p_ovl']*1000:.0f} mW")
    q201_diss_wc = r_wc["p_cond_pri"] * (r_dson_converged / (r_dson_converged + R_201 + R_DCR_PRI)) + r_wc["p_ovl"]
    print(f"  Q201 dissipation (worst-case T_OVL) = {q201_diss_wc*1000:.0f} mW, "
          f"dT = {q201_diss_wc*THETA_JA_Q201:.0f} K")
    print()

    print("=== Nominal point: V_out = 170 V, typical T_OVL, design-max R_DSON reused ===")
    budget_n = total_output(170.0)
    for k, v in budget_n.items():
        unit = "A" if k.startswith("i_") else "W"
        print(f"  {k} = {v*1000:.2f} m{unit}")
    nominal = {}
    for vb in (V_BUS_MIN, 9.0, V_BUS_MAX):
        rn = converge(p_out=budget_n["p_out"], v_bus=vb, v_out=170.0, r_dson=r_dson_converged)
        nominal[vb] = rn
        print(f"  V_BUS={vb:5.2f} V: eta={rn['eta']:.3f}, P_in={rn['p_in']:.3f} W, "
              f"I_pk={rn['i_pk']:.2f} A, t_on={rn['t_on']*1e6:.2f} us, duty={rn['duty']:.3f}, "
              f"I_rms_pri={rn['i_rms_pri']:.2f} A, I_in={rn['p_in']/vb*1000:.0f} mA, "
              f"BIAS={rn['v_bias']:.1f} V ({rn['bias_source']})")
    r_n = nominal[9.0]
    print()

    print("=== Shape of the efficiency curve across the input window (design-max) ===")
    rows, a_fit, b_fit, v_min_loss = loss_shape(budget["p_out"], 191.5, r_dson_converged)
    for row in rows:
        print(f"  V_BUS={row['v_bus']:5.2f} V: duty={row['duty']:.3f}, "
              f"loss={row['p_loss']*1000:.0f} mW, eta={row['eta']:.3f} "
              f"(rising {row['rising']*1000:.0f}, falling {row['falling']*1000:.0f}, "
              f"flat {row['flat']*1000:.0f})")
    print(f"  fit: A={a_fit*1000:.1f} mW/V, B={b_fit*1000:.0f} mW.V, "
          f"loss minimized at sqrt(B/A) = {v_min_loss:.1f} V")
    print()

    print("=== Switching-frequency bracket (design-max load) ===")
    fb = freq_bracket(budget["p_out"], 191.5, r_dson_converged)
    print(f"  DCM fails (idle = 0) at {fb['f_dcm_fail']/1e3:.0f} kHz; "
          f"idle = 5% at {fb['f_idle_5pct']/1e3:.0f} kHz")
    print(f"  R_S power-delivery ceiling meets the {R_S_FLOOR*1000:.1f} mOhm floor at "
          f"{fb['f_rs_floor']/1e3:.0f} kHz; reaches the specified "
          f"{R_201*1000:.0f} mOhm at {fb['f_rs_specified']/1e3:.0f} kHz")
    for f in (fb["f_rs_floor"], fb["f_dcm_fail"]):
        print(f"  eta at {f/1e3:.0f} kHz = {_at_freq(f, budget['p_out'], 191.5, r_dson_converged)['eta']:.3f}")
    idle_nom = dcm_idle_fraction(F_SW, budget["p_out"], 191.5, r_dson_converged)
    idle_dither = dcm_idle_fraction(F_SW * 1.078, budget["p_out"], 191.5, r_dson_converged)
    print(f"  worst-corner idle fraction: {idle_nom*100:.1f}% at f_sw, "
          f"{idle_dither*100:.1f}% at the top of the dither range")
    print()

    print("=== Gate-rail bound: the rail at which I_pk(Lmin) reaches I_lim_min ===")
    gb = gate_rail_bound(budget["p_out"], 191.5)
    print(f"  I_lim_min={gb['i_lim_min']:.3f} A -> v_gate={gb['v_gate']:.2f} V, "
          f"t_ovl={gb['t_ovl']*1e9:.0f} ns, "
          f"drive above plateau={gb['v_drive_above_plateau']:.2f} V")
    print()

    print("=== Efficiency across the window at design-max load, pump vs no pump ===")
    print("    (no-pump column lets the gate rail sag with the input, which is the point)")
    for vb in (V_BUS_MIN, 5.0, 9.0, V_BUS_MAX):
        rp = converge(p_out=budget["p_out"], v_bus=vb, v_out=191.5, r_dson=r_dson_converged)
        rnp = converge(p_out=budget["p_out"], v_bus=vb, v_out=191.5, pump=False)
        print(f"  V_BUS={vb:5.2f} V: pump eta={rp['eta']:.3f} "
              f"(BIAS {rp['v_bias']:5.2f} V, gate {rp['v_gate']:.2f} V, "
              f"t_ovl {rp['t_ovl']*1e9:3.0f} ns, p_gate {rp['p_gate']*1000:3.0f} mW, "
              f"p_ovl {rp['p_ovl']*1000:3.0f} mW)")
        print(f"                 no pump eta={rnp['eta']:.3f} "
              f"(BIAS {rnp['v_bias']:5.2f} V, gate {rnp['v_gate']:.2f} V, "
              f"t_ovl {rnp['t_ovl']*1e9:3.0f} ns, p_gate {rnp['p_gate']*1000:3.0f} mW, "
              f"p_ovl {rnp['p_ovl']*1000:3.0f} mW, "
              f"driver peak {rnp['i_gate_peak']:.2f} A)")
    print(f"  pump overhead vs feeding BIAS from V_BUS at the same gate rail = "
          f"I_BIAS * V_refl = {I_BIAS*1000:.2f} mA * 19.25 V = {I_BIAS*19.25*1000:.0f} mW, "
          f"flat across the window")
    print()

    print("=== Charge pump sizing ===")
    print(f"  Q_BIAS = Q_G + I_Q/f_sw = {Q_BIAS*1e9:.1f} nC/cycle, I_BIAS = {I_BIAS*1000:.2f} mA")
    print(f"  tau = R_PUMP*C_PUMP = {R_PUMP*C_PUMP*1e9:.0f} ns "
          f"(spike t1 ~ 10 ns; t_dem {r['t_dem']*1e9:.0f} ns at design-max)")
    # Worst delivery corner: bottom of the input window at the lowest trim
    # setpoint, where the reflected shelf, the load, and therefore both the
    # pump's drive and its delivery window are all smallest. C_PUMP is taken at
    # its -5% C0G tolerance limit.
    r_lo = converge(p_out=total_output(164.8)["p_out"], v_bus=V_BUS_MIN,
                    v_out=164.8, r_dson=r_dson_converged)
    print(f"  worst corner load: {total_output(164.8)['p_out']:.3f} W, "
          f"t_dem={r_lo['t_dem']*1e9:.0f} ns, V_refl={r_lo['v_refl']:.2f} V")
    for c_tol, label in ((1.0, "nominal"), (0.95, "-5% C0G")):
        vb_pump, src, v_shelf_lo, k_lo = pump_bias(V_BUS_MIN, r_lo["v_refl"],
                                                   r_lo["t_dem"], c_pump=C_PUMP * c_tol)
        print(f"  worst corner (V_BUS {V_BUS_MIN} V, V_out 164.8 V, C_PUMP {label}): "
              f"k={k_lo:.3f}, BIAS={vb_pump:.2f} V via {src} "
              f"vs {V_BIAS_DROPOUT} V spec point")
    vb_hi, _, _, _ = pump_bias(V_BUS_MAX, (191.5 + V_F_RECT) / N_TURNS, r["t_dem"])
    print(f"  highest BIAS (V_BUS {V_BUS_MAX} V, V_out 191.5 V): {vb_hi:.2f} V "
          f"vs 60 V recommended max; internal LDO dissipation "
          f"{(vb_hi - V_VCC)*I_BIAS*1000:.0f} mW")
    i_pump_pk = (V_BUS_MAX + (191.5 + V_F_RECT) / N_TURNS - V_C_RESET - vb_hi - VF_PUMP) / R_PUMP
    print(f"  peak pump current drawn from the switch node = {i_pump_pk*1000:.0f} mA")
    print()

    print(f"=== DCM worst corner: L=11uH, V_BUS={V_BUS_MIN}V, design-max load ===")
    e_cyc = budget["p_out"] / r["eta"] / F_SW
    l_max = 11e-6
    i_pk_dcm = (2 * e_cyc / l_max) ** 0.5
    t_on_dcm = l_max * i_pk_dcm / V_BUS_MIN
    t_dem_dcm = N_TURNS * l_max * i_pk_dcm / (191.5 + V_F_RECT)
    period = 1 / F_SW
    print(f"  E_cyc={e_cyc*1e6:.2f} uJ, I_pk={i_pk_dcm:.2f} A")
    print(f"  t_on={t_on_dcm*1e6:.2f} us, t_dem={t_dem_dcm*1e6:.2f} us, "
          f"sum={((t_on_dcm+t_dem_dcm)*1e6):.2f} us = {(t_on_dcm+t_dem_dcm)/period:.2f} T")
    print(f"  t_idle={((period-t_on_dcm-t_dem_dcm)*1e6):.2f} us, "
          f"duty={t_on_dcm*F_SW:.2f}")
    print()

    print("=== Peak current at minimum inductance (design-max envelope) ===")
    i_pk_lmin = (2 * e_cyc / 9e-6) ** 0.5
    print(f"  I_pk(L=9uH) = {i_pk_lmin:.2f} A")
    print()

    print("=== R201 current-sense margin, typical-T_OVL E_cyc (worst-case-additive vs RSS) ===")
    m = cs_margin(e_cyc)
    print(f"  I_pk_Lmin={m['i_pk_lmin']:.3f} A, I_lim_min={m['i_lim_min']:.3f} A")
    print(f"  M_nom={m['m_nom']*1000:.1f} mA")
    print(f"  d_threshold={m['d_threshold']*1000:.1f} mA, d_R201={m['d_r201']*1000:.1f} mA, "
          f"d_Lp={m['d_lp']*1000:.1f} mA")
    print(f"  M_wc={m['m_wc']*1000:.1f} mA ({m['m_wc']/m['i_lim_min']*100:.1f}%)")
    print(f"  M_rss={m['m_rss']*1000:.1f} mA ({m['m_rss']/m['i_lim_min']*100:.1f}%)")
    print()

    print("=== R201 current-sense margin, WORST-CASE-T_OVL E_cyc (both efficiency and tolerance pessimistic) ===")
    e_cyc_wc = budget["p_out"] / r_wc["eta"] / F_SW
    m_wc_eta = cs_margin(e_cyc_wc)
    print(f"  E_cyc(worst T_OVL)={e_cyc_wc*1e6:.2f} uJ (vs typical {e_cyc*1e6:.2f} uJ)")
    print(f"  I_pk_Lmin={m_wc_eta['i_pk_lmin']:.3f} A, I_lim_min={m_wc_eta['i_lim_min']:.3f} A")
    print(f"  M_wc={m_wc_eta['m_wc']*1000:.1f} mA ({m_wc_eta['m_wc']/m_wc_eta['i_lim_min']*100:.1f}%)")
    print(f"  M_rss={m_wc_eta['m_rss']*1000:.1f} mA ({m_wc_eta['m_rss']/m_wc_eta['i_lim_min']*100:.1f}%)")
    print()

    print("=== Optional 4th RSS term: fold T_OVL uncertainty in as a sourced tolerance ===")
    d_tovl = m["i_pk_lmin"] - m_wc_eta["i_pk_lmin"]
    m_rss4 = m["m_nom"] - (m["d_threshold"]**2 + m["d_r201"]**2 + m["d_lp"]**2 + d_tovl**2) ** 0.5
    print(f"  d_Tovl={d_tovl*1000:.1f} mA")
    print(f"  M_rss(4-term)={m_rss4*1000:.1f} mA ({m_rss4/m['i_lim_min']*100:.1f}%)")
    print(f"  power-delivery bound (typ T_OVL basis) = "
          f"{0.093/m['i_pk_lmin']*1000:.1f} mOhm")
    print()

    print("=== R201 dissipation, bus ripple, clamped-peak-vs-Isat (design-max, typ T_OVL) ===")
    r201_diss = r["i_rms_pri"] ** 2 * R_201
    print(f"  R201 dissipation = {r201_diss*1000:.0f} mW")
    i_in_dm = r["p_in"] / V_BUS_MIN
    c_in = 105e-6
    dv_bus = (r["i_pk"]/2 - i_in_dm) * r["t_on"] / c_in + r["i_pk"] * ESR_IN
    print(f"  I_in(avg)={i_in_dm*1000:.0f} mA, bus ripple = {dv_bus*1000:.0f} mV pk-pk")
    i_lim_max = 0.107 / (R_201 * 0.99)
    clamped_peak = i_lim_max + I_OVS
    print(f"  clamped peak + overshoot = {clamped_peak:.2f} A vs 3.0 A saturation "
          f"({(3.0-clamped_peak)/3.0*100:.0f}% margin)")
    c_out = 4.8e-6
    dv_cap = budget["i_out"] * (1/F_SW - r["t_dem"]) / c_out
    i_s_pk = r["i_pk"] / N_TURNS
    dv_esr = i_s_pk * ESR_OUT
    print(f"  cap ripple = {dv_cap*1000:.0f} mV, ESR step = {dv_esr*1000:.0f} mV pk-pk")
    print()

    print("=== Loop compensation (nominal point, typ T_OVL) ===")
    r_l = 170.0 / budget_n["i_out"]
    g_comp = 0.142
    s_e = 40e-3 * F_SW
    s_n = R_201 * 9.0 / L_P
    di_pk_dvc = g_comp / (R_201 * (1 + s_e/s_n))
    di_out_di_pk = 2 * budget_n["i_out"] / r_n["i_pk"]
    g_ps = di_out_di_pk * di_pk_dvc
    g0 = g_ps * r_l / 2
    f_p = 2 / (2 * 3.14159265 * r_l * c_out)
    print(f"  R_L={r_l/1000:.1f} kOhm, dI_out/dI_pk={di_out_di_pk*1000:.2f} mA/A, "
          f"g_ps={g_ps*1000:.1f} mS")
    print(f"  G0={g0:.0f} ({20*__import__('math').log10(g0):.1f} dB), f_p={f_p:.1f} Hz")

    R210 = 10e3
    C207 = 100e-9
    C208 = 220e-12
    GM = 2e-3
    f_z = 1 / (2 * 3.14159265 * R210 * C207)
    f_hp = 1 / (2 * 3.14159265 * R210 * (C207*C208)/(C207+C208))
    h = 1/170.0
    mid_band_gain = h * GM * R210   # H * gm * R210, the compensator's flat-region gain

    import math
    def loop_mag(f, g0_):
        mag = mid_band_gain
        mag *= (1 + (f_z/f) ** 2) ** 0.5           # compensator: integrator+zero
        mag /= (1 + (f/f_hp) ** 2) ** 0.5           # compensator: high-freq pole
        mag *= g0_ / (1 + (f/f_p) ** 2) ** 0.5      # plant: DC gain + single pole
        return mag

    def solve_fc(g0_):
        lo, hi = 1.0, 100000.0
        for _ in range(200):
            mid = (lo*hi) ** 0.5
            if loop_mag(mid, g0_) > 1:
                lo = mid
            else:
                hi = mid
        return (lo*hi) ** 0.5

    def phase_margin(fc):
        return (180 - math.degrees(math.atan(fc/f_p)) - 90
                + math.degrees(math.atan(fc/f_z)) - math.degrees(math.atan(fc/f_hp)))

    f_c = solve_fc(g0)
    phi_m = phase_margin(f_c)
    print(f"  f_z={f_z:.0f} Hz, f_hp={f_hp/1000:.1f} kHz, H=1/170")
    print(f"  f_c={f_c:.0f} Hz (f_sw/{F_SW/f_c:.0f}), phi_m={phi_m:.0f} deg, "
          f"zero/f_c={f_z/f_c:.2f}, f_hp/f_c={f_hp/f_c:.0f}x")
    print()

    print("=== Soft start (design-max eta) ===")
    i_lim_typ = 0.100 / R_201
    i_lim_min = CS_THRESH_MIN / (R_201 * (1 + R201_TOL))
    e_stored = 0.5 * c_out * 170.0**2
    t_r = t_rise(c_out, r["eta"])
    # Worst case: C_out at +20%, the current limit at its guaranteed minimum
    # (which enters squared), efficiency at the pessimistic turn-off overlap.
    t_r_wc = t_rise(c_out * 1.2, r_wc["eta"], i_lim=i_lim_min)
    print(f"  I_lim(typ)={i_lim_typ:.3f} A, E_stored={e_stored*1000:.1f} mJ, "
          f"t_rise={t_r*1000:.1f} ms")
    print(f"  worst case (C+20%, I_lim {i_lim_min:.3f} A, eta {r_wc['eta']:.3f}): "
          f"t_rise_max={t_r_wc*1000:.1f} ms -> C_SS_min={t_r*10e-6/1.0*1e9:.0f} nF nominal, "
          f"{t_r_wc*10e-6/1.0*1e9:.0f} nF against the worst case")
    for c_ss in (220e-9, 470e-9):
        t_ss_min = c_ss * 0.9 * 0.99 / 11e-6
        t_ss_max = c_ss * 1.1 * 1.01 / 9e-6
        print(f"  C_SS={c_ss*1e9:.0f} nF: t_SS={c_ss*1.0/10e-6*1000:.1f} ms nominal, "
              f"{t_ss_min*1000:.1f}-{t_ss_max*1000:.1f} ms worst-case-additive "
              f"({(t_ss_min-t_r_wc)*1000:+.1f} ms vs t_rise_max)")
    print()

    print("=== Bleeder: minimum load and bleed-down (design-max eta) ===")
    i_pk_min = 13 * 165e-9 / L_P
    p_min = 0.5 * L_P * i_pk_min**2 * F_SW * r["eta"]
    print(f"  I_pk_min={i_pk_min:.3f} A, P_min={p_min*1000:.1f} mW")
    p_bleed = 170.0**2 / R_BLEEDER
    p_div = 170.0 * divider_current(170.0)
    print(f"  preload: bleeder {p_bleed*1000:.0f} mW + divider {p_div*1000:.0f} mW "
          f"= {(p_bleed+p_div)*1000:.0f} mW ({(p_bleed+p_div)/p_min:.2f}x P_min); "
          f"R_BLEED ceiling for preload = "
          f"{170.0**2/(p_min - p_div)/1e6:.2f} MOhm")
    r_par = 1 / (1 / R_BLEEDER + 1 / R_DIVIDER)
    bd = bleed_down(c_out, r_par)
    print(f"  R_BLEED || R_div = {r_par/1e3:.0f} kOhm")
    print(f"  digit phase: {bd['t_digit_phase']*1000:.0f} ms to "
          f"{bd['v_digit_ext']:.1f} V")
    print(f"  colon phase: tau={bd['tau_colon']:.3f} s toward "
          f"{bd['v_inf_colon']:.1f} V, {bd['t_colon_phase']:.2f} s to 60 V")
    print(f"  total {bd['t_total']:.2f} s vs the 2 s ES1 window "
          f"({(2-bd['t_total'])/2*100:.0f}% margin)")
    bd_div = bleed_down(c_out, R_DIVIDER)
    print(f"  divider alone (no bleeder): {bd_div['t_total']:.2f} s")
    print(f"  no tubes installed, resistive path alone: "
          f"{bleed_down_resistive_only(c_out, r_par):.2f} s")

    print()
    print("=== Efficiency lever: same switch at half the gate charge ===")
    global Q_G
    q_g_save = Q_G
    Q_G = 20e-9
    try:
        r_half = converge(p_out=budget["p_out"], v_bus=V_BUS_MIN, v_out=191.5,
                          t_ovl=T_OVL_TYP / 2, r_dson=r_dson_converged)
    finally:
        Q_G = q_g_save
    print(f"  Q_G 20 nC, t_ovl {T_OVL_TYP/2*1e9:.0f} ns: eta={r_half['eta']:.3f} "
          f"(vs {r['eta']:.3f} as specified)")


if __name__ == "__main__":
    main()
