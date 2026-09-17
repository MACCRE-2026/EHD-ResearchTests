"""Tests for :mod:`ehdpsu.sweeps`.

These tests verify that each sweep returns a non-empty DataFrame with the
documented columns, that physically expected monotone trends hold (thrust rises
with voltage above onset, V_onset rises with wire radius, droop falls as C or f
rises), and that the CSV/PNG writers produce files. All output goes to a
pytest ``tmp_path`` so the project datacenter (``artifacts/07_Outputs/``) is
untouched.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import reference_design

from ehdpsu import sweeps
from ehdpsu.sweeps import labelled

P = reference_design()


def _is_nonempty(df: pd.DataFrame, expected_cols: set[str]) -> None:
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert expected_cols.issubset(set(df.columns))


def test_sweep_voltage_columns_and_thrust_monotone() -> None:
    """Voltage sweep is non-empty and thrust increases with V above onset."""
    df = sweeps.sweep_voltage(P, v_min=15_000.0, v_max=25_000.0, n=21)
    _is_nonempty(
        df,
        {
            "V_op_kV",
            "I_ion_mA",
            "power_W",
            labelled("thrust_N"),
            labelled("thrust_gf"),
            labelled("efficiency_N_per_kW"),
        },
    )
    # Above onset (default V_onset ~2.7 kV, well below 15 kV) thrust is strictly
    # increasing with voltage.
    thrust = df[labelled("thrust_N")].to_numpy()
    assert np.all(np.diff(thrust) > 0)
    # And current is non-negative throughout.
    assert np.all(df["I_ion_mA"].to_numpy() >= 0)


def test_sweep_wire_radius_onset_increases() -> None:
    """V_onset increases with wire radius over the swept range."""
    df = sweeps.sweep_wire_radius(P, r_min=25e-6, r_max=50e-6, n=21)
    _is_nonempty(df, {"r_wire_um", "E_peek_MVpm", "V_onset_kV", "corona_onset_margin"})
    v_onset = df["V_onset_kV"].to_numpy()
    assert np.all(np.diff(v_onset) > 0)


def test_sweep_gap_has_breakdown_and_onset_margins() -> None:
    """Gap sweep reports mean-gap-field breakdown and corona-onset margins."""
    df = sweeps.sweep_gap(P, d_min=0.008, d_max=0.020, n=21)
    _is_nonempty(
        df,
        {
            "d_gap_mm",
            "V_onset_kV",
            labelled("thrust_N"),
            "mean_gap_breakdown_margin",
            "corona_onset_margin",
        },
    )
    # Wider gap -> lower mean field -> larger breakdown margin (monotone up).
    margin = df["mean_gap_breakdown_margin"].to_numpy()
    assert np.all(np.diff(margin) > 0)
    # Margins are positive and finite for the swept operating point.
    assert np.all(margin > 0)
    assert np.all(np.isfinite(df["corona_onset_margin"].to_numpy()))


def test_sweep_frequency_droop_decreases() -> None:
    """Droop decreases as switching frequency increases."""
    df = sweeps.sweep_frequency(P, f_min=100_000.0, f_max=500_000.0, n=21)
    _is_nonempty(df, {"f_sw_kHz", "droop_V", "droop_pct", "ripple_Vpp"})
    droop = df["droop_pct"].to_numpy()
    assert np.all(np.diff(droop) < 0)


def test_sweep_capacitance_droop_decreases() -> None:
    """Droop decreases as per-stage capacitance increases."""
    df = sweeps.sweep_capacitance(P, c_min=0.5e-9, c_max=5.0e-9, n=21)
    _is_nonempty(df, {"C_stage_nF", "droop_V", "droop_pct", "ripple_Vpp"})
    droop = df["droop_pct"].to_numpy()
    assert np.all(np.diff(droop) < 0)


def test_sweep_stages_columns_and_noload_increases() -> None:
    """Stage sweep is non-empty; no-load output rises with N."""
    df = sweeps.sweep_stages(P, n_min=3, n_max=8)
    _is_nonempty(df, {"N_stages", "droop_V", "droop_pct", "ripple_Vpp", "V_out_noload_ref_kV"})
    assert list(df["N_stages"]) == [3, 4, 5, 6, 7, 8]
    v_out = df["V_out_noload_ref_kV"].to_numpy()
    assert np.all(np.diff(v_out) > 0)
    # More stages -> more droop and more ripple (monotone up).
    assert np.all(np.diff(df["droop_pct"].to_numpy()) > 0)
    assert np.all(np.diff(df["ripple_Vpp"].to_numpy()) > 0)


def test_write_sweep_creates_csv_and_png(tmp_path: Path) -> None:
    """write_sweep writes both a CSV and a PNG to the target directory."""
    df = sweeps.sweep_voltage(P, n=11)
    csv_path, png_path = sweeps.write_sweep(
        df,
        "sweep_voltage",
        "V_op_kV",
        [labelled("thrust_gf")],
        "title",
        "V_op [kV]",
        "thrust [gf]",
        output_dir=tmp_path,
    )
    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert png_path.exists() and png_path.stat().st_size > 0
    # Round-trip the CSV to confirm it is non-empty and parseable.
    reloaded = pd.read_csv(csv_path)
    assert len(reloaded) == len(df)


def test_run_all_writes_all_files(tmp_path: Path) -> None:
    """run_all writes a CSV+PNG pair for every sweep under tmp_path."""
    written = sweeps.run_all(P, output_dir=tmp_path)
    assert len(written) == 12  # 6 sweeps x (csv + png)
    for f in written:
        assert f.exists() and f.stat().st_size > 0
    csvs = sorted(tmp_path.glob("*.csv"))
    pngs = sorted(tmp_path.glob("*.png"))
    assert len(csvs) == 6
    assert len(pngs) == 6


# ---------------------------------------------------------------------------
# Upper-bound labelling is structural, not incidental
# ---------------------------------------------------------------------------
#
# *Physics honesty rule 4:* an upper bound is labelled an upper bound everywhere it appears. These
# tests are what stop the label being dropped from a CSV header during a tidy-up, which is the most
# likely way it would go: the suffix is verbose, and a bare `thrust_N` looks cleaner right up to the
# moment somebody quotes it as a prediction.

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

#: Columns that carry the k_geo band but are NOT bounds. Kept as a named set because the
#: interesting half of the rule is which columns must *not* be labelled.
BANDED_BUT_NOT_BOUNDED = ("I_ion_mA", "power_W", "droop_V", "droop_pct", "ripple_Vpp")


def test_the_ceiling_column_set_is_exactly_the_three_bounds() -> None:
    """``UPPER_BOUND_COLUMNS`` names the ceilings and nothing else.

    ``thrust`` and its grams-force form are ceilings because ``T = I*d/mu`` assumes full
    ion-to-neutral momentum transfer with no drag. Efficiency is the ratio of that ceiling to the
    same power, so it inherits the bound even though its ``k_geo`` band is exact.

    The current, power, droop and ripple are **not** ceilings. They carry the ``k_geo`` x10 band,
    which is a two-sided uncertainty: the real current may be higher or lower. Labelling them
    ``UPPER_BOUND`` would be a false statement in the direction that matters least but is still
    false, and it would dilute the label everywhere else.
    """
    assert set(sweeps.UPPER_BOUND_COLUMNS) == {
        "thrust_N",
        "thrust_gf",
        "efficiency_N_per_kW",
    }
    for column in BANDED_BUT_NOT_BOUNDED:
        assert column not in sweeps.UPPER_BOUND_COLUMNS, (
            f"{column} carries the k_geo band but is not a ceiling; labelling it UPPER_BOUND "
            f"would assert the real value cannot be higher, which is false."
        )


def test_labelled_is_the_only_way_a_suffix_is_applied() -> None:
    assert labelled("thrust_N") == "thrust_N" + sweeps.UPPER_BOUND_SUFFIX
    assert labelled("power_W") == "power_W"
    # Idempotence matters: applying it twice during a refactor must not produce a doubled suffix.
    assert labelled(labelled("power_W")) == "power_W"


def test_every_sweep_row_labels_its_ceilings() -> None:
    """Checked on a generated row, not on a file, so a new sweep cannot skip the labelling."""
    row = sweeps.sweep_voltage(reference_design(), n=3).iloc[0].to_dict()
    for base in sweeps.UPPER_BOUND_COLUMNS:
        assert base not in row, f"{base} appears unlabelled in a sweep row"
        assert labelled(base) in row, f"{labelled(base)} is missing from a sweep row"


@pytest.mark.parametrize(
    "csv_name",
    [
        "sweep_voltage.csv",
        "sweep_wire_radius.csv",
        "sweep_gap.csv",
        "sweep_frequency.csv",
        "sweep_capacitance.csv",
    ],
)
def test_tracked_reference_csv_headers_carry_the_label(csv_name: str) -> None:
    """The label has to be in the file a cloner reads, not only in the code that wrote it."""
    header = (EXAMPLES / csv_name).read_text(encoding="utf-8").splitlines()[0].split(",")

    for base in sweeps.UPPER_BOUND_COLUMNS:
        assert (
            base not in header
        ), f"{csv_name} has an unlabelled ceiling column {base!r}. Regenerate the reference CSVs."
        assert labelled(base) in header

    # And nothing else wears the suffix, or it stops meaning anything.
    suffixed = [c for c in header if c.endswith(sweeps.UPPER_BOUND_SUFFIX)]
    assert len(suffixed) == len(sweeps.UPPER_BOUND_COLUMNS)


def test_telemetry_thrust_is_deliberately_not_labelled() -> None:
    """A load-cell reading is not a ceiling, and labelling it would be wrong the other way.

    ``telemetry.derive`` computes ``thrust_N`` from the measured ``F_mN``, and ``eff_N_per_W`` from
    measured thrust over measured **input** power — which additionally includes driver losses, so it
    is not even the same quantity as the model's efficiency.

    This asymmetry is pinned because "make the thrust columns consistent" is exactly the tidy-up that
    would corrupt it. The model's thrust is an upper bound; the measurement is a measurement.
    """
    derived = REPO_ROOT / "examples" / "example_telemetry_derived.csv"
    header = derived.read_text(encoding="utf-8").splitlines()[0].split(",")

    assert "thrust_N" in header, "telemetry's measured thrust column was renamed"
    assert not [
        c for c in header if c.endswith(sweeps.UPPER_BOUND_SUFFIX)
    ], "a telemetry column carries the UPPER_BOUND suffix. Measured thrust is not a ceiling."


def test_the_ceiling_plot_says_so_in_its_title_axis_and_caption() -> None:
    """A PNG cannot be diffed, so the labelling is asserted on the code that produces it.

    Matplotlib output is not byte-reproducible across versions and fonts, which is why plots are not
    tracked. That leaves the source as the only checkable place, and an axis label is exactly what a
    reader takes at face value.
    """
    source = (REPO_ROOT / "src" / "ehdpsu" / "sweeps.py").read_text(encoding="utf-8")
    voltage_call = source.split('"sweep_voltage",', 1)[1].split("written +=", 1)[0]

    assert (
        "UPPER BOUNDS" in voltage_call
    ), "the thrust/efficiency plot title or axis omits the label"
    assert voltage_call.count("UPPER BOUNDS") >= 2, "the label is in only one of title and axis"
    assert "caption=UPPER_BOUND_CAVEAT" in voltage_call

    # The droop and ripple plots are not bounds, but they do inherit the band, and a reader takes an
    # absolute level at face value unless told otherwise.
    assert (
        source.count("caption=K_GEO_BAND_CAVEAT") == 3
    ), "the frequency, capacitance and stage-count plots must each carry the k_geo band caveat"
    assert "NOT an upper bound" in sweeps.K_GEO_BAND_CAVEAT
