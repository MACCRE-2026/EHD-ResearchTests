"""Specification for the milestone snapshot — CRSDL Task 2, Batch A.

Written 2026-09-19 before the implementation.

``backup_datacenter.ps1`` has existed since Task 2 of the MK era and **has never been executed**.
Writing these tests is the first time anything has examined what it actually declares, and three
gaps fell out immediately. The script is good — the gaps are all of the same kind: it was written to
back up the *datacenter*, and the CRSDL epoch needs it to back up a **milestone**, which is the
datacenter *plus the codebase*.

What is being specified
-----------------------
1. **A code source set, excluding ``.venv``.** The declared sources are ``artifacts/`` tiers and
   ``.kiro/`` directories. The codebase is absent, so a "milestone snapshot" taken with this script
   today would contain no code. The operator asked for a no-venv codebase container; that is a new
   declared source, not a flag.
2. **``*.log`` currently excludes run evidence.** The exclusion list was aimed at noise, and it now
   also excludes ``OBSERVED_2026-09-18_ltspice_gui_parse_failure.log`` — the first observation of a
   real defect, deliberately preserved in the solver-run tier. An exclusion that removes evidence is
   a defect in the exclusion, not in the evidence.
3. **The transcript tier is ``Required`` and CRSDL Task 1 empties it.** Removing
   ``artifacts/01_Collaborator_Conversations`` outright would make every future run exit 3
   ``SOURCE-MISSING``. The tier must survive holding its removal-reference note, or its declared
   ``Kind`` must change. Recorded here because the collision is between two tasks and neither would
   notice it alone.

The rest of this module is **regression guarding**, not new work: the destination rule, the
verify-from-destination rule, the asymmetric in-flight guard and the distinct exit codes are all
already correct, and they are the properties most likely to be casually broken by someone adding a
source set.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".kiro" / "governance" / "backup_datacenter.ps1"


@pytest.fixture(scope="module")
def script_text() -> str:
    assert SCRIPT.is_file(), f"{SCRIPT} is missing"
    return SCRIPT.read_text(encoding="utf-8")


def _declared_source_rels(text: str) -> list[str]:
    """Every ``Rel = '<path>'`` in the declared ``$sources`` array."""
    block = re.search(r"\$sources\s*=\s*@\((.*?)\n\)", text, flags=re.DOTALL)
    assert block, "could not locate the $sources declaration; its shape changed"
    return re.findall(r"Rel\s*=\s*'([^']+)'", block.group(1))


def _excluded_globs(text: str) -> list[str]:
    block = re.search(r"\$excludedGlobs\s*=\s*@\(([^)]*)\)", text)
    assert block, "could not locate the $excludedGlobs declaration"
    return re.findall(r"'([^']+)'", block.group(1))


class TestTheMilestoneNeedsTheCodebase:
    """A milestone snapshot with no code in it is not a milestone."""

    def test_the_codebase_is_a_declared_source(self, script_text: str) -> None:
        """``src/`` must be in the declared set.

        The operator's requirement is a code container that serves as a rollback point for the
        epoch. Today the script would produce a snapshot of governance and artifacts with no code,
        which would restore a plan describing software that is not in the snapshot.
        """
        rels = _declared_source_rels(script_text)
        assert any(
            r.rstrip("/").endswith("src") or r.rstrip("/") == "src" for r in rels
        ), f"no source set names src/; declared sets are {rels}"

    def test_the_tests_are_a_declared_source(self, script_text: str) -> None:
        """Tests are the specification, so a snapshot without them cannot be judged.

        Every delegated task in this project is tests-first. A restored codebase whose tests were
        not captured has lost the thing that says what it was supposed to do.
        """
        rels = _declared_source_rels(script_text)
        assert any(r.rstrip("/").endswith("tests") for r in rels), (
            f"no source set names tests/; a restored snapshot would carry code with no "
            f"specification. Declared sets are {rels}"
        )

    def test_the_venv_is_excluded_and_the_exclusion_says_why(self, script_text: str) -> None:
        """``.venv`` is ~408 MB of reconstructible third-party code.

        Explicitly excluded per the operator's instruction, and the exclusion must be *declared*
        rather than achieved by accident of which directories were listed — an accidental exclusion
        is indistinguishable from an oversight, which is the pattern
        ``TOOLS_WITHOUT_DEFAULT_PATHS`` and ``DESIGN_VALUE_EXEMPTIONS`` both exist to break.
        """
        assert ".venv" in script_text, (
            ".venv is not mentioned anywhere in the script. It must be excluded by name with a "
            "stated reason, not left out by accident of the source list."
        )
        assert re.search(
            r"(?i)\.venv.{0,400}?(reconstruct|regenerat|pip|requirements|lock)",
            script_text,
            flags=re.DOTALL,
        ), (
            ".venv is mentioned but no nearby text says why excluding it is safe. The reason is "
            "that it is reconstructible from requirements.lock; say so."
        )


class TestExclusionsMustNotRemoveEvidence:
    def test_the_log_glob_does_not_swallow_solver_run_evidence(self, script_text: str) -> None:
        """``*.log`` was aimed at noise and now also excludes a preserved run observation.

        ``artifacts/05_Solver_Runs/OBSERVED_2026-09-18_ltspice_gui_parse_failure.log`` is the
        operator's own LTspice log capturing the first sighting of the ``M1``-versus-``S1`` netlist
        defect. It is evidence, it is deliberately retained, and the current glob means no backup
        would ever contain it.

        Either narrow the glob so the solver-run tier is spared, or drop it and exclude the noisy
        sources by name. Renaming the evidence to dodge a backup rule would be the wrong fix — the
        rule is what is wrong.
        """
        globs = _excluded_globs(script_text)
        if "*.log" not in globs:
            return  # resolved by removing the blanket glob
        assert re.search(r"(?i)05_solver_runs|solver.run", script_text), (
            f"excludedGlobs still contains a blanket '*.log' ({globs}) and nothing in the script "
            f"spares the solver-run tier, so preserved run evidence would never be captured."
        )


class TestTheTranscriptTierCollisionWithTask1:
    def test_a_required_tier_that_task_1_empties_is_reconciled(self, script_text: str) -> None:
        """CRSDL Task 1 removes the transcripts; this script calls that tier ``Required``.

        If Task 1 deletes ``artifacts/01_Collaborator_Conversations`` rather than emptying it, every
        subsequent backup exits 3 ``SOURCE-MISSING`` and the operator learns about it at the worst
        possible moment. Two acceptable resolutions, and this test accepts either:

        * the tier survives, holding its removal-reference note, and stays ``Required``; or
        * its declared ``Kind`` becomes ``Optional`` with the reason recorded in the script.

        What is not acceptable is leaving a ``Required`` declaration pointing at a directory another
        task is about to remove.
        """
        block = re.search(
            r"Rel\s*=\s*'artifacts/01_Collaborator_Conversations';\s*Kind\s*=\s*'(\w+)'",
            script_text,
        )
        assert block, "the collaborator-conversations source declaration could not be located"
        kind = block.group(1)
        tier = REPO_ROOT / "artifacts" / "01_Collaborator_Conversations"

        if kind == "Required":
            assert tier.is_dir(), (
                "artifacts/01_Collaborator_Conversations is declared Required but does not exist, "
                "so every backup run exits 3 SOURCE-MISSING. Either keep the directory (holding "
                "the transcript-removal note) or change its declared Kind to Optional with a "
                "reason."
            )
            assert any(tier.iterdir()), (
                "the tier is declared Required and exists but is empty. Leave the "
                "transcript-removal reference note in it so the tier still means something."
            )


class TestPropertiesAlreadyCorrectAndWorthGuarding:
    """These pass today. They are the ones a new source set is most likely to break."""

    def test_destination_inside_the_repo_is_refused(self, script_text: str) -> None:
        """A snapshot inside the Drive-synced root shares the failure domain it exists to survive."""
        assert "destIsUnderRepo" in script_text
        assert "DEST-UNWRITABLE" in script_text

    def test_verification_rehashes_from_the_destination(self, script_text: str) -> None:
        """Hashing the source twice verifies nothing. *Principle 3.*"""
        assert re.search(
            r"(?i)re-?hash.{0,200}destination", script_text, flags=re.DOTALL
        ), "nothing in the script states that verification reads the destination"
        assert (
            "MISSING-AFTER-COPY" in script_text
        ), "a file absent after copying must be its own distinct outcome, not a hash mismatch"

    def test_download_staging_blocks_and_upload_staging_does_not(self, script_text: str) -> None:
        """The two Drive staging directories are not symmetric.

        Uploads *read* the tree; downloads *write* into it. Only the second moves the source under
        a copy. Collapsing them made the script unusable during active work, which is exactly when
        a backup is wanted.
        """
        assert "SOURCE-IN-FLIGHT" in script_text
        assert ".tmp.drivedownload" in script_text and ".tmp.driveupload" in script_text
        assert re.search(
            r"downloadCount\s*-gt\s*0", script_text
        ), "the in-flight refusal must be gated on the DOWNLOAD count only"
        assert not re.search(
            r"uploadCount\s*-gt\s*0\s*-and\s*-not\s*\$IgnoreInFlight", script_text
        ), "upload staging must not block; it does not modify the source"

    def test_nothing_copied_is_its_own_terminal_state(self, script_text: str) -> None:
        """Zero files copied is not a success with a small number in it."""
        assert "NOTHING-COPIED" in script_text

    def test_no_database_is_captured(self, script_text: str) -> None:
        """*Principle 8, atomicity is a property of an artifact set, not a file.*"""
        globs = _excluded_globs(script_text)
        for pattern in ("*.db", "*.db-wal", "*.db-shm"):
            assert (
                pattern in globs
            ), f"{pattern} must be excluded; a .db without its -wal is corrupt"

    def test_the_manifest_records_a_hash_per_file(self, script_text: str) -> None:
        """Names and sizes do not distinguish two governance documents differing in one clause."""
        assert "Sha256" in script_text
        assert "SHA-256 per file" in script_text or "SHA-256" in script_text
