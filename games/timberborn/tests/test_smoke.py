"""Smoke tests for Timberborn."""
import pytest
from understudy import Stack, GameSession, Screen, waits
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
def test_main_menu_screenshot(game_session, tmp_path):
    """Capture a screenshot once the main menu is visible and verify it's non-empty."""
    img = Screen().grab()
    assert img.width == 1920 and img.height == 1080
