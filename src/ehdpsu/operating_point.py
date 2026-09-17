"""The derived operating point, as Quantities rather than floats.

This is the seam where a computed number acquires its unit, band, basis and references. Everything
here is **derived**; nothing is stored. A profile holds design inputs, this module holds what they
imply, and the two are never mixed — a stored derivation is a second representation of its inputs.

Why the pure float functions in :mod:`ehdpsu.physics` were not changed
---------------------------------------------------------------------
They stay float-in, float-out, and this module wraps them. Three reasons, in order of weight:

1. **``docs/PHYSICS_NOTES.md`` records a formula-by-formula verdict** — *correct as written*,
   *correct in form but an idealised upper bound*, and so on. Those verdicts are about the closed
   forms in ``physics.py``. Rewriting them to shuffle Quantities would change the thing that was
   reviewed, and the review would silently stop applying.
2. **The MK0 reference figures must keep reproducing bit-identically.** Leaving the arithmetic
   untouched makes that a fact rather than a hope, and a Quantity wrapper cannot perturb a number it
   does not compute.
3. **Computing and attributing are different jobs.** A pure function is the right shape for a cited
   relation; provenance is bookkeeping about that relation. Merging them would put both in one place
   and make neither testable alone.

This is a wrapper, not a second implementation. There is exactly one piece of arithmetic per
quantity and it lives in ``physics.py``.

Why every basis here comes out ``claimed``
------------------------------------------
Low-water-mark over the inputs, and every MK0 profile field is ``claimed`` — a design choice is an
assertion until the built article is measured, and ion mobility is a literature figure.

So a value computed by a correctly cited closed form over ``claimed`` inputs is ``claimed``. The
citation does not raise it; the citation goes in ``refs``. ``analytical-cited`` describes a value
that is *itself* a reference figure, or one whose inputs are better than claimed. That distinction
is the whole point of the ladder: *what is known about this number*, not *how carefully was it
computed*.

The consequence is that **the model uncertainty is carried by the band and the provenance by the
basis**, and they are genuinely different axes. ``k_geo`` being a placeholder shows up as a ×10
band, not as a lower basis, once the inputs are already at the floor.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import physics
from .basis import Basis
from .profile import Profile
from .quantity import Band, Quantity

# ---------------------------------------------------------------------------
# Model-form uncertainty
# ---------------------------------------------------------------------------
#
# This band is a property of the RELATION, not of any input, which is why it lives here rather than
# in a profile. `k_geo = 2*eps0*mu*L/d^2` is a parallel-plate (1-D space-charge-limited) coefficient
# standing in for a wire-to-plane emitter. The quadratic Townsend *form* is well established; the
# prefactor's geometry is not.
#
# x0.1 to x1.0 -- an order of magnitude, biased low, because the parallel-plate form is expected to
# OVERSTATE the current for a thin wire at this gap. It is a labelled model parameter, never a
# fitted constant: no measurement has been used to choose it, and none may be.
#
# UNCALIBRATED. No FEMM run has been performed. Fitting this to a measured I-V curve is a real task
# (plan Task 14) and it will *narrow* the band with recorded provenance; it will not "fix" the value.
K_GEO_MODEL_BAND = Band(0.1, 1.0)

#: References attached to the quantities that descend from each relation.
PEEK_REFS = ("Peek 1929", "Kuffel & Zaengl p.366")
TOWNSEND_REFS = ("Kuffel & Zaengl, corona current",)
THRUST_REFS = ("Bahder & Fazi, ARL-TR-3005 (2003)", "Christenson & Moller, AIAA J. 5(10), 1967")
CASCADE_REFS = ("Kuffel & Zaengl, cascade generator section",)


@dataclass(frozen=True)
class OperatingPoint:
    """Every derived figure for one design, each carrying what is known about it.

    Field names carry units, as everywhere else in this project. ``thrust`` and ``efficiency`` are
    **upper bounds** and say so in their own ``is_upper_bound`` flag, so no formatting path can drop
    the label.
    """

    e_peek: Quantity
    v_onset: Quantity
    k_geo: Quantity
    i_ion: Quantity
    power: Quantity
    thrust: Quantity
    efficiency: Quantity
    cw_droop: Quantity
    cw_ripple: Quantity
    onset_margin: Quantity
    breakdown_margin: Quantity

    def as_dict(self) -> dict[str, Quantity]:
        """Return the figures by name, in declaration order."""
        return {
            "e_peek": self.e_peek,
            "v_onset": self.v_onset,
            "k_geo": self.k_geo,
            "i_ion": self.i_ion,
            "power": self.power,
            "thrust": self.thrust,
            "efficiency": self.efficiency,
            "cw_droop": self.cw_droop,
            "cw_ripple": self.cw_ripple,
            "onset_margin": self.onset_margin,
            "breakdown_margin": self.breakdown_margin,
        }

    @property
    def ceiling(self) -> Basis:
        """The worst basis across every derived figure."""
        return min(q.basis for q in self.as_dict().values())

    def report_lines(self) -> list[str]:
        """One fully-qualified line per figure, for a report or a console summary.

        Uses :meth:`Quantity.describe`, so the band, the basis and the upper-bound label travel with
        every number. *Physics honesty rule 4:* labelled everywhere it appears, not once in a
        footnote.
        """
        return [f"{name:18s} {q.describe()}" for name, q in self.as_dict().items()]


def operating_point(prof: Profile, k_geo_band: Band = K_GEO_MODEL_BAND) -> OperatingPoint:
    """Compute every derived figure for ``prof``.

    The arithmetic is entirely :mod:`ehdpsu.physics`; this function supplies units, bands, bases and
    references, and decides which figures are ceilings.

    Parameters
    ----------
    prof : Profile
        The design. Every input is read from it; nothing is defaulted.
    k_geo_band : Band
        The current-law model-form uncertainty, defaulting to :data:`K_GEO_MODEL_BAND`.

        Injectable rather than read from the module constant so the propagation can be
        *demonstrated* rather than asserted: widening it widens thrust, power, droop and ripple
        together, and leaves ``e_peek``, ``v_onset``, ``efficiency`` and the margins untouched,
        because none of those depends on ``k_geo``. An uncertainty layer that widened every figure
        would be indistinguishable from one that had not been thought about.

        This is **not** a tuning knob. Narrowing it requires a calibration with recorded
        provenance — plan Task 14, fitting against a measured I-V curve — not a judgement that the
        model is probably fine.
    """
    # --- profile inputs, as Quantities so their basis reaches the results -------------------
    # Only the inputs that take part in a Quantity-level calculation are wrapped. The rest are read
    # as floats and handed to the pure physics functions, with their basis gathered via
    # `prof.ceiling(...)` per figure -- wrapping every input would create Quantities that exist only
    # to be unused, which reads as an oversight rather than as a decision.
    d_gap = Quantity(prof.required("d_gap_m"), "m", basis=prof.basis_of("d_gap_m"))
    v_op = Quantity(prof.required("V_op_V"), "V", basis=prof.basis_of("V_op_V"))
    mu_ion = Quantity(
        prof.required("mu_ion_m2_per_Vs"),
        "m^2/(V*s)",
        basis=prof.basis_of("mu_ion_m2_per_Vs"),
        refs=("Kuffel & Zaengl p.366",),
    )
    inputs_basis = prof.ceiling(
        [
            "r_wire_m",
            "L_wire_m",
            "m_rough_factor",
            "d_gap_m",
            "delta_air_density",
            "mu_ion_m2_per_Vs",
            "V_op_V",
            "f_sw_Hz",
            "N_stages",
            "C_stage_F",
        ]
    )

    # --- electrostatics: independent of k_geo ------------------------------------------------
    e_peek_value = physics.peek_inception_field(
        prof.required("r_wire_m"),
        prof.required("delta_air_density"),
        prof.required("m_rough_factor"),
    )
    e_peek = Quantity(
        e_peek_value,
        "V/m",
        basis=prof.ceiling(["r_wire_m", "delta_air_density", "m_rough_factor"]),
        refs=PEEK_REFS,
        note=(
            "Peek's law is EMPIRICAL and fitted for smooth cylindrical geometry near STP; "
            "extrapolation to a 25 um wire carries uncertainty this band does not express."
        ),
    )
    v_onset = Quantity(
        physics.corona_inception_voltage(
            e_peek_value, prof.required("r_wire_m"), prof.required("d_gap_m")
        ),
        "V",
        basis=prof.ceiling(["r_wire_m", "delta_air_density", "m_rough_factor", "d_gap_m"]),
        refs=PEEK_REFS,
        note=(
            "Assumes a logarithmic coaxial potential profile, exact for a wire in a cylinder and a "
            "good approximation for wire-to-plane at d >> r."
        ),
    )

    # --- the current law: k_geo is where the model uncertainty enters -------------------------
    k_geo = Quantity(
        physics.geometric_constant_parallel_plate(
            physics.EPS0,
            prof.required("mu_ion_m2_per_Vs"),
            prof.required("L_wire_m"),
            prof.required("d_gap_m"),
        ),
        "A/V^2",
        band=k_geo_band,
        basis=prof.ceiling(["mu_ion_m2_per_Vs", "L_wire_m", "d_gap_m"]),
        refs=TOWNSEND_REFS,
        note=(
            "PARALLEL-PLATE coefficient on a wire-to-plane emitter: geometrically inconsistent, "
            "kept deliberately and labelled rather than replaced with something that fits. "
            "UNCALIBRATED - no FEMM run has been performed."
        ),
    )
    i_ion_value = physics.ion_current(prof.required("V_op_V"), v_onset.value, k_geo.value)
    i_ion = Quantity(
        i_ion_value,
        "A",
        band=k_geo.band,
        basis=inputs_basis,
        refs=TOWNSEND_REFS,
        note="Inherits the k_geo model band; the quadratic form itself is well established.",
    )
    power = Quantity(
        physics.electrical_power(prof.required("V_op_V"), i_ion_value),
        "W",
        band=k_geo.band,
        basis=inputs_basis,
        note="Ideal DC power at the load; ignores driver and multiplier conversion losses.",
    )

    # --- thrust and efficiency: both UPPER BOUNDS -------------------------------------------
    thrust = Quantity(
        physics.thrust_newton(
            i_ion_value, prof.required("d_gap_m"), prof.required("mu_ion_m2_per_Vs")
        ),
        "N",
        band=k_geo.band,
        basis=inputs_basis,
        refs=THRUST_REFS,
        is_upper_bound=True,
        note=(
            "MOBILITY-LIMITED CEILING: assumes every ion transfers all its momentum to neutrals, "
            "with no neutral drag and a uniform gap field. Real thrust is LOWER. No drag term "
            "exists in the suite yet."
        ),
    )

    # Efficiency comes from its OWN relation, d/(mu*V), and not from thrust/power.
    #
    # F/P = (I*d/mu) / (V*I) = d/(mu*V). The k_geo factor CANCELS -- it never appears in efficiency
    # at all -- so the honest band from k_geo is EXACT. Dividing the two derived Quantities would
    # report a x100 band from two x10 inputs, because the Quantity layer treats correlated operands
    # as independent and cannot see that the same factor sits in both.
    #
    # Special-casing that cancellation inside the arithmetic would be a hidden tightening. Deriving
    # each published quantity from its own cited relation is the general fix, and the disagreement
    # between the two routes is Task 9's output rather than something reconciled here.
    efficiency = d_gap / (mu_ion * v_op)
    efficiency = Quantity(
        efficiency.value,
        "N/W",
        band=efficiency.band,
        basis=efficiency.basis,
        refs=THRUST_REFS,
        is_upper_bound=True,
        note=(
            "F/P = d/(mu*V). Independent of k_geo, so its band does not inherit the x10. Still an "
            "UPPER BOUND: it is the ratio of a ceiling thrust to the same power."
        ),
    )

    # --- the multiplier: settled formulas, taking a current that is not settled ---------------
    cw_droop = Quantity(
        physics.cw_voltage_droop(
            i_ion_value,
            prof.required("f_sw_Hz"),
            prof.required("C_stage_F"),
            prof.count("N_stages"),
        ),
        "V",
        band=k_geo.band,
        basis=inputs_basis,
        refs=CASCADE_REFS,
        note="Droop grows as N^3. Inherits the k_geo band through the load current.",
    )
    cw_ripple = Quantity(
        physics.cw_ripple_pp(
            i_ion_value,
            prof.required("f_sw_Hz"),
            prof.required("C_stage_F"),
            prof.count("N_stages"),
        ),
        "V",
        band=k_geo.band,
        basis=inputs_basis,
        refs=CASCADE_REFS,
    )

    # --- margins ----------------------------------------------------------------------------
    onset_margin = Quantity(
        physics.corona_onset_margin(prof.required("V_op_V"), v_onset.value),
        "1",
        basis=v_onset.basis,
        note="V_op / V_onset. Says nothing about the streamer-to-spark upper limit.",
    )
    breakdown_margin = Quantity(
        physics.mean_gap_breakdown_margin(prof.required("V_op_V"), prof.required("d_gap_m")),
        "1",
        basis=prof.ceiling(["V_op_V", "d_gap_m"]),
        refs=("Kuffel & Zaengl, air breakdown ~30 kV/cm STP",),
        note=(
            "Compares the MEAN gap field against the uniform-field breakdown figure. Because the "
            "wire-to-plane field is non-uniform, corona onset occurs at the wire well before the "
            "mean field reaches this value: a margin above 1 does not mean corona-free."
        ),
    )

    return OperatingPoint(
        e_peek=e_peek,
        v_onset=v_onset,
        k_geo=k_geo,
        i_ion=i_ion,
        power=power,
        thrust=thrust,
        efficiency=efficiency,
        cw_droop=cw_droop,
        cw_ripple=cw_ripple,
        onset_margin=onset_margin,
        breakdown_margin=breakdown_margin,
    )
