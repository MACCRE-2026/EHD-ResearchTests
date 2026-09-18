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


def test_readback_is_computed_not_merely_documented(lua: str) -> None:
    """The script COMPUTES and prints both readings, rather than describing where to click.

    Strengthened 2026-09-16, after the script's first-ever run in FEMM. This test previously
    asserted that the prose contained the strings ``2 * W / V_op^2`` and ``Q / V_op`` — that is,
    that the script *told the operator* how to read the values by hand. It passed for the entire
    life of a script that **could not solve at all**, which is the point: a test over generated text
    cannot see whether the tool accepts it.

    Reading by hand is also where a transcription error enters. So the requirement is now the
    stronger one: the script performs both capacitance routes itself and prints them, and it prints
    the field. A ratio between the two routes is printed as well, because they are a cross-check and
    a disagreement is a finding rather than a choice.
    """
    assert "capacitance" in lua.lower()

    # Route (a), stored energy, computed rather than described.
    assert "eo_blockintegral(0)" in lua, "the stored-energy integral is not performed"
    assert "C_from_energy" in lua

    # Route (b), emitter charge. Note the PLURAL function name: eo_getconductorproperty, which
    # this script named for months, does not exist in FEMM.
    assert "eo_getconductorproperties" in lua, "the conductor-charge route is not performed"
    assert "eo_getconductorproperty(" not in lua, (
        "the script calls eo_getconductorproperty (singular), which is not a FEMM function; "
        "the name is eo_getconductorproperties"
    )
    assert "C_from_charge" in lua

    # The two routes are compared, not silently reconciled.
    assert "route ratio" in lua

    # The field is probed, and at more than one radius so the reading's sensitivity is visible.
    assert "eo_getpointvalues" in lua
    assert lua.count("probe_ring(") >= 4, (
        "the surface field is sampled at fewer than three radii, so the reading is reported "
        "without the spread that quantifies it"
    )

    # Field cross-check against Peek's analytical prediction.
    assert "E_peek" in lua


def test_the_script_does_not_invite_the_invalid_peek_comparison(lua: str) -> None:
    """The script must not tell anyone to compare its field directly against ``E_peek``.

    Added 2026-09-16, immediately after the first successful run. The script had said, for its whole
    life, that "the peak wire-surface |E| should be close to the analytical E_peek". That is a
    **category error**: the script applies ``V_op``, while ``E_peek`` is the surface field **at
    onset**. On the MK0 geometry the two differ by a factor of about 7.4, so an operator following
    that sentence would have reported a catastrophic disagreement where there is none — a
    manufactured false alarm, from documentation, in the artifact whose whole job is to be an
    independent check.

    Worse than a wrong number, because a wrong number gets questioned and a wrong *comparison* gets
    believed.

    The valid route exploits Laplace being linear in the applied voltage: one solve gives
    ``E_per_V``, onset is where ``E_surface == E_peek``, so ``V_onset_implied = E_peek / E_per_V``,
    and *that* is compared against the closed-form ``V_onset``.
    """
    lowered = lua.lower()
    assert "should be close to the analytical e_peek" not in lowered, (
        "the script still invites a direct comparison between its applied-voltage surface field "
        "and Peek's onset field"
    )
    # The valid comparison has to be spelled out, or the caveat above is just a prohibition.
    assert "v_onset_implied" in lowered, "the script does not state the valid comparison"
    assert "linear" in lowered, "the script does not say why one solve suffices"
    # And the capacitance comparison must name the image-charge form, not the coaxial one.
    assert "acosh(h/r)" in lua, "the capacitance cross-check does not name the acosh form"


def test_the_lua_is_written_for_the_dialect_femm_actually_embeds(lua: str) -> None:
    """FEMM 4.2 embeds Lua 4, where ``sqrt`` and ``format`` are globals.

    There is no ``math`` table and no ``string`` table, so ``math.sqrt(...)`` raises. FEMM's own
    readme refers to "the Lua format command", which is what established the dialect here. The
    script carries a shim that binds the globals from the Lua 5 tables when they are missing, so it
    runs under either — and that shim is the only place the table forms may appear.
    """
    for line in lua.splitlines():
        if "math." in line or "string." in line:
            assert line.strip().startswith("if not "), (
                f"Lua 5 table access outside the compatibility shim: {line.strip()!r}. FEMM 4.2 "
                f"embeds Lua 4 and has no math or string table."
            )
    assert "if not sqrt then" in lua, "no Lua 4/5 compatibility shim"


def test_every_enclosed_region_gets_a_block_label(lua: str) -> None:
    """Three closed regions, three labels. This is the defect that stopped the first run.

    FEMM refuses to solve with "Material properties have not been defined for all regions" if any
    region a closed boundary encloses has no block label. This geometry closes three, and the script
    placed one:

      * the main air region above the collector and outside the wire;
      * the wire interior — two 180-degree arcs form a closed circle;
      * the region below the collector — ``collector_hw`` equals ``outer_r``, so the plate's end
        nodes land on the side walls and partition the box.

    The count is asserted rather than the positions, because the positions are expressions in the
    generated script. A fourth region added later without a label fails here rather than in FEMM.
    """
    assert lua.count("ei_addblocklabel(") == 3, (
        f"{lua.count('ei_addblocklabel(')} block label(s) for three enclosed regions. FEMM will "
        f"refuse to solve, and the failure appears as a missing .res file when ei_loadsolution "
        f"finds no solution to load."
    )
    assert "ei_addblocklabel(0, 0)" in lua, "the wire interior has no block label"


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
