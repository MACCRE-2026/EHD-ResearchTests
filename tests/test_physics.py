"""Physics-regression tests for :mod:`ehdpsu.physics`.

Every test exercises real physics and pins a hand-computable reference value at
the original script's default parameters (r_wire = 25 um, d = 12 mm,
L = 15 cm, mu = 1.5e-4, V_op = 22 kV, f_sw = 250 kHz, N = 5, C = 1 nF). Each
test would fail if the underlying formula were reverted or corrupted.

Reference values (computed by hand from the closed-form expressions and
confirmed against the implementation):

* Peek field:
      r_cm = 25e-6 * 100 = 2.5e-3 cm
      E = 3.1e6 * 0.8 * 1.0 * (1 + 0.308/sqrt(1.0 * 2.5e-3))
        = 2.48e6 * (1 + 0.308/0.05) = 2.48e6 * 7.16 = 1.77568e7 V/m
* V_onset = E * r * ln(d/r) = 1.77568e7 * 25e-6 * ln(0.012/25e-6)
          = 443.92 * ln(480) = 443.92 * 6.17379 ~= 2740.67 V
* k_pp = 2 * 8.854e-12 * 1.5e-4 * 0.15 / 0.012**2 = 2.766875e-12 A/V^2
* I = k_pp * V * (V - V_onset)
     = 2.766875e-12 * 22000 * (22000 - 2740.67) ~= 1.17234e-3 A
* P = V * I = 22000 * 1.17234e-3 ~= 25.7915 W
* T = I * d / mu = 1.17234e-3 * 0.012 / 1.5e-4 ~= 0.0937872 N
* grams-force = (T / 9.81) * 1000 ~= 9.56036 gf
* eff = (T / P) * 1000 ~= 3.63636 N/kW
* CW droop = (I/(f*C)) * ((2/3)*125 + 0.5*25 - (1/6)*5)
           = (I/(2.5e5*1e-9)) * (83.3333 + 12.5 - 0.83333)
           = (I/2.5e-4) * 95.0 ~= 445.489 V
* CW ripple = (I/(f*C)) * (5*6/2) = (I/2.5e-4) * 15 ~= 70.3404 V
"""

import math

import numpy as np

from ehdpsu import physics
from ehdpsu.physics import EPS0, DesignParameters

P = DesignParameters()

# Pinned reference values (see module docstring for derivation).
E_PEEK_REF = 1.77568e7
V_ONSET_REF = 2740.6671272441477
K_GEO_REF = 2.7668749999999996e-12
I_REF = 0.0011723396661307394
P_REF = 25.791472654876266
T_REF = 0.09378717329045916
GF_REF = 9.560364249791963
EFF_REF = 3.6363636363636367
DROOP_REF = 445.489073129681
RIPPLE_REF = 70.34037996784437


def test_peek_inception_field_reference() -> None:
    """Peek field matches the hand-computed value at reference parameters."""
    e = physics.peek_inception_field(P.r_wire_m, P.delta, P.m_rough)
    assert np.isclose(e, E_PEEK_REF, rtol=1e-4)


def test_peek_field_roughness_scaling() -> None:
    """Peek field scales linearly with the roughness factor m (real physics)."""
    e1 = physics.peek_inception_field(P.r_wire_m, P.delta, 1.0)
    e2 = physics.peek_inception_field(P.r_wire_m, P.delta, 0.5)
    assert np.isclose(e2, 0.5 * e1, rtol=1e-12)


def test_corona_inception_voltage_reference() -> None:
    """V_onset matches E_peek * r * ln(d/r) at reference parameters."""
    v = physics.corona_inception_voltage(E_PEEK_REF, P.r_wire_m, P.d_gap_m)
    # Recompute independently from the pinned E_PEEK_REF.
    expected = E_PEEK_REF * P.r_wire_m * math.log(P.d_gap_m / P.r_wire_m)
    assert np.isclose(v, expected, rtol=1e-12)
    assert np.isclose(v, V_ONSET_REF, rtol=1e-4)


def test_geometric_constant_parallel_plate_reference() -> None:
    """Parallel-plate prefactor equals 2*eps0*mu*L/d^2."""
    k = physics.geometric_constant_parallel_plate(EPS0, P.mu_ion, P.L_wire_m, P.d_gap_m)
    assert np.isclose(k, K_GEO_REF, rtol=1e-12)


def test_ion_current_zero_below_onset() -> None:
    """No corona current when V_op <= V_onset."""
    assert physics.ion_current(V_ONSET_REF, V_ONSET_REF, K_GEO_REF) == 0.0
    assert physics.ion_current(V_ONSET_REF - 1.0, V_ONSET_REF, K_GEO_REF) == 0.0


def test_ion_current_quadratic_above_onset() -> None:
    """Above onset the current follows the Townsend quadratic law."""
    i = physics.ion_current(P.V_op, V_ONSET_REF, K_GEO_REF)
    assert np.isclose(i, I_REF, rtol=1e-6)
    # Verify the quadratic form directly: I / (k*V) == (V - V_onset).
    assert np.isclose(i / (K_GEO_REF * P.V_op), P.V_op - V_ONSET_REF, rtol=1e-12)


def test_electrical_power_reference() -> None:
    """P = V * I."""
    p = physics.electrical_power(P.V_op, I_REF)
    assert np.isclose(p, P_REF, rtol=1e-9)
    assert np.isclose(p, P.V_op * I_REF, rtol=1e-12)


def test_thrust_newton_reference_and_relation() -> None:
    """Thrust equals I*d/mu and matches the reference value."""
    t = physics.thrust_newton(I_REF, P.d_gap_m, P.mu_ion)
    assert np.isclose(t, T_REF, rtol=1e-9)
    assert np.isclose(t, I_REF * P.d_gap_m / P.mu_ion, rtol=1e-12)


def test_thrust_grams_force_conversion() -> None:
    """grams-force = (T/9.81)*1000."""
    gf = physics.thrust_grams_force(T_REF)
    assert np.isclose(gf, GF_REF, rtol=1e-9)
    assert np.isclose(gf, (T_REF / 9.81) * 1000.0, rtol=1e-12)


def test_efficiency_reference_and_zero_power() -> None:
    """Efficiency = (T/P)*1000, and 0 when power is non-positive."""
    eff = physics.efficiency_N_per_kW(T_REF, P_REF)
    assert np.isclose(eff, EFF_REF, rtol=1e-9)
    assert physics.efficiency_N_per_kW(T_REF, 0.0) == 0.0
    assert physics.efficiency_N_per_kW(T_REF, -5.0) == 0.0


def test_cw_voltage_droop_reference() -> None:
    """CW droop matches the standard cascade formula at reference parameters."""
    d = physics.cw_voltage_droop(I_REF, P.f_sw, P.C_stage, P.N_stages)
    assert np.isclose(d, DROOP_REF, rtol=1e-6)
    # Independent recomputation of the polynomial factor for N=5 -> 95.0.
    n = P.N_stages
    poly = (2.0 / 3.0) * n**3 + 0.5 * n**2 - (1.0 / 6.0) * n
    assert np.isclose(poly, 95.0, rtol=1e-12)
    assert np.isclose(d, (I_REF / (P.f_sw * P.C_stage)) * 95.0, rtol=1e-12)


def test_cw_ripple_pp_reference() -> None:
    """CW peak-to-peak ripple matches (I/(f*C))*N(N+1)/2."""
    r = physics.cw_ripple_pp(I_REF, P.f_sw, P.C_stage, P.N_stages)
    assert np.isclose(r, RIPPLE_REF, rtol=1e-6)
    n = P.N_stages
    assert np.isclose(r, (I_REF / (P.f_sw * P.C_stage)) * (n * (n + 1) / 2), rtol=1e-12)


def test_wire_cylinder_note_is_nonempty_string() -> None:
    """The wire-cylinder note is a pure helper returning documented text."""
    note = physics.geometric_constant_wire_cylinder_note()
    assert isinstance(note, str)
    assert "PARALLEL-PLATE" in note
    assert "wire" in note.lower()
