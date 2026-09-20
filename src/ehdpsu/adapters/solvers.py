"""The adapters that exist today: FEMM, LTspice, QSPICE.

Each wraps a generator that already existed and was already tested. The adapter adds the contract,
not the physics — ``ehdpsu.femm`` and ``ehdpsu.spice`` are unchanged, and a wrapper that recomputed
anything would be a second representation of the same artifact.

All three report ``run`` as **manual**, and that is a statement about this project's state rather
than about the tools. QSPICE genuinely accepts a netlist on the command line, and LTspice has a
batch switch; neither is claimed here, because **no installation of either has been inspected** and
an invocation nobody has performed is not a capability. Plan Task 13 installs them, and the day one
of these returns ``COMPLETED`` will be a diff.

What each tool answers, and what it does not
--------------------------------------------
**FEMM** solves Laplace with no space charge. Its peak wire-surface field is the **corona-onset**
field, comparable against Peek — it is *not* the loaded operating field, because once current flows
ion space charge lowers the near-wire field. Its cell capacitance is what the SPICE ladder needs.

**LTspice and QSPICE** inherit their component models. The generated netlist's ``.model DHV``
parameters are placeholders, so any loss or efficiency figure read out of it is uncalibrated however
carefully the simulation ran.
"""

from __future__ import annotations

from pathlib import Path

from .. import femm as femm_module
from .. import spice as spice_module
from ..detect import KNOWN_TOOLS, ToolSpec, ToolStatus
from ..physics import default_design
from ..spice import default_spice_params
from .base import Adapter, GenerateError, RunOutcome, RunResult

_SPECS_BY_NAME = {spec.name: spec for spec in KNOWN_TOOLS}

#: The one name for the wire-to-collector flow-domain mesh, shared by every stage of the
#: Gmsh -> ElmerGrid -> ElmerSolver chain.
#:
#: F10 (CRSDL Task 20): the .geo's own comment named the mesh file with one stem while the .sif's
#: Mesh DB declared a second, differently-suffixed stem. ElmerGrid names its output directory after
#: the mesh *file* it converted, so it produced a directory matching the first stem, and
#: ElmerSolver's first real run stopped on a LoadMesh error naming the mesh directory it could not
#: find. *Principle 4, two representations of one thing will drift* -- this pair was born drifted,
#: and 998 passing tests, a tracked regeneration diff and a planner review all missed it, because
#: none of them is an Elmer parser.
#:
#: Both the Gmsh adapter's .geo/.msh naming and the Elmer adapter's Mesh DB declaration interpolate
#: this constant. Neither may spell the name for itself again.
#:
#: Written plainly, 2026-09-19. It was briefly ``"ehd" + "_cell"`` — assembled from two tokens so
#: that no single double-quoted literal held the value — because the test guarding this seam counted
#: literal occurrences in source and required zero, which this line cannot satisfy. That test was
#: defective and has been replaced by a behavioural one that changes ``CELL_STEM`` and checks both
#: artifacts follow, so the value can be a value again. Recorded because obfuscated code with no
#: surviving reason is the kind of thing a later reader restores rather than removes.
CELL_STEM = "ehd_cell"


def _spec(name: str) -> ToolSpec:
    """Look the spec up rather than restating it.

    *Principle 4, two representations of one thing will drift.* An adapter carrying its own copy of
    an executable list would eventually disagree with ``detect.KNOWN_TOOLS`` about what to look for,
    and the vendor-cited provenance register only covers the copy in ``detect``.
    """
    try:
        return _SPECS_BY_NAME[name]
    except KeyError as exc:  # pragma: no cover - guarded by test_adapters
        raise GenerateError(
            f"no ToolSpec named {name!r} in detect.KNOWN_TOOLS; the adapter and the detection "
            f"table have diverged"
        ) from exc


def _manual(tool: str, inputs: tuple[Path, ...], steps: str) -> RunResult:
    """A uniform manual-run outcome, so no adapter phrases 'you have to do this' differently."""
    return RunResult(
        outcome=RunOutcome.MANUAL_REQUIRED,
        detail=(
            f"{tool} is GUI-driven and no headless invocation has been verified on this machine, "
            f"so nothing was run. {steps} Transcribe the values into a result file beginning "
            f"`# ehd-run-result v1` and carrying tool_version and input_sha256, then parse it."
        ),
        inputs=inputs,
    )


class FemmAdapter(Adapter):
    """FEMM 4.2 — 2D/axisymmetric electrostatics."""

    @property
    def name(self) -> str:
        return "femm"

    @property
    def attribution(self) -> str:
        return "FEMM"

    @property
    def capability(self) -> str:
        return (
            "solved peak wire-surface field and cell capacitance; the route that would replace "
            "k_geo's ~10x placeholder band with a calibrated coefficient"
        )

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("femm")

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("E_peak_surface_V_per_m", "C_cell_F")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        written = femm_module.write_artifacts(
            default_design(), output_dir=output_dir, write_notes=True
        )
        return tuple(written)

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"FEMM detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. The solved-field capability is absent; nothing "
                    f"substitutes for it, and the analytical Peek figure is not a stand-in."
                ),
                inputs=inputs,
            )
        return _manual(
            "FEMM",
            inputs,
            "Open the .lua script in FEMM's Lua console, run it to solve and load the solution, "
            "then read the peak wire-surface |E| and the cell capacitance as the script tail "
            "describes.",
        )


class _SpiceAdapter(Adapter):
    """Shared behaviour for the two SPICE engines, which differ only in input format."""

    @property
    def capability(self) -> str:
        return (
            "simulated Cockcroft-Walton droop and ripple under the EHD load, against the "
            "closed-form estimates; the component models remain placeholders"
        )

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("V_out_loaded_V", "V_ripple_pp_V", "I_load_A")

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"{self.attribution} detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. No circuit simulation is available, and the "
                    f"closed-form droop and ripple figures are not a substitute for one."
                ),
                inputs=inputs,
            )
        return _manual(
            self.attribution,
            inputs,
            "Open the generated file, run a transient long enough for the ladder to settle, then "
            "read the loaded output voltage, the peak-to-peak ripple and the load current.",
        )


class LtspiceAdapter(_SpiceAdapter):
    """LTspice — schematic form of the LLC + Cockcroft-Walton chain."""

    @property
    def name(self) -> str:
        return "ltspice"

    @property
    def attribution(self) -> str:
        return "LTspice"

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("ltspice")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "ehd_llc_cw.asc"
        path.write_text(
            spice_module.build_asc(default_design(), default_spice_params()), encoding="utf-8"
        )
        return (path,)


class QspiceAdapter(_SpiceAdapter):
    """QSPICE — netlist form of the same chain."""

    @property
    def name(self) -> str:
        return "qspice"

    @property
    def attribution(self) -> str:
        return "QSPICE"

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("qspice")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "ehd_llc_cw.cir"
        path.write_text(
            spice_module.build_netlist(default_design(), default_spice_params()), encoding="utf-8"
        )
        return (path,)


def _no_verified_headless_run(tool: str, inputs: tuple[Path, ...]) -> RunResult:
    """The shared response for a present-but-never-run headless tool.

    Gmsh and Elmer both run without a human at the console (``manual_only=False``), so they must
    never report ``MANUAL_REQUIRED`` — that state means a human must drive a GUI, and neither tool
    needs one. But no headless invocation of either has been verified on this machine, so
    ``COMPLETED`` would be *principle 3, never report success over unperformed work*.

    ``PRESENT_UNVERIFIED`` is now the only outcome that is not a false statement: the tool is
    genuinely present (the probe succeeded), but we have not yet verified it runs.
    """
    return RunResult(
        outcome=RunOutcome.PRESENT_UNVERIFIED,
        detail=(
            f"{tool} is present and may be functional, but no headless invocation of it has been "
            f"verified on this machine, so nothing was run and no closed-form estimate or stand-in "
            f"figure substitutes for a real result. Generate the input and invoke {tool} by hand "
            f"until that verification exists."
        ),
        inputs=inputs,
    )


class GmshAdapter(Adapter):
    """Gmsh — the mesher every CFD route needs, whether Elmer, OpenFOAM or the in-process solve.

    Not a CFD route itself: it produces the mesh those routes consume. The generated geometry
    describes only the fluid domain — the flow box above the collector with the emitter wire's
    interior cut out as a hole — rather than reusing FEMM's three-region electrostatics geometry,
    because the wire interior and the region below the collector carry no fluid and meshing them
    would be wasted, physically meaningless cells.
    """

    @property
    def name(self) -> str:
        return "gmsh"

    @property
    def attribution(self) -> str:
        return "Gmsh"

    @property
    def capability(self) -> str:
        return (
            "a mesh of the wire-to-collector flow domain for the CFD routes to solve on; without "
            "it neither Elmer nor any other mesh-based fluid solver has anything to run against"
        )

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("gmsh")

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("n_nodes", "n_elements", "min_element_quality")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        design = default_design()
        r_wire = design.r_wire_m
        d_gap = design.d_gap_m
        L_wire = design.L_wire_m
        lines = [
            "// ===============================================================",
            "// EHD wire-to-collector flow-domain mesh (Gmsh script)",
            "// Generated by ehdpsu.adapters.solvers.GmshAdapter. Run with:",
            f"//   gmsh {CELL_STEM}.geo -2 -o {CELL_STEM}.msh",
            "//",
            "// Reference: Gmsh reference manual, https://gmsh.info/doc/texinfo/",
            "//",
            "// Geometry, from ehdpsu.physics.default_design() -- units are metres, matching the",
            "// profile, rather than the millimetres ehdpsu.femm uses for FEMM's own unit system:",
            f"//   r_wire = {r_wire!r} m   (emitter wire radius)",
            f"//   d_gap  = {d_gap!r} m   (emitter-to-collector gap)",
            f"//   L_wire = {L_wire!r} m   (out-of-plane wire length; unused by this 2D mesh)",
            "//",
            "// The flow domain is the region ABOVE the collector and OUTSIDE the wire: a box",
            "// with the wire's interior removed as a hole. Unlike ehdpsu.femm's electrostatics",
            "// geometry (which needs the wire interior and the below-collector region as inert",
            "// Air blocks so FEMM's solver has a label for every closed region), a fluid mesh has",
            "// no use for either: no fluid occupies them, so meshing them would be wasted.",
            "// ===============================================================",
            "",
            f"r_wire = {r_wire!r};",
            f"d_gap = {d_gap!r};",
            "outer_hw = ((d_gap * 5.0 > r_wire * 200.0) ? d_gap * 5.0 : r_wire * 200.0);",
            "outer_top = d_gap * 10.0;",
            "lc_wire = r_wire / 4.0;",
            "lc_outer = d_gap / 8.0;",
            "collector_y = -(r_wire + d_gap);",
            "",
            "// Flow-box corners.",
            "Point(1) = {-outer_hw, collector_y, 0, lc_outer};",
            "Point(2) = { outer_hw, collector_y, 0, lc_outer};",
            "Point(3) = { outer_hw, outer_top,   0, lc_outer};",
            "Point(4) = {-outer_hw, outer_top,   0, lc_outer};",
            "",
            "Line(1) = {1, 2};  // Collector plate (bottom boundary)",
            "Line(2) = {2, 3};  // Right wall",
            "Line(3) = {3, 4};  // Top far-field boundary",
            "Line(4) = {4, 1};  // Left wall",
            "Curve Loop(10) = {1, 2, 3, 4};",
            "",
            "// Emitter wire, as two 180-degree arcs about its centre -- the same convention",
            "// ehdpsu.femm.build_lua_script uses for the identical physical wire.",
            "Point(5) = {-r_wire, 0, 0, lc_wire};",
            "Point(6) = { r_wire, 0, 0, lc_wire};",
            "Point(7) = {0, 0, 0, lc_wire};",
            "Circle(20) = {5, 7, 6};",
            "Circle(21) = {6, 7, 5};",
            "Curve Loop(11) = {20, 21};",
            "",
            "// The flow domain: the box with the wire's interior removed as a hole.",
            "Plane Surface(1) = {10, 11};",
            "",
            'Physical Curve("Emitter") = {20, 21};',
            'Physical Curve("Collector") = {1};',
            'Physical Curve("SideWalls") = {2, 4};',
            'Physical Curve("TopFarField") = {3};',
            'Physical Surface("Air") = {1};',
            "",
        ]
        path = output_dir / f"{CELL_STEM}.geo"
        path.write_text("\n".join(lines), encoding="utf-8")
        return (path,)

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"Gmsh detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. The meshing capability is absent; nothing "
                    f"substitutes for it, and a closed-form mesh estimate is not a stand-in."
                ),
                inputs=inputs,
            )
        return _no_verified_headless_run("Gmsh", inputs)


class ElmerAdapter(Adapter):
    """ElmerSolver — the fidelity CFD route, one of the competing routes plan Task 14 maps.

    Deliberately not chosen as the default: OpenFOAM and the in-process axisymmetric Python
    solver are competing routes, and *adapter-contract.md* is explicit that an unchosen route
    stays unchosen rather than becoming the default because it happens to be the one this batch
    wrote first.
    """

    @property
    def name(self) -> str:
        return "elmer"

    @property
    def attribution(self) -> str:
        return "Elmer"

    @property
    def capability(self) -> str:
        return (
            "a solved ion-wind flow field on the Gmsh mesh, against the mobility-limited thrust "
            "ceiling — a field that carries no information about its own discretisation error "
            "without demonstrated mesh convergence, however smooth it renders"
        )

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("elmer")

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("v_ion_wind_m_per_s", "p_static_Pa")

    @property
    def read_back_keys(self) -> tuple[str, ...]:
        """Everything a run record must carry, including the mesh the solve actually ran on.

        F10b (CRSDL Task 20): ElmerGrid's ``-autoclean`` conversion silently changed the mesh on its
        first real run -- 14,544 to 14,543 nodes, 371 to 364 line elements, probably the arc-centre
        construction point and duplicate curve endpoints, but that is a *hypothesis* and nothing
        recorded what was dropped. Gmsh already reports the mesh it produced (``n_nodes``,
        ``n_elements`` in :attr:`GmshAdapter.expected_values`); what was missing is the count Elmer
        actually *received* after conversion, which is the only place the drop becomes visible.
        Without it a run record attests to a field without attesting to the mesh under it.

        Distinct from :attr:`expected_values`: that tuple is what a *solved* result file must carry
        to be promotable to ``solved`` at all (see ``base.parse_result_file``); this one is the
        superset a complete run record needs, chain-of-custody included.
        """
        return self.expected_values + ("mesh_n_nodes_received", "mesh_n_elements_received")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        design = default_design()
        lines = [
            "! ===============================================================",
            "! EHD ion-wind flow domain -- ElmerSolver Solver Input File (SIF).",
            "! Generated by ehdpsu.adapters.solvers.ElmerAdapter.",
            "!",
            f"! Mesh: convert the Gmsh output ({CELL_STEM}.geo -> {CELL_STEM}.msh) with ElmerGrid",
            f"! before running ElmerSolver, e.g.  ElmerGrid 14 2 {CELL_STEM}.msh -autoclean",
            "! -autoclean MAY CHANGE THE MESH: on this project's first real run it dropped one",
            "! node and seven line elements (14,544 -> 14,543 nodes; 371 -> 364 line elements),",
            "! probably the arc-centre construction point and duplicate curve endpoints. Read the",
            "! node and element counts ElmerGrid reports back and record them; do not assume they",
            "! match Gmsh's own count. 'Mesh DB' below names the directory ElmerGrid produces --",
            f"! named after the .msh file it converts, i.e. '{CELL_STEM}', not a descriptive suffix.",
            "!",
            "! Design point, from ehdpsu.physics.default_design():",
            f"!   d_gap = {design.d_gap_m!r} m   (sets the flow domain's height)",
            "!",
            "! Physics honesty (steering: physics-honesty.md, principle 1 -- never curve-fit or",
            "! invent a coefficient). This file sets up the NUMERICAL SKELETON for the flow --",
            "! mesh, material, Navier-Stokes solver, no-slip walls at the emitter and collector --",
            "! and deliberately OMITS the electrohydrodynamic body force (rho_ion * E) that would",
            "! actually drive the ion wind. Inventing a plausible-looking force term with no cited",
            "! coefficient would be exactly the curve-fitting this project forbids. With no body",
            "! force this .sif solves to the trivial zero-velocity field; it exists so the mesh and",
            "! boundary wiring can be checked once Elmer is installed, not to produce a flow result.",
            "!",
            '! Procedure = File "FlowSolve" "FlowSolver" -- confirmed from a published Elmer .sif,',
            "! https://forum.freecad.org/viewtopic.php?style=8&t=48175 (P. Raback, Elmer",
            "! developer, replying on the Elmer forum/FreeCAD forum bridge). ElmerSolver 26.1",
            "! loaded this Procedure successfully on 2026-09-18, confirming the citation.",
            '! Air material properties -- F. M. White, "Viscous Fluid Flow", 3rd ed., Table 1.4',
            "! (dry air, 20 C, 1 atm): rho = 1.2 kg/m^3, mu = 1.8e-5 Pa*s.",
            "!",
            "! Boundary wiring: all four Physical Curves the .geo declares (Emitter, Collector,",
            "! SideWalls, TopFarField) survive ElmerGrid's conversion and get a condition here.",
            "! TopFarField is deliberately NOT a no-slip wall -- wiring it as one would seal the",
            "! flow domain and make the binding check meaningless. It is left as a natural",
            "! (traction-free) boundary: no Velocity component is constrained, so Elmer leaves it",
            "! open rather than clamping it to zero. That is a numerical-skeleton choice, not a",
            "! physical claim about the far field; the .sif still solves to zero velocity because",
            "! no body force drives any flow toward it.",
            "! ===============================================================",
            "",
            "Header",
            f'  Mesh DB "." "{CELL_STEM}"',
            "End",
            "",
            "Simulation",
            '  Coordinate System = String "Cartesian 2D"',
            '  Simulation Type = String "Steady state"',
            "  Steady State Max Iterations = Integer 1",
            "  Output Intervals = Integer 1",
            "End",
            "",
            "Constants",
            "  Gravity(4) = Real 0.0 -1.0 0.0 9.81",
            "End",
            "",
            "Body 1",
            "  Equation = Integer 1",
            "  Material = Integer 1",
            "End",
            "",
            "Equation 1",
            "  Active Solvers(2) = Integer 1 2",
            '  Convection = String "Computed"',
            "End",
            "",
            "Material 1",
            "  Density = Real 1.2",
            "  Viscosity = Real 1.8e-5",
            "End",
            "",
            "Solver 1",
            '  Equation = String "Navier-Stokes"',
            '  Procedure = File "FlowSolve" "FlowSolver"',
            '  Exec Solver = String "Always"',
            "  Stabilize = Logical True",
            '  Linear System Solver = String "Iterative"',
            '  Linear System Iterative Method = String "BiCGStab"',
            "  Linear System Max Iterations = Integer 500",
            "  Linear System Convergence Tolerance = Real 1e-8",
            "  Nonlinear System Max Iterations = Integer 50",
            "  Nonlinear System Convergence Tolerance = Real 1e-6",
            "End",
            "",
            "Solver 2",
            '  Equation = String "ResultOutput"',
            '  Exec Solver = String "After simulation"',
            '  Procedure = File "ResultOutputSolve" "ResultOutputSolver"',
            f'  Output File Name = File "{CELL_STEM}"',
            "  Vtu Format = Logical True",
            "End",
            "",
            "Boundary Condition 1",
            '  Name = String "Emitter"',
            "  Velocity 1 = Real 0.0",
            "  Velocity 2 = Real 0.0",
            "End",
            "",
            "Boundary Condition 2",
            '  Name = String "Collector"',
            "  Velocity 1 = Real 0.0",
            "  Velocity 2 = Real 0.0",
            "End",
            "",
            "Boundary Condition 3",
            '  Name = String "SideWalls"',
            "  Velocity 1 = Real 0.0",
            "  Velocity 2 = Real 0.0",
            "End",
            "",
            "Boundary Condition 4",
            '  Name = String "TopFarField"',
            "  ! Natural (traction-free) boundary: no Velocity component is set, so this is not",
            "  ! a no-slip wall. Left unconstrained rather than given an invented outflow or",
            "  ! prescribed-pressure value, because neither is cited for this geometry.",
            "End",
            "",
        ]
        path = output_dir / f"{CELL_STEM}.sif"
        path.write_text("\n".join(lines), encoding="utf-8")
        return (path,)

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"Elmer detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. The fidelity CFD capability is absent; nothing "
                    f"substitutes for it, and a closed-form flow estimate is not a stand-in."
                ),
                inputs=inputs,
            )
        return _no_verified_headless_run("Elmer", inputs)


class ParaviewAdapter(Adapter):
    """ParaView — rendering. The only adapter whose output is an image rather than a number.

    ``manual_only=True`` even though ``pvpython`` is scriptable: real visualisation work in this
    project is GUI-driven, and ``detect.py``'s ``GUI_EXECUTABLES`` register is the reason the
    detection spec names ``pvpython.exe`` only — a version probe against ``paraview.exe`` would
    open a window during a test run.
    """

    @property
    def name(self) -> str:
        return "paraview"

    @property
    def attribution(self) -> str:
        return "ParaView"

    @property
    def capability(self) -> str:
        return (
            "a rendered image of the Elmer flow field or the FEMM electrostatic field, with the "
            "scalar range read back so a degenerate render is visible rather than silent"
        )

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("paraview")

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("image_width_px", "image_height_px", "field_range_min", "field_range_max")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "# ===============================================================",
            "# EHD flow-field render script. Run with:  pvpython ehd_cell_render.py",
            "# Generated by ehdpsu.adapters.solvers.ParaviewAdapter.",
            "#",
            "# Reference: ParaView Python scripting,",
            "# https://docs.paraview.org/en/latest/UsersGuide/commandLineArguments.html and the",
            "# pvpython/pvbatch tutorial, https://docs.paraview.org/en/v5.11.0/Tutorials/",
            "# ClassroomTutorials/pythonAndBatchPvpythonAndPvbatch.html",
            "#",
            "# Scripted deliberately, not a saved GUI state (.pvsm): a render nobody can",
            "# regenerate from source is not a reproducible result.",
            "#",
            "# This expects the Elmer VTU output named below. No Elmer run has occurred on this",
            "# machine, so the file will not exist yet -- running this script before one does",
            "# will fail loudly on OpenDataFile, rather than rendering nothing and calling it a",
            "# result.",
            "# ===============================================================",
            "",
            "from paraview.simple import *  # noqa: F401,F403 -- the ParaView Python bindings",
            "",
            "IMAGE_WIDTH_PX = 800",
            "IMAGE_HEIGHT_PX = 600",
            "",
            f"source = OpenDataFile('{CELL_STEM}0001.vtu')",
            'view = GetActiveViewOrCreate("RenderView")',
            "view.ViewSize = [IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX]",
            "",
            "display = Show(source, view)",
            'ColorBy(display, ("POINTS", "velocity"))',
            "display.RescaleTransferFunctionToDataRange(True, False)",
            "Render()",
            f"SaveScreenshot('{CELL_STEM}_render.png', view,",
            "               ImageResolution=[IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX])",
            "",
            "data_info = source.GetDataInformation()",
            'array_info = data_info.GetPointDataInformation().GetArrayInformation("velocity")',
            "if array_info is not None:",
            "    field_range_min, field_range_max = array_info.GetComponentRange(-1)",
            "else:",
            "    field_range_min, field_range_max = (0.0, 0.0)",
            "",
            '# Transcribe these four into a result file beginning "# ehd-run-result v1":',
            'print(f"image_width_px = {IMAGE_WIDTH_PX}")',
            'print(f"image_height_px = {IMAGE_HEIGHT_PX}")',
            'print(f"field_range_min = {field_range_min}")',
            'print(f"field_range_max = {field_range_max}")',
            "",
        ]
        path = output_dir / f"{CELL_STEM}_render.py"
        path.write_text("\n".join(lines), encoding="utf-8")
        return (path,)

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"ParaView detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. The rendering capability is absent; nothing "
                    f"substitutes for it, and a described-but-unrendered field is not a "
                    f"stand-in for an image."
                ),
                inputs=inputs,
            )
        return _manual(
            "ParaView",
            inputs,
            "Run `pvpython ehd_cell_render.py` (ParaView is GUI-driven for interactive work, so "
            "this project treats it as manual even though pvpython is scriptable), then read the "
            "printed image dimensions and field range, or open the saved PNG to confirm the "
            "render is not degenerate.",
        )
