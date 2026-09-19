"""Specification for ``ehdsuite runrecord <tool>`` — FR-007, batch 2 step B.

Written 2026-09-18 before the implementation.

Why this verb exists
--------------------
Three result-file skeletons were produced by hand on 2026-09-16 so the first FEMM run could start
immediately. That worked once and does not scale: **every regeneration of a solver input needs a new
skeleton, and the field that must be regenerated is a 64-character SHA-256.**

Asking an operator to hand-copy a digest is inviting the exact transcription error that
``record_from_parsed`` then rejects. The rejection is safe — a wrong hash cannot become a run record —
but the whole round trip is avoidable, and the operator is at a bench with a solver open.

The trap this verb has to avoid
-------------------------------
**It must never emit a skeleton carrying a hash of something other than the input the operator will
actually feed the tool.** A skeleton with a plausible-looking but wrong digest is worse than no
skeleton: the operator fills it in, the record is refused, and the refusal names the hash rather than
the cause. *Principle 2, an approximately-correct identifier is worse than an absent one.*

So the verb generates the input and hashes **that file, on disk, as it stands**, or it refuses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ehdpsu import adapters, cli
from ehdpsu.adapters import provenance as prov

REPO_ROOT = Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def run(*argv: str) -> int:
    return cli.main(list(argv))


class TestTheVerbExists:
    def test_runrecord_is_a_registered_subcommand(self) -> None:
        import argparse

        actions = [
            a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction)
        ]
        assert actions, "the parser declares no subcommands"
        assert "runrecord" in actions[0].choices

    def test_it_takes_a_tool_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run("runrecord", "femm") == cli.EXIT_OK
        assert capsys.readouterr().out.strip()

    def test_an_unknown_tool_is_reported_not_guessed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Naming the registered adapters beats a stack trace, and beats silence.

        A verb that emits an empty skeleton for a mistyped tool would hand the operator a file that
        looks usable.
        """
        assert run("runrecord", "no-such-tool") == cli.EXIT_NOT_FOUND
        err = capsys.readouterr().err
        assert "no-such-tool" in err
        for name in ("femm", "gmsh"):
            assert name in err, "the error does not list what is registered"


class TestTheSkeletonIsUsable:
    """Whatever it emits must survive a round trip through the parser that will read it back."""

    @pytest.mark.parametrize("tool", ["femm", "ltspice", "qspice", "gmsh", "elmer", "paraview"])
    def test_the_skeleton_carries_the_magic_line_first(
        self, tool: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run("runrecord", tool) == cli.EXIT_OK
        out = capsys.readouterr().out
        body = [ln for ln in out.splitlines() if ln.strip()]
        assert body[0].strip() == adapters.RESULT_FILE_MAGIC, (
            f"the skeleton for {tool} does not begin with {adapters.RESULT_FILE_MAGIC!r}, so "
            f"parse() will refuse it"
        )

    @pytest.mark.parametrize("tool", ["femm", "gmsh", "elmer", "paraview"])
    def test_the_skeleton_names_every_expected_value_and_no_others(
        self, tool: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exactly the adapter's own value names. An extra one is refused by ``parse``."""
        run("runrecord", tool)
        out = capsys.readouterr().out
        expected = set(adapters.adapter_for(tool).expected_values)
        present = {
            ln.split("=")[0].strip()
            for ln in out.splitlines()
            if "=" in ln and not ln.lstrip().startswith("#")
        }
        assert expected <= present, f"missing value lines for {sorted(expected - present)}"
        assert present <= expected | {"tool_version", "input_sha256"}, (
            f"the skeleton carries names parse() will reject: "
            f"{sorted(present - expected - {'tool_version', 'input_sha256'})}"
        )

    @pytest.mark.parametrize("tool", ["femm", "gmsh", "elmer", "paraview"])
    def test_the_unfilled_skeleton_is_refused_by_parse(
        self, tool: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An unfilled skeleton must not parse. Otherwise blank values become data.

        This is the property that makes the whole format safe: a half-transcribed file is a
        refusal, not a partial result.
        """
        run("runrecord", tool)
        out = capsys.readouterr().out
        with pytest.raises(adapters.ParseError):
            adapters.adapter_for(tool).parse(out)

    @pytest.mark.parametrize("tool", ["femm", "gmsh", "elmer", "paraview"])
    def test_the_filled_skeleton_parses(
        self, tool: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fill in the blanks and it must go through. The round trip is the point of the verb."""
        run("runrecord", tool)
        out = capsys.readouterr().out
        adapter = adapters.adapter_for(tool)
        filled = out
        for name in adapter.expected_values:
            filled = re.sub(rf"(?m)^{re.escape(name)}\s*=.*$", f"{name} = 1.0", filled)
        filled = re.sub(
            r"(?m)^tool_version\s*=.*$", "tool_version = STAND-IN 0.0 (no run occurred)", filled
        )
        parsed = adapter.parse(filled)
        assert set(parsed.values) == set(adapter.expected_values)


class TestTheHashIsGeneratedFromTheRealInput:
    """The one thing this verb must not get wrong."""

    @pytest.mark.parametrize("tool", ["femm", "gmsh", "elmer", "paraview"])
    def test_the_hash_is_a_lowercase_sha256(
        self, tool: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run("runrecord", tool)
        out = capsys.readouterr().out
        match = re.search(r"(?m)^input_sha256\s*=\s*(\S+)\s*$", out)
        assert match, "the skeleton has no filled input_sha256 line"
        assert SHA256_RE.match(match.group(1)), (
            f"input_sha256 is {match.group(1)!r}, not a 64-character lowercase hex digest. A "
            f"placeholder here is worse than a blank: the operator fills the file in, the record is "
            f"refused, and the refusal names the hash rather than the cause."
        )

    @pytest.mark.parametrize("tool", ["gmsh", "elmer", "paraview"])
    def test_the_hash_matches_the_input_the_adapter_actually_generates(
        self, tool: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Recomputed independently here, from the adapter's own ``generate`` output.

        These three generate deterministically and have no tracked counterpart, so the digest the
        verb prints must equal the digest of a freshly generated file.
        """
        run("runrecord", tool)
        printed = re.search(r"(?m)^input_sha256\s*=\s*(\S+)\s*$", capsys.readouterr().out)
        assert printed
        written = adapters.adapter_for(tool).generate(tmp_path)
        digests = {prov.sha256_of_file(p) for p in written}
        assert printed.group(1) in digests, (
            f"the printed digest is not the digest of any file {tool}.generate() produces; the "
            f"skeleton describes an input the operator will not be feeding the tool"
        )

    def test_the_femm_hash_matches_the_tracked_solver_input(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FEMM's input is tracked in ``solver_inputs/``, so there is an on-disk file to check."""
        run("runrecord", "femm")
        printed = re.search(r"(?m)^input_sha256\s*=\s*(\S+)\s*$", capsys.readouterr().out)
        assert printed
        tracked = REPO_ROOT / "solver_inputs" / "ehd_wire_collector.lua"
        assert printed.group(1) == prov.sha256_of_file(tracked)

    def test_the_skeleton_names_the_input_path_it_hashed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A digest with no filename cannot be checked by the person holding the file."""
        run("runrecord", "femm")
        assert "ehd_wire_collector.lua" in capsys.readouterr().out


class TestItRefusesRatherThanInvents:
    def test_no_tool_version_is_fabricated(self, capsys: pytest.CaptureFixture[str]) -> None:
        """All six tools are ``manual_only`` or unprobeable, so no version can be captured.

        The line must be present and **blank**, or carry an explicit marker — never a plausible
        version string. *solver-provenance.md*: tool identity captured from the tool itself, not the
        version somebody believed was installed.
        """
        run("runrecord", "gmsh")
        out = capsys.readouterr().out
        match = re.search(r"(?m)^tool_version\s*=\s*(.*)$", out)
        assert match, "no tool_version line"
        value = match.group(1).strip()
        assert not re.search(r"\d+\.\d+", value), (
            f"tool_version reads {value!r}, which contains a version-shaped number. Nothing has "
            f"asked Gmsh for its version and it is not installed here."
        )

    def test_it_states_that_no_run_has_occurred(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The skeleton is an invitation to run something, not a record that something ran."""
        run("runrecord", "elmer")
        out = capsys.readouterr().out.lower()
        assert "not been run" in out or "no run" in out or "has not run" in out

    def test_running_it_twice_is_byte_identical(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No timestamp in the skeleton.

        A generated timestamp would make two skeletons for the same input differ, which is a
        second representation of "when" competing with the run record's own ``run_utc``.
        """
        run("runrecord", "gmsh")
        first = capsys.readouterr().out
        run("runrecord", "gmsh")
        assert capsys.readouterr().out == first
