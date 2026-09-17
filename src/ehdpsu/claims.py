"""Externally asserted figures, recorded verbatim so they can be adjudicated.

Every entry here is something a **source claimed**, not something this project derived. All of them
carry ``basis = claimed`` and a reference to where the assertion came from, and none may be used as
an input to a calculation. They exist to be checked.

Why a claim register is tracked code rather than a note
------------------------------------------------------
The project's stated purpose is reality alignment: its inputs include figures from an AI collaborator
known to be optimistic and from maker-community builds whose instrumentation is unstated, and the
central failure mode is an inherited claim acquiring confidence it never earned.

A claim written in prose can be quietly forgotten, restated with different numbers, or dropped from a
summary. A claim in code with a test against it cannot. So the adjudication is **reproducible in a
clone**, which nothing under ``artifacts/`` is.

Ranges are encoded as a midpoint with a multiplicative band
-----------------------------------------------------------
"28-38 grams-force" becomes a value of 33 gf with a band of ``x0.848 to x1.152``. That is a faithful
encoding rather than a reinterpretation: :attr:`Quantity.interval` returns the original endpoints
back. Picking one end instead would be choosing the number that suited the argument.

Everything is stored in SI
--------------------------
``gf`` is not a unit in :mod:`ehdpsu.quantity` — see that module on why scaled units are excluded —
so the conversion happens here, once, using ``physics.G_EARTH``. There is no second copy of 9.81.
"""

from __future__ import annotations

from dataclasses import dataclass

from .basis import Basis
from .physics import G_EARTH
from .quantity import Band, Quantity


def grams_force_to_newtons(gf: float) -> float:
    """Convert grams-force to newtons using the project's single gravity constant."""
    return gf * 1e-3 * G_EARTH


def _range_quantity(
    lo: float,
    hi: float,
    unit: str,
    refs: tuple[str, ...],
    note: str,
) -> Quantity:
    """Encode an asserted range as a midpoint carrying a band that reproduces the endpoints."""
    midpoint = (lo + hi) / 2.0
    return Quantity(
        value=midpoint,
        unit=unit,
        band=Band(lo / midpoint, hi / midpoint),
        basis=Basis.CLAIMED,
        refs=refs,
        note=note,
    )


@dataclass(frozen=True)
class ClaimSet:
    """A group of figures asserted together by one source about one design.

    Grouped because the useful check is **internal consistency**: whether the source's own numbers
    imply each other. That is a stronger statement than "our model disagrees with them", because it
    needs no agreement about whose model is right.
    """

    claim_id: str
    source: str
    description: str
    figures: dict[str, Quantity]

    def __getitem__(self, name: str) -> Quantity:
        if name not in self.figures:
            raise KeyError(
                f"{self.claim_id} asserts no figure {name!r}; it asserts {sorted(self.figures)}"
            )
        return self.figures[name]


#: Reference for the MK1 figures. Deliberately does not name the model or vendor: the repository is
#: intended to become public and a third party's model identity is framing material rather than
#: provenance. What bears on trust is that the source is known to be optimistic.
MK1_SOURCE = "External AI design collaborator, session of 2026-08-29 (known to be optimistic)"

#: The palm-scale MK1 claim, as asserted. Every figure here is the source's, including the geometry
#: and the mobility, which is what makes an internal-consistency check possible.
MK1_PALM_SCALE = ClaimSet(
    claim_id="mk1-palm-scale-2026-08-29",
    source=MK1_SOURCE,
    description="Palm-scale single-cell demonstrator: 2.5 mm gap, ~5 kV, 2-stage CW multiplier",
    figures={
        "thrust": _range_quantity(
            grams_force_to_newtons(28.0),
            grams_force_to_newtons(38.0),
            "N",
            (MK1_SOURCE,),
            "Asserted as 28-38 grams-force. The headline figure of the demonstration plan.",
        ),
        "power": _range_quantity(
            10.5,
            14.5,
            "W",
            (MK1_SOURCE,),
            "Asserted as 10.5-14.5 W input power at the claimed thrust.",
        ),
        "d_gap": _range_quantity(
            2.5e-3,
            2.5e-3,
            "m",
            (MK1_SOURCE,),
            "Emitter-to-collector gap, asserted as 2.5 mm. A single value, not a range.",
        ),
        "V_op": _range_quantity(
            4.8e3,
            5.2e3,
            "V",
            (MK1_SOURCE,),
            "Operating voltage, asserted as 4.8-5.2 kV.",
        ),
        "mu_ion": _range_quantity(
            1.5e-4,
            1.5e-4,
            "m^2/(V*s)",
            ("Kuffel & Zaengl p.366", MK1_SOURCE),
            (
                "Ion mobility in air. A literature value the source adopted rather than one it "
                "asserted independently; included because the consistency check needs it and the "
                "source used it."
            ),
        ),
    },
)

#: Every claim set, by id.
CLAIM_SETS: dict[str, ClaimSet] = {MK1_PALM_SCALE.claim_id: MK1_PALM_SCALE}
