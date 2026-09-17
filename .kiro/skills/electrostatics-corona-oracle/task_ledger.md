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
