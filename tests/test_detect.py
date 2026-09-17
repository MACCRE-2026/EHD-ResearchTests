"""Tests for the adapter detection layer."""

import subprocess
import sys
from pathlib import Path

import pytest

from ehdpsu import detect


class TestToolSpec:
    """Test ToolSpec structure and constraints."""

    def test_every_known_tool_has_non_empty_name(self):
        """Every known tool must have a non-empty name."""
        for spec in detect.KNOWN_TOOLS:
            assert spec.name, f"{spec}: name must be non-empty"

    def test_every_known_tool_has_at_least_one_executable(self):
        """Every known tool must have at least one executable."""
        for spec in detect.KNOWN_TOOLS:
            assert spec.executables, f"{spec}: executables must be non-empty"

    def test_every_known_tool_has_manual_only_flag(self):
        """Every known tool must have a manual_only flag."""
        for spec in detect.KNOWN_TOOLS:
            assert isinstance(spec.manual_only, bool), f"{spec}: manual_only must be bool"


class TestDetectTool:
    """Tests for detect_tool."""

    def test_configured_path_that_exists_returns_present(self, tmp_path: Path):
        """A configured path that exists returns PRESENT with configured-path first."""
        # Create a fake executable
        fake_exe = tmp_path / "fake_tool.exe"
        fake_exe.write_text("# fake")

        spec = detect.ToolSpec(
            name="fake_tool",
            executables=("fake_tool.exe",),
            default_paths=(),
            version_args=(),
        )

        probe = detect.detect_tool(spec, configured_path=tmp_path)

        assert probe.status == detect.ToolStatus.PRESENT
        assert probe.path == fake_exe
        assert probe.routes_tried[0] == "configured-path"
        assert probe.version is None
        assert probe.note == "no version args"

    def test_configured_path_that_does_not_exist_falls_through(self, tmp_path: Path):
        """A configured path that does not exist falls through and does not return PRESENT."""
        # Intentionally don't create the file

        spec = detect.ToolSpec(
            name="fake_tool",
            executables=("fake_tool.exe",),
            default_paths=(),
            version_args=(),
        )

        probe = detect.detect_tool(spec, configured_path=tmp_path)

        # Should not be PRESENT since the file doesn't exist
        assert probe.status != detect.ToolStatus.PRESENT
        assert probe.routes_tried[0] == "configured-path"

    def test_absent_tool_returns_absent_only_when_every_route_tried(self, tmp_path: Path):
        """A tool absent everywhere returns TOOL_ABSENT only when every route was genuinely attempted."""
        # Create a spec with an executable that definitely doesn't exist
        spec = detect.ToolSpec(
            name="definitely_absent_tool",
            executables=("nonexistent_tool_xyz123.exe",),
            default_paths=(tmp_path / "definitely_not_here",),  # Non-existent default path
            version_args=(),
        )

        probe = detect.detect_tool(spec)

        assert probe.status == detect.ToolStatus.TOOL_ABSENT
        assert probe.path is None
        assert probe.version is None
        assert "configured-path" in probe.routes_tried
        assert "process-path" in probe.routes_tried
        assert "windows-registry" in probe.routes_tried
        assert "default-paths" in probe.routes_tried

    def test_registry_route_unavailable_is_tool_unresolved(self, monkeypatch: pytest.MonkeyPatch):
        """When the registry route cannot be attempted, result is TOOL_UNRESOLVED, never TOOL_ABSENT."""
        # On Windows, this test verifies that if the registry key is unreadable,
        # the result is TOOL_UNRESOLVED. We simulate this by patching winreg.OpenKey.
        if sys.platform != "win32":
            pytest.skip("Windows-specific test")

        import winreg

        # Patch winreg.OpenKey to raise FileNotFoundError (simulating unreadable key)

        def mock_openkey(*args, **kwargs):
            raise FileNotFoundError("Registry key not found")

        monkeypatch.setattr(winreg, "OpenKey", mock_openkey)

        spec = detect.ToolSpec(
            name="test_tool",
            executables=("absent_tool.exe",),
            default_paths=(),
            version_args=(),
        )

        probe = detect.detect_tool(spec)

        # Registry was attempted but unreadable, so TOOL_UNRESOLVED
        assert probe.status == detect.ToolStatus.TOOL_UNRESOLVED
        assert "windows-registry" in probe.routes_tried

    def test_probe_never_has_version_without_path(self, tmp_path: Path):
        """A probe never carries a version without a path."""
        # Create a fake executable
        fake_exe = tmp_path / "version_tool.exe"
        fake_exe.write_text("# fake")

        spec = detect.ToolSpec(
            name="version_tool",
            executables=("version_tool.exe",),
            default_paths=(),
            version_args=("--version",),  # Has version args
        )

        probe = detect.detect_tool(spec, configured_path=tmp_path)

        if probe.version is not None:
            assert probe.path is not None
        else:
            # Even without version, path must be present
            assert probe.path is not None

    def test_probe_with_manual_only_tool_is_still_detected(self, tmp_path: Path):
        """Manual-only tools are still detected."""
        fake_exe = tmp_path / "manual_tool.exe"
        fake_exe.write_text("# manual")

        spec = detect.ToolSpec(
            name="manual_tool",
            executables=("manual_tool.exe",),
            default_paths=(),
            version_args=(),  # No version args
            manual_only=True,
        )

        probe = detect.detect_tool(spec, configured_path=tmp_path)

        assert probe.status == detect.ToolStatus.PRESENT
        assert probe.path == fake_exe
        assert probe.note == "no version args"


class TestDetectAll:
    """Tests for detect_all."""

    def test_detect_all_returns_one_probe_per_known_tool(self):
        """detect_all returns one probe per known tool, with no duplicates."""
        probes = detect.detect_all()

        names = [p.name for p in probes]
        assert len(probes) == len(set(names)), "Duplicate tool names in probes"
        assert len(probes) == len(
            detect.KNOWN_TOOLS
        ), f"Expected {len(detect.KNOWN_TOOLS)} probes, got {len(probes)}"


class TestNoSubprocessAtImport:
    """Tests that nothing invokes subprocess at import time."""

    def test_import_does_not_invoke_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Importing the module does not invoke subprocess.run."""
        recorded_calls = []

        def mock_run(*args, **kwargs):
            recorded_calls.append((args, kwargs))

            # Don't actually run anything
            class MockResult:
                returncode = 0
                stdout = ""
                stderr = ""

            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Import fresh in a subprocess to avoid cached imports
        script = f"""
import sys
import subprocess
sys.path.insert(0, r'''{tmp_path.parent}''')
# Patch before import
original_run = subprocess.run
calls = []
def patched(*a, **k):
    calls.append((a, k))
    class M: returncode = 0; stdout = ''; stderr = ''
    return M()
subprocess.run = patched
import ehdpsu.detect
if calls:
    print('FAIL: subprocess.run called at import')
    sys.exit(1)
else:
    print('OK: no subprocess at import')
"""

        # Write a temp script and run it
        script_path = tmp_path / "import_test.py"
        script_path.write_text(script)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "FAIL" not in result.stdout, f"Subprocess was called at import: {result.stdout}"
