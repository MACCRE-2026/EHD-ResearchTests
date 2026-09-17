"""Run records: the only thing that distinguishes a solve that happened from one that was asserted.

Every external solver in this project sits **outside ``pytest``**. Nothing in the test suite can
confirm a run occurred, so the honest default is that it did not, and a record is the only evidence.
*Principle 3, never report success over unperformed work*, applies with full force here: a
cross-check attributed to a solver nobody opened is a fabricated result **even when the number
happens to be right.**

Why the record is strict rather than best-effort
------------------------------------------------
``solved`` sits above ``analytical-cited`` on the basis ladder precisely because a numerical solve
resolves something a closed form cannot — ``k_geo`` for a wire-to-plane emitter being the case this
project needs most. That promotion is exactly why it must be gated. A ``solved`` label on an
unrecorded run launders an assumption into evidence, and every downstream band tightens on the
strength of it. *Principle 1, trust is a ceiling inherited from provenance.*

So ``RunRecord`` **cannot be constructed** without tool version, input hash and values read back.
An incomplete run does not become a weaker record; it is not a record at all. That is
*principle 2, an approximately-correct identifier is worse than an absent one* — a run record
missing its hash would sit in the datacenter looking like evidence.

What a record does not establish
--------------------------------
Recorded provenance says the run happened against a known input. It says nothing about whether the
run answered the question. FEMM solves Laplace with **no space charge**, so its peak wire-surface
field is the corona-onset field and not the loaded operating field. A SPICE result inherits its
component models, and the ``.model DHV`` parameters are placeholders. A CFD field inherits its mesh
and carries no information about its own discretisation error without demonstrated convergence.
Those caveats belong on the value, not on the record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..basis import Basis
from .base import ParsedResult

_SHA256_HEX_LENGTH = len(hashlib.sha256(b"").hexdigest())


class ProvenanceError(ValueError):
    """A run record was incomplete, so it is not a record."""


def sha256_of_file(path: Path) -> str:
    """SHA-256 of the exact bytes fed to the solver."""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class RunRecord:
    """One solver run, complete or not constructible.

    Frozen and append-only. A re-run is a **new** record naming the one it supersedes: two runs of
    the same solver on the same input that disagree is a finding worth keeping both halves of, and
    overwriting the first destroys the only evidence the disagreement existed.
    """

    tool: str
    tool_version: str
    """Captured from the tool itself, or transcribed from its own about box. Never the version
    somebody believed was installed."""

    input_path: str
    input_sha256: str
    values: dict[str, float]
    profile_id: str
    run_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    supersedes: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        missing: list[str] = []
        if not self.tool.strip():
            missing.append("tool")
        if not self.tool_version.strip():
            missing.append("tool_version")
        if not self.input_path.strip():
            missing.append("input_path")
        if len(self.input_sha256) != _SHA256_HEX_LENGTH or not all(
            c in "0123456789abcdef" for c in self.input_sha256.lower()
        ):
            missing.append("input_sha256")
        if not self.values:
            missing.append("values")
        if not self.profile_id.strip():
            missing.append("profile_id")
        if missing:
            raise ProvenanceError(
                f"cannot record a run missing {missing}. A value derived from a run without tool "
                f"version, input hash and values read back is not `solved`, and a partial record "
                f"in the datacenter would look like evidence. Record no run instead."
            )

    @property
    def basis(self) -> Basis:
        """``Basis.SOLVED``, unconditionally — and that is the point.

        There is no branch here because there is no way to hold an incomplete ``RunRecord``:
        ``__post_init__`` refuses to build one. The gate is at construction rather than at
        interpretation, so a caller cannot reach a ``solved`` label by ignoring a returned flag.
        Impossible by construction rather than prevented by vigilance.
        """
        return Basis.SOLVED

    def to_json(self) -> dict[str, object]:
        """Serialise for ``artifacts/05_Solver_Runs/``."""
        return {
            "tool": self.tool,
            "tool_version": self.tool_version,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "values": dict(self.values),
            "profile_id": self.profile_id,
            "run_utc": self.run_utc,
            "supersedes": self.supersedes,
            "note": self.note,
            "basis": self.basis.label,
        }


def record_from_parsed(
    *,
    tool: str,
    parsed: ParsedResult,
    input_path: Path,
    profile_id: str,
    supersedes: str | None = None,
    note: str | None = None,
) -> RunRecord:
    """Build a record from a parsed result file, checking the hash against the input on disk.

    The check is the reason this function exists rather than callers assembling a ``RunRecord``
    themselves. A transcribed hash that does not match the artifact now present means the values
    describe an input that has since changed — and that is a *different* failure from a missing
    hash, so it gets its own message.
    """
    actual = sha256_of_file(input_path)
    if actual.lower() != parsed.input_sha256.lower():
        raise ProvenanceError(
            f"the result file was transcribed against input hash {parsed.input_sha256} but "
            f"{input_path.name} currently hashes to {actual}. Either the input was regenerated "
            f"after the run, or the values came from a different file. Re-run rather than "
            f"reconciling: the numbers describe a geometry or circuit that no longer exists."
        )
    return RunRecord(
        tool=tool,
        tool_version=parsed.tool_version,
        input_path=str(input_path),
        input_sha256=parsed.input_sha256.lower(),
        values=dict(parsed.values),
        profile_id=profile_id,
        supersedes=supersedes,
        note=note,
    )


def write_run_record(record: RunRecord, destination: Path) -> Path:
    """Write a record, refusing to overwrite.

    Records are append-only. Refusing overwrite is the enforcement; a docstring saying "do not
    overwrite" is not.
    """
    if destination.exists():
        raise ProvenanceError(
            f"{destination} already exists. Run records are append-only — a re-run is a new record "
            f"naming the one it supersedes, not an edit of the old one."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination
