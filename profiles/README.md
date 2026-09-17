# profiles/

**This directory clones empty.** Everything in it except this file is ignored by git.

Spec-scope-profiles are the operator's working designs. They stay on disk, are backed up to
Google Drive, and are **not** pushed to the public remote.

## Why nothing is shipped here

**There is no set design point.** The MK0 22 kV benchtop figures were a planning baseline and will
change with the design and the size. Shipping one profile here would make it look like *the*
design, and the first person to clone the repository would treat it as authoritative.

## Where the reference profile actually lives

`tests/data/mk0_benchtop_22kv.json`, tracked, as a **test fixture**.

That separation is deliberate, and it is the important thing on this page. Two different questions
were sharing one switch:

- *Which design am I working on?* — a profile in this directory.
- *What proves the physics has not drifted?* — the frozen MK0 fixture.

If those share a file, then pointing the suite at a new design turns roughly thirty tests red, and
the obvious fix is to update the pinned reference numbers so they pass again. That would destroy the
only thing detecting a changed formula. The fixture is frozen; new designs are additive.

## Authoring a profile

Today: copy the fixture as a starting point and edit the JSON, then validate it.

```powershell
Copy-Item tests\data\mk0_benchtop_22kv.json profiles\my_design.json
.\.venv\Scripts\python.exe -m ehdpsu.profile
```

`python -m ehdpsu.profile` validates every profile in this directory and reports the inherited
`basis` ceiling for each.

Planned, and tracked in `artifacts/00_Governance/FEATURE_REQUESTS.md`: a field-based GUI editor and
an agent that writes profiles to direction. Hand-editing JSON is the current state, not the
intended one.

## What the schema requires

Every field carries `value`, `unit`, `basis` and `kind`. Nothing is defaulted — a missing design
value is an error rather than a silent assumption, because a default in a loader is a hidden design
decision. Validation refuses unknown fields, wrong units, unknown `basis` labels, fractional stage
counts and non-finite numbers. Run the validator; it names the field and the reason.

**A note on `basis`.** A design value you chose is `claimed` — a manufacturer's spec for 25 µm wire
is an assertion until somebody puts a micrometer on it. It becomes `measured` when you measure the
built article. Because trust propagates by low-water-mark, a profile of `claimed` inputs ceilings
every quantity derived from it at `claimed`, however careful the arithmetic in between. That is
correct, and raising a `basis` to make an output look better qualified is the specific failure this
project exists to catch.
