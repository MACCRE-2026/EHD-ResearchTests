"""Reference-output regression tests against ``examples/``.

``examples/README.md`` tells a reader that this file exists and that it "fails if the numbers
move". That promise is itself a claim about behaviour, so it needs a test that fails when it
goes false — *principle 5, specifications drift from implementations unless mechanically
checked*.

Why the comparison is numeric rather than byte-for-byte
------------------------------------------------------
Float formatting in a CSV can differ in its last digit across numpy and pandas versions
without any physics changing. A byte diff would therefore go red for a dependency bump, and a
red test that means "a library patch release shipped" trains people to ignore it. So the
comparison is on parsed values with an explicit relative tolerance.

The tolerance is deliberately tight (1e-9 relative). It is there to absorb float
representation, not to absorb physics. A real change to a coefficient, a formula or a default
moves these numbers by far more and will fail loudly.

What this module does NOT cover
-------------------------------
Plots. Matplotlib PNG output is not byte-reproducible across versions, fonts and platform
rasterisation, so the plots are generated into the untracked datacenter and are not compared.
The CSVs hold the numbers, which is the part worth pinning.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from conftest import reference_design

from ehdpsu import sweeps, telemetry

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
TELEMETRY_INPUT = REPO_ROOT / "tests" / "data" / "example_telemetry.csv"

# Relative tolerance for float comparison. Absorbs last-digit representation only.
RTOL = 1e-9

# Reference CSV name -> the sweep function that regenerates it.
#
# sweep_stages is deliberately absent: its V_out_noload_ref_kV column is wrong by a factor of
# ten, so the reference file is withheld from examples/ rather than published defective. See
# examples/README.md. It returns here once the column is corrected.
SWEEP_CASES = {
    "sweep_voltage.csv": sweeps.sweep_voltage,
    "sweep_wire_radius.csv": sweeps.sweep_wire_radius,
    "sweep_gap.csv": sweeps.sweep_gap,
    "sweep_frequency.csv": sweeps.sweep_frequency,
    "sweep_capacitance.csv": sweeps.sweep_capacitance,
}


def _assert_frames_match(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    """Compare two frames column-by-column, reporting the first real disagreement."""
    assert list(actual.columns) == list(expected.columns), (
        f"{label}: column set changed.\n"
        f"  reference: {list(expected.columns)}\n"
        f"  regenerated: {list(actual.columns)}"
    )
    assert len(actual) == len(expected), (
        f"{label}: row count changed — reference {len(expected)}, regenerated {len(actual)}. "
        f"A sweep range or step count moved."
    )

    for column in expected.columns:
        exp = expected[column]
        act = actual[column]
        if pd.api.types.is_numeric_dtype(exp) and pd.api.types.is_numeric_dtype(act):
            mismatched = ~pd.Series(
                [
                    abs(a - e) <= RTOL * max(abs(e), 1e-300)
                    for a, e in zip(act.to_numpy(), exp.to_numpy(), strict=True)
                ]
            )
            if mismatched.any():
                # The Series is built from a list, so its index is a RangeIndex and `idxmax`
                # returns an int position. `idxmax` is *typed* as returning `Hashable` though,
                # because a Series can carry any index type — so the int() call pyright objected
                # to was reading a genuine gap between what the type allows and what this code
                # relies on. Use the positional argmax instead, which is typed as an int.
                first = int(mismatched.to_numpy().argmax())
                pytest.fail(
                    f"{label}: column {column!r} disagrees with the reference at row {first} — "
                    f"reference {exp.iloc[first]!r}, regenerated {act.iloc[first]!r} "
                    f"(rtol={RTOL}). This is a physics or default change, not float noise."
                )
        else:
            assert exp.equals(act), f"{label}: non-numeric column {column!r} changed"


@pytest.mark.parametrize("csv_name", sorted(SWEEP_CASES))
def test_sweep_matches_reference(csv_name: str, tmp_path: Path) -> None:
    """Regenerating a sweep reproduces the committed MK0 reference numbers."""
    reference_path = EXAMPLES / csv_name
    assert (
        reference_path.is_file()
    ), f"reference {csv_name} missing from examples/. examples/README.md lists it as present."

    expected = pd.read_csv(reference_path)
    regenerated = SWEEP_CASES[csv_name](reference_design())

    # Round-trip through CSV so the comparison sees exactly what a user would diff.
    scratch = tmp_path / csv_name
    regenerated.to_csv(scratch, index=False)
    actual = pd.read_csv(scratch)

    _assert_frames_match(actual, expected, csv_name)


def test_telemetry_matches_reference(tmp_path: Path) -> None:
    """Reducing the example telemetry log reproduces the committed derived CSV."""
    reference_path = EXAMPLES / "example_telemetry_derived.csv"
    assert reference_path.is_file(), "examples/example_telemetry_derived.csv missing"
    assert TELEMETRY_INPUT.is_file(), f"telemetry input missing: {TELEMETRY_INPUT}"

    expected = pd.read_csv(reference_path)
    derived, _summary, _written = telemetry.process(
        TELEMETRY_INPUT, output_dir=tmp_path, write_plots=False
    )

    scratch = tmp_path / "roundtrip.csv"
    derived.to_csv(scratch, index=False)
    actual = pd.read_csv(scratch)

    _assert_frames_match(actual, expected, "example_telemetry_derived.csv")


def test_examples_holds_no_plots() -> None:
    """No PNGs are tracked in examples/.

    Stated as a test because the reasoning is easy to forget and the temptation to commit a
    nice-looking plot is real. A byte-compared PNG goes red on a font substitution, which is
    indistinguishable from a genuine regression.
    """
    plots = sorted(p.name for p in EXAMPLES.glob("*.png"))
    assert not plots, (
        f"PNGs present in examples/: {plots}. Plots are not byte-reproducible across "
        f"matplotlib versions, fonts and platforms; commit the CSVs instead."
    )


def test_withheld_stages_reference_is_absent() -> None:
    """sweep_stages.csv stays out of examples/ while its column is 10x wrong.

    An approximately-correct value in a published reference is worse than an absent one:
    a wrong non-empty number propagates and gets acted on, while an absent file is visibly
    absent. *Principle 2, an approximately-correct identifier is worse than an absent one.*

    When V_out_noload_ref_kV is corrected, add the file, add it to SWEEP_CASES, and delete
    this test in the same change.
    """
    assert not (EXAMPLES / "sweep_stages.csv").exists(), (
        "sweep_stages.csv has appeared in examples/. If V_out_noload_ref_kV is now correct, "
        "add it to SWEEP_CASES and remove this test. If it is not, remove the file."
    )
