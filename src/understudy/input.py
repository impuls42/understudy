"""Compositor input: click, move, type, key, scroll.

Implements via wlrctl over zwlr_virtual_pointer_v1 / zwlr_virtual_keyboard_v1.
These are wlroots-specific protocols not shipped by pywayland; wlrctl is the
stable CLI interface to them. This module wraps wlrctl with proper error
handling and env injection so callers never spawn raw subprocesses.

Note (see plan §fallback policy): if pywayland gains the wlr protocol XML
files, the subprocess calls here should be replaced with a persistent
pywayland client connection. The public API is unchanged either way.
"""

from __future__ import annotations

import subprocess
import time

from ._runtime import wayland_env
from .errors import ExternalCommandError, PreconditionError


def _wlrctl(*args: str) -> None:
    env = wayland_env()
    result = subprocess.run(["wlrctl", *args], env=env, capture_output=True)
    if result.returncode != 0:
        msg = result.stderr.decode().strip() or result.stdout.decode().strip()
        raise ExternalCommandError(
            f"wlrctl {' '.join(args)!r} failed: {msg}",
            hint="Is the headless stack running? Try `us stack up`.",
        )


class Compositor:
    """Input driver for the headless sway session.

    All coordinates are absolute pixels within the 1920×1080 HEADLESS-1 output.
    """

    def move(self, x: int, y: int) -> None:
        """Move the virtual pointer to absolute position (x, y)."""
        _wlrctl("pointer", "move", str(x), str(y))

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        delay: float = 0.05,
    ) -> None:
        """Move to (x, y) then press and release *button*.

        *delay* seconds are inserted between move and click so the target
        window has time to process the hover before receiving the click.
        """
        self.move(x, y)
        time.sleep(delay)
        _wlrctl("pointer", "click", button)

    def scroll(self, dx: float = 0.0, dy: float = 0.0) -> None:
        """Scroll horizontally by *dx* and vertically by *dy* (positive = down/right)."""
        if dy:
            axis = "vertical"
            _wlrctl("pointer", "scroll", axis, str(dy))
        if dx:
            axis = "horizontal"
            _wlrctl("pointer", "scroll", axis, str(dx))

    def type(self, text: str) -> None:
        """Type a string of characters via the virtual keyboard."""
        _wlrctl("keyboard", "type", text)

    def key(self, keysym: str) -> None:
        """Press and release a single key by its XKB keysym name (e.g. 'Return', 'Escape')."""
        _wlrctl("keyboard", "key", keysym)
