"""``python -m ehdpsu`` — always-available entry point for the CLI.

Kept separate from the ``ehdsuite`` console script declared in ``pyproject.toml``: that script only
exists after an editable install regenerates it, so a fresh clone or a mid-bootstrap environment
would have no command at all. ``python -m ehdpsu`` works as soon as the package is importable, which
makes it the form the documentation uses.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
