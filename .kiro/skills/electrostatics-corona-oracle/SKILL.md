---
name: electrostatics-corona-oracle
description: Domain specialist for corona physics and electrostatic field solving — Peek's inception law, onset voltage, the Townsend quadratic current law and its geometry-dependent prefactor, space charge, air breakdown margins, and the FEMM adapter. Use when touching physics.py's electrostatics or current-law functions, femm.py, the FEMM adapter, or when reasoning about k_geo, corona onset, or arc-over risk.
---

# Electrostatics & Corona Oracle

Domain expertise over the field and the discharge — everything upstream of momentum transfer.

- **Peek's inception law** — `peek_inception_field()`; `E_peek = g0·m·δ·(1 + c/√(δ·r_cm))` with
  `g0 = 3.1e6 V/m`, `c = 0.308 cm^0.5`, radius in **centimetres** inside the Peek term.
- **Onset voltage** — the coaxial-cylinder field-to-voltage integral `V_onset = E_peek·r·ln(d/r)`,
  valid in the thin-wire limit `d >> r`.
- **Townsend quadratic current law** — `I = k·V·(V − V_onset)`, and the geometry-dependent
  prefactor `k`.
- **Air breakdown margin** — mean gap field `V/d` against `AIR_BREAKDOWN_FIELD = 3.0e6 V/m`
  (~30 kV/cm, dry air, uniform field, cm-scale gaps).
- **FEMM electrostatics** — `src/ehdpsu/femm.py`, `solver_inputs/ehd_wire_collector.lua`,
  `solver_inputs/ehd_wire_collector_geometry.txt`.

## Refresh before acting

1. `docs/PHYSICS_NOTES.md` §1 and §2 — the recorded verdicts on Peek and on the current law,
   including exactly which part was found correct and which carries a caveat.
2. `src/ehdpsu/physics.py` module docstring — the parallel-plate versus wire-cylinder discussion,
   which is the most important prose in the repository for this domain.
3. `solver_inputs/ehd_wire_collector_geometry.txt` — what the FEMM run is supposed to read back
   and what disagreement would mean.
4. `.kiro/skills/electrostatics-corona-oracle/task_ledger.md`.

## Live hazards in this domain

**`k_geo` is a parallel-plate coefficient standing in for a wire-to-plane emitter, and it is the
single largest uncertainty in the project.** The script this project inherited uses
`k_pp = 2·ε₀·µ·L/d²`, which assumes a 1-D space-charge-limited gap with uniform field `~V/d` over
a planar area `~L`. The physical emitter is a thin wire facing a plane, whose corona current per
unit length scales as `i' = C_wp·µ·ε₀·V·(V − V_onset)` with `C_wp` an O(1) dimensionless factor
set by the gap-to-radius ratio, **not** by `1/d²`. At `r_wire = 25 µm` and `d = 12 mm` the two
prefactors can differ by roughly an order of magnitude.

It is **kept and labelled**, not replaced with something that fits. Current, power, thrust and
efficiency all descend from it and all inherit its band. Retiring that band is what the FEMM
calibration is for, and until it lands nothing downstream is validated.

**The radius/diameter collision is live in this project's source material.** The design prose
treats "25 µm tungsten" as a **radius**; the reference implementation halves it to a 12.5 µm
radius. At `d = 2.5 mm` those give `V_onset` ≈ 2.10 kV and ≈ 1.63 kV — a 29% split, because the
dimension sits inside both Peek's `1/√r` term and `ln(d/r)`. The prose figure matches the radius
reading. Never accept a wire dimension without establishing which it is.

**FEMM has never been run in this project.** `femm.py` generates a Lua geometry script and a
notes file; no solve has been performed and no field has been read back. Any statement that the
solver "confirms" Peek is unperformed work until a run records its tool version, input hash and
returned values.

**FEMM solves Laplace, with no space charge.** Its peak wire-surface field is therefore the
**corona-onset** field to compare against Peek — **not** the loaded operating field. Once current
flows, ion space charge lowers the near-wire field. Do not use a FEMM result to describe the cell
in operation.

**The 8 mm gap end of the gap sweep is an arc-over watch item.** At 8 mm and 22 kV the mean gap
field reaches ~2.75 MV/m against ~3 MV/m breakdown — a margin of ~1.09, within ~9% of bulk-air
breakdown. That is a real risk of flashover, not a modelling artefact.

## Domain laws

1. **Radius in centimetres inside the Peek term, metres everywhere else.** The conversion
   (`r_wire_m * 100`) is correct in the existing code and is the single easiest thing to break.
   Any change here needs the reference value re-checked: `E_peek = 17.76 MV/m` at
   `r = 25 µm`, `m = 0.8`, `δ = 1.0`.
2. **The quadratic form is settled; only the prefactor is open.** `I = k·V·(V − V_onset)` is the
   standard corona I-V relation and is not the thing to question. Do not "improve" the form while
   the coefficient is the actual uncertainty.
3. **Never substitute a fitted `k`.** If a wire-to-plane coefficient is derived, it is derived
   from geometry or from a solved field with recorded provenance — never chosen because it makes
   a claimed thrust reachable.
4. **A FEMM-derived value is `solved` only with its provenance.** Tool version, input file hash,
   and the values read back. Absent any of the three it is `analytical-placeholder`.
5. **Onset margin and breakdown margin are different quantities.** Corona onset margin is
   `V_op / V_onset` and wants to be large. Mean-gap breakdown margin is
   `AIR_BREAKDOWN_FIELD / (V_op/d)` and wants to stay comfortably above 1. Conflating them
   produces a design that looks safe on one axis while arcing on the other.
6. **State the thin-wire assumption when the geometry approaches its limit.** `V_onset` uses the
   coaxial integral, valid for `d >> r`. At `d/r = 100` it is sound; do not extend it to a
   micro-gap without saying what changed.
7. **Task artifact and ledger entry after any change here.** Append only.

## What this skill deliberately does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope, cited by number and name.
- **The no-curve-fitting rule, the basis ladder and the upper-bound labelling rule** —
  `physics-honesty.md`, always applied.
- **High-voltage bench safety** — `hv-safety.md`, always applied. This domain sets the voltages
  that make that file necessary; it does not restate its procedures.
