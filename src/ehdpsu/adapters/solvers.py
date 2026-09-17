"""The adapters that exist today: FEMM, LTspice, QSPICE.

Each wraps a generator that already existed and was already tested. The adapter adds the contract,
not the physics — ``ehdpsu.femm`` and ``ehdpsu.spice`` are unchanged, and a wrapper that recomputed
anything would be a second representation of the same artifact.

All three report ``run`` as **manual**, and that is a statement about this project's state rather
than about the tools. QSPICE genuinely accepts a netlist on the command line, and LTspice has a
batch switch; neither is claimed here, because **no installation of either has been inspected** and
an invocation nobody has performed is not a capability. Plan Task 13 installs them, and the day one
of these returns ``COMPLETED`` will be a diff.

What each tool answers, and what it does not
--------------------------------------------
**FEMM** solves Laplace with no space charge. Its peak wire-surface field is the **corona-onset**
field, comparable against Peek — it is *not* the loaded operating field, because once current flows
ion space charge lowers the near-wire field. Its cell capacitance is what the SPICE ladder needs.

**LTspice and QSPICE** inherit their component models. The generated netlist's ``.model DHV``
parameters are placeholders, so any loss or efficiency figure read out of it is uncalibrated however
carefully the simulation ran.
"""

from __future__ import annotations

from pathlib import Path

from .. import femm as femm_module
from .. import spice as spice_module
from ..detect import KNOWN_TOOLS, ToolSpec, ToolStatus
from ..physics import default_design
from ..spice import default_spice_params
from .base import Adapter, GenerateError, RunOutcome, RunResult

_SPECS_BY_NAME = {spec.name: spec for spec in KNOWN_TOOLS}


def _spec(name: str) -> ToolSpec:
    """Look the spec up rather than restating it.

    *Principle 4, two representations of one thing will drift.* An adapter carrying its own copy of
    an executable list would eventually disagree with ``detect.KNOWN_TOOLS`` about what to look for,
    and the vendor-cited provenance register only covers the copy in ``detect``.
    """
    try:
        return _SPECS_BY_NAME[name]
    except KeyError as exc:  # pragma: no cover - guarded by test_adapters
        raise GenerateError(
            f"no ToolSpec named {name!r} in detect.KNOWN_TOOLS; the adapter and the detection "
            f"table have diverged"
        ) from exc


def _manual(tool: str, inputs: tuple[Path, ...], steps: str) -> RunResult:
    """A uniform manual-run outcome, so no adapter phrases 'you have to do this' differently."""
    return RunResult(
        outcome=RunOutcome.MANUAL_REQUIRED,
        detail=(
            f"{tool} is GUI-driven and no headless invocation has been verified on this machine, "
            f"so nothing was run. {steps} Transcribe the values into a result file beginning "
            f"`# ehd-run-result v1` and carrying tool_version and input_sha256, then parse it."
        ),
        inputs=inputs,
    )


class FemmAdapter(Adapter):
    """FEMM 4.2 — 2D/axisymmetric electrostatics."""

    @property
    def name(self) -> str:
        return "femm"

    @property
    def attribution(self) -> str:
        return "FEMM"

    @property
    def capability(self) -> str:
        return (
            "solved peak wire-surface field and cell capacitance; the route that would replace "
            "k_geo's ~10x placeholder band with a calibrated coefficient"
        )

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("femm")

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("E_peak_surface_V_per_m", "C_cell_F")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        written = femm_module.write_artifacts(
            default_design(), output_dir=output_dir, write_notes=True
        )
        return tuple(written)

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"FEMM detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. The solved-field capability is absent; nothing "
                    f"substitutes for it, and the analytical Peek figure is not a stand-in."
                ),
                inputs=inputs,
            )
        return _manual(
            "FEMM",
            inputs,
            "Open the .lua script in FEMM's Lua console, run it to solve and load the solution, "
            "then read the peak wire-surface |E| and the cell capacitance as the script tail "
            "describes.",
        )


class _SpiceAdapter(Adapter):
    """Shared behaviour for the two SPICE engines, which differ only in input format."""

    @property
    def capability(self) -> str:
        return (
            "simulated Cockcroft-Walton droop and ripple under the EHD load, against the "
            "closed-form estimates; the component models remain placeholders"
        )

    @property
    def expected_values(self) -> tuple[str, ...]:
        return ("V_out_loaded_V", "V_ripple_pp_V", "I_load_A")

    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        probe = self.detect()
        if probe.status is not ToolStatus.PRESENT:
            return RunResult(
                outcome=RunOutcome.TOOL_UNAVAILABLE,
                detail=(
                    f"{self.attribution} detection returned {probe.status.value} after trying "
                    f"{list(probe.routes_tried)}. No circuit simulation is available, and the "
                    f"closed-form droop and ripple figures are not a substitute for one."
                ),
                inputs=inputs,
            )
        return _manual(
            self.attribution,
            inputs,
            "Open the generated file, run a transient long enough for the ladder to settle, then "
            "read the loaded output voltage, the peak-to-peak ripple and the load current.",
        )


class LtspiceAdapter(_SpiceAdapter):
    """LTspice — schematic form of the LLC + Cockcroft-Walton chain."""

    @property
    def name(self) -> str:
        return "ltspice"

    @property
    def attribution(self) -> str:
        return "LTspice"

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("ltspice")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "ehd_llc_cw.asc"
        path.write_text(
            spice_module.build_asc(default_design(), default_spice_params()), encoding="utf-8"
        )
        return (path,)


class QspiceAdapter(_SpiceAdapter):
    """QSPICE — netlist form of the same chain."""

    @property
    def name(self) -> str:
        return "qspice"

    @property
    def attribution(self) -> str:
        return "QSPICE"

    @property
    def tool_spec(self) -> ToolSpec:
        return _spec("qspice")

    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "ehd_llc_cw.cir"
        path.write_text(
            spice_module.build_netlist(default_design(), default_spice_params()), encoding="utf-8"
        )
        return (path,)
