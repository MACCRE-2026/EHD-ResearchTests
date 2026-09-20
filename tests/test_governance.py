"""Governance tests — the datacenter boundary and tracked-file hygiene.

These tests exist because *principle 5, specifications drift from implementations unless
mechanically checked*. ``ehd-dev-rules.md`` and ``ehd-charter.md`` make several claims about
repository structure. Without these tests those claims are sentences of good intention.

Each test states what it covers and, where relevant, what it does **not** — a check whose
scope is unstated is the same problem as an unperformed one.

Scope limit that applies to every test in this module
----------------------------------------------------
All of these inspect the **working tree and the git index**. None of them inspects git
**history**. A secret or transcript that was committed and later removed is still in the
object database and still reachable. So these tests can never justify the claim "the
repository is clean"; only "no findings in the tracked working tree". A full-history sweep
needs a purpose-built tool (``gitleaks detect --log-opts=--all``).
"""

from __future__ import annotations

import functools
import importlib
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# The declared datacenter tiers, per ehd-dev-rules.md. Adding a tier on disk without
# declaring it here is the drift this list exists to catch.
DECLARED_TIERS = (
    "00_Governance",
    "01_Collaborator_Conversations",
    "02_Kiro_Conversations",
    "03_Task_Packets",
    "04_BreadCrumbs",
    "05_Solver_Runs",
    "06_Inputs",
    "07_Outputs",
    "08_Reference",
    "09_Backups",
)

# Terms whose presence in a TRACKED file means collaborator-conversation, persona or
# private-framing material has leaked toward a public remote.
#
# "Biefeld" is deliberately absent: Biefeld-Brown is the standard name of the physical
# effect and is legitimate, on-topic engineering vocabulary.
FORBIDDEN_IN_TRACKED = (
    "TIGR",
    "Diamond Architecture",
    "Origin Vertex",
    "RedTeam",
    "Redteam",
    "aistudio",
    "gemini",
    "APL Rectification",
    "Cellular Gravitator",
    "5D superfluid",
)

# This module DEFINES the sentinel list above, so it necessarily contains every term it
# searches for. It is exempt from its own scan.
#
# This exemption was not foreseen. The scan passed while this file was untracked and began
# failing the moment it was staged, because `git ls-files` then included it. Recorded rather
# than quietly patched, because "add an exemption to make the scan pass" is the exact move that
# turns a leak detector into decoration.
#
# The exemption is kept to a single named path, and `test_leakage_scan_exemptions_are_minimal`
# asserts it stays that way. A suppression list that grows on the authority of whoever was
# fixing a red test is worse than no scan, because it reads as though the check is still
# working.
SCAN_EXEMPT = ("tests/test_governance.py",)

# Text file suffixes worth scanning. Binary content is reported as skipped rather than
# silently passed.
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".cir",
    ".asc",
    ".lua",
    ".ps1",
    ".gitignore",
}


@functools.cache
def _git(*args: str) -> str:
    """Run a read-only git command in the repo root and return stdout.

    Cached for the session because the git index does not change during a test run, so repeating
    a query is pure waste. Uncached, the parametrized tests below spawned about a dozen
    subprocesses.

    A correction, recorded because the wrong version of it was written here first
    ------------------------------------------------------------------------------
    This docstring originally claimed git was "extremely slow in this workspace" at **1.3 to 4
    seconds** per invocation, and attributed that to Google Drive I/O contention across the
    ~408 MB ``.venv`` in the synced tree.

    **That attribution was wrong.** The measurement was real but was taken while the machine's
    terminal state had degraded over a long session — the operator's own observation, and the
    reason they restart periodically. Re-measured immediately after a reboot, the same
    ``git ls-files`` takes **145 ms**.

    So the slowdown was an environment artefact, not a property of Drive. One measurement in a
    degraded environment was written down as an established cause, which is
    *principle 7, verified means reproduced*, applied to a diagnosis rather than a defect.

    The caching stays, on its own merits: 145 ms times a dozen calls is still over a second of
    avoidable work per run, and a slow suite is a suite that stops being run.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr}")
    return result.stdout


@functools.lru_cache(maxsize=1)
def _tracked_files() -> tuple[str, ...]:
    """Return every path in the git index, as forward-slash relative strings."""
    out = _git("ls-files")
    return tuple(line.strip() for line in out.splitlines() if line.strip())


@functools.lru_cache(maxsize=1)
def _stageable_files() -> tuple[str, ...]:
    """Return files that are untracked but NOT ignored — what `git add` would pick up next.

    Added 2026-09-15 after a real leak. ``src/ehdpsu/breadcrumb.py`` named a third-party model in
    two docstrings; the Gate ran green, and only afterwards was the file staged. The leakage scan
    reads the git index, so a file created and scanned in that order is **not scanned at all** —
    the check reported CLEAN over a file it had never opened, which is
    *principle 3, never report success over unperformed work*, wearing the shape of a passing test.

    Ignored paths stay excluded, so the untracked datacenter under ``artifacts/`` is not swept.
    """
    out = _git("ls-files", "--others", "--exclude-standard")
    return tuple(line.strip() for line in out.splitlines() if line.strip())


def _scan_for_framing(paths: tuple[str, ...]) -> tuple[list[str], int, list[str]]:
    """Scan ``paths`` for the forbidden framing terms.

    Returns ``(findings, scanned_count, skipped)``. Extracted so the tracked scan and the
    about-to-be-tracked scan share one implementation: two copies of a scanner is
    *principle 4, two representations of one thing will drift*, applied to the thing whose whole
    job is to catch what everyone else missed.
    """
    findings: list[str] = []
    scanned = 0
    skipped: list[str] = []

    for rel in paths:
        if rel in SCAN_EXEMPT:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            skipped.append(rel)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            skipped.append(f"{rel} ({type(exc).__name__})")
            continue
        scanned += 1
        for term in FORBIDDEN_IN_TRACKED:
            if term in text:
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if term in line:
                        findings.append(f"{rel}:{lineno}: {term!r}")

    return findings, scanned, skipped


@functools.cache
def _check_ignore(path: str) -> int:
    """Return git check-ignore's exit code for a path: 0 ignored, 1 not, 128 error.

    Separate from :func:`_git` because a non-zero exit here is a meaningful answer rather than a
    failure, so it must not skip the test. Cached for the same performance reason.
    """
    return subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


# ---------------------------------------------------------------------------
# The datacenter boundary
# ---------------------------------------------------------------------------


def test_declared_datacenter_tiers_exist() -> None:
    """Every declared tier exists on disk.

    A declared tier that is absent means a write will land somewhere unintended, and the
    backup script's declared source set is incomplete.
    """
    artifacts = REPO_ROOT / "artifacts"
    assert artifacts.is_dir(), "artifacts/ (the project datacenter) does not exist"

    missing = [t for t in DECLARED_TIERS if not (artifacts / t).is_dir()]
    assert not missing, f"declared datacenter tiers missing from disk: {missing}"


def test_no_undeclared_datacenter_tiers() -> None:
    """No directory exists under artifacts/ that is not declared.

    An undeclared tier is one nobody agreed to and that no backup script knows about, so it
    is silently outside the backup set.
    """
    artifacts = REPO_ROOT / "artifacts"
    if not artifacts.is_dir():
        pytest.skip("artifacts/ absent; covered by test_declared_datacenter_tiers_exist")

    on_disk = {p.name for p in artifacts.iterdir() if p.is_dir()}
    undeclared = sorted(on_disk - set(DECLARED_TIERS))
    assert not undeclared, (
        f"undeclared tiers on disk: {undeclared}. Declare them in ehd-dev-rules.md and in "
        f"DECLARED_TIERS, or remove them."
    )


def test_nothing_under_artifacts_is_tracked() -> None:
    """The datacenter is ignored at the folder level, so nothing in it is in the index.

    ``git ls-files`` is the authoritative check. ``git status`` is not: a staged rename or
    deletion makes an already-removed path appear there, which reads like residue.
    """
    tracked = _git("ls-files", "--", "artifacts").splitlines()
    tracked = [t for t in tracked if t.strip()]
    assert not tracked, (
        f"{len(tracked)} file(s) tracked under artifacts/: {tracked[:10]}. "
        f"The datacenter must never enter the index; it holds conversation transcripts."
    )


def test_artifacts_is_actually_ignored() -> None:
    """git actively ignores paths under artifacts/.

    Distinct from the test above: that one proves nothing is tracked *now*, this one proves a
    new file would not be trackable. A ``.gitignore`` negation with no matching ignore rule
    silently does nothing, which is exactly how four files once became tracked in here.
    """
    probe = "artifacts/07_Outputs/__ignore_probe__.csv"
    code = _check_ignore(probe)
    # exit 0 => ignored, 1 => not ignored, 128 => error
    assert code == 0, (
        f"{probe} is NOT ignored by git (check-ignore exit {code}). "
        f"artifacts/ must be ignored at the folder level."
    )


def test_outputs_directory_is_gone() -> None:
    """The old top-level outputs/ directory was migrated to artifacts/07_Outputs/.

    Two output destinations would be two representations of one thing.
    """
    assert not (REPO_ROOT / "outputs").exists(), (
        "outputs/ still exists. Generated data belongs in artifacts/07_Outputs/; leaving both "
        "invites writes to the wrong one."
    )


# ---------------------------------------------------------------------------
# Tracked-file hygiene
# ---------------------------------------------------------------------------


def test_tracked_files_carry_no_private_framing() -> None:
    """No tracked file contains collaborator-conversation or persona framing terms.

    Scope: the tracked working tree only. Git history is NOT scanned, so a pass here does not
    mean the terms were never committed. Files not yet tracked are covered by
    :func:`test_stageable_files_carry_no_private_framing`, deliberately as a separate test so the
    failure message says which of the two situations you are in.
    """
    findings, scanned, skipped = _scan_for_framing(_tracked_files())

    # A scan that read nothing is not a pass.
    assert scanned > 0, (
        f"scanned 0 tracked text files (skipped {len(skipped)}). "
        f"This is NOT-SCANNED, not CLEAN."
    )
    assert not findings, (
        f"private framing found in {len(findings)} location(s) in tracked files "
        f"(scanned {scanned}, skipped {len(skipped)}):\n" + "\n".join(findings[:20])
    )


def test_stageable_files_carry_no_private_framing() -> None:
    """The same scan over files that are untracked but not ignored — the next `git add`.

    This closes a real hole rather than a hypothetical one. On 2026-09-15 a new module named a
    third-party model in two docstrings, the Gate ran green because the file was still untracked,
    and the file was staged immediately afterwards. The scan had reported CLEAN over a file it
    never opened.

    Kept separate from the tracked scan on purpose. A finding here means "not yet in the index,
    fix it and nothing has been recorded"; a finding there means "already tracked, and history may
    carry it". Folding them together would lose that distinction, and an ambiguous terminal state
    gets its own status rather than being merged into another.

    Unlike the tracked scan, **zero files scanned is a legitimate pass**: a clean working tree
    genuinely has nothing staged. So the count is reported rather than asserted.
    """
    stageable = _stageable_files()
    findings, scanned, skipped = _scan_for_framing(stageable)

    assert not findings, (
        f"private framing found in {len(findings)} location(s) in files that are untracked but "
        f"NOT ignored, i.e. the next `git add` would record them (scanned {scanned} of "
        f"{len(stageable)}, skipped {len(skipped)}):\n" + "\n".join(findings[:20])
    )


def test_leakage_scan_exemptions_are_minimal() -> None:
    """The scan exempts exactly one file, and that file genuinely enumerates the sentinels.

    An exemption list is the cheapest way to make a failing scan green, and therefore the cheapest
    way to make it useless. Two guards, because pinning the path alone is not enough:

    1. **The tuple is pinned exactly.** A new path cannot be added to get past a red build.
    2. **The exempt file must contain most of the sentinel list.** That is what distinguishes a
       genuine scanner definition from a file exempted to hide one leaked term.

    This was nearly widened once. `.kiro/agents/git-steward.md` restated the sentinel list, so it
    tripped the scan, and adding a second exemption was the obvious fix. The better fix was to
    stop having two copies: the profile now cites this constant instead of reproducing it, which
    resolves the scan failure and the *principle 4, two representations of one thing will drift*
    problem in the same move. A scanner working from a stale copy of the list reports clean on
    exactly the term someone added to the real one.
    """
    assert SCAN_EXEMPT == ("tests/test_governance.py",), (
        f"leakage scan exemptions changed to {SCAN_EXEMPT}. Only the module defining the sentinel "
        f"list may be exempt. If another file trips the scan, ask whether it should be citing "
        f"FORBIDDEN_IN_TRACKED rather than restating it."
    )

    for rel in SCAN_EXEMPT:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        present = sum(1 for term in FORBIDDEN_IN_TRACKED if term in text)
        assert present >= len(FORBIDDEN_IN_TRACKED) - 1, (
            f"{rel} is exempt from the leakage scan but contains only {present} of "
            f"{len(FORBIDDEN_IN_TRACKED)} sentinel terms. An exemption is for a file that "
            f"enumerates the list, not for one that happens to contain a term."
        )


def test_handover_transcript_is_not_tracked() -> None:
    """The cloud-session handover transcript is not in the index under any name.

    It contains the framing terms above verbatim. It lives in the datacenter.
    """
    offenders = [p for p in _tracked_files() if "handover" in p.lower()]
    assert not offenders, f"handover transcript(s) tracked: {offenders}"


# ---------------------------------------------------------------------------
# Steering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ehd-charter.md", "ehd-dev-rules.md", "hv-safety.md"])
def test_always_applied_steering_exists_and_is_valid(name: str) -> None:
    """Each always-applied steering file exists and declares ``inclusion: always``.

    ehd-charter.md asserts hv-safety.md is always applied. If that file were absent or
    scoped differently, the charter would be making a false claim about behaviour.
    """
    path = REPO_ROOT / ".kiro" / "steering" / name
    assert path.is_file(), f"steering file missing: {path}"

    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{name} has no YAML front matter"
    front_matter = text.split("---", 2)[1]
    assert (
        "inclusion: always" in front_matter
    ), f"{name} does not declare 'inclusion: always'; the charter claims it is always applied"


def test_no_steering_file_pairs_auto_with_a_file_pattern() -> None:
    """No steering file combines ``inclusion: auto`` with ``fileMatchPattern``.

    ``auto`` keys off name/description and takes no pattern. Pairing the two means the file
    silently never applies, and invalid front matter produces no warning.
    """
    steering_dir = REPO_ROOT / ".kiro" / "steering"
    if not steering_dir.is_dir():
        pytest.skip(".kiro/steering absent")

    offenders: list[str] = []
    for path in sorted(steering_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        front_matter = text.split("---", 2)[1]
        if "inclusion: auto" in front_matter and "fileMatchPattern" in front_matter:
            offenders.append(path.name)

    assert not offenders, (
        f"steering files pairing 'inclusion: auto' with 'fileMatchPattern' (never applies): "
        f"{offenders}"
    )


def test_no_steering_file_uses_pipe_alternation_in_a_glob() -> None:
    """No steering file puts pipe-alternation inside a single glob string.

    ``'**/a.py|**/b.py'`` is treated as one literal pattern and matches nothing. Multiple
    patterns require a YAML array.
    """
    steering_dir = REPO_ROOT / ".kiro" / "steering"
    if not steering_dir.is_dir():
        pytest.skip(".kiro/steering absent")

    offenders: list[str] = []
    for path in sorted(steering_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        front_matter = text.split("---", 2)[1]
        for line in front_matter.splitlines():
            stripped = line.strip()
            if ("fileMatchPattern" in stripped or stripped.startswith("- ")) and "|" in stripped:
                offenders.append(f"{path.name}: {stripped}")

    assert not offenders, f"pipe-alternation inside a glob string: {offenders}"


# ---------------------------------------------------------------------------
# Tracked generated inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "ehd_llc_cw.cir",
        "ehd_llc_cw.asc",
        "ehd_wire_collector.lua",
        "ehd_wire_collector_geometry.txt",
    ],
)
def test_solver_inputs_are_tracked(name: str) -> None:
    """Generated solver inputs are tracked, so a cloner can run the GUI solvers.

    They are deliberately outside the datacenter for exactly this reason.
    """
    assert (REPO_ROOT / "solver_inputs" / name).is_file(), (
        f"solver_inputs/{name} missing; regenerate with `python -m ehdpsu.spice` and "
        f"`python -m ehdpsu.femm`"
    )
    tracked = _git("ls-files", "--", f"solver_inputs/{name}").strip()
    assert tracked, f"solver_inputs/{name} exists but is not tracked"


# ---------------------------------------------------------------------------
# Governance tooling
# ---------------------------------------------------------------------------

GOVERNANCE_SCRIPTS = (
    "gate.ps1",
    "verify_citations.ps1",
    "verify_no_artifacts_tracked.ps1",
    "backup_datacenter.ps1",
    "model_pin_probe.ps1",
)


@pytest.mark.parametrize("name", GOVERNANCE_SCRIPTS)
def test_governance_script_exists(name: str) -> None:
    """Each governance script is present and tracked.

    They live in ``.kiro/governance/`` rather than ``.kiro/scripts/`` deliberately: a bare
    ``scripts/`` ignore pattern matches at any depth, and governance tooling that does not
    travel with the repository is not governance.
    """
    path = REPO_ROOT / ".kiro" / "governance" / name
    assert path.is_file(), f"governance script missing: {path}"

    tracked = _git("ls-files", "--", f".kiro/governance/{name}").strip()
    assert tracked, f".kiro/governance/{name} exists but is not tracked"


@pytest.mark.parametrize("name", GOVERNANCE_SCRIPTS)
def test_governance_script_declares_distinct_exit_codes(name: str) -> None:
    """Each script documents its exit codes, and they are distinct.

    A script that folds several failure modes into one code cannot tell the operator which
    thing went wrong, and an ambiguous terminal state is the failure that
    *principle 3, never report success over unperformed work*, warns about. Every one of these
    scripts has at least one non-success state that is specifically NOT a pass -- a tool that
    was absent, a list that was empty, a scan that read nothing.
    """
    text = (REPO_ROOT / ".kiro" / "governance" / name).read_text(encoding="utf-8")

    # Lines in the .OUTPUTS block look like:  "        0  OK    description"
    codes = re.findall(r"^\s{4,}(\d)\s{2,}([A-Z][A-Z-]+)", text, flags=re.MULTILINE)
    assert len(codes) >= 4, (
        f"{name} documents only {len(codes)} exit code(s); expected at least 4 "
        f"(success plus distinct failure modes)"
    )

    numbers = [c[0] for c in codes]
    assert len(numbers) == len(
        set(numbers)
    ), f"{name} reuses an exit code: {numbers}. Distinct failure modes need distinct codes."

    names = [c[1] for c in codes]
    assert len(names) == len(set(names)), f"{name} reuses a status name: {names}"
    assert "OK" in names, f"{name} declares no OK status"
    assert numbers[names.index("OK")] == "0", f"{name} does not map OK to exit 0"


def test_no_governance_script_offers_a_fix_switch() -> None:
    """No governance script can silently repair what it reports.

    These scripts verify configuration that governs agent behaviour, including model pins that
    control cost. A probe that rewrites a profile it judged wrong removes the human from the
    decision. Reporting and repairing are separate jobs on purpose.
    """
    offenders: list[str] = []
    for name in GOVERNANCE_SCRIPTS:
        text = (REPO_ROOT / ".kiro" / "governance" / name).read_text(encoding="utf-8")
        # A -Fix parameter declaration, not a mention of the word in prose.
        if re.search(r"^\s*\[switch\]\s*\$Fix\b", text, flags=re.MULTILINE):
            offenders.append(name)
    assert not offenders, f"governance scripts declaring a -Fix switch: {offenders}"


# ---------------------------------------------------------------------------
# Oracle skills
# ---------------------------------------------------------------------------

ORACLE_SKILLS = (
    "suite-core-oracle",
    "electrostatics-corona-oracle",
    "hv-power-electronics-oracle",
    "fluid-cfd-oracle",
    "geometry-cad-oracle",
    "visualization-oracle",
    "metrology-telemetry-oracle",
)

# Path-scoped steering: file name -> the patterns it must declare.
PATH_SCOPED_STEERING = {
    "profile-seam.md": ("src/**", "profiles/**"),
    "adapter-contract.md": ("src/ehdpsu/adapters/**",),
    "solver-provenance.md": ("artifacts/05_Solver_Runs/**",),
}


def _front_matter(path: Path) -> str:
    """Return a file's YAML front matter, or '' when it has none."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


@pytest.mark.parametrize("skill", ORACLE_SKILLS)
def test_oracle_skill_is_complete(skill: str) -> None:
    """Each Oracle has a SKILL.md with valid front matter and a task ledger beside it.

    A skill without its ledger has nowhere to record why its domain looks the way it does, and
    the next session has to rediscover it.
    """
    skill_dir = REPO_ROOT / ".kiro" / "skills" / skill
    assert skill_dir.is_dir(), f"skill directory missing: {skill_dir}"

    skill_md = skill_dir / "SKILL.md"
    ledger = skill_dir / "task_ledger.md"
    assert skill_md.is_file(), f"{skill}/SKILL.md missing"
    assert ledger.is_file(), f"{skill}/task_ledger.md missing"

    fm = _front_matter(skill_md)
    assert fm, f"{skill}/SKILL.md has no YAML front matter"
    assert f"name: {skill}" in fm, (
        f"{skill}/SKILL.md front matter does not declare 'name: {skill}'. A name that does not "
        f"match its directory cannot be activated reliably."
    )
    assert "description:" in fm, (
        f"{skill}/SKILL.md declares no description. Description is how the skill gets matched to "
        f"a request; without one it is unreachable."
    )


@pytest.mark.parametrize("skill", ORACLE_SKILLS)
def test_oracle_skill_states_its_hazards_and_defers(skill: str) -> None:
    """Each Oracle states live hazards and declares what it does not restate.

    Both sections are load-bearing. The hazards section is how a domain's known traps reach the
    next session instead of being rediscovered. The does-not-restate section is what keeps the
    skill from becoming a second representation of the doctrine or the steering, which
    *principle 4, two representations of one thing will drift*, warns about.
    """
    text = (REPO_ROOT / ".kiro" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")

    assert "Live hazards" in text, (
        f"{skill}/SKILL.md has no 'Live hazards' section. A domain with no stated hazards is "
        f"either brand new or has lost them."
    )
    assert "does not restate" in text, (
        f"{skill}/SKILL.md has no 'does not restate' section, so nothing stops it duplicating "
        f"the doctrine or the always-applied steering."
    )


@pytest.mark.parametrize("skill", ORACLE_SKILLS)
def test_oracle_ledger_is_append_only_and_demands_evidence(skill: str) -> None:
    """Each ledger states the append-only rule and that COMPLETED needs observed evidence."""
    text = (REPO_ROOT / ".kiro" / "skills" / skill / "task_ledger.md").read_text(encoding="utf-8")
    assert "Append only" in text, f"{skill}/task_ledger.md does not state the append-only rule"
    assert "COMPLETED" in text, f"{skill}/task_ledger.md declares no terminal states"
    assert (
        "evidence" in text.lower()
    ), f"{skill}/task_ledger.md does not require evidence for a completion claim"


def test_no_skill_restates_the_eight_principles() -> None:
    """No skill reproduces the canonical principle set.

    The doctrine is the only place the eight are stated; everything else cites them by number and
    name. `.kiro/governance/verify_citations.ps1` enforces this across all documents; this test
    is the pytest-visible half so a suite run catches it too.
    """
    # A numbered list item beginning with a canonical principle name is a restatement.
    canonical_openers = (
        "trust is a ceiling",
        "an approximately-correct identifier",
        "never report success",
        "two representations of one thing",
        "specifications drift from implementations",
        "a green test suite",
        "verified means reproduced",
        "atomicity is a property",
    )
    offenders: list[str] = []
    for skill in ORACLE_SKILLS:
        path = REPO_ROOT / ".kiro" / "skills" / skill / "SKILL.md"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            item = re.match(r"^\s{0,3}\d+[.)]\s+\*{0,2}(.{10,})", line)
            if not item:
                continue
            body = item.group(1).lower().lstrip("*_`")
            if any(body.startswith(opener) for opener in canonical_openers):
                offenders.append(f"{skill}/SKILL.md:{lineno}")
    assert not offenders, (
        f"skills restating the canonical principle set as numbered items: {offenders}. "
        f"Cite by number and name instead."
    )


# ---------------------------------------------------------------------------
# Path-scoped steering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PATH_SCOPED_STEERING))
def test_path_scoped_steering_uses_filematch_with_an_array(name: str) -> None:
    """Each path-scoped steering file uses `fileMatch` with `fileMatchPattern` as a YAML array.

    Two schema traps, both recorded in MACCRE's own analysis after they shipped broken:

    * `inclusion: auto` keys off name/description and takes NO pattern. Pairing the two means the
      file silently never applies.
    * Multiple patterns require a YAML array. Pipe-alternation inside one glob string
      (``'**/a.py|**/b.py'``) is treated as a single literal pattern and matches nothing.

    Invalid front matter produces no warning — the file simply never loads. So this is checked
    rather than trusted.
    """
    path = REPO_ROOT / ".kiro" / "steering" / name
    assert path.is_file(), f"path-scoped steering missing: {path}"

    fm = _front_matter(path)
    assert fm, f"{name} has no YAML front matter"
    assert "inclusion: fileMatch" in fm, f"{name} does not declare 'inclusion: fileMatch'"
    assert (
        "inclusion: auto" not in fm
    ), f"{name} declares 'inclusion: auto', which takes no pattern and would never apply"

    # The patterns must be YAML list items, not a single inline string.
    pattern_lines = [ln.strip() for ln in fm.splitlines() if ln.strip().startswith("- ")]
    assert pattern_lines, (
        f"{name} declares fileMatchPattern but not as a YAML array. A single inline string cannot "
        f"express multiple patterns, and pipe-alternation inside one matches nothing."
    )
    for ln in pattern_lines:
        assert "|" not in ln, f"{name} uses pipe-alternation inside a glob: {ln}"

    declared = {ln.lstrip("- ").strip().strip("'\"") for ln in pattern_lines}
    for required in PATH_SCOPED_STEERING[name]:
        assert (
            required in declared
        ), f"{name} does not declare the pattern {required!r}; declared: {sorted(declared)}"


# ---------------------------------------------------------------------------
# Agent seats
# ---------------------------------------------------------------------------

# seat name -> (expected pin, expected tools)
AGENT_SEATS = {
    "sim-executor": ("qwen3-coder-next", {"read", "write", "shell"}),
    "physics-executor": ("claude-haiku-4.5", {"read", "write", "shell"}),
    "solver-runner": ("qwen3-coder-next", {"read", "write", "shell"}),
    "breadcrumb-recorder": ("claude-sonnet-5", {"read", "write"}),
    "git-steward": ("claude-sonnet-5", {"read", "shell", "write"}),
}

# The enumeration snapshot lives in the untracked datacenter, so it is absent from every clone.
ENUMERATION_SNAPSHOT = (
    REPO_ROOT / "artifacts" / "00_Governance" / "2026-09-15_model_enumeration_snapshot.md"
)


def _agent_front_matter(seat: str) -> str:
    return _front_matter(REPO_ROOT / ".kiro" / "agents" / f"{seat}.md")


@pytest.mark.parametrize("seat", sorted(AGENT_SEATS))
def test_agent_seat_declares_its_pin_and_tools(seat: str) -> None:
    """Each seat exists and declares the pin and tool set its role requires.

    The tool set is part of the design, not a convenience. ``breadcrumb-recorder`` has **no
    shell** deliberately: a seat that can re-run commands to gather evidence can re-run them until
    the evidence takes the shape it expected.
    """
    path = REPO_ROOT / ".kiro" / "agents" / f"{seat}.md"
    assert path.is_file(), f"agent profile missing: {path}"

    fm = _agent_front_matter(seat)
    assert fm, f"{seat}.md has no YAML front matter"
    assert f"name: {seat}" in fm, f"{seat}.md front matter name does not match its filename"
    assert "description:" in fm, f"{seat}.md declares no description"

    expected_pin, expected_tools = AGENT_SEATS[seat]
    assert f"model: {expected_pin}" in fm, (
        f"{seat}.md does not pin {expected_pin!r}. A wrong pin does not error — it silently falls "
        f"back to the default model and bills at that rate."
    )

    declared_tools = set(re.findall(r'"(read|write|shell)"', fm))
    assert (
        declared_tools == expected_tools
    ), f"{seat}.md declares tools {sorted(declared_tools)}, expected {sorted(expected_tools)}"


def test_breadcrumb_recorder_has_no_shell() -> None:
    """The breadcrumb seat cannot run commands, by design.

    Stated as its own test rather than left implicit in the table above, because it is the one
    tool-set decision that looks like an oversight and is not. It records what already happened;
    a seat that can regenerate evidence can regenerate it into the shape it expected.
    """
    fm = _agent_front_matter("breadcrumb-recorder")
    assert '"shell"' not in fm, (
        "breadcrumb-recorder has been granted shell access. It records provenance and must not be "
        "able to re-run the work it is describing."
    )


@pytest.mark.parametrize("seat", sorted(AGENT_SEATS))
def test_every_pin_appears_in_the_enumeration_snapshot(seat: str) -> None:
    """Each pin appears in the authoritative model enumeration.

    Scope, stated because this check can legitimately not run: the enumeration snapshot lives in
    ``artifacts/00_Governance/``, which is **untracked**, so it does not exist in a clone. When it
    is absent this test **skips with a reason** rather than passing — an unavailable check is not a
    clean one. ``.kiro/governance/model_pin_probe.ps1`` is the live version that queries the CLI
    directly.
    """
    if not ENUMERATION_SNAPSHOT.is_file():
        pytest.skip(
            "model enumeration snapshot absent (it lives in the untracked datacenter). "
            "Run .kiro/governance/model_pin_probe.ps1 to verify pins against the live CLI."
        )

    snapshot = ENUMERATION_SNAPSHOT.read_text(encoding="utf-8")
    pin = AGENT_SEATS[seat][0]
    assert f"`{pin}`" in snapshot, (
        f"{seat} pins {pin!r}, which does not appear in the enumeration snapshot. Display names "
        f"are not IDs: 'Qwen3 Coder Next' is a label, 'qwen3-coder-next' is the identifier."
    )


@pytest.mark.parametrize("seat", ["sim-executor", "physics-executor"])
def test_executor_seats_forbid_editing_their_own_constraints(seat: str) -> None:
    """The coding seats explicitly forbid the paths that define their own limits.

    A seat that can edit ``.kiro/`` can rewrite its own instructions; one that can edit
    ``pyproject.toml`` can change the dependency pins and the gate configuration. Both must be
    named in the profile, because a prohibition the seat cannot read is not a prohibition.
    """
    text = (REPO_ROOT / ".kiro" / "agents" / f"{seat}.md").read_text(encoding="utf-8")
    for forbidden in (".kiro/", "artifacts/00_Governance/", "pyproject.toml", ".gitignore"):
        assert forbidden in text, f"{seat}.md does not name {forbidden!r} as forbidden"


@pytest.mark.parametrize("seat", sorted(AGENT_SEATS))
def test_no_seat_claims_authority_to_commit(seat: str) -> None:
    """No seat may commit. Staging is delegated; committing stays with the operator."""
    text = (REPO_ROOT / ".kiro" / "agents" / f"{seat}.md").read_text(encoding="utf-8").lower()
    assert "never commit" in text or "do not commit" in text, (
        f"{seat}.md does not state that it must never commit. Every seat needs this explicitly; "
        f"a staged change is reviewable, a committed one is a fait accompli."
    )


# ---------------------------------------------------------------------------
# The Gate
# ---------------------------------------------------------------------------

GATE = REPO_ROOT / ".kiro" / "governance" / "gate.ps1"


def _gate_floor() -> int:
    """Return the Gate's declared collected-count floor.

    Extracted into a helper because the inline version was written as
    ``re.search(...).group(1)``, which is a type error: ``re.search`` returns ``Match | None``.
    mypy flagged both occurrences the moment the configuration was fixed to actually examine
    files — two real latent defects that had been invisible while it was checking zero.
    """
    match = re.search(r"\$COLLECTED_FLOOR\s*=\s*(\d+)", GATE.read_text(encoding="utf-8"))
    assert match is not None, "gate.ps1 does not declare $COLLECTED_FLOOR as an integer literal"
    return int(match.group(1))


def test_gate_has_no_scoped_variant() -> None:
    """The Gate accepts no path argument and no stage selector.

    ``omni qa some_file.py`` is the failure mode that produced MACCRE's own mandate against
    scoping: a scoped check passes while the rest of the project is broken. The cheapest way to
    prevent that is to make it inexpressible, so the Gate's parameter block must not accept a
    path, a target or a stage.
    """
    text = GATE.read_text(encoding="utf-8")
    param_block = text.split("param(", 1)[1].split(")", 1)[0]

    for forbidden in ("Path", "Target", "Stage", "Only", "Scope", "File"):
        assert f"${forbidden}" not in param_block, (
            f"gate.ps1 accepts a ${forbidden} parameter, which makes a scoped run expressible. "
            f"The Gate runs everything or it is not the Gate."
        )


def test_gate_asserts_mypy_examined_something() -> None:
    """The Gate fails when mypy examines zero files, rather than reporting its exit code alone.

    This is the assertion the Gate was built for. ``errors prevented further checking`` makes mypy
    abort collection, so it can exit non-zero having type-checked **nothing** — which four
    consecutive task reports described as one tidy error plus a caveat, while working around it
    with an explicit ``--python-version`` override.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "MYPY-CHECKED-NOTHING" in text, (
        "gate.ps1 has no distinct status for mypy examining zero files. Without it, an aborted "
        "type-check is indistinguishable from a type error."
    )
    assert "$fileCount -eq 0" in text, "gate.ps1 does not test mypy's examined-file count"

    # And it must not defeat the point by overriding the project's configured target version.
    #
    # Checked against the INVOCATION LINE, not the whole file. The Gate's docstring legitimately
    # discusses `--python-version` while explaining why it does not pass it, and a naive
    # whole-file substring check flagged that as a violation on first run — the same mistake that
    # once reported seven clean ledger files as corrupt because "rtifacts" is a substring of
    # "artifacts". A checker that cannot distinguish discussing a thing from doing it is not a
    # checker.
    invocation = [line for line in text.splitlines() if "Invoke-Stage 'mypy'" in line]
    assert invocation, "gate.ps1 has no recognisable mypy invocation line"
    assert "--python-version" not in invocation[0], (
        f"gate.ps1 passes --python-version to mypy: {invocation[0].strip()}. The purpose of this "
        f"stage is that the project's own configured invocation works; overriding it reproduces "
        f"the original defect."
    )


def test_gate_judges_pytest_on_collected_count() -> None:
    """The Gate enforces a collected-count floor, not just a passing exit code.

    One ``ImportError`` in one module aborts collection for everything after it while the report
    still looks normal. A floor is what makes that visible.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "COLLECTED_FLOOR" in text, "gate.ps1 declares no collected-count floor"
    assert "PYTEST-UNDER-FLOOR" in text, "gate.ps1 has no distinct status for an under-floor run"

    assert _gate_floor() > 0, "the collected-count floor is zero, which asserts nothing"


def test_gate_floor_matches_the_current_suite_size() -> None:
    """The floor equals the number of tests currently collected.

    A floor that is never raised stops catching collection errors as the suite grows: a stale
    floor of 12 would happily accept a suite that had silently collapsed to 12. Raising it is part
    of adding checks, so this test fails when checks are added and the floor is not moved.

    It is deliberately an equality, not a lower bound. A floor below the real count is slack that
    accumulates silently; a floor above it fails immediately and obviously.
    """
    floor = _gate_floor()

    out = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "pytest",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        pytest.skip(f"pytest --collect-only failed (exit {out.returncode}); cannot compare floor")

    match = re.search(r"(\d+) tests? collected", out.stdout)
    assert match, f"could not parse a collected count from:\n{out.stdout[-400:]}"
    actual = int(match.group(1))

    assert floor == actual, (
        f"gate.ps1's COLLECTED_FLOOR is {floor} but the suite collects {actual}. Raise the floor "
        f"and add the new count to the history comment above it."
    )


def test_gate_proves_sweep_breadth_rather_than_trusting_config() -> None:
    """Every static sweep in the Gate must report how many files it examined.

    A test is the scoped check — it proves one property precisely. A whole-codebase sweep is not
    another narrow check; it is the **antidote** to the narrowness of all the others, answering the
    one question no test can: did this local change break something lateral or downstream?

    So the asymmetry: narrowing a test makes a smaller test, still useful. **Narrowing a sweep
    destroys its entire purpose**, converting the anti-siloing layer into one more silo.

    The incident: a ``pyrightconfig.json`` excluding one package meant two files were never
    type-checked and held six real errors, with nothing reporting it. The config was internally
    consistent and silently narrower than anyone believed.
    """
    text = GATE.read_text(encoding="utf-8")

    assert "SWEEP-TOO-NARROW" in text, (
        "gate.ps1 has no distinct status for a sweep that examined too few files, so a silently "
        "narrowed sweep would report success."
    )
    assert "EXPECTED_SWEEP_FILES" in text, "gate.ps1 declares no expected sweep breadth"
    assert "Assert-Breadth" in text, "gate.ps1 has no breadth assertion helper"

    # Every sweep must be subject to it, named explicitly so adding a sweep without a breadth
    # assertion fails here.
    for tool in ("ruff", "black", "mypy", "pyright"):
        assert f"Assert-Breadth '{tool}'" in text, (
            f"gate.ps1 does not assert breadth for {tool}. A sweep that does not prove what it "
            f"reached is trusted rather than verified."
        )

    # ruff reports nothing about its own breadth in normal output, so it needs --show-files.
    assert "--show-files" in text, (
        "gate.ps1 does not use `ruff check --show-files`. Ruff's normal output says nothing about "
        "how many files it reached, so a config narrowing it would be invisible."
    )


def test_gate_runs_two_type_checkers_and_requires_them_to_agree() -> None:
    """mypy and pyright both run, and the Gate fails if they examine different file sets.

    Two checkers because they demonstrably catch different classes: pyright found a function in
    ``telemetry.py`` declared to return ``DataFrame`` that could return ``DataFrame | Series``,
    which mypy missed because it infers pandas loosely under ``ignore_missing_imports``.

    They must agree on breadth because a divergence is a blind spot shaped exactly like one tool's
    configuration — and neither checker reports it as a failure.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "PYRIGHT-FAILED" in text, "gate.ps1 has no pyright stage"
    assert (
        "CHECKER-DIVERGED" in text
    ), "gate.ps1 does not fail when mypy and pyright examine different file sets"
    assert (
        "$fileCount -ne $pyrightCount" in text
    ), "gate.ps1 declares CHECKER-DIVERGED but does not compare the two file counts"


def test_gate_rejects_undeclared_tool_config_exclusions() -> None:
    """Any exclusion in a tool config must be declared in ehd-dev-rules.md.

    An exclusion is not wrong; an **undeclared** one is, because it narrows a sweep invisibly.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "UNDECLARED-EXCLUSION" in text, "gate.ps1 has no undeclared-exclusion status"
    assert (
        "ehd-dev-rules.md" in text
    ), "gate.ps1's exclusion check does not read the declaration register"


def test_dev_rules_carry_an_exclusion_declaration_register() -> None:
    """The steering file states the sweep-breadth rule and holds a live exclusion register.

    The register must be present even when empty. An absent register reads as "nobody thought
    about it"; an explicit "none" reads as a checked state.
    """
    text = (REPO_ROOT / ".kiro" / "steering" / "ehd-dev-rules.md").read_text(encoding="utf-8")
    assert (
        "whole-codebase or it is not a sweep" in text
    ), "ehd-dev-rules.md does not state the sweep-breadth rule"
    assert "declared exclusions" in text.lower(), (
        "ehd-dev-rules.md holds no exclusion declaration register. The Gate reads this file to "
        "decide whether an exclusion was declared, so the register must exist."
    )


def test_gate_reports_the_thresholds_it_actually_enforces() -> None:
    """The Gate's summary reads its thresholds through the constants, not a second copy of them.

    The incident, 2026-09-15: ``$result.expectedBreadth`` was initialised to a hardcoded ``15``
    about a hundred lines above ``$EXPECTED_SWEEP_FILES``, which enforcement read. When the
    constant was raised to 19, the summary went on printing ``expected >= 15`` **in the same run
    that enforced 19**. Nothing failed. It was caught by reading the Gate's own output, which is
    the worst available detection mechanism.

    *Principle 4, two representations of one thing will drift* — inside the tool built to catch
    exactly that, which is the part worth a permanent check. A reported threshold that disagrees
    with the enforced one is worse than no reported threshold, because a reader who checks the
    summary comes away with a specific wrong number.
    *Principle 2, an approximately-correct identifier is worse than an absent one.*

    The invariant, stated so it also covers thresholds added later: a threshold is declared **once**
    as a literal, and every other mention of it is a variable reference.
    """
    text = GATE.read_text(encoding="utf-8")

    # Each threshold: the constant that enforcement reads, and the summary field that reports it.
    thresholds = {
        "expectedBreadth": "EXPECTED_SWEEP_FILES",
        "collectedFloor": "COLLECTED_FLOOR",
    }

    for field, constant in thresholds.items():
        # The literal declaration must be unique. Two literals is the drift condition itself.
        literals = re.findall(rf"^\s*\${constant}\s*=\s*(\d+)\s*$", text, re.MULTILINE)
        assert len(literals) == 1, (
            f"gate.ps1 declares ${constant} as an integer literal {len(literals)} time(s) "
            f"({literals}); it must be declared exactly once so enforcement and reporting cannot "
            f"disagree."
        )

        # And the reported field must be assigned from that constant, never from its own literal.
        # The optional `$result.` prefix matters: the field is initialised inside the hashtable
        # literal and assigned again as a property once the constant exists.
        assignments = re.findall(rf"^\s*(?:\$\w+\.)?{field}\s*=\s*(\S+)", text, re.MULTILINE)
        assert assignments, f"gate.ps1 has no {field} field in its result record"
        for value in assignments:
            assert not value.lstrip("-").isdigit(), (
                f"gate.ps1 assigns {field} the literal {value}. It must read ${constant} instead, "
                f"or the summary will report a threshold the Gate is not applying — which is what "
                f"happened on 2026-09-15."
            )
            assert value in ("$null", f"${constant}"), (
                f"gate.ps1 assigns {field} the value {value}, which is neither $null nor "
                f"${constant}. The reported threshold must come from the enforced one."
            )

        # A $null placeholder is only acceptable if something later fills it in from the constant.
        if "$null" in assignments:
            assert f"${constant}" in assignments, (
                f"gate.ps1 initialises {field} to $null and never assigns it from ${constant}, so "
                f"the summary would report a blank threshold."
            )


def test_no_test_is_marked_xfail() -> None:
    """This project does not use ``xfail``, and that is a policy rather than an accident.

    An ``xfail`` is a **tolerated known defect**. The answer here to a known-bad value is to
    withhold it and record why — ``sweep_stages.csv`` is the live example: its
    ``V_out_noload_ref_kV`` column is wrong by a factor of ten, so the file is kept out of
    ``examples/`` and a test asserts it stays out. That is a visible, explained absence.
    *Principle 2, an approximately-correct identifier is worse than an absent one.*

    A non-strict ``xfail`` is worse than the defect it documents, because it passes whether the
    test fails **or** succeeds. It therefore conceals a fix exactly as readily as a regression, and
    an xfail that has silently started passing is indistinguishable from one that never worked.

    None of this makes ``xfail`` universally wrong — it earns its place in a project tracking known
    upstream bugs it cannot fix. It is wrong *here*, where the deliverable is the credibility of
    the numbers and every tolerated failure is a number nobody is checking.

    If that judgement ever needs revisiting, delete this test deliberately and say why in the
    ledger. Do not add the first ``xfail`` and leave this test to be discovered by whoever it
    breaks.
    """
    # The needles are assembled from fragments so this module's own source does not contain them
    # literally. Written the obvious way, the search string sat on the comparison line and the
    # check reported itself as the violation -- the same self-detection that once made the leakage
    # scanner flag its own sentinel list, and that flagged the Gate's docstring for discussing
    # `--python-version` while explaining why it does not pass it.
    #
    # A checker that cannot distinguish discussing a thing from doing it is not a checker.
    marker = "@pytest.mark." + "xfail"
    direct_call = "pytest." + "xfail("

    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            # A decorator or an in-test call, not prose: this module discusses xfail at length.
            if stripped.startswith(marker) or direct_call in stripped:
                offenders.append(f"{path.name}:{lineno}: {stripped}")

    assert not offenders, (
        "xfail markers found:\n"
        + "\n".join(offenders)
        + "\nWithhold the bad value and record why, or fix it. Do not tolerate it in a test."
    )


def test_gate_treats_reduced_coverage_as_its_own_status() -> None:
    """Skips and xfails must not be folded into OK, or into the collected-count floor's diagnosis.

    The collected floor cannot see a skip: the count is satisfied while the coverage is not, which
    is the same failure the floor exists to catch one level up.

    And the floor's message must not be the one that fires. Before 2026-09-15 the Gate parsed only
    ``(\\d+) passed`` and reconstructed ``collected`` from it, so any skip made ``collected`` too
    low and produced ``PYTEST-UNDER-FLOOR: a collection error is hiding`` — red for the right
    reason, blamed on a cause that was not there.
    """
    text = GATE.read_text(encoding="utf-8")

    assert "PYTEST-COVERAGE-REDUCED" in text, (
        "gate.ps1 has no distinct status for skipped or xfailed tests, so an incomplete run would "
        "report as clean or be misdiagnosed as a collection error."
    )
    # Every outcome pytest can report must be parsed, or `collected` is reconstructed wrongly.
    for word in ("skipped", "xfailed", "xpassed", "deselected"):
        assert f"'{word}'" in text, (
            f"gate.ps1 does not parse pytest's {word!r} count, so a run containing them would "
            f"compute a collected total that is too low."
        )
    assert "INCOMPLETE" in text, (
        "gate.ps1 does not name the state INCOMPLETE. `SKIPPED` and `NOT-SCANNED` are distinct "
        "from `CLEAN`, and the status text is where that distinction reaches the reader."
    )


def test_gate_reads_pytest_counts_from_the_summary_line_only() -> None:
    """The Gate's outcome counts come from pytest's summary line, never from its whole output.

    **Second defect found in this parser, 2026-09-19**, while writing the CRSDL batch
    specifications. ``Get-PytestCount`` matched ``(\\d+) <word>`` anywhere in pytest's output — and
    pytest prints each failing test's source, docstring included, in the traceback. Two of the new
    specification files contain the phrase ``"1 error"`` while explaining why they resolve a module
    dynamically, so ``$errored`` parsed as **1 from a test's own prose**. ``collected`` was then
    reconstructed as 1136 against an actual 1135.

    Inflation is the dangerous direction. The collected floor exists to catch tests silently
    vanishing, and a count a docstring can raise is a floor a collection error can hide under.
    *Principle 2, an approximately-correct identifier is worse than an absent one* — the number was
    non-empty, plausible and wrong, which is worse than no number at all.

    The first defect in the same parser, recorded 2026-09-15, was reading only ``(\\d+) passed`` and
    falling back to it for ``collected``. Two bugs in one function, both about reading a number from
    roughly the right place.
    """
    text = GATE.read_text(encoding="utf-8")

    assert "Get-PytestSummaryLine" in text, (
        "gate.ps1 has no function isolating pytest's summary line, so outcome counts are parsed "
        "from the whole output and any test whose prose contains '<digits> failed' or "
        "'<digits> error' corrupts them."
    )
    calls = re.findall(r"Get-PytestCount\s+(\$\w+)", text)
    assert calls, "no call to Get-PytestCount found; the parser's shape changed"
    offenders = sorted({c for c in calls if c != "$summaryLine"})
    assert not offenders, (
        f"Get-PytestCount is called with {offenders} rather than $summaryLine. Counts must be read "
        f"from the summary line only; the full output contains every failing test's source."
    )
    for word in ("passed", "failed", "skipped", "xfailed", "xpassed", "deselected", "error"):
        assert f"Get-PytestCount $summaryLine '{word}'" in text, (
            f"the {word!r} count is not read from the summary line. Every outcome is parsed "
            f"separately and all of them must come from the same anchored source."
        )


def test_requirements_lock_pins_pyright() -> None:
    """The lock carries a ``pyright==<version>`` line the Gate can read.

    Precondition for the two tests below: they assert the Gate *reads* the pin, which is worthless
    if there is nothing to read. A lock without the line would make the Gate exit
    ``PYRIGHT-UNPINNED`` on every run, which is loud — but the reason would arrive as a Gate
    failure rather than as a named test, and the reader would go looking in the wrong file.
    """
    lock = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^pyright==\d+\.\d+\.\d+\s*$", lock
    ), "requirements.lock has no exact pyright== pin for gate.ps1 to force the node package to"


def test_gate_forces_the_node_pyright_version() -> None:
    """The Gate pins the checker that runs, not only the wrapper that launches it.

    ``pyright==1.1.414`` in the lock pins the **Python wrapper**. The wrapper then downloads a
    **node package**, and that download was version-unconstrained: the local cache already held
    1.1.409, 1.1.410, 1.1.411, 1.1.413 and 1.1.414. So requirements.lock's stated purpose for
    pinning dev tooling — that an unpinned release "makes the Gate useless as a regression signal"
    — was not being served by the pin that claimed to serve it.

    Found 2026-09-18 while attributing 26 pyright errors that a handover had described as absent.
    The errors were real and pre-existing; the investigation is what surfaced the unpinned node
    package underneath them.

    This is the failure shape the project keeps meeting: a control that is present, internally
    consistent, and narrower than everyone believed. *Principle 5, specifications drift from
    implementations unless mechanically checked* — the lock's comment was the specification.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "PYRIGHT_PYTHON_FORCE_VERSION" in text, (
        "gate.ps1 does not set PYRIGHT_PYTHON_FORCE_VERSION, so the node pyright that actually "
        "type-checks is whatever the wrapper last downloaded, regardless of the lock."
    )
    assert "PYRIGHT-UNPINNED" in text, (
        "gate.ps1 has no distinct status for an unreadable pyright pin. It must not be folded "
        "into TOOLING-ABSENT: pyright would still run and still produce a verdict, from an "
        "unknown version. 'Present but unverified' is not 'absent'."
    )


def test_gate_derives_the_pyright_pin_from_the_lock() -> None:
    """The version is read from requirements.lock, never written into gate.ps1 as a literal.

    A literal would be a second representation of the pin, and *principle 4, two representations
    of one thing will drift*. This drift would be silent in the worst way: forcing a version the
    lock does not name does not error, it type-checks with a different checker and reports success.
    """
    text = GATE.read_text(encoding="utf-8")
    assert "requirements.lock" in text, (
        "gate.ps1 does not read requirements.lock, so its pyright pin cannot be derived from the "
        "single place the project declares it."
    )
    forcing_lines = [
        ln
        for ln in text.splitlines()
        if "PYRIGHT_PYTHON_FORCE_VERSION" in ln and not ln.strip().startswith("#")
    ]
    assert forcing_lines, "no non-comment line sets PYRIGHT_PYTHON_FORCE_VERSION"
    for line in forcing_lines:
        assert not re.search(r"\d+\.\d+\.\d+", line), (
            f"gate.ps1 forces a hardcoded pyright version: {line.strip()!r}. Read it from "
            f"requirements.lock instead so the lock stays the only place the version lives."
        )


@pytest.mark.parametrize(
    "script",
    [
        "gate.ps1",
        "verify_citations.ps1",
        "verify_no_artifacts_tracked.ps1",
        "backup_datacenter.ps1",
        "model_pin_probe.ps1",
    ],
)
def test_governance_script_parses(script: str) -> None:
    """Every governance script is syntax-checked in milliseconds, without running it.

    The Gate cannot validate its own syntax: a parse error aborts the whole script before any stage
    executes, so the only feedback is a three-minute run that produces nothing. And a parse error
    in a *branch* — a status path that only fires when something is already wrong — sits undetected
    until the day it is needed, which is the worst possible moment.

    **Twice now** the same PowerShell trap has cost a full cycle: ``"$passed:"`` parses as a scope
    qualifier rather than a variable followed by a colon, because ``$scope:name`` is valid syntax.
    It needs ``"${passed}:"``. It happened at ``gate.ps1:303`` and again at ``gate.ps1:488``, the
    second time inside the new reduced-coverage status — exactly the kind of rarely-taken branch
    that would otherwise stay broken.

    Uses PowerShell's own parser, so this is the real grammar rather than a regex approximating it.
    """
    path = REPO_ROOT / ".kiro" / "governance" / script
    assert path.is_file(), f"{script} is missing from .kiro/governance/"

    # `Parser::ParseFile` reports every syntax error without executing a single statement.
    probe = (
        "$errors = $null; "
        "$null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path.as_posix()}', [ref]$null, [ref]$errors); "
        "if ($errors) { $errors | ForEach-Object { $_.ToString() }; exit 1 } else { exit 0 }"
    )
    out = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode not in (0, 1):
        pytest.skip(f"could not run the PowerShell parser (exit {out.returncode})")

    assert out.returncode == 0, f"{script} has PowerShell syntax errors:\n{out.stdout.strip()}"


def test_every_project_path_named_in_docs_and_output_exists() -> None:
    """A path presented to the operator must be a path that exists.

    **The incident, 2026-09-15.** The MK0 regression fixture was renamed from
    ``mk0_reference_profile.json`` to ``mk0_benchtop_22kv.json`` so its filename would match its
    ``profile_id``. Four references were left behind, and two of them were not prose:

    * ``profiles/README.md`` told the operator to run
      ``Copy-Item tests\\data\\mk0_reference_profile.json profiles\\my_design.json``.
    * ``ehdpsu/profile.py`` **printed that same command** as the guidance shown when ``profiles/``
      is empty — which is exactly the moment somebody follows it verbatim.

    Nothing caught it. Every existing check verifies that generated *numbers* match, that citations
    resolve, and that tracked files are tracked; none verified that a **path named in a document or
    in user-facing output actually resolves**. A command that cannot work is worse than no command,
    because it is followed before it is doubted.

    Scope, stated rather than implied: this checks paths under the project's own tracked directories
    that appear with a recognisable extension. It does not check directory-only references, paths
    inside ``artifacts/`` (untracked and absent from a clone by design), or paths that are patterns
    rather than literals.
    """
    # Paths that are named deliberately and must NOT exist. Declared with a reason each, the same
    # pattern as DESIGN_VALUE_EXEMPTIONS: an exemption is not wrong, an undeclared one is.
    paths_that_need_not_exist = {
        # A destination in a copy command. It exists after the operator runs it, not before.
        "profiles/my_design.json": "destination of the documented `new`/Copy-Item example",
        # Fed to `git check-ignore --no-index`, which answers about a path whether or not it exists.
        # Creating it would defeat the test.
        "profiles/__ignore_probe__.json": "probe for git check-ignore; must not exist",
        # Named in a docstring recording the fabrication incident, where a delegated seat cited two
        # modules that did not exist. Creating it to satisfy a checker would be the same error again,
        # and deleting the reference would erase the record of why the attribution test exists.
        "src/ehdpsu/provenance.py": "historical record of a fabricated citation; never existed",
    }

    # Directories whose contents are tracked, so a named file in them must exist in a clone.
    tracked_roots = ("tests/data", "solver_inputs", "examples", "profiles", "src/ehdpsu", "docs")
    pattern = re.compile(
        r"(?<![\w/\\.-])((?:" + "|".join(tracked_roots) + r")[/\\][\w./\\-]*\.\w{2,4})"
    )

    searched: list[Path] = []
    for rel in _tracked_files():
        path = REPO_ROOT / rel
        if path.suffix.lower() in {".md", ".py"} and path.is_file():
            searched.append(path)

    assert searched, "no tracked .md or .py files were searched; this is NOT-SCANNED, not CLEAN"

    findings: list[str] = []
    for path in searched:
        if path.name == "test_governance.py":
            # This module names the renamed fixture in the docstring above while explaining the
            # incident. A checker that cannot distinguish discussing a path from publishing one is
            # not a checker -- the fifth time that has come up here.
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in pattern.finditer(line):
                candidate = match.group(1).replace("\\\\", "/").replace("\\", "/")
                # Glob patterns and wildcards are references to a set, not to a file.
                if "*" in candidate or "<" in candidate:
                    continue
                if candidate in paths_that_need_not_exist:
                    continue
                if not (REPO_ROOT / candidate).exists():
                    findings.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: {candidate!r}"
                    )

    assert not findings, (
        f"these paths are named in tracked documents or source but do not exist "
        f"(searched {len(searched)} files):\n" + "\n".join(sorted(set(findings)))
    )


def test_the_machine_local_tool_config_is_ignored() -> None:
    """``tools.local.json`` holds absolute paths on one machine and must never be pushed.

    It exists because installing the solvers on 2026-09-16 exposed a structural gap: ``configured-
    path`` is the **first** route in ``detect.ROUTE_ORDER`` and nothing in the suite could populate
    it. LTspice at ``B:\\LTspice`` and QSPICE at ``B:\\QSPICE`` were both installed and working, and
    both reported ``tool-absent`` — correctly by the contract's own definition, since all four routes
    were attempted and each concluded, and wrongly in the only sense that matters.

    The file is configuration, not repository content. Leaked, it would publish one operator's
    directory layout and would be wrong in every clone — an approximately-correct path for everybody
    else, which is *principle 2, an approximately-correct identifier is worse than an absent one*,
    applied to the fix rather than the defect.

    Checked with ``--no-index`` so the answer holds whether or not the file exists locally.
    """
    code = _check_ignore("tools.local.json")
    assert code == 0, (
        f"tools.local.json is NOT ignored by git (check-ignore exit {code}). It names absolute "
        f"paths on one machine; publishing it would hand every clone a set of wrong tool locations."
    )


def test_the_machine_local_tool_config_is_not_tracked() -> None:
    """Ignored is not the same as absent from the index.

    A file added before the ignore rule stays tracked and keeps being committed, with ``.gitignore``
    saying nothing about it — the failure mode recorded in this file's own ``.gitkeep`` incident,
    where four generated files sat tracked inside a folder everyone believed was ignored.
    ``git ls-files`` is the authoritative tracked check; ``git status`` is not.
    """
    tracked = _git("ls-files", "--", "tools.local.json").strip()
    assert not tracked, (
        "tools.local.json is in the git index despite being ignored. Remove it with "
        "`git rm --cached tools.local.json`; the ignore rule does not retroactively untrack."
    )


# ---------------------------------------------------------------------------
# Declared registers may not shrink silently.
#
# Added 2026-09-16, before the first multi-step delegated batch, because this is the class of defect
# that has escaped the Gate twice and would escape it again.
#
# The incident: a delegated seat rewrote detect.KNOWN_TOOLS and emptied ALL SEVEN `default_paths`
# tuples. Every test passed. The `default-paths` detection route could no longer resolve anything for
# any tool, the seat's report did not mention it, and nothing in the suite could have said so -- the
# tests assert that default_paths is a tuple of Path, and an empty tuple satisfies that perfectly.
#
# The general shape: **reference data is checked for VALIDITY and never for PRESENCE.** A register that
# is emptied is still well-formed. Deletion passes every schema check ever written, which is why
# principle 2, an approximately-correct identifier is worse than an absent one, has a sibling worth
# stating: an ABSENT register is worse than a wrong one, because a wrong entry eventually fails
# visibly and a missing entry just stops doing its job.
#
# So the registers that carry the suite's accumulated knowledge get a floor, and the floor is recorded
# here rather than inferred. Raising it is part of adding an entry.
# ---------------------------------------------------------------------------

REGISTER_FLOORS: dict[str, int] = {
    # profile.DESIGN_VALUE_EXEMPTIONS -- every one is a reasoned decision about what is not a design
    # value, each named in the suite-core-oracle ledger. Losing one silently re-arms the drift test
    # against something deliberately allowed.
    "ehdpsu.profile:DESIGN_VALUE_EXEMPTIONS": 18,
    # detect.EXECUTABLE_PROVENANCE -- vendor-cited filenames. THIS is the register that matters most:
    # three of its entries were fabricated before it existed, and a filename cannot be re-derived,
    # only re-researched. An emptied entry costs a web search; an emptied register costs eleven.
    "ehdpsu.detect:EXECUTABLE_PROVENANCE": 11,
    # detect.GUI_EXECUTABLES -- the launch-during-pytest hazard register. Emptying it makes
    # test_no_version_probe_targets_a_gui_executable pass by vacuity.
    "ehdpsu.detect:GUI_EXECUTABLES": 7,
    # The two declared-gap registers. Each entry is a stated reason a capability is absent; losing one
    # turns a declared gap back into an undeclared one.
    "ehdpsu.detect:TOOLS_WITHOUT_DEFAULT_PATHS": 2,
    # Lowered 5 -> 4 on 2026-09-19, in advance and deliberately. CRSDL Task 7 examines FEMM's
    # headless routes; if one works, femm gains `version_args` and
    # `test_detect.py::test_declared_reasons_are_substantive_and_not_orphaned` then forces its entry
    # out of this register, dropping it to 4. The implementing seat may not edit anything under
    # `tests/`, so a floor of 5 would be a guaranteed stall on a shrink the planner can already
    # predict.
    #
    # This does not make the shrink free. `tests/test_femm_automation.py` asserts that femm's
    # ABSENCE from this register requires a recorded working route, so the entry can only leave
    # against evidence. The floor still guards the other four.
    "ehdpsu.detect:TOOLS_WITHOUT_A_VERSION_PROBE": 4,
    # detect.KNOWN_TOOLS and adapters.ADAPTERS -- the tool table and the adapter registry.
    "ehdpsu.detect:KNOWN_TOOLS": 7,
    "ehdpsu.adapters:ADAPTERS": 3,
}


@pytest.mark.parametrize("target", sorted(REGISTER_FLOORS))
def test_no_declared_register_shrinks(target: str) -> None:
    """Each register holds at least as many entries as it did when the floor was recorded.

    An equality is deliberately NOT used here, unlike the Gate's collected-test floor. Registers grow
    for good reasons and often -- a new adapter, a new vendor citation -- and requiring the floor to be
    bumped on every addition would make it noise that gets bumped without being read. What must never
    happen is a register getting *smaller* without somebody deciding to make it smaller.

    Removing an entry is legitimate. Doing it means lowering the floor here, in a tracked file, in the
    same change -- which is the point: it converts a silent deletion into a visible decision.
    """
    module_name, attr = target.split(":")
    module = importlib.import_module(module_name)
    register = getattr(module, attr)
    floor = REGISTER_FLOORS[target]
    assert len(register) >= floor, (
        f"{target} holds {len(register)} entry/entries, below its recorded floor of {floor}. "
        f"Reference data is normally checked for validity and never for presence, so an emptied "
        f"register passes every other check in this suite while quietly doing nothing. If the removal "
        f"is intended, lower the floor in REGISTER_FLOORS in the same change and say why in the "
        f"relevant task ledger."
    )


def test_every_known_tool_keeps_its_default_paths_or_declares_why() -> None:
    """The specific regression, pinned at the governance level as well as in ``test_detect.py``.

    ``tests/test_detect.py`` already asserts this against ``TOOLS_WITHOUT_DEFAULT_PATHS``. It is
    repeated here on purpose and the duplication is justified: that test lives in the file a seat is
    told to make pass, and this one lives in the file a seat is forbidden to touch. Two different
    guarantees — one that the contract is met, one that the contract cannot be edited into meeting.
    """
    from ehdpsu import detect

    silently_empty = [
        spec.name
        for spec in detect.KNOWN_TOOLS
        if not spec.default_paths and spec.name not in detect.TOOLS_WITHOUT_DEFAULT_PATHS
    ]
    assert not silently_empty, (
        f"tools with no default_paths and no declared reason: {silently_empty}. A delegated seat "
        f"emptied all seven of these on 2026-09-16 and every test still passed."
    )


def test_the_register_floors_name_registers_that_exist() -> None:
    """A floor for a register that has been renamed away is a check guarding nothing.

    The same failure the leakage-scan exemption test guards against: a register of things to check,
    which itself drifts, and reports success over a target it can no longer find.
    """
    for target in REGISTER_FLOORS:
        module_name, attr = target.split(":")
        module = importlib.import_module(module_name)
        assert hasattr(module, attr), (
            f"REGISTER_FLOORS names {target}, which no longer exists. Either the register was "
            f"renamed and this entry is stale, or it was deleted and that needs a ledger entry."
        )
        assert (
            len(getattr(module, attr)) > 0
        ), f"{target} is empty; a floor over nothing checks nothing"
