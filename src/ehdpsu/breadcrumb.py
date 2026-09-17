"""BreadCrumb trust artifacts in W3C PROV vocabulary, with low-water-mark trust arithmetic.

Run as::

    python -m ehdpsu.breadcrumb

Writes the MK0 retrospective derivation graph and the laundering-path artifact into
``artifacts/04_BreadCrumbs/``.

Why W3C PROV and not a private schema
-------------------------------------
**PROV-DM / PROV-O** (W3C Recommendations, 2013) supply the derivation graph — ``prov:Entity``,
``prov:Activity``, ``prov:Agent``, ``prov:wasDerivedFrom``, ``prov:used``, ``prov:wasGeneratedBy``
— and **deliberately leave the trust arithmetic to the consumer**. That is precisely the division
of labour this project needs: PROV records *what came from what*, and
:mod:`ehdpsu.basis` decides *what that implies about trust*.

A private encoding of a thirteen-year-old W3C Recommendation would cost interoperability and buy
nothing, and this corpus is intended as empirical input to somebody else's trust-scoring standard.
Naming the ancestor is part of the rule rather than a courtesy — see ``ATTRIBUTIONS.md``.

The one extension
-----------------
PROV has no basis or uncertainty property, because it deliberately declines to. So this module adds
a minimal ``ehd:`` namespace carrying ``ehd:basis``, ``ehd:band`` and ``ehd:isUpperBound``. Nothing
else is invented: every structural relation is PROV's own.

What this module does NOT do
---------------------------
It does not compute physics, and it does not re-run anything to find out what happened. It records
what is already on disk or in version control. A recorder that can regenerate its own evidence can
regenerate it into the shape it expected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .basis import Basis, low_water_mark, may_be_called_validated

# Tier 04 of the untracked project datacenter.
DEFAULT_BREADCRUMB_DIR = Path("artifacts/04_BreadCrumbs")

PROV_CONTEXT: dict[str, Any] = {
    "prov": "http://www.w3.org/ns/prov#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    # The single local extension, for what PROV deliberately omits.
    "ehd": "https://maccre-2026.github.io/EHD-ResearchTests/ns#",
    "basis": "ehd:basis",
    "band": "ehd:band",
    "isUpperBound": "ehd:isUpperBound",
    "effectiveBasis": "ehd:effectiveBasis",
    "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
    "wasGeneratedBy": {"@id": "prov:wasGeneratedBy", "@type": "@id"},
    "wasAttributedTo": {"@id": "prov:wasAttributedTo", "@type": "@id"},
    "wasAssociatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
    "used": {"@id": "prov:used", "@type": "@id"},
    "startedAtTime": {"@id": "prov:startedAtTime", "@type": "xsd:dateTime"},
    "label": "http://www.w3.org/2000/01/rdf-schema#label",
}


class BreadcrumbError(RuntimeError):
    """Raised when a graph is malformed or an append-only rule would be broken."""


@dataclass(frozen=True)
class Agent:
    """A ``prov:Agent`` — who or what performed an activity."""

    id: str
    label: str
    #: ``prov:Person``, ``prov:SoftwareAgent``, or ``prov:Organization``.
    kind: str = "prov:SoftwareAgent"

    def to_jsonld(self) -> dict[str, Any]:
        return {"@id": self.id, "@type": ["prov:Agent", self.kind], "label": self.label}


@dataclass(frozen=True)
class Activity:
    """A ``prov:Activity`` — something that happened and produced or consumed entities."""

    id: str
    label: str
    started_at: str | None = None
    agent_id: str | None = None
    used: tuple[str, ...] = ()

    def to_jsonld(self) -> dict[str, Any]:
        node: dict[str, Any] = {
            "@id": self.id,
            "@type": "prov:Activity",
            "label": self.label,
        }
        if self.started_at:
            node["startedAtTime"] = self.started_at
        if self.agent_id:
            node["wasAssociatedWith"] = self.agent_id
        if self.used:
            node["used"] = list(self.used)
        return node


@dataclass(frozen=True)
class Entity:
    """A ``prov:Entity`` — a number, a file, a claim, or a decision.

    ``declared_basis`` is what this entity would be *on its own*. Its **effective** basis is
    computed by :meth:`Graph.effective_basis`, which takes the low-water-mark over every ancestor.
    The two differ whenever an entity inherits a worse ceiling than its own nature would suggest,
    and that gap is the single most interesting thing in the corpus.
    """

    id: str
    label: str
    declared_basis: Basis
    derived_from: tuple[str, ...] = ()
    generated_by: str | None = None
    attributed_to: str | None = None
    band: str | None = None
    is_upper_bound: bool = False
    refs: tuple[str, ...] = ()
    note: str | None = None

    def to_jsonld(self, effective: Basis) -> dict[str, Any]:
        node: dict[str, Any] = {
            "@id": self.id,
            "@type": "prov:Entity",
            "label": self.label,
            "basis": self.declared_basis.label,
            "effectiveBasis": effective.label,
        }
        if self.derived_from:
            node["wasDerivedFrom"] = list(self.derived_from)
        if self.generated_by:
            node["wasGeneratedBy"] = self.generated_by
        if self.attributed_to:
            node["wasAttributedTo"] = self.attributed_to
        if self.band:
            node["band"] = self.band
        if self.is_upper_bound:
            node["isUpperBound"] = True
        if self.refs:
            node["ehd:references"] = list(self.refs)
        if self.note:
            node["ehd:note"] = self.note
        return node


@dataclass
class Graph:
    """A PROV derivation graph with low-water-mark trust propagation."""

    title: str
    agents: dict[str, Agent] = field(default_factory=dict)
    activities: dict[str, Activity] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)

    def add(self, item: Agent | Activity | Entity) -> None:
        """Add a node, refusing to replace an existing one.

        Provenance records are append-only. Replacing a node in place would destroy the only
        evidence of what was previously recorded, and "why is this trusted" is the one question an
        audit asks.
        """
        if item.id in self.agents or item.id in self.activities or item.id in self.entities:
            raise BreadcrumbError(
                f"{item.id!r} is already in the graph. Provenance is append-only: record a new "
                f"node that supersedes it rather than replacing it."
            )
        if isinstance(item, Agent):
            self.agents[item.id] = item
        elif isinstance(item, Activity):
            self.activities[item.id] = item
        else:
            self.entities[item.id] = item

    def effective_basis(self, entity_id: str) -> Basis:
        """Return the low-water-mark basis for ``entity_id`` over its whole ancestry.

        The result is ``min`` of the entity's own declared basis and the effective basis of every
        entity it was derived from, transitively.

        Raises
        ------
        BreadcrumbError
            On an unknown id, or if the derivation graph contains a cycle. A cycle is not a
            recoverable condition: trust would be defined in terms of itself, and any value could
            be justified.
        """
        return self._effective(entity_id, ())

    def _effective(self, entity_id: str, stack: tuple[str, ...]) -> Basis:
        if entity_id in stack:
            cycle = " -> ".join([*stack, entity_id])
            raise BreadcrumbError(
                f"derivation cycle: {cycle}. Trust cannot be defined in terms of itself; a cyclic "
                f"graph would justify any value."
            )
        entity = self.entities.get(entity_id)
        if entity is None:
            raise BreadcrumbError(
                f"unknown entity {entity_id!r}. A derivation naming a node that is not in the "
                f"graph is a gap, not a root — say so explicitly rather than letting it resolve "
                f"to nothing."
            )
        if not entity.derived_from:
            return entity.declared_basis
        ancestors = [self._effective(pid, (*stack, entity_id)) for pid in entity.derived_from]
        return low_water_mark([entity.declared_basis, *ancestors])

    def laundering_gap(self, entity_id: str) -> tuple[Basis, Basis, bool]:
        """Return ``(declared, effective, would_have_been_laundered)`` for one entity.

        ``would_have_been_laundered`` is ``True`` when the declared basis would permit calling the
        entity *validated* but the inherited ceiling does not. That is the exact transition this
        project exists to prevent, and flagging it is the corpus's central output.
        """
        entity = self.entities.get(entity_id)
        if entity is None:
            raise BreadcrumbError(f"unknown entity {entity_id!r}")
        declared = entity.declared_basis
        effective = self.effective_basis(entity_id)
        laundered = may_be_called_validated(declared) and not may_be_called_validated(effective)
        return declared, effective, laundered

    def to_jsonld(self) -> dict[str, Any]:
        """Serialise the whole graph as a JSON-LD document."""
        nodes: list[dict[str, Any]] = []
        nodes.extend(a.to_jsonld() for a in self.agents.values())
        nodes.extend(a.to_jsonld() for a in self.activities.values())
        nodes.extend(e.to_jsonld(self.effective_basis(e.id)) for e in self.entities.values())
        return {
            "@context": PROV_CONTEXT,
            "ehd:title": self.title,
            "ehd:generatedAt": datetime.now(UTC).isoformat(),
            "ehd:trustArithmetic": (
                "W(result) = min over inputs, transitively over prov:wasDerivedFrom. Biba "
                "low-water-mark; PROV supplies the graph and leaves the arithmetic to the consumer."
            ),
            "@graph": nodes,
        }

    def summary_lines(self) -> list[str]:
        """Return a human-readable audit of every entity's declared versus effective basis."""
        lines: list[str] = []
        for eid in self.entities:
            declared, effective, laundered = self.laundering_gap(eid)
            mark = "  LAUNDERING RISK" if laundered else ""
            gap = "" if declared == effective else f"  (declared {declared.label}, ceiling applies)"
            lines.append(f"{effective.label:24s} {eid}{gap}{mark}")
        return lines


def write_graph(
    graph: Graph,
    stem: str,
    output_dir: Path = DEFAULT_BREADCRUMB_DIR,
) -> Path:
    """Write ``graph`` as JSON-LD, refusing to overwrite an existing artifact.

    Breadcrumbs are append-only. A correction is a **new** artifact naming what it corrects, so an
    overwrite is always a mistake — and an overwritten history cannot answer the only question an
    audit asks.

    Raises
    ------
    BreadcrumbError
        If the target already exists.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{stem}.jsonld"
    if target.exists():
        raise BreadcrumbError(
            f"{target} already exists. Breadcrumbs are append-only: write a new artifact naming "
            f"the one it supersedes rather than overwriting it."
        )
    target.write_text(json.dumps(graph.to_jsonld(), indent=2) + "\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# The MK0 retrospective
# ---------------------------------------------------------------------------


def build_mk0_graph() -> Graph:
    """Return the MK0 derivation graph, built from what is on disk and in version control.

    Every node here corresponds to something checkable: a commit in the git log, a file in the
    datacenter, or a figure recorded in ``docs/PHYSICS_NOTES.md``. Nothing is inferred.
    """
    g = Graph(title="MK0 retrospective — Concept Testing, Research, and Mental Prototyping")

    collaborator = Agent(
        "ehd:agent/collaborator",
        # The vendor and model are deliberately NOT named. This repository is intended to become
        # public, and a third party's model identity is framing material rather than provenance —
        # what the corpus needs is a stable agent id and the one fact that bears on trust.
        # (The project's own seat pins are a different matter and are tracked in .kiro/agents/.)
        "External AI design collaborator, session of 2026-08-29 — known to be optimistic",
        "prov:SoftwareAgent",
    )
    operator = Agent("ehd:agent/operator", "Chief Operator", "prov:Person")
    cloud_session = Agent(
        "ehd:agent/kiro-cloud", "Kiro cloud session (2026-09-09)", "prov:SoftwareAgent"
    )
    g.add(collaborator)
    g.add(operator)
    g.add(cloud_session)

    # --- root facts -------------------------------------------------------
    g.add(
        Entity(
            "ehd:ref/peek-1929",
            "F. W. Peek, Dielectric Phenomena in High Voltage Engineering (1929)",
            Basis.ANALYTICAL_CITED,
            refs=("Peek 1929",),
        )
    )
    g.add(
        Entity(
            "ehd:ref/kuffel-zaengl",
            "Kuffel, Zaengl & Kuffel, High Voltage Engineering: Fundamentals, 2nd ed., p.366",
            Basis.ANALYTICAL_CITED,
            refs=("Kuffel & Zaengl p.366",),
        )
    )
    g.add(
        Entity(
            "ehd:ref/bahder-fazi-2003",
            "Bahder & Fazi, Force on an Asymmetric Capacitor, ARL-TR-3005 (2003)",
            Basis.ANALYTICAL_CITED,
            refs=("ARL-TR-3005",),
        )
    )
    g.add(
        Entity(
            "ehd:claim/collaborator-thrust-28-38gf",
            "Collaborator's palm-scale thrust figure: 28-38 grams-force at 10.5-14.5 W",
            Basis.CLAIMED,
            attributed_to=collaborator.id,
            note=(
                "Asserted in the design conversation of 2026-09-14. Never derived in front of the "
                "operator and never reproduced. This is the entity the corpus exists to track."
            ),
        )
    )

    # --- the MK0 build ----------------------------------------------------
    scaffold = Activity(
        "ehd:activity/mk0-scaffold",
        "Scaffold ehdpsu package and physics core (commit 9dc4b9e)",
        "2026-09-09T00:00:00Z",
        cloud_session.id,
        used=("ehd:ref/peek-1929", "ehd:ref/kuffel-zaengl", "ehd:ref/bahder-fazi-2003"),
    )
    g.add(scaffold)

    g.add(
        Entity(
            "ehd:quantity/e-peek",
            "Peek inception surface field E_peek = 17.76 MV/m",
            Basis.ANALYTICAL_CITED,
            derived_from=("ehd:ref/peek-1929", "ehd:ref/kuffel-zaengl"),
            generated_by=scaffold.id,
            refs=("docs/PHYSICS_NOTES.md section 1",),
        )
    )
    g.add(
        Entity(
            "ehd:quantity/v-onset",
            "Corona inception voltage V_onset = 2.74 kV",
            Basis.ANALYTICAL_CITED,
            derived_from=("ehd:quantity/e-peek", "ehd:ref/kuffel-zaengl"),
            generated_by=scaffold.id,
            note=(
                "Reproduces exactly. Carries an unresolved radius-versus-diameter ambiguity in the "
                "SOURCE material: 25 um read as a radius gives 2.10 kV at d=2.5mm, as a diameter "
                "1.63 kV — a 29% split."
            ),
        )
    )

    # k_geo: the placeholder everything downstream inherits.
    g.add(
        Entity(
            "ehd:coefficient/k-geo",
            "Townsend current prefactor k_geo = 2*eps0*mu*L/d^2 (parallel-plate)",
            Basis.ANALYTICAL_PLACEHOLDER,
            derived_from=("ehd:ref/kuffel-zaengl",),
            generated_by=scaffold.id,
            band="x0.1 to x1.0 (order-of-magnitude; parallel-plate coefficient on a wire-to-plane emitter)",
            note=(
                "Geometrically inconsistent with the physical emitter and KEPT DELIBERATELY, "
                "labelled rather than replaced with something that fits. Uncalibrated: no FEMM run "
                "has been performed."
            ),
        )
    )
    g.add(
        Entity(
            "ehd:quantity/i-ion",
            "Ion current I = 1.17 mA at 22 kV",
            Basis.ANALYTICAL_CITED,
            derived_from=("ehd:coefficient/k-geo", "ehd:quantity/v-onset"),
            generated_by=scaffold.id,
            note="Declared analytical-cited; inherits the k_geo ceiling.",
        )
    )
    g.add(
        Entity(
            "ehd:quantity/thrust-raw",
            "Raw thrust T = 0.0938 N (9.56 gf), mobility-limited",
            Basis.ANALYTICAL_CITED,
            derived_from=("ehd:quantity/i-ion", "ehd:ref/bahder-fazi-2003"),
            generated_by=scaffold.id,
            is_upper_bound=True,
            note=(
                "An UPPER BOUND: assumes full ion-to-neutral momentum transfer, no neutral drag, "
                "uniform gap field. Real thrust is lower. No drag term exists in the suite yet."
            ),
        )
    )
    g.add(
        Entity(
            "ehd:quantity/efficiency",
            "Thrust efficiency 3.64 N/kW",
            Basis.ANALYTICAL_CITED,
            derived_from=("ehd:quantity/thrust-raw",),
            generated_by=scaffold.id,
            is_upper_bound=True,
        )
    )

    # --- the spec sheet, which is where a laundering would have surfaced ---
    spec_activity = Activity(
        "ehd:activity/mk0-spec-sheet",
        "Write BOM spec sheet (commit 09cfe12)",
        "2026-09-09T00:00:00Z",
        cloud_session.id,
        used=("ehd:quantity/thrust-raw", "ehd:quantity/efficiency"),
    )
    g.add(spec_activity)
    g.add(
        Entity(
            "ehd:artifact/mk0-spec-sheet",
            "docs/SPEC_SHEET.md — MK0 BOM and rating justifications",
            Basis.ANALYTICAL_CITED,
            derived_from=("ehd:quantity/thrust-raw", "ehd:quantity/efficiency"),
            generated_by=spec_activity.id,
            note=(
                "Honest as written: it states both caveats in section 6. The corpus records it "
                "anyway, because the ceiling it inherits is not visible from the headline figures."
            ),
        )
    )

    return g


def build_laundering_graph() -> Graph:
    """Return the counterfactual graph: what would have happened had nobody checked.

    This is the corpus's most valuable artifact and the reason the project claims the ladder is
    populated with real rather than synthetic tiers. It records a **path not taken**, and marks
    plainly what actually stopped it.
    """
    g = Graph(title="Laundering path — the 28-38 gf claim, and what prevented its promotion")

    collaborator = Agent(
        "ehd:agent/collaborator",
        "External AI design collaborator — known to be optimistic",
        "prov:SoftwareAgent",
    )
    planner = Agent(
        "ehd:agent/planner", "Kiro planning session (claude-opus-5)", "prov:SoftwareAgent"
    )
    g.add(collaborator)
    g.add(planner)

    g.add(
        Entity(
            "ehd:claim/thrust-28-38gf",
            "28-38 grams-force at 10.5-14.5 W for the MK1 palm-scale cell",
            Basis.CLAIMED,
            attributed_to=collaborator.id,
            note="The headline figure of the investor demonstration plan.",
        )
    )

    # The counterfactual: the claim adopted as a design target, then published.
    adopt = Activity(
        "ehd:activity/counterfactual-adoption",
        "COUNTERFACTUAL: adopt the claimed figure as the MK1 design target without deriving it",
        None,
        planner.id,
        used=("ehd:claim/thrust-28-38gf",),
    )
    g.add(adopt)
    g.add(
        Entity(
            "ehd:counterfactual/mk1-spec-sheet",
            "COUNTERFACTUAL: an MK1 spec sheet quoting 28-38 gf, described as validated",
            # Declared as if solved -- which is exactly the fabrication being modelled.
            Basis.SOLVED,
            derived_from=("ehd:claim/thrust-28-38gf",),
            generated_by=adopt.id,
            note=(
                "Declared SOLVED to model the fabrication. Its effective basis is CLAIMED, because "
                "the ceiling propagates. laundering_gap() flags this node, and that flag is the "
                "whole point of the corpus."
            ),
        )
    )

    # What actually happened instead.
    handcheck = Activity(
        "ehd:activity/planning-hand-check",
        "Hand-check during planning: F/P = d/(mu*V) = 3.33 N/kW, so ~4.8 gf at 14 W",
        "2026-09-15T00:00:00Z",
        planner.id,
        used=("ehd:claim/thrust-28-38gf",),
    )
    g.add(handcheck)
    g.add(
        Entity(
            "ehd:finding/thrust-discrepancy-lead",
            "LEAD: the claimed figure is ~6-9x above what the source's own formula yields",
            Basis.CLAIMED,
            derived_from=("ehd:claim/thrust-28-38gf",),
            generated_by=handcheck.id,
            note=(
                "Deliberately CLAIMED, not a finding. A hand-check is a lead — principle 7, "
                "verified means reproduced. It cuts both ways: arithmetic contradicting a claim is "
                "also only a lead, and this one is awaiting reproduction in plan Task 9. Recording "
                "it as anything better would be the same error in the opposite direction."
            ),
        )
    )

    return g


def main() -> None:
    """Write both graphs and print an audit of every entity's ceiling."""
    written: list[Path] = []
    for stem, builder in (
        ("2026-09-15_mk0_retrospective", build_mk0_graph),
        ("2026-09-15_laundering_path_thrust_claim", build_laundering_graph),
    ):
        graph = builder()
        print(f"\n=== {graph.title} ===")
        for line in graph.summary_lines():
            print(f"  {line}")
        target = DEFAULT_BREADCRUMB_DIR / f"{stem}.jsonld"
        if target.exists():
            print(f"  [exists, not overwritten] {target}")
            continue
        written.append(write_graph(graph, stem))

    print("\n=== written ===")
    for path in written:
        print(f"  {path}")
    if not written:
        print("  nothing written; breadcrumbs are append-only and both artifacts already exist")

    print(
        "\nTrust arithmetic: W(result) = min over inputs, transitively. Biba low-water-mark.\n"
        "PROV supplies the graph; the arithmetic is this project's, per the doctrine's division "
        "of labour."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
