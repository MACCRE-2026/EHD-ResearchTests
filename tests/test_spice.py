"""Tests for :mod:`ehdpsu.spice`.

These tests **parse the generated netlist text** and assert on its structure;
they never execute a SPICE engine (LTspice/QSPICE/ngspice are not available in
the headless sandbox). They verify:

* the coupled-inductor ``K`` mutual-coupling statement is present;
* the reusable ``.subckt EHD_LOAD`` carries the quadratic Townsend behavioral
  expression with ``k`` and ``V_onset`` numbers matching :mod:`ehdpsu.physics`
  for the default design;
* the ladder has exactly 5 Cockcroft-Walton stages (by diode and cap counts);
* the secondary self-capacitance element ``C_sec`` is present;
* a diode ``.model`` line is present;
* the artifacts are actually written to disk (to a pytest ``tmp_path``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ehdpsu import spice
from ehdpsu.physics import DesignParameters

P = DesignParameters()


@pytest.fixture
def netlist() -> str:
    """The default-design netlist text."""
    return spice.build_netlist(P, spice.SpiceParams())


def test_ehd_load_numbers_match_physics() -> None:
    """The SPICE EHD load k and V_onset equal the physics-core values."""
    import math

    from ehdpsu import physics

    e_peek = physics.peek_inception_field(P.r_wire_m, P.delta, P.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, P.r_wire_m, P.d_gap_m)
    k = physics.geometric_constant_parallel_plate(physics.EPS0, P.mu_ion, P.L_wire_m, P.d_gap_m)
    model = spice.ehd_load_model(P)
    assert math.isclose(model.k, k, rel_tol=0, abs_tol=0)
    assert math.isclose(model.v_onset, v_onset, rel_tol=0, abs_tol=0)


def test_k_coupling_statement_present(netlist: str) -> None:
    """A K coupled-inductor statement links the primary and secondary."""
    # Match e.g. "K_xfmr L_pri L_sec 0.98"
    pattern = re.compile(r"^K\S*\s+L_pri\s+L_sec\s+[0-9.eE+-]+\s*$", re.IGNORECASE | re.MULTILINE)
    assert pattern.search(netlist), "missing K L_pri L_sec coupling statement"


def test_secondary_self_capacitance_present(netlist: str) -> None:
    """A secondary self-capacitance element (C_sec) is across the secondary."""
    pattern = re.compile(r"^C_sec\s+\S+\s+\S+\s+[0-9.eEpfn+-]+", re.MULTILINE)
    assert pattern.search(netlist), "missing C_sec secondary self-capacitance"


def test_diode_model_present(netlist: str) -> None:
    """A diode .model line describes the ultrafast HV rectifier."""
    pattern = re.compile(r"^\.model\s+\S+\s+D\(", re.IGNORECASE | re.MULTILINE)
    assert pattern.search(netlist), "missing diode .model line"
    # Sanity: the HV rectifier has a high breakdown voltage in the model.
    assert re.search(r"BV=", netlist, re.IGNORECASE)


def test_exactly_five_cw_stages(netlist: str) -> None:
    """The ladder has exactly 5 CW stages: 10 diodes and 10 stage capacitors."""
    # Each stage emits two diodes (Dd<n>a, Dd<n>b) and two caps (Cc<n>, Cs<n>).
    diode_lines = re.findall(r"^Dd\d+[ab]\s", netlist, re.MULTILINE)
    coupling_caps = re.findall(r"^Cc\d+\s", netlist, re.MULTILINE)
    smoothing_caps = re.findall(r"^Cs\d+\s", netlist, re.MULTILINE)
    assert len(diode_lines) == 10, f"expected 10 CW diodes, got {len(diode_lines)}"
    assert len(coupling_caps) == 5, f"expected 5 coupling caps, got {len(coupling_caps)}"
    assert len(smoothing_caps) == 5, f"expected 5 smoothing caps, got {len(smoothing_caps)}"
    # Stage indices run 1..5 with no gaps.
    stage_nums = sorted({int(m) for m in re.findall(r"^Cc(\d+)\s", netlist, re.MULTILINE)})
    assert stage_nums == [1, 2, 3, 4, 5]


def test_ehd_subckt_present_with_quadratic_expression(netlist: str) -> None:
    """The .subckt EHD_LOAD implements I = k*V*(V - V_onset) above onset."""
    assert re.search(r"^\.subckt\s+EHD_LOAD\s+hv\s+gnd", netlist, re.MULTILINE)
    assert re.search(r"^\.ends\s+EHD_LOAD", netlist, re.MULTILINE)
    # Behavioral B-source with the guarded quadratic law.
    assert re.search(r"^Behd\s+hv\s+gnd\s+I\s*=", netlist, re.MULTILINE)
    assert "Vonset" in netlist
    assert re.search(r"k\s*\*\s*V\(hv,gnd\)\s*\*\s*\(V\(hv,gnd\)\s*-\s*Vonset\)", netlist)
    # The subckt declares the exact k / Vonset numbers from the physics core.
    model = spice.ehd_load_model(P)
    assert repr(model.k) in netlist
    assert repr(model.v_onset) in netlist


def test_static_approximation_caveat_present(netlist: str) -> None:
    """The netlist documents the static-approximation caveat."""
    assert "STATIC approximation" in netlist
    assert "no plasma dynamics" in netlist.lower()


def test_llc_primary_present(netlist: str) -> None:
    """The LLC primary has complementary PULSE gate drives and an Lr/Cr/Lm tank."""
    assert len(re.findall(r"PULSE\(", netlist)) == 2, "expected 2 complementary PULSE drives"
    assert re.search(r"^Lr\s", netlist, re.MULTILINE)
    assert re.search(r"^Cr\s", netlist, re.MULTILINE)
    assert re.search(r"^Lm\s", netlist, re.MULTILINE)


def test_write_artifacts_creates_files(tmp_path: Path) -> None:
    """write_artifacts writes both the .cir and .asc to the target directory."""
    written = spice.write_artifacts(P, spice.SpiceParams(), output_dir=tmp_path, write_asc=True)
    assert len(written) == 2
    cir = tmp_path / "ehd_llc_cw.cir"
    asc = tmp_path / "ehd_llc_cw.asc"
    assert cir.exists() and cir.stat().st_size > 0
    assert asc.exists() and asc.stat().st_size > 0
    # The .cir round-trips as the same structural content.
    text = cir.read_text(encoding="utf-8")
    assert ".subckt EHD_LOAD" in text
    assert text.rstrip().endswith(".end")


def test_write_artifacts_cir_only(tmp_path: Path) -> None:
    """write_asc=False writes only the .cir artifact."""
    written = spice.write_artifacts(P, spice.SpiceParams(), output_dir=tmp_path, write_asc=False)
    assert len(written) == 1
    assert written[0].name == "ehd_llc_cw.cir"
    assert not (tmp_path / "ehd_llc_cw.asc").exists()


def test_stage_count_follows_design_parameters() -> None:
    """Changing N_stages changes the generated ladder stage count."""
    import dataclasses

    p3 = dataclasses.replace(P, N_stages=3)
    netlist = spice.build_netlist(p3, spice.SpiceParams())
    diode_lines = re.findall(r"^Dd\d+[ab]\s", netlist, re.MULTILINE)
    assert len(diode_lines) == 6  # 3 stages x 2 diodes
