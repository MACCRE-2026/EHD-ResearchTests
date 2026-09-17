"""The drift test: no design value may live in code.

*Principle 4, two representations of one thing will drift.* Five representations of the 22 kV
design point existed in this repository, and the profile layer exists to end that. This module is
what keeps it ended — without it, `DESIGN_VALUE_EXEMPTIONS` is documentation rather than
enforcement, and the next well-intentioned "just put a sensible default here" reopens the hole.

Two layers, because they catch different things
-----------------------------------------------
**Layer 1, structural.** A design value in code lives in one of exactly three places: a
module-level constant, a dataclass field default, or a function parameter default. Each is found
with ``ast`` and must be registered in :data:`~ehdpsu.profile.DESIGN_VALUE_EXEMPTIONS`.

**Layer 2, by value.** No number that appears in the profile may also appear as a literal anywhere
under ``src/``. This catches the case layer 1 cannot: a design value pasted into the middle of a
function body.

Why ``ast`` and not a regex
---------------------------
A regex over numbers flags array indices, float tolerances, format widths and the ``2/3`` in a
cascade polynomial. It would produce so much noise that the register would fill with exemptions
until the check meant nothing. Parsing gives the *position* of a literal, which is what makes the
distinction between "a design value" and "part of a relation" expressible at all.

Scope, stated rather than implied
---------------------------------
* **Numbers inside expressions are out of scope for layer 1.** ``2.0 * eps0 * mu * L / d**2`` and
  the ``(2/3)N³ + ½N² - ⅙N`` cascade polynomial are parts of *cited relations*, not design values,
  and forcing them into a profile would invite tuning published formulas — the curve-fitting this
  project forbids. Layer 2 covers the subset of those that match a real profile value.
* **Layer 2 skips undistinctive numbers.** ``1.0``, ``2.0`` and ``5`` appear in the profile and
  also, innocently, everywhere. Flagging them would make the check useless, so a small
  common-number allowlist is skipped and named below.
* **Only ``src/`` is scanned.** Tests legitimately pin reference values, which ``profile-seam.md``
  explicitly permits, and documents are covered by the doc-binding checks in
  ``test_mk0_reproduction.py``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import reference_profile

from ehdpsu import profile as prof

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "ehdpsu"

#: Numbers too common to attribute to the profile. Each also appears in the profile, which is
#: exactly why they cannot be used as evidence of a copied design value.
#:
#: ``1.0`` is delta_air_density and also every identity factor. ``2.0`` is the diode emission
#: coefficient and also the ``2`` in a hundred formulas. ``5`` is the stage count and also a loop
#: bound. Including them would bury the real findings.
UNDISTINCTIVE = frozenset({0, 1, 2, 3, 4, 5, 6, 10, 100, 1000, 0.5, 1.5, 2.5})


@dataclass(frozen=True)
class Literal:
    """A numeric literal found somewhere it might not belong."""

    module: str
    qualname: str
    value: float | int
    lineno: int

    @property
    def key(self) -> str:
        """The registration key this literal would need in the exemption register."""
        return f"ehdpsu.{self.module}.{self.qualname}"


def _number(node: ast.expr | None) -> float | int | None:
    """Return the value of a plain numeric literal, else ``None``.

    Returns the number rather than a boolean so the caller gets a narrowed type and does not need
    to re-read ``.value`` off the node, which ``ast`` types as a broad union.

    ``bool`` is excluded even though it subclasses ``int``: ``True`` is not a design value, and
    ``nullable: bool = False`` in a schema declaration is not a number in code.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        return node.value
    return None


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(target, "attr", None) or getattr(target, "id", None)
        if name == "dataclass":
            return True
    return False


def _module_sources() -> dict[str, str]:
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(SRC.glob("*.py"))
        if path.stem != "__init__"
    }


def _collect_declaration_literals() -> list[Literal]:
    """Layer 1: numeric literals in the three places a design value hides.

    Module-level constants, dataclass field defaults, and function parameter defaults. Enum members
    are not collected: they live inside a ``ClassDef`` that is not a dataclass, and the basis ladder
    values are ordering tokens rather than design values.
    """
    found: list[Literal] = []

    for module, source in _module_sources().items():
        tree = ast.parse(source)

        for stmt in tree.body:
            # (a) module-level constants
            if isinstance(stmt, ast.Assign):
                value = _number(stmt.value)
                if value is not None:
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            found.append(Literal(module, target.id, value, stmt.lineno))
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                value = _number(stmt.value)
                if value is not None:
                    found.append(Literal(module, stmt.target.id, value, stmt.lineno))

            # (b) dataclass field defaults
            elif isinstance(stmt, ast.ClassDef) and _is_dataclass(stmt):
                for member in stmt.body:
                    if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                        value = _number(member.value)
                        if value is not None:
                            found.append(
                                Literal(
                                    module,
                                    f"{stmt.name}.{member.target.id}",
                                    value,
                                    member.lineno,
                                )
                            )

        # (c) function parameter defaults, at any nesting depth
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = fn.args
            positional = args.posonlyargs + args.args
            paired: list[tuple[str, ast.expr | None]] = [
                (arg.arg, default)
                for arg, default in zip(
                    positional[len(positional) - len(args.defaults) :],
                    args.defaults,
                    strict=False,
                )
            ]
            paired += [
                (arg.arg, default)
                for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=False)
            ]
            for arg_name, default in paired:
                value = _number(default)
                if value is not None:
                    found.append(Literal(module, f"{fn.name}.{arg_name}", value, fn.lineno))

    return found


def _is_registered(key: str) -> bool:
    """True when ``key`` is covered by the exemption register.

    A register entry covers an exact key, or acts as a prefix for a whole module or function when
    written as ``ehdpsu.sweeps`` or ``ehdpsu.sweeps.*``.
    """
    for raw in prof.DESIGN_VALUE_EXEMPTIONS:
        entry = raw.removesuffix(".*")
        if key == entry or key.startswith(entry + "."):
            return True
    return False


class TestLayerOneDeclarations:
    """Every numeric declaration in ``src/`` is either absent or registered with a reason."""

    def test_the_scan_finds_something(self) -> None:
        """A scan that found nothing is NOT-SCANNED, not CLEAN.

        If the AST walk silently stopped matching — a renamed decorator, a syntax change — this
        whole module would pass while checking nothing.
        """
        assert _collect_declaration_literals(), (
            "the declaration scan found zero numeric literals across src/ehdpsu, which cannot be "
            "right. The AST walk has stopped matching."
        )

    def test_every_declaration_is_registered(self) -> None:
        unregistered = [
            lit for lit in _collect_declaration_literals() if not _is_registered(lit.key)
        ]
        assert not unregistered, (
            "these numeric declarations are not in DESIGN_VALUE_EXEMPTIONS. If a value is a design "
            "choice it belongs in a profile; if it is a physical constant, a cited coefficient or "
            "a study range, register it there with the reason:\n"
            + "\n".join(
                f"    {lit.key} = {lit.value!r}  ({lit.module}.py:{lit.lineno})"
                for lit in unregistered
            )
        )

    def test_the_design_dataclasses_carry_no_numeric_defaults(self) -> None:
        """Named separately from the general check, because this is the specific regression.

        ``DesignParameters`` and ``SpiceParams`` held the MK0 design point as defaults. Re-adding
        one is the edit most likely to happen by accident.
        """
        offenders = [
            lit
            for lit in _collect_declaration_literals()
            if lit.qualname.startswith(("DesignParameters.", "SpiceParams."))
        ]
        assert not offenders, (
            f"the design dataclasses have numeric defaults again: "
            f"{[(o.key, o.value) for o in offenders]}. Build them from a profile."
        )


class TestLayerTwoValues:
    """No distinctive profile value appears as a literal under ``src/``."""

    @staticmethod
    def _distinctive_profile_values() -> dict[float, str]:
        """Profile values worth searching for, keyed by value."""
        profile_obj = reference_profile()
        out: dict[float, str] = {}
        for name, entry in profile_obj.values.items():
            if entry.value is None:
                continue
            numeric = float(entry.value)
            if numeric in UNDISTINCTIVE:
                continue
            out[numeric] = name
        return out

    def test_there_are_distinctive_values_to_search_for(self) -> None:
        # Guards against the allowlist growing until nothing is checked.
        distinctive = self._distinctive_profile_values()
        assert len(distinctive) >= 15, (
            f"only {len(distinctive)} profile values are considered distinctive enough to search "
            f"for. UNDISTINCTIVE has grown too broad and this layer no longer checks much."
        )

    def test_no_profile_value_is_hardcoded_in_src(self) -> None:
        """Scans every module except those carrying a blanket exemption.

        ``ehdpsu.sweeps`` is blanket-exempt because every numeric declaration in it is a study
        range, and three of them collide numerically with profile fields: the wire-radius sweep
        deliberately *starts* at the design radius, and ``0.02``/``5e-9`` coincide with the dead-time
        fraction and the diode saturation current by pure arithmetic accident. Flagging those would
        be a false positive, and a check that cries wolf gets switched off.
        """
        distinctive = self._distinctive_profile_values()
        findings: list[str] = []

        # A literal that layer 1 already found AND that is registered has been explicitly accounted
        # for, so re-reporting it here is noise. Added 2026-09-15: `_ABSOLUTE_UNCERTAINTY_TOLERANCE`
        # is 1e-9, numerically identical to the profile's `C_stage_F`, and a float comparison
        # tolerance is not a capacitance. Rather than widen UNDISTINCTIVE -- which would blind this
        # layer to a real design value -- the exemption is carried by the named declaration.
        #
        # This deliberately does NOT exempt unregistered declarations: those still fail layer 1.
        accounted_for = {
            (lit.module, lit.lineno)
            for lit in _collect_declaration_literals()
            if _is_registered(lit.key)
        }

        for module, source in _module_sources().items():
            if _is_registered(f"ehdpsu.{module}"):
                continue
            for node in ast.walk(ast.parse(source)):
                if (module, getattr(node, "lineno", -1)) in accounted_for:
                    continue
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                    continue
                field_name = distinctive.get(float(node.value))
                if field_name is not None:
                    findings.append(
                        f"    {module}.py:{node.lineno}: {node.value!r} "
                        f"equals profile field {field_name!r}"
                    )

        assert not findings, (
            "these literals in src/ equal a value that lives in the profile. A design value in "
            "code is a second representation of it, and both copies keep working while they "
            "disagree:\n" + "\n".join(findings)
        )


class TestTheRegisterItself:
    """The register is the check's configuration, so its own shape matters."""

    def test_no_entry_is_dead(self) -> None:
        """An exemption matching nothing is stale and should be removed.

        A register full of entries for code that no longer exists is how the next reader concludes
        the check is unmaintained and stops trusting it. Module-wide entries are skipped: they
        legitimately cover whatever the module currently declares, including nothing.
        """
        literals = _collect_declaration_literals()
        dead: list[str] = []
        for raw in prof.DESIGN_VALUE_EXEMPTIONS:
            entry = raw.removesuffix(".*")
            # A bare `ehdpsu.<module>` entry is a deliberate blanket; do not call it dead.
            if entry.count(".") <= 1:
                continue
            if not any(lit.key == entry or lit.key.startswith(entry + ".") for lit in literals):
                dead.append(raw)
        assert not dead, (
            f"these exemptions match no literal in src/ any more: {dead}. Remove them, or the "
            f"register stops describing the code."
        )

    @pytest.mark.parametrize("key", sorted(prof.DESIGN_VALUE_EXEMPTIONS))
    def test_every_exemption_is_recorded_in_the_ledger(self, key: str) -> None:
        """An exemption must be named in the append-only ledger, not merely reasoned about in code.

        **The hole this closes.** The drift test refuses a numeric design value anywhere in ``src/``,
        and this register is its only escape hatch. Nothing previously stopped an author from
        **adding an exemption to make the check pass instead of fixing the code** — the only
        requirement was a reason longer than twenty characters, and a plausible-sounding sentence is
        cheap to produce. That matters most for work delegated to a cheap coding seat, where the
        incentive is to get the Gate green rather than to get the design right.

        Naming the key here raises the cost from one sentence to a dated, reviewable claim in a
        record that is never edited or deleted. It does not make gaming impossible; it makes it
        **visible**, which is the achievable goal.

        Deliberately *not* a count check against a stored baseline: a baseline number is a second
        representation of the register and would drift from it, which is
        *principle 4, two representations of one thing will drift*, applied to the guard itself.
        """
        ledger = (
            REPO_ROOT / ".kiro" / "skills" / "suite-core-oracle" / "task_ledger.md"
        ).read_text(encoding="utf-8")

        assert key in ledger, (
            f"{key!r} is registered in DESIGN_VALUE_EXEMPTIONS but is not named anywhere in\n"
            f"  .kiro/skills/suite-core-oracle/task_ledger.md\n"
            f"Append a ledger entry naming the key and saying why the value is not a design value. "
            f"Adding the entry is part of adding the exemption."
        )

    @pytest.mark.parametrize("key", sorted(prof.DESIGN_VALUE_EXEMPTIONS))
    def test_every_entry_names_the_package(self, key: str) -> None:
        assert key.startswith("ehdpsu."), (
            f"{key!r} is not a dotted path into this package, so it cannot be matched against "
            f"anything the scan finds."
        )
