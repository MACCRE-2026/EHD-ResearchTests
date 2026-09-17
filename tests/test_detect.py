"""Invariant tests for the adapter detection layer.

**These tests were written before the implementation, and they are the specification.** The
implementing seat may not modify this file; making it pass is the whole task.

That inversion is deliberate. The first attempt at this module was specified in prose, and prose
invariants proved insufficient: the module shipped violating the one invariant the packet argued for
at greatest length, while its own tests were green. Turning each invariant into a test converts
"did it follow the spec?" from the reviewing agent's judgement into a Gate result.

Every test here is an **invariant or a refusal**, never a happy path. The detection layer exists
because reporting a working tool as absent is *principle 2, an approximately-correct identifier is
worse than an absent one*: Kiro CLI 2.21.4 was installed and working on this machine while
``Get-Command kiro-cli`` found nothing, because the shell had inherited its environment before the
installer wrote the user ``PATH``. So the load-bearing property is not "finds tools". It is
**never claims an absence it has not earned.**

Five things are pinned that the first attempt got wrong:

1. ``TOOL_ABSENT`` is reachable only when every route in ``ROUTE_ORDER`` was attempted *and* each
   reached a conclusion. Off Windows the registry route cannot conclude, so absence is unreachable
   there. The first attempt returned it anyway, because its guard
   (``sys.platform == "win32" and registry_accessible is False``) has a left operand that is false
   on exactly the platforms where the right operand matters.
2. ``ToolProbe`` and ``ToolSpec`` are frozen dataclasses. The first attempt used hand-written
   ``__slots__`` classes whose fields could be reassigned, so a caller could set ``status`` to
   ``present`` on a tool that had not been found.
3. ``routes_tried`` records the routes **actually attempted**, in order, and the search stops at the
   first route that resolves. The packet's wording — "append the route's name whether or not it
   succeeds" — was ambiguous, and the first attempt read it as "always all four", which makes the
   packet's own ``TOOL_ABSENT`` test vacuous: the assertion becomes unconditionally true. Recording
   a route as tried when it was skipped is *principle 3, never report success over unperformed
   work*, in miniature.
4. No branch of a test may assert what its sibling asserts. The first attempt's "never a version
   without a path" test asserted ``path is not None`` in both the ``if`` and the ``else``, so no
   input could have failed it.
5. Nothing in this seam reduces coverage conditionally. The first attempt carried
   ``pytest.skip("Windows-specific test")``, invisible on this machine and Gate-reddening on any
   other. Platform-specific behaviour is injected at a seam instead.

**No test here depends on which solvers happen to be installed.** A test whose result depends on the
operator's install state is not a test. The real spec table is exercised only through assertions of
the form "whatever came back is self-consistent".
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from ehdpsu import detect

# The canonical route order. Stated here rather than read from the module, because reading
# `detect.ROUTE_ORDER` and comparing it against itself would assert nothing.
EXPECTED_ROUTE_ORDER = (
    "configured-path",
    "process-path",
    "windows-registry",
    "default-paths",
)

# The tools the suite orchestrates, and which of them are GUI-driven. `manual_only` does not exempt
# a tool from detection; it only means `run` will later report as manual.
EXPECTED_TOOLS = ("femm", "ltspice", "qspice", "gmsh", "elmer", "openfoam", "paraview")
EXPECTED_MANUAL_ONLY = ("femm", "ltspice", "qspice", "paraview")

# A filename no executable on any machine can have, so every route is forced to be attempted and
# to fail. Not a design value: it is chosen to be meaningless.
UNRESOLVABLE_EXE = "ehd-no-such-tool-2f8a1c94.exe"

REPO_ROOT = Path(__file__).resolve().parents[1]


def _unresolvable_spec(
    name: str = "unresolvable",
    version_args: tuple[str, ...] = (),
    default_paths: tuple[Path, ...] = (),
    manual_only: bool = False,
) -> detect.ToolSpec:
    """A spec that cannot resolve by any route, for exercising the absence paths."""
    return detect.ToolSpec(
        name=name,
        executables=(UNRESOLVABLE_EXE,),
        default_paths=default_paths,
        version_args=version_args,
        manual_only=manual_only,
    )


def _fake_tool(
    tmp_path: Path,
    filename: str = "faketool.exe",
    version_args: tuple[str, ...] = (),
    manual_only: bool = False,
) -> tuple[Path, detect.ToolSpec]:
    """A file on disk, plus a spec that resolves to it through the ``configured-path`` route."""
    exe = tmp_path / filename
    exe.write_text("not a real executable\n", encoding="utf-8")
    spec = detect.ToolSpec(
        name=filename.removesuffix(".exe"),
        executables=(filename,),
        default_paths=(),
        version_args=version_args,
        manual_only=manual_only,
    )
    return exe, spec


def _is_frozen_dataclass(cls: type) -> bool:
    """True when ``cls`` is a dataclass declared ``frozen=True``.

    Read through ``getattr`` because ``__dataclass_params__`` is undocumented as far as the type
    checkers are concerned, and a ``type: ignore`` that mypy and pyright disagree about turns the
    Gate red for the wrong reason.
    """
    if not dataclasses.is_dataclass(cls):
        return False
    params = getattr(cls, "__dataclass_params__", None)
    return bool(getattr(params, "frozen", False))


class TestKnownTools:
    """The spec table is a published fact, so it is checked as one."""

    def test_every_known_tool_is_well_formed(self) -> None:
        for spec in detect.KNOWN_TOOLS:
            assert spec.name and spec.name.strip(), f"{spec!r}: empty name"
            assert spec.executables, f"{spec.name}: no executables to look for"
            assert all(e and e.strip() for e in spec.executables), f"{spec.name}: empty executable"
            assert isinstance(spec.manual_only, bool), f"{spec.name}: manual_only is not a bool"
            assert isinstance(spec.version_args, tuple), f"{spec.name}: version_args not a tuple"
            assert isinstance(spec.default_paths, tuple), f"{spec.name}: default_paths not a tuple"
            assert all(
                isinstance(p, Path) for p in spec.default_paths
            ), f"{spec.name}: default_paths holds something that is not a Path"

    def test_known_tool_names_are_unique(self) -> None:
        """Two specs under one name would be two representations of one tool.

        *Principle 4, two representations of one thing will drift.*
        """
        names = [s.name for s in detect.KNOWN_TOOLS]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"

    def test_every_expected_tool_is_known(self) -> None:
        """All seven solvers are in the table.

        A missing entry does not error. It reports nothing about a tool, which reads to a caller
        exactly like a tool that is absent.
        """
        names = {s.name for s in detect.KNOWN_TOOLS}
        missing = [t for t in EXPECTED_TOOLS if t not in names]
        assert not missing, f"KNOWN_TOOLS omits {missing}"

    def test_gui_driven_tools_are_marked_manual_only(self) -> None:
        by_name = {s.name: s for s in detect.KNOWN_TOOLS}
        for name in EXPECTED_MANUAL_ONLY:
            assert by_name[name].manual_only is True, f"{name} is GUI-driven but not manual_only"

    def test_headless_tools_are_not_marked_manual_only(self) -> None:
        """The flag has to discriminate, or it carries no information."""
        by_name = {s.name: s for s in detect.KNOWN_TOOLS}
        for name in (n for n in EXPECTED_TOOLS if n not in EXPECTED_MANUAL_ONLY):
            assert by_name[name].manual_only is False, (
                f"{name} runs headless but is marked manual_only; if every tool is manual_only the "
                f"flag distinguishes nothing"
            )

    def test_no_version_probe_targets_a_gui_executable(self) -> None:
        """A GUI executable is never asked for a version, because asking launches it.

        ``paraview.exe --version`` opens a window on Windows, so a suite that runs ``detect_all``
        would launch an application on any machine where ParaView is installed — machine-dependent
        behaviour for a reason invisible in the test.

        **Amended 2026-09-16.** This test previously read "no ``manual_only`` tool carries
        ``version_args``", which is a coarser claim than it meant and it failed on a tool that is
        perfectly safe to probe. ParaView is GUI-driven for visualisation work *and* ships
        ``pvpython.exe``, which accepts ``--version``; one boolean cannot carry both facts. The
        invariant is therefore stated against the executables that actually get invoked. The probe
        runs on whichever executable resolved, so a GUI name **anywhere** in a probeable spec's list
        is the hazard, not just the first one.
        """
        offenders = [
            f"{spec.name}:{name}"
            for spec in detect.KNOWN_TOOLS
            if spec.version_args
            for name in spec.executables
            if name in detect.GUI_EXECUTABLES
        ]
        assert not offenders, (
            f"version-probeable specs listing a GUI executable: {offenders}. The probe runs against "
            f"whichever executable resolved, so this launches an application."
        )

    def test_the_gui_register_is_not_empty_and_names_real_executables(self) -> None:
        """An empty hazard register would make the test above pass by vacuity."""
        assert detect.GUI_EXECUTABLES, "GUI_EXECUTABLES is empty, so nothing is guarded against"
        unknown = sorted(n for n in detect.GUI_EXECUTABLES if n not in detect.EXECUTABLE_PROVENANCE)
        assert not unknown, (
            f"GUI_EXECUTABLES names executables with no provenance entry: {unknown}. A hazard "
            f"register built from guessed filenames guards against nothing."
        )


class TestRouteOrder:
    """The order is published, and every recorded route was really attempted."""

    def test_module_publishes_the_canonical_route_order(self) -> None:
        """The order is a constant, not something inferable only from control flow.

        Order buried in an if-chain cannot be asserted by a caller, and cannot be shown to a human
        reading a probe to work out why their tool was not found.
        """
        assert hasattr(detect, "ROUTE_ORDER"), "detect.ROUTE_ORDER is not defined"
        assert detect.ROUTE_ORDER == EXPECTED_ROUTE_ORDER

    def test_routes_tried_is_an_ordered_prefix_of_the_canonical_order(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        assert isinstance(probe.routes_tried, tuple), "routes_tried must be an immutable tuple"
        n = len(probe.routes_tried)
        assert probe.routes_tried == EXPECTED_ROUTE_ORDER[:n], (
            f"routes_tried {probe.routes_tried} is not a prefix of {EXPECTED_ROUTE_ORDER}; routes "
            f"are attempted in the published order and none is skipped mid-run"
        )

    def test_configured_path_is_attempted_first_even_when_none_is_given(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec(), configured_path=None)
        assert probe.routes_tried[0] == "configured-path"

    def test_search_stops_at_the_route_that_resolves(self, tmp_path: Path) -> None:
        """A resolved configured path means the later routes were never attempted.

        Recording them anyway claims work that was not performed — *principle 3, never report
        success over unperformed work* — and it makes the ``TOOL_ABSENT`` invariant untestable,
        because "all four routes recorded" becomes unconditionally true.
        """
        exe, spec = _fake_tool(tmp_path)
        probe = detect.detect_tool(spec, configured_path=tmp_path)
        assert probe.path == exe
        assert probe.routes_tried == ("configured-path",), (
            f"routes_tried is {probe.routes_tried}; the configured path resolved, so no later "
            f"route was attempted and none may be recorded as tried"
        )

    def test_every_recorded_route_is_a_known_route_name(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        unknown = [r for r in probe.routes_tried if r not in EXPECTED_ROUTE_ORDER]
        assert not unknown, f"routes_tried holds unrecognised route name(s): {unknown}"

    def test_routes_tried_has_no_duplicates(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        assert len(probe.routes_tried) == len(set(probe.routes_tried)), (
            f"routes_tried {probe.routes_tried} repeats a route; a route recorded twice makes the "
            f"record useless for working out what was actually done"
        )


class TestAbsenceIsEarned:
    """``TOOL_ABSENT`` is the only status making a positive claim about the world."""

    def test_absence_requires_every_route_to_have_been_attempted(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        if probe.status is detect.ToolStatus.TOOL_ABSENT:
            assert probe.routes_tried == EXPECTED_ROUTE_ORDER, (
                f"TOOL_ABSENT claimed after attempting only {probe.routes_tried}. Absence means "
                f"every route was tried and none resolved."
            )

    def test_absence_never_carries_a_path_or_a_version(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        if probe.status is detect.ToolStatus.TOOL_ABSENT:
            assert probe.path is None
            assert probe.version is None

    def test_off_windows_absence_is_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The invariant the first attempt violated.

        The registry route cannot be attempted to a conclusion off Windows, so absence cannot be
        earned there, and every unresolved tool must come back ``TOOL_UNRESOLVED``.
        """
        monkeypatch.setattr(detect.sys, "platform", "linux")
        probe = detect.detect_tool(_unresolvable_spec())
        assert probe.status is detect.ToolStatus.TOOL_UNRESOLVED, (
            f"status is {probe.status.value!r} off Windows. The windows-registry route cannot "
            f"conclude there, so absence has not been established and TOOL_UNRESOLVED is the only "
            f"honest answer."
        )

    def test_off_windows_the_registry_route_is_still_recorded_as_attempted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Skipped and recorded, so a reader can see *why* the answer is inconclusive."""
        monkeypatch.setattr(detect.sys, "platform", "linux")
        probe = detect.detect_tool(_unresolvable_spec())
        assert "windows-registry" in probe.routes_tried

    def test_an_inconclusive_probe_says_why_it_could_not_conclude(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An inconclusive result with no stated reason is indistinguishable from a bug."""
        monkeypatch.setattr(detect.sys, "platform", "linux")
        probe = detect.detect_tool(_unresolvable_spec())
        assert probe.note is not None and probe.note.strip(), (
            "TOOL_UNRESOLVED with no note. The note is the only place the reason for "
            "inconclusiveness survives to whoever reads the probe."
        )

    def test_off_windows_no_known_tool_is_reported_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same invariant across the real spec table, not only a fabricated spec."""
        monkeypatch.setattr(detect.sys, "platform", "linux")
        wrongly_absent = [
            p.name for p in detect.detect_all() if p.status is detect.ToolStatus.TOOL_ABSENT
        ]
        assert not wrongly_absent, f"reported absent off Windows: {wrongly_absent}"

    def test_an_unreadable_registry_is_unresolved_not_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A route that raised did not conclude, so absence has not been established.

        Runs on every platform: the failure is injected at the module's own registry helper rather
        than at ``winreg``, which does not exist off Windows. Guarding this with a ``skipif``
        instead would leave the behaviour unchecked on the platform where it is hardest to observe.
        """
        monkeypatch.setattr(detect.sys, "platform", "win32")

        def explode(*_a: object, **_k: object) -> list[Path]:
            raise OSError("registry unreadable")

        monkeypatch.setattr(detect, "_read_registry_path_entries", explode)
        probe = detect.detect_tool(_unresolvable_spec())
        assert probe.status is detect.ToolStatus.TOOL_UNRESOLVED, (
            f"status is {probe.status.value!r} after the registry route raised. This is the Kiro "
            f"CLI 2.21.4 case: the tool was installed and working while the process path knew "
            f"nothing about it."
        )

    def test_the_registry_read_is_a_single_injectable_seam(self) -> None:
        """One helper, so the unreadable case is reachable from a test.

        Registry access spread inline through ``detect_tool`` cannot be made to fail, which means
        the ``TOOL_UNRESOLVED`` branch cannot be exercised and only looks covered.
        """
        assert hasattr(detect, "_read_registry_path_entries"), (
            "no _read_registry_path_entries helper; the registry read must be one seam that a "
            "test can make fail, or the unreadable-registry path is unreachable"
        )

    def test_both_path_scopes_are_read(self) -> None:
        """Machine **and** User. The Kiro CLI incident was a User-scope write.

        Asserted against the source rather than by reading the registry, so it holds on a machine
        where either scope happens to be empty.
        """
        source = Path(detect.__file__).read_text(encoding="utf-8")
        assert "HKEY_LOCAL_MACHINE" in source, "the Machine PATH scope is never read"
        assert "HKEY_CURRENT_USER" in source, "the User PATH scope is never read"


class TestConfiguredPath:
    def test_a_configured_path_that_does_not_exist_does_not_resolve(self, tmp_path: Path) -> None:
        probe = detect.detect_tool(_unresolvable_spec(), configured_path=tmp_path / "nowhere")
        assert probe.status is not detect.ToolStatus.PRESENT
        assert probe.path is None
        assert probe.routes_tried[0] == "configured-path"

    def test_a_configured_directory_containing_the_executable_resolves(
        self, tmp_path: Path
    ) -> None:
        exe, spec = _fake_tool(tmp_path)
        probe = detect.detect_tool(spec, configured_path=tmp_path)
        assert probe.status is detect.ToolStatus.PRESENT
        assert probe.path == exe

    def test_a_configured_file_that_is_the_executable_resolves(self, tmp_path: Path) -> None:
        exe, spec = _fake_tool(tmp_path)
        probe = detect.detect_tool(spec, configured_path=exe)
        assert probe.status is detect.ToolStatus.PRESENT
        assert probe.path == exe

    def test_a_configured_path_falling_through_does_not_abort_the_search(
        self, tmp_path: Path
    ) -> None:
        """A wrong override degrades to the remaining routes, never to a false absence."""
        probe = detect.detect_tool(_unresolvable_spec(), configured_path=tmp_path / "nowhere")
        assert len(probe.routes_tried) > 1, (
            f"routes_tried is {probe.routes_tried}; a configured path that did not resolve falls "
            f"through to the later routes rather than ending the search"
        )


class TestVersionCapture:
    """Verbatim or not at all. A constructed version string is a fabricated measurement."""

    def test_a_version_is_never_reported_without_a_path(self, tmp_path: Path) -> None:
        """Checked across every scenario this file can produce, with distinct branch assertions.

        The first attempt's version of this test asserted ``path is not None`` in both branches of
        its ``if``, so no input could have failed it.
        """
        _, resolving = _fake_tool(tmp_path)
        probes = [
            detect.detect_tool(_unresolvable_spec()),
            detect.detect_tool(_unresolvable_spec(version_args=("--version",))),
            detect.detect_tool(resolving, configured_path=tmp_path),
            detect.detect_tool(resolving, configured_path=tmp_path / "nowhere"),
            *detect.detect_all(),
        ]
        with_version = [p for p in probes if p.version is not None]
        without_version = [p for p in probes if p.version is None]
        assert len(with_version) + len(without_version) == len(probes)
        for probe in with_version:
            assert probe.path is not None, (
                f"{probe.name}: version {probe.version!r} with no path. A version that did not "
                f"come from a located executable was constructed, not captured."
            )
        for probe in without_version:
            assert probe.status is not detect.ToolStatus.PRESENT or probe.note, (
                f"{probe.name}: PRESENT with no version and no note. The note is what "
                f"distinguishes 'could not be asked' from 'asked and it said nothing'."
            )

    def test_a_tool_that_cannot_be_asked_reports_no_version_and_says_why(
        self, tmp_path: Path
    ) -> None:
        _, spec = _fake_tool(tmp_path)
        probe = detect.detect_tool(spec, configured_path=tmp_path)
        assert probe.version is None, (
            f"version {probe.version!r} captured from a spec with no version_args; there was no "
            f"way to ask, so any string here was invented"
        )
        assert (
            probe.note is not None and probe.note.strip()
        ), "PRESENT with version=None and no note explaining why the version is missing"

    def test_a_captured_version_is_the_tool_output_unaltered(self) -> None:
        """The one real subprocess here, and it is a program the suite already depends on.

        ``sys.executable`` stands in for a solver so the assertion does not depend on any solver
        being installed. The reported string is deliberately awkward — mixed case, inner runs of
        spaces, a pre-release suffix, build metadata — because normalisation is the failure mode
        and a tidy string cannot detect tidying.
        """
        reported = "fAkE-SoLvEr   9.9.9-beta+build.7"
        python = Path(sys.executable)
        spec = detect.ToolSpec(
            name="python-as-a-stand-in",
            executables=(python.name,),
            default_paths=(),
            version_args=("-c", f"print({reported!r})"),
            manual_only=False,
        )
        probe = detect.detect_tool(spec, configured_path=python)
        assert probe.status is detect.ToolStatus.PRESENT
        assert probe.path == python
        assert probe.version == reported, (
            f"version came back {probe.version!r}, not {reported!r}. Trimming the line's own "
            f"leading and trailing whitespace is permitted; altering anything inside it is not."
        )

    def test_no_version_probe_runs_when_nothing_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing resolved, so there is no executable to ask, so nothing may be executed."""

        def forbidden(*_a: object, **_k: object) -> object:
            raise AssertionError("subprocess.run called although no executable had been located")

        monkeypatch.setattr(detect.subprocess, "run", forbidden)
        probe = detect.detect_tool(_unresolvable_spec(version_args=("--version",)))
        assert probe.version is None

    def test_a_failing_version_probe_does_not_invent_a_version(self, tmp_path: Path) -> None:
        """The file exists and is not executable, so the probe fails. A failure is not a version."""
        exe, spec = _fake_tool(tmp_path, filename="notexecutable.exe", version_args=("--version",))
        probe = detect.detect_tool(spec, configured_path=exe)
        assert probe.path == exe
        assert probe.version is None
        assert probe.note is not None and probe.note.strip(), (
            "a failed version probe left no note; the reason the version is missing is the only "
            "thing that distinguishes 'could not ask' from 'asked and it said nothing'"
        )


class TestManualOnlyIsStillDetected:
    def test_manual_only_does_not_suppress_detection(self, tmp_path: Path) -> None:
        """Packet invariant 4. Needing a human to press a button is a ``run`` concern.

        If ``manual_only`` suppressed detection, every GUI solver in the suite — FEMM, LTspice,
        QSPICE, ParaView — would report as undetected while installed and working.
        """
        exe, spec = _fake_tool(tmp_path, filename="guitool.exe", manual_only=True)
        probe = detect.detect_tool(spec, configured_path=tmp_path)
        assert probe.status is detect.ToolStatus.PRESENT
        assert probe.path == exe

    def test_manual_only_is_not_consulted_before_detection(self, tmp_path: Path) -> None:
        """Two specs differing only in the flag detect identically."""
        exe = tmp_path / "eithertool.exe"
        exe.write_text("either\n", encoding="utf-8")
        manual = detect.ToolSpec(
            name="eithertool",
            executables=("eithertool.exe",),
            default_paths=(),
            version_args=(),
            manual_only=True,
        )
        headless = detect.ToolSpec(
            name="eithertool",
            executables=("eithertool.exe",),
            default_paths=(),
            version_args=(),
            manual_only=False,
        )
        a = detect.detect_tool(manual, configured_path=tmp_path)
        b = detect.detect_tool(headless, configured_path=tmp_path)
        assert a.status is b.status
        assert a.path == b.path == exe


class TestImmutability:
    """A probe is a record of what was observed. A record that can be edited is not evidence."""

    def test_tool_probe_is_a_frozen_dataclass(self) -> None:
        assert _is_frozen_dataclass(detect.ToolProbe), (
            "ToolProbe is not a frozen dataclass. The first attempt used a hand-written __slots__ "
            "class, and a caller could overwrite status on a tool that had not been found."
        )

    def test_tool_spec_is_a_frozen_dataclass(self) -> None:
        assert _is_frozen_dataclass(detect.ToolSpec), "ToolSpec is not a frozen dataclass"

    def test_a_probe_status_cannot_be_overwritten(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(probe, "status", detect.ToolStatus.PRESENT)  # noqa: B010

    def test_a_probe_path_cannot_be_overwritten(self) -> None:
        probe = detect.detect_tool(_unresolvable_spec())
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(probe, "path", Path("C:/anything"))  # noqa: B010

    def test_a_spec_cannot_be_edited_in_place(self) -> None:
        spec = _unresolvable_spec()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(spec, "name", "renamed")  # noqa: B010

    def test_detection_does_not_mutate_the_spec_it_was_given(self) -> None:
        spec = _unresolvable_spec()
        before = (spec.name, spec.executables, spec.default_paths, spec.version_args)
        detect.detect_tool(spec)
        assert (spec.name, spec.executables, spec.default_paths, spec.version_args) == before


class TestDetectAll:
    def test_one_probe_per_known_tool_in_order(self) -> None:
        probes = detect.detect_all()
        assert [p.name for p in probes] == [s.name for s in detect.KNOWN_TOOLS]

    def test_no_duplicate_probes(self) -> None:
        names = [p.name for p in detect.detect_all()]
        assert len(names) == len(set(names)), f"duplicate probes: {names}"

    def test_every_probe_is_internally_consistent(self) -> None:
        """Holds whatever is installed, which is what lets it run on any machine."""
        for probe in detect.detect_all():
            assert probe.status in tuple(detect.ToolStatus)
            assert isinstance(probe.routes_tried, tuple)
            assert probe.routes_tried, f"{probe.name}: no route recorded as attempted"
            if probe.status is detect.ToolStatus.PRESENT:
                assert probe.path is not None, f"{probe.name}: PRESENT with no path"
            else:
                assert probe.path is None, (
                    f"{probe.name}: {probe.status.value} while carrying path {probe.path}. A "
                    f"located executable is PRESENT."
                )

    def test_detect_all_accepts_an_explicit_spec_set(self) -> None:
        specs = (_unresolvable_spec("one"), _unresolvable_spec("two"))
        assert [p.name for p in detect.detect_all(specs)] == ["one", "two"]


class TestNoSideEffects:
    def test_importing_the_module_runs_no_subprocess(self) -> None:
        """Import must be inert. A module that probes at import time probes on ``--help``.

        Run in a clean interpreter, because the module is already imported in this one and an
        import that has already happened cannot be observed again. ``subprocess`` is broken
        *before* the import, so a call raises rather than being counted afterwards.
        """
        script = (
            "import subprocess\n"
            "def forbidden(*a, **k):\n"
            "    raise SystemExit('subprocess invoked at import time')\n"
            "subprocess.run = forbidden\n"
            "subprocess.Popen = forbidden\n"
            "subprocess.check_output = forbidden\n"
            "import ehdpsu.detect\n"
            "print('inert')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"import was not inert: {result.stdout}{result.stderr}"
        assert "inert" in result.stdout

    def test_detection_writes_nothing_into_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Packet invariant 5: version probes only, and nothing on disk changes."""
        work = tmp_path / "cwd"
        work.mkdir()
        monkeypatch.chdir(work)
        detect.detect_all()
        left_behind = list(work.iterdir())
        assert left_behind == [], f"detection left files behind: {left_behind}"


class TestThisSeamStaysChecked:
    """Guards against the checks being weakened rather than satisfied."""

    def test_neither_this_module_nor_the_implementation_reduces_coverage(self) -> None:
        """No skip, no xfail, no importorskip anywhere in this seam.

        Parsed rather than grepped: this docstring and the assertion messages name the constructs,
        and a substring scan would fail on its own explanation. The AST walk sees calls and
        decorators, so prose about them is invisible to it.

        A conditional skip reports success over unperformed work on every machine where the
        condition holds — *principle 3, never report success over unperformed work* — and the Gate
        treats a skip that fires as reduced coverage, exit 14.
        """
        banned_calls = {"skip", "importorskip", "exit"}
        banned_marks = {"skipif", "xfail"}
        offenders: list[str] = []

        for path in (Path(__file__), Path(detect.__file__)):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr in banned_calls
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "pytest"
                    ):
                        offenders.append(f"{path.name}:{node.lineno} pytest.{func.attr}(...)")
                if isinstance(node, ast.Attribute) and node.attr in banned_marks:
                    offenders.append(f"{path.name}:{node.lineno} .{node.attr}")

        assert not offenders, (
            f"coverage-reducing constructs in this seam: {offenders}. A platform-specific case is "
            f"injected at a seam instead, as test_an_unreadable_registry_is_unresolved_not_absent "
            f"does."
        )


# ---------------------------------------------------------------------------
# Added 2026-09-16, after the second implementation attempt.
#
# The tests above caught every defect they were written for. What they did not catch is the more
# useful finding: the implementing seat satisfied every invariant that was written down and drifted
# on every dimension that was not. It emptied all seven `default_paths` tuples, dropped Elmer's
# version probe, changed `detect_all`'s published signature, ran version probes in the caller's
# working directory, and — worst — carried three executable names that do not exist on any machine.
#
# None of that was a failure of the seat's reading. It was an absence in this file. So each gap
# becomes an invariant here rather than a note in a ledger, because a fix without a test does not
# survive the next implementation.
# ---------------------------------------------------------------------------


class TestExecutableNamesAreAttributed:
    """The worst defect this module can have, and the only one with an external cause.

    A wrong executable name yields a confident ``TOOL_ABSENT`` for a tool that is installed and
    working — the precise failure the module exists to prevent, arriving through its reference data
    rather than its logic. *Principle 2, an approximately-correct identifier is worse than an absent
    one*, at the point where the identifier enters the system.

    Three fabricated names survived two implementations and a Gate run: ``ASCA.exe`` for LTspice,
    ``ElmerMesh.exe`` for Elmer, ``OpenFOAM.exe`` for OpenFOAM. No test could have distinguished
    them from real ones, because a filename is only checkable against the vendor.
    """

    def test_every_executable_name_is_attributed(self) -> None:
        unattributed = [
            f"{spec.name}:{name}"
            for spec in detect.KNOWN_TOOLS
            for name in spec.executables
            if name not in detect.EXECUTABLE_PROVENANCE
        ]
        assert not unattributed, (
            f"executable names with no entry in EXECUTABLE_PROVENANCE: {unattributed}. A filename "
            f"cannot be inferred, only read from the vendor. An unattributed name is a guess, and a "
            f"guess here produces a false absence rather than an error."
        )

    def test_every_attribution_cites_a_source(self) -> None:
        """A reason without a source is an assertion wearing a citation's clothes."""
        uncited = [
            name
            for name, text in detect.EXECUTABLE_PROVENANCE.items()
            if "http" not in text or len(text) < 40
        ]
        assert (
            not uncited
        ), f"EXECUTABLE_PROVENANCE entries with no URL or too terse to check: {uncited}"

    def test_no_attribution_is_orphaned(self) -> None:
        """The register documents the table, so it may not outlive it.

        An entry for a name no spec uses is a stale citation, and a stale citation is what makes the
        next reader trust the rest of the register less than they should.
        """
        in_use = {name for spec in detect.KNOWN_TOOLS for name in spec.executables}
        # GUI_EXECUTABLES is the other legitimate consumer: a name may be cited because it must
        # never be probed rather than because it is detected.
        orphans = sorted(set(detect.EXECUTABLE_PROVENANCE) - in_use - detect.GUI_EXECUTABLES)
        assert not orphans, (
            f"EXECUTABLE_PROVENANCE cites names that no spec detects and no hazard register "
            f"guards: {orphans}"
        )


class TestDeclaredGapsAreDeclared:
    """Empty reference data is either a fact or an oversight, and only a register can tell them apart.

    Both registers mirror ``DESIGN_VALUE_EXEMPTIONS`` and the Gate's declared exclusions: the escape
    hatch exists, and using it costs a written reason. An earlier revision emptied every
    ``default_paths`` tuple silently, so the ``default-paths`` route could not resolve anything and
    nothing said so.
    """

    def test_every_tool_has_default_paths_or_a_declared_reason(self) -> None:
        undeclared = [
            spec.name
            for spec in detect.KNOWN_TOOLS
            if not spec.default_paths and spec.name not in detect.TOOLS_WITHOUT_DEFAULT_PATHS
        ]
        assert not undeclared, (
            f"tools with no default_paths and no declared reason: {undeclared}. The default-paths "
            f"route cannot resolve anything for them, which is a capability gap, not a neutral fact."
        )

    def test_every_tool_can_be_version_probed_or_a_declared_reason(self) -> None:
        """A tool with no version probe cannot support a `solved` basis.

        ``solver-provenance`` requires a tool version before a run counts as ``solved`` rather than
        ``analytical-placeholder``, so an unprobeable tool caps the basis of everything derived from
        it. That is a consequence worth declaring rather than discovering.
        """
        undeclared = [
            spec.name
            for spec in detect.KNOWN_TOOLS
            if not spec.version_args and spec.name not in detect.TOOLS_WITHOUT_A_VERSION_PROBE
        ]
        assert (
            not undeclared
        ), f"tools that cannot be asked for a version, with no declared reason: {undeclared}"

    @pytest.mark.parametrize(
        "register", ["TOOLS_WITHOUT_DEFAULT_PATHS", "TOOLS_WITHOUT_A_VERSION_PROBE"]
    )
    def test_declared_reasons_are_substantive_and_not_orphaned(self, register: str) -> None:
        """A one-word reason is a rubber stamp, and an entry for an unknown tool is stale."""
        entries: dict[str, str] = getattr(detect, register)
        known = {spec.name for spec in detect.KNOWN_TOOLS}
        for name, reason in entries.items():
            assert name in known, f"{register} names {name!r}, which is not a known tool"
            assert len(reason.split()) >= 8, (
                f"{register}[{name!r}] gives {reason!r}. A reason short enough to write without "
                f"thinking is not a reason."
            )

    def test_an_unverified_name_says_so_where_it_is_used(self) -> None:
        """``simpleFoam.exe`` is a lead, not a confirmed filename, and it is labelled as one.

        No blueCFD-Core installation was inspected. Rather than drop the entry or present it as
        checked, it is carried with ``windows_native=False`` so absence can never be claimed from it
        — *principle 7, verified means reproduced*, applied to reference data.
        """
        text = detect.EXECUTABLE_PROVENANCE["simpleFoam.exe"]
        assert "LEAD" in text.upper(), "the unverified OpenFOAM filename is not labelled as a lead"
        by_name = {s.name: s for s in detect.KNOWN_TOOLS}
        assert by_name["openfoam"].windows_native is False


class TestToolsWithoutANativeWindowsBinary:
    """OpenFOAM is not reachable by a Windows path search, so its absence cannot be established."""

    def test_a_non_native_tool_is_never_reported_absent(self) -> None:
        by_name = {s.name: s for s in detect.KNOWN_TOOLS}
        probe = detect.detect_tool(by_name["openfoam"])
        assert probe.status is not detect.ToolStatus.TOOL_ABSENT, (
            "openfoam reported absent. It runs under WSL2, Docker, or a third-party port, none of "
            "which a Windows path search reaches, so the four routes cannot conclude."
        )

    def test_a_non_native_tool_explains_itself(self) -> None:
        spec = detect.ToolSpec(
            name="openfoam",
            executables=(UNRESOLVABLE_EXE,),
            default_paths=(),
            version_args=(),
            windows_native=False,
        )
        probe = detect.detect_tool(spec)
        assert probe.status is detect.ToolStatus.TOOL_UNRESOLVED
        assert probe.note is not None and "native" in probe.note.lower()

    def test_windows_native_defaults_to_true(self) -> None:
        """The unusual case is the one that has to be declared, not the ordinary one."""
        assert _unresolvable_spec().windows_native is True


class TestThePublishedInterfaceDoesNotDrift:
    """A signature is part of the contract, and an equivalent-but-different one is still a change."""

    def test_detect_all_defaults_to_known_tools_in_its_signature(self) -> None:
        """The default belongs in the signature, where a reader and a type checker both see it.

        An earlier revision took ``Iterable[ToolSpec] | None = None`` and resolved the default in the
        body. Behaviourally identical for every caller, and undetectable from the outside, which is
        why it needs asserting rather than reviewing: the published interface is what other adapters
        will be written against.
        """
        default = inspect.signature(detect.detect_all).parameters["specs"].default
        assert default is detect.KNOWN_TOOLS, (
            f"detect_all's specs default is {default!r}, not KNOWN_TOOLS. A default resolved inside "
            f"the body is invisible in the signature and in help()."
        )

    def test_the_module_exports_what_the_contract_names(self) -> None:
        expected = {
            "EXECUTABLE_PROVENANCE",
            "GUI_EXECUTABLES",
            "KNOWN_TOOLS",
            "ROUTE_ORDER",
            "TOOLS_WITHOUT_A_VERSION_PROBE",
            "TOOLS_WITHOUT_DEFAULT_PATHS",
            "ToolProbe",
            "ToolSpec",
            "ToolStatus",
            "detect_all",
            "detect_tool",
        }
        assert (
            set(detect.__all__) == expected
        ), f"__all__ is {sorted(detect.__all__)}; the contract names {sorted(expected)}"


class TestVersionProbeIsolation:
    """A version probe runs somewhere disposable, because some tools write beside their cwd."""

    def test_a_version_probe_runs_in_a_directory_it_was_given(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asserted by inspecting the call, not by looking for droppings afterwards.

        ``test_detection_writes_nothing_into_the_working_directory`` passed on this machine only
        because no version-probeable tool resolved here, so it asserted the invariant without
        exercising it. Capturing the ``cwd`` keyword tests the same property on any machine.
        """
        work = tmp_path / "caller_cwd"
        work.mkdir()
        monkeypatch.chdir(work)

        seen: list[object] = []

        class Completed:
            returncode = 0
            stdout = "STAND-IN 1.0\n"
            stderr = ""

        def record(*_a: object, **kw: object) -> Completed:
            seen.append(kw.get("cwd"))
            return Completed()

        monkeypatch.setattr(detect.subprocess, "run", record)

        exe, _ = _fake_tool(tmp_path, filename="probeme.exe")
        spec = detect.ToolSpec(
            name="probeme",
            executables=("probeme.exe",),
            default_paths=(),
            version_args=("--version",),
            manual_only=False,
        )
        probe = detect.detect_tool(spec, configured_path=exe)

        assert probe.version == "STAND-IN 1.0"
        assert seen, "no subprocess call was recorded, so the probe did not run"
        cwd = seen[0]
        assert cwd is not None, (
            "the version probe inherited the caller's working directory. A tool that writes a log "
            "or a cache beside its cwd would then write it into the caller's."
        )
        assert Path(str(cwd)).resolve() != work.resolve()

    def test_a_version_on_stderr_is_still_captured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gmsh prints its version on stderr in some builds.

        Reading stdout alone would report no version from an installed, working Gmsh — a missing
        version rather than a wrong one, so it degrades visibly, but it degrades for no reason.
        """

        class Completed:
            returncode = 0
            stdout = "   \n"
            stderr = "  4.15.2  \n"

        monkeypatch.setattr(detect.subprocess, "run", lambda *_a, **_k: Completed())

        exe, _ = _fake_tool(tmp_path, filename="stderrtool.exe")
        spec = detect.ToolSpec(
            name="stderrtool",
            executables=("stderrtool.exe",),
            default_paths=(),
            version_args=("-version",),
            manual_only=False,
        )
        probe = detect.detect_tool(spec, configured_path=exe)
        assert probe.version == "4.15.2"

    def test_a_nonzero_exit_is_not_a_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output from a failed invocation is a usage message, not a version."""

        class Failed:
            returncode = 1
            stdout = "usage: tool [options]\n"
            stderr = "unrecognised option\n"

        monkeypatch.setattr(detect.subprocess, "run", lambda *_a, **_k: Failed())

        exe, _ = _fake_tool(tmp_path, filename="grumpy.exe")
        spec = detect.ToolSpec(
            name="grumpy",
            executables=("grumpy.exe",),
            default_paths=(),
            version_args=("--version",),
            manual_only=False,
        )
        probe = detect.detect_tool(spec, configured_path=exe)
        assert probe.version is None
        assert probe.note is not None and probe.note.strip()


class TestGmshVersionSwitch:
    def test_gmsh_asks_with_a_single_dash(self) -> None:
        """``-version``, not ``--version``. Both earlier revisions had it wrong.

        Gmsh's documented general options list ``-version`` with one dash. The wrong switch does not
        error visibly: the probe fails, the version comes back ``None``, and an installed Gmsh looks
        like one that cannot report a version. A silent capability loss is the hardest kind to notice,
        which is why the switch is pinned here rather than trusted to the table.
        """
        by_name = {s.name: s for s in detect.KNOWN_TOOLS}
        assert by_name["gmsh"].version_args == ("-version",), (
            f"gmsh version_args is {by_name['gmsh'].version_args}; Gmsh takes -version with a "
            f"single dash - https://manpages.ubuntu.com/manpages/noble/man1/gmsh.1.html"
        )

    def test_paraview_is_detected_only_through_its_headless_client(self) -> None:
        """``pvpython.exe`` and nothing else, so a version probe can never open a window.

        Any real ParaView install carries ``pvpython.exe`` beside ``paraview.exe`` in the same
        ``bin\\``, and a GUI-only install could not drive the adapter regardless — the visualization
        path renders through ``pvpython``. So excluding the GUI name loses no detection and removes
        the hazard by construction. ``-V/--version`` is documented as common to every ParaView
        executable.
        """
        by_name = {s.name: s for s in detect.KNOWN_TOOLS}
        assert by_name["paraview"].executables == ("pvpython.exe",), (
            f"paraview executables are {by_name['paraview'].executables}; adding a GUI name back "
            f"reintroduces the launch-during-pytest hazard"
        )
        assert by_name["paraview"].version_args == ("--version",)


class TestNoDeadCode:
    def test_every_private_helper_is_used(self) -> None:
        """A helper nobody calls was copied in, not written.

        ``_is_frozen_dataclass`` was lifted verbatim out of this test file into the implementation and
        never called. Ruff does not flag an unused module-level function, so nothing said so. Dead
        code is not merely untidy here: it reads as a capability the module has, and the next author
        wires it up rather than asking whether it was ever wanted.
        """
        tree = ast.parse(Path(detect.__file__).read_text(encoding="utf-8"))
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_")
        }
        called = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        unused = sorted(defined - called)
        assert (
            not unused
        ), f"private helpers defined and never referenced in {Path(detect.__file__).name}: {unused}"

    def test_the_probe_record_is_built_in_few_enough_places_to_stay_consistent(self) -> None:
        """The note rule lived at all four routes once, eight duplicated lines each.

        Four representations of one rule is *principle 4, two representations of one thing will
        drift*, and the drift here would be four probes disagreeing about what a missing version
        means. Bounded rather than forbidden: a resolved probe and the two unresolved outcomes are
        genuinely different records.
        """
        tree = ast.parse(Path(detect.__file__).read_text(encoding="utf-8"))
        constructions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ToolProbe"
        ]
        assert len(constructions) <= 3, (
            f"ToolProbe is constructed in {len(constructions)} places. Each carries its own note "
            f"logic, and they will disagree."
        )
