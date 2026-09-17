"""Tests for the Quantity layer.

Four properties are load-bearing, and each is tested as a *refusal* or an *invariant* rather than a
happy path, because each exists to make a mistake impossible rather than to make a calculation
convenient:

1. A band is never tightened.
2. ``basis`` propagates by low-water-mark, never by the caller's confidence.
3. A ``claimed`` input cannot produce a quantity that may be called validated.
4. An upper bound stays labelled, and an operation that would invert it is refused.

The fifth thing tested here is a **limitation**, not a guarantee: correlation is not tracked, so
correlated inputs over-widen. It is pinned deliberately so nobody reads the over-wide efficiency
band as arithmetic gone wrong, and so a future correlation-aware version has to change a test on
purpose.
"""

from __future__ import annotations

import pytest

from ehdpsu.basis import Basis
from ehdpsu.quantity import (
    EXACT,
    UNITS,
    Band,
    Dimension,
    Quantity,
    QuantityError,
    dimension_of,
    exact,
    widest,
)

# The MK0 k_geo band: a parallel-plate coefficient standing in for a wire-to-plane emitter.
K_GEO_BAND = Band(0.1, 1.0)


class TestDimensions:
    def test_registered_units_have_the_right_dimensions(self) -> None:
        # Spot-checked against the SI definitions rather than against each other, so a transcription
        # error in the table does not validate itself.
        assert dimension_of("V") == Dimension(m=2, kg=1, s=-3, A=-1)
        assert dimension_of("N") == Dimension(m=1, kg=1, s=-2)
        assert dimension_of("W") == Dimension(m=2, kg=1, s=-3)
        assert dimension_of("F") == Dimension(m=-2, kg=-1, s=4, A=2)

    def test_volts_times_amps_is_watts(self) -> None:
        assert dimension_of("V") * dimension_of("A") == dimension_of("W")

    def test_newtons_per_watt_is_seconds_per_metre(self) -> None:
        assert dimension_of("N") / dimension_of("W") == dimension_of("N/W")
        assert dimension_of("N/W") == Dimension(m=-1, s=1)

    def test_the_current_law_prefactor_closes(self) -> None:
        """``I = k * V^2`` must come out in amps, or the prefactor's unit is wrong."""
        assert dimension_of("A/V^2") * dimension_of("V").power(2) == dimension_of("A")

    def test_mobility_closes_against_thrust(self) -> None:
        """``T = I*d/mu`` must come out in newtons."""
        result = dimension_of("A") * dimension_of("m") / dimension_of("m^2/(V*s)")
        assert result == dimension_of("N")

    def test_count_and_one_are_both_dimensionless(self) -> None:
        # The profile schema uses both. They must agree dimensionally while staying distinct in
        # display, so a stage count does not read as a ratio.
        assert dimension_of("count").is_dimensionless
        assert dimension_of("1").is_dimensionless

    def test_canonical_form_round_trips(self) -> None:
        # Derived quantities carry generated unit strings; if those did not parse back, every
        # intermediate result would be unusable.
        for unit in UNITS:
            dim = dimension_of(unit)
            assert dimension_of(str(dim)) == dim

    def test_an_unregistered_unit_is_an_error_not_dimensionless(self) -> None:
        # Defaulting to dimensionless would make every check on it pass silently, which is worse
        # than having no check.
        with pytest.raises(QuantityError, match="unknown unit"):
            dimension_of("furlongs")

    def test_a_typo_in_a_canonical_unit_is_rejected(self) -> None:
        with pytest.raises(QuantityError, match="unknown unit"):
            dimension_of("m^2*kgg^-1")

    def test_no_scaled_units_are_registered(self) -> None:
        """``gf`` and ``N/kW`` must stay out of the registry.

        Registering them needs a conversion factor, and ``G_EARTH`` already lives in
        ``physics.py`` — a second copy of 9.81 inside a unit table is the drift this layer exists to
        prevent. Worse, a scaled unit makes ``N + gf`` dimensionally valid and numerically nonsense.
        """
        for scaled in ("gf", "N/kW", "kV", "mA", "nF", "kHz"):
            assert scaled not in UNITS, (
                f"{scaled!r} is a scaled unit. Presentation belongs at the output boundary, not in "
                f"the arithmetic."
            )


class TestBands:
    def test_exact_is_the_only_certain_band(self) -> None:
        assert EXACT.is_exact
        assert EXACT.width == 1.0
        assert not Band(0.9, 1.1).is_exact

    def test_width_is_the_span_as_a_factor(self) -> None:
        assert K_GEO_BAND.width == pytest.approx(10.0)

    def test_multiplication_widens(self) -> None:
        assert (K_GEO_BAND * K_GEO_BAND).width == pytest.approx(100.0)

    def test_division_widens(self) -> None:
        assert (K_GEO_BAND / K_GEO_BAND).width == pytest.approx(100.0)

    def test_a_band_spanning_zero_is_refused(self) -> None:
        # It cannot be expressed multiplicatively, and silently clamping it would understate.
        with pytest.raises(QuantityError, match="positive"):
            Band(0.0, 1.0)
        with pytest.raises(QuantityError, match="positive"):
            Band(-0.5, 1.0)

    def test_inverted_band_is_refused(self) -> None:
        with pytest.raises(QuantityError, match="exceeds"):
            Band(2.0, 0.5)

    def test_widest_compares_span_not_endpoints(self) -> None:
        # A band shifted but not widened is not a tightening, so width is the right comparison.
        shifted = Band(2.0, 20.0)
        assert shifted.width == pytest.approx(K_GEO_BAND.width)
        assert widest([EXACT, K_GEO_BAND]) is K_GEO_BAND

    def test_widest_refuses_an_empty_input(self) -> None:
        with pytest.raises(QuantityError):
            widest([])


class TestBandIsNeverTightened:
    """The invariant, checked by the type on every operation."""

    @pytest.mark.parametrize(
        "op",
        [lambda a, b: a * b, lambda a, b: a / b],
        ids=["mul", "div"],
    )
    def test_multiplicative_ops_never_narrow_the_relative_band(self, op: object) -> None:
        """The family where ``k_geo``'s x10 must survive to the last published figure."""
        wide = Quantity(2.0, "1", K_GEO_BAND)
        tight = Quantity(3.0, "1", EXACT)
        result = op(wide, tight)  # type: ignore[operator]
        assert result.band.width >= K_GEO_BAND.width * (1 - 1e-12)

    def test_addition_may_narrow_the_relative_band_and_that_is_correct(self) -> None:
        """Adding an exact term legitimately reduces *relative* uncertainty.

        This is where the unqualified rule "a band is never tightened" turns out to be wrong, and
        the type had to learn the difference. Adding an exact ``3`` to a ``2`` carrying a x10 band
        leaves the absolute uncertainty at ``1.8`` — unchanged — while the magnitude grows to ``5``,
        so the relative band becomes ``x0.64 to x1.0``.

        Nothing is laundered: the absolute uncertainty is preserved exactly. Forcing the relative
        band to stay at x10 would **invent** uncertainty, which is its own dishonesty.
        """
        wide = Quantity(2.0, "1", K_GEO_BAND)
        exact_term = Quantity(3.0, "1", EXACT)
        total = wide + exact_term

        assert total.value == pytest.approx(5.0)
        assert total.band.width < K_GEO_BAND.width
        assert total.band.lo == pytest.approx(0.64)

        # The invariant that does hold for addition: absolute uncertainty is never reduced.
        wide_lo, wide_hi = wide.interval
        total_lo, total_hi = total.interval
        assert (total_hi - total_lo) >= (wide_hi - wide_lo) * (1 - 1e-9)

    def test_the_additive_postcondition_fires_on_lost_absolute_uncertainty(self) -> None:
        """A fabricated additive result that shrinks absolute uncertainty must be refused.

        No public operation can produce one, which is the point — and also why it would otherwise
        go untested.
        """
        wide = Quantity(2.0, "1", K_GEO_BAND)
        other = Quantity(3.0, "1", EXACT)
        with pytest.raises(QuantityError, match="ABSOLUTE uncertainty"):
            wide._combined((other,), 5.0, "1", EXACT, False, additive=True)

    def test_multiplying_by_a_bare_number_does_not_widen_or_tighten(self) -> None:
        # Scaling by 2 adds no uncertainty and removes none.
        q = Quantity(5.0, "N", K_GEO_BAND)
        assert (q * 2.0).band == q.band

    def test_an_exact_chain_stays_exact(self) -> None:
        # Not a tightening: nothing uncertain entered.
        a, b = exact(2.0, "V"), exact(3.0, "A")
        assert (a * b).band.is_exact

    def test_the_postcondition_actually_fires(self) -> None:
        """A deliberately wrong propagation must be caught by the type, not published.

        This is the self-check on the arithmetic in ``quantity.py``. Exercised through the private
        assembler with a fabricated too-narrow band, because no public operation can produce one —
        which is the point, and also why it would otherwise be untested.
        """
        wide = Quantity(1.0, "1", K_GEO_BAND)
        other = Quantity(1.0, "1", K_GEO_BAND)
        with pytest.raises(QuantityError, match="never tighter"):
            wide._combined((other,), 1.0, "1", EXACT, False)

    def test_the_two_invariants_are_not_the_same_check(self) -> None:
        """Multiplicative and additive paths must report distinct failures.

        Folding them into one message would send a reader looking for the wrong kind of bug, and the
        two cases have genuinely different causes.
        """
        wide = Quantity(2.0, "1", K_GEO_BAND)
        other = Quantity(3.0, "1", K_GEO_BAND)

        with pytest.raises(QuantityError) as multiplicative:
            wide._combined((other,), 6.0, "1", EXACT, False, additive=False)
        with pytest.raises(QuantityError) as additive:
            wide._combined((other,), 5.0, "1", EXACT, False, additive=True)

        assert "relative band" in str(multiplicative.value)
        assert "ABSOLUTE uncertainty" in str(additive.value)


class TestBasisPropagation:
    def test_basis_is_the_worst_input(self) -> None:
        measured = Quantity(1.0, "V", basis=Basis.MEASURED)
        placeholder = Quantity(2.0, "A", basis=Basis.ANALYTICAL_PLACEHOLDER)
        assert (measured * placeholder).basis is Basis.ANALYTICAL_PLACEHOLDER

    def test_a_claimed_input_cannot_produce_a_validated_output(self) -> None:
        """The transition this project exists to catch, made inexpressible.

        Every tier is tried against a ``claimed`` input, so the guarantee does not depend on which
        basis the other operand happens to carry.
        """
        claimed = Quantity(1.0, "V", basis=Basis.CLAIMED)
        for basis in Basis:
            other = Quantity(2.0, "A", basis=basis)
            product = claimed * other
            assert product.basis is Basis.CLAIMED
            assert product.may_be_called_validated() is False

    def test_a_solved_chain_may_be_called_validated(self) -> None:
        # The flag has to be able to say yes, or it is not a gate but a constant.
        a = Quantity(1.0, "V", basis=Basis.SOLVED)
        b = Quantity(2.0, "A", basis=Basis.MEASURED)
        assert (a * b).may_be_called_validated() is True

    def test_analytical_cited_is_not_validated(self) -> None:
        cited = Quantity(1.0, "V", basis=Basis.ANALYTICAL_CITED)
        assert cited.may_be_called_validated() is False

    def test_refs_are_unioned_without_duplicates(self) -> None:
        # Provenance is the union of its inputs' plus the transformation. Order is preserved so the
        # output is stable and diffable.
        a = Quantity(1.0, "V", refs=("Peek 1929", "Kuffel & Zaengl"))
        b = Quantity(2.0, "A", refs=("Kuffel & Zaengl", "ARL-TR-3005"))
        assert (a * b).refs == ("Peek 1929", "Kuffel & Zaengl", "ARL-TR-3005")


class TestUpperBoundStaysLabelled:
    def test_multiplying_an_upper_bound_keeps_the_label(self) -> None:
        ceiling = Quantity(1.0, "N", is_upper_bound=True)
        assert (ceiling * Quantity(2.0, "1")).is_upper_bound is True

    def test_numerator_upper_bound_survives_division(self) -> None:
        ceiling = Quantity(1.0, "N", is_upper_bound=True)
        assert (ceiling / Quantity(2.0, "W")).is_upper_bound is True

    def test_dividing_by_an_upper_bound_is_refused(self) -> None:
        """The result would be a LOWER bound, which this type cannot express.

        Labelling it ``is_upper_bound`` would be wrong in the dangerous direction; dropping the
        label would lose it entirely. So the operation is refused.
        *Principle 2, an approximately-correct identifier is worse than an absent one.*
        """
        ceiling = Quantity(1.0, "N", is_upper_bound=True)
        with pytest.raises(QuantityError, match="LOWER bound"):
            _ = Quantity(10.0, "W") / ceiling

    def test_subtracting_an_upper_bound_is_refused(self) -> None:
        ceiling = Quantity(1.0, "N", is_upper_bound=True)
        with pytest.raises(QuantityError, match="LOWER bound"):
            _ = Quantity(10.0, "N") - ceiling

    def test_the_label_is_in_every_rendering(self) -> None:
        """*Physics honesty rule 4:* labelled everywhere it appears, not once in a footnote."""
        ceiling = Quantity(0.09378717329045916, "N", K_GEO_BAND, is_upper_bound=True)
        assert "UPPER BOUND" in ceiling.describe()
        assert "UPPER BOUND" in str(ceiling)
        assert ceiling.column_header("thrust").endswith("_UPPER_BOUND")

    def test_a_plain_quantity_is_not_labelled(self) -> None:
        # The label has to mean something, so it must be absent when it does not apply.
        plain = Quantity(25.79, "W")
        assert "UPPER BOUND" not in plain.describe()
        assert not plain.column_header("power").endswith("_UPPER_BOUND")


class TestDimensionalRejection:
    def test_adding_different_dimensions_is_refused(self) -> None:
        with pytest.raises(QuantityError, match="cannot add"):
            _ = Quantity(1.0, "m") + Quantity(1.0, "V")

    def test_subtracting_different_dimensions_is_refused(self) -> None:
        with pytest.raises(QuantityError, match="cannot subtract"):
            _ = Quantity(1.0, "N") - Quantity(1.0, "W")

    def test_adding_the_same_dimension_under_different_names_is_allowed(self) -> None:
        # `count` and `1` are the same dimension; refusing that would be pedantry with no safety.
        total = Quantity(5.0, "count") + Quantity(1.0, "1")
        assert total.value == pytest.approx(6.0)

    def test_a_non_finite_value_is_refused(self) -> None:
        with pytest.raises(QuantityError, match="finite"):
            Quantity(float("inf"), "V")

    def test_an_unregistered_unit_fails_at_construction(self) -> None:
        # Eagerly, so it fails where it was written rather than at the first arithmetic elsewhere.
        with pytest.raises(QuantityError, match="unknown unit"):
            Quantity(1.0, "smoots")


class TestDegenerateArithmetic:
    def test_a_sum_of_exactly_zero_is_refused(self) -> None:
        # A multiplicative band around zero is undefined; returning one would be invented.
        with pytest.raises(QuantityError, match="exactly zero"):
            _ = Quantity(1.0, "V") + Quantity(-1.0, "V")

    def test_a_difference_of_exactly_zero_is_refused(self) -> None:
        with pytest.raises(QuantityError, match="exactly zero"):
            _ = Quantity(1.0, "V") - Quantity(1.0, "V")

    def test_integer_powers_widen_correctly(self) -> None:
        q = Quantity(2.0, "V", K_GEO_BAND)
        squared = q.power(2)
        assert squared.value == pytest.approx(4.0)
        assert squared.band.width == pytest.approx(100.0)
        assert squared.dimension == dimension_of("V").power(2)


class TestCorrelationIsNotTracked:
    """A pinned **limitation**, not a guarantee.

    Bands propagate as independent intervals, so correlated inputs over-widen — always
    conservatively, never flatteringly. Pinned so the over-wide efficiency band is not mistaken for
    an arithmetic error, and so a correlation-aware version has to change a test deliberately.
    """

    def test_dividing_correlated_quantities_over_widens(self) -> None:
        """``T/P`` reports x0.1-x10 where the ``k_geo`` dependence physically cancels.

        ``F/P = I·d/µ / (V·I) = d/(µV)`` contains no ``k_geo`` at all, so the honest band from
        ``k_geo`` is exact. This type cannot see that the same factor appears in both operands.

        The fix is **not** to special-case the cancellation here — that would be a hidden
        tightening, and the next correlated pair would not get it. Each published quantity is
        derived from its own cited relation instead, and two routes disagreeing is a finding for the
        cross-validation engine to report.
        """
        thrust = Quantity(0.0938, "N", K_GEO_BAND, is_upper_bound=True)
        power = Quantity(25.79, "W", K_GEO_BAND)

        naive = thrust / power
        assert naive.band.width == pytest.approx(100.0)

        # The honest route: efficiency from d/(mu*V), where k_geo never enters.
        gap = Quantity(0.012, "m")
        mobility = Quantity(1.5e-4, "m^2/(V*s)")
        voltage = Quantity(22000.0, "V")
        direct = gap / (mobility * voltage)

        assert direct.band.is_exact
        assert direct.dimension == dimension_of("N/W")
        # And the two routes agree on the value, which is what makes the band difference the story.
        assert direct.value == pytest.approx(naive.value, rel=1e-3)

    def test_the_over_widening_is_conservative(self) -> None:
        # Stated as a test because "wrong but safe" is only acceptable if the direction is pinned.
        wide = Quantity(1.0, "N", K_GEO_BAND, is_upper_bound=False)
        other = Quantity(1.0, "W", K_GEO_BAND)
        assert (wide / other).band.width > K_GEO_BAND.width
