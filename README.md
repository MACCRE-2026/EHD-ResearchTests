# ehdpsu

Analytical and simulation toolkit to validate a **benchtop single-cell EHD
(electrohydrodynamic / Biefeld-Brown) thruster power supply and driver** before
any parts are purchased.

This is a pre-purchase proof-of-concept validation project. The goal is to
simulate and validate the design premises (corona inception, ion current,
thrust, Cockcroft-Walton multiplier health, driver-chain topology) with
**honest, cited physics** and no curve-fitting, then use the results to nail
down a part/spec sheet. The spec sheet is intended to support the funding case
for the later miniaturization + alcohol-cooling phase.

## Design targets (from the design conversation)

- Single thruster cell, ~80-120 W peak burst (3-5 s bursts)
- +15 kV to +25 kV DC output
- LLC/half-bridge GaN/MOSFET primary -> PQ26/20 HF transformer -> 5-stage
  Cockcroft-Walton multiplier
- 25-50 um tungsten emitter wire, ~12 mm gap, ~15 cm wire length
- Split-collector solid-state thrust vectoring
- Load-cell (HX711) + INA226 telemetry logged to CSV
- ESP32-S3 / STM32 controller

## Sandbox vs. local GUI tools

The **Python layer runs and is validated in-sandbox**: the physics core, the
parameter sweeps, the telemetry reduction, and the artifact generators all
execute here and their outputs are checked by the pytest suite.

**FEMM, LTspice, and QSPICE are GUI/Windows-only tools and are NOT run here.**
The `ehdpsu.spice` and `ehdpsu.femm` modules instead **generate input artifact
files** (a SPICE netlist and a FEMM Lua geometry script plus notes) that you
open and run locally on those tools. Nothing in this repo purchases or orders
hardware.

## Layout

```
src/ehdpsu/         importable package (physics core + analysis modules)
  physics.py        pure-function physics core (SI units, cited)
  sanity.py         reproduces the original sanity-check script + validation notes
  sweeps.py         parameter studies -> outputs/*.csv + *.png, safety margins
  spice.py          generates artifacts/ehd_llc_cw.cir (+ .asc) for LTspice/QSPICE
  femm.py           generates artifacts/ehd_wire_collector.lua (+ notes) for FEMM
  telemetry.py      ingests ESP32 CSV logs -> derived metrics + plots
tests/              pytest suite pinning known reference operating points
tests/data/         example telemetry CSV (ESP32 schema)
outputs/            generated CSVs and plots (gitignored except .gitkeep)
artifacts/          generated SPICE netlists and FEMM inputs for local GUI tools
docs/               PHYSICS_NOTES.md (formula validation) + SPEC_SHEET.md (BOM)
```

## Setup

```bash
cd /projects/sandbox
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Dependencies: numpy, scipy, matplotlib, pandas. Dev extras: pytest, ruff,
black, mypy.

## Usage

Each analysis is a module entrypoint (`python -m ehdpsu.<module>`):

| Command | What it does | Produces |
| --- | --- | --- |
| `python -m ehdpsu.sanity` | Reproduces the original sanity-check numbers (Peek inception, single-cell operating point, CW multiplier health) and prints a `VALIDATION NOTES` section reviewing every formula. | stdout only |
| `python -m ehdpsu.sweeps` | Parameter studies over voltage, wire radius, gap, frequency, per-stage capacitance, and stage count. Includes corona-onset and air-breakdown safety margins. | 12 files in `outputs/` (6 CSV + 6 PNG) |
| `python -m ehdpsu.spice` | Generates the LLC half-bridge + PQ26/20 transformer + 5-stage CW + non-linear EHD load netlist for local simulation. | `artifacts/ehd_llc_cw.cir` and `.asc` |
| `python -m ehdpsu.femm` | Generates the wire-to-collector electrostatics geometry script and a plain-text geometry/expected-outputs note, with the analytical Peek cross-check embedded. | `artifacts/ehd_wire_collector.lua` and `..._geometry.txt` |
| `python -m ehdpsu.telemetry --input tests/data/example_telemetry.csv` | Ingests an ESP32 telemetry CSV (`t_s, F_mN, V_HV_kV, I_HV_mA, P_in_W`), computes derived thrust/power/efficiency and a burst-window summary. | `outputs/example_telemetry_derived.csv` + 2 PNG |

Development checks:

```bash
pytest -q                 # physics + module regression tests
ruff check . && black --check .
mypy src
```

## Reference operating point

`python -m ehdpsu.sanity` reproduces (at the base design: r_wire=25 um,
d=12 mm, L=15 cm, V_op=22 kV, f_sw=250 kHz, N=5, C_stage=1 nF):

- Peek breakdown surface field: **17.76 MV/m**
- Corona inception: **2.74 kV**
- Ion current: **1.17 mA**, electrical power **25.79 W**
- Raw thrust: **0.0938 N (9.56 gf)**, thrust efficiency **3.64 N/kW**
- CW loaded droop: **445.5 V (2.02%)**, pk-pk ripple **70.3 V**

These numbers are reproduced from the original script exactly. Two of them
carry **documented caveats**: the ion-current prefactor is a labeled
parallel-plate (order-of-magnitude) model parameter, and the thrust/efficiency
are idealized mobility-limited upper bounds. See
[docs/PHYSICS_NOTES.md](docs/PHYSICS_NOTES.md) for the formula-by-formula
review and [docs/SPEC_SHEET.md](docs/SPEC_SHEET.md) for the part selections.

## Physics honesty policy

Every physics function cites a reference and states its idealizing assumptions.
Where the original script's physics is geometrically inconsistent (notably the
parallel-plate current-law coefficient for a wire-to-plane emitter), the code
**labels** the assumption and documents the alternative rather than silently
changing or curve-fitting it. No coefficients were curve-fit or invented. See
the docstrings in `physics.py`, the `VALIDATION NOTES` printed by
`ehdpsu.sanity`, and [docs/PHYSICS_NOTES.md](docs/PHYSICS_NOTES.md).
