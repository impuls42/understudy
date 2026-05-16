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
    try:
        bus = DBus(user_mode=True)
        bus.open()
        return bus
    except Exception as exc:
        raise PreconditionError(
            f"Cannot connect to the user D-Bus session: {exc}",
            hint=(
                "Run this command from the same user session that owns the "
                "understudy services (e.g. the login shell, not su/sudo)."
            ),
        ) from exc


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
            name = proc.info.get("name")
            uids = proc.info.get("uids")
            if name and "steam" in name.lower() and uids and uids.real == uid:
                raise PreconditionError(
                    f"Steam process already running (PID {proc.pid}: {name}).",
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
        inner_cmd: list[str] | None = None,
    ) -> None:
        self.appid = appid
        self.unit_name = unit_name or _UNIT_TEMPLATE.format(appid)
        self.width = width
        self.height = height
        self.extra_gamescope_args = extra_gamescope_args if extra_gamescope_args is not None else ["-f"]
        # Override what runs inside gamescope. When None (default) the session
        # launches Steam with the configured appid; pass an explicit command
        # list to run any other X11/Wayland client (e.g. xeyes for input tests).
        # When set, the stray-Steam pre-flight is skipped.
        self.inner_cmd = inner_cmd
        self._unit: Unit | None = None

    @classmethod
    def from_unit_name(cls, name: str) -> "GameSession":
        """Reconstruct a teardown-only session from an existing unit name.

        The returned object is only valid for calling stop(). appid and other
        launch-time attributes are set to inert defaults.
        """
        obj = cls(appid=0)
        obj.unit_name = name
        return obj

    # --- context manager ---

    def __enter__(self) -> "GameSession":
        self.launch()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # --- public methods ---

    def launch(self) -> None:
        """Pre-flight, then start the game in a transient systemd service."""
        if self.inner_cmd is None:
            _check_no_stray_steam()
            inner = ["steam", f"steam://rungameid/{self.appid}"]
        else:
            inner = list(self.inner_cmd)

        # Clear a stale transient unit from a prior crashed/failed run. systemd
        # holds onto failed transient units until reset-failed is called; if
        # the previous game crashed and stop() wasn't run, StartTransientUnit
        # below would fail with UnitExists. Be defensive: reset whether it's
        # actually failed or not (no-op if the unit doesn't exist).
        try:
            bus = _user_bus()
            if _unit_active(self.unit_name, bus):
                raise PreconditionError(
                    f"Unit {self.unit_name} is already active.",
                    hint="Stop it first: `us game kill`.",
                )
            m = Manager(bus=bus)
            m.load()
            try:
                m.Manager.ResetFailedUnit(self.unit_name.encode())
            except Exception:
                pass
        except PreconditionError:
            raise
        except Exception:
            pass

        display = wayland_display()
        if not display:
            raise PreconditionError(
                "Headless Wayland stack is not up.",
                hint="Run `us stack up` first.",
            )

        # --backend wayland: explicit. Without it gamescope sometimes auto-
        #   selects paths that don't present to sway, leaving wayvnc blank.
        # -w/-h matching -W/-H: eliminates internal rescaling so injected
        #   coordinates match 1:1 between sway and the game's view.
        # --force-grab-cursor: pins the cursor inside gamescope's surface so
        #   relative-mode mouse input doesn't escape.
        #
        # Intentionally NOT here: -e (--steam). The issue #1 dossier called for
        # it as a fix for synthetic input on Proton games, but empirically on
        # this stack: (a) wlrctl input reaches the game without it (verified
        # via `us xeyes`); (b) -e CHANGES window-management to expect Steam to
        # drive mapping, so the surface stays unmapped when the inner cmd is
        # anything else. If a specific Proton game truly needs Steam
        # Integration Mode, add "-e" to that profile's extra_gamescope_args.
        cmd = [
            _GAMESCOPE,
            "--backend", "wayland",
            "-W", str(self.width),
            "-H", str(self.height),
            "-w", str(self.width),
            "-h", str(self.height),
            "--force-grab-cursor",
            *self.extra_gamescope_args,
            "--",
            *inner,
        ]
        env = {
            "WAYLAND_DISPLAY": display,
            "SDL_VIDEODRIVER": "wayland",
            "XDG_RUNTIME_DIR": str(xdg_runtime_dir()),
            # Override the inherited XDG_CURRENT_DESKTOP=ubuntu:GNOME so portal
            # backend selection and gamescope's heuristics pick the wlroots/sway
            # paths. See issue #1 study §7.4.
            "XDG_CURRENT_DESKTOP": "sway",
            "XDG_SESSION_TYPE": "wayland",
            # Prevent gamescope from using the login session's X display.
            # Gamescope spawns its own Xwayland and sets DISPLAY for children.
            "DISPLAY": "",
            # Disable the Steam overlay injector to avoid the long-session
            # memory bloat ("lag bomb"). Steam itself still runs; only the
            # in-process GameOverlay hook is suppressed. See issue #1 study §7.5.
            "LD_PRELOAD": "",
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

def is_unit_active(name: str) -> bool:
    """Return True if the given systemd user unit is currently active."""
    return _unit_active(name, _user_bus())


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
