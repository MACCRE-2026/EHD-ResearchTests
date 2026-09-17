"""The adapter contract, checked rather than reviewed.

Three obligations this file discharges, from plan Task 12:

1. **A contract test every adapter satisfies.** Parameterised over the registry, so a new adapter is
   covered the moment it is registered rather than when somebody remembers to add tests.
2. **An attribution test that fails when a registered tool is absent from ``ATTRIBUTIONS.md``.**
3. **A provenance test rejecting a manual solver run lacking version and input hash.**

The framing that matters here
-----------------------------
No FEMM, LTspice, QSPICE, Gmsh, Elmer, OpenFOAM or ParaView run has occurred in this project, and
none of the tools is installed on this machine. So every test below asserts something about the
**shape and the refusals**, never about a solved number. A test that needed a solver present would
be a test that silently stops running the moment the environment changes, which is the opposite of
what this layer is for.

The most dangerous input any adapter will receive is a tool that ran, exited zero and returned
nothing usable. Most of this file is that case, in its several disguises.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ehdpsu import adapters
from ehdpsu.adapters import base as adapter_base
from ehdpsu.adapters import provenance as prov
from ehdpsu.basis import Basis
from ehdpsu.detect import KNOWN_TOOLS, ToolStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTIONS = REPO_ROOT / "ATTRIBUTIONS.md"

# The five obligations, by name, from .kiro/steering/adapter-contract.md. Stated here rather than
# read from the ABC: comparing the ABC against itself would assert nothing.
FIVE_OBLIGATIONS = ("detect", "version", "generate", "run", "parse")

A_VALID_DIGEST = "0" * 64
ANOTHER_VALID_DIGEST = "a" * 64


def _adapter_ids() -> list[str]:
    return [a.name for a in adapters.ADAPTERS]


@pytest.fixture(params=adapters.ADAPTERS, ids=_adapter_ids())
def adapter(request: pytest.FixtureRequest) -> adapters.Adapter:
    """Every registered adapter, so the contract tests scale with the registry."""
    result: adapters.Adapter = request.param
    return result


class TestTheRegistryItself:
    def test_at_least_one_adapter_is_registered(self) -> None:
        """An empty registry would make every parameterised contract test vacuous."""
        assert adapters.ADAPTERS, "no adapters registered, so the contract tests assert nothing"

    def test_adapter_names_are_unique(self) -> None:
        names = [a.name for a in adapters.ADAPTERS]
        assert len(names) == len(set(names)), f"duplicate adapter names: {names}"

    def test_every_adapter_name_matches_a_detection_spec(self) -> None:
        """The adapter and the detection table must agree about what the tool is called.

        *Principle 4, two representations of one thing will drift.* An adapter naming a tool the
        detection table does not know would report a permanent absence for a tool nobody is looking
        for.
        """
        known = {spec.name for spec in KNOWN_TOOLS}
        stray = sorted(a.name for a in adapters.ADAPTERS if a.name not in known)
        assert not stray, f"adapters with no ToolSpec in detect.KNOWN_TOOLS: {stray}"

    def test_adapter_for_raises_on_an_unknown_name(self) -> None:
        """Not ``None``. A caller receiving ``None`` treats 'no adapter' as 'nothing to do'."""
        with pytest.raises(KeyError, match="registered"):
            adapters.adapter_for("no-such-tool")

    def test_adapter_for_returns_the_registered_instance(self, adapter: adapters.Adapter) -> None:
        assert adapters.adapter_for(adapter.name) is adapter

    def test_tools_detectable_but_unadapted_are_not_silently_claimed(self) -> None:
        """Four tools have detection and no adapter, and that gap is deliberate.

        Detection is implemented for gmsh, elmer, openfoam and paraview; the other four obligations
        are not. Registering them would advertise a capability that does not exist — plan Tasks 14
        and 15 add it. Pinned so the day an adapter appears, this test changes on purpose.
        """
        registered = {a.name for a in adapters.ADAPTERS}
        detectable = {spec.name for spec in KNOWN_TOOLS}
        assert detectable - registered == {"gmsh", "elmer", "openfoam", "paraview"}


class TestTheFiveObligations:
    @pytest.mark.parametrize("obligation", FIVE_OBLIGATIONS)
    def test_every_adapter_implements_every_obligation(
        self, adapter: adapters.Adapter, obligation: str
    ) -> None:
        """An adapter missing any of the five is incomplete, not minimal."""
        attr = getattr(adapter, obligation, None)
        assert callable(attr), f"{adapter.name} has no callable {obligation}()"

    def test_the_abstract_base_declares_the_tool_specific_obligations_abstract(self) -> None:
        """``generate`` and ``run`` cannot be inherited, because they are the tool-specific pair.

        ``detect``, ``version`` and ``parse`` are deliberately concrete and shared: an adapter that
        could reimplement detection could get the TOOL_ABSENT / TOOL_UNRESOLVED distinction wrong on
        its own, and an adapter with its own parser is one more chance to disagree about what a
        missing version means.
        """
        abstract = adapters.Adapter.__abstractmethods__
        assert {"generate", "run"} <= abstract
        assert not ({"detect", "version", "parse"} & abstract)

    def test_declared_metadata_is_present_and_substantive(self, adapter: adapters.Adapter) -> None:
        assert adapter.name.strip()
        assert adapter.attribution.strip()
        assert len(adapter.capability.split()) >= 6, (
            f"{adapter.name}'s capability line is too terse to tell an operator what they lose "
            f"when the tool is absent: {adapter.capability!r}"
        )
        assert adapter.expected_values, f"{adapter.name} declares no expected result values"

    def test_expected_value_names_carry_their_units(self, adapter: adapters.Adapter) -> None:
        """Units and geometry live in identifiers, in result files as much as in code.

        A transcribed ``E_peak`` could be V/m or kV/mm and nothing would catch the difference; a
        transcribed ``E_peak_surface_V_per_m`` cannot be misread.
        """
        unitless = [
            name
            for name in adapter.expected_values
            if not any(name.endswith(suffix) for suffix in ("_V", "_A", "_F", "_m", "_s"))
            and "_per_" not in name
            and not name.endswith("_pp_V")
        ]
        assert not unitless, f"{adapter.name} expects value names with no unit: {unitless}"


class TestDetectAndVersion:
    def test_detect_returns_a_probe_without_touching_the_tool(
        self, adapter: adapters.Adapter
    ) -> None:
        probe = adapter.detect()
        assert probe.name == adapter.name
        assert probe.routes_tried, "no route recorded as attempted"

    def test_version_is_none_or_a_nonempty_string(self, adapter: adapters.Adapter) -> None:
        """``None`` is a real answer, not a failure: these tools are GUI-driven."""
        version = adapter.version()
        assert version is None or version.strip()

    def test_a_present_tool_is_the_only_one_with_a_path(self, adapter: adapters.Adapter) -> None:
        probe = adapter.detect()
        if probe.status is ToolStatus.PRESENT:
            assert probe.path is not None
        else:
            assert probe.path is None


class TestGenerateIsDeterministic:
    def test_generating_twice_produces_identical_bytes(
        self, adapter: adapters.Adapter, tmp_path: Path
    ) -> None:
        """``solver_inputs/`` is tracked and diffed, so nondeterminism is indistinguishable from a
        real change.

        A timestamp, a dict ordering or a locale-dependent float format would produce a failing diff
        on every regeneration, and a failure that fires constantly is a failure nobody reads.
        """
        first = adapter.generate(tmp_path / "a")
        second = adapter.generate(tmp_path / "b")
        assert [p.name for p in first] == [p.name for p in second]
        for left, right in zip(first, second, strict=True):
            assert left.read_bytes() == right.read_bytes(), f"{left.name} is not byte-reproducible"

    def test_generate_writes_at_least_one_artifact(
        self, adapter: adapters.Adapter, tmp_path: Path
    ) -> None:
        written = adapter.generate(tmp_path)
        assert written
        for path in written:
            assert path.is_file()
            assert path.stat().st_size > 0, f"{path.name} was created empty"

    def test_generate_creates_its_output_directory(
        self, adapter: adapters.Adapter, tmp_path: Path
    ) -> None:
        """A caller naming a fresh directory should not have to create it first."""
        target = tmp_path / "does" / "not" / "exist"
        written = adapter.generate(target)
        assert all(p.is_file() for p in written)

    def test_generated_artifacts_match_the_tracked_solver_inputs(
        self, adapter: adapters.Adapter, tmp_path: Path
    ) -> None:
        """What the adapter emits is what a cloner already has.

        ``solver_inputs/`` is tracked precisely so somebody who cannot run this suite can still open
        the file in the tool. If the adapter path and the ``python -m ehdpsu.spice`` path diverged,
        the tracked file would describe a circuit the code no longer generates.
        """
        for produced in adapter.generate(tmp_path):
            tracked = REPO_ROOT / "solver_inputs" / produced.name
            if not tracked.is_file():
                continue
            assert produced.read_text(encoding="utf-8") == tracked.read_text(encoding="utf-8"), (
                f"{produced.name} from {adapter.name}.generate() differs from the tracked "
                f"solver_inputs/ copy; regenerate the tracked file deliberately or fix the drift"
            )


class TestRunIsHonestAboutWhatHappened:
    def test_no_adapter_claims_to_have_run_anything(self, adapter: adapters.Adapter) -> None:
        """No solver run has occurred in this project, and no adapter may imply one has.

        *Principle 3, never report success over unperformed work.* This test is **expected to
        change** the day plan Task 13 installs FEMM and a headless invocation is verified — and the
        change should be visible in a diff rather than silent.
        """
        outcome = adapter.run(()).outcome
        assert outcome is not adapters.RunOutcome.COMPLETED, (
            f"{adapter.name} reported COMPLETED. Nothing in this repository has run a solver; if "
            f"that changed, this test is the place to say so deliberately."
        )

    def test_run_reports_manual_or_unavailable_and_says_why(
        self, adapter: adapters.Adapter
    ) -> None:
        result = adapter.run(())
        assert result.outcome in (
            adapters.RunOutcome.MANUAL_REQUIRED,
            adapters.RunOutcome.TOOL_UNAVAILABLE,
        )
        assert (
            len(result.detail.split()) >= 10
        ), f"{adapter.name}'s run detail is too terse to act on: {result.detail!r}"

    def test_an_unavailable_tool_names_the_routes_it_tried(self, adapter: adapters.Adapter) -> None:
        """Absence has to be legible, or an operator cannot tell a missing install from a bug."""
        result = adapter.run(())
        if result.outcome is adapters.RunOutcome.TOOL_UNAVAILABLE:
            assert "configured-path" in result.detail

    def test_an_unavailable_tool_refuses_to_substitute_a_closed_form(
        self, adapter: adapters.Adapter
    ) -> None:
        """A missing tool degrades a capability visibly and never quietly stands something in.

        The suite has closed-form figures for every quantity these solvers would produce, which is
        exactly why the temptation exists and why the refusal is asserted.
        """
        result = adapter.run(())
        if result.outcome is adapters.RunOutcome.TOOL_UNAVAILABLE:
            assert "substitut" in result.detail or "stand-in" in result.detail

    def test_no_adapter_returns_not_chosen_yet(self, adapter: adapters.Adapter) -> None:
        """``NOT_CHOSEN`` exists for Task 14's competing CFD routes and nothing produces it yet.

        Pinned rather than left implicit so the state is not quietly repurposed as a synonym for
        'unavailable', which would collapse the distinction the plan depends on.
        """
        assert adapter.run(()).outcome is not adapters.RunOutcome.NOT_CHOSEN

    def test_a_result_with_no_detail_is_refused(self) -> None:
        with pytest.raises(adapters.AdapterError, match="no detail"):
            adapters.RunResult(outcome=adapters.RunOutcome.MANUAL_REQUIRED, detail="   ")


class TestParseRefusesEverythingUnrecognised:
    """An unrecognised output shape is an error, never an empty result."""

    def _valid(self, adapter: adapters.Adapter) -> str:
        lines = [
            adapters.RESULT_FILE_MAGIC,
            "tool_version = STAND-IN 0.0 (no solver was run)",
            f"input_sha256 = {A_VALID_DIGEST}",
        ]
        lines += [f"{name} = 1.0" for name in adapter.expected_values]
        return "\n".join(lines) + "\n"

    def test_a_well_formed_file_parses(self, adapter: adapters.Adapter) -> None:
        parsed = adapter.parse(self._valid(adapter))
        assert parsed.input_sha256 == A_VALID_DIGEST
        assert set(parsed.values) == set(adapter.expected_values)

    def test_an_empty_file_is_an_error_not_an_empty_result(self, adapter: adapters.Adapter) -> None:
        """The named hazard: a tool that ran, exited zero, and returned nothing usable."""
        with pytest.raises(adapters.ParseError, match="magic|empty"):
            adapter.parse("")

    def test_whitespace_and_comments_alone_are_an_error(self, adapter: adapters.Adapter) -> None:
        with pytest.raises(adapters.ParseError):
            adapter.parse("\n\n   \n# just a comment\n")

    def test_a_missing_magic_line_is_refused(self, adapter: adapters.Adapter) -> None:
        text = self._valid(adapter).replace(adapters.RESULT_FILE_MAGIC + "\n", "")
        with pytest.raises(adapters.ParseError, match="magic|does not begin"):
            adapter.parse(text)

    def test_a_missing_tool_version_is_refused(self, adapter: adapters.Adapter) -> None:
        text = "\n".join(
            ln for ln in self._valid(adapter).splitlines() if not ln.startswith("tool_version")
        )
        with pytest.raises(adapters.ParseError, match="tool_version"):
            adapter.parse(text + "\n")

    def test_a_missing_input_hash_is_refused(self, adapter: adapters.Adapter) -> None:
        text = "\n".join(
            ln for ln in self._valid(adapter).splitlines() if not ln.startswith("input_sha256")
        )
        with pytest.raises(adapters.ParseError, match="input_sha256"):
            adapter.parse(text + "\n")

    def test_a_truncated_hash_is_refused(self, adapter: adapters.Adapter) -> None:
        text = self._valid(adapter).replace(A_VALID_DIGEST, A_VALID_DIGEST[:-4])
        with pytest.raises(adapters.ParseError, match="hex digest"):
            adapter.parse(text)

    def test_a_non_hex_hash_is_refused(self, adapter: adapters.Adapter) -> None:
        text = self._valid(adapter).replace(A_VALID_DIGEST, "z" * 64)
        with pytest.raises(adapters.ParseError, match="hex digest"):
            adapter.parse(text)

    def test_a_missing_value_is_refused(self, adapter: adapters.Adapter) -> None:
        """Some of what was asked for is its own state, not a success with gaps."""
        dropped = adapter.expected_values[0]
        text = "\n".join(
            ln for ln in self._valid(adapter).splitlines() if not ln.startswith(dropped)
        )
        with pytest.raises(adapters.ParseError, match="missing"):
            adapter.parse(text + "\n")

    def test_an_unrecognised_value_name_is_refused(self, adapter: adapters.Adapter) -> None:
        """A mistyped identifier must not arrive as data."""
        text = self._valid(adapter) + "E_peak_surfce_V_per_m = 1.0\n"
        with pytest.raises(adapters.ParseError, match="unrecognised"):
            adapter.parse(text)

    def test_a_repeated_name_is_refused(self, adapter: adapters.Adapter) -> None:
        """Taking the last one silently would hide a transcription error."""
        text = self._valid(adapter) + f"{adapter.expected_values[0]} = 2.0\n"
        with pytest.raises(adapters.ParseError, match="repeats"):
            adapter.parse(text)

    def test_a_line_without_an_assignment_is_refused(self, adapter: adapters.Adapter) -> None:
        text = self._valid(adapter) + "the solver seemed happy\n"
        with pytest.raises(adapters.ParseError, match="assignment"):
            adapter.parse(text)

    @pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
    def test_a_non_finite_value_is_refused(self, adapter: adapters.Adapter, bad: str) -> None:
        text = self._valid(adapter).replace(
            f"{adapter.expected_values[0]} = 1.0", f"{adapter.expected_values[0]} = {bad}"
        )
        with pytest.raises(adapters.ParseError, match="finite"):
            adapter.parse(text)

    def test_a_non_numeric_value_is_refused(self, adapter: adapters.Adapter) -> None:
        text = self._valid(adapter).replace(
            f"{adapter.expected_values[0]} = 1.0", f"{adapter.expected_values[0]} = about 1e7"
        )
        with pytest.raises(adapters.ParseError, match="not a number"):
            adapter.parse(text)

    def test_one_parser_serves_every_adapter(self) -> None:
        """No adapter overrides ``parse``.

        Six adapters with six parsers is six chances to disagree about what a missing version means
        — *principle 4, two representations of one thing will drift*, applied to the refusals that
        keep the layer honest.
        """
        overriders = [type(a).__name__ for a in adapters.ADAPTERS if "parse" in vars(type(a))]
        assert not overriders, f"adapters overriding parse(): {overriders}"


class TestProvenanceRefusesAnIncompleteRun:
    """A run record missing any of its three facts is not a weaker record. It is not a record."""

    def _kwargs(self) -> dict[str, object]:
        return {
            "tool": "femm",
            "tool_version": "FEMM 4.2 (stand-in; no run occurred)",
            "input_path": "solver_inputs/ehd_wire_collector.lua",
            "input_sha256": A_VALID_DIGEST,
            "values": {"E_peak_surface_V_per_m": 1.0},
            "profile_id": "a-profile",
        }

    def test_a_complete_record_constructs_and_is_solved(self) -> None:
        record = prov.RunRecord(**self._kwargs())  # type: ignore[arg-type]
        assert record.basis is Basis.SOLVED
        assert record.run_utc

    @pytest.mark.parametrize(
        "field_name",
        ["tool", "tool_version", "input_path", "input_sha256", "values", "profile_id"],
    )
    def test_a_record_missing_any_required_field_is_refused(self, field_name: str) -> None:
        kwargs = self._kwargs()
        kwargs[field_name] = {} if field_name == "values" else ""
        with pytest.raises(prov.ProvenanceError, match=field_name):
            prov.RunRecord(**kwargs)  # type: ignore[arg-type]

    def test_a_manual_run_without_version_or_hash_cannot_be_recorded(self) -> None:
        """The Task 12 requirement, stated as the case it is meant to catch.

        A human opened a GUI, read two numbers off it, and wrote them down without noting which
        build they used or which input file was loaded. Those numbers may well be right. They are
        not attributable to a run, so they cannot reach `solved`.
        """
        kwargs = self._kwargs()
        kwargs["tool_version"] = ""
        kwargs["input_sha256"] = ""
        with pytest.raises(prov.ProvenanceError) as exc:
            prov.RunRecord(**kwargs)  # type: ignore[arg-type]
        assert "tool_version" in str(exc.value)
        assert "input_sha256" in str(exc.value)

    def test_the_basis_has_no_branch_to_bypass(self) -> None:
        """``basis`` is unconditional because the gate is at construction, not interpretation.

        A property returning ``SOLVED`` or ``ANALYTICAL_PLACEHOLDER`` depending on a flag would let a
        caller reach a `solved` label by not reading the flag. Impossible by construction beats
        prevented by vigilance, so the check lives where an object cannot exist without passing it.
        """
        tree = ast.parse(Path(prov.__file__).read_text(encoding="utf-8"))
        basis_bodies = [
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "RunRecord"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "basis"
        ]
        assert basis_bodies, "RunRecord has no basis property to check"
        branches = [n for n in ast.walk(basis_bodies[0]) if isinstance(n, ast.If | ast.IfExp)]
        assert not branches, (
            "RunRecord.basis contains a branch. The gate belongs at construction, where an object "
            "cannot exist without passing it, not at interpretation where a caller can ignore it."
        )

    def test_a_truncated_hash_is_refused(self) -> None:
        kwargs = self._kwargs()
        kwargs["input_sha256"] = A_VALID_DIGEST[:-1]
        with pytest.raises(prov.ProvenanceError, match="input_sha256"):
            prov.RunRecord(**kwargs)  # type: ignore[arg-type]

    def test_a_record_is_frozen(self) -> None:
        record = prov.RunRecord(**self._kwargs())  # type: ignore[arg-type]
        with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError, by any name
            setattr(record, "tool_version", "something else")  # noqa: B010

    def test_a_hash_that_does_not_match_the_input_is_refused(self, tmp_path: Path) -> None:
        """A different failure from a missing hash, so it gets a different message.

        The values were transcribed against an input that has since been regenerated, so they
        describe a geometry or circuit that no longer exists. Re-running is the remedy; reconciling
        the hash would be curve-fitting the provenance.
        """
        artifact = tmp_path / "input.lua"
        artifact.write_text("-- geometry\n", encoding="utf-8")
        parsed = adapters.ParsedResult(
            tool_version="STAND-IN 0.0",
            input_sha256=ANOTHER_VALID_DIGEST,
            values={"E_peak_surface_V_per_m": 1.0},
        )
        with pytest.raises(prov.ProvenanceError, match="currently hashes"):
            prov.record_from_parsed(
                tool="femm", parsed=parsed, input_path=artifact, profile_id="a-profile"
            )

    def test_a_matching_hash_produces_a_record(self, tmp_path: Path) -> None:
        artifact = tmp_path / "input.lua"
        artifact.write_text("-- geometry\n", encoding="utf-8")
        digest = prov.sha256_of_file(artifact)
        parsed = adapters.ParsedResult(
            tool_version="STAND-IN 0.0",
            input_sha256=digest,
            values={"E_peak_surface_V_per_m": 1.0},
        )
        record = prov.record_from_parsed(
            tool="femm", parsed=parsed, input_path=artifact, profile_id="a-profile"
        )
        assert record.input_sha256 == digest
        assert record.basis is Basis.SOLVED

    def test_writing_a_record_refuses_to_overwrite(self, tmp_path: Path) -> None:
        """Records are append-only; a re-run is a new record naming what it supersedes.

        Two runs of the same solver on the same input that disagree is a finding worth keeping both
        halves of, and overwriting destroys the only evidence the disagreement existed.
        """
        record = prov.RunRecord(**self._kwargs())  # type: ignore[arg-type]
        destination = tmp_path / "runs" / "record.json"
        prov.write_run_record(record, destination)
        assert json.loads(destination.read_text(encoding="utf-8"))["basis"] == "solved"
        with pytest.raises(prov.ProvenanceError, match="append-only"):
            prov.write_run_record(record, destination)

    def test_a_written_record_carries_every_field_a_clone_will_not_have(
        self, tmp_path: Path
    ) -> None:
        """``artifacts/05_Solver_Runs/`` is untracked, so the record must stand alone.

        When a calibrated coefficient enters tracked code, the record justifying it does **not**
        travel with it. Whatever the tracked artifact cites has to be inline here.
        """
        record = prov.RunRecord(**self._kwargs())  # type: ignore[arg-type]
        written = prov.write_run_record(record, tmp_path / "record.json")
        payload = json.loads(written.read_text(encoding="utf-8"))
        for key in ("tool", "tool_version", "input_sha256", "values", "run_utc", "profile_id"):
            assert payload.get(key), f"written record omits {key}"


class TestAttributionIsMechanicallyChecked:
    def test_every_registered_adapter_is_named_in_attributions(self) -> None:
        """The Task 12 requirement: a registered tool absent from ``ATTRIBUTIONS.md`` fails.

        Naming what the suite stands on costs nothing and is the transparency the public release
        rests on.
        """
        text = ATTRIBUTIONS.read_text(encoding="utf-8")
        missing = sorted(a.attribution for a in adapters.ADAPTERS if a.attribution not in text)
        assert not missing, (
            f"registered adapters whose tool is absent from ATTRIBUTIONS.md: {missing}. Add the "
            f"entry; a wrapped tool the project does not credit is the transparency gap this check "
            f"exists to close."
        )

    def test_the_attribution_check_is_not_vacuous(self) -> None:
        """A registry of adapters with blank attributions would pass the test above trivially."""
        assert all(a.attribution.strip() for a in adapters.ADAPTERS)
        assert adapters.ADAPTERS


class TestDoctorReportsTheMatrix:
    def test_one_row_per_registered_adapter(self) -> None:
        rows = adapters.doctor_rows()
        assert [r.tool for r in rows] == [a.name for a in adapters.ADAPTERS]

    def test_every_row_states_a_capability(self) -> None:
        for row in adapters.doctor_rows():
            assert row.capability.strip(), f"{row.tool} row has no capability line"
            assert row.status.strip()
            assert row.run_mode.strip()

    def test_an_absent_tool_reports_absent_rather_than_degraded(self) -> None:
        """No row may describe a missing tool as working-with-limitations."""
        for row in adapters.doctor_rows():
            if row.status != ToolStatus.PRESENT.value:
                assert row.version == ""
                assert row.path == ""

    def test_a_broken_adapter_becomes_a_row_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A doctor that dies on the first broken adapter reports nothing about the rest.

        That is the least useful moment to stop talking, so the failure is contained to its own row.
        """

        def explode(self: adapters.Adapter, configured_path: Path | None = None) -> object:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(adapter_base.Adapter, "detect", explode)
        rows = adapters.doctor_rows()
        assert len(rows) == len(adapters.ADAPTERS)
        assert all(r.status == "adapter-error" for r in rows)
        assert all("probe exploded" in r.note for r in rows)

    def test_unresolved_capabilities_agrees_with_the_matrix(self) -> None:
        """One derivation, read two ways.

        This started as a check that two derivations agreed, which was the smell rather than the
        remedy: ``unresolved_capabilities`` probed the adapters a second time. That second probe
        escaped ``doctor_rows``'s containment and crashed ``doctor`` on a raising adapter — inside
        the summary that was reporting the breakage. It now reads the rows.
        """
        rows = adapters.doctor_rows()
        from_rows = tuple(r.tool for r in rows if r.status != ToolStatus.PRESENT.value)
        assert adapters.unresolved_capabilities(rows) == from_rows

    def test_a_broken_adapter_counts_as_unresolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An adapter that cannot say whether its tool is present has not established that it is."""

        def explode(self: adapters.Adapter, configured_path: Path | None = None) -> object:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(adapter_base.Adapter, "detect", explode)
        rows = adapters.doctor_rows()
        assert adapters.unresolved_capabilities(rows) == tuple(a.name for a in adapters.ADAPTERS)

    def test_summarising_a_broken_matrix_does_not_probe_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression itself, pinned.

        With every adapter raising, deriving the summary must stay inside the rows. A second probe
        would propagate the exception out of a function whose whole job is to describe the failure.
        """

        def explode(self: adapters.Adapter, configured_path: Path | None = None) -> object:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(adapter_base.Adapter, "detect", explode)
        rows = adapters.doctor_rows()
        assert adapters.unresolved_capabilities(rows)  # must not raise
