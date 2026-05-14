"""Sway IPC bindings via i3ipc.

Provides typed access to sway's IPC socket — no `swaymsg` subprocess needed.
All methods require the headless stack to be running; they will raise
PreconditionError if the sway IPC socket cannot be found.
"""

from __future__ import annotations

from typing import Any

import i3ipc

from ._runtime import sway_ipc_socket
from .errors import PreconditionError


def _connection() -> i3ipc.Connection:
    sock = sway_ipc_socket()
    if sock is None or not sock.exists():
        raise PreconditionError(
            "No sway IPC socket found for wayland-headless display.",
            hint="Run `us stack up` first.",
        )
    return i3ipc.Connection(socket_path=str(sock))


def get_outputs() -> list[dict[str, Any]]:
    """Return all sway outputs as dicts (name, active, resolution, …)."""
    conn = _connection()
    return [
        {
            "name": o.name,
            "active": o.active,
            "width": o.rect.width if o.rect else None,
            "height": o.rect.height if o.rect else None,
            "scale": o.scale,
            "transform": o.transform,
        }
        for o in conn.get_outputs()
    ]


def get_inputs() -> list[dict[str, Any]]:
    """Return sway-visible input devices."""
    conn = _connection()
    return [
        {
            "identifier": i.identifier,
            "name": i.name,
            "type": i.type,
        }
        for i in conn.get_inputs()
    ]


def get_tree_summary() -> dict[str, Any]:
    """Return a compact summary of the sway layout tree (workspaces + windows)."""
    conn = _connection()
    tree = conn.get_tree()
    return {
        "workspaces": [
            {
                "name": ws.name,
                "focused": ws.focused,
                "windows": [n.name for n in ws.leaves()],
            }
            for ws in tree.workspaces()
        ]
    }


def run_command(cmd: str) -> list[dict]:
    """Run an arbitrary swaymsg command. Returns the list of reply dicts."""
    conn = _connection()
    results = conn.command(cmd)
    return [{"success": r.success, "error": getattr(r, "error", None)} for r in results]
