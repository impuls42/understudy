"""Smoke tests for Timberborn."""
import pytest
from understudy import Stack, GameSession, Screen, waits, Compositor
from understudy.profile import load_profile

PROFILE = load_profile("timberborn")


@pytest.fixture(scope="module")
def game_session():
    with Stack():
        with GameSession(
            appid=PROFILE.appid,
            extra_gamescope_args=PROFILE.extra_gamescope_args,
            width=PROFILE.resolution[0],
            height=PROFILE.resolution[1],
        ) as session:
            yield session


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
    """Clicking Start should show loading screen then reach in-game view."""
    comp = Compositor()
    comp.click(*PROFILE.coords.flow_next)

    # Loading screen should appear first
    score, _ = waits.for_template(
        PROFILE.refs.path("loading_screen"),
        timeout=15.0,
    )
    assert score >= 0.85, f"Loading screen not found (score={score:.3f})"

    # Then in-game view (may show name-settlement dialog or game directly)
    score, _ = waits.for_template(
        PROFILE.refs.path("in_game"),
        timeout=60.0,
    )
    assert score >= 0.70, f"In-game view not reached (score={score:.3f})"


@pytest.mark.game
def test_screenshot_resolution(game_session):
    """Screen captures should be 1920×1080."""
    img = Screen().grab()
    assert img.width == 1920 and img.height == 1080
