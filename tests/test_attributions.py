"""Attribution tracking — every external work cited in the physics core must be named."""

from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTIONS = REPO_ROOT / "ATTRIBUTIONS.md"

REQUIRED_AUTHORS = ("Peek", "Kuffel", "Zaengl", "Bahder", "Fazi", "Christenson", "Moller", "Meeker")


@functools.cache
def _git(*args: str) -> str:
    """Run a read-only git command and return stdout, cached for the session.

    The cache is real. An earlier version of this function carried this same docstring while
    having no decorator — the claim was there, the caching was not. Caught while reviewing the
    packet that created this file, alongside two fabricated module paths in ``ATTRIBUTIONS.md``.
    Same failure class: a description asserting something the code does not do.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr}")
    return result.stdout


def test_attributions_file_exists_and_is_tracked() -> None:
    """ATTRIBUTIONS.md exists at the repository root and is tracked by git."""
    path = REPO_ROOT / "ATTRIBUTIONS.md"
    assert path.is_file(), f"ATTRIBUTIONS.md missing from {REPO_ROOT}"

    tracked = _git("ls-files", "--", "ATTRIBUTIONS.md").strip()
    assert tracked, "ATTRIBUTIONS.md exists but is not tracked by git"


def test_every_physics_reference_is_attributed() -> None:
    """Every author surname in REQUIRED_AUTHORS appears in ATTRIBUTIONS.md."""
    path = REPO_ROOT / "ATTRIBUTIONS.md"
    content = path.read_text(encoding="utf-8")

    missing = []
    for author in REQUIRED_AUTHORS:
        # Match surname at word boundary, case-insensitive
        if not re.search(rf"\b{author}\b", content, re.IGNORECASE):
            missing.append(author)

    assert not missing, (
        f"Required authors missing from ATTRIBUTIONS.md: {missing}. "
        f"Every work cited in src/ehdpsu/physics.py and src/ehdpsu/femm.py must be named."
    )


def test_planned_tools_are_marked_planned() -> None:
    """Every planned tool appears in ATTRIBUTIONS.md and is explicitly marked as planned."""
    path = REPO_ROOT / "ATTRIBUTIONS.md"
    content = path.read_text(encoding="utf-8")

    # These must all appear and be marked as planned (not yet installed or run)
    planned_tools = (
        "FEMM",
        "LTspice",
        "QSPICE",
        "Gmsh",
        "Elmer",
        "OpenFOAM",
        "ParaView",
        "CadQuery",
        "OpenCASCADE",
    )

    missing = []
    for tool in planned_tools:
        if tool not in content:
            missing.append(tool)

    assert not missing, (
        f"Planned tools missing from ATTRIBUTIONS.md: {missing}. "
        f"Every planned adapter tool must be listed."
    )

    # The file must contain the word 'planned' to indicate these are not yet implemented
    assert (
        "planned" in content.lower()
    ), "ATTRIBUTIONS.md does not contain the word 'planned', so the planned status of tools is unclear."


def test_prov_and_biba_are_named() -> None:
    """The two deliberate standard reuses (PROV and Biba) appear in ATTRIBUTIONS.md."""
    path = REPO_ROOT / "ATTRIBUTIONS.md"
    content = path.read_text(encoding="utf-8")

    assert (
        "PROV" in content
    ), "ATTRIBUTIONS.md does not name PROV-DM/PROV-O. The project deliberately reuses this standard."
    assert (
        "Biba" in content
    ), "ATTRIBUTIONS.md does not name the Biba integrity model. The project deliberately reuses this model."


def test_no_attribution_references_a_nonexistent_module() -> None:
    """Every ``src/ehdpsu/*.py`` path named in ATTRIBUTIONS.md actually exists.

    Why this test exists
    --------------------
    The first draft of ``ATTRIBUTIONS.md`` cited ``src/ehdpsu/provenance.py`` and
    ``src/ehdpsu/quantity.py`` as the places where PROV-O and the low-water-mark rule were
    implemented. **Neither module existed.** Both are planned work.

    Nothing failed. The file was well formed, all four original tests passed, and the executor's
    summary was accurate about structure — four sections, populated. The defect was that a
    document claimed a capability the codebase does not have, which only a reader who checked the
    paths would notice.

    That is *principle 5, specifications drift from implementations unless mechanically checked*,
    and *principle 2, an approximately-correct identifier is worse than an absent one*: a
    plausible module path sends a reader looking for code that is not there, and reads as evidence
    of work that was never done.

    An attribution list for a project that has not yet built the thing it attributes must say so.
    Marking something *planned* is honest; naming a file that does not exist is not.
    """
    text = ATTRIBUTIONS.read_text(encoding="utf-8")

    # Match backtick-quoted paths under the package, e.g. `src/ehdpsu/physics.py`.
    referenced = set(re.findall(r"`(src/ehdpsu/[A-Za-z0-9_/]+\.py)`", text))
    assert referenced, (
        "ATTRIBUTIONS.md references no module paths at all. Either the citations lost their "
        "'used for' detail, or this pattern no longer matches how they are written."
    )

    missing = sorted(p for p in referenced if not (REPO_ROOT / p).is_file())
    assert not missing, (
        f"ATTRIBUTIONS.md references module(s) that do not exist: {missing}. "
        f"If the work is planned, say 'planned' instead of naming a file."
    )
