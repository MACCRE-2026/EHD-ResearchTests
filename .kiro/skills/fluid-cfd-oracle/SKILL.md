---
name: fluid-cfd-oracle
description: Domain specialist for the fluid side of EHD propulsion — momentum flux and mobility-limited thrust, mesh collector porosity drag, exhaust velocity, the multi-stage velocity-matching penalty, and the coupled Poisson/charge-conservation/Navier-Stokes solve behind the Gmsh, Elmer, OpenFOAM and axisymmetric-Python adapters. Use when touching thrust or fluid functions, the mesh or CFD adapters, or when reasoning about net versus raw thrust, screen drag, or staging.
---

# Fluid Dynamics & CFD Oracle

Domain expertise over momentum transfer and the air's response to the field.

- **Mobility-limited thrust** — `thrust_from_current()`; `T = I·d/µ`, derived from
  `T = ∫ρE dV` with `J = ρµE`.
- **Screen porosity drag** — `K_w = (1 − β²)/β²`, `Δp = K_w·(½ρu²)`; the aerodynamic cost of a
  collector mesh at open-area ratio `β`.
- **Exhaust velocity and momentum flux** — `u = √(F_raw/(ρ·A))`, and net thrust as
  `raw − drag`.
- **Multi-stage velocity matching** — ion transit `t = d/(u_air + µE)`, and why an identical
  second stage does not double thrust.
- **The coupled system** — Poisson `∇²φ = −ρ_q/ε₀`, charge conservation
  `∂ρ_q/∂t + ∇·J = 0`, and Navier-Stokes with the `ρ_q·E` body force.
- **Adapters** — Gmsh meshing; then the routes: in-process axisymmetric Python, Elmer FEM,
  OpenFOAM via WSL2.

## Refresh before acting

1. `docs/PHYSICS_NOTES.md` §3 — the recorded verdict on thrust: correct in form, idealised upper
   bound. That verdict is the reason the fluid layer exists.
2. `artifacts/00_Governance/2026-09-15_PLAN_ehd_modeling_suite.md` — the hand-checked thrust
   discrepancy and the cross-route agreement requirement. Note that those hand-checks are
   **leads**, not findings.
3. `src/ehdpsu/physics.py` — the existing thrust function and its stated assumptions.
4. `.kiro/skills/fluid-cfd-oracle/task_ledger.md`.

## Live hazards in this domain

**No CFD route has ever been executed in this project.** No mesh has been generated, no coupled
solve has been run, and none of Gmsh, Elmer, OpenFOAM or FEniCS is installed. Every fluid number
currently in the repository is closed-form. Any statement about a velocity field, a wake, or a
boundary layer is unperformed work.

**`T = I·d/µ` is a ceiling, not a prediction.** It assumes full ion-to-neutral momentum transfer,
no neutral drag, and a uniform gap field. Real thrust is **lower**. The 9.56 gf MK0 figure and its
3.64 N/kW efficiency are both upper bounds, and both additionally inherit the `k_geo` band from
`electrostatics-corona-oracle`. Reporting either without both caveats overstates by an unknown
factor that is at least 1 and plausibly 10.

**There is currently no drag term at all.** The repository models raw thrust only. Net thrust,
screen drag and exhaust velocity do not exist yet, which means the present "thrust" figure has no
subtractive term whatsoever — it is the most optimistic quantity the project produces.

**The staging penalty is real and counter-intuitive.** Community bench testing found a second
identical stage yielding **under 30%** additional thrust rather than 100%, because stage 1 acts on
still air while stage 2 acts on air already moving. Ions spend less time in the drift region, so
collisional momentum transfer per ion falls. A multi-stage model that scales linearly with stage
count is wrong, and wrong in the flattering direction.

**Thrust-per-watt and thrust-per-mass are different claims.** `F/P = d/(µV) = 1/(µE)`. Holding the
field near breakdown and shrinking the gap leaves `E` roughly unchanged, so N/kW barely moves —
3.64 to 3.33 across the MK0-to-MK1 transition. What improves is thrust-per-**mass**, because
structure falls as `L³` while thrust falls as `L²`. Conflating them turns a scaling argument into
an efficiency claim it does not support, and the project's source material does conflate them.

**Open-area ratio has a genuine optimum, not a monotone trend.** Below ~75% the mesh chokes the
intake; above ~90% ions escape uncollected and form a downstream space-charge cloud that opposes
incoming thrust. The useful band is ~80–88%.

## Domain laws

1. **Net thrust is never greater than raw thrust.** Assert it, do not assume it. A drag term that
   can go negative is a sign error, and a sign error here inflates the headline figure.
2. **Every thrust figure is labelled with what it includes.** `raw`, `net`, or `upper bound`,
   in the identifier and in every column header, axis label and table cell.
3. **A staged model must degrade with stage count.** If adding a stage multiplies thrust by the
   stage count, the velocity-matching term is missing or inert.
4. **The fast route and the high-fidelity route must be compared, and disagreement reported.** The
   in-process axisymmetric solver exists for sweep speed; Elmer exists for fidelity. When they
   disagree, that is the result — not something to average or to resolve by preferring the
   convenient one.
5. **A solver-derived field is `solved` only with recorded provenance.** Tool version, input mesh
   hash, and the values read back. A mesh that was generated but never solved is an input.
6. **State the coupling direction actually implemented.** A one-way solve (field computed, then
   flow) is not the two-way coupled system, and the difference matters once space charge is strong
   enough to alter the field it was produced by.
7. **Mesh convergence is demonstrated, not assumed.** A single-resolution result carries no
   information about its own discretisation error.
8. **Task artifact and ledger entry after any change here.** Append only.

## Route selection is deliberately open

The plan commits to **mapping all routes and investigating them as the suite grows**, not to
picking one early. Treat "not installed" and "not chosen" as first-class states: a missing solver
degrades a capability **visibly** rather than silently substituting a closed-form estimate. Do not
quietly make one route the default because it happens to be present.

## What this skill deliberately does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope, cited by number and name.
- **The upper-bound labelling rule, the basis ladder and the thrust-per-watt versus
  thrust-per-mass distinction as a prose ban** — `physics-honesty.md`, always applied. The physics
  of that distinction is stated here because it belongs to this domain; the writing rule lives
  there.
- **The adapter contract** — `adapter-contract.md`, applied under `src/**/adapters/**`.
