---
name: hv-power-electronics-oracle
description: Domain specialist for the high-voltage supply and driver chain — LLC/half-bridge resonant conversion, transformer design and parasitics, the Cockcroft-Walton multiplier's droop and ripple, HV diode and capacitor selection, GaN and MOSFET switch choice, and the SPICE netlist generator plus LTspice/QSPICE adapters. Use when touching spice.py, physics.py's multiplier functions, the circuit adapters, or when reasoning about droop, ripple, turns ratio, secondary self-capacitance or switch ratings.
---

# HV Power Electronics Oracle

Domain expertise over everything between the DC input and the emitter rail.

- **Cockcroft-Walton droop and ripple** — `cw_voltage_droop()`, `cw_ripple()`;
  `V_droop = (I/(f·C))·((2/3)N³ + (1/2)N² − (1/6)N)` and
  `V_ripple = (I/(f·C))·N(N+1)/2` peak-to-peak.
- **LLC resonant primary** — half-bridge, `Lr`/`Cr` series tank, `Lm` magnetising, dead-time,
  ZVS operation.
- **Transformer design and parasitics** — core selection (PQ26/20 for MK0, EFD15/RM6 for MK1),
  turns ratio, leakage, and secondary self-capacitance `C_sec`.
- **HV rectifier and capacitor ratings** — reverse voltage per CW position, recovery behaviour,
  per-stage capacitance.
- **Switch selection** — GaN HEMT versus superjunction MOSFET, bus voltage margin, gate drive.
- **SPICE generation and adapters** — `src/ehdpsu/spice.py`,
  `solver_inputs/ehd_llc_cw.cir`, `solver_inputs/ehd_llc_cw.asc`.

## Refresh before acting

1. `docs/PHYSICS_NOTES.md` §4 — the recorded verdict on droop and ripple. Both were found correct
   as written; do not re-derive them from scratch and risk introducing an error into formulas that
   already reproduce.
2. `docs/SPEC_SHEET.md` §1–§3 — the part selections and their rating justifications, including
   which numbers are netlist values versus datasheet values.
3. `solver_inputs/ehd_llc_cw.cir` — the actual netlist, especially `.model DHV`, `.model SW`, and
   the `K_xfmr`/`C_sec` elements.
4. `.kiro/skills/hv-power-electronics-oracle/task_ledger.md`.

## Live hazards in this domain

**The diode model's parameters are placeholders, not datasheet values.** `.model DHV` uses
`BV = 20 kV`, `CJO = 2 pF`, `TT = 5 ns`. `BV = 20 kV` deliberately models a full HV stack rather
than a single part, and `CJO`/`TT` are first-order proxies chosen for plausibility. At 250–300 kHz
reverse-recovery charge directly drives CW ripple and switching loss, so **any loss number derived
from this model is uncalibrated.** Refine from the chosen part's datasheet before quoting a loss
or efficiency figure.

**Transformer parasitics are design targets, not measurements.** `Lr = 60 µH`, `Lm = 300 µH`,
`K_xfmr = 0.98`, `C_sec = 47 pF` are values to build and measure the wound part *against*. HV
secondary self-capacitance in particular detunes the tank and rounds the CW drive edges, and it
is the parameter most likely to differ on the real component. LLC tuning derived from these
numbers is provisional until the part is measured.

**No SPICE simulation has ever been run in this project.** `spice.py` generates a netlist; nothing
has solved it. LTspice and QSPICE are not installed. Any statement that the circuit "works in
simulation" is unperformed work.

**The EHD load model is static.** The behavioural `EHD_LOAD` subcircuit implements only the
steady-state quadratic I-V curve. It has no plasma dynamics: no ion-transit lag, no
streamer/spark transition, no frequency dependence. It will not predict the arc-over the gap
sweep flags as a risk, and it should not be used to argue that arcing is absent.

**The load current itself carries the `k_geo` band.** The operating current feeding droop and
ripple descends from an uncalibrated parallel-plate coefficient with roughly a 10× band. Droop and
ripple are correct *given* the current, so their uncertainty is inherited wholesale. See
`electrostatics-corona-oracle`.

**Droop grows as N³.** 445.5 V at N=5 rising to ~1.74 kV at N=8. Adding stages to reach a voltage
is not free, and the sweep exists to make that visible.

## Domain laws

1. **Droop and ripple formulas are settled. Do not re-derive them.** They are the standard HV
   cascade relations, they reproduce exactly, and they have a recorded verdict. Changing them
   requires a cited reason and a re-check of the reference values: 445.5 V droop (2.02%) and
   70.3 V peak-to-peak at the MK0 operating point.
2. **Distinguish a netlist value from a datasheet value in every statement.** The netlist is a
   model; the datasheet is a component. A rating justification that cites the netlist as evidence
   for a real part's capability is circular.
3. **Reverse voltage per CW position is `2·Vp`, not the output voltage.** Each element sees up to
   twice the secondary peak. Sizing a diode against the 22 kV rail overspecifies by roughly 5×;
   sizing it against `Vp` alone underspecifies by 2×.
4. **Never quote a loss or efficiency figure from the placeholder diode model.** Recovery
   behaviour dominates loss at these frequencies and `TT` is a guess.
5. **A simulation result requires a recorded run.** Tool name and version, netlist hash, and the
   values read back — or the netlist is an input file and nothing more.
6. **Voltage margin is stated as a ratio against a named rail.** "600–650 V device on a 400 V bus"
   is a claim with a denominator. "Adequate margin" is not.
7. **Task artifact and ledger entry after any change here.** Append only.

## What this skill deliberately does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope, cited by number and name.
- **The no-curve-fitting rule and the basis ladder** — `physics-honesty.md`, always applied.
- **Bench safety, bleeder sizing and the discharge procedure** — `hv-safety.md`, always applied.
  This domain designs the ladder whose stored energy makes that file necessary; the procedures
  live there.
