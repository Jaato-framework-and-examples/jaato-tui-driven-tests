"""Prefetch script — inform the agent about an existing manual section.

When a prior run wrote ``manual/20-walkthrough-<feature_id>.md``, this
prefetch tells the agent **the path** of that file.  It deliberately
does NOT inline the file's contents — the agent's `readFile` tool can
fetch them, and reading first lets the agent identify the markdown
anchors it will target with `updateFile`.

Wired via ``{{!py:scripts/prefetch_manual_writer_prior.py}}`` in
``.jaato/agents/manual_writer.md``.  Reads
``context.agent_params['feature_id']`` to know which file to mention.
Cold-start (file absent) emits a clear "no prior version, generate
from scratch via writeNewFile" note.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List


def render(context: Any, args: List[str]) -> str:
    workspace = Path(context.workspace_path) if context.workspace_path else Path.cwd()
    params = context.agent_params or {}
    feature_id = params.get("feature_id")

    if not feature_id:
        return (
            "## Prior version (this feature)\n\n"
            "[prefetch error: agent_params is missing `feature_id` — the "
            "walker must forward it.  Treat this as a cold-start.]"
        )

    # Path the agent should read.  Reported as a workspace-relative
    # string because that's what readFile / updateFile expect.
    rel_path = f"manual/20-walkthrough-{feature_id}.md"
    abs_path = workspace / rel_path

    if not abs_path.is_file():
        return (
            "## Prior version (this feature)\n\n"
            f"No prior file at `{rel_path}` — this is a cold-start for "
            f"`{feature_id}`.  Use the section template in your persona "
            "and `writeNewFile` to create the manual section from "
            "scratch.  Then `signal_completion` with "
            "`decision: \"created\"`."
        )

    return (
        "## Prior version (this feature)\n\n"
        f"A prior version exists at `{rel_path}`.\n\n"
        "**Workflow:**\n\n"
        f"1. `readFile(path=\"{rel_path}\")` to inspect the existing "
        "section (one tool call).\n"
        "2. Identify the anchors listed in your persona "
        "(`# heading`, `<!-- jaato:feature ... -->`, `**On screen:**`, "
        "`**Notes**`, `**Related sections**`).\n"
        "3. Use `updateFile` with old_string / new_string edits to "
        "surgically revise:\n"
        "   - **Always refresh** the `**On screen:**` code block from "
        "the new scene capture in your prompt.\n"
        "   - **Conservatively update** `**Notes**` only where the new "
        "scene actually differs.\n"
        "   - **Carry forward** the italic summary and prose paragraph(s) "
        "verbatim unless the new scene contradicts them.\n"
        "   - **Preserve** `**Related sections**` entries that still apply.\n"
        "4. `signal_completion` with `decision: \"updated\"` (or "
        "`\"no_change\"` if the new scene is identical to what's in "
        "the file).\n"
    )
