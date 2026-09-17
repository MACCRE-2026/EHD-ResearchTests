---
inclusion: fileMatch
fileMatchPattern:
  - 'src/**'
  - 'profiles/**'
  - 'tests/**'
---

# The profile seam

Applied automatically when editing source, profiles or tests. `suite-core-oracle` owns this
domain; this file is the subset that must be in front of you while the file is open.

---

## The rule

**A design value lives in the profile and nowhere else.**

Not in a dataclass default, not in a module constant, not in a docstring, not in a plot label, not
in a test fixture, not in a generated netlist. Anything that needs a design number reads it from
the profile.

*Principle 4, two representations of one thing will drift.* Not eventually — reliably, and
silently, because both copies keep working while they disagree.

## Why this is live right now

**Five representations of the 22 kV design point exist in this repository today.** The values
appear in `physics.py`'s `DesignParameters` defaults, in `README.md`, in `docs/SPEC_SHEET.md`, in
`docs/PHYSICS_NOTES.md`, and inside the text of the generated netlist. Changing one and not the
other four is a drift, and there is currently nothing stopping it.

The profile layer exists to end that condition, and it is sequenced **before** the fluid, adapter
and CFD work for one reason: every module built against `DesignParameters` before the migration is
a module that has to be migrated twice.

## Naming, which is not a style preference

**Units in every identifier. Radius versus diameter explicit, always.**

```
r_wire_m        not  wire, wire_size, r_wire
d_gap_m         not  gap, spacing
d_mesh_wire_m   not  mesh_wire        (mesh specs quote DIAMETER)
pitch_mesh_m    not  mesh_pitch
L_wire_m        not  length
```

The reason is concrete rather than aesthetic. "25 µm tungsten" read as a radius gives
`V_onset ≈ 2.10 kV`; read as a diameter it gives `≈ 1.63 kV` — a **29% split**, because the
dimension sits inside both Peek's `1/√r` term and `ln(d/r)`. **Both readings already exist in this
project's source material**: the design prose used one and the reference implementation used the
other. This is a live defect, not a hypothetical.

## Quantities, not floats

A number crossing a module boundary carries `value`, `unit`, `band`, `basis`, `refs` and
`is_upper_bound`.

- **A band is never tightened — and which band depends on the operation.** Low-water-mark, always
  — *principle 1, trust is a ceiling inherited from provenance*.

  **Amended 2026-09-15**, because the unqualified rule is wrong for addition and the code had to
  learn the difference. This bullet previously read "a function returning a narrower band than it
  received is a bug even when every arithmetic step is right", full stop.

  *The incident:* `Quantity.__add__` was caught by its own postcondition. Adding an exact `3` to a
  `2` carrying a ×10 band leaves the **absolute** uncertainty at `1.8` — unchanged — while the
  magnitude grows to `5`, so the **relative** band becomes `×0.64 to ×1.0`. That is a genuine
  narrowing of the relative band and nothing was laundered. Forcing it to stay at ×10 would
  **invent** uncertainty, which is its own dishonesty.

  Neither measure is scale-invariant — dividing by an exact `3` shrinks absolute uncertainty
  threefold while leaving the relative band untouched — so each is enforced where it is the
  meaningful one:

  - **Multiplicative** (`*`, `/`, powers): the **relative** band is preserved or widened. This is
    the family where `k_geo`'s ×10 must survive to the last published figure.
  - **Additive** (`+`, `-`): the **absolute** uncertainty is preserved or widened.

  A violation of either is a defect in the propagation code, not in the caller, and
  `ehdpsu.quantity` raises with distinct messages so a reader is not sent after the wrong cause.

- **Correlation is not tracked, so correlated inputs over-widen.** Always conservatively, never
  flatteringly, which is why it is tolerated. The live case: `T/P` reports a ×100 band from two
  ×10 inputs because `k_geo` appears in both, while physically it **cancels** —
  `F/P = d/(µV)` contains no `k_geo` at all and its band from `k_geo` is exact.

  **The fix is never to special-case the cancellation**: that would be a hidden tightening, and the
  next correlated pair would not get it. Each published quantity is derived from **its own cited
  relation**, and two independent routes disagreeing is a finding for the cross-validation engine to
  *report* — never something the arithmetic layer reconciles.
- **`basis` follows provenance, not the caller's confidence.** Anything computed from an
  `analytical-placeholder` input stays `analytical-placeholder`.
- **A `claimed` input cannot yield a `validated` output.** Enforced in code, not by review.

## Before adding a design parameter

1. Does it already exist in the profile under a different name? Use it.
2. Is it a *design* value or a *derived* value? Derived values are computed, never stored.
3. Does its name carry its unit and, if a length, whether it is a radius or a diameter?
4. Does the schema version need incrementing, and is the migration explicit?

## Tests are not exempt

A test fixture with a hardcoded design value is a sixth representation. Load the profile, or
construct one explicitly in the test and say why that value was chosen.

The exception is a **pinned reference value** — `E_peek = 17.76 MV/m`, `V_onset = 2.74 kV`,
`I = 1.17 mA`, `droop = 445.5 V`. Those are deliberately hardcoded, because their whole job is to
fail when the physics moves. Name them as reference constants so the intent is unmistakable.

## What this file does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope. Cite by number and name.
- **The no-curve-fitting rule and the full basis ladder** — `physics-honesty.md`, always applied.
- **The schema, migration and cross-validation detail** — `suite-core-oracle`.
