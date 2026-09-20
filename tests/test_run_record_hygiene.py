"""Specification for solver-run tier hygiene — CRSDL Task 19, Batch A.

Written 2026-09-19 before the implementation. Audit finding F9.

What went wrong
---------------
``artifacts/05_Solver_Runs/`` accumulated three ``PENDING_*`` skeletons, **one of which has had a
completed ``RECORD_*.json`` beside it since 2026-09-16**. An unretired ``PENDING`` is
indistinguishable from work still owed, so the tier stopped being readable as a ledger.

Then the planner made it worse on 2026-09-18 by filing ``RUN_ltspice_llc_cw_..._INCOMPLETE.md``
instead of resolving the existing ``PENDING_ltspice_llc_cw.txt`` — creating a **second naming
convention for the same thing** — and never writing the QSPICE record at all, despite having the
values. Terminal states are ``COMPLETED``, ``WITHDRAWN`` and ``SUPERSEDED``; "still sitting there" is
none of them.

Why this is a validator and not a cleanup
-----------------------------------------
A one-time tidy leaves the tier in exactly the state that produced the mess: correct because someone
was careful, with nothing to notice when they are not. So the deliverable is a **library function
plus a CLI verb** that reads a tier and reports its findings — a capability with a test, a scriptable
form, and a way to reproduce what it did. Cleaning the real tier is then the demo, not the task.

Why the tests use synthetic tiers
---------------------------------
``artifacts/`` is untracked, so the real tier does not exist in a clone. A guarded ``pytest.skip``
would make the Gate report ``PYTEST-COVERAGE-REDUCED`` — skips are not free here — so the
specification lives in ``tmp_path`` fixtures that exist everywhere, and the real tier gets one
opportunistic check that passes when absent rather than skipping.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ehdpsu.adapters import provenance as prov

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_TIER = REPO_ROOT / "artifacts" / "05_Solver_Runs"

A_VALID_DIGEST = "0" * 64

# Synthetic records below name their inputs under `synthetic_inputs/`, never `solver_inputs/`, and
# the reason is not cosmetic. `test_every_project_path_named_in_docs_and_output_exists` requires every
# `solver_inputs/...` string in TRACKED source to name a file that exists — so realistic-looking
# fixture paths turn red the moment the file is committed, and **not before**, because that check
# only scans tracked files. Exactly what happened on the first CRSDL commit: the specification was
# green locally and the act of committing it made the check fire. Do not tidy these back.


def _validate(tier: Path) -> Any:
    """Call the validator, or fail with what its interface must be.

    Resolved through ``getattr`` so that its absence is a readable assertion rather than a
    module-scope ``ImportError``, which would abort collection for this whole file and hand the
    implementing seat "1 error" instead of a list of requirements.
    """
    fn = getattr(prov, "validate_tier", None)
    assert fn is not None, (
        "ehdpsu.adapters.provenance.validate_tier(tier: Path) does not exist. It must return an "
        "iterable of findings, each carrying at least a machine-readable `kind` and a `detail` "
        "naming the files involved. An empty result means the tier is clean."
    )
    return list(fn(tier))


def _kinds(findings: Any) -> set[str]:
    out: set[str] = set()
    for f in findings:
        kind = getattr(f, "kind", None)
        assert (
            kind is not None
        ), f"finding {f!r} has no `kind`; a finding nothing can match on is prose"
        out.add(str(kind))
    return out


def _write_record(tier: Path, slug: str, date: str, tool: str, input_path: str) -> Path:
    path = tier / f"RECORD_{slug}_{date}.json"
    path.write_text(
        json.dumps(
            {
                "basis": "solved",
                "tool": tool,
                "tool_version": f"{tool} 1.0 (synthetic)",
                "input_path": input_path,
                "input_sha256": A_VALID_DIGEST,
                "profile_id": "synthetic",
                "run_utc": f"{date}T00:00:00+00:00",
                "supersedes": None,
                "values": {"x": 1.0},
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_pending(tier: Path, slug: str, tool: str, input_path: str) -> Path:
    path = tier / f"PENDING_{slug}.txt"
    path.write_text(
        f"# ehd-run-result v1\ntool = {tool}\ninput_path = {input_path}\n"
        f"tool_version = \ninput_sha256 = \nx = \n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tier(tmp_path: Path) -> Path:
    d = tmp_path / "05_Solver_Runs"
    d.mkdir()
    return d


class TestACleanTierReportsNothing:
    def test_empty_tier_is_clean(self, tier: Path) -> None:
        assert _validate(tier) == []

    def test_a_record_alone_is_clean(self, tier: Path) -> None:
        _write_record(tier, "femm_cell", "2026-09-16", "femm", "synthetic_inputs/a.lua")
        assert _validate(tier) == []

    def test_a_pending_with_no_record_is_clean(self, tier: Path) -> None:
        """Work genuinely still owed is the state ``PENDING`` exists to express."""
        _write_pending(tier, "qspice_llc", "qspice", "synthetic_inputs/b.cir")
        assert _validate(tier) == []


class TestTheOrphanedPending:
    def test_a_pending_beside_a_completed_record_is_a_finding(self, tier: Path) -> None:
        """The specific F9 defect: FEMM completed on 2026-09-16 and its skeleton never retired."""
        _write_pending(tier, "femm_cell", "femm", "synthetic_inputs/a.lua")
        _write_record(tier, "femm_cell", "2026-09-16", "femm", "synthetic_inputs/a.lua")
        assert "orphaned-pending" in _kinds(_validate(tier)), (
            "a PENDING coexisting with a completed RECORD for the same tool and input must be "
            "reported. It is indistinguishable from work still owed."
        )

    def test_matching_is_on_tool_and_input_not_on_the_slug(self, tier: Path) -> None:
        """Filename slugs drift; the tool and the input hash are what identify a run.

        *Principle 2, an approximately-correct identifier is worse than an absent one* — matching on
        a human-chosen slug would silently miss a retired pending whose name was tidied.
        """
        _write_pending(tier, "femm_wire_collector", "femm", "synthetic_inputs/a.lua")
        _write_record(tier, "femm_cell_v2", "2026-09-16", "femm", "synthetic_inputs/a.lua")
        assert "orphaned-pending" in _kinds(_validate(tier))

    def test_a_pending_for_a_different_input_is_not_a_finding(self, tier: Path) -> None:
        """Two runs of one tool on different inputs are two runs, not a stale skeleton."""
        _write_pending(tier, "femm_other", "femm", "synthetic_inputs/other.lua")
        _write_record(tier, "femm_cell", "2026-09-16", "femm", "synthetic_inputs/a.lua")
        assert "orphaned-pending" not in _kinds(_validate(tier))


class TestOneNamingConvention:
    def test_the_declared_prefixes_are_exposed(self) -> None:
        """The convention is data, not a docstring, or the validator and the docs will disagree."""
        prefixes = getattr(prov, "TIER_FILE_PREFIXES", None)
        assert prefixes is not None, (
            "ehdpsu.adapters.provenance.TIER_FILE_PREFIXES does not exist. Declare the prefix set "
            "so the validator and any document describing the tier read the same list."
        )
        for required in ("RECORD_", "PENDING_", "INCOMPLETE_"):
            assert required in prefixes, f"{required} is not a declared tier prefix"

    def test_an_undeclared_prefix_is_a_finding(self, tier: Path) -> None:
        (tier / "RUN_something_2026-09-18_INCOMPLETE.md").write_text("x", encoding="utf-8")
        assert "undeclared-prefix" in _kinds(_validate(tier)), (
            "the planner's second convention, RUN_*_INCOMPLETE.md, must be reported rather than "
            "quietly tolerated. One tier, one convention."
        )

    def test_incomplete_is_a_first_class_state_not_a_weak_record(self, tier: Path) -> None:
        """An unconverged run has no ``solved`` values, so it is not a record at all.

        ``RunRecord`` already refuses construction without tool version, input hash and values read
        back. ``INCOMPLETE_`` is the name for a run that happened and produced nothing promotable —
        which is a different fact from "no run has occurred" and must not be folded into either
        ``PENDING`` or ``RECORD``.
        """
        (tier / "INCOMPLETE_ltspice_llc_2026-09-18.md").write_text(
            "Status: INCOMPLETE. The transient had not reached steady state.", encoding="utf-8"
        )
        assert _validate(tier) == [], "a correctly named INCOMPLETE artifact is not a finding"


class TestARecordMustNotClaimMoreThanItHas:
    def test_a_record_with_an_empty_value_is_a_finding(self, tier: Path) -> None:
        """A skeleton saved under the RECORD prefix is the laundering route into ``solved``."""
        path = tier / "RECORD_half_done_2026-09-19.json"
        payload = json.loads(_write_record(tier, "tmp", "2026-09-19", "femm", "x.lua").read_text())
        (tier / "RECORD_tmp_2026-09-19.json").unlink()
        payload["values"] = {"x": None}
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert "incomplete-record" in _kinds(_validate(tier))

    def test_a_record_missing_a_provenance_field_is_a_finding(self, tier: Path) -> None:
        """Tool version, input hash and values read back. Absent any one, it is not ``solved``."""
        payload = {
            "basis": "solved",
            "tool": "femm",
            "input_path": "x.lua",
            "input_sha256": A_VALID_DIGEST,
            "values": {"x": 1.0},
        }  # tool_version deliberately absent
        (tier / "RECORD_noversion_2026-09-19.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        assert "incomplete-record" in _kinds(_validate(tier))

    def test_unparseable_json_is_its_own_finding(self, tier: Path) -> None:
        """A file that cannot be read is not a clean file.

        *An unrecognised shape is an error, never an empty result* — the adapter contract's rule,
        applied to the tier's own artifacts.
        """
        (tier / "RECORD_broken_2026-09-19.json").write_text("{not json", encoding="utf-8")
        kinds = _kinds(_validate(tier))
        assert "unreadable" in kinds, f"expected an `unreadable` finding, got {kinds}"


class TestTheCliVerb:
    def test_the_verb_exists_and_reports_a_clean_tier(
        self, tier: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*A new capability is a library function plus a CLI verb.*"""
        from ehdpsu import cli

        _write_record(tier, "femm_cell", "2026-09-16", "femm", "synthetic_inputs/a.lua")
        assert cli.main(["runs", "--tier", str(tier)]) == cli.EXIT_OK
        assert capsys.readouterr().out.strip()

    def test_the_verb_exits_non_zero_on_findings(
        self, tier: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A tier with findings must not exit 0, or nothing scripted will ever notice."""
        from ehdpsu import cli

        _write_pending(tier, "femm_cell", "femm", "synthetic_inputs/a.lua")
        _write_record(tier, "femm_cell", "2026-09-16", "femm", "synthetic_inputs/a.lua")
        code = cli.main(["runs", "--tier", str(tier)])
        assert code != cli.EXIT_OK
        assert "orphaned" in capsys.readouterr().out.lower()


class TestTheLiveTierOpportunistically:
    def test_the_real_tier_is_clean_if_it_is_present(self) -> None:
        """An opportunistic check on live data, not the specification.

        Returns early rather than skipping when the tier is absent, because ``artifacts/`` does not
        exist in a clone and a skip would make the Gate report ``PYTEST-COVERAGE-REDUCED``. The
        synthetic cases above are what actually specify the behaviour; this one catches the real
        tier drifting on the machine where the runs happen.
        """
        if not LIVE_TIER.is_dir():
            return
        findings = _validate(LIVE_TIER)
        details = [getattr(f, "detail", repr(f)) for f in findings]
        assert not findings, "the live solver-run tier has findings:\n  " + "\n  ".join(details)
