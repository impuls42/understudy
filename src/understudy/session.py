"""Game session lifecycle.

Launches a game inside a transient systemd service unit via pystemd.run,
which is the Python equivalent of `systemd-run --user --unit=... --property=Delegate=yes`.

The cgroup wrapping is what makes teardown reliable: `systemctl kill` on the
unit nukes every descendant (gamescope, gamescopereaper, Steam, the game)
atomically, regardless of their process-tree depth.

See design doc §3.9 for the process-tree explanation.
"""

from __future__ import annotations

import time
from pathlib import Path

import psutil
from pystemd.dbuslib import DBus
from pystemd.systemd1 import Manager, Unit
from pystemd import run as pystemd_run

from ._runtime import wayland_display, xdg_runtime_dir, SWAY_UNIT
from .errors import PreconditionError, UnderstudyError

_UNIT_TEMPLATE = "understudy-game-{}.service"
_GAMESCOPE = "/usr/games/gamescope"


def _user_bus() -> DBus:
    bus = DBus(user_mode=True)
    bus.open()
    return bus


def _unit_active(name: str, bus: DBus) -> bool:
    try:
        u = Unit(name.encode(), bus=bus)
        u.load()
        return u.Unit.ActiveState.decode() == "active"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pre-flight check
# ---------------------------------------------------------------------------

def _check_no_stray_steam() -> None:
    """Raise PreconditionError if a Steam process is already running for this user.

    If another Steam daemon is running, the `steam steam://rungameid/...` URL
    handler will hand off the launch to it rather than to our gamescope
    session. See design doc §3.6.
    """
    uid = psutil.Process().uids().real
    for proc in psutil.process_iter(["name", "uids"]):
        try:
            if (
                "steam" in proc.info["name"].lower()
                and proc.info["uids"].real == uid
            ):
                raise PreconditionError(
                    f"Steam process already running (PID {proc.pid}: {proc.info['name']}).",
                    hint=(
                        "Kill it first: `pkill -u $USER steam` or `us game kill`."
                        " See design doc §3.6."
                    ),
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


# ---------------------------------------------------------------------------
# GameSession
# ---------------------------------------------------------------------------

class GameSession:
    """Context manager that launches a game and tears it down atomically.

    Usage::

        with GameSession(appid=1062090) as session:
            # game is running; wait for main menu, click, capture, assert
            ...
        # game is stopped here

    Or without context manager::

        session = GameSession(appid=1062090)
        session.launch()
        session.stop()
    """

    def __init__(
        self,
        appid: int,
        unit_name: str | None = None,
        width: int = 1920,
        height: int = 1080,
        extra_gamescope_args: list[str] | None = None,
    ) -> None:
        self.appid = appid
        self.unit_name = unit_name or _UNIT_TEMPLATE.format(appid)
        self.width = width
        self.height = height
        self.extra_gamescope_args = extra_gamescope_args or ["-e", "-f"]
        self._unit: Unit | None = None

    # --- context manager ---

    def __enter__(self) -> "GameSession":
        self.launch()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # --- public methods ---

    def launch(self) -> None:
        """Pre-flight, then start the game in a transient systemd service."""
        _check_no_stray_steam()

        display = wayland_display()
        if not display:
            raise PreconditionError(
                "Headless Wayland stack is not up.",
                hint="Run `us stack up` first.",
            )

        cmd = [
            _GAMESCOPE,
            "-W", str(self.width),
            "-H", str(self.height),
            *self.extra_gamescope_args,
            "--",
            "steam",
            f"steam://rungameid/{self.appid}",
        ]
        env = {
            "WAYLAND_DISPLAY": display,
            "SDL_VIDEODRIVER": "wayland",
            "XDG_RUNTIME_DIR": str(xdg_runtime_dir()),
        }

        self._unit = pystemd_run(
            cmd,
            name=self.unit_name.encode(),
            user_mode=True,
            env=env,
            remain_after_exit=True,
            extra={b"Delegate": True},
        )

    def is_active(self) -> bool:
        """Return True if the service unit is active (game may still be running)."""
        if self._unit is None:
            bus = _user_bus()
            return _unit_active(self.unit_name, bus)
        try:
            self._unit.load()
            return self._unit.Unit.ActiveState.decode() == "active"
        except Exception:
            return False

    def stop(self, grace: float = 5.0) -> None:
        """Kill the game's cgroup: SIGTERM → wait *grace* seconds → SIGKILL → reset."""
        bus = _user_bus()
        m = Manager(bus=bus)
        m.load()
        uname = self.unit_name.encode()

        def _kill(sig: str) -> None:
            try:
                m.Manager.KillUnit(uname, b"all", self._signum(sig))
            except Exception:
                pass

        _kill("SIGTERM")
        time.sleep(grace)
        _kill("SIGKILL")
        time.sleep(0.5)

        try:
            m.Manager.StopUnit(uname, b"replace")
        except Exception:
            pass
        time.sleep(0.5)

        try:
            m.Manager.ResetFailedUnit(uname)
        except Exception:
            pass

    @staticmethod
    def _signum(name: str) -> int:
        import signal
        return getattr(signal, name).value


# ---------------------------------------------------------------------------
# CLI-level helpers (used by `us game`)
# ---------------------------------------------------------------------------

def active_unit_name() -> str | None:
    """Return the name of any currently active understudy game unit, or None."""
    bus = _user_bus()
    m = Manager(bus=bus)
    m.load()
    try:
        units = m.Manager.ListUnits()
        for u in units:
            name = u[0].decode() if isinstance(u[0], bytes) else u[0]
            active = u[3].decode() if isinstance(u[3], bytes) else u[3]
            if name.startswith("understudy-game-") and active == "active":
                return name
    except Exception:
        pass
    return None
