"""Compositor input: click, move, type, key, scroll.

Two input paths:
1. **wlrctl** (Wayland): sends virtual pointer/keyboard events to sway.
   Works for native Wayland surfaces. Does NOT reliably reach Wine/Proton
   games running inside gamescope (they use X11/Xwayland internally).

2. **xdotool** (X11): sends events directly to the gamescope Xwayland display
   (e.g. ':3'). Reliably reaches Wine/Proton game windows and Steam overlay.
   Used automatically when a gamescope session is active.

`Compositor.click()` and friends auto-select the best path.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from ._runtime import wayland_env
from .errors import ExternalCommandError, PreconditionError


# ---------------------------------------------------------------------------
# wlrctl helpers (Wayland path)
# ---------------------------------------------------------------------------

def _wlrctl(*args: str) -> None:
    env = wayland_env()
    result = subprocess.run(["wlrctl", *args], env=env, capture_output=True)
    if result.returncode != 0:
        msg = result.stderr.decode().strip() or result.stdout.decode().strip()
        raise ExternalCommandError(
            f"wlrctl {' '.join(args)!r} failed: {msg}",
            hint="Is the headless stack running? Try `us stack up`.",
        )


# ---------------------------------------------------------------------------
# xdotool helpers (X11 / gamescope path)
# ---------------------------------------------------------------------------

def _gamescope_xdisplay() -> str | None:
    """Return the X display number (e.g. ':3') of gamescope's Xwayland, or None."""
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,ppid,args"],
            text=True, stderr=subprocess.DEVNULL,
        )
        gamescope_pids: set[str] = set()
        xwayland_entries: list[tuple[str, str, str]] = []  # (pid, ppid, display)

        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            pid, ppid, args = parts
            if "gamescope" in args and "Xwayland" not in args:
                gamescope_pids.add(pid)
            m = re.search(r"Xwayland\s+(:\d+)", args)
            if m:
                xwayland_entries.append((pid, ppid, m.group(1)))

        # Find Xwayland whose parent is a gamescope process
        for pid, ppid, display in xwayland_entries:
            if ppid in gamescope_pids and display != ":0":
                return display
        # Fallback: any Xwayland that's not :0
        for pid, ppid, display in xwayland_entries:
            if display != ":0":
                return display
    except Exception:
        pass
    return None


def _game_window_id(xdisplay: str) -> str | None:
    """Return the hex window ID of the main game window on *xdisplay*.

    Prefers windows with WM_CLASS 'steam_app_*' (the actual game) over
    'steamwebhelper' (the Steam overlay), then picks the largest one.
    """
    try:
        out = subprocess.check_output(
            ["xwininfo", "-root", "-tree"],
            env={**os.environ, "DISPLAY": xdisplay},
            text=True, stderr=subprocess.DEVNULL,
        )
        game_wid = None
        fallback_wid = None
        best_game_area = 0
        best_fallback_area = 0
        for line in out.splitlines():
            m = re.match(r'\s+(0x[0-9a-f]+)\s+"[^"]*":\s+\("([^"]*)"', line)
            if not m:
                continue
            wid, wm_class = m.group(1), m.group(2)
            sz = re.search(r"(\d+)x(\d+)\+0\+0", line)
            if not sz:
                continue
            area = int(sz.group(1)) * int(sz.group(2))
            if wm_class.startswith("steam_app_"):
                if area > best_game_area:
                    best_game_area = area
                    game_wid = wid
            elif area > best_fallback_area:
                best_fallback_area = area
                fallback_wid = wid
        return game_wid or fallback_wid
    except Exception:
        return None


def _xdotool_click(x: int, y: int, button: str = "left",
                   xdisplay: str | None = None) -> None:
    display = xdisplay or _gamescope_xdisplay()
    if display is None:
        raise ExternalCommandError(
            "No gamescope Xwayland display found.",
            hint="Launch a game first with `us game launch`.",
        )
    win = _game_window_id(display)
    env = {**os.environ, "DISPLAY": display}
    cmds = [["xdotool", "mousemove", str(x), str(y)]]
    if win:
        cmds.insert(0, ["xdotool", "windowfocus", win])
    cmds.append(["xdotool", "click", "--clearmodifiers", "1" if button == "left" else "3"])
    for cmd in cmds:
        r = subprocess.run(cmd, env=env, capture_output=True)
        if r.returncode != 0:
            err = r.stderr.decode().strip() or r.stdout.decode().strip()
            raise ExternalCommandError(f"xdotool failed: {err}")


def _xdotool_key(keysym: str, xdisplay: str | None = None) -> None:
    display = xdisplay or _gamescope_xdisplay()
    if display is None:
        raise ExternalCommandError("No gamescope Xwayland display found.")
    env = {**os.environ, "DISPLAY": display}
    r = subprocess.run(["xdotool", "key", "--clearmodifiers", keysym],
                       env=env, capture_output=True)
    if r.returncode != 0:
        raise ExternalCommandError(f"xdotool key failed: {r.stderr.decode().strip()}")


def _xdotool_type(text: str, xdisplay: str | None = None) -> None:
    display = xdisplay or _gamescope_xdisplay()
    if display is None:
        raise ExternalCommandError("No gamescope Xwayland display found.")
    env = {**os.environ, "DISPLAY": display}
    r = subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text],
                       env=env, capture_output=True)
    if r.returncode != 0:
        raise ExternalCommandError(f"xdotool type failed: {r.stderr.decode().strip()}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class Compositor:
    """Input driver for the headless sway session.

    All coordinates are absolute pixels within the 1920×1080 HEADLESS-1 output.

    Uses xdotool (X11) when a gamescope session is active (reliable for Wine/
    Proton games and Steam overlay), falling back to wlrctl (Wayland) otherwise.
    """

    def _use_xdotool(self) -> bool:
        return _gamescope_xdisplay() is not None

    def move(self, x: int, y: int) -> None:
        """Move the virtual pointer to absolute position (x, y)."""
        if self._use_xdotool():
            display = _gamescope_xdisplay()
            env = {**os.environ, "DISPLAY": display}
            subprocess.run(["xdotool", "mousemove", str(x), str(y)],
                           env=env, capture_output=True)
        else:
            _wlrctl("pointer", "move", str(x), str(y))

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        delay: float = 0.05,
    ) -> None:
        """Move to (x, y) then press and release *button*."""
        if self._use_xdotool():
            self.move(x, y)
            time.sleep(delay)
            _xdotool_click(x, y, button)
        else:
            self.move(x, y)
            time.sleep(delay)
            _wlrctl("pointer", "click", button)

    def scroll(self, dx: float = 0.0, dy: float = 0.0) -> None:
        """Scroll horizontally by *dx* and vertically by *dy* (positive = down/right)."""
        if dy:
            _wlrctl("pointer", "scroll", "vertical", str(dy))
        if dx:
            _wlrctl("pointer", "scroll", "horizontal", str(dx))

    def type(self, text: str) -> None:
        """Type a string of characters."""
        if self._use_xdotool():
            _xdotool_type(text)
        else:
            _wlrctl("keyboard", "type", text)

    def key(self, keysym: str) -> None:
        """Press and release a single key by its XKB keysym name (e.g. 'Return', 'Escape')."""
        if self._use_xdotool():
            _xdotool_key(keysym)
        else:
            _wlrctl("keyboard", "type", keysym)
