# Reference outputs

Committed outputs from the **MK0 benchtop design point** (22 kV, 12 mm gap, 5-stage
Cockcroft-Walton, 25 µm emitter **radius**, 150 mm wire length). They exist so that a fresh
clone has something to compare its own run against, rather than having to trust that the
code works.

Regenerate and compare:

```powershell
.\.venv\Scripts\python.exe -m ehdpsu.sweeps
.\.venv\Scripts\python.exe -m ehdpsu.telemetry --input tests/data/example_telemetry.csv
# your output lands in artifacts/07_Outputs/ ; diff it against this directory
```

`tests/test_examples.py` does this automatically and fails if the numbers move.

---

## Why CSVs and not plots

The comparison is **numeric, with a tolerance** — not a byte-for-byte diff.

Matplotlib PNG output is not reliably byte-reproducible: it varies with matplotlib version,
available fonts and platform rasterisation. Tracking the plots would therefore create a
drift surface where a failure tells you nothing useful — a red test caused by a font
substitution looks exactly like a red test caused by a physics regression. So the plots are
generated into the untracked datacenter and are not committed.

The CSVs are the actual numbers, so they are the thing worth pinning.

---

## Known defect in these files, stated rather than shipped quietly

**`sweep_stages.csv` is deliberately absent from this directory.**

Its `V_out_noload_ref_kV` column is **wrong by a factor of 10.** The generator passes `V_op`
(22 kV, the multiplier *output*) where the *secondary peak* (2.2 kV) belongs, so the column
reads `44·N` kV instead of `4.4·N` — 220 kV at N=5 rather than 22 kV. The `sweeps.py`
docstring is honest that the value is only a scaling reference, but the CSV column carries a
`_kV` suffix and no caveat, so anyone reading the file alone is misled by an order of
magnitude.

An approximately-correct value in a published reference artifact is worse than an absent
one: a wrong non-empty number propagates and gets acted on, while an absent file is visibly
absent. The column is corrected as part of the MK1 work, and this file will be added here
once it is.

**Everything in this directory is still MK0.** Its design inputs came from a source known to
be optimistic, and two of its headline figures carry documented caveats — the ion-current
prefactor is an uncalibrated parallel-plate coefficient on a wire-to-plane emitter (roughly a
10× band), and the thrust and efficiency figures are idealised mobility-limited **upper
bounds**, not predictions. See [`../docs/PHYSICS_NOTES.md`](../docs/PHYSICS_NOTES.md).

---

## Reading the column headers

**Three columns carry an `_UPPER_BOUND` suffix**, and it is part of the data rather than decoration:

| Column | Why it is a ceiling |
| --- | --- |
| `thrust_N_UPPER_BOUND` | `T = I·d/µ` assumes every ion transfers all its momentum to neutrals, with no neutral drag and a uniform gap field. Real thrust is **lower** |
| `thrust_gf_UPPER_BOUND` | The same ceiling in grams-force |
| `efficiency_N_per_kW_UPPER_BOUND` | The ratio of that ceiling thrust to the same power, so it inherits the bound |

The suffix is in the header because that is what travels with the data. A ceiling in a column called
plainly `thrust_N` becomes a prediction the moment somebody opens the CSV without having read the
derivation, and that somebody is often the author six weeks later.

**The columns without the suffix are not therefore certain**, and the distinction is worth
understanding:

- `I_ion_mA`, `power_W`, `droop_V`, `droop_pct` and `ripple_Vpp` all inherit the `k_geo`
  **×0.1 to ×1.0 band** through the load current. That is a *two-sided* uncertainty — the real
  current may be higher or lower — so calling them upper bounds would be false. Their **trend**
  against voltage, frequency, capacitance and stage count is sound; their **absolute level** is
  uncertain by an order of magnitude. Two different things, and only the first is being shown.
- `E_peek_MVpm`, `V_onset_kV`, `corona_onset_margin` and `mean_gap_breakdown_margin` do not depend
  on `k_geo` at all.
- `k_geo_ApV2` is itself the uncalibrated coefficient. No FEMM run has been performed.

**`example_telemetry_derived.csv` deliberately has no suffixed columns.** Its `thrust_N` is a
load-cell reading, not a model output, so labelling it a ceiling would be wrong in the opposite
direction. `tests/test_sweeps.py` pins that asymmetry, because making the two files "consistent" is
the tidy-up that would corrupt it.

For a figure with its full qualification attached — band, basis and bound status in one string —
use the operating-point report rather than the CSV:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'tests'); from conftest import reference_profile; from ehdpsu.operating_point import operating_point; [print(l) for l in operating_point(reference_profile()).report_lines()]"
```

---

## Contents

| File | What it is |
| --- | --- |
| `sweep_voltage.csv` | Operating point vs applied voltage, with corona-onset and mean-gap breakdown margins |
| `sweep_gap.csv` | Operating point vs emitter-collector gap. First row (8 mm) is the arc-over watch item: breakdown margin ~1.09 |
| `sweep_wire_radius.csv` | Peek field and onset voltage vs emitter radius over 25–50 µm |
| `sweep_frequency.csv` | CW droop and ripple vs switching frequency (ripple falls as 1/f) |
| `sweep_capacitance.csv` | CW droop and ripple vs per-stage capacitance (both fall as 1/C) |
| `example_telemetry_derived.csv` | Reduced telemetry from `tests/data/example_telemetry.csv` — derived thrust, power and efficiency |
