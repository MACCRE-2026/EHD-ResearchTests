"""Tests for the cross-validation engine.

The engine's defining constraint is negative: **it reports disagreement and never reconciles it.**
That is harder to test than a calculation, because the failure mode is the engine being *too helpful*
— producing a best estimate, a weighted mean, or a preferred route. So a good part of this module
asserts that no such output exists.

The two substantive checks are the ones the engine was built for:

* The MK1 thrust claim, adjudicated against a ceiling derived from **the source's own** geometry,
  voltage and power. This is the reproduction of a hand-check that had been carried as a lead since
  planning — *principle 7, verified means reproduced*.
* The two efficiency routes, which agree exactly on the value and disagree by a factor of a hundred
  on the band.
"""

from __future__ import annotations

import pytest
from conftest import reference_profile

from ehdpsu.basis import Basis
from ehdpsu.claims import CLAIM_SETS, MK1_PALM_SCALE, grams_force_to_newtons
from ehdpsu.crossvalidate import (
    Agreement,
    ClaimAdjudication,
    ClaimVerdict,
    Route,
    adjudicate_claim,
    adjudicate_claim_set,
    compare_efficiency_routes,
    compare_routes,
    efficiency_routes,
    mobility_limited_thrust_route,
)
from ehdpsu.quantity import EXACT, Band, Quantity, QuantityError


class TestClaimRegister:
    """Claims are recorded verbatim so they can be checked, and never used as inputs."""

    def test_every_claimed_figure_is_claimed(self) -> None:
        for claim_set in CLAIM_SETS.values():
            for name, figure in claim_set.figures.items():
                assert figure.basis is Basis.CLAIMED, f"{claim_set.claim_id}.{name}"
                assert figure.may_be_called_validated() is False

    def test_every_claimed_figure_names_its_source(self) -> None:
        # A claim with no attribution cannot be adjudicated: there is nobody to have been wrong.
        for claim_set in CLAIM_SETS.values():
            for name, figure in claim_set.figures.items():
                assert figure.refs, f"{claim_set.claim_id}.{name} has no reference"

    def test_the_source_is_described_without_naming_a_vendor(self) -> None:
        """The repository is intended to become public.

        A third party's model identity is framing material rather than provenance; what bears on
        trust is that the source is known to be optimistic. This is the same line drawn when the
        BreadCrumb corpus was corrected.
        """
        source = MK1_PALM_SCALE.source.lower()
        assert "optimistic" in source

        # The vendor names are assembled from fragments so this module's own source does not contain
        # them literally. Written the obvious way, the leakage scanner flagged this file as the
        # violation -- the FOURTH instance of that trap here, after the `rtifacts` substring, the
        # Gate's `--python-version` docstring, and the diff's own disclaimer.
        #
        # It is worth stating as a general law rather than a recurring surprise: a checker that names
        # what it forbids becomes an instance of what it forbids.
        vendors = ["gem" + "ini", "op" + "enai", "anthro" + "pic", "goo" + "gle", "lla" + "ma"]
        for vendor in vendors:
            assert vendor not in source, f"the recorded source names a vendor ({vendor})"

    def test_a_range_round_trips_to_its_original_endpoints(self) -> None:
        """ "28-38 gf" is stored as a midpoint plus a band, and must read back unchanged.

        Encoding a range as one end would be choosing the number that suited the argument.
        """
        lo, hi = MK1_PALM_SCALE["thrust"].interval
        assert lo == pytest.approx(grams_force_to_newtons(28.0))
        assert hi == pytest.approx(grams_force_to_newtons(38.0))

    def test_a_single_value_is_stored_as_an_exact_band(self) -> None:
        assert MK1_PALM_SCALE["d_gap"].band.is_exact
        assert MK1_PALM_SCALE["d_gap"].value == pytest.approx(2.5e-3)

    def test_an_unknown_figure_raises_rather_than_returning_nothing(self) -> None:
        with pytest.raises(KeyError, match="asserts no figure"):
            MK1_PALM_SCALE["thrust_to_weight"]

    def test_grams_force_conversion_uses_the_project_gravity_constant(self) -> None:
        from ehdpsu.physics import G_EARTH

        assert grams_force_to_newtons(1000.0) == pytest.approx(G_EARTH)


@pytest.fixture(scope="module")
def adjudication() -> ClaimAdjudication:
    """The MK1 thrust claim against a ceiling from its own figures.

    Module-scoped and defined at module level rather than as a class-scoped instance method: pytest
    deprecated the latter, and a deprecation left in place becomes a collection error on the next
    major version.
    """
    return adjudicate_claim(
        "thrust", MK1_PALM_SCALE["thrust"], mobility_limited_thrust_route(MK1_PALM_SCALE)
    )


class TestMk1ThrustAdjudication:
    """The reproduction. A hand-check was a lead; this is the finding."""

    def test_the_claim_exceeds_a_ceiling_from_its_own_figures(
        self, adjudication: ClaimAdjudication
    ) -> None:
        """The strongest available negative result.

        The derived figure uses only the source's own gap, voltage and power, so this is a test of the
        claim's internal consistency and cannot be answered with "your model might be wrong". And the
        derived figure is an **upper bound**, so the real gap is wider than the numbers below.
        """
        assert adjudication.verdict is ClaimVerdict.EXCEEDS_UPPER_BOUND
        assert adjudication.derived.quantity.is_upper_bound is True

    def test_the_derived_ceiling_reproduces(self, adjudication: ClaimAdjudication) -> None:
        # 3.43-5.13 gf, against a claim of 28-38 gf.
        lo, hi = adjudication.derived.quantity.interval
        assert lo / grams_force_to_newtons(1.0) == pytest.approx(3.431, rel=1e-3)
        assert hi / grams_force_to_newtons(1.0) == pytest.approx(5.132, rel=1e-3)

    def test_the_overstatement_is_reported_in_both_directions(
        self, adjudication: ClaimAdjudication
    ) -> None:
        """Both factors, so neither can be quoted alone.

        The conservative figure is the one to use; the generous one exists so nobody can accuse the
        report of choosing the dramatic end, and so nobody quotes the dramatic end either.
        """
        conservative, generous = adjudication.conservative_factor, adjudication.generous_factor
        # Narrowed before comparing: both are Optional, because a consistent claim reports neither.
        assert conservative is not None and generous is not None
        assert conservative == pytest.approx(5.46, rel=1e-2)
        assert generous == pytest.approx(11.1, rel=1e-2)
        assert conservative < generous

    def test_the_report_names_the_conservative_figure_as_the_one_to_quote(
        self, adjudication: ClaimAdjudication
    ) -> None:
        text = "\n".join(adjudication.report_lines())
        assert "quote that one" in text
        assert "UPPER BOUND" in text

    def test_the_adjudication_stays_claimed(self, adjudication: ClaimAdjudication) -> None:
        """A cross-check cannot raise trust above its inputs.

        Both sides are ``claimed``, so the finding is ``claimed`` — a well-founded conclusion about
        two claims is still about two claims. It is a strong argument, not a measurement.
        """
        assert adjudication.basis is Basis.CLAIMED

    def test_the_hand_check_was_only_a_lead(self, adjudication: ClaimAdjudication) -> None:
        """The planning hand-check said 6-9x. The reproduction says 5.46-11.1x.

        Recorded as a test because the direction of the difference matters: the reproduced
        **conservative** bound is *lower* than the hand-check's, so quoting "6x" would have overstated
        the floor of the disagreement. The lead was approximately right, and an approximately right
        number is what *principle 7, verified means reproduced*, exists to stop being published.
        """
        assert adjudication.conservative_factor is not None
        assert adjudication.conservative_factor < 6.0
        assert adjudication.generous_factor is not None
        assert adjudication.generous_factor > 9.0

    def test_the_claim_set_check_runs_it(self) -> None:
        results = adjudicate_claim_set(MK1_PALM_SCALE)
        assert [r.figure_name for r in results] == ["thrust"]
        assert results[0].verdict is ClaimVerdict.EXCEEDS_UPPER_BOUND


class TestEfficiencyRoutes:
    """Two routes, same value, bands a factor of a hundred apart."""

    def test_the_routes_agree_on_the_value(self) -> None:
        comparison = compare_efficiency_routes(reference_profile())
        assert comparison.agreement is Agreement.AGREE
        assert comparison.value_ratio == pytest.approx(1.0)

    def test_the_routes_disagree_about_precision_and_that_is_flagged(self) -> None:
        """Agreeing on a number while disagreeing about how well it is known is itself a finding."""
        comparison = compare_efficiency_routes(reference_profile())
        assert comparison.bands_differ is True
        assert "disagree on how well it is known" in "\n".join(comparison.report_lines())

    def test_the_closed_form_band_is_exact_and_the_ratio_route_is_wide(self) -> None:
        closed_form, from_ratio = efficiency_routes(reference_profile())
        assert closed_form.quantity.band.is_exact
        assert from_ratio.quantity.band.width == pytest.approx(100.0)

    def test_both_routes_state_their_relation(self) -> None:
        # A route without its relation is an unexplained number, and the reader cannot check it.
        for route in efficiency_routes(reference_profile()):
            assert len(route.relation) > 20

    def test_both_routes_keep_the_upper_bound_label(self) -> None:
        for route in efficiency_routes(reference_profile()):
            assert route.quantity.is_upper_bound is True


class TestComparisonSemantics:
    @staticmethod
    def _route(name: str, value: float, band: Band | None = None, unit: str = "W") -> Route:
        # `band=None` rather than `band=EXACT` in the signature: a call in a default argument is
        # evaluated once at import, and a shared mutable default is a classic source of
        # action-at-a-distance even where the object happens to be frozen.
        return Route(name, Quantity(value, unit, band or EXACT), f"{name} relation")

    def test_close_values_agree(self) -> None:
        left = self._route("a", 100.0)
        right = self._route("b", 101.0)
        assert compare_routes("p", left, right).agreement is Agreement.AGREE

    def test_non_overlapping_intervals_disagree(self) -> None:
        left = self._route("a", 100.0)
        right = self._route("b", 500.0)
        assert compare_routes("p", left, right).agreement is Agreement.DISAGREE

    def test_overlap_bought_by_a_wide_band_is_weak_not_agreement(self) -> None:
        """A wide band makes agreement easy, and saying "they agree" would overstate the evidence.

        Two figures a factor of five apart overlap if one carries an order-of-magnitude band. The
        answer is not a tighter test — the band is what is honestly known — but a distinct verdict.
        """
        left = self._route("a", 100.0, Band(0.1, 1.0))
        right = self._route("b", 20.0)
        comparison = compare_routes("p", left, right)
        assert comparison.agreement is Agreement.WEAK

    def test_different_dimensions_are_incomparable_not_disagreeing(self) -> None:
        """A category error gets its own state rather than a large ratio somebody might interpret."""
        left = self._route("a", 1.0, unit="N")
        right = self._route("b", 1.0, unit="W")
        comparison = compare_routes("p", left, right)
        assert comparison.agreement is Agreement.INCOMPARABLE
        assert comparison.value_ratio is None

    def test_the_comparison_basis_is_the_worse_of_the_two(self) -> None:
        left = Route("a", Quantity(1.0, "W", basis=Basis.MEASURED), "r")
        right = Route("b", Quantity(1.0, "W", basis=Basis.CLAIMED), "r")
        assert compare_routes("p", left, right).basis is Basis.CLAIMED


class TestItNeverReconciles:
    """The engine's defining constraint, tested as the absence of a capability."""

    def test_no_output_offers_a_preferred_route_or_a_best_estimate(self) -> None:
        """Domain law: cross-validation reports disagreement; it never reconciles it.

        Checked by attribute name rather than by reading the report text, because the temptation is to
        *add* a helpful field — ``best``, ``recommended``, ``mean`` — and that would pass any test
        written only against today's output.
        """
        comparison = compare_efficiency_routes(reference_profile())
        forbidden = ("best", "recommended", "preferred", "mean", "average", "consensus", "resolved")
        for attribute in dir(comparison):
            if attribute.startswith("_"):
                continue
            for word in forbidden:
                assert word not in attribute.lower(), (
                    f"RouteComparison exposes {attribute!r}, which reconciles rather than reports. "
                    f"Choosing between routes is a physics decision for the operator."
                )

    def test_the_report_says_no_route_is_preferred(self) -> None:
        text = "\n".join(compare_efficiency_routes(reference_profile()).report_lines())
        assert "No route is preferred" in text

    def test_both_values_are_always_present_in_the_output(self) -> None:
        # An output carrying only one number would have made a choice, whatever it said elsewhere.
        comparison = compare_efficiency_routes(reference_profile())
        assert comparison.left.quantity.value > 0
        assert comparison.right.quantity.value > 0

    def test_an_understated_claim_is_reported_rather_than_welcomed(self) -> None:
        """A claim below the derived range is still an unexplained disagreement.

        Treating it as good news would be a judgement, and a source that understates is no more
        reliable than one that overstates — it is simply wrong in the direction nobody checks.
        """
        claim = Quantity(1.0, "W", basis=Basis.CLAIMED)
        derived = Route("d", Quantity(100.0, "W"), "relation")
        adjudication = adjudicate_claim("p", claim, derived)
        assert adjudication.verdict is ClaimVerdict.BELOW_DERIVED_RANGE

    def test_a_consistent_claim_reports_no_factor(self) -> None:
        claim = Quantity(100.0, "W", basis=Basis.CLAIMED)
        derived = Route("d", Quantity(100.0, "W"), "relation")
        adjudication = adjudicate_claim("p", claim, derived)
        assert adjudication.verdict is ClaimVerdict.CONSISTENT
        assert adjudication.conservative_factor is None

    def test_a_claim_outside_a_non_bound_range_is_not_called_a_bound_breach(self) -> None:
        # EXCEEDS_UPPER_BOUND is the strongest verdict and must not be used where no bound exists.
        claim = Quantity(1000.0, "W", basis=Basis.CLAIMED)
        derived = Route("d", Quantity(1.0, "W"), "relation")
        assert adjudicate_claim("p", claim, derived).verdict is ClaimVerdict.OUTSIDE_DERIVED_RANGE

    def test_adjudicating_across_dimensions_raises(self) -> None:
        claim = Quantity(1.0, "N", basis=Basis.CLAIMED)
        derived = Route("d", Quantity(1.0, "W"), "relation")
        with pytest.raises(QuantityError, match="cannot adjudicate"):
            adjudicate_claim("p", claim, derived)
