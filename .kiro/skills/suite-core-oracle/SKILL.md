---
name: suite-core-oracle
description: Domain specialist for the modeling suite's own machinery — the spec-scope-profile schema and its versioning, the Quantity layer that carries value/unit/band/basis/refs, low-water-mark uncertainty propagation, the cross-validation engine that adjudicates claimed-versus-derived, and the CLI. Use when touching profile.py, quantity.py, validate.py, the CLI entrypoints, or anything that decides where a design number lives or how confidence attaches to it.
---

# Suite Core Oracle

Domain expertise over the seam itself. Every other Oracle's work passes through this one.

- **Profile schema and versioning** — the spec-scope-profile: create, save, load, validate, diff,
  migrate. `src/ehdpsu/profile.py` (planned), `profiles/*.json`.
- **The Quantity layer** — `value`, `unit`, `band`, `basis`, `refs`, `is_upper_bound`, and the
  arithmetic that propagates them.
- **Cross-validation engine** — independent routes to the same quantity, and the claimed-versus-derived
  adjudication that makes an optimistic input self-flagging.
- **CLI and orchestration** — `ehdsuite profile|validate|run|sweep|report|doctor`.
- **The Gate** — `.kiro/governance/gate.ps1`: the unscopeable, zero-cost verification command that
  runs every turn, plus the `Stop` hook that invokes it. Its check set is a ledger of everything
  this project has ever got wrong, and it grows every time something is caught.
- **The Survey** — the second tier: occasional, expensive, non-deterministic problem finding,
  reached for when a wall has been hit that nobody has identified yet. Its output is **new Gate
  checks**; that one-directional interface is what makes the flywheel structural. Task 21, and
  deliberately provisional.
- **Existing surfaces this replaces or absorbs** — `src/ehdpsu/physics.py`'s `DesignParameters`
  dataclass, and the module-level default constants in `sweeps.py`, `telemetry.py`, `spice.py`,
  `femm.py`.

## Refresh before acting

1. `artifacts/00_Governance/2026-09-15_PLAN_ehd_modeling_suite.md` — the architecture, the task
   sequence, and every appended correction and task amendment.
2. `artifacts/00_Governance/2026-09-15_DECISION_verification_architecture.md` — the two-tier
   Gate/Survey design, the check catalogue with its per-task placement, and the acknowledged
   tradeoff that dimensional analysis lives **inside `Quantity`** rather than in a standalone
   checker. Read this before touching the Quantity layer.
2. `artifacts/00_Governance/ROADMAP_Eisenhower_LT.md` — which milestone is active and what its
   exit criteria are.
3. `src/ehdpsu/physics.py` — the current `DesignParameters` and every cited formula, before
   changing where its values come from.
4. `docs/PHYSICS_NOTES.md` — the formula-by-formula verdicts, so a migration does not quietly
   change a number that has a recorded provenance.
5. `.kiro/skills/suite-core-oracle/task_ledger.md` — what previous work in this domain decided.

`artifacts/` is untracked and absent from every clone. Never cite it as evidence in a commit or
in anything public.

## Live hazards in this domain

**Five representations of one design point exist right now.** The 22 kV benchtop values appear in
`physics.py`'s dataclass defaults, in `README.md`, in `docs/SPEC_SHEET.md`, in
`docs/PHYSICS_NOTES.md`, and inside the generated netlist text. Until the profile layer lands and
everything reads through it, any change to a design value must be made in all five or it has
drifted. This is the condition the profile layer exists to end, and the reason it is sequenced
before the fluid and CFD work rather than after.

**`V_out_noload_ref_kV` in the stages sweep is wrong by a factor of ten.** `sweeps.py` passes
`V_op` — the 22 kV multiplier *output* — where the ~2.2 kV secondary peak belongs, so the column
reads `44·N` kV instead of `4.4·N`. The docstring is honest that the value is only a scaling
reference; the CSV column carries a `_kV` suffix and no caveat. The reference file is withheld
from `examples/` and `tests/test_examples.py::test_withheld_stages_reference_is_absent` asserts
it stays out. Fixing the column means deleting that test in the same change.

**~~`mypy src` currently checks zero files~~ — RESOLVED 2026-09-15.** The pin was `python_version
= "3.11"` against numpy 2.5.3's stubs, so `mypy src` aborted inside the stubs having examined
**zero** files while reporting one tidy error. Fixed to `3.12` during the Gate's construction, and
`requires-python` was narrowed to match in Task 6. Three files now state that floor and
`tests/test_environment_lock.py` asserts they agree. The Gate additionally fails with a distinct
`MYPY-CHECKED-NOTHING` status if the examined-file count is ever zero again, so this cannot recur
silently. Kept here rather than deleted: the incident is why the Gate counts files instead of
trusting exit codes.

## Domain laws

1. **The profile is the only home for a design value.** No module, document, netlist, plot label
   or test may hardcode one. A test asserts this; when it fails, the fix is to read from the
   profile, never to update the second copy.
2. **Every field name carries its unit, and radius versus diameter is explicit.** `r_wire_m`, not
   `wire`. This is not style: both readings of "25 µm" already exist in this project's source
   material and they differ by 29% in onset voltage.
3. **A Quantity's band is never tighter than its worst input.** Low-water-mark, always. A
   function that returns a tighter band than it received is a bug even if every number in it is
   right.
4. **`basis` is assigned by provenance, never by the caller's confidence.** A value computed from
   an `analytical-placeholder` input is `analytical-placeholder` regardless of how many correct
   steps followed it.
5. **A `claimed` input cannot produce a `validated` output.** This is enforced structurally in
   the propagation code, not by review. If it is possible to express, it will eventually be
   expressed.
6. **The schema is versioned and migrations are explicit.** A profile that loads under a newer
   schema without stating what was migrated is a silent reinterpretation of the operator's
   design intent.
7. **Cross-validation reports disagreement; it never reconciles it.** When two independent routes
   to a quantity differ, both numbers and the ratio are reported. Choosing between them is a
   physics decision belonging to the relevant domain Oracle, not to the engine.
8. **A task artifact and a ledger entry after any change here.** Dated artifact in
   `artifacts/00_Governance/`, appended bullet in this skill's `task_ledger.md`. Append only.

## Sequencing constraint this domain owns

The profile layer and the Quantity layer are **prerequisites**, not parallel work. Every module
built against `DesignParameters` before the migration is a module that has to be migrated twice.
When asked to add a physics or adapter capability before the seam exists, say so and propose the
ordering rather than building against the shape that is about to change.

## What this skill deliberately does not restate

- **The eight principles** and the append-only rule — `maccre-systems-doctrine.md` at user scope.
  Cite by number **and** name.
- **The physics honesty rules** — `physics-honesty.md`, always applied, including the basis ladder
  and the no-curve-fitting rule.
- **The datacenter layout and git discipline** — `ehd-dev-rules.md`, always applied.
