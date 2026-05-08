"""Prefetch script for manual_writer.

Reads the workspace's ``manual/`` directory and emits a TOC summary
of features already documented so the agent can:

- cross-reference via ``see_also``
- use consistent terminology with prior sections
- avoid duplicating coverage of features already covered

Wired into the agent persona via ``{{!py:scripts/prefetch_manual_writer_toc.py}}``
in ``.jaato/agents/manual_writer.md`` — runs at session-creation time and
becomes part of the system instructions.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List


def render(context: Any, args: List[str]) -> str:
    workspace = Path(context.workspace_path) if context.workspace_path else Path.cwd()
    manual_dir = workspace / "manual"
    if not manual_dir.is_dir():
        return (
            "## Manual TOC (so far)\n\n"
            "No `manual/` directory yet — this is the first feature being "
            "documented.  `see_also` should be an empty list."
        )

    rows: List[str] = []
    for md in sorted(manual_dir.glob("20-walkthrough-*.md")):
        text = md.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else md.stem
        feature_match = re.search(r"<!--\s*jaato:feature\s+(\S+)\s*-->", text)
        fid = (
            feature_match.group(1)
            if feature_match
            else md.stem.replace("20-walkthrough-", "")
        )
        rows.append(f"- `{fid}` — {title}")

    if not rows:
        return (
            "## Manual TOC (so far)\n\n"
            "No walkthroughs documented yet — this is the first feature.  "
            "`see_also` should be an empty list."
        )

    return (
        "## Manual TOC (so far)\n\n"
        "Walkthrough sections already documented (use the IDs in `see_also` "
        "to cross-reference):\n\n"
        + "\n".join(rows)
    )
