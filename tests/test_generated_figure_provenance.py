"""Every figure in a generated artifact traces to the profile — CRSDL Task 18, Batch A.

Written 2026-09-19 before the implementation. Audit finding F7.

The gap this closes
-------------------
``tests/test_profile_seam.py`` enforces the seam in two layers: **structurally**, over module
constants, dataclass field defaults and function parameter defaults found with ``ast``; and **by
value**, over any number that also appears in the profile. Between them they cover every route a
design value takes into code *as a number*.

Neither covers a design value reaching a **tracked artifact as text**, and the audit found one::

    * Target: single EHD cell, ~80-120 W, 3-5 s bursts.

``80`` and ``120`` are not AST numeric literals — they are inside a string — and they are not profile
values, so layer 2 had nothing to match. The netlist therefore asserted a power target of
``~80-120 W`` while the profile's own relation derives **25.79 W**: two representations of one design
figure, disagreeing by 3.10x to 4.65x, in a file a cloner can open. *Principle 4, two representations
of one thing will drift* — this pair was born drifted.

Why this checks artifacts and not all source text
-------------------------------------------------
The first draft of this module swept every string literal in the package and found **82** figures, of
which exactly three were defects. Most of the rest were not near-misses, they were the wrong
*category*: ``ehdpsu.claims`` and ``ehdpsu.breadcrumb`` hold inherited claim text **on purpose** —
recording what a source asserted is their entire function, and they are the audit trail rather than a
drift risk. ``ehdpsu.mk0_reference`` holds the pinned reference values, which are deliberately
hardcoded and already declared in ``DESIGN_VALUE_EXEMPTIONS``.

A check that reports 80 non-findings to surface 3 gets switched off, and worse, it invites bulk
registration — which would sweep the real findings in with the noise.

So the property is stated correctly instead: **a figure written into a generated artifact must trace
to the profile or to a derived quantity, or be registered with its citation.** That is narrower by
*type* rather than by exclusion — the artifacts are the things a reader outside this repository will
quote, which is exactly where an unsupported figure does damage. It is also behavioural rather than
static, so docstrings and comments that never reach an artifact are correctly out of scope.

What the fix is, and what it is not
-----------------------------------
**Not** "move 80-120 W into the profile." That enshrines a figure the profile's own power relation
contradicts; a claimed-versus-derived disagreement is Task 15's job, not a field.

**Not** "register the findings." See ``test_no_withdrawn_claim_is_registered_instead_of_withdrawn``.

Both figures are **inherited claims about hardware that was never built**, traceable to the AI Studio
conversation, supported by nothing. Both are **withdrawn** and the withdrawal recorded —
*physics-honesty 7, absent beats approximately correct*, the same basis on which ``sweep_stages.csv``
is withheld from ``examples/``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import REFERENCE_PROFILE_PATH, reference_design, reference_spice_params

from ehdpsu import adapters, spice
from ehdpsu import profile as prof
from ehdpsu.operating_point import operating_point

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / ".kiro" / "skills" / "suite-core-oracle" / "task_ledger.md"

#: SI prefix multipliers, so ``22 kV`` and ``22000 V`` are recognised as one figure.
_PREFIX = {"": 1.0, "k": 1e3, "M": 1e6, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}

#: Base units whose presence beside a number makes it a **design figure**. Closed set on purpose: an
#: open-ended unit regex matches every version string and ordinal in the repository.
_BASE = ("W", "V", "A", "Hz", "F", "H", "s", "m", "N", "Pa", "gf")

#: Single-character units **require** a preceding space. Without that rule ``.tran 0 2m 0 20n`` reads
#: as ``2 metres`` and ``in 24 steps`` reads as ``24 seconds`` — both were false positives in the
#: first draft. Multi-character units may abut, because ``22kV`` is a plausible way to write it.
_FIGURE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"(?:\s+([kMmunp]?(?:" + "|".join(u for u in _BASE if len(u) == 1) + r"))"
    r"|\s?([kMmunp]?(?:" + "|".join(u for u in _BASE if len(u) > 1) + r")))"
    # `/` is excluded so a compound unit is never half-matched: `1.833e+06 V/m` is a FIELD, and
    # reading its `V` as a voltage produced two false positives in the first draft.
    #
    # Stated tradeoff: this also stops `8e-08 s/edge` matching, so the dead-time figure is a known
    # false negative. Accepted because the period on the same line (`4e-06 s`) catches the identical
    # class, and because a false positive on every field quantity in every artifact is the failure
    # mode that gets a check switched off.
    r"(?![A-Za-z0-9_/])"
)


def _register() -> dict[str, str]:
    """The declared exemption register, or a failure stating what it must be.

    Resolved with ``getattr`` rather than imported so its absence before implementation is a readable
    assertion instead of a module-scope ``ImportError``, which would abort collection for this whole
    file and hand the implementing seat "1 error" in place of a list of requirements.
    """
    register = getattr(prof, "GENERATED_FIGURE_EXEMPTIONS", None)
    assert register is not None, (
        "ehdpsu.profile.GENERATED_FIGURE_EXEMPTIONS does not exist. It belongs beside "
        "DESIGN_VALUE_EXEMPTIONS and maps '<artifact>:<matched figure>' to the reason the figure "
        "legitimately appears in a generated artifact without tracing to the profile. Cited material "
        "properties and physical conditions belong in it; inherited design claims do not."
    )
    assert isinstance(register, dict), "GENERATED_FIGURE_EXEMPTIONS must be a dict of key -> reason"
    return register


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Every generated artifact's text, keyed by filename.

    Generated through the adapters rather than read from ``solver_inputs/`` so the test examines what
    the code produces now, not what happened to be committed.
    """
    out = tmp_path_factory.mktemp("generated")
    text: dict[str, str] = {}
    for adapter in adapters.ADAPTERS:
        for path in adapter.generate(out):
            text[path.name] = path.read_text(encoding="utf-8")
    # The adapters already emit the netlist, so calling build_netlist as well would count every
    # figure in it twice and double the register. Asserted here instead, so that the adapter route
    # and the direct route cannot silently diverge.
    direct = spice.build_netlist(p=reference_design(), sp=reference_spice_params())
    assert text["ehd_llc_cw.cir"] == direct, (
        "the netlist the QSPICE adapter writes differs from what spice.build_netlist returns. Two "
        "routes to one artifact, disagreeing."
    )
    return text


@pytest.fixture(scope="module")
def traceable() -> set[tuple[float, str]]:
    """Every ``(value, unit)`` the profile holds or the operating point derives, in base SI units.

    **The unit is carried deliberately, and leaving it out was a real bug in this module's first
    draft.** A value-only comparison let ``3-5 s bursts`` pass, because the figure ``5`` matched
    ``N_stages = 5`` — a dimensionless stage count standing in for five seconds. That is
    *principle 2, an approximately-correct identifier is worse than an absent one*: the match was
    non-empty, wrong, and silently satisfied the check that existed to catch it.
    """
    loaded = prof.load(REFERENCE_PROFILE_PATH)
    values: set[tuple[float, str]] = set()
    for spec in prof.FIELDS:
        v = loaded.value(spec.name)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values.add((float(v), spec.unit.strip()))
    for q in operating_point(loaded).as_dict().values():
        values.add((float(q.value), q.unit.strip()))
    return values


def _figures(text: str) -> dict[str, tuple[float, str]]:
    """``{matched text: (value in base units, base unit)}`` for every figure in the artifact."""
    found: dict[str, tuple[float, str]] = {}
    for m in _FIGURE.finditer(text):
        unit = m.group(2) or m.group(3)
        base = next((u for u in sorted(_BASE, key=len, reverse=True) if unit.endswith(u)), None)
        if base is None:  # pragma: no cover - the regex cannot produce this
            continue
        prefix = unit[: -len(base)]
        found[m.group(0)] = (float(m.group(1)) * _PREFIX.get(prefix, 1.0), base)
    return found


def _traces(value: float, unit: str, traceable: set[tuple[float, str]]) -> bool:
    """Within 0.5% of a profile or derived value **of the same unit**.

    The tolerance absorbs display rounding and nothing else. Zero is structural, never a design
    figure: a grounded boundary or a reference potential written as ``0 V`` is the *absence* of a
    value, and requiring the profile to hold a zero so a ground node can be named would be
    bookkeeping with no reader.
    """
    if value == 0.0:
        return True
    return any(u == unit and abs(value - t) <= 5e-3 * max(abs(value), abs(t)) for t, u in traceable)


def _untraceable(artifacts: dict[str, str], traceable: set[tuple[float, str]]) -> dict[str, float]:
    """``{'<artifact>:<figure>': value}`` for figures that trace to nothing of their own unit."""
    out: dict[str, float] = {}
    for name, text in artifacts.items():
        for matched, (value, unit) in _figures(text).items():
            if not _traces(value, unit, traceable):
                out[f"{name}:{matched}"] = value
    return out


class TestEveryFigureInAGeneratedArtifactTraces:
    def test_no_untraceable_figure_is_unregistered(
        self, artifacts: dict[str, str], traceable: set[tuple[float, str]]
    ) -> None:
        """The sweep, over every artifact every adapter generates.

        A figure here is either traceable to the profile, or **cited** — registered with its citation
        — or it is an inherited claim that belongs withdrawn. There is no fourth case, and "it is
        only a comment" is not one: the comment is inside a file a cloner opens.
        """
        register = _register()
        stray = _untraceable(artifacts, traceable)
        unregistered = sorted(k for k in stray if k not in register)
        assert not unregistered, (
            "these figures appear in generated artifacts and trace to neither the profile nor a "
            "derived quantity, and are not registered:\n  "
            + "\n  ".join(f"{k}  (= {stray[k]:.6g} base units)" for k in unregistered)
            + "\n\nRegister it with its citation if it is a cited constant or condition. Derive it "
            "from the profile if it is a design value. Withdraw it and record the withdrawal if it "
            "is an inherited claim nothing supports."
        )

    def test_the_withdrawn_power_target_is_gone(
        self, artifacts: dict[str, str], traceable: set[tuple[float, str]]
    ) -> None:
        """``~80-120 W`` specifically, so a later reader sees the defect and not only the rule."""
        stray = _untraceable(artifacts, traceable)
        offenders = sorted(k for k in stray if re.search(r":\s*(80|120)\s?W$", k))
        assert not offenders, (
            f"the unsupported power target is still in a generated artifact: {offenders}. The "
            f"profile derives its own electrical power; a second figure disagreeing with it by "
            f"3.10x to 4.65x is principle 4 in a file a cloner can open."
        )

    def test_the_withdrawn_burst_duration_is_gone(
        self, artifacts: dict[str, str], traceable: set[tuple[float, str]]
    ) -> None:
        """``3-5 s bursts`` — an inherited claim about a controller that does not exist."""
        stray = _untraceable(artifacts, traceable)
        offenders = sorted(k for k in stray if re.search(r":\s*[35]\s+s$", k))
        assert not offenders, (
            f"the inherited burst-duration claim is still in a generated artifact: {offenders}. No "
            f"hardware has been built and nothing supports 3-5 s. Withdraw it and record why; do "
            f"not invent a profile field to hold it."
        )

    def test_the_planners_own_transient_comment_is_accounted_for(
        self, artifacts: dict[str, str], traceable: set[tuple[float, str]]
    ) -> None:
        """Found by writing this test: commit 9fe8c12 added six unsourced figures of its own.

        The active ``.tran`` directive landed with an order-of-magnitude justification in its comment
        — ``200 pF``, ``22 kV``, ``2 ms``, ``250 kHz``, ``200 us`` — none of which traces. Most are
        *explanatory*, and the transient duration is a real parameter that should come from somewhere
        declared. Named as its own test because the planner wrote it three commits before writing the
        check that catches it, which is the most honest available demonstration that this class of
        defect is not something only other people produce.
        """
        stray = _untraceable(artifacts, traceable)
        register = _register()
        offenders = sorted(
            k
            for k in stray
            if k not in register and re.search(r":\s*(200\s?pF|2\s+ms|200\s?us)$", k)
        )
        assert not offenders, (
            f"the transient-duration justification still carries unsourced figures: {offenders}. "
            f"Derive the duration from a declared value, or register the explanatory figures with "
            f"the reasoning they came from."
        )


class TestTheNetlistStatesThePowerItsProfileDerives:
    def test_the_netlist_carries_the_derived_electrical_power(
        self, artifacts: dict[str, str]
    ) -> None:
        """Having withdrawn the unsupported target, state the supported figure.

        The point is not that a netlist must mention power. It is that **if** it does, the figure
        comes from the profile — at which point it cannot contradict it, because it *is* it. A netlist
        that silently stopped mentioning power would satisfy the tests above while losing information
        the reader wants.
        """
        loaded = prof.load(REFERENCE_PROFILE_PATH)
        power = operating_point(loaded).as_dict()["power"].value
        netlist = artifacts["ehd_llc_cw.cir"]
        wanted = f"{power:.4g}"
        assert wanted in netlist, (
            f"the netlist does not state its own derived electrical power ({wanted} W). Emit it, so "
            f"the artifact and the profile cannot disagree."
        )

    def test_the_netlist_says_which_side_of_the_converter(self, artifacts: dict[str, str]) -> None:
        """HV output power is not wall-plug input power, and the audit could not tell which was meant.

        The withdrawn ``~80-120 W`` may have meant input, implying a chain efficiency nobody
        recorded. Whatever figure replaces it must say which side it describes, or the next reader
        inherits the same ambiguity.
        """
        netlist = artifacts["ehd_llc_cw.cir"].lower()
        assert any(
            phrase in netlist
            for phrase in ("hv output power", "output power", "delivered power", "hv power")
        ), "the netlist states a power figure without saying whether it is input or output power."


class TestTheWithdrawalIsRecorded:
    def test_the_ledger_records_both_withdrawals(self) -> None:
        """A withdrawn claim leaves a record naming it, or it gets re-proposed.

        Terminal states are ``COMPLETED``, ``WITHDRAWN`` and ``SUPERSEDED``. A figure that simply
        vanishes from source has no terminal state at all, and the next person to read the AI Studio
        transcript will put it back.
        """
        assert LEDGER.is_file(), f"{LEDGER} is missing"
        text = LEDGER.read_text(encoding="utf-8")
        assert "80-120" in text or "80–120" in text, (
            "the ledger does not name the withdrawn ~80-120 W power target. Append an entry saying "
            "what it claimed, that nothing supported it, and that the profile derives 25.79 W."
        )
        assert re.search(
            r"3-5\s?s|3–5\s?s|burst duration", text
        ), "the ledger does not name the withdrawn 3-5 s burst-duration claim."


class TestTheRegisterItselfIsDisciplined:
    """Mirrors the guards already on ``DESIGN_VALUE_EXEMPTIONS``.

    A register with no discipline becomes where inconvenient findings are filed, which turns an
    enforcement mechanism into a list nobody reads.
    """

    def test_every_exemption_carries_a_substantive_reason(self) -> None:
        for key, reason in _register().items():
            assert isinstance(reason, str) and len(reason) > 20, (
                f"{key!r} has no substantive reason. A cited constant states its citation; a "
                f"condition states where it came from."
            )

    def test_every_key_names_an_artifact_and_a_figure(self) -> None:
        for key in _register():
            assert ":" in key, (
                f"{key!r} is not in '<artifact>:<figure>' form. An artifact-wide blanket would "
                f"exempt every figure in the file, which is what this check exists to prevent."
            )

    def test_no_exemption_is_dead(
        self, artifacts: dict[str, str], traceable: set[tuple[float, str]]
    ) -> None:
        """An entry matching nothing is stale, and a stale register hides the live ones."""
        stray = _untraceable(artifacts, traceable)
        dead = sorted(k for k in _register() if k not in stray)
        assert not dead, (
            f"these exemptions match nothing in any generated artifact and are stale: {dead}. "
            f"Remove them so the register keeps describing what the code emits."
        )

    def test_no_withdrawn_claim_is_registered_instead_of_withdrawn(self) -> None:
        """Registering the findings would satisfy the sweep and defeat its purpose.

        The cheapest way to green this module is to paste the two withdrawn figures into the register
        with a plausible reason. This test exists because that route is open and tempting, and
        because the whole point is that neither figure is supported by anything.
        """
        offenders = sorted(
            k for k in _register() if re.search(r":\s*(80|120)\s?W$|:\s*[35]\s+s$", k)
        )
        assert not offenders, (
            f"the withdrawn claims are registered rather than withdrawn: {offenders}. The register "
            f"is for cited constants and conditions, not for figures nothing supports."
        )
