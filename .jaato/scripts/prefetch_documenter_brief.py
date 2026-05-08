"""Prefetch script — render the documenter's per-feature brief.

The walker passes the feature's manifest entry to the documenter via
``agent_params``: ``feature_id`` / ``feature_title`` / ``feature_goal``
/ ``context_hints`` / ``tmux_pane``.  This prefetch turns those
into a labeled brief block that gets injected into the documenter's
system instructions where ``{{!py:scripts/prefetch_documenter_brief.py}}``
appears.

Why a prefetch (not inline ``{{feature_id}}`` template substitution):
jaato's persona-template engine resolves ``{{!py:...}}`` placeholders
via a render context that exposes ``agent_params``, but does NOT
auto-interpolate bare ``{{var}}`` placeholders against agent_params.
A prefetch script is the supported path to read agent_params and
inject content into the system prompt.

Wired via ``{{!py:scripts/prefetch_documenter_brief.py}}`` in
``.jaato/agents/documenter.md``.  Cold-start (agent_params missing
required keys) emits a clear error block so the agent can surface
the misconfiguration via ``warnings`` in its completion payload.
"""
from __future__ import annotations

from typing import Any, List


def render(context: Any, args: List[str]) -> str:
    params = context.agent_params or {}
    feature_id = params.get("feature_id")
    feature_title = params.get("feature_title")
    feature_goal = params.get("feature_goal")
    context_hints = params.get("context_hints", "")
    tmux_pane = params.get("tmux_pane")

    missing: List[str] = []
    for key, val in (
        ("feature_id", feature_id),
        ("feature_title", feature_title),
        ("feature_goal", feature_goal),
        ("tmux_pane", tmux_pane),
    ):
        if not val:
            missing.append(key)

    if missing:
        return (
            "## Feature brief\n\n"
            f"[prefetch error: agent_params is missing required keys: "
            f"{', '.join(missing)}.  The walker must forward all of "
            "feature_id, feature_title, feature_goal, tmux_pane.  Call "
            "signal_completion with decision='no_change' and a warnings "
            f"entry explaining the misconfiguration.]"
        )

    hints_block = (
        f"### Hints from the manifest\n\n{context_hints.strip()}\n"
        if context_hints and context_hints.strip()
        else ""
    )

    return (
        "## Feature brief — what you're documenting\n\n"
        f"- **feature_id**: `{feature_id}`  \n"
        f"  The chapter you write is `manual/20-walkthrough-{feature_id}.md`.\n"
        f"- **title**: {feature_title}  \n"
        f"  Use this exact string in the H1 of the chapter.\n"
        f"- **tmux_pane**: `{tmux_pane}`  \n"
        "  Target this string for EVERY `tmux capture-pane` and "
        "`tmux send-keys` call.  Do not assume any other pane.\n\n"
        "### Goal — what to cover in the chapter\n\n"
        f"{feature_goal.strip()}\n"
        + (f"\n{hints_block}" if hints_block else "")
    )
