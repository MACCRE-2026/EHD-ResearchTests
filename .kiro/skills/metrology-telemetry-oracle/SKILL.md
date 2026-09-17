---
name: metrology-telemetry-oracle
description: Domain specialist for physical measurement and the calibration loop — the HX711 load cell, INA226 power monitor, HV divider and shunt current sense, the ESP32 telemetry schema, measurement uncertainty, simulated-versus-measured comparison, and fitting k_geo from a measured I-V curve. Use when touching telemetry.py, controller firmware, bench procedures, or anything that turns an instrument reading into a number the model is judged against.
---

# Metrology & Telemetry Oracle

Domain expertise over the only inputs in this project that are not derived: things an instrument
actually measured.

- **Thrust** — 100 g micro cantilever load cell into an HX711 24-bit ADC, ~80 Hz.
- **Input power** — INA226 high-side current and bus voltage monitor.
- **High voltage** — 50 MΩ into 50 kΩ, a 1000:1 divider.
- **Ion current** — low-side shunt on the collector return (100 Ω at MK1 scale).
- **Controller and schema** — ESP32-S3; CSV as `t_s, F_mN, V_HV_kV, I_HV_mA, P_in_W`.
- **Reduction and comparison** — `src/ehdpsu/telemetry.py`, burst-window detection, derived
  thrust/power/efficiency, and simulated-versus-measured overlay.
- **Calibration** — fitting the wire-to-plane current coefficient from a measured I-V curve.

This domain owns the top rung of the basis ladder. A `measured` value is the only kind that can
retire an `analytical-placeholder`, which makes the integrity of this domain the ceiling on the
whole project's credibility.

## Refresh before acting

1. `tests/data/example_telemetry.csv` — the exact schema, column order and units. Order matters
   for the validation messages.
2. `src/ehdpsu/telemetry.py` — the existing reduction, burst-window logic and summary fields.
3. `examples/example_telemetry_derived.csv` — the pinned reference reduction.
4. `docs/SPEC_SHEET.md` §5 — the instrument selections and the ranges they were chosen against.
5. `.kiro/skills/metrology-telemetry-oracle/task_ledger.md`.

## Live hazards in this domain

**The load cell measures net thrust minus mount reaction, not raw thrust.** A cell mounted under
a ducted assembly reads the *whole assembly's* reaction, which already includes collector screen
drag and duct losses. The model's `T = I·d/µ` is *raw* thrust. Comparing the two directly compares
different quantities and will appear to show the model overpredicting by whatever the drag happens
to be. Compare measured against **net**, or say explicitly which is which.

**A measured value is not automatically trustworthy — it carries its own uncertainty.** `measured`
is the top of the basis ladder, not an exemption from bands. HX711 resolution, load-cell
nonlinearity and creep, divider ratio tolerance, shunt tolerance and ADC reference drift all
propagate. A measurement quoted without its instrument uncertainty is a `claimed` value wearing a
better label, and that is precisely the laundering this project exists to prevent.

**Ozone and nitric acid attack the emitter during the very runs being measured.** Positive corona
in ambient air embrittles fine tungsten within minutes to hours. So the wire's effective radius —
and therefore onset voltage — **drifts during a test campaign**. A long series of runs is not a
series of measurements of one apparatus. Record wire age and replacement events alongside the
data, or the calibration fits to a moving target.

**Humidity and air density are uncontrolled and both matter.** Peek's law carries `δ` explicitly,
and ion mobility and corona behaviour are humidity-sensitive. Bench data taken without recording
ambient temperature, pressure and relative humidity cannot be compared across days, and cannot
legitimately calibrate `δ`-dependent terms.

**Thermal drift in a 5-second burst is real for the load cell, not for the electronics.** The GaN
stage and core barely warm over 5 s. The load cell and its mount, however, respond to airflow and
to any thermal gradient, and a cantilever's zero can walk. Tare immediately before each burst, and
record the pre- and post-burst zero.

**No physical measurement exists yet.** `tests/data/example_telemetry.csv` is an example file, not
bench data. Nothing in this project has been measured. Every number is analytical.

## Domain laws

1. **Every measured quantity carries its instrument uncertainty.** Resolution, tolerance and any
   known nonlinearity, stated where the number is stated.
2. **Compare like with like.** Measured net against modelled net. If only raw is modelled, say so
   and do not present the difference as model error.
3. **Record the environment with the data.** Temperature, pressure, relative humidity, wire age,
   and the run index. Data without ambient conditions cannot be pooled.
4. **Tare per burst, and record both zeros.** A single tare at the start of a campaign is a drift
   measurement disguised as a thrust measurement.
5. **A fitted coefficient is fitted to data, with its residuals reported, and it is never tuned to
   a target.** Calibrating `k_geo` from a measured I-V curve is legitimate and is the point.
   Adjusting it so a thrust figure reaches a hoped-for number is the thing this project forbids;
   the difference is whether a measurement or a wish is the input.
6. **A measured point outside the model band is a finding, and it is reported, not excluded.** The
   band widening or the model being wrong are both acceptable outcomes. Dropping the point is not.
7. **Every generated bench procedure and firmware carries the safety elements.** Bleeder sizing,
   explicit discharge step, verify-dead, interlock failing to off, single-hand rule. A procedure
   missing any of them is incomplete, not terse.
8. **Task artifact and ledger entry after any change here.** Append only.

## Why this domain is the project's pivot

Everything else produces predictions. This produces evidence. The MK1 milestone is named
*Concept/Reality Alignment Baseline* because a single honest I-V curve and thrust series from this
domain does more for the project's credibility than any amount of additional modelling — it is the
only thing that can move `k_geo` off `analytical-placeholder` and narrow every band that descends
from it.

That leverage cuts both ways. A sloppy measurement presented as `measured` corrupts the basis
ladder at its top rung, and every downstream number inherits a confidence that was never earned.

## What this skill deliberately does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope, cited by number and name.
- **The basis ladder and the no-curve-fitting rule** — `physics-honesty.md`, always applied.
- **The full bench safety procedure** — `hv-safety.md`, always applied. Law 7 above points at it;
  it does not reproduce it.
- **What `k_geo` is and why it is uncertain** — `electrostatics-corona-oracle`.
