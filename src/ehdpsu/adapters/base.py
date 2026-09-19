"""The shape every external-tool adapter wears.

Five obligations, and one that is not optional. ``.kiro/steering/adapter-contract.md`` states the
contract; this module makes it a type that a test can check rather than a convention a reviewer has
to remember.

Two states are first-class here, and that is the whole point of the layer
--------------------------------------------------------------------------
The plan maps every solver route without committing to one, which only works if **"not installed"**
and **"not chosen"** are things an adapter can say. A missing tool degrades a capability *visibly*:
it never silently substitutes a closed-form estimate, a cached result, or another tool's output. An
unchosen route stays unchosen — no solver becomes the default merely by being the one that happens
to be installed.

The parse hazard, named
-----------------------
The most dangerous input any adapter will ever receive is **a tool that ran, exited zero, and
returned nothing usable** — an empty list, a bare ``[]``, a truncated file. Falling through to a
default reads as success, which is *principle 3, never report success over unperformed work*. So
``parse`` raises on an unrecognised shape and can never return an empty result.

Every solver here is a GUI or external tool, so a human transcribes what they read. That
transcription is the adapter's parse input, and it must carry the tool version and the input hash —
otherwise the values describe a run nobody can identify. See ``provenance.py``.
"""

from __future__ import annotations

import abc
import enum
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from ..detect import ToolProbe, ToolSpec, detect_tool
from .toolconfig import configured_path_for

# Derived rather than typed, so the literal is neither a magic number nor an exemption.
_SHA256_HEX_LENGTH = len(hashlib.sha256(b"").hexdigest())

RESULT_FILE_MAGIC = "# ehd-run-result v1"
"""First non-blank line of a transcribed result file.

A magic line rather than a guessed shape. Output formats for these tools are largely unpublished, so
the adapter cannot recognise "a FEMM result" in the wild; what it can recognise is a file somebody
wrote *for this suite*, in a stated format. Anything else is unusable rather than best-effort."""


class AdapterError(RuntimeError):
    """Base for adapter failures. Never raised directly."""


class ParseError(AdapterError):
    """A result was unreadable, incomplete, or in an unrecognised shape.

    Deliberately an exception rather than an empty return. An adapter that returns ``{}`` for an
    unparseable file hands its caller a result that looks like a successful read of nothing.
    """


class GenerateError(AdapterError):
    """An input artifact could not be produced deterministically from the profile."""


class RunOutcome(enum.Enum):
    """How an invocation attempt ended.

    Five states, because two of them are the ones that keep the suite honest about what it has
    actually done.
    """

    COMPLETED = "completed"
    """The tool was invoked here and exited successfully. No adapter returns this yet: no FEMM,
    SPICE, Elmer, Gmsh, OpenFOAM or ParaView run has occurred in this project."""

    MANUAL_REQUIRED = "manual-required"
    """The tool is present but must be driven by a human. The adapter has generated the input and
    says what to do; it has *not* produced a result. **This is not a partial success.**"""

    TOOL_UNAVAILABLE = "tool-unavailable"
    """Detection did not resolve the tool, so nothing was attempted. The capability is absent, not
    degraded — and specifically not silently replaced by a closed-form estimate."""

    NOT_CHOSEN = "not-chosen"
    """This route exists and was deliberately not selected. Reserved for the competing CFD routes
    of plan Task 14 — in-process axisymmetric Python, Elmer, OpenFOAM — where mapping every route
    without committing to one is the explicit intent. No adapter returns it yet, and a test asserts
    that, so the day one does is visible in a diff."""

    PRESENT_UNVERIFIED = "present-unverified"
    """The tool resolved during detection, but no headless invocation of it has been verified on this
    machine. Returned by adapters for tools that are GUI-driven (manual_only=True) and whose runs
    cannot therefore be automated. Distinct from TOOL_UNAVAILABLE: the tool is genuinely present, just
    not yet verified to run here."""


@dataclass(frozen=True)
class RunResult:
    """What an invocation attempt produced, which is usually an instruction rather than data."""

    outcome: RunOutcome
    detail: str
    """Why, in a sentence the operator can act on. Required for every outcome."""

    inputs: tuple[Path, ...] = ()
    """Artifacts the operator is being asked to open, when the outcome is ``MANUAL_REQUIRED``."""

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise AdapterError(
                f"{self.outcome.value} with no detail. An outcome a human cannot act on is a "
                f"status nobody will read."
            )


@dataclass(frozen=True)
class ParsedResult:
    """Values transcribed from a solver run, with the two facts that identify the run.

    ``tool_version`` and ``input_sha256`` live here rather than in ``provenance`` because they must
    come out of the **same file** as the numbers. A version supplied separately is a version
    somebody remembered, and an input hash supplied separately cannot prove the numbers came from
    that input.
    """

    tool_version: str
    input_sha256: str
    values: dict[str, float]


class Adapter(abc.ABC):
    """One external tool, wearing the five obligations.

    Subclasses supply reference data and the two tool-specific behaviours. Detection and version
    capture are inherited, so no adapter can get the ``TOOL_ABSENT`` / ``TOOL_UNRESOLVED``
    distinction wrong on its own.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short identifier, matching the ``ToolSpec`` name."""

    @property
    @abc.abstractmethod
    def attribution(self) -> str:
        """The string that must appear in ``ATTRIBUTIONS.md``.

        Naming what the suite stands on costs nothing and is the transparency the public release
        rests on. A registered tool absent from that file fails a test.
        """

    @property
    @abc.abstractmethod
    def capability(self) -> str:
        """What the suite loses when this tool is absent. Shown by ``doctor``."""

    @property
    @abc.abstractmethod
    def tool_spec(self) -> ToolSpec:
        """The detection spec, from ``ehdpsu.detect.KNOWN_TOOLS``."""

    @property
    @abc.abstractmethod
    def expected_values(self) -> tuple[str, ...]:
        """Value names a result file must carry, units in the identifiers.

        Declared, so ``parse`` accepts an explicit shape and refuses everything else instead of
        returning whatever it happened to find.
        """

    # -- obligation 1: detect ------------------------------------------------

    def detect(self, configured_path: Path | None = None) -> ToolProbe:
        """Resolve through every route before concluding absence. Never overridden.

        When no path is passed, the machine-local tool configuration is consulted. That is what makes
        route 1 reachable at all: before ``toolconfig`` existed, ``configured-path`` was recorded as
        attempted on every single probe and could never resolve anything, because nothing in the suite
        could supply it. Two working installs were reported ``tool-absent`` as a result.
        """
        if configured_path is None:
            configured_path = configured_path_for(self.name)
        return detect_tool(self.tool_spec, configured_path=configured_path)

    # -- obligation 2: version -----------------------------------------------

    def version(self, configured_path: Path | None = None) -> str | None:
        """The tool's own reported version string, verbatim, or ``None``.

        ``None`` is a real answer here and not a failure: four of these tools are GUI-driven and
        cannot be asked. The operator supplies the version in the result file instead, which is why
        ``ParsedResult`` requires it.
        """
        return self.detect(configured_path).version

    # -- obligation 3: generate ----------------------------------------------

    @abc.abstractmethod
    def generate(self, output_dir: Path) -> tuple[Path, ...]:
        """Write the input artifact(s) deterministically from the profile.

        Deterministic is load-bearing, not aspirational: ``solver_inputs/`` is tracked and diffed by
        a test, so a timestamp or a dict ordering in generated text would produce failures
        indistinguishable from a real change.
        """

    # -- obligation 4: run ---------------------------------------------------

    @abc.abstractmethod
    def run(self, inputs: tuple[Path, ...]) -> RunResult:
        """Invoke the tool, or state clearly that invocation is manual."""

    # -- obligation 5: parse -------------------------------------------------

    def parse(self, text: str) -> ParsedResult:
        """Read a transcribed result back, failing loudly on anything unrecognised.

        Not overridden by any adapter: the format is the suite's, not the tool's, so one parser
        serves all of them. *Principle 4, two representations of one thing will drift* — six
        adapters with six parsers is six chances to disagree about what a missing version means.
        """
        return parse_result_file(text, self.expected_values)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


def parse_result_file(text: str, expected_values: tuple[str, ...]) -> ParsedResult:
    """Parse a transcribed solver result, or raise ``ParseError``.

    The format, deliberately small enough to hand-write at a bench::

        # ehd-run-result v1
        tool_version = FEMM 4.2 (25Jul2022)
        input_sha256 = 3b1f...  (64 hex characters)
        E_peak_V_per_m = 1.83e7
        C_cell_F = 4.1e-12

    Every failure below is its own message, because "could not parse" tells the operator nothing
    about what to fix.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    body = [ln for ln in lines if ln and not (ln.startswith("#") and ln != RESULT_FILE_MAGIC)]

    if not body or body[0] != RESULT_FILE_MAGIC:
        first = body[0] if body else "<empty>"
        raise ParseError(
            f"result file does not begin with {RESULT_FILE_MAGIC!r} (found {first!r}). A file "
            f"without the magic line is not in this suite's format, and guessing at its shape is "
            f"how an unrecognised output becomes an apparent success."
        )

    fields: dict[str, str] = {}
    for lineno, line in enumerate(body[1:], start=2):
        if "=" not in line:
            raise ParseError(f"line {lineno} is not a `name = value` assignment: {line!r}")
        key, _, raw = line.partition("=")
        key, raw = key.strip(), raw.strip()
        if key in fields:
            raise ParseError(
                f"line {lineno} repeats {key!r}. Two values for one name is a transcription "
                f"error, and silently taking the last one would hide it."
            )
        fields[key] = raw

    tool_version = fields.pop("tool_version", "").strip()
    if not tool_version:
        raise ParseError(
            "no tool_version. Values that cannot be tied to a specific build of a specific tool "
            "describe a run nobody can identify or repeat."
        )

    input_sha256 = fields.pop("input_sha256", "").strip().lower()
    if len(input_sha256) != _SHA256_HEX_LENGTH or not all(
        c in "0123456789abcdef" for c in input_sha256
    ):
        raise ParseError(
            f"input_sha256 is not a {_SHA256_HEX_LENGTH}-character hex digest: {input_sha256!r}. "
            f"Without it, a run against an input that has since changed describes a geometry or "
            f"circuit that no longer exists."
        )

    unknown = sorted(set(fields) - set(expected_values))
    if unknown:
        raise ParseError(
            f"unrecognised value name(s) {unknown}; this adapter expects {list(expected_values)}. "
            f"Accepting an unknown name would let a mistyped identifier arrive as data."
        )

    missing = [name for name in expected_values if name not in fields]
    if missing:
        raise ParseError(
            f"result file is missing {missing}. A run that reported some of what was asked for is "
            f"its own state, not a success with gaps."
        )

    values: dict[str, float] = {}
    for name in expected_values:
        raw = fields[name]
        try:
            number = float(raw)
        except ValueError as exc:
            raise ParseError(f"{name} is not a number: {raw!r}") from exc
        if not math.isfinite(number):
            raise ParseError(
                f"{name} is not finite: {raw!r}. A NaN or an infinity is a solver that failed, "
                f"not a value it produced."
            )
        values[name] = number

    return ParsedResult(tool_version=tool_version, input_sha256=input_sha256, values=values)
