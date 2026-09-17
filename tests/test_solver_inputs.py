"""The tracked solver inputs must equal what the code currently generates.

Why this file exists
--------------------
``adapter-contract.md`` states that generated inputs are tracked and "diffed by a test so they
cannot drift silently". **That claim was false until 2026-09-15.** The only check on
``solver_inputs/`` asserted the files existed and were tracked; nothing compared their contents to
a regeneration.

It was found the way these things usually are — by accident. Task 7 changed the Cockcroft-Walton
capacitor in ``spice.py`` from the literal ``"1n"`` to a value derived from the profile, which
altered eleven lines of ``ehd_llc_cw.cir``. Nothing failed. The change was only noticed because it
was explicitly regenerated and diffed by hand.

*Principle 5, specifications drift from implementations unless mechanically checked* — and the
specification here was a steering file asserting a test existed.

What a failure means
--------------------
Not necessarily a defect. A deliberate change to a generated input is legitimate; what is not
legitimate is that change reaching the tracked file without anybody seeing it, or the tracked file
going stale while the generator moves on. So the failure message says to regenerate and review the
diff, rather than implying something is broken.

Why byte-for-byte here, when ``examples/`` is compared numerically
------------------------------------------------------------------
``examples/*.csv`` holds floats whose last digit can move with a numpy patch release, so those are
compared with a tolerance. Solver inputs are deterministic text assembled by this repository's own
code from a profile — no third-party formatting is involved, so any byte difference is a real
change in what the solver would be asked to do.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ehdpsu import femm, spice

REPO_ROOT = Path(__file__).resolve().parents[1]
SOLVER_INPUTS = REPO_ROOT / "solver_inputs"

#: Files each adapter is responsible for generating.
SPICE_FILES = ("ehd_llc_cw.cir", "ehd_llc_cw.asc")
FEMM_FILES = ("ehd_wire_collector.lua", "ehd_wire_collector_geometry.txt")


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Regenerate every solver input into a scratch directory.

    Written to a temporary directory rather than over the tracked files: a test that regenerates
    in place would make the comparison vacuous, since it would be diffing a file against itself.
    """
    out = tmp_path_factory.mktemp("solver_inputs")
    spice.write_artifacts(output_dir=out)
    femm.write_artifacts(output_dir=out)
    return out


@pytest.mark.parametrize("name", [*SPICE_FILES, *FEMM_FILES])
def test_tracked_solver_input_matches_regeneration(regenerated: Path, name: str) -> None:
    tracked = SOLVER_INPUTS / name
    fresh = regenerated / name

    assert tracked.is_file(), (
        f"solver_inputs/{name} is missing. Regenerate with `python -m ehdpsu.spice` and "
        f"`python -m ehdpsu.femm`."
    )
    assert fresh.is_file(), (
        f"the adapter did not generate {name}. Either the filename changed without this test "
        f"being updated, or the adapter stopped producing it."
    )

    tracked_text = tracked.read_text(encoding="utf-8")
    fresh_text = fresh.read_text(encoding="utf-8")

    if tracked_text != fresh_text:
        tracked_lines = tracked_text.splitlines()
        fresh_lines = fresh_text.splitlines()
        differing = [
            f"    line {i + 1}:\n      tracked: {t!r}\n      current: {f!r}"
            for i, (t, f) in enumerate(zip(tracked_lines, fresh_lines, strict=False))
            if t != f
        ]
        if len(tracked_lines) != len(fresh_lines):
            differing.append(
                f"    line count: tracked {len(tracked_lines)}, current {len(fresh_lines)}"
            )
        pytest.fail(
            f"solver_inputs/{name} does not match what the code generates now, in "
            f"{len(differing)} place(s). This is not necessarily a defect: if the change is "
            f"intended, regenerate the file, review the diff, and stage it by name. If it is not "
            f"intended, something moved a design value or a formatter.\n"
            + "\n".join(differing[:10])
        )


@pytest.mark.parametrize("name", [*SPICE_FILES, *FEMM_FILES])
def test_solver_input_is_tracked(name: str) -> None:
    """A generated input nobody can clone is of no use to a cloner.

    Kept here beside the content check so the two live together: existence, tracking and content
    are three separate claims and only one of them was previously tested.
    """
    out = subprocess.run(
        ["git", "ls-files", "--", f"solver_inputs/{name}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        pytest.skip("git unavailable; cannot confirm tracking")
    assert out.stdout.strip(), f"solver_inputs/{name} is not tracked"


def test_every_tracked_solver_input_is_covered_by_this_module() -> None:
    """No file may sit in ``solver_inputs/`` without a regeneration check.

    Otherwise an adapter could add an output that nothing compares, which is how the gap this
    module closes came to exist in the first place.
    """
    on_disk = {p.name for p in SOLVER_INPUTS.iterdir() if p.is_file()}
    covered = {*SPICE_FILES, *FEMM_FILES}
    uncovered = sorted(on_disk - covered)
    assert not uncovered, (
        f"these files are in solver_inputs/ but no regeneration check covers them: {uncovered}. "
        f"Add them to SPICE_FILES or FEMM_FILES, or explain why they are not generated."
    )


def test_regeneration_is_deterministic(regenerated: Path, tmp_path: Path) -> None:
    """Two runs of the generators produce identical bytes.

    If they did not, the comparison above would be a coin flip and would eventually be dismissed
    as flaky. A timestamp or a dict-ordering dependence in an adapter would show up here.
    """
    spice.write_artifacts(output_dir=tmp_path)
    femm.write_artifacts(output_dir=tmp_path)
    for name in (*SPICE_FILES, *FEMM_FILES):
        assert (tmp_path / name).read_text(encoding="utf-8") == (regenerated / name).read_text(
            encoding="utf-8"
        ), f"{name} is not byte-reproducible across two generator runs"
