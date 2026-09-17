"""Tests for the BreadCrumb PROV corpus and its trust propagation.

Three of these tests exist because the plan named them, and they are the three properties the
charter offers to an outside consumer of the corpus:

1. **Propagation** — a derived entity's trust never exceeds the worst of its inputs.
2. **Append-only** — neither a node nor an artifact can be replaced in place.
3. **Laundering is impossible** — a ``claimed`` input cannot produce an output that may be called
   validated, no matter what basis the node declares for itself.

The third is the one worth stating carefully. The counterfactual node in
:func:`~ehdpsu.breadcrumb.build_laundering_graph` **declares itself** ``SOLVED`` on top of a
``claimed`` parent. That is deliberate: it models the fabrication rather than assuming nobody would
attempt it. What must hold is that the declaration does not survive contact with
:meth:`~ehdpsu.breadcrumb.Graph.effective_basis`.

Also checked here: the two real graphs shipped in ``artifacts/04_BreadCrumbs/`` have no dangling
references. A derivation naming a node that is not in the graph would resolve to nothing and quietly
widen the ceiling, which is the failure mode
*principle 2, an approximately-correct identifier is worse than an absent one*, describes.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ehdpsu.basis import Basis, may_be_called_validated
from ehdpsu.breadcrumb import (
    PROV_CONTEXT,
    Activity,
    Agent,
    BreadcrumbError,
    Entity,
    Graph,
    build_laundering_graph,
    build_mk0_graph,
    write_graph,
)


def _root(entity_id: str, basis: Basis) -> Entity:
    """Return a minimal root entity, for tests that care only about basis arithmetic."""
    return Entity(entity_id, f"root {entity_id}", basis)


def _referenced_ids(graph: Graph) -> set[str]:
    """Return every id any node points at, across all four PROV relations used here."""
    pointed: set[str] = set()
    for entity in graph.entities.values():
        pointed.update(entity.derived_from)
        if entity.generated_by:
            pointed.add(entity.generated_by)
        if entity.attributed_to:
            pointed.add(entity.attributed_to)
    for activity in graph.activities.values():
        pointed.update(activity.used)
        if activity.agent_id:
            pointed.add(activity.agent_id)
    return pointed


class TestPropagation:
    """*Principle 1, trust is a ceiling inherited from provenance.*"""

    def test_a_root_keeps_its_declared_basis(self) -> None:
        g = Graph("roots")
        g.add(_root("e:measured", Basis.MEASURED))
        assert g.effective_basis("e:measured") is Basis.MEASURED

    def test_derived_entity_inherits_the_worst_parent(self) -> None:
        g = Graph("one hop")
        g.add(_root("e:good", Basis.MEASURED))
        g.add(_root("e:bad", Basis.CLAIMED))
        g.add(Entity("e:derived", "derived", Basis.MEASURED, derived_from=("e:good", "e:bad")))
        assert g.effective_basis("e:derived") is Basis.CLAIMED

    def test_ceiling_survives_a_long_chain(self) -> None:
        # The realistic shape: one placeholder coefficient far upstream, then four honest
        # analytical steps. Every one of those steps is correct, and the ceiling still holds.
        g = Graph("chain")
        g.add(_root("e:placeholder", Basis.ANALYTICAL_PLACEHOLDER))
        previous = "e:placeholder"
        for hop in range(4):
            current = f"e:step{hop}"
            g.add(Entity(current, f"step {hop}", Basis.ANALYTICAL_CITED, derived_from=(previous,)))
            previous = current
        assert g.effective_basis(previous) is Basis.ANALYTICAL_PLACEHOLDER

    def test_a_node_cannot_declare_its_way_above_its_ancestry(self) -> None:
        g = Graph("declaration")
        g.add(_root("e:claim", Basis.CLAIMED))
        g.add(Entity("e:optimistic", "optimistic", Basis.MEASURED, derived_from=("e:claim",)))
        assert g.effective_basis("e:optimistic") is Basis.CLAIMED

    def test_a_node_can_declare_itself_worse_than_its_ancestry(self) -> None:
        # The direction that must stay open: a hand-check over well-cited inputs is still only a
        # lead, and it has to be able to say so. *Principle 7, verified means reproduced.*
        g = Graph("self-limiting")
        g.add(_root("e:cited", Basis.ANALYTICAL_CITED))
        g.add(Entity("e:lead", "a lead", Basis.CLAIMED, derived_from=("e:cited",)))
        assert g.effective_basis("e:lead") is Basis.CLAIMED

    @pytest.mark.parametrize(
        "parents",
        [
            (Basis.MEASURED, Basis.SOLVED),
            (Basis.SOLVED, Basis.ANALYTICAL_CITED),
            (Basis.ANALYTICAL_CITED, Basis.ANALYTICAL_PLACEHOLDER),
            (Basis.MEASURED, Basis.MEASURED, Basis.CLAIMED),
        ],
    )
    def test_effective_never_exceeds_any_ancestor(self, parents: tuple[Basis, ...]) -> None:
        g = Graph("never exceeds")
        ids: list[str] = []
        for index, basis in enumerate(parents):
            pid = f"e:parent{index}"
            g.add(_root(pid, basis))
            ids.append(pid)
        g.add(Entity("e:child", "child", Basis.MEASURED, derived_from=tuple(ids)))
        effective = g.effective_basis("e:child")
        assert all(effective <= parent for parent in parents)


class TestAppendOnly:
    """Provenance records are never replaced. An overwritten history cannot be audited."""

    def test_add_refuses_a_duplicate_entity_id(self) -> None:
        g = Graph("dupes")
        g.add(_root("e:one", Basis.SOLVED))
        with pytest.raises(BreadcrumbError) as exc:
            g.add(_root("e:one", Basis.CLAIMED))
        assert "append-only" in str(exc.value)

    def test_add_refuses_an_id_collision_across_node_types(self) -> None:
        # The namespace is flat because PROV's is: an @id is an @id. An agent shadowing an entity id
        # would make wasDerivedFrom and wasAttributedTo resolve to different things by accident.
        g = Graph("cross-type")
        g.add(_root("x:shared", Basis.SOLVED))
        with pytest.raises(BreadcrumbError):
            g.add(Agent("x:shared", "an agent wearing an entity's id"))
        with pytest.raises(BreadcrumbError):
            g.add(Activity("x:shared", "an activity wearing an entity's id"))

    def test_write_graph_refuses_to_overwrite(self, tmp_path: Path) -> None:
        g = Graph("write once")
        g.add(_root("e:one", Basis.SOLVED))
        first = write_graph(g, "corpus", output_dir=tmp_path)
        assert first.exists()
        with pytest.raises(BreadcrumbError) as exc:
            write_graph(g, "corpus", output_dir=tmp_path)
        assert "append-only" in str(exc.value)

    def test_write_graph_leaves_the_original_bytes_untouched(self, tmp_path: Path) -> None:
        # The refusal is worthless if the file is truncated before the check.
        g = Graph("write once")
        g.add(_root("e:one", Basis.SOLVED))
        target = write_graph(g, "corpus", output_dir=tmp_path)
        before = target.read_bytes()
        with pytest.raises(BreadcrumbError):
            write_graph(Graph("a different graph"), "corpus", output_dir=tmp_path)
        assert target.read_bytes() == before

    def test_write_graph_creates_the_tier_directory(self, tmp_path: Path) -> None:
        g = Graph("nested")
        g.add(_root("e:one", Basis.MEASURED))
        target = write_graph(g, "corpus", output_dir=tmp_path / "04_BreadCrumbs")
        assert target.is_file()

    def test_entities_are_immutable(self) -> None:
        # frozen=True is what stops a node being edited after it is in the graph, which would defeat
        # the add() guard entirely.
        entity = _root("e:frozen", Basis.CLAIMED)
        with pytest.raises(FrozenInstanceError):
            entity.declared_basis = Basis.MEASURED  # type: ignore[misc]


class TestLaunderingIsImpossible:
    """A ``claimed`` input cannot yield an output that may be called validated."""

    def test_declared_solved_over_a_claim_reports_an_effective_claim(self) -> None:
        g = Graph("laundering")
        g.add(_root("e:claim", Basis.CLAIMED))
        g.add(Entity("e:published", "published", Basis.SOLVED, derived_from=("e:claim",)))
        declared, effective, laundered = g.laundering_gap("e:published")
        assert declared is Basis.SOLVED
        assert effective is Basis.CLAIMED
        assert laundered is True
        assert may_be_called_validated(effective) is False

    def test_no_declaration_over_a_claim_can_reach_validated(self) -> None:
        g = Graph("exhaustive")
        g.add(_root("e:claim", Basis.CLAIMED))
        for basis in Basis:
            eid = f"e:published-{basis.label}"
            g.add(Entity(eid, eid, basis, derived_from=("e:claim",)))
            assert may_be_called_validated(g.effective_basis(eid)) is False

    def test_an_honest_solved_root_is_not_flagged(self) -> None:
        # The flag has to be specific, or it becomes noise and gets ignored.
        g = Graph("honest")
        g.add(_root("e:solver-run", Basis.SOLVED))
        _declared, effective, laundered = g.laundering_gap("e:solver-run")
        assert laundered is False
        assert may_be_called_validated(effective) is True

    def test_a_modest_declaration_over_a_claim_is_not_flagged(self) -> None:
        # Declaring CLAIMED over a claim is correct behaviour, not a laundering attempt. The flag
        # means "would have been promoted", not "has a bad ceiling".
        g = Graph("modest")
        g.add(_root("e:claim", Basis.CLAIMED))
        g.add(Entity("e:lead", "a lead", Basis.CLAIMED, derived_from=("e:claim",)))
        _declared, _effective, laundered = g.laundering_gap("e:lead")
        assert laundered is False

    def test_summary_marks_the_risk_in_text(self) -> None:
        g = Graph("summary")
        g.add(_root("e:claim", Basis.CLAIMED))
        g.add(Entity("e:published", "published", Basis.SOLVED, derived_from=("e:claim",)))
        joined = "\n".join(g.summary_lines())
        assert "LAUNDERING RISK" in joined


class TestMalformedGraphs:
    """Refusals, not defaults. Every one of these would otherwise widen a ceiling silently."""

    def test_unknown_entity_raises(self) -> None:
        g = Graph("empty")
        with pytest.raises(BreadcrumbError) as exc:
            g.effective_basis("e:absent")
        assert "unknown entity" in str(exc.value)

    def test_dangling_derivation_raises_rather_than_resolving_to_nothing(self) -> None:
        g = Graph("dangling")
        g.add(Entity("e:child", "child", Basis.MEASURED, derived_from=("e:missing",)))
        with pytest.raises(BreadcrumbError):
            g.effective_basis("e:child")

    def test_laundering_gap_raises_on_unknown_entity(self) -> None:
        with pytest.raises(BreadcrumbError):
            Graph("empty").laundering_gap("e:absent")

    def test_self_reference_is_a_cycle(self) -> None:
        g = Graph("self")
        g.add(Entity("e:ouroboros", "self-derived", Basis.MEASURED, derived_from=("e:ouroboros",)))
        with pytest.raises(BreadcrumbError) as exc:
            g.effective_basis("e:ouroboros")
        assert "cycle" in str(exc.value)

    def test_multi_hop_cycle_is_detected_and_named(self) -> None:
        g = Graph("ring")
        g.add(Entity("e:a", "a", Basis.MEASURED, derived_from=("e:b",)))
        g.add(Entity("e:b", "b", Basis.MEASURED, derived_from=("e:c",)))
        g.add(Entity("e:c", "c", Basis.MEASURED, derived_from=("e:a",)))
        with pytest.raises(BreadcrumbError) as exc:
            g.effective_basis("e:a")
        message = str(exc.value)
        # The path is printed because a cycle in a real corpus is not obvious from either endpoint.
        assert "e:a -> e:b -> e:c -> e:a" in message

    def test_a_diamond_is_not_mistaken_for_a_cycle(self) -> None:
        # Two paths to one ancestor is the normal shape of a derivation graph, and a naive
        # visited-set guard would reject it. The cycle check tracks the stack, not visits.
        g = Graph("diamond")
        g.add(_root("e:root", Basis.ANALYTICAL_PLACEHOLDER))
        g.add(Entity("e:left", "left", Basis.MEASURED, derived_from=("e:root",)))
        g.add(Entity("e:right", "right", Basis.MEASURED, derived_from=("e:root",)))
        g.add(Entity("e:join", "join", Basis.MEASURED, derived_from=("e:left", "e:right")))
        assert g.effective_basis("e:join") is Basis.ANALYTICAL_PLACEHOLDER


class TestJsonLd:
    """The encoding is PROV-O / JSON-LD, which the charter names as contractual."""

    def test_round_trips_through_json(self) -> None:
        g = Graph("serialisable")
        g.add(_root("e:one", Basis.SOLVED))
        parsed = json.loads(json.dumps(g.to_jsonld()))
        assert parsed["@context"]["prov"] == "http://www.w3.org/ns/prov#"
        assert parsed["ehd:title"] == "serialisable"

    def test_context_declares_prov_and_the_single_local_extension(self) -> None:
        # PROV supplies every structural relation. The ehd: namespace exists only for what PROV
        # deliberately omits: basis, band and the upper-bound flag.
        assert PROV_CONTEXT["prov"] == "http://www.w3.org/ns/prov#"
        assert PROV_CONTEXT["basis"] == "ehd:basis"
        assert PROV_CONTEXT["isUpperBound"] == "ehd:isUpperBound"

    def test_every_entity_node_carries_declared_and_effective_basis(self) -> None:
        # Publishing one without the other is how a ceiling becomes invisible: the declared basis
        # alone reads as the answer.
        document = build_mk0_graph().to_jsonld()
        entity_nodes = [n for n in document["@graph"] if n.get("@type") == "prov:Entity"]
        assert entity_nodes
        for node in entity_nodes:
            assert "basis" in node, node["@id"]
            assert "effectiveBasis" in node, node["@id"]

    def test_upper_bound_entities_are_labelled_in_the_serialisation(self) -> None:
        # *Physics honesty rule 4*: an upper bound is labelled everywhere it appears, including
        # inside a machine-readable artifact somebody else will parse.
        document = build_mk0_graph().to_jsonld()
        nodes = {n["@id"]: n for n in document["@graph"]}
        assert nodes["ehd:quantity/thrust-raw"]["isUpperBound"] is True
        assert nodes["ehd:quantity/efficiency"]["isUpperBound"] is True

    def test_agents_and_activities_are_typed_as_prov(self) -> None:
        document = build_mk0_graph().to_jsonld()
        types = {n["@id"]: n["@type"] for n in document["@graph"]}
        assert "prov:Agent" in types["ehd:agent/operator"]
        assert types["ehd:activity/mk0-scaffold"] == "prov:Activity"

    def test_trust_arithmetic_is_stated_in_the_document(self) -> None:
        # The corpus is intended as input to somebody else's standard, so the arithmetic travels
        # with the data rather than living only in this repository's prose.
        document = build_mk0_graph().to_jsonld()
        assert "min over inputs" in document["ehd:trustArithmetic"]
        assert "low-water-mark" in document["ehd:trustArithmetic"]


class TestMk0Retrospective:
    """The real graph. These assertions are the corpus's substantive claims."""

    def test_k_geo_is_the_placeholder_that_sets_the_ceiling(self) -> None:
        g = build_mk0_graph()
        assert g.effective_basis("ehd:coefficient/k-geo") is Basis.ANALYTICAL_PLACEHOLDER

    def test_k_geo_carries_its_band(self) -> None:
        # An uncertain coefficient without its band is just a number. The band is what makes it a
        # documented model parameter rather than a fitted constant.
        band = build_mk0_graph().entities["ehd:coefficient/k-geo"].band
        assert band is not None and band.strip()

    @pytest.mark.parametrize(
        "entity_id",
        [
            "ehd:quantity/i-ion",
            "ehd:quantity/thrust-raw",
            "ehd:quantity/efficiency",
            "ehd:artifact/mk0-spec-sheet",
        ],
    )
    def test_everything_downstream_of_k_geo_inherits_its_ceiling(self, entity_id: str) -> None:
        # Each of these declares itself analytical-cited, and each one is correct to. The ceiling
        # is inherited anyway, which is the entire content of the MK0 retrospective.
        g = build_mk0_graph()
        assert g.entities[entity_id].declared_basis is Basis.ANALYTICAL_CITED
        assert g.effective_basis(entity_id) is Basis.ANALYTICAL_PLACEHOLDER

    def test_the_electrostatics_chain_is_not_dragged_down_by_k_geo(self) -> None:
        # Peek onset does not descend from k_geo, and must not inherit a ceiling it has no
        # connection to. A low-water-mark that pessimises everything equally would be useless.
        g = build_mk0_graph()
        assert g.effective_basis("ehd:quantity/e-peek") is Basis.ANALYTICAL_CITED
        assert g.effective_basis("ehd:quantity/v-onset") is Basis.ANALYTICAL_CITED

    def test_nothing_in_mk0_may_be_called_validated(self) -> None:
        # No FEMM run and no load-cell reading exists yet. The day one does, this test changes on
        # purpose and the change is visible in a diff.
        g = build_mk0_graph()
        for entity_id in g.entities:
            assert not may_be_called_validated(g.effective_basis(entity_id)), entity_id

    def test_the_collaborator_claim_is_recorded_as_claimed(self) -> None:
        g = build_mk0_graph()
        claim = g.entities["ehd:claim/collaborator-thrust-28-38gf"]
        assert claim.declared_basis is Basis.CLAIMED
        assert claim.attributed_to == "ehd:agent/collaborator"

    def test_no_mk0_entity_is_flagged_as_laundered(self) -> None:
        # MK0 is the honest half of the corpus. If a node here ever starts declaring itself solved,
        # the flag should be the reason somebody notices.
        g = build_mk0_graph()
        flagged = [eid for eid in g.entities if g.laundering_gap(eid)[2]]
        assert flagged == []

    def test_no_dangling_references(self) -> None:
        g = build_mk0_graph()
        known = set(g.entities) | set(g.activities) | set(g.agents)
        assert _referenced_ids(g) <= known


class TestLaunderingPathGraph:
    """The counterfactual. The artifact the charter says is worth something to another team."""

    def test_the_counterfactual_declares_itself_solved(self) -> None:
        # Stated as a test so nobody "fixes" the declaration later. It is the fabrication being
        # modelled, and softening it would remove the only laundering example in the corpus.
        g = build_laundering_graph()
        node = g.entities["ehd:counterfactual/mk1-spec-sheet"]
        assert node.declared_basis is Basis.SOLVED
        assert node.derived_from == ("ehd:claim/thrust-28-38gf",)

    def test_the_counterfactual_is_flagged(self) -> None:
        g = build_laundering_graph()
        declared, effective, laundered = g.laundering_gap("ehd:counterfactual/mk1-spec-sheet")
        assert (declared, effective, laundered) == (Basis.SOLVED, Basis.CLAIMED, True)

    def test_the_hand_check_lead_stays_claimed(self) -> None:
        # A hand-check contradicting a claim is still only a lead. Recording it as a finding would
        # be the same error in the opposite direction.
        g = build_laundering_graph()
        lead = g.entities["ehd:finding/thrust-discrepancy-lead"]
        assert lead.declared_basis is Basis.CLAIMED
        assert g.effective_basis("ehd:finding/thrust-discrepancy-lead") is Basis.CLAIMED

    def test_exactly_one_node_is_flagged(self) -> None:
        g = build_laundering_graph()
        flagged = [eid for eid in g.entities if g.laundering_gap(eid)[2]]
        assert flagged == ["ehd:counterfactual/mk1-spec-sheet"]

    def test_nothing_here_may_be_called_validated(self) -> None:
        g = build_laundering_graph()
        for entity_id in g.entities:
            assert not may_be_called_validated(g.effective_basis(entity_id)), entity_id

    def test_no_dangling_references(self) -> None:
        g = build_laundering_graph()
        known = set(g.entities) | set(g.activities) | set(g.agents)
        assert _referenced_ids(g) <= known

    def test_both_real_graphs_serialise(self) -> None:
        for builder in (build_mk0_graph, build_laundering_graph):
            document = json.loads(json.dumps(builder().to_jsonld()))
            assert document["@graph"]
