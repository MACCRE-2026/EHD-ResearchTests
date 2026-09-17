"""The adapter layer: one uniform shape over every external tool the suite orchestrates.

``ADAPTERS`` is the registry, and it is deliberately the *only* place an adapter is announced. Two
things read it — ``ehdsuite doctor``, which prints the tool matrix, and the attribution test, which
fails when a registered tool is missing from ``ATTRIBUTIONS.md``. A registry nobody reads would be a
list that drifts from the adapters it names.

**Registered, and reporting absent, is the correct state today.** No FEMM, LTspice, QSPICE, Gmsh,
Elmer, OpenFOAM or ParaView run has occurred in this project, and none of the three tools below has
been detected on this machine. ``doctor`` says so per tool rather than degrading quietly, because a
capability whose tool is absent reports as absent, not as degraded-but-fine.

The four tools with no adapter yet — Gmsh, Elmer, OpenFOAM, ParaView — are detectable
(``detect.KNOWN_TOOLS``) and unregistered here, which is honest: detection is implemented for them
and the other four obligations are not. Plan Tasks 14 and 15 add them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..detect import ToolStatus
from .base import (
    RESULT_FILE_MAGIC,
    Adapter,
    AdapterError,
    GenerateError,
    ParsedResult,
    ParseError,
    RunOutcome,
    RunResult,
    parse_result_file,
)
from .provenance import (
    ProvenanceError,
    RunRecord,
    record_from_parsed,
    sha256_of_file,
    write_run_record,
)
from .solvers import FemmAdapter, LtspiceAdapter, QspiceAdapter
from .toolconfig import (
    TOOL_CONFIG_FILENAME,
    ToolConfigError,
    config_template,
    configured_path_for,
    load_tool_paths,
    tool_config_path,
)

__all__ = (
    "ADAPTERS",
    "RESULT_FILE_MAGIC",
    "TOOL_CONFIG_FILENAME",
    "Adapter",
    "AdapterError",
    "DoctorRow",
    "FemmAdapter",
    "GenerateError",
    "LtspiceAdapter",
    "ParseError",
    "ParsedResult",
    "ProvenanceError",
    "QspiceAdapter",
    "RunOutcome",
    "RunRecord",
    "RunResult",
    "ToolConfigError",
    "adapter_for",
    "config_template",
    "configured_path_for",
    "doctor_rows",
    "load_tool_paths",
    "parse_result_file",
    "record_from_parsed",
    "sha256_of_file",
    "tool_config_path",
    "write_run_record",
)

ADAPTERS: tuple[Adapter, ...] = (
    FemmAdapter(),
    LtspiceAdapter(),
    QspiceAdapter(),
)


def adapter_for(name: str) -> Adapter:
    """The adapter registered under ``name``.

    Raises ``KeyError`` naming what is registered, rather than returning ``None``. A caller that
    receives ``None`` and carries on ends up treating "no adapter" as "nothing to do".
    """
    for adapter in ADAPTERS:
        if adapter.name == name:
            return adapter
    registered = ", ".join(a.name for a in ADAPTERS)
    raise KeyError(f"no adapter named {name!r}; registered: {registered}")


@dataclass(frozen=True)
class DoctorRow:
    """One line of the tool matrix.

    A record rather than a formatted string, so the CLI owns presentation and a test can assert the
    content. The GUI will render the same rows — *the GUI holds no architecture of its own.*
    """

    tool: str
    status: str
    path: str
    version: str
    routes_tried: tuple[str, ...]
    run_mode: str
    capability: str
    note: str


def doctor_rows() -> tuple[DoctorRow, ...]:
    """Probe every registered adapter and describe what the suite can and cannot do.

    Each adapter is probed independently and a raising adapter becomes a row saying so, rather than
    aborting the matrix. A ``doctor`` that dies on the first broken adapter reports nothing about the
    other six, which is the least useful moment to stop talking.
    """
    rows: list[DoctorRow] = []
    for adapter in ADAPTERS:
        try:
            probe = adapter.detect()
        except Exception as exc:  # noqa: BLE001 - a broken adapter is a row, not a crash
            rows.append(
                DoctorRow(
                    tool=adapter.name,
                    status="adapter-error",
                    path="",
                    version="",
                    routes_tried=(),
                    run_mode="unknown",
                    capability=adapter.capability,
                    note=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        outcome = adapter.run(())
        rows.append(
            DoctorRow(
                tool=adapter.name,
                status=probe.status.value,
                path=str(probe.path) if probe.path else "",
                version=probe.version or "",
                routes_tried=probe.routes_tried,
                run_mode=outcome.outcome.value,
                capability=adapter.capability,
                note=probe.note or "",
            )
        )
    return tuple(rows)


def unresolved_capabilities(rows: tuple[DoctorRow, ...] | None = None) -> tuple[str, ...]:
    """Names of registered tools that did not resolve.

    Exposed so a caller can act on absence without re-deriving it from ``doctor_rows``, and so the
    fact that this is currently *all three* is a value rather than a paragraph.

    Reads ``DoctorRow`` rather than probing again, for two reasons that turned out to be one. It is
    *principle 4, two representations of one thing will drift* — two derivations of "which tools are
    missing" can disagree. And the drift was immediate: an earlier version re-probed each adapter
    here, so a raising adapter escaped the containment ``doctor_rows`` provides and ``doctor``
    crashed inside the very summary that was reporting the breakage. The Gate caught it, not review.

    An ``adapter-error`` row counts as unresolved: an adapter that cannot say whether its tool is
    present has not established that it is.
    """
    matrix = doctor_rows() if rows is None else rows
    return tuple(row.tool for row in matrix if row.status != ToolStatus.PRESENT.value)
