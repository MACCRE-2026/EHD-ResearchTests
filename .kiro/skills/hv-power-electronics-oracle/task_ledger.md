# Task ledger — hv-power-electronics-oracle

**Append only.** Entries are never edited, deleted or reordered. A correction is a new entry that
names the one it corrects. Newest at the bottom, so the file reads chronologically.

An entry is written after **any** code mutation or planning decision in this domain. Its purpose
is to answer one question for the next session: *why does this look the way it does?* A change
without a ledger entry leaves that question unanswerable, which is the audit failure that
*principle 1, trust is a ceiling inherited from provenance*, warns about — an overwritten or
absent history cannot say why anything is trusted.

## Entry format

### <YYYY-MM-DD> — <short title>

- **Status:** `COMPLETED` | `WITHDRAWN` | `SUPERSEDED` (names its replacement)
- **Files:** what changed
- **Signatures:** functions or schemas added or changed
- **Decision:** what was chosen, what was rejected, and why
- **Evidence:** the observed result — test counts, gate output, reproduced values
- **Inherited:** any hazard this leaves open for the next session

`COMPLETED` requires observed evidence and a timestamp. A completion claim without evidence is
*principle 3, never report success over unperformed work*, in document form.

---

## Entries

*(none yet — this domain has had no code mutation. The skill definition itself is recorded in
`artifacts/00_Governance/2026-09-15_PLAN_ehd_modeling_suite.md` Task 3, not here, because
authoring a skill is not work in its domain.)*

---

## 2026-09-18 — The netlist had never been run, and the first run broke in two places

**How this came up.** Plan step 13.2. The operator installed LTspice, opened
`solver_inputs/ehd_llc_cw.cir`, and pressed Run. It refused to parse. Nobody had ever loaded this
file into a simulator, in either direction, at any point in the project's life.

### Defect 1 — MOSFET device letter on a voltage-controlled switch

```
ehd_llc_cw.cir(19): Node or model name expected.
M1 vbus ghi sw SW
```

The half-bridge switches were emitted as `M1`/`M2` — SPICE's **MOSFET** letter, requiring
`Mxxx Nd Ng Ns Nb <model>` — while the model card was `.model SW SW(Ron Roff Vt Vh)`, a
**voltage-controlled switch** model. LTspice read four nodes, found no model name, and stopped.

The comment above those lines had said "voltage-controlled switches" from the beginning. So the
**intent was documented and the code did something else**, which is why this is a clean case rather
than an ambiguous one: the fix is making the emitted netlist do what its own comment says.

Corrected to `Sxxx n+ n- nc+ nc- <model>`:

```
S1 vbus sw ghi 0 SW
S2 sw 0 glo 0 SW
```

The `M` form had no room for the **control pair**, which is the substantive part — a VCSW needs a
separate sensing pair and a MOSFET does not. Control is ground-referenced, which is a deliberate
idealisation now stated in the netlist: a real half-bridge references the high-side gate to the
switching node and needs a bootstrap or an isolated supply, while an ideal switch does not care about
its own source potential. The **topology's** behaviour is modelled; gate-drive feasibility, level
shifting and gate-charge loss are not.

**What missed it:** 1072 passing tests, the `solver_inputs/` regeneration diff, and planner review.
None of them is a SPICE parser. No test pinned those two lines, so there was nothing to break.

### Defect 2 — the tracked artifact was unrunnable as generated

The `.tran` directive was emitted **commented out**, under "Suggested analysis (uncomment locally)".
So even with the switches fixed, LTspice would parse the file and do nothing.

This is a provenance defect rather than a convenience one. An artifact that must be hand-edited before
it runs means **the file that was simulated is not the file whose SHA-256 the run record carries.** A
provenance chain with an unrecorded hand-edit in the middle is not a provenance chain.

Now emitted active as `.tran 0 2m 0 20n uic`, with `uic` because a Cockcroft-Walton ladder starting
from fully discharged capacitors has no meaningful DC operating point. The 2 ms came from an
order-of-magnitude charge estimate — roughly 4.4 µC to bring 5 × 1 nF in series to 22 kV, which at a
few mA lands near 1–2 ms. **That estimate was wrong**, see below, and the netlist comment says in
capitals that convergence must be checked by inspection rather than assumed from the duration.

### LTspice is not manual-only, and that is a capability finding

```
LTspice.exe -b -Run ehd_llc_cw.cir   ->  20.204 s, no warnings, 52,962,240 bytes of results
```

`.raw` is machine-readable: UTF-16LE header, then float64 time plus float32 per variable, 59
variables over 220,676 points. Read back in-process with a throwaway parser, retained at
`artifacts/07_Outputs/ltspice_batch_2026-09-18/read_raw_throwaway.py`.

So `ltspice`'s `manual_only=True` / `MANUAL_REQUIRED` classification is **wrong**, and the same
question now stands over QSPICE. Not changed here: it moves an adapter's declared run mode and touches
the `GUI_EXECUTABLES` register, so it wants its own tests-first pass. Logged, not done.

A parsing note worth keeping, because it is the failure this project cares about: the first parser
attempt guessed the wrong stride (it searched for an ASCII `Binary:` marker in a UTF-16 header),
computed 52,962,240 expected against 52,965,725 actual, and **refused to report any numbers**. Had it
fallen through to a default it would have produced plausible garbage. *An unrecognised output shape is
an error, never an empty result.*

### The finding — the open-loop chain delivers about twice its design point

Full write-up: `artifacts/05_Solver_Runs/RUN_ltspice_llc_cw_2026-09-18_INCOMPLETE.md`

| Quantity | At t = 2 ms | Design intent | Ratio |
|---|---|---|---|
| `V(cw_out)` | 44,639 V | 22,000 V | **2.03x** |
| ripple pk-pk | 786 V | — | — |
| load current | 5.175 mA | 1.17 mA closed-form | **4.42x** |

**Not steady state.** Decile means climbed monotonically to the final sample — 21.5, 35.4, 40.1, 42.7,
44.3, 44.6 kV — so 44,639 V is a **lower bound**. Filed as `RUN_*_INCOMPLETE.md` rather than
`RECORD_*.json` because the record schema exists to hold `solved` values and an unconverged run has
none. *Principle 3, never report success over unperformed work.*

**The load model is exonerated.** Hand-evaluating the Townsend law at the simulated voltage:
`2.7668749999999996e-12 × 44639 × (44639 − 2740.6671272441477) = 5.175e-3 A`, matching the simulation
exactly. The 4.42x current excess is **entirely** the 2.03x voltage excess squared through a quadratic
load. Nothing anomalous in the B-source.

**Where the voltage comes from**, as reasoning and not as a solved number: 400 V bus in a half-bridge
gives ±200 V primary; at 12:1 that is ~2.4 kV secondary peak; an ideal 5-stage half-wave CW multiplies
peak by `2N = 10`, so ~24 kV. Reaching 44.6 kV and still climbing implies **LLC resonant gain near
1.9** at 250 kHz — plausible close to resonance, and represented nowhere in the closed-form design.

**Nothing was adjusted to close this.** Two independent routes disagreeing is a finding for
cross-validation to report, never something the arithmetic reconciles.

Three things it does *not* establish, all worth stating because the number will get quoted:

- **Not "a built supply sits at 44 kV".** The netlist is open loop at fixed 250 kHz with no regulation,
  and a real LLC is frequency-controlled precisely to regulate output. It says the **available gain at
  the design frequency is about double** what the closed form assumed — a turns-ratio or
  control-frequency question.
- **Still a safety question.** Ratings and clearances were chosen against 22 kV. A chain capable of
  44 kV in a 22 kV design is an insulation and arc-over concern, and on a control fault it is the case
  to design against. 4.8–22 kV at milliampere currents is lethal.
- **Component models remain placeholders**, as the netlist states: ideal switches with no gate-charge
  loss, a first-order HV diode with `TT` as a proxy rather than a datasheet `trr`/`Qrr`, no core loss,
  no interwinding capacitance. Any loss or efficiency figure from this netlist is uncalibrated however
  carefully it ran.

**Possible connection, explicitly not established:** `V_out_noload_ref_kV` in the MK0 reference is
recorded as roughly 10x wrong and step 11.4 exists to correct or withhold it. Whether that and this 2x
are the same error seen from two directions has **not** been tested and must not be assumed.

### Defect 3 — running a solver in the tracked input directory

Opening the `.cir` in place made LTspice write `solver_inputs/ehd_llc_cw.log` into the **tracked**
directory, and the next Gate went red on
`test_every_tracked_solver_input_is_covered_by_this_module` — a check written to catch generated-input
drift, catching working-directory pollution instead.

**A solver writes its byproducts beside the input it was given**, and that directory holds the artifact
whose hash a run record cites. The discipline is to copy the input to a scratch directory and run it
there. `.gitignore` now carries the usual exhaust extensions under `solver_inputs/`, but only to stop
them being staged — it deliberately does not stop the test failing, because exhaust there means the
discipline slipped and that is worth being told about. The operator's failing log is preserved in
`artifacts/05_Solver_Runs/` as the first observation of defect 1.

### Evidence

Gate after all of it: **status OK, exit 0.** `ruff and black swept 48/48 files; mypy and pyright (node
1.1.414, forced from the lock) both examined 48 (agreeing, expected >= 48); no undeclared exclusions;
pytest 1072 collected / 1072 passed at floor 1072; 2 governance verifier(s) passed.` Three red Gates
preceded it — `PYTEST-FAILED` on the stray log, `RUFF-FAILED` on an extraneous f-prefix I introduced in
the improved failure message, and `PYTEST-FAILED` again on the path-existence check catching my own
docstring naming a file that correctly no longer existed. Each was the intended behaviour of a working
Gate.

New netlist SHA-256: `9449F3EA2930537203E6AF1E2D901865121D2D9E111573A3A553FC82665993C3`
(was `718BA4A3…`).
