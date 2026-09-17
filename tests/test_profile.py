"""Tests for the spec-scope-profile layer.

The profile is the seam: if it can be loaded wrong, mis-united, silently defaulted, or migrated
without saying so, then every number downstream inherits that. So validation is tested by
rejection — one test per way a profile can be malformed — rather than by a single happy path.

What is deliberately NOT tested here
------------------------------------
That the profile reproduces the MK0 figures. That lives in ``test_mk0_reproduction.py`` beside the
other reproduction claims, where it can be compared against the chain built from the old
``DesignParameters`` defaults in the same file.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import REFERENCE_PROFILE_PATH

from ehdpsu import profile as prof
from ehdpsu.basis import Basis

REPO_ROOT = Path(__file__).resolve().parents[1]
MK0_PATH = REFERENCE_PROFILE_PATH


@pytest.fixture(scope="module")
def mk0_raw() -> dict[str, Any]:
    """The tracked MK0 profile as a raw mapping."""
    return json.loads(MK0_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def raw(mk0_raw: dict[str, Any]) -> dict[str, Any]:
    """A fresh deep copy, so a rejection test can mutate it without affecting the next."""
    return copy.deepcopy(mk0_raw)


class TestSchemaShape:
    """The schema declaration itself, which everything else is checked against."""

    def test_field_names_are_unique(self) -> None:
        names = [spec.name for spec in prof.FIELDS]
        assert len(set(names)) == len(names)

    def test_every_field_belongs_to_a_declared_section(self) -> None:
        for spec in prof.FIELDS:
            assert spec.section in prof.SECTIONS

    def test_every_section_has_at_least_one_field(self) -> None:
        for section in prof.SECTIONS:
            assert any(spec.section == section for spec in prof.FIELDS)

    def test_every_field_declares_a_unit(self) -> None:
        # An empty unit is indistinguishable from a forgotten one, which is why dimensionless is
        # spelled "1".
        for spec in prof.FIELDS:
            assert spec.unit, f"{spec.name} declares no unit"

    def test_lengths_state_radius_or_diameter_or_are_unambiguous(self) -> None:
        """A metre-valued field must not be named in a way that leaves radius-vs-diameter open.

        The 29% onset-voltage split is the reason. ``r_`` and ``d_`` prefixes and ``L_`` for a
        length are the accepted forms; anything else has to be argued for.
        """
        for spec in prof.FIELDS:
            if spec.unit != "m":
                continue
            assert spec.name.startswith(("r_", "d_", "L_")), (
                f"{spec.name} is a length but its name does not begin r_ (radius), d_ "
                f"(distance/diameter) or L_ (length)."
            )

    def test_only_one_field_is_nullable(self) -> None:
        # Nullability is an escape hatch, and each one needs a documented derivation. If a second
        # appears, that is a decision rather than an oversight.
        nullable = [spec.name for spec in prof.FIELDS if spec.nullable]
        assert nullable == ["L_sec_H"]


class TestExemptionRegister:
    """The register the drift test reads. An undeclared exemption is the failure mode."""

    def test_register_is_populated(self) -> None:
        assert prof.DESIGN_VALUE_EXEMPTIONS

    def test_every_exemption_carries_a_reason(self) -> None:
        for key, reason in prof.DESIGN_VALUE_EXEMPTIONS.items():
            assert len(reason) > 20, f"{key} has no substantive reason"

    def test_physical_constants_are_exempt_and_design_values_are_not(self) -> None:
        keys = set(prof.DESIGN_VALUE_EXEMPTIONS)
        assert "ehdpsu.physics.EPS0" in keys
        # And nothing that IS a design value may be sitting in the register.
        for spec in prof.FIELDS:
            assert not any(
                spec.name in key for key in keys
            ), f"{spec.name} is a profile field and must not also be an exemption"


class TestTrackedProfile:
    """The shipped MK0 profile."""

    def test_the_reference_fixture_is_tracked(self) -> None:
        """The frozen MK0 fixture must exist in a clone: the regression suite loads it."""
        rel = REFERENCE_PROFILE_PATH.relative_to(REPO_ROOT).as_posix()
        out = subprocess.run(
            ["git", "ls-files", "--", rel],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            pytest.skip("git unavailable; cannot confirm the fixture is tracked")
        assert out.stdout.strip(), (
            f"{rel} is not tracked. The physics pins are compared against it, so a clone without "
            f"it cannot verify anything."
        )

    def test_the_profiles_directory_clones_empty(self) -> None:
        """No design may be committed to ``profiles/``.

        Chief Operator, 2026-09-15: the directory ships empty, and the operator's working profiles
        stay on disk and are backed up to Drive rather than pushed. Two reasons this needs a test
        rather than a habit:

        * The repository is intended to become public, so a working design reaching the remote is
          an exposure, not just untidiness.
        * **There is no set design point.** A committed profile would present a planning baseline
          as authoritative, and every clone would inherit it as though it were the design.

        Only ``README.md`` is permitted, so the directory exists with an explanation in it rather
        than being absent.
        """
        out = subprocess.run(
            ["git", "ls-files", "--", "profiles"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            pytest.skip("git unavailable; cannot confirm what is tracked under profiles/")
        tracked = sorted(line.strip() for line in out.stdout.splitlines() if line.strip())
        assert tracked == ["profiles/README.md"], (
            f"profiles/ tracks {tracked}; only profiles/README.md may be tracked. A design "
            f"committed here would reach the public remote and would look authoritative."
        )

    def test_a_profile_in_the_working_directory_is_ignored(self) -> None:
        """The ignore rule actually covers a ``.json`` in ``profiles/``.

        Checked with ``git check-ignore`` against a path that need not exist, because the negation
        for ``README.md`` sits directly beside the ignore rule and a mistake there is silent —
        ``.gitignore`` once carried ``!artifacts/.gitkeep`` with no matching ignore rule at all,
        which did nothing and let four generated files become tracked.
        """
        probe = "profiles/__ignore_probe__.json"
        code = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", probe],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        # 0 => ignored, 1 => not ignored, 128 => error
        assert code == 0, (
            f"{probe} is NOT ignored (check-ignore exit {code}). Working profiles would be one "
            f"`git add` away from the public remote."
        )

    def test_loads_and_validates(self) -> None:
        p = prof.load(MK0_PATH)
        assert p.profile_id == "mk0_benchtop_22kv"
        assert set(p.values) == set(prof.FIELDS_BY_NAME)

    def test_ceiling_is_claimed_and_that_is_correct(self) -> None:
        """Every design value is an assertion until the built article is measured.

        Asserted rather than left implicit, because the tempting edit is to raise a basis so the
        headline figures look better qualified than they are.
        """
        p = prof.load(MK0_PATH)
        assert p.ceiling() is Basis.CLAIMED
        for name in p.values:
            assert p.basis_of(name) is Basis.CLAIMED, name

    def test_no_field_claims_to_be_measured_yet(self) -> None:
        # This test is EXPECTED to change the day a micrometer touches the wire. The change should
        # be visible in a diff rather than silent.
        p = prof.load(MK0_PATH)
        assert not any(v.basis >= Basis.SOLVED for v in p.values.values())

    def test_provenance_records_the_basis_consequence(self) -> None:
        """The provenance block must say what the basis is and what it supersedes.

        A profile whose provenance omits the ceiling reads as though the numbers stand on their
        own. Keys are searched as well as values, since the block's structure carries meaning.
        """
        p = prof.load(MK0_PATH)
        text = " ".join(
            [*(k.lower() for k in p.provenance), *(str(v).lower() for v in p.provenance.values())]
        )
        assert "claimed" in text, "provenance does not state the basis"
        assert "ceiling" in text, "provenance does not state the propagation consequence"
        assert "supersede" in text, "provenance does not say what this profile replaces"

    def test_secondary_inductance_is_null_not_a_sentinel(self) -> None:
        # It was 0.0 in SpiceParams, meaning "derive me". A zero inductance is a physically
        # meaningful value, so the sentinel was indistinguishable from a real setting.
        p = prof.load(MK0_PATH)
        assert p.value("L_sec_H") is None
        with pytest.raises(prof.ProfileError, match="null"):
            p.required("L_sec_H")


class TestRoundTrip:
    def test_to_json_then_from_json_preserves_every_value_and_basis(self) -> None:
        original = prof.load(MK0_PATH)
        again = prof.from_json(original.to_json())
        assert again.values == original.values
        assert again.profile_id == original.profile_id
        assert again.provenance == original.provenance

    def test_serialisation_is_byte_stable(self) -> None:
        """Re-serialising the tracked file reproduces it exactly.

        Ordering comes from the schema, not from dict insertion order, so a profile edited by hand
        and re-saved produces a clean diff instead of a reordered file.
        """
        on_disk = MK0_PATH.read_text(encoding="utf-8")
        regenerated = json.dumps(prof.load(MK0_PATH).to_json(), indent=2) + "\n"
        assert regenerated == on_disk

    def test_save_refuses_to_clobber_without_permission(self, tmp_path: Path) -> None:
        p = prof.load(MK0_PATH)
        target = tmp_path / "copy.json"
        p.save(target)
        with pytest.raises(prof.ProfileError, match="exists"):
            p.save(target)
        p.save(target, overwrite=True)  # explicit is fine

    def test_load_named_resolves_by_id(self) -> None:
        p = prof.load_named("mk0_benchtop_22kv", REPO_ROOT / "profiles")
        assert p.profile_id == "mk0_benchtop_22kv"


class TestValidationRejects:
    """One test per way a profile can be wrong. Nothing is defaulted."""

    def test_missing_field(self, raw: dict[str, Any]) -> None:
        del raw["design"]["emitter"]["L_wire_m"]
        with pytest.raises(prof.ProfileError, match="missing fields"):
            prof.from_json(raw)

    def test_unknown_field(self, raw: dict[str, Any]) -> None:
        raw["design"]["emitter"]["r_wire_mm"] = {
            "value": 0.025,
            "unit": "m",
            "basis": "claimed",
            "kind": "choice",
        }
        with pytest.raises(prof.ProfileError, match="unknown fields"):
            prof.from_json(raw)

    def test_missing_section(self, raw: dict[str, Any]) -> None:
        del raw["design"]["rectifier"]
        with pytest.raises(prof.ProfileError, match="missing design sections"):
            prof.from_json(raw)

    def test_unknown_section(self, raw: dict[str, Any]) -> None:
        raw["design"]["cooling"] = {}
        with pytest.raises(prof.ProfileError, match="unknown design sections"):
            prof.from_json(raw)

    def test_wrong_unit(self, raw: dict[str, Any]) -> None:
        # The failure this schema exists for: 25 um expressed in mm while still called _m.
        raw["design"]["emitter"]["r_wire_m"]["unit"] = "mm"
        with pytest.raises(prof.ProfileError, match="unit"):
            prof.from_json(raw)

    def test_wrong_kind(self, raw: dict[str, Any]) -> None:
        raw["design"]["emitter"]["r_wire_m"]["kind"] = "property"
        with pytest.raises(prof.ProfileError, match="kind"):
            prof.from_json(raw)

    def test_unknown_basis_label(self, raw: dict[str, Any]) -> None:
        raw["design"]["emitter"]["r_wire_m"]["basis"] = "validated"
        with pytest.raises(prof.ProfileError, match="unknown basis"):
            prof.from_json(raw)

    def test_null_in_a_non_nullable_field(self, raw: dict[str, Any]) -> None:
        raw["design"]["gap"]["d_gap_m"]["value"] = None
        with pytest.raises(prof.ProfileError, match="null is not permitted"):
            prof.from_json(raw)

    def test_boolean_is_not_a_design_value(self, raw: dict[str, Any]) -> None:
        # bool is a subclass of int in Python, so True would otherwise pass an integer check.
        raw["design"]["multiplier"]["N_stages"]["value"] = True
        with pytest.raises(prof.ProfileError, match="boolean"):
            prof.from_json(raw)

    def test_fractional_stage_count(self, raw: dict[str, Any]) -> None:
        raw["design"]["multiplier"]["N_stages"]["value"] = 5.5
        with pytest.raises(prof.ProfileError, match="integer count"):
            prof.from_json(raw)

    def test_non_finite_value(self, raw: dict[str, Any]) -> None:
        raw["design"]["supply"]["V_op_V"]["value"] = float("inf")
        with pytest.raises(prof.ProfileError, match="finite"):
            prof.from_json(raw)

    def test_non_numeric_value(self, raw: dict[str, Any]) -> None:
        raw["design"]["supply"]["V_op_V"]["value"] = "22kV"
        with pytest.raises(prof.ProfileError, match="expected a number"):
            prof.from_json(raw)

    def test_unknown_key_inside_a_value_node(self, raw: dict[str, Any]) -> None:
        # Catches a typo like "bais" that would otherwise be ignored, leaving the real basis
        # silently defaulted.
        raw["design"]["supply"]["V_op_V"]["bais"] = "measured"
        with pytest.raises(prof.ProfileError, match="unknown keys"):
            prof.from_json(raw)

    def test_missing_key_inside_a_value_node(self, raw: dict[str, Any]) -> None:
        del raw["design"]["supply"]["V_op_V"]["basis"]
        with pytest.raises(prof.ProfileError, match="missing 'basis'"):
            prof.from_json(raw)

    def test_unknown_top_level_key(self, raw: dict[str, Any]) -> None:
        raw["derived"] = {"thrust_N": 0.0938}
        with pytest.raises(prof.ProfileError, match="unknown top-level"):
            prof.from_json(raw)

    def test_missing_top_level_key(self, raw: dict[str, Any]) -> None:
        del raw["title"]
        with pytest.raises(prof.ProfileError, match="missing top-level"):
            prof.from_json(raw)

    def test_load_reports_bad_json_with_the_path(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(prof.ProfileError, match="not valid JSON"):
            prof.load(bad)

    def test_load_reports_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(prof.ProfileError, match="no profile at"):
            prof.load(tmp_path / "absent.json")


class TestMigration:
    """A profile that loads under a newer schema without saying what changed is a silent
    reinterpretation of the operator's design intent."""

    def test_non_integer_version_is_refused(self, raw: dict[str, Any]) -> None:
        raw["schema_version"] = "1"
        with pytest.raises(prof.ProfileError, match="must be an integer"):
            prof.from_json(raw)

    def test_newer_schema_is_refused_rather_than_read_loosely(self, raw: dict[str, Any]) -> None:
        # Reading a newer profile would silently drop fields this build does not know about.
        raw["schema_version"] = prof.SCHEMA_VERSION + 1
        with pytest.raises(prof.ProfileError, match="newer schema"):
            prof.from_json(raw)

    def test_older_version_without_a_registered_migration_is_refused(
        self, raw: dict[str, Any]
    ) -> None:
        raw["schema_version"] = 0
        with pytest.raises(prof.ProfileError, match="no migration registered"):
            prof.from_json(raw)

    def test_the_migration_mechanism_works(self, raw: dict[str, Any]) -> None:
        """Exercised with an INJECTED synthetic migration, and labelled as such.

        There is no v0 of this schema, so there is no real migration to run. Proving the mechanism
        with a fake is honest; inventing a v0 that never existed to make the test look real would
        not be. The first genuine bump then finds working machinery rather than writing it under
        pressure.
        """
        raw["schema_version"] = 0
        applied_marker = {"ran": False}

        def fake_v0_to_v1(doc: dict[str, Any]) -> dict[str, Any]:
            applied_marker["ran"] = True
            return doc

        migrated, applied = prof.migrate_raw(raw, {0: ("synthetic-v0-to-v1", fake_v0_to_v1)})
        assert applied_marker["ran"] is True
        assert applied == ("synthetic-v0-to-v1",)
        assert migrated["schema_version"] == prof.SCHEMA_VERSION

    def test_current_version_applies_nothing(self) -> None:
        p = prof.load(MK0_PATH)
        assert p.migrations_applied == ()

    def test_migration_can_be_disabled_for_a_strict_read(self, raw: dict[str, Any]) -> None:
        raw["schema_version"] = 0
        with pytest.raises(prof.ProfileError, match="migration was disabled"):
            prof.from_json(raw, migrate=False)


class TestAccessors:
    def test_unknown_field_name_raises_at_the_read(self) -> None:
        p = prof.load(MK0_PATH)
        with pytest.raises(prof.ProfileError, match="unknown design field"):
            p.value("r_wire_mm")
        with pytest.raises(prof.ProfileError, match="unknown design field"):
            p.basis_of("nope")

    def test_count_refuses_a_float_typed_field(self) -> None:
        p = prof.load(MK0_PATH)
        assert p.count("N_stages") == 5
        with pytest.raises(prof.ProfileError, match="not an integer-typed field"):
            p.count("V_op_V")

    def test_section_returns_only_that_section(self) -> None:
        p = prof.load(MK0_PATH)
        emitter = p.section("emitter")
        assert set(emitter) == {"r_wire_m", "L_wire_m", "m_rough_factor"}
        with pytest.raises(prof.ProfileError, match="unknown section"):
            p.section("cooling")

    def test_ceiling_over_a_subset(self) -> None:
        p = prof.load(MK0_PATH)
        assert p.ceiling(["r_wire_m", "d_gap_m"]) is Basis.CLAIMED


class TestDiff:
    def test_identical_profiles_diff_empty(self) -> None:
        assert prof.diff(prof.load(MK0_PATH), prof.load(MK0_PATH)) == []

    def test_changed_value_is_reported_with_its_ratio(self, raw: dict[str, Any]) -> None:
        left = prof.load(MK0_PATH)
        raw["design"]["gap"]["d_gap_m"]["value"] = 0.0024
        right = prof.from_json(raw)

        changes = prof.diff(left, right)
        assert [c.name for c in changes] == ["d_gap_m"]
        assert changes[0].ratio is not None
        assert abs(changes[0].ratio - 0.2) < 1e-12

    def test_changed_basis_alone_is_a_difference(self, raw: dict[str, Any]) -> None:
        # The value is the same and its standing is not. That is exactly the change worth seeing.
        left = prof.load(MK0_PATH)
        raw["design"]["gap"]["d_gap_m"]["basis"] = "measured"
        right = prof.from_json(raw)

        changes = prof.diff(left, right)
        assert [c.name for c in changes] == ["d_gap_m"]
        assert changes[0].left_basis is Basis.CLAIMED
        assert changes[0].right_basis is Basis.MEASURED
        assert changes[0].ratio == 1.0

    def test_ratio_is_none_when_it_would_be_meaningless(self, raw: dict[str, Any]) -> None:
        # Null on one side, so there is no ratio to report. Reporting 0 or 1 would be a number
        # somebody could act on.
        left = prof.load(MK0_PATH)
        raw["design"]["driver"]["L_sec_H"]["value"] = 0.0432
        right = prof.from_json(raw)

        changes = prof.diff(left, right)
        assert [c.name for c in changes] == ["L_sec_H"]
        assert changes[0].ratio is None

    def test_diff_is_in_schema_order(self, raw: dict[str, Any]) -> None:
        left = prof.load(MK0_PATH)
        raw["design"]["rectifier"]["diode_n"]["value"] = 2.5
        raw["design"]["emitter"]["L_wire_m"]["value"] = 0.2
        right = prof.from_json(raw)

        names = [c.name for c in prof.diff(left, right)]
        order = [spec.name for spec in prof.FIELDS]
        assert names == sorted(names, key=order.index)
