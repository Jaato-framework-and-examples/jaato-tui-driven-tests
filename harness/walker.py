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
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from jaato_sdk.client.ipc import IPCClient
from jaato_sdk.events import AgentCompletedEvent, ClientType, ErrorEvent

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

    async def _run_async(self) -> None:
        client = IPCClient(
            socket_path=self._socket,
            workspace_path=str(WORKSPACE),
            env_file=".env",
            auto_start=False,
            client_type=ClientType.API,
        )
        if not await client.connect():
            raise RuntimeError(
                f"could not connect to daemon at {self._socket} — "
                "is the daemon running?"
            )

        try:
            with TmuxDriver(window_name="tui-manual-build") as drv:
                tmux_pane = drv.target
                tui_profile = self._manifest.get("tui_profile", "tiered_test")

                # Single TUI lifecycle for the whole run.  The TUI is
                # launched ONCE with --new-session so its conversation
                # starts empty.  Between features the walker types the
                # TUI's `reset` command to clear conversation history
                # without restarting the TUI process — keeps the visible
                # pane stable, no open/close churn, but each feature's
                # documenter sees a clean slate when it inspects the
                # TUI scene.
                self._launch_tui(drv, profile=tui_profile)
                try:
                    features = self._manifest.get("features", [])
                    for index, feature in enumerate(features):
                        if index > 0:
                            self._reset_tui(drv, tui_profile)
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
                await client.disconnect()
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

    def _reset_tui(self, drv: TmuxDriver, tui_profile: str) -> None:
        """Clear the TUI's conversation history between features.

        Tries the cheap path first: send the ``reset`` command (per
        ``jaato/CLAUDE.md`` line 752 — "reset: Reset conversation
        history") and wait for the ``User>`` prompt to confirm.  Same
        TUI process, same pane, just zeroed conversation buffer.

        Resilience fallback: if the previous feature's documenter
        accidentally killed the TUI (e.g., typed `exit` and chose `e`),
        the ``reset`` command goes nowhere and ``wait_for`` times out.
        In that case, relaunch the TUI fresh — the run still
        finishes, we just lose the in-pane reset shortcut.
        """
        drv.send("reset")
        if drv.wait_for("User>", timeout=10):
            time.sleep(0.5)
            return

        # Reset failed → TUI is likely dead.  Relaunch.
        print(
            "\n    ! TUI didn't return to User> after reset — "
            "relaunching", end="", flush=True,
        )
        try:
            self._launch_tui(drv, profile=tui_profile)
        except Exception as exc:
            raise RuntimeError(
                f"TUI relaunch failed after reset timeout: {exc}"
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
        reset by the run loop's ``_reset_tui`` call before this feature
        starts.  The documenter session is fresh (created here per
        feature).  When done, the run loop will reset the TUI before
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

        try:
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
                timeout=60.0,
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

        completed = await self._wait_for_completion(client)
        if completed:
            print("✓")
        else:
            print("FAIL (no AgentCompletedEvent before timeout)")

    async def _wait_for_completion(
        self, client: IPCClient, timeout: float = 600.0,
    ) -> bool:
        """Block until the documenter's ``AgentCompletedEvent`` arrives.

        Filters by ``agent_id == 'documenter'``.  Sequential
        per-feature spawning means at most one documenter is in
        flight, so the agent_id is unambiguous.

        Timeout is generous (10 minutes) because the documenter
        may iterate through several capture-pane / send-keys cycles
        for multi-state features (tier switching with multiple turns,
        for example).
        """
        async def _inner() -> bool:
            async for event in client.events():
                if (
                    isinstance(event, AgentCompletedEvent)
                    and event.agent_id == "documenter"
                ):
                    return True
                if isinstance(event, ErrorEvent) and not event.recoverable:
                    print(
                        f"\n    ! ErrorEvent: {event.error}",
                        end="", flush=True,
                    )
                    return False
            return False

        try:
            return await asyncio.wait_for(_inner(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
