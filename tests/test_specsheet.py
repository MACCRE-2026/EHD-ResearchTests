"""Specification for the spec-sheet generator — plan step 11.2, batch 2 step C.

Written 2026-09-18 before the implementation.

This step sits directly on the project's central failure mode, which is why it is in this batch rather
than a later one. A spec sheet is **the artifact most likely to be quoted by someone who did not read
the derivation** — a funder, a reviewer, the author six weeks later. So it is where a dropped caveat
does the most damage, and where a generator that produces a *tidy* table is most tempting.

The three properties that matter, in order
------------------------------------------
1. **Every number is generated, never typed.** A hand-entered figure in a document is an unchecked
   claim with no reviewer. *Principle 5, specifications drift from implementations unless mechanically
   checked.*
2. **An upper bound is labelled in its own row**, not once in a footnote. ``T = I·d/µ`` is a
   mobility-limited ceiling assuming every ion transfers all its momentum with no drag; real thrust is
   lower. A ceiling shown without its label becomes a prediction the moment it is quoted.
3. **The band and the basis travel with every figure.** Because ``k_geo`` is a parallel-plate
   coefficient standing in for a wire-to-plane emitter, current, power, thrust and efficiency all
   inherit its roughly 10x band. Reporting any of them as a tight figure is laundering whether or not
   anyone intended it.

``OperatingPoint`` already carries all of this — each figure is a ``Quantity`` with ``band``, ``basis``
and ``is_upper_bound``, and ``Quantity.describe()`` renders them together. **The generator's job is to
not lose it.** A formatter that reaches past ``describe()`` to print a bare ``value`` is the defect
this file exists to catch.

Required interface
------------------
``ehdpsu.specsheet.build_spec_sheet(profile: Profile) -> str`` returning markdown, plus a CLI verb
``ehdsuite specsheet <profile-id-or-path>`` that prints exactly what the library returns.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import REFERENCE_PROFILE_PATH

from ehdpsu import cli
from ehdpsu import profile as prof
from ehdpsu.basis import may_be_called_validated
from ehdpsu.operating_point import operating_point

REPO_ROOT = Path(__file__).resolve().parents[1]

UPPER_BOUND_FIGURES = ("thrust", "efficiency")


def _specsheet() -> Any:
    """Import the module under test dynamically.

    Two deliberate choices, both about what the implementing seat sees when it starts.

    **Not a module-level import**, because ``ehdpsu.specsheet`` does not exist yet and a failed import
    at module scope **aborts collection for the whole file** — handing the seat "1 error during
    collection" instead of a list of requirements. One ``ImportError`` reducing a suite to a useless
    report is a recorded hazard in this project; no reason to reproduce it inside the specification.

    **And ``importlib`` rather than ``from ehdpsu import specsheet``**, because both mypy and pyright
    resolve that statically and fail on a module that is not there yet. The Gate runs them *before*
    pytest and would abort at the type-check stage, hiding the 16 test failures that are the actual
    specification. Resolved dynamically, the only red is pytest.
    """
    try:
        return importlib.import_module("ehdpsu.specsheet")
    except ModuleNotFoundError as exc:  # pragma: no cover - the pre-implementation state
        raise AssertionError(
            "ehdpsu.specsheet does not exist. Batch 2 step C creates it, exposing "
            "build_spec_sheet(profile) -> str."
        ) from exc


def _sheet() -> str:
    """The generated sheet for the frozen MK0 fixture."""
    return _specsheet().build_spec_sheet(prof.load(REFERENCE_PROFILE_PATH))


def _number_tokens(text: str) -> set[str]:
    """Numeric-looking tokens, normalised enough to compare across formatting."""
    return {m.group(0) for m in re.finditer(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)}


class TestItGeneratesAtAll:
    def test_build_spec_sheet_takes_a_profile_and_returns_markdown(self) -> None:
        sheet = _sheet()
        assert sheet.strip()
        assert sheet.lstrip().startswith("#"), "the sheet has no markdown heading"

    def test_it_names_the_profile_it_describes(self) -> None:
        """A sheet that does not say which design it is for is a sheet for any design."""
        assert prof.load(REFERENCE_PROFILE_PATH).profile_id in _sheet()

    def test_it_is_deterministic(self) -> None:
        """No timestamp, no dict-ordering wobble.

        A sheet that differs between two runs cannot be diffed, and a diff nobody trusts is a
        document nobody checks.
        """
        loaded = prof.load(REFERENCE_PROFILE_PATH)
        build = _specsheet().build_spec_sheet
        assert build(loaded) == build(loaded)


class TestEveryNumberIsGenerated:
    def test_every_derived_figure_appears(self) -> None:
        """All eleven figures from ``OperatingPoint``, not a chosen subset.

        A sheet that silently omits ``breakdown_margin`` is a sheet that omits the arc-over risk.
        """
        sheet = _sheet()
        point = operating_point(prof.load(REFERENCE_PROFILE_PATH))
        missing = [name for name in point.as_dict() if name not in sheet]
        assert not missing, f"figures absent from the sheet: {missing}"

    def test_no_number_in_the_sheet_is_absent_from_the_computation(self) -> None:
        """Every numeric token traces to the profile or the operating point.

        The mechanical form of "generated, never typed". Small integers and the schema version are
        excluded because they are structure — table widths, list markers, a stage count — rather than
        measurements.

        **Amended 2026-09-18, by the planner who wrote it.** As first written this test and
        ``test_it_names_the_profile_it_describes`` were **mutually unsatisfiable**, and no
        implementation could have passed both. One requires ``mk0_benchtop_22kv`` to appear in the
        sheet; the other then read the ``22`` inside that identifier as an ungenerated number. The
        implementing seat correctly reported the contradiction rather than deleting either test or
        weakening the generator to dodge it.

        The resolution is that a **profile id is a label, not a figure**. Digits inside it are part
        of a name the operator chose, carry no unit and are not read as a quantity by anything. So
        the id is removed from the text before tokenising — narrowing *what counts as a number*,
        which is the test's own definition, rather than widening ``allowed``, which would have let a
        genuinely typed ``22`` through anywhere in the document.
        """
        sheet = _sheet()
        loaded = prof.load(REFERENCE_PROFILE_PATH)
        point = operating_point(loaded)

        # The id is asserted present by test_it_names_the_profile_it_describes; see the docstring.
        tokenisable = sheet.replace(loaded.profile_id, "")

        allowed: set[str] = set()
        for q in point.as_dict().values():
            allowed.update(_number_tokens(q.describe()))
        for spec in prof.FIELDS:
            value = loaded.value(spec.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                allowed.update(_number_tokens(f"{value!r} {value:.6g} {value:g}"))
        allowed.update(str(n) for n in range(13))
        allowed.add(str(prof.SCHEMA_VERSION))

        stray = sorted(t for t in _number_tokens(tokenisable) if t not in allowed)
        assert not stray, (
            f"numeric tokens in the sheet that come from neither the profile nor the operating "
            f"point: {stray}. Every number in a document is generated, never typed."
        )


class TestTheUpperBoundLabelSurvives:
    @pytest.mark.parametrize("figure", UPPER_BOUND_FIGURES)
    def test_the_label_is_on_the_figures_own_row(self, figure: str) -> None:
        """Not in a footnote. On the line carrying the number.

        Strict about *placement* rather than presence, because presence somewhere in the document is
        exactly the weaker property that lets a table row be quoted without its caveat.
        """
        rows = [ln for ln in _sheet().splitlines() if figure in ln]
        assert rows, f"no row mentions {figure}"
        assert any(
            "UPPER BOUND" in ln.upper() for ln in rows
        ), f"no row mentioning {figure} carries an upper-bound label. Rows found: {rows}"

    def test_the_sheet_explains_why_thrust_is_a_ceiling(self) -> None:
        """The label without the reason is jargon; the reason is what makes it actionable."""
        lowered = _sheet().lower()
        assert "momentum" in lowered
        assert (
            "lower" in lowered
        ), "the sheet does not say that real thrust is LOWER than the figure shown"

    def test_no_non_bound_figure_is_labelled_a_bound(self) -> None:
        """Labelling everything a ceiling would make the label meaningless.

        ``v_onset`` and ``e_peek`` are cited closed forms, not bounds. If they carried the label, a
        reader would stop reading it anywhere.
        """
        sheet = _sheet()
        point = operating_point(prof.load(REFERENCE_PROFILE_PATH))
        for name, q in point.as_dict().items():
            if q.is_upper_bound:
                continue
            rows = [ln for ln in sheet.splitlines() if name in ln]
            assert not any(
                "UPPER BOUND" in ln.upper() for ln in rows
            ), f"{name} is not an upper bound but its row is labelled as one"


class TestBandAndBasisTravelWithEveryFigure:
    def test_every_figure_row_carries_its_basis(self) -> None:
        sheet = _sheet()
        point = operating_point(prof.load(REFERENCE_PROFILE_PATH))
        for name, q in point.as_dict().items():
            rows = [ln for ln in sheet.splitlines() if name in ln]
            assert any(q.basis.label in ln for ln in rows), (
                f"{name}'s row does not state its basis ({q.basis.label}). A number without its "
                f"basis is a number whose provenance the reader has to guess."
            )

    def test_the_placeholder_band_is_visible_on_the_figures_that_inherit_it(self) -> None:
        """``k_geo``'s band reaches current, power and thrust, and the sheet must show that.

        A tight-looking thrust figure beside a banded ``k_geo`` is the laundering this project exists
        to catch, and a spec sheet is where it would be read.
        """
        sheet = _sheet()
        point = operating_point(prof.load(REFERENCE_PROFILE_PATH))
        for name in ("i_ion", "power", "thrust"):
            q = point.as_dict()[name]
            assert not q.band.is_exact, f"{name} unexpectedly has an exact band; test needs review"
            rows = [ln for ln in sheet.splitlines() if name in ln]
            assert any(
                "x" in ln.lower() or "band" in ln.lower() for ln in rows
            ), f"{name}'s row shows no band. It inherits k_geo's roughly 10x placeholder band."

    def test_the_sheet_states_the_ceiling(self) -> None:
        point = operating_point(prof.load(REFERENCE_PROFILE_PATH))
        assert point.ceiling.label in _sheet()

    def test_nothing_in_the_sheet_claims_to_be_validated(self) -> None:
        """A ``claimed`` ceiling cannot produce a validated document.

        Checked as a word ban rather than a basis check, because the failure mode is prose: the
        figures can be correctly labelled while a heading says "validated design".
        """
        point = operating_point(prof.load(REFERENCE_PROFILE_PATH))
        assert not may_be_called_validated(
            point.ceiling
        ), "fixture ceiling changed; test needs review"
        lowered = _sheet().lower()
        for banned in ("validated", "proven", "confirmed", "demonstrated"):
            assert banned not in lowered, (
                f"the sheet uses {banned!r} while its ceiling is {point.ceiling.label}. "
                f"physics-honesty.md bans exactly these four words for a figure below `solved`."
            )


class TestItRefusesRatherThanInvents:
    def test_a_missing_profile_is_an_error_not_an_empty_sheet(self, tmp_path: Path) -> None:
        with pytest.raises((FileNotFoundError, prof.ProfileError)):
            _specsheet().build_spec_sheet(prof.load(tmp_path / "nope.json"))

    def test_the_cli_verb_reports_a_missing_profile(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["specsheet", "definitely-not-a-profile"]) == cli.EXIT_NOT_FOUND
        assert capsys.readouterr().err.strip()

    def test_the_cli_verb_emits_the_same_sheet_as_the_library(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*The GUI wraps the CLI, and the CLI wraps the library.* One derivation, three surfaces.

        A verb that formatted independently would be a second representation of the sheet.
        """
        assert cli.main(["specsheet", str(REFERENCE_PROFILE_PATH)]) == cli.EXIT_OK
        printed = capsys.readouterr().out
        assert _sheet().strip() in printed
