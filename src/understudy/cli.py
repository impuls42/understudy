"""`us` console script.

Each subcommand group is a Typer app registered to `app`. The actual work
lives in the SDK modules; the CLI is a thin JSON-aware wrapper.

Subcommand groups by phase:
  Phase 1 — stack {up,down,status,install}, doctor
  Phase 2 — act {click,move,type,key}, scene capture
  Phase 3 — game {launch,kill,is-running,status,scaffold,list}
  Phase 4 — scene {wait-for,wait-quiescent,diff}, ref {record,list,show}
  Phase 5 — run <path>
"""

from __future__ import annotations

import json as _json_mod
import socket
import sys
from pathlib import Path

import typer

from . import __version__
from .errors import UnderstudyError

app = typer.Typer(no_args_is_help=True, add_completion=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _out(data: object, json_mode: bool) -> None:
    if json_mode:
        typer.echo(_json_mod.dumps(data, indent=2, default=str))
    else:
        # data is expected to be a plain string in text mode
        typer.echo(str(data))


def _err(exc: UnderstudyError, json_mode: bool) -> None:
    if json_mode:
        typer.echo(_json_mod.dumps(exc.as_dict(), indent=2))
    else:
        typer.echo(f"Error: {exc.reason}", err=True)
        if exc.hint:
            typer.echo(f"Hint:  {exc.hint}", err=True)
    raise typer.Exit(exc.code)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

@app.command()
def version() -> None:
    """Print the installed version and exit."""
    typer.echo(__version__)


@app.command()
def status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Show overall status: stack health, active game, and display info."""
    from .stack import Stack
    from .session import active_unit_name
    from ._runtime import wayland_display, wayland_socket

    # Gather stack info — may fail if D-Bus is unavailable.
    try:
        st = Stack.status()
        stack_ok = True
    except UnderstudyError as e:
        st = None
        stack_ok = False
        stack_err = str(e)

    # Gather game info — same caveat.
    try:
        game_unit = active_unit_name()
    except UnderstudyError:
        game_unit = None

    if as_json:
        data: dict = {
            "stack": st if stack_ok else {"error": stack_err},
            "game": {"unit": game_unit, "active": game_unit is not None},
        }
        typer.echo(_json_mod.dumps(data, indent=2, default=str))
        return

    # Human-readable output.
    if not stack_ok:
        typer.echo(f"stack:   error  ({stack_err})", err=False)
    else:
        sway = st["sway"]
        vnc  = st["wayvnc"]
        health = "healthy" if st["healthy"] else "degraded"
        sock   = "✓" if sway["socket_exists"] else "✗"
        typer.echo(f"stack:   {health}")
        typer.echo(f"  sway:    {sway['active_state']}  (socket {sock}  display {sway['wayland_display']})")
        typer.echo(f"  wayvnc:  {vnc['active_state']}  (:{vnc['port']})")

    if game_unit:
        typer.echo(f"game:    {game_unit}")
    else:
        typer.echo("game:    none")


# ---------------------------------------------------------------------------
# stack
# ---------------------------------------------------------------------------

stack_app = typer.Typer(no_args_is_help=True, help="Manage the headless Wayland stack.")
app.add_typer(stack_app, name="stack")


@stack_app.command("up")
def stack_up(
    as_json: bool = typer.Option(False, "--json"),
    timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait for socket."),
) -> None:
    """Start sway (headless) and wayvnc. Idempotent."""
    from .stack import Stack, install_units
    try:
        updated = install_units()
        if updated and not as_json:
            typer.echo(f"Installed units: {', '.join(updated)}")
        Stack.up(wait_timeout=timeout)
        st = Stack.status()
        if as_json:
            typer.echo(_json_mod.dumps({**st, "ok": True}, indent=2, default=str))
        else:
            typer.echo("Stack is up." if st["healthy"] else "Stack started (may not be fully healthy).")
    except UnderstudyError as e:
        _err(e, as_json)


@stack_app.command("down")
def stack_down(
    as_json: bool = typer.Option(False, "--json"),
    grace: float = typer.Option(3.0, "--grace", help="Seconds to wait after SIGTERM."),
) -> None:
    """Stop wayvnc and sway. Safe to call when nothing is running."""
    from .stack import Stack
    try:
        Stack.down(grace=grace)
        st = Stack.status()
        if as_json:
            typer.echo(_json_mod.dumps({**st, "ok": True}, indent=2, default=str))
        else:
            typer.echo("Stack stopped.")
    except UnderstudyError as e:
        _err(e, as_json)


@stack_app.command("status")
def stack_status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Show stack state: sway/wayvnc unit states, socket presence, IPC socket."""
    from .stack import Stack
    try:
        st = Stack.status()
    except UnderstudyError as e:
        _err(e, as_json)
        return
    if as_json:
        typer.echo(_json_mod.dumps(st, indent=2, default=str))
    else:
        sway = st["sway"]
        vnc = st["wayvnc"]
        typer.echo(f"sway:    {sway['active_state']}  (socket: {'✓' if sway['socket_exists'] else '✗'})")
        typer.echo(f"wayvnc:  {vnc['active_state']}  (port {vnc['port']})")
        typer.echo(f"healthy: {st['healthy']}")


@stack_app.command("install")
def stack_install(
    force: bool = typer.Option(False, "--force", help="Overwrite even if unchanged."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Copy unit files from the repo into ~/.config/systemd/user/ and reload daemon."""
    from .stack import install_units
    updated = install_units(force=force)
    if as_json:
        typer.echo(_json_mod.dumps({"ok": True, "updated": updated}, indent=2))
    else:
        if updated:
            typer.echo(f"Installed: {', '.join(updated)}")
        else:
            typer.echo("Units already up-to-date.")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

@app.command()
def doctor(as_json: bool = typer.Option(False, "--json")) -> None:
    """Run smoke checks (design doc §4.3). Exits 0 if all pass."""
    from ._runtime import wayland_env
    from .stack import Stack
    from .ipc import get_outputs

    checks: list[dict] = []

    def check(name: str, fn) -> bool:
        try:
            fn()
            checks.append({"name": name, "pass": True})
            return True
        except Exception as e:
            checks.append({"name": name, "pass": False, "error": str(e)})
            return False

    check(
        "sway-running",
        lambda: _assert(Stack.status()["sway"]["active_state"] == "active", "sway not active"),
    )
    check(
        "wayland-socket",
        lambda: _assert(Stack.status()["sway"]["socket_exists"], "wayland socket missing"),
    )

    def _vnc_port():
        with socket.create_connection(("127.0.0.1", 5900), timeout=2):
            pass
    check("wayvnc-port-open", _vnc_port)

    check(
        "sway-ipc-headless-output",
        lambda: _assert(
            any(o["name"] == "HEADLESS-1" for o in get_outputs()),
            "HEADLESS-1 output not found — sway may still be starting",
        ),
    )

    def _grim_capture():
        import subprocess
        out = Path("/tmp/understudy-doctor-check.png")
        r = subprocess.run(["grim", str(out)], capture_output=True, env=wayland_env())
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode().strip() or "grim returned non-zero")
        _assert(out.exists() and out.stat().st_size > 1000, "grim output too small")

    check("grim-capture", _grim_capture)

    all_pass = all(c["pass"] for c in checks)
    if as_json:
        typer.echo(_json_mod.dumps({"ok": all_pass, "checks": checks}, indent=2))
    else:
        for c in checks:
            mark = "✓" if c["pass"] else "✗"
            suffix = f"  — {c['error']}" if not c["pass"] else ""
            typer.echo(f"  {mark}  {c['name']}{suffix}")
    if not all_pass:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# act — input injection
# ---------------------------------------------------------------------------

act_app = typer.Typer(no_args_is_help=True, help="Inject synthetic input into the headless session.")
app.add_typer(act_app, name="act")


@act_app.command("click")
def act_click(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    button: str = typer.Option("left", "--button", "-b", help="left | right | middle"),
    delay: float = typer.Option(0.05, "--delay", help="Seconds between move and click."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Move pointer to (x, y) and click."""
    from .input import Compositor
    from .errors import UnderstudyError
    try:
        Compositor().click(x, y, button=button, delay=delay)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "x": x, "y": y, "button": button}))
    except UnderstudyError as e:
        _err(e, as_json)


@act_app.command("move")
def act_move(
    x: int = typer.Argument(...),
    y: int = typer.Argument(...),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Move the virtual pointer to absolute (x, y)."""
    from .input import Compositor
    from .errors import UnderstudyError
    try:
        Compositor().move(x, y)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "x": x, "y": y}))
    except UnderstudyError as e:
        _err(e, as_json)


@act_app.command("type")
def act_type(
    text: str = typer.Argument(..., help="Text to type via virtual keyboard."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Type a string of characters."""
    from .input import Compositor
    from .errors import UnderstudyError
    try:
        Compositor().type(text)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "typed": text}))
    except UnderstudyError as e:
        _err(e, as_json)


@act_app.command("key")
def act_key(
    keysym: str = typer.Argument(..., help="XKB keysym name, e.g. Return, Escape, space."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Press and release a single key."""
    from .input import Compositor
    from .errors import UnderstudyError
    try:
        Compositor().key(keysym)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "key": keysym}))
    except UnderstudyError as e:
        _err(e, as_json)


# ---------------------------------------------------------------------------
# scene — capture and comparison (capture only in Phase 2; waits/diff in Phase 4)
# ---------------------------------------------------------------------------

scene_app = typer.Typer(no_args_is_help=True, help="Capture and compare screen state.")
app.add_typer(scene_app, name="scene")


@scene_app.command("capture")
def scene_capture(
    out: str = typer.Option("", "--out", "-o", help="Output path. Default: state/frames/<timestamp>.png"),
    output_name: str = typer.Option("HEADLESS-1", "--output", help="Sway output name."),
    crop: str = typer.Option("", "--crop", help="Region as 'x,y WxH' (grim format)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Capture the headless display to a PNG. Prints the saved path."""
    from .capture import Screen
    from .errors import UnderstudyError
    try:
        region = None
        if crop:
            # Parse 'x,y WxH'
            try:
                pos, dim = crop.split()
                x, y = map(int, pos.split(","))
                w, h = map(int, dim.split("x"))
                region = (x, y, w, h)
            except Exception:
                typer.echo(f"Error: --crop must be 'x,y WxH', got: {crop!r}", err=True)
                raise typer.Exit(2)
        path = Screen().save(
            path=Path(out) if out else None,
            output=output_name,
            region=region,
        )
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "path": str(path)}))
        else:
            typer.echo(str(path))
    except UnderstudyError as e:
        _err(e, as_json)


# ---------------------------------------------------------------------------
# game — launch / kill / status
# ---------------------------------------------------------------------------

game_app = typer.Typer(no_args_is_help=True, help="Manage the game session.")
app.add_typer(game_app, name="game")


@game_app.command("launch")
def game_launch(
    slug_or_appid: str = typer.Argument(..., help="Profile slug (e.g. timberborn) or raw appid."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Launch a game. Accepts a profile slug or numeric appid."""
    from .session import GameSession
    from .profile import load_profile
    from .errors import UnderstudyError
    try:
        if slug_or_appid.isdigit():
            appid = int(slug_or_appid)
            session = GameSession(appid=appid)
        else:
            profile = load_profile(slug_or_appid)
            session = GameSession(
                appid=profile.appid,
                extra_gamescope_args=profile.extra_gamescope_args,
                width=profile.resolution[0],
                height=profile.resolution[1],
            )

        session.launch()
        if as_json:
            typer.echo(_json_mod.dumps({
                "ok": True,
                "unit": session.unit_name,
                "appid": session.appid,
            }))
        else:
            typer.echo(f"Game launched (unit: {session.unit_name})")
    except UnderstudyError as e:
        _err(e, as_json)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)


@game_app.command("kill")
def game_kill(
    grace: float = typer.Option(5.0, "--grace"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Kill the active game session (SIGTERM → SIGKILL → reset-failed)."""
    from .session import GameSession, active_unit_name
    from .errors import UnderstudyError
    name = active_unit_name()
    if name is None:
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "note": "no active game unit found"}))
        else:
            typer.echo("No active game session found.")
        return
    try:
        # Reconstruct session from unit name (unit name encodes appid)
        session = GameSession.__new__(GameSession)
        session.unit_name = name
        session._unit = None
        session.stop(grace=grace)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "killed": name}))
        else:
            typer.echo(f"Killed {name}.")
    except UnderstudyError as e:
        _err(e, as_json)


@game_app.command("is-running")
def game_is_running(as_json: bool = typer.Option(False, "--json")) -> None:
    """Exit 0 if a game session is active, 1 if not."""
    from .session import active_unit_name
    name = active_unit_name()
    active = name is not None
    if as_json:
        typer.echo(_json_mod.dumps({"ok": True, "active": active, "unit": name}))
    else:
        typer.echo("running" if active else "not running")
    if not active:
        raise typer.Exit(1)


@game_app.command("status")
def game_status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Show the active game session unit state."""
    from .session import active_unit_name
    try:
        name = active_unit_name()
    except UnderstudyError as e:
        _err(e, as_json)
        return
    data: dict = {"unit": name, "active": name is not None}
    if as_json:
        typer.echo(_json_mod.dumps(data))
    else:
        typer.echo(f"unit:   {name or '(none)'}")
        typer.echo(f"active: {data['active']}")


@game_app.command("list")
def game_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """List available game profiles."""
    from .profile import _PROJECT_ROOT
    games_dir = _PROJECT_ROOT / "games"
    profiles = sorted(
        d.name for d in games_dir.iterdir()
        if d.is_dir() and d.name != "_template" and (d / "profile.py").exists()
    )
    if as_json:
        typer.echo(_json_mod.dumps({"ok": True, "profiles": profiles}))
    else:
        for p in profiles:
            typer.echo(p)


@game_app.command("scaffold")
def game_scaffold(
    slug: str = typer.Argument(..., help="Short lowercase identifier for the game."),
    appid: int = typer.Option(..., "--appid", help="Steam appid."),
    display_name: str = typer.Option("", "--display-name"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Create a new game profile from the template."""
    import shutil
    from .profile import _PROJECT_ROOT

    dest = _PROJECT_ROOT / "games" / slug
    if dest.exists():
        typer.echo(f"Error: {dest} already exists.", err=True)
        raise typer.Exit(2)

    scaffold_src = Path(__file__).parent / "scaffold"
    name = display_name or slug.title()

    def _render(text: str) -> str:
        return text.replace("{{slug}}", slug).replace("{{appid}}", str(appid)).replace("{{display_name}}", name)

    # Copy scaffold, rendering templates.
    for src in scaffold_src.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(scaffold_src)
        dst_name = str(rel).replace(".in", "")
        dst = dest / dst_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(_render(src.read_text()))

    # Create empty refs dir.
    (dest / "refs").mkdir(exist_ok=True)

    steps = [
        f"1. `us game launch {slug}` and connect TigerVNC to :5900",
        "2. Navigate the game to its main menu",
        f"3. `us ref record main_menu --refs-dir games/{slug}/refs`",
        f"4. Fill in `coords` in games/{slug}/profile.py",
        f"5. `us run games/{slug}/tests/`",
    ]
    if as_json:
        typer.echo(_json_mod.dumps({"ok": True, "path": str(dest), "next_steps": steps}))
    else:
        typer.echo(f"Created: {dest}")
        typer.echo("Next steps:")
        for s in steps:
            typer.echo(f"  {s}")


@scene_app.command("wait-for")
def scene_wait_for(
    ref_name: str = typer.Argument(..., help="Reference name or path to a PNG."),
    timeout: float = typer.Option(90.0, "--timeout", "-t"),
    threshold: float = typer.Option(0.85, "--threshold"),
    poll: float = typer.Option(2.0, "--poll"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Block until a reference image appears on screen (or timeout)."""
    from .waits import for_template
    from .errors import UnderstudyError
    from pathlib import Path

    # Resolve: could be a name in the profile refs, or a bare path.
    ref: Path | str = Path(ref_name) if Path(ref_name).exists() else ref_name
    try:
        score, loc = for_template(ref, timeout=timeout, threshold=threshold, poll=poll)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True, "score": round(score, 4), "loc": list(loc)}))
        else:
            typer.echo(f"Matched (score={score:.3f} at {loc})")
    except UnderstudyError as e:
        _err(e, as_json)


@scene_app.command("wait-quiescent")
def scene_wait_quiescent(
    frames: int = typer.Option(5, "--frames", help="Consecutive identical frames to confirm quiescence."),
    poll: float = typer.Option(0.5, "--poll"),
    timeout: float = typer.Option(30.0, "--timeout"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Wait until the screen stops changing."""
    from .waits import for_quiescence
    from .errors import UnderstudyError
    try:
        for_quiescence(identical_frames=frames, poll=poll, timeout=timeout)
        if as_json:
            typer.echo(_json_mod.dumps({"ok": True}))
        else:
            typer.echo("Screen quiescent.")
    except UnderstudyError as e:
        _err(e, as_json)


@scene_app.command("diff")
def scene_diff(
    a: str = typer.Argument(..., help="First image path."),
    b: str = typer.Argument(..., help="Second image path."),
    method: str = typer.Option("template", "--method", "-m", help="template | phash | pixelmatch"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Compare two images. Exits 0 if similar, 4 if not."""
    from . import compare as cmp
    from .errors import UnderstudyError

    try:
        if method == "template":
            matched, score, loc = cmp.template(a, b)
            data = {"matched": matched, "score": round(score, 4), "loc": list(loc)}
        elif method == "phash":
            similar, dist = cmp.phash(a, b)
            data = {"similar": similar, "hamming_distance": dist}
        elif method == "pixelmatch":
            similar, ratio = cmp.pixelmatch(a, b)
            data = {"similar": similar, "diff_ratio": round(ratio, 4)}
        else:
            typer.echo(f"Unknown method: {method}", err=True)
            raise typer.Exit(2)

        similar = data.get("matched", data.get("similar", False))
        if as_json:
            typer.echo(_json_mod.dumps({"ok": similar, **data}))
        else:
            typer.echo(_json_mod.dumps(data, indent=2))
        if not similar:
            raise typer.Exit(4)
    except UnderstudyError as e:
        _err(e, as_json)


# ---------------------------------------------------------------------------
# ref — reference image management
# ---------------------------------------------------------------------------

ref_app = typer.Typer(no_args_is_help=True, help="Manage reference (golden) screenshots.")
app.add_typer(ref_app, name="ref")

_DEFAULT_REFS_DIR = Path(__file__).parent.parent.parent / "refs"


def _refs_dir() -> Path:
    _DEFAULT_REFS_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_REFS_DIR


@ref_app.command("record")
def ref_record(
    name: str = typer.Argument(..., help="Reference name (no extension)."),
    from_file: str = typer.Option("", "--from-file", help="Record from this PNG instead of screen."),
    refs_dir: str = typer.Option("", "--refs-dir", help="Override default refs directory."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Capture the current screen (or --from-file) and save as a reference."""
    from .refs import RefStore
    store = RefStore(refs_dir if refs_dir else _refs_dir())
    source = Path(from_file) if from_file else None
    p = store.record(name, source=source)
    if as_json:
        typer.echo(_json_mod.dumps({"ok": True, "name": name, "path": str(p)}))
    else:
        typer.echo(f"Recorded: {p}")


@ref_app.command("list")
def ref_list(
    refs_dir: str = typer.Option("", "--refs-dir"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List all reference images."""
    from .refs import RefStore
    store = RefStore(refs_dir if refs_dir else _refs_dir())
    names = store.list()
    if as_json:
        typer.echo(_json_mod.dumps({"ok": True, "refs": names}))
    else:
        for n in names:
            typer.echo(n)


@ref_app.command("show")
def ref_show(
    name: str = typer.Argument(...),
    refs_dir: str = typer.Option("", "--refs-dir"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Print the path to a reference image (useful for agents to Read it)."""
    from .refs import RefStore
    store = RefStore(refs_dir if refs_dir else _refs_dir())
    p = store.path(name)
    if as_json:
        typer.echo(_json_mod.dumps({"ok": p.exists(), "path": str(p), "exists": p.exists()}))
    else:
        typer.echo(str(p))


# ---------------------------------------------------------------------------
# run — pytest passthrough
# ---------------------------------------------------------------------------

@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    ctx: typer.Context = None,
    paths: list[str] = typer.Argument(default=None, help="Test paths passed to pytest."),
) -> None:
    """Run pytest with understudy fixtures pre-loaded. Extra pytest flags are passed through."""
    import subprocess
    import sys
    extra_args = ctx.args if ctx else []
    cmd = [sys.executable, "-m", "pytest"] + (paths or []) + extra_args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


if __name__ == "__main__":  # pragma: no cover
    app()
