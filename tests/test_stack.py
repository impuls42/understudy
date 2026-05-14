"""Automated §4.3 smoke checks as a pytest suite.

All marked @pytest.mark.smoke — these run without a game session.
"""

import socket
import subprocess
from pathlib import Path

import pytest

from understudy.stack import Stack
from understudy.ipc import get_outputs
from understudy._runtime import wayland_env


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    """Assert the headless stack is running. Run `us stack up` before this suite."""
    Stack.require_up()
    yield


@pytest.mark.smoke
def test_sway_running():
    st = Stack.status()
    assert st["sway"]["active_state"] == "active", "sway is not active"


@pytest.mark.smoke
def test_wayland_socket():
    st = Stack.status()
    assert st["sway"]["socket_exists"], "Wayland socket not found"


@pytest.mark.smoke
def test_wayvnc_port():
    with socket.create_connection(("127.0.0.1", 5900), timeout=5):
        pass


@pytest.mark.smoke
def test_sway_ipc_headless_output():
    outputs = get_outputs()
    names = [o["name"] for o in outputs]
    assert "HEADLESS-1" in names, f"HEADLESS-1 not in sway outputs: {names}"


@pytest.mark.smoke
def test_headless_output_resolution():
    outputs = {o["name"]: o for o in get_outputs()}
    h1 = outputs.get("HEADLESS-1", {})
    assert h1.get("width") == 1920 and h1.get("height") == 1080, (
        f"Unexpected resolution: {h1.get('width')}x{h1.get('height')}"
    )


@pytest.mark.smoke
def test_grim_capture():
    out = Path("/tmp/understudy-test-capture.png")
    r = subprocess.run(["grim", str(out)], capture_output=True, env=wayland_env())
    assert r.returncode == 0, r.stderr.decode()
    assert out.exists() and out.stat().st_size > 1000, "grim output too small"
    out.unlink(missing_ok=True)
