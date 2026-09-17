# EHD PSU / driver spec sheet (pre-purchase validation)

This spec sheet ties the **simulated and swept results** of the `ehdpsu`
toolkit to **concrete BOM part selections**, each with a rating justification
and a pointer to the generated file that supports it. It is deliberately framed
as **pre-purchase validation**: no parts are ordered. The purpose is to
establish that the single-cell benchtop design is buildable from off-the-shelf
components and safe at its operating point, so as to **support the funding case
for the later miniaturization + alcohol-cooling phase**.

All numbers below are reproduced by running the toolkit:

```bash
python -m ehdpsu.sanity     # reference operating point + validation notes
python -m ehdpsu.sweeps     # artifacts/07_Outputs/sweep_*.csv + *.png (safety margins)
python -m ehdpsu.spice      # solver_inputs/ehd_llc_cw.cir (+ .asc)
python -m ehdpsu.femm       # solver_inputs/ehd_wire_collector.lua (+ notes)
python -m ehdpsu.telemetry --input tests/data/example_telemetry.csv
```

**Design operating point:** V_op = 22 kV, f_sw = 250 kHz, N = 5 CW stages,
C_stage = 1 nF, r_wire = 25 um, gap = 12 mm, wire length = 15 cm. Burst budget
~80-120 W for 3-5 s.

---

## 1. LLC half-bridge primary switches (GaN / MOSFET)

**Selection:** two 600-650 V enhancement-mode GaN HEMTs (e.g. GaN Systems
GS66504B class) or 650 V superjunction MOSFETs for the half-bridge legs.

**Ratings justification.**

- **Voltage:** the netlist drives the half-bridge from `Vbus = 400 V`
  (`Vbus vbus 0 DC 400.0` in `solver_inputs/ehd_llc_cw.cir`). A 600-650 V device
  gives ~1.5x margin over the 400 V rail, adequate for hard/soft-switched LLC
  ringing.
- **Current / power:** the burst budget is ~80-120 W (confirmed by the
  telemetry example: `P_in` peak 110 W, mean ~99 W over the 1-5 s burst window
  from `python -m ehdpsu.telemetry`). At 400 V bus this is well under 1 A of
  primary current; the switch current rating is set by the resonant circulating
  current, not the DC average, so a device rated for several amps RMS is
  comfortable.
- **Switching:** f_sw = 250 kHz with 80 ns dead-time per edge
  (`Vg_hi`/`Vg_lo` PULSE sources). GaN's low Qg/Coss favors the soft-switching
  LLC operation and keeps gate-drive losses low at this frequency.

**Supporting files:** `solver_inputs/ehd_llc_cw.cir` (`Vbus`, gate `PULSE` sources,
`M1`/`M2` switches, `.model SW`); `artifacts/07_Outputs/example_telemetry_derived.csv` and
the telemetry burst summary for the real burst power envelope.

---

## 2. PQ26/20 HF transformer (turns ratio and parasitic targets)

**Selection:** PQ26/20 ferrite core (N87/3C95 class), litz primary, layered /
sectioned HV secondary.

**Targets from the SPICE model (`solver_inputs/ehd_llc_cw.cir`).**

| Parameter | Netlist value | Meaning / target |
| --- | --- | --- |
| Turns ratio (sec:pri) | **12** | Steps 400 V bus toward the ~2.2 kV peak needed to feed the CW ladder |
| `Lr` (resonant + leakage) | **60 uH** | Series tank inductance; also lumps primary leakage |
| `Cr` (resonant cap) | **6.8 nF** | Sets LLC series resonance with `Lr` |
| `Lm` (magnetizing) | **300 uH** | Across the primary winding (`L_pri`) |
| `L_sec` | **43.2 uH** | Secondary self-inductance (= Lm * ratio^2 scaling) |
| `K_xfmr` coupling | **0.98** | PQ26/20 winding coupling; lower toward 0.95 to model more leakage |
| `C_sec` (secondary self-C) | **47 pF** | HV winding self-capacitance; **measure on the real part** and refine |

**Justification.** The turns ratio is chosen so the secondary peak feeding the
CW ladder is ~2.2 kV (Vout / (2N) = 22 kV / 10), which the 5-stage doubler
raises to the 22 kV operating point. `Lr`/`Cr`/`Lm` define the LLC resonance;
these are **design targets to build/measure the transformer against**, not
free-fit values. `C_sec` is called out explicitly because HV secondary
self-capacitance detunes the tank and rounds the CW drive edges; the netlist
comments instruct measuring it on the wound part.

**Supporting files:** `solver_inputs/ehd_llc_cw.cir` (`Lr`, `Cr`, `Lm`, `L_pri`,
`L_sec`, `K_xfmr`, `C_sec`), plus the module's printed "how the model maps to
real parts" notes from `python -m ehdpsu.spice`.

---

## 3. Cockcroft-Walton ladder: HV diodes and capacitors

**Diode selection:** ultrafast / fast-recovery HV rectifiers, e.g. a 15-20 kV
stacked fast diode or a series string of 2-3 kV ultrafast parts per position.

**Ratings justification.**

- **Reverse voltage (Vrrm):** each CW element sees up to **2 * Vp** in reverse,
  where Vp is the secondary peak (~2.2 kV), i.e. ~**4.4 kV per stage**. The
  SPICE diode `.model DHV` uses **BV = 20 kV**, which is intentionally
  conservative (it models a full HV stack); a real per-position part needs a
  comfortable margin over 4.4 kV. Target **>= ~2x** the per-stage 2*Vp, i.e.
  >= ~9 kV Vrrm per position (or a series string that sums to it).
- **Recovery:** the `.model DHV` uses `CJO = 2 pF`, `TT = 5 ns` as first-order
  proxies. At 250 kHz the reverse-recovery charge (Qrr/trr) directly costs CW
  ripple and switching loss, so **ultrafast** recovery is required; refine
  `TT`/`CJO` from the chosen datasheet before trusting loss numbers (the netlist
  comments say exactly this).

**Capacitor selection:** the ladder uses **1 nF per-stage** caps
(`Cc*`/`Cs* ... 1n`). Each cap sees up to **2 * Vp (~4.4 kV)**; pick HV ceramic
(e.g. 6.3-10 kV rated) for **>= ~1.5-2x** margin. The `sweep_capacitance.csv`
study confirms droop and ripple scale as `1/C`, so a larger cap directly buys
lower droop if board area allows.

**Supporting files:** `solver_inputs/ehd_llc_cw.cir` (`.model DHV`, the `Cc*`/`Cs*`
1 nF ladder, `Dd*` diodes); `artifacts/07_Outputs/sweep_capacitance.csv` /
`sweep_capacitance.png` (ripple/droop vs C); `artifacts/07_Outputs/sweep_stages.csv` /
`sweep_stages.png` (droop grows as N^3: 445.5 V at N=5, rising to ~1.74 kV at
N=8, confirming N=5 as a sound choice); `artifacts/07_Outputs/sweep_frequency.csv` (ripple
falls as 1/f, justifying the 250 kHz choice).

---

## 4. Emitter wire and gap (corona and air-breakdown margins)

**Selection:** **25-50 um tungsten** emitter wire, **~12 mm** emitter-collector
gap, ~15 cm wire length.

**Ratings justification (from the sweeps).**

- **Corona onset margin** at the 22 kV operating point is **~8.0** (V_op /
  V_onset = 22 kV / 2.74 kV), from `artifacts/07_Outputs/sweep_voltage.csv`. The design runs
  well above corona inception, as intended.
- **Air-breakdown margin** at the base 12 mm gap / 22 kV is **~1.64** (mean gap
  field V/d vs ~3 MV/m ~ 30 kV/cm bulk-air breakdown), from
  `artifacts/07_Outputs/sweep_gap.csv` and `sweep_voltage.csv`.
- **Watch item:** at the **8 mm gap end with V_op = 22 kV the air-breakdown
  margin collapses to ~1.09** (`artifacts/07_Outputs/sweep_gap.csv`, first row: mean gap
  field ~2.75 MV/m against ~3 MV/m breakdown). Running that tight a gap at full
  voltage puts the mean gap field within ~9% of bulk-air breakdown, i.e. at real
  risk of arc-over. **Keep the gap at ~12 mm (or larger) at 22 kV**, or reduce
  voltage if a smaller gap is required for the miniaturization phase.
- **Wire radius:** the `sweep_wire_radius.csv` study over 25-50 um shows E_peek
  falling from ~17.76 MV/m (25 um) to ~13.28 MV/m (50 um) and V_onset rising;
  the air-breakdown margin is set by the gap, not the wire, so any wire in the
  25-50 um band is acceptable. Thinner wire lowers onset voltage (easier corona
  start) at the cost of faster erosion; 25-50 um tungsten balances erosion life
  against onset.

**Supporting files:** `artifacts/07_Outputs/sweep_gap.csv` / `sweep_gap.png` (the 8 mm ~1.09
margin), `artifacts/07_Outputs/sweep_voltage.csv` / `sweep_voltage.png` (margins vs voltage),
`artifacts/07_Outputs/sweep_wire_radius.csv` / `sweep_wire_radius.png` (E_peek/onset vs wire
radius), and `solver_inputs/ehd_wire_collector.lua` /
`ehd_wire_collector_geometry.txt` (FEMM electrostatics cross-check: the
solver's peak wire-surface field should match the analytical E_peek = 17.76
MV/m).

---

## 5. Telemetry and control

**Selection.**

- **Load cell + HX711** 24-bit ADC for thrust measurement (mN-resolution over
  the ~10 mN peak seen in the example burst).
- **INA226** high-side current/power monitor for the input rail (bus voltage and
  input power logging).
- **ESP32-S3** (or STM32) controller for burst sequencing, HV enable, split-
  collector thrust-vectoring drive, and CSV logging.

**Justification.** The telemetry schema (`t_s, F_mN, V_HV_kV, I_HV_mA, P_in_W`)
is exactly what `python -m ehdpsu.telemetry` ingests and reduces. On the example
log it computes a **1-5 s burst window**, thrust mean **7.78 mN** / peak
**10 mN**, P_in mean **98.9 W** / peak **110 W**, P_HV mean **77.8 W**, and
system efficiency (P_HV/P_in) **~78%**. The HX711's resolution and the INA226's
bus/current ranges comfortably cover these values. This closes the loop:
measured thrust/power can be compared against the physics-model upper bound.

**Supporting files:** `tests/data/example_telemetry.csv` (ESP32 schema),
`artifacts/07_Outputs/example_telemetry_derived.csv`, `example_telemetry_thrust_power.png`,
`example_telemetry_efficiency.png`.

---

## 6. Open questions / model limitations

These are stated plainly so the funding case is not oversold:

1. **EHD current-law geometry uncertainty.** The ion-current prefactor `k` is a
   **labeled parallel-plate coefficient** used for a wire-to-plane emitter; the
   true wire-cylinder prefactor can differ by roughly an order of magnitude (see
   [PHYSICS_NOTES.md](PHYSICS_NOTES.md) Section 2). Current, power, thrust, and
   efficiency all inherit this O(1)-to-O(10) band. A FEMM field solve or a
   measured I-V curve is needed to calibrate it. Nothing was curve-fit to hide
   this.
2. **Idealized thrust upper bound.** `T = I * d / mu` is a **mobility-limited
   maximum** (full ion-to-neutral momentum transfer, no neutral drag, uniform
   field). Real thrust will be **lower**; the 9.56 gf figure is a ceiling, not a
   prediction. Efficiency (3.64 N/kW) inherits the same ceiling plus the
   current-law uncertainty.
3. **Static EHD SPICE load.** The behavioral `EHD_LOAD` subckt models only the
   steady-state quadratic I-V curve; it has no plasma dynamics (no ion-transit
   lag, no streamer/spark transition, no frequency dependence).
4. **Electrostatic-only FEMM.** The FEMM solve is Laplace (no space charge), so
   it validates the **corona-onset** field, not the loaded operating field (ion
   space charge lowers the near-wire field once current flows).
5. **Transformer parasitics are targets, not measurements.** `Lr`, `Lm`, and
   especially `C_sec` must be measured on the wound PQ26/20 part and fed back
   into the netlist before the LLC tuning is trusted.

**Bottom line for funding.** With honest caveats, the sweeps and simulations
show a single-cell benchtop EHD PSU that (a) is buildable from off-the-shelf
600-650 V GaN/MOSFET, PQ26/20, ultrafast HV diode, and HV ceramic parts; (b)
operates with an ~8x corona-onset margin and an adequate ~1.64x air-breakdown
margin at 12 mm / 22 kV (with a clear "do not shrink the gap to 8 mm at full
voltage" caution); and (c) has a defined measurement path (HX711 + INA226 +
ESP32) to calibrate the one genuinely uncertain parameter. That is the concrete
basis for funding the miniaturization + alcohol-cooling phase.
