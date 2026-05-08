# Ctrl+B — Budget panel (token usage by category)

<!-- jaato:feature ctrl-b-budget-panel -->

_View real-time token consumption across system, plugin, enrichment, conversation, and thinking categories._

The budget panel displays a live breakdown of how your context window is being consumed. This is useful for understanding where tokens are going and whether you're approaching the context limit. The panel shows each category's token count, garbage-collection status, and a visual bar indicating usage relative to the total.

The panel is organized by source: **System** (base instructions and framework overhead), **Plugin** (reliability and coordination plugins), **Enrichment** (dynamic context), **Conversation** (user and agent messages), and **Thinking** (internal reasoning tokens, if enabled). Each row shows the token count, a lock/partial/ephemeral indicator, and a proportional usage bar.

At the top of the panel, you'll see the total token count and the percentage of context available. The status line at the bottom reminds you of navigation controls: arrow keys to move between rows, Enter to drill down into a category, and Esc to close the panel.

**On screen:**

```text
╭──────────────────────────────────────────────────────────────────────────────── Token Usage (Total: 29.8K tokens) ────────────────────────────────────────────────────────────────────────────────╮
│  Source                                                                                Tokens           GC           Usage                                                                        │
│  ▶ System                                                                               25.4K           🔒           ███████████████░░░                                                           │
│    Plugin                                                                                4.4K           🔒           ██░░░░░░░░░░░░░░░░                                                           │
│    Enrichment                                                                               0           ○            ░░░░░░░░░░░░░░░░░░                                                           │
│    Conversation                                                                             0           ◐            ░░░░░░░░░░░░░░░░░░                                                           │
│    Thinking                                                                                 0           ○            ░░░░░░░░░░░░░░░░░░                                                           │
```

**Notes**

- Each row shows a source category with its token count, garbage-collection status (🔒 locked, ◐ partial, ○ ephemeral), and a proportional usage bar
- The ▶ symbol indicates a collapsible category; press Enter to drill down and see subcategories
- The total token count and context availability percentage appear in the panel header
- Navigation is via arrow keys (↑↓), Enter to expand/drill down, and Esc to close
- Locked categories (🔒) are protected from garbage collection; ephemeral (○) categories may be cleared to free space

**Related sections**

