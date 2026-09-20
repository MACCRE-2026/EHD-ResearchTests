"""Specification for FEMM's automation story — CRSDL Task 7, Batch D.

Written 2026-09-19 before the implementation.

Why this task exists
--------------------
CRSDL Task 8 is a **headless** Plausibility Contract loop: a PRR goes in, a PC or an RoC comes out,
one command, no GUI in the path. FEMM is the electrostatics route and is currently classified
``manual_only=True``, which would stop the loop at the one domain this project understands best.

The operator supplied a screenshot claiming two headless routes. It was treated as a **lead** and
checked against disk on 2026-09-19:

* **``femm-lua.bat`` does not exist.** No ``.bat``, ``.cmd`` or ``.py`` file exists anywhere under
  ``C:\\femm42``. The screenshot's first route is not available on this install as described.
* **"pyFEMM without legacy ActiveX" is doubtful here.** ``C:\\femm42\\bin\\femm.tlb`` is present, and
  a type library *is* the ActiveX binding. ActiveX is not disqualifying; it changes what the adapter
  records, not whether the route works.
* **Two routes the screenshot did not name, both present on disk:** COM automation through
  ``femm.tlb``, and **the solvers are separate executables** — ``bin\\csolv.exe`` for electrostatics,
  with ``triangle.exe`` as the mesher — so a prepared problem file can be solved with no GUI at all.

So there are three candidate routes and **no verdict on any of them**. This module specifies that
each gets one, and that whichever way it lands, the registers stop describing an assumption and start
describing a verification.

Nothing here launches FEMM
--------------------------
Every test below reads registers and specs. None invokes ``femm.exe``, because a version probe against
a GUI executable opens a window during the test run — which is why ``GUI_EXECUTABLES`` exists. The
actual headless attempt is the task's demo and is recorded in a run record, not performed in pytest.
*A solver run nobody performed did not happen*, and a solver run performed inside a test suite that
was supposed to be headless is its own kind of lie.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ehdpsu import detect

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The three candidate routes, from the 2026-09-19 reconnaissance. Each needs a recorded verdict.
EXPECTED_ROUTES = ("femm-lua-bat", "com-typelib", "solver-exe-direct")

#: Verdicts a route may carry. ``unverified`` is deliberately **not** among them: the whole point of
#: the task is that every route leaves with a verdict, and "we did not look" is a verdict only when
#: it says why looking was impossible.
ALLOWED_VERDICTS = ("works", "absent", "fails", "not-attempted-because")


def _routes() -> dict[str, str]:
    """The route register, or a failure stating what it must be.

    ``getattr`` rather than an import so its absence is a readable assertion instead of a
    module-scope ``ImportError`` that aborts collection for this file.
    """
    register = getattr(detect, "FEMM_AUTOMATION_ROUTES", None)
    assert register is not None, (
        "ehdpsu.detect.FEMM_AUTOMATION_ROUTES does not exist. It must map each candidate route to "
        "its verified verdict and the evidence for it, so that FEMM's manual_only classification "
        "cites a verification rather than an assumption. Expected route keys: "
        f"{list(EXPECTED_ROUTES)}."
    )
    assert isinstance(register, dict), "FEMM_AUTOMATION_ROUTES must be a dict of route -> verdict"
    return register


def _femm_spec() -> Any:
    for spec in detect.KNOWN_TOOLS:
        if spec.name == "femm":
            return spec
    pytest.fail("no ToolSpec named 'femm' in detect.KNOWN_TOOLS")


class TestEveryCandidateRouteLeavesWithAVerdict:
    @pytest.mark.parametrize("route", EXPECTED_ROUTES)
    def test_the_route_is_registered(self, route: str) -> None:
        assert route in _routes(), (
            f"{route!r} has no recorded verdict. All three candidates were identified on "
            f"2026-09-19; leaving one unexamined means the next session re-derives the same "
            f"reconnaissance."
        )

    @pytest.mark.parametrize("route", EXPECTED_ROUTES)
    def test_the_verdict_is_one_of_the_declared_kinds(self, route: str) -> None:
        verdict = _routes().get(route, "")
        assert any(verdict.startswith(v) for v in ALLOWED_VERDICTS), (
            f"{route!r} carries {verdict!r}, which does not begin with one of {ALLOWED_VERDICTS}. "
            f"A verdict has to be machine-readable at its head so a reader cannot mistake a "
            f"hedge for a result."
        )

    @pytest.mark.parametrize("route", EXPECTED_ROUTES)
    def test_the_verdict_carries_its_evidence(self, route: str) -> None:
        """A verdict without evidence is the assumption it was supposed to replace."""
        verdict = _routes().get(route, "")
        assert len(verdict) > 60, (
            f"{route!r}'s verdict is {verdict!r}, too short to carry evidence. State what was run "
            f"or looked for, and what came back."
        )

    def test_the_bat_route_is_recorded_absent_on_this_install(self) -> None:
        """Already verified: no ``.bat`` exists anywhere under ``C:\\femm42``.

        Pinned because it is the route the screenshot named first, and the next reader will find the
        same screenshot. Recording the negative is what stops the lead being chased twice.
        """
        verdict = _routes().get("femm-lua-bat", "")
        assert verdict.startswith("absent"), (
            f"femm-lua-bat is recorded as {verdict!r}. The 2026-09-19 disk check found no .bat, "
            f".cmd or .py file anywhere under C:\\femm42 on this install. If a later FEMM version "
            f"ships one, supersede this test rather than editing the finding."
        )


class TestTheClassificationFollowsTheVerdicts:
    def test_a_working_route_makes_femm_scriptable(self) -> None:
        """If any route works, ``manual_only=True`` is a false statement about the world.

        The same shape as the LTspice discovery: a tool classified manual-only because nobody had
        tried, then found to run headless in 20 seconds.
        """
        working = {k: v for k, v in _routes().items() if v.startswith("works")}
        if not working:
            return  # covered by the no-route case below
        assert _femm_spec().manual_only is False, (
            f"these FEMM routes are recorded as working — {sorted(working)} — but the ToolSpec "
            f"still says manual_only=True. A capability that exists and is declared absent is the "
            f"same class of error as one that is absent and declared present."
        )

    def test_a_working_route_gives_femm_a_version_probe(self) -> None:
        """A headless route that can solve can also report a version.

        ``TOOLS_WITHOUT_A_VERSION_PROBE`` exists for tools that genuinely cannot be asked. A tool
        that can be driven headlessly and still has its version transcribed by hand is carrying an
        operator-typed figure for no reason, and a typed figure has no reviewer.
        """
        working = {k: v for k, v in _routes().items() if v.startswith("works")}
        if not working:
            return
        spec = _femm_spec()
        assert spec.version_args or "femm" not in detect.TOOLS_WITHOUT_A_VERSION_PROBE, (
            "a working headless route exists, so femm should either declare version_args or be "
            "removed from TOOLS_WITHOUT_A_VERSION_PROBE with the new route named as the source of "
            "the version string."
        )

    def test_femm_may_only_leave_the_version_probe_register_against_evidence(self) -> None:
        """The counterpart to the lowered register floor.

        ``REGISTER_FLOORS`` was dropped from 5 to 4 on 2026-09-19 so that this task would not stall
        on a shrink the planner could already predict — if a headless route works, femm gains
        ``version_args`` and ``test_detect.py`` forces its entry out of this register.

        That concession is paid for here. The entry may leave, but only when a working route is
        recorded, so the register cannot quietly lose a member for any other reason. A lowered floor
        with no compensating assertion would be a checked thing becoming an unchecked one.
        """
        if "femm" in detect.TOOLS_WITHOUT_A_VERSION_PROBE:
            return
        working = {k: v for k, v in _routes().items() if v.startswith("works")}
        assert working, (
            "femm has been removed from TOOLS_WITHOUT_A_VERSION_PROBE but no FEMM automation route "
            "is recorded as working. The register floor was lowered to 4 specifically to allow this "
            "removal against evidence; without the evidence the removal is an undeclared gap."
        )

    def test_no_working_route_is_recorded_as_a_verified_negative(self) -> None:
        """The honest outcome if FEMM cannot be driven headlessly here.

        ``manual_only=True`` stays — but its *reason* must change from the current assumption
        ("GUI-driven; asking femm.exe for a version launches it") to a statement of what was
        attempted. An unexamined assumption and a verified constraint look identical in a register
        and are completely different facts.
        """
        if any(v.startswith("works") for v in _routes().values()):
            return
        reason = detect.TOOLS_WITHOUT_A_VERSION_PROBE.get("femm", "")
        assert any(
            token in reason.lower() for token in ("attempted", "tried", "verified", "2026-09")
        ), (
            "no FEMM route works, so the version-probe exemption must cite the attempt rather than "
            f"the assumption. Current reason reads: {reason!r}"
        )


class TestTheHeadlessLoopDependencyIsVisible:
    def test_something_states_that_task_8_depends_on_this(self) -> None:
        """A dependency nobody wrote down is a dependency that gets discovered late.

        This is the MK era's first failure in miniature: the plan committed to a headless loop while
        the electrostatics route's automation story was unexamined.
        """
        text = "\n".join(
            p.read_text(encoding="utf-8") for p in (REPO_ROOT / ".kiro" / "steering").glob("*.md")
        )
        register_text = " ".join(_routes().values())
        combined = (text + register_text).lower()
        assert "headless" in combined, (
            "nothing in the steering layer or the route register says why FEMM's automation story "
            "matters. State that a scripted contract loop cannot contain a GUI step."
        )


class TestTheReconnaissanceIsPinned:
    """Facts established on disk 2026-09-19. Pinned so a later change is visible as a change."""

    def test_the_type_library_is_named_as_the_com_route(self) -> None:
        verdict = _routes().get("com-typelib", "")
        assert "tlb" in verdict.lower() or "com" in verdict.lower(), (
            "the COM route's verdict does not mention the type library it depends on. "
            "C:\\femm42\\bin\\femm.tlb is the binding, and naming it is what makes the verdict "
            "checkable by someone else."
        )

    def test_the_direct_solver_route_names_the_electrostatics_solver(self) -> None:
        verdict = _routes().get("solver-exe-direct", "")
        assert "csolv" in verdict.lower(), (
            "the direct-solver verdict does not name csolv.exe. The FEMM install ships its solvers "
            "as separate executables — belasolv, csolv, hsolv, plus triangle as the mesher — and "
            "csolv is the electrostatics one this project needs."
        )
