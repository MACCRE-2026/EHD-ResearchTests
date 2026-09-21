"""ESP32 telemetry CSV ingest + derived-metric processor.

Run with::

    python -m ehdpsu.telemetry --input tests/data/example_telemetry.csv

The benchtop controller (ESP32-S3 / STM32 with an HX711 load cell and an INA226
current/voltage monitor) logs a CSV with the schema:

============  =========================================  =====
column        meaning                                     unit
============  =========================================  =====
``t_s``       sample time                                s
``F_mN``      measured thrust (load cell)                mN
``V_HV_kV``   high-voltage output                        kV
``I_HV_mA``   high-voltage output current                mA
``P_in_W``    DC input (wall/bench-supply) power          W
============  =========================================  =====

This module ingests such a CSV with :mod:`pandas`, validates the columns, and
computes **derived series from the measured data** (these are honest
measured-data reductions, not physics-model predictions):

* ``thrust_N``      = ``F_mN`` / 1000                      (mN -> N)
* ``P_HV_W``        = ``V_HV_kV`` * ``I_HV_mA``            (kV * mA = W)
* ``eff_N_per_W``   = ``thrust_N`` / ``P_in_W``            (N/W)
* ``eff_N_per_kW``  = ``eff_N_per_W`` * 1000               (N/kW)
* ``sys_eff``       = ``P_HV_W`` / ``P_in_W``              (HV-power / input-power)

Unit-conversion notes (explicit at the boundary)
-------------------------------------------------
* Thrust: 1 mN = 1e-3 N, so ``thrust_N = F_mN * 1e-3``.
* HV electrical power: ``V_HV_kV`` [kV] * ``I_HV_mA`` [mA] = (1e3 V)*(1e-3 A) =
  1 W, so ``P_HV_W = V_HV_kV * I_HV_mA`` with **no extra factor**.
* Efficiency N/kW: divide thrust [N] by input power [W] to get N/W, then
  multiply by 1000 (W per kW) to express per-kilowatt: ``N/kW = (N/W) * 1000``.

Efficiency uses ``P_in_W`` (the wall-plug / bench-supply input power) as the
denominator so it reflects the *system* thrust efficiency the user actually
cares about. ``sys_eff`` separately reports the HV-delivered / input-power
fraction (a conversion-efficiency proxy for the driver + multiplier chain).

Burst-window summary
--------------------
The controller drives short bursts. :func:`burst_window` selects the samples
where the HV is live (``P_HV_W`` above a threshold) and :func:`summarize`
reports mean and peak of the key series within that window, so a short logged
burst reduces to a handful of spec-sheet numbers.

Matplotlib runs on the non-interactive ``Agg`` backend (headless environment);
:func:`matplotlib.use` is called before importing ``pyplot``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend; must precede pyplot import

import matplotlib.pyplot as plt
import pandas as pd

# Default output directory for derived CSV + plots.
#
# Tier 07 of the untracked project datacenter. See :mod:`ehdpsu.sweeps`.
DEFAULT_OUTPUT_DIR = Path("artifacts/07_Outputs")

# The exact controller CSV schema (order matters for validation messages).
REQUIRED_COLUMNS: tuple[str, ...] = ("t_s", "F_mN", "V_HV_kV", "I_HV_mA", "P_in_W")

# Fraction of the peak HV power above which a sample is considered "in burst".
DEFAULT_BURST_THRESHOLD_FRAC = 0.5


class TelemetrySchemaError(ValueError):
    """Raised when an ingested CSV does not match the expected schema."""


@dataclass(frozen=True)
class BurstSummary:
    """Mean/peak reduction of a telemetry burst window.

    All fields are measured-data reductions (see module docstring). Times are in
    seconds; thrust in N; powers in W; efficiencies in N/kW and N/W; ``sys_eff``
    is dimensionless.

    Attributes
    ----------
    n_samples : int
        Number of samples inside the burst window.
    t_start_s, t_end_s, duration_s : float
        Burst window start, end, and duration [s].
    mean_thrust_N, peak_thrust_N : float
        Mean and peak thrust in the window [N].
    mean_P_in_W, peak_P_in_W : float
        Mean and peak input power [W].
    mean_P_HV_W, peak_P_HV_W : float
        Mean and peak HV electrical power [W].
    mean_eff_N_per_kW, peak_eff_N_per_kW : float
        Mean and peak thrust efficiency [N/kW].
    mean_eff_N_per_W : float
        Mean thrust efficiency [N/W].
    mean_sys_eff : float
        Mean HV/input power ratio (dimensionless).
    """

    n_samples: int
    t_start_s: float
    t_end_s: float
    duration_s: float
    mean_thrust_N: float
    peak_thrust_N: float
    mean_P_in_W: float
    peak_P_in_W: float
    mean_P_HV_W: float
    peak_P_HV_W: float
    mean_eff_N_per_kW: float
    peak_eff_N_per_kW: float
    mean_eff_N_per_W: float
    mean_sys_eff: float


def load_telemetry(path: str | Path) -> pd.DataFrame:
    """Load and validate a controller telemetry CSV.

    Parameters
    ----------
    path : str or Path
        Path to the CSV with columns ``t_s, F_mN, V_HV_kV, I_HV_mA, P_in_W``.

    Returns
    -------
    pandas.DataFrame
        The raw telemetry (only the required columns, in canonical order).

    Raises
    ------
    TelemetrySchemaError
        If any required column is missing.
    """
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise TelemetrySchemaError(
            f"telemetry CSV is missing required column(s): {missing}; "
            f"expected schema {list(REQUIRED_COLUMNS)}, got {list(df.columns)}"
        )
    # The explicit DataFrame construction is not redundant. `df[list_of_columns]` is typed as
    # `DataFrame | Series` because pandas returns a Series when the indexer collapses to a single
    # label, and the declared return type here is `DataFrame`. Any downstream caller doing
    # `result["thrust_N"]` would break on a Series.
    #
    # Found by pyright (`reportReturnType`) and NOT by mypy, which infers pandas loosely under
    # `ignore_missing_imports`. It is the first concrete evidence in this project that the two
    # checkers catch different classes, which is why both are in the Gate.
    return pd.DataFrame(df[list(REQUIRED_COLUMNS)]).copy()


def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with derived measured-data columns appended.

    Adds (see module docstring for the unit-conversion rationale):

    * ``thrust_N``     = ``F_mN`` * 1e-3
    * ``P_HV_W``       = ``V_HV_kV`` * ``I_HV_mA``
    * ``eff_N_per_W``  = ``thrust_N`` / ``P_in_W`` (0 where ``P_in_W`` <= 0)
    * ``eff_N_per_kW`` = ``eff_N_per_W`` * 1000
    * ``sys_eff``      = ``P_HV_W`` / ``P_in_W`` (0 where ``P_in_W`` <= 0)

    Parameters
    ----------
    df : pandas.DataFrame
        Validated telemetry (from :func:`load_telemetry`).

    Returns
    -------
    pandas.DataFrame
        A copy with the derived columns added.
    """
    out = df.copy()
    out["thrust_N"] = out["F_mN"] * 1e-3
    # kV * mA = (1e3 V) * (1e-3 A) = 1 W, so no extra scale factor.
    out["P_HV_W"] = out["V_HV_kV"] * out["I_HV_mA"]

    p_in = out["P_in_W"]
    safe = p_in > 0
    out["eff_N_per_W"] = 0.0
    out.loc[safe, "eff_N_per_W"] = out.loc[safe, "thrust_N"] / p_in[safe]
    out["eff_N_per_kW"] = out["eff_N_per_W"] * 1000.0
    out["sys_eff"] = 0.0
    out.loc[safe, "sys_eff"] = out.loc[safe, "P_HV_W"] / p_in[safe]
    return out


def burst_window(
    df: pd.DataFrame,
    threshold_frac: float = DEFAULT_BURST_THRESHOLD_FRAC,
) -> pd.DataFrame:
    """Return the sub-frame of samples inside the active HV burst.

    A sample is "in burst" when its HV electrical power ``P_HV_W`` exceeds
    ``threshold_frac`` of the run's peak ``P_HV_W``. This isolates the powered
    window from the idle head/tail of the log, whatever its duration.

    The burst duration is deliberately **not** stated here. It read "3-5 s" until
    2026-09-20, inherited from the AI Studio conversation as a claim about a
    controller that has never been built, supported by nothing. Withdrawn rather
    than moved into the profile, because inventing a field to hold an unsourced
    figure is the same act with extra ceremony. The window is found from the data.

    Parameters
    ----------
    df : pandas.DataFrame
        Telemetry with derived columns (from :func:`compute_derived`); if
        ``P_HV_W`` is absent it is computed on the fly.
    threshold_frac : float
        Fraction of peak HV power that marks the burst (default 0.5).

    Returns
    -------
    pandas.DataFrame
        The rows within the burst window. Empty if there is no HV power.
    """
    work = df if "P_HV_W" in df.columns else compute_derived(df)
    peak = work["P_HV_W"].max()
    if not (peak > 0):
        return work.iloc[0:0]
    mask = work["P_HV_W"] >= threshold_frac * peak
    return work.loc[mask]


def _scalar(value: Any) -> float:
    """Narrow a pandas reduction result to a ``float``.

    ``Series.min()``, ``.max()`` and ``.mean()`` are typed loosely by pandas' stubs --
    ``Series | Unknown | Any`` -- because on a *DataFrame* those methods reduce along an axis and
    return a Series. On a **1-D Series**, which is the only thing passed here, they always return a
    scalar. pyright reports the bare ``float(...)`` as ``reportArgumentType`` on that basis; mypy
    does not, because it infers pandas loosely under ``ignore_missing_imports``. That divergence is
    why both checkers are in the Gate.

    One helper rather than 13 inline casts, deliberately: *principle 4, two representations of one
    thing will drift*. The assumption being made -- "this reduction is over a Series, so it is a
    scalar" -- is stated once, in a place where it can be found and argued with, instead of being
    re-asserted at every call site where the next reader would have to re-derive it.

    This narrows a **type**, not a **number**. It performs no conversion beyond ``float()`` and
    changes no value, so nothing here touches basis, band or provenance.
    """
    return float(value)


def summarize(
    df: pd.DataFrame,
    threshold_frac: float = DEFAULT_BURST_THRESHOLD_FRAC,
) -> BurstSummary:
    """Reduce a telemetry run to a :class:`BurstSummary` over its burst window.

    Parameters
    ----------
    df : pandas.DataFrame
        Telemetry with derived columns (from :func:`compute_derived`).
    threshold_frac : float
        Burst-detection threshold (see :func:`burst_window`).

    Returns
    -------
    BurstSummary
        Mean/peak reduction of the burst window.

    Raises
    ------
    ValueError
        If no active burst window is found (no HV power in the log).
    """
    window = burst_window(df, threshold_frac=threshold_frac)
    if window.empty:
        raise ValueError("no active HV burst window found (P_HV_W never exceeds threshold)")
    t = window["t_s"]
    return BurstSummary(
        n_samples=len(window),
        t_start_s=_scalar(t.min()),
        t_end_s=_scalar(t.max()),
        duration_s=_scalar(t.max()) - _scalar(t.min()),
        mean_thrust_N=_scalar(window["thrust_N"].mean()),
        peak_thrust_N=_scalar(window["thrust_N"].max()),
        mean_P_in_W=_scalar(window["P_in_W"].mean()),
        peak_P_in_W=_scalar(window["P_in_W"].max()),
        mean_P_HV_W=_scalar(window["P_HV_W"].mean()),
        peak_P_HV_W=_scalar(window["P_HV_W"].max()),
        mean_eff_N_per_kW=_scalar(window["eff_N_per_kW"].mean()),
        peak_eff_N_per_kW=_scalar(window["eff_N_per_kW"].max()),
        mean_eff_N_per_W=_scalar(window["eff_N_per_W"].mean()),
        mean_sys_eff=_scalar(window["sys_eff"].mean()),
    )


def _save_plots(df: pd.DataFrame, output_dir: Path, name: str) -> list[Path]:
    """Render thrust/power and efficiency time-series PNGs (Agg backend).

    Returns the list of PNG paths written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Thrust and powers vs time.
    fig, ax1 = plt.subplots(figsize=(8.0, 5.0))
    ax1.plot(df["t_s"], df["thrust_N"] * 1e3, color="tab:blue", label="thrust [mN]")
    ax1.set_xlabel("t [s]")
    ax1.set_ylabel("thrust [mN]", color="tab:blue")
    ax1.grid(True, alpha=0.3)
    ax2 = ax1.twinx()
    ax2.plot(df["t_s"], df["P_in_W"], color="tab:red", label="P_in [W]")
    ax2.plot(df["t_s"], df["P_HV_W"], color="tab:orange", label="P_HV [W]")
    ax2.set_ylabel("power [W]")
    ax1.set_title("Telemetry: thrust and power vs time")
    fig.tight_layout()
    p1 = output_dir / f"{name}_thrust_power.png"
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    written.append(p1)

    # Efficiency vs time.
    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    ax.plot(df["t_s"], df["eff_N_per_kW"], color="tab:green", marker=".")
    ax.set_xlabel("t [s]")
    ax.set_ylabel("thrust efficiency [N/kW]")
    ax.set_title("Telemetry: dynamic thrust efficiency vs time")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p2 = output_dir / f"{name}_efficiency.png"
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    written.append(p2)

    return written


def process(
    input_path: str | Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    write_plots: bool = True,
    threshold_frac: float = DEFAULT_BURST_THRESHOLD_FRAC,
) -> tuple[pd.DataFrame, BurstSummary, list[Path]]:
    """Full pipeline: load, derive, summarize, and write CSV/plots.

    Parameters
    ----------
    input_path : str or Path
        Path to the controller telemetry CSV.
    output_dir : Path
        Destination directory for the derived CSV and plots.
    write_plots : bool
        Also render the time-series PNGs.
    threshold_frac : float
        Burst-detection threshold (see :func:`burst_window`).

    Returns
    -------
    tuple[pandas.DataFrame, BurstSummary, list[Path]]
        The derived DataFrame, the burst summary, and the files written.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    df = load_telemetry(input_path)
    derived = compute_derived(df)
    summary = summarize(derived, threshold_frac=threshold_frac)

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    name = input_path.stem
    csv_path = output_dir / f"{name}_derived.csv"
    derived.to_csv(csv_path, index=False)
    written.append(csv_path)
    if write_plots:
        written += _save_plots(derived, output_dir, name)

    return derived, summary, written


def _print_summary(summary: BurstSummary) -> None:
    """Print a burst summary to stdout in a compact, labeled block."""
    print("=== EHD telemetry burst summary ===")
    print(
        f"burst window: {summary.t_start_s:.3f}-{summary.t_end_s:.3f} s "
        f"(duration {summary.duration_s:.3f} s, {summary.n_samples} samples)"
    )
    print(
        f"thrust:  mean {summary.mean_thrust_N * 1e3:.4g} mN, "
        f"peak {summary.peak_thrust_N * 1e3:.4g} mN"
    )
    print(f"P_in:    mean {summary.mean_P_in_W:.4g} W, peak {summary.peak_P_in_W:.4g} W")
    print(f"P_HV:    mean {summary.mean_P_HV_W:.4g} W, peak {summary.peak_P_HV_W:.4g} W")
    print(
        f"thrust efficiency: mean {summary.mean_eff_N_per_kW:.4g} N/kW "
        f"({summary.mean_eff_N_per_W:.4g} N/W), peak {summary.peak_eff_N_per_kW:.4g} N/kW"
    )
    print(f"system eff (P_HV/P_in): mean {summary.mean_sys_eff * 100.0:.3g} %")


def main(argv: list[str] | None = None) -> None:
    """CLI: process a telemetry CSV, print the summary, write derived CSV/plots."""
    parser = argparse.ArgumentParser(
        prog="python -m ehdpsu.telemetry",
        description="Ingest ESP32 EHD telemetry CSV and compute derived thrust/efficiency metrics.",
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="path to the controller telemetry CSV (t_s,F_mN,V_HV_kV,I_HV_mA,P_in_W)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"output directory for derived CSV/plots (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="skip writing PNG plots (still writes the derived CSV)",
    )
    parser.add_argument(
        "--threshold-frac",
        type=float,
        default=DEFAULT_BURST_THRESHOLD_FRAC,
        help="fraction of peak HV power that marks the burst window (default 0.5)",
    )
    args = parser.parse_args(argv)

    _derived, summary, written = process(
        args.input,
        output_dir=Path(args.output_dir),
        write_plots=not args.no_plots,
        threshold_frac=args.threshold_frac,
    )
    _print_summary(summary)
    print(f"\nWrote {len(written)} file(s):")
    for f in written:
        print(f"  {f}")
    print(
        "\nNOTE: efficiencies are MEASURED-data reductions (thrust/power from "
        "the logged load-cell + INA226 channels), not physics-model predictions."
    )


if __name__ == "__main__":
    main()
