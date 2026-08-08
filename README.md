# jaato-tui-driven-tests

A self-documenting harness for the **jaato** TUI client.

The harness drives the live TUI through a manifest of features, captures
each scene as a real terminal recording, asks an LLM agent to write the
chapter for it, then renders the whole manual to a PDF.  The output is
not a synthesized mockup — it's the jaato TUI documenting itself.

## Quickstart

```bash
# 1. Activate a Python env that has jaato-sdk available (typically the
#    same venv where jaato-server / jaato-tui live as editable installs;
#    in the canonical dev setup that's /tmp/jaato-test/).  Then install
#    the harness itself:
pip install -e .

# 2. Install system deps (one-shot; see `harness doctor` for the full list).
sudo apt install -y \
    tmux pandoc texlive-xetex texlive-fonts-extra \
    fonts-dejavu-core fonts-freefont-ttf

# 3. Provider credentials: copy the template and add your OpenRouter key.
cp .env.example .env
#    then edit .env and set JAATO_OPENROUTER_API_KEY=sk-or-...
#    (.env is git-ignored; the openrouter provider reads that var directly.)

# 4. Verify everything is wired.
jaato-manual doctor          # or: python -m harness doctor

# 5. Generate the manual end-to-end.
jaato-manual all             # or: python -m harness all
# → build/tui-user-manual.pdf
```

> **⚠️ Credentials & jaato-premium.** `.env` supplies
> `JAATO_OPENROUTER_API_KEY` as a plain env var. The `.env` used to set it to a
> `pass://` secret URI, but that scheme is resolved only by the private
> **jaato-premium** package — on a public checkout it fails **silently** (jaato
> logs a warning and sends the literal `pass://…` string to OpenRouter as the
> key). Use the plain-key form. If you have jaato-premium you can switch back to
> `pass://` — see `.env.example` and the
> [org-wide note](https://github.com/Jaato-framework-and-examples/.github/blob/main/profile/README.md#-providers-and-api-keys-in-these-examples--read-this-first).

## Pipeline

The harness has four phases.  Each can be run on its own; `all` chains
them in order.

| Phase | What it does | Outputs |
|-------|--------------|---------|
| `doctor` | Probe every Python + system dep, print availability table.  Exit 0 if all present, 1 otherwise. | stdout report |
| `inventory` | Walk the live framework via the SDK and emit reference catalogs (keybindings, slash commands, plugins, tools, profile knobs). | `manual/1*-catalog-*.md` |
| `walk` | Spawn the TUI under `manifest.tui_profile`; for each feature, spawn a `documenter` agent with the feature brief in `agent_params`; the agent autonomously drives the TUI via tmux and writes the manual section. | `manual/20-walkthrough-*.md`, `manual/.payloads/*.json` |
| `build` | Concatenate sections (page-break separated), render to PDF via pandoc + xelatex with full Unicode font fallback. | `build/tui-user-manual.{md,pdf}` |

`doctor` is the right command to run first when something doesn't work.

## Peer-review feedback loop

The walker only spawns the documenter for features that need it:

| Sidecar at `manual/.payloads/<id>.json` | Walker behaviour |
|------------------------------------------|------------------|
| Missing | Cold-start — spawn documenter, generate the chapter from scratch. |
| Exists, `peer_review` empty | Skip — chapter was previously generated and accepted. Re-running is a no-op. |
| Exists, `peer_review` filled | Re-spawn documenter to address the feedback.  Reactor clears `peer_review` on write so the loop terminates after one revision pass. |

This means iterating on a chapter is a **JSON edit + re-run**:

1. Read the chapter (`manual/20-walkthrough-<id>.md`); decide what
   needs improvement.
2. Edit the sidecar JSON (`manual/.payloads/<id>.json`); set
   `peer_review` to your prose feedback.  Be specific — the agent
   acts on what the field says.  Multi-line strings are fine.
3. Re-run `python -m harness walk`.  Only the feature with filled
   `peer_review` re-triggers; the others skip.
4. Inspect the revised chapter.  The reactor cleared `peer_review`
   on write — to iterate again, fill it once more.

A separate LLM (e.g. a critique pass invoked via the SDK) can
populate `peer_review` programmatically — there's no human-only
constraint on the field.

## How `walk` works

The harness is **LLM-driven**: the manifest is *prefetch context* for
an autonomous documenter agent, not a keystroke script.  Per feature:

1. Walker creates a fresh `documenter` agent session via the SDK.
2. The feature's `goal` / `context_hints` / tmux pane / feature_id /
   title are passed as `agent_params` and rendered into the agent's
   system prompt by `.jaato/scripts/prefetch_documenter_brief.py`.
3. Walker sends a kickoff message; the agent's turn loop starts.
4. The agent has the `cli` plugin — it shells out to `tmux
   capture-pane -p -t <pane>` to observe the TUI, and `tmux send-keys
   -t <pane> ...` to drive it.  It decides every keystroke.
5. The TUI's permission policy is `defaultPolicy: ask` (in the
   `tiered_test` profile) so prompts surface naturally.  The agent
   observes them via capture-pane and responds with `y` / `n` / etc.
6. When the agent has enough material, it writes the manual section
   via `writeNewFile` / `updateFile` and emits `signal_completion`.
7. A reactor records an audit sidecar at `manual/.payloads/<id>.json`.

Between features, the walker types `reset` into the TUI to clear
conversation history (no process restart — same TUI, fresh slate).
If the agent accidentally kills the TUI, the walker re-launches.

## Adding a feature

Edit `harness/manifest.yaml` and append:

```yaml
- id: my-new-feature                # snake-case; .md filename suffix
  title: "What this section is called"
  goal: >-
    Free-form English brief — what to cover in the chapter.  This is
    the documenter agent's authoritative context (passed via
    agent_params, embedded in the persona via a prefetch).
  context_hints: >-
    Optional: extra guidance when the feature is non-obvious — what
    keystrokes open it, what to look for, what NOT to capture.  The
    agent uses these as a starting point but is free to deviate based
    on what it observes.
```

Re-run `python -m harness walk` (or `all` to also rebuild the PDF).
The walker spawns a documenter agent for the new feature; the agent
explores the TUI, writes `manual/20-walkthrough-my-new-feature.md`
directly via `file_edit`, emits `signal_completion`, and a reactor
records the audit sidecar at `manual/.payloads/my-new-feature.json`.

The manifest's only top-level setting today is `tui_profile:` — the
profile the TUI runs under for the whole walker pass.  Defaults to
`tiered_test` (model_tiers + cli + file_edit + permission ask).
Override per workspace by editing the manifest.

### When the documenter struggles

The agent is autonomous but not infallible — the `documenter` profile
runs a cost-efficient model (`openai/gpt-oss-20b:free` via OpenRouter;
see `.jaato/profiles/documenter.yaml` for the authoritative value).
Symptoms to watch for:

- **Agent picks the wrong feature angle** — refine the `goal` to
  point the agent at the specific UI surface.  E.g., "Document the
  `/model` slash command" vs "Document per-turn tier switching" are
  different features even though both relate to "models".
- **Agent kills the TUI** — the persona forbids `Ctrl+D` and the
  exit-menu's `e`/`d` choices, but a confused agent may still type
  destructive sequences.  Walker auto-relaunches the TUI on
  `_reset_tui` failure between features, so the run completes; the
  failed feature's chapter may be stale.
- **Agent claims missing context** — usually a one-off; re-run.
  Confirm `agent_params` are reaching the prefetch by reading
  `.jaato/scripts/prefetch_documenter_brief.py` and adding a
  diagnostic log line.

If a feature consistently fails the LLM-driven path, you can fall
back to the older `manual_writer` flow (which expects a pre-captured
scene).  See `.jaato/agents/manual_writer.md` for that persona.

## Layout

```
jaato-tui-driven-tests/
├── harness/                ← Python package — `python -m harness <step>`
│   ├── __main__.py         CLI entry, phase dispatch, `doctor` subcommand
│   ├── deps.py             dep probes + per-phase gates
│   ├── manifest.yaml       what features to capture (extend this!)
│   ├── inventory.py        reference-catalog generator
│   ├── walker.py           single-TUI lifecycle + per-feature documenter spawn
│   ├── tmux_driver.py      send-keys / capture-pane primitives
│   └── pdf_builder.py      pandoc invocation + font fallback config
├── manual/                 ← manual sources (mix of committed + generated)
│   ├── 00-intro.md         hand-written intro (committed)
│   ├── 05-getting-started.md  hand-written setup chapter (committed)
│   ├── 20-walkthrough-*.md auto-generated by walk (gitignored)
│   └── .payloads/          audit sidecars (gitignored)
├── docs/                   ← design notes
└── build/                  ← PDF + assembled markdown (gitignored)
```

Hand-written chapters use a numeric prefix (`00-`, `05-`, ...) so they
sort alphabetically with the auto-generated walkthroughs (`20-`).
Add new prose chapters with prefixes that fit the desired position.

## Output

The final PDF is `build/tui-user-manual.pdf`.  The intermediate
concatenated markdown is `build/tui-user-manual.md` (handy for
diff-debugging the section ordering before pandoc renders).

## Troubleshooting

- **`harness doctor` shows missing deps** → install them with the apt
  line above; rerun.
- **`walk` fails with "tmux: command not found"** → `apt install tmux`.
- **`build` shows "Missing character" warnings** → install
  `fonts-freefont-ttf` (FreeMono carries the emoji codepoints DejaVu
  Sans Mono lacks).
- **Daemon not running** → the walker uses `IPCRecoveryClient` with
  `auto_start=True`, so `python -m harness walk` will start a fresh
  daemon itself (cold start ~30–60s) and reconnect if it restarts
  mid-walk.  `jaato-server --status` shows an existing one.
- **A walkthrough chapter looks wrong** → check the audit sidecar at
  `manual/.payloads/<feature-id>.json` to see the LLM's typed
  completion payload before the reactor rendered it.

## Validating `.jaato/` assets against the framework

`jaato-scaffold` introspects the **installed** framework — it's the
source of truth for current profile/agent patterns, not guesswork.
Run it from the daemon's venv:

```bash
JAATO=../jaato
PYTHONPATH=$JAATO/jaato-server /tmp/jaato-test/bin/python -m shared.scaffold validate .
# explain <scope> to interrogate the framework (plugins | profile | tiers | env | paths)
# new client --recoverable to compare harness/ against the current SDK-client scaffold
```

Patterns this workspace follows (all current): `plugins:` (not the
deprecated `tools:`); personas in `.jaato/agents/<name>.md` (not
inline `system_instructions:`); provider knobs under
`plugin_configs.<provider>.api_params:`; `model_tiers` with an
`initial:` tier (no redundant top-level `model:`); reactors kept
workspace-local in `.jaato/` (never force-installed to the shared
daemon-global `~/.jaato`).

**Scope note:** `validate .` discovers profiles from the daemon-global
`~/.jaato/profiles/` registry too, so it reports on profiles that
aren't in this repo.  Use `--profile documenter|manual_writer|tiered_test`
to check only this workspace's profiles; findings on other profiles
(global/premium) aren't this repo's to fix.

## See also

- `harness/manifest.yaml` — the feature manifest (extend to add chapters).
- `docs/` — design notes for the harness architecture.
- The jaato repo at `../jaato/` for framework internals.
