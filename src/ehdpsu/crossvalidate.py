"""Cross-validation: independent routes to one quantity, and claimed-versus-derived adjudication.

**This engine reports disagreement. It never reconciles it.** When two routes to a quantity differ,
both numbers and the ratio are reported and nothing is chosen. Picking one is a physics decision
belonging to the operator and the relevant domain Oracle — an engine that answered it would be making
a judgement it has no basis for, and would erase the disagreement that was the finding.

So there is deliberately **no** "best estimate", no weighted mean and no preferred route. Every output
type below carries both inputs.

The two things it checks
------------------------
**Route agreement.** Two independent derivations of the same quantity should land in the same place.
Where they do not, either a relation is wrong or an assumption differs, and which is a question for a
human.

**Claim adjudication.** A figure asserted by a source, compared against one derived from *other
figures the same source asserted*. That framing matters: it is a test of the claim's **internal
consistency**, not of our model against theirs, so it cannot be answered with "your model might be
wrong". If a source's own geometry and power imply a thrust its own headline contradicts, the
contradiction is the source's.

Agreement over bands, and why wide agreement is reported as weak
----------------------------------------------------------------
Two quantities agree when their intervals overlap. That is the right test, and it has a consequence
worth naming: a wide band makes agreement **easy**. Two figures a factor of five apart will "agree"
if one carries an order-of-magnitude band.

That is not a reason to use a tighter test — the band is what is honestly known. It is a reason to
report *how* the agreement was obtained, so :class:`RouteComparison` distinguishes agreement that
survives on the values from agreement that exists only because a band is wide.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .basis import Basis, low_water_mark
from .claims import ClaimSet
from .operating_point import operating_point
from .profile import Profile
from .quantity import Quantity, QuantityError


class Agreement(Enum):
    """How two routes relate. Descriptive only — none of these is a verdict about which is right."""

    #: Intervals overlap and the central values are close.
    AGREE = "agree"
    #: Intervals overlap only because at least one band is wide; the values are far apart.
    WEAK = "weak"
    #: Intervals do not overlap at all.
    DISAGREE = "disagree"
    #: Different dimensions. Not a disagreement — a category error, and its own state.
    INCOMPARABLE = "incomparable"


class ClaimVerdict(Enum):
    """How a claimed figure sits against a derived one."""

    #: The claim lies inside the derived interval.
    CONSISTENT = "consistent"
    #: The claim exceeds a derived **upper bound**. The strongest available negative result.
    EXCEEDS_UPPER_BOUND = "exceeds-upper-bound"
    #: The claim lies outside the derived interval, which is not a bound.
    OUTSIDE_DERIVED_RANGE = "outside-derived-range"
    #: The claim is below the derived interval. Recorded, not celebrated: an understated claim is
    #: still an unexplained disagreement.
    BELOW_DERIVED_RANGE = "below-derived-range"


@dataclass(frozen=True)
class Route:
    """One named way of arriving at a quantity, with the relation it rests on."""

    name: str
    quantity: Quantity
    #: The closed form or procedure, written out so a reader can check it without reading code.
    relation: str


@dataclass(frozen=True)
class RouteComparison:
    """Two routes to one quantity, compared and not adjudicated."""

    quantity_name: str
    left: Route
    right: Route
    agreement: Agreement
    #: ``right.value / left.value``, or ``None`` when the comparison is meaningless.
    value_ratio: float | None
    #: ``True`` when the two bands differ in width by more than a factor of two. Flagged separately
    #: from value agreement because two routes can agree on a number while disagreeing entirely
    #: about how well it is known — which is itself a finding.
    bands_differ: bool

    @property
    def basis(self) -> Basis:
        """The low-water-mark basis across both routes.

        A cross-check cannot raise trust above its inputs. Two ``claimed`` routes agreeing is two
        claims agreeing, and *principle 1, trust is a ceiling inherited from provenance*, says that
        is still ``claimed``.
        """
        return low_water_mark([self.left.quantity.basis, self.right.quantity.basis])

    def report_lines(self) -> list[str]:
        lines = [
            f"{self.quantity_name}: {self.agreement.value.upper()}",
            f"  {self.left.name:22s} {self.left.quantity.describe()}",
            f"      via {self.left.relation}",
            f"  {self.right.name:22s} {self.right.quantity.describe()}",
            f"      via {self.right.relation}",
        ]
        if self.value_ratio is not None:
            lines.append(f"  ratio (right/left)     x{self.value_ratio:.6g}")
        if self.bands_differ:
            lines.append(
                "  NOTE the routes agree on the value and disagree on how well it is known."
            )
        lines.append(f"  basis (low-water-mark) {self.basis.label}")
        lines.append("  No route is preferred. Choosing between them is a physics decision.")
        return lines


@dataclass(frozen=True)
class ClaimAdjudication:
    """A claimed figure against a derived one. Reports the gap; recommends nothing."""

    figure_name: str
    claim: Quantity
    derived: Route
    verdict: ClaimVerdict
    #: How far the claim sits beyond the derived interval, as a factor, and always the **most
    #: conservative** reading: the smallest overstatement the two intervals permit. ``None`` when the
    #: claim is consistent.
    conservative_factor: float | None
    #: The largest overstatement the intervals permit. Reported alongside the conservative figure so
    #: neither can be quoted alone.
    generous_factor: float | None

    @property
    def basis(self) -> Basis:
        return low_water_mark([self.claim.basis, self.derived.quantity.basis])

    def report_lines(self) -> list[str]:
        lines = [
            f"{self.figure_name}: {self.verdict.value.upper()}",
            f"  claimed   {self.claim.describe()}",
            f"  derived   {self.derived.quantity.describe()}",
            f"      via {self.derived.relation}",
        ]
        if self.conservative_factor is not None and self.generous_factor is not None:
            lines.append(
                f"  the claim exceeds the derived figure by x{self.conservative_factor:.3g} "
                f"to x{self.generous_factor:.3g}"
            )
            lines.append(
                f"  the conservative figure is x{self.conservative_factor:.3g}; quote that one"
            )
        if self.verdict is ClaimVerdict.EXCEEDS_UPPER_BOUND:
            lines.append(
                "  The derived figure is an UPPER BOUND, so the real value is lower still and the "
                "gap is wider than stated."
            )
        lines.append(f"  basis (low-water-mark) {self.basis.label}")
        return lines


def _intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def compare_routes(
    quantity_name: str,
    left: Route,
    right: Route,
    close_ratio: float = 1.05,
    band_ratio: float = 2.0,
) -> RouteComparison:
    """Compare two routes to one quantity.

    Parameters
    ----------
    close_ratio : float
        How near the central values must be to call the agreement strong rather than weak. Applied to
        the values, **not** to the intervals, so a wide band cannot buy a strong verdict.
    band_ratio : float
        How different the band widths must be before the disagreement about *precision* is flagged.
    """
    if left.quantity.dimension != right.quantity.dimension:
        # Not a disagreement about a number: a category error, and it gets its own state rather than
        # being reported as a large ratio that somebody might try to interpret.
        return RouteComparison(
            quantity_name, left, right, Agreement.INCOMPARABLE, None, bands_differ=False
        )

    lv, rv = left.quantity.value, right.quantity.value
    ratio = rv / lv if lv != 0.0 else None

    overlap = _intervals_overlap(left.quantity.interval, right.quantity.interval)
    values_close = ratio is not None and (1.0 / close_ratio) <= ratio <= close_ratio

    # Closeness of the central values is checked FIRST, and interval overlap is not a precondition
    # for it.
    #
    # Requiring overlap was wrong, and the tests caught it: two *exact* quantities have point
    # intervals, so 100 W and 101 W could never overlap and were reported as DISAGREE despite being
    # within 1%. That would have made the engine useless for the common case of two closed forms
    # differing only by rounding -- which is most of what it is for.
    if values_close:
        agreement = Agreement.AGREE
    elif overlap:
        # The intervals touch only because a band is wide. Reported as weak rather than as agreement,
        # because "they agree" would be a stronger statement than the evidence supports.
        agreement = Agreement.WEAK
    else:
        agreement = Agreement.DISAGREE

    widths = (left.quantity.band.width, right.quantity.band.width)
    bands_differ = max(widths) > min(widths) * band_ratio

    return RouteComparison(quantity_name, left, right, agreement, ratio, bands_differ)


def adjudicate_claim(figure_name: str, claim: Quantity, derived: Route) -> ClaimAdjudication:
    """Compare a claimed figure against a derived one, reporting the gap in both directions.

    Raises
    ------
    QuantityError
        If the dimensions differ. An adjudication across dimensions is meaningless, and returning a
        number for it would invite somebody to act on it.
    """
    if claim.dimension != derived.quantity.dimension:
        raise QuantityError(
            f"cannot adjudicate {figure_name}: claim is {claim.unit!r} and the derived route is "
            f"{derived.quantity.unit!r}."
        )

    claim_lo, claim_hi = claim.interval
    derived_lo, derived_hi = derived.quantity.interval

    if _intervals_overlap((claim_lo, claim_hi), (derived_lo, derived_hi)):
        return ClaimAdjudication(figure_name, claim, derived, ClaimVerdict.CONSISTENT, None, None)

    if claim_lo > derived_hi:
        # The smallest overstatement the two intervals permit, and the largest. Both are reported so
        # the conservative one cannot be dropped and the dramatic one cannot be quoted alone.
        conservative = claim_lo / derived_hi
        generous = claim_hi / derived_lo if derived_lo != 0 else float("inf")
        verdict = (
            ClaimVerdict.EXCEEDS_UPPER_BOUND
            if derived.quantity.is_upper_bound
            else ClaimVerdict.OUTSIDE_DERIVED_RANGE
        )
        return ClaimAdjudication(figure_name, claim, derived, verdict, conservative, generous)

    # The claim sits below the derived range. Recorded rather than treated as good news: an
    # understated claim is still a disagreement nobody has explained.
    return ClaimAdjudication(
        figure_name, claim, derived, ClaimVerdict.BELOW_DERIVED_RANGE, None, None
    )


# ---------------------------------------------------------------------------
# The built-in checks
# ---------------------------------------------------------------------------


def mobility_limited_thrust_route(claims: ClaimSet) -> Route:
    """Derive a thrust ceiling from a claim set's **own** geometry, voltage and power.

    ``F/P = I·d/µ ÷ (V·I) = d/(µV)``, so ``T = P·d/(µV)``. Every input is the source's own figure,
    which is what makes this a test of internal consistency rather than of one model against another.

    The result is an **upper bound**: ``T = I·d/µ`` assumes every ion transfers all its momentum to
    neutrals, with no drag and a uniform gap field. A claim exceeding it is exceeding a ceiling, not
    merely a best estimate — the real figure is lower still.
    """
    gap = claims["d_gap"]
    mobility = claims["mu_ion"]
    voltage = claims["V_op"]
    power = claims["power"]

    thrust_per_watt = gap / (mobility * voltage)
    thrust = thrust_per_watt * power
    return Route(
        name="d/(mu*V) x claimed P",
        quantity=Quantity(
            value=thrust.value,
            unit="N",
            band=thrust.band,
            basis=thrust.basis,
            refs=thrust.refs,
            is_upper_bound=True,
            note=(
                "Mobility-limited ceiling from the claim's own gap, voltage and power. Real thrust "
                "is lower."
            ),
        ),
        relation="T = P*d/(mu*V), the mobility-limited ceiling, using the source's own figures",
    )


def efficiency_routes(prof: Profile) -> tuple[Route, Route]:
    """Return the two independent routes to thrust efficiency for a profile.

    This is the case that made the engine necessary. The routes **agree exactly on the value** and
    **disagree entirely about the band**, which is a disagreement worth surfacing rather than
    averaging away:

    * ``d/(mu*V)`` is the closed form. ``k_geo`` does not appear in it, so its band from ``k_geo`` is
      exact.
    * ``thrust / power`` reaches the same number through two figures that both descend from
      ``k_geo``. The Quantity layer treats them as independent and cannot see that the factor cancels,
      so it reports a band a hundred times wider.

    Neither route is wrong. The first is the honest band; the second is what interval arithmetic can
    know without tracking correlation. The engine reports the gap, and the reason lives here rather
    than in a special case inside the arithmetic — special-casing the cancellation would be a hidden
    tightening, and the next correlated pair would not get one.
    """
    point = operating_point(prof)

    closed_form = Route(
        name="d/(mu*V)",
        quantity=point.efficiency,
        relation="F/P = d/(mu*V); independent of k_geo, so its band does not inherit the x10",
    )
    from_ratio = Route(
        name="thrust / power",
        quantity=point.thrust / point.power,
        relation=(
            "F/P = T/P; both operands descend from k_geo, and interval arithmetic cannot see that "
            "the factor cancels"
        ),
    )
    return closed_form, from_ratio


def compare_efficiency_routes(prof: Profile) -> RouteComparison:
    """Compare the two efficiency routes for a profile."""
    closed_form, from_ratio = efficiency_routes(prof)
    return compare_routes("thrust efficiency", closed_form, from_ratio)


def adjudicate_claim_set(claims: ClaimSet) -> list[ClaimAdjudication]:
    """Run every available internal-consistency check over a claim set.

    Currently one check: the thrust ceiling implied by the source's own geometry, voltage and power.
    Returned as a list so adding a check does not change the caller.
    """
    return [
        adjudicate_claim("thrust", claims["thrust"], mobility_limited_thrust_route(claims)),
    ]
