---
inclusion: fileMatch
fileMatchPattern:
  - 'artifacts/05_Solver_Runs/**'
  - 'src/ehdpsu/adapters/provenance*'
---

# Solver run provenance

Applied when writing or reading anything in the solver-run tier. Every external solver in this
project sits **outside `pytest`**, so provenance is the only thing that distinguishes a run that
happened from a run that was asserted.

---

## A run record is not optional

Three fields, and a value derived from a run missing any of them is **not** `solved`:

1. **Tool identity and version**, captured from the tool itself. Not the version someone believed
   was installed.
2. **Input file hash** — SHA-256 of the exact artifact fed in. A run against an input that has
   since changed describes a geometry or circuit that no longer exists.
3. **Values read back**, with what was read and from where.

Plus the run's **date** and the **profile identity** it derives from.

## Why the bar is here and not lower

FEMM, LTspice, QSPICE, Elmer, OpenFOAM and ParaView are GUI or external tools. Nothing in the test
suite can confirm a run occurred, so the honest default is that **it did not**. A record is the
only evidence, and *principle 3, never report success over unperformed work*, applies with full
force: a cross-check attributed to a solver nobody opened is a fabricated result even when the
number happens to be right.

**As of 2026-09-15 no solver run exists in this project.** FEMM, LTspice, QSPICE, Elmer, Gmsh,
OpenFOAM and ParaView are all uninstalled. Every number currently in the repository is closed-form.

## The `solved` basis is earned, not assigned

`solved` sits above `analytical-cited` on the ladder precisely because a numerical solve can
resolve something a closed form cannot — the wire-to-plane `k_geo` coefficient being the case this
project needs most.

That promotion is exactly why it must be gated. A `solved` label attached to an unrecorded run
launders an assumption into evidence, and every downstream band tightens on the strength of it.
*Principle 1, trust is a ceiling inherited from provenance.*

## What a solve does and does not establish

Stated because the difference is easy to lose once a number is in a table.

- **FEMM solves Laplace with no space charge.** Its peak wire-surface field is the
  **corona-onset** field, comparable against Peek. It is *not* the loaded operating field: once
  current flows, ion space charge lowers the near-wire field.
- **A SPICE result inherits its component models.** The `.model DHV` parameters are placeholders,
  so a loss or efficiency figure from that netlist is uncalibrated regardless of how carefully the
  simulation ran.
- **A CFD field inherits its mesh.** A result without demonstrated mesh convergence carries no
  information about its own discretisation error, however smooth it renders.

## Records are append-only

A run record is never edited. A re-run is a **new** record that names the one it supersedes.

Two runs of the same solver on the same input that disagree is a finding worth keeping both halves
of — overwriting the first destroys the only evidence that the disagreement existed.

## The tier is untracked

`artifacts/05_Solver_Runs/` is inside the ignored datacenter, so **nothing here exists in a clone**.
It may not be cited as evidence by a commit, and a commit touching it is not self-contained.

Consequence worth stating plainly: when a calibrated coefficient enters tracked code, the record
justifying it does **not** travel with it. So the tracked artifact must carry enough — tool,
version, input hash, date — inline to stand on its own, with the full record kept here for the
operator.

## What this file does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope. Cite by number and name.
- **The full basis ladder and the no-curve-fitting rule** — `physics-honesty.md`, always applied.
- **The five adapter obligations and tool detection** — `adapter-contract.md`.
- **The datacenter tier declaration** — `ehd-dev-rules.md`, always applied.
