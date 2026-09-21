"""Tool detection and version capture for the external solvers.

Every adapter owes five obligations — detect, version, generate, run, parse. This module implements
the first two.

The load-bearing property is **not** "finds tools". It is **never claims an absence it has not
earned.** Kiro CLI 2.21.4 was installed and working on this machine while ``Get-Command kiro-cli``
found nothing, because the shell had inherited its environment before the installer wrote the user
``PATH``. Reporting a working tool as absent is *principle 2, an approximately-correct identifier is
worse than an absent one* — a wrong non-empty answer propagates and gets acted on, while an
inconclusive one degrades visibly. Hence three statuses rather than two, and hence
``TOOL_UNRESOLVED`` wherever a route could not be attempted to a conclusion.

The same principle governs the spec table, and it is why ``EXECUTABLE_PROVENANCE`` exists. A
**guessed** executable name is the worst possible input here: it produces a confident
``TOOL_ABSENT`` for a tool that is installed and working, which is exactly the failure this module
was written to prevent. Two earlier revisions carried names that do not exist — ``ASCA.exe``,
``ElmerMesh.exe``, ``OpenFOAM.exe`` — and nothing caught them, because a plausible filename is
indistinguishable from a real one until somebody checks. Every name now cites where it was read, and
a test refuses a name without a citation.

``tests/test_detect.py`` is the specification for the behaviour, and it was written before this
module.
"""

from __future__ import annotations

import enum
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    import winreg

__all__ = (
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
)


@dataclass(frozen=True)
class RouteVerdict:
    """One automation route's verdict, with its evidence in named fields.

    **Structured rather than prose, corrected 2026-09-20.** The first version of this register mapped
    each route to a single string and the test guarding it asserted only ``len(verdict) > 60`` — so it
    rewarded **length, not truth**. A verdict padded with a plausible-sounding file extension scored
    identically to one carrying a real observation, and that is exactly what happened: the
    ``solver-exe-direct`` verdict asserted a ``.pro`` problem file, a format FEMM does not have.

    Splitting the evidence into ``tried`` and ``observed`` makes "did anyone look, and what came back"
    two separate questions that can each be empty-checked. That is a property. A character count is
    not.
    """

    #: One of ``works``, ``absent``, ``fails``, ``not-attempted``. Machine-readable, so a reader
    #: cannot mistake a hedge for a result.
    verdict: str
    #: What was actually done. An empty string means nobody looked, which is itself a finding.
    tried: str
    #: What came back. The observation, not the interpretation.
    observed: str
    #: ISO date of the check, so a stale verdict is visibly stale.
    checked_on: str


#: FEMM automation routes and what is actually known about each.
#:
#: **Two corrections applied 2026-09-20 after domain review.**
#:
#: 1. The electrostatics solver is **``belasolv.exe``**, not ``csolv.exe``. Read from the binaries'
#:    own strings: ``belasolv -> .fee``, ``csolv -> .fec`` (current flow), ``hsolv -> .feh`` (heat),
#:    ``fkn -> .fem`` (magnetics). The planner's reconnaissance mislabelled it, and the test guarding
#:    this register then *mandated* naming ``csolv``, so the error arrived with the authority of a
#:    check. ``solver_inputs/ehd_wire_collector.lua`` writes ``ei_saveas("ehd_wire_collector.fee")``,
#:    so the file this project already generates is exactly what ``belasolv.exe`` consumes.
#: 2. There is **no ``.pro`` format** in FEMM. That claim was fabricated.
#:
#: The practical consequence reverses the earlier reading: this route is not blocked by a format
#: mismatch, it is simply **untried**, and the path to trying it is concrete.
FEMM_AUTOMATION_ROUTES: dict[str, RouteVerdict] = {
    "femm-lua-bat": RouteVerdict(
        verdict="absent",
        tried=(
            "Searched C:\\femm42 recursively for *.bat, *.cmd and *.py. This is the route the "
            "operator's screenshot named first, so recording the negative is what stops the lead "
            "being chased twice."
        ),
        observed=(
            "No .bat, .cmd or .py file exists anywhere under C:\\femm42 on this install. If a later "
            "FEMM version ships femm-lua.bat, supersede this entry rather than editing it."
        ),
        checked_on="2026-09-19",
    ),
    "com-typelib": RouteVerdict(
        verdict="not-attempted",
        tried=(
            "Checked for a Python COM binding with importlib.util.find_spec over win32com, pyfemm, "
            "femm, pythoncom and win32api."
        ),
        observed=(
            "All five absent, so no binding exists to drive the interface. The type library "
            "C:\\femm42\\bin\\femm.tlb IS present, which means the route is available in principle "
            "and blocked only by a missing dependency. Installing pyfemm or pywin32 makes it "
            "testable; ActiveX is not disqualifying, it only changes what the adapter records."
        ),
        checked_on="2026-09-19",
    ),
    "solver-exe-direct": RouteVerdict(
        verdict="fails",
        tried=(
            "Identified the electrostatics solver by reading the ASCII strings out of each solver "
            "binary and matching the problem-file extension each names. Then ran belasolv.exe three "
            "ways, stdin closed: with no arguments, with -h, and finally against a real problem file "
            "-- C:\\femm42\\examples\\ehd_wire_collector.fee, which THIS PROJECT's own FEMM session "
            "wrote on 2026-09-16 -- copied to a scratch directory and passed as the sole argument "
            "with cwd set there, under a 120 second timeout."
        ),
        observed=(
            "belasolv.exe takes .fee and is the electrostatics solver; csolv.exe takes .fec and is "
            "current flow. All three invocations TIMED OUT. The bare and -h forms neither printed "
            "usage nor exited within 12 s. Given a valid .fee it ran for the full 120 s, wrote NO "
            "output files at all, and produced nothing on stdout or stderr -- so it does not solve "
            "headlessly by this invocation and its argument convention is not established here. "
            "Attempted and failed rather than untried: the input existed, was ours, and was valid. "
            "A different argument form may work; that is now the specific open question rather than "
            "the whole route being unexamined."
        ),
        checked_on="2026-09-20",
    ),
}

# The four routes, in the order they are attempted. Published as a constant rather than left implicit
# in control flow: an order buried in an if-chain cannot be asserted by a caller, and cannot be shown
# to a human reading a probe to work out why their tool was not found.
ROUTE_ORDER = (
    "configured-path",
    "process-path",
    "windows-registry",
    "default-paths",
)

_REGISTRY_PATH_SCOPES = (
    ("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ("HKEY_CURRENT_USER", r"Environment"),
)


class ToolStatus(enum.Enum):
    """What a probe concluded.

    The distinction between the two negative statuses is the point of the module, so it is stated
    here rather than left to the caller to infer.
    """

    PRESENT = "present"
    """An executable was located. A version may or may not have been captured; see ``note``."""

    TOOL_UNRESOLVED = "tool-unresolved"
    """Not located, **and absence was not established.** At least one route could not be attempted to
    a conclusion — the registry was unreadable, ``winreg`` does not exist on this platform, or the
    tool is not a Windows executable at all. Says nothing about whether the tool is installed."""

    TOOL_ABSENT = "tool-absent"
    """Every route in ``ROUTE_ORDER`` was attempted, each reached a conclusion, and none resolved.
    The only status that makes a positive claim about the world."""


@dataclass(frozen=True)
class ToolSpec:
    """How to look for one tool.

    Frozen because a spec is reference data, and reference data a caller can edit in place is
    reference data that will differ between two callers in the same process.
    """

    name: str

    executables: tuple[str, ...]
    """Filenames to look for, most-preferred first. Every entry needs an ``EXECUTABLE_PROVENANCE``
    citation."""

    default_paths: tuple[Path, ...]
    """Known install directories. Empty is legitimate only with an entry in
    ``TOOLS_WITHOUT_DEFAULT_PATHS`` saying why."""

    version_args: tuple[str, ...]
    """Arguments that make the tool print its version and exit. Empty means it cannot be asked, and
    needs an entry in ``TOOLS_WITHOUT_A_VERSION_PROBE``."""

    manual_only: bool = False
    """GUI-driven: a human presses a button. Does **not** exempt the tool from detection; it means
    ``run`` will later report as manual."""

    windows_native: bool = True
    """False when the tool has no native Windows executable — OpenFOAM, which runs under WSL2,
    Docker, or the third-party blueCFD-Core port. For such a tool the four path-based routes cannot
    conclude, so ``TOOL_ABSENT`` is unreachable and the honest answer is ``TOOL_UNRESOLVED``."""


@dataclass(frozen=True)
class ToolProbe:
    """What one detection attempt observed.

    Frozen because a probe is evidence. A record that can be edited after the fact is not evidence,
    and an earlier revision allowed ``probe.status`` to be reassigned to ``present`` on a tool that
    had never been found.
    """

    name: str
    status: ToolStatus
    path: Path | None

    version: str | None
    """Verbatim, exactly as the tool printed it. Never constructed, normalised, inferred or
    defaulted. Trimming the captured text's own surrounding whitespace is the only alteration."""

    routes_tried: tuple[str, ...]
    """The routes **actually attempted**, in ``ROUTE_ORDER``. The search stops at the route that
    resolves, and routes after it are not recorded. Recording a skipped route as tried is
    *principle 3, never report success over unperformed work*, and it makes the ``TOOL_ABSENT``
    invariant untestable."""

    note: str | None = None
    """Why the result is not self-explanatory. Required for ``TOOL_UNRESOLVED``, and for ``PRESENT``
    with no version."""


# ---------------------------------------------------------------------------
# Where every executable name in KNOWN_TOOLS was read.
#
# The remedy for the worst defect this module has had. Filenames are not guessable: LTspice's binary
# is XVIIx64.exe under XVII and LTspice.exe under 24, neither of which anyone would invent, while
# ASCA.exe is exactly the kind of plausible name that does get invented and then produces a confident
# false absence. test_every_executable_name_is_attributed refuses a name without an entry here.
# ---------------------------------------------------------------------------
EXECUTABLE_PROVENANCE: dict[str, str] = {
    "femm.exe": (
        "FEMM 4.2 installs to C:\\femm42\\ by default with the binary in its bin subdirectory - "
        "https://nicadd.niu.edu/~syphers/tutorials/FEMMinstall.html"
    ),
    "LTspice.exe": (
        "LTspice 24 installs under ADI\\LTspice and contains LTspice.exe - "
        "https://uspas.fnal.gov/materials/25Knoxville/Accelerator-Power-Electronics/"
        "InstructionstoInstallandUseLTspice24.pdf"
    ),
    "XVIIx64.exe": (
        "LTspice XVII installs to C:\\Program Files\\LTC\\LTspiceXVII with the 64-bit binary named "
        "XVIIx64.exe - https://uspas.fnal.gov/materials/22onlineTAMU/PowerElectronics/"
        "Computer%20Lab/InstructionstoInstallandUseLTspiceXVII.pdf"
    ),
    "QSPICE64.exe": (
        "Qorvo's forum documents invoking C:\\Program Files\\QSPICE\\QSPICE64.exe on a netlist - "
        "https://forum.qorvo.com/t/qspice-not-responding/23100"
    ),
    "QSPICE80.exe": (
        "the selective-80-bit-arithmetic build shipped alongside QSPICE64.exe - "
        "https://forum.qorvo.com/t/running-qspice-from-command-line/14182"
    ),
    "gmsh.exe": (
        "Gmsh ships for Windows as a portable archive containing gmsh.exe; its CLI is documented in "
        "the reference manual - https://gmsh.info/doc/texinfo/"
    ),
    "ElmerSolver.exe": (
        "Elmer's solution engine, documented as living in <install>\\bin - "
        "https://www.elmerfem.org/forum/viewtopic.php?t=4058"
    ),
    "ElmerGrid.exe": (
        "Elmer's mesh generator and importer, invoked as ElmerGrid.exe on Windows - "
        "https://elmerfem.org/forum/viewtopic.php?p=31429"
    ),
    "ElmerGUI.exe": (
        "Elmer's graphical preprocessor, named alongside ElmerSolver and ElmerGrid as one of the "
        "package's main components - https://nic.csc.fi/pub/files/index/elmer/slides/ElmerIntro.pdf. "
        "Listed in GUI_EXECUTABLES only; no spec detects it, because the adapter drives ElmerSolver."
    ),
    "pvpython.exe": (
        "ParaView's headless Python client; -V/--version is common to all ParaView executables - "
        "https://docs.paraview.org/en/latest/UsersGuide/commandLineArguments.html"
    ),
    "paraview.exe": (
        "the ParaView GUI, in <install>\\bin - https://github.com/Kitware/paraviewweb/blob/master/"
        "documentation/content/docs/windows_10.md"
    ),
    "simpleFoam.exe": (
        "blueCFD-Core is the third-party native-Windows OpenFOAM port, installing by default to "
        "C:\\Program Files\\blueCFD-Core <year>-<n> - https://github.com/blueCFD/Core/issues/257. "
        "Recorded as a LEAD, not a verified filename: no blueCFD-Core installation was inspected, "
        "which is why openfoam carries windows_native=False and can never report TOOL_ABSENT."
    ),
}

# Tools whose `default_paths` is legitimately empty, with the reason. Mirrors the declared-exclusion
# pattern the Gate and DESIGN_VALUE_EXEMPTIONS use: an empty tuple with no reason is
# indistinguishable from an oversight, and an earlier revision emptied all seven silently.
TOOLS_WITHOUT_DEFAULT_PATHS: dict[str, str] = {
    "gmsh": (
        "Gmsh is distributed for Windows as a portable archive with no installer, so there is no "
        "standard directory to look in. An invented one would be a path that never resolves."
    ),
    "openfoam": (
        "OpenFOAM has no native Windows build. It runs under WSL2 or Docker, which a Windows path "
        "cannot reach, or via the third-party blueCFD-Core port whose directory carries a release "
        "number no installation here has confirmed. windows_native is False in consequence."
    ),
}

# Tools that cannot be asked for a version, with the reason. A headless tool with no version probe is
# a gap rather than a neutral fact: solver-provenance requires a tool version before a run counts as
# `solved` instead of `analytical-placeholder`.
TOOLS_WITHOUT_A_VERSION_PROBE: dict[str, str] = {
    "femm": (
        # Corrected 2026-09-20. This read 'verified negative:' over three routes of which only ONE
        # was actually verified; the other two are untried. Unattempted is not verified-absent, and
        # collapsing them is principle 3 in the negative direction -- reporting a stronger status
        # than the work supports. See FEMM_AUTOMATION_ROUTES for each route's own verdict.
        "ONE route verified absent, ONE attempted and failed, ONE untried; none working as of "
        "2026-09-20. Absent: no femm-lua.bat or any .bat/.cmd/.py exists under C:\\femm42. Failed: "
        "belasolv.exe -- the electrostatics solver, which takes .fee, NOT csolv.exe which is current "
        "flow -- was run against this project's own ehd_wire_collector.fee and timed out at 120 s "
        "producing no output. Untried: the COM route via bin\\femm.tlb is available in principle and "
        "blocked only by pyfemm/pywin32 being absent. So femm keeps manual_only=True on one verified "
        "absence, one observed failure and one unexamined route -- not on a settled negative."
    ),
    "ltspice": (
        "GUI-driven, with no documented version-and-exit switch. Its installer does however record "
        "the version in the registry - HKCU\\Software\\Analog Devices Inc.\\LTspice\\Version read "
        "26.0.2.1 on 2026-09-16 - so this tool IS identifiable without launching it, and the "
        "app-registry detection route noted in the ledger would capture it."
    ),
    "qspice": (
        "GUI-driven, and QSPICE has no version number to ask for. Observed 2026-09-16: its About "
        "box reports a BUILD TIMESTAMP PER BINARY, and the four differ - QUX.exe Sep 13 2026, "
        "QSPICE64.exe and QSPICE80.exe Sep 11 2026, QPOST.exe Sep 9 2026. The engine is "
        "QSPICE64.exe, so its build is the one a run record must carry. QUX.exe is listed first and "
        "is the newest, which makes the GUI's timestamp the line a reader naturally grabs and the "
        "wrong one to record."
    ),
    "elmer": (
        "NOT VERIFIED, and left unprobed deliberately. ElmerSolver's behaviour when invoked without "
        "a .sif file is not established here, and a wrong switch risks a solver that waits on input "
        "rather than exiting. An absent version degrades visibly; an invented one does not."
    ),
    "openfoam": (
        "no native Windows executable to invoke. A version would have to come from inside WSL, "
        "outside this module's four routes."
    ),
}

# Executables that open a window when invoked, whatever arguments they are given. No spec carrying
# `version_args` may list one, because the probe runs against whichever executable resolved — so a
# GUI name anywhere in a probeable spec's list is a latent "launches an application during pytest".
#
# ParaView is the case that forced this to be a register rather than a use of `manual_only`. It is
# GUI-driven for actual visualisation work, so `manual_only` is True, and it also ships a headless
# client that accepts `--version`. Those are two different facts and one flag cannot carry both. The
# spec therefore names `pvpython.exe` **only**: any real ParaView install has it beside `paraview.exe`
# in the same `bin\`, and a hypothetical GUI-only install could not drive the adapter anyway. That
# makes the hazard impossible by construction rather than prevented by vigilance.
GUI_EXECUTABLES: frozenset[str] = frozenset(
    {
        "femm.exe",
        "LTspice.exe",
        "XVIIx64.exe",
        "QSPICE64.exe",
        "QSPICE80.exe",
        "paraview.exe",
        "ElmerGUI.exe",
    }
)

KNOWN_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="femm",
        executables=("femm.exe",),
        default_paths=(
            Path(r"C:\femm42\bin"),
            Path(r"C:\Program Files\femm42\bin"),
            Path(r"C:\Program Files (x86)\femm42\bin"),
        ),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="ltspice",
        executables=("LTspice.exe", "XVIIx64.exe"),
        default_paths=(
            Path(r"C:\Program Files\ADI\LTspice"),
            Path(r"C:\ADI\LTspice"),
            Path(r"C:\Program Files\LTC\LTspiceXVII"),
            Path(r"C:\Program Files (x86)\LTC\LTspiceXVII"),
        ),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="qspice",
        executables=("QSPICE64.exe", "QSPICE80.exe"),
        default_paths=(
            Path(r"C:\Program Files\QSPICE"),
            Path(r"C:\Program Files (x86)\QSPICE"),
        ),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="gmsh",
        # `-version`, single dash. Both earlier revisions used `--version`, which Gmsh does not
        # accept, so the probe would have failed on an installed Gmsh and reported no version at all.
        executables=("gmsh.exe",),
        default_paths=(),
        version_args=("-version",),
        manual_only=False,
    ),
    ToolSpec(
        name="elmer",
        executables=("ElmerSolver.exe", "ElmerGrid.exe"),
        default_paths=(
            Path(r"C:\Program Files\Elmer 9.0\bin"),
            Path(r"C:\Program Files (x86)\Elmer 9.0\bin"),
        ),
        version_args=(),
        manual_only=False,
    ),
    ToolSpec(
        name="openfoam",
        executables=("simpleFoam.exe",),
        default_paths=(),
        version_args=(),
        manual_only=False,
        windows_native=False,
    ),
    ToolSpec(
        name="paraview",
        # pvpython.exe ONLY. See GUI_EXECUTABLES: listing paraview.exe here would mean a machine
        # without pvpython gets its GUI launched by a version probe during a test run.
        executables=("pvpython.exe",),
        default_paths=(
            Path(r"C:\Program Files\ParaView\bin"),
            Path(r"C:\Program Files (x86)\ParaView\bin"),
        ),
        version_args=("--version",),
        manual_only=True,
    ),
)


def _read_registry_path_entries() -> list[Path]:
    """Every ``PATH`` directory recorded in the Machine and User registry scopes.

    One seam, for two reasons. It is the only way a test can make the registry route fail — access
    spread inline through ``detect_tool`` would leave the ``TOOL_UNRESOLVED`` branch unreachable, so
    it would only *look* covered. And it is where the Machine/User distinction lives: the Kiro CLI
    incident was a **User**-scope write the process environment had not picked up, so reading only
    the Machine scope would reproduce the original bug.

    Raises:
        OSError: a scope exists but cannot be read. A scope that is simply **absent** is skipped
            instead, because an absent scope is a conclusion while an unreadable one is not.
    """
    entries: list[Path] = []
    for hive_name, key_path in _REGISTRY_PATH_SCOPES:
        hive = getattr(winreg, hive_name)
        try:
            with winreg.OpenKey(hive, key_path) as key:
                raw, _ = winreg.QueryValueEx(key, "PATH")
        except FileNotFoundError:
            continue
        for segment in str(raw).split(";"):
            text = segment.strip().strip('"')
            if text:
                entries.append(Path(text))
    return entries


def _in_directories(directories: Iterable[Path], executables: tuple[str, ...]) -> Path | None:
    """First executable found by scanning ``directories`` in order, preferring earlier names."""
    for directory in directories:
        for name in executables:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _resolve_configured(configured: Path, executables: tuple[str, ...]) -> Path | None:
    """Resolve an operator-supplied override, which may name a directory or the file itself.

    A file the operator named explicitly is accepted on the strength of them naming it, without
    checking it against ``executables``: an override that has to match the built-in list can only
    ever confirm what the built-in list already knew, which defeats the purpose of an override.
    """
    if configured.is_file():
        return configured
    if configured.is_dir():
        return _in_directories((configured,), executables)
    return None


def _resolve_process_path(executables: tuple[str, ...]) -> Path | None:
    """``shutil.which`` per candidate name.

    Deliberately ``shutil.which`` rather than a hand-rolled ``PATH`` walk: it honours ``PATHEXT`` and
    the platform's own notion of executability. A hand-rolled version in an earlier revision required
    a Unix execute bit, which no ordinary Windows file carries.
    """
    for name in executables:
        found = shutil.which(name)
        if found is not None:
            return Path(found)
    return None


def _capture_version(executable: Path, version_args: tuple[str, ...]) -> str | None:
    """Ask a located executable for its version, verbatim, or return ``None``.

    Runs in a throwaway temporary directory so a tool that writes a log or a cache beside its
    working directory cannot touch the caller's. Reads ``stdout`` and falls back to ``stderr``,
    because Gmsh prints its version on ``stderr`` in some builds; whichever stream carried it, the
    text is returned unaltered apart from trimming its own surrounding whitespace.
    """
    if not version_args:
        return None
    try:
        with tempfile.TemporaryDirectory() as scratch:
            completed = subprocess.run(
                [str(executable), *version_args],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=scratch,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    for stream in (completed.stdout, completed.stderr):
        text = (stream or "").strip()
        if text:
            return text
    return None


def _note_for_resolved(spec: ToolSpec, version: str | None) -> str | None:
    """The one place a resolved probe's note is composed.

    One place because an earlier revision built it at all four routes, eight duplicated lines each —
    four representations of one rule, which *principle 4, two representations of one thing will
    drift*, says will eventually disagree.
    """
    if version is not None:
        return None
    if not spec.version_args:
        reason = TOOLS_WITHOUT_A_VERSION_PROBE.get(spec.name)
        if reason is not None:
            return f"located; no version probe available: {reason}"
        return "located; this spec declares no version_args, so the tool was not asked"
    return "located, but the version probe failed or printed nothing; version withheld rather than guessed"


def _join_notes(parts: Iterable[str | None]) -> str | None:
    """Combine note fragments, or ``None`` when there is nothing to say.

    An empty string would be a note that renders as blank while being technically present, which is
    the difference between "nothing to report" and "reported nothing".
    """
    kept = [p.strip() for p in parts if p and p.strip()]
    return "; ".join(kept) if kept else None


def detect_tool(spec: ToolSpec, configured_path: Path | None = None) -> ToolProbe:
    """Locate one tool, trying each route in ``ROUTE_ORDER`` until one resolves.

    Args:
        spec: what to look for.
        configured_path: an operator override, either the executable or a directory holding it.

    Returns:
        A ``ToolProbe``. ``TOOL_ABSENT`` only when every route was attempted **and** each concluded.
    """
    routes_tried: list[str] = []
    inconclusive: list[str] = []
    warnings: list[str] = []
    resolved: Path | None = None

    routes_tried.append("configured-path")
    if configured_path is not None:
        resolved = _resolve_configured(configured_path, spec.executables)
        if resolved is None:
            # Reported whatever happens next, including when a later route succeeds. A configured
            # path that was supplied and did not resolve is a STALE CONFIG -- an install that moved,
            # or a typo -- and if it were silent it would look identical to no configuration at all.
            # The operator would then see the tool found "normally" and never learn that the entry
            # they wrote is now wrong. *Principle 3, never report success over unperformed work*,
            # applied to a route that was attempted and failed rather than skipped.
            warnings.append(
                f"the configured path {configured_path} did not resolve any of "
                f"{list(spec.executables)}; falling through to the remaining routes"
            )

    if resolved is None:
        routes_tried.append("process-path")
        resolved = _resolve_process_path(spec.executables)

    if resolved is None:
        routes_tried.append("windows-registry")
        if sys.platform != "win32":
            inconclusive.append(
                "windows-registry could not be attempted: this is not Windows, so there is no "
                "registry PATH to read"
            )
        else:
            try:
                resolved = _in_directories(_read_registry_path_entries(), spec.executables)
            except OSError as exc:
                inconclusive.append(f"windows-registry could not be read: {exc}")

    if resolved is None:
        routes_tried.append("default-paths")
        resolved = _in_directories(spec.default_paths, spec.executables)

    if resolved is not None:
        version = _capture_version(resolved, spec.version_args) if spec.version_args else None
        return ToolProbe(
            name=spec.name,
            status=ToolStatus.PRESENT,
            path=resolved,
            version=version,
            routes_tried=tuple(routes_tried),
            note=_join_notes([*warnings, _note_for_resolved(spec, version)]),
        )

    if not spec.windows_native:
        inconclusive.append(
            "this tool has no native Windows executable, so a Windows path search cannot establish "
            "its absence: "
            + TOOLS_WITHOUT_DEFAULT_PATHS.get(spec.name, "see TOOLS_WITHOUT_DEFAULT_PATHS")
        )

    if inconclusive:
        return ToolProbe(
            name=spec.name,
            status=ToolStatus.TOOL_UNRESOLVED,
            path=None,
            version=None,
            routes_tried=tuple(routes_tried),
            note=_join_notes([*warnings, *inconclusive]),
        )

    return ToolProbe(
        name=spec.name,
        status=ToolStatus.TOOL_ABSENT,
        path=None,
        version=None,
        routes_tried=tuple(routes_tried),
        note=_join_notes(warnings),
    )


def detect_all(specs: Iterable[ToolSpec] = KNOWN_TOOLS) -> list[ToolProbe]:
    """One probe per spec, in the order given."""
    return [detect_tool(spec) for spec in specs]
