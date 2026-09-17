"""The five-tier basis ladder and its low-water-mark arithmetic.

This module is deliberately small and has **no dependencies on the rest of the suite**, because
two separate layers must share it:

* :mod:`ehdpsu.breadcrumb` — the PROV trust corpus, which propagates basis over a derivation graph.
* the ``Quantity`` layer (planned) — which attaches a basis to every number the suite computes.

Defining the ladder in one place is the whole point. Two enumerations of these five tiers would be
two representations of one thing, and *principle 4, two representations of one thing will drift*,
says what happens next — with the specific consequence here that a quantity and its breadcrumb
could disagree about how trustworthy the same number is.

The ladder
----------
Ordered from least to most trustworthy. The numeric values exist **only** to make ``min()``
meaningful; they are not scores and must not be arithmetic-averaged.

===========================  =====  =========================================================
Basis                        Value  Meaning
===========================  =====  =========================================================
``CLAIMED``                      0  Asserted by a source, unverified
``ANALYTICAL_PLACEHOLDER``       1  Correct form, uncertain coefficient
``ANALYTICAL_CITED``             2  Closed form from a cited reference
``SOLVED``                       3  Solver output, with tool version and input hash recorded
``MEASURED``                     4  Instrument reading with stated uncertainty
===========================  =====  =========================================================

Why the arithmetic is a minimum and not an average
--------------------------------------------------
*Principle 1, trust is a ceiling inherited from provenance.* An output's trust is bounded **above**
by the minimum trust of its inputs, and is never a label applied by the last handler. Averaging
would let a single well-cited input raise the standing of a claimed one, which is exactly the
laundering this project exists to catch.

This is not original. It is the **Biba integrity model** with a low-water-mark policy (Biba, MITRE,
1977), which ships in FreeBSD as ``mac_lomac``; in another vocabulary it is taint propagation.
Naming the ancestor costs nothing and removes the easiest way for a reader to dismiss the work. See
``ATTRIBUTIONS.md``.

"Validated" is not a tier
-------------------------
It is a **publication-level assertion about** a quantity, which is why it does not appear in the
ladder. :func:`may_be_called_validated` is the gate, and it answers ``False`` for anything below
``SOLVED``. Modelling it as a sixth tier would have made "promote to validated" an expressible
operation, and the rule is that the transition must be *impossible by construction* rather than
prevented by vigilance.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum


class Basis(IntEnum):
    """How a number came to be known. Ordered; higher is more trustworthy."""

    CLAIMED = 0
    ANALYTICAL_PLACEHOLDER = 1
    ANALYTICAL_CITED = 2
    SOLVED = 3
    MEASURED = 4

    @property
    def label(self) -> str:
        """Return the canonical lowercase-hyphen spelling used in documents and JSON-LD."""
        return self.name.lower().replace("_", "-")

    @classmethod
    def from_label(cls, label: str) -> Basis:
        """Parse a canonical label such as ``analytical-placeholder``.

        Raises
        ------
        ValueError
            If the label is not one of the five tiers. Deliberately strict: an unrecognised basis
            must not silently become a default, because the most likely default (``CLAIMED``) would
            understate trust and the most convenient one would overstate it. Both are wrong, so
            neither is chosen.
        """
        wanted = label.strip().lower().replace("_", "-")
        for member in cls:
            if member.label == wanted:
                return member
        raise ValueError(f"unknown basis {label!r}; expected one of " f"{[m.label for m in cls]}")


def low_water_mark(bases: Iterable[Basis]) -> Basis:
    """Return the **worst** basis in ``bases`` — the ceiling on anything derived from them.

    Parameters
    ----------
    bases : Iterable[Basis]
        The bases of every input. Must be non-empty.

    Raises
    ------
    ValueError
        If ``bases`` is empty. An empty input set has no defensible answer: returning ``MEASURED``
        would invent trust from nothing, and returning ``CLAIMED`` would condemn a quantity that
        may be a legitimate root fact with its own declared basis. The caller must say which it
        has, so refusing is the only honest behaviour.
        *Principle 2, an approximately-correct identifier is worse than an absent one.*
    """
    materialised = list(bases)
    if not materialised:
        raise ValueError(
            "low_water_mark() received no bases. An output derived from nothing has no inherited "
            "ceiling; declare the root's own basis explicitly instead."
        )
    return min(materialised)


def may_be_called_validated(basis: Basis) -> bool:
    """Return whether a quantity at ``basis`` may be described as *validated* in any output.

    ``True`` only for ``SOLVED`` and ``MEASURED`` — a solver run with recorded provenance, or an
    instrument reading with stated uncertainty. Everything else is a form of "we worked it out",
    however well cited.

    ``ANALYTICAL_CITED`` deliberately returns ``False``. A closed form from a textbook is
    trustworthy *as mathematics* and says nothing about whether it describes this apparatus —
    Peek's law is correctly cited here and still carries an unresolved question about whether it
    applies to a 25 µm wire at this gap.
    """
    return basis >= Basis.SOLVED


def describe_ceiling(inputs: Iterable[Basis]) -> str:
    """Return a one-line human explanation of the ceiling a set of inputs imposes.

    Written for report and figure captions, so the reason a number is qualified travels with the
    number instead of living in a footnote nobody reads.
    """
    materialised = list(inputs)
    ceiling = low_water_mark(materialised)
    worst_count = sum(1 for b in materialised if b == ceiling)
    verdict = (
        "may be called validated"
        if may_be_called_validated(ceiling)
        else "may NOT be called validated"
    )
    return (
        f"ceiling {ceiling.label} (set by {worst_count} of {len(materialised)} inputs); {verdict}"
    )
