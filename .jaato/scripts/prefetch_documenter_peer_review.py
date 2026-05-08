"""Prefetch script — surface any peer review of the prior chapter.

Companion to ``prefetch_documenter_brief.py``.  Reads the existing
audit sidecar at ``manual/.payloads/<feature_id>.json`` (if present)
and looks for a non-empty ``peer_review`` field.  Surfaces the
content as authoritative feedback for the documenter agent to
address in this revision.

The peer review channel is for **post-run human or LLM critique**
that should drive a chapter rewrite on the next walker pass.  The
operator (or another LLM, e.g. running ``jaato-manual review`` —
not yet shipped) edits the sidecar JSON to fill ``peer_review`` with
prose feedback.  The walker's per-feature gate then sees the filled
review and re-triggers this feature's documenter.  This prefetch
hands the feedback to the agent.  After the agent calls
``signal_completion``, the reactor (``render_manual_section.py``)
writes a NEW sidecar with ``peer_review: ""`` — clearing the
feedback the agent just consumed.  One review → one revision pass.

When ``peer_review`` is absent or empty, this prefetch emits a brief
"this is either a cold-start or a satisfied warm-start; no peer
review pending" note so the agent's prompt always includes the
section header (predictable structure for the persona's read flow).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List


def render(context: Any, args: List[str]) -> str:
    workspace = (
        Path(context.workspace_path) if context.workspace_path
        else Path.cwd()
    )
    params = context.agent_params or {}
    feature_id = params.get("feature_id")

    if not feature_id:
        return (
            "## Peer review of the prior version\n\n"
            "[prefetch error: feature_id missing from agent_params; "
            "cannot read peer-review sidecar.  Treat as cold-start.]"
        )

    sidecar = workspace / "manual" / ".payloads" / f"{feature_id}.json"
    if not sidecar.is_file():
        return (
            "## Peer review of the prior version\n\n"
            "No prior audit sidecar — this is a cold-start.  No peer "
            "review feedback to address.  Generate the chapter from "
            "scratch per your persona's instructions."
        )

    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return (
            "## Peer review of the prior version\n\n"
            f"[prefetch error: could not parse sidecar at "
            f"`{sidecar}` — {exc}.  Treat as cold-start.]"
        )

    review = (data.get("peer_review") or "").strip()
    if not review:
        return (
            "## Peer review of the prior version\n\n"
            "Prior sidecar exists but `peer_review` is empty — the "
            "previous chapter was accepted without further feedback. "
            "(The walker normally skips features in this state; if "
            "you're seeing this, the operator force-triggered the "
            "feature.)  Treat as a warm-start refresh — read the "
            "existing chapter via your persona's prefetch and update "
            "only what's stale."
        )

    chapter_rel = f"manual/20-walkthrough-{feature_id}.md"
    return (
        "## Peer review of the prior version — ADDRESS THIS IN YOUR REVISION\n\n"
        f"A reviewer left the following feedback on the previously-written "
        f"chapter for `{feature_id}`:\n\n"
        f"```\n{review}\n```\n\n"
        "**This is the load-bearing input for this run.**  The previous "
        f"chapter exists at `{chapter_rel}` (your other prefetch points "
        "to it).  Your job:\n\n"
        f"1. `readFile(path=\"{chapter_rel}\")` to ground yourself in "
        "what's currently there.\n"
        "2. Re-observe the TUI as needed (`tmux capture-pane`) to verify "
        "the feedback against current reality.\n"
        "3. Use `updateFile` with surgical old-string / new-string edits "
        "to address the feedback — change ONLY what the review calls "
        "out, preserve everything else (especially operator polish).\n"
        "4. Call `signal_completion` with `decision: \"updated\"` and a "
        "`summary` that names which review point you addressed.\n\n"
        "Do NOT call `signal_completion` with `decision: \"no_change\"` "
        "when peer_review is present — the reviewer asked for a change "
        "and you must respond, even if only to disagree (in which case "
        "leave a `warnings` entry explaining why no change was made)."
    )
