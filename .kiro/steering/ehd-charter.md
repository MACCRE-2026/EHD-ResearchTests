---
inclusion: always
---

# EHD-ResearchTests — Charter

Global MACCRE Systems doctrine applies here and is **not repeated**. See
`maccre-systems-doctrine.md` and `maccre-systems-interteam-protocol.md` at user scope for the
eight principles, the append-only rule, the sovereignty contract and the Iron Rule.

Cite doctrine **by number and name together** — *principle 3, never report success over
unperformed work* — never the bare number. This file states what **this** project is and
where its boundaries sit, and nothing that belongs upstream.

---

## What this project is

**A modeling suite for electrohydrodynamic thruster design, and the physical programme it
serves.**

The suite lets the operator author, save, adjust and mathematically validate
**spec-scope-profiles**; orchestrates open-source tools for electrostatics, circuit
simulation, meshing, CFD, visualization and CAD behind a uniform adapter layer; imports
drawings into formats the simulation can consume; and extrapolates simulation results back
into physical dimensions and idealized geometry.

The physics core is one component of the suite, not its purpose.

Two things follow from *modeling suite* and shape every decision here:

1. **The profile is the seam.** Design values live in a profile and nowhere else. A number
   typed into a module, a document, a netlist or a plot label is a second representation, and
   *principle 4, two representations of one thing will drift*, says what happens next.
2. **The suite's standing job is reality alignment.** Its inputs include figures from an AI
   collaborator known to be optimistic, and from maker-community benchmarks. An output that
   presents an inherited claim with more confidence than its provenance supports is the
   central failure mode this project exists to prevent.

## What this project is *not*

**It is not a MACCRE Systems project.**

The doctrine, the interteam protocol and the development pause each scope themselves to
MACCRE (`B:\EXO_GANS`), Sovereign Importer (`B:\SovereignImporter`) and MACCRE-VIZ. They reach
this workspace because they sit at **user scope**, not because they name it. The doctrine's
principles are adopted here **deliberately, by citation**, because they were earned by real
incidents and this project will meet the same ones.

**The pause does not apply here.** Chief Operator, 2026-09-15: MACCRE Systems is paused *so
that this project takes precedence*. Feature development here is open.

## Relationship to MACCRE and Sovereign Importer

**One-directional, and currently inert.**

- The Iron Rule holds. This project **reads** `B:\EXO_GANS` and `B:\SovereignImporter` to
  understand them — expected and encouraged — and **writes to neither**. Work needed there is
  a TFR in `B:\EXO_GANS-SovereignImporter_Shared\`, not a patch.
- Nothing in this workspace binds another team. Only reports in the coordination folder do.
- This project **produces** something the other two want: a BreadCrumb corpus of numerically
  real trust artifacts, encoded in W3C PROV vocabulary, intended as empirical input to their
  trust-scoring standard. **Producing it is unconstrained. Delivering it is not.**
  Ratified 2026-09-15 as **produce and hold** — no coordination-channel activity is
  initiated, and the handoff is a separate decision once MACCRE Systems is unpaused.

Why the corpus is worth anything to them: the basis ladder here is **populated with real
measurements and real solver output**, not synthetic tiers, and the spread between its top and
bottom is an order of magnitude. It can show an actual laundering path — a `claimed` figure
that would have become `validated` had nobody checked. That is the case
*principle 1, trust is a ceiling inherited from provenance*, describes, caught in the wild.

## What is contractual here, and what is incidental

Stated because an outside reader cannot tell the difference, and only this project can say.

**Contractual — may be built against:**
- The `solver_inputs/` and `examples/` directories, and the fact that generated inputs are
  tracked while generated data is not.
- The five-tier basis ladder (`measured`, `solved`, `analytical-cited`,
  `analytical-placeholder`, `claimed`) and low-water-mark propagation over it.
- PROV-O / JSON-LD as the BreadCrumb encoding.

**Incidental — may change without notice:**
- Everything under `artifacts/`, including tier names and layout.
- Module paths, class names and the internal profile schema until the schema is versioned and
  published.
- The `ehdpsu` package name. `pyehd` is reserved as a public identity and the rename has one
  clean moment.

## Layering: the GUI wraps the CLI, and holds no architecture of its own

**Chief Operator, 2026-09-15, standing requirement:** any new architecture belongs at the **CLI
level and below**, never in the GUI. *"The GUI should wrap a well thought architecture and not end
up being architecture itself."*

So the order is settled and is not a matter of convenience: the CLI comes first, and the GUI wraps
it. A capability that exists only behind a GUI button is a capability with no test, no scriptable
form, and no way to reproduce what it did.

Applied rules:

- **A new capability is a library function plus a CLI verb.** The GUI may then call it. If a
  behaviour cannot be expressed as a command, it is not ready to be a button.
- **The GUI holds no design values, no schema knowledge and no physics.** It renders from
  `profile.FIELDS` and calls the same code the CLI calls. A form maintained by hand is a second
  representation of the schema, and *principle 4, two representations of one thing will drift*.
- **No behaviour is GUI-only.** If the GUI can do something the CLI cannot, that is the defect, not
  a feature — it means the architecture moved upward without anyone deciding to move it.

Feature requests and their open questions live in
`artifacts/00_Governance/FEATURE_REQUESTS.md`, which is untracked and therefore not citable
evidence.

## Publication and exposure

**This repository is intended to become public.** The remote is
`MACCRE-2026/EHD-ResearchTests`.

Consequences that hold regardless of current visibility:

- **Stage by name.** Never `git add .`, `-A`, `-u`, or a directory.
- **`artifacts/` is ignored at the folder level and holds conversation transcripts.** Those
  transcripts contain framing and persona material that must never reach a public remote. The
  folder-level ignore is the enforcement; a test asserts it holds.
- **Nothing under `artifacts/` is citable evidence.** It does not exist in a clone, so a
  commit touching it is never self-contained or reproducible for anyone else.
- **A scan of the working tree says nothing about history.** Never report "the repository is
  clean" — only a scoped result, with the scope in the same sentence.

## Verification stance

- **A hand-check is a lead, not a finding.** *Principle 7, verified means reproduced.* Several
  figures in this project were worked by hand during planning; none of them counts until code
  reproduces it.
- **Judge every test run on the collected count**, never the pass count alone.
- **A solver run that nobody performed did not happen.** FEMM, LTspice, QSPICE, Elmer and
  ParaView are outside `pytest`. A cross-check claimed against a solver nobody opened is
  *principle 3, never report success over unperformed work*.
- **`k_geo` is uncalibrated.** Do not write a docstring or a document implying that current,
  power, thrust or efficiency figures are validated while it carries its placeholder band.

## Safety

This is a **4.8 kV to 22 kV** project at milliampere currents. That is lethal. The palm-scale
rail being "low voltage" relative to the benchtop cell is exactly the framing that gets
someone hurt. `hv-safety.md` is always applied and is not discretionary.

## Platform reality

Windows-first, PowerShell, `pwsh`. No heredocs. Never race a shell command against the
`fs_write` it depends on.

`B:` is a local fixed NTFS volume, not a synced mount — but Google Drive for Desktop is
running and may cover folders on it. Drive sync is not atomic across a file set, so
*principle 8, atomicity is a property of an artifact set, not a file*, governs anything
placed in the datacenter.
