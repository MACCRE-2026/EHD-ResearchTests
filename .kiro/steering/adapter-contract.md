---
inclusion: fileMatch
fileMatchPattern:
  - 'src/ehdpsu/adapters/**'
  - 'src/ehdpsu/spice.py'
  - 'src/ehdpsu/femm.py'
---

# The adapter contract

Applied when editing any external-tool adapter. The suite's job is to string together a host of
open-source tools; this is the shape every one of them wears.

---

## The five obligations

Every adapter implements all five. An adapter missing any of them is incomplete, not minimal.

| Obligation | Meaning |
|---|---|
| **detect** | Is the tool present? Resolve through every route before concluding absence |
| **version** | Capture the tool's own reported version string, verbatim |
| **generate** | Produce the input artifact deterministically from the profile |
| **run** | Invoke it, or state clearly that invocation is manual |
| **parse** | Read results back, and fail loudly on an unrecognised shape |

Plus one that is not optional: **provenance**. A run records tool version, input file hash and the
values read back. Absent any of the three, the result is not `solved`.

## "Not installed" and "not chosen" are first-class states

This is what lets the plan map every route without committing to one.

- A **missing tool** degrades a capability **visibly**. It never silently substitutes a
  closed-form estimate, a cached result, or another tool's output.
- An **unchosen route** stays unchosen. Do not quietly make one solver the default because it
  happens to be the one that is installed.
- `doctor` reports the matrix. A capability whose tool is absent reports as absent, not as
  degraded-but-fine.

## Detection must survive a stale environment

`Get-Command` or a bare `shutil.which` is **not sufficient**, and this is not theoretical here.

Kiro CLI 2.21.4 was installed and working on this machine while `Get-Command kiro-cli` found
nothing, because the installer had written to the user `PATH` and the shell had inherited its
environment beforehand. Separately, the installer's own success message named
`C:\Program Files\Kiro-Cli\` — a path it never checked and where the tool was not. Two checks, each
correct in isolation, jointly reported a working tool as absent.

So detection tries, in order: an explicit configured path, the process environment, the platform's
authoritative path source (on Windows, the Machine and User registry `Path` scopes), and known
default install locations. And it distinguishes:

- **`TOOL-ABSENT`** — every route tried, genuinely not present.
- **`TOOL-UNRESOLVED`** — not on the process path, other routes unchecked or inconclusive.

Folding the second into the first produces a confident false negative, which is
*principle 2, an approximately-correct identifier is worse than an absent one*.

## Parsing

**An unrecognised output shape is an error, never an empty result.** The single most dangerous
input any adapter will receive is a tool that ran, exited zero, and returned nothing usable — an
empty list, a bare `[]`, a truncated file. That must be its own terminal state.

Output shapes for these tools are largely unpublished. Accept the plausible shapes explicitly, and
treat anything else as unusable rather than falling through to a default that reads as success.

## Generated inputs versus generated data

| Kind | Destination | Tracked |
|---|---|---|
| Solver **inputs** — netlists, Lua geometry, `.geo`, case dirs | `solver_inputs/` | **yes** — small, deterministic, diffed by a test |
| Solver **runs and outputs** | `artifacts/05_Solver_Runs/` | no |
| Derived data, plots, reports | `artifacts/07_Outputs/` | no |

Inputs are tracked so a cloner can run the tool. Outputs are not, because they are reproducible and
committing them creates a second representation that can disagree with what the code now produces.

## Attribution is mechanically checked

Every adapter registers the tool it wraps, and every wrapped tool has an entry in
`ATTRIBUTIONS.md`. A registered tool absent from that file **fails a test**. Naming what the suite
stands on costs nothing and is the transparency the public release rests on.

## Manual tools are still adapters

FEMM, LTspice, QSPICE and ParaView may need a human to press a button. That does not exempt them:
the adapter still generates the input deterministically, still captures the version, still records
the input hash, and still parses whatever the human saves back. It simply reports `run` as manual.

**A cross-check attributed to a solver nobody opened is unperformed work** —
*principle 3, never report success over unperformed work*. As of now, no FEMM, SPICE, Elmer or
ParaView run has occurred in this project.

## What this file does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope. Cite by number and name.
- **The basis ladder** — `physics-honesty.md`, always applied.
- **Datacenter tiers and git discipline** — `ehd-dev-rules.md`, always applied.
- **What each tool is for and what its results mean** — the relevant domain Oracle.
