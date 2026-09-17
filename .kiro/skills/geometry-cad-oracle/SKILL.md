---
name: geometry-cad-oracle
description: Domain specialist for the suite's bidirectional geometry — importing hand drawings and scans into dimensioned digital form, scale calibration, parametric CAD via CadQuery/OpenCASCADE, STEP and STL export, and the inverse solve that turns simulation targets into buildable physical dimensions and idealised geometry. Use when touching the geometry import or extrapolation modules, the CAD adapter, or anything that converts between a picture, a number and a part.
---

# Geometry & CAD Oracle

Domain expertise over the two directions between drawings, numbers and parts.

**Inbound** — raster sketch or scan → traced vector → scale-calibrated, dimensioned 2-D profile →
mesh-ready geometry. OpenCV or potrace for tracing, `ezdxf`/`svgpathtools` for vector, Gmsh or
OpenCASCADE for the geometry kernel.

**Outbound** — simulation targets and constraints → solved physical dimensions → parametric CAD →
STEP, STL and a dimensioned drawing. CadQuery or build123d as the Pythonic kernel.

Owned quantities: duct inner diameter, electrode gap, emitter wire count and spacing, collector
mesh pitch and wire diameter, creepage and clearance distances, and the nacelle shell layering.

## Refresh before acting

1. `artifacts/00_Governance/2026-09-15_PLAN_ehd_modeling_suite.md` — Tasks 16 and 17, which define
   inbound and outbound respectively, and their round-trip test requirement.
2. The active profile in `profiles/` — geometry is a *view* of profile values, never a second
   source for them.
3. `solver_inputs/ehd_wire_collector_geometry.txt` — the existing textual geometry description and
   the conventions it already uses.
4. `.kiro/skills/geometry-cad-oracle/task_ledger.md`.

## Live hazards in this domain

**A traced drawing has no dimensions until a scale reference is established.** Tracing recovers
*proportions*. Without a known length in the image — a ruler, a printed scale bar, a stated
dimension on the drawing — every extracted number is a pixel count wearing millimetre units. This
is the domain's characteristic failure and it produces confident, plausible, wrong geometry.
*Principle 2, an approximately-correct identifier is worse than an absent one.* Refuse to emit
dimensions rather than emit uncalibrated ones.

**Radius versus diameter is the live collision in this project, and it lands here hardest.**
Drawings and datasheets are inconsistent about which they annotate. Mesh specifications quote
*wire diameter*; wire suppliers quote either; Peek's law needs *radius*. A 25 µm value read the
wrong way shifts onset voltage by 29%. Every geometry field carries which it is in its name.

**Mesh open-area ratio is derived, not measured, and the derivation is easy to get wrong.** For a
square weave of wire diameter `d_w` and pitch `s`, `β = ((s − d_w)/s)²` — the ratio is areal, so
the linear open fraction is **squared**. Using the linear fraction overstates porosity and
understates drag.

**Creepage and clearance are different distances and both are geometry outputs.** Clearance is
through air; creepage is along a surface. A conical collar on a potted feedthrough exists to
lengthen creepage without lengthening the part. At 22 kV these are centimetre-scale and they
constrain the shell layout, not the other way round.

**No CAD or tracing tool is installed yet, and no geometry has been imported or exported.**
Everything in this domain is planned. Do not describe a round-trip as working.

## Domain laws

1. **Geometry reads from the profile; it never becomes a second source of truth.** A dimension
   that exists only in a CAD file or only in a drawing has escaped the seam.
2. **No dimension without a scale reference.** An import that cannot establish scale fails
   visibly and says which reference it looked for.
3. **Radius or diameter in every identifier**, and the unit too. `r_wire_m`, `d_mesh_wire_m`,
   `pitch_mesh_m`.
4. **Round-trip or it did not work.** Extrapolated geometry must be re-simulated and reproduce the
   requested target within a stated tolerance. Emitting a STEP file is not evidence that the part
   meets the goal.
5. **An infeasible request is reported as infeasible, naming the binding constraint.** Never
   silently clip a dimension to make a target reachable — that is curve-fitting with a CAD kernel.
   Breakdown margin, creepage minimum and manufacturable wire diameter are all legitimate
   binding constraints.
6. **Tolerances are stated, and they are manufacturing tolerances, not solver tolerances.** A
   2.5 mm gap specified as `±0.1 mm` is a build instruction; a gap specified to five decimals is
   noise pretending to be precision.
7. **Task artifact and ledger entry after any change here.** Append only.

## What this skill deliberately does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope, cited by number and name.
- **The units-in-identifiers rule and the absent-beats-approximate rule** — `physics-honesty.md`,
  always applied. The geometry-specific consequences are stated here; the rules live there.
- **Creepage and flashover safety practice** — `hv-safety.md`, always applied.
- **The profile schema** — `suite-core-oracle`, which owns it.
