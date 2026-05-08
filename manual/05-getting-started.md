# Getting started — running the TUI

The TUI is launched with the `jaato` command.  The daemon (the
"server") is launched with `jaato-server`.  Both come from the
`jaato-tui` and `jaato-server` packages respectively; once the project's
virtualenv is activated, both commands are on `PATH` — there is no need
to invoke `python -m server` or `python rich_client.py` manually.

## First run — auto-start

The simplest way to start a session is:

```
$ jaato
```

If no daemon is listening on the default IPC socket
(`/tmp/jaato.sock`), the TUI **spawns one in the background** and
connects to it.  The default config directory is `.jaato/` in the
current working directory; if that directory does not exist, the TUI
will exit and ask you to scaffold it first:

```
$ jaato --init
```

`--init` writes a starter `.jaato/` next to the current directory with
example agents, profiles, references, and an `.env` template.  Edit
those files, then re-run `jaato`.

## Reconnecting to an existing session

Re-running `jaato` on a workspace where the daemon is already listening
on `/tmp/jaato.sock` will **resume the default session** — the same
conversation history, todos, plan, and budget you had in the previous
TUI window.  This is the expected behaviour when you close the TUI
(Ctrl+D) and come back later: the daemon stays alive in the background
and your context is waiting for you.

If you want to start fresh without losing the prior session, pass
`--new-session`:

```
$ jaato --new-session
```

The default session is left intact on the daemon — you can switch back
to it later from the TUI's session-management commands.

## Connecting to a specific socket

The default IPC socket path is `/tmp/jaato.sock`.  If you run the
daemon on a different socket (for example to isolate workspaces or to
run multiple daemons side-by-side), point the TUI at it explicitly:

```
$ jaato --connect /tmp/scratch.sock
```

When `--connect` is set, auto-start is disabled by default for any
non-default path — the TUI assumes you already have the daemon running
where you want it.  Use `--no-auto-start` to opt out of auto-start
unconditionally.

## Running the daemon by hand

For most users, auto-start is sufficient.  The cases where you want to
run the daemon manually are:

- You want the daemon to outlive the TUI window (so reconnects are
  fast, even after a system reboot of the TUI's terminal multiplexer
  process).
- You want to expose the daemon over WebSocket so a remote client can
  connect.
- You want to inspect the daemon's logs in real time (`/tmp/jaato.log`
  rotates by default; the foreground daemon prints directly to its
  terminal).

Run the daemon manually with:

```
$ jaato-server --ipc-socket /tmp/jaato.sock --daemon
```

To also expose a WebSocket endpoint:

```
$ jaato-server --ipc-socket /tmp/jaato.sock --web-socket :8080 --daemon
```

The `--daemon` flag detaches the server from the current terminal.
Without it the daemon runs in the foreground (useful for tailing logs).

## Checking + stopping the daemon

```
$ jaato-server --status     # show pid, sockets, uptime
$ jaato-server --stop       # send graceful shutdown
```

## Selecting a profile or agent at startup

Sessions can be created with a runtime **profile** (model + plugins +
GC) or an **agent** (parameterized prompt + persona).  Both are read
from `.jaato/profiles/` and `.jaato/agents/` respectively.  At startup,
pass either or both:

```
$ jaato --profile researcher --agent code-explainer
```

`--new-session` is implied when `--profile` or `--agent` is set —
profiles and agents only apply to fresh sessions.  Existing sessions
keep the profile they were created with.

## A non-interactive one-shot

For scripting or piping output into another tool, ask the TUI for a
single response and exit:

```
$ jaato --prompt "What changed in the latest commit?"
```

The TUI runs the prompt against the default session, prints the
response, and exits.  Auto-start still applies — this is a useful
pattern for CI hooks and editor integrations that don't want a
persistent terminal.

If you want to seed the session with an opening prompt but **stay
interactive** afterwards, use `--initial-prompt` (`-i`) instead.
