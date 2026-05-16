"""libei client — sends synthetic input directly to gamescope's libeis socket.

Architecturally the cleanest input path on this stack: Wayland-native,
focus-independent, bypasses sway routing and Xwayland entirely. Talks to
the EIS socket gamescope opens at `$XDG_RUNTIME_DIR/gamescope-<N>-ei`
(see issue #1 study §8.1 for the gamescope source reference).

Gamescope's libeis seat advertises POINTER, POINTER_ABSOLUTE, KEYBOARD,
SCROLL, and BUTTON (no TOUCH — issue #1 study §8.2). We bind to absolute
pointer + button + keyboard.

Dependency: `snegg` (no PyPI; installed from git per pyproject.toml).
Pinned commit because snegg's author explicitly notes the API is unstable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from .errors import ExternalCommandError, PreconditionError


# XKB keysym → Linux input-event code (linux/input-event-codes.h).
# Covers the common UI keys agents need. Letters/digits are not here because
# their evdev codes follow physical keyboard layout, not alphabetical order;
# use xdotool's `type` for text.
_XKB_TO_EVDEV: dict[str, int] = {
    "Escape": 1,
    "BackSpace": 14,
    "Tab": 15,
    "Return": 28,
    "Control_L": 29, "Control_R": 97,
    "Shift_L": 42, "Shift_R": 54,
    "Alt_L": 56, "Alt_R": 100,
    "space": 57,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63, "F6": 64,
    "F7": 65, "F8": 66, "F9": 67, "F10": 68, "F11": 87, "F12": 88,
    "Home": 102, "Up": 103, "Page_Up": 104,
    "Left": 105, "Right": 106, "End": 107, "Down": 108, "Page_Down": 109,
    "Insert": 110, "Delete": 111,
    "Super_L": 125, "Super_R": 126, "Menu": 127,
}

# Mouse button names → Linux input button codes (BTN_LEFT etc.).
_BUTTON_CODES: dict[str, int] = {
    "left": 0x110,    # 272 BTN_LEFT
    "right": 0x111,   # 273 BTN_RIGHT
    "middle": 0x112,  # 274 BTN_MIDDLE
}


def find_gamescope_eis_socket() -> Path | None:
    """Locate gamescope's libeis socket. Returns None if no gamescope is running.

    Gamescope writes its socket as `gamescope-<N>-ei` under XDG_RUNTIME_DIR,
    where N is the wayland display slot it picked (0, 1, ... up to 128).
    If multiple gamescope instances are running, picks the most recent.
    """
    rt = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    candidates = [p for p in rt.glob("gamescope-*-ei") if p.is_socket()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


class LibeiBackend:
    """Send synthetic input to gamescope's libeis socket via snegg.

    Stateful: holds an open Sender + Device for the lifetime of the gamescope
    process. Auto-reconnects when the socket path changes (i.e. gamescope
    restarted between calls).
    """

    def __init__(self, name: str = "understudy"):
        self.name = name
        self._sender = None  # snegg.ei.Sender
        self._device = None  # snegg.ei.Device
        self._socket_path: Optional[Path] = None

    # ---- lifecycle ----

    def _ensure_connected(self) -> None:
        socket = find_gamescope_eis_socket()
        if socket is None:
            raise PreconditionError(
                "libei backend selected but no gamescope EIS socket is open.",
                hint="Launch a game first: `us game launch <slug>`.",
            )
        if self._sender is not None and self._socket_path == socket:
            return
        # Different socket (gamescope restarted) — reconnect.
        self._disconnect()
        self._connect(socket)

    def _connect(self, socket: Path) -> None:
        import snegg.ei as ei

        sender = ei.Sender.create_for_socket(socket, self.name)
        device = None
        seat_bound = False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            sender.dispatch()
            for event in sender.events:
                t = event.event_type
                if t == ei.EventType.SEAT_ADDED and not seat_bound:
                    event.seat.bind(capabilities=(
                        ei.DeviceCapability.POINTER_ABSOLUTE,
                        ei.DeviceCapability.BUTTON,
                        ei.DeviceCapability.KEYBOARD,
                    ))
                    seat_bound = True
                elif t == ei.EventType.DEVICE_ADDED:
                    device = event.device
                elif t == ei.EventType.DEVICE_RESUMED:
                    if device is None:
                        continue
                    device.start_emulating()
                    self._sender = sender
                    self._device = device
                    self._socket_path = socket
                    return
                elif t == ei.EventType.DISCONNECT:
                    raise ExternalCommandError(
                        f"libei: disconnected during handshake to {socket}",
                    )
            time.sleep(0.02)
        raise ExternalCommandError(
            f"libei: handshake timeout to {socket}; "
            f"got device={device!r}, seat_bound={seat_bound}",
        )

    def _disconnect(self) -> None:
        if self._device is not None:
            try:
                self._device.stop_emulating()
            except Exception:
                pass
            self._device = None
        if self._sender is not None:
            try:
                self._sender.disconnect()
            except Exception:
                pass
            self._sender = None
        self._socket_path = None

    # ---- input ops ----

    def move(self, x: int, y: int) -> None:
        self._ensure_connected()
        self._device.pointer_motion_absolute(float(x), float(y))
        self._device.frame()

    def click(self, x: int, y: int, button: str = "left", delay: float = 0.03) -> None:
        self.move(x, y)
        code = _BUTTON_CODES.get(button)
        if code is None:
            raise ExternalCommandError(
                f"libei: unknown button {button!r}",
                hint="Use one of: left, right, middle.",
            )
        self._device.button_button(code, True)
        self._device.frame()
        time.sleep(delay)
        self._device.button_button(code, False)
        self._device.frame()

    def key(self, keysym: str) -> None:
        self._ensure_connected()
        code = _XKB_TO_EVDEV.get(keysym)
        if code is None:
            raise ExternalCommandError(
                f"libei: keysym {keysym!r} not in evdev map.",
                hint=(
                    "Supported: Escape, Return, Tab, BackSpace, space, F1-F12, "
                    "Up/Down/Left/Right, Home/End, Page_Up/Down, Insert, Delete, "
                    "Control_L/R, Shift_L/R, Alt_L/R, Super_L/R, Menu. For "
                    "letters/digits or text strings use `us act type` (xdotool)."
                ),
            )
        self._device.keyboard_key(code, True)
        self._device.frame()
        time.sleep(0.03)
        self._device.keyboard_key(code, False)
        self._device.frame()


# Module-level singleton so callers don't repeat the handshake.
_singleton: Optional[LibeiBackend] = None


def get_libei_backend() -> LibeiBackend:
    global _singleton
    if _singleton is None:
        _singleton = LibeiBackend()
    return _singleton
