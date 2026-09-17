"""Tests for the five-tier basis ladder and its low-water-mark arithmetic.

``basis.py`` is the smallest module in the suite and the one with the most leverage: every trust
claim the project makes reduces to ``min()`` over this enumeration. Two things therefore need
mechanical checking rather than review.

**The integer values are pinned.** They exist only so ``min()`` is meaningful, which means a
reordering would silently invert every ceiling in the corpus without changing a single call site.
A test that asserts the order is the only thing standing between that edit and a published number.

**"Validated" must stay inexpressible as a tier.** The charter's contractual claim is a *five*-tier
ladder with promotion impossible by construction. If a sixth member ever appears, or if
:func:`~ehdpsu.basis.may_be_called_validated` ever answers ``True`` for ``ANALYTICAL_CITED``, the
guarantee is gone and nothing else in the codebase would notice.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from ehdpsu.basis import (
    Basis,
    describe_ceiling,
    low_water_mark,
    may_be_called_validated,
)

# The ladder as the charter publishes it, worst first. Pinned here so a reordering in the source
# fails a test rather than quietly inverting every ceiling in the BreadCrumb corpus.
LADDER_WORST_FIRST = [
    Basis.CLAIMED,
    Basis.ANALYTICAL_PLACEHOLDER,
    Basis.ANALYTICAL_CITED,
    Basis.SOLVED,
    Basis.MEASURED,
]


class TestLadderShape:
    """The ladder's membership, ordering and integer values are all contractual."""

    def test_exactly_five_tiers(self) -> None:
        # The charter names the five-tier ladder as contractual and may be built against. A sixth
        # tier is a schema change for anybody consuming the corpus, not an internal detail.
        assert list(Basis) == LADDER_WORST_FIRST

    def test_integer_values_are_pinned(self) -> None:
        # These integers are never scores and are never averaged; they exist so min() orders the
        # tiers. Pinning them means a renumbering cannot pass silently.
        assert [int(b) for b in LADDER_WORST_FIRST] == [0, 1, 2, 3, 4]

    def test_order_is_strictly_increasing(self) -> None:
        for worse, better in pairwise(LADDER_WORST_FIRST):
            assert worse < better, f"{worse.label} must rank below {better.label}"

    def test_claimed_is_the_floor_and_measured_the_ceiling(self) -> None:
        assert min(Basis) is Basis.CLAIMED
        assert max(Basis) is Basis.MEASURED

    def test_validated_is_not_a_member(self) -> None:
        # Modelling "validated" as a tier would make "promote to validated" an expressible
        # operation. It is a gate function instead, deliberately.
        assert not hasattr(Basis, "VALIDATED")
        assert "validated" not in {b.label for b in Basis}


class TestLabels:
    """Labels are the spelling that reaches JSON-LD, CSV headers and prose."""

    def test_labels_are_lowercase_hyphenated(self) -> None:
        assert Basis.ANALYTICAL_PLACEHOLDER.label == "analytical-placeholder"
        assert Basis.CLAIMED.label == "claimed"
        assert Basis.MEASURED.label == "measured"

    def test_labels_are_unique(self) -> None:
        labels = [b.label for b in Basis]
        assert len(set(labels)) == len(labels)

    @pytest.mark.parametrize("basis", LADDER_WORST_FIRST)
    def test_label_round_trips(self, basis: Basis) -> None:
        assert Basis.from_label(basis.label) is basis

    @pytest.mark.parametrize(
        "spelling",
        [
            "analytical-placeholder",
            "analytical_placeholder",
            "ANALYTICAL-PLACEHOLDER",
            "  Analytical_Placeholder  ",
        ],
    )
    def test_from_label_tolerates_case_underscores_and_whitespace(self, spelling: str) -> None:
        # Tolerant on the spellings that are unambiguously the same tier, strict on everything
        # else. Accepting "analytical_placeholder" costs nothing; guessing at "analytic" does not.
        assert Basis.from_label(spelling) is Basis.ANALYTICAL_PLACEHOLDER

    @pytest.mark.parametrize(
        "unknown",
        [
            "validated",  # the specific promotion this project exists to prevent
            "verified",
            "analytical",  # a plausible abbreviation of two different tiers
            "estimated",
            "",
        ],
    )
    def test_from_label_refuses_to_guess(self, unknown: str) -> None:
        # An unrecognised basis must not become a default. CLAIMED would understate a legitimate
        # root fact; anything higher would overstate an unknown one. Both are wrong, so the
        # function refuses. *Principle 2, an approximately-correct identifier is worse than an
        # absent one.*
        with pytest.raises(ValueError) as exc:
            Basis.from_label(unknown)
        # The message must enumerate the real tiers, so the caller learns the ladder from the
        # error rather than from guessing again.
        assert "analytical-placeholder" in str(exc.value)


class TestLowWaterMark:
    """``W(result) = min over inputs`` — *principle 1, trust is a ceiling from provenance*."""

    def test_returns_the_worst_input(self) -> None:
        assert low_water_mark([Basis.MEASURED, Basis.CLAIMED, Basis.SOLVED]) is Basis.CLAIMED

    def test_is_order_independent(self) -> None:
        forward = [Basis.ANALYTICAL_CITED, Basis.ANALYTICAL_PLACEHOLDER, Basis.MEASURED]
        assert low_water_mark(forward) is low_water_mark(list(reversed(forward)))

    def test_single_input_passes_through(self) -> None:
        assert low_water_mark([Basis.ANALYTICAL_CITED]) is Basis.ANALYTICAL_CITED

    def test_accepts_any_iterable_not_just_a_list(self) -> None:
        # Generators are the natural call shape from a comprehension over graph ancestors, and a
        # one-shot iterator must not be consumed by a length check before it is used.
        assert low_water_mark(b for b in (Basis.SOLVED, Basis.CLAIMED)) is Basis.CLAIMED

    def test_never_exceeds_any_input(self) -> None:
        inputs = [Basis.MEASURED, Basis.ANALYTICAL_PLACEHOLDER, Basis.SOLVED]
        result = low_water_mark(inputs)
        assert all(result <= each for each in inputs)

    def test_one_good_input_cannot_raise_a_bad_one(self) -> None:
        # The averaging failure, stated as a test. A single well-cited reference must not lift a
        # claimed figure, because that is the laundering mechanism itself.
        assert low_water_mark([Basis.CLAIMED, Basis.MEASURED, Basis.MEASURED]) is Basis.CLAIMED

    def test_empty_raises_rather_than_inventing_a_default(self) -> None:
        # MEASURED would invent trust from nothing; CLAIMED would condemn a legitimate root fact
        # that has its own declared basis. There is no defensible answer, so there is no answer.
        with pytest.raises(ValueError) as exc:
            low_water_mark([])
        assert "no bases" in str(exc.value)


class TestMayBeCalledValidated:
    """The publication gate. ``False`` is the safe answer and the default one."""

    @pytest.mark.parametrize("basis", [Basis.SOLVED, Basis.MEASURED])
    def test_true_only_for_solver_output_and_instrument_readings(self, basis: Basis) -> None:
        assert may_be_called_validated(basis) is True

    @pytest.mark.parametrize(
        "basis",
        [Basis.CLAIMED, Basis.ANALYTICAL_PLACEHOLDER, Basis.ANALYTICAL_CITED],
    )
    def test_false_for_everything_worked_out_on_paper(self, basis: Basis) -> None:
        assert may_be_called_validated(basis) is False

    def test_analytical_cited_is_explicitly_not_validated(self) -> None:
        # The tier most likely to be argued about, so it gets its own named test. A correctly cited
        # closed form is trustworthy as mathematics and silent about whether it describes this
        # apparatus. Peek's law is the live example.
        assert may_be_called_validated(Basis.ANALYTICAL_CITED) is False

    def test_the_gate_agrees_with_the_ladder_threshold(self) -> None:
        # If a tier is ever inserted, this catches the case where the >= SOLVED threshold no longer
        # means what the docstring says.
        allowed = {b for b in Basis if may_be_called_validated(b)}
        assert allowed == {Basis.SOLVED, Basis.MEASURED}


class TestDescribeCeiling:
    """Caption text, so the qualification travels with the number instead of in a footnote."""

    def test_names_the_ceiling_and_how_many_inputs_set_it(self) -> None:
        line = describe_ceiling([Basis.MEASURED, Basis.CLAIMED, Basis.SOLVED])
        assert "claimed" in line
        assert "1 of 3" in line

    def test_counts_every_input_at_the_ceiling(self) -> None:
        line = describe_ceiling([Basis.CLAIMED, Basis.CLAIMED, Basis.SOLVED])
        assert "2 of 3" in line

    def test_states_the_negative_verdict_explicitly(self) -> None:
        # "may NOT be called validated" has to be present as text, not implied by omission. A
        # caption that simply fails to claim validation reads as neutral.
        line = describe_ceiling([Basis.ANALYTICAL_CITED])
        assert "may NOT be called validated" in line

    def test_states_the_positive_verdict_when_earned(self) -> None:
        line = describe_ceiling([Basis.SOLVED, Basis.MEASURED])
        assert "may be called validated" in line
        assert "NOT" not in line

    def test_empty_input_propagates_the_refusal(self) -> None:
        with pytest.raises(ValueError):
            describe_ceiling([])
