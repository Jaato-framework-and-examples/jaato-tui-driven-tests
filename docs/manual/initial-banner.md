# Initial TUI state — banner + prompt

<!-- jaato:feature initial-banner -->

_The TUI opens with a header showing session metadata, agent status, and helpful guidance text._

When you start the jaato TUI, you see a structured interface with three main zones: a header bar at the top displaying session information and agent configuration, a large central area for conversation and output, and a footer with quick-reference guidance and connection status.

The header shows your current session ID, workspace path, toolblocks status (collapsed or expanded), and permission mode. Below that, you see the active agent name, the LLM provider and model in use, and a real-time context budget indicator showing how much of your token window is available. This helps you monitor whether you're approaching context limits during a long session.

The footer provides immediate guidance: it tells you that file editing is now available from the workspace panel, explains that tab completion is enabled (with hints for different completion types), lists keyboard shortcuts for common actions, and confirms your connection to the LLM provider. This information is always visible, so you can reference it without needing to type `help`.

**On screen:**

```text
 Session: 20260507_222929  │  Workspace: ~/Sources/Jaato-framework-and-examples/jaato-tui-driven-tests  │  Toolblocks: ▶ collapsed [Ctrl+T]  │  Permissions: ask
 ⠋  Main Agent
 Provider: openrouter  │  Model: anthropic/claude-haiku-4.5  │  Context: 85% available (29K used, continuous →40%) [Ctrl+B for budget]
 We now can edit files from the workspace panel
 Tab completion enabled. Use file for files, @path for sandbox paths, prompt for skills.
 Type 'help' for commands, Ctrl+G for editor, Ctrl+F for search.
 Connected to openrouter/anthropic/claude-haiku-4.5 (OpenRouter API key)
 Session created: Session 2026-05-07 22:29 (20260507_222929)

User>
```

**Notes**

- The header line displays the session ID (for reference and logging), the workspace directory, and quick toggles: Toolblocks (collapsed by default, toggled with Ctrl+T) and Permissions mode (set to "ask")
- The agent line shows the active agent name (Main Agent) with a spinner icon (⠋) indicating readiness
- The provider/model line shows which LLM backend is active and the current context budget (percentage available, absolute tokens used, and continuous mode status)
- The footer provides immediate guidance: file editing availability, tab completion hints (file, @path, prompt), keyboard shortcuts (Ctrl+G for editor, Ctrl+F for search), and connection confirmation
- A session creation timestamp is displayed, confirming when the session was initialized
- The header bar is always visible and updates in real time (e.g., context budget changes as you use tokens)
- Tab completion works in the input prompt and adapts based on context (file paths, sandbox paths, or skill names)

**Related sections**

- (none yet)
