"""SPICE netlist artifact generator for the EHD PSU driver chain.

Run with::

    python -m ehdpsu.spice

This module **generates a text SPICE netlist** (``.cir``, LTspice/ngspice
compatible) and, optionally, a minimal LTspice schematic (``.asc``) for the full
driver chain of the benchtop EHD thruster:

* an **LLC half-bridge primary**: two switches driven by complementary PULSE
  gate sources at ``f_sw`` with a dead-time, a resonant tank (``Lr``/``Cr``) and
  a magnetizing inductance (``Lm``);
* the **PQ26/20 high-frequency transformer** modelled as coupled inductors with
  an explicit ``K L_pri L_sec <k>`` mutual-coupling statement (leakage is
  represented by the series ``Lr`` on the primary), a **secondary
  self-capacitance lump** ``C_sec`` across the secondary winding, and an
  interwinding-capacitance note;
* a **5-stage Cockcroft-Walton ladder** built from diodes and 1 nF capacitors
  with a realistic ultrafast HV rectifier ``.model``;
* the **non-linear EHD behavioral load** emitted as a reusable ``.subckt
  EHD_LOAD``: a B-source current source reproducing the Townsend quadratic law
  ``I = k * V * (V - V_onset)`` for ``V > V_onset`` (else 0), using the **same**
  ``k`` and ``V_onset`` numbers as :mod:`ehdpsu.physics` for the default design.

Why this is an *artifact*, not a sandbox simulation
---------------------------------------------------
LTspice and QSPICE are GUI / Windows tools and cannot run in this headless
sandbox. This module therefore only *writes the netlist text* for the user to
open and simulate locally. Nothing here executes a SPICE engine, and the test
suite validates the netlist by **parsing its text** (structural assertions),
never by running it.

Physics honesty
---------------
The EHD load numbers are **not invented**: ``k`` and ``V_onset`` come straight
from :mod:`ehdpsu.physics` (``geometric_constant_parallel_plate`` and
``corona_inception_voltage`` for the default :class:`DesignParameters`). The
behavioral source is a **static** approximation of the quadratic Townsend
corona law: it captures the steady-state I-V curve only and models no plasma
dynamics (no ion transit lag, no streamer/spark transition, no frequency
dependence). This caveat is written into the netlist as a comment.

References
----------
* Townsend quadratic corona-current law; Kuffel & Zaengl, *High Voltage
  Engineering: Fundamentals* (corona current, Cockcroft-Walton cascade).
* Steigerwald, "A comparison of half-bridge resonant converter topologies",
  IEEE Trans. Power Electron., 1988 (LLC resonant tank).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import physics, profile
from .physics import DesignParameters, default_design
from .profile import Profile

# Default output directory for generated netlist solver inputs.
#
# Tracked, for the same reason as in :mod:`ehdpsu.femm`: the netlist is a small,
# deterministic text deliverable a public cloner needs to run LTspice or QSPICE locally.
# Generated *data* goes to the untracked datacenter under ``artifacts/``.
DEFAULT_ARTIFACT_DIR = Path("solver_inputs")

# Static-approximation caveat, embedded verbatim in the generated netlist.
STATIC_APPROX_CAVEAT = (
    "EHD load is a STATIC approximation of the quadratic Townsend corona law "
    "I = k*V*(V - V_onset); it models the steady-state I-V curve only, with NO "
    "plasma dynamics (no ion transit lag, no streamer/spark transition, no "
    "frequency dependence). k and V_onset come from ehdpsu.physics."
)


@dataclass(frozen=True)
class SpiceParams:
    """Parameters for the generated LLC + transformer + CW netlist.

    Defaults are documented order-of-magnitude values consistent with a PQ26/20
    ferrite core driving a 5-stage Cockcroft-Walton multiplier for an ~80-120 W
    burst target. They are engineering starting points for local simulation, not
    calibrated measurements.

    Attributes
    ----------
    v_bus : float
        Half-bridge DC bus voltage [V]. ~400 V PFC/bulk rail is typical for an
        offline LLC front end.
    lr_h : float
        Resonant (series) inductance [H]. Also represents transformer primary
        leakage in this lumped model.
    cr_f : float
        Resonant (series) capacitance [F].
    lm_h : float
        Magnetizing inductance of the primary [H]. For an LLC, Lm/Lr ~ 3-10;
        the default gives a moderate ratio for a PQ26/20 gapped core.
    l_sec_h : float
        Secondary self-inductance [H], set by ``lm_h * turns_ratio**2`` if left
        at the sentinel ``0.0`` (see :func:`__post_init__`-style resolution in
        :func:`build_netlist`).
    k_coupling : float
        Mutual coupling coefficient for the ``K L_pri L_sec`` statement
        (dimensionless, 0 < k < 1). ~0.98 is realistic for a well-coupled but
        not perfect HF transformer; the remaining leakage is lumped into Lr.
    c_sec_f : float
        Secondary self-capacitance lump [F], placed across the secondary. HF HV
        windings on a PQ26/20 typically show tens of pF.
    turns_ratio : float
        Secondary:primary turns ratio (step-up). The CW ladder further
        multiplies the rectified secondary voltage.
    deadtime_frac : float
        Dead-time as a fraction of the switching period (per edge).
    diode_bv : float
        HV rectifier reverse breakdown / Vrrm [V].
    diode_cjo : float
        HV rectifier zero-bias junction capacitance [F] (small = fast, low
        charge-storage part).
    diode_rs : float
        HV rectifier series resistance [ohm].
    diode_tt : float
        HV rectifier transit time [s] (reverse-recovery proxy; ultrafast parts
        have very small tt).
    diode_is : float
        HV rectifier saturation current [A].
    diode_n : float
        HV rectifier emission coefficient.
    """

    # NO DEFAULTS, and NO ``f_sw_hz``. Both were second homes for design values.
    #
    # ``f_sw_hz`` duplicated ``DesignParameters.f_sw``, and ``build_netlist`` reconciled them by
    # silently overwriting whichever one the caller passed in ``sp``. Silently reconciling a
    # disagreement is worse than reporting it, so the field is gone rather than defended: the
    # switching frequency now has exactly one home, the profile's ``f_sw_Hz``, reached through
    # ``DesignParameters.f_sw``.
    v_bus: float
    lr_h: float
    cr_f: float
    lm_h: float
    l_sec_h: float
    k_coupling: float
    c_sec_f: float
    turns_ratio: float
    deadtime_frac: float
    diode_bv: float
    diode_cjo: float
    diode_rs: float
    diode_tt: float
    diode_is: float
    diode_n: float

    @classmethod
    def from_profile(cls, prof: Profile) -> SpiceParams:
        """Build netlist parameters from a spec-scope-profile.

        ``l_sec_h`` keeps its ``0.0`` sentinel here because :func:`build_netlist` still reads it
        that way; the profile stores an explicit ``null`` instead, which cannot be mistaken for a
        real inductance. The translation happens here, at the boundary, rather than the profile
        carrying a sentinel it would then have to explain.

        This is the only populating constructor; the dataclass has no defaults.
        """
        l_sec = prof.value("L_sec_H")
        return cls(
            v_bus=prof.required("V_bus_V"),
            lr_h=prof.required("L_r_H"),
            cr_f=prof.required("C_r_F"),
            lm_h=prof.required("L_m_H"),
            l_sec_h=0.0 if l_sec is None else float(l_sec),
            k_coupling=prof.required("k_coupling"),
            c_sec_f=prof.required("C_sec_F"),
            turns_ratio=prof.required("turns_ratio_sec_per_pri"),
            deadtime_frac=prof.required("deadtime_frac"),
            diode_bv=prof.required("diode_BV_V"),
            diode_cjo=prof.required("diode_Cjo_F"),
            diode_rs=prof.required("diode_Rs_ohm"),
            diode_tt=prof.required("diode_tt_s"),
            diode_is=prof.required("diode_Is_A"),
            diode_n=prof.required("diode_n"),
        )


def default_spice_params() -> SpiceParams:
    """Return netlist parameters from the default profile. Reads a file; the name says so."""
    return SpiceParams.from_profile(profile.default_profile())


@dataclass(frozen=True)
class EhdLoadModel:
    """Resolved EHD behavioral-load numbers for the netlist.

    These are taken directly from :mod:`ehdpsu.physics` for a given
    :class:`DesignParameters`; nothing is fitted.

    Attributes
    ----------
    k : float
        Current-law prefactor [A/V^2] (parallel-plate, labeled model parameter).
    v_onset : float
        Corona-inception voltage [V].
    """

    k: float
    v_onset: float


def ehd_load_model(p: DesignParameters | None = None) -> EhdLoadModel:
    """Return the EHD load ``k`` and ``V_onset`` for the given design.

    Both numbers are computed by :mod:`ehdpsu.physics` (never invented):
    ``V_onset`` via Peek's field + coaxial integration, and ``k`` via the
    labeled parallel-plate prefactor. This is the single source of truth shared
    between the analytical core and the SPICE artifact.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters` (original targets).

    Returns
    -------
    EhdLoadModel
        The resolved ``k`` [A/V^2] and ``v_onset`` [V].
    """
    p = p or default_design()
    e_peek = physics.peek_inception_field(p.r_wire_m, p.delta, p.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, p.r_wire_m, p.d_gap_m)
    k = physics.geometric_constant_parallel_plate(physics.EPS0, p.mu_ion, p.L_wire_m, p.d_gap_m)
    return EhdLoadModel(k=k, v_onset=v_onset)


def _eng(value: float) -> str:
    """Format a float for SPICE using a compact, unambiguous representation.

    SPICE is case-insensitive and does not understand Python's ``e`` only when
    ambiguous with the ``e`` (exa? no) suffix, so we emit explicit scientific
    notation (e.g. ``2.7668749999999996e-12``) which every SPICE dialect parses
    as a plain floating-point number. Full precision is preserved so the netlist
    matches the physics core exactly.
    """
    return repr(float(value))


def _ehd_subckt(model: EhdLoadModel) -> list[str]:
    """Return the ``.subckt EHD_LOAD`` lines for the behavioral current source.

    The subcircuit has two pins, ``hv`` (anode / high side) and ``gnd``. It
    draws current ``I = k*V*(V - V_onset)`` for ``V > V_onset`` and 0 otherwise,
    where ``V = V(hv,gnd)``. Implemented as an ngspice/LTspice ``B`` behavioral
    current source with a ternary guard so it never sources current below onset.
    """
    k_str = _eng(model.k)
    v_onset_str = _eng(model.v_onset)
    return [
        "* ---------------------------------------------------------------",
        "* EHD behavioral load (reusable subcircuit)",
        "* Quadratic Townsend corona law: I = k*V*(V - V_onset), V>V_onset.",
        f"* {STATIC_APPROX_CAVEAT}",
        f"* k       = {k_str} A/V^2  (parallel-plate, labeled model parameter)",
        f"* V_onset = {v_onset_str} V",
        "* Pins: hv = emitter/high-voltage node, gnd = collector/return.",
        "* ---------------------------------------------------------------",
        ".subckt EHD_LOAD hv gnd",
        f".param k={k_str} Vonset={v_onset_str}",
        "* B-source: current flows hv->gnd (loads the CW output) only above onset.",
        ("Behd hv gnd I = (V(hv,gnd) > Vonset) ? " "(k*V(hv,gnd)*(V(hv,gnd) - Vonset)) : 0"),
        ".ends EHD_LOAD",
    ]


def _llc_primary(sp: SpiceParams, f_sw_hz: float) -> list[str]:
    """Return the LLC half-bridge primary netlist lines.

    Two switches (high-side ``M1``, low-side ``M2``) modelled as voltage-
    controlled switches driven by complementary PULSE gate sources at ``f_sw``
    with a per-edge dead-time. The resonant tank is the series ``Lr``/``Cr`` and
    the magnetizing inductance ``Lm`` sits across the transformer primary.

    ``f_sw_hz`` is passed in rather than read from ``sp``, because the switching frequency lives in
    the profile once and reaches here through ``DesignParameters.f_sw``.
    """
    period = 1.0 / f_sw_hz
    deadtime = sp.deadtime_frac * period
    # Complementary ~50% duty gate drives with dead-time on both edges.
    half = period / 2.0
    on = half - 2.0 * deadtime
    trise = deadtime
    tfall = deadtime
    # High-side turns on at t=0; low-side is delayed by half a period.
    return [
        "* ---------------------------------------------------------------",
        "* LLC half-bridge primary",
        (
            f"* f_sw = {f_sw_hz:.0f} Hz, period = {_eng(period)} s, "
            f"dead-time = {_eng(deadtime)} s/edge."
        ),
        "* Ref: Steigerwald, IEEE TPEL 1988 (LLC resonant tank).",
        "* ---------------------------------------------------------------",
        f"Vbus vbus 0 DC {_eng(sp.v_bus)}",
        "* Complementary gate drives (PULSE) with dead-time.",
        (f"Vg_hi ghi 0 PULSE(0 12 0 {_eng(trise)} {_eng(tfall)} " f"{_eng(on)} {_eng(period)})"),
        (
            f"Vg_lo glo 0 PULSE(0 12 {_eng(half)} {_eng(trise)} {_eng(tfall)} "
            f"{_eng(on)} {_eng(period)})"
        ),
        "* High-side and low-side switches (voltage-controlled switches).",
        "M1 vbus ghi sw SW",
        "M2 sw glo 0 SW",
        ".model SW SW(Ron=0.05 Roff=1e9 Vt=6 Vh=0.5)",
        "* Resonant tank: series Lr (also lumps primary leakage) + Cr.",
        f"Lr sw nr {_eng(sp.lr_h)}",
        f"Cr nr pri_p {_eng(sp.cr_f)}",
        "* Magnetizing inductance across the primary winding.",
        f"Lm pri_p 0 {_eng(sp.lm_h)}",
    ]


def _transformer(sp: SpiceParams) -> list[str]:
    """Return the coupled-inductor transformer lines with the K statement.

    The primary winding ``L_pri`` and secondary winding ``L_sec`` are coupled by
    an explicit ``K L_pri L_sec <k_coupling>`` mutual-inductance statement.
    Leakage is represented by the series ``Lr`` in the primary tank (see
    :func:`_llc_primary`). A ``C_sec`` lump models the secondary self-
    capacitance; interwinding capacitance is noted as a comment.
    """
    l_sec = sp.l_sec_h if sp.l_sec_h > 0 else sp.lm_h * sp.turns_ratio**2
    return [
        "* ---------------------------------------------------------------",
        "* PQ26/20 HF transformer as coupled inductors.",
        (
            f"* Turns ratio (sec:pri) = {_eng(sp.turns_ratio)}; "
            f"K coupling = {_eng(sp.k_coupling)}."
        ),
        "* Leakage inductance is represented by the series Lr in the tank.",
        "* NOTE: interwinding (primary-secondary) capacitance is a real HV",
        "* concern (couples switching noise + shifts resonance); model it by",
        "* adding a small C between pri_p and sec_p if you need common-mode",
        "* fidelity. Here we lump only the secondary self-capacitance C_sec.",
        "* ---------------------------------------------------------------",
        f"L_pri pri_p 0 {_eng(sp.lm_h)}",
        f"L_sec sec_p sec_n {_eng(l_sec)}",
        f"K_xfmr L_pri L_sec {_eng(sp.k_coupling)}",
        "* Secondary self-capacitance lump across the secondary winding.",
        f"C_sec sec_p sec_n {_eng(sp.c_sec_f)}",
        "* Secondary low side is the CW ladder ground reference.",
        "Rsec_gnd sec_n 0 1e-3",
    ]


def _cw_ladder(n_stages: int, c_stage_f: float) -> list[str]:
    """Return the N-stage Cockcroft-Walton ladder lines.

    Builds a classic half-wave (Greinacher/Villard) voltage-multiplier cascade:
    each stage adds two capacitors and two diodes. The AC drive is the
    transformer secondary node ``sec_p`` (relative to the ``sec_n`` ground
    reference). The DC output accumulates at node ``cw_out``.

    Parameters
    ----------
    n_stages : int
        Number of CW stages (each = 2 diodes + 2 capacitors).
    c_stage_f : float
        Per-stage capacitance [F], from the profile's ``C_stage_F``.

    Notes
    -----
    The capacitance was previously the literal ``"1n"`` here, with a comment stating that it
    matched ``DesignParameters.C_stage``. That comment was the only thing keeping the two in
    agreement, which is exactly the generated-netlist case ``profile-seam.md`` names: a design
    value living inside emitted text. It now comes from the profile, and is formatted with the
    same :func:`_eng` used for every other value in the netlist rather than a second formatter.

    The ``sp`` parameter was dropped at the same time: it was never read.
    """
    cap = _eng(c_stage_f)
    lines: list[str] = [
        "* ---------------------------------------------------------------",
        f"* {n_stages}-stage Cockcroft-Walton multiplier (half-wave cascade).",
        f"* Per-stage caps {cap} F, from the profile; ultrafast HV rectifier .model below.",
        "* ---------------------------------------------------------------",
    ]
    # AC input to the ladder is sec_p; the "column" nodes are built up per stage.
    # Standard half-wave CW: oscillating column (a-nodes tied to drive via caps),
    # rectified column (b-nodes) forming the smoothed DC stack.
    ac = "sec_p"
    prev_b = "sec_n"  # DC stack starts at the secondary return.
    for stage in range(1, n_stages + 1):
        a = f"cw_a{stage}"
        b = f"cw_b{stage}"
        # Coupling capacitor from the AC drive into this stage's oscillating node.
        lines.append(f"Cc{stage} {ac} {a} {cap}")
        # Diode D_odd conducts on one half-cycle: prev_b -> a.
        lines.append(f"Dd{stage}a {prev_b} {a} DHV")
        # Diode D_even conducts on the other half-cycle: a -> b (rectified stack).
        lines.append(f"Dd{stage}b {a} {b} DHV")
        # Smoothing capacitor on the rectified DC stack node.
        lines.append(f"Cs{stage} {b} {prev_b} {cap}")
        prev_b = b
    # The top of the DC stack is the multiplier output.
    lines.append(f"* CW DC output node: {prev_b}")
    lines.append(f"Rout {prev_b} cw_out 1")
    return lines


def _diode_model(sp: SpiceParams) -> list[str]:
    """Return the ``.model DHV D(...)`` line for the ultrafast HV rectifier.

    Represents a real fast HV rectifier (e.g. an axial 20 kV, sub-ns to few-ns
    recovery stack): high reverse breakdown ``BV``, small junction capacitance
    ``Cjo``, and a small transit time ``tt`` as a reverse-recovery proxy.
    """
    return [
        "* ---------------------------------------------------------------",
        "* Ultrafast HV rectifier model (e.g. 20 kV fast-recovery stack).",
        "* High BV (Vrrm), small Cjo (low charge storage), small tt.",
        "* REVERSE-RECOVERY NOTE: real HV stacks show finite trr; tt below is a",
        "* first-order proxy. For hard-switched CW ripple studies, refine tt/Cjo",
        "* from the chosen part's datasheet (trr, Qrr) before trusting losses.",
        "* ---------------------------------------------------------------",
        (
            f".model DHV D(IS={_eng(sp.diode_is)} N={_eng(sp.diode_n)} "
            f"RS={_eng(sp.diode_rs)} BV={_eng(sp.diode_bv)} "
            f"CJO={_eng(sp.diode_cjo)} TT={_eng(sp.diode_tt)})"
        ),
    ]


def build_netlist(
    p: DesignParameters | None = None,
    sp: SpiceParams | None = None,
) -> str:
    """Assemble and return the full ``.cir`` netlist as a single string.

    Combines the LLC primary, coupled-inductor transformer (with the ``K``
    statement and ``C_sec`` lump), the 5-stage (by default) Cockcroft-Walton
    ladder, the ultrafast HV rectifier ``.model``, and the reusable
    ``EHD_LOAD`` subcircuit instantiated across the multiplier output.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters`. Supplies ``f_sw``,
        ``N_stages`` and the EHD load ``k`` / ``V_onset``.
    sp : SpiceParams, optional
        Netlist parameters; defaults to the profile's driver and rectifier sections. It no longer
        carries a switching frequency: that lived in two places and was silently reconciled here,
        and now lives once in the profile.

    Returns
    -------
    str
        The complete netlist text (newline-terminated).
    """
    p = p or default_design()
    sp = sp or default_spice_params()
    model = ehd_load_model(p)

    lines: list[str] = [
        "* ===============================================================",
        "* EHD PSU driver-chain netlist (LLC + PQ26/20 xfmr + CW + EHD load)",
        "* Generated by ehdpsu.spice -- open locally in LTspice/QSPICE/ngspice.",
        "* This file is an ARTIFACT: it is NOT executed in the build sandbox.",
        (
            f"* Design: V_op={p.V_op / 1e3:.0f} kV, f_sw={p.f_sw / 1e3:.0f} kHz, "
            f"N_stages={p.N_stages}, C_stage={p.C_stage * 1e9:.0f} nF."
        ),
        "* Target: single EHD cell, ~80-120 W, 3-5 s bursts.",
        "* ===============================================================",
        "",
    ]
    lines += _llc_primary(sp, p.f_sw)
    lines.append("")
    lines += _transformer(sp)
    lines.append("")
    lines += _diode_model(sp)
    lines.append("")
    lines += _cw_ladder(p.N_stages, p.C_stage)
    lines.append("")
    lines += _ehd_subckt(model)
    lines.append("")
    lines += [
        "* ---------------------------------------------------------------",
        "* Instantiate the EHD load across the CW multiplier output.",
        "* ---------------------------------------------------------------",
        "Xload cw_out 0 EHD_LOAD",
        "",
        "* Suggested analysis (uncomment locally):",
        "* .tran 1n 200u uic",
        "* .probe",
        ".end",
        "",
    ]
    return "\n".join(lines)


def build_asc(p: DesignParameters | None = None, sp: SpiceParams | None = None) -> str:
    """Return a minimal LTspice schematic (``.asc``) referencing the netlist.

    LTspice ``.asc`` files are a proprietary line-based format. Rather than
    fabricate a full graphical schematic (which risks silent incompatibility),
    this emits a tiny valid ``.asc`` header plus SPICE-directive text blocks so
    the user has an LTspice-openable stub. The authoritative artifact is the
    ``.cir`` netlist; the ``.asc`` is a convenience wrapper.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters`.
    sp : SpiceParams, optional
        Netlist parameters; defaults to :class:`SpiceParams`.

    Returns
    -------
    str
        LTspice ``.asc`` text.
    """
    p = p or default_design()
    sp = sp or default_spice_params()
    model = ehd_load_model(p)
    header = [
        "Version 4",
        "SHEET 1 1600 1080",
        "* LTspice schematic stub generated by ehdpsu.spice.",
        "* The authoritative circuit is solver_inputs/ehd_llc_cw.cir; load it via",
        "* a .include directive or paste the netlist into an LTspice .cir run.",
    ]
    # Embed the key directives as TEXT elements so they are visible in LTspice.
    notes = [
        (
            f"TEXT 48 48 Left 2 ;EHD PSU: LLC + PQ26/20 xfmr (K={_eng(sp.k_coupling)}) "
            f"+ {p.N_stages}-stage CW + EHD_LOAD"
        ),
        f"TEXT 48 96 Left 2 !.param k={_eng(model.k)} Vonset={_eng(model.v_onset)}",
        "TEXT 48 144 Left 2 !.include ehd_llc_cw.cir",
    ]
    return "\n".join(header + notes) + "\n"


def write_artifacts(
    p: DesignParameters | None = None,
    sp: SpiceParams | None = None,
    output_dir: Path = DEFAULT_ARTIFACT_DIR,
    write_asc: bool = True,
) -> list[Path]:
    """Write the ``.cir`` (and optionally ``.asc``) artifact(s) to ``output_dir``.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters`.
    sp : SpiceParams, optional
        Netlist parameters; defaults to :class:`SpiceParams`.
    output_dir : Path
        Destination directory (created if missing).
    write_asc : bool
        Also write the LTspice ``.asc`` stub when True.

    Returns
    -------
    list[Path]
        The files written, in creation order.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    cir_path = output_dir / "ehd_llc_cw.cir"
    cir_path.write_text(build_netlist(p, sp), encoding="utf-8")
    written.append(cir_path)

    if write_asc:
        asc_path = output_dir / "ehd_llc_cw.asc"
        asc_path.write_text(build_asc(p, sp), encoding="utf-8")
        written.append(asc_path)

    return written


def main() -> None:
    """Write the netlist artifact(s) and print their paths plus a mapping note."""
    p = default_design()
    sp = default_spice_params()
    model = ehd_load_model(p)
    written = write_artifacts(p, sp, DEFAULT_ARTIFACT_DIR, write_asc=True)

    print("=== EHD PSU SPICE netlist generation ===")
    print(
        f"Design: V_op={p.V_op / 1e3:.0f} kV, f_sw={p.f_sw / 1e3:.0f} kHz, "
        f"N_stages={p.N_stages}, C_stage={p.C_stage * 1e9:.0f} nF"
    )
    print(f"EHD load: k={_eng(model.k)} A/V^2, V_onset={_eng(model.v_onset)} V")
    print(f"Wrote {len(written)} artifact(s):")
    for f in written:
        print(f"  {f}")
    print("\nHow the model maps to real parts:")
    print(
        f"  - K statement (K_xfmr L_pri L_sec {_eng(sp.k_coupling)}): the "
        "PQ26/20 winding coupling. Lowering it toward 0.95 increases modeled "
        "leakage; the series Lr in the tank carries the leakage that shapes the "
        "LLC resonance."
    )
    print(
        f"  - C_sec ({sp.c_sec_f * 1e12:.0f} pF across the secondary): the HV "
        "winding self-capacitance. Measure it on the real transformer (or "
        "estimate from turns/geometry); it detunes the tank and rounds the CW "
        "drive edges."
    )
    print(
        f"  - DHV .model (BV={sp.diode_bv / 1e3:.0f} kV, Cjo={sp.diode_cjo * 1e12:.1f} pF, "
        f"tt={sp.diode_tt * 1e9:.1f} ns): pick a real ultrafast HV rectifier and "
        "refine BV/Cjo/tt from its datasheet (Vrrm, junction C, trr/Qrr)."
    )
    print("\nCAVEAT: " + STATIC_APPROX_CAVEAT)
    print(
        "NOTE: LTspice/QSPICE are GUI tools; this is a generated netlist "
        "artifact to open locally, not a sandbox-run simulation."
    )


if __name__ == "__main__":
    main()
