"""Tool detection and version capture for external solvers.

Every adapter implements detect, version, generate, run and parse. This module
implements the first two: detection through every route before concluding
absence, and version capture verbatim or not at all.
"""

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from enum import Enum
from pathlib import Path

if sys.platform == "win32":
    import winreg


class ToolStatus(Enum):
    """Status of a tool probe."""

    PRESENT = "present"  # resolved, and a version string was captured
    TOOL_UNRESOLVED = "tool-unresolved"  # not on the process path; other routes inconclusive
    TOOL_ABSENT = "tool-absent"  # every route tried, genuinely not present


class ToolProbe:
    """Result of a tool detection attempt."""

    __slots__ = ("name", "note", "path", "routes_tried", "status", "version")

    def __init__(
        self,
        name: str,
        status: ToolStatus,
        path: Path | None,
        version: str | None,
        routes_tried: tuple[str, ...],
        note: str | None = None,
    ):
        self.name = name
        self.status = status
        self.path = path
        self.version = version
        self.routes_tried = routes_tried
        self.note = note

    def __repr__(self) -> str:
        return (
            f"ToolProbe(name={self.name!r}, status={self.status.value!r}, "
            f"path={self.path!r}, version={self.version!r}, "
            f"routes_tried={self.routes_tried!r}, note={self.note!r})"
        )


class ToolSpec:
    """Specification for a tool to be detected."""

    __slots__ = ("default_paths", "executables", "manual_only", "name", "version_args")

    def __init__(
        self,
        name: str,
        executables: tuple[str, ...],
        default_paths: tuple[Path, ...],
        version_args: tuple[str, ...],
        manual_only: bool = False,
    ):
        self.name = name
        self.executables = executables
        self.default_paths = default_paths
        self.version_args = version_args
        self.manual_only = manual_only


# Known tools, ordered by the route order they are tried.
# FEMM, LTspice, QSPICE, Gmsh, Elmer, OpenFOAM, ParaView
KNOWN_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="femm",
        executables=("femm.exe",),
        default_paths=(
            Path(r"C:\Program Files\femm42"),
            Path(r"C:\Program Files (x86)\femm42"),
        ),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="ltspice",
        executables=("ltspice.exe",),
        default_paths=(
            Path(r"C:\Program Files\Analog\LTspice"),
            Path(r"C:\Program Files (x86)\Analog\LTspice"),
        ),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="qspice",
        executables=("qspice.exe",),
        default_paths=(
            Path(r"C:\Program Files\QORCA\QSPICE"),
            Path(r"C:\Program Files (x86)\QORCA\QSPICE"),
        ),
        version_args=(),
        manual_only=True,
    ),
    ToolSpec(
        name="gmsh",
        executables=("gmsh.exe",),
        default_paths=(Path(r"C:\Program Files\Gmsh\bin"),),
        version_args=("--version",),
        manual_only=False,
    ),
    ToolSpec(
        name="elmer",
        executables=("ElmerSolver.exe",),
        default_paths=(
            Path(r"C:\Program Files\Elmer 9.0\bin"),
            Path(r"C:\Program Files (x86)\Elmer 9.0\bin"),
        ),
        version_args=("--version",),
        manual_only=False,
    ),
    ToolSpec(
        name="openfoam",
        executables=("OpenFOAM.bat", "foam"),
        default_paths=(),
        version_args=(),
        manual_only=False,
    ),
    ToolSpec(
        name="paraview",
        executables=("paraview.exe",),
        default_paths=(
            Path(r"C:\Program Files\ParaView"),
            Path(r"C:\Program Files (x86)\ParaView"),
        ),
        version_args=("--version",),
        manual_only=True,
    ),
)


def _try_configured_path(
    spec: ToolSpec, configured_path: Path | None
) -> tuple[Path | None, str | None]:
    """Try an explicitly configured path."""
    if configured_path is None:
        return None, None

    # If configured_path is a directory, try each executable in it
    if configured_path.is_dir():
        for exe in spec.executables:
            candidate = configured_path / exe
            if candidate.is_file():
                return candidate, None
        return None, None

    # If configured_path is a file, check if it matches any executable
    if configured_path.is_file():
        if configured_path.name in spec.executables:
            return configured_path, None
        return None, None

    return None, None


def _try_process_path(spec: ToolSpec) -> tuple[Path | None, str | None]:
    """Try finding the tool via shutil.which."""
    for exe in spec.executables:
        full_path = shutil.which(exe)
        if full_path is not None:
            return Path(full_path), None
    return None, None


def _try_windows_registry(spec: ToolSpec) -> tuple[Path | None, str | None]:
    """Try finding the tool via Windows registry PATH scopes.

    Returns (path, note) where path is the tool executable if found, or None if not found
    or registry was unreadable. If the registry key itself is unreadable, returns (None, None)
    to signal TOOL_UNRESOLVED territory.

    On non-Windows platforms, returns (None, None) but this is recorded in routes_tried
    as "windows-registry" being attempted and skipped.
    """
    if sys.platform != "win32":
        return None, None

    # Collect paths from Machine and User registry
    all_paths: list[Path] = []

    for hive, path_base in [
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ]:
        try:
            with winreg.OpenKey(hive, path_base) as key:
                value, _ = winreg.QueryValueEx(key, "PATH")
                for p in value.split(";"):
                    if p:
                        all_paths.append(Path(p))
        except (OSError, FileNotFoundError):
            # Registry key unreadable - this is TOOL_UNRESOLVED territory
            # Return None with no note - caller will determine TOOL_UNRESOLVED
            return None, None

    # Check each path for executables
    for p in all_paths:
        for exe in spec.executables:
            candidate = p / exe
            if candidate.is_file():
                return candidate, None

    # Registry was accessible but tool not found
    return None, None


def _try_default_paths(spec: ToolSpec) -> tuple[Path | None, str | None]:
    """Try known default installation locations."""
    for p in spec.default_paths:
        if not p.exists():
            continue
        for exe in spec.executables:
            candidate = p / exe
            if candidate.is_file():
                return candidate, None
    return None, None


def _try_version(tool_path: Path, spec: ToolSpec) -> str | None:
    """Attempt to capture version string from tool."""
    if not spec.version_args:
        return None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [str(tool_path)] + list(spec.version_args),
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmpdir,
                check=False,
            )
            if result.returncode == 0:
                # Return the first non-empty line, stripped
                for line in result.stdout.splitlines():
                    stripped = line.strip()
                    if stripped:
                        return stripped
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def detect_tool(spec: ToolSpec, configured_path: Path | None = None) -> ToolProbe:
    """Detect a tool and capture its version.

    Attempts detection in this order, recording each route:
    1. configured_path (if provided)
    2. process path via shutil.which
    3. Windows registry PATH scopes (Machine and User)
    4. known default installation locations

    Returns a ToolProbe with status, path, version and routes_tried.
    """
    routes_tried: list[str] = []
    path: Path | None = None
    version: str | None = None
    note: str | None = None
    registry_accessible: bool | None = (
        None  # None = not attempted (non-Windows), True = accessible, False = unreadable
    )

    # 1. configured path
    path, _ = _try_configured_path(spec, configured_path)
    routes_tried.append("configured-path")

    # 2. process path
    if path is None:
        path, _ = _try_process_path(spec)
        routes_tried.append("process-path")
    else:
        routes_tried.append("process-path")

    # 3. Windows registry
    if path is None and sys.platform == "win32":
        registry_accessible = True  # Assume accessible until we hit an error
        path, _ = _try_windows_registry(spec)
        if path is None:
            # Try to determine if registry was unreadable
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                ):
                    pass
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment"):
                    pass
                # Both keys readable, so registry was accessible but tool not found
                registry_accessible = True
            except (OSError, FileNotFoundError):
                # Registry key unreadable
                registry_accessible = False
        routes_tried.append("windows-registry")
    elif path is None:
        # Non-Windows platform - route attempted but skipped
        registry_accessible = False  # Not applicable
        routes_tried.append("windows-registry")
    else:
        # Path already found, skip registry
        routes_tried.append("windows-registry")

    # 4. default paths
    if path is None:
        path, _ = _try_default_paths(spec)
        routes_tried.append("default-paths")
    else:
        routes_tried.append("default-paths")

    # Determine status and version
    routes_tried_tuple = tuple(routes_tried)

    if path is None:
        # All routes exhausted without finding anything
        # Check if registry was unreadable (Windows only)
        if sys.platform == "win32" and registry_accessible is False:
            # Registry key was unreadable - TOOL_UNRESOLVED territory
            status = ToolStatus.TOOL_UNRESOLVED
        else:
            status = ToolStatus.TOOL_ABSENT
        return ToolProbe(
            name=spec.name,
            status=status,
            path=None,
            version=None,
            routes_tried=routes_tried_tuple,
            note=note,
        )

    # Path resolved - now try to get version
    if spec.version_args:
        version = _try_version(path, spec)
        if version is None and not spec.manual_only:
            # Tool is present but couldn't report version and isn't manual-only
            note = "version probe failed"
    else:
        # Tool has no version args
        note = "no version args"

    return ToolProbe(
        name=spec.name,
        status=ToolStatus.PRESENT,
        path=path,
        version=version,
        routes_tried=routes_tried_tuple,
        note=note,
    )


def detect_all(specs: Iterable[ToolSpec] = KNOWN_TOOLS) -> list[ToolProbe]:
    """Detect all known tools.

    Returns a list of ToolProbe, one per spec, in the order of specs.
    """
    return [detect_tool(spec) for spec in specs]
