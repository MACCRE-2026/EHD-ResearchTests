"""Shared test scaffolding: the frozen MK0 reference profile.

Why the regression suite does not use ``default_profile()``
----------------------------------------------------------
``profiles/`` is gitignored and **ships empty**. There is no set design point — the MK0 22 kV
figures were a planning baseline and will change with the design and the size — so committing a
reference design would present a baseline as authoritative, and a clone would inherit it.

That leaves the suite needing a design to test against, and the honest answer is that what it needs
is **not a design at all**. It needs a frozen fixture. So the MK0 profile lives here, in
``tests/data/``, tracked, and every physics-pinning test loads it **by name** through this module.

The failure this prevents
-------------------------
Before this split, the ``mk0`` fixture and ``test_examples.py`` both called ``default_design()``,
which reads whichever profile ``DEFAULT_PROFILE_ID`` names. Pointing that at a new design would have
turned roughly thirty tests red — the eleven pinned figures, the composition-perturbation checks and
all six reference-CSV comparisons — and the obvious way to make them pass again would have been to
update ``mk0_reference.py``. That would have destroyed the only thing detecting a changed formula,
which is exactly what those pins are for.

So: *which design am I working on* and *what proves the physics has not drifted* are different
questions, and they no longer share a switch. The fixture is frozen; new designs are additive.

Imported explicitly rather than used as pytest fixtures because several modules need a design at
**import** time for a module-level constant, which a pytest fixture cannot supply.
"""

from __future__ import annotations

from pathlib import Path

from ehdpsu import profile
from ehdpsu.physics import DesignParameters
from ehdpsu.spice import SpiceParams

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "tests" / "data"

#: The frozen MK0 regression fixture. Tracked, unlike anything in ``profiles/``.
#:
#: Its filename stem matches its ``profile_id`` so ``load_named`` and the file agree; its *role*
#: is conveyed by living under ``tests/data/`` rather than by its name.
REFERENCE_PROFILE_ID = "mk0_benchtop_22kv"
REFERENCE_PROFILE_PATH = DATA_DIR / f"{REFERENCE_PROFILE_ID}.json"


def reference_profile() -> profile.Profile:
    """Load the frozen MK0 reference profile."""
    return profile.load(REFERENCE_PROFILE_PATH)


def reference_design() -> DesignParameters:
    """Design parameters from the frozen MK0 reference profile."""
    return DesignParameters.from_profile(reference_profile())


def reference_spice_params() -> SpiceParams:
    """Netlist parameters from the frozen MK0 reference profile."""
    return SpiceParams.from_profile(reference_profile())
