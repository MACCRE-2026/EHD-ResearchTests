"""End-to-end MK0 reproduction: the whole chain, at full precision, bound to the published docs.

Why this module exists when ``test_physics.py`` already pins every figure
------------------------------------------------------------------------
``test_physics.py`` tests each function **in isolation**, handing it pinned constants as inputs.
Nothing in it ever feeds one stage's output into the next, so the composition is never executed.
A wiring defect — ``ion_current`` receiving a stale onset voltage, or a ``k_geo`` computed from
the wrong gap — would leave every test in that file green.

*Principle 6, a green test suite is not evidence of a working system.* The seam between these
functions is precisely the place no stubbed or isolated test visits, so this module runs the chain
from :class:`~ehdpsu.physics.DesignParameters` alone and lets each stage consume the real output
of the one before it.

Three things are checked, and they are different claims
------------------------------------------------------
1. **The chain reproduces the pinned figures** at ``rtol=1e-12``, roughly four orders tighter
   than the ``1e-4``/``1e-6`` tolerances the per-function tests use. This is the "full precision"
   the plan asked for.
2. **The chain is genuinely composed**, proved by perturbation rather than asserted. ``m_rough``
   enters only through Peek's law and ``L_wire_m`` only through ``k_geo``; if moving either one
   fails to move the thrust, the corresponding input is not reaching the current law.
3. **The code and the documents agree.** Every published figure string is regenerated from the
   live computation and located in the documents that carry it, so ``README.md`` and the docs
   cannot quietly drift away from the code. This is the live problem ``profile-seam.md`` names:
   five representations of the 22 kV design point exist in this repository.

Why the tolerance is not zero
-----------------------------
The chain calls ``math.log`` and ``math.sqrt``, which are libm-backed and may differ by an ULP
across platforms and C libraries. Demanding bit-identity would fail a legitimate Linux clone for
a reason that has nothing to do with physics, and a test that goes red for the wrong reason
trains people to ignore it. ``1e-12`` admits a few ULP and nothing meaningful.

What reproduction does NOT establish
------------------------------------
That any of these numbers is **right**. The pins were captured from the implementation, so on the
day they were written the comparison was a tautology; its value is prospective. And everything
downstream of ``k_geo`` inherits an ``analytical-placeholder`` basis with an order-of-magnitude
band — *principle 1, trust is a ceiling inherited from provenance*. Thrust and efficiency are
additionally **upper bounds**. Reproducing a figure exactly says only that it has not moved.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from conftest import reference_design, reference_profile, reference_spice_params

from ehdpsu import physics, profile
from ehdpsu.basis import Basis, may_be_called_validated
from ehdpsu.mk0_reference import (
    CW_DROOP_REF_PERCENT,
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
from ehdpsu.physics import EPS0, DesignParameters
from ehdpsu.spice import SpiceParams

REPO_ROOT = Path(__file__).resolve().parents[1]

# Full precision, four orders tighter than the per-function tests. See the module docstring for
# why this is not exact equality.
RTOL = 1e-12


def run_mk0_chain(params: DesignParameters) -> dict[str, float]:
    """Run the whole MK0 chain, each stage consuming the previous stage's real output.

    This is the composition ``test_physics.py`` cannot exercise. Note that no pinned constant
    appears as an *input* anywhere below: everything after ``params`` is computed.
    """
    e_peek = physics.peek_inception_field(params.r_wire_m, params.delta, params.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, params.r_wire_m, params.d_gap_m)
    k_geo = physics.geometric_constant_parallel_plate(
        EPS0, params.mu_ion, params.L_wire_m, params.d_gap_m
    )
    i_ion = physics.ion_current(params.V_op, v_onset, k_geo)
    power = physics.electrical_power(params.V_op, i_ion)
    thrust_n = physics.thrust_newton(i_ion, params.d_gap_m, params.mu_ion)
    thrust_gf = physics.thrust_grams_force(thrust_n)
    efficiency = physics.efficiency_N_per_kW(thrust_n, power)
    droop_v = physics.cw_voltage_droop(i_ion, params.f_sw, params.C_stage, params.N_stages)
    ripple_vpp = physics.cw_ripple_pp(i_ion, params.f_sw, params.C_stage, params.N_stages)
    return {
        "e_peek": e_peek,
        "v_onset": v_onset,
        "k_geo": k_geo,
        "i_ion": i_ion,
        "power": power,
        "thrust_n": thrust_n,
        "thrust_gf": thrust_gf,
        "efficiency": efficiency,
        "droop_v": droop_v,
        "droop_pct": droop_v / params.V_op * 100.0,
        "ripple_vpp": ripple_vpp,
    }


@pytest.fixture(scope="module")
def mk0() -> dict[str, float]:
    """The MK0 chain at the committed design defaults."""
    return run_mk0_chain(reference_design())


# ---------------------------------------------------------------------------
# 1. The chain reproduces every pinned figure, at full precision.
# ---------------------------------------------------------------------------

CHAIN_PINS: list[tuple[str, float]] = [
    ("e_peek", E_PEEK_REF_V_PER_M),
    ("v_onset", V_ONSET_REF_V),
    ("k_geo", K_GEO_REF_A_PER_V2),
    ("i_ion", I_ION_REF_A),
    ("power", POWER_REF_W),
    ("thrust_n", THRUST_REF_N),
    ("thrust_gf", THRUST_REF_GF),
    ("efficiency", EFFICIENCY_REF_N_PER_KW),
    ("droop_v", CW_DROOP_REF_V),
    ("droop_pct", CW_DROOP_REF_PERCENT),
    ("ripple_vpp", CW_RIPPLE_REF_VPP),
]


@pytest.mark.parametrize(("key", "expected"), CHAIN_PINS, ids=[k for k, _ in CHAIN_PINS])
def test_chain_reproduces_pinned_figure(mk0: dict[str, float], key: str, expected: float) -> None:
    assert np.isclose(mk0[key], expected, rtol=RTOL, atol=0.0), (
        f"{key} computed as {mk0[key]!r} but the pinned MK0 reference is {expected!r}. If this "
        f"change is intended, update ehdpsu/mk0_reference.py and say in the ledger what moved "
        f"and why."
    )


def test_every_pinned_reference_is_covered() -> None:
    """No pinned constant may sit in ``mk0_reference`` without appearing in the chain check.

    A reference value nothing compares against is decoration. This fails when a constant is added
    to the module and not wired in here — the omission would otherwise be invisible, since the
    remaining tests would all still pass.
    """
    from ehdpsu import mk0_reference

    exported = {name for name in vars(mk0_reference) if name.isupper() and not name.startswith("_")}
    covered = {
        "E_PEEK_REF_V_PER_M",
        "V_ONSET_REF_V",
        "K_GEO_REF_A_PER_V2",
        "I_ION_REF_A",
        "POWER_REF_W",
        "THRUST_REF_N",
        "THRUST_REF_GF",
        "EFFICIENCY_REF_N_PER_KW",
        "CW_DROOP_REF_V",
        "CW_DROOP_REF_PERCENT",
        "CW_RIPPLE_REF_VPP",
    }
    assert exported == covered, (
        f"ehdpsu.mk0_reference exports {sorted(exported)} but this module checks "
        f"{sorted(covered)}. Every pinned reference needs a comparison, or it asserts nothing."
    )


# ---------------------------------------------------------------------------
# 2. The chain is genuinely composed. Proved by perturbation, not asserted.
# ---------------------------------------------------------------------------


def test_roughness_reaches_the_current_law(mk0: dict[str, float]) -> None:
    """``m_rough`` enters ONLY through Peek's law, so it must still move the thrust.

    The targeted probe: if ``ion_current`` were fed a constant or stale onset voltage instead of
    the computed one, this figure would not budge and every isolated test would stay green.

    Direction is checked too, not just movement. A rougher wire lowers ``E_peek``, which lowers
    ``V_onset``, which *raises* ``I = k·V·(V − V_onset)``.
    """
    rougher = run_mk0_chain(dataclasses.replace(reference_design(), m_rough=0.4))

    assert rougher["e_peek"] < mk0["e_peek"]
    assert rougher["v_onset"] < mk0["v_onset"]
    assert rougher["i_ion"] > mk0["i_ion"], (
        "lowering the roughness factor did not raise the ion current, so the computed onset "
        "voltage is not reaching the current law"
    )
    assert rougher["thrust_n"] > mk0["thrust_n"]
    # k_geo does not depend on roughness, and must be untouched.
    assert rougher["k_geo"] == mk0["k_geo"]


def test_wire_length_reaches_the_current_law(mk0: dict[str, float]) -> None:
    """``L_wire_m`` enters ONLY through ``k_geo``, and ``k_geo`` is linear in it.

    So doubling the emitter length must double both ``k_geo`` and the current, exactly. This is
    the other half of ``ion_current``'s wiring: the previous test proves the onset arrives, this
    one proves the prefactor does.
    """
    base = reference_design()
    longer = run_mk0_chain(dataclasses.replace(base, L_wire_m=base.L_wire_m * 2.0))

    assert np.isclose(longer["k_geo"], 2.0 * mk0["k_geo"], rtol=RTOL)
    assert np.isclose(longer["i_ion"], 2.0 * mk0["i_ion"], rtol=RTOL)
    assert np.isclose(longer["thrust_n"], 2.0 * mk0["thrust_n"], rtol=RTOL)
    # Electrostatics is independent of emitter length, and must not move.
    assert longer["e_peek"] == mk0["e_peek"]
    assert longer["v_onset"] == mk0["v_onset"]


def test_efficiency_is_insensitive_to_wire_length(mk0: dict[str, float]) -> None:
    """``F/P = d/(µV)`` — doubling the current doubles thrust and power together.

    Stated as a test because conflating thrust-per-watt with thrust-per-mass is the specific
    scaling error this project's source material makes. Efficiency must not improve just because
    the emitter got longer.
    """
    base = reference_design()
    longer = run_mk0_chain(dataclasses.replace(base, L_wire_m=base.L_wire_m * 2.0))
    assert np.isclose(longer["efficiency"], mk0["efficiency"], rtol=RTOL)


# ---------------------------------------------------------------------------
# 3. The documents agree with the code.
# ---------------------------------------------------------------------------

README = "README.md"
NOTES = "docs/PHYSICS_NOTES.md"
SPEC = "docs/SPEC_SHEET.md"

# (label, formatter over the live chain, documents that must carry the figure).
#
# The formatter regenerates the published string FROM the computation, so the figure is never
# typed twice. Only the document list is declared by hand.
#
# The SPEC_SHEET subset is deliberate: it quotes the electrostatics, thrust, efficiency and droop
# figures but not current, power, raw newtons or ripple.
PUBLISHED_FIGURES: list[tuple[str, Callable[[dict[str, float]], str], tuple[str, ...]]] = [
    ("E_peek", lambda c: f"{c['e_peek'] / 1e6:.2f} MV/m", (README, NOTES, SPEC)),
    ("V_onset", lambda c: f"{c['v_onset'] / 1e3:.2f} kV", (README, NOTES, SPEC)),
    ("I_ion", lambda c: f"{c['i_ion'] * 1e3:.2f} mA", (README, NOTES)),
    ("power", lambda c: f"{c['power']:.2f} W", (README, NOTES)),
    ("thrust_N", lambda c: f"{c['thrust_n']:.4f} N", (README, NOTES)),
    ("thrust_gf", lambda c: f"{c['thrust_gf']:.2f} gf", (README, NOTES, SPEC)),
    ("efficiency", lambda c: f"{c['efficiency']:.2f} N/kW", (README, NOTES, SPEC)),
    ("droop_V", lambda c: f"{c['droop_v']:.1f} V", (README, NOTES, SPEC)),
    ("droop_pct", lambda c: f"({c['droop_pct']:.2f}%)", (README, NOTES)),
    ("ripple_Vpp", lambda c: f"{c['ripple_vpp']:.1f} V", (README, NOTES)),
]


@pytest.mark.parametrize(
    ("label", "formatter", "documents"),
    PUBLISHED_FIGURES,
    ids=[label for label, _, _ in PUBLISHED_FIGURES],
)
def test_published_figure_matches_the_documents(
    mk0: dict[str, float],
    label: str,
    formatter: Callable[[dict[str, float]], str],
    documents: tuple[str, ...],
) -> None:
    """Each document carrying a figure must carry the one the code currently produces.

    Scope, stated rather than implied: this is a **presence** check. It fails when the code's
    output no longer appears in a document, which is the drift that matters. It cannot detect a
    document that contains both the right figure and a stale one somewhere else — a blanket
    "every number in these files must match" scan is not available, because the docs legitimately
    quote other quantities in the same units (``3 MV/m`` for air breakdown, ``13.28 MV/m`` for a
    50 µm wire, ``1.74 kV`` for droop at N=8).
    """
    expected = formatter(mk0)
    for document in documents:
        path = REPO_ROOT / document
        assert path.is_file(), f"{document} is missing, so the {label} claim cannot be checked"
        text = path.read_text(encoding="utf-8")
        assert expected in text, (
            f"{document} does not contain the {label} figure the code produces ({expected!r}). "
            f"Either the physics moved and the document is now stale, or the document was edited "
            f"away from the code."
        )


def test_upper_bound_caveat_travels_with_the_thrust_figures() -> None:
    """Every document quoting thrust or efficiency also labels it an upper bound.

    *Physics honesty rule 4:* an upper bound is labelled an upper bound **everywhere** it appears,
    not once in a footnote. ``T = I·d/µ`` assumes full ion-to-neutral momentum transfer with no
    drag; a ceiling quoted without its label becomes a prediction the moment somebody repeats it.
    """
    for document in (README, NOTES, SPEC):
        text = (REPO_ROOT / document).read_text(encoding="utf-8").lower()
        assert "upper bound" in text or "ceiling" in text, (
            f"{document} quotes the thrust or efficiency figures without the words 'upper bound' "
            f"or 'ceiling' anywhere in it."
        )


# ---------------------------------------------------------------------------
# 4. The pins must not become circular.
# ---------------------------------------------------------------------------


class TestProfileReproducesMk0:
    """The plan's Task 7 demo: the reference figures come back from the profile file alone.

    This is what makes the profile the seam rather than a sixth copy of the design point. The
    chain below is fed from ``profiles/mk0_benchtop_22kv.json`` and nothing else.
    """

    @staticmethod
    def _from_profile() -> dict[str, float]:
        prof = reference_profile()
        return run_mk0_chain(DesignParameters.from_profile(prof))

    @pytest.mark.parametrize(("key", "expected"), CHAIN_PINS, ids=[k for k, _ in CHAIN_PINS])
    def test_profile_reproduces_pinned_figure(self, key: str, expected: float) -> None:
        assert np.isclose(self._from_profile()[key], expected, rtol=RTOL, atol=0.0)

    def test_profile_chain_is_identical_to_the_defaults_chain(self, mk0: dict[str, float]) -> None:
        """Bit-identical, not merely close.

        Same floats through the same functions on the same machine, so there is no libm variation
        to absorb here — and this is the assertion that makes switching the call sites over to the
        profile a change that provably moves no number.
        """
        assert self._from_profile() == mk0

    def test_the_ceiling_the_profile_imposes_is_claimed(self) -> None:
        """And it is one tier BELOW what the BreadCrumb corpus recorded. Deliberately.

        The corpus modelled the provenance of the formulas. The profile models the provenance of
        the inputs, and the inputs are operator choices and literature figures that nothing has
        measured. So every MK0 quantity is ceilinged at ``claimed``, not
        ``analytical-placeholder``.

        Asserted so the discrepancy cannot be quietly resolved in the flattering direction. If
        somebody wants the higher tier back, they need a measurement, not an edit.
        """
        prof = reference_profile()
        assert prof.ceiling() is Basis.CLAIMED
        assert not may_be_called_validated(prof.ceiling())


class TestNoSecondHomeForADesignValue:
    """The design point exists once, and the dataclasses cannot supply one themselves.

    This replaced an interim parity check. That check asserted the hardcoded defaults *equalled*
    the profile, which was the best available guarantee while both existed. The defaults are now
    gone, so equality is no longer the property worth testing — **absence** is. These tests fail if
    someone re-adds a default, which is the easy and well-intentioned edit that would silently undo
    the migration.

    The mapping tables are the only place the dataclass and profile field names sit side by side.
    """

    # dataclass attribute -> profile field name
    DESIGN_MAP: ClassVar[dict[str, str]] = {
        "r_wire_m": "r_wire_m",
        "d_gap_m": "d_gap_m",
        "L_wire_m": "L_wire_m",
        "mu_ion": "mu_ion_m2_per_Vs",
        "delta": "delta_air_density",
        "m_rough": "m_rough_factor",
        "V_op": "V_op_V",
        "f_sw": "f_sw_Hz",
        "N_stages": "N_stages",
        "C_stage": "C_stage_F",
    }

    SPICE_MAP: ClassVar[dict[str, str]] = {
        "v_bus": "V_bus_V",
        "lr_h": "L_r_H",
        "cr_f": "C_r_F",
        "lm_h": "L_m_H",
        "k_coupling": "k_coupling",
        "c_sec_f": "C_sec_F",
        "turns_ratio": "turns_ratio_sec_per_pri",
        "deadtime_frac": "deadtime_frac",
        "diode_bv": "diode_BV_V",
        "diode_cjo": "diode_Cjo_F",
        "diode_rs": "diode_Rs_ohm",
        "diode_tt": "diode_tt_s",
        "diode_is": "diode_Is_A",
        "diode_n": "diode_n",
    }

    @staticmethod
    def _profile() -> profile.Profile:
        return reference_profile()

    @pytest.mark.parametrize("cls", [DesignParameters, SpiceParams])
    def test_no_field_carries_a_default(self, cls: type) -> None:
        """Every field is required, so an instance cannot exist without a profile behind it.

        A default here would be a design value living in code, and it would keep working while
        disagreeing with the profile. Making the fields required means the failure is a
        ``TypeError`` at construction rather than a wrong number three modules away.
        """
        offenders = [
            f.name
            for f in dataclasses.fields(cls)
            if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
        ]
        assert not offenders, (
            f"{cls.__name__} has defaults for {offenders}. A design value in code is a second "
            f"home for it; build these from a profile instead."
        )

    def test_spice_params_no_longer_carries_a_switching_frequency(self) -> None:
        """The duplicate was removed, not reconciled.

        ``SpiceParams.f_sw_hz`` duplicated ``DesignParameters.f_sw``, and ``build_netlist``
        papered over any disagreement by overwriting whichever the caller passed. Silently
        reconciling a disagreement is worse than reporting it — so the field is gone, and
        ``_llc_primary`` takes the frequency as an argument sourced from the profile.
        """
        assert "f_sw_hz" not in {f.name for f in dataclasses.fields(SpiceParams)}
        assert "f_sw_hz" not in self.SPICE_MAP.values()

    def test_every_design_field_comes_from_the_profile(self) -> None:
        prof = self._profile()
        built = DesignParameters.from_profile(prof)
        for attribute, field_name in self.DESIGN_MAP.items():
            assert getattr(built, attribute) == prof.value(
                field_name
            ), f"DesignParameters.{attribute} does not match profile {field_name}"

    def test_every_spice_field_comes_from_the_profile(self) -> None:
        prof = self._profile()
        built = SpiceParams.from_profile(prof)
        for attribute, field_name in self.SPICE_MAP.items():
            assert getattr(built, attribute) == prof.value(
                field_name
            ), f"SpiceParams.{attribute} does not match profile {field_name}"

    def test_the_maps_cover_every_dataclass_field(self) -> None:
        """A field added without a profile source would otherwise escape these checks."""
        design_fields = {f.name for f in dataclasses.fields(DesignParameters)}
        assert design_fields == set(self.DESIGN_MAP)

        spice_fields = {f.name for f in dataclasses.fields(SpiceParams)}
        # l_sec_h is the one exception: the profile stores an explicit null where the netlist
        # builder still wants a 0.0 sentinel, so there is no value to compare directly.
        # from_profile() performs that translation at the boundary.
        assert spice_fields - {"l_sec_h"} == set(self.SPICE_MAP)

    def test_the_maps_name_only_real_profile_fields(self) -> None:
        known = set(profile.FIELDS_BY_NAME)
        assert set(self.DESIGN_MAP.values()) <= known
        assert set(self.SPICE_MAP.values()) <= known

    def test_the_default_helpers_agree_with_an_explicit_load(self) -> None:
        assert SpiceParams.from_profile(self._profile()) == reference_spice_params()
        assert DesignParameters.from_profile(self._profile()) == reference_design()


def test_physics_core_does_not_import_the_reference_values() -> None:
    """``physics.py`` must not read from ``mk0_reference``.

    If it did, these tests would be comparing the implementation against a number the
    implementation itself supplied, and would assert nothing whatsoever. A docstring warning is
    not a mechanism, so this is the mechanism.

    Scope: the guard covers ``physics.py``, the module the pins judge. Another module consuming
    the reference values for a report or a figure caption is legitimate and is not restricted
    here.
    """
    source = (REPO_ROOT / "src" / "ehdpsu" / "physics.py").read_text(encoding="utf-8")
    offending = [
        line.strip()
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "mk0_reference" in line
    ]
    assert not offending, (
        f"physics.py imports the pinned reference values: {offending}. The regression pins would "
        f"then be checking the code against itself."
    )
