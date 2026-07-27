"""
170 V flyback converter loss-model / efficiency convergence, reproducing the
iterative procedure in docs/design_analysis/sections/05_hv_converter.tex
sec:hv-op onward (guess eta, compute P_in and I_pk, evaluate each loss
mechanism, recompute eta, repeat to convergence), plus the dependent
downstream figures (RCD clamp voltage, DCM demag time, secondary RMS
current, etc).

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
I_GATE_ON = (V_GATE_DRIVE - V_PLATEAU) / (R211 + R_INT)   # A, turn-on plateau current (unaffected by D203)
I_GATE = (V_GATE_DRIVE - V_PLATEAU - VF_D203) / (R214 + R_INT)   # A, turn-off plateau current, via D203+R214
I_GATE_PEAK_INITIAL = (V_GATE_DRIVE - VF_D203) / (R214 + R_INT)   # A, pre-plateau turn-off peak, checked against the LM5155's 1.5A driver rating
T_OVL_TYP = Q_GD_TYP / I_GATE   # s, typical turn-off overlap (~36 ns)
T_OVL_MAX = Q_GD_MAX / I_GATE   # s, worst-case turn-off overlap (~54 ns)

Q_G = 40e-9                    # C, gate charge at the 6.85 V VCC rail
I_Q = 480e-6                   # A, LM5155 operating current (datasheet max)
R212 = 30_000.0               # ohm, clamp resistor (sec:hv-clamp, sized for 20% switch-voltage margin at the current-limit corner)
ESR_IN = 0.03                  # ohm, input bulk capacitor ESR
ESR_OUT = 0.496                # ohm, C204 (KEMET A759KS475M2EAAE496) ESR @ 100kHz/20C
CORE_LOSS = 0.050              # W, fixed core-loss allowance

# ---------------------------------------------------------------------------
# Ballast/divider-derived load currents (sec:hv-load, sec:hv-divider)
# ---------------------------------------------------------------------------

V_M_DIGIT = 145.0             # IN-12B maintaining voltage, typical
V_K_EXPECTED = 1.0            # K155ID1 expected on-drop
R_A_DIGIT = 10.00e3           # specified digit ballast (ohm)

V_M_COLON = 90.0              # IN-6 conservative maintaining voltage
V_K_COLON = 2.5               # conservative driver drop used for colon (sec:hv-load-colon)
R_A_COLON = 120e3             # specified colon ballast (ohm)

R_BLEEDER = 1.5e6              # R202, sized in sec:hv-bleeder for 1.8s to 60V (IEC 62368-1 ES1)
R_DIVIDER = 1.69e6 + 8.87e3   # R203+R204+R205 at the specified row's nominal point (approx, upper leg dominates)
V_REF = 1.0

def digit_current(v_out):
    """Per-tube digit cathode current (A) at v_out (V), specified 10 kOhm ballast."""
    return (v_out - V_M_DIGIT - V_K_EXPECTED) / R_A_DIGIT

def colon_current(v_out):
    """Per-tube colon anode current (A) at v_out (V), specified 120 kOhm ballast."""
    return (v_out - V_M_COLON - V_K_COLON) / R_A_COLON

def bleeder_current(v_out):
    return v_out / R_BLEEDER

def divider_current(v_out):
    return (v_out - V_REF) / R_DIVIDER

def total_output(v_out, digit_current_override=None, colon_current_override=None):
    """
    Total load current/power at v_out. digit_current_override and
    colon_current_override let the design-max point force each tube's
    own rated maximum (3.5 mA/tube digit, 0.85 mA/tube colon) -- the
    design-max envelope's defining condition, matching the document's
    "every load element at its own individual maximum, non-simultaneous,
    deliberately conservative" convention -- rather than the literal
    per-ballast-formula current at that voltage.
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

def converge(p_out, v_bus, v_out, t_ovl=T_OVL_TYP, r_dson=R_DSON_COLD, eta0=0.85, iterations=8):
    eta = eta0
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
        p_gate = (Q_G * F_SW + I_Q) * v_bus

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

    print("=== Design-max envelope: V_out = 191.5 V, typical T_OVL ===")
    budget = total_output(191.5, digit_current_override=3.5e-3, colon_current_override=0.85e-3)
    for k, v in budget.items():
        unit = "A" if k.startswith("i_") else "W"
        print(f"  {k} = {v*1000:.2f} m{unit}")
    r_dson_converged, r, t_j_converged = solve_r_dson(p_out=budget["p_out"], v_bus=8.5, v_out=191.5)
    print(f"  R_DSON converged = {r_dson_converged*1000:.1f} mOhm at T_J = {t_j_converged:.0f} C "
          f"(factor {r_dson_temp_factor(t_j_converged):.3f}x cold)")
    print(f"  eta={r['eta']:.3f}, P_in={r['p_in']:.3f} W, I_pk={r['i_pk']:.2f} A")
    print(f"  t_on={r['t_on']*1e6:.2f} us, duty={r['duty']:.3f}, "
          f"I_rms_pri={r['i_rms_pri']:.2f} A")
    print(f"  v_refl={r['v_refl']:.2f} V, t_dem={r['t_dem']*1e6:.2f} us, "
          f"I_s_rms={r['i_s_rms']*1000:.1f} mA")
    print(f"  V_cl={r['v_cl']:.1f} V ({r['v_cl']/r['v_refl']:.1f}x v_refl), "
          f"V_com={r['v_com']:.1f} V")
    print("  Loss breakdown (mW):")
    for k in ("p_ovl", "p_clamp", "p_cond_pri", "p_gate", "p_core", "p_cap",
              "p_rect", "p_sec"):
        print(f"    {k}: {r[k]*1000:.0f}")
    print(f"    total: {r['p_loss']*1000:.0f}")
    q201_diss_typ = r["p_cond_pri"] * (r_dson_converged / (r_dson_converged + R_201 + R_DCR_PRI)) + r["p_ovl"]
    print(f"  Q201 dissipation (typ T_OVL) = {q201_diss_typ*1000:.0f} mW, "
          f"dT = {q201_diss_typ*THETA_JA_Q201:.0f} K")
    print()

    print("=== Design-max envelope: V_out = 191.5 V, WORST-CASE T_OVL (Q201 thermal check) ===")
    r_wc = converge(p_out=budget["p_out"], v_bus=8.5, v_out=191.5, t_ovl=T_OVL_MAX, r_dson=r_dson_converged)
    print(f"  eta={r_wc['eta']:.3f}, I_pk={r_wc['i_pk']:.2f} A, p_ovl={r_wc['p_ovl']*1000:.0f} mW")
    q201_diss_wc = r_wc["p_cond_pri"] * (r_dson_converged / (r_dson_converged + R_201 + R_DCR_PRI)) + r_wc["p_ovl"]
    print(f"  Q201 dissipation (worst-case T_OVL) = {q201_diss_wc*1000:.0f} mW, "
          f"dT = {q201_diss_wc*THETA_JA_Q201:.0f} K")
    print()

    print("=== Nominal point: V_out = 170 V (V_BUS = 9 V), typical T_OVL, design-max R_DSON reused ===")
    budget_n = total_output(170.0)
    for k, v in budget_n.items():
        unit = "A" if k.startswith("i_") else "W"
        print(f"  {k} = {v*1000:.2f} m{unit}")
    r_n = converge(p_out=budget_n["p_out"], v_bus=9.0, v_out=170.0, r_dson=r_dson_converged)
    print(f"  eta={r_n['eta']:.3f}, P_in={r_n['p_in']:.3f} W, I_pk={r_n['i_pk']:.2f} A")
    print(f"  t_on={r_n['t_on']*1e6:.2f} us, duty={r_n['duty']:.3f}, "
          f"I_rms_pri={r_n['i_rms_pri']:.2f} A")
    print(f"  I_in(avg)={r_n['p_in']/9.0*1000:.0f} mA")
    print()

    print("=== Nominal point: V_out = 170 V (V_BUS = 12 V), typical T_OVL, design-max R_DSON reused ===")
    r_n12 = converge(p_out=budget_n["p_out"], v_bus=12.0, v_out=170.0, r_dson=r_dson_converged)
    print(f"  eta={r_n12['eta']:.3f}, P_in={r_n12['p_in']:.3f} W, I_pk={r_n12['i_pk']:.2f} A")
    print(f"  t_on={r_n12['t_on']*1e6:.2f} us, duty={r_n12['duty']:.3f}, "
          f"I_rms_pri={r_n12['i_rms_pri']:.2f} A")
    print(f"  I_in(avg)={r_n12['p_in']/12.0*1000:.0f} mA")
    print()

    print("=== DCM worst corner: L=11uH, V_BUS=8.5V, design-max load ===")
    e_cyc = budget["p_out"] / r["eta"] / F_SW
    l_max = 11e-6
    i_pk_dcm = (2 * e_cyc / l_max) ** 0.5
    t_on_dcm = l_max * i_pk_dcm / 8.5
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
    i_in_dm = r["p_in"] / 8.5
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

    fc_validate = solve_fc(287.0)   # old G0, should reproduce doc's old 194 Hz / 52 deg
    print(f"  VALIDATION at old G0=287: f_c={fc_validate:.0f} Hz "
          f"(doc: 194 Hz), phi_m={phase_margin(fc_validate):.0f} deg (doc: 52 deg)")

    f_c = solve_fc(g0)
    phi_m = phase_margin(f_c)
    print(f"  f_z={f_z:.0f} Hz, f_hp={f_hp/1000:.1f} kHz, H=1/170")
    print(f"  f_c={f_c:.0f} Hz (f_sw/{F_SW/f_c:.0f}), phi_m={phi_m:.0f} deg, "
          f"zero/f_c={f_z/f_c:.2f}, f_hp/f_c={f_hp/f_c:.0f}x")
    print()

    print("=== Soft start (design-max eta) ===")
    i_lim_typ = 0.100 / R_201
    denom = 0.5 * L_P * i_lim_typ**2 * F_SW * r["eta"]
    e_stored = 0.5 * c_out * 170.0**2
    t_rise = e_stored / denom
    print(f"  I_lim(typ)={i_lim_typ:.3f} A, denom={denom:.2f} W, t_rise={t_rise*1000:.1f} ms")
    print()

    print("=== Bleeder minimum-load check (design-max eta) ===")
    i_pk_min = 13 * 165e-9 / L_P
    p_min = 0.5 * L_P * i_pk_min**2 * F_SW * r["eta"]
    print(f"  I_pk_min={i_pk_min:.3f} A, P_min={p_min*1000:.1f} mW")


if __name__ == "__main__":
    main()
