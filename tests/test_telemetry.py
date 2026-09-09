"""Tests for :mod:`ehdpsu.telemetry`.

These tests feed the committed synthetic CSV (``tests/data/example_telemetry.csv``)
through the ingest + derived-metric pipeline and assert that the derived N/kW,
N/W, and efficiency values match **hand-computed** references, and that the
burst-window aggregation selects the correct samples.

The synthetic run is a 4 s burst (t = 1.0..5.0 s) bracketed by idle head/tail
samples. During the burst V_HV_kV = 20 for every powered sample, so
P_HV_W = 20 * I_HV_mA. Peak P_HV_W = 100 W (at t = 3.0, I = 5.0 mA), so with the
default 0.5 threshold every powered sample (P_HV >= 50 W) is in the burst and the
two idle ends (P_HV = 0) are excluded.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from ehdpsu import telemetry

DATA = Path(__file__).parent / "data" / "example_telemetry.csv"


def test_load_validates_schema() -> None:
    """Loading the example CSV returns exactly the required columns."""
    df = telemetry.load_telemetry(DATA)
    assert list(df.columns) == list(telemetry.REQUIRED_COLUMNS)
    assert len(df) == 13


def test_missing_column_raises(tmp_path: Path) -> None:
    """A CSV missing a required column raises TelemetrySchemaError."""
    bad = tmp_path / "bad.csv"
    bad.write_text("t_s,F_mN,V_HV_kV\n0,0,0\n", encoding="utf-8")
    with pytest.raises(telemetry.TelemetrySchemaError):
        telemetry.load_telemetry(bad)


def test_derived_columns_unit_conversions() -> None:
    """thrust_N, P_HV_W, N/W, N/kW, sys_eff match hand-computed values."""
    df = telemetry.load_telemetry(DATA)
    d = telemetry.compute_derived(df)

    # Row at t = 2.0 s: F = 8 mN, V = 20 kV, I = 4 mA, P_in = 100 W.
    row = d.loc[d["t_s"] == 2.0].iloc[0]
    assert math.isclose(row["thrust_N"], 0.008, rel_tol=0, abs_tol=1e-12)
    # kV * mA = W: 20 * 4 = 80 W.
    assert math.isclose(row["P_HV_W"], 80.0, rel_tol=0, abs_tol=1e-9)
    # N/W = 0.008 / 100 = 8e-5.
    assert math.isclose(row["eff_N_per_W"], 8e-5, rel_tol=0, abs_tol=1e-12)
    # N/kW = N/W * 1000 = 0.08.
    assert math.isclose(row["eff_N_per_kW"], 0.08, rel_tol=0, abs_tol=1e-9)
    # sys_eff = P_HV / P_in = 80 / 100 = 0.8.
    assert math.isclose(row["sys_eff"], 0.8, rel_tol=0, abs_tol=1e-9)


def test_idle_rows_have_zero_derived_metrics() -> None:
    """Idle samples (no HV) get zero HV power and zero efficiency, not NaN."""
    df = telemetry.load_telemetry(DATA)
    d = telemetry.compute_derived(df)
    idle = d.loc[d["t_s"] == 0.0].iloc[0]
    assert idle["P_HV_W"] == 0.0
    assert idle["eff_N_per_W"] == 0.0
    assert idle["eff_N_per_kW"] == 0.0
    assert idle["sys_eff"] == 0.0


def test_burst_window_selects_powered_samples() -> None:
    """The burst window is the 9 powered samples from t = 1.0 to 5.0 s."""
    df = telemetry.load_telemetry(DATA)
    d = telemetry.compute_derived(df)
    window = telemetry.burst_window(d)
    assert len(window) == 9
    assert math.isclose(window["t_s"].min(), 1.0)
    assert math.isclose(window["t_s"].max(), 5.0)
    # Idle ends (P_HV = 0) are excluded.
    assert (window["P_HV_W"] > 0).all()


def test_summary_matches_hand_computed() -> None:
    """BurstSummary mean/peak values match hand computation."""
    df = telemetry.load_telemetry(DATA)
    d = telemetry.compute_derived(df)
    s = telemetry.summarize(d)

    assert s.n_samples == 9
    assert math.isclose(s.t_start_s, 1.0)
    assert math.isclose(s.t_end_s, 5.0)
    assert math.isclose(s.duration_s, 4.0)

    # thrust_N over the burst: 0.006,0.007,0.008,0.009,0.010,0.009,0.008,0.007,0.006
    # sum = 0.070, mean = 0.070/9, peak = 0.010.
    assert math.isclose(s.mean_thrust_N, 0.070 / 9.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(s.peak_thrust_N, 0.010, rel_tol=0, abs_tol=1e-12)

    # P_HV over the burst: 60,70,80,90,100,90,80,70,60 W -> sum 700, mean 700/9.
    assert math.isclose(s.mean_P_HV_W, 700.0 / 9.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(s.peak_P_HV_W, 100.0, rel_tol=0, abs_tol=1e-9)

    # P_in over the burst: 90,95,100,105,110,105,100,95,90 -> sum 890, mean 890/9.
    assert math.isclose(s.mean_P_in_W, 890.0 / 9.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(s.peak_P_in_W, 110.0, rel_tol=0, abs_tol=1e-9)

    # Peak N/kW occurs at the highest per-sample eff. Per-sample N/kW =
    # thrust_N/P_in*1000. t=3.0: 0.010/110*1000 = 0.0909..., which is the peak.
    assert math.isclose(s.peak_eff_N_per_kW, 0.010 / 110.0 * 1000.0, rel_tol=0, abs_tol=1e-9)
    # mean N/kW = mean of per-sample N/kW.
    per_sample = [
        0.006 / 90.0,
        0.007 / 95.0,
        0.008 / 100.0,
        0.009 / 105.0,
        0.010 / 110.0,
        0.009 / 105.0,
        0.008 / 100.0,
        0.007 / 95.0,
        0.006 / 90.0,
    ]
    expected_mean_n_per_w = sum(per_sample) / 9.0
    assert math.isclose(s.mean_eff_N_per_W, expected_mean_n_per_w, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(
        s.mean_eff_N_per_kW, expected_mean_n_per_w * 1000.0, rel_tol=0, abs_tol=1e-9
    )


def test_process_writes_outputs(tmp_path: Path) -> None:
    """process() writes a derived CSV and two plots and returns the summary."""
    derived, summary, written = telemetry.process(DATA, output_dir=tmp_path, write_plots=True)
    assert summary.n_samples == 9
    # derived CSV + 2 PNGs.
    assert len(written) == 3
    csv = tmp_path / "example_telemetry_derived.csv"
    assert csv.exists() and csv.stat().st_size > 0
    assert (tmp_path / "example_telemetry_thrust_power.png").exists()
    assert (tmp_path / "example_telemetry_efficiency.png").exists()
    # Derived frame carries the computed columns.
    assert "eff_N_per_kW" in derived.columns


def test_process_no_plots(tmp_path: Path) -> None:
    """write_plots=False writes only the derived CSV."""
    _, _, written = telemetry.process(DATA, output_dir=tmp_path, write_plots=False)
    assert len(written) == 1
    assert written[0].name == "example_telemetry_derived.csv"


def test_summary_raises_without_burst(tmp_path: Path) -> None:
    """A log with no HV power raises when summarized."""
    csv = tmp_path / "idle.csv"
    csv.write_text(
        "t_s,F_mN,V_HV_kV,I_HV_mA,P_in_W\n0.0,0.0,0.0,0.0,2.0\n1.0,0.0,0.0,0.0,2.0\n",
        encoding="utf-8",
    )
    d = telemetry.compute_derived(telemetry.load_telemetry(csv))
    with pytest.raises(ValueError):
        telemetry.summarize(d)
