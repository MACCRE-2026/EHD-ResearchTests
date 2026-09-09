"""Tests for :mod:`ehdpsu.sweeps`.

These tests verify that each sweep returns a non-empty DataFrame with the
documented columns, that physically expected monotone trends hold (thrust rises
with voltage above onset, V_onset rises with wire radius, droop falls as C or f
rises), and that the CSV/PNG writers produce files. All output goes to a
pytest ``tmp_path`` so the repo ``outputs/`` directory is untouched.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ehdpsu import sweeps
from ehdpsu.physics import DesignParameters

P = DesignParameters()


def _is_nonempty(df: pd.DataFrame, expected_cols: set[str]) -> None:
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert expected_cols.issubset(set(df.columns))


def test_sweep_voltage_columns_and_thrust_monotone() -> None:
    """Voltage sweep is non-empty and thrust increases with V above onset."""
    df = sweeps.sweep_voltage(P, v_min=15_000.0, v_max=25_000.0, n=21)
    _is_nonempty(
        df,
        {"V_op_kV", "I_ion_mA", "power_W", "thrust_N", "thrust_gf", "efficiency_N_per_kW"},
    )
    # Above onset (default V_onset ~2.7 kV, well below 15 kV) thrust is strictly
    # increasing with voltage.
    thrust = df["thrust_N"].to_numpy()
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
            "thrust_N",
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
        ["thrust_gf"],
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
