"""Machine-local tool locations: the thing that populates detection route 1.

Why this module had to exist
----------------------------
``configured-path`` is the first route in ``detect.ROUTE_ORDER`` and, until this file, **nothing in
the suite could supply it.** ``detect_tool`` accepted the argument, the adapters called ``detect()``
with no argument, and the CLI offered no way to pass one. So the route existed, was recorded as
attempted on every probe, and could never resolve anything.

That gap was found by installing the tools. On 2026-09-16 the operator installed LTspice to
``B:\\LTspice`` and QSPICE to ``B:\\QSPICE``. Both were working, and ``ehdsuite doctor`` reported both
``tool-absent`` — *correctly*, by the contract's own definition: all four routes were attempted, the
registry PATH scopes were read successfully (34 entries, neither tool among them), and none resolved.
The status logic was right and the outcome was the exact failure the detection layer exists to
prevent, which is a working tool reported absent. *Principle 2, an approximately-correct identifier is
worse than an absent one* — and ``TOOL_ABSENT`` is a positive claim about the world, so being wrong
about it is worse than the inconclusive answer.

Why a file rather than the profile, or an environment variable
--------------------------------------------------------------
**Not the profile.** A profile is a portable description of a *design*, and an install path is a fact
about *this machine*. Putting one in the other would make a profile non-portable and would break the
rule that the profile is the seam for design values — an install path is not a design value and never
becomes one.

**Not an environment variable.** The stale-environment hazard is the origin story of this whole
module: Kiro CLI 2.21.4 was installed and working while ``Get-Command`` found nothing, because a shell
had inherited its environment before the installer wrote it. An env var carrying a tool path inherits
exactly that failure mode, and it is invisible when wrong. A file on disk can be read, reviewed and
diffed.

**One mechanism, not two.** Supporting both a file and an env var would be two representations of one
fact — *principle 4, two representations of one thing will drift* — with a precedence rule nobody
remembers.

The file is untracked
---------------------
``tools.local.json`` names absolute paths on one operator's machine. It is gitignored, a test asserts
that it is, and it must never reach a public remote: it is configuration, not repository content, and
it would be wrong in every clone.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..detect import KNOWN_TOOLS

TOOL_CONFIG_FILENAME = "tools.local.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]

_TEMPLATE = """{
  "_comment": "Machine-local tool locations. Untracked: these paths are true only here.",
  "tools": {
    "ltspice": "B:\\\\LTspice\\\\LTspice.exe"
  }
}"""


class ToolConfigError(ValueError):
    """The tool configuration file exists and is unusable.

    A malformed config **raises** rather than being skipped. Ignoring it would make a typo
    indistinguishable from no configuration at all, and the operator would see ``tool-absent`` for a
    tool they had just told the suite where to find.
    """


def tool_config_path(root: Path | None = None) -> Path:
    """Where the config lives. Repository root by default."""
    return (root or _REPO_ROOT) / TOOL_CONFIG_FILENAME


def config_template() -> str:
    """A minimal valid file, for an operator who has none.

    Deliberately shows **one** tool rather than all seven. A template listing every tool invites
    filling every line in, and a wrong path is worse than an absent one.
    """
    return _TEMPLATE


def load_tool_paths(root: Path | None = None) -> dict[str, Path]:
    """Read the configured tool paths, or return an empty mapping.

    An **absent** file is the normal case and returns ``{}`` — most machines will have the tools where
    the vendor put them, and requiring a config file to detect a default install would be a worse
    default than none. Every other malformation raises.

    Raises:
        ToolConfigError: the file exists and is not valid, names an unknown tool, or gives a path that
            is not absolute.
    """
    path = tool_config_path(root)
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolConfigError(f"{path.name} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ToolConfigError(f"{path.name} must hold a JSON object, not {type(raw).__name__}")

    tools = raw.get("tools")
    if tools is None:
        raise ToolConfigError(
            f"{path.name} has no 'tools' object. An empty config is written as "
            f'{{"tools": {{}}}}, so that "configured nothing" is explicit rather than implied by '
            f"a missing key."
        )
    if not isinstance(tools, dict):
        raise ToolConfigError(f"{path.name}: 'tools' must be an object mapping name to path")

    known = {spec.name for spec in KNOWN_TOOLS}
    resolved: dict[str, Path] = {}
    for name, value in tools.items():
        if name not in known:
            raise ToolConfigError(
                f"{path.name} configures unknown tool {name!r}. Known: {sorted(known)}. A mistyped "
                f"name would otherwise be silently unconfigured, which looks identical to a tool "
                f"that is not installed."
            )
        if not isinstance(value, str) or not value.strip():
            raise ToolConfigError(f"{path.name}: {name} must be a non-empty path string")
        candidate = Path(value.strip())
        if not candidate.is_absolute():
            raise ToolConfigError(
                f"{path.name}: {name} is {value!r}, which is not absolute. A relative path resolves "
                f"against the working directory, so the same config would find the tool from one "
                f"directory and not from another."
            )
        resolved[name] = candidate

    return resolved


def configured_path_for(name: str, root: Path | None = None) -> Path | None:
    """The configured path for one tool, or ``None`` if it is not configured.

    Does **not** check that the path exists. Whether it resolves is ``detect_tool``'s business, and it
    reports a configured path that failed rather than treating it as absent configuration — a stale
    entry pointing at a moved install has to be visible.
    """
    return load_tool_paths(root).get(name)
