"""Runtime environment helpers.

Single source of truth for the Wayland socket name, XDG_RUNTIME_DIR, and
other env values that must be consistent across every component.

Socket-name note: sway 1.9 uses wl_display_add_socket_auto(), which generates
sequential names (wayland-0, wayland-1, …) regardless of the WAYLAND_DISPLAY
env var. So we auto-discover the socket sway actually created by correlating
it with the sway IPC socket mtime. The GDM session always holds wayland-0,
our headless sway takes the next free slot.
"""

from __future__ import annotations

import os
from pathlib import Path


SWAY_UNIT = "understudy-sway.service"
WAYVNC_UNIT = "understudy-wayvnc.service"
VNC_PORT = 5900


def xdg_runtime_dir() -> Path:
    val = os.environ.get("XDG_RUNTIME_DIR")
    if val:
        return Path(val)
    uid = os.getuid()
    return Path(f"/run/user/{uid}")


def sway_ipc_socket() -> Path | None:
    """Find the active sway IPC socket, or None if sway isn't running."""
    rt = xdg_runtime_dir()
    uid = os.getuid()
    candidates = sorted(rt.glob(f"sway-ipc.{uid}.*.sock"))
    return candidates[-1] if candidates else None


def discover_wayland_display() -> str | None:
    """Return the name of the Wayland socket that the headless sway created.

    Strategy: the sway IPC socket and the Wayland socket are created at
    essentially the same instant. Find all wayland-N sockets whose mtime
    matches the IPC socket mtime within a 5-second window.
    If exactly one match exists, return it. If ambiguous, return the newest
    non-wayland-0 socket.
    """
    ipc = sway_ipc_socket()
    if ipc is None or not ipc.exists():
        return None

    rt = xdg_runtime_dir()
    ipc_mtime = ipc.stat().st_mtime

    wayland_sockets = [
        p for p in rt.iterdir()
        if p.name.startswith("wayland-")
        and not p.name.endswith(".lock")
        and p.is_socket()
        and p.name != "wayland-0"  # GDM session
    ]
    if not wayland_sockets:
        return None

    # Prefer sockets created within 5 seconds of the IPC socket.
    close = [p for p in wayland_sockets if abs(p.stat().st_mtime - ipc_mtime) < 5.0]
    candidates = close if close else wayland_sockets
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0].name


def wayland_display() -> str:
    """Return the active Wayland display name (e.g. 'wayland-1').

    Falls back to 'wayland-headless' (the desired name) if not yet discoverable.
    """
    return discover_wayland_display() or "wayland-headless"


def wayland_socket() -> Path:
    return xdg_runtime_dir() / wayland_display()


def wayland_env() -> dict[str, str]:
    """Env dict to pass to commands / subprocesses that need to connect to our sway."""
    return {
        **os.environ,
        "WAYLAND_DISPLAY": wayland_display(),
        "XDG_RUNTIME_DIR": str(xdg_runtime_dir()),
    }
