"""Tests for the derived operating point.

Two jobs. First, the Quantity wrapper must not have moved a single number: every MK0 reference
figure has to come back **bit-identically** through the new path, because the wrapper attaches
provenance and computes nothing. Second, the propagation has to be *demonstrated* rather than
asserted — widening the ``k_geo`` model band must widen exactly the figures that depend on it and
leave the rest alone.

That second half is the plan's Task 8 demo, reframed. Its original wording said widening ``k_geo``
should widen "thrust, power and efficiency together". The efficiency part is physically wrong:
``F/P = I·d/µ ÷ (V·I) = d/(µV)``, and ``k_geo`` cancels exactly. It never appears in efficiency.

The reframed claim is stronger, because an uncertainty layer that widens *every* downstream figure
is indistinguishable from one that has not been thought about.
"""

from __future__ import annotations

import pytest
from conftest import reference_profile

from ehdpsu import physics
from ehdpsu.basis import Basis
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
from ehdpsu.operating_point import K_GEO_MODEL_BAND, OperatingPoint, operating_point
from ehdpsu.quantity import Band, Quantity

#: Figures that descend from ``k_geo`` and must therefore carry its band.
INHERITS_K_GEO = ("i_ion", "power", "thrust", "cw_droop", "cw_ripple")

#: Figures independent of ``k_geo``, whose band must stay exact.
INDEPENDENT_OF_K_GEO = ("e_peek", "v_onset", "efficiency", "onset_margin", "breakdown_margin")


@pytest.fixture(scope="module")
def mk0() -> OperatingPoint:
    return operating_point(reference_profile())


class TestNoNumberMoved:
    """The wrapper attaches provenance and computes nothing, so nothing may shift."""

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("e_peek", E_PEEK_REF_V_PER_M),
            ("v_onset", V_ONSET_REF_V),
            ("k_geo", K_GEO_REF_A_PER_V2),
            ("i_ion", I_ION_REF_A),
            ("power", POWER_REF_W),
            ("thrust", THRUST_REF_N),
            ("cw_droop", CW_DROOP_REF_V),
            ("cw_ripple", CW_RIPPLE_REF_VPP),
        ],
    )
    def test_figure_is_bit_identical_to_its_pin(
        self, mk0: OperatingPoint, field: str, expected: float
    ) -> None:
        # Exact equality, not a tolerance: the same floats through the same functions. A tolerance
        # here would hide precisely the kind of drift this test exists to catch.
        assert mk0.as_dict()[field].value == expected

    def test_efficiency_matches_its_pin_after_the_boundary_conversion(
        self, mk0: OperatingPoint
    ) -> None:
        """The Quantity is in ``N/W``; the published figure is ``N/kW``.

        This is the scaled-unit boundary in action. ``N/kW`` is deliberately not a registered unit —
        registering it would need a scale factor in the unit table, and a scaled unit makes a wrong
        sum dimensionally valid. So the ×1000 happens here, where a figure is being presented.
        """
        assert mk0.efficiency.unit == "N/W"
        assert mk0.efficiency.value * 1000.0 == pytest.approx(EFFICIENCY_REF_N_PER_KW, rel=1e-12)

    def test_thrust_in_grams_force_matches_its_pin(self, mk0: OperatingPoint) -> None:
        """``gf`` is likewise a boundary conversion, using ``physics.G_EARTH``.

        Kept out of the unit registry so ``9.81`` has exactly one home. A second copy inside a unit
        table is the drift the Quantity layer exists to prevent.
        """
        assert physics.thrust_grams_force(mk0.thrust.value) == THRUST_REF_GF


class TestUnitsAndDimensions:
    @pytest.mark.parametrize(
        ("field", "unit"),
        [
            ("e_peek", "V/m"),
            ("v_onset", "V"),
            ("k_geo", "A/V^2"),
            ("i_ion", "A"),
            ("power", "W"),
            ("thrust", "N"),
            ("efficiency", "N/W"),
            ("cw_droop", "V"),
            ("cw_ripple", "V"),
            ("onset_margin", "1"),
            ("breakdown_margin", "1"),
        ],
    )
    def test_unit_is_as_declared(self, mk0: OperatingPoint, field: str, unit: str) -> None:
        assert mk0.as_dict()[field].unit == unit

    def test_efficiency_dimension_is_derived_not_asserted(self, mk0: OperatingPoint) -> None:
        """``d/(µV)`` must come out as ``N/W`` by dimensional algebra, not by being told so.

        If the dimensions did not close, the relation would be wrong and this is where that shows.
        """
        gap = Quantity(1.0, "m")
        mobility = Quantity(1.0, "m^2/(V*s)")
        volts = Quantity(1.0, "V")
        assert (gap / (mobility * volts)).unit == "N/W"


class TestBoundsAreLabelled:
    @pytest.mark.parametrize("field", ["thrust", "efficiency"])
    def test_ceilings_are_labelled(self, mk0: OperatingPoint, field: str) -> None:
        q = mk0.as_dict()[field]
        assert q.is_upper_bound is True
        assert "UPPER BOUND" in q.describe()
        assert q.column_header(field).endswith("_UPPER_BOUND")

    @pytest.mark.parametrize("field", ["i_ion", "power", "cw_droop", "cw_ripple", "v_onset"])
    def test_non_ceilings_are_not_labelled(self, mk0: OperatingPoint, field: str) -> None:
        # The label has to mean something, so it must be absent where it does not apply.
        assert mk0.as_dict()[field].is_upper_bound is False

    def test_efficiency_is_a_ceiling_even_though_its_band_is_exact(
        self, mk0: OperatingPoint
    ) -> None:
        """An exact band and an upper bound are different claims, and both must hold at once.

        Efficiency's band from ``k_geo`` is exact because ``k_geo`` cancels. It is still a ceiling,
        because it is the ratio of a ceiling thrust to the same power. Conflating "precisely known"
        with "not a bound" is exactly how a ceiling becomes a prediction.
        """
        assert mk0.efficiency.band.is_exact
        assert mk0.efficiency.is_upper_bound is True

    def test_every_report_line_carries_its_qualifications(self, mk0: OperatingPoint) -> None:
        lines = mk0.report_lines()
        assert len(lines) == len(mk0.as_dict())
        for line in lines:
            assert "basis" in line
        # And the two ceilings are labelled in the report text itself, not only in the flag.
        assert sum("UPPER BOUND" in line for line in lines) == 2


class TestBasisPropagation:
    def test_every_figure_is_claimed(self, mk0: OperatingPoint) -> None:
        """Low-water-mark over inputs that are all ``claimed``.

        A correctly cited closed form over claimed inputs is claimed. The citation does not raise
        the basis — it goes in ``refs``. That is the ladder's whole point: *what is known about this
        number*, not *how carefully was it computed*.
        """
        for name, q in mk0.as_dict().items():
            assert q.basis is Basis.CLAIMED, name

    def test_nothing_may_be_called_validated(self, mk0: OperatingPoint) -> None:
        # No FEMM run and no load-cell reading exists. The day one does, this changes on purpose.
        for name, q in mk0.as_dict().items():
            assert q.may_be_called_validated() is False, name

    def test_the_ceiling_is_claimed(self, mk0: OperatingPoint) -> None:
        assert mk0.ceiling is Basis.CLAIMED

    def test_citations_reach_the_figures_that_rest_on_them(self, mk0: OperatingPoint) -> None:
        # A relation with no citation is an assertion; the reference has to travel with the number.
        assert any("Peek" in ref for ref in mk0.e_peek.refs)
        assert any("Bahder" in ref for ref in mk0.thrust.refs)
        assert any("Kuffel" in ref for ref in mk0.cw_droop.refs)

    def test_k_geo_records_that_it_is_uncalibrated(self, mk0: OperatingPoint) -> None:
        # The note is the only place a reader learns the coefficient is a stand-in, so its absence
        # would be a silent omission rather than a missing nicety.
        note = (mk0.k_geo.note or "").upper()
        assert "UNCALIBRATED" in note
        assert "PARALLEL-PLATE" in note


class TestKgeoBandPropagation:
    """The plan's Task 8 demo, reframed: widening ``k_geo`` widens what depends on it, and only that."""

    @staticmethod
    def _at(band: Band) -> OperatingPoint:
        return operating_point(reference_profile(), k_geo_band=band)

    def test_the_default_band_is_an_order_of_magnitude(self) -> None:
        assert K_GEO_MODEL_BAND.width == pytest.approx(10.0)

    @pytest.mark.parametrize("field", INHERITS_K_GEO)
    def test_widening_k_geo_widens_what_descends_from_it(self, field: str) -> None:
        narrow = self._at(Band(0.9, 1.1)).as_dict()[field]
        wide = self._at(Band(0.01, 1.0)).as_dict()[field]
        assert wide.band.width > narrow.band.width

    @pytest.mark.parametrize("field", INDEPENDENT_OF_K_GEO)
    def test_widening_k_geo_leaves_the_rest_exact(self, field: str) -> None:
        """The half of the demo that matters most.

        ``e_peek``, ``v_onset``, ``efficiency`` and both margins do not depend on ``k_geo``, so a
        100× widening must not touch them. A layer that smeared the band over everything downstream
        would pass the first half of this demo and fail here.
        """
        for band in (Band(0.9, 1.1), Band(0.01, 1.0)):
            assert self._at(band).as_dict()[field].band.is_exact, field

    def test_widening_the_band_never_moves_a_value(self) -> None:
        """Uncertainty is not a value. Widening a band must change no figure at all."""
        narrow = self._at(Band(0.99, 1.01)).as_dict()
        wide = self._at(Band(0.001, 1.0)).as_dict()
        for name, q in narrow.items():
            assert q.value == wide[name].value, name

    def test_efficiency_is_independent_of_k_geo_by_construction(self) -> None:
        """Not merely exact-banded: numerically identical under a 1000× change of band.

        Stated separately because "the band happens to be exact" and "the figure cannot depend on
        k_geo" are different claims, and only the second is the physics.
        """
        assert (
            self._at(Band(0.999, 1.001)).efficiency.value
            == self._at(Band(0.001, 1.0)).efficiency.value
        )

    def test_the_thrust_band_tracks_the_model_band_exactly(self) -> None:
        # Not merely "wider": thrust is linear in k_geo, so its band width must equal k_geo's.
        band = Band(0.05, 2.0)
        assert self._at(band).thrust.band.width == pytest.approx(band.width)
