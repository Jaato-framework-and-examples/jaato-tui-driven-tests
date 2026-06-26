"""LLM-driven harness — drive the TUI through every feature in the manifest.

Walker responsibilities:

1. Spawn the jaato TUI in a tmux pane, attached to a session created
   with ``manifest.tui_profile`` (defaults to ``tiered_test``).  The
   TUI is the SUBJECT of documentation and lives for the whole run.
2. For each feature in the manifest, spawn a ``documenter`` agent
   session via the SDK with the feature's ``goal`` /
   ``context_hints`` / ``tmux_pane`` baked into ``agent_params``.
3. Wait for the documenter's ``AgentCompletedEvent``.  The agent has
   already written the manual section to disk via ``writeNewFile`` /
   ``updateFile``; the reactor at
   ``.jaato/scripts/reactors/render_manual_section.py`` records an
   audit sidecar at ``manual/.payloads/<feature_id>.json``.
4. Exit the TUI cleanly at the end.

The walker does NOT prescribe keystrokes.  The documenter agent
observes the TUI via ``tmux capture-pane`` and decides every
interaction itself — that's the LLM-driven design (the manifest is
prefetch context, not a script).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from jaato_sdk import ClientType, IPCRecoveryClient
from jaato_sdk.events import (
    AgentCompletedEvent,
    AgentStatusChangedEvent,
    ErrorEvent,
    RetryEvent,
    SessionTerminatedEvent,
)

from .tmux_driver import TmuxDriver

WORKSPACE = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"
REPO_ROOT = WORKSPACE.parent / "jaato"


class Walker:
    def __init__(self, socket: str, manual_dir: Path):
        self._socket = socket
        self._manual_dir = manual_dir
        self._manifest = yaml.safe_load(MANIFEST_PATH.read_text())

    def run(self) -> None:
        asyncio.run(self._run_async())

    @staticmethod
    def _on_conn(status: Any) -> None:
        """Surface the recovery client's connection-state transitions.

        IPCRecoveryClient drives a DISCONNECTED→CONNECTING→CONNECTED
        state machine and auto-reconnects on connection loss (e.g. a
        per-run ``jaato-server --stop`` + autostart).  Printing each
        transition makes a mid-walk daemon restart visible in the run
        log instead of looking like a silent stall.
        """
        print(f"\n    [conn] {getattr(status, 'state', status)}", flush=True)

    async def _run_async(self) -> None:
        # IPCRecoveryClient (not plain IPCClient): the walk is a
        # long-lived driver (minutes, one documenter session per feature,
        # retry storms) — the SDK's recommended client for anything
        # long-lived.  auto_start=True removes the "daemon must already be
        # running" precondition; the recovery state machine rides through
        # a daemon restart and reattaches.  (The separately-launched TUI
        # is a distinct process: if the daemon restarts mid-feature the
        # TUI dies, but the run loop's _clear_tui already relaunches a
        # dead TUI before the next feature, so the two resiliencies
        # compose.)
        client = IPCRecoveryClient(
            self._socket,
            client_type=ClientType.API,
            auto_start=True,
            env_file=".env",
            workspace_path=WORKSPACE,
            on_status_change=self._on_conn,
        )
        # Cold autostart of the daemon is ~30-60s; give connect headroom.
        if not await client.connect(timeout=120.0):
            raise RuntimeError(
                f"could not connect to (or autostart) the daemon at "
                f"{self._socket} — run `python -m harness doctor` and "
                "check provider auth"
            )

        try:
            with TmuxDriver(window_name="tui-manual-build") as drv:
                tmux_pane = drv.target
                tui_profile = self._manifest.get("tui_profile", "tiered_test")

                # Single TUI lifecycle for the whole run.  The TUI is
                # launched ONCE with --new-session so its conversation
                # starts empty.  Between features the walker types the
                # TUI's `clear` command to clear conversation history
                # without restarting the TUI process — keeps the visible
                # pane stable, no open/close churn, but each feature's
                # documenter sees a clean slate when it inspects the
                # TUI scene.
                self._launch_tui(drv, profile=tui_profile)
                try:
                    features = self._manifest.get("features", [])
                    for index, feature in enumerate(features):
                        if index > 0:
                            self._clear_tui(drv, tui_profile)
                        try:
                            await self._drive_feature(
                                drv, client, feature, tmux_pane=tmux_pane,
                            )
                        except Exception as exc:
                            print(f"FAIL ({type(exc).__name__}: {exc})")
                finally:
                    self._exit_tui(drv)
        finally:
            try:
                # Terminal shutdown of the recovery client — close() marks
                # it permanently CLOSED (cancels any in-flight reconnection),
                # the right end-of-run teardown vs disconnect() which leaves
                # it reattachable.
                await client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # TUI lifecycle
    # ------------------------------------------------------------------

    def _launch_tui(self, drv: TmuxDriver, profile: str) -> None:
        """Launch the TUI with a fresh per-feature session.

        Uses ``--new-session --profile <name>`` so the TUI creates its
        OWN fresh session every time it starts.  We do NOT pass
        ``--session <id>`` (which is documented as a one-shot command
        target requiring ``--cmd``, NOT an interactive attach flag —
        without ``--cmd`` it falls back to resuming the default session,
        which carries content from previous runs and breaks the
        per-feature isolation we want).

        The walker doesn't need to know the TUI's session_id — the
        documenter drives the TUI via tmux ``send-keys`` regardless of
        which session_id the TUI is on.
        """
        cmd = (
            f"cd {WORKSPACE} && "
            f"PYTHONPATH={REPO_ROOT}/jaato-server "
            f"/tmp/jaato-test/bin/python {REPO_ROOT}/jaato-tui/rich_client.py "
            f"--connect {self._socket} --new-session --profile {profile}"
        )
        drv.send(cmd)
        if not drv.wait_for("User>", timeout=30):
            raise RuntimeError(
                "TUI did not reach 'User>' prompt within 30s — daemon "
                "down or auth misconfigured?"
            )
        # Brief dwell so the banner finishes drawing before the
        # documenter observes.
        time.sleep(1)

    def _clear_tui(self, drv: TmuxDriver, tui_profile: str) -> None:
        """Clear the TUI's conversation history between features.

        Tries the cheap path first: send the ``clear`` slash command
        (the rich_client TUI's actual conversation-reset command — note
        that ``jaato/CLAUDE.md`` says ``reset`` but the live TUI accepts
        ``clear``; the CLAUDE.md text is stale) and wait for the
        ``User>`` prompt to confirm.  Same TUI process, same pane, just
        zeroed conversation buffer.

        Resilience fallback: if the previous feature's documenter
        accidentally killed the TUI (e.g., typed `exit` and chose `e`),
        the ``clear`` command goes nowhere and ``wait_for`` times out.
        In that case, relaunch the TUI fresh — the run still
        finishes, we just lose the in-pane clear shortcut.
        """
        drv.send("clear")
        if drv.wait_for("User>", timeout=10):
            time.sleep(0.5)
            return

        # Clear failed → TUI is likely dead.  Relaunch.
        print(
            "\n    ! TUI didn't return to User> after clear — "
            "relaunching", end="", flush=True,
        )
        try:
            self._launch_tui(drv, profile=tui_profile)
        except Exception as exc:
            raise RuntimeError(
                f"TUI relaunch failed after clear timeout: {exc}"
            )

    def _exit_tui(self, drv: TmuxDriver) -> None:
        """End the TUI session via the ``exit`` command + ``e`` choice.

        Cleanly terminates the TUI process AND the daemon-side
        session.  Walker doesn't need to detach explicitly — the
        ``e`` choice ends the session, the TUI exits.

        Resilient: if the TUI is already dead (window gone), tmux
        commands raise CalledProcessError; we swallow them.  The
        TmuxDriver's ``__exit__`` will kill the (potentially-dead)
        window cleanly afterward.
        """
        try:
            drv.send("exit")
            if drv.wait_for("Choice [", timeout=10):
                drv._send_raw("e")
                drv._send_raw("Enter")
                drv.wait_for("$", timeout=10)
        except Exception:
            # TUI already gone — nothing to exit.
            return

    # ------------------------------------------------------------------
    # Per-feature documenter spawn
    # ------------------------------------------------------------------

    async def _drive_feature(
        self,
        drv: TmuxDriver,
        client: IPCClient,
        feature: Dict[str, Any],
        tmux_pane: str,
    ) -> None:
        """Run one feature: spawn documenter, send kickoff, await completion.

        The TUI is shared across features — its conversation has been
        clear by the run loop's ``_clear_tui`` call before this feature
        starts.  The documenter session is fresh (created here per
        feature).  When done, the run loop will clear the TUI before
        the next feature.
        """
        feature_id = feature["id"]
        title = feature.get("title", feature_id)
        goal = feature.get("goal", "")
        context_hints = feature.get("context_hints", "")

        print(f"  · {feature_id} ...", end=" ", flush=True)

        if not goal:
            print("FAIL (feature missing 'goal:' field)")
            return

        # Peer-review gate (server 0.6.71+ workflow):
        #
        # * No sidecar exists  → cold-start; spawn the documenter.
        # * Sidecar exists with empty `peer_review` → previous chapter
        #   was accepted; skip (no feedback to act on).
        # * Sidecar exists with non-empty `peer_review` → operator (or
        #   peer LLM) left feedback; spawn the documenter so it can
        #   address the review.  The reactor will clear the field on
        #   write so the loop clears.
        sidecar = self._manual_dir / ".payloads" / f"{feature_id}.json"
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            review = (data.get("peer_review") or "").strip()
            if not review:
                print("(skip — no peer_review feedback)")
                return

        try:
            # No `timeout=` kwarg: IPCRecoveryClient.create_session() doesn't
            # accept one (unlike the plain IPCClient) — connection timing is
            # governed by the recovery config + connect(timeout=).
            doc_session_id = await client.create_session(
                profile="documenter",
                agent="documenter",
                agent_params={
                    "feature_id": feature_id,
                    "feature_title": title,
                    "feature_goal": goal,
                    "context_hints": context_hints,
                    "tmux_pane": tmux_pane,
                },
            )
        except Exception as exc:
            print(f"FAIL (documenter create_session: {exc})")
            return

        if not doc_session_id:
            print("FAIL (documenter create_session returned empty)")
            return

        # Kickoff — agent_params populate the persona system
        # instructions, but the agent needs a user message to start
        # its turn loop.
        kickoff = (
            f"Begin documenting feature `{feature_id}` per your "
            "persona instructions. The TUI is at the User> prompt "
            "and ready. End with `signal_completion`."
        )
        await client.send_message(kickoff)

        completed, reason = await self._wait_for_completion(client)
        if completed:
            print("✓")
        else:
            print(f"FAIL ({reason})")

    async def _wait_for_completion(
        self, client: IPCClient, timeout: float = 600.0,
    ) -> tuple[bool, str]:
        """Block until the documenter terminates one way or another.

        Returns ``(success, reason)`` where ``reason`` is a short
        human-readable string describing the outcome.  ``success`` is
        True only on a clean ``AgentCompletedEvent`` for the
        ``documenter`` agent.

        Termination paths surfaced (none of these silently hang):

        * ``AgentCompletedEvent(success=True)`` → ✓
        * ``AgentCompletedEvent(success=False)`` → FAIL with the
          carried error message
        * ``AgentStatusChangedEvent(status='error')`` for the
          documenter → FAIL with the carried error
        * ``SessionTerminatedEvent`` for the documenter session →
          FAIL with "session terminated"
        * Any ``ErrorEvent(recoverable=False)`` → FAIL
        * 5+ recoverable ``ErrorEvent`` for the same session →
          FAIL with "5 consecutive recoverable errors" (avoids
          retry-storm hangs e.g. Z.AI 1302 rate-limit mid-stream)
        * ``RetryEvent`` is logged inline so retry storms are
          visible while in progress
        * Hard timeout → FAIL
        """
        recoverable_seen = 0

        async def _inner() -> tuple[bool, str]:
            nonlocal recoverable_seen
            async for event in client.events():
                if (
                    isinstance(event, AgentCompletedEvent)
                    and event.agent_id == "documenter"
                ):
                    if event.success:
                        return True, "completed"
                    return False, (
                        f"AgentCompletedEvent(success=False) — "
                        f"{event.error or 'no error message'}"
                    )

                if (
                    isinstance(event, AgentStatusChangedEvent)
                    and event.agent_id == "documenter"
                    and event.status == "error"
                ):
                    return False, (
                        f"agent went to error status: "
                        f"{event.error or 'no error message'}"
                    )

                if isinstance(event, SessionTerminatedEvent):
                    return False, "session terminated without completion"

                if isinstance(event, ErrorEvent):
                    if not event.recoverable:
                        return False, (
                            f"non-recoverable ErrorEvent: {event.error}"
                        )
                    recoverable_seen += 1
                    print(
                        f"\n    ! recoverable error #{recoverable_seen}: "
                        f"{event.error[:200]}",
                        end="", flush=True,
                    )
                    if recoverable_seen >= 5:
                        return False, (
                            f"{recoverable_seen} consecutive recoverable "
                            f"errors — likely upstream rate-limit / "
                            f"streaming-stop class; abandoning"
                        )

                if isinstance(event, RetryEvent):
                    print(
                        f"\n    · retry {event.attempt}/"
                        f"{event.max_attempts} in {event.delay:.1f}s "
                        f"({event.error_type or 'transient'})",
                        end="", flush=True,
                    )
            return False, "event stream ended"

        try:
            return await asyncio.wait_for(_inner(), timeout=timeout)
        except asyncio.TimeoutError:
            return False, f"timeout after {timeout:.0f}s"
