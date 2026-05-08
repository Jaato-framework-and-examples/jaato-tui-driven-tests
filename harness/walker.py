"""Drive the TUI through every feature in the manifest.

The walker is the deterministic half of the cascade.  Per feature:

1. Drive the TUI through the manifest's ``pre_setup`` + ``trigger`` steps
   via ``tmux send-keys`` / ``tmux capture-pane``.
2. Spawn a ``manual_writer`` session via the SDK with the captured scene
   as the initial prompt.  Pass ``feature_id`` and ``feature_title`` as
   ``agent_params``.
3. Wait for the session's ``AgentCompletedEvent``.  The reactor rule
   ``manual_writer-render-section`` (in ``.jaato/reactors.json``) then
   renders ``manual/20-walkthrough-<feature_id>.md`` from the typed
   payload.
4. Run the manifest's ``cleanup`` steps to return the TUI to baseline.

The walker does NOT write the .md files — that's the reactor's job.  The
walker's only outputs are: tmux scene captures (transient, in-memory)
and SDK calls (persistent via the daemon's session journal).
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from jaato_sdk.client.ipc import IPCClient
from jaato_sdk.events import AgentCompletedEvent, ClientType, ErrorEvent

from .tmux_driver import TmuxDriver

WORKSPACE = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"
REPO_ROOT = WORKSPACE.parent / "jaato"


def _crop(capture: str, anchors: Optional[Dict[str, str]]) -> str:
    """Trim a capture to the region between optional regex anchors."""
    if not anchors:
        return capture
    lines = capture.splitlines()
    start = 0
    end = len(lines)
    if "from_line_matching" in anchors:
        rx = re.compile(anchors["from_line_matching"])
        for i, line in enumerate(lines):
            if rx.search(line):
                start = i
                break
    if "to_line_matching" in anchors:
        rx = re.compile(anchors["to_line_matching"])
        for i, line in enumerate(lines[start:], start=start):
            if rx.search(line):
                end = i + 1
                break
    return "\n".join(lines[start:end])


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
            # Headless harness: declare API so the server-side
            # interactive-root filter (0.6.61+) does NOT strip
            # signal_completion from manual_writer's tool surface.
            client_type=ClientType.API,
        )
        if not await client.connect():
            raise RuntimeError(
                f"could not connect to daemon at {self._socket} — "
                "is the daemon running?"
            )

        try:
            with TmuxDriver(window_name="tui-manual-build") as drv:
                self._launch_tui(drv)
                try:
                    for feature in self._manifest.get("features", []):
                        # Don't let one feature's TUI cascade-failure
                        # abort the whole run — print the failure and
                        # continue with the next feature.  The cleanup
                        # of each feature still runs in _drive_feature's
                        # own try/finally.
                        try:
                            await self._drive_feature(drv, client, feature)
                        except Exception as exc:
                            print(f"FAIL ({type(exc).__name__}: {exc})")
                finally:
                    self._exit_tui(drv)
        finally:
            # disconnect() only — never end_session() (per the
            # `feedback_no_end_session_after_agent_completed` memory).
            try:
                await client.disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # TUI lifecycle (the "scene" host)
    # ------------------------------------------------------------------

    def _launch_tui(self, drv: TmuxDriver) -> None:
        cmd = (
            f"cd {WORKSPACE} && "
            f"PYTHONPATH={REPO_ROOT}/jaato-server "
            f"/tmp/jaato-test/bin/python {REPO_ROOT}/jaato-tui/rich_client.py "
            f"--connect {self._socket} --new-session"
        )
        drv.send(cmd)
        if not drv.wait_for("User>", timeout=30):
            raise RuntimeError(
                "TUI did not reach 'User>' prompt within 30s — daemon down "
                "or auth misconfigured?"
            )
        # Brief dwell after the prompt appears to let the banner finish drawing.
        time.sleep(1)

    def _exit_tui(self, drv: TmuxDriver) -> None:
        """Clean exit — the `exit` command + 'e' menu choice."""
        drv.send("exit")
        if drv.wait_for("Exit options:", timeout=10):
            drv._send_raw("e")
            drv._send_raw("Enter")
            drv.wait_for("$", timeout=10)

    # ------------------------------------------------------------------
    # Per-feature cascade — Walker → manual_writer → reactor
    # ------------------------------------------------------------------

    async def _drive_feature(
        self, drv: TmuxDriver, client: IPCClient, feature: Dict[str, Any],
    ) -> None:
        feature_id = feature["id"]
        title = feature.get("title", feature_id)
        print(f"  · {feature_id} ...", end=" ", flush=True)

        # Step 1 — pre-acquire the manual_writer session BEFORE driving
        # the TUI.  If the daemon is overloaded and create_session times
        # out, we abort cleanly without burning TUI keystrokes (e.g.
        # without leaving the budget panel open or sending Ctrl+B that
        # the agent never gets to consume).
        try:
            session_id = await client.create_session(
                profile="manual_writer",
                agent="manual_writer",
                agent_params={
                    "feature_id": feature_id,
                    "feature_title": title,
                },
                timeout=60.0,
            )
        except Exception as exc:
            print(f"FAIL (create_session: {exc})")
            return

        if not session_id:
            print("FAIL (no session_id returned)")
            return

        # Step 2 — set the scene via tmux + run the agent.  Wrap in
        # try/finally so cleanup fires regardless of failure mode
        # (trigger hung, agent timed out, exception in send_message).
        # Without this guard, feature N+1 would inherit a TUI left in
        # feature N's scene state.
        completed = False
        try:
            for step in feature.get("pre_setup", []):
                self._do_step(drv, step)
            for step in feature.get("trigger", []):
                self._do_step(drv, step)

            capture_cfg = feature.get("capture", {}) or {}
            history = capture_cfg.get("history", 0)
            full = drv.capture(history=history)
            scene = _crop(full, capture_cfg.get("crop_anchors"))

            # Step 3 — feed the captured scene to the pre-acquired session.
            prompt = self._build_writer_prompt(feature_id, title, scene)
            await client.send_message(prompt)

            # Step 4 — wait for AgentCompletedEvent (reactor renders the .md).
            completed = await self._wait_for_completion(client)
        finally:
            # Cleanup the TUI scene regardless of outcome.
            self._run_cleanup(drv, feature)

        if completed:
            print("✓")
        else:
            print("FAIL (no AgentCompletedEvent before timeout)")

    def _build_writer_prompt(
        self, feature_id: str, title: str, scene: str,
    ) -> str:
        return (
            f"## TUI scene capture for `{feature_id}`\n\n"
            f"**Feature title:** {title}\n\n"
            "**What follows is the verbatim `tmux capture-pane` output of "
            "the TUI immediately after the trigger sequence ran.**  Treat "
            "it as ground truth.\n\n"
            "```text\n"
            f"{scene.rstrip()}\n"
            "```\n\n"
            "Produce the manual section per your persona instructions.  "
            "Exactly one tool call: `signal_completion` with the typed "
            "payload."
        )

    async def _wait_for_completion(
        self, client: IPCClient, timeout: float = 300.0,
    ) -> bool:
        """Block until manual_writer signals completion.

        Returns True on success, False on timeout / error.  Filters the
        event stream for ``AgentCompletedEvent`` with
        ``agent_id == "manual_writer"`` — the walker only ever has one
        manual_writer in flight at a time (sequential per-feature
        spawning), so the agent_id is unambiguous.

        Uses ``asyncio.wait_for`` so the timeout fires even when no
        events arrive at all (unlike a deadline check inside the event
        loop body, which only runs after each yielded event).
        """
        async def _inner() -> bool:
            async for event in client.events():
                if (
                    isinstance(event, AgentCompletedEvent)
                    and event.agent_id == "manual_writer"
                ):
                    return True
                if isinstance(event, ErrorEvent) and not event.recoverable:
                    print(f"\n    ! ErrorEvent: {event.error}", end="", flush=True)
                    return False
            return False

        try:
            return await asyncio.wait_for(_inner(), timeout=timeout)
        except asyncio.TimeoutError:
            return False

    def _run_cleanup(self, drv: TmuxDriver, feature: Dict[str, Any]) -> None:
        for step in feature.get("cleanup", []):
            try:
                self._do_step(drv, step)
            except Exception as exc:
                print(f"\n    ! cleanup step failed: {exc}", end="", flush=True)

    def _do_step(self, drv: TmuxDriver, step: Dict[str, Any]) -> None:
        if "send" in step:
            drv.send(step["send"])
        if "send_raw" in step:
            drv._send_raw(step["send_raw"])
        if "wait_for" in step:
            timeout = step.get("timeout", 30.0)
            if not drv.wait_for(step["wait_for"], timeout=timeout):
                raise RuntimeError(
                    f"wait_for {step['wait_for']!r} timed out ({timeout}s)"
                )
        if "sleep" in step:
            time.sleep(step["sleep"])
