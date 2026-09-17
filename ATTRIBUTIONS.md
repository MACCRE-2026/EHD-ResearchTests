# Attribution List

This project is built on the work of others. Every external work, open-source tool and prior-art
benchmark is named here because naming what the work stands on costs nothing, removes the easiest
way for a reader to dismiss it, and is a standing obligation rather than a one-off. A citation
without a reason is decoration; every entry states what it is used for here.

---

## 1. Physics and engineering references

These sources appear in docstrings in `src/ehdpsu/physics.py` and `src/ehdpsu/femm.py`. They are
the foundation for the corona inception law, the electrostatic solver, the Cockcroft-Walton
multiplier droop/ripple formulas, and the mobility-limited EHD thrust upper bound.

- **F. W. Peek, *Dielectric Phenomena in High Voltage Engineering*, 1929** — the corona inception
  law (`V_onset ∝ 1/√r · ln(d/r)`), used in `src/ehdpsu/physics.py` to calculate onset voltage for
  wire-to-plane emitters.
- **E. Kuffel, W. S. Zaengl, J. Kuffel, *High Voltage Engineering: Fundamentals*, 2nd ed., p. 366**
  — Peek's law derivation, coaxial field-to-voltage integration, corona current formula, and the
  Cockcroft-Walton cascade droop/ripple equations used in `src/ehdpsu/physics.py`.
- **T. B. Bahder, C. Fazi, *Force on an Asymmetric Capacitor*, ARL-TR-3005, 2003** — the
  mobility-limited EHD thrust upper bound `T = I·d/µ`, used in `src/ehdpsu/physics.py` as a
  theoretical ceiling for ion-neutral momentum transfer.
- **E. A. Christenson, P. S. Moller, "Ion-neutral propulsion in atmospheric media", *AIAA Journal*
  5(10), 1967** — the ion-neutral momentum transfer model that underlies the Bahder-Fazi thrust
  expression.
- **D. Meeker, *Finite Element Method Magnetics: Electrostatics Tutorial*, and the FEMM 4.2 Lua
  scripting reference (`ei_*` command set)** — the geometry generator and boundary condition setup
  used by the FEMM adapter in `src/ehdpsu/femm.py`.

---

## 2. Prior art and benchmarks

These designs informed the project's architecture and performance targets. Their published figures
are treated as `claimed` until reproduced by this suite.

- **MIT solid-state EHD aircraft (Barrett et al., 2018)** — demonstration that EHD flight is real
  at scale; used as a rough performance anchor for scaling arguments.
- **Plasma Channel (Jay Bowles), multi-stage ducted thruster series** — the aerodynamic-collector
  finding, and the sequential-staging penalty observed in multi-stage builds (an identical second
  stage yielding well under the naive doubling). Recorded as a constraint the planned fluid layer
  must reproduce; **no staging model exists in the suite yet.**
- **Integza (Joaquim Gomes), electroplated annular corona thruster** — graphite-and-electroplate
  fabrication for lightweight collectors. A fabrication technique noted for the physical build;
  **the suite models no collector mass.**
- **Open EAD / grid-thruster research including the UC Berkeley micro-ionocraft work** — the
  open-area-ratio optimum (roughly 80–88%, choking below ~75% and leaking space charge above
  ~90%). Recorded as a target band for the planned porosity-drag model; **the suite models no
  porosity yet.**

---

## 3. Open-source tools

### In use now

The following packages are installed and actively used by the suite:

- **numpy** — numerical array operations and linear algebra.
- **scipy** — special functions, integration, and optimisation.
- **matplotlib** — figure generation.
- **pandas** — data frame handling for sweeps and telemetry.
- **pytest** — test runner.
- **ruff** — linting.
- **black** — code formatting.
- **mypy** — static type checking.

### Planned adapters, not yet installed or run

The following tools are required for the planned adapter layer, but the suite does not yet call
them or depend on their presence:

- **FEMM** — electrostatics solver (not yet installed or run).
- **LTspice** — circuit simulation (not yet installed or run).
- **QSPICE** — circuit simulation (not yet installed or run).
- **Gmsh** — mesh generator (not yet installed or run).
- **Elmer** — CFD solver (not yet installed or run).
- **OpenFOAM** — CFD solver (not yet installed or run).
- **ParaView** — field visualisation (not yet installed or run).
- **CadQuery / OpenCASCADE** — CAD export (not yet installed or run).

---

## 4. Standards and models

The project deliberately reuses these vocabularies rather than reinventing them:

- **W3C PROV-DM and PROV-O (2013 Recommendations)** — the vocabulary chosen for the BreadCrumb
  derivation graph (entity, activity, `wasDerivedFrom`), serialised as JSON-LD. Chosen because PROV
  supplies the graph and deliberately leaves trust arithmetic to the consumer. **Not yet
  implemented** — the encoder is planned work.
- **Biba integrity model with a low-water-mark policy (Biba, MITRE, 1977)** — the ancestor of the
  trust-ceiling rule this project applies to uncertainty propagation: a derived quantity's
  confidence is bounded above by the worst of its inputs, `W(result) = min over inputs`. The rule
  is currently stated in project steering and applied by hand; **the propagating implementation is
  planned work.** Naming the ancestor is part of the rule rather than a courtesy — the project
  claims no novelty for it.
