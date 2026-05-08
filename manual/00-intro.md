---
title: "jaato TUI — User Manual"
---

# Introduction

This manual documents the jaato TUI client (`rich_client.py`) — the
terminal interface for interacting with the jaato daemon.  Sections are
organized into:

- **Reference catalogs** (auto-generated): keybindings, slash commands,
  tools, profile knobs.  These reflect the live framework state on the
  day this manual was built.
- **Feature walkthroughs** (auto-generated capture + operator-edited
  caption): one section per feature, showing what you see and what to
  do with it.
- **Appendix**: tear-down, troubleshooting, where to read the source.

This document is built by a self-documenting harness — the harness
drives a real TUI session via tmux and captures each feature's screen
state directly.  The captures are real terminal output, not synthesized
mockups.

If something in here looks wrong or stale, regenerate the manual:

    cd jaato-tui-driven-tests
    python -m harness all

The walk phase needs an active jaato daemon on `/tmp/jaato.sock`.
