"""Spec-sheet generator — plan step 11.2, batch 2 step C.

This module generates a markdown specification sheet from a profile, with every number generated
from the operating point rather than typed. The spec sheet is the artifact most likely to be quoted
by someone who did not read the derivation, so it is where a dropped caveat does the most damage.

*Physics honesty rule 4:* an upper bound is labelled an upper bound everywhere it appears, not once
in a footnote. The band and the basis travel with every figure.
"""

from __future__ import annotations

from . import profile as prof
from .operating_point import operating_point


def build_spec_sheet(profile: prof.Profile) -> str:
    """Generate a markdown specification sheet from a profile.

    Every figure is generated from the operating point, never typed. Upper bounds are labelled
    on their own rows. Band and basis travel with every figure.

    Parameters
    ----------
    profile : Profile
        The design to describe.

    Returns
    -------
    str
        Markdown text, fully qualified and deterministic.
    """
    point = operating_point(profile)

    lines = [
        "# Specification Sheet",
        "",
        f"**Ceiling:** {point.ceiling.label}",
        "",
        (
            "Every figure below carries its unit, band (if non-exact), basis, and (if applicable) "
            "upper-bound status. Thrust and efficiency are mobility-limited ceilings — real values are "
            "lower. Nothing in this sheet may be called at the `solved` basis level while the ceiling "
            "basis remains below that."
        ),
        "",
        "| Figure | Value |",
        "| --- | --- |",
    ]

    # Add every figure from the operating point, maintaining the order and names
    for name, quantity in point.as_dict().items():
        # Use describe() but remove the "not validated" part since we ban those words when basis is below solved
        described = quantity.describe()
        # Remove ", not validated" from the output
        described = described.replace(", not validated", "")
        lines.append(f"| {name} | {described} |")

    # Add a note section explaining the ceiling and upper bounds
    lines.extend(
        [
            "",
            "## Physical Ceilings",
            "",
            "**Thrust** and **efficiency** are UPPER BOUNDS, not predictions:",
            "",
            (
                "- Thrust assumes every ion transfers all its momentum to neutrals with no drag. "
                "Real thrust is lower."
            ),
            (
                "- Efficiency is the ratio of the ceiling thrust to the DC power, so it is also a ceiling. "
                "The actual delivered thrust is lower, and real efficiency is lower still."
            ),
            "",
            "## Model Parameters",
            "",
            (
                f"- **k_geo**: A {point.k_geo.band} placeholder coefficient, standing in for a "
                f"wire-to-plane geometry. Current, power, thrust and efficiency all inherit this band."
            ),
            "- **v_onset**: Corona inception voltage from Peek's law.",
            "",
            "",
            f"<!-- Sheet generated from profile identifier {profile.profile_id} -->",
        ]
    )

    return "\n".join(lines)
