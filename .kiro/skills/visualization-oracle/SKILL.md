---
name: visualization-oracle
description: Domain specialist for how the suite renders its results — ParaView and pvpython field rendering of the nacelle and its flow, matplotlib figure standards, uncertainty band rendering, colour and accessibility choices, and the whitepaper figure set. Use when touching plotting code, the ParaView adapter, or when deciding how a number is shown rather than what it is.
---

# Visualization Oracle

Domain expertise over the presentation layer — the last place a well-qualified number can become
an overstated one.

- **Field rendering** — ParaView / `pvpython`: velocity and space-charge fields through the
  nacelle, scripted camera paths, animation of the accelerating jet.
- **Plot generation** — matplotlib figures accompanying every sweep and telemetry reduction.
- **Uncertainty rendering** — bands, shaded regions, and upper-bound annotation.
- **Figure sets** — the whitepaper's plates, generated rather than assembled by hand.

## Refresh before acting

1. `src/ehdpsu/sweeps.py` and `src/ehdpsu/telemetry.py` — the existing plot writers and the
   caveat string already reused in captions.
2. `examples/README.md` — why plots are **not** tracked, which is a decision this domain owns.
3. `artifacts/00_Governance/2026-09-15_PLAN_ehd_modeling_suite.md` — Task 15 and Task 19.
4. `.kiro/skills/visualization-oracle/task_ledger.md`.

## Live hazards in this domain

**A plot without its uncertainty band overstates its own result.** This is the domain's central
failure. A clean line through `thrust vs voltage` reads as a prediction; the same line with its
`k_geo` band shaded reads as what it is — a shape whose vertical position is known to within
roughly an order of magnitude. The band is not decoration and is not optional.

**Matplotlib PNG output is not byte-reproducible.** It varies with matplotlib version, available
fonts and platform rasterisation. This is why plots are generated into the untracked datacenter
and **never committed**: a byte-compared PNG goes red on a font substitution, which is
indistinguishable from a genuine regression, and a test that cries wolf gets ignored. The CSVs
carry the numbers and are what `tests/test_examples.py` pins.

**A rendered field is only as real as the solve behind it.** ParaView will happily produce a
beautiful, smooth, entirely fictional velocity field from a coarse or non-converged mesh. A render
is a *view* of a solve, and it inherits that solve's provenance and its mesh-convergence status.
Nothing has been solved in this project yet, so no field render exists and none should be implied.

**Renders are the most persuasive artefact the project will produce, and therefore the most
dangerous.** A funding audience will remember an animation of air accelerating through the stages
long after they have forgotten the caption. Whatever qualification the number carries must survive
into the image itself, not only into the surrounding text.

**No visualization tool beyond matplotlib is installed.** ParaView is not present, `pvpython` has
never run, and no field render has been produced.

## Domain laws

1. **Every plot of a banded quantity shows its band.** Shaded region, error bars, or an explicit
   annotation — but never a bare line.
2. **Upper bounds are labelled in the axis label or the title, not only in the caption.** Captions
   are cropped when a figure is reused; axis labels travel with the image.
3. **The caveat travels with the figure.** The existing shared caveat string exists for this
   reason; reuse it rather than writing a new wording that will drift from it.
4. **Plots are never tracked in git.** Generated to `artifacts/07_Outputs/`. `examples/` holds
   CSVs only, and a test asserts no PNG appears there.
5. **A render states its source solve.** Tool, version, mesh identity and convergence status, in
   the figure metadata or an accompanying note. A render whose solve cannot be identified is
   decorative.
6. **Colour choices must survive greyscale and colour-vision deficiency.** Perceptually uniform
   maps for fields; distinguishable line styles as well as colours for series. A figure that only
   works in colour fails for a meaningful fraction of any audience and for every printed copy.
7. **Axes are labelled with units, and log scales are announced.** An unlabelled axis in a
   technical document is an invitation to misread by an order of magnitude.
8. **Task artifact and ledger entry after any change here.** Append only.

## What this skill deliberately does not restate

- **The eight principles** — `maccre-systems-doctrine.md` at user scope, cited by number and name.
- **The upper-bound labelling rule and the do-not-oversell rules** — `physics-honesty.md`, always
  applied. This domain implements them in pixels; it does not redefine them.
- **What the numbers mean** — the physics belongs to `electrostatics-corona-oracle`,
  `fluid-cfd-oracle` and `hv-power-electronics-oracle`.
