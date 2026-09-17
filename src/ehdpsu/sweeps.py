"""Parameter-sweep validation toolkit built on the pure physics core.

Run with::

    python -m ehdpsu.sweeps

This module turns the single-operating-point physics in :mod:`ehdpsu.physics`
into **parameter studies** that help nail down the part/spec sheet: it sweeps
one design variable at a time (operating voltage, wire radius, gap, switching
frequency, per-stage capacitance, stage count) and returns a
:class:`pandas.DataFrame` of derived quantities for each. Each sweep can be
rendered to a companion CSV (``DataFrame.to_csv``) and a matplotlib PNG under
``artifacts/07_Outputs/`` (tier 07 of the untracked project datacenter).

Physics honesty
---------------
No formulas are duplicated here: every physical quantity is computed by calling
:mod:`ehdpsu.physics`. The sweeps therefore inherit the physics core's
documented caveats, in particular:

* the ion current uses the *labeled parallel-plate* prefactor
  (:func:`ehdpsu.physics.geometric_constant_parallel_plate`), an
  order-of-magnitude model parameter, not a fitted constant; and
* thrust / efficiency are *idealized mobility-limited upper bounds*
  (:func:`ehdpsu.physics.thrust_newton`).

These caveats are surfaced in the CLI summary and in the plot captions so the
numbers are never mistaken for calibrated predictions.

Matplotlib runs on the non-interactive ``Agg`` backend (this is a headless
environment); :func:`matplotlib.use` is called *before* importing ``pyplot``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend; must precede pyplot import

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import physics
from .physics import DesignParameters, default_design

# ---------------------------------------------------------------------------
# Upper-bound labelling for emitted columns.
# ---------------------------------------------------------------------------
#
# *Physics honesty rule 4:* an upper bound is labelled an upper bound **everywhere** it appears --
# the CSV column header, the plot axis, the spec-sheet row, the docstring -- and not once in a
# footnote. A ceiling in a bare column called `thrust_N` becomes a prediction the moment somebody
# opens the CSV without having read the derivation, and that somebody is often the author six weeks
# later.
#
# Why exactly these three:
#   thrust_N, thrust_gf     `T = I*d/mu` assumes every ion transfers all its momentum to neutrals,
#                           with no neutral drag and a uniform gap field. Real thrust is LOWER.
#   efficiency_N_per_kW     the ratio of that ceiling thrust to the same power, so it inherits the
#                           ceiling even though its k_geo band is exact (k_geo cancels in F/P).
#
# Why NOT the others, which is the more interesting half:
#   I_ion, power, droop, ripple   these carry the k_geo x10 BAND, which is a two-sided uncertainty
#                                 and not a ceiling. Labelling them UPPER_BOUND would be false --
#                                 the real current could be higher or lower.
#   E_peek, V_onset, margins      independent of k_geo, and neither bounds nor especially uncertain.
#
# And telemetry's `thrust_N` is deliberately NOT labelled: it is a load-cell reading, so calling it
# a ceiling would be wrong in the opposite direction. `tests/test_sweeps.py` pins that asymmetry,
# because "make these consistent" is the tidying that would corrupt it.
UPPER_BOUND_SUFFIX = "_UPPER_BOUND"

#: Emitted column base names that are ceilings rather than estimates.
UPPER_BOUND_COLUMNS: tuple[str, ...] = ("thrust_N", "thrust_gf", "efficiency_N_per_kW")


def labelled(column: str) -> str:
    """Return ``column`` with the upper-bound suffix appended if it names a ceiling.

    One function, applied at the single point where a sweep row is assembled, so the label cannot
    be forgotten for one sweep and remembered for another.
    """
    return f"{column}{UPPER_BOUND_SUFFIX}" if column in UPPER_BOUND_COLUMNS else column


# Default output directory for CSVs and PNGs.
#
# Tier 07 of the untracked project datacenter. Generated data is never tracked: it is
# reproducible from the code and the profile, and committing it would create a second
# representation that can disagree with what the code now produces.
DEFAULT_OUTPUT_DIR = Path("artifacts/07_Outputs")

# A short caveat string reused in plot captions / CLI output.
UPPER_BOUND_CAVEAT = (
    "Thrust/efficiency are idealized mobility-limited UPPER BOUNDS; "
    "ion current uses a labeled parallel-plate prefactor (order-of-magnitude)."
)

# For the droop and ripple plots, which are NOT bounds but do inherit the k_geo band through the
# load current. Without this a reader takes the absolute level at face value: the curve *shape*
# against frequency, capacitance and stage count is sound, and the level is uncertain by an order
# of magnitude. Two different things, and only one of them is being demonstrated.
K_GEO_BAND_CAVEAT = (
    "Inherits the k_geo x0.1-x1.0 model band through the load current: the trend is sound, "
    "the absolute level is uncertain by an order of magnitude. NOT an upper bound -- the real "
    "current may be higher or lower."
)


def _replace(p: DesignParameters, **changes: Any) -> DesignParameters:
    """Return a copy of ``p`` with the given field overrides.

    Thin wrapper over :func:`dataclasses.replace` so the sweep functions read
    cleanly. ``DesignParameters`` is frozen, so this never mutates the input.
    """
    return dataclasses.replace(p, **changes)


def _operating_point(p: DesignParameters) -> dict[str, float]:
    """Compute the full single-cell operating point for one parameter set.

    Returns a flat dict of derived quantities, every one obtained from
    :mod:`ehdpsu.physics` (no formula is reimplemented here). This is the shared
    kernel behind the voltage/gap/wire sweeps.
    """
    e_peek = physics.peek_inception_field(p.r_wire_m, p.delta, p.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, p.r_wire_m, p.d_gap_m)
    k_geo = physics.geometric_constant_parallel_plate(physics.EPS0, p.mu_ion, p.L_wire_m, p.d_gap_m)
    i_ion = physics.ion_current(p.V_op, v_onset, k_geo)
    power = physics.electrical_power(p.V_op, i_ion)
    thrust_n = physics.thrust_newton(i_ion, p.d_gap_m, p.mu_ion)
    thrust_gf = physics.thrust_grams_force(thrust_n)
    eff = physics.efficiency_N_per_kW(thrust_n, power)
    onset_margin = physics.corona_onset_margin(p.V_op, v_onset)
    breakdown_margin = physics.mean_gap_breakdown_margin(p.V_op, p.d_gap_m)
    droop = physics.cw_voltage_droop(i_ion, p.f_sw, p.C_stage, p.N_stages)
    ripple = physics.cw_ripple_pp(i_ion, p.f_sw, p.C_stage, p.N_stages)
    row = {
        "E_peek_MVpm": e_peek / 1e6,
        "V_onset_kV": v_onset / 1e3,
        "k_geo_ApV2": k_geo,
        "I_ion_mA": i_ion * 1e3,
        "power_W": power,
        "thrust_N": thrust_n,
        "thrust_gf": thrust_gf,
        "efficiency_N_per_kW": eff,
        "corona_onset_margin": onset_margin,
        "mean_gap_breakdown_margin": breakdown_margin,
        "droop_V": droop,
        "droop_pct": (droop / p.V_op * 100.0) if p.V_op > 0 else 0.0,
        "ripple_Vpp": ripple,
    }
    # Applied uniformly at the one place every sweep row is built, so a ceiling cannot reach a CSV
    # without its label. See UPPER_BOUND_COLUMNS for why these three and not the others.
    return {labelled(name): value for name, value in row.items()}


def sweep_voltage(
    p: DesignParameters | None = None,
    v_min: float = 15_000.0,
    v_max: float = 25_000.0,
    n: int = 41,
) -> pd.DataFrame:
    """Sweep operating voltage; return thrust/power/current/efficiency vs V_op.

    Parameters
    ----------
    p : DesignParameters, optional
        Base design; defaults to :class:`DesignParameters` (original targets).
    v_min, v_max : float
        Voltage range [V].
    n : int
        Number of points.

    Returns
    -------
    pandas.DataFrame
        Columns include ``V_op_kV``, ``I_ion_mA``, ``power_W``,
        ``thrust_N_UPPER_BOUND``, ``thrust_gf_UPPER_BOUND``,
        ``efficiency_N_per_kW_UPPER_BOUND``, ``corona_onset_margin``.
    """
    p = p or default_design()
    rows = []
    for v in np.linspace(v_min, v_max, n):
        op = _operating_point(_replace(p, V_op=float(v)))
        rows.append({"V_op_kV": v / 1e3, **op})
    return pd.DataFrame(rows)


def sweep_wire_radius(
    p: DesignParameters | None = None,
    r_min: float = 25e-6,
    r_max: float = 50e-6,
    n: int = 41,
) -> pd.DataFrame:
    """Sweep emitter wire radius; return V_onset and onset margin vs r_wire.

    Returns
    -------
    pandas.DataFrame
        Columns include ``r_wire_um``, ``E_peek_MVpm``, ``V_onset_kV``,
        ``corona_onset_margin``, ``I_ion_mA``, ``thrust_N_UPPER_BOUND``.
    """
    p = p or default_design()
    rows = []
    for r in np.linspace(r_min, r_max, n):
        op = _operating_point(_replace(p, r_wire_m=float(r)))
        rows.append({"r_wire_um": r * 1e6, **op})
    return pd.DataFrame(rows)


def sweep_gap(
    p: DesignParameters | None = None,
    d_min: float = 0.008,
    d_max: float = 0.020,
    n: int = 41,
) -> pd.DataFrame:
    """Sweep emitter-collector gap; return V_onset, thrust, breakdown margin.

    Returns
    -------
    pandas.DataFrame
        Columns include ``d_gap_mm``, ``V_onset_kV``, ``thrust_N_UPPER_BOUND``,
        ``mean_gap_breakdown_margin``, ``corona_onset_margin``, ``I_ion_mA``.
    """
    p = p or default_design()
    rows = []
    for d in np.linspace(d_min, d_max, n):
        op = _operating_point(_replace(p, d_gap_m=float(d)))
        rows.append({"d_gap_mm": d * 1e3, **op})
    return pd.DataFrame(rows)


def sweep_frequency(
    p: DesignParameters | None = None,
    f_min: float = 100_000.0,
    f_max: float = 500_000.0,
    n: int = 41,
) -> pd.DataFrame:
    """Sweep CW switching frequency; return droop% and ripple vs f_sw.

    Returns
    -------
    pandas.DataFrame
        Columns include ``f_sw_kHz``, ``droop_V``, ``droop_pct``,
        ``ripple_Vpp``, ``I_ion_mA``.
    """
    p = p or default_design()
    rows = []
    for f in np.linspace(f_min, f_max, n):
        op = _operating_point(_replace(p, f_sw=float(f)))
        rows.append({"f_sw_kHz": f / 1e3, **op})
    return pd.DataFrame(rows)


def sweep_capacitance(
    p: DesignParameters | None = None,
    c_min: float = 0.5e-9,
    c_max: float = 5.0e-9,
    n: int = 41,
) -> pd.DataFrame:
    """Sweep per-stage CW capacitance; return droop% and ripple vs C_stage.

    Returns
    -------
    pandas.DataFrame
        Columns include ``C_stage_nF``, ``droop_V``, ``droop_pct``,
        ``ripple_Vpp``, ``I_ion_mA``.
    """
    p = p or default_design()
    rows = []
    for c in np.linspace(c_min, c_max, n):
        op = _operating_point(_replace(p, C_stage=float(c)))
        rows.append({"C_stage_nF": c * 1e9, **op})
    return pd.DataFrame(rows)


def sweep_stages(
    p: DesignParameters | None = None,
    n_min: int = 3,
    n_max: int = 8,
) -> pd.DataFrame:
    """Sweep CW stage count; return droop%, ripple, and no-load output vs N.

    The Cockcroft-Walton no-load output for a symmetric cascade is
    ``2 * N * V_peak`` where ``V_peak`` is the **rectified secondary peak AC
    voltage feeding the multiplier** (each stage adds ~2x that peak). Here we do
    NOT have a separate secondary-peak parameter, so this column reuses ``V_op``
    (the 22 kV DC operating point) purely as a *per-stage peak reference* to
    show the ``2*N`` scaling trend. It is therefore labeled
    ``V_out_noload_ref_kV`` and is a scaling reference, not the physical
    multiplier output for this design (which is ``V_op`` by construction). Feed
    the true secondary peak to interpret it as an absolute no-load output.

    Returns
    -------
    pandas.DataFrame
        Columns include ``N_stages``, ``droop_V``, ``droop_pct``,
        ``ripple_Vpp``, ``V_out_noload_ref_kV``, ``I_ion_mA``.
    """
    p = p or default_design()
    rows = []
    for n_stage in range(n_min, n_max + 1):
        pp = _replace(p, N_stages=int(n_stage))
        op = _operating_point(pp)
        # V_op stands in as the per-stage peak reference; see docstring.
        v_out_noload_ref = 2.0 * n_stage * p.V_op
        rows.append(
            {
                "N_stages": n_stage,
                "V_out_noload_ref_kV": v_out_noload_ref / 1e3,
                **op,
            }
        )
    return pd.DataFrame(rows)


def _save_plot(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    title: str,
    xlabel: str,
    ylabel: str,
    png_path: Path,
    caption: str | None = None,
) -> Path:
    """Render selected columns of ``df`` against ``x_col`` to a PNG.

    Uses the ``Agg`` backend (set at import time). Returns the PNG path.
    """
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    for y in y_cols:
        ax.plot(df[x_col], df[y], marker=".", label=y)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    if len(y_cols) > 1:
        ax.legend()
    if caption:
        fig.text(0.5, 0.005, caption, ha="center", va="bottom", fontsize=7, wrap=True)
        fig.subplots_adjust(bottom=0.18)
    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)
    return png_path


def write_sweep(
    df: pd.DataFrame,
    name: str,
    x_col: str,
    y_cols: list[str],
    title: str,
    xlabel: str,
    ylabel: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    caption: str | None = None,
) -> tuple[Path, Path]:
    """Write a sweep DataFrame to ``<name>.csv`` and ``<name>.png``.

    Parameters
    ----------
    df : pandas.DataFrame
        The sweep result.
    name : str
        Base filename (no extension).
    x_col, y_cols : str, list[str]
        Column to plot on the x axis and the columns to plot on the y axis.
    title, xlabel, ylabel : str
        Plot annotations (labels include units).
    output_dir : Path
        Destination directory (created if missing).
    caption : str, optional
        Small-font caption under the plot (used to carry the physics caveat).

    Returns
    -------
    tuple[Path, Path]
        ``(csv_path, png_path)``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{name}.csv"
    png_path = output_dir / f"{name}.png"
    df.to_csv(csv_path, index=False)
    _save_plot(df, x_col, y_cols, title, xlabel, ylabel, png_path, caption=caption)
    return csv_path, png_path


def run_all(p: DesignParameters | None = None, output_dir: Path = DEFAULT_OUTPUT_DIR) -> list[Path]:
    """Run every sweep with default ranges and write all CSVs + PNGs.

    Parameters
    ----------
    p : DesignParameters, optional
        Base design; defaults to :class:`DesignParameters`.
    output_dir : Path
        Destination directory for the generated files.

    Returns
    -------
    list[Path]
        All files written (CSVs and PNGs), in creation order.
    """
    p = p or default_design()
    output_dir = Path(output_dir)
    written: list[Path] = []

    csv, png = write_sweep(
        sweep_voltage(p),
        "sweep_voltage",
        "V_op_kV",
        [labelled("thrust_gf"), labelled("efficiency_N_per_kW")],
        "Thrust and efficiency vs operating voltage (UPPER BOUNDS)",
        "V_op [kV]",
        "thrust [gf] / efficiency [N/kW] - UPPER BOUNDS, real values are lower",
        output_dir=output_dir,
        caption=UPPER_BOUND_CAVEAT,
    )
    written += [csv, png]

    csv, png = write_sweep(
        sweep_wire_radius(p),
        "sweep_wire_radius",
        "r_wire_um",
        ["V_onset_kV"],
        "Corona inception voltage vs wire radius",
        "r_wire [um]",
        "V_onset [kV]",
        output_dir=output_dir,
    )
    written += [csv, png]

    csv, png = write_sweep(
        sweep_gap(p),
        "sweep_gap",
        "d_gap_mm",
        ["mean_gap_breakdown_margin", "corona_onset_margin"],
        "Mean-gap-field breakdown and corona-onset margins vs gap",
        "d_gap [mm]",
        "margin [dimensionless]",
        output_dir=output_dir,
        caption="mean_gap_breakdown_margin = 3 MV/m / (V/d); corona_onset_margin = V_op / V_onset.",
    )
    written += [csv, png]

    csv, png = write_sweep(
        sweep_frequency(p),
        "sweep_frequency",
        "f_sw_kHz",
        ["droop_pct"],
        "CW voltage droop vs switching frequency",
        "f_sw [kHz]",
        "droop [% of V_op]",
        output_dir=output_dir,
        caption=K_GEO_BAND_CAVEAT,
    )
    written += [csv, png]

    csv, png = write_sweep(
        sweep_capacitance(p),
        "sweep_capacitance",
        "C_stage_nF",
        ["droop_pct"],
        "CW voltage droop vs per-stage capacitance",
        "C_stage [nF]",
        "droop [% of V_op]",
        output_dir=output_dir,
        caption=K_GEO_BAND_CAVEAT,
    )
    written += [csv, png]

    csv, png = write_sweep(
        sweep_stages(p),
        "sweep_stages",
        "N_stages",
        ["droop_pct", "ripple_Vpp"],
        "CW droop and ripple vs stage count",
        "N stages",
        "droop [%] / ripple [Vpp]",
        output_dir=output_dir,
        caption=K_GEO_BAND_CAVEAT,
    )
    written += [csv, png]

    return written


def main() -> None:
    """Run all sweeps to ``artifacts/07_Outputs/`` and summarise the files written."""
    p = default_design()
    written = run_all(p, DEFAULT_OUTPUT_DIR)
    print("=== EHD PSU parameter sweeps ===")
    print(
        f"Base design: r_wire={p.r_wire_m * 1e6:.0f} um, d={p.d_gap_m * 1e3:.0f} mm, "
        f"L={p.L_wire_m * 1e2:.0f} cm, V_op={p.V_op / 1e3:.0f} kV, "
        f"f_sw={p.f_sw / 1e3:.0f} kHz, N={p.N_stages}, C={p.C_stage * 1e9:.1f} nF"
    )
    print(f"Wrote {len(written)} files to {DEFAULT_OUTPUT_DIR}/:")
    for f in written:
        print(f"  {f}")
    print("\nCAVEAT: " + UPPER_BOUND_CAVEAT)


if __name__ == "__main__":
    main()
