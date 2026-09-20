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
from typing import NamedTuple

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


#: The tier file naming convention. Every file in ``artifacts/05_Solver_Runs/`` must use one of
#: these prefixes, or it is a finding.
TIER_FILE_PREFIXES: frozenset[str] = frozenset(("RECORD_", "PENDING_", "INCOMPLETE_"))


class TierFinding(NamedTuple):
    """One defect in a solver-run tier."""

    kind: str
    """Machine-readable category: ``orphaned-pending``, ``undeclared-prefix``, ``incomplete-record``,
    ``unreadable``, etc."""

    detail: str
    """Human-readable description, naming files involved."""


def validate_tier(tier: Path) -> list[TierFinding]:
    """Scan a solver-run tier and report findings.

    An empty result means the tier is clean. Every finding carries a machine-readable ``kind`` and
    a ``detail`` naming the files involved.

    Findings reported:
    - ``orphaned-pending``: A PENDING exists for which a completed RECORD already exists (matched
      on tool and input_path, not on slug).
    - ``undeclared-prefix``: A file uses a prefix not in TIER_FILE_PREFIXES.
    - ``incomplete-record``: A RECORD_*.json lacks tool_version, input_sha256, or values, or has
      any None values in the values dict.
    - ``unreadable``: A RECORD_*.json could not be parsed as JSON.
    """
    findings: list[TierFinding] = []

    if not tier.is_dir():
        return findings

    records: dict[tuple[str, str], Path] = {}  # (tool, input_path) -> RECORD path
    pendings: list[tuple[Path, str, str]] = []  # [(path, tool, input_path), ...]

    for item in sorted(tier.iterdir()):
        if not item.is_file():
            continue

        name = item.name
        matched_prefix = False

        # Check if this file matches any declared prefix
        for prefix in TIER_FILE_PREFIXES:
            if name.startswith(prefix):
                matched_prefix = True

                if prefix == "RECORD_":
                    # Parse the RECORD_*.json
                    try:
                        payload = json.loads(item.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        findings.append(
                            TierFinding(
                                kind="unreadable",
                                detail=f"{name}: could not be parsed as JSON",
                            )
                        )
                        break

                    # Check required fields
                    tool = (
                        payload.get("tool", "").strip()
                        if isinstance(payload.get("tool"), str)
                        else ""
                    )
                    input_path_str = (
                        payload.get("input_path", "").strip()
                        if isinstance(payload.get("input_path"), str)
                        else ""
                    )
                    tool_version = (
                        payload.get("tool_version", "").strip()
                        if isinstance(payload.get("tool_version"), str)
                        else ""
                    )
                    input_sha256 = (
                        payload.get("input_sha256", "").strip()
                        if isinstance(payload.get("input_sha256"), str)
                        else ""
                    )
                    values = payload.get("values", {})

                    # Check for incomplete record: missing fields or None values
                    has_none_values = isinstance(values, dict) and any(
                        v is None for v in values.values()
                    )

                    if not tool_version or not input_sha256 or not values or has_none_values:
                        findings.append(
                            TierFinding(
                                kind="incomplete-record",
                                detail=f"{name}: missing or empty tool_version, input_sha256, or values",
                            )
                        )
                    else:
                        records[(tool, input_path_str)] = item

                elif prefix == "PENDING_":
                    # Collect PENDING info for orphan detection
                    try:
                        text = item.read_text(encoding="utf-8")
                        lines = {}
                        for line in text.split("\n"):
                            if "=" in line:
                                key, val = line.split("=", 1)
                                lines[key.strip()] = val.strip()
                        tool = lines.get("tool", "").strip()
                        input_path_str = lines.get("input_path", "").strip()
                        if tool and input_path_str:
                            pendings.append((item, tool, input_path_str))
                    except (OSError, ValueError):
                        pass

                break

        if not matched_prefix:
            findings.append(
                TierFinding(
                    kind="undeclared-prefix",
                    detail=f"{name}: uses a prefix not in TIER_FILE_PREFIXES",
                )
            )

    # Check for orphaned pendings (must happen after all records are cataloged)
    for pending_path, tool, input_path_str in pendings:
        if (tool, input_path_str) in records:
            findings.append(
                TierFinding(
                    kind="orphaned-pending",
                    detail=f"{pending_path.name} is orphaned beside {records[(tool, input_path_str)].name}",
                )
            )

    return findings
