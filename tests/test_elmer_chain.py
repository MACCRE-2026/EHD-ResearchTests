"""Specification for the Gmsh → ElmerGrid → ElmerSolver chain — CRSDL Task 20, Batch E.

Written 2026-09-19 before the implementation. Audit findings F10 and F11.

What running the chain found
---------------------------
On 2026-09-18, with Gmsh 4.15.2 and Elmer 26.1-Release freshly installed, the whole chain was run for
the first time::

    Gmsh 4.15.2      ehd_cell.geo -2            rc 0   14544 nodes / 29093 elements, no warnings
    ElmerGrid 26.1   14 2 ehd_cell.msh -autoclean  rc 0   mesh DB ehd_cell/  14543 nodes / 28722 tris
    ElmerSolver 26.1 ehd_cell.sif               rc 1   ERROR:: LoadMesh: Requested mesh
                                                        > ./ehd_cell_mesh < does not exist!

Three things fell out, and the first is the one that matters most for how this project works.

**F10 — the mesh directory name exists twice and the two copies disagree.** The ``.geo``'s own comment
says to run ``gmsh ehd_cell.geo -2 -o ehd_cell.msh``; the ``.sif`` declares
``Mesh DB "." "ehd_cell_mesh"``. ElmerGrid names its output directory after the mesh file, so it
produces ``ehd_cell``, and the solve stops. *Principle 4, two representations of one thing will
drift* — and this pair was born drifted. **998 passing tests, a tracked regeneration diff and a
planner review all missed it**, because none of them is an Elmer parser.

**F11 — four named boundaries, two boundary conditions.** The ``.geo`` declares
``Physical Curve("Emitter")``, ``("Collector")``, ``("SideWalls")`` and ``("TopFarField")``, and all
four survive conversion: ``mesh.names`` carries ``Emitter=1 Collector=2 SideWalls=3 TopFarField=4``
and ElmerGrid writes an ``entities.sif`` skeleton naming them. The generated ``.sif`` declares only
two. So there is no inlet and no outlet — consistent with the file's own statement that it solves to
the trivial zero-velocity field, but it means the boundary wiring has never been exercised.

**F10b — the conversion silently changed the mesh.** 14,544 → 14,543 nodes, and 371 → 364 line
elements. Probably the arc-centre construction point and duplicate curve endpoints, but that is a
*hypothesis* and nothing records what was dropped. *A CFD field inherits its mesh*, so the
transformation belongs in the chain of custody rather than in someone's memory.

Scope note
----------
These tests do not run Elmer. They specify the generated artifacts and the adapter contract, which is
what can be checked in a clone. The end-to-end solve is the task's demo and is recorded in a run
record — and reaching boundary assembly is what finally closes the name-binding question that has been
open since batch 1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from ehdpsu import adapters
from ehdpsu.adapters import solvers


def _adapter(name: str) -> Any:
    for a in adapters.ADAPTERS:
        if a.name == name:
            return a
    pytest.fail(f"no adapter named {name!r} in adapters.ADAPTERS")


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """The ``.geo`` and ``.sif`` as generated, keyed by suffix."""
    out = tmp_path_factory.mktemp("elmer_chain")
    text: dict[str, str] = {}
    for name in ("gmsh", "elmer"):
        for path in _adapter(name).generate(out):
            text[path.suffix] = path.read_text(encoding="utf-8")
    assert ".geo" in text and ".sif" in text, f"expected a .geo and a .sif, got {sorted(text)}"
    return text


def _physical_curves(geo: str) -> list[str]:
    return re.findall(r'Physical\s+Curve\s*\(\s*"([^"]+)"\s*\)', geo)


def _sif_boundary_names(sif: str) -> list[str]:
    return re.findall(r'Boundary Condition\s+\d+\s*\n\s*Name\s*=\s*String\s*"([^"]+)"', sif)


def _mesh_db(sif: str) -> tuple[str, str]:
    m = re.search(r'Mesh DB\s+"([^"]*)"\s+"([^"]*)"', sif)
    assert m, "the .sif has no `Mesh DB` declaration"
    return m.group(1), m.group(2)


def _msh_stem(geo: str) -> str:
    """The mesh filename the ``.geo`` tells its reader to produce, without its suffix."""
    m = re.search(r"-o\s+(\S+?)\.msh", geo)
    assert m, "the .geo does not name its own .msh output; the chain has no stated entry point"
    return m.group(1)


class TestTheMeshDirectoryNameHasOneSource:
    def test_a_shared_stem_constant_exists(self) -> None:
        """One seam, and everything reads through it.

        Neither adapter may spell the cell's name for itself. The specific defect was two spellings
        of one directory; a shared constant is the only fix that cannot drift again, because there is
        nothing left to disagree with.
        """
        stem = getattr(solvers, "CELL_STEM", None)
        assert stem is not None, (
            "ehdpsu.adapters.solvers.CELL_STEM does not exist. The Gmsh geometry, its .msh output "
            "and the Elmer Mesh DB are three references to one name and must read from one place."
        )
        assert isinstance(stem, str) and stem, "CELL_STEM must be a non-empty string"

    def test_the_sif_mesh_db_matches_the_msh_the_geo_produces(
        self, generated: dict[str, str]
    ) -> None:
        """The exact F10 defect, as a regression.

        ElmerGrid names its output directory after the mesh file it converted. So the Mesh DB name is
        the ``.msh`` stem — not the stem plus a suffix, however descriptive that suffix reads.
        """
        _, db_name = _mesh_db(generated[".sif"])
        stem = _msh_stem(generated[".geo"])
        assert db_name == stem, (
            f"the .sif asks Elmer for mesh {db_name!r} while the .geo produces {stem}.msh, so "
            f"ElmerGrid writes a directory called {stem!r}. This is the error the first real run hit:\n"
            f"  ERROR:: LoadMesh: Requested mesh > ./{db_name} < does not exist!"
        )

    def test_neither_artifact_hardcodes_the_stem(self, generated: dict[str, str]) -> None:
        """Both must interpolate ``CELL_STEM``, not repeat its value.

        Checked at the source level rather than in the output, because two literals that happen to
        agree today are still two literals.
        """
        stem = getattr(solvers, "CELL_STEM", None)
        if stem is None:
            pytest.fail("CELL_STEM does not exist; see the previous test")
        source = Path(solvers.__file__).read_text(encoding="utf-8")
        occurrences = len(re.findall(rf'"{re.escape(stem)}', source))
        assert occurrences == 0, (
            f'the literal "{stem}" still appears {occurrences} time(s) in solvers.py. Interpolate '
            f"CELL_STEM instead, or the next rename reproduces F10."
        )


class TestEveryNamedBoundaryHasACondition:
    def test_the_geo_still_declares_four_physical_curves(self, generated: dict[str, str]) -> None:
        """Guard on the input side, so a change here is visible as a change."""
        curves = _physical_curves(generated[".geo"])
        assert set(curves) == {"Emitter", "Collector", "SideWalls", "TopFarField"}, (
            f"the .geo's physical curves changed to {curves}. If the domain's boundaries genuinely "
            f"changed, update this test deliberately in the same diff."
        )

    def test_the_sif_declares_a_condition_for_each(self, generated: dict[str, str]) -> None:
        """F11. Two of four is not a wiring you can claim has been checked."""
        curves = set(_physical_curves(generated[".geo"]))
        declared = set(_sif_boundary_names(generated[".sif"]))
        missing = sorted(curves - declared)
        assert not missing, (
            f"these named boundaries have no condition in the .sif: {missing}. All four survive "
            f"ElmerGrid — mesh.names carries Emitter=1 Collector=2 SideWalls=3 TopFarField=4 — so "
            f"leaving two unwired means the domain has no inlet and no outlet, and the binding has "
            f"never been exercised."
        )

    def test_no_condition_names_a_boundary_the_mesh_does_not_have(
        self, generated: dict[str, str]
    ) -> None:
        """The other direction: a condition for a boundary that does not exist binds to nothing.

        Elmer does not necessarily complain, which is what makes it worth a test — a silently unbound
        condition reads exactly like a bound one in the file.
        """
        curves = set(_physical_curves(generated[".geo"]))
        stray = sorted(set(_sif_boundary_names(generated[".sif"])) - curves)
        assert not stray, f"these conditions name boundaries absent from the mesh: {stray}"

    def test_the_far_field_is_not_silently_a_wall(self, generated: dict[str, str]) -> None:
        """Wiring all four as no-slip would satisfy the coverage test and mean nothing.

        The cheapest way to make the test above green is to copy the emitter's zero-velocity block
        four times. That is a sealed box, and it is a *different* wrong answer from two missing
        conditions rather than a fix. Whatever the top boundary becomes — open, outlet, prescribed
        pressure — it must not be a zero-velocity wall.
        """
        sif = generated[".sif"]
        block = re.search(
            r'Boundary Condition\s+\d+\s*\n\s*Name\s*=\s*String\s*"TopFarField".*?\nEnd',
            sif,
            flags=re.DOTALL,
        )
        assert block, "no TopFarField boundary condition block found"
        body = block.group(0)
        both_zero = re.search(r"Velocity 1\s*=\s*Real\s*0\.0", body) and re.search(
            r"Velocity 2\s*=\s*Real\s*0\.0", body
        )
        assert not both_zero, (
            "TopFarField is wired as a no-slip wall, which seals the flow domain. The .sif already "
            "states it solves to the trivial zero-velocity field for want of a body force; sealing "
            "the box removes even the possibility of checking the wiring."
        )


class TestTheConversionIsPartOfTheChainOfCustody:
    def test_elmer_reads_back_the_mesh_it_solved_on(self) -> None:
        """F10b. ElmerGrid changed the mesh and nothing recorded it.

        Gmsh already reports its own ``n_nodes`` and ``n_elements``. What is missing is the count
        Elmer actually *received*, which is the only place the 14,544 → 14,543 drop becomes visible.
        Without it a run record attests to a field without attesting to the mesh under it.
        """
        keys = set(_adapter("elmer").read_back_keys)
        assert any("node" in k for k in keys) and any("element" in k for k in keys), (
            f"the Elmer adapter reads back {sorted(keys)} and nothing about the mesh it solved on. "
            f"Add the received node and element counts so the ElmerGrid transformation is recorded "
            f"rather than remembered."
        )

    def test_the_sif_says_the_conversion_may_change_the_mesh(
        self, generated: dict[str, str]
    ) -> None:
        """The artifact carries the warning, because the artifact is what gets read.

        ``-autoclean`` is in the instruction the ``.sif`` already prints. That it silently drops
        entities is a fact the next operator needs at the moment they run the command, not one they
        should rediscover by comparing two log files.
        """
        sif = generated[".sif"].lower()
        assert "autoclean" in sif, "the .sif no longer names the ElmerGrid command it depends on"
        assert any(
            token in sif for token in ("may change", "drops", "removed", "differ", "fewer")
        ), (
            "the .sif tells the reader to run ElmerGrid -autoclean without saying that it can "
            "change the node and element counts. On this project's own first run it dropped one "
            "node and seven line elements."
        )


class TestWhatThisChainStillCannotClaim:
    def test_the_sif_still_declares_that_it_has_no_body_force(
        self, generated: dict[str, str]
    ) -> None:
        """The honesty that survived the 0.05x seat and must survive this task too.

        Wiring the boundaries makes the mesh and the binding checkable. It does **not** add the
        electrohydrodynamic body force, and a ``.sif`` that gained four boundary conditions and lost
        its statement about the missing physics would be a more convincing file describing the same
        trivial solve. Inventing a coupling coefficient here is the curve-fitting this project
        forbids.
        """
        sif = generated[".sif"].lower()
        assert "body force" in sif, (
            "the .sif no longer states that the EHD body force is deliberately absent. That "
            "statement is why the file is honest about solving to zero velocity."
        )
        assert any(
            token in sif for token in ("zero-velocity", "zero velocity", "trivial")
        ), "the .sif no longer says what it actually solves to."
