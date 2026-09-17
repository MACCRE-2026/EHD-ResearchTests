---
inclusion: always
---

# EHD-ResearchTests — Development Rules

Companion to `ehd-charter.md`. The charter says what this project is; this file says how work
is done in it. Doctrine is cited by number **and** name, never restated.

---

## The datacenter

`artifacts/` is the **project-scoped datacenter**, ignored at the folder level, backed up
locally and to Google Drive.

**The entire project root is Drive-synced** — confirmed 2026-09-15, and it syncs while work is
in progress. Drive is the operator's chosen mechanism for redundancy, multi-device access and
data protection. Treat it as a feature to be made safe, not an obstacle.

```
artifacts/
  00_Governance/                 roadmap, plans, decision records, directives
  01_Collaborator_Conversations/ AI collaborator transcripts
  02_Kiro_Conversations/         session transcripts and handovers
  03_Task_Packets/               planner -> executor instructions
  04_BreadCrumbs/                trust artifacts, PROV graphs, append-only
  05_Solver_Runs/                FEMM / SPICE / Elmer runs + provenance
  06_Inputs/                     imported drawings, scans, measured telemetry
  07_Outputs/                    sweeps, meshes, renders, reports
  08_Reference/                  papers, datasheets, standards
  09_Backups/                    hash-verified local snapshots + manifests
```

**The tier set is declared, not improvised.** Adding a tier means adding it to this list
first. A directory that appears on disk without a declaration is a tier nobody agreed to and
that no backup script knows about.

### Three standing consequences

1. **Untracked is an evidence gap.** Nothing under `artifacts/` exists in a clone. No commit
   may cite it, and no commit touching it may be described as self-contained or reproducible.
   Its version history is the backups, not git.
2. **No SQLite in the datacenter.** Drive covers it, and Drive uploads files independently. If
   one is unavoidable, `journal_mode=DELETE`. **Checkpoint, never unlink:**
   `PRAGMA wal_checkpoint(TRUNCATE)` is lossless, while deleting a `-wal` can destroy
   committed transactions. *Principle 8, atomicity is a property of an artifact set, not a
   file.*
3. **Backups are verified from the destination, and never inside the synced tree.** A copy
   re-hashed from its source verifies nothing. A snapshot stored inside the Drive-synced root
   is protected by the same mechanism whose non-atomicity it exists to survive. A declared
   source set, a timestamped directory outside the project root, a manifest with SHA-256 per
   file, and a non-zero verified count — or it is a claim, not a backup.
4. **Never snapshot a tree that is mid-sync.** If `.tmp.driveupload/` holds files, a transfer
   is in flight and the tree is moving. That is its own terminal state, not a backup.

## Git under Drive sync

**`.git/` is inside the synced tree, and a git repository is an artifact set.** `.git/index`,
the object store, `refs/` and `HEAD` are only meaningful together, and Drive uploads them
independently. A sync that captures a half-written index, or propagates one device's `refs/`
against another's objects, yields a corrupted or divergent repository. Single-writer discipline
does not help — the non-atomicity is in the sync, not in git. `.git` being small here is
irrelevant; the hazard is ordering.

**Git and Drive have complementary jobs and must not be made to overlap on `.git/`:**

| Concern | Carrier |
|---|---|
| Tracked content across devices | `origin` on GitHub |
| The untracked datacenter | Google Drive |
| `.git/` internals | neither — GitHub already holds this state |

**Applied rule: push often, and treat the remote as authoritative.** A corrupted local `.git`
then costs a re-clone rather than history.

**`git status` is not stable under sync.** Drive creates `.tmp.driveupload/` inside the synced
folder mid-transfer, so a status check can be empty one minute and show thirty untracked files
the next for reasons unrelated to any work. Both staging directories are ignored; never report
a working tree as clean without accounting for sync state.

**Drive does not read `.gitignore`.** Ignoring a path in git says nothing about whether Drive
uploads it. `.venv/` (~408 MB) and `.mypy_cache/` (~17 MB) are gitignored and synced anyway.
Excluding them is an operator-side Drive configuration decision.

## Tracked inputs, untracked outputs

| Directory | Tracked? | Holds |
|---|---|---|
| `solver_inputs/` | **yes** | Generated inputs the GUI solvers need. Small, deterministic, regenerable, and diffed by a test so they cannot drift silently |
| `examples/` | **yes** | Reference outputs so a clone has something to compare against. Numeric CSVs only |
| `artifacts/07_Outputs/` | no | All working generated data |

**Plots are never tracked.** Matplotlib PNG output is not byte-reproducible across versions,
fonts and platforms, so a byte diff produces failures indistinguishable from real regressions.
The CSVs carry the numbers; the numbers are what is worth pinning.

## Git

- **Stage by name.** Never `git add .`, `-A`, `-u`, or a directory. Route non-trivial staging
  through `git-steward`.
- **A negation without a matching ignore silently does nothing.** `.gitignore` once carried
  `!artifacts/.gitkeep` with no ignore rule for `artifacts/` at all, so the folder was never
  ignored and four generated files ended up tracked inside it. Git does not warn about this.
  When adding a negation, verify with `git check-ignore -v`.
- **`git ls-files -- <path>` is the authoritative tracked check**, not `git status`. Staged
  renames and deletions make removed paths appear in status while they are already out of the
  index.
- Push to `main` directly until the repository is public; PRs thereafter so the diff is
  reviewable.
- Never force-push, `reset --hard`, `clean -f`, rewrite history, or amend a pushed commit
  without explicit per-instance approval.

## Verification: two tiers, and why sweep breadth is not negotiable

**The Gate** (`.kiro/governance/gate.ps1`) runs every turn, costs nothing, and is unscopeable. Run
it rather than assembling its stages by hand. **The Survey** is the occasional, expensive problem
finder reached for when a wall has been hit that nobody has identified yet; its output is new Gate
checks.

**A test is the scoped check.** It proves one property precisely — its virtue and its limitation. A
green test is a **narrow** success, and narrow success is what obscures failure elsewhere.

**A whole-codebase static sweep is not another narrow check. It is the antidote to the narrowness of
all the others**, answering the one question no test can: did this local change break something
lateral or downstream?

From which the asymmetry that governs every change here:

- **Narrowing a test** makes a smaller test. Still useful.
- **Narrowing a sweep destroys its entire purpose**, converting the anti-siloing layer into one more
  silo.

**Applied rule: a static sweep is whole-codebase or it is not a sweep.** The Gate proves the breadth
rather than trusting the configuration — every sweep reports how many files it examined and the Gate
asserts that count. A config trusted to be as wide as intended is the same category of error as a
solver run nobody performed.

**Any exclusion in any tool configuration is declared and justified here, or it is a defect.** The
incident: a `pyrightconfig.json` excluding one package meant two files were never type-checked and
held six real errors, with nothing reporting it — the config was internally consistent and silently
narrower than anyone believed.

*Currently declared exclusions: none. Every sweep covers the whole tree.*

**A green Gate means no known class of error is present.** It has never meant the system works, and
nothing generated here may imply otherwise — *principle 6, a green test suite is not evidence of a
working system*.

## Numbers and documents

- **Every number in a document is generated, never typed.** A hand-entered figure is an
  unchecked claim, and *principle 5, specifications drift from implementations unless
  mechanically checked*, is the rule it breaks.
- **An upper bound is labelled an upper bound everywhere it appears** — CSV column header,
  plot axis, spec sheet line, whitepaper table. Labelling it once in a footnote and omitting
  it in the table is how a ceiling becomes a prediction.
- **A derived quantity inherits the worst uncertainty of its inputs.** Low-water-mark, never
  the confidence of the last handler. *Principle 1, trust is a ceiling inherited from
  provenance.*
- **An absent value beats an approximately-correct one.** *Principle 2, an
  approximately-correct identifier is worse than an absent one.* A known-defective reference
  is withheld and the reason recorded — never published with a caveat nobody will read next to
  it.
- **Units and geometry belong in identifiers.** `r_wire_m`, not `wire`. Radius versus diameter
  is explicit in the name. A 25 µm emitter read as a radius and as a diameter differ by 29% in
  onset voltage, and both readings already exist in this project's source material.

## Records

- **Append-only.** Corrections are appended beside the claim they correct, with a date.
  Nothing is deleted; nothing is renumbered.
- Terminal states are `COMPLETED` (observed evidence and a timestamp), `WITHDRAWN` (a
  rationale) or `SUPERSEDED` (naming its replacement).
- A completion claim without observed evidence is *principle 3, never report success over
  unperformed work*, in document form.

## Reporting

- **State the scope in the same sentence as the result.** "No findings in staged content and
  the 3 unpushed commits; full history not scanned" is a result. "Clean" is not.
- **`SKIPPED`, `NOT-SCANNED` and `INCOMPLETE` are distinct from `CLEAN`.** A check whose output
  did not render is not a passing check.
- **Judge every test run on the collected count.** One `ImportError` in one orphaned module can
  reduce a suite to zero while the report looks normal.
- **A tool reported missing may be a stale environment, not an absence.** `Get-Command` alone
  once reported Kiro CLI absent while it was installed and working, because the shell predated
  the installer's PATH write. Check the registry `Path` scopes before concluding absence, and
  keep "not on the process path" distinct from "not present".

## Verification

- **A hand-check or a user report is a lead.** Reproduction is the first task and the size of
  the work is unknown until it completes. *Principle 7, verified means reproduced.*
- **Seam changes need a scripted by-hand walkthrough**, recorded with its failure modes. A
  green suite is not evidence of a working system when no stubbed test visits the seam.
- **A manual solver run records tool version, input file hash and the values read back.**
  FEMM, LTspice, QSPICE, Elmer and ParaView sit outside `pytest`; provenance is the only thing
  that distinguishes a performed run from an asserted one.
- Clean up temporary files created during verification.

## Platform

Windows-first, `pwsh`. Command separator is `;`, never `&&`. Environment variables are
`$env:TEMP`, never `%TEMP%`. No heredocs. Quote paths containing spaces. Never race a shell
command against the `fs_write` it depends on.

Long-running processes — dev servers, watchers, solver GUIs — are not launched from a
blocking shell call.
### The terminal is not a stable container

Two failure modes were diagnosed on 2026-09-15, after months of the operator's own terminals
behaving perfectly under the identical commands. Neither is a PowerShell problem, and neither
is fixable from a PowerShell profile.

**1. Stop every background process you start, as soon as you have read its output.**

Seventeen accumulated terminals — six of them reported `running` while long finished — wedged the
long-lived shell completely: every command returned empty output at exit `-1`. Stopping them
restored it on the next command. Terminals accumulate monotonically across a session, which is
exactly why the trouble looks like gradual degradation.

A background process is not finished when its output arrives. It is finished when it has been
stopped.

**2. Set the terminal's geometry yourself, in the first command of every new shell.**

The agent PTY is never rendered, so it comes up at **80 columns with a 2-line buffer** and drifts
to about **19 columns** during a session. PowerShell's formatter hard-wraps to host width *at
format time*, so `Format-Table`, `Select-String` and anything reaching `Out-Default` emit
19-character lines — words split mid-token, output unreadable. The commands are fine; the
container is not.

```powershell
try { $r = $Host.UI.RawUI; if ($r.BufferSize.Width -lt 200) {
  $r.BufferSize = [System.Management.Automation.Host.Size]::new(200,3000)
  $r.WindowSize = [System.Management.Automation.Host.Size]::new(200,50) } } catch {}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $env:NO_COLOR = '1'
```

This genuinely resizes the pseudoconsole rather than faking a host value — a child `pwsh` spawned
afterwards inherits 200 columns.

**Why this cannot live in `$PROFILE`, which was tried and failed.** `$Host.UI.RawUI` is **null at
profile-load time** in this terminal, though it works moments later. The resize therefore threw
into a silent `catch` on every shell, and looked plausible for an hour. `$env:TERM_PROGRAM` is
also not reliably set that early: the same guard fired on one fresh terminal and not on the two
after it. A profile can carry the encoding most of the time; it can never carry the geometry.

### Consequences for how output is read

- **Long or wide output goes to a file, and the file is read with the file-reading tool.** That
  bypasses the formatter, the PTY and the harness's output capture in one move. It is how the
  Gate's result must be read.
- **`| Select-Object -Last N` forces the formatter**, which is what wraps to host width. Prefer
  `Out-String -Width 200`, or a file.
- **Never trust output read back from a reused background terminal.** A reused terminal returned
  the *previous* run's tail, which is indistinguishable from a fresh result and is how a stale
  number gets reported as a new one. *Principle 3, never report success over unperformed work.*
- **No nested `pwsh -File`** from inside a harness shell. Use a background process, or invoke the
  script directly.
- **A command returning empty output at exit `-1` is not a failed command.** It is an
  unresponsive shell. Distinguish the two before concluding anything about the code, and check
  `list_processes` first.
