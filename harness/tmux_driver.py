"""Tmux pane driver — send-keys, capture-pane, polling waits.

Always-fresh-window-per-run policy (per design): the harness creates a
dedicated window on entry and kills it on exit.  No stale state from
prior runs; concurrent harness invocations don't collide because each
gets its own window.

Use as a context manager for guaranteed teardown:

    with TmuxDriver() as drv:
        drv.send("ls")
        drv.wait_for("$ ")
        out = drv.capture()
"""
import subprocess
import time
from typing import Optional


class TmuxDriver:
    """Wrap a single tmux window lifecycle + send/capture/wait operations."""

    def __init__(self, window_name: str = "tui-manual-build"):
        self._window_name = window_name
        self._target: Optional[str] = None

    def __enter__(self) -> "TmuxDriver":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        """Create a fresh tmux window in the current session.

        Returns the target identifier (``session:window`` form) for
        subsequent ``-t`` flags.  Requires the harness to be invoked
        from inside a tmux session — checks ``$TMUX`` indirectly by
        letting tmux's ``new-window`` fail loudly if it can't find one.
        """
        out = subprocess.check_output(
            [
                "tmux", "new-window", "-d", "-P",
                "-F", "#{session_name}:#{window_index}",
                "-n", self._window_name,
            ],
            text=True,
        ).strip()
        self._target = out

    def close(self) -> None:
        """Kill the tmux window.  Idempotent (no-op if already closed)."""
        if self._target:
            subprocess.run(
                ["tmux", "kill-window", "-t", self._target],
                check=False,
            )
            self._target = None

    @property
    def target(self) -> str:
        if not self._target:
            raise RuntimeError("TmuxDriver: open() not called or already closed")
        return self._target

    # ------------------------------------------------------------------
    # send / capture / wait primitives
    # ------------------------------------------------------------------

    def send(self, keys: str) -> None:
        """Send keystrokes to the pane.

        Heuristic: known special-key tokens (``C-b``, ``Enter``,
        ``Escape``, ``Tab``, etc.) are sent directly.  Anything else is
        treated as literal text and uses the two-step pattern (text
        first, sleep 1, then ``Enter``) to dodge the TUI's paste-block
        placeholder swallow on multi-character input.

        For non-text inputs that aren't single special keys (e.g. arrow
        sequences), call ``send_raw`` instead.
        """
        if self._is_special_key(keys):
            self._send_raw(keys)
        else:
            # Literal text: text → sleep → Enter
            self._send_raw(keys)
            time.sleep(1)
            self._send_raw("Enter")

    def send_raw(self, *keys: str) -> None:
        """Pass-through to ``tmux send-keys`` with no two-step or sleep."""
        for k in keys:
            self._send_raw(k)

    def _send_raw(self, key: str) -> None:
        subprocess.run(
            ["tmux", "send-keys", "-t", self.target, key],
            check=True,
        )

    @staticmethod
    def _is_special_key(s: str) -> bool:
        # Single special-key tokens tmux understands directly.
        special = {
            "Enter", "Escape", "Tab", "BSpace", "BTab",
            "Up", "Down", "Left", "Right",
            "Home", "End", "PageUp", "PageDown",
            "DC", "IC", "Space",
        }
        if s in special:
            return True
        # Modifier-prefixed: "C-x", "M-x", "S-Tab", etc.
        if len(s) <= 6 and (s.startswith("C-") or s.startswith("M-") or s.startswith("S-")):
            return True
        return False

    def capture(self, history: int = 0) -> str:
        """Capture pane content as plain text.

        Args:
            history: Lines of scrollback to include before the visible
                portion.  ``0`` (default) = visible only.  For features
                that scroll past the visible window pass e.g. ``200``.
        """
        cmd = ["tmux", "capture-pane", "-t", self.target, "-p"]
        if history > 0:
            cmd.extend(["-S", f"-{history}"])
        return subprocess.check_output(cmd, text=True)

    def wait_for(
        self, anchor: str, timeout: float = 30.0, poll: float = 0.5,
    ) -> bool:
        """Poll capture-pane until ``anchor`` appears in the visible content.

        Returns True on hit, False on timeout.  ``poll`` is the interval
        between captures; tune lower (e.g. 0.2) for fast-rendering
        features, higher (e.g. 1.0) for prefetch-heavy launch.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if anchor in self.capture():
                return True
            time.sleep(poll)
        return False
