"""Headless Wayland stack lifecycle.

Drives `understudy-sway.service` and `understudy-wayvnc.service` via the
systemd user-bus (pystemd), never via subprocess shell-outs.

Typical usage (from the SDK):

    with Stack() as stack:
        info = stack.status()
        ...

Or one-shot:

    Stack.up()
    Stack.down()
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from pystemd.dbuslib import DBus
from pystemd.systemd1 import Manager, Unit

from ._runtime import (
    SWAY_UNIT,
    WAYVNC_UNIT,
    VNC_PORT,
    discover_wayland_display,
    sway_ipc_socket,
    wayland_display,
    wayland_socket,
    xdg_runtime_dir,
)
from .errors import PreconditionError, UnderstudyError

_UNIT_NAMES = (SWAY_UNIT, WAYVNC_UNIT)
_SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
# Repo-relative path to service files — resolved relative to this file.
_UNIT_SRC_DIR = Path(__file__).parent.parent.parent / "systemd"


def _user_bus() -> DBus:
    try:
        from pystemd.dbusexc import DBusBaseError
        bus = DBus(user_mode=True)
        bus.open()
        return bus
    except Exception as exc:
        # DBusBaseError (and OSError on missing socket) both mean no D-Bus session.
        raise PreconditionError(
            f"Cannot connect to the user D-Bus session: {exc}",
            hint=(
                "Run this command from the same user session that owns the "
                "understudy services (e.g. the login shell, not su/sudo)."
            ),
        ) from exc


def _manager(bus: DBus) -> Manager:
    m = Manager(bus=bus)
    m.load()
    return m


def _unit(name: str, bus: DBus) -> Unit:
    u = Unit(name.encode(), bus=bus)
    u.load()
    return u


def _active_state(name: str, bus: DBus) -> str:
    """Return the ActiveState string for a user unit ('active', 'inactive', …)."""
    try:
        u = _unit(name, bus)
        return u.Unit.ActiveState.decode()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Public install helper
# ---------------------------------------------------------------------------

def install_units(force: bool = False) -> list[str]:
    """Copy service files from the repo into ~/.config/systemd/user/.

    Safe to call repeatedly — skips files that are already in place unless
    *force* is True. Returns the list of files that were updated.
    """
    _SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    updated: list[str] = []
    for src in _UNIT_SRC_DIR.glob("*.service"):
        dst = _SYSTEMD_USER_DIR / src.name
        if not dst.exists() or force or dst.read_bytes() != src.read_bytes():
            shutil.copy2(src, dst)
            updated.append(src.name)

    if updated:
        # Reload the daemon so it sees the new/updated units.
        bus = _user_bus()
        m = _manager(bus)
        m.Manager.Reload()
        time.sleep(0.3)  # let the reload settle before callers start units

    return updated


# ---------------------------------------------------------------------------
# Stack.up / Stack.down / Stack.status
# ---------------------------------------------------------------------------

class Stack:
    """Context manager that brings the headless Wayland stack up on enter and
    down on exit. Also works as a plain namespace for one-shot calls.

    Idempotent: calling `up()` when the stack is already running is a no-op.
    """

    def __enter__(self) -> "Stack":
        Stack.up()
        return self

    def __exit__(self, *_: object) -> None:
        Stack.down()

    # ------------------------------------------------------------------
    @staticmethod
    def up(wait_timeout: float = 10.0) -> None:
        """Start sway (headless) and wayvnc, installing units if needed.

        Blocks until the Wayland socket appears (or *wait_timeout* seconds pass).
        """
        install_units()

        bus = _user_bus()
        m = _manager(bus)

        if _active_state(SWAY_UNIT, bus) != "active":
            m.Manager.StartUnit(SWAY_UNIT.encode(), b"replace")
            _wait_for_socket(wait_timeout)

        # Write the env file that the wayvnc service reads for WAYLAND_DISPLAY.
        # Must happen AFTER the socket is discovered (i.e. after sway is up).
        _write_env_file()

        # NOTE: if wayvnc is already active but was started against a stale
        # WAYLAND_DISPLAY, StartUnit is a no-op and wayvnc listens on the wrong
        # display. The safe recovery is `us stack down && us stack up`.
        if _active_state(WAYVNC_UNIT, bus) != "active":
            m.Manager.StartUnit(WAYVNC_UNIT.encode(), b"replace")

    @staticmethod
    def down(grace: float = 3.0) -> None:
        """Stop wayvnc then sway. Safe to call when nothing is running."""
        bus = _user_bus()
        m = _manager(bus)
        for unit in (WAYVNC_UNIT, SWAY_UNIT):
            if _active_state(unit, bus) != "inactive":
                m.Manager.StopUnit(unit.encode(), b"replace")
        time.sleep(grace)

    @staticmethod
    def status() -> dict:
        """Return a JSON-serialisable dict describing the current stack state."""
        bus = _user_bus()
        sway_state = _active_state(SWAY_UNIT, bus)
        wayvnc_state = _active_state(WAYVNC_UNIT, bus)
        sock = wayland_socket()
        ipc_sock = sway_ipc_socket()
        return {
            "sway": {
                "unit": SWAY_UNIT,
                "active_state": sway_state,
                "wayland_display": wayland_display(),
                "socket_exists": sock.exists(),
                "socket_path": str(sock),
                "ipc_socket": str(ipc_sock) if ipc_sock else None,
            },
            "wayvnc": {
                "unit": WAYVNC_UNIT,
                "active_state": wayvnc_state,
                "port": VNC_PORT,
            },
            "healthy": sway_state == "active" and wayvnc_state == "active" and sock.exists(),
        }

    @staticmethod
    def is_up() -> bool:
        return Stack.status()["healthy"]

    @staticmethod
    def require_up() -> None:
        """Raise PreconditionError if the stack is not healthy."""
        st = Stack.status()
        if not st["healthy"]:
            detail = (
                f"sway={st['sway']['active_state']} "
                f"wayvnc={st['wayvnc']['active_state']} "
                f"socket={'present' if st['sway']['socket_exists'] else 'missing'}"
            )
            raise PreconditionError(
                f"Headless stack is not up: {detail}",
                hint="Run `us stack up` first.",
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_env_file() -> None:
    """Write /run/user/<uid>/understudy.env for services that need WAYLAND_DISPLAY."""
    from ._runtime import wayland_display, xdg_runtime_dir
    display = wayland_display()
    env_path = xdg_runtime_dir() / "understudy.env"
    env_path.write_text(f"WAYLAND_DISPLAY={display}\n")

def _wait_for_socket(timeout: float) -> None:
    """Poll until sway's Wayland socket appears.

    Because sway uses auto-numbered sockets (wayland-N), we detect the
    socket by looking for a new entry in XDG_RUNTIME_DIR that wasn't there
    before sway started (excluding wayland-0, which belongs to GDM/GNOME).
    """
    from ._runtime import xdg_runtime_dir, discover_wayland_display

    rt = xdg_runtime_dir()
    before = {
        p.name for p in rt.iterdir()
        if p.name.startswith("wayland-") and not p.name.endswith(".lock") and p.is_socket()
    }

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Check if sway IPC socket is up AND a new wayland socket appeared.
        if discover_wayland_display() is not None:
            current = {
                p.name for p in rt.iterdir()
                if p.name.startswith("wayland-") and not p.name.endswith(".lock") and p.is_socket()
            }
            if current - before:  # new socket appeared
                return
        time.sleep(0.25)

    raise UnderstudyError(
        f"Sway Wayland socket did not appear within {timeout:.0f}s",
        hint="Check `journalctl --user -u understudy-sway.service` for errors.",
    )
