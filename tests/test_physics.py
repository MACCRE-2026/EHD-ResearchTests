"""Physics-regression tests for :mod:`ehdpsu.physics`.

Every test exercises real physics and pins a hand-computable reference value at
the original script's default parameters (r_wire = 25 um, d = 12 mm,
L = 15 cm, mu = 1.5e-4, V_op = 22 kV, f_sw = 250 kHz, N = 5, C = 1 nF). Each
test would fail if the underlying formula were reverted or corrupted.

The reference values and their hand derivation live in :mod:`ehdpsu.mk0_reference` and are
imported here rather than restated. They were duplicated in this docstring and again as module
constants until 2026-09-15; a second test module needed the same eleven floats, and three copies
of a number that keep passing against themselves is *principle 4, two representations of one
thing will drift*.

Scope of this module versus :mod:`tests.test_mk0_reproduction`
-------------------------------------------------------------
Each test **here** exercises one function in isolation, feeding it pinned constants as inputs.
That is deliberate: it localises a failure to a single formula. What it cannot do is notice that
the functions are wired together wrongly, because the composition is never run — every input is
handed in rather than produced by the previous stage. ``test_mk0_reproduction.py`` runs the chain
end to end for exactly that reason. *Principle 6, a green test suite is not evidence of a working
system*, and the seam between these functions is the part no test in this file visits.
"""

import math

import numpy as np
from conftest import reference_design

from ehdpsu import physics
from ehdpsu.mk0_reference import (
    CW_DROOP_REF_V,
    CW_RIPPLE_REF_VPP,
    E_PEEK_REF_V_PER_M,
    EFFICIENCY_REF_N_PER_KW,
    I_ION_REF_A,
    K_GEO_REF_A_PER_V2,
    POWER_REF_W,
    THRUST_REF_GF,
    THRUST_REF_N,
    V_ONSET_REF_V,
)
from ehdpsu.physics import EPS0

P = reference_design()


def test_peek_inception_field_reference() -> None:
    """Peek field matches the hand-computed value at reference parameters."""
    e = physics.peek_inception_field(P.r_wire_m, P.delta, P.m_rough)
    assert np.isclose(e, E_PEEK_REF_V_PER_M, rtol=1e-4)


def test_peek_field_roughness_scaling() -> None:
    """Peek field scales linearly with the roughness factor m (real physics)."""
    e1 = physics.peek_inception_field(P.r_wire_m, P.delta, 1.0)
    e2 = physics.peek_inception_field(P.r_wire_m, P.delta, 0.5)
    assert np.isclose(e2, 0.5 * e1, rtol=1e-12)


def test_corona_inception_voltage_reference() -> None:
    """V_onset matches E_peek * r * ln(d/r) at reference parameters."""
    v = physics.corona_inception_voltage(E_PEEK_REF_V_PER_M, P.r_wire_m, P.d_gap_m)
    # Recompute independently from the pinned E_PEEK_REF_V_PER_M.
    expected = E_PEEK_REF_V_PER_M * P.r_wire_m * math.log(P.d_gap_m / P.r_wire_m)
    assert np.isclose(v, expected, rtol=1e-12)
    assert np.isclose(v, V_ONSET_REF_V, rtol=1e-4)


def test_geometric_constant_parallel_plate_reference() -> None:
    """Parallel-plate prefactor equals 2*eps0*mu*L/d^2."""
    k = physics.geometric_constant_parallel_plate(EPS0, P.mu_ion, P.L_wire_m, P.d_gap_m)
    assert np.isclose(k, K_GEO_REF_A_PER_V2, rtol=1e-12)


def test_ion_current_zero_below_onset() -> None:
    """No corona current when V_op <= V_onset."""
    assert physics.ion_current(V_ONSET_REF_V, V_ONSET_REF_V, K_GEO_REF_A_PER_V2) == 0.0
    assert physics.ion_current(V_ONSET_REF_V - 1.0, V_ONSET_REF_V, K_GEO_REF_A_PER_V2) == 0.0


def test_ion_current_quadratic_above_onset() -> None:
    """Above onset the current follows the Townsend quadratic law."""
    i = physics.ion_current(P.V_op, V_ONSET_REF_V, K_GEO_REF_A_PER_V2)
    assert np.isclose(i, I_ION_REF_A, rtol=1e-6)
    # Verify the quadratic form directly: I / (k*V) == (V - V_onset).
    assert np.isclose(i / (K_GEO_REF_A_PER_V2 * P.V_op), P.V_op - V_ONSET_REF_V, rtol=1e-12)


def test_electrical_power_reference() -> None:
    """P = V * I."""
    p = physics.electrical_power(P.V_op, I_ION_REF_A)
    assert np.isclose(p, POWER_REF_W, rtol=1e-9)
    assert np.isclose(p, P.V_op * I_ION_REF_A, rtol=1e-12)


def test_thrust_newton_reference_and_relation() -> None:
    """Thrust equals I*d/mu and matches the reference value."""
    t = physics.thrust_newton(I_ION_REF_A, P.d_gap_m, P.mu_ion)
    assert np.isclose(t, THRUST_REF_N, rtol=1e-9)
    assert np.isclose(t, I_ION_REF_A * P.d_gap_m / P.mu_ion, rtol=1e-12)


def test_thrust_grams_force_conversion() -> None:
    """grams-force = (T/9.81)*1000."""
    gf = physics.thrust_grams_force(THRUST_REF_N)
    assert np.isclose(gf, THRUST_REF_GF, rtol=1e-9)
    assert np.isclose(gf, (THRUST_REF_N / 9.81) * 1000.0, rtol=1e-12)


def test_efficiency_reference_and_zero_power() -> None:
    """Efficiency = (T/P)*1000, and 0 when power is non-positive."""
    eff = physics.efficiency_N_per_kW(THRUST_REF_N, POWER_REF_W)
    assert np.isclose(eff, EFFICIENCY_REF_N_PER_KW, rtol=1e-9)
    assert physics.efficiency_N_per_kW(THRUST_REF_N, 0.0) == 0.0
    assert physics.efficiency_N_per_kW(THRUST_REF_N, -5.0) == 0.0


def test_cw_voltage_droop_reference() -> None:
    """CW droop matches the standard cascade formula at reference parameters."""
    d = physics.cw_voltage_droop(I_ION_REF_A, P.f_sw, P.C_stage, P.N_stages)
    assert np.isclose(d, CW_DROOP_REF_V, rtol=1e-6)
    # Independent recomputation of the polynomial factor for N=5 -> 95.0.
    n = P.N_stages
    poly = (2.0 / 3.0) * n**3 + 0.5 * n**2 - (1.0 / 6.0) * n
    assert np.isclose(poly, 95.0, rtol=1e-12)
    assert np.isclose(d, (I_ION_REF_A / (P.f_sw * P.C_stage)) * 95.0, rtol=1e-12)


def test_cw_ripple_pp_reference() -> None:
    """CW peak-to-peak ripple matches (I/(f*C))*N(N+1)/2."""
    r = physics.cw_ripple_pp(I_ION_REF_A, P.f_sw, P.C_stage, P.N_stages)
    assert np.isclose(r, CW_RIPPLE_REF_VPP, rtol=1e-6)
    n = P.N_stages
    assert np.isclose(r, (I_ION_REF_A / (P.f_sw * P.C_stage)) * (n * (n + 1) / 2), rtol=1e-12)


def test_wire_cylinder_note_is_nonempty_string() -> None:
    """The wire-cylinder note is a pure helper returning documented text."""
    note = physics.geometric_constant_wire_cylinder_note()
    assert isinstance(note, str)
    assert "PARALLEL-PLATE" in note
    assert "wire" in note.lower()
