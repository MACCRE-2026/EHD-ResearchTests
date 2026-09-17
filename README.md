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
  sweeps.py         parameter studies -> CSV + PNG, safety margins
  spice.py          generates solver_inputs/ehd_llc_cw.cir (+ .asc) for LTspice/QSPICE
  femm.py           generates solver_inputs/ehd_wire_collector.lua (+ notes) for FEMM
  telemetry.py      ingests ESP32 CSV logs -> derived metrics + plots
tests/              pytest suite pinning known reference operating points
tests/data/         example telemetry CSV (ESP32 schema)
solver_inputs/      tracked, generated inputs for the local GUI solvers
examples/           tracked reference outputs, so a clone has something to compare against
docs/               PHYSICS_NOTES.md (formula validation) + SPEC_SHEET.md (BOM)
artifacts/          the project datacenter -- UNTRACKED, see below
```

### Tracked inputs, untracked outputs

Generated **inputs** (`solver_inputs/`) are tracked: they are small, deterministic text
files that a cloner needs in order to run FEMM or LTspice locally, and a test regenerates
and diffs them so they cannot drift silently.

Generated **data** is not tracked. It goes to `artifacts/`, a numbered project datacenter
that is ignored at the folder level:

```
artifacts/00_Governance  01_Collaborator_Conversations  02_Kiro_Conversations
          03_Task_Packets  04_BreadCrumbs  05_Solver_Runs
          06_Inputs  07_Outputs  08_Reference  09_Backups
```

Nothing under `artifacts/` exists in a clone. It is therefore never citable as evidence by
a commit, and a commit that touches it is not self-contained. Reference figures a reader
does need live in `examples/`.

## Setup

This project is developed Windows-first with PowerShell (`pwsh`).

**One command, from a clean clone:**

```powershell
.\bootstrap.ps1
```

That creates `.venv`, installs the exact pins from
[`requirements.lock`](requirements.lock), installs `ehdpsu` editable, verifies the installed
set against the lock, and then reproduces the MK0 reference figures. It reports a distinct
status for each way it can fail, so a partially installed environment is never reported as
success. Add `-Recreate` to rebuild `.venv` from scratch.

It deliberately does **not** run the whole-codebase sweep, which takes minutes:

```powershell
pwsh -File .kiro\governance\gate.ps1
```

The manual equivalent, if you would rather do it by hand:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

`--no-deps` matters: without it pip re-resolves numpy, scipy and pandas and may install
versions the lock does not name, which defeats the lock while appearing to work.

**Python 3.12 or later is required**, not merely recommended. Below 3.12, mypy cannot parse
the pinned numpy's type stubs and aborts having checked **zero** files — it exits non-zero
over no work at all, which is worse than failing. Reversible by pinning numpy below 2.3.

**The venv is not vendored.** It is ~408 MB, and `pyvenv.cfg` and `Scripts\*.exe` embed
absolute paths, so a committed venv would only work on the machine that built it.
Reproducibility comes from the lock plus the bootstrap instead.

**What the lock guarantees.** Exact versions of all 32 packages, including the linters and
type checkers, because the Gate's verdict is a function of its tools. It does **not** pin
artifact hashes, so it does not defend against a re-uploaded PyPI artifact at an
already-released version; that needs `pip install --require-hashes`. Build isolation also
fetches `setuptools>=61` at install time, and that fetch is not covered by the lock.

Dependencies: numpy, scipy, matplotlib, pandas. Dev extras: pytest, ruff, black, mypy,
pyright.

The generated solver inputs under `solver_inputs/` are asserted byte-stable by a test, so a
dependency bump that silently changes their formatting fails loudly. An earlier version of
this README also claimed byte-identity across Linux/Python 3.11/numpy 1.x and
Windows/Python 3.12/numpy 2.x; that comparison predates the 3.12 floor and is no longer
reproducible here, so it is withdrawn rather than restated.

## The `ehdsuite` command

Design values live in a **spec-scope-profile**, and this is the surface for authoring and inspecting
them. `python -m ehdpsu` always works; `ehdsuite` is the same thing via a console script, available
once an editable install has regenerated it.

```powershell
python -m ehdpsu schema --json          # the field schema, for an editor or a writer to render from
python -m ehdpsu list                   # profiles present, with the trust ceiling each imposes
python -m ehdpsu validate               # validate everything in profiles/
python -m ehdpsu diff <a> <b>           # field-by-field differences, with ratios
python -m ehdpsu new <id> --from <src>  # copy an existing profile
python -m ehdpsu report <id>            # derived figures, each with band, basis and bound status
python -m ehdpsu crosscheck [<id>]      # independent-route agreement, and claim adjudication
```

`crosscheck` does two things. It compares independent routes to the same quantity and **reports the
disagreement without resolving it** — choosing between them is a physics decision, not a diff. And it
adjudicates recorded claims against figures derived from **the source's own numbers**, which is a test
of internal consistency rather than of one model against another.

It exits `7` when a claim contradicts its own source. The MK1 palm-scale thrust claim currently does,
by a factor of **at least 5.5** against an upper bound computed from the claimant's own gap, voltage
and power — and since that derived figure is a ceiling, the real gap is wider.

`profiles/` **ships empty** — see [`profiles/README.md`](profiles/README.md). There is no set design
point, so `new` requires an explicit `--from` rather than inventing one. To start from the frozen
regression fixture:

```powershell
python -m ehdpsu new my_design --from tests/data/mk0_benchtop_22kv.json
```

Exit codes, because a script branches on them: `0` ok, `2` usage error (argparse), `3` invalid
profile, `4` nothing validated, `5` not found, `6` refused to overwrite. **Validating zero profiles
returns 4, not 0** — a green result over no work is not success.

The CLI is deliberately built before any GUI. Per the charter, new architecture belongs at the CLI
level and below: a capability that exists only behind a button has no test and no scriptable form.

## Usage

Each analysis is a module entrypoint (`python -m ehdpsu.<module>`):

| Command | What it does | Produces |
| --- | --- | --- |
| `python -m ehdpsu.sanity` | Reproduces the original sanity-check numbers (Peek inception, single-cell operating point, CW multiplier health) and prints a `VALIDATION NOTES` section reviewing every formula. | stdout only |
| `python -m ehdpsu.sweeps` | Parameter studies over voltage, wire radius, gap, frequency, per-stage capacitance, and stage count. Includes corona-onset and mean-gap breakdown safety margins. | 12 files in `artifacts/07_Outputs/` (6 CSV + 6 PNG) |
| `python -m ehdpsu.spice` | Generates the LLC half-bridge + PQ26/20 transformer + 5-stage CW + non-linear EHD load netlist for local simulation. | `solver_inputs/ehd_llc_cw.cir` and `.asc` |
| `python -m ehdpsu.femm` | Generates the wire-to-collector electrostatics geometry script and a plain-text geometry/expected-outputs note, with the analytical Peek cross-check embedded. | `solver_inputs/ehd_wire_collector.lua` and `..._geometry.txt` |
| `python -m ehdpsu.telemetry --input tests/data/example_telemetry.csv` | Ingests an ESP32 telemetry CSV (`t_s, F_mN, V_HV_kV, I_HV_mA, P_in_W`), computes derived thrust/power/efficiency and a burst-window summary. | `artifacts/07_Outputs/example_telemetry_derived.csv` + 2 PNG |

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
