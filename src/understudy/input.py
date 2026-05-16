"""Compositor input: click, move, type, key, scroll.

Three input backends:

1. **xdotool** (X11, auto-default when gamescope is up): events injected
   directly into gamescope's nested Xwayland (`DISPLAY=:N`). Empirically the
   only path that reliably reaches Steam-launched Unity-under-Proton games on
   this stack (verified against Timberborn). Does NOT depend on
   `_NET_ACTIVE_WINDOW` (gamescope's Xwayland doesn't implement it).

2. **wlrctl** (Wayland, auto-default when no gamescope): virtual pointer/
   keyboard events to sway via wlr-virtual-pointer-unstable-v1 /
   -keyboard-unstable-v1. Sway forwards to its focused client. Reaches
   simple X11 clients inside gamescope (e.g. xeyes) but does NOT deliver
   clicks to Steam games — useful for the `us xeyes` rig.

3. **libei** (opt-in via `--backend libei`): events go directly to gamescope's
   libeis socket (`$XDG_RUNTIME_DIR/gamescope-*-ei`), bypassing sway. Cursor
   positioning works (verified against xeyes). Empirically does NOT dismiss
   Timberborn UI dialogs the way xdotool does on this stack — gamescope
   appears to route libei pointer-button events to its own seat without
   forwarding through to the nested Xwayland → Unity layer. Kept as opt-in
   for direct gamescope control and future investigation.

Override with `--backend xdotool|wlrctl|libei|auto` or `UNDERSTUDY_BACKEND=...`.
Set `UNDERSTUDY_VERBOSE=1` (or `--verbose` on `us act ...`) to log every
injected command + exit code to stderr.

== Coordinate handling ==

`wlrctl pointer move <dx> <dy>` is RELATIVE displacement, not absolute. Sway
clamps the seat cursor to output bounds, so we issue a large negative delta
first (lands at (0, 0)) then move by (x, y) for absolute positioning.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from typing import Literal

from ._runtime import wayland_env
from .errors import ExternalCommandError

Backend = Literal["xdotool", "wlrctl", "libei", "auto"]

# Larger than any reasonable display dimension; sway clamps to (0, 0).
_CLAMP_DELTA = 32768


# ---------------------------------------------------------------------------
# Verbose logging wrapper
# ---------------------------------------------------------------------------

def _verbose() -> bool:
    return os.environ.get("UNDERSTUDY_VERBOSE", "").lower() in ("1", "true", "yes")


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing output. Log to stderr when UNDERSTUDY_VERBOSE=1.

    Translates a missing binary into ExternalCommandError with an install hint.
    """
    if _verbose():
        env_prefix = ""
        if env:
            for k in ("DISPLAY", "WAYLAND_DISPLAY"):
                v = env.get(k)
                if v and v != os.environ.get(k):
                    env_prefix += f"{k}={shlex.quote(v)} "
        sys.stderr.write(f"[understudy] {env_prefix}{shlex.join(cmd)}\n")
    try:
        r = subprocess.run(cmd, env=env, capture_output=True)
    except FileNotFoundError:
        raise ExternalCommandError(
            f"{cmd[0]!r} not found in PATH.",
            hint=f"Install it (e.g. `sudo apt install {cmd[0]}`) or pick a different --backend.",
        )
    if _verbose():
        sys.stderr.write(f"[understudy]   → exit {r.returncode}\n")
    return r


# ---------------------------------------------------------------------------
# wlrctl helpers (Wayland — default)
# ---------------------------------------------------------------------------

def _wlrctl(*args: str) -> None:
    env = wayland_env()
    result = _run(["wlrctl", *args], env=env)
    if result.returncode != 0:
        msg = result.stderr.decode().strip() or result.stdout.decode().strip()
        raise ExternalCommandError(
            f"wlrctl {' '.join(args)!r} failed: {msg}",
            hint="Is the headless stack running? Try `us stack up`.",
        )


def _wlrctl_move_abs(x: int, y: int) -> None:
    """Position the seat cursor at absolute (x, y).

    `wlrctl pointer move` takes a relative delta; sway clamps the seat cursor
    to output bounds, so a large negative delta lands at (0, 0). Then move by
    (x, y) to land at the target. Two subprocess calls per absolute move.
    """
    _wlrctl("pointer", "move", str(-_CLAMP_DELTA), str(-_CLAMP_DELTA))
    if x or y:
        _wlrctl("pointer", "move", str(x), str(y))


# ---------------------------------------------------------------------------
# xdotool helpers (X11 / gamescope path — opt-in)
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

        for pid, ppid, display in xwayland_entries:
            if ppid in gamescope_pids and display != ":0":
                return display
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


def _xdotool_env(xdisplay: str | None = None) -> dict[str, str]:
    display = xdisplay or _gamescope_xdisplay()
    if display is None:
        raise ExternalCommandError(
            "xdotool backend selected but no gamescope Xwayland display found.",
            hint="Launch a game first with `us game launch`, or use the default wlrctl backend.",
        )
    return {**os.environ, "DISPLAY": display}


def _xdotool_click(x: int, y: int, button: str = "left",
                   xdisplay: str | None = None) -> None:
    env = _xdotool_env(xdisplay)
    win = _game_window_id(env["DISPLAY"])
    cmds = [["xdotool", "mousemove", str(x), str(y)]]
    if win:
        cmds.insert(0, ["xdotool", "windowfocus", win])
    cmds.append(["xdotool", "click", "--clearmodifiers", "1" if button == "left" else "3"])
    for cmd in cmds:
        r = _run(cmd, env=env)
        if r.returncode != 0:
            err = r.stderr.decode().strip() or r.stdout.decode().strip()
            raise ExternalCommandError(f"xdotool failed: {err}")


def _xdotool_key(keysym: str, xdisplay: str | None = None) -> None:
    env = _xdotool_env(xdisplay)
    r = _run(["xdotool", "key", "--clearmodifiers", keysym], env=env)
    if r.returncode != 0:
        raise ExternalCommandError(f"xdotool key failed: {r.stderr.decode().strip()}")


def _xdotool_type(text: str, xdisplay: str | None = None) -> None:
    env = _xdotool_env(xdisplay)
    r = _run(["xdotool", "type", "--clearmodifiers", "--", text], env=env)
    if r.returncode != 0:
        raise ExternalCommandError(f"xdotool type failed: {r.stderr.decode().strip()}")


def _xdotool_move(x: int, y: int, xdisplay: str | None = None) -> None:
    env = _xdotool_env(xdisplay)
    r = _run(["xdotool", "mousemove", str(x), str(y)], env=env)
    if r.returncode != 0:
        raise ExternalCommandError(f"xdotool mousemove failed: {r.stderr.decode().strip()}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_backend(backend: Backend = "auto") -> str:
    """Pick a concrete backend. Honors `UNDERSTUDY_BACKEND` env var as a fallback.

    Auto resolves to xdotool when gamescope's Xwayland is reachable (the
    common case during a game session), else wlrctl.

    Empirical finding from issue #1: on this stack, wlrctl pointer events
    delivered via sway → gamescope reach simple X11 clients (xeyes) but DO
    NOT reach Steam-launched games inside gamescope's Xwayland — Unity gets
    no events. xdotool injected directly into gamescope's Xwayland reaches
    the game. Both paths land at the requested coordinates (the wlrctl
    relative→absolute clamp is correct), it's the gamescope→game leg that
    drops wlrctl events for Steam games.
    """
    b = backend if backend != "auto" else os.environ.get("UNDERSTUDY_BACKEND", "auto")
    if b in ("xdotool", "wlrctl", "libei"):
        return b
    if _gamescope_xdisplay() is not None:
        return "xdotool"
    return "wlrctl"


def probe_sway() -> dict:
    """Cheap liveness check: wlrctl can dispatch a pointer event to sway.

    Confirms the wl_seat / wlr-virtual-pointer protocol is reachable. Says
    nothing about whether events reach gamescope or the game — that's what
    probe_gamescope() and probe_game() are for.
    """
    _wlrctl("pointer", "move", "0", "0")
    return {"backend": "wlrctl", "result": "sway accepted virtual pointer move"}


def probe_gamescope() -> dict | None:
    """Round-trip probe through gamescope's Xwayland.

    Injects a mousemove via the auto-selected backend, then reads the cursor
    position back via xdotool from gamescope's Xwayland. Verifies the cursor
    landed in the requested gamescope-coordinate space. Returns None when no
    gamescope is running (skip cleanly rather than raise).

    Verifies cursor positioning. Does NOT verify that the event was processed
    by the game itself — Unity/Proton may receive a positioned cursor but
    ignore the click. Use probe_game() for that.
    """
    display = _gamescope_xdisplay()
    if display is None:
        return None

    backend = resolve_backend("auto")
    target_x, target_y = 100, 100
    env = {**os.environ, "DISPLAY": display}

    if backend == "wlrctl":
        _wlrctl_move_abs(target_x, target_y)
    else:
        _xdotool_move(target_x, target_y, xdisplay=display)

    r = _run(["xdotool", "getmouselocation", "--shell"], env=env)
    if r.returncode != 0:
        raise ExternalCommandError(
            f"xdotool getmouselocation failed on {display}: {r.stderr.decode().strip()}"
        )
    pos: dict[str, str] = {}
    for line in r.stdout.decode().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            pos[k] = v
    actual_x = int(pos.get("X", "-1"))
    actual_y = int(pos.get("Y", "-1"))
    if abs(actual_x - target_x) > 2 or abs(actual_y - target_y) > 2:
        raise ExternalCommandError(
            f"Gamescope-input probe FAILED: backend={backend!r} injected "
            f"({target_x}, {target_y}) but gamescope's Xwayland reports cursor at "
            f"({actual_x}, {actual_y}). The {backend} → gamescope path is dropping "
            f"or rerouting pointer events.",
            hint=(
                f"Try --backend {'xdotool' if backend == 'wlrctl' else 'wlrctl'} to "
                "isolate. See TROUBLESHOOTING.md."
            ),
        )
    return {
        "backend": backend,
        "display": display,
        "target": [target_x, target_y],
        "actual": [actual_x, actual_y],
    }


def probe_game(key: str = "Escape", settle: float = 0.6, max_phash_dist: int = 4) -> dict:
    """End-to-end probe: verify input causes visible game-side state change.

    Tries two strategies before concluding input is broken:

    1. Press *key* (default Escape). Most games open/toggle a menu — if so,
       the second press restores the prior screen.
    2. If the key produced no change, sweep the mouse from (100, 100) to
       near the far corner — most game UIs show hover-state changes on
       interactive widgets, which the perceptual hash will catch.

    Only raises ExternalCommandError when *both* strategies produce no
    visible change. That's the signal input is dropped end-to-end — not
    just "Escape happens to be a no-op in this game state".

    Caller is responsible for ensuring a game is actually running.
    """
    from .capture import Screen
    from . import compare as cmp

    screen = Screen()
    before = screen.grab()
    distances: dict[str, int] = {}

    comp = Compositor()

    # Strategy 1: key press (default Escape).
    comp.key(key)
    time.sleep(settle)
    after_key = screen.grab()
    similar, dist_key = cmp.phash(before, after_key, max_distance=max_phash_dist)
    distances["key"] = dist_key
    if not similar:
        # Best-effort restore: another press usually closes the menu the first
        # press opened. If destructive on a specific game, the caller can
        # pass a different *key*.
        try:
            comp.key(key)
        except Exception:
            pass
        return {
            "changed": True,
            "strategy": f"key={key!r}",
            "phash_distances": distances,
            "result": "screen changed — input reached the game",
        }

    # Strategy 2: mouse sweep. Most interactive UIs reveal hover state.
    comp.move(100, 100)
    time.sleep(0.15)
    comp.move(1820, 980)
    time.sleep(0.3)
    after_move = screen.grab()
    similar, dist_move = cmp.phash(before, after_move, max_distance=max_phash_dist)
    distances["mouse_sweep"] = dist_move
    if not similar:
        try:
            comp.move(100, 100)
        except Exception:
            pass
        return {
            "changed": True,
            "strategy": "mouse_sweep",
            "phash_distances": distances,
            "result": "screen changed via mouse sweep — input reached the game",
        }

    # Both strategies produced no change.
    raise ExternalCommandError(
        f"Game-input probe inconclusive: pressing {key!r} (phash dist "
        f"{dist_key}) and sweeping the mouse (phash dist {dist_move}) "
        "produced no visible screen change. Either input is being dropped "
        "end-to-end OR the game is in a non-interactive state (loading "
        "screen, intro video, fully static menu). Retry once the game is "
        "interactive.",
        hint="See TROUBLESHOOTING.md > Input not reaching the game.",
    )


# Backward-compat alias: older callers / external skill docs use probe().
def probe() -> dict:
    """Legacy entry point. Prefer probe_sway / probe_gamescope / probe_game."""
    result = probe_gamescope()
    if result is not None:
        return result
    return probe_sway()


class Compositor:
    """Input driver for the headless sway session.

    All coordinates are absolute pixels within the output bounds (typically
    1920×1080 for HEADLESS-1).

    Backend selection: pass `backend=` to any method, or set `UNDERSTUDY_BACKEND`
    in the env. Default (`"auto"`) uses wlrctl (Wayland → sway → gamescope).
    Pass `backend="xdotool"` to talk directly to gamescope's nested Xwayland.
    """

    def move(self, x: int, y: int, backend: Backend = "auto") -> None:
        """Move the virtual pointer to absolute position (x, y)."""
        b = resolve_backend(backend)
        if b == "libei":
            from .libei_backend import get_libei_backend
            get_libei_backend().move(x, y)
        elif b == "xdotool":
            _xdotool_move(x, y)
        else:
            _wlrctl_move_abs(x, y)

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        delay: float = 0.05,
        backend: Backend = "auto",
    ) -> None:
        """Move to (x, y) then press and release *button*."""
        b = resolve_backend(backend)
        if b == "libei":
            from .libei_backend import get_libei_backend
            time.sleep(delay)
            get_libei_backend().click(x, y, button=button)
        elif b == "xdotool":
            time.sleep(delay)
            _xdotool_click(x, y, button)
        else:
            _wlrctl_move_abs(x, y)
            time.sleep(delay)
            _wlrctl("pointer", "click", button)

    def scroll(self, dx: float = 0.0, dy: float = 0.0, backend: Backend = "auto") -> None:
        """Scroll horizontally by *dx* and vertically by *dy* (positive = down/right)."""
        b = resolve_backend(backend)
        if b == "xdotool":
            env = _xdotool_env()
            if dy:
                btn = "5" if dy > 0 else "4"
                for _ in range(max(1, abs(int(dy)))):
                    _run(["xdotool", "click", btn], env=env)
            if dx:
                btn = "7" if dx > 0 else "6"
                for _ in range(max(1, abs(int(dx)))):
                    _run(["xdotool", "click", btn], env=env)
        else:
            if dy:
                _wlrctl("pointer", "scroll", "vertical", str(dy))
            if dx:
                _wlrctl("pointer", "scroll", "horizontal", str(dx))

    def type(self, text: str, backend: Backend = "auto") -> None:
        """Type a string of characters.

        Note: libei has no string-input concept (only individual keycodes
        with manual XKB-layout handling), so even with `backend=libei` this
        falls back to xdotool when gamescope is available, otherwise wlrctl.
        """
        b = resolve_backend(backend)
        if b == "libei":
            if _gamescope_xdisplay() is not None:
                _xdotool_type(text)
            else:
                _wlrctl("keyboard", "type", text)
        elif b == "xdotool":
            _xdotool_type(text)
        else:
            _wlrctl("keyboard", "type", text)

    def key(self, keysym: str, backend: Backend = "auto") -> None:
        """Press and release a single key by its XKB keysym name (e.g. 'Return', 'Escape')."""
        b = resolve_backend(backend)
        if b == "libei":
            from .libei_backend import get_libei_backend
            get_libei_backend().key(keysym)
        elif b == "xdotool":
            _xdotool_key(keysym)
        else:
            # wlrctl 0.2.2 has no combined key command — emit press then release
            # so the key doesn't stay stuck down on the virtual keyboard.
            _wlrctl("keyboard", "press", keysym)
            _wlrctl("keyboard", "release", keysym)


# ---------------------------------------------------------------------------
# Public helpers (thin wrappers around private discovery functions)
# ---------------------------------------------------------------------------

def gamescope_x_display() -> str | None:
    """Return the X display string for the active gamescope Xwayland (e.g. ':3'), or None."""
    return _gamescope_xdisplay()


def game_window_id(xdisplay: str) -> str | None:
    """Return the hex window ID of the main game window on *xdisplay*, or None."""
    return _game_window_id(xdisplay)
