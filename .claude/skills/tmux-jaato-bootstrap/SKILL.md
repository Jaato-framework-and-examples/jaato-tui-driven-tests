---
name: tmux-jaato-bootstrap
description: Stand up a fresh jaato workspace from inside a Claude Code session using tmux as the driver. Covers the pre-check/post-check discipline, workspace anatomy, .env vs profile config decisions, provider-auth precheck, TUI launch arguments, and end-to-end health verification via the daemon + session logs. Use when bootstrapping an ad-hoc workspace for testing a framework change, validating a config knob, or sanity-checking an environment without leaving the Claude Code session.
---

# Tmux-driven jaato workspace bootstrap

Bring up a working jaato workspace from inside a Claude Code session: open a tmux pane, lay out the workspace files, configure the .env, launch the TUI, and verify the daemon accepted the session — without ever leaving the conversation. Built from the empirical pattern that proved each step works (preventing the failure modes that bite when you skip checks).

The methodology is broader than just "run the TUI". It's a discipline:

- **Pre-check before each step.** Don't assume the prior state — verify the directory exists / the daemon is up / the auth file is present. Catches the surprises early, before they cascade.
- **Tmux as the driver.** Open a separate pane / window so the bootstrap doesn't pollute Claude Code's pane and so the operator can `tail` the live session if needed.
- **Post-check after each step.** Don't assume the action succeeded — confirm via `pwd` / `ls` / `tmux capture-pane` / daemon log. The post-check is what distinguishes "I did the thing" from "the thing happened."
- **End-to-end health check.** A trivial prompt like "Who are you?" closes the loop on every layer (TUI ↔ daemon ↔ provider ↔ GC ↔ reactor) — cheaper than reasoning about which layer might be broken.

---

## When to use this skill

Invoke it when:

- Bootstrapping a fresh jaato workspace for ad-hoc testing — a sandbox to try a new persona / profile / GC mode without touching an existing project's tree.
- Validating a freshly-shipped framework change end-to-end before declaring it done (e.g. server X.Y.Z just merged; new workspace + minimal .env confirms the daemon picks up the new behavior cleanly).
- Sanity-checking host state after suspect daemon behavior (auth re-rotation, plugin discovery, AppArmor profile generation).
- Setting up a coordination peer's workspace where they need a usable session but you're driving from your own pane.

If you're attaching to an existing workspace OR running an orchestrator-driven cascade (handoff_test-style), use the running-orchestrator pattern instead — this skill is for from-scratch greenfield bootstrap.

---

## The pre-check / post-check discipline

Six steps, each gated by a check pair. Skipping pre-checks invites "the directory already exists with stale content" or "the daemon isn't running" failures that surface as confusing TUI errors much later. Skipping post-checks lets silent failures (action sent to the wrong pane, file written to the wrong path, env var ignored) live until something else breaks.

| Step | Pre-check | Action | Post-check |
|---|---|---|---|
| 1. Open new tmux window | `tmux list-windows -a` — see existing layout, pick a non-colliding index | `tmux new-window -t <session>: -n <descriptive-name>` | `tmux list-panes -t <session>:<idx> -F '#{pane_current_command} #{pane_current_path}'` confirms the pane exists with bash + a known cwd |
| 2. cd to parent dir | `ls -d <parent>/` — confirm parent exists | Send `cd <absolute-path>` via two-step `tmux send-keys` (text first, sleep 1, then Enter) | Send `pwd`; capture pane; verify the printed path |
| 3. mkdir workspace | `ls -d <new-workspace>` — confirm it does NOT exist (stale content from prior runs is a real failure mode) | Send `mkdir <name> && cd <name> && pwd` | `ls -ld <new-workspace>` from outside the pane; capture pane to confirm `pwd` matches |
| 4. Write .env | `ls <workspace>/.env` — confirm it does NOT exist | Write file via Claude Code's Write tool (NOT echo > .env in the pane — Write gives you reviewable content) | `cat .env` in the pane confirms content; check no surprise BOM / line-ending issues |
| 5. Launch TUI | Daemon is up (`/tmp/jaato-test/bin/jaato-server --status`); provider auth file exists (`ls ~/.jaato/<provider>_auth.json`); TUI script exists at `<jaato-repo>/jaato-tui/rich_client.py`; venv has python | Send the TUI launch command; sleep 8s for startup + session.new round-trip | Capture pane; look for `Session: <id>` + `Workspace: <path>` + `Connected to <provider>/<model>` + `User>` prompt; daemon log has matching `Creating session for client ipc_N: env_file=<workspace>/.env` |
| 6. Health check via prompt | Pane is at `User>` (capture confirms) | Send `Who are you?` (two-step tmux send-keys); sleep 15s for provider round-trip | Capture pane shows model response with token counts + duration; daemon's session log has `GC_CHECK: plugin=BudgetGCPlugin usage=X% threshold=Y% target=Z% continuous=…` confirming env-var handoff to GCConfig |

Each pre-check is cheap (under a second). Each post-check is the only authoritative confirmation that the action took effect. The discipline pays for itself the first time a step silently fails.

---

## Tmux pane vs new-window choice

Sessions on this host historically use **one pane per window** (each Claude instance gets its own window). The bootstrap skill follows that convention: `tmux new-window -t <session>: -n <name>` rather than `tmux split-window`.

When to deviate:

- **Split-pane** when the bootstrap needs to be visually adjacent to the current pane (e.g. side-by-side log tail). Cost: smaller pane size; the TUI is most readable at ≥120 cols.
- **Existing window with bash** when the operator has a "scratch" pane already open and asks you to reuse it. Pre-check by capturing the pane to confirm it's at a clean prompt (no half-typed command, no running process).

The default-and-best is a fresh window. New windows inherit cwd from the active pane, so verify cwd in the post-check (step 2 in the table above) — your starting cwd may not be where the new window lands.

---

## Workspace anatomy

Minimum viable workspace for a TUI session:

```
<workspace>/
├── .env                           # provider + model + (optionally) GC env-var knobs
└── .jaato/                        # auto-created by daemon on first session.new
    └── logs/
        └── session_<id>_client_*.log
```

That's the floor. Most workspaces add:

```
<workspace>/
├── .env
├── .jaato/
│   ├── profiles/
│   │   └── <name>.yaml            # if you want non-default plugins / GC config / completion schema
│   ├── agents/
│   │   └── <name>.md              # if a profile references --agent
│   └── reactors/
│       └── <name>.json            # for cascade flows
├── sandbox/                       # write target for cli / file_edit tools
│   └── (workspace files)
└── README.md                      # optional; tracks the workspace's purpose
```

The bootstrap skill creates only `<workspace>/` and `<workspace>/.env`. The daemon auto-provisions `.jaato/logs/` on session.new. Profiles / agents / reactors are added when the workspace's purpose requires them.

---

## .env vs profile config — the decision tree

Both surfaces accept config; pick the right one or things end up split awkwardly.

**Use .env when:**
- Provider selection (`JAATO_PROVIDER=<name>`).
- Model selection (`MODEL_NAME=<name>`).
- GC env-var knobs (`JAATO_GC_THRESHOLD`, `JAATO_GC_TARGET`, `JAATO_GC_PRESSURE` — see "GC modes via .env" below).
- Workspace-wide secrets (`OPENROUTER_API_KEY`, etc.) — though prefer `~/.jaato/<provider>_auth.json` for OAuth-style credentials.
- Per-workspace overrides of daemon-level defaults that the daemon reads via `os.environ.get`.

**Use a profile YAML when:**
- Plugin set differs from daemon default (`plugins: [signal_completion(preload), cli, ...]`).
- Per-plugin config (`plugin_configs.permission.policy.whitelist.tools: [...]`).
- Completion schema reference (`completion_payload_schema: completion_schemas/<x>.json`).
- Provider-specific knobs that don't have env-var equivalents (e.g. anthropic `enable_thinking: true`, openrouter routing extension).
- Anything the model's persona references at session-init.

**Anti-pattern**: writing GC plugin config (target / pressure / threshold) inline in a profile when the .env env-var path covers the same knobs. Pick one. The .env path is simpler for ad-hoc workspaces; the profile path scales for many tenants sharing a base config.

### GC modes via .env

`shared/plugins/gc/base.py` reads three env vars at `GCConfig` construction time:

| Env var | Default | Meaning |
|---|---|---|
| `JAATO_GC_THRESHOLD` | `80.0` | Threshold-mode trigger — GC runs once when usage ≥ this percent |
| `JAATO_GC_TARGET` | `60.0` | Continuous-mode trigger AND post-GC usage target |
| `JAATO_GC_PRESSURE` | `90.0` | When to touch PRESERVABLE entries; **`0` enables continuous mode** |

Continuous-mode .env stanza (the "budget GC continuous-target" pattern):

```bash
JAATO_GC_PRESSURE=0          # = continuous mode
JAATO_GC_TARGET=60.0         # GC keeps usage at or below 60%
JAATO_GC_THRESHOLD=80.0      # kept for completeness; unused while pressure=0
```

Threshold-mode is the default; explicitly setting `JAATO_GC_THRESHOLD=80.0` carries no behavioral change. Continuous-mode is more aggressive — it prunes after every turn rather than waiting for context pressure.

Verification (after step 6 health check fires): grep the per-session log for `GC_CHECK:` — if your env vars took effect, you'll see `plugin=BudgetGCPlugin usage=…% threshold=80.0% target=60.0% continuous=True`.

---

## Auth-state precheck

Before pinning `JAATO_PROVIDER=<X>` in .env, verify the corresponding auth file exists:

```bash
ls ~/.jaato/*_auth.json
ls ~/.jaato/anthropic-pkce.json   # OAuth PKCE token (anthropic subscription)
```

Common mappings:

| Provider | Auth file | Setup command |
|---|---|---|
| `zhipuai` | `~/.jaato/zhipuai_auth.json` | `zhipuai-auth key <api-key>` |
| `anthropic` | `~/.jaato/anthropic-pkce.json` (OAuth) or `ANTHROPIC_API_KEY` env | PKCE: `oauth_login()` from `shared.plugins.model_provider.anthropic` |
| `openrouter` | `~/.jaato/openrouter_auth.json` | `openrouter-auth key <api-key>` |
| `nim` | `~/.jaato/nim_auth.json` | `nim-auth key <api-key>` |
| `github_models` | `~/.jaato/github_auth.json` | `github-auth login` |
| `claude_cli` | (uses local `claude` CLI subscription state) | `claude login` (not via jaato) |
| `antigravity` | OAuth via `oauth_login()` from `shared.plugins.model_provider.antigravity` | (interactive) |
| `gemini` / `google_genai` | `GOOGLE_APPLICATION_CREDENTIALS` env or ADC | (gcloud setup) |

**If the auth file is missing**, the TUI starts but session.new fails at provider connect time with an opaque error. Pre-check saves the cycle. If multiple providers are authenticated, pick the one matching the workload's known-working pattern (e.g. handoff_test uses zhipuai; kb-enablement-2.0 uses anthropic; reach for whichever has been recently exercised).

---

## TUI launch invocation

Canonical command:

```bash
PYTHONPATH=<jaato-repo>/jaato-server \
  /tmp/jaato-test/bin/python \
  <jaato-repo>/jaato-tui/rich_client.py \
  --connect /tmp/jaato.sock \
  --new-session
```

Send via two-step `tmux send-keys` (text first, `sleep 1`, then `Enter`) to dodge Claude-Code-style paste-block placeholder swallow.

Args that matter:

| Arg | Purpose | When to use |
|---|---|---|
| `--connect /tmp/jaato.sock` | Bind to a running daemon | Always when daemon is already up; without this, TUI tries to auto-start |
| `--new-session` | Start fresh; don't resume the workspace's last session | When bootstrapping; resume is a different workflow |
| `--profile <name>` | Use a profile from `<workspace>/.jaato/profiles/` | When the workspace has a profile worth pinning |
| `--agent <name>` | Use an agent persona from `<workspace>/.jaato/agents/` | When you want the agent's persona instead of the daemon default |
| `--env-file <path>` | Override the default `.env` location | Rarely; default is `./.env` from the launch cwd |
| `--workspace <path>` | Override workspace dir for headless | When using `--headless`; otherwise launch from the workspace dir |
| `--prompt "..."` / `--initial-prompt "..."` | One-shot vs interactive-with-seed | Headless / scripted runs |

Default workspace is the launch cwd — pre-check that cwd is correct before launching.

---

## Post-launch verification sources

Four sources to cross-reference; consult all four when a session looks half-functional:

**1. TUI banner** (the visible top of the pane):
```
Session: <id>  │  Workspace: <truncated-path>
Provider: <name>  │  Model: <name>  │  Context: X% available (Y used, …)
```
Tells you the session-id, the user-visible workspace path, the resolved provider/model. Truncates at the column width — for full paths cross-reference the daemon log.

**2. Daemon log** (`/tmp/jaato.log`, append-only):
```
[INFO] server.session_manager: Client ipc_N set working_dir=…
[INFO] server.session_manager: Client ipc_N set env_file=…
[INFO] server.session_manager: Creating session for client ipc_N: env_file=…
[INFO] server.session_manager:   Client config: {'presentation': {…}, 'working_dir': '…', 'env_file': '…'}
[INFO] server.session_manager: Session created: <id> (Session …)
```
Authoritative for: workspace path, env_file path, presentation context, profile resolution.

**3. Per-session log** (`<workspace>/.jaato/logs/session_<id>_client_<ipc-N>.log`):
```
[INFO] shared.jaato_session: GC_CHECK: plugin=… usage=…% threshold=…% target=…% continuous=…
[DEBUG] anthropic._base_client: Request options: {…}
[INFO] shared.plugins.<name>: <plugin-specific>
```
Authoritative for: GC plugin selection + config, per-plugin init traces, provider request bodies (under DEBUG), tool execution traces.

**4. dmesg AppArmor audit** (when daemon is confined):
```bash
dmesg -T | grep apparmor | tail
```
Authoritative for: AppArmor allow/deny decisions per session profile. Required when verifying multi-tenant isolation; skip when daemon is unconfined (Phase 2+ runner work).

---

## Health check via "Who are you?"

A trivial prompt that exercises every layer:

- TUI input handling (text-first → Enter pattern)
- TUI → daemon IPC frame (round-trip)
- daemon's session manager → JaatoSession turn-handler
- session → provider client (auth + network)
- provider response → session GC check (validates GCConfig env-var handoff)
- response → TUI display (markdown rendering, token-count footer)

If "Who are you?" returns a coherent persona statement with token counts and a duration, every layer is up. If any layer is broken, the failure is concretely visible (no response = provider; partial response = streaming; weird tokens = bad prompt cache; etc.).

Why this prompt over alternatives:

- **Cheap**: ~20K tokens in / a few hundred out, 10-15s wall time on most providers.
- **No tools**: doesn't exercise plugin config, so failures isolate to the provider+session layer.
- **Self-introspecting**: the response usually mentions the agent's tools / persona, surfacing whether the workspace's plugin set landed in the system instructions.
- **GC verification**: forces a GC_CHECK log entry so .env GC env-var handoff can be confirmed (see "GC modes via .env" above).

Variants for narrower checks:

- **"List your tools"** — exercises the tool-schema injection path; if a plugin failed to load, its tools are missing here.
- **"What workspace are you in?"** — exercises the system-instruction substitution that includes `workspace_path`; surfaces presentation-context handling.
- **"Run `pwd`"** — exercises the cli plugin end-to-end (subprocess spawn + streaming + result enrichment).

Default to "Who are you?" for the first health check; reach for variants when narrowing a specific failure.

---

## Anti-patterns to avoid

- **Skipping pre-checks** "because I just ran the prior step." A long thinking-pause between steps is enough for daemon state to drift; the operator can have run an unrelated command in another pane; tmux send-keys can have landed on the wrong target. Pre-check is cheap; skip-and-discover is expensive.
- **Single-call `tmux send-keys 'cmd' Enter`**. Multi-line content gets swallowed by Claude Code's paste-block placeholder. Two-call (text first → `sleep 1` → `Enter`) is uniformly safe. Single-call works for one-line content but isn't a habit worth forming.
- **Writing .env via `echo > .env` in the pane**. Heredocs through tmux are fragile (newline handling, escaping). Use Claude Code's Write tool — content is reviewable in the conversation, file lands atomically, no escaping fights.
- **Pinning a provider whose auth isn't set up.** The TUI starts (auth check is lazy), but session.new fails at provider connect with an opaque error. Pre-check `~/.jaato/<provider>_auth.json` before pinning.
- **Trusting the TUI banner alone for workspace path verification.** It's truncated at the column width. Cross-reference daemon log's `working_dir=…` line.
- **Treating "session created" as "everything works."** session.new succeeds before the first model call. Run the health-check prompt to confirm provider-side end-to-end works.
- **Forgetting to verify GC env vars in the per-session log.** "I set the env vars" ≠ "GCConfig read them." First GC_CHECK log entry is the only authoritative confirmation.

---

## Reference: paste-ready bootstrap script

```bash
# 0. Inspect existing tmux layout
tmux list-windows -a -F '#{session_name}:#{window_index} #{window_name}'

# 1. New window for the workspace
SESSION=7  # adjust to match the operator's session
tmux new-window -t ${SESSION}: -n my-test-workspace
sleep 1
tmux list-panes -t ${SESSION}:5 -F '#{pane_current_command} #{pane_current_path}'

# 2. cd to parent
tmux send-keys -t ${SESSION}:5 'cd /home/apanoia/Sources/Jaato-framework-and-examples'
sleep 1
tmux send-keys -t ${SESSION}:5 Enter
sleep 1
tmux send-keys -t ${SESSION}:5 'pwd'
sleep 1
tmux send-keys -t ${SESSION}:5 Enter
sleep 1
tmux capture-pane -t ${SESSION}:5 -p | tail -3

# 3. mkdir workspace
tmux send-keys -t ${SESSION}:5 'mkdir my-test-workspace && cd my-test-workspace && pwd'
sleep 1
tmux send-keys -t ${SESSION}:5 Enter
sleep 1
ls -ld /home/apanoia/Sources/Jaato-framework-and-examples/my-test-workspace

# 4. Write .env (use Claude Code's Write tool, not echo > .env — the
# example below shows the content shape; in practice write via Write).
cat > /home/apanoia/Sources/Jaato-framework-and-examples/my-test-workspace/.env <<'EOF'
JAATO_PROVIDER=zhipuai
MODEL_NAME=glm-5-turbo
JAATO_GC_PRESSURE=0
JAATO_GC_TARGET=60.0
JAATO_GC_THRESHOLD=80.0
EOF
ls -la /home/apanoia/Sources/Jaato-framework-and-examples/my-test-workspace/.env

# 5. Pre-check daemon + auth + venv
/tmp/jaato-test/bin/jaato-server --status
ls ~/.jaato/zhipuai_auth.json
ls /home/apanoia/Sources/Jaato-framework-and-examples/jaato/jaato-tui/rich_client.py

# 5. Launch TUI
tmux send-keys -t ${SESSION}:5 'PYTHONPATH=/home/apanoia/Sources/Jaato-framework-and-examples/jaato/jaato-server /tmp/jaato-test/bin/python /home/apanoia/Sources/Jaato-framework-and-examples/jaato/jaato-tui/rich_client.py --connect /tmp/jaato.sock --new-session'
sleep 1
tmux send-keys -t ${SESSION}:5 Enter
sleep 8
tmux capture-pane -t ${SESSION}:5 -p | tail -30

# Cross-reference daemon log
grep -E '20260507|jaato-tui-driven-tests' /tmp/jaato.log | tail -10

# 6. Health check
tmux send-keys -t ${SESSION}:5 'Who are you?'
sleep 1
tmux send-keys -t ${SESSION}:5 Enter
sleep 15
tmux capture-pane -t ${SESSION}:5 -p | tail -30

# Verify GC continuous mode took effect
SID=$(grep -oE 'Session created: [0-9_]+' /tmp/jaato.log | tail -1 | awk '{print $3}')
grep 'GC_CHECK' "/home/apanoia/Sources/Jaato-framework-and-examples/my-test-workspace/.jaato/logs/session_${SID}"_*.log | head -3
```

---

## Tmux command quick-reference

The commands this skill leans on, grouped by purpose. All assume an
existing tmux session (the operator's current one); `<S>` = session,
`<W>` = window, `<P>` = pane.

### Identify topology — what panes exist where?

```bash
# All panes across all sessions, with cwd + running command
tmux list-panes -a -F '#{session_name}:#{window_index}:#{pane_index} #{pane_current_command} #{pane_current_path}'

# Windows in one session
tmux list-windows -t <S>

# Panes in one window
tmux list-panes -t <S>:<W>

# What's running in a specific pane (script-friendly, no header)
tmux display-message -t <S>:<W> -p '#{pane_current_command}'
tmux display-message -t <S>:<W> -p '#{pane_current_path}'
```

The list-panes `-F '...'` format string is the primary discovery tool —
use it whenever you're not 100% sure which pane the operator means by
"my Claude pane" or "the TUI pane."

### Capture pane content — read what the TUI is showing

```bash
# Visible portion only (most common)
tmux capture-pane -t <S>:<W> -p

# Last N lines (chain through tail)
tmux capture-pane -t <S>:<W> -p | tail -30

# Last N lines from history (-S flag = start of capture)
tmux capture-pane -t <S>:<W> -p -S -100

# Entire scrollback history
tmux capture-pane -t <S>:<W> -p -S -

# Filter for a marker — useful when expecting specific output
tmux capture-pane -t <S>:<W> -p -S -200 | grep -B2 -A5 'Session created'
```

`-p` writes to stdout (vs the default which writes to a tmux paste
buffer). `-S -<N>` controls how far back into the scrollback to capture
— omit and you get just what's currently visible.

For TUI sessions specifically, **the visible portion is what matters**
(the TUI redraws on every event), so `tmux capture-pane -t <pane> -p`
without `-S` is usually right. Reach for `-S -<N>` only when the TUI
has scrolled past the content you need (long agent responses, memory
injections, etc.).

### Send input — drive a pane from outside

The two-step pattern (text first, sleep, then Enter as a separate
call) is uniformly safe across single-line and multi-line content:

```bash
tmux send-keys -t <S>:<W> 'your text here'
sleep 1
tmux send-keys -t <S>:<W> Enter
```

**Why two-step:** Claude Code's TUI shows multi-line content as a
`[Pasted text #1 +N lines]` placeholder. If `Enter` lands in the same
`send-keys` call as the text, it's consumed by paste-mode rather than
the submit handler — your text sits in the input box forever.

For special keys the second arg names the key directly:

```bash
tmux send-keys -t <S>:<W> Enter         # submit
tmux send-keys -t <S>:<W> C-c           # Ctrl+C — cancel current operation
tmux send-keys -t <S>:<W> C-d           # Ctrl+D — EOF (NOT a clean TUI exit; see Tear-down)
tmux send-keys -t <S>:<W> C-l           # Ctrl+L — clear screen
tmux send-keys -t <S>:<W> BSpace        # Backspace
tmux send-keys -t <S>:<W> Escape        # ESC
tmux send-keys -t <S>:<W> Up            # arrow keys
tmux send-keys -t <S>:<W> Tab           # tab (autocomplete in most TUIs)
```

Combine via spaces or chain calls:

```bash
# Send text then submit in one call (one-line content; safe for single line)
tmux send-keys -t <S>:<W> 'pwd' Enter

# Cancel a running command, wait, then run a new one
tmux send-keys -t <S>:<W> C-c
sleep 1
tmux send-keys -t <S>:<W> 'jaato-server --status'
sleep 1
tmux send-keys -t <S>:<W> Enter
```

### Window / pane management

```bash
# Create a new window with a descriptive name
tmux new-window -t <S>: -n <name>

# Kill a window (e.g., tear-down after workspace use)
tmux kill-window -t <S>:<W>

# Rename a window
tmux rename-window -t <S>:<W> <new-name>

# Split current pane (rarely needed for jaato bootstrap; use new-window)
tmux split-window -t <S>:<W>           # horizontal split (top/bottom)
tmux split-window -t <S>:<W> -h        # vertical split (left/right)
```

### Paste buffers — for content too large for `send-keys`

When pushing multi-paragraph content (e.g. a long ping to a peer), use
the paste-buffer pattern:

```bash
# Stage content from a file into the buffer, paste into target pane,
# submit as a separate Enter to dodge the paste-block placeholder.
tmux load-buffer /tmp/my-message.txt
tmux paste-buffer -t <S>:<W>
sleep 2
tmux send-keys -t <S>:<W> Enter
```

This is the canonical pattern for Claude-to-Claude pings (see
`tmux-pair-claude` skill for the full bidirectional protocol).

### Pane state diagnosis — is the TUI ready for input?

```bash
# Quick "what does the prompt look like right now"
tmux capture-pane -t <S>:<W> -p | tail -3

# What's actually running in the pane (claude / bash / python / etc.)
tmux display-message -t <S>:<W> -p '#{pane_current_command}'

# Is there queued input the TUI hasn't processed yet?
# (shows as "❯ Press up to edit queued messages" on the last line)
tmux capture-pane -t <S>:<W> -p | tail -1
```

**Diagnostic rules:**

- TUI shows `User>` (or equivalent prompt-arrow) — ready for input.
- TUI shows `[Pasted text #N: +M lines]` — paste-block; don't send
  more text, send `Enter` to flush.
- TUI shows `Press up to edit queued messages` — your prior input
  landed and is queued; receiver will pick it up when current task
  completes. Don't retry; don't poll aggressively.
- TUI shows nothing matching any of the above — capture more
  scrollback (`-S -50`) to see what state it's in.

---

## Tear-down

When the workspace is no longer needed:

1. **Close the TUI by typing `exit` at the User> prompt.**  This is the
   ONLY clean-disconnect path.  Tmux equivalent:

   ```bash
   tmux send-keys -t <pane> 'exit'
   sleep 1
   tmux send-keys -t <pane> Enter
   sleep 3
   tmux capture-pane -t <pane> -p | tail -5  # confirm shell prompt
   ```

   **Do NOT use `Ctrl+D` for this.**  Despite being mapped to `exit` in
   `keybindings.py`, the Ctrl+D handler raises `EOFError` via
   `event.app.exit(exception=EOFError())`, which propagates as an
   unhandled Python stack trace through prompt_toolkit's run loop —
   not a clean shutdown.  The capture will end with a traceback ending
   in `EOFError`; easy to misread as "clean" if you only glance.

   **Do NOT use `Ctrl+C` either.**  That's `cancel` — interrupts the
   current turn, leaves the TUI alive at the User> prompt.

2. Close the tmux window: `tmux kill-window -t <session>:<idx>`.
3. (Optional) `rm -rf <workspace>` — the workspace is application-owned,
   no daemon-side cleanup needed beyond the session log already written
   there.

The daemon survives across workspace tear-downs.  Don't restart it
unless the test was specifically about post-restart behavior (e.g.,
verifying that a freshly-shipped framework change loads cleanly via
the editable install).
