# Task ledger — electrostatics-corona-oracle

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

### 2026-09-16 — the FEMM script was run for the first time and could not solve

The skill's own hazard note said "FEMM has never been run in this project." It has now, and the
script did not work. Recorded here because this is the domain's artifact and because the failure mode
generalises well beyond FEMM.

- **Status:** COMPLETED for the fix. The solve itself is still unperformed — the operator re-runs.
- **Files:** `src/ehdpsu/femm.py`, `solver_inputs/ehd_wire_collector.lua` (regenerated),
  `tests/test_femm.py` (one test strengthened, two added),
  `.kiro/governance/gate.ps1` (floor 842 → 844).
- **Evidence — what FEMM reported**, from the operator's screenshots:
  1. `Material properties have not been defined for all regions`
  2. `c:\femm42\examples\ehd_wire_collector.res was not found.`
  3. The geometry window showed the outer box with a horizontal line across it, a single `Air`
     label near the top, and the wire as a dot.
  The second message is a consequence of the first: `ei_analyze(0)` never produced a solution, so
  `ei_loadsolution()` had nothing to load. It also revealed FEMM's working directory —
  `C:\femm42\examples` — which is where `ei_saveas` had been putting the `.fee`.
- **Defect 1: one block label for three enclosed regions.** Every region a closed boundary encloses
  needs a material. This geometry closes three, and the script placed one:
  - the main air region, above the collector and outside the wire;
  - **the wire interior** — the two 180° arcs form a closed circle, so its inside is a region;
  - **the region below the collector** — `collector_hw` equals `outer_r`, so the plate spans the full
    width, its end nodes land on the side walls, and the box is partitioned. Visible in the screenshot
    as the line across the middle.
  - **Fix:** all three labelled `Air`. Both added regions are physically inert and the reasoning is
    recorded in the script rather than left implicit: inside a conductor held at a single potential
    the solution is constant, so `E = 0` and the region contributes nothing to stored energy or to the
    conductor-charge integral; below a grounded plate bounded by grounded walls every boundary is at
    0 V, so that region solves to `V = 0` throughout.
  - **Rejected: FEMM's `<No Mesh>` block property for the wire interior**, which would be tidier and
    would avoid meshing a 25 µm circle. Its availability in FEMM 4.2 is confirmed, but the exact
    spelling — `<No Mesh>` versus `<NoMesh>` — was **not** verified against this installation, and a
    wrong material name fails in exactly the same way the missing label did. `Air` is already defined
    and cannot be misspelt. Recorded as an improvement available once the string is confirmed.
  - **Rejected: shrinking `collector_hw` below `outer_r`** so the plate stops partitioning the box.
    That changes the modelled geometry from an effectively infinite grounded plane to a finite one,
    which changes the numbers. A geometry change is not the right way to fix a missing label.
- **Defect 2: the read-back named a function that does not exist.** The script's notes told the
  operator to call `eo_getconductorproperty`. The function is **`eo_getconductorproperties`**, plural,
  established from FEMM's own Octave wrapper at `C:\femm42\mfiles\eo_getconductorproperties.m`.
- **Defect 3, found while fixing the others: the dialect.** FEMM 4.2 embeds **Lua 4**, where the
  maths and string functions are globals — `sqrt`, `cos`, `sin`, `format` — and the `math` and
  `string` tables of Lua 5 do not exist. Established from FEMM's own readme, which refers to "the Lua
  `format` command". A first draft of the computed read-back used `math.sqrt`, `string.format` and
  `ipairs`; all three would have raised. The script now carries a shim binding the globals from the
  Lua 5 tables when absent, so it runs under either dialect, and a test asserts the table forms appear
  nowhere but inside that shim.
- **Decision — the read-back is now COMPUTED, not described.** The script prints the peak surface
  field and both capacitance routes instead of explaining where to click. Two reasons: hand-reading is
  where a transcription error enters, and a printed number is reproducible where a GUI reading is not.
  The API was taken from the `mfiles` wrappers rather than guessed: `eo_getpointvalues(x, y)` returns
  eight values, `V, Dx, Dy, Ex, Ey, ex, ey, energy_density`, deduced from `eo_getv` taking column 1,
  `eo_getd` 2:3, `eo_gete` 4:5, `eo_getperm` 6:7 and `eo_getenergydensity` 8.
- **Decision — the field is sampled at three radii, not one.** 1.005, 1.01 and 1.02 × `r_wire`,
  just outside the surface because a point exactly on the boundary may lie in no element. Near a thin
  wire the field falls roughly as `1/r`, so **the spread across those three is the reading's own
  uncertainty** and it is printed alongside rather than collapsed into a single figure. Reporting one
  number would state a precision the sampling does not have.
- **Decision — the two capacitance routes stay a cross-check.** Stored energy and emitter charge are
  computed independently and their ratio is printed. If they disagree that is a finding about the mesh
  or the geometry, to be reported with both figures — never averaged. This also serves as the check
  that the two inert regions really are inert, since they are included in the energy integral.
- **The failure mode, which is the part worth keeping.** `tests/test_femm.py` had **16 tests over this
  script and every one passed** while the script could not solve. They validate the generated Lua
  *text* — that parameters are substituted, that the header carries the analytical cross-check, that
  the read-back guidance is present. No test could feed the text to FEMM, so nothing checked the only
  property that matters. *Principle 6, a green test suite is not evidence of a working system*, and
  specifically the seam-nobody-visits case: the tests and the tool sit on opposite sides of a boundary
  no automated check crosses.
  - The strengthened test is now the closest a text check can get: it asserts the routes are
    **performed** (`eo_blockintegral(0)`, `eo_getconductorproperties`) rather than described, that the
    non-existent singular name is absent, that the label count matches the region count, and that the
    dialect is right. None of that proves FEMM accepts the file. **Only a run does.**
- **Inherited:**
  - **The solve has still not happened.** No field, no capacitance, no run record. `k_geo` remains a
    parallel-plate placeholder with its ~10× band, and everything downstream still inherits it.
  - The label-count test hardcodes **three**. That is correct for this geometry and will need changing
    deliberately if the geometry gains a region — which is the intent, but it is a coupling worth
    knowing about.
  - `ei_saveas` uses a **relative** path, so `ehd_wire_collector.fee` lands in FEMM's working
    directory (`C:\femm42\examples` here) rather than in the datacenter. Harmless, but it means solver
    scratch files sit in the install tree. Not changed, because hardcoding an absolute path into a
    generated artifact would bake one machine's layout into a tracked file.
  - **The 1° arc discretisation is untested at scale.** `ei_addarc(..., 180, 1)` gives 360 segments
    around a 25 µm circle inside a 240 mm domain — an aspect ratio of about 5×10⁵. Whether the mesher
    copes, and how long it takes, is unknown until the run completes.

### 2026-09-16 — Task 13.1: FEMM solved. The project's first `solved` values

The skill's standing hazard — *"FEMM has never been run in this project"* — is now retired. One run
exists, it is recorded, and its basis is `solved`.

- **Status:** COMPLETED for 13.1. **13.3 (`k_geo`) is NOT done and is not implied by this.**
- **Files:** `artifacts/05_Solver_Runs/femm_wire_collector_2026-09-16.txt` (the transcribed result),
  `RECORD_femm_wire_collector_2026-09-16.json` (the run record),
  `NOTE_femm_2026-09-16_input_hash.md`; `src/ehdpsu/femm.py` and
  `solver_inputs/ehd_wire_collector.lua` (cross-check text corrected), `tests/test_femm.py` (+1),
  `.kiro/governance/gate.ps1` (floor 844 → 845). All the solver-run artifacts are untracked.
- **Evidence — the run, as FEMM reported it.** Mesh 7457 nodes / 14631 elements, 2-D planar,
  depth 150 mm.

  | Quantity | Value |
  |---|---|
  | `E_peak` at 1.005 × r_wire | `1.322473e8` V/m (peak at 226°) |
  | `E_peak` at 1.010 × r_wire | `1.321825e8` V/m (226°) |
  | `E_peak` at 1.020 × r_wire | `1.315339e8` V/m (222°) |
  | `W_stored` | `3.053114e-4` J |
  | `C_from_energy` | `1.261617e-12` F |
  | `Q_emitter` | `2.775559e-8` C |
  | `C_from_charge` | `1.261618e-12` F |
  | route ratio | `1.0000` |

- **The strongest internal evidence: the two capacitance routes agree to six significant figures.**
  Stored-energy integration and emitter-charge integration are independent computations over the
  solved field, and they concur. That also confirms the two added block labels really are inert, since
  the energy integral includes them.
- **Evidence — the run record.** `basis = solved`, hash verified against the input at construction
  time, `profile_id = mk0_benchtop_22kv`. This is the first `solved` value in the project.
- **The defect this run exposed, and it is a documentation defect of the worst kind.** The script had
  said, for its entire life, that its peak wire-surface field should be close to the analytical Peek
  figure. **That is a category error.** The script applies `V_op = 22 kV`; Peek's figure is the surface
  field **at onset**. The ratio is `E_femm / E_peek = 7.4477`, so an operator following the old wording
  would have reported a catastrophic disagreement **where there is none.**
  - Worse than a wrong number, because a wrong number gets questioned and a wrong *comparison* gets
    believed. And I repeated it in the operator-facing skeleton, so the false alarm was two steps from
    being filed as a finding.
  - **The valid comparison**, now in the script, exploits Laplace being linear in the applied voltage:
    one solve gives `E_per_V`, onset is where `E_surface = E_peek`, so
    `V_onset_implied = E_peek / E_per_V`, and that is compared against the closed-form `V_onset`.
  - Closed by `test_the_script_does_not_invite_the_invalid_peek_comparison`.
- **Evidence — the cross-checks, computed rather than hand-worked.** All figures below are generated
  from the parsed result and `ehdpsu.physics`:

  | Comparison | Solved | Analytical | Ratio |
  |---|---|---|---|
  | Capacitance vs wire-above-plane `2πε₀/acosh(h/r)` | `1.261617e-12` F | `1.214832e-12` F | **1.0385** |
  | Capacitance vs coaxial `2πε₀/ln(d/r)` | `1.261617e-12` F | `1.351634e-12` F | 0.9334 |
  | Surface field per volt vs wire-above-plane | `6.011241e3` /m | `5.823253e3` /m | **1.0323** |
  | Surface field per volt vs coaxial | `6.011241e3` /m | `6.479006e3` /m | 0.9278 |
  | **Implied onset voltage vs closed form** | **2953.93 V** | **2740.67 V** | **1.0778** |

- **What the numbers say, and it is coherent.** Two *independent* quantities — capacitance and
  field-per-volt — both sit **3.2–3.9% above** the infinite-wire-above-plane analytic, in the direction
  a finite outer boundary predicts: the walls at ±120 mm are held at 0 V and act as extra grounded
  electrodes, adding capacitance and raising the field per volt. Agreement in **magnitude and
  direction, on two quantities, from one solve** is much better evidence than either alone.
  - Against the **coaxial** `ln(d/r)` approximation both are ~7% low, which is the same finding read
    the other way: the coaxial form overestimates the surface field, therefore **underestimates the
    onset voltage.** The solved geometry puts onset at **2954 V, 7.8% above the 2741 V closed form.**
  - This is the first quantitative evidence in the project that the coaxial approximation
    `V_onset = E_peek·r·ln(d/r)` is biased for a wire-to-plane geometry, and by how much. The
    image-charge form `acosh(h/r)` is the better idealisation, as expected — and FEMM lands between
    the two, nearer the image form.
- **Basis arithmetic, stated because it is easy to get flattering.** The FEMM values are `solved`.
  `E_peek` is `analytical-cited`. So the **implied onset voltage is `analytical-cited`**, not `solved`
  — low-water-mark over its inputs. A solved field does not promote a figure that still depends on
  Peek's empirical coefficients. *Principle 1, trust is a ceiling inherited from provenance.*
- **The peak angle is meaningless and is recorded as such.** At `h/r = 481` the first-order variation
  of surface field around the circumference is `2r/h = 0.416%`, so which element holds the maximum is
  mesh noise — which is exactly why it moved from 226° to 222° between sampling radii. Nobody should
  read a physical asymmetry into it.
- **The reading's uncertainty is 0.54%**, the spread across the three sampling radii, and it travels
  with the number rather than being dropped.
- **Third instance of one trap, now recorded from a third angle.** The new test scans the script for
  the retracted sentence, and my first draft of the correction **quoted that sentence verbatim** — so
  the test failed on the file's own retraction. Earlier instances: a leak report pasting the term it
  matched, and a ledger entry naming a dead path in the record of having removed it. The rule that
  generalises all three: **a record of a defect must describe the defect, never instantiate it.** The
  script now paraphrases and says why.
- **Inherited:**
  - **`k_geo` IS NOT SOLVED, and this run does not solve it.** FEMM gives the *electrostatic* geometry
    — capacitance and field-per-volt, hence onset. `k_geo` is the prefactor in
    `I = k·V·(V − V_onset)`, a **space-charge-limited current** coefficient. A Laplace solve carries no
    space charge by construction, so converting this run into `k_geo` needs a cited relation connecting
    the solved geometry to the corona current — the `C_wp·µ·ε₀` wire-to-plane form this skill names.
    That is Task 13.3's actual content, it is where the no-curve-fitting rule bites hardest, and it has
    not started. **Current, power, thrust and efficiency still carry the ~10× band.**
  - **The run record's input hash no longer matches the working tree**, because the comment fix changed
    the file. `NOTE_femm_2026-09-16_input_hash.md` covers it: 104 non-comment lines are byte-identical
    on both sides, proven rather than asserted. A hash cannot distinguish a comment change from a
    geometry change, and that limitation needed a separate check.
  - **The prose should move out of the input file.** Generating the Lua with its explanation in the
    companion `_geometry.txt` would decouple documentation changes from the input hash entirely. Right
    change to make **before** the next solver run, not after this one.
  - **Mesh convergence has not been demonstrated.** One mesh, 14631 elements. The 3.2–3.9% excess over
    the infinite-plane analytic is *attributed* to the finite boundary, and that attribution is
    untested — the way to test it is to enlarge `outer_r` and watch both quantities fall toward the
    analytic. Until then the attribution is reasoning, not evidence.
  - **The 1° arc discretisation coped**, which was an open question: 360 segments around a 25 µm circle
    inside a 240 mm domain meshed to 14631 elements without complaint.

---

## 2026-09-20 — FEMM's headless routes, and two wrong claims I made about them

Three routes were examined for CRSDL Task 7, because a scripted Plausibility Contract loop cannot
contain a GUI step and FEMM is the electrostatics route.

### The solvers, read from the binaries rather than inferred

```
belasolv.exe -> .fee     electrostatics   <- what ehd_wire_collector.lua writes via ei_saveas
csolv.exe    -> .fec     current flow
hsolv.exe    -> .feh     heat flow
fkn.exe      -> .fem     magnetics
```

Obtained by extracting ASCII strings from each binary and matching the problem-file extension each
names. **This corrects a planner error.** The 2026-09-19 reconnaissance recorded `csolv.exe` as the
electrostatics solver, inferring it from the name. It is the current-flow solver. Worse, the test
guarding the route register then *asserted* `"csolv" in verdict`, so the register was **required** to
name the wrong tool and the implementing seat complied correctly with a false requirement.

### Verdicts as they now stand

| Route | Verdict | Basis |
|---|---|---|
| `femm-lua-bat` | **absent** | no `.bat`, `.cmd` or `.py` exists anywhere under `C:\femm42` |
| `com-typelib` | **not-attempted** | `bin\femm.tlb` present, but `win32com`, `pyfemm`, `femm`, `pythoncom` and `win32api` are all absent — no binding to drive it |
| `solver-exe-direct` | **fails** | `belasolv.exe` run against a real `.fee`, timed out at 120 s, wrote nothing |

### The second wrong claim, and how it was caught

The first corrected verdict said *"no `.fee` file exists anywhere on this machine"*, so the route was
recorded `not-attempted`. **That was false, and the cause was my own tooling error:**
`Get-ChildItem -Path 'C:\femm42' -Include '*.fee' -Recurse` silently returns nothing because `-Include`
needs a wildcard on `-Path`. The correct form finds three:

```
bdemo1.fee   bdemo2.fee   ehd_wire_collector.fee
```

The third is **ours** — written into FEMM's working directory by the 2026-09-16 session, exactly as
`PENDING_femm_wire_collector.txt` had said it would be. I had read that note earlier the same session.
A silent-empty search result was taken for an absence, which is the same shape as
*principle 2, an approximately-correct identifier is worse than an absent one*: the search returned
nothing and nothing was read as "there is nothing."

So the route was then actually attempted: `ehd_wire_collector.fee` copied to a scratch directory,
`belasolv.exe` passed it as its sole argument with `cwd` set there, stdin closed, 120 s timeout. It ran
the full 120 s, wrote **no output files**, and printed nothing on either stream. Bare and `-h`
invocations had already timed out at 12 s without printing usage.

**Verdict `fails`, not `not-attempted`** — the input existed, was ours, and was valid. A different
argument convention may well work; that is now the specific open question instead of the whole route
being unexamined.

### Consequences recorded

- `femm` keeps `manual_only=True` and stays in `TOOLS_WITHOUT_A_VERSION_PROBE`, but its reason now
  states **one verified absence, one observed failure, one unexamined route** rather than the earlier
  `verified negative:` over three — which was *principle 3 in the negative direction*, a stronger
  status than the work supported.
- **CRSDL Task 8's headless loop has no electrostatics route today.** The nearest available one is the
  COM binding, which needs `pyfemm` or `pywin32` installed — a one-line dependency decision, not a
  research problem.
- `FEMM_AUTOMATION_ROUTES` is now `dict[str, RouteVerdict]` with `tried`, `observed` and `checked_on`
  as separate fields, because the test that let the `.pro` fabrication through asserted only
  `len(verdict) > 60` and so rewarded length rather than truth. There is no `.pro` format in FEMM.

**Nothing here changes any physics.** No FEMM solve was performed, no field was read back, and
`RECORD_femm_wire_collector_2026-09-16.json` remains the project's only `solved` entry — still the
corona-onset geometry factor from a Laplace solve with no space charge, not the loaded operating field.
