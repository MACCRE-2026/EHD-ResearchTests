# ehdpsu

Analytical and simulation toolkit to validate a **benchtop single-cell EHD
(electrohydrodynamic / Biefeld-Brown) thruster power supply** before any parts
are purchased.

This is a pre-purchase proof-of-concept validation project. The goal is to
simulate and validate the design premises (corona inception, ion current,
thrust, Cockcroft-Walton multiplier health) with **honest, cited physics** and
no curve-fitting, then use the results to nail down a part/spec sheet.

## Design targets (from the design conversation)

- Single thruster cell, ~80-120 W peak burst (3-5 s bursts)
- +15 kV to +25 kV DC output
- LLC/half-bridge GaN/MOSFET primary -> PQ26/20 HF transformer -> 5-stage
  Cockcroft-Walton multiplier
- 25-50 um tungsten emitter wire, ~12 mm gap, ~15 cm wire length
- Split-collector solid-state thrust vectoring
- Load-cell (HX711) + INA226 telemetry logged to CSV
- ESP32-S3 / STM32 controller

## Layout

- `src/ehdpsu/physics.py` - pure-function physics core (SI units, cited).
- `src/ehdpsu/sanity.py` - reproduces the original sanity-check script and
  prints validation notes. Run with `python -m ehdpsu.sanity`.
- `tests/` - pytest suite pinning known reference operating points.
- `outputs/` - generated CSVs and plots (gitignored except `.gitkeep`).
- `artifacts/` - generated SPICE netlists and FEMM inputs for local GUI tools.

## Setup

```bash
cd /projects/sandbox
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

## Usage

```bash
python -m ehdpsu.sanity   # reproduce original numbers + validation notes
pytest -q                 # run the physics regression tests
ruff check . && black --check .
```

## Physics honesty policy

Every physics function cites a reference and states its idealizing assumptions.
Where the original script's physics is geometrically inconsistent (notably the
parallel-plate current-law coefficient for a wire-to-plane emitter), the code
**labels** the assumption and documents the alternative rather than silently
changing or curve-fitting it. See the docstrings in `physics.py` and the
`VALIDATION NOTES` section printed by `ehdpsu.sanity`.
