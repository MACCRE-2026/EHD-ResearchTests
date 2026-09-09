"""Pure-function physics core for the EHD thruster power-supply validation.

All functions in this module are **pure** (no I/O, no printing, no global
state) and operate in **SI units** unless a name explicitly states otherwise
(e.g. ``thrust_grams_force``). Unit conversions are performed explicitly at the
boundaries where they occur, and each conversion is noted in the relevant
docstring.

Physics honesty policy
----------------------
Every formula below cites a reference and states its idealizing assumptions.
The one place where the originally-provided sanity script is *geometrically
inconsistent* is the current-law prefactor: the script uses a parallel-plate
(1-D) coefficient ``k_geo = 2*eps0*mu*L/d**2`` for what is physically a
wire-to-plane / coaxial emitter. Rather than silently "fixing" this or
curve-fitting a replacement, this module:

1. keeps the original coefficient but names it
   :func:`geometric_constant_parallel_plate` so the assumption is explicit;
2. documents the wire-cylinder alternative in
   :func:`geometric_constant_wire_cylinder_note`; and
3. treats the coefficient as a **labeled, order-of-magnitude model parameter**,
   not a fitted constant.

Current-law geometry: parallel-plate vs wire-cylinder
-----------------------------------------------------
The corona-driven ion current follows the Townsend quadratic law
``I = k * V * (V - V_onset)`` (see :func:`ion_current`). The quadratic *form*
is well established for a self-sustained unipolar corona discharge. The
prefactor ``k``, however, is geometry-dependent:

* **Parallel-plate (Mott-Gurney-like) form**
  ``k_pp = 2 * eps0 * mu * L / d**2`` (:func:`geometric_constant_parallel_plate`)
  assumes a 1-D space-charge-limited gap of area proportional to ``L`` and
  uniform field ``~V/d``. It is what the original script used.

* **Wire-to-plane / coaxial form**
  The true emitter is a thin wire facing a plane. The standard wire-to-plane
  corona current per unit length is ``i' = C_wp * mu * eps0 * V * (V - V_onset)``
  where ``C_wp`` is an O(1) dimensionless factor set by the wire-to-plane
  geometry (gap/radius ratio) rather than by ``1/d**2``. See
  :func:`geometric_constant_wire_cylinder_note` for the reasoning.

The two prefactors can differ by an order of magnitude for the design geometry
(r_wire = 25 um, d = 12 mm). This module therefore reports currents computed
with the *labeled* parallel-plate coefficient and flags the associated
order-of-magnitude uncertainty rather than presenting a single "true" number.

References
----------
* F. W. Peek, *Dielectric Phenomena in High Voltage Engineering*, 1929.
* E. Kuffel, W. S. Zaengl, J. Kuffel, *High Voltage Engineering: Fundamentals*,
  2nd ed., p. 366 (Peek's law, coaxial field-to-voltage integration).
* T. B. Bahder, C. Fazi, *Force on an Asymmetric Capacitor*, ARL-TR-3005, 2003
  (mobility-limited EHD thrust ``T = I*d/mu`` as an idealized upper bound).
* E. A. Christenson, P. S. Moller, "Ion-neutral propulsion in atmospheric
  media", *AIAA Journal*, 5(10), 1967.
* Standard HV textbook Cockcroft-Walton cascade droop/ripple formulas
  (e.g. Kuffel & Zaengl, cascade generator section).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Physical constants (SI)
EPS0: float = 8.854e-12  # Vacuum permittivity [F/m]
G_EARTH: float = 9.81  # Standard gravity [m/s^2]

# Uniform-field dielectric strength of air at STP. The classic engineering
# figure is ~30 kV/cm = 3.0 MV/m (dry air, sea-level, uniform field, cm-scale
# gaps). See Kuffel & Zaengl, HV Engineering, and any Paschen-curve reference.
AIR_BREAKDOWN_FIELD: float = 3.0e6  # [V/m] (~30 kV/cm)


@dataclass(frozen=True)
class DesignParameters:
    """Design parameters for a single EHD thruster cell and its CW multiplier.

    All fields are SI unless noted. Defaults reproduce the original
    sanity-check script exactly (r_wire = 25 um, d = 12 mm, L = 15 cm,
    mu = 1.5e-4 m^2/(V*s), V_op = 22 kV, f_sw = 250 kHz, N = 5, C = 1 nF).

    Attributes
    ----------
    r_wire_m : float
        Emitter wire radius [m].
    d_gap_m : float
        Emitter-to-collector gap distance [m].
    L_wire_m : float
        Active emitter wire length [m].
    mu_ion : float
        Ion mobility in air [m^2/(V*s)].
    delta : float
        Relative air density factor (1.0 = sea-level standard air).
    m_rough : float
        Peek surface-roughness factor (1.0 = polished, <1 = rough wire).
    V_op : float
        DC operating voltage [V].
    f_sw : float
        Multiplier switching frequency [Hz].
    N_stages : int
        Number of Cockcroft-Walton stages.
    C_stage : float
        Per-stage capacitance [F].
    """

    r_wire_m: float = 25e-6
    d_gap_m: float = 0.012
    L_wire_m: float = 0.15
    mu_ion: float = 1.5e-4
    delta: float = 1.0
    m_rough: float = 0.8
    V_op: float = 22000.0
    f_sw: float = 250000.0
    N_stages: int = 5
    C_stage: float = 1.0e-9


def peek_inception_field(
    r_wire_m: float,
    delta: float = 1.0,
    m_rough: float = 1.0,
    g0: float = 3.1e6,
    c: float = 0.308,
) -> float:
    """Return the Peek corona-inception surface field ``E_peek`` [V/m].

    Uses Peek's empirical law for the visual corona onset gradient on a
    cylindrical conductor::

        E_peek = g0 * m * delta * (1 + c / sqrt(delta * r_cm))

    where ``r_cm`` is the wire radius in **centimetres**. This function converts
    the SI input ``r_wire_m`` to cm internally (``r_cm = r_wire_m * 100``),
    matching the original script (``r_wire * 100``).

    Parameters
    ----------
    r_wire_m : float
        Wire radius [m].
    delta : float
        Relative air density (1.0 = sea-level standard air).
    m_rough : float
        Surface-roughness factor (1.0 polished, ~0.6-0.85 practical wire).
    g0 : float
        Base breakdown gradient [V/m]. Literature: 3.0-3.2e6 V/m.
    c : float
        Peek coefficient [cm^0.5]. Literature: ~0.301-0.308.

    Returns
    -------
    float
        Corona-inception surface field [V/m].

    Assumptions / caveats
    ---------------------
    Peek's law is an *empirical* fit for smooth cylindrical geometry in air. It
    is valid near standard temperature/pressure and for the radius/roughness
    ranges of the original measurements; extrapolation to very thin wires
    carries uncertainty. Reference: Peek 1929; Kuffel & Zaengl, p. 366.
    """
    r_cm = r_wire_m * 100.0
    return g0 * m_rough * delta * (1.0 + c / math.sqrt(delta * r_cm))


def corona_inception_voltage(E_peek: float, r_wire_m: float, d_gap_m: float) -> float:
    """Return the corona-inception voltage ``V_onset`` [V].

    Integrates the coaxial-cylinder field to voltage::

        V_onset = E_peek * r * ln(d / r)

    This is the standard field-to-voltage relation for a thin wire (radius
    ``r``) inside/near a much larger electrode at distance ``d``, i.e. the
    coaxial-cylinder approximation of the wire-to-plane geometry.

    Parameters
    ----------
    E_peek : float
        Peek inception surface field [V/m] (see :func:`peek_inception_field`).
    r_wire_m : float
        Wire radius [m].
    d_gap_m : float
        Gap distance [m].

    Returns
    -------
    float
        Corona-inception voltage [V].

    Assumptions / caveats
    ---------------------
    Assumes a logarithmic (coaxial-cylinder) potential profile, which is exact
    for a wire concentric in a cylinder and a good approximation for
    wire-to-plane at ``d >> r``. Reference: Kuffel & Zaengl, p. 366.
    """
    return E_peek * r_wire_m * math.log(d_gap_m / r_wire_m)


def geometric_constant_parallel_plate(eps0: float, mu: float, L: float, d: float) -> float:
    """Return the **parallel-plate** current-law prefactor ``k_pp`` [A/V^2].

    ::

        k_pp = 2 * eps0 * mu * L / d**2

    This is the coefficient used by the original sanity script. It is a
    parallel-plate / 1-D space-charge-limited (Mott-Gurney-like) approximation:
    it assumes a uniform gap field ``~V/d`` and an emitting area proportional to
    the wire length ``L``.

    Parameters
    ----------
    eps0 : float
        Permittivity [F/m].
    mu : float
        Ion mobility [m^2/(V*s)].
    L : float
        Emitter length [m].
    d : float
        Gap distance [m].

    Returns
    -------
    float
        Prefactor for ``I = k * V * (V - V_onset)`` [A/V^2].

    Assumptions / caveats
    ---------------------
    **Geometrically inconsistent** with the actual wire-to-plane emitter: the
    ``1/d**2`` scaling comes from a planar gap, not a wire corona. It is kept
    here (a) to reproduce the original script's numbers exactly and (b) as a
    clearly-labeled, order-of-magnitude model parameter. It is NOT a curve-fit.
    See :func:`geometric_constant_wire_cylinder_note` for the alternative form
    and the reasoning behind treating this as an O(1)-to-O(10) uncertainty.
    Reference for the Townsend quadratic form: Kuffel & Zaengl (corona current).
    """
    return 2.0 * eps0 * mu * L / d**2


def geometric_constant_wire_cylinder_note() -> str:
    """Return a text note describing the wire-cylinder current-law alternative.

    This helper carries no physics computation; it exists so the wire-to-plane
    reasoning is available programmatically (e.g. for the sanity-check
    ``VALIDATION NOTES`` section) without duplicating the discussion. It is a
    pure function returning a constant string.

    Returns
    -------
    str
        Explanation of the wire-cylinder vs parallel-plate distinction.
    """
    return (
        "Current-law geometry: the Townsend quadratic form "
        "I = k*V*(V - V_onset) is correct, but the prefactor is geometry "
        "dependent. The script's k_pp = 2*eps0*mu*L/d^2 is a PARALLEL-PLATE "
        "(1-D) coefficient (uniform field ~V/d, planar area ~L). The physical "
        "emitter is a wire facing a plane, whose corona current per unit length "
        "scales as i' = C_wp * mu * eps0 * V * (V - V_onset) with C_wp an O(1) "
        "dimensionless factor set by the gap/radius ratio, NOT by 1/d^2. For "
        "r_wire = 25 um and d = 12 mm the two prefactors can differ by roughly "
        "an order of magnitude. We keep the labeled parallel-plate coefficient "
        "and flag this O(1)-to-O(10) uncertainty rather than curve-fitting a "
        "replacement. Refs: Peek 1929; Kuffel & Zaengl; Bahder & Fazi 2003."
    )


def ion_current(V_op: float, V_onset: float, k_geo: float) -> float:
    """Return the corona ion current ``I`` [A] via the Townsend quadratic law.

    ::

        I = k_geo * V * (V - V_onset)   for V > V_onset, else 0

    Parameters
    ----------
    V_op : float
        Operating voltage [V].
    V_onset : float
        Corona-inception voltage [V] (see :func:`corona_inception_voltage`).
    k_geo : float
        Current-law prefactor [A/V^2] (see
        :func:`geometric_constant_parallel_plate`).

    Returns
    -------
    float
        Ion current [A]. Zero when ``V_op <= V_onset`` (no corona).

    Assumptions / caveats
    ---------------------
    The quadratic form is standard for a self-sustained unipolar corona. The
    absolute magnitude inherits the geometry uncertainty of ``k_geo`` (see
    :func:`geometric_constant_parallel_plate`). Reference: Townsend/Kuffel &
    Zaengl corona-current relation.
    """
    if V_op > V_onset:
        return k_geo * V_op * (V_op - V_onset)
    return 0.0


def electrical_power(V_op: float, I_ion: float) -> float:
    """Return DC electrical power ``P = V * I`` [W].

    Parameters
    ----------
    V_op : float
        Operating voltage [V].
    I_ion : float
        Ion current [A].

    Returns
    -------
    float
        Electrical power [W].

    Assumptions / caveats
    ---------------------
    Ideal DC power at the load; ignores driver/multiplier conversion losses.
    """
    return V_op * I_ion


def thrust_newton(I_ion: float, d_gap_m: float, mu_ion: float) -> float:
    """Return mobility-limited EHD thrust ``T = I*d/mu`` [N].

    Parameters
    ----------
    I_ion : float
        Ion current [A].
    d_gap_m : float
        Gap distance [m].
    mu_ion : float
        Ion mobility [m^2/(V*s)].

    Returns
    -------
    float
        Thrust [N].

    Assumptions / caveats
    ---------------------
    ``T = I*d/mu`` is the **idealized mobility-limited upper bound**: it follows
    from ``T = integral(rho*E) dV`` with ``J = rho*mu*E`` and ``I = J*A``, and
    assumes every ion transfers all its momentum to neutrals with no drag losses
    and a uniform gap field. Real thrust is lower (neutral drag, non-uniform
    field, recombination). Reference: Bahder & Fazi, ARL-TR-3005 (2003);
    Christenson & Moller, AIAA J. 5(10), 1967.
    """
    return I_ion * d_gap_m / mu_ion


def thrust_grams_force(thrust_n: float, g: float = G_EARTH) -> float:
    """Convert thrust in newtons to grams-force.

    ::

        grams_force = (T / g) * 1000

    Parameters
    ----------
    thrust_n : float
        Thrust [N].
    g : float
        Gravitational acceleration [m/s^2] (default 9.81).

    Returns
    -------
    float
        Thrust [grams-force].

    Assumptions / caveats
    ---------------------
    Pure unit conversion (1 kgf = g newtons). Boundary conversion N -> gf.
    """
    return (thrust_n / g) * 1000.0


def efficiency_N_per_kW(thrust_n: float, power_w: float) -> float:
    """Return thrust efficiency in newtons per kilowatt [N/kW].

    ::

        eff = (T / P) * 1000   (0 if P <= 0)

    Parameters
    ----------
    thrust_n : float
        Thrust [N].
    power_w : float
        Electrical power [W].

    Returns
    -------
    float
        Efficiency [N/kW]; 0 when ``power_w <= 0``.

    Assumptions / caveats
    ---------------------
    Boundary conversion W -> kW (``*1000`` because N/W * 1000 W/kW = N/kW).
    Inherits the thrust upper-bound caveat of :func:`thrust_newton`.
    """
    if power_w > 0:
        return (thrust_n / power_w) * 1000.0
    return 0.0


def mean_gap_field(V_op: float, d_gap_m: float) -> float:
    """Return the mean (uniform-approximation) gap field ``V/d`` [V/m].

    Parameters
    ----------
    V_op : float
        Operating voltage [V].
    d_gap_m : float
        Gap distance [m].

    Returns
    -------
    float
        Mean gap field [V/m].

    Assumptions / caveats
    ---------------------
    This is the *spatially averaged* field ``V/d``. The real wire-to-plane
    field is highly non-uniform (very high at the wire, low mid-gap), so the
    local field at the emitter greatly exceeds this average. The mean field is
    nonetheless the right quantity to compare against the bulk uniform-field air
    breakdown strength (:data:`AIR_BREAKDOWN_FIELD`) for a whole-gap arc-over
    (sparkover) sanity check.
    """
    return V_op / d_gap_m


def mean_gap_breakdown_margin(
    V_op: float, d_gap_m: float, e_breakdown: float = AIR_BREAKDOWN_FIELD
) -> float:
    """Return the mean-gap-field breakdown margin ``E_breakdown / (V/d)`` (dimensionless).

    ::

        margin = e_breakdown / (V_op / d_gap)

    A margin ``> 1`` means the mean gap field is below the bulk air breakdown
    strength (no full-gap sparkover expected on average); ``< 1`` means the mean
    field exceeds it and a whole-gap arc is likely.

    Parameters
    ----------
    V_op : float
        Operating voltage [V].
    d_gap_m : float
        Gap distance [m].
    e_breakdown : float
        Uniform-field air breakdown strength [V/m]. Defaults to
        :data:`AIR_BREAKDOWN_FIELD` (~3 MV/m = ~30 kV/cm at STP).

    Returns
    -------
    float
        Dimensionless safety margin. ``inf`` when ``V_op <= 0``.

    Assumptions / caveats
    ---------------------
    Compares the *mean* gap field ``V/d`` (see :func:`mean_gap_field`) against
    the STP uniform-field breakdown figure ~30 kV/cm (3 MV/m). This is a
    coarse whole-gap sparkover check: because the wire-to-plane field is
    non-uniform, corona onset (see :func:`corona_inception_voltage`) occurs at
    the wire well *before* the mean field reaches this value. A margin above 1
    therefore does not guarantee corona-free operation; it guards against gross
    gap arc-over. Reference: Kuffel & Zaengl (air breakdown ~30 kV/cm STP).
    """
    field = mean_gap_field(V_op, d_gap_m)
    if field <= 0:
        return math.inf
    return e_breakdown / field


def corona_onset_margin(V_op: float, V_onset: float) -> float:
    """Return the corona onset margin ``V_op / V_onset`` (dimensionless).

    ::

        margin = V_op / V_onset

    A margin ``> 1`` means the supply is driving the emitter above corona
    inception (the intended operating regime); ``< 1`` means no corona (and thus
    no ion current / thrust). Larger values drive more current but push toward
    streamer/spark transition.

    Parameters
    ----------
    V_op : float
        Operating voltage [V].
    V_onset : float
        Corona-inception voltage [V] (see :func:`corona_inception_voltage`).

    Returns
    -------
    float
        Dimensionless onset margin. ``inf`` when ``V_onset <= 0``.

    Assumptions / caveats
    ---------------------
    Purely the ratio of operating to inception voltage; it says nothing about
    the streamer/spark upper limit, which the mean-gap-field breakdown margin
    (:func:`mean_gap_breakdown_margin`) addresses.
    """
    if V_onset <= 0:
        return math.inf
    return V_op / V_onset


def cw_voltage_droop(I_load: float, f_sw: float, C_stage: float, N_stages: int) -> float:
    """Return Cockcroft-Walton cascade DC voltage droop ``V_droop`` [V].

    Standard HV textbook cascade formula::

        V_droop = (I / (f * C)) * ((2/3)*N**3 + (1/2)*N**2 - (1/6)*N)

    Parameters
    ----------
    I_load : float
        Load (ion) current [A].
    f_sw : float
        Switching frequency [Hz].
    C_stage : float
        Per-stage capacitance [F].
    N_stages : int
        Number of stages.

    Returns
    -------
    float
        Mean DC voltage droop under load [V].

    Assumptions / caveats
    ---------------------
    Assumes equal per-stage capacitance, steady-state load, and the classic
    symmetric-cascade derivation. Reference: standard HV texts (Kuffel &
    Zaengl, cascade generator section).
    """
    n = float(N_stages)
    return (I_load / (f_sw * C_stage)) * ((2.0 / 3.0) * n**3 + 0.5 * n**2 - (1.0 / 6.0) * n)


def cw_ripple_pp(I_load: float, f_sw: float, C_stage: float, N_stages: int) -> float:
    """Return Cockcroft-Walton peak-to-peak output ripple ``V_ripple`` [V].

    Standard HV textbook cascade formula::

        V_ripple = (I / (f * C)) * (N * (N + 1) / 2)

    Parameters
    ----------
    I_load : float
        Load (ion) current [A].
    f_sw : float
        Switching frequency [Hz].
    C_stage : float
        Per-stage capacitance [F].
    N_stages : int
        Number of stages.

    Returns
    -------
    float
        Peak-to-peak output ripple [V].

    Assumptions / caveats
    ---------------------
    Same cascade assumptions as :func:`cw_voltage_droop`. Reference: standard
    HV texts (Kuffel & Zaengl, cascade generator section).
    """
    n = float(N_stages)
    return (I_load / (f_sw * C_stage)) * (n * (n + 1.0) / 2.0)
