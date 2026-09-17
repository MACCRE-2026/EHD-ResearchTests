"""Tests for the ``ehdsuite`` command surface.

The CLI is deliberately built before the GUI, per the charter's layering rule: any new architecture
belongs at the CLI level and below. So these tests are not incidental coverage of a convenience —
they pin the vocabulary the GUI and the agent-authoring seats will call.

Every command is exercised through :func:`ehdpsu.cli.main` with an argument list, rather than through
a subprocess. That keeps the tests fast and lets them assert on **exit codes**, which are the part a
script or an agent actually branches on.

The failure paths get more attention than the success paths, because the success paths are what
somebody would notice being broken.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from conftest import REFERENCE_PROFILE_PATH

from ehdpsu import adapters, cli

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """An empty profile directory, matching how ``profiles/`` ships."""
    directory = tmp_path / "profiles"
    directory.mkdir()
    return directory


@pytest.fixture
def seeded(workdir: Path) -> Path:
    """A profile directory holding one valid profile copied from the frozen fixture."""
    target = workdir / "mk0_benchtop_22kv.json"
    target.write_text(REFERENCE_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return workdir


def run(*argv: str) -> int:
    return cli.main(list(argv))


class TestSchema:
    """The machine-readable surface an editor or a writer seat renders from."""

    def test_json_output_lists_every_field(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run("schema", "--json") == cli.EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_version"] >= 1
        assert len(payload["fields"]) == 25

    def test_every_field_exposes_what_a_form_needs(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FR-001 decided the GUI renders from ``profile.FIELDS``, so this is the contract.

        A hand-maintained form would be a second representation of the schema. That makes these keys
        load-bearing for a user interface, not just for validation.
        """
        run("schema", "--json")
        for field in json.loads(capsys.readouterr().out)["fields"]:
            assert set(field) == {"name", "section", "unit", "kind", "type", "nullable", "doc"}
            assert field["doc"], f"{field['name']} has no documentation to show a user"
            assert field["unit"], f"{field['name']} has no unit to show a user"

    def test_human_output_states_that_nothing_is_defaulted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The single most important thing for someone about to hand-author a profile.
        assert run("schema") == cli.EXIT_OK
        assert "Nothing is defaulted" in capsys.readouterr().out


class TestList:
    def test_an_empty_directory_says_so_and_is_not_an_error(
        self, workdir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Empty is the shipped state, so it must not read as a failure.
        assert run("--profile-dir", str(workdir), "list") == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "how it ships" in out
        assert "no set design point" in out

    def test_lists_the_ceiling_alongside_each_profile(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The ceiling is the thing a reader needs next, so it belongs in the listing rather than
        # behind another command.
        assert run("--profile-dir", str(seeded), "list") == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "mk0_benchtop_22kv" in out
        assert "claimed" in out

    def test_one_broken_profile_does_not_hide_the_others(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (seeded / "broken.json").write_text("{not json", encoding="utf-8")
        assert run("--profile-dir", str(seeded), "list") == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "INVALID" in out
        assert "mk0_benchtop_22kv" in out, "a malformed profile aborted the listing"


class TestValidate:
    def test_validating_nothing_is_not_success(
        self, workdir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*Principle 3, never report success over unperformed work*, in command form.

        ``profiles/`` ships empty, so "validated 0 profiles, all fine" would be a green result over
        no work at all. It gets its own exit code.
        """
        assert run("--profile-dir", str(workdir), "validate") == cli.EXIT_NOTHING_VALIDATED
        assert "NOTHING VALIDATED" in capsys.readouterr().err

    def test_a_valid_profile_passes_and_reports_its_ceiling(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run("--profile-dir", str(seeded), "validate") == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "1/1 profile(s) valid" in out
        assert "NOT validated" in out, "a claimed ceiling must be reported as not validated"

    def test_an_invalid_profile_fails_with_the_field_and_the_reason(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = json.loads((seeded / "mk0_benchtop_22kv.json").read_text(encoding="utf-8"))
        raw["design"]["emitter"]["r_wire_m"]["unit"] = "mm"
        (seeded / "mk0_benchtop_22kv.json").write_text(json.dumps(raw), encoding="utf-8")

        assert run("--profile-dir", str(seeded), "validate") == cli.EXIT_INVALID_PROFILE
        err = capsys.readouterr().err
        assert "r_wire_m" in err, "the failure does not name the offending field"
        assert "unit" in err

    def test_an_unknown_target_is_reported_rather_than_skipped(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Silently validating nothing because a name was mistyped would report success over an
        # unperformed check.
        assert run("--profile-dir", str(seeded), "validate", "nope") == cli.EXIT_NOT_FOUND
        assert "no profile 'nope'" in capsys.readouterr().err

    def test_an_explicit_path_works_outside_the_profile_directory(
        self, workdir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--profile-dir", str(workdir), "validate", str(REFERENCE_PROFILE_PATH)]
        assert cli.main(argv) == cli.EXIT_OK
        assert "1/1" in capsys.readouterr().out


class TestDiff:
    def test_identical_profiles_report_no_difference(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--profile-dir", str(seeded), "diff", "mk0_benchtop_22kv", "mk0_benchtop_22kv"]
        assert cli.main(argv) == cli.EXIT_OK
        assert "identical" in capsys.readouterr().out

    def test_a_changed_value_is_reported_with_its_ratio(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = json.loads((seeded / "mk0_benchtop_22kv.json").read_text(encoding="utf-8"))
        raw["design"]["supply"]["V_op_V"]["value"] = 5000.0
        raw["profile_id"] = "mk1"
        (seeded / "mk1.json").write_text(json.dumps(raw), encoding="utf-8")

        argv = ["--profile-dir", str(seeded), "diff", "mk0_benchtop_22kv", "mk1"]
        assert cli.main(argv) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "V_op_V" in out
        assert "1 field(s) differ" in out

    def test_the_diff_refuses_to_interpret(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A ratio is reported, never judged.

        Whether a design change is an improvement is a physics question. An engine that answered it
        would be making a decision that belongs to the operator and the relevant domain Oracle.
        """
        raw = json.loads((seeded / "mk0_benchtop_22kv.json").read_text(encoding="utf-8"))
        raw["design"]["supply"]["V_op_V"]["value"] = 5000.0
        (seeded / "other.json").write_text(json.dumps(raw), encoding="utf-8")

        cli.main(["--profile-dir", str(seeded), "diff", "mk0_benchtop_22kv", "other"])
        out = capsys.readouterr().out.lower()
        assert "not interpreted" in out

        # Scoped to the per-field lines, which end where the summary begins. The trailing
        # explanation legitimately contains the word "improvement" while *disclaiming* any verdict,
        # and a checker that cannot tell discussing a thing from doing it is not a checker -- the
        # same trap that once made the leakage scanner flag its own sentinel list.
        field_lines = out.split("field(s) differ")[0]
        for verdict in ("better", "worse", "improve", "recommend", "should"):
            assert verdict not in field_lines, (
                f"the diff output passes judgement ({verdict!r}) on a field. Whether a change is an "
                f"improvement is a physics question for the operator and the relevant Oracle."
            )


class TestNew:
    def test_source_is_required(self, workdir: Path) -> None:
        """There is no set design point, so this command cannot default one.

        argparse exits 2 on a usage error, which is why no status of ours uses 2.
        """
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--profile-dir", str(workdir), "new", "mk1"])
        assert exit_info.value.code == 2

    def test_creates_a_profile_from_an_explicit_source(
        self, workdir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = [
            "--profile-dir",
            str(workdir),
            "new",
            "mk1_palm",
            "--from",
            str(REFERENCE_PROFILE_PATH),
        ]
        assert cli.main(argv) == cli.EXIT_OK
        created = workdir / "mk1_palm.json"
        assert created.is_file()
        assert "inherited" in capsys.readouterr().out

    def test_the_new_profile_id_matches_its_filename(self, workdir: Path) -> None:
        # `load_named` resolves by filename stem, so a mismatch would make the file disagree with
        # its own identity.
        cli.main(
            [
                "--profile-dir",
                str(workdir),
                "new",
                "mk1_palm",
                "--from",
                str(REFERENCE_PROFILE_PATH),
            ]
        )
        raw = json.loads((workdir / "mk1_palm.json").read_text(encoding="utf-8"))
        assert raw["profile_id"] == "mk1_palm"

    def test_provenance_records_the_source_and_warns_about_inherited_bases(
        self, workdir: Path
    ) -> None:
        """A copied basis is not evidence about the new design, and the file must say so.

        Without it, a profile inherits ``claimed`` values that look considered because they came
        from somewhere.
        """
        cli.main(
            [
                "--profile-dir",
                str(workdir),
                "new",
                "mk1_palm",
                "--from",
                str(REFERENCE_PROFILE_PATH),
            ]
        )
        provenance = json.loads((workdir / "mk1_palm.json").read_text(encoding="utf-8"))[
            "provenance"
        ]
        assert "mk0_benchtop_22kv" in provenance["derived_from"]
        assert "not evidence" in provenance["derived_note"]

    def test_refuses_to_clobber_without_permission(self, workdir: Path) -> None:
        argv = [
            "--profile-dir",
            str(workdir),
            "new",
            "mk1_palm",
            "--from",
            str(REFERENCE_PROFILE_PATH),
        ]
        assert cli.main(argv) == cli.EXIT_OK
        assert cli.main(argv) == cli.EXIT_REFUSED_OVERWRITE
        assert cli.main([*argv, "--overwrite"]) == cli.EXIT_OK

    def test_refuses_to_copy_an_invalid_source(
        self, workdir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Copying a malformed profile under a new name would propagate the defect and give it a
        # fresh, more trustworthy-looking identity.
        bad = workdir / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        argv = ["--profile-dir", str(workdir), "new", "mk1", "--from", str(bad)]
        assert cli.main(argv) == cli.EXIT_INVALID_PROFILE
        assert "refusing to copy" in capsys.readouterr().err

    def test_a_missing_source_is_reported(self, workdir: Path) -> None:
        argv = ["--profile-dir", str(workdir), "new", "mk1", "--from", "absent"]
        assert cli.main(argv) == cli.EXIT_NOT_FOUND

    def test_the_created_profile_validates(self, workdir: Path) -> None:
        # The round trip that matters: a profile this command writes must load back.
        cli.main(
            ["--profile-dir", str(workdir), "new", "mk1", "--from", str(REFERENCE_PROFILE_PATH)]
        )
        assert cli.main(["--profile-dir", str(workdir), "validate", "mk1"]) == cli.EXIT_OK


class TestReport:
    def test_reports_every_figure_with_its_qualifications(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--profile-dir", str(seeded), "report", "mk0_benchtop_22kv"]
        assert cli.main(argv) == cli.EXIT_OK
        out = capsys.readouterr().out
        for figure in ("e_peek", "v_onset", "k_geo", "thrust", "efficiency", "cw_droop"):
            assert figure in out

    def test_the_upper_bound_label_reaches_the_console(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*Physics honesty rule 4:* labelled everywhere it appears, including here."""
        cli.main(["--profile-dir", str(seeded), "report", "mk0_benchtop_22kv"])
        out = capsys.readouterr().out
        assert out.count("UPPER BOUND") >= 3, "the ceilings and the explanation must both be shown"
        assert "real thrust is lower" in out

    def test_the_band_reaches_the_console(
        self, seeded: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.main(["--profile-dir", str(seeded), "report", "mk0_benchtop_22kv"])
        assert "x0.1 to x1" in capsys.readouterr().out

    def test_a_missing_profile_is_reported(self, seeded: Path) -> None:
        assert cli.main(["--profile-dir", str(seeded), "report", "absent"]) == cli.EXIT_NOT_FOUND


class TestExitCodes:
    def test_no_status_collides_with_argparse(self) -> None:
        """argparse exits 2 on a usage error, so 2 must stay reserved.

        A collision would make "you typed the command wrong" indistinguishable from a real failure,
        which is the difference a script branches on.
        """
        statuses = [
            cli.EXIT_OK,
            cli.EXIT_INVALID_PROFILE,
            cli.EXIT_NOTHING_VALIDATED,
            cli.EXIT_NOT_FOUND,
            cli.EXIT_REFUSED_OVERWRITE,
        ]
        assert 2 not in statuses
        assert len(set(statuses)) == len(statuses), "two statuses share a code"

    def test_every_command_is_reachable(self) -> None:
        # A subcommand wired into the parser but with no handler would fail only when invoked.
        # argparse exposes no public accessor for its subparsers, so the private attributes are
        # read deliberately. The alternative is duplicating the command list here, which would be a
        # second representation of the parser and would drift from it.
        subparser_actions = [
            action
            for action in cli.build_parser()._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        assert subparser_actions, "the parser declares no subcommands"

        choices = subparser_actions[0].choices
        assert set(choices) == {
            "schema",
            "list",
            "validate",
            "diff",
            "new",
            "report",
            "crosscheck",
            "doctor",
        }
        for name, sub in choices.items():
            assert sub.get_default("func") is not None, f"{name} has no handler"


class TestDoctor:
    """``ehdsuite doctor`` — the Task 12 demo, and the command an operator runs first.

    Its whole job is to say what the suite cannot do. Every assertion here is about absence being
    legible, because absence is the answer today: no FEMM, LTspice, QSPICE, Gmsh, Elmer, OpenFOAM or
    ParaView run has occurred in this project.
    """

    def test_the_matrix_lists_every_registered_adapter(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run("doctor") == cli.EXIT_OK
        out = capsys.readouterr().out
        for adapter in adapters.ADAPTERS:
            assert adapter.name in out, f"{adapter.name} is registered but absent from the matrix"

    def test_absent_tools_are_not_a_command_failure(self) -> None:
        """Exit 0 with nothing installed.

        An absent solver is the normal state of this repository. A non-zero exit would make the
        ordinary condition indistinguishable from a defect, and the operator would learn to ignore
        it.
        """
        assert run("doctor") == cli.EXIT_OK

    def test_an_absent_capability_is_called_absent_rather_than_degraded(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The contract's wording, checked: absent, not degraded-but-fine."""
        run("doctor")
        out = capsys.readouterr().out
        if adapters.unresolved_capabilities():
            assert "ABSENT" in out
            assert "not stand-ins" in out or "substitut" in out

    def test_the_matrix_states_what_each_capability_would_provide(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A tool name alone does not tell an operator what installing it buys them."""
        run("doctor")
        out = capsys.readouterr().out
        assert "capability" in out
        assert "k_geo" in out, "the FEMM row does not say it is the route to calibrating k_geo"

    def test_the_matrix_names_the_detectable_tools_that_have_no_adapter(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Silence about them would read as coverage.

        Detection is implemented for seven tools and four of them have no adapter. Omitting that
        from the matrix would let a reader conclude the suite drives everything it can detect.
        """
        run("doctor")
        out = capsys.readouterr().out
        for pending in ("gmsh", "elmer", "openfoam", "paraview"):
            assert pending in out

    def test_the_routes_tried_are_shown_so_absence_can_be_argued_with(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The Kiro CLI 2.21.4 case: a tool that was installed and working while a check said no.

        Showing the routes lets an operator see *how* the conclusion was reached, and supply
        ``--configured-path`` reasoning of their own if it looks wrong.
        """
        run("doctor")
        assert "configured-path" in capsys.readouterr().out

    def test_a_broken_adapter_exits_nonzero_and_is_distinguished_from_absence(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An adapter that raises is a defect in the suite; a missing tool is a fact about the
        machine. Two different things, so two different exit codes."""

        def explode(self: adapters.Adapter, configured_path: Path | None = None) -> object:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(adapters.Adapter, "detect", explode)
        assert run("doctor") == cli.EXIT_ADAPTER_BROKEN
        assert "raised while probing" in capsys.readouterr().err

    def test_the_new_exit_code_collides_with_nothing(self) -> None:
        codes = [
            cli.EXIT_OK,
            cli.EXIT_INVALID_PROFILE,
            cli.EXIT_NOTHING_VALIDATED,
            cli.EXIT_NOT_FOUND,
            cli.EXIT_REFUSED_OVERWRITE,
            cli.EXIT_CLAIM_INCONSISTENT,
            cli.EXIT_ADAPTER_BROKEN,
        ]
        assert len(codes) == len(set(codes))
        assert 2 not in codes, "2 is reserved: argparse exits 2 on a usage error"
