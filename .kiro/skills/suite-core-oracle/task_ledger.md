# Task ledger — suite-core-oracle

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

### 2026-09-15 — seed ATTRIBUTIONS.md

- **Status:** COMPLETED
- **Files:** `ATTRIBUTIONS.md`, `tests/test_attributions.py`
- **Signatures:** four new tests in `test_attributions.py`:
  - `test_attributions_file_exists_and_is_tracked`
  - `test_every_physics_reference_is_attributed`
  - `test_planned_tools_are_marked_planned`
  - `test_prov_and_biba_are_named`
- **Decision:** created `ATTRIBUTIONS.md` with four sections: physics references, prior art, open-source tools (in use vs planned), and standards/models. Every entry states what it is used for in this project. The planned tools are explicitly marked as not yet installed or run.
- **Evidence:** pytest: 118 collected / 118 passed; ruff: clean; black: clean; mypy --python-version 3.12: success.
- **Inherited:** none — this completes the seed attribution list as planned in Task 1 and makes attribution mechanically checked as in Task 12.

### 2026-09-15 — Task 5: basis ladder and the BreadCrumb PROV corpus

- **Status:** COMPLETED
- **Files:** `src/ehdpsu/basis.py` (new), `src/ehdpsu/breadcrumb.py` (new),
  `tests/test_basis.py` (new, 40 checks), `tests/test_breadcrumb.py` (new, 50 checks),
  `.kiro/governance/gate.ps1` (floor 147 → 237, sweep breadth 15 → 19),
  `artifacts/04_BreadCrumbs/2026-09-15_mk0_retrospective.jsonld` (new),
  `artifacts/04_BreadCrumbs/2026-09-15_laundering_path_thrust_claim.jsonld` (new).
- **Signatures:**
  - `basis.Basis(IntEnum)` — five tiers, `CLAIMED=0` … `MEASURED=4`, with `.label` and
    `from_label()`.
  - `basis.low_water_mark(Iterable[Basis]) -> Basis` — raises `ValueError` on empty.
  - `basis.may_be_called_validated(Basis) -> bool` — `True` only at `>= SOLVED`.
  - `basis.describe_ceiling(Iterable[Basis]) -> str` — caption text.
  - `breadcrumb.{Agent,Activity,Entity}` frozen dataclasses; `breadcrumb.Graph` with
    `add()`, `effective_basis()`, `laundering_gap()`, `to_jsonld()`, `summary_lines()`;
    `breadcrumb.write_graph()`; `build_mk0_graph()`; `build_laundering_graph()`;
    `BreadcrumbError`.
- **Decision:**
  - The ladder lives in **its own module** rather than inside `breadcrumb.py`, because Task 8's
    `quantity.py` needs the same five tiers. Two enumerations of one ladder is
    *principle 4, two representations of one thing will drift*, with the specific consequence
    that a quantity and its breadcrumb could disagree about the same number.
  - **"Validated" is not a tier.** Modelled as `may_be_called_validated()` so that "promote to
    validated" is not an expressible operation. Rejected: a sixth `VALIDATED` member.
  - `ANALYTICAL_CITED` returns `False` from that gate. Rejected treating a cited closed form as
    validated: Peek's law is correctly cited here and still silent on whether it describes a
    25 µm wire at this gap.
  - `low_water_mark([])` **raises** rather than defaulting. `MEASURED` would invent trust from
    nothing and `CLAIMED` would condemn a legitimate root fact. *Principle 2, an
    approximately-correct identifier is worse than an absent one.*
  - **W3C PROV-O / JSON-LD**, with a single `ehd:` extension for `basis`, `band`,
    `isUpperBound`, `effectiveBasis` — the properties PROV deliberately omits. Rejected a private
    schema: the corpus is meant as input to somebody else's trust standard, and a private
    encoding of a 2013 Recommendation costs interoperability for nothing.
  - `Graph.add()` and `write_graph()` both **refuse replacement**. A correction is a new node or
    a new artifact naming what it supersedes.
  - A derivation cycle raises rather than resolving: trust defined in terms of itself justifies
    any value.
  - The counterfactual node declares itself `SOLVED` on a `claimed` parent **deliberately** — it
    models the fabrication instead of assuming nobody would attempt it. A test pins that
    declaration so a later session does not "fix" away the only laundering example in the corpus.
- **Evidence** (observed, this session, `.venv` Python 3.12.8):
  - pytest: **237 collected / 237 passed** in 13.78 s. The 147 floor test failed first and named
    the new count, then passed after the floor was raised — the check worked before it was
    updated.
  - ruff `check .`: `All checks passed!` after fixing six findings it raised on the new code
    (`UP035`, `F401`, `C408`, `UP017`, `RUF007`, `B017`).
  - black `--check src tests`: 19 files unchanged. mypy: no issues in 19 source files.
    pyright: 0 errors, 0 warnings.
  - Propagation reproduced on the real graph: `i-ion`, `thrust-raw`, `efficiency` and
    `mk0-spec-sheet` each **declare** `analytical-cited` and each resolve to
    `analytical-placeholder`, the ceiling set by `k_geo`. `e-peek` and `v-onset` stay at
    `analytical-cited`, confirming the low-water-mark is not simply pessimising everything.
  - Laundering flagged: `ehd:counterfactual/mk1-spec-sheet` → declared `solved`, effective
    `claimed`, `laundered=True`. Exactly one node in that graph is flagged and none in MK0.
  - Both on-disk `.jsonld` artifacts re-parse and are **identical to freshly built output modulo
    `ehd:generatedAt`** — checked explicitly, because the modules were reformatted after the
    artifacts were written.
- **Inherited:**
  - `to_jsonld()` stamps `ehd:generatedAt` from the wall clock, so the artifacts are **not**
    byte-reproducible. This is not a defect to fix by removing the timestamp — a provenance
    record without a time is worse — but it does mean the artifacts cannot be diffed byte-wise,
    which is why `write_graph()` refuses overwrite rather than rewriting.
  - Nothing in either graph may be called validated, and a test asserts it. That test is
    **expected to change** the day a FEMM run or a load-cell reading lands, and the change should
    be visible in a diff rather than silent.
  - `ehd:finding/thrust-discrepancy-lead` is recorded as `CLAIMED` and stays a lead until plan
    Task 9 reproduces it. *Principle 7, verified means reproduced.* Do not size or schedule
    against it.
  - The `ehd:` namespace URI (`https://maccre-2026.github.io/EHD-ResearchTests/ns#`) does not
    resolve yet. Harmless for JSON-LD parsing; it will need to serve a context document before
    the corpus is delivered to anyone.

### 2026-09-15 — the Gate reported a threshold it was not enforcing

Not a correction to the Task 5 entry above — a defect found *while* raising that entry's
thresholds, in the Gate itself. Recorded separately so the incident keeps its own provenance.

- **Status:** COMPLETED
- **Files:** `.kiro/governance/gate.ps1`, `tests/test_governance.py`
- **Signatures:** one new test,
  `test_gate_reports_the_thresholds_it_actually_enforces`.
- **Decision:** `$result.expectedBreadth` was initialised to a hardcoded `15` roughly a hundred
  lines above `$EXPECTED_SWEEP_FILES`, which enforcement read. Raising the constant to `19` left
  the summary printing `expected >= 15` **in the same run that enforced 19**. Nothing failed;
  it was caught by reading the Gate's own output, which is the weakest detection mechanism
  available. *Principle 4, two representations of one thing will drift* — inside the tool built to
  catch that.
  - Fixed by making the reported value derive from the constant: the field is `$null` in the
    result record and assigned `$result.expectedBreadth = $EXPECTED_SWEEP_FILES` at the point the
    constant is declared. Rejected: moving the constant above the record, which would have
    separated it from the comment block explaining the breadth rule.
  - Rejected: fixing the literal and moving on. A reported threshold that disagrees with the
    enforced one hands a reader a specific wrong number, which is worse than reporting none —
    *principle 2, an approximately-correct identifier is worse than an absent one*. So the fix is
    the mechanical check, and the literal correction is incidental to it.
  - The test is written as an invariant over **both** thresholds rather than a patch for this one:
    each threshold is declared exactly once as a literal, and every reporting field must read
    `$null` or the constant. `collectedFloor` already satisfied it, which is what makes it an
    invariant rather than a regression test.
- **Evidence** (observed, this session):
  - Planted the defect back (`expectedBreadth = 15`) and the new test failed with
    `gate.ps1 assigns expectedBreadth the literal 15`. Reverted; it passes. A check nobody has
    seen fail is not a check.
  - Gate re-run to completion, captured to file rather than read from the terminal: **status OK**,
    `EXIT=0`, `pytest 238 collected / 238 passed at floor 238`,
    `sweep breadth ruff=19 black=19 mypy=19 pyright=19 (expected >= 19)` — the reported and
    enforced figures now agree, which is the thing that was wrong.
  - Floor raised 237 → 238 for the new test, with both counts in the history comment.
- **Inherited:**
  - The Gate's other summary fields were **not** audited for the same pattern beyond the two
    thresholds the new test covers. Scope stated rather than implied: `expectedBreadth` and
    `collectedFloor` are checked; the stage names, exit-code table and skip reasons are still
    duplicated between the docstring, the constants and the summary text, and nothing checks them.
  - The Gate takes ~3 minutes and its output must be captured to a file to be read reliably in a
    long session; reading it back from a reused background terminal returned the previous run's
    tail, which is how a stale figure could be mistaken for a fresh one.

### 2026-09-15 — Task 6: lock reproducibility, bootstrap, MK0 end-to-end chain

- **Status:** COMPLETED
- **Files:** `requirements.lock` (new), `bootstrap.ps1` (new),
  `src/ehdpsu/mk0_reference.py` (new), `tests/test_mk0_reproduction.py` (new, 27 checks),
  `tests/test_environment_lock.py` (new, 23 checks), `tests/test_physics.py` (rewired to the
  shared reference module), `tests/test_governance.py` (new stageable-file leakage scan),
  `src/ehdpsu/breadcrumb.py` (leak fix), `README.md` (setup section rewritten),
  `.kiro/governance/gate.ps1` (floor 238 → 289, sweep breadth 19 → 22).
- **Signatures:** `run_mk0_chain(DesignParameters) -> dict[str, float]`;
  `_stageable_files()` and `_scan_for_framing()` in `test_governance.py`; eleven
  `*_REF_*` constants in `ehdpsu.mk0_reference`.
- **Decision:**
  - **The venv is not vendored**, per the appended plan decision of 2026-09-15. Reproducibility
    is `requirements.lock` plus `bootstrap.ps1`.
  - **Dev tooling is pinned in the same lock as numpy.** The Gate's verdict is a function of its
    tools; an unpinned ruff or pyright means the Gate can change its answer without the code
    changing, which destroys it as a regression signal.
  - **`ehdpsu` and `pip` are excluded from the lock.** `pip freeze` emits the project as
    `-e git+https://…@<commit>#egg=ehdpsu`, which would make the bootstrap clone the repository
    it is already inside. Pinning pip makes pip change its own version partway through installing
    the file. Both omissions are explained in the lockfile header and a test asserts the
    explanation is present, because an unexplained omission reads as an oversight and gets
    re-added.
  - **The lock's sort order is part of its format.** It was first generated with PowerShell's
    `Sort-Object`, which is culture-aware and put `mypy_extensions` before `mypy`; that would
    regenerate differently under another culture and produce diff noise indistinguishable from a
    real dependency change. Regenerated sorted by lowercased package name, and a test asserts it.
  - **Reference figures moved into the package**, `src/ehdpsu/mk0_reference.py`. They existed in
    three places — `test_physics.py`'s docstring, its module constants, and again in what the new
    reproduction test needed. Three copies of eleven floats that each pass against their own copy
    is *principle 4, two representations of one thing will drift*. `test_physics.py` now imports
    them.
  - **A test asserts `physics.py` does not import the reference module.** If it did, the pins
    would be comparing the code against a number the code itself supplied. A docstring warning is
    not a mechanism.
  - **The new reproduction test is the composition, not a duplicate.** `test_physics.py` tests
    each function in isolation with pinned inputs, so the chain is never executed and a wiring
    defect would leave it green — *principle 6, a green test suite is not evidence of a working
    system*. Composition is proved by perturbation rather than asserted: `m_rough` enters only
    through Peek's law and `L_wire_m` only through `k_geo`, so each must still move the thrust.
  - **The docs are bound to the code.** Ten published figure strings are regenerated from the live
    computation and located in the documents that carry them, so `README.md` and `docs/` cannot
    drift from the code silently. Scope stated in the test: it is a presence check and cannot
    detect a document holding both a right and a stale figure, because the docs legitimately quote
    other quantities in the same units (`3 MV/m`, `13.28 MV/m`, `1.74 kV`).
  - **Three representations of the minimum Python version now have to agree** —
    `requires-python`, `[tool.mypy] python_version`, and `bootstrap.ps1`'s floor. This drift
    already caused a real incident: `python_version` sat at 3.11 while numpy's stubs needed 3.12,
    so mypy aborted having checked zero files.
  - **README's package count is checked rather than removed.** It was a typed number; it now has
    a test.
- **Evidence** (observed, this session):
  - Gate: 289 collected / 289 passed at floor 289; ruff/black/mypy/pyright each swept 22/22 files;
    `EXIT=0`. Captured to a file, not read from a terminal.
  - `bootstrap.ps1` **actually run, twice.** Reuse path against the existing venv: OK, 32 packages
    verified, 27 reproduction checks passed. Then from a genuinely empty venv: OK, `EXIT=0`,
    32 packages verified, 27 checks passed, and the full suite re-run at 289/289 afterwards.
  - Interpreter discovery and venv creation verified from the partial `-Recreate` run:
    `using py -3.12 -> Python 3.12.8`, `creating .venv`.
  - The rebuilt venv came with `pip 24.3.1` where the previous one had `26.2.1`, and the lock
    comparison correctly ignored it. The pip exclusion did the job it was written for.
- **Inherited:**
  - **Three bootstrap branches remain unexercised:** `NO-PYTHON`, `PYTHON-TOO-OLD`, and the
    three failure statuses. Their text and exit codes are asserted by
    `test_environment_lock.py`; none has been observed firing. Stated rather than glossed —
    *principle 3* applies to my own report of this task.
  - **The lock pins versions, not hashes.** It does not defend against a re-uploaded PyPI artifact
    at an already-released version. Build isolation additionally fetches `setuptools>=61`
    unpinned. Both are recorded in the lockfile header and the README.
  - A stray `scipy-1.18.1-cp312-cp312-win_amd64.whl` sits in `.venv\Lib\site-packages` after the
    rebuild. Harmless and untracked; noted so a later reader does not treat it as a finding.
  - `README.md`'s inherited claim of byte-identical solver inputs across Linux/Python 3.11/numpy
    1.x is **withdrawn** rather than restated: it predates the 3.12 floor and is no longer
    reproducible here.

### 2026-09-15 — a third-party model name reached a tracked file, and the scan had a blind spot

- **Status:** COMPLETED
- **Files:** `src/ehdpsu/breadcrumb.py`, `tests/test_governance.py`
- **Decision:** Task 5's `breadcrumb.py` named a third-party model in two agent labels. The Gate
  ran green and the file was staged **afterwards** — and the leakage scan reads the git index, so
  a file created and scanned in that order is never opened at all. The check reported CLEAN over a
  file it had not read, which is *principle 3, never report success over unperformed work*, wearing
  the shape of a passing test.
  - Labels replaced with a non-identifying description. The corpus needs a stable agent id and the
    one fact bearing on trust — "known to be optimistic" — not a vendor.
  - The line drawn, stated so it is arguable: a **third party's** model identity is framing
    material; **this project's own** seat pins are its configuration and are already tracked in
    `.kiro/agents/`. `claude-opus-5` therefore stays.
  - Closed mechanically with `test_stageable_files_carry_no_private_framing`, which scans files
    that are untracked but **not ignored** — what the next `git add` would record. Kept as a
    separate test from the tracked scan so the failure says which situation you are in: not yet
    in the index and recoverable, versus already tracked with history possibly carrying it.
  - Zero files scanned is a legitimate pass **there** and not in the tracked scan, because a clean
    working tree genuinely has nothing staged. The asymmetry is deliberate and commented.
  - The scanning logic was extracted into one helper rather than written twice. Two copies of the
    scanner is principle 4 applied to the thing whose job is catching what everything else missed.
- **Evidence:** planted `__leak_probe__.md` in the working tree carrying one sentinel term; the new
  test failed, naming that file, its line number and the term it matched. Probe deleted; the test
  passes. A check nobody has seen fail is not a check.

  **Redaction, and why it is here rather than appended below.** This line first quoted the failure
  output verbatim, which put the sentinel term into a tracked file and turned the Gate red on the
  very next run — the check catching its own evidence. The term was removed from this line in
  place rather than corrected below it, because appending a correction would have left the
  offending string tracked, and the publication rule outranks the append-only habit when they
  conflict. Nothing else about the entry changed.

  **The general trap, now recorded twice from opposite directions.** An earlier note observed that
  *a checker which cannot distinguish discussing a thing from doing it is not a checker* — that was
  about false positives, when a docstring mentioning `--python-version` tripped a scan. This is the
  mirror image: **quoting a finding verbatim reproduces it.** A leak report describes what matched;
  it does not paste it.
- **Inherited:**
  - The two `.jsonld` artifacts already written into `artifacts/04_BreadCrumbs/` **still carry the
    old labels.** Breadcrumbs are append-only and `write_graph` refuses overwrite, so they were not
    corrected in place. They are untracked, so nothing leaks; the divergence between the code's
    labels and those artifacts' labels is recorded here rather than silently reconciled. A
    superseding artifact is the correct remedy if it ever matters.
  - Git history is still not scanned by either test. A pass means the working tree is clean, not
    that the terms were never committed.

### 2026-09-15 — Task 7 part 1: the profile layer exists and reproduces MK0

- **Status:** `COMPLETED` for the schema, the shipped profile and the reproduction proof.
  **Task 7 is NOT complete**: the consumer migration and the drift test remain. Recorded as a part
  rather than claimed whole — *principle 3, never report success over unperformed work*.
- **Files:** `src/ehdpsu/profile.py` (new), `profiles/mk0_benchtop_22kv.json` (new, tracked),
  `tests/test_profile.py` (new, 52 checks), `tests/test_mk0_reproduction.py` (+19 checks),
  `src/ehdpsu/physics.py` (`DesignParameters.from_profile`),
  `src/ehdpsu/spice.py` (`SpiceParams.from_profile`),
  `.kiro/governance/gate.ps1` (floor 289 → 360, breadth 22 → 24).
- **Signatures:** `FieldSpec`, `ProfileValue`, `Profile` (`value`/`required`/`count`/`basis_of`/
  `ceiling`/`section`/`to_json`/`save`), `ProfileError`, `FIELDS` (25 fields across 7 sections),
  `DESIGN_VALUE_EXEMPTIONS`, `from_json`, `load`, `load_named`, `migrate_raw`, `MIGRATIONS`,
  `FieldDiff`, `diff`; `DesignParameters.from_profile`, `SpiceParams.from_profile`.
- **Decision:**
  - **What counts as a design value, stated sharply**, because a drift test built on a fuzzy
    definition is either toothless or a false-positive generator. A design value is an **operator
    choice**. A physical constant (`EPS0`, `G_EARTH`) is not. A **cited empirical coefficient**
    (Peek's `g0` and `c`, the air-breakdown figure) is not — moving those into a profile would
    invite per-design tuning of published figures, which is the curve-fitting the project forbids.
    A **study range** (sweep endpoints, point counts) is not: it specifies an investigation, not the
    artifact. Registered in `DESIGN_VALUE_EXEMPTIONS` with a reason each, mirroring the Gate's
    declared-exclusions pattern.
  - **Every field carries `basis` and `kind`, and every MK0 field is `claimed`.** A `choice` is an
    assertion until the built article is measured; a `property` such as ion mobility is a
    literature figure. **The consequence is that the MK0 ceiling is `claimed` — one tier BELOW the
    `analytical-placeholder` the BreadCrumb corpus recorded.** The corpus modelled the provenance
    of the *formulas*; the profile models the provenance of the *inputs*. The lower ceiling is the
    correct figure, and a test asserts it so it cannot be quietly resolved in the flattering
    direction. Rejected: assigning `analytical-cited` to the design values to keep the two
    artifacts agreeing.
  - **Values are read through `Profile.value()`, never by attribute.** A mistyped name raises at
    the read instead of becoming an `AttributeError` inside a formula, and every read passes
    through one place that Task 8 can change to return a `Quantity` without touching a call site.
  - **`{value, unit, basis, kind, refs?, note?}` per field now**, not a bare number, so Task 8's
    Quantity layer needs no schema break.
  - **`L_sec_H` is an explicit `null`**, where `SpiceParams` used a `0.0` sentinel. Zero
    inductance is a physically meaningful value, so the sentinel was indistinguishable from a real
    setting — *principle 2, an approximately-correct identifier is worse than an absent one*. The
    sentinel translation happens in `SpiceParams.from_profile`, at the boundary.
  - **Validation is tested by rejection**, one test per malformation: missing/unknown field,
    missing/unknown section, wrong unit, wrong kind, unknown basis label, null in a non-nullable
    field, boolean (a subclass of `int`, so `True` would otherwise pass an integer check),
    fractional stage count, non-finite, non-numeric, unknown or missing key inside a value node,
    unknown or missing top-level key. **Nothing is defaulted**: a default in a loader is a hidden
    design decision.
  - **A newer schema is refused, not read loosely** — unknown fields would be silently dropped.
  - **Migration machinery ships unexercised by a real migration**, and the test that proves the
    mechanism uses an **injected synthetic migration and says so**. There is no v0. Proving a
    mechanism with a fake is honest; inventing a v0 that never existed would not be.
  - **The profile is generated, not typed.** A throwaway script read the `DesignParameters` and
    `SpiceParams` defaults and emitted the JSON, then was deleted. `test_profile.py` asserts the
    tracked file is byte-stable under re-serialisation, so a hand edit and re-save produces a clean
    diff rather than a reordered file.
  - **Defaults were kept for now and a parity test added**, rather than removing them in the same
    change. `TestProfileParity` asserts every `DesignParameters` and `SpiceParams` default equals
    its profile field, and that the maps cover every dataclass field so a new default cannot escape
    the check. This is what makes the remaining call-site migration provably number-neutral.
- **Evidence** (observed):
  - Gate: **360 collected / 360 passed** at floor 360; ruff, black, mypy and pyright each swept
    24/24 files; `EXIT=0`. Captured to a file.
  - **The chain built from `profiles/mk0_benchtop_22kv.json` is bit-identical to the chain built
    from the old defaults** — exact equality, not a tolerance — and matches all eleven pinned MK0
    reference figures at `rtol=1e-12`. That is the Task 7 demo: the reference numbers come back
    from the file alone.
  - `python -m ehdpsu.profile` validates the tracked profile and reports its ceiling as `claimed`.
  - A live duplicate was closed: `DesignParameters.f_sw` and `SpiceParams.f_sw_hz` were two
    representations of one number in two modules, and nothing had ever compared them. Both now map
    to `f_sw_Hz` and a test asserts the three agree.
- **Inherited — the remaining Task 7 work, stated explicitly:**
  - **The consumer migration has NOT happened.** `sweeps.py`, `femm.py`, `sanity.py`,
    `spice.build_netlist` and the tests still construct `DesignParameters()` and `SpiceParams()`
    with defaults. Until they read the profile, the design point still exists twice — the parity
    test is a guard against drift, not the migration.
  - **`spice.py` still hardcodes `cap = "1n"` in the netlist text**, with a comment admitting it
    duplicates `C_stage`. This is the generated-netlist case `profile-seam.md` names by name, and
    it is the single highest-value remaining target.
  - **The drift test does not exist yet.** `DESIGN_VALUE_EXEMPTIONS` is written and tested for
    shape, but nothing yet reads it to fail on an unregistered design-shaped literal. Until then
    the exemption register is documentation, not enforcement.
  - **Solver inputs have not been regenerated** through the profile path. When `build_netlist`
    switches over, `solver_inputs/` must come out byte-identical or the change must be deliberate
    and diffed; a test already pins those files.
  - The `README.md`, `docs/SPEC_SHEET.md` and `docs/PHYSICS_NOTES.md` copies of the design point
    remain. `test_mk0_reproduction.py` binds their *derived* figures to the code, but their
    *input* values are still independent text.

### 2026-09-15 — Task 7 part 2: the consumer migration and the drift test. Task 7 `COMPLETED`

- **Status:** COMPLETED. With part 1 above, this closes Task 7.
- **Files:** `src/ehdpsu/physics.py`, `src/ehdpsu/spice.py`, `src/ehdpsu/profile.py`,
  `src/ehdpsu/sweeps.py`, `src/ehdpsu/femm.py`, `src/ehdpsu/sanity.py`,
  `solver_inputs/ehd_llc_cw.cir` (regenerated), `tests/test_profile_seam.py` (new, 15 checks),
  `tests/test_solver_inputs.py` (new, 10 checks), and six test modules updated to the new
  constructors. `.kiro/governance/gate.ps1` (floor 360 → 387, breadth 24 → 26).
- **Signatures:** `physics.default_design()`, `spice.default_spice_params()`,
  `profile.default_profile()`, `profile.DEFAULT_PROFILE_ID`;
  `_llc_primary(sp, f_sw_hz)` and `_cw_ladder(n_stages, c_stage_f)` changed;
  `peek_inception_field`'s `delta` and `m_rough` became **required**;
  `SpiceParams.f_sw_hz` **removed**.
- **Decision:**
  - **No dataclass defaults at all.** `DesignParameters` and `SpiceParams` fields are now required,
    so an instance cannot exist without a profile behind it. Rejected: keeping the defaults but
    sourcing them from the profile via `default_factory`. That would have made a bare
    `DesignParameters()` perform hidden disk I/O, and a constructor that reads a file when it looks
    like it reads nothing is the kind of behaviour that is hard to reason about when it fails. The
    explicit `default_design()` names the file read in its name.
  - **`SpiceParams.f_sw_hz` was deleted, not reconciled.** `build_netlist` had been overwriting
    whichever value the caller passed so the two representations agreed. Silently reconciling a
    disagreement is worse than reporting it, and worse again than not having two. `_llc_primary`
    now takes the frequency as an argument sourced from the profile.
  - **`peek_inception_field`'s `delta` and `m_rough` are required.** They defaulted to `1.0`, which
    let a caller silently assume standard air and a polished wire — a design assumption made by
    omission, and one that *overstates* the inception field for any real emitter. Every call site
    already passed both explicitly, so nothing broke. `g0` and `c` keep their defaults and stay
    registered: they are part of Peek's cited relation, and per-design tuning of them is the
    curve-fitting the project forbids.
  - **`DEFAULT_PROFILE_DIR` is resolved from the package, not the process working directory.** A
    relative `Path("profiles")` would make `default_profile()` succeed or fail depending on where
    the caller was invoked from, which reproduces as a code bug.
  - **`default_profile()` is deliberately not cached.** `Profile` is mutable, and a shared cached
    instance would let one consumer's edit reach another's read.
  - **The drift test is structural, not a regex.** Layer 1 uses `ast` to find numeric literals in
    the three places a design value hides — module constants, dataclass field defaults, function
    parameter defaults — and requires each to be registered. Layer 2 asserts no *distinctive*
    profile value appears as a literal anywhere in `src/`. A regex over numbers would flag array
    indices, tolerances and the `(2/3)N³` cascade polynomial, and the register would fill with
    exemptions until the check meant nothing. Parsing gives the literal's *position*, which is what
    makes "a design value" distinguishable from "part of a relation".
  - **Layer 2 skips undistinctive numbers and blanket-exempt modules, and says why.** `1.0`, `2.0`
    and `5` are profile values and also appear innocently everywhere. `sweeps.py` is blanket-exempt
    because every numeric declaration in it is a study range, and three collide with profile fields
    — the wire-radius sweep deliberately *starts* at the design radius, while `0.02` and `5e-9`
    coincide with the dead-time fraction and diode saturation current by arithmetic accident.
    Flagging those would be false positives, and a check that cries wolf gets switched off.
  - **`mk0_reference` is registered as a blanket exemption.** Those constants are expected
    **outputs**, which `profile-seam.md` names as the one permitted hardcoding: their whole job is
    to fail when the physics moves. A profile stores no derived value.
  - **A dead-exemption test.** An entry matching nothing is stale and must be removed, or the
    register stops describing the code and the next reader concludes the check is unmaintained.
- **Evidence** (observed):
  - Gate: **387 collected / 387 passed** at floor 387; ruff, black, mypy and pyright each swept
    26/26 files; `EXIT=0`. Captured to a file.
  - **The drift test was proven against a planted violation.** Re-adding `C_stage: float = 1.0e-9`
    to `DesignParameters` failed three checks at once — the general registration check, the
    named design-dataclass regression check, and layer 2's value scan (`1e-09` equals profile field
    `C_stage_F`). Reverted; all 15 pass.
  - **The solver-input regeneration check was proven** by planting `2.2e-09` into the tracked
    `.cir`, which failed with the exact line and both values, then restoring by regeneration.
  - Every MK0 figure still reproduces; the numbers did not move.
- **A false claim in steering, found and fixed:**
  - `adapter-contract.md` states that generated inputs are "diffed by a test so they cannot drift
    silently". **That was untrue.** The only check on `solver_inputs/` asserted the files existed
    and were tracked; nothing compared their contents to a regeneration.
  - It surfaced by accident. Deriving the CW capacitor from the profile changed eleven lines of
    `ehd_llc_cw.cir` from `1n` to `1e-09`, and **nothing failed**. It was noticed only because the
    file was regenerated and diffed by hand.
  - `tests/test_solver_inputs.py` now regenerates every input into a scratch directory and compares
    byte-for-byte, asserts each is tracked, asserts no file in `solver_inputs/` lacks a check, and
    asserts two generator runs agree so the comparison cannot be flaky. The steering's claim is now
    true. *Principle 5, specifications drift from implementations unless mechanically checked* —
    where the specification was a steering file asserting a test existed.
  - The regeneration writes to a temp directory deliberately: a test that regenerated in place would
    diff a file against itself.
- **Inherited:**
  - **The `.cir` change is semantic-neutral but not byte-neutral.** SPICE parses `1e-09` and `1n`
    identically. The tracked file was regenerated deliberately and the diff reviewed; it is eleven
    capacitor lines and one comment.
  - **`profiles/` is not packaged.** `DEFAULT_PROFILE_DIR` resolves relative to the source tree,
    which works for the editable install this project uses. A wheel install would not carry the
    profiles, and `default_profile()` would raise. Packaging them as package data is a real task,
    not done here.
  - **Layer 1 does not see numbers inside expressions.** A design value pasted into the middle of a
    function body is caught only if it matches a distinctive profile value via layer 2. Stated in
    the module docstring rather than implied.
  - **The docs still hold the design point as independent text.** `README.md`,
    `docs/SPEC_SHEET.md` and `docs/PHYSICS_NOTES.md` have their *derived* figures bound to the code
    by `test_mk0_reproduction.py`, but their *input* values — 25 µm, 12 mm, 22 kV — are still prose
    nothing checks against the profile.
  - **`sanity.py` no longer imports `DesignParameters`** and reads the profile through
    `default_design()`; its printed output was not re-verified against a previous run beyond the
    test suite passing.

### 2026-09-15 — the reference profile became a test fixture; `profiles/` clones empty

- **Status:** COMPLETED
- **Files:** `.gitignore`, `profiles/README.md` (new, the only tracked file there),
  `tests/data/mk0_benchtop_22kv.json` (new, tracked fixture), `tests/conftest.py` (new),
  `src/ehdpsu/profile.py`, eight test modules repointed,
  `.kiro/governance/gate.ps1` (floor 387 → 389, breadth 26 → 27).
  `profiles/mk0_benchtop_22kv.json` **untracked** via `git rm --cached`, left on disk as the
  operator's working profile.
- **Decision:** Chief Operator, 2026-09-15: *"there is no set design point, that was a planning
  baseline that will change based on design and size"* and *"the profiles directory should clone
  empty and the profiles i work on should stay on disk … but should not be pushed publicly."*
  - **The MK0 profile is a regression fixture, not a design**, and now lives where fixtures live.
    Two different questions had been sharing one switch: *which design am I working on* and *what
    proves the physics has not drifted*. The `mk0` fixture and `test_examples.py` both called
    `default_design()`, so repointing `DEFAULT_PROFILE_ID` at a new design would have turned about
    thirty tests red — eleven pinned figures, three composition-perturbation checks, six CSV
    comparisons — and the obvious way to green them again would have been to edit
    `mk0_reference.py`. That would have destroyed the only mechanism detecting a changed formula.
    Every physics-pinning test now loads the fixture **by name** through `tests/conftest.py`.
  - **`profiles/*` ignored with `!profiles/README.md`.** Verified with `git check-ignore -v` and
    with `git ls-files --others --exclude-standard`, because a negation without a matching ignore
    rule silently does nothing — the `!artifacts/.gitkeep` incident. Only `README.md` is addable;
    the JSON is ignored; nothing else is tracked.
  - **A README rather than an empty or absent directory.** The folder exists in a clone carrying
    the explanation, including why nothing is shipped and where the fixture is.
  - **`default_profile()` now raises with guidance on a fresh clone, and that is correct.** A clone
    has no design. Inventing one would be worse than saying so: it would look authoritative and
    would be a second home for a design point. The error lists the profiles actually present.
  - Rejected: shipping a reference design in `profiles/` for convenience. It is precisely the thing
    the operator ruled out, and it would make a baseline read as the design.
  - The fixture's filename stem matches its `profile_id` so `load_named` and the file agree; its
    *role* is conveyed by its location, not its name.
- **Evidence:** Gate green — 389 collected / 389 passed at floor 389, all four sweeps at 27/27
  files, `EXIT=0`. `git ls-files -- profiles` returns only `profiles/README.md`;
  `git ls-files -- artifacts` returns nothing. Three new governance tests assert the fixture is
  tracked, that only the README is tracked under `profiles/`, and that a `.json` there is ignored.
- **Inherited:**
  - **`python -m ehdpsu.sweeps` and friends now fail on a fresh clone** until the operator authors
    a profile. That is the honest consequence of having no set design point, and the error says
    what to do, but it does mean the entrypoints are no longer runnable out of the box.
  - `test_the_default_helpers_agree_with_an_explicit_load` still exercises `default_design()`, so
    it depends on the operator's local `profiles/mk0_benchtop_22kv.json` existing. On a machine
    without it that test will fail rather than skip. Not fixed here; noted so it is not mistaken
    for a real defect.
  - The on-disk working profile and the tracked fixture are currently **byte-identical copies**.
    Nothing keeps them so, and nothing should — the working one is meant to change. But a reader
    may reasonably wonder which is authoritative: the fixture is, for tests only.
- **Feature requests recorded:** `artifacts/00_Governance/FEATURE_REQUESTS.md` created (it did not
  exist) with FR-001 GUI field-based profile editor, FR-002 in-GUI agent chat, FR-003
  `PhysicsCollaborator` sounding-board seat with search tooling, FR-004 low-temperature JSON writer
  seat. Each carries its open questions. Three hazards flagged there rather than in passing:
  vendoring MACCRE search tooling would make the charter's "one-directional and currently inert"
  relationship no longer inert and needs attribution or reimplementation; a search result is
  `claimed` and its provenance must be recorded, not just its content; and a writer seat able to
  stamp `measured` on an unmeasured value would defeat the basis ladder by design.

### 2026-09-15 — Task 8 parts 1-3: the Quantity layer and the derived operating point

- **Status:** `COMPLETED` for `quantity.py`, `operating_point.py` and the reframed propagation demo.
  **Task 8 is NOT complete:** the upper-bound label is not yet structural in `sweeps.py`'s CSV
  headers or the plot axes. Recorded as parts rather than claimed whole.
- **Files:** `src/ehdpsu/quantity.py` (new), `src/ehdpsu/operating_point.py` (new),
  `tests/test_quantity.py` (new, 47 checks), `tests/test_operating_point.py` (new, 50 checks),
  `src/ehdpsu/profile.py` (five exemptions), `tests/test_profile_seam.py` (layer-2 exemption path),
  `.kiro/steering/profile-seam.md` (**amended**), `.kiro/governance/gate.ps1`
  (floor 396 → 498, breadth 27 → 31).
- **Signatures:** `Dimension`, `UNITS`, `dimension_of`, `Band`, `EXACT`, `widest`, `Quantity`
  (`interval`, `may_be_called_validated`, `describe`, `column_header`, arithmetic), `QuantityError`,
  `exact`; `OperatingPoint`, `operating_point(prof, k_geo_band=...)`, `K_GEO_MODEL_BAND`.
- **Decision:**
  - **The pure float functions in `physics.py` were NOT changed.** `operating_point.py` wraps them.
    Three reasons in order of weight: `docs/PHYSICS_NOTES.md` records a formula-by-formula verdict
    about *those closed forms*, and rewriting them would silently invalidate the review; the MK0
    pins keep reproducing bit-identically because a wrapper cannot perturb a number it does not
    compute; and computing versus attributing are different jobs. This is a wrapper, not a second
    implementation — there is one piece of arithmetic per quantity.
  - **Units are SI-only with no scale factors.** `gf` and `N/kW` are deliberately unregistered even
    though the project publishes `9.56 gf` and `3.64 N/kW`. Registering them needs a conversion
    factor, and `G_EARTH` already lives in `physics.py`; a second copy of 9.81 in a unit table is the
    drift this layer exists to prevent. Worse, a scaled unit makes `N + gf` **dimensionally valid**
    and numerically nonsense. Presentation conversions happen at the output boundary.
  - **`dimension_of` parses its own generated canonical form.** Derived intermediates legitimately
    have unnamed dimensions — `k_geo * V` is siemens — so requiring every combination to be
    pre-registered would have made intermediate results unusable. Unregistered *hand-written* units
    still raise.
  - **Bands are multiplicative**, matching how this project states uncertainty (`k_geo` is
    "x0.1 to x1.0"). A band spanning zero is refused: it cannot be expressed multiplicatively, and
    clamping would understate.
  - **Dividing by, or subtracting, an upper bound is refused.** The result is a *lower* bound, which
    the type cannot express. Labelling it `is_upper_bound` would be wrong in the dangerous
    direction; dropping the label would lose it. *Principle 2.*
  - **`K_GEO_MODEL_BAND` lives in `operating_point.py`, not in a profile.** It is model-form
    uncertainty — a property of the *relation* — not a design input. Injectable as a parameter so
    the propagation can be demonstrated rather than asserted, with the docstring stating plainly
    that it is not a tuning knob: narrowing it requires calibration with recorded provenance.
- **A steering amendment, with the incident named:**
  - `profile-seam.md` stated "**a band is never tightened**" unqualified. **That is wrong for
    addition**, and `Quantity.__add__` was caught by its own postcondition. Adding an exact `3` to a
    `2` carrying a x10 band leaves the **absolute** uncertainty at `1.8` unchanged while the
    magnitude grows to `5`, so the **relative** band becomes `x0.64 to x1.0` — genuinely narrower,
    and nothing laundered. Forcing it to stay at x10 would **invent** uncertainty.
  - Neither measure is scale-invariant: dividing by an exact `3` shrinks absolute uncertainty
    threefold while leaving the relative band untouched. So the invariant is now split —
    multiplicative operations preserve or widen the **relative** band, additive operations preserve
    or widen the **absolute** uncertainty — with distinct error messages so a reader is not sent
    after the wrong cause. Both proven to fire.
  - Amended by the operator's explicit instruction, with the incident recorded beside the rule
    rather than the rule quietly reworded.
- **The plan's Task 8 demo was physically wrong, and is reframed:**
  - It said widening `k_geo` should widen "thrust, power and efficiency together". **Efficiency does
    not depend on `k_geo` at all**: `F/P = I·d/µ ÷ (V·I) = d/(µV)`, and the factor cancels exactly.
  - Computing efficiency as `T/P` makes the band *appear* to widen — x100 from two x10 inputs —
    because the Quantity layer treats correlated operands as independent. That is an artifact, not
    physics.
  - **The cancellation is deliberately not special-cased**: that would be a hidden tightening, and
    the next correlated pair would not get it. Efficiency is computed from its own cited relation
    instead, and the general rule is now in `profile-seam.md`: each published quantity comes from its
    own relation, and two routes disagreeing is Task 9's output.
  - Reframed demo, a sharper claim: widening `k_geo` widens **thrust, power, droop and ripple** and
    demonstrably leaves **`e_peek`, `v_onset`, efficiency and both margins untouched**. A layer that
    smeared the band over everything downstream would pass the original demo and fail this one.
- **Evidence** (observed):
  - Gate: **498 collected / 498 passed** at floor 498; all four sweeps at 31/31 files;
    `0 skipped, 0 xfail/xpass, 0 deselected`; `EXIT=0`.
  - Every MK0 figure reproduces **bit-identically** through the Quantity path — exact equality, not
    a tolerance. `e_peek`, `v_onset`, `k_geo`, `i_ion`, `power`, `thrust`, `cw_droop`, `cw_ripple`
    against their pins; efficiency and grams-force after their boundary conversions.
  - Every derived figure comes out `basis = claimed` and `may_be_called_validated() is False`.
  - `thrust.band.width` tracks the injected model band exactly (linear in `k_geo`), while
    `efficiency.value` is numerically identical under a 1000x change of that band.
  - The drift test caught `quantity.py` on its first run. The `1e-9` postcondition tolerance is
    numerically identical to the profile's `C_stage_F` — a genuine layer-2 false positive. Resolved
    by **naming** the tolerance (an improvement on the inline literal) and adding a layer-2 rule
    that skips literals belonging to an already-registered layer-1 declaration. The planted-violation
    proof was **re-run** afterwards, because an exemption path is exactly where a check quietly stops
    working.
- **Inherited:**
  - **Correlation is not tracked**, so correlated inputs over-widen — always conservatively, never
    flatteringly. Pinned in `TestCorrelationIsNotTracked` so the over-wide `T/P` band is not mistaken
    for an arithmetic error, and so a correlation-aware version has to change a test on purpose.
  - **`sweeps.py` still emits float CSVs with unlabelled headers.** `Quantity.column_header` exists
    and nothing calls it yet, so the upper-bound label is *not* structural in `examples/*.csv` or on
    the plot axes. This is the remaining half of Task 8 and it will change tracked reference files
    deliberately.
  - **`OperatingPoint` is not yet used by `sweeps.py`, `spice.py` or `sanity.py`.** They still call
    the float functions directly, which is correct but means the provenance layer is available rather
    than mandatory.
  - **Peek's law carries an uncertainty the band does not express.** The relation is empirical and
    fitted for smooth cylinders near STP; extrapolating to a 25 µm wire is a real unknown recorded
    only as a note on `e_peek`. Quantifying it would need a source this project does not have.

### 2026-09-15 — Task 8 part 4: the upper-bound label became structural. Task 8 `COMPLETED`

- **Status:** COMPLETED. With parts 1-3 above, this closes Task 8.
- **Files:** `src/ehdpsu/sweeps.py`, `tests/test_sweeps.py` (+10 checks), `examples/README.md`,
  the five tracked reference CSVs regenerated, `.kiro/governance/gate.ps1`
  (floor 498 → 508).
- **Signatures:** `sweeps.UPPER_BOUND_SUFFIX`, `sweeps.UPPER_BOUND_COLUMNS`,
  `sweeps.labelled(column)`, `sweeps.K_GEO_BAND_CAVEAT`.
- **Decision:**
  - **The label is applied at the single point a sweep row is assembled**, by mapping
    `labelled()` over the row dict rather than by writing three suffixed literals. So the label
    cannot be remembered for one sweep and forgotten for another, and the set of ceilings is
    declared once in `UPPER_BOUND_COLUMNS`.
  - **Exactly three columns are labelled**, and the more interesting half of the rule is which are
    not. `I_ion_mA`, `power_W`, `droop_V`, `droop_pct` and `ripple_Vpp` carry the `k_geo` x10
    **band**, which is a *two-sided* uncertainty — the real current may be higher or lower — so
    labelling them `UPPER_BOUND` would be a false statement, and would dilute the label everywhere
    it is true. A named `BANDED_BUT_NOT_BOUNDED` set in the test records that reasoning.
  - **Efficiency is labelled a ceiling even though its band is exact.** `k_geo` cancels in `F/P`,
    so the band is honestly exact; it is still the ratio of a ceiling thrust to the same power.
    "Precisely known" and "not a bound" are different claims and conflating them is how a ceiling
    becomes a prediction.
  - **Telemetry is deliberately NOT labelled**, and a test pins the asymmetry. `telemetry.derive`'s
    `thrust_N` is a load-cell reading; calling it a ceiling would be wrong in the opposite
    direction. Its `eff_N_per_W` additionally divides by measured *input* power, so it includes
    driver losses and is not the same quantity as the model's efficiency. "Make the thrust columns
    consistent" is precisely the tidy-up that would corrupt this.
  - **The droop and ripple plots gained a band caveat**, not a bound label. They are not ceilings,
    but a reader takes an absolute level at face value: their **trend** against frequency,
    capacitance and stage count is sound and their **level** is uncertain by an order of magnitude.
    Only the first is being demonstrated.
  - **The plot labelling is asserted against the source**, because a PNG cannot be diffed —
    matplotlib output is not byte-reproducible, which is why plots are untracked. The test checks
    the voltage plot's title and axis both contain `UPPER BOUNDS` and that all three band plots
    carry `K_GEO_BAND_CAVEAT`.
  - `labelled()` is **idempotent**, tested, so applying it twice during a later refactor cannot
    produce a doubled suffix.
- **Evidence** (observed):
  - Gate: **508 collected / 508 passed** at floor 508; all four sweeps at 31/31 files;
    `0 skipped, 0 xfail/xpass, 0 deselected`; `EXIT=0`.
  - The five tracked reference CSVs were regenerated deliberately. `git diff --stat` shows
    **one changed line per file** — the header only. No data row moved, which is the evidence that
    the labelling changed names and not numbers.
  - Tests assert the label in three places independently: on a freshly generated sweep row, in the
    tracked CSV headers a cloner actually reads, and in the plot-producing source.
- **Inherited:**
  - **`sweeps.py` still emits floats, not Quantities.** `Quantity.column_header` exists and remains
    uncalled; the labelling here is a parallel implementation of the same idea in the CSV layer.
    That is two representations of "which columns are ceilings" — `UPPER_BOUND_COLUMNS` in
    `sweeps.py` and `is_upper_bound` on the `OperatingPoint` fields — and they could drift. Not
    reconciled because routing sweeps through `OperatingPoint` is a larger change than this task,
    and the test suite currently pins both. **This is the most likely place the next drift appears.**
  - `sweep_stages.csv` remains withheld from `examples/` with its 10x `V_out_noload_ref_kV` defect,
    unchanged by this work.
  - `docs/SPEC_SHEET.md` and `docs/PHYSICS_NOTES.md` state the upper-bound caveat in prose and are
    bound to the code only for their *derived figures*, not for the labelling itself.

### 2026-09-15 — FR-005: the `ehdsuite` profile CLI. `COMPLETED`

Built **before** any GUI work, on the operator's instruction and the charter's layering rule: new
architecture belongs at the CLI level and below.

- **Status:** COMPLETED for the profile surface. `run`, `sweep` and `doctor` verbs are not built.
- **Files:** `src/ehdpsu/cli.py` (new), `src/ehdpsu/__main__.py` (new), `tests/test_cli.py` (new,
  28 checks), `pyproject.toml` (`[project.scripts]`), `README.md`, `src/ehdpsu/profile.py`
  (exit-code exemption), `.kiro/governance/gate.ps1` (floor 508 → 537, breadth 31 → 34).
- **Commands:** `schema [--json]`, `list`, `validate [targets...]`, `diff A B`,
  `new <id> --from <src> [--overwrite]`, `report <target>`.
- **Decision:**
  - **`new` requires an explicit `--from`.** There is no set design point, so the command cannot
    default one, and emitting a skeleton of placeholder values would put numbers nobody chose into a
    file that looks authoritative. `profile.from_json` already refuses to default anything for the
    same reason. A new profile is a copy of a design somebody stands behind.
  - **Validating zero profiles returns exit 4, not 0.** `profiles/` ships empty, so "validated 0
    profiles, all fine" is *principle 3, never report success over unperformed work*, in command
    form. Mirrors the Gate's `MYPY-CHECKED-NOTHING`.
  - **2 is reserved.** argparse exits 2 on a usage error, so no status of ours uses it: a collision
    would make a mistyped command indistinguishable from a real failure, which is exactly the
    distinction a script or an agent branches on. A test asserts the codes are distinct and skip 2.
  - **`python -m ehdpsu` is the documented form**, with `__main__.py` delegating to `cli.main`. The
    `ehdsuite` console script only exists after an install regenerates it, so a fresh clone or a
    half-finished bootstrap would have no command at all.
  - **`schema --json` is the surface FR-001 and FR-004 render from.** The GUI renders from
    `profile.FIELDS` rather than a hand-maintained form, and the writer seat needs the same
    description; exposing it once stops either duplicating it. A test asserts every field carries a
    non-empty `doc` and `unit`, because those are now user-visible strings.
  - **`diff` reports and never judges.** A ratio is printed; whether a change is an improvement is a
    physics question for the operator and the relevant Oracle. A test asserts no verdict word appears
    in the per-field lines.
  - **`new` refuses to copy an invalid source**, rather than propagating a defect under a fresh and
    more trustworthy-looking name.
  - **A copied profile's provenance warns that its bases are inherited.** Without it, a new design
    carries `claimed` values that look considered because they came from somewhere.
  - **`_resolve` does not fall back to `tests/`.** Reaching into the fixture directory from a user
    command would make a regression fixture behave like a design — the confusion the fixture was
    moved there to end. The fixture is usable, but only as an explicit path.
  - **One malformed profile does not hide the others** in `list`; it is reported in place.
- **Evidence** (observed):
  - Gate: **537 collected / 537 passed** at floor 537; all four sweeps at 34/34 files;
    `0 skipped, 0 xfail/xpass, 0 deselected`; `EXIT=0`.
  - Every command run by hand: `list`, `validate`, `report`, `new`, and `diff` on a real edited copy
    — `d_gap_m x0.2083`, `V_op_V x0.2273`, `N_stages x0.4` reported with ratios and no verdict. The
    overwrite refusal returned 6.
  - `report` shows the bound label and the band on the console: `thrust ... [UPPER BOUND, x0.1 to
    x1, basis claimed, not validated]`.
- **Two self-inflicted errors caught during the work, both worth recording:**
  - I wrote an unused `shutil` import with a fabricated justification comment ("imported for its
    side-effect-free presence... remove if it stays unused"). That is invented rationale for a
    mistake, which is worse than the mistake. Removed.
  - `test_the_diff_refuses_to_interpret` failed against its own subject: the diff's *disclaimer*
    contains the word "improvement". Scoped the check to the per-field lines. **Third instance** of
    the discussing-versus-doing trap in this project, after the `rtifacts` substring and the Gate's
    `--python-version` docstring. The pattern is now familiar enough to expect: any checker looking
    for a word will eventually find its own explanation of that word.
- **Inherited:**
  - **A throwaway `mk1_palm_5kv.json` was created and deleted** during manual testing. It was only
    partially edited — `V_op_V`, `d_gap_m` and `N_stages` changed while `r_wire_m` and `L_wire_m`
    stayed at MK0 — so it was not a faithful MK1 and its derived figures were not recorded. A
    half-real design left in `profiles/` is an approximately-correct artifact that gets mistaken for
    a decision. Authoring a real MK1 needs real inputs and is its own task.
  - `run`, `sweep` and `doctor` verbs are absent. `doctor` in particular needs the adapter detection
    matrix, which does not exist.
  - The CLI has **no way to edit a field**, only to copy a whole profile. Editing is hand-editing
    JSON, which is FR-001's job. `new` plus an editor is the current workflow, and it is a starting
    point rather than an interface.

### 2026-09-15 — Task 9: cross-validation engine. `COMPLETED`

- **Status:** COMPLETED for route agreement and claim adjudication.
- **Files:** `src/ehdpsu/claims.py` (new), `src/ehdpsu/crossvalidate.py` (new),
  `tests/test_crossvalidate.py` (new, 31 checks), `src/ehdpsu/cli.py` (`crosscheck` verb),
  `src/ehdpsu/profile.py` (three exemptions), `README.md`,
  `.kiro/governance/gate.ps1` (floor 537 → 571, breadth 34 → 37).
- **Signatures:** `ClaimSet`, `CLAIM_SETS`, `MK1_PALM_SCALE`, `grams_force_to_newtons`;
  `Route`, `RouteComparison`, `ClaimAdjudication`, `Agreement`, `ClaimVerdict`, `compare_routes`,
  `adjudicate_claim`, `adjudicate_claim_set`, `mobility_limited_thrust_route`, `efficiency_routes`,
  `compare_efficiency_routes`; `cli.EXIT_CLAIM_INCONSISTENT = 7`.
- **Decision:**
  - **The claim is adjudicated against the source's OWN figures**, not against this project's model.
    `T = P·d/(µV)` uses the source's gap, voltage and power, so the result is a test of the claim's
    **internal consistency**. That framing cannot be answered with "your model might be wrong",
    which is the objection any model-versus-claim comparison invites.
  - **The derived figure is an upper bound**, so a claim exceeding it exceeds a *ceiling*. The real
    figure is lower still and the gap is wider than the reported factor. The verdict
    `EXCEEDS_UPPER_BOUND` is distinct from `OUTSIDE_DERIVED_RANGE` precisely so the strongest
    statement is not used where no bound exists.
  - **Both overstatement factors are always reported.** The conservative one is named as the figure
    to quote; the generous one exists so the report cannot be accused of choosing the dramatic end,
    and so nobody quotes the dramatic end either.
  - **A claim register is tracked code, not a note.** A claim in prose can be forgotten, restated
    with different numbers, or dropped from a summary. In code with a test against it, the
    adjudication is reproducible in a clone — which nothing under `artifacts/` is.
  - **Ranges are a midpoint plus a band**, and a test asserts the original endpoints read back.
    Storing one end would be choosing the number that suited the argument.
  - **The source is described without naming a vendor.** A third party's model identity is framing
    material; what bears on trust is that the source is known to be optimistic. Same line as the
    BreadCrumb correction.
  - **`Agreement` has four states, not two.** `WEAK` exists because a wide band makes agreement
    easy: two figures a factor of five apart overlap if one carries an order-of-magnitude band, and
    calling that "agreement" overstates the evidence. `INCOMPARABLE` is its own state so a
    dimensional category error is never reported as a large ratio somebody might interpret.
  - **`bands_differ` is reported separately from value agreement**, because two routes agreeing on a
    number while disagreeing about how well it is known is itself a finding.
  - **Nothing is reconciled.** No best estimate, no weighted mean, no preferred route. A test
    asserts no attribute of `RouteComparison` is named `best`/`mean`/`preferred`/`consensus` — checked
    by attribute name rather than output text, because the temptation is to *add* a helpful field and
    that would pass any test written against today's output.
  - **An understated claim is reported, not welcomed.** `BELOW_DERIVED_RANGE` exists because a source
    that understates is no more reliable than one that overstates — it is wrong in the direction
    nobody checks.
- **The reproduction, and a correction to a lead carried since planning:**
  - Claimed MK1 thrust: **28-38 gf**. Derived ceiling from the source's own figures:
    **3.43-5.13 gf**. Overstatement **x5.46 to x11.1**, conservative figure **x5.46**.
  - The planning hand-check said **6-9x**. The reproduction is **wider on both ends**, and critically
    the conservative bound is **lower** than the hand-check's — so quoting "6x" would have overstated
    the floor of the disagreement. The lead was approximately right, which is exactly the condition
    *principle 7, verified means reproduced*, exists to stop being published. A test pins that the
    reproduced range brackets the hand-check rather than matching it.
  - The adjudication's basis is **claimed**, because both sides are. A well-founded conclusion about
    two claims is still about two claims: a strong argument, not a measurement.
  - The second case: the two efficiency routes **agree exactly on the value** (ratio x1) and differ
    by **x100 on the band**, flagged via `bands_differ`.
- **Two design flaws the tests found in the engine itself:**
  - **Interval overlap was the wrong precondition for agreement.** Two *exact* quantities have point
    intervals, so 100 W and 101 W could never overlap and were reported as `DISAGREE` despite being
    within 1%. That would have made the engine useless for two closed forms differing only by
    rounding, which is most of what it is for. Value closeness is now checked first, and overlap only
    decides between `WEAK` and `DISAGREE`.
  - A class-scoped fixture defined as an instance method is deprecated in pytest and becomes a
    collection error in pytest 10. Moved to module scope rather than left as a warning.
- **A fourth instance of the discussing-versus-doing trap.** `test_the_source_is_described_without_
  naming_a_vendor` listed vendor names literally, so the leakage scanner flagged the test file as the
  violation. Needles now assembled from fragments. After the `rtifacts` substring, the Gate's
  `--python-version` docstring and the diff's own disclaimer, this is frequent enough to state as a
  law: **a checker that names what it forbids becomes an instance of what it forbids.**
- **Evidence:** Gate **571 collected / 571 passed** at floor 571; all four sweeps at 37/37 files;
  `0 skipped, 0 xfail/xpass, 0 deselected`; `EXIT=0`. `python -m ehdpsu crosscheck mk0_benchtop_22kv`
  run by hand: route comparison AGREE with the band note, claim adjudication EXCEEDS-UPPER-BOUND,
  process exit **7**.
- **Inherited:**
  - **Only one claim set and one consistency check exist.** `adjudicate_claim_set` returns a list so
    adding checks does not change callers, but the MK1 power and voltage claims are not themselves
    adjudicated against anything.
  - **No route comparison for thrust or current.** Those have only one route each in the suite; a
    second would need FEMM (for `k_geo`) or a measurement, neither of which exists.
  - **The engine cannot detect a shared-ancestor error.** Two routes that both descend from the same
    wrong assumption will agree, and agreement is reported as agreement. Independence is asserted by
    the author in the `relation` string, not verified.
  - The `crosscheck` verb sets a failing exit status for an inconsistent **claim** but not for a route
    disagreement. Two routes differing is information for a human; making it a build break would
    force somebody to reconcile it, which is the thing the engine refuses to do.

### 2026-09-15 — the founding exemption register, enumerated

Written so that `DESIGN_VALUE_EXEMPTIONS` can be required to be recorded here. Sixteen of the
eighteen entries had been *described* in the entries above but never *named*, and a rule that every
exemption is named in the ledger cannot be enforced against a record that omits most of them.

**Why the rule is worth having.** The drift test refuses a numeric design value anywhere in `src/`,
and the exemption register is its only escape hatch. Nothing previously stopped an author — and
specifically a delegated coding seat — from **adding an exemption to make the check pass instead of
fixing the code**. The test only required a reason longer than twenty characters, and a
plausible-sounding sentence is cheap to produce.

Requiring the key to appear in this append-only ledger raises the cost of that from one sentence to
a recorded, dated, reviewable claim. It does not make it impossible; it makes it visible.

The eighteen founding entries, by category:

**Physical constants and cited empirical coefficients** — nobody chooses these, and moving them into
a profile would invite per-design tuning of published figures, which is the curve-fitting this
project forbids:
`ehdpsu.physics.EPS0`, `ehdpsu.physics.G_EARTH`, `ehdpsu.physics.AIR_BREAKDOWN_FIELD`,
`ehdpsu.physics.peek_inception_field.g0`, `ehdpsu.physics.peek_inception_field.c`.

**Study ranges, not design values** — they specify an investigation rather than the artifact:
`ehdpsu.sweeps` (blanket), `ehdpsu.telemetry.DEFAULT_BURST_THRESHOLD_FRAC`.

**Expected outputs, deliberately hardcoded** — `profile-seam.md` names pinned reference values as
the one permitted exception, because their whole job is to fail when the physics moves:
`ehdpsu.mk0_reference` (blanket).

**Algebra identity elements and formatting** — not quantities at all:
`ehdpsu.quantity.Dimension` (all four exponents default to 0, the dimensionless identity),
`ehdpsu.quantity.Band` (1.0/1.0, the exact-band identity),
`ehdpsu.quantity.describe.precision`,
`ehdpsu.quantity._RELATIVE_BAND_TOLERANCE`,
`ehdpsu.quantity._ABSOLUTE_UNCERTAINTY_TOLERANCE` (its 1e-9 collides numerically with the profile's
`C_stage_F`, which is why it had to be named rather than left inline).

**Schema and process metadata** — describing the file format or how a command terminated, not the
apparatus: `ehdpsu.profile.SCHEMA_VERSION`, `ehdpsu.cli` (blanket, exit codes).

**Comparison thresholds** — how close counts as close, which is a property of the check:
`ehdpsu.crossvalidate.compare_routes.close_ratio`,
`ehdpsu.crossvalidate.compare_routes.band_ratio`.

**Recorded claims** — figures asserted by an external source, kept verbatim for adjudication and
never used as inputs: `ehdpsu.claims` (blanket). Note this one adopts the same literature ion
mobility that appears in profiles, which the value scan would otherwise flag.

**Standing obligation from here on:** an exemption added without an entry in this ledger naming its
key fails `tests/test_profile_seam.py::TestTheRegisterItself::test_every_exemption_is_recorded_in_the_ledger`.
Adding the entry is part of adding the exemption, not paperwork that follows it.
