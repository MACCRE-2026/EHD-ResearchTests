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
from ehdpsu.adapters import toolconfig
from ehdpsu.basis import Basis
from ehdpsu.detect import KNOWN_TOOLS, ToolStatus
from ehdpsu.physics import default_design

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTIONS = REPO_ROOT / "ATTRIBUTIONS.md"

# The five obligations, by name, from .kiro/steering/adapter-contract.md. Stated here rather than
# read from the ABC: comparing the ABC against itself would assert nothing.
FIVE_OBLIGATIONS = ("detect", "version", "generate", "run", "parse")

A_VALID_DIGEST = "0" * 64
ANOTHER_VALID_DIGEST = "a" * 64

# Result-value names that are genuinely dimensionless, with the reason. Declared rather than inferred,
# for the same cause as every other register here: an escape hatch with no register stops being an
# escape hatch and becomes the normal case. `n_*` counts and `*_px` pixel dimensions are handled by
# convention in the test above and do not need entries.
DIMENSIONLESS_VALUE_NAMES: dict[str, str] = {
    "min_element_quality": (
        "a mesh quality metric on a 0-1 scale, dimensionless by definition; attaching an SI suffix "
        "would invent a unit it does not have"
    ),
    "field_range_min": (
        "the low end of the rendered scalar range, whose unit depends on which field was rendered "
        "and is therefore carried by the render script rather than the identifier"
    ),
    "field_range_max": (
        "the high end of the rendered scalar range, dimensionally ambiguous for the same reason as "
        "field_range_min"
    ),
}


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
        """Exactly one tool has detection and no adapter, and that gap is deliberate.

        Registering a tool advertises a capability, so the set of detectable-but-unadapted tools is
        pinned rather than allowed to drift in either direction.

        **Updated 2026-09-16 for the first delegated batch**, from
        ``{"gmsh", "elmer", "openfoam", "paraview"}`` down to ``{"openfoam"}``. This is a
        tests-first specification, not a record of work done: the batch's job is to make it true by
        registering Gmsh, Elmer and ParaView adapters.

        ``openfoam`` stays unadapted on purpose. Its route is Docker, decided 2026-09-16, and nothing
        about that route has been verified because Docker is not installed — the same discipline that
        found three fabricated executable names. It gets an adapter after step 14.3.0, not before.
        """
        registered = {a.name for a in adapters.ADAPTERS}
        detectable = {spec.name for spec in KNOWN_TOOLS}
        assert detectable - registered == {"openfoam"}, (
            f"detectable-but-unadapted is {sorted(detectable - registered)}; expected exactly "
            f"{{'openfoam'}}. Registering a tool claims a capability, and un-registering one "
            f"withdraws it — neither should happen as a side effect."
        )


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

        **Extended 2026-09-16** for tools whose read-back is genuinely dimensionless. A mesher reports
        element counts and a renderer reports pixel dimensions; demanding an SI suffix on a count
        would force a fake one, which is worse than none. Two escapes, both narrow and both declared:

          * a leading ``n_`` marks a count — ``n_nodes``, ``n_elements``;
          * a trailing ``_px`` marks a pixel dimension.

        Anything else dimensionless needs an entry in ``DIMENSIONLESS_VALUE_NAMES`` with a reason,
        mirroring every other declared register in this project. An escape hatch with no register is
        how a unit-free name becomes normal.
        """
        suffixes = ("_V", "_A", "_F", "_m", "_s", "_Pa", "_N", "_K", "_W", "_px")
        unitless = [
            name
            for name in adapter.expected_values
            if not any(name.endswith(s) for s in suffixes)
            and "_per_" not in name
            and not name.startswith("n_")
            and name not in DIMENSIONLESS_VALUE_NAMES
        ]
        assert not unitless, (
            f"{adapter.name} expects value names with no unit and no declared reason: {unitless}. "
            f"Add the unit to the identifier, or register the name in DIMENSIONLESS_VALUE_NAMES "
            f"with why it has none."
        )

    def test_the_dimensionless_register_is_not_a_loophole(self) -> None:
        """Every declared dimensionless name is in use and carries a substantive reason.

        A register that accumulates entries nobody removes becomes a list of everything, which is the
        same as no rule at all.
        """
        in_use = {name for a in adapters.ADAPTERS for name in a.expected_values}
        for name, reason in DIMENSIONLESS_VALUE_NAMES.items():
            assert name in in_use, (
                f"DIMENSIONLESS_VALUE_NAMES declares {name!r}, which no adapter expects. A stale "
                f"exemption is an exemption nobody re-justified."
            )
            assert len(reason.split()) >= 6, (
                f"DIMENSIONLESS_VALUE_NAMES[{name!r}] gives {reason!r}, too terse to have been "
                f"thought about."
            )


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


# ---------------------------------------------------------------------------
# Added 2026-09-16, after installing the tools exposed the gap.
#
# `configured-path` is the FIRST route in detect.ROUTE_ORDER and nothing in the suite could populate
# it. detect_tool accepted the argument, the adapters called detect() with no argument, and the CLI
# offered no way to pass one. The route was recorded as attempted on every probe and could never
# resolve anything.
#
# Found by installing: LTspice at B:\LTspice and QSPICE at B:\QSPICE, both working, both reported
# `tool-absent`. Correctly, by the contract's own definition -- all four routes were attempted, the
# registry PATH scopes were read successfully (34 entries, neither tool among them), and none
# resolved. The status logic was right and the outcome was a working tool reported absent, which is
# the one thing this layer exists to prevent.
#
# Every test below uses an isolated root. None may depend on what is installed on the machine
# running it, or on whether an operator has written a config at all.
# ---------------------------------------------------------------------------


class TestToolConfigLocation:
    def test_the_config_lives_at_the_repository_root_under_a_local_name(self) -> None:
        """``.local.`` in the name, so it reads as machine-specific before anyone opens it."""
        assert toolconfig.TOOL_CONFIG_FILENAME == "tools.local.json"
        assert toolconfig.tool_config_path() == REPO_ROOT / "tools.local.json"

    def test_an_explicit_root_is_respected(self, tmp_path: Path) -> None:
        assert toolconfig.tool_config_path(tmp_path) == tmp_path / "tools.local.json"

    def test_the_template_is_valid_input_to_the_loader(self, tmp_path: Path) -> None:
        """A template an operator cannot paste in is worse than no template.

        It is also the only documentation of the format that the CLI prints, so a template the loader
        rejects would be the CLI handing out a broken example.
        """
        (tmp_path / toolconfig.TOOL_CONFIG_FILENAME).write_text(
            toolconfig.config_template(), encoding="utf-8"
        )
        loaded = toolconfig.load_tool_paths(tmp_path)
        assert loaded, "the template configures nothing, so it demonstrates nothing"
        assert all(p.is_absolute() for p in loaded.values())

    def test_the_template_shows_one_tool_not_every_tool(self, tmp_path: Path) -> None:
        """A template listing all seven invites filling every line in.

        And a wrong path is worse than an absent one: it produces a configured route that fails,
        where no entry at all produces a clean fall-through to the vendor default.
        """
        (tmp_path / toolconfig.TOOL_CONFIG_FILENAME).write_text(
            toolconfig.config_template(), encoding="utf-8"
        )
        assert len(toolconfig.load_tool_paths(tmp_path)) == 1


class TestToolConfigLoading:
    def _write(self, root: Path, text: str) -> None:
        (root / toolconfig.TOOL_CONFIG_FILENAME).write_text(text, encoding="utf-8")

    def test_no_config_file_is_the_normal_case_and_not_an_error(self, tmp_path: Path) -> None:
        """Most machines have the tools where the vendor put them.

        Requiring a config file to detect a default install would be a worse default than none — and
        FEMM on this machine proves the point: it resolved through ``default-paths`` unconfigured.
        """
        assert toolconfig.load_tool_paths(tmp_path) == {}

    def test_a_valid_config_returns_absolute_paths(self, tmp_path: Path) -> None:
        self._write(tmp_path, '{"tools": {"ltspice": "B:\\\\LTspice\\\\LTspice.exe"}}')
        loaded = toolconfig.load_tool_paths(tmp_path)
        assert loaded == {"ltspice": Path(r"B:\LTspice\LTspice.exe")}

    def test_an_explicitly_empty_config_is_accepted(self, tmp_path: Path) -> None:
        """``{"tools": {}}`` says "configured nothing" out loud, which is a legitimate state."""
        self._write(tmp_path, '{"tools": {}}')
        assert toolconfig.load_tool_paths(tmp_path) == {}

    def test_malformed_json_raises_rather_than_being_skipped(self, tmp_path: Path) -> None:
        """Ignoring it would make a typo indistinguishable from no configuration.

        The operator would see ``tool-absent`` for a tool they had just told the suite where to find,
        with nothing anywhere saying the file was unreadable.
        """
        self._write(tmp_path, "{not json")
        with pytest.raises(toolconfig.ToolConfigError, match="not valid JSON"):
            toolconfig.load_tool_paths(tmp_path)

    def test_a_non_object_document_is_refused(self, tmp_path: Path) -> None:
        self._write(tmp_path, "[]")
        with pytest.raises(toolconfig.ToolConfigError, match="JSON object"):
            toolconfig.load_tool_paths(tmp_path)

    def test_a_missing_tools_key_is_refused(self, tmp_path: Path) -> None:
        self._write(tmp_path, '{"_comment": "nothing here"}')
        with pytest.raises(toolconfig.ToolConfigError, match="no 'tools' object"):
            toolconfig.load_tool_paths(tmp_path)

    def test_a_non_object_tools_value_is_refused(self, tmp_path: Path) -> None:
        self._write(tmp_path, '{"tools": ["B:\\\\LTspice"]}')
        with pytest.raises(toolconfig.ToolConfigError, match="must be an object"):
            toolconfig.load_tool_paths(tmp_path)

    def test_an_unknown_tool_name_is_refused(self, tmp_path: Path) -> None:
        """A mistyped name would otherwise be silently unconfigured.

        And silently unconfigured looks exactly like a tool that is not installed, which is the
        confusion this whole file exists to remove.
        """
        self._write(tmp_path, '{"tools": {"ltspce": "B:\\\\LTspice\\\\LTspice.exe"}}')
        with pytest.raises(toolconfig.ToolConfigError, match="unknown tool"):
            toolconfig.load_tool_paths(tmp_path)

    def test_every_known_tool_name_is_accepted(self, tmp_path: Path) -> None:
        """The register of valid names is ``detect.KNOWN_TOOLS``, not a second list here."""
        entries = ", ".join(f'"{spec.name}": "C:\\\\x\\\\y.exe"' for spec in KNOWN_TOOLS)
        self._write(tmp_path, f'{{"tools": {{{entries}}}}}')
        assert set(toolconfig.load_tool_paths(tmp_path)) == {s.name for s in KNOWN_TOOLS}

    @pytest.mark.parametrize("value", ['""', '"   "', "null", "42", "[]"])
    def test_a_non_string_or_empty_path_is_refused(self, tmp_path: Path, value: str) -> None:
        self._write(tmp_path, f'{{"tools": {{"ltspice": {value}}}}}')
        with pytest.raises(toolconfig.ToolConfigError, match="non-empty path string"):
            toolconfig.load_tool_paths(tmp_path)

    def test_a_relative_path_is_refused(self, tmp_path: Path) -> None:
        """The same config would find the tool from one working directory and not another."""
        self._write(tmp_path, '{"tools": {"ltspice": "LTspice\\\\LTspice.exe"}}')
        with pytest.raises(toolconfig.ToolConfigError, match="not absolute"):
            toolconfig.load_tool_paths(tmp_path)

    def test_the_loader_does_not_check_that_the_path_exists(self, tmp_path: Path) -> None:
        """Existence is ``detect_tool``'s business, and it reports a failure rather than hiding it.

        Validating here would collapse two different states — "you configured nothing" and "you
        configured something that has moved" — into one, and the second has to stay visible.
        """
        self._write(tmp_path, '{"tools": {"ltspice": "Z:\\\\nowhere\\\\LTspice.exe"}}')
        assert toolconfig.load_tool_paths(tmp_path)["ltspice"] == Path(r"Z:\nowhere\LTspice.exe")

    def test_configured_path_for_returns_none_when_unconfigured(self, tmp_path: Path) -> None:
        self._write(tmp_path, '{"tools": {"ltspice": "B:\\\\LTspice\\\\LTspice.exe"}}')
        assert toolconfig.configured_path_for("qspice", tmp_path) is None
        assert toolconfig.configured_path_for("ltspice", tmp_path) is not None


class TestAdaptersConsultTheConfig:
    def test_detect_uses_the_configured_path_when_none_is_passed(
        self, adapter: adapters.Adapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wiring that makes route 1 reachable.

        Monkeypatched rather than reading the real file, so this passes on a machine with no config
        and on one where the operator has configured every tool.
        """
        exe = tmp_path / adapter.tool_spec.executables[0]
        exe.write_text("stand-in\n", encoding="utf-8")
        monkeypatch.setattr(
            adapter_base, "configured_path_for", lambda name, root=None: exe if name else None
        )
        probe = adapter.detect()
        assert probe.status is ToolStatus.PRESENT
        assert probe.path == exe
        assert probe.routes_tried == ("configured-path",)

    def test_an_explicit_argument_beats_the_config(
        self, adapter: adapters.Adapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller who names a path meant that path.

        Otherwise a stale config entry would quietly override a deliberate one-off override, which is
        the wrong precedence: the more specific instruction is the one given at the call site.
        """
        from_config = tmp_path / "config" / adapter.tool_spec.executables[0]
        explicit = tmp_path / "explicit" / adapter.tool_spec.executables[0]
        for path in (from_config, explicit):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stand-in\n", encoding="utf-8")
        monkeypatch.setattr(
            adapter_base, "configured_path_for", lambda name, root=None: from_config
        )
        assert adapter.detect(explicit).path == explicit

    def test_no_config_leaves_detection_exactly_as_it_was(
        self, adapter: adapters.Adapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adapter_base, "configured_path_for", lambda name, root=None: None)
        probe = adapter.detect()
        assert probe.routes_tried[0] == "configured-path"
        assert len(probe.routes_tried) > 1 or probe.status is ToolStatus.PRESENT


# ---------------------------------------------------------------------------
# Specification for the first delegated batch, written 2026-09-16 BEFORE the code.
#
# Steps 14.1 (Gmsh), 14.2 (Elmer) and 15.1 (ParaView) each register a fourth, fifth and sixth adapter
# against the existing ABC. The bulk of each one's contract is already covered: every test above is
# parameterised over `adapters.ADAPTERS`, so registering an adapter subjects it to the five
# obligations, deterministic generation, the parse refusals, immutability, attribution and the doctor
# matrix without a line being written here.
#
# What follows is only the per-tool part the generic contract cannot know: what each one generates,
# what its result file carries, and the one thing each tool gets wrong if nobody says otherwise.
# ---------------------------------------------------------------------------


class TestRunWithNoInputsNeverClaimsToHaveRun:
    """``run(())`` cannot return ``COMPLETED``, whatever is installed.

    Added with the batch because it is about to matter. Three adapters registered here wrap **headless**
    tools, so unlike FEMM and the SPICE pair they *could* legitimately invoke something. That would make
    ``test_no_adapter_claims_to_have_run_anything`` pass or fail depending on what the operator has
    installed, and a test whose result depends on install state is not a test.

    The rule is also simply correct: with an empty inputs tuple there is nothing to run, so reporting a
    completed run would be *principle 3, never report success over unperformed work*, in its purest form
    — success over literally no work.
    """

    def test_empty_inputs_never_completes(self, adapter: adapters.Adapter) -> None:
        result = adapter.run(())
        assert (
            result.outcome is not adapters.RunOutcome.COMPLETED
        ), f"{adapter.name} reported COMPLETED for an empty input set. There was nothing to run."
        assert result.detail.strip()


class TestGmshAdapter:
    """14.1 — the mesher. Not a CFD route: every CFD route needs it."""

    @property
    def gmsh(self) -> adapters.Adapter:
        return adapters.adapter_for("gmsh")

    def test_it_is_registered(self) -> None:
        assert self.gmsh.name == "gmsh"

    def test_it_generates_a_geo_file(self, tmp_path: Path) -> None:
        written = self.gmsh.generate(tmp_path)
        names = [p.name for p in written]
        assert any(n.endswith(".geo") for n in names), f"no .geo among {names}"

    def test_the_geo_is_built_from_the_profile(self, tmp_path: Path) -> None:
        """No typed geometry. The mesher describes the same cell the physics does.

        *Principle 4, two representations of one thing will drift* — a `.geo` carrying its own
        dimensions would mesh a geometry the rest of the suite is not analysing, and both would keep
        working while they disagreed.
        """
        geo = next(p for p in self.gmsh.generate(tmp_path) if p.name.endswith(".geo"))
        text = geo.read_text(encoding="utf-8")
        design = default_design()
        # The gap is the defining dimension of the cell and must appear, in metres or millimetres.
        assert (
            repr(design.d_gap_m) in text
            or repr(design.d_gap_m * 1e3) in text
            or f"{design.d_gap_m:.6g}" in text
            or f"{design.d_gap_m * 1e3:.6g}" in text
        ), "the .geo does not carry the profile's gap; it is describing a geometry of its own"

    def test_it_asks_for_a_version_with_a_single_dash(self) -> None:
        """``-version``. Both earlier revisions of the detect table had ``--version``, which Gmsh
        rejects, and the failure is silent: an installed Gmsh reports no version."""
        assert self.gmsh.tool_spec.version_args == ("-version",)

    def test_its_result_values_are_mesh_statistics(self) -> None:
        """A mesher reports a mesh, not a field. Counts and a quality metric, nothing physical.

        An adapter claiming to read a velocity out of Gmsh would be claiming the mesher solved
        something.
        """
        expected = set(self.gmsh.expected_values)
        assert "n_nodes" in expected
        assert "n_elements" in expected
        assert "min_element_quality" in expected

    def test_it_is_not_manual_only(self) -> None:
        """Gmsh runs headless, which is why it is the one tool here that could reach COMPLETED."""
        assert self.gmsh.tool_spec.manual_only is False


class TestElmerAdapter:
    """14.2 — the fidelity CFD route, and one of the competing routes the plan will not pick yet."""

    @property
    def elmer(self) -> adapters.Adapter:
        return adapters.adapter_for("elmer")

    def test_it_is_registered(self) -> None:
        assert self.elmer.name == "elmer"

    def test_it_generates_a_sif(self, tmp_path: Path) -> None:
        """ElmerSolver reads a Solver Input File. Without one there is nothing to run."""
        names = [p.name for p in self.elmer.generate(tmp_path)]
        assert any(n.endswith(".sif") for n in names), f"no .sif among {names}"

    def test_its_result_values_are_flow_quantities_with_units(self) -> None:
        expected = set(self.elmer.expected_values)
        assert any(n.endswith("_m_per_s") for n in expected), "no velocity in the read-back"
        assert any(n.endswith("_Pa") for n in expected), "no pressure in the read-back"

    def test_it_stays_unprobed_for_a_version_with_its_reason_intact(self) -> None:
        """The open question from the detect ledger, kept open rather than guessed.

        ``ElmerSolver``'s behaviour when invoked without a ``.sif`` is not established here, and a wrong
        switch risks a solver that waits on input rather than exiting. An absent version degrades
        visibly; an invented switch does not. Closing this needs an Elmer installation, not more
        reading.
        """
        from ehdpsu import detect

        assert self.elmer.tool_spec.version_args == ()
        assert "elmer" in detect.TOOLS_WITHOUT_A_VERSION_PROBE
        assert "NOT VERIFIED" in detect.TOOLS_WITHOUT_A_VERSION_PROBE["elmer"]

    def test_its_capability_line_says_a_field_inherits_its_mesh(self) -> None:
        """The caveat belongs where an operator reads it, which is the ``doctor`` matrix.

        A CFD field carries no information about its own discretisation error without demonstrated mesh
        convergence, however smooth it renders — and on the operator's hardware the temptation will be
        to run a mesh that fits rather than one that converges.
        """
        assert "mesh" in self.elmer.capability.lower()


class TestParaviewAdapter:
    """15.1 — rendering. The only adapter whose output is an image rather than a number."""

    @property
    def paraview(self) -> adapters.Adapter:
        return adapters.adapter_for("paraview")

    def test_it_is_registered(self) -> None:
        assert self.paraview.name == "paraview"

    def test_it_generates_a_python_render_script(self, tmp_path: Path) -> None:
        """Scripted, not a saved GUI state. A render nobody can regenerate is not a result."""
        names = [p.name for p in self.paraview.generate(tmp_path)]
        assert any(n.endswith(".py") for n in names), f"no .py render script among {names}"

    def test_the_render_script_drives_pvpython_not_the_gui(self, tmp_path: Path) -> None:
        script = next(p for p in self.paraview.generate(tmp_path) if p.name.endswith(".py"))
        text = script.read_text(encoding="utf-8")
        assert "paraview" in text.lower(), "the script does not import the ParaView bindings"

    def test_it_is_detected_only_through_pvpython(self) -> None:
        """Listing ``paraview.exe`` would let a version probe open a window during pytest."""
        assert self.paraview.tool_spec.executables == ("pvpython.exe",)

    def test_its_result_values_describe_the_image_and_its_field_range(self) -> None:
        """The Task 15 test is that a render is non-degenerate with expected field ranges.

        So the read-back is the image dimensions and the scalar range: a render that came out 1x1, or
        with a flat field range, ran and produced nothing usable — the named parse hazard, in image
        form.
        """
        expected = set(self.paraview.expected_values)
        assert "image_width_px" in expected
        assert "image_height_px" in expected
        assert "field_range_min" in expected
        assert "field_range_max" in expected


class TestAttributionCoversTheNewAdapters:
    """19.3 — every wrapped tool is credited, and the credit distinguishes written from run."""

    @pytest.mark.parametrize("tool", ["Gmsh", "Elmer", "ParaView"])
    def test_the_tool_is_named_in_attributions(self, tool: str) -> None:
        assert tool in ATTRIBUTIONS.read_text(encoding="utf-8")

    def test_attributions_distinguishes_an_adapter_from_a_run(self) -> None:
        """A tool with an adapter and no successful run is not the same as one in use.

        Gmsh, Elmer and ParaView are still **not installed** and have **never been run** in this
        project. Recording them as tools the suite uses would be *principle 3, never report success
        over unperformed work*, in an attribution file — the document whose whole purpose is to be
        accurate about what this project stands on.
        """
        text = ATTRIBUTIONS.read_text(encoding="utf-8").lower()
        assert "not been run" in text or "never been run" in text or "not run" in text, (
            "ATTRIBUTIONS.md does not distinguish tools that have an adapter from tools that have "
            "actually been run"
        )
