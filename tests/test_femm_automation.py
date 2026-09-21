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
#: it says what was looked for.
ALLOWED_VERDICTS = ("works", "absent", "fails", "not-attempted")


def _routes() -> dict[str, Any]:
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
        entry = _routes().get(route)
        assert entry is not None, f"{route!r} is not registered"
        assert entry.verdict in ALLOWED_VERDICTS, (
            f"{route!r} carries verdict {entry.verdict!r}, which is not one of {ALLOWED_VERDICTS}. "
            f"The verdict is a closed set so a reader cannot mistake a hedge for a result."
        )

    @pytest.mark.parametrize("route", EXPECTED_ROUTES)
    def test_the_verdict_carries_its_evidence_in_named_fields(self, route: str) -> None:
        """Each of ``tried``, ``observed`` and ``checked_on`` is separately non-empty.

        **This replaced a character-count check, 2026-09-20.** The original asserted
        ``len(verdict) > 60`` on a single prose string, which rewards **length rather than truth** — and
        that is not hypothetical. The ``solver-exe-direct`` verdict passed it while asserting that
        ``csolv.exe`` requires a ``.pro`` problem file: FEMM has no ``.pro`` format, and ``csolv`` is
        the current-flow solver rather than the electrostatics one. A fabricated file extension and a
        misattributed binary scored exactly as well as an observation, because the only thing being
        measured was how many characters were present.

        Splitting the evidence into *what was tried* and *what came back* makes each separately
        empty-checkable, which is a property. A character count is a token assertion wearing property
        clothing, which is the same error the planner has now made three times.
        """
        entry = _routes().get(route)
        assert entry is not None, f"{route!r} is not registered"
        for field in ("tried", "observed", "checked_on"):
            value = getattr(entry, field, "")
            assert isinstance(value, str) and value.strip(), (
                f"{route!r} has an empty {field!r}. `tried` says what was done, `observed` says what "
                f"came back, `checked_on` dates it. An empty `tried` means nobody looked, which is "
                f"itself the finding."
            )
        assert len(entry.observed.split()) >= 8, (
            f"{route!r}'s `observed` is {entry.observed!r}, too terse to be an observation. State "
            f"what came back, not whether it worked."
        )

    def test_no_verdict_claims_a_file_format_femm_does_not_have(self) -> None:
        """``.pro`` specifically, because a fabricated format is what got past the old check.

        FEMM's problem files are ``.fem`` (magnetics), ``.fee`` (electrostatics), ``.feh`` (heat flow)
        and ``.fec`` (current flow) — read from the solver binaries' own strings. Nothing in FEMM uses
        ``.pro``, and the project's own Lua already writes a ``.fee``.
        """
        for route, entry in _routes().items():
            blob = f"{entry.tried} {entry.observed}".lower()
            assert ".pro" not in blob, (
                f"{route!r} names a .pro file. FEMM has no such format; the electrostatics problem "
                f"file is .fee, which ehd_wire_collector.lua already writes via ei_saveas."
            )

    def test_the_bat_route_is_recorded_absent_on_this_install(self) -> None:
        """Already verified: no ``.bat`` exists anywhere under ``C:\\femm42``.

        Pinned because it is the route the screenshot named first, and the next reader will find the
        same screenshot. Recording the negative is what stops the lead being chased twice.
        """
        entry = _routes().get("femm-lua-bat")
        assert entry is not None and entry.verdict == "absent", (
            f"femm-lua-bat is recorded as {entry!r}. The 2026-09-19 disk check found no .bat, "
            f".cmd or .py file anywhere under C:\\femm42 on this install. If a later FEMM version "
            f"ships one, supersede this test rather than editing the finding."
        )


class TestTheClassificationFollowsTheVerdicts:
    def test_a_working_route_makes_femm_scriptable(self) -> None:
        """If any route works, ``manual_only=True`` is a false statement about the world.

        The same shape as the LTspice discovery: a tool classified manual-only because nobody had
        tried, then found to run headless in 20 seconds.
        """
        working = {k: v for k, v in _routes().items() if v.verdict == "works"}
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
        working = {k: v for k, v in _routes().items() if v.verdict == "works"}
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
        working = {k: v for k, v in _routes().items() if v.verdict == "works"}
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
        if any(v.verdict == "works" for v in _routes().values()):
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
        register_text = " ".join(f"{v.tried} {v.observed}" for v in _routes().values())
        combined = (text + register_text).lower()
        assert "headless" in combined, (
            "nothing in the steering layer or the route register says why FEMM's automation story "
            "matters. State that a scripted contract loop cannot contain a GUI step."
        )


class TestTheReconnaissanceIsPinned:
    """Facts established on disk 2026-09-19. Pinned so a later change is visible as a change."""

    def test_the_type_library_is_named_as_the_com_route(self) -> None:
        entry = _routes().get("com-typelib")
        blob = f"{entry.tried} {entry.observed}".lower() if entry else ""
        assert "tlb" in blob or "com" in blob, (
            "the COM route's verdict does not mention the type library it depends on. "
            "C:\\femm42\\bin\\femm.tlb is the binding, and naming it is what makes the verdict "
            "checkable by someone else."
        )

    def test_the_direct_solver_route_names_the_electrostatics_solver(self) -> None:
        """``belasolv.exe``, not ``csolv.exe``.

        **This test asserted the wrong solver until 2026-09-20 and is the reason the register named
        the wrong one.** The planner's reconnaissance inferred "csolv" was electrostatics from its
        name; the test then *mandated* that the verdict say so, and the implementing seat complied
        correctly with a false requirement. Resolved by reading the ASCII strings out of each solver
        binary and matching the problem-file extension each one names:

            belasolv.exe -> .fee     electrostatics   <- what ehd_wire_collector.lua writes
            csolv.exe    -> .fec     current flow
            hsolv.exe    -> .feh     heat flow
            fkn.exe      -> .fem     magnetics

        The lesson is not "check harder". It is that a test asserting a **token** carries the
        planner's error with the authority of a check, where a test asserting a **property** would
        not have had an opinion about which binary is which.
        """
        entry = _routes().get("solver-exe-direct")
        assert entry is not None, "solver-exe-direct is not registered"
        blob = f"{entry.tried} {entry.observed}".lower()
        assert "belasolv" in blob, (
            "the direct-solver verdict does not name belasolv.exe, which is FEMM's electrostatics "
            "solver and the one this project needs. FEMM ships its solvers as separate executables; "
            "csolv is current flow, not electrostatics."
        )
