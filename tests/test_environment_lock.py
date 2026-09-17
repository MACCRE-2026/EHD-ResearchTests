"""Tests that keep ``requirements.lock`` and ``bootstrap.ps1`` honest.

A lockfile nobody checks is a document that drifts away from the thing it claims to describe, and
the drift is silent because everything keeps working on the machine that generated it.
*Principle 5, specifications drift from implementations unless mechanically checked.*

The load-bearing test here is :func:`test_installed_environment_matches_the_lock`. Everything else
checks the file's shape; that one checks the claim.

A note on what a version lock does not do
-----------------------------------------
It pins versions, not artifact hashes, so it does not defend against a re-uploaded PyPI artifact
at an already-released version. That needs ``pip install --require-hashes`` and a hash-bearing
lock, which ``pip freeze`` cannot produce. Asserted nowhere below, because the file does not claim
it — and stated here because a name ending in ``.lock`` invites the stronger reading.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK = REPO_ROOT / "requirements.lock"
BOOTSTRAP = REPO_ROOT / "bootstrap.ps1"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Deliberately absent from the lock. See the lockfile header for the reasoning on each.
LOCK_EXCLUSIONS = ("ehdpsu", "pip")

# The tools the Gate's verdict is a function of. An unpinned linter or type checker means the Gate
# can change its answer without the code changing, which destroys it as a regression signal.
GATE_TOOLING = ("ruff", "black", "mypy", "pyright", "pytest")


def _lock_pins() -> list[str]:
    """Return the lock's pin lines, comments and blanks stripped."""
    return [
        line.strip()
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _package_name(pin: str) -> str:
    """Return the lowercased distribution name from a ``name==version`` pin."""
    return pin.split("==")[0].strip().lower()


def _installed_pins() -> list[str]:
    """Return the current environment's pins, filtered the same way the lock is generated.

    Uses ``sys.executable`` rather than a hardcoded ``.venv\\Scripts\\python.exe`` so the check
    works on a clone that put its environment somewhere else, or on a non-Windows clone.
    """
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        pytest.skip(f"pip freeze failed (exit {out.returncode}); cannot compare against the lock")
    pins = []
    for line in out.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-e "):
            continue
        if _package_name(stripped) in LOCK_EXCLUSIONS:
            continue
        pins.append(stripped)
    return pins


class TestLockShape:
    """The file's format, which the regeneration procedure and the drift test both depend on."""

    def test_lock_exists_and_is_tracked(self) -> None:
        assert LOCK.is_file(), "requirements.lock is missing"
        out = subprocess.run(
            ["git", "ls-files", "--", "requirements.lock"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            pytest.skip("git unavailable; cannot confirm the lock is tracked")
        # `git ls-files` is the authoritative tracked check, not `git status`.
        assert out.stdout.strip(), (
            "requirements.lock is not tracked by git. An untracked lock does not exist in a "
            "clone, so the bootstrap it describes cannot run there."
        )

    def test_every_line_is_an_exact_pin(self) -> None:
        # A range specifier in a lockfile defeats its only purpose. `>=` would resolve to whatever
        # is newest at install time, which is precisely the non-determinism being removed.
        for pin in _lock_pins():
            assert re.fullmatch(r"[A-Za-z0-9._-]+==[A-Za-z0-9._!+-]+", pin), (
                f"{pin!r} is not an exact `name==version` pin. Ranges, extras, URLs and editable "
                f"installs all make the lock non-deterministic."
            )

    def test_no_duplicate_packages(self) -> None:
        names = [_package_name(p) for p in _lock_pins()]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert not duplicates, f"the lock pins these packages more than once: {duplicates}"

    def test_pins_are_sorted_by_lowercased_package_name(self) -> None:
        # The sort rule is part of the format. PowerShell's culture-aware `Sort-Object` ordered
        # `mypy_extensions` before `mypy`, which would regenerate differently under another
        # culture and produce diff noise indistinguishable from a dependency change.
        pins = _lock_pins()
        assert pins == sorted(pins, key=_package_name), (
            "the lock is not sorted by lowercased package name. Regenerate it with the procedure "
            "in the file header so the ordering is reproducible."
        )

    @pytest.mark.parametrize("excluded", LOCK_EXCLUSIONS)
    def test_deliberate_exclusions_are_absent(self, excluded: str) -> None:
        assert excluded not in {_package_name(p) for p in _lock_pins()}, (
            f"{excluded!r} is pinned in the lock. It is excluded deliberately: see the lockfile "
            f"header. Pinning the project itself makes the bootstrap clone the repository it is "
            f"already inside, and pinning pip makes pip change its own version mid-install."
        )

    def test_the_exclusions_are_explained_in_the_file(self) -> None:
        # An unexplained omission reads as an oversight, and the next person re-adds it.
        header = LOCK.read_text(encoding="utf-8")
        for excluded in LOCK_EXCLUSIONS:
            assert excluded in header, (
                f"the lockfile header does not mention why {excluded!r} is excluded, so the "
                f"omission looks accidental."
            )


class TestLockCoverage:
    """The lock has to cover everything the project and the Gate actually depend on."""

    @pytest.mark.parametrize("tool", GATE_TOOLING)
    def test_gate_tooling_is_pinned(self, tool: str) -> None:
        assert tool in {_package_name(p) for p in _lock_pins()}, (
            f"{tool} is not pinned. The Gate's verdict depends on it, so an unpinned version "
            f"means the Gate can change its answer without the code changing."
        )

    def test_every_declared_runtime_dependency_is_pinned(self) -> None:
        """``pyproject.toml``'s dependency list and the lock must not disagree.

        The lock is generated from an installed environment, so a dependency added to
        ``pyproject.toml`` but never installed would be missing here and nothing else would say
        so.
        """
        declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
        names = {re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0].strip().lower() for d in declared}
        pinned = {_package_name(p) for p in _lock_pins()}
        missing = sorted(names - pinned)
        assert not missing, (
            f"declared in pyproject.toml but absent from requirements.lock: {missing}. Install "
            f"them and regenerate the lock."
        )

    def test_installed_environment_matches_the_lock(self) -> None:
        """The claim, as opposed to the file's shape.

        Checked in both directions. A missing package means the environment is behind the lock; an
        extra one means somebody installed something without recording it, and the next clone
        will not have it. Both are drift, and only one of them would ever surface as an
        ``ImportError``.
        """
        locked = set(_lock_pins())
        installed = set(_installed_pins())

        missing = sorted(locked - installed)
        extra = sorted(installed - locked)

        assert not missing and not extra, (
            "requirements.lock and the installed environment disagree.\n"
            f"  locked but not installed: {missing}\n"
            f"  installed but not locked: {extra}\n"
            "Either run bootstrap.ps1 -Recreate, or regenerate the lock if the change is "
            "intended."
        )


class TestMinimumPythonHasOneRepresentation:
    """3.12 is stated in three files, and they must agree.

    ``pyproject.toml``'s ``requires-python``, its ``[tool.mypy] python_version``, and
    ``bootstrap.ps1``'s interpreter floor. *Principle 4, two representations of one thing will
    drift* — and this particular drift already caused a real incident: ``python_version`` sat at
    3.11 while numpy's stubs needed 3.12, so mypy aborted having checked **zero** files and four
    consecutive task reports described that as a minor caveat.
    """

    @staticmethod
    def _pyproject() -> dict:
        return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    def test_requires_python_matches_mypy_target(self) -> None:
        data = self._pyproject()
        requires = data["project"]["requires-python"]
        mypy_target = data["tool"]["mypy"]["python_version"]
        floor = requires.lstrip(">=~^ ").strip()
        assert floor == mypy_target, (
            f"pyproject requires-python is {requires!r} (floor {floor}) but [tool.mypy] "
            f"python_version is {mypy_target!r}. A mypy target below the real floor cannot parse "
            f"the pinned numpy's stubs and aborts having examined nothing."
        )

    def test_bootstrap_floor_matches_pyproject(self) -> None:
        floor = self._pyproject()["project"]["requires-python"].lstrip(">=~^ ").strip()
        major, minor = floor.split(".")[:2]
        text = BOOTSTRAP.read_text(encoding="utf-8")

        major_match = re.search(r"\$minMajor\s*=\s*(\d+)", text)
        minor_match = re.search(r"\$minMinor\s*=\s*(\d+)", text)
        assert major_match and minor_match, "bootstrap.ps1 does not declare $minMajor/$minMinor"
        assert (major_match.group(1), minor_match.group(1)) == (major, minor), (
            f"bootstrap.ps1 accepts Python "
            f"{major_match.group(1)}.{minor_match.group(1)} but pyproject requires {floor}. The "
            f"bootstrap would build an environment the project does not support."
        )

    def test_the_running_interpreter_satisfies_the_floor(self) -> None:
        floor = self._pyproject()["project"]["requires-python"].lstrip(">=~^ ").strip()
        major, minor = (int(part) for part in floor.split(".")[:2])
        assert sys.version_info[:2] >= (major, minor), (
            f"this suite is running on Python {sys.version_info.major}."
            f"{sys.version_info.minor}, below the declared floor of {floor}."
        )


class TestBootstrap:
    """``bootstrap.ps1`` is the one command the README promises, so its promises need checking."""

    def test_bootstrap_exists_and_is_tracked(self) -> None:
        assert BOOTSTRAP.is_file(), "bootstrap.ps1 is missing"
        out = subprocess.run(
            ["git", "ls-files", "--", "bootstrap.ps1"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            pytest.skip("git unavailable; cannot confirm the bootstrap is tracked")
        assert out.stdout.strip(), "bootstrap.ps1 is not tracked, so a clone would not have it"

    def test_bootstrap_installs_from_the_lock(self) -> None:
        text = BOOTSTRAP.read_text(encoding="utf-8")
        assert "requirements.lock" in text, "bootstrap.ps1 does not reference requirements.lock"
        assert "--no-deps" in text, (
            "bootstrap.ps1 installs the project without --no-deps, so pip re-resolves numpy, "
            "scipy and pandas and may pull versions the lock does not name -- defeating the lock "
            "while appearing to succeed."
        )

    def test_bootstrap_verifies_rather_than_assumes(self) -> None:
        """It must not report success over unperformed work.

        *Principle 3.* Three specific things: a distinct status for a partially-installed
        environment, a distinct status for lock drift, and an actual reproduction run before the
        OK. An installer that exits zero because pip exited zero has verified nothing.
        """
        text = BOOTSTRAP.read_text(encoding="utf-8")
        for status in ("LOCK-INSTALL-FAILED", "LOCK-DRIFT", "VERIFY-FAILED"):
            assert status in text, (
                f"bootstrap.ps1 has no distinct {status} status, so that outcome would be folded "
                f"into another one."
            )
        assert "test_mk0_reproduction.py" in text, (
            "bootstrap.ps1 never runs the reproduction test, so its OK means 'pip exited zero' "
            "rather than 'the physics reproduces here'."
        )

    def test_bootstrap_does_not_vendor_or_commit_anything(self) -> None:
        # The venv is deliberately not vendored, and no setup script stages or commits on the
        # operator's behalf.
        text = BOOTSTRAP.read_text(encoding="utf-8")
        for forbidden in ("git add", "git commit", "git push"):
            assert forbidden not in text, f"bootstrap.ps1 runs `{forbidden}`"

    def test_readme_documents_the_bootstrap(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "bootstrap.ps1" in readme, (
            "README.md does not mention bootstrap.ps1, so the one command a new clone needs is "
            "undiscoverable."
        )
        assert "requirements.lock" in readme, "README.md does not mention requirements.lock"

    def test_readme_package_count_matches_the_lock(self) -> None:
        """The README states how many packages the lock pins, so the figure needs checking.

        Every number in a document is generated, never typed — and this one was typed. Rather
        than removing it, which would make the README vaguer, it gets the check that
        *principle 5, specifications drift from implementations unless mechanically checked*,
        asks for.
        """
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        match = re.search(r"Exact versions of all (\d+) packages", readme)
        assert match, (
            "README.md no longer states the pinned package count in the expected form "
            "('Exact versions of all N packages'). Either restore it or drop this test with a "
            "reason."
        )
        assert int(match.group(1)) == len(_lock_pins()), (
            f"README.md claims the lock pins {match.group(1)} packages; it pins "
            f"{len(_lock_pins())}."
        )
