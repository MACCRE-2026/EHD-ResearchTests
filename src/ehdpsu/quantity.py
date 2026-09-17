"""The Quantity layer: a number that carries what is known about it.

A number crossing a module boundary carries ``value``, ``unit``, ``band``, ``basis``, ``refs`` and
``is_upper_bound``. Floats travel inside a formula; Quantities travel between them.

The four rules this type enforces by construction
-------------------------------------------------
1. **A band is never tightened.** A function returning a narrower band than it received is a bug
   even when every arithmetic step in it is right. Every operation below checks its own output
   against that, so an error in the propagation code fails here rather than surfacing as a
   confident figure. *Principle 1, trust is a ceiling inherited from provenance.*
2. **``basis`` follows provenance, not the caller's confidence.** Low-water-mark over the inputs,
   always. Anything computed from an ``analytical-placeholder`` stays ``analytical-placeholder``
   however many correct steps follow.
3. **A ``claimed`` input cannot produce a ``validated`` output.** Not prevented by review —
   inexpressible, because :func:`~ehdpsu.basis.may_be_called_validated` reads the propagated
   basis and nothing can raise it.
4. **An upper bound stays labelled.** ``is_upper_bound`` propagates through every operation, and
   an operation that would *invert* the bound is refused rather than mislabelled (see below).

Dimensional analysis lives in here, deliberately
------------------------------------------------
Decided 2026-09-15 and recorded in
``artifacts/00_Governance/2026-09-15_DECISION_verification_architecture.md``: dimensional checking
is part of this type rather than a standalone checker.

**The accepted tradeoff:** the guarantee is now coupled to the type, so a number that bypasses
``Quantity`` is unchecked. A standalone checker would cover raw floats too — but it would be a
second description of the same relations, and it could **drift from the code it checks**, which is
*principle 4, two representations of one thing will drift*, applied to the checker itself. A
coupled guarantee that cannot drift beat a broader one that can.

Units are SI only, and that is a rule rather than an omission
-------------------------------------------------------------
The registry holds no scale factors. ``gf`` and ``N/kW`` are **not** units here even though the
project publishes ``9.56 gf`` and ``3.64 N/kW``, because registering them would need a conversion
factor, and ``G_EARTH`` already lives in :mod:`ehdpsu.physics` — a second copy of ``9.81`` inside a
unit table is exactly the drift this layer exists to prevent.

Worse, a scaled unit makes a wrong sum *dimensionally valid*: ``N + gf`` would pass a dimension
check and be numerically nonsense. So non-SI presentation happens at the output boundary, where a
figure is being formatted for a human, and never inside the arithmetic.

Correlation is NOT tracked, and it has a live consequence
---------------------------------------------------------
Bands here propagate as **independent** intervals. When two inputs share an ancestor, that
over-widens the result — always in the conservative direction, never the flattering one, which is
why it is acceptable. But it is not free, and one case matters right now.

Thrust and power both descend from ``k_geo``. Computing efficiency as ``T / P`` gives a band of
``x0.1 to x10`` — width 100 — from two inputs of width 10, because this type cannot see that the
``k_geo`` factor is the *same* factor in both. Physically it **cancels exactly**:
``F/P = I·d/µ / (V·I) = d/(µV)``, which contains no ``k_geo`` at all. The honest efficiency band
from ``k_geo`` is therefore **exact**, and ``x0.1 to x10`` is a real overstatement.

The rule this must not break: **a band is never tightened.** So the answer is not to special-case
the cancellation inside the arithmetic — that would be a hidden tightening, and the next correlated
pair would not get it.

The answer is that **each published quantity is derived from its own cited relation**, not by
dividing two other derived quantities. Efficiency comes from ``d/(µV)``. Two independent routes to
the same figure then disagreeing is a finding for the cross-validation engine to *report* — plan
Task 9 — and never something this layer silently reconciles.

*Principle 7, verified means reproduced*, cuts both ways here: an over-wide band is also a number
nobody has checked.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .basis import Basis, low_water_mark, may_be_called_validated


class QuantityError(ValueError):
    """Raised on a dimensional mismatch, an undefined band, or an inexpressible bound."""


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dimension:
    """Exponents over the four SI base units this project needs.

    Temperature, amount and luminous intensity are omitted because nothing here uses them. Adding
    one later is a change to this class and to every registry entry, which is the point: the set is
    declared rather than open.
    """

    m: int = 0
    kg: int = 0
    s: int = 0
    A: int = 0

    def __mul__(self, other: Dimension) -> Dimension:
        return Dimension(self.m + other.m, self.kg + other.kg, self.s + other.s, self.A + other.A)

    def __truediv__(self, other: Dimension) -> Dimension:
        return Dimension(self.m - other.m, self.kg - other.kg, self.s - other.s, self.A - other.A)

    def power(self, n: int) -> Dimension:
        return Dimension(self.m * n, self.kg * n, self.s * n, self.A * n)

    @property
    def is_dimensionless(self) -> bool:
        return self == Dimension()

    def __str__(self) -> str:
        """Return a canonical ``kg*m^2*s^-3`` form, or ``1`` when dimensionless."""
        parts = [
            f"{name}^{exp}" if exp != 1 else name
            for name, exp in (("m", self.m), ("kg", self.kg), ("s", self.s), ("A", self.A))
            if exp != 0
        ]
        return "*".join(parts) if parts else "1"


DIMENSIONLESS = Dimension()

#: Every unit string this project uses, mapped to its dimension. **No scale factors** — see the
#: module docstring. A unit absent from here is an error rather than a guess: an unrecognised unit
#: silently treated as dimensionless would defeat the whole check.
UNITS: dict[str, Dimension] = {
    "1": DIMENSIONLESS,
    # `count` is dimensionless but kept distinct so a stage count does not read as a ratio. The
    # profile schema uses it, so the registry must know it.
    "count": DIMENSIONLESS,
    "m": Dimension(m=1),
    "kg": Dimension(kg=1),
    "s": Dimension(s=1),
    "A": Dimension(A=1),
    "Hz": Dimension(s=-1),
    "N": Dimension(m=1, kg=1, s=-2),
    "W": Dimension(m=2, kg=1, s=-3),
    "V": Dimension(m=2, kg=1, s=-3, A=-1),
    "V/m": Dimension(m=1, kg=1, s=-3, A=-1),
    "F": Dimension(m=-2, kg=-1, s=4, A=2),
    "H": Dimension(m=2, kg=1, s=-2, A=-2),
    "ohm": Dimension(m=2, kg=1, s=-3, A=-2),
    # Ion mobility, as the profile spells it.
    "m^2/(V*s)": Dimension(kg=-1, s=2, A=1),
    # Townsend current-law prefactor: A/V^2.
    "A/V^2": Dimension(m=-4, kg=-2, s=6, A=3),
    # Thrust per watt. The published figure is N/kW, which is this scaled by 1000 at the boundary.
    "N/W": Dimension(m=-1, s=1),
}

#: Reverse lookup for display, first registered name wins. Built once so a derived quantity can
#: report ``W`` rather than ``kg*m^2*s^-3`` when the dimension happens to match a known unit.
_BY_DIMENSION: dict[Dimension, str] = {}
for _name, _dim in UNITS.items():
    _BY_DIMENSION.setdefault(_dim, _name)


_BASE_NAMES = ("m", "kg", "s", "A")


def _parse_canonical(unit: str) -> Dimension | None:
    """Parse a generated canonical form such as ``m^-2*kg^-1*s^3*A^2``, else ``None``.

    Intermediate results legitimately have dimensions with no named unit — ``k_geo * V`` is amps per
    volt, which is siemens, and registering every such combination would be a losing game. So
    :meth:`Quantity._display_unit` emits a canonical string when no registered name matches, and
    this reads it back.

    The grammar is exactly what that method produces and nothing more: ``name`` or ``name^int``
    joined by ``*``. Anything else returns ``None`` and becomes an error, so a typo in a hand-written
    unit is still caught.
    """
    exponents = {name: 0 for name in _BASE_NAMES}
    for token in unit.split("*"):
        name, _, exponent = token.partition("^")
        if name not in exponents:
            return None
        if exponent == "":
            exponents[name] += 1
            continue
        try:
            exponents[name] += int(exponent)
        except ValueError:
            return None
    return Dimension(**exponents)


def dimension_of(unit: str) -> Dimension:
    """Return the dimension of ``unit``: a registered name, or a canonical generated form."""
    registered = UNITS.get(unit)
    if registered is not None:
        return registered
    parsed = _parse_canonical(unit)
    if parsed is not None:
        return parsed
    raise QuantityError(
        f"unknown unit {unit!r}. Register it in ehdpsu.quantity.UNITS with its SI dimension, or "
        f"write it in canonical base-unit form such as 'kg*m^2*s^-3'. An unrecognised unit must "
        f"not default to dimensionless: that would make every dimensional check on it pass "
        f"silently. Registered: {sorted(UNITS)}"
    )


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Band:
    """A **multiplicative** uncertainty interval: the true value lies in ``[v*lo, v*hi]``.

    Multiplicative rather than absolute because that is how this project's uncertainty is actually
    stated — ``k_geo`` is "roughly a 10× band, x0.1 to x1.0" — and because order-of-magnitude
    factors compose by multiplication, which is the common case here.

    ``Band(1.0, 1.0)`` means exact, and is the only band that claims certainty.
    """

    lo: float = 1.0
    hi: float = 1.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.lo) and math.isfinite(self.hi)):
            raise QuantityError(f"band factors must be finite, got ({self.lo}, {self.hi})")
        if self.lo <= 0 or self.hi <= 0:
            raise QuantityError(
                f"band factors must be positive, got ({self.lo}, {self.hi}). A band spanning zero "
                f"cannot be expressed multiplicatively; use an absolute interval at the boundary "
                f"and say so."
            )
        if self.lo > self.hi:
            raise QuantityError(f"band lo {self.lo} exceeds hi {self.hi}")

    @property
    def is_exact(self) -> bool:
        return self.lo == 1.0 and self.hi == 1.0

    @property
    def width(self) -> float:
        """``hi / lo`` — the span, as a factor. ``1.0`` for an exact band, ``10.0`` for a 10x band."""
        return self.hi / self.lo

    def __mul__(self, other: Band) -> Band:
        return Band(self.lo * other.lo, self.hi * other.hi)

    def __truediv__(self, other: Band) -> Band:
        return Band(self.lo / other.hi, self.hi / other.lo)

    def power(self, n: int) -> Band:
        lo, hi = self.lo**n, self.hi**n
        return Band(min(lo, hi), max(lo, hi))

    def __str__(self) -> str:
        if self.is_exact:
            return "exact"
        return f"x{self.lo:g} to x{self.hi:g}"


EXACT = Band()

#: Slack in the never-tightened postconditions, so float rounding in the propagation itself cannot
#: masquerade as a rule violation. Named rather than written inline for two reasons: a magic
#: tolerance in a comparison is unreviewable, and the drift test flagged the inline `1e-9` because it
#: is numerically identical to the profile's `C_stage_F`. That collision was a false positive, but
#: only a *named* constant can be registered as one — see `profile.DESIGN_VALUE_EXEMPTIONS`.
_RELATIVE_BAND_TOLERANCE = 1e-12
_ABSOLUTE_UNCERTAINTY_TOLERANCE = 1e-9


def widest(bands: Iterable[Band]) -> Band:
    """Return the band with the greatest :attr:`Band.width`.

    Used for the never-tightened postcondition. Comparing widths rather than endpoints, because a
    band shifted but not widened is not a tightening.
    """
    materialised = list(bands)
    if not materialised:
        raise QuantityError("widest() received no bands")
    return max(materialised, key=lambda b: b.width)


# ---------------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantity:
    """A value with its unit, uncertainty band, basis, references and bound status."""

    value: float
    unit: str
    band: Band = EXACT
    basis: Basis = Basis.CLAIMED
    refs: tuple[str, ...] = ()
    #: ``True`` when this is a ceiling rather than an estimate. ``T = I*d/mu`` assumes full
    #: ion-to-neutral momentum transfer with no drag, so real thrust is lower.
    is_upper_bound: bool = False
    #: Free text carried into reports, e.g. why a coefficient is a placeholder.
    note: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise QuantityError(f"{self.value!r} is not a finite value")
        # Validates the unit eagerly, so an unregistered unit fails where it was written rather
        # than at the first arithmetic three modules away.
        dimension_of(self.unit)

    # --- properties -------------------------------------------------------------------

    @property
    def dimension(self) -> Dimension:
        return dimension_of(self.unit)

    @property
    def interval(self) -> tuple[float, float]:
        """The absolute interval ``(value*lo, value*hi)``, ordered low to high."""
        a, b = self.value * self.band.lo, self.value * self.band.hi
        return (a, b) if a <= b else (b, a)

    def may_be_called_validated(self) -> bool:
        """Whether this quantity may be described as *validated* in any output.

        Reads the propagated basis, so a figure derived from a ``claimed`` input answers ``False``
        no matter what the caller believes about it.
        """
        return may_be_called_validated(self.basis)

    # --- arithmetic -------------------------------------------------------------------

    def _combined(
        self,
        others: tuple[Quantity, ...],
        value: float,
        unit: str,
        band: Band,
        upper: bool,
        *,
        additive: bool = False,
    ) -> Quantity:
        """Assemble a derived quantity and enforce the never-tightened postcondition.

        This is a self-check on the propagation code above it: an operation that loosens the
        uncertainty rule fails here rather than becoming a confident number downstream.

        **Why the invariant differs between the two families of operation**, discovered while
        testing this on 2026-09-15. "A band is never tightened" is stated in ``profile-seam.md`` as
        an unqualified rule, and taken literally it is wrong for addition:

        * Adding an exact ``3`` to a ``2`` carrying a x10 band gives a sum of ``5`` whose absolute
          uncertainty is still ``1.8`` — unchanged — but whose *relative* band is now
          ``x0.64 to x1.0``, a width of 1.56. The relative band genuinely narrowed, and nothing was
          laundered: the absolute uncertainty was preserved exactly. Forcing it to widen would
          **invent** uncertainty, which is its own dishonesty.
        * Dividing by an exact ``3`` shrinks the absolute uncertainty by three while leaving the
          relative band untouched. So absolute span is not a universal invariant either.

        Neither measure is scale-invariant, so each is checked where it is the meaningful one:

        * **Multiplicative** operations (``*``, ``/``, ``power``) preserve or widen the **relative**
          band. That is the family where ``k_geo``'s x10 must survive to the last figure.
        * **Additive** operations preserve or widen the **absolute** uncertainty.
        """
        inputs = (self, *others)

        if additive:

            def absolute_span(q: Quantity) -> float:
                lo, hi = q.interval
                return abs(hi - lo)

            required_abs = max(absolute_span(q) for q in inputs)
            lo, hi = (value * band.lo, value * band.hi)
            produced_abs = abs(hi - lo)
            if produced_abs < required_abs * (1 - _ABSOLUTE_UNCERTAINTY_TOLERANCE):
                raise QuantityError(
                    f"an additive operation reduced the ABSOLUTE uncertainty from "
                    f"{required_abs:g} to {produced_abs:g}. Addition may narrow a relative band, "
                    f"but it may never shrink the absolute uncertainty; this is a defect in "
                    f"ehdpsu.quantity, not in the caller."
                )
        else:
            required = widest(q.band for q in inputs)
            if band.width < required.width * (1 - _RELATIVE_BAND_TOLERANCE):
                raise QuantityError(
                    f"a multiplicative operation produced a band of width {band.width:g} from "
                    f"inputs whose worst is {required.width:g}. A derived relative band is never "
                    f"tighter than its worst input; this is a defect in ehdpsu.quantity, not in "
                    f"the caller."
                )

        return Quantity(
            value=value,
            unit=unit,
            band=band,
            basis=low_water_mark([q.basis for q in inputs]),
            refs=tuple(dict.fromkeys(r for q in inputs for r in q.refs)),
            is_upper_bound=upper,
        )

    def _display_unit(self, dimension: Dimension) -> str:
        return _BY_DIMENSION.get(dimension, str(dimension))

    def __mul__(self, other: Quantity | float) -> Quantity:
        if isinstance(other, (int, float)):
            # A bare number is dimensionless and exact: scaling by 2 adds no uncertainty.
            return replace(self, value=self.value * float(other))
        dim = self.dimension * other.dimension
        return self._combined(
            (other,),
            self.value * other.value,
            self._display_unit(dim),
            self.band * other.band,
            self.is_upper_bound or other.is_upper_bound,
        )

    __rmul__ = __mul__

    def __truediv__(self, other: Quantity | float) -> Quantity:
        if isinstance(other, (int, float)):
            return replace(self, value=self.value / float(other))
        if other.is_upper_bound:
            raise QuantityError(
                "dividing by an upper bound would produce a LOWER bound, which this type cannot "
                "express. Labelling it `is_upper_bound` would be wrong in the dangerous "
                "direction, and dropping the label would lose it entirely. Restate the "
                "calculation, or add explicit lower-bound support and say why it is needed."
            )
        dim = self.dimension / other.dimension
        return self._combined(
            (other,),
            self.value / other.value,
            self._display_unit(dim),
            self.band / other.band,
            self.is_upper_bound,
        )

    def __add__(self, other: Quantity) -> Quantity:
        self._require_same_dimension(other, "add")
        total = self.value + other.value
        if total == 0.0:
            raise QuantityError(
                "the sum is exactly zero, so a multiplicative band is undefined. Use the absolute "
                "intervals at the boundary instead of expressing this as a Quantity."
            )
        lo_abs = self.value * self.band.lo + other.value * other.band.lo
        hi_abs = self.value * self.band.hi + other.value * other.band.hi
        band = _band_from_absolute(total, lo_abs, hi_abs)
        return self._combined(
            (other,),
            total,
            self.unit,
            band,
            self.is_upper_bound or other.is_upper_bound,
            additive=True,
        )

    def __sub__(self, other: Quantity) -> Quantity:
        self._require_same_dimension(other, "subtract")
        if other.is_upper_bound:
            raise QuantityError(
                "subtracting an upper bound produces a LOWER bound, which this type cannot "
                "express. Restate the calculation rather than dropping the label."
            )
        difference = self.value - other.value
        if difference == 0.0:
            raise QuantityError(
                "the difference is exactly zero, so a multiplicative band is undefined."
            )
        lo_abs = self.value * self.band.lo - other.value * other.band.hi
        hi_abs = self.value * self.band.hi - other.value * other.band.lo
        band = _band_from_absolute(difference, lo_abs, hi_abs)
        return self._combined(
            (other,), difference, self.unit, band, self.is_upper_bound, additive=True
        )

    def power(self, n: int) -> Quantity:
        """Raise to an integer power. Fractional powers are not supported; none is needed."""
        dim = self.dimension.power(n)
        return self._combined(
            (), self.value**n, self._display_unit(dim), self.band.power(n), self.is_upper_bound
        )

    def _require_same_dimension(self, other: Quantity, verb: str) -> None:
        if self.dimension != other.dimension:
            raise QuantityError(
                f"cannot {verb} {self.unit!r} and {other.unit!r}: dimensions "
                f"{self.dimension} and {other.dimension} differ."
            )

    # --- presentation -----------------------------------------------------------------

    def describe(self, precision: int = 4) -> str:
        """Return the figure with every qualification attached.

        *Physics honesty rule 4:* an upper bound is labelled an upper bound **everywhere** it
        appears, not once in a footnote. So the label is part of the string, and there is no
        formatting path that omits it.
        """
        parts = [f"{self.value:.{precision}g} {self.unit}"]
        qualifiers = []
        if self.is_upper_bound:
            qualifiers.append("UPPER BOUND")
        if not self.band.is_exact:
            qualifiers.append(str(self.band))
        qualifiers.append(f"basis {self.basis.label}")
        if not self.may_be_called_validated():
            qualifiers.append("not validated")
        return f"{parts[0]} [{', '.join(qualifiers)}]"

    def column_header(self, name: str) -> str:
        """Return a CSV column header carrying the unit and the bound label.

        A ceiling published in a bare column called ``thrust_N`` becomes a prediction the moment
        somebody reads the CSV without the derivation. The label goes in the header because that
        is what travels with the data.
        """
        suffix = "_UPPER_BOUND" if self.is_upper_bound else ""
        return f"{name}_{self.unit.replace('/', '_per_').replace('^', '')}{suffix}"

    def __str__(self) -> str:
        return self.describe()


def _band_from_absolute(value: float, lo_abs: float, hi_abs: float) -> Band:
    """Convert an absolute interval back to a multiplicative band around ``value``."""
    lo_factor, hi_factor = lo_abs / value, hi_abs / value
    if lo_factor > hi_factor:
        lo_factor, hi_factor = hi_factor, lo_factor
    return Band(lo_factor, hi_factor)


def exact(value: float, unit: str, basis: Basis = Basis.CLAIMED, **kwargs: object) -> Quantity:
    """Construct a Quantity with an exact band. A convenience, not a claim of certainty.

    ``basis`` still defaults to ``claimed``, because an exact *number* says nothing about whether
    it describes the apparatus.
    """
    return Quantity(value=value, unit=unit, band=EXACT, basis=basis, **kwargs)  # type: ignore[arg-type]
