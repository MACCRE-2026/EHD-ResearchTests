# Physics validation notes

This document records the formula-by-formula validation of the original
benchtop-EHD sanity-check script that the `ehdpsu` toolkit reproduces and
extends. For each relation we state the reference, whether the original script
was **correct as written**, and any **caveat or correction** applied with its
reasoning.

**No numbers were curve-fit or invented.** Every reference operating point is
computed from first-principles formulas with cited coefficients. Where a
coefficient is geometry dependent and uncertain, it is exposed as a clearly
labeled model parameter rather than tuned to hit a target. The exact reference
values quoted below are reproduced live by `python -m ehdpsu.sanity`.

Base design parameters used throughout: r_wire = 25 um, gap d = 12 mm,
wire length L = 15 cm, V_op = 22 kV, f_sw = 250 kHz, N = 5 CW stages,
C_stage = 1 nF, ion mobility mu ~ 1.5e-4 m^2/(V*s) (air).

---

## 1. Peek's law -- corona inception field and onset voltage

**Formula.**

```
E_peek = g0 * m * delta * (1 + c / sqrt(delta * r_cm))     [V/m]
V_onset = E_peek * r * ln(d / r)                             [V]
```

with g0 = 3.1e6 V/m, roughness factor m, relative air density delta, empirical
constant c = 0.308 cm^0.5, and the wire radius `r_cm` expressed in centimeters
(the script correctly converts `r_wire * 100`). `V_onset` is the
coaxial-cylinder field-to-voltage integration, valid for a thin wire when
`d >> r`.

**Reference values (reproduced):** E_peek = **17.76 MV/m**, V_onset = **2.74 kV**.

**Verdict: CORRECT as written.** The functional form, the coefficient values,
and the unit handling (radius in cm inside the Peek term) all match the standard
high-voltage engineering literature. No correction.

**References.** F. W. Peek, *Dielectric Phenomena in High Voltage Engineering*
(1929); Kuffel, Zaengl & Kuffel, *High Voltage Engineering: Fundamentals*, 2nd
ed., p.366 (corona inception, Peek's formula and the coaxial field integral).

---

## 2. Ion current -- Townsend quadratic law (with prefactor caveat)

**Formula.**

```
I = k * V * (V - V_onset)     for V > V_onset      [A]
```

**Reference value (reproduced):** I = **1.17 mA** at 22 kV, electrical power
**25.79 W**.

**Verdict: form CORRECT; prefactor carries a documented O(1)-to-O(10) caveat.**

The quadratic (Townsend) voltage-current form `I = k*V*(V - V_onset)` is the
standard corona/EHD I-V relationship and is correct. The **caveat is on the
prefactor** `k`. The original script uses

```
k_pp = 2 * eps0 * mu * L / d^2
```

which is a **parallel-plate (1-D, Mott-Gurley-like) coefficient**: it assumes a
uniform field ~ V/d over a planar area ~ L. The physical emitter is a **thin
wire facing a plane**, whose corona current per unit length scales as

```
i' = C_wp * mu * eps0 * V * (V - V_onset)
```

with `C_wp` an O(1) dimensionless factor set by the gap/radius ratio, **not** by
`1/d^2`. For r_wire = 25 um and d = 12 mm the two prefactors can differ by
roughly an order of magnitude.

**Decision (no curve-fitting).** We **keep the labeled parallel-plate
coefficient** and explicitly flag the order-of-magnitude uncertainty in the
code, the sanity output, and the sweeps, rather than substituting a fitted
replacement to hit any target. The coefficient is surfaced as a named,
documented model parameter (`k_geo`) so that a future FEMM/measured calibration
can replace it transparently. Because current, power, thrust, and efficiency all
inherit `k`, they share this uncertainty band.

**References.** Peek (1929); Kuffel & Zaengl (corona current); Bahder & Fazi,
ARL-TR-3005 (2003) for the EHD force/current context.

---

## 3. Thrust -- mobility-limited upper bound

**Formula.**

```
T = I * d / mu     [N]
```

derived from `T = integral(rho * E) dV` with `J = rho * mu * E` and
`I = J * A`, which collapses to `I * d / mu` for a gap `d`.

**Reference values (reproduced):** T = **0.0938 N (9.56 gf)**, thrust
efficiency **3.64 N/kW**.

**Verdict: CORRECT IN FORM, but an IDEALIZED UPPER BOUND.** The relation is the
standard mobility-limited EHD thrust ceiling. It assumes full ion-to-neutral
momentum transfer, no neutral drag, and a uniform gap field; **real thrust is
lower**. The efficiency (N/kW) inherits both this upper-bound nature and the
current-law prefactor uncertainty from Section 2. We report it plainly as an
upper bound and never present it as a predicted achievable thrust.

**References.** Bahder & Fazi, *Force on an Asymmetric Capacitor*, ARL-TR-3005
(2003); Christenson & Moller, AIAA J. (1967).

---

## 4. Cockcroft-Walton droop and ripple

**Formulas.**

```
V_droop  = (I / (f * C)) * ((2/3) N^3 + (1/2) N^2 - (1/6) N)     [V]
V_ripple = (I / (f * C)) * N (N + 1) / 2                          [V, pk-pk]
```

**Reference values (reproduced):** loaded droop **445.5 V (2.02%)**, pk-pk
ripple **70.3 V** (5-stage, 250 kHz, 1 nF, at the 22 kV operating point).

**Verdict: BOTH CORRECT.** These are the standard high-voltage cascade
(Cockcroft-Walton) generator formulas for output-voltage drop and ripple under
DC load. Reproduced with no correction. The `sweep_stages.csv` /
`sweep_frequency.csv` / `sweep_capacitance.csv` studies show the expected
`N^3` droop growth and the `1/(f*C)` scaling.

**References.** Kuffel, Zaengl & Kuffel, *High Voltage Engineering:
Fundamentals* (cascade / Greinacher-Cockcroft-Walton generator, voltage drop and
ripple).

---

## Summary

| Section | Relation | Verdict |
| --- | --- | --- |
| 1 | Peek inception E_peek, V_onset | Correct as written |
| 2 | Townsend quadratic current `I = k V (V - V_onset)` | Form correct; prefactor is a labeled parallel-plate (order-of-magnitude) parameter |
| 3 | Thrust `T = I d / mu` | Correct in form; idealized upper bound |
| 4 | CW droop and ripple | Both correct |

Sections 1 and 3 (form) and Section 4 reproduce with **no correction**.
Section 2's numbers are reproduced **exactly** but carry two documented caveats
(parallel-plate current prefactor; idealized upper-bound thrust/efficiency).
Nothing was curve-fit or invented; the uncertain coefficient is labeled and
left in place pending a FEMM or measured calibration.
