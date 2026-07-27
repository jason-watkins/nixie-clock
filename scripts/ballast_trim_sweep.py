"""
Digit-ballast / feedback-divider design-space sweep for the 170 V flyback
converter's IN-12B digit ballast (R1-R4) and divider resistor R205.

Context: docs/design_analysis/sections/05_hv_converter.tex,
sec:hv-load-digit and sec:hv-divider-split. The design uses a fixed
2 kOhm trimmer (RV201) relegated to a build-time selection aid rather
than a wide field-adjustable range: for each candidate digit-ballast
value, this script sizes R205 so the trimmer's electrical midpoint lands
on that ballast's typical-current (3.0 mA) voltage, then reports the
divider's absolute worst-case and guaranteed-reachable ceiling and floor
voltages (trimmer at its two mechanical end-stops, component tolerances
stacked to the extreme in each direction, in both directions).

The ballast candidates are swept on the coarser E24 (~10%) series rather
than E96 (1%): this table's purpose is to hand a builder a practical,
well-spaced set of substitutable ballast values and their per-value
tuning targets, not an exhaustive 1%-resolution reference. R205 itself is
still rounded to E96, since it is a fixed, precision divider component
rather than something a builder substitutes.

This script intentionally does NOT constrain the ceiling to stay under
the tube's rated maximum current -- that goal was found not to be
simultaneously achievable with the other targets, and is a known,
accepted risk covered instead by a hardware-user-guide requirement that
voltage be verified and adjusted with tubes removed. The absolute
max/min columns exist so a builder can see how wide that risk actually
is, not to gate row selection.

Run: python scripts/ballast_trim_sweep.py
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# IN-12B tube parameters (sec:in12b)
V_M_TYP = 145.0  # maintaining voltage, V (typical; no tabulated spread)
I_MIN_MA = 2.5  # rated DC minimum cathode current, mA
I_TYP_MA = 3.0  # chosen typical/center target, mA (no datasheet "typ" given)
I_MAX_MA = 3.5  # rated DC maximum cathode current, mA

# K155ID1/SN74141 driver on-state drop (sec:bcd-driver)
V_K_EXPECTED = 1.0  # expected on-state drop at this design's low current, V

# Sweep control
SEED_VOLTAGE = 170.0  # nominal voltage used to compute the starting ballast seed
TARGET_TYP_CEILING = 185.0  # sweep stops once a row's (pre-rounding) V_typ >= this, V

# Feedback divider (sec:hv-divider)
R_UPPER_KOHM = 1690.0  # R203 + R204, fixed upper leg, kOhm
V_REF_NOM = 1.00  # LM5155 FB reference, nominal, V
RV_TOTAL_KOHM = 2.0  # fixed trimmer total resistance, kOhm

# Component tolerances (worst-case, additive stacking -- matches this
# document's established methodology elsewhere; not RSS/statistical)
R_UPPER_TOL = 0.01  # R203/R204, 1% each
R_LOWER_TOL = 0.01  # R205, 1%
V_REF_TOL = 0.01  # LM5155 reference, 1%
TRIMMER_TOL = 0.10  # ASSUMPTION: cermet trimmer total-resistance tolerance;
# not datasheet-specified for the Bourns 3296W. Only
# enters the absolute-minimum (floor) calculation --
# the trimmer contributes zero resistance at the
# ceiling (R_V = 0) regardless of its own tolerance.

# Standard E96 (1%) base mantissas, 1.00-9.76 -- used for R205 (precision
# divider resistor, not builder-substituted)
# fmt: off
E96_BASE = [
    1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24,
    1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58,
    1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00,
    2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
    2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24,
    3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
    4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23,
    5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
    6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45,
    8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
]
# fmt: on

# Standard E24 (~10%) base mantissas, 1.0-9.1 -- used for the digit-ballast
# sweep, since the table's purpose is a practical, builder-substitutable
# spread of values, not 1% design resolution
E24_BASE = [
    1.0,
    1.1,
    1.2,
    1.3,
    1.5,
    1.6,
    1.8,
    2.0,
    2.2,
    2.4,
    2.7,
    3.0,
    3.3,
    3.6,
    3.9,
    4.3,
    4.7,
    5.1,
    5.6,
    6.2,
    6.8,
    7.5,
    8.2,
    9.1,
]

# ---------------------------------------------------------------------------
# E-series helpers
# ---------------------------------------------------------------------------


def e_series_values(base, decade_min_kohm=1.0, decade_max_kohm=100.0):
    """All standard values (kOhm) of the given base mantissa list, sorted."""
    values = set()
    decade = 1.0
    while decade <= decade_max_kohm * 10:
        for mantissa in base:
            value = round(mantissa * decade, 4)
            if decade_min_kohm <= value <= decade_max_kohm:
                values.add(value)
        decade *= 10
    return sorted(values)


def round_down_series(target_kohm, series):
    """Largest series value <= target_kohm."""
    candidates = [v for v in series if v <= target_kohm]
    if not candidates:
        raise ValueError(f"No series value <= {target_kohm} kOhm in series")
    return max(candidates)


def round_nearest_series(target_kohm, series):
    """Closest series value to target_kohm."""
    return min(series, key=lambda v: abs(v - target_kohm))


# ---------------------------------------------------------------------------
# Ballast (R_A) calculations
# ---------------------------------------------------------------------------


def ballast_for_target(voltage, current_ma, v_k=V_K_EXPECTED, v_m=V_M_TYP):
    """Ballast resistance (kOhm) that gives current_ma at voltage (nominal)."""
    return (voltage - v_m - v_k) / current_ma


def voltage_for_current(r_a_kohm, current_ma, v_k=V_K_EXPECTED, v_m=V_M_TYP):
    """Voltage that drives current_ma through ballast r_a_kohm (nominal)."""
    return v_m + v_k + current_ma * r_a_kohm


# ---------------------------------------------------------------------------
# Divider calculations
# ---------------------------------------------------------------------------


def divider_voltage(r_lower_kohm, r_upper_kohm=R_UPPER_KOHM, v_ref=V_REF_NOM):
    """Nominal V_out for a given lower-leg resistance."""
    return v_ref * (1 + r_upper_kohm / r_lower_kohm)


def r205_for_midpoint(
    v_typ, rv_total=RV_TOTAL_KOHM, r_upper=R_UPPER_KOHM, v_ref=V_REF_NOM
):
    """
    R205 such that the trimmer's electrical midpoint (R_V = rv_total / 2)
    puts the divider at v_typ, for a ballast that wants v_typ at r_a_kohm.
    """
    r_lower_mid = r_upper / (v_typ / v_ref - 1)
    return r_lower_mid - rv_total / 2


def ceiling_voltage_worst_case(r205_kohm, r_upper=R_UPPER_KOHM, v_ref=V_REF_NOM):
    """
    Absolute maximum divider voltage: trimmer at R_V = 0 (one mechanical
    end-stop), every component tolerance stacked in the direction that
    maximizes V_out. The trimmer's own tolerance does not enter here --
    it contributes zero resistance at this end-stop regardless of its
    manufactured value.
    """
    r_upper_wc = r_upper * (1 + R_UPPER_TOL)
    r205_wc = r205_kohm * (1 - R_LOWER_TOL)
    v_ref_wc = v_ref * (1 + V_REF_TOL)
    return v_ref_wc * (1 + r_upper_wc / r205_wc)


def floor_voltage_worst_case(
    r205_kohm, rv_total=RV_TOTAL_KOHM, r_upper=R_UPPER_KOHM, v_ref=V_REF_NOM
):
    """
    Absolute minimum divider voltage: trimmer at R_V = rv_total (the
    other mechanical end-stop), every component tolerance -- including
    the trimmer's own assumed total-resistance tolerance -- stacked in
    the direction that minimizes V_out.
    """
    r_upper_wc = r_upper * (1 - R_UPPER_TOL)
    r_lower_wc = r205_kohm * (1 + R_LOWER_TOL) + rv_total * (1 + TRIMMER_TOL)
    v_ref_wc = v_ref * (1 - V_REF_TOL)
    return v_ref_wc * (1 + r_upper_wc / r_lower_wc)


def ceiling_voltage_guaranteed(r205_kohm, r_upper=R_UPPER_KOHM, v_ref=V_REF_NOM):
    """
    Guaranteed-reachable maximum divider voltage: trimmer at R_V = 0, every
    component tolerance stacked in the direction that MINIMIZES V_out --
    the complement of ceiling_voltage_worst_case. This is the highest
    voltage every unit is certain to reach, regardless of where its
    component tolerances actually landed.
    """
    r_upper_wc = r_upper * (1 - R_UPPER_TOL)
    r205_wc = r205_kohm * (1 + R_LOWER_TOL)
    v_ref_wc = v_ref * (1 - V_REF_TOL)
    return v_ref_wc * (1 + r_upper_wc / r205_wc)


def floor_voltage_guaranteed(
    r205_kohm, rv_total=RV_TOTAL_KOHM, r_upper=R_UPPER_KOHM, v_ref=V_REF_NOM
):
    """
    Guaranteed-reachable minimum divider voltage: trimmer at R_V = rv_total,
    every component tolerance -- including the trimmer's own -- stacked in
    the direction that MAXIMIZES V_out -- the complement of
    floor_voltage_worst_case. This is the lowest voltage every unit is
    certain to reach down to, regardless of tolerance stackup.
    """
    r_upper_wc = r_upper * (1 + R_UPPER_TOL)
    r_lower_wc = r205_kohm * (1 - R_LOWER_TOL) + rv_total * (1 - TRIMMER_TOL)
    v_ref_wc = v_ref * (1 + V_REF_TOL)
    return v_ref_wc * (1 + r_upper_wc / r_lower_wc)


# ---------------------------------------------------------------------------
# Table generation
# ---------------------------------------------------------------------------


def build_table():
    ballast_series = e_series_values(E24_BASE)
    r205_series = e_series_values(E96_BASE)

    seed_r_a = ballast_for_target(SEED_VOLTAGE, I_TYP_MA)
    start_r_a = round_down_series(seed_r_a, ballast_series)
    sweep_values = [v for v in ballast_series if v >= start_r_a]

    rows = []
    for r_a in sweep_values:
        v_min = voltage_for_current(r_a, I_MIN_MA)
        v_typ_ideal = voltage_for_current(r_a, I_TYP_MA)
        v_max = voltage_for_current(r_a, I_MAX_MA)

        r205_exact = r205_for_midpoint(v_typ_ideal)
        r205 = round_nearest_series(r205_exact, r205_series)

        v_floor_wc = floor_voltage_worst_case(r205)
        v_floor_gtd = floor_voltage_guaranteed(r205)
        v_ceiling_gtd = ceiling_voltage_guaranteed(r205)
        v_ceiling_wc = ceiling_voltage_worst_case(r205)

        rows.append(
            {
                "r_a": r_a,
                "v_min": v_min,
                "v_typ": v_typ_ideal,
                "v_max": v_max,
                "r205": r205,
                "v_floor_wc": v_floor_wc,
                "v_floor_gtd": v_floor_gtd,
                "v_ceiling_gtd": v_ceiling_gtd,
                "v_ceiling_wc": v_ceiling_wc,
            }
        )

        if v_typ_ideal >= TARGET_TYP_CEILING:
            break
    else:
        raise RuntimeError(
            "Swept every E24 ballast value up to the top of the generated "
            "series without reaching TARGET_TYP_CEILING -- widen "
            "e_series_values()'s range."
        )

    return rows


def print_table(rows):
    header = (
        f"{'R_A (kOhm)':>10}  {'V_min (V)':>9}  {'V_typ (V)':>9}  "
        f"{'V_max (V)':>9}  {'R205 (kOhm)':>11}  "
        f"{'V_floor,wc (V)':>14}  {'V_floor,gtd (V)':>15}  "
        f"{'V_ceil,gtd (V)':>14}  {'V_ceil,wc (V)':>13}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['r_a']:>10.2f}  {row['v_min']:>9.1f}  {row['v_typ']:>9.1f}  "
            f"{row['v_max']:>9.1f}  {row['r205']:>11.2f}  "
            f"{row['v_floor_wc']:>14.1f}  {row['v_floor_gtd']:>15.1f}  "
            f"{row['v_ceiling_gtd']:>14.1f}  {row['v_ceiling_wc']:>13.1f}"
        )


def main():
    rows = build_table()
    print_table(rows)
    print()
    print(
        f"{len(rows)} rows, ballast {rows[0]['r_a']:.2f} kOhm to "
        f"{rows[-1]['r_a']:.2f} kOhm."
    )


if __name__ == "__main__":
    main()
