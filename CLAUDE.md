# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A self-documenting harness for the **jaato** TUI client. It drives the live TUI
through a manifest of features, has an LLM agent write a manual chapter for each,
and renders the result to PDF. The output is the jaato TUI documenting itself —
not a synthesized mockup.

This repo is an *example workspace* that sits beside the framework it documents.
It does not contain the framework; it consumes it via `jaato-sdk` and by spawning
the real TUI process. See `../jaato/` for framework internals.

## Commands

```bash
pip install -e .                 # install the harness (needs jaato-sdk on the venv)
jaato-manual doctor              # or: python -m harness doctor — run this FIRST
jaato-manual all                 # inventory → walk → build → build/tui-user-manual.pdf
python -m harness walk           # just the TUI-driving phase
python -m harness build          # just re-render the PDF from manual/*.md
python -m harness <step> --socket /path/to/jaato.sock   # non-default daemon socket
```

- There is **no test suite, linter, or formatter**. `doctor` is the closest thing
  to a health check — it probes every Python + system dep and exits non-zero if any
  is missing. Run it before debugging "it doesn't work" problems.
- `inventory` is currently a **no-op stub** (`harness/inventory.py`) pending a
  `toc_discoverer` agent + reactor rewrite. `all` still runs it harmlessly.

## Hard runtime preconditions

`walk` will not work unless these are true — they are not auto-provisioned:

1. **A reachable daemon socket** (default `/tmp/jaato.sock`). The walker uses
   `IPCRecoveryClient` with `auto_start=True`, so it will **start the daemon if one
   isn't running** (cold start ~30–60s; `connect(timeout=120)`) and auto-reconnect if
   the daemon restarts mid-walk. Check an existing one with `jaato-server --status`.
2. **The TUI launch path is environment-specific.** `walker._launch_tui` shells out
   to `/tmp/jaato-test/bin/python` running `../jaato/jaato-tui/rich_client.py` with
   `PYTHONPATH=../jaato/jaato-server`. `REPO_ROOT` is hardcoded as the `jaato`
   sibling of this repo (`harness/walker.py`). A different dev layout means editing
   `_launch_tui`.
3. Provider auth is configured (`.env` + the active profile's provider). The TUI
   must reach its `User>` prompt within 30s or the launch raises.

## Architecture

The defining trait: this harness is **LLM-driven, not a keystroke script**. The
manifest is *prefetch context* for an autonomous agent that decides every keystroke.

### Two LLMs, one tmux pane

There are two distinct LLMs at runtime, and conflating them is the most common
source of confusion (the `documenter` persona opens with a section warning about
exactly this):

- **The documenter agent** — spawned by the walker per feature. Has the `cli`
  plugin (to run `tmux capture-pane` / `send-keys`) and `file_edit` (to write the
  chapter). It *observes and orchestrates* the TUI.
- **The TUI's own model** — a separate LLM running inside the TUI session under
  `tui_profile`. The documenter cannot see or call its tools; it can only send
  user input via `tmux send-keys` and observe the result via `capture-pane`.

When a feature's `goal` references something the TUI's model does, the documenter's
job is to *elicit that behavior with prompts and document what it observes* — not to
perform it itself.

### Control flow (`harness/walker.py`)

1. `IPCRecoveryClient` (top-level `from jaato_sdk import …`) connects to the daemon
   over the socket — the recoverable client because the walk is a long-lived driver
   (auto-reconnect + `auto_start`). Event classes still come from `jaato_sdk.events`.
2. The TUI is launched **once** in a tmux pane (`TmuxDriver`) and lives for the whole
   run — it is the *subject* of documentation. Between features the walker sends the
   TUI's `clear` command to zero conversation history without restarting the process.
   If the previous documenter killed the TUI, `_clear_tui` times out and relaunches.
3. Per feature: `client.create_session(profile="documenter", agent="documenter",
   agent_params={feature_id, feature_title, feature_goal, context_hints, tmux_pane})`,
   then a kickoff `send_message` starts the agent's turn loop.
4. `_wait_for_completion` blocks on the SDK event stream until a terminal event for
   the `documenter` agent (`AgentCompletedEvent`, error status, session-terminated,
   non-recoverable error, 5 consecutive recoverable errors, or timeout). Every
   termination path is surfaced — none hang silently.
5. A reactor records an audit sidecar; the chapter `.md` was written directly by the
   agent.

### How config reaches the agent (`.jaato/`)

This is jaato-SDK configuration, not harness Python — the LLM-facing behavior lives
here:

- `agents/documenter.md` — the documenter **persona** (system prompt). Ends with
  `{{!py:scripts/...}}` placeholders that inject runtime content.
- `scripts/prefetch_documenter_brief.py` — a **prefetch**: reads `agent_params` from
  the render context and injects the per-feature "Feature brief" block into the
  persona. `agent_params` are *not* auto-interpolated as `{{var}}` — a prefetch
  script is the supported path to surface them. Other prefetches inject the manual
  TOC, the prior chapter version, and the peer-review text.
- `scripts/reactors/render_manual_section.py` — wired in `reactors.json` to fire on
  `agent.completed` for `documenter` (and the legacy `manual_writer`). Writes
  `manual/.payloads/<feature_id>.json` from the agent's typed completion payload and
  **clears `peer_review` on every write** (that field reset is what terminates the
  feedback loop).
- `profiles/*.yaml` — `documenter.yaml` (the agent), `tiered_test.yaml` (the TUI
  subject, with `defaultPolicy: ask` so permission prompts surface for documentation).
- `completion_schemas/manual_writer.json` — the typed payload the agent must emit.

### Peer-review feedback loop

Iterating on a chapter is a **JSON edit + re-run**, gated by the sidecar:

| `manual/.payloads/<id>.json` state | Walker behavior |
|---|---|
| missing | cold-start — generate the chapter |
| exists, `peer_review` empty | skip (already accepted) |
| exists, `peer_review` filled | re-spawn documenter to address the feedback |

Fill `peer_review` with prose feedback, re-run `python -m harness walk`; only that
feature re-triggers, the agent revises via `updateFile`, and the reactor clears the
field again. A critique LLM can populate the field programmatically — nothing is
human-only.

## Validating `.jaato/` assets against the framework

`jaato-scaffold` introspects the **installed** framework and is the source of truth
for current profile/agent patterns. Run it from the daemon's venv:

```bash
JAATO=../jaato
PYTHONPATH=$JAATO/jaato-server /tmp/jaato-test/bin/python -m shared.scaffold <verb> …
#   explain  — interrogate the framework (explain plugins | profile | tiers | prefetch | env | paths)
#   validate — check assets        (validate .  → workspace; --profile <name> to scope)
#   new      — scaffold an asset    (new client --recoverable | cascade | observer | …)
```

Conventions this repo follows (all current per `explain profile`):

- **`plugins:` not `tools:`** — `tools:` is the deprecated alias.
- **Agents, not `system_instructions:`** — persona text lives in `.jaato/agents/<name>.md`
  (shared base text in `.jaato/instructions/`); profiles carry runtime config only and
  reference the agent by name (the walker passes `agent="documenter"`).
- **Provider knobs under `plugin_configs.<provider>.api_params:`** — flat keys are
  deprecation-warned.
- **`model_tiers` over per-profile `model:`** — `tiered_test` is tiers-based; the
  `initial:` control key sets the starting tier. Top-level `model:` is silently ignored
  when `model_tiers` is non-empty, so it is omitted.
- **Reactors are workspace-local opt-in** — `.jaato/reactors.json` + `.jaato/scripts/`;
  never force-installed to `~/.jaato` (which is daemon-global/shared).

**Scope gotcha:** `validate <target>` discovers profiles from the **daemon-global**
`~/.jaato/profiles/` registry, *not* only from the target path. So `validate .` reports
on profiles that aren't in this repo (e.g. `gen-references`, `skill-*`). To check only
this repo's profiles, use `--profile documenter|manual_writer|tiered_test`. Errors
outside this workspace (e.g. a retired `flow_tools` plugin in a global premium profile)
are **not** this repo's to fix.

## Source-of-truth notes (docs that have drifted)

When prose disagrees with code/config, trust the code/config:

- **Models:** the README quickstart mentions `claude-haiku-4.5`, but the live profiles
  (`tiered_test.yaml`, `documenter.yaml`, `manual_writer.yaml`) run
  `openai/gpt-oss-20b:free` via `openrouter`. The YAML is authoritative.
- **TUI reset command:** the walker sends `clear` (see `_clear_tui`), not `reset` as
  some comments/`../jaato/CLAUDE.md` claim.
- **Validator gap (`missing_model`):** `jaato-scaffold validate` warns `missing_model`
  for a tiers-based profile that sets `provider:` but no top-level `model:`, because the
  check (`validate.py:86`) doesn't treat a non-empty `model_tiers` as satisfying the
  model requirement. It's a benign warning, not an error — `tiered_test` is correctly
  tiers-driven.

## What is and isn't committed

`.jaato/` is committed *selectively*: personas, profiles, scripts, schemas, and
`reactors.json` are source; `sessions/`, `logs/`, `cache/`, `templates/`, and
`*_auth.json` are gitignored runtime/leak artifacts (see `.gitignore` for the
template cross-tenant-leak note). In `manual/`, only numeric-prefixed hand-written
chapters (`00-`, `05-`) are source; `20-walkthrough-*.md` and `.payloads/` are
generated. `build/*.md` is regenerated, but `build/*.pdf` is committed so reviewers
can read the manual without rebuilding.

## Adding a feature

Append an entry (`id` / `title` / `goal` / optional `context_hints`) to
`harness/manifest.yaml` and re-run `python -m harness walk`. The walker spawns a
documenter that explores the TUI and writes `manual/20-walkthrough-<id>.md`. The
`goal` is the agent's authoritative brief — be specific about which UI surface to
document. Hand-written prose chapters use numeric prefixes so they sort with the
`20-` walkthroughs; pick a prefix for the desired position.
