"""``ehdsuite`` — the command surface for spec-scope-profiles.

Run as ``python -m ehdpsu <command>`` (always available) or ``ehdsuite <command>`` (after an
editable install regenerates the console script).

Why this exists before the GUI
------------------------------
Chief Operator, 2026-09-15, standing requirement recorded in ``.kiro/steering/ehd-charter.md``: any
new architecture belongs at the **CLI level and below**, never in the GUI. *"The GUI should wrap a
well thought architecture and not end up being architecture itself."*

So this module defines the vocabulary — ``schema``, ``list``, ``validate``, ``diff``, ``new``,
``report`` — and the GUI and the agent-authoring seats (FR-001 and FR-004) call the same operations.
A capability that exists only behind a button has no test, no scriptable form, and no way to
reproduce what it did.

Two design choices worth stating
--------------------------------
**``new`` requires an explicit ``--from``.** There is no set design point, so this command cannot
invent one. Emitting a skeleton with placeholder values would put numbers nobody chose into a file
that looks authoritative — and ``profile.from_json`` refuses to default anything for exactly that
reason. A new profile is a copy of a design somebody already stands behind.

**Validating zero profiles is not success.** ``profiles/`` ships empty, so "validated 0 profiles,
all fine" is *principle 3, never report success over unperformed work*, in command form. It gets its
own exit code and says what to do.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import adapters
from . import profile as prof
from .basis import may_be_called_validated
from .claims import CLAIM_SETS
from .crossvalidate import (
    ClaimVerdict,
    adjudicate_claim_set,
    compare_efficiency_routes,
)
from .operating_point import operating_point

# Exit codes. 0 and 1 carry their usual meanings and 2 is reserved: argparse exits 2 on a usage
# error, so a status of ours must never collide with it.
EXIT_OK = 0
EXIT_INVALID_PROFILE = 3
EXIT_NOTHING_VALIDATED = 4
EXIT_NOT_FOUND = 5
EXIT_REFUSED_OVERWRITE = 6
# A claim that contradicts figures derived from its own source. Distinct from EXIT_INVALID_PROFILE
# because nothing is malformed: the data is well-formed and the physics does not support it.
EXIT_CLAIM_INCONSISTENT = 7
# An adapter raised while probing. Distinct from every code above because it reports a defect in the
# suite, not a fact about the machine: an absent solver is the normal state here and exits 0.
EXIT_ADAPTER_BROKEN = 8


def _resolve(target: str, profile_dir: Path) -> Path:
    """Resolve a profile id or a path to a file, without guessing.

    An id is looked up only in ``profile_dir``. It deliberately does not fall back to the test
    fixture: reaching into ``tests/`` from a user command would make a regression fixture behave
    like a design, which is the confusion the fixture was moved there to end.
    """
    as_path = Path(target)
    if as_path.suffix == ".json" and as_path.is_file():
        return as_path
    candidate = profile_dir / f"{target}.json"
    if candidate.is_file():
        return candidate
    available = prof.available_profiles(profile_dir)
    found = ", ".join(available) if available else "none"
    raise FileNotFoundError(
        f"no profile {target!r}: not a .json path, and not in {profile_dir}/ (present: {found})"
    )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_schema(args: argparse.Namespace) -> int:
    """Print the field schema — the machine-readable surface an editor or writer seat renders from.

    FR-001 decided the GUI renders from ``profile.FIELDS`` rather than a hand-maintained form, and
    FR-004's writer seat needs the same description. This is that description, so neither has to
    duplicate it.
    """
    fields = [
        {
            "name": spec.name,
            "section": spec.section,
            "unit": spec.unit,
            "kind": spec.kind,
            "type": spec.numeric_type.__name__,
            "nullable": spec.nullable,
            "doc": spec.doc,
        }
        for spec in prof.FIELDS
    ]
    if args.json:
        print(json.dumps({"schema_version": prof.SCHEMA_VERSION, "fields": fields}, indent=2))
        return EXIT_OK

    print(f"spec-scope-profile schema v{prof.SCHEMA_VERSION} — {len(fields)} fields")
    for section in prof.SECTIONS:
        print(f"\n  [{section}]")
        for field in (f for f in fields if f["section"] == section):
            nullable = "  (nullable)" if field["nullable"] else ""
            print(f"    {field['name']:26s} {field['unit']:14s} {field['kind']}{nullable}")
            print(f"      {field['doc']}")
    print(
        "\nEvery field also carries `basis` and optional `refs`/`note`. Nothing is defaulted: a "
        "missing\nvalue is an error, because a default in a loader is a hidden design decision."
    )
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """List the profiles present, with the trust ceiling each one imposes."""
    ids = prof.available_profiles(args.profile_dir)
    if not ids:
        print(f"no profiles in {args.profile_dir}/ — which is how it ships.")
        print("There is no set design point, so no reference design is committed.")
        print("Start one with:  python -m ehdpsu new <id> --from tests/data/mk0_benchtop_22kv.json")
        return EXIT_OK

    print(f"{len(ids)} profile(s) in {args.profile_dir}/")
    for profile_id in ids:
        try:
            loaded = prof.load_named(profile_id, args.profile_dir)
        except prof.ProfileError as exc:
            # Reported per profile rather than aborting the listing: one malformed file must not
            # hide the others.
            print(f"  {profile_id:28s} INVALID — {exc}")
            continue
        print(f"  {profile_id:28s} ceiling {loaded.ceiling().label:24s} {loaded.title}")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate profiles, naming the field and the reason on any failure."""
    if args.targets:
        try:
            paths = [_resolve(t, args.profile_dir) for t in args.targets]
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_NOT_FOUND
    else:
        paths = [
            args.profile_dir / f"{profile_id}.json"
            for profile_id in prof.available_profiles(args.profile_dir)
        ]

    if not paths:
        # A check that examined nothing is not a passing check.
        print(
            f"NOTHING VALIDATED: no profiles in {args.profile_dir}/ and none named.\n"
            f"  This is not success. `profiles/` ships empty because there is no set design "
            f"point;\n  author one, or name a path explicitly.",
            file=sys.stderr,
        )
        return EXIT_NOTHING_VALIDATED

    failures = 0
    for path in paths:
        try:
            loaded = prof.load(path)
        except prof.ProfileError as exc:
            failures += 1
            print(f"INVALID  {path}\n         {exc}", file=sys.stderr)
            continue
        migrated = (
            f" (migrated: {', '.join(loaded.migrations_applied)})"
            if loaded.migrations_applied
            else ""
        )
        validated = (
            "may be called validated"
            if may_be_called_validated(loaded.ceiling())
            else "NOT validated"
        )
        print(
            f"OK       {path.name}  {len(loaded.values)} fields, "
            f"ceiling {loaded.ceiling().label}, {validated}{migrated}"
        )

    print(f"\n{len(paths) - failures}/{len(paths)} profile(s) valid")
    return EXIT_INVALID_PROFILE if failures else EXIT_OK


def cmd_diff(args: argparse.Namespace) -> int:
    """Report every field where two profiles disagree. Reports; never reconciles."""
    try:
        left_path = _resolve(args.left, args.profile_dir)
        right_path = _resolve(args.right, args.profile_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        left, right = prof.load(left_path), prof.load(right_path)
    except prof.ProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID_PROFILE

    changes = prof.diff(left, right)
    print(f"{left.profile_id}  ->  {right.profile_id}")
    if not changes:
        print("  identical in every field and basis")
        return EXIT_OK

    for change in changes:
        ratio = "" if change.ratio is None else f"  (x{change.ratio:.4g})"
        basis = (
            ""
            if change.left_basis == change.right_basis
            else f"  basis {change.left_basis.label} -> {change.right_basis.label}"
        )
        print(f"  {change.name:26s} {change.left!r:>16} -> {change.right!r:<16}{ratio}{basis}")

    print(
        f"\n{len(changes)} field(s) differ. A ratio is reported, not interpreted: whether a change "
        f"is\nan improvement is a physics question, not a diff question."
    )
    return EXIT_OK


def cmd_new(args: argparse.Namespace) -> int:
    """Create a profile by copying one that already exists.

    ``--from`` is required. See the module docstring: this command cannot invent a design point, and
    a skeleton of placeholder values would look authoritative while containing numbers nobody chose.
    """
    try:
        source = _resolve(args.source, args.profile_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        loaded = prof.load(source)
    except prof.ProfileError as exc:
        # Refuses to copy something invalid, rather than propagating it under a new name.
        print(f"ERROR: source profile is invalid, refusing to copy it:\n  {exc}", file=sys.stderr)
        return EXIT_INVALID_PROFILE

    target = args.profile_dir / f"{args.profile_id}.json"
    if target.exists() and not args.overwrite:
        print(
            f"ERROR: {target} exists. Pass --overwrite if replacing it is intended.",
            file=sys.stderr,
        )
        return EXIT_REFUSED_OVERWRITE

    # Captured before the id is overwritten, so the provenance names the source rather than the
    # copy. Reloading the file to recover it would be a second read of something already in hand.
    source_id = loaded.profile_id

    # `profile_id` inside the file is set to match the filename stem, because `load_named` resolves
    # by stem and a mismatch would make the file disagree with its own identity.
    loaded.profile_id = args.profile_id
    loaded.provenance = {
        **loaded.provenance,
        "derived_from": f"{source.name} (profile_id {source_id})",
        "derived_note": (
            "Created with `ehdsuite new`. Every value is inherited from the source and every basis "
            "is whatever the source claimed. Review them: a copied basis is not evidence about "
            "this design."
        ),
    }
    written = loaded.save(target, overwrite=args.overwrite)

    print(f"wrote {written}")
    print(f"  copied from : {source}")
    print(f"  fields      : {len(loaded.values)}")
    print(f"  ceiling     : {loaded.ceiling().label}")
    print(
        "\nThe values and their bases are inherited. Edit them, then re-validate:\n"
        f"  python -m ehdpsu validate {args.profile_id}"
    )
    return EXIT_OK


def cmd_crosscheck(args: argparse.Namespace) -> int:
    """Report route disagreements and adjudicate recorded claims.

    Exits non-zero when a claim is inconsistent with figures derived from the source's own numbers,
    so a script or a gate can branch on it. A route disagreement does **not** set a failing status:
    two routes differing is information for a human, not a build break.
    """
    findings = 0

    if args.target:
        try:
            path = _resolve(args.target, args.profile_dir)
            loaded = prof.load(path)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_NOT_FOUND
        except prof.ProfileError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_INVALID_PROFILE

        print(f"=== route agreement: {loaded.profile_id} ===")
        for line in compare_efficiency_routes(loaded).report_lines():
            print(f"  {line}")
        print()

    print("=== recorded claims, adjudicated against their own figures ===")
    for claim_id, claim_set in CLAIM_SETS.items():
        print(f"\n  {claim_id}")
        print(f"    source: {claim_set.source}")
        print(f"    {claim_set.description}")
        for adjudication in adjudicate_claim_set(claim_set):
            print()
            for line in adjudication.report_lines():
                print(f"    {line}")
            if adjudication.verdict is not ClaimVerdict.CONSISTENT:
                findings += 1

    print(
        "\nNothing here is reconciled. A ratio is reported and no route or figure is preferred:\n"
        "choosing between them is a physics decision for the operator and the relevant Oracle."
    )
    if findings:
        print(f"\n{findings} claim(s) inconsistent with their own source figures.", file=sys.stderr)
        return EXIT_CLAIM_INCONSISTENT
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    """Print the derived operating point with every qualification attached."""
    try:
        path = _resolve(args.target, args.profile_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        loaded = prof.load(path)
    except prof.ProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID_PROFILE

    point = operating_point(loaded)
    print(f"{loaded.profile_id} — {loaded.title}")
    print(f"  input ceiling : {loaded.ceiling().label}")
    print()
    for line in point.report_lines():
        print(f"  {line}")
    print(
        "\nEvery figure carries its band, its basis and its bound status. Thrust and efficiency are"
        "\nUPPER BOUNDS: T = I*d/mu assumes full ion-to-neutral momentum transfer with no drag, so"
        "\nreal thrust is lower. Nothing here may be called validated while its basis is below "
        "`solved`."
    )
    return EXIT_OK


def cmd_specsheet(args: argparse.Namespace) -> int:
    """Generate and print a markdown specification sheet from a profile.

    Every figure is generated from the operating point, never typed. Upper bounds are labelled
    on their own rows. Band and basis travel with every figure.
    """
    from . import specsheet

    target = args.target
    try:
        path = _resolve(target, args.profile_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        loaded = prof.load(path)
    except prof.ProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID_PROFILE

    sheet = specsheet.build_spec_sheet(loaded)
    print(sheet)
    return EXIT_OK


def cmd_runrecord(args: argparse.Namespace) -> int:
    """Emit a result-file skeleton for a named tool — FR-007, batch 2 step B.

    Three result-file skeletons were produced by hand on 2026-09-16 so the first FEMM run could
    start immediately. That worked once and does not scale: every regeneration of a solver input
    needs a new skeleton, and the field that must be regenerated is a 64-character SHA-256.

    Asking an operator to hand-copy a digest is inviting the exact transcription error that
    ``record_from_parsed`` then rejects. The rejection is safe — a wrong hash cannot become a run
    record — but the whole round trip is avoidable, and the operator is at a bench with a solver open.

    The trap this command has to avoid: it must never emit a skeleton carrying a hash of something
    other than the input the operator will actually feed the tool. A skeleton with a plausible-looking
    but wrong digest is worse than no skeleton: the operator fills it in, the record is refused, and
    the refusal names the hash rather than the cause. *Principle 2, an approximately-correct identifier
    is worse than an absent one.*
    """
    tool_name = args.tool

    try:
        adapter = adapters.adapter_for(tool_name)
    except KeyError:
        registered = ", ".join(a.name for a in adapters.ADAPTERS)
        print(f"error: no adapter named {tool_name!r}", file=sys.stderr)
        print(f"registered adapters: {registered}", file=sys.stderr)
        return EXIT_NOT_FOUND

    # Generate the input artifact(s) in a temporary directory
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        try:
            generated = adapter.generate(tmp_path)
        except adapters.GenerateError as e:
            print(f"error: {tool_name} adapter.generate() failed: {e}", file=sys.stderr)
            return EXIT_INVALID_PROFILE

        # Compute the hash of the generated input(s). For adapters with a single input, use that.
        # The tests check that the hash matches what the operator will actually feed to the tool.
        if not generated:
            print(f"error: {tool_name} adapter.generate() produced no output", file=sys.stderr)
            return EXIT_INVALID_PROFILE

        input_hash = adapters.sha256_of_file(generated[0])
        input_path = generated[0]

    # Emit the skeleton
    lines = [
        adapters.RESULT_FILE_MAGIC,
        "tool_version = (no run has occurred on this machine; captured from tool when one does)",
        f"input_sha256 = {input_hash}",
    ]

    for value_name in adapter.expected_values:
        lines.append(f"{value_name} = ")

    # Add a comment showing the filename after a blank line for reference
    output = "\n".join(lines)
    output += f"\n\n# The input above was hashed from: {input_path.name}"

    print(output)
    return EXIT_OK


def cmd_runs(args: argparse.Namespace) -> int:
    """Validate a solver-run tier and report findings.

    The tier lives in ``artifacts/05_Solver_Runs/`` and holds run records, pending markers and
    incomplete-run notes. This command scans it and reports three classes of defects:

    - **orphaned-pending**: A PENDING skeleton beside a completed RECORD for the same tool and
      input.
    - **undeclared-prefix**: A file using a naming prefix not in TIER_FILE_PREFIXES.
    - **incomplete-record**: A RECORD_*.json missing tool_version, input_sha256, or values.

    An empty tier reports no findings.
    """
    tier_path = Path(args.tier)

    if not tier_path.is_dir():
        print(f"error: {tier_path} is not a directory", file=sys.stderr)
        return EXIT_NOT_FOUND

    from .adapters.provenance import validate_tier

    findings = validate_tier(tier_path)

    if not findings:
        print(f"✓ {tier_path.name}/: tier is clean")
        return EXIT_OK

    print(f"findings in {tier_path}:")
    for finding in findings:
        print(f"  {finding.kind:20s}  {finding.detail}")

    return 1  # Non-zero on findings


def cmd_doctor(args: argparse.Namespace) -> int:
    """Print the tool matrix: what the suite can drive, and what it cannot.

    Absence is the expected answer today and is reported per tool rather than summarised away. A
    capability whose tool is absent reports as **absent**, not as degraded-but-fine, because the
    alternative — quietly falling back to a closed-form estimate — is how a placeholder becomes a
    result.

    Exit status is ``EXIT_OK`` when the matrix printed, including when nothing resolved. An absent
    solver is the normal state of this repository, not a command failure. ``EXIT_ADAPTER_BROKEN`` is
    reserved for an adapter that raised while probing, which is a defect in the suite rather than a
    fact about the machine.
    """
    rows = adapters.doctor_rows()
    broken = [r for r in rows if r.status == "adapter-error"]

    print("Tool matrix — registered adapters and what each can currently do.\n")
    for row in rows:
        print(f"  {row.tool}")
        print(f"    status     : {row.status}")
        print(f"    run mode   : {row.run_mode}")
        if row.path:
            print(f"    path       : {row.path}")
        print(f"    version    : {row.version or '(not captured)'}")
        if row.routes_tried:
            print(f"    routes     : {', '.join(row.routes_tried)}")
        print(f"    capability : {row.capability}")
        if row.note:
            print(f"    note       : {row.note}")
        print()

    # Derived from the rows already probed, never by probing again: a re-probe would step outside
    # doctor_rows()'s containment and let a raising adapter crash the summary that reports it.
    unresolved = adapters.unresolved_capabilities(rows)
    if unresolved:
        print(
            f"{len(unresolved)} of {len(rows)} registered tool(s) did not resolve: "
            f"{', '.join(unresolved)}."
        )
        print(
            "Those capabilities are ABSENT. Nothing substitutes for them: the closed-form figures\n"
            "elsewhere in this suite are not stand-ins for a solve, and no result may be called\n"
            "`solved` without a run record carrying tool version, input hash and values read back."
        )
        # Said here because the alternative is an operator concluding their working install is
        # undetectable. A tool installed outside its vendor's default directory resolves through no
        # other route: the process PATH and the registry PATH scopes will not know about it either.
        config = adapters.tool_config_path()
        print(
            f"\nIf a tool above IS installed, its location is not on the process PATH, not in "
            f"either\nregistry Path scope, and not in a known default directory. Tell the suite "
            f"where it is:\n\n  {config}\n\n"
            f"holding, for example:\n\n"
            + "\n".join(f"  {line}" for line in adapters.config_template().splitlines())
            + "\n\nThat file is untracked by design — the paths in it are true only on this "
            "machine.\nA configured path that stops resolving is reported in the note rather than "
            "ignored,\nso a moved install cannot silently become a fresh absence."
        )
    else:
        print(f"All {len(rows)} registered tool(s) resolved.")

    print(
        "\nDetection covers seven tools; four of them (gmsh, elmer, openfoam, paraview) have no\n"
        "adapter yet, so they are absent from this matrix rather than shown as untested."
    )

    if broken:
        names = ", ".join(r.tool for r in broken)
        print(f"\nERROR: adapter(s) raised while probing: {names}", file=sys.stderr)
        return EXIT_ADAPTER_BROKEN
    return EXIT_OK


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ehdsuite",
        description="Author, inspect and validate EHD spec-scope-profiles.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=prof.DEFAULT_PROFILE_DIR,
        help="where working profiles live (default: the package's profiles/ directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema = subparsers.add_parser("schema", help="print the field schema")
    schema.add_argument("--json", action="store_true", help="machine-readable output")
    schema.set_defaults(func=cmd_schema)

    listing = subparsers.add_parser("list", help="list available profiles and their ceilings")
    listing.set_defaults(func=cmd_list)

    validate = subparsers.add_parser("validate", help="validate profiles")
    validate.add_argument("targets", nargs="*", help="profile ids or paths (default: all)")
    validate.set_defaults(func=cmd_validate)

    diff = subparsers.add_parser("diff", help="report field differences between two profiles")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.set_defaults(func=cmd_diff)

    new = subparsers.add_parser("new", help="create a profile by copying an existing one")
    new.add_argument("profile_id", help="id for the new profile; becomes the filename stem")
    new.add_argument(
        "--from",
        dest="source",
        required=True,
        help="source profile id or path. Required: there is no set design point to default to",
    )
    new.add_argument("--overwrite", action="store_true", help="replace an existing profile")
    new.set_defaults(func=cmd_new)

    report = subparsers.add_parser("report", help="derived operating point, fully qualified")
    report.add_argument("target", help="profile id or path")
    report.set_defaults(func=cmd_report)

    crosscheck = subparsers.add_parser(
        "crosscheck",
        help="compare independent routes and adjudicate recorded claims",
    )
    crosscheck.add_argument(
        "target",
        nargs="?",
        help="profile id or path for the route comparison; claims are adjudicated either way",
    )
    crosscheck.set_defaults(func=cmd_crosscheck)

    doctor = subparsers.add_parser(
        "doctor",
        help="print the external-tool matrix: what the suite can drive, and what it cannot",
    )
    doctor.set_defaults(func=cmd_doctor)

    runs = subparsers.add_parser(
        "runs",
        help="validate a solver-run tier",
    )
    runs.add_argument("--tier", required=True, help="path to the solver-run tier")
    runs.set_defaults(func=cmd_runs)

    runrecord = subparsers.add_parser(
        "runrecord",
        help="emit a result-file skeleton for a named tool",
    )
    runrecord.add_argument("tool", help="tool name (registered adapter)")
    runrecord.set_defaults(func=cmd_runrecord)

    specsheet = subparsers.add_parser(
        "specsheet",
        help="generate a markdown specification sheet from a profile",
    )
    specsheet.add_argument("target", help="profile id or path")
    specsheet.set_defaults(func=cmd_specsheet)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code; never raises for an expected failure."""
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
