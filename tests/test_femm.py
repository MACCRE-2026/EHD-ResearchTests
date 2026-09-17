"""Tests for :mod:`ehdpsu.femm`.

These tests **parse the generated FEMM Lua script text** and assert on its
structure; they never launch FEMM (a Windows GUI tool unavailable in the
headless sandbox). They verify:

* the required electrostatics API calls are present (``newdocument(1)``,
  ``ei_probdef``, geometry primitives, ``ei_analyze``, ``ei_loadsolution``);
* the emitter and collector conductor properties are fixed at ``V_op`` and 0;
* the geometry parameters are substituted from :class:`DesignParameters`;
* the read-back guidance (max field, capacitance) is documented;
* the artifacts are written to disk (to a pytest ``tmp_path``).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest
from conftest import reference_design

from ehdpsu import femm, physics

P = reference_design()


@pytest.fixture
def lua() -> str:
    """The default-design FEMM Lua script text."""
    return femm.build_lua_script(P)


def test_newdocument_electrostatics(lua: str) -> None:
    """A new electrostatics document (mode 1) is created."""
    assert re.search(r"^\s*newdocument\(1\)", lua, re.MULTILINE)


def test_probdef_present_with_depth(lua: str) -> None:
    """ei_probdef sets millimetre units and uses the wire length as depth."""
    assert re.search(r'ei_probdef\(\s*"millimeters"\s*,\s*"planar"', lua)
    # depth variable is passed to probdef and set from L_wire (in mm).
    assert re.search(r"ei_probdef\([^)]*depth[^)]*\)", lua)
    depth_mm = P.L_wire_m * 1e3
    assert re.search(rf"^depth\s*=\s*{re.escape(repr(depth_mm))}", lua, re.MULTILINE)


def test_geometry_primitives_present(lua: str) -> None:
    """Node/segment/arc primitives draw the wire and collector."""
    assert "ei_addnode(" in lua
    assert "ei_addsegment(" in lua
    assert "ei_addarc(" in lua
    # Two 180-degree arcs form the circular wire cross-section.
    arcs = re.findall(r"ei_addarc\([^)]*,\s*180\s*,", lua)
    assert len(arcs) == 2


def test_air_material_and_boundary(lua: str) -> None:
    """Air material and a far-field boundary property are defined."""
    assert re.search(r'ei_addmaterial\(\s*"Air"\s*,\s*1\s*,\s*1', lua)
    assert re.search(r'ei_addboundprop\(\s*"FarField"', lua)


def test_conductor_props_at_vop_and_zero(lua: str) -> None:
    """Emitter conductor is fixed at V_op and the collector at 0 V."""
    assert re.search(r'ei_addconductorprop\(\s*"Emitter"\s*,\s*V_op\s*,', lua)
    assert re.search(r'ei_addconductorprop\(\s*"Collector"\s*,\s*0\s*,', lua)
    # V_op variable is set to the design operating voltage.
    assert re.search(rf"^V_op\s*=\s*{re.escape(repr(float(P.V_op)))}", lua, re.MULTILINE)


def test_analyze_and_loadsolution(lua: str) -> None:
    """The script solves (ei_analyze) and loads the solution (ei_loadsolution)."""
    assert "ei_analyze(" in lua
    assert "ei_loadsolution()" in lua
    assert "ei_zoomnatural()" in lua


def test_parameter_substitution(lua: str) -> None:
    """Wire radius and gap are substituted in millimetres from DesignParameters."""
    r_wire_mm = P.r_wire_m * 1e3
    d_gap_mm = P.d_gap_m * 1e3
    assert re.search(rf"^r_wire\s*=\s*{re.escape(repr(r_wire_mm))}", lua, re.MULTILINE)
    assert re.search(rf"^d_gap\s*=\s*{re.escape(repr(d_gap_mm))}", lua, re.MULTILINE)


def test_readback_guidance_present(lua: str) -> None:
    """The script documents how to read max field and cell capacitance."""
    assert "capacitance" in lua.lower()
    # Both capacitance routes are documented.
    assert "2 * W / V_op^2" in lua or "2*W" in lua
    assert "Q / V_op" in lua or "Q/V" in lua
    # Field cross-check against Peek's analytical prediction.
    assert "E_peek" in lua


def test_local_run_header_present(lua: str) -> None:
    """The header explains this must be opened/run in FEMM locally."""
    assert "RUN THIS IN FEMM" in lua.upper() or "run in femm" in lua.lower()
    assert "dofile(" in lua


def test_analytical_crosscheck_values_in_header(lua: str) -> None:
    """The header embeds the physics-core E_peek and V_onset (not fitted)."""
    e_peek = physics.peek_inception_field(P.r_wire_m, P.delta, P.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, P.r_wire_m, P.d_gap_m)
    assert repr(e_peek) in lua
    assert repr(v_onset) in lua


def test_geometry_scales_with_design() -> None:
    """A larger wire radius changes the substituted r_wire value."""
    p2 = dataclasses.replace(P, r_wire_m=50e-6)
    lua2 = femm.build_lua_script(p2)
    assert re.search(rf"^r_wire\s*=\s*{re.escape(repr(50e-6 * 1e3))}", lua2, re.MULTILINE)


def test_write_artifacts_creates_files(tmp_path: Path) -> None:
    """write_artifacts writes the Lua script and the geometry notes."""
    written = femm.write_artifacts(P, output_dir=tmp_path, write_notes=True)
    assert len(written) == 2
    lua_path = tmp_path / femm.DEFAULT_LUA_NAME
    notes_path = tmp_path / "ehd_wire_collector_geometry.txt"
    assert lua_path.exists() and lua_path.stat().st_size > 0
    assert notes_path.exists() and notes_path.stat().st_size > 0
    text = lua_path.read_text(encoding="utf-8")
    assert "newdocument(1)" in text


def test_write_artifacts_lua_only(tmp_path: Path) -> None:
    """write_notes=False writes only the Lua artifact."""
    written = femm.write_artifacts(P, output_dir=tmp_path, write_notes=False)
    assert len(written) == 1
    assert written[0].name == femm.DEFAULT_LUA_NAME
    assert not (tmp_path / "ehd_wire_collector_geometry.txt").exists()


def test_geometry_notes_reference_peek(tmp_path: Path) -> None:
    """The plain-text notes cross-reference the analytical Peek prediction."""
    notes = femm.build_geometry_notes(P)
    assert "Peek" in notes
    assert "capacitance" in notes.lower()
    assert "V_op" in notes
