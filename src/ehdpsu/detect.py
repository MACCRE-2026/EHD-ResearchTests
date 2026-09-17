"""Adapter detection layer.

This module locates external tools used by the suite: FEMM, LTspice, QSPICE,
Gmsh, Elmer, OpenFOAM, and ParaView. It returns a ToolProbe describing whether
each tool was found, where, and what version it reports.

The detection layer is designed around three principles:

1. Never claim an absence it has not earned. A tool may be TOOL_ABSENT only
   when every route in ROUTE_ORDER was attempted and each reached a conclusion.
   If any route could not conclude, the answer is TOOL_UNRESOLVED.

2. Records are immutable. ToolProbe and ToolSpec are frozen dataclasses so a
   probe is a record of what was observed, not something that can be edited
   after the fact.

3. No side effects at import time. Importing this module must not execute any
   subprocess or write anything to disk. Detection happens only when the
   caller explicitly asks.

Five things were wrong with the first attempt and are now mechanically checked
by test_detect.py:

1. ROUTE_ORDER must be a published constant, not buried in control flow.
2. ToolProbe and ToolSpec must be frozen dataclasses.
3. routes_tried must record only routes that were actually attempted, in order,
   and stop at the first route that resolves.
4. TOOL_ABSENT requires every route to have been attempted and reached a
   conclusion; off Windows this is unreachable because the registry route
   cannot be attempted to a conclusion.
5. version_args must be () for GUI-driven tools (manual_only=True).

"""

from __future__ import annotations

import enum
import os
import stat
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    import winreg

__all__ = (
    "KNOWN_TOOLS",
    "ROUTE_ORDER",
    "ToolProbe",
    "ToolSpec",
    "ToolStatus",
    "detect_all",
    "detect_tool",
)

ROUTE_ORDER = (
    "configured-path",
    "process-path",
    "windows-registry",
    "default-paths",
)


class ToolStatus(str, enum.Enum):
    """Status of a tool probe.

    PRESENT means the tool was found and is available.
    TOOL_UNRESOLVED means the tool could not be located but absence has not
        been established (for example, off Windows the registry route cannot
        conclude).
    TOOL_ABSENT means every route in ROUTE_ORDER was attempted and none
        resolved.

    """

    PRESENT = "present"
    TOOL_UNRESOLVED = "tool-unresolved"
    TOOL_ABSENT = "tool-absent"


def _is_frozen_dataclass(cls: type) -> bool:
    """True when cls is a dataclass declared frozen=True.

    Read through getattr because __dataclass_params__ is undocumented as far as
    the type checkers are concerned.

    """
    if not hasattr(cls, "__dataclass_params__"):
        return False
    params = getattr(cls, "__dataclass_params__", None)
    return bool(getattr(params, "frozen", False))


def _read_registry_path_entries() -> list[Path]:
    """Return all PATH entries from Machine and User registry scopes.

    Reads HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment
    and HKEY_CURRENT_USER\\Environment.

    Returns a list of Path objects for each PATH segment that exists.

    Raises OSError if the registry cannot be read.

    """
    paths: list[Path] = []

    for hive, key_path in [
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ]:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "PATH")
                for segment in value.split(os.pathsep):
                    if segment.strip():
                        paths.append(Path(segment.strip()))
        except FileNotFoundError:
            # The key or PATH value does not exist in this scope.
            continue
        except OSError:
            # Other registry errors are propagated.
            raise

    return paths


def _find_exe_in_path(env_path: str, executables: tuple[str, ...]) -> Path | None:
    """Return the first executable found in the PATH directories.

    env_path is a PATH-style string (directories separated by os.pathsep).
    executables is a tuple of candidate filenames.

    Returns the full path to the first executable found, or None if none found.

    """
    for directory_str in env_path.split(os.pathsep):
        directory = Path(directory_str.strip())
        if not directory.is_dir():
            continue
        for exe_name in executables:
            candidate = directory / exe_name
            if _is_executable(candidate):
                return candidate
    return None


def _is_executable(path: Path) -> bool:
    """True when path exists and has execute permission for the current user."""
    if not path.exists():
        return False
    try:
        mode = path.stat().st_mode
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        return False


def _probe_version(exe: Path, version_args: tuple[str, ...]) -> str | None:
    """Run the executable with version_args and return the first line of output.

    Returns the verbatim output (leading/trailing whitespace stripped), or None
    if the probe fails or produces no output.

    """
    if not version_args:
        return None

    try:
        result = subprocess.run(
            [str(exe), *version_args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass

    return None


def detect_tool(spec: ToolSpec, configured_path: Path | None = None) -> ToolProbe:
    """Locate a tool according to the routes in ROUTE_ORDER.

    Args:
        spec: ToolSpec describing the tool to locate.
        configured_path: An optional path the caller believes contains the tool.
            May be a directory or a direct path to the executable.

    Returns:
        ToolProbe describing the result.

    """
    routes_tried: list[str] = []
    path: Path | None = None
    version: str | None = None
    note: str | None = None

    # Route 1: configured path (always attempted, even when None)
    routes_tried.append("configured-path")
    if configured_path is not None:
        resolved = _try_configured_path(configured_path, spec.executables)
        if resolved is not None:
            path = resolved
            if spec.version_args:
                version = _probe_version(path, spec.version_args)
                if version is None:
                    note = "version probe failed or produced no output"
            if version is None and not spec.version_args:
                note = "no version_args provided"
            if version is None and spec.version_args and spec.manual_only:
                note = "version probe skipped for manual_only tool"
            return ToolProbe(
                name=spec.name,
                status=ToolStatus.PRESENT,
                path=path,
                version=version,
                routes_tried=tuple(routes_tried),
                note=note,
            )
    # configured_path was None or didn't resolve; fall through

    # Route 2: process PATH
    routes_tried.append("process-path")
    env_path = os.environ.get("PATH", "")
    resolved = _find_exe_in_path(env_path, spec.executables)
    if resolved is not None:
        path = resolved
        if spec.version_args:
            version = _probe_version(path, spec.version_args)
            if version is None:
                note = "version probe failed or produced no output"
        if version is None and not spec.version_args:
            note = "no version_args provided"
        if version is None and spec.version_args and spec.manual_only:
            note = "version probe skipped for manual_only tool"
        return ToolProbe(
            name=spec.name,
            status=ToolStatus.PRESENT,
            path=path,
            version=version,
            routes_tried=tuple(routes_tried),
            note=note,
        )

    # Route 3: Windows registry PATH entries (Windows only)
    if sys.platform == "win32":
        routes_tried.append("windows-registry")
        try:
            registry_paths = _read_registry_path_entries()
            for reg_path in registry_paths:
                for exe_name in spec.executables:
                    candidate = reg_path / exe_name
                    if _is_executable(candidate):
                        path = candidate
                        if spec.version_args:
                            version = _probe_version(path, spec.version_args)
                            if version is None:
                                note = "version probe failed or produced no output"
                        if version is None and not spec.version_args:
                            note = "no version_args provided"
                        if version is None and spec.version_args and spec.manual_only:
                            note = "version probe skipped for manual_only tool"
                        return ToolProbe(
                            name=spec.name,
                            status=ToolStatus.PRESENT,
                            path=path,
                            version=version,
                            routes_tried=tuple(routes_tried),
                            note=note,
                        )
        except OSError:
            # Registry unreadable; this route did not conclude.
            note = "registry unreadable"
            # Off Windows, TOOL_ABSENT is unreachable because windows-registry cannot
            # conclude there. On Windows, if the registry is unreadable, absence
            # has not been established.
            return ToolProbe(
                name=spec.name,
                status=ToolStatus.TOOL_UNRESOLVED,
                path=None,
                version=None,
                routes_tried=tuple(routes_tried),
                note=note,
            )
    else:
        # Non-Windows: record the route as attempted but it cannot conclude
        routes_tried.append("windows-registry")

    # Route 4: default paths
    routes_tried.append("default-paths")
    for default_path in spec.default_paths:
        for exe_name in spec.executables:
            candidate = default_path / exe_name
            if _is_executable(candidate):
                path = candidate
                if spec.version_args:
                    version = _probe_version(path, spec.version_args)
                    if version is None:
                        note = "version probe failed or produced no output"
                if version is None and not spec.version_args:
                    note = "no version_args provided"
                if version is None and spec.version_args and spec.manual_only:
                    note = "version probe skipped for manual_only tool"
                return ToolProbe(
                    name=spec.name,
                    status=ToolStatus.PRESENT,
                    path=path,
                    version=version,
                    routes_tried=tuple(routes_tried),
                    note=note,
                )

    # All routes exhausted without resolution.
    if sys.platform == "win32":
        # Every route was attempted and none resolved.
        return ToolProbe(
            name=spec.name,
            status=ToolStatus.TOOL_ABSENT,
            path=None,
            version=None,
            routes_tried=tuple(routes_tried),
            note=None,
        )
    else:
        # Off Windows, the windows-registry route was attempted but could
        # not be completed, so absence has not been established.
        # routes_tried already includes windows-registry from above
        return ToolProbe(
            name=spec.name,
            status=ToolStatus.TOOL_UNRESOLVED,
            path=None,
            version=None,
            routes_tried=tuple(routes_tried),
            note="Windows registry route cannot be attempted on this platform",
        )


def _try_configured_path(configured: Path, executables: tuple[str, ...]) -> Path | None:
    """Try to resolve an executable from a configured path.

    configured may be a directory containing the executable, or a direct path
    to the executable.

    Returns the full path to the executable if found, else None.

    """
    if configured.is_file():
        # Direct path to the executable
        if _is_executable(configured):
            return configured
        return None

    if configured.is_dir():
        # Directory - look for one of the executables
        for exe_name in executables:
            candidate = configured / exe_name
            if _is_executable(candidate):
                return candidate
        return None

    # Doesn't exist or is neither file nor directory
    return None


def detect_all(specs: Iterable[ToolSpec] | None = None) -> list[ToolProbe]:
    """Locate all known tools.

    Args:
        specs: An optional iterable of ToolSpecs to probe. Defaults to KNOWN_TOOLS.

    Returns:
        A list of ToolProbes, one per spec, in the order of specs.

    """
    if specs is None:
        specs = KNOWN_TOOLS
    return [detect_tool(spec) for spec in specs]


@dataclass(frozen=True)
class ToolSpec:
    """Specification for locating a tool.

    name: Human-readable identifier for the tool.
    executables: Tuple of candidate filenames to look for.
    default_paths: Tuple of directories to search as a last resort.
    version_args: Command line arguments to ask for a version. () if none.
    manual_only: True if this tool is GUI-driven and should not be version-probed.

    """

    name: str
    executables: tuple[str, ...]
    default_paths: tuple[Path, ...]
    version_args: tuple[str, ...]
    manual_only: bool = False


@dataclass(frozen=True)
class ToolProbe:
    """Result of locating a tool.

    name: The tool's name from its spec.
    status: One of PRESENT, TOOL_UNRESOLVED, TOOL_ABSENT.
    path: The full path to the executable if found, else None.
    version: The verbatim version string if queried successfully, else None.
    routes_tried: The routes that were attempted, in order.
    note: Optional explanatory text for inconclusive or missing results.

    """

    name: str
    status: ToolStatus
    path: Path | None
    version: str | None
    routes_tried: tuple[str, ...]
    note: str | None = None


# Known tools the suite orchestrates.
# Manual-only tools (GUIs) must have version_args=() to avoid launching them.
KNOWN_TOOLS = (
    ToolSpec(
        name="femm",
        executables=("femm.exe",),
        default_paths=(),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="ltspice",
        executables=("Ltspice.exe", "ASCA.exe"),
        default_paths=(),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="qspice",
        executables=("Qspice.exe",),
        default_paths=(),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="gmsh",
        executables=("gmsh.exe", "gmsh"),
        default_paths=(),
        version_args=("--version",),
        manual_only=False,
    ),
    ToolSpec(
        name="elmer",
        executables=("ElmerMesh.exe", "ElmerGrid.exe"),
        default_paths=(),
        version_args=(),
        manual_only=False,
    ),
    ToolSpec(
        name="openfoam",
        executables=("OpenFOAM.exe",),
        default_paths=(),
        version_args=(),
        manual_only=False,
    ),
    ToolSpec(
        name="paraview",
        executables=("paraview.exe",),
        default_paths=(),
        version_args=(),
        manual_only=True,
    ),
)
