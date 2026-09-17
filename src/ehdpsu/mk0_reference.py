"""Pinned MK0 reference figures — the single place the expected numbers live.

These are **expected outputs, not design inputs.** The design point lives in
:class:`ehdpsu.physics.DesignParameters` (and, from plan Task 7 onward, in a profile file).
The constants here are what that design point *produces*, recorded exactly so a change to the
physics core cannot pass unnoticed.

Why they are in the package rather than in a test module
--------------------------------------------------------
They were duplicated. ``tests/test_physics.py`` held one copy for its per-function tests, and
``tests/test_mk0_reproduction.py`` needed the same values for the end-to-end chain. Two copies of
eleven floats is *principle 4, two representations of one thing will drift* — and the drift would
be silent, because both test modules would keep passing against their own copy while disagreeing
with each other. One module, imported by both.

**Nothing in the physics core may import this module.** If ``physics.py`` ever read a value from
here, the regression tests would be comparing the code against a number the code itself supplied,
which asserts nothing at all. ``test_mk0_reproduction.py`` enforces that with a check on the
physics core's imports, because a docstring warning is not a mechanism.

What a pinned value can and cannot tell you
-------------------------------------------
It detects **movement**. It says nothing about **correctness** — these floats were captured from
the implementation, so a test asserting the implementation reproduces them is, on the day it is
written, a tautology. Its value is entirely prospective.

The independent anchor is the hand derivation below, which was worked from the closed forms, and
the published figures in ``README.md``, ``docs/PHYSICS_NOTES.md`` and ``docs/SPEC_SHEET.md``.
``test_mk0_reproduction.py`` binds the computed chain to those published strings, so the docs and
the code cannot drift apart quietly either.

Nothing here is validated
-------------------------
Every figure below descends from ``k_geo``, which is an ``analytical-placeholder`` carrying an
order-of-magnitude band (see :mod:`ehdpsu.basis` and
``artifacts/04_BreadCrumbs/2026-09-15_mk0_retrospective.jsonld``). Current, power, thrust and
efficiency therefore inherit that ceiling — *principle 1, trust is a ceiling inherited from
provenance*. Reproducing a number exactly is not evidence that the number is right.

``THRUST_REF_N``, ``THRUST_REF_GF`` and ``EFFICIENCY_REF_N_PER_KW`` are **upper bounds**.
``T = I·d/µ`` assumes full ion-to-neutral momentum transfer with no neutral drag and a uniform
gap field; real thrust is lower.

The hand derivation
-------------------
At the MK0 design point: ``r_wire = 25 µm`` (a RADIUS — read as a diameter these figures move by
29%), ``d_gap = 12 mm``, ``L_wire = 15 cm``, ``µ = 1.5e-4 m²/(V·s)``, ``V_op = 22 kV``,
``f_sw = 250 kHz``, ``N = 5``, ``C_stage = 1 nF``, ``m_rough = 0.8``, ``δ = 1.0``::

    r_cm     = 25e-6 * 100 = 2.5e-3 cm
    E_peek   = 3.1e6 * 0.8 * 1.0 * (1 + 0.308/sqrt(1.0 * 2.5e-3))
             = 2.48e6 * (1 + 0.308/0.05) = 2.48e6 * 7.16 = 1.77568e7 V/m
    V_onset  = E_peek * r * ln(d/r) = 1.77568e7 * 25e-6 * ln(0.012/25e-6)
             = 443.92 * ln(480) = 443.92 * 6.17379 ~= 2740.67 V
    k_pp     = 2 * 8.854e-12 * 1.5e-4 * 0.15 / 0.012**2 = 2.766875e-12 A/V^2
    I        = k_pp * V * (V - V_onset)
             = 2.766875e-12 * 22000 * (22000 - 2740.67) ~= 1.17234e-3 A
    P        = V * I = 22000 * 1.17234e-3 ~= 25.7915 W
    T        = I * d / mu = 1.17234e-3 * 0.012 / 1.5e-4 ~= 0.0937872 N
    gf       = (T / 9.81) * 1000 ~= 9.56036 gf
    eff      = (T / P) * 1000 ~= 3.63636 N/kW
    droop    = (I/(f*C)) * ((2/3)*125 + 0.5*25 - (1/6)*5)
             = (I/2.5e-4) * 95.0 ~= 445.489 V
    ripple   = (I/(f*C)) * (5*6/2) = (I/2.5e-4) * 15 ~= 70.3404 V
"""

from __future__ import annotations

from typing import Final

# --- electrostatics: independent of k_geo, so these carry a genuine analytical-cited basis ----

#: Peek corona-inception surface field at the MK0 emitter [V/m]. Published as 17.76 MV/m.
E_PEEK_REF_V_PER_M: Final = 17756800.0

#: Corona-inception voltage [V]. Published as 2.74 kV.
V_ONSET_REF_V: Final = 2740.6671272441477

# --- the current law: k_geo is the placeholder everything below inherits -----------------------

#: Townsend prefactor, parallel-plate coefficient standing in for a wire-to-plane emitter
#: [A/V²]. ``analytical-placeholder``, roughly a x0.1-to-x1.0 band, UNCALIBRATED — no FEMM run
#: has been performed. Every constant after this one inherits that ceiling.
K_GEO_REF_A_PER_V2: Final = 2.7668749999999996e-12

#: Ion current at the 22 kV operating point [A]. Published as 1.17 mA.
I_ION_REF_A: Final = 0.0011723396661307394

#: DC electrical power [W]. Published as 25.79 W.
POWER_REF_W: Final = 25.791472654876266

# --- thrust and efficiency: UPPER BOUNDS, and labelled as such in every name and comment ------

#: Mobility-limited thrust UPPER BOUND [N]. Published as 0.0938 N. Real thrust is lower.
THRUST_REF_N: Final = 0.09378717329045916

#: The same UPPER BOUND expressed in grams-force. Published as 9.56 gf.
THRUST_REF_GF: Final = 9.560364249791963

#: Thrust efficiency UPPER BOUND [N/kW]. Published as 3.64 N/kW.
EFFICIENCY_REF_N_PER_KW: Final = 3.6363636363636367

# --- the Cockcroft-Walton multiplier: settled formulas, but the current they take is not -------

#: Loaded cascade droop [V]. Published as 445.5 V. Inherits k_geo through the load current.
CW_DROOP_REF_V: Final = 445.489073129681

#: Droop as a percentage of V_op. Published as 2.02%.
CW_DROOP_REF_PERCENT: Final = 2.024950332407641

#: Peak-to-peak output ripple [Vpp]. Published as 70.3 V.
CW_RIPPLE_REF_VPP: Final = 70.34037996784437
