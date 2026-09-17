"""The spec-scope-profile: the one home for a design value.

A design value lives in a profile and nowhere else — not in a dataclass default, a module
constant, a docstring, a plot label, a generated netlist or a test fixture.
*Principle 4, two representations of one thing will drift.*

The condition this ends
-----------------------
Five representations of the 22 kV design point existed here: ``physics.py``'s
``DesignParameters`` defaults, ``README.md``, ``docs/SPEC_SHEET.md``, ``docs/PHYSICS_NOTES.md``,
and the generated netlist's text. ``spice.py`` also hardcoded ``cap = "1n"`` with a comment
admitting it duplicated ``C_stage``, and carried an ``f_sw_hz`` default beside
``DesignParameters.f_sw``. Every copy kept working while they disagreed.

What counts as a design value
-----------------------------
Sharp, or the drift test built on it is toothless or noisy.

* **A design value is an operator choice** — wire radius, gap, operating voltage, stage count,
  turns ratio, diode ratings. It belongs here.
* **A physical constant is not** — ``EPS0``, ``G_EARTH``. Nobody chooses them.
* **A cited empirical coefficient is not** — Peek's ``g0`` and ``c``, the air-breakdown figure.
  They are part of a *cited relation*; moving them into a profile invites per-design tuning,
  which is the curve-fitting this project forbids.
* **A study range is not** — sweep endpoints and point counts specify an investigation, not the
  artifact.

:data:`DESIGN_VALUE_EXEMPTIONS` registers every numeric literal that survives this rule, with its
reason. An exemption is not wrong; an **undeclared** one is.

Basis, and why this lowers the MK0 ceiling
------------------------------------------
Each field carries a basis from :mod:`ehdpsu.basis` plus a ``kind`` saying why:

* ``choice`` — the operator specified it. ``claimed``, because a manufacturer's spec for 25 µm
  wire is an assertion nobody has put a micrometer to. It becomes ``measured`` when the built
  article is measured, which is an expected transition rather than a hypothetical one.
* ``property`` — a claim about nature, such as ion mobility. ``claimed`` until this apparatus
  verifies it.

**Consequence, stated rather than smoothed over.** Low-water-mark over ``claimed`` inputs makes
the MK0 chain ``claimed`` — one tier *below* the ``analytical-placeholder`` recorded in
``artifacts/04_BreadCrumbs/2026-09-15_mk0_retrospective.jsonld``. That corpus modelled the
provenance of the **formulas** and not of the **inputs**. Encoding inputs honestly lowers the
ceiling, and the ceiling dropping is the correct outcome. Raising a basis to preserve a tidier
number would be the laundering this project exists to catch.

No physics, and no derived values
---------------------------------
This module loads, validates, diffs, migrates and saves. It holds no formula, and a profile never
stores a derived value: a stored derivation is a second representation of its inputs.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .basis import Basis, low_water_mark

#: Bump only alongside an entry in :data:`MIGRATIONS`.
SCHEMA_VERSION = 1

#: Tracked, because a clone needs the design point to reproduce anything.
#
#: Resolved from the package location rather than the process working directory. A relative
#: ``Path("profiles")`` would make ``default_profile()`` succeed or fail depending on where the
#: caller happened to be invoked from, which is the kind of environment-dependent behaviour that
#: looks like a code bug when it is reproduced.
DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[2] / "profiles"

#: The profile every module falls back to when no other is supplied.
#:
#: This is a **selection**, not a design value: it names which design to load, and changing it
#: changes which numbers are used without changing any number. Kept in this module so the choice
#: lives beside the loader rather than being repeated in each consumer.
DEFAULT_PROFILE_ID = "mk0_benchtop_22kv"

#: Spelled out so a missing unit and a dimensionless one are distinguishable.
DIMENSIONLESS = "1"

FieldKind = Literal["choice", "property"]

_ALLOWED_TOP_KEYS = frozenset({"schema_version", "profile_id", "title", "provenance", "design"})
_ALLOWED_VALUE_KEYS = frozenset({"value", "unit", "basis", "kind", "refs", "note"})


class ProfileError(ValueError):
    """Raised when a profile is malformed, mis-united, or at an unhandled schema version."""


@dataclass(frozen=True)
class FieldSpec:
    """The schema for one design field. The only place field names and units are declared."""

    name: str
    section: str
    unit: str
    kind: FieldKind
    #: ``int`` for counts. Enforced, because ``N_stages = 5.5`` is nonsense that would otherwise
    #: propagate into a cascade polynomial.
    numeric_type: type
    doc: str
    #: ``True`` where ``null`` legitimately means "derive it". An explicit null is honest where a
    #: magic ``0.0`` sentinel is not — *principle 2, an approximately-correct identifier is worse
    #: than an absent one*.
    nullable: bool = False


def _f(
    name: str,
    section: str,
    unit: str,
    kind: FieldKind,
    numeric_type: type,
    doc: str,
    nullable: bool = False,
) -> FieldSpec:
    return FieldSpec(name, section, unit, kind, numeric_type, doc, nullable)


# Units live in identifiers and radius-versus-diameter is explicit, because "25 µm" read as a
# radius gives V_onset = 2.10 kV and as a diameter 1.63 kV -- a 29% split -- and both readings
# already exist in this project's source material.
FIELDS: tuple[FieldSpec, ...] = (
    _f(
        "r_wire_m",
        "emitter",
        "m",
        "choice",
        float,
        "Emitter wire RADIUS. Not a diameter: it sits inside both Peek's 1/sqrt(r) term and "
        "ln(d/r), so the two readings differ by 29% in onset voltage.",
    ),
    _f("L_wire_m", "emitter", "m", "choice", float, "Active emitter wire length."),
    _f(
        "m_rough_factor",
        "emitter",
        DIMENSIONLESS,
        "choice",
        float,
        "Peek surface-roughness factor. 1.0 polished, ~0.6-0.85 practical wire.",
    ),
    _f(
        "d_gap_m",
        "gap",
        "m",
        "choice",
        float,
        "Emitter-to-collector gap DISTANCE, wire centre to collector plane.",
    ),
    _f(
        "delta_air_density",
        "environment",
        DIMENSIONLESS,
        "property",
        float,
        "Relative air density. 1.0 is sea-level standard air.",
    ),
    _f(
        "mu_ion_m2_per_Vs",
        "environment",
        "m^2/(V*s)",
        "property",
        float,
        "Ion mobility in air. A literature value, unverified in this apparatus.",
    ),
    _f("V_op_V", "supply", "V", "choice", float, "DC operating voltage at the emitter."),
    _f(
        "f_sw_Hz",
        "multiplier",
        "Hz",
        "choice",
        float,
        "Switching frequency. Previously duplicated as DesignParameters.f_sw and "
        "SpiceParams.f_sw_hz; there is now one.",
    ),
    _f(
        "N_stages",
        "multiplier",
        "count",
        "choice",
        int,
        "Cockcroft-Walton stage count. Droop grows as N^3, so this is not a free knob.",
    ),
    _f("C_stage_F", "multiplier", "F", "choice", float, "Per-stage capacitance."),
    _f("V_bus_V", "driver", "V", "choice", float, "DC bus feeding the LLC front end."),
    _f("L_r_H", "driver", "H", "choice", float, "Resonant series inductance."),
    _f("C_r_F", "driver", "F", "choice", float, "Resonant series capacitance."),
    _f("L_m_H", "driver", "H", "choice", float, "Primary magnetising inductance."),
    _f(
        "L_sec_H",
        "driver",
        "H",
        "choice",
        float,
        "Secondary self-inductance. null means derive it as L_m_H * turns_ratio^2.",
        nullable=True,
    ),
    _f(
        "k_coupling",
        "driver",
        DIMENSIONLESS,
        "choice",
        float,
        "Transformer mutual coupling coefficient, 0 < k < 1.",
    ),
    _f("C_sec_F", "driver", "F", "choice", float, "Secondary self-capacitance lump."),
    _f(
        "turns_ratio_sec_per_pri",
        "driver",
        DIMENSIONLESS,
        "choice",
        float,
        "Step-up turns ratio, SECONDARY over PRIMARY. The direction is in the name because the "
        "reciprocal is an equally plausible reading and differs by a factor of 144 here.",
    ),
    _f(
        "deadtime_frac",
        "driver",
        DIMENSIONLESS,
        "choice",
        float,
        "Dead time as a fraction of the switching period, per edge.",
    ),
    _f("diode_BV_V", "rectifier", "V", "choice", float, "HV rectifier reverse Vrrm."),
    _f("diode_Cjo_F", "rectifier", "F", "choice", float, "Zero-bias junction capacitance."),
    _f("diode_Rs_ohm", "rectifier", "ohm", "choice", float, "Series resistance."),
    _f("diode_tt_s", "rectifier", "s", "choice", float, "Transit time, a recovery proxy."),
    _f("diode_Is_A", "rectifier", "A", "choice", float, "Saturation current."),
    _f("diode_n", "rectifier", DIMENSIONLESS, "choice", float, "Diode emission coefficient."),
)

FIELDS_BY_NAME: dict[str, FieldSpec] = {spec.name: spec for spec in FIELDS}
SECTIONS: tuple[str, ...] = tuple(dict.fromkeys(spec.section for spec in FIELDS))


# Numeric literals that legitimately remain in code. `tests/test_profile_seam.py` reads this and
# fails on a design-shaped literal that is not registered here.
DESIGN_VALUE_EXEMPTIONS: dict[str, str] = {
    "ehdpsu.physics.EPS0": "Permittivity of vacuum. A constant of nature.",
    "ehdpsu.physics.G_EARTH": "Standard gravity, used only for the N-to-grams-force conversion "
    "at an output boundary.",
    "ehdpsu.physics.AIR_BREAKDOWN_FIELD": "Uniform-field air breakdown at STP (~30 kV/cm), from "
    "Kuffel & Zaengl. A cited material property; putting it in a profile would invite "
    "per-design tuning of a published figure.",
    "ehdpsu.physics.peek_inception_field.g0": "Peek's base gradient 3.1e6 V/m, part of the cited "
    "empirical relation. Tuning it per design is the curve-fitting the project forbids.",
    "ehdpsu.physics.peek_inception_field.c": "Peek's coefficient 0.308 cm^0.5. Same reasoning.",
    "ehdpsu.sweeps": "Sweep endpoints and point counts specify an investigation, not the "
    "artifact being designed. A blanket entry: every numeric declaration in that module is a "
    "study range. Note that `sweep_wire_radius`'s lower endpoint coincides with the design "
    "radius because the study deliberately starts at the design point; that is a relationship, "
    "not a copy.",
    "ehdpsu.mk0_reference": "Pinned MK0 reference values. These are expected OUTPUTS, not design "
    "inputs, and `profile-seam.md` names them as the one permitted exception: their whole job is "
    "to be hardcoded so they fail when the physics moves. A profile stores no derived value.",
    "ehdpsu.profile.SCHEMA_VERSION": "The profile schema's own version number. It describes the "
    "file format, not the apparatus, and putting it inside the file it versions would be "
    "circular.",
    "ehdpsu.claims": "Figures asserted by an external source, recorded verbatim so they can be "
    "adjudicated. They are NOT design values and are never used as inputs to anything -- they exist "
    "to be checked against. A blanket entry, and note that the MK1 claim adopts the same literature "
    "ion mobility (1.5e-4) that appears in profiles, which the value scan would otherwise flag: a "
    "claim quoting a literature figure is not a design value living in code.",
    "ehdpsu.crossvalidate.compare_routes.close_ratio": "How near two central values must be to call "
    "an agreement strong rather than weak. A comparison threshold, not a property of the apparatus.",
    "ehdpsu.crossvalidate.compare_routes.band_ratio": "How different two band widths must be before "
    "the disagreement about precision is flagged. Also a comparison threshold.",
    "ehdpsu.cli": "Process exit codes. They describe how a command terminated, not the apparatus, "
    "and a script branches on them -- which is why 2 is deliberately skipped: argparse uses it for "
    "usage errors, and a collision would make a mistyped command indistinguishable from a real "
    "failure. A blanket entry, because every numeric declaration in that module is a status code.",
    "ehdpsu.quantity.Dimension": "The four exponent defaults are all 0 -- the dimensionless "
    "identity of the dimension algebra. Not a design value; an identity element.",
    "ehdpsu.quantity.Band": "The lo/hi defaults are both 1.0 -- the exact band, which is the "
    "multiplicative identity. Not a design value.",
    "ehdpsu.quantity.describe.precision": "Significant figures for display formatting. A "
    "presentation choice, not a property of the apparatus.",
    "ehdpsu.quantity._RELATIVE_BAND_TOLERANCE": "Float slack in the never-tightened postcondition, "
    "so rounding inside the propagation cannot masquerade as a rule violation.",
    "ehdpsu.quantity._ABSOLUTE_UNCERTAINTY_TOLERANCE": "The same slack for the additive "
    "postcondition. Its value 1e-9 is numerically identical to the profile's C_stage_F, which the "
    "value scan flagged -- a genuine false positive: a comparison tolerance is not a capacitance. "
    "Registering it required naming it, which is an improvement on the inline literal it replaced.",
    "ehdpsu.telemetry.DEFAULT_BURST_THRESHOLD_FRAC": "An analysis threshold for segmenting a "
    "recorded burst, not a property of the hardware.",
}


@dataclass(frozen=True)
class ProfileValue:
    """One design value with its unit, basis and provenance."""

    value: float | int | None
    unit: str
    basis: Basis
    kind: FieldKind
    refs: tuple[str, ...] = ()
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        node: dict[str, Any] = {
            "value": self.value,
            "unit": self.unit,
            "basis": self.basis.label,
            "kind": self.kind,
        }
        if self.refs:
            node["refs"] = list(self.refs)
        if self.note:
            node["note"] = self.note
        return node


@dataclass
class Profile:
    """A validated spec-scope-profile.

    Values are reached through :meth:`value`, never by attribute, so a mistyped field name is an
    error at the read rather than an ``AttributeError`` inside a formula — and so every read goes
    through one place that can later hand back a ``Quantity`` instead of a float without changing
    a single call site.
    """

    profile_id: str
    title: str
    values: dict[str, ProfileValue]
    provenance: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    #: Migrations applied on load, oldest first. A profile that loads under a newer schema
    #: without saying what was reinterpreted is a silent reinterpretation of design intent.
    migrations_applied: tuple[str, ...] = ()

    def value(self, name: str) -> float | int | None:
        if name not in self.values:
            raise ProfileError(f"unknown design field {name!r}. Known: {sorted(self.values)}")
        return self.values[name].value

    def required(self, name: str) -> float:
        """Return a value that must not be null, as a float.

        A nullable field reaching a formula as ``None`` would become a ``TypeError`` several
        frames from the cause.
        """
        raw = self.value(name)
        if raw is None:
            raise ProfileError(
                f"{name!r} is null in profile {self.profile_id!r} but this caller requires a "
                f"value. Set it, or use the derivation its schema documents."
            )
        return float(raw)

    def count(self, name: str) -> int:
        """Return an integer-typed value, refusing a float that is not exactly integral."""
        spec = FIELDS_BY_NAME.get(name)
        if spec is None or spec.numeric_type is not int:
            raise ProfileError(f"{name!r} is not an integer-typed field")
        return int(self.required(name))

    def basis_of(self, name: str) -> Basis:
        if name not in self.values:
            raise ProfileError(f"unknown design field {name!r}")
        return self.values[name].basis

    def ceiling(self, names: list[str] | None = None) -> Basis:
        """Low-water-mark basis over ``names``, or the whole profile.

        The ceiling on anything derived from those inputs.
        *Principle 1, trust is a ceiling inherited from provenance.*
        """
        wanted = names if names is not None else sorted(self.values)
        return low_water_mark([self.basis_of(n) for n in wanted])

    def section(self, name: str) -> dict[str, ProfileValue]:
        if name not in SECTIONS:
            raise ProfileError(f"unknown section {name!r}. Known: {list(SECTIONS)}")
        return {spec.name: self.values[spec.name] for spec in FIELDS if spec.section == name}

    def to_json(self) -> dict[str, Any]:
        """Serialise, grouped and ordered by the schema rather than by dict insertion order."""
        design: dict[str, Any] = {
            section: {
                spec.name: self.values[spec.name].to_json()
                for spec in FIELDS
                if spec.section == section
            }
            for section in SECTIONS
        }
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "title": self.title,
            "provenance": self.provenance,
            "design": design,
        }

    def save(self, path: Path, overwrite: bool = False) -> Path:
        """Write the profile as JSON. Refuses to clobber unless ``overwrite`` is explicit."""
        path = Path(path)
        if path.exists() and not overwrite:
            raise ProfileError(f"{path} exists. Pass overwrite=True if replacing it is intended.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------
#
# Keyed by the version being migrated FROM. Empty at v1 because v1 is the first schema; the
# machinery exists so that the first real bump is not also the moment the mechanism is written.
# `tests/test_profile.py` exercises it with an injected synthetic migration, and says so -- a
# mechanism proven with a fake is honest, inventing a v0 that never existed would not be.
MIGRATIONS: dict[int, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {}


def migrate_raw(
    raw: dict[str, Any],
    migrations: dict[int, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Bring ``raw`` up to :data:`SCHEMA_VERSION`, returning it and the migrations applied."""
    table = MIGRATIONS if migrations is None else migrations
    version = raw.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProfileError(
            f"schema_version is {version!r}; it must be an integer. A profile without a usable "
            f"version cannot be migrated, and guessing one would reinterpret design intent."
        )
    if version > SCHEMA_VERSION:
        raise ProfileError(
            f"profile is at schema version {version} but this build understands at most "
            f"{SCHEMA_VERSION}. Refusing to read a newer schema: unknown fields would be "
            f"silently dropped."
        )

    applied: list[str] = []
    current = dict(raw)
    while version < SCHEMA_VERSION:
        if version not in table:
            raise ProfileError(
                f"no migration registered from schema version {version}. The profile cannot be "
                f"upgraded, and loading it as-is would misread it."
            )
        name, fn = table[version]
        current = fn(current)
        applied.append(name)
        version += 1
        current["schema_version"] = version
    return current, tuple(applied)


# ---------------------------------------------------------------------------
# Validation and loading
# ---------------------------------------------------------------------------


def _validate_value_node(name: str, node: Any) -> ProfileValue:
    spec = FIELDS_BY_NAME[name]
    if not isinstance(node, dict):
        raise ProfileError(
            f"{name}: expected an object with value/unit/basis/kind, got {type(node).__name__}"
        )

    unknown = set(node) - _ALLOWED_VALUE_KEYS
    if unknown:
        raise ProfileError(f"{name}: unknown keys {sorted(unknown)}")
    for required_key in ("value", "unit", "basis", "kind"):
        if required_key not in node:
            raise ProfileError(f"{name}: missing {required_key!r}")

    if node["unit"] != spec.unit:
        raise ProfileError(
            f"{name}: unit is {node['unit']!r} but the schema declares {spec.unit!r}. A "
            f"mis-united value is the failure mode this schema exists to prevent."
        )
    if node["kind"] != spec.kind:
        raise ProfileError(f"{name}: kind is {node['kind']!r}, schema declares {spec.kind!r}")

    try:
        basis = Basis.from_label(str(node["basis"]))
    except ValueError as exc:
        raise ProfileError(f"{name}: {exc}") from exc

    raw_value = node["value"]
    if raw_value is None:
        if not spec.nullable:
            raise ProfileError(
                f"{name}: null is not permitted. An absent required design value must be "
                f"supplied, not defaulted."
            )
        value: float | int | None = None
    elif isinstance(raw_value, bool):
        raise ProfileError(f"{name}: booleans are not design values")
    elif spec.numeric_type is int:
        if not isinstance(raw_value, int):
            raise ProfileError(
                f"{name}: expected an integer count, got {raw_value!r}. A fractional stage "
                f"count would propagate into the cascade polynomial."
            )
        value = raw_value
    elif isinstance(raw_value, (int, float)):
        if not math.isfinite(float(raw_value)):
            raise ProfileError(f"{name}: {raw_value!r} is not finite")
        value = float(raw_value)
    else:
        raise ProfileError(f"{name}: expected a number, got {type(raw_value).__name__}")

    refs = tuple(str(r) for r in node.get("refs", ()))
    note = node.get("note")
    return ProfileValue(
        value, spec.unit, basis, spec.kind, refs, None if note is None else str(note)
    )


def from_json(raw: dict[str, Any], *, migrate: bool = True) -> Profile:
    """Validate a raw mapping into a :class:`Profile`.

    Every failure raises :class:`ProfileError` naming the field. Nothing is defaulted: a profile
    missing a design value is an error, because a default here is a hidden design decision.
    """
    if not isinstance(raw, dict):
        raise ProfileError(f"a profile must be an object, got {type(raw).__name__}")

    applied: tuple[str, ...] = ()
    if migrate:
        raw, applied = migrate_raw(raw)
    elif raw.get("schema_version") != SCHEMA_VERSION:
        raise ProfileError(
            f"schema_version {raw.get('schema_version')!r} != {SCHEMA_VERSION} and migration "
            f"was disabled"
        )

    unknown_top = set(raw) - _ALLOWED_TOP_KEYS
    if unknown_top:
        raise ProfileError(f"unknown top-level keys {sorted(unknown_top)}")
    for key in ("profile_id", "title", "design"):
        if key not in raw:
            raise ProfileError(f"missing top-level {key!r}")

    design = raw["design"]
    if not isinstance(design, dict):
        raise ProfileError("'design' must be an object keyed by section")

    unknown_sections = set(design) - set(SECTIONS)
    if unknown_sections:
        raise ProfileError(f"unknown design sections {sorted(unknown_sections)}")
    missing_sections = set(SECTIONS) - set(design)
    if missing_sections:
        raise ProfileError(f"missing design sections {sorted(missing_sections)}")

    seen: dict[str, ProfileValue] = {}
    for section, entries in design.items():
        if not isinstance(entries, dict):
            raise ProfileError(f"section {section!r} must be an object")
        expected = {spec.name for spec in FIELDS if spec.section == section}
        unknown_fields = set(entries) - expected
        if unknown_fields:
            raise ProfileError(f"section {section!r}: unknown fields {sorted(unknown_fields)}")
        missing_fields = expected - set(entries)
        if missing_fields:
            raise ProfileError(f"section {section!r}: missing fields {sorted(missing_fields)}")
        for name, node in entries.items():
            seen[name] = _validate_value_node(name, node)

    provenance = raw.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ProfileError("'provenance' must be an object")

    return Profile(
        profile_id=str(raw["profile_id"]),
        title=str(raw["title"]),
        values=seen,
        provenance=provenance,
        schema_version=SCHEMA_VERSION,
        migrations_applied=applied,
    )


def load(path: Path) -> Profile:
    """Load and validate a profile from disk."""
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"no profile at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{path} is not valid JSON: {exc}") from exc
    return from_json(raw)


def load_named(profile_id: str, profile_dir: Path = DEFAULT_PROFILE_DIR) -> Profile:
    """Load ``<profile_dir>/<profile_id>.json``."""
    return load(Path(profile_dir) / f"{profile_id}.json")


def available_profiles(profile_dir: Path = DEFAULT_PROFILE_DIR) -> list[str]:
    """Return the profile ids present in ``profile_dir``, sorted."""
    directory = Path(profile_dir)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def default_profile() -> Profile:
    """Load the profile named by :data:`DEFAULT_PROFILE_ID` from the operator's profile directory.

    **This raises on a fresh clone, and that is correct.** ``profiles/`` is ignored and ships
    empty, because there is no set design point — the MK0 22 kV figures were a planning baseline
    and will change with the design and the size. A clone therefore has no design, and inventing
    one would be worse than saying so: it would look authoritative and would be a second home for
    a design point.

    The regression suite does **not** come through here. It loads
    ``tests/data/mk0_benchtop_22kv.json`` explicitly, so pointing this at a new design cannot
    turn the physics pins red.

    Deliberately **not cached**: :class:`Profile` is mutable, so a shared instance would let one
    consumer's edit reach another's read.
    """
    try:
        return load_named(DEFAULT_PROFILE_ID)
    except ProfileError as exc:
        present = available_profiles()
        found = ", ".join(present) if present else "none"
        raise ProfileError(
            f"{exc}\n"
            f"  DEFAULT_PROFILE_ID is {DEFAULT_PROFILE_ID!r}; profiles present: {found}.\n"
            f"  {DEFAULT_PROFILE_DIR} ships empty on purpose: there is no set design point, so no "
            f"reference design is committed.\n"
            f"  Author a profile there (see profiles/README.md), or pass one explicitly instead of "
            f"relying on the default."
        ) from exc


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldDiff:
    """One field's disagreement between two profiles."""

    name: str
    left: float | int | None
    right: float | int | None
    left_basis: Basis
    right_basis: Basis

    @property
    def ratio(self) -> float | None:
        """``right / left`` where both are non-zero numbers, else ``None``.

        Reported rather than interpreted: a factor of 10 between two profiles is a finding for
        whoever owns the physics, not something this module resolves.
        """
        if not isinstance(self.left, (int, float)) or not isinstance(self.right, (int, float)):
            return None
        if float(self.left) == 0.0:
            return None
        return float(self.right) / float(self.left)


def diff(left: Profile, right: Profile) -> list[FieldDiff]:
    """Return every field whose value or basis differs, in schema order.

    Both profiles are validated by construction, so the field sets are identical and a diff is
    always field-by-field rather than structural.
    """
    out: list[FieldDiff] = []
    for spec in FIELDS:
        lv, rv = left.values[spec.name], right.values[spec.name]
        if lv.value != rv.value or lv.basis != rv.basis:
            out.append(FieldDiff(spec.name, lv.value, rv.value, lv.basis, rv.basis))
    return out


def main() -> None:
    """Validate the tracked profiles and report each one's inherited ceiling."""
    profile_dir = DEFAULT_PROFILE_DIR
    paths = sorted(profile_dir.glob("*.json")) if profile_dir.is_dir() else []
    if not paths:
        print(f"no profiles in {profile_dir}/ -- which is how it ships.")
        print("There is no set design point, so no reference design is committed.")
        print("Start one by copying the regression fixture:")
        print("  Copy-Item tests\\data\\mk0_benchtop_22kv.json profiles\\my_design.json")
        print("See profiles/README.md.")
        return

    print("=== spec-scope-profiles ===")
    for path in paths:
        prof = load(path)
        ceiling = prof.ceiling()
        print(f"\n  {path.name}")
        print(f"    id      : {prof.profile_id}")
        print(f"    title   : {prof.title}")
        print(f"    schema  : v{prof.schema_version}")
        print(f"    fields  : {len(prof.values)} across {len(SECTIONS)} sections")
        print(f"    ceiling : {ceiling.label}  <- bounds every quantity derived from this profile")
    print(
        "\nA ceiling of 'claimed' is expected and correct: the design values are operator "
        "choices\nand literature figures that nothing has yet measured on the built article."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
