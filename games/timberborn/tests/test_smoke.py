"""Smoke tests for Timberborn."""
import subprocess
import threading
import time

import pytest

from understudy import Stack, GameSession, Screen, waits, Compositor
from understudy.profile import load_profile

PROFILE = load_profile("timberborn")

# -----------------------------------------------------------------------
# Startup helper
# -----------------------------------------------------------------------

def _dismiss_mods_dialog(duration: float = 70.0, interval: float = 5.0) -> None:
    """Repeatedly click the mods-reorder dialog OK button until it clears.

    Timberborn shows a "Mods load order changed" dialog before the main menu.
    It appears ~30s after launch (after Steam store → game binary loads).
    This function clicks (960, 826) every *interval* seconds for *duration*
    seconds so we catch the dialog whenever it appears.  Clicks before and
    after the dialog are harmless.
    """
    import os
    from understudy.input import gamescope_x_display, game_window_id

    deadline = time.monotonic() + duration
    xd = win = None

    while time.monotonic() < deadline:
        if xd is None:
            xd = gamescope_x_display()
        if xd and win is None:
            win = game_window_id(xd)

        if xd and win:
            env = {**os.environ, "DISPLAY": xd}
            subprocess.run(["xdotool", "windowfocus", win], env=env, capture_output=True)
            subprocess.run(["xdotool", "mousemove", "960", "826"], env=env, capture_output=True)
            subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True)

        time.sleep(interval)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def game_session():
    """Launch Timberborn, dismiss any startup dialogs, yield the session."""
    with Stack():
        with GameSession(
            appid=PROFILE.appid,
            extra_gamescope_args=PROFILE.extra_gamescope_args,
            width=PROFILE.resolution[0],
            height=PROFILE.resolution[1],
        ) as session:
            # Click the mods-reorder dialog OK button in the background while
            # test_main_menu_appears polls for the main menu ref.  The dialog
            # appears ~30s after launch; clicking every 5s across a 70s window
            # guarantees we hit it regardless of exact timing.
            t = threading.Thread(target=_dismiss_mods_dialog, daemon=True)
            t.start()
            yield session


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------

@pytest.mark.game
def test_main_menu_appears(game_session):
    """Game should reach its main menu within launch_timeout_s."""
    score, loc = waits.for_template(
        PROFILE.refs.path(PROFILE.ready_ref),
        timeout=PROFILE.launch_timeout_s,
    )
    assert score >= 0.85, f"Main menu not found (score={score:.3f})"


@pytest.mark.game
def test_new_game_reaches_faction_select(game_session):
    """Clicking New Game should open the faction selection screen."""
    comp = Compositor()
    comp.click(*PROFILE.coords.mm_new_game)
    score, _ = waits.for_template(
        PROFILE.refs.path("faction_select"),
        timeout=15.0,
    )
    assert score >= 0.85, f"Faction select not found (score={score:.3f})"


@pytest.mark.game
def test_faction_next_reaches_map_select(game_session):
    """Clicking Next on faction select should show the map selection screen."""
    comp = Compositor()
    comp.click(*PROFILE.coords.flow_next)
    score, _ = waits.for_template(
        PROFILE.refs.path("map_select"),
        timeout=15.0,
    )
    assert score >= 0.85, f"Map select not found (score={score:.3f})"


@pytest.mark.game
def test_map_next_reaches_difficulty_select(game_session):
    """Clicking Next on map select should show the difficulty selection screen."""
    comp = Compositor()
    comp.click(*PROFILE.coords.flow_next)
    score, _ = waits.for_template(
        PROFILE.refs.path("difficulty_select"),
        timeout=15.0,
    )
    assert score >= 0.85, f"Difficulty select not found (score={score:.3f})"


@pytest.mark.game
def test_start_loads_game(game_session):
    """Clicking Start should show loading screen then the name-settlement dialog."""
    comp = Compositor()
    comp.click(*PROFILE.coords.flow_next)

    # Loading screen appears briefly
    score, _ = waits.for_template(
        PROFILE.refs.path("loading_screen"),
        timeout=20.0,
    )
    assert score >= 0.85, f"Loading screen not found (score={score:.3f})"

    # Name-settlement dialog appears on top of the game world once loaded.
    # It is a static UI element (more reliable than the animated game background).
    score, _ = waits.for_template(
        PROFILE.refs.path("name_settlement"),
        timeout=60.0,
    )
    assert score >= 0.85, f"Name-settlement dialog not found (score={score:.3f})"


@pytest.mark.game
def test_screenshot_resolution(game_session):
    """Screen captures should be 1920×1080."""
    img = Screen().grab()
    assert img.width == 1920 and img.height == 1080
