"""FEMM electrostatics input generator for the EHD wire-to-collector cell.

Run with::

    python -m ehdpsu.femm

This module **generates a FEMM Lua script** (``solver_inputs/ehd_wire_collector.lua``)
that draws the 2-D cross-section of the single EHD thruster cell (a circular
tungsten emitter wire facing a flat collector) and sets up a FEMM electrostatics
problem parameterized from :class:`ehdpsu.physics.DesignParameters` (wire radius,
gap, and wire length as the out-of-plane depth). It optionally also emits a
plain-text geometry + expected-outputs description so the user can cross-check
FEMM's reported maximum surface field against the analytical Peek prediction and
read off the cell capacitance.

Why this is an *artifact*, not a sandbox simulation
---------------------------------------------------
FEMM is a Windows GUI tool (driven by a Lua console / pyFEMM) and cannot run in
this headless sandbox. This module therefore only *writes the Lua script text*
for the user to open and run locally in FEMM. Nothing here launches FEMM, and
the test suite validates the script by **parsing its text** (structural
assertions on the required API calls and parameter substitution), never by
running it.

FEMM electrostatics API used
-----------------------------
The generated script uses the standard FEMM electrostatics (``ei_*``) Lua API:

* ``newdocument(1)`` opens a new electrostatics document (mode 1);
* ``ei_probdef`` sets the problem definition (units, planar, depth, precision);
* ``ei_addnode`` / ``ei_addsegment`` / ``ei_addarc`` draw the emitter-wire
  circle and the collector plate + outer air boundary;
* ``ei_addboundprop`` defines the far-field / Dirichlet boundary;
* ``ei_addmaterial`` defines air (relative permittivity 1);
* ``ei_addconductorprop`` fixes the wire conductor at ``V_op`` and the collector
  conductor at ``0`` V;
* ``ei_analyze`` / ``ei_loadsolution`` solve and load the result;
* trailing comments show how to read the maximum surface field (line-integral /
  point values) and the cell capacitance (from stored energy or conductor
  charge, ``C = 2*W/V^2`` or ``C = Q/V``).

Physics honesty
---------------
The geometry and the wire potential come straight from
:class:`ehdpsu.physics.DesignParameters`; nothing is fitted. The header comment
tells the user to compare FEMM's peak wire-surface field with
:func:`ehdpsu.physics.peek_inception_field` (the two should agree to within the
usual meshing / geometry-idealization tolerance) and warns that FEMM computes
the electrostatic (Laplace) field with no space charge, so it predicts the
*onset* field, not the loaded operating field.

References
----------
* D. Meeker, *Finite Element Method Magnetics: Electrostatics Tutorial* and the
  FEMM 4.2 Lua scripting reference (``ei_*`` command set).
* F. W. Peek, *Dielectric Phenomena in High Voltage Engineering*, 1929
  (surface-field cross-check).
"""

from __future__ import annotations

from pathlib import Path

from . import physics
from .physics import DesignParameters, default_design

# Default output directory for generated FEMM solver inputs.
#
# This is a **tracked** directory, deliberately: the generated Lua geometry and its
# companion notes are small, deterministic text deliverables that a public cloner needs
# in order to run FEMM locally. They are regenerable, and a test regenerates and diffs
# them, so tracking them cannot drift silently.
#
# Generated *data* (CSVs, plots, solver run output) goes to the untracked project
# datacenter under ``artifacts/`` instead. Inputs are tracked; outputs are not.
DEFAULT_ARTIFACT_DIR = Path("solver_inputs")

# Default FEMM artifact filename.
DEFAULT_LUA_NAME = "ehd_wire_collector.lua"

# Laplace-vs-loaded caveat, embedded verbatim in the generated script header.
LAPLACE_CAVEAT = (
    "FEMM solves the electrostatic (Laplace) field with NO space charge, so the "
    "peak wire-surface field it reports is the CORONA-ONSET field to compare "
    "against Peek's law, not the loaded operating field (ion space charge lowers "
    "the near-wire field once current flows)."
)


def _num(value: float) -> str:
    """Format a float for embedding in Lua source at full precision.

    Lua parses standard floating-point / scientific notation, so ``repr`` gives
    a round-trippable literal that keeps the artifact numerically identical to
    the design parameters.
    """
    return repr(float(value))


def build_lua_script(p: DesignParameters | None = None) -> str:
    """Assemble and return the FEMM electrostatics Lua script as a string.

    The script draws (in FEMM's millimetre length units) a circular emitter wire
    of radius ``r_wire`` centred at the origin, a flat collector plate a distance
    ``d_gap`` below the wire surface, and an outer semicircular air boundary held
    at a fixed potential (open-boundary approximation). The wire conductor is
    fixed at ``V_op`` and the collector conductor at ``0`` V. The out-of-plane
    depth is the wire length ``L_wire`` so FEMM's per-metre results scale to the
    real cell.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters` (original targets).

    Returns
    -------
    str
        The complete FEMM Lua script text (newline-terminated).
    """
    p = p or default_design()

    # Analytical cross-check numbers (computed, never fitted).
    e_peek = physics.peek_inception_field(p.r_wire_m, p.delta, p.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, p.r_wire_m, p.d_gap_m)

    # Work in millimetres inside FEMM (ei_probdef "millimeters").
    r_wire_mm = p.r_wire_m * 1e3
    d_gap_mm = p.d_gap_m * 1e3
    depth_mm = p.L_wire_m * 1e3
    # Outer air-boundary radius: generously larger than the gap so the open
    # boundary does not distort the near-wire field.
    outer_r_mm = max(d_gap_mm * 10.0, r_wire_mm * 2000.0)
    # Wire is centred at the origin; the collector plate sits d_gap below the
    # bottom of the wire (i.e. at y = -(r_wire + d_gap)).
    collector_y_mm = -(r_wire_mm + d_gap_mm)
    # Collector plate half-width: wide relative to the gap (approximates a plane).
    collector_hw_mm = max(d_gap_mm * 5.0, outer_r_mm)

    v_op = p.V_op

    lines: list[str] = [
        "-- ===============================================================",
        "-- EHD wire-to-collector electrostatics (FEMM Lua script)",
        "-- Generated by ehdpsu.femm -- OPEN AND RUN THIS IN FEMM LOCALLY.",
        "--",
        "-- FEMM is a Windows GUI/Lua tool and is NOT executed in the build",
        "-- sandbox. To use this file: launch FEMM, then File > Open Lua Script",
        "-- (or from the FEMM Lua console: dofile('ehd_wire_collector.lua')).",
        "--",
        (
            f"-- Design: r_wire = {r_wire_mm} mm, d_gap = {d_gap_mm} mm, "
            f"depth (L_wire) = {depth_mm} mm, V_op = {v_op} V."
        ),
        "-- Analytical cross-check (from ehdpsu.physics):",
        f"--   Peek onset surface field E_peek = {_num(e_peek)} V/m",
        f"--   corona onset voltage    V_onset = {_num(v_onset)} V",
        f"-- {LAPLACE_CAVEAT}",
        "-- ===============================================================",
        "",
        "-- Parameters (millimetres; FEMM length unit set below).",
        f"r_wire = {_num(r_wire_mm)}      -- emitter wire radius [mm]",
        f"d_gap = {_num(d_gap_mm)}        -- emitter-to-collector gap [mm]",
        f"depth = {_num(depth_mm)}        -- out-of-plane depth = wire length [mm]",
        f"outer_r = {_num(outer_r_mm)}    -- outer air-boundary radius [mm]",
        f"collector_y = {_num(collector_y_mm)}   -- collector plate y-position [mm]",
        f"collector_hw = {_num(collector_hw_mm)} -- collector plate half-width [mm]",
        f"V_op = {_num(v_op)}             -- emitter operating voltage [V]",
        "",
        "-- 1) New electrostatics document (mode 1).",
        "newdocument(1)",
        "",
        "-- 2) Problem definition: millimetres, planar, out-of-plane depth,",
        "--    solver precision, min angle. Depth carries the wire length so",
        "--    energy/charge results scale to the real cell.",
        'ei_probdef("millimeters", "planar", 1e-8, depth, 30)',
        "",
        "-- 3) Air material (relative permittivity 1).",
        'ei_addmaterial("Air", 1, 1, 0)',
        "",
        "-- 4) Boundary property: fixed-potential (Dirichlet) outer boundary at",
        "--    0 V, an open-boundary approximation (outer_r >> gap).",
        "-- ei_addboundprop(name, Vc, qs, c0, c1, BdryFormat) : BdryFormat 0 = fixed V.",
        'ei_addboundprop("FarField", 0, 0, 0, 0, 0)',
        "",
        "-- 5) Conductor properties: fix the wire at V_op and the collector at 0 V.",
        "-- ei_addconductorprop(name, Vc, qc, ConductorType) : ConductorType 1 = fixed V.",
        'ei_addconductorprop("Emitter", V_op, 0, 1)',
        'ei_addconductorprop("Collector", 0, 0, 1)',
        "",
        "-- 6) Geometry -----------------------------------------------------",
        "-- Emitter wire: a circle of radius r_wire centred at the origin,",
        "-- drawn as two 180-degree arcs between the left/right nodes.",
        "ei_addnode(-r_wire, 0)",
        "ei_addnode(r_wire, 0)",
        "-- ei_addarc(x1, y1, x2, y2, angle_deg, maxseg)",
        "ei_addarc(-r_wire, 0, r_wire, 0, 180, 1)",
        "ei_addarc(r_wire, 0, -r_wire, 0, 180, 1)",
        "",
        "-- Collector plate: a horizontal segment a distance d_gap below the",
        "-- wire surface, spanning +/- collector_hw.",
        "ei_addnode(-collector_hw, collector_y)",
        "ei_addnode(collector_hw, collector_y)",
        "ei_addsegment(-collector_hw, collector_y, collector_hw, collector_y)",
        "",
        "-- Outer air boundary: a large box (open-boundary approximation).",
        "ei_addnode(-outer_r, outer_r)",
        "ei_addnode(outer_r, outer_r)",
        "ei_addnode(outer_r, -outer_r)",
        "ei_addnode(-outer_r, -outer_r)",
        "ei_addsegment(-outer_r, outer_r, outer_r, outer_r)",
        "ei_addsegment(outer_r, outer_r, outer_r, -outer_r)",
        "ei_addsegment(outer_r, -outer_r, -outer_r, -outer_r)",
        "ei_addsegment(-outer_r, -outer_r, -outer_r, outer_r)",
        "",
        "-- 7) Assign boundary property to the four outer edges (midpoints).",
        "ei_selectsegment(0, outer_r)",
        "ei_selectsegment(outer_r, 0)",
        "ei_selectsegment(0, -outer_r)",
        "ei_selectsegment(-outer_r, 0)",
        'ei_setsegmentprop("FarField", 0, 1, 0, 0, "<None>")',
        "ei_clearselected()",
        "",
        "-- 8) Assign the Emitter conductor to the wire arcs.",
        "ei_selectarcsegment(0, r_wire)",
        "ei_selectarcsegment(0, -r_wire)",
        'ei_setarcsegmentprop(1, "<None>", 0, 0, "Emitter")',
        "ei_clearselected()",
        "",
        "-- 9) Assign the Collector conductor to the collector plate segment.",
        "ei_selectsegment(0, collector_y)",
        'ei_setsegmentprop("<None>", 0, 1, 0, 0, "Collector")',
        "ei_clearselected()",
        "",
        "-- 10) Block labels. THE GEOMETRY HAS THREE REGIONS, NOT ONE.",
        "--",
        "-- Corrected 2026-09-16, the first time this script was ever run in FEMM. It",
        "-- previously placed ONE label, at (0, outer_r/2), and FEMM refused to solve with",
        '-- "Material properties have not been defined for all regions". Every region a',
        "-- closed boundary encloses needs a label, and this geometry closes three:",
        "--",
        "--   (a) the main air region, above the collector and outside the wire;",
        "--   (b) the wire INTERIOR -- the two 180-degree arcs form a closed circle, so its",
        "--       inside is its own region;",
        "--   (c) the region BELOW the collector -- collector_hw equals outer_r, so the plate",
        "--       spans the full width and its end nodes land on the side walls, partitioning",
        "--       the box in two.",
        "--",
        "-- (b) and (c) are both physically inert and are labelled Air rather than excluded:",
        "--   * inside a conductor held at a single potential the solution is constant, so",
        "--     E = 0 there, contributing nothing to stored energy and nothing to the",
        "--     conductor charge integral;",
        "--   * below a grounded plate bounded by grounded walls every boundary sits at 0 V,",
        "--     so that region solves to V = 0 throughout and E = 0.",
        "--",
        "-- FEMM 4.2 does offer a <No Mesh> block property, which would be tidier for (b) and",
        "-- would save meshing a 25 um circle. It is NOT used here because its exact spelling",
        "-- was not verified against this installation, and a wrong material name fails the",
        "-- same way the missing label did. Air is already defined and cannot be misspelt.",
        "ei_addblocklabel(0, outer_r * 0.5)",
        "ei_selectlabel(0, outer_r * 0.5)",
        'ei_setblockprop("Air", 1, 0, 0)',
        "ei_clearselected()",
        "",
        "-- (b) wire interior.",
        "ei_addblocklabel(0, 0)",
        "ei_selectlabel(0, 0)",
        'ei_setblockprop("Air", 1, 0, 0)',
        "ei_clearselected()",
        "",
        "-- (c) below the collector plate.",
        "ei_addblocklabel(0, (collector_y - outer_r) * 0.5)",
        "ei_selectlabel(0, (collector_y - outer_r) * 0.5)",
        'ei_setblockprop("Air", 1, 0, 0)',
        "ei_clearselected()",
        "",
        "-- 11) Zoom, save, mesh, solve, and load the solution.",
        "ei_zoomnatural()",
        'ei_saveas("ehd_wire_collector.fee")',
        "ei_analyze(0)",
        "ei_loadsolution()",
        "",
        "-- 12) Read the outputs, in the script rather than by hand -------",
        "--",
        "-- Added 2026-09-16. This block previously described where to click and which",
        "-- function to call, and it named eo_getconductorproperty -- which does not exist.",
        "-- The function is eo_getconductorproperties, PLURAL, confirmed from FEMM's own",
        "-- Octave wrapper at C:\\femm42\\mfiles\\eo_getconductorproperties.m.",
        "--",
        "-- Computing the values here rather than reading them off the GUI removes the step",
        "-- where a transcription error would enter, and it makes the reading reproducible:",
        "-- the same script run twice gives the same numbers.",
        "--",
        "-- eo_getpointvalues(x, y) returns EIGHT values in this order, established from the",
        "-- same wrapper set (eo_getv takes column 1, eo_getd 2:3, eo_gete 4:5, eo_getperm",
        "-- 6:7, eo_getenergydensity 8):",
        "--     V, Dx, Dy, Ex, Ey, ex, ey, energy_density",
        "-- ---------------------------------------------------------------",
        "",
        "-- DIALECT: FEMM 4.2 embeds Lua 4, where the maths and string functions are GLOBALS",
        "-- (sqrt, cos, sin, format) and the math/string tables of Lua 5 do not exist. FEMM's",
        '-- own readme refers to "the Lua format command" for exactly that reason. The shim',
        "-- below makes this script run under either dialect: under Lua 4 the globals already",
        "-- exist and nothing happens, under Lua 5 they are bound to their table members.",
        "-- Radians are converted with a literal rather than PI, so the script does not depend",
        "-- on which name the constant has.",
        "if not sqrt then sqrt = math.sqrt end",
        "if not cos then cos = math.cos end",
        "if not sin then sin = math.sin end",
        "if not format then format = string.format end",
        "deg2rad = 0.0174532925199433",
        "",
        "-- Peak surface field. Sampled just OUTSIDE the wire, because a point exactly on the",
        "-- boundary may not lie in any element. Three radii are reported rather than one so",
        "-- the radial sensitivity of the reading is visible instead of hidden: near a thin",
        "-- wire the field falls roughly as 1/r, so a 1% offset costs about 1%. Record the",
        "-- 1.005 figure and keep the other two -- the spread IS the reading's uncertainty.",
        "function probe_ring(frac)",
        "  Emax = 0",
        "  th_at = 0",
        "  i = 0",
        "  while i < 360 do",
        "    th = i * deg2rad",
        "    xs = frac * r_wire * cos(th)",
        "    ys = frac * r_wire * sin(th)",
        "    V, Dx, Dy, Ex, Ey, ex, ey, nrg = eo_getpointvalues(xs, ys)",
        "    if Ex then",
        "      E = sqrt(Ex * Ex + Ey * Ey)",
        "      if E > Emax then",
        "        Emax = E",
        "        th_at = i",
        "      end",
        "    end",
        "    i = i + 1",
        "  end",
        '  print(format("E_peak at r = %.4f * r_wire : %.6e V/m  (peak at %d deg)",',
        "               frac, Emax, th_at))",
        "  return Emax",
        "end",
        "",
        "E_at_1005 = probe_ring(1.005)",
        "E_at_101 = probe_ring(1.01)",
        "E_at_102 = probe_ring(1.02)",
        "",
        "-- Cell capacitance, two independent routes. They should agree; a DISAGREEMENT IS A",
        "-- FINDING and must be reported rather than averaged away.",
        "--",
        "-- Route (a), stored energy: C = 2W / V_op^2. All three air blocks are selected",
        "-- because the energy integral covers only what is selected -- and (b) and (c) hold",
        "-- no energy, so including them is a check that they really are inert rather than an",
        "-- approximation.",
        "eo_clearblock()",
        "eo_selectblock(0, outer_r * 0.5)",
        "eo_selectblock(0, 0)",
        "eo_selectblock(0, (collector_y - outer_r) * 0.5)",
        "W = eo_blockintegral(0)",
        "eo_clearblock()",
        "C_from_energy = 2 * W / (V_op * V_op)",
        "",
        "-- Route (b), emitter charge: C = Q / V_op.",
        'Vc, Q = eo_getconductorproperties("Emitter")',
        "C_from_charge = Q / V_op",
        "",
        'print(format("W_stored_J        : %.6e", W))',
        'print(format("C_from_energy_F   : %.6e", C_from_energy))',
        'print(format("Q_emitter_C       : %.6e", Q))',
        'print(format("C_from_charge_F   : %.6e", C_from_charge))',
        "if C_from_charge ~= 0 then",
        '  print(format("route ratio (energy/charge) : %.4f",',
        "               C_from_energy / C_from_charge))",
        "end",
        "",
        "-- FEMM reports per the problem depth set in ei_probdef, which is the wire length,",
        "-- so C is the whole-cell capacitance rather than a per-metre figure.",
        "--",
        "-- HOW TO CROSS-CHECK AGAINST PEEK, AND HOW NOT TO.",
        "--",
        "-- Corrected 2026-09-16, immediately after the first successful run. This block used to",
        "-- direct the reader to compare the solved surface field against the analytical Peek",
        "-- figure as though they were the same quantity. They are not, and the wording is",
        "-- PARAPHRASED here rather than quoted, because a test scans this file for the old",
        "-- sentence and quoting it verbatim would reproduce the very thing being retracted.",
        "--",
        "-- It was a CATEGORY ERROR and it would have manufactured a false alarm: the script",
        "-- applies V_op, whereas Peek's figure is the surface field AT ONSET. On the MK0",
        "-- geometry the two differ by a factor of about 7.4, so an operator following the old",
        "-- wording would have reported a catastrophic disagreement where there is none.",
        "--",
        "-- The valid comparison uses the fact that Laplace is LINEAR in the applied voltage,",
        "-- so one solve at any voltage gives the whole geometry:",
        "--",
        "--   1. field per volt from this run:      E_per_V = E_surface / V_op",
        "--   2. onset is where E_surface = E_peek: V_onset_implied = E_peek / E_per_V",
        "--   3. compare V_onset_implied against the closed-form V_onset in the header.",
        "--",
        "-- Differences come from the geometry the closed form assumes, from meshing, and from",
        "-- the finite outer boundary. A disagreement is a result to report, NOT something to",
        "-- tune the mesh until it goes away.",
        "--",
        "-- The capacitance has an independent analytical comparison of its own: for a wire at",
        "-- height h above a ground plane, C' = 2*pi*eps0 / acosh(h/r) per unit length. Note",
        "-- acosh(h/r), NOT ln(d/r) -- the image-charge form, not the coaxial approximation.",
        "-- " + LAPLACE_CAVEAT,
        "-- ===============================================================",
        "",
    ]
    return "\n".join(lines)


def build_geometry_notes(p: DesignParameters | None = None) -> str:
    """Return a plain-text geometry + expected-outputs description.

    This companion text lets the user cross-check FEMM's results against the
    analytical model without reading the Lua source: it lists the geometry, the
    conductor potentials, and the two quantities to read back (peak surface
    field vs Peek prediction, and cell capacitance) with the formulas.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters`.

    Returns
    -------
    str
        Plain-text description (newline-terminated).
    """
    p = p or default_design()
    e_peek = physics.peek_inception_field(p.r_wire_m, p.delta, p.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, p.r_wire_m, p.d_gap_m)
    mean_field = physics.mean_gap_field(p.V_op, p.d_gap_m)

    lines = [
        "EHD wire-to-collector FEMM cell -- geometry and expected outputs",
        "================================================================",
        "",
        "Run ehd_wire_collector.lua in FEMM (Windows GUI). This file just",
        "documents what the script builds and what to read back.",
        "",
        "Geometry (2-D cross-section, out-of-plane depth = wire length):",
        (
            f"  emitter wire radius r_wire = {p.r_wire_m * 1e3:.4g} mm "
            f"({p.r_wire_m * 1e6:.1f} um)"
        ),
        f"  emitter-to-collector gap d_gap = {p.d_gap_m * 1e3:.4g} mm",
        (
            f"  out-of-plane depth (L_wire)   = {p.L_wire_m * 1e3:.4g} mm "
            f"({p.L_wire_m * 1e2:.1f} cm)"
        ),
        f"  emitter conductor potential   = {p.V_op:.1f} V (V_op)",
        "  collector conductor potential = 0 V",
        "  air material: relative permittivity 1; outer boundary fixed at 0 V.",
        "",
        "Expected outputs to read back from FEMM:",
        "  1) Peak wire-surface field |E|_max [V/m].",
        (
            f"     Analytical Peek onset field  E_peek = {e_peek:.4g} V/m "
            f"({e_peek / 1e6:.3f} MV/m)."
        ),
        (
            f"     Analytical corona onset      V_onset = {v_onset:.4g} V "
            f"({v_onset / 1e3:.2f} kV)."
        ),
        (
            f"     Mean gap field (V/d)         = {mean_field:.4g} V/m "
            f"({mean_field / 1e6:.3f} MV/m)."
        ),
        "     FEMM's |E|_max at the wire should be close to E_peek (Laplace,",
        "     no space charge). Large disagreement means a meshing or",
        "     geometry-scale problem (refine mesh / enlarge outer boundary).",
        "  2) Cell capacitance C [F].",
        "     From stored energy W:   C = 2 * W / V_op^2.",
        "     From emitter charge Q:  C = Q / V_op.",
        "     The two routes should agree; C is the whole-cell value at the",
        "     depth set in ei_probdef.",
        "",
        "Caveat: " + LAPLACE_CAVEAT,
        "",
    ]
    return "\n".join(lines)


def write_artifacts(
    p: DesignParameters | None = None,
    output_dir: Path = DEFAULT_ARTIFACT_DIR,
    write_notes: bool = True,
) -> list[Path]:
    """Write the FEMM Lua script (and optional notes) to ``output_dir``.

    Parameters
    ----------
    p : DesignParameters, optional
        Design point; defaults to :class:`DesignParameters`.
    output_dir : Path
        Destination directory (created if missing).
    write_notes : bool
        Also write the plain-text geometry/expected-outputs description.

    Returns
    -------
    list[Path]
        The files written, in creation order.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    lua_path = output_dir / DEFAULT_LUA_NAME
    lua_path.write_text(build_lua_script(p), encoding="utf-8")
    written.append(lua_path)

    if write_notes:
        notes_path = output_dir / "ehd_wire_collector_geometry.txt"
        notes_path.write_text(build_geometry_notes(p), encoding="utf-8")
        written.append(notes_path)

    return written


def main() -> None:
    """Write the FEMM artifact(s) and print their paths plus local-run steps."""
    p = default_design()
    written = write_artifacts(p, DEFAULT_ARTIFACT_DIR, write_notes=True)

    e_peek = physics.peek_inception_field(p.r_wire_m, p.delta, p.m_rough)
    v_onset = physics.corona_inception_voltage(e_peek, p.r_wire_m, p.d_gap_m)

    print("=== EHD PSU FEMM geometry generation ===")
    print(
        f"Design: r_wire={p.r_wire_m * 1e6:.0f} um, d_gap={p.d_gap_m * 1e3:.0f} mm, "
        f"depth(L_wire)={p.L_wire_m * 1e2:.0f} cm, V_op={p.V_op / 1e3:.0f} kV"
    )
    print(
        f"Analytical cross-check: E_peek={e_peek / 1e6:.3f} MV/m, "
        f"V_onset={v_onset / 1e3:.2f} kV"
    )
    print(f"Wrote {len(written)} artifact(s):")
    for f in written:
        print(f"  {f}")
    print("\nHow to run locally in FEMM (Windows GUI):")
    print("  1. Install and launch FEMM 4.2 (femm.info).")
    print(f"  2. File > Open Lua Script and choose {DEFAULT_LUA_NAME}, or from")
    print(f"     the FEMM Lua console run: dofile('{DEFAULT_LUA_NAME}')")
    print("  3. The script builds the geometry, meshes, solves, and loads the")
    print("     solution. Read back:")
    print("     - peak wire-surface |E| (compare with E_peek above);")
    print("     - cell capacitance via C = 2*W/V^2 or C = Q/V (see script tail).")
    print("\nCAVEAT: " + LAPLACE_CAVEAT)
    print(
        "NOTE: FEMM is a GUI tool; this is a generated Lua-script artifact to "
        "open locally, not a sandbox-run simulation."
    )


if __name__ == "__main__":
    main()
