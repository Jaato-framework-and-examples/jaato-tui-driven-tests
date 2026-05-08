"""Static catalog generation — placeholder.

The original `inventory` step parsed `jaato-tui/keybindings.py` via
regex and merged in regex-based discoveries from live captures.  Both
were stop-gaps for the cascade-driven shape we're moving to:

- A `toc_discoverer` agent reads the relevant TUI source files and
  emits a typed TOC payload (keybindings[], commands[], panels[],
  walkthrough_candidates[]).
- A reactor renders the catalog .md files (10-* / 11-* / 12-*) from
  the validated payload — same primitive cascade as `manual_writer`.

This module is a stub until that agent + reactor land.  Running it is
a no-op so `python -m harness all` doesn't fail; the walk + build
phases work independently.
"""
from pathlib import Path


class InventoryGenerator:
    """No-op for now — see module docstring."""

    def __init__(self, manual_dir: Path):
        self._manual_dir = manual_dir

    def run(self) -> None:
        print(
            "  · inventory step is a no-op pending the toc_discoverer "
            "agent + reactor (cascade rewrite in progress)"
        )
