"""Reproduce the original sanity-check script, then print validation notes.

Run with::

    python -m ehdpsu.sanity

This module first reproduces, using the pure physics core in
:mod:`ehdpsu.physics` and the ORIGINAL default parameters, the three printed
sections of the design conversation's sanity script:

1. Electrostatic inception (Peek field + corona inception voltage)
2. Single-cell operating point (ion current, power, thrust, efficiency)
3. Cockcroft-Walton multiplier health (droop + ripple)

It then prints a clearly separated ``VALIDATION NOTES`` section that documents
which parts of the original physics are correct as-is and which carry
idealizing assumptions or geometric caveats, with reasoning. No numbers are
invented; every value comes from the physics core.

All printing lives here (not in :mod:`ehdpsu.physics`, which is pure).
"""

from __future__ import annotations

from . import physics
from .physics import DesignParameters


def main() -> None:
    """Print the reproduced sanity-check sections plus validation notes."""
    p = DesignParameters()  # original script defaults

    # --- Section 1: electrostatic inception -------------------------------
    e_peek = physics.peek_inception_field(p.r_wire_m, p.delta, p.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, p.r_wire_m, p.d_gap_m)

    print("--- 1. ELECTROSTATIC INCEPTION ---")
    print(f"Peek's Breakdown Surface Field: {e_peek / 1e6:.2f} MV/m")
    print(f"Calculated Corona Inception (V_onset): {v_onset / 1e3:.2f} kV")

    # --- Section 2: single-cell operating point ---------------------------
    k_geo = physics.geometric_constant_parallel_plate(physics.EPS0, p.mu_ion, p.L_wire_m, p.d_gap_m)
    i_ion = physics.ion_current(p.V_op, v_onset, k_geo)
    p_elec = physics.electrical_power(p.V_op, i_ion)
    thrust_n = physics.thrust_newton(i_ion, p.d_gap_m, p.mu_ion)
    thrust_gf = physics.thrust_grams_force(thrust_n)
    eff = physics.efficiency_N_per_kW(thrust_n, p_elec)

    print(f"\n--- 2. SINGLE-CELL OPERATING POINT (at {p.V_op / 1e3:.1f} kV) ---")
    print(f"Ion Current (I_load): {i_ion * 1e3:.2f} mA")
    print(f"Electrical Power:     {p_elec:.2f} Watts")
    print(f"Raw Output Thrust:    {thrust_n:.4f} N ({thrust_gf:.2f} grams-force)")
    print(f"Thrust Efficiency:    {eff:.2f} N/kW")

    # --- Section 3: Cockcroft-Walton multiplier health --------------------
    v_droop = physics.cw_voltage_droop(i_ion, p.f_sw, p.C_stage, p.N_stages)
    v_ripple = physics.cw_ripple_pp(i_ion, p.f_sw, p.C_stage, p.N_stages)

    print(
        f"\n--- 3. MULTIPLIER STAGE HEALTH "
        f"({p.N_stages}-Stage @ {p.f_sw / 1e3:.0f} kHz, "
        f"{p.C_stage * 1e9:.0f}nF) ---"
    )
    print(f"Loaded Voltage Droop: {v_droop:.1f} V ({(v_droop / p.V_op) * 100:.2f}% loss)")
    print(f"Peak-to-Peak Ripple:  {v_ripple:.1f} V")

    # --- Validation notes -------------------------------------------------
    print("\n=== VALIDATION NOTES (physics review of the original script) ===")
    print(
        "1) PEEK'S LAW (Section 1): CORRECT as written. "
        "E_peek = g0*m*delta*(1 + c/sqrt(delta*r_cm)) with g0=3.1e6 V/m, "
        "c=0.308 cm^0.5, roughness m, and r converted to cm (r_wire*100). "
        "V_onset = E_peek*r*ln(d/r) is the coaxial-cylinder field-to-voltage "
        "integration, valid for a thin wire at d >> r. "
        "Refs: Peek 1929; Kuffel & Zaengl, p.366."
    )
    print(
        "2) CURRENT LAW (Section 2): the quadratic form "
        "I = k*V*(V - V_onset) is CORRECT (Townsend). CAVEAT on the prefactor: "
        + physics.geometric_constant_wire_cylinder_note()
    )
    print(
        "3) THRUST (Section 2): T = I*d/mu is CORRECT IN FORM but is an "
        "IDEALIZED, mobility-limited UPPER BOUND. It assumes full ion->neutral "
        "momentum transfer, no neutral drag, and a uniform gap field; real "
        "thrust is lower. Efficiency (N/kW) inherits the same upper-bound and "
        "the current-law geometry uncertainty. "
        "Refs: Bahder & Fazi (ARL-TR-3005, 2003); Christenson & Moller (1967)."
    )
    print(
        "4) COCKCROFT-WALTON (Section 3): BOTH the droop "
        "V_droop = (I/(f*C))*((2/3)N^3 + (1/2)N^2 - (1/6)N) and the pk-pk "
        "ripple V_ripple = (I/(f*C))*N(N+1)/2 are CORRECT standard HV cascade "
        "formulas. Ref: Kuffel & Zaengl (cascade generator)."
    )
    print(
        "SUMMARY: Section 1 and Section 3 reproduce with no correction. "
        "Section 2's numbers are reproduced exactly but carry TWO documented "
        "caveats: the current-law prefactor is a labeled parallel-plate "
        "(order-of-magnitude) model parameter, and the thrust/efficiency are "
        "idealized upper bounds. No coefficients were curve-fit."
    )


if __name__ == "__main__":
    main()
