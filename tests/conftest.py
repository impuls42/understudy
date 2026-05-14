"""Shared pytest fixtures for understudy tests.

Session-scoped fixtures that manage the headless stack and game lifetime.
Import these in game-specific test files; they're auto-discovered by pytest
because this file is in the root tests/ dir.
"""

from __future__ import annotations

import pytest

from understudy import Stack
from understudy.capture import Screen
from understudy.input import Compositor
from understudy.session import GameSession


@pytest.fixture(scope="session", autouse=False)
def stack():
    """Bring the headless Wayland stack up for the test session."""
    with Stack() as s:
        yield s


@pytest.fixture(scope="module")
def compositor():
    """Return a Compositor bound to the live headless session."""
    return Compositor()


@pytest.fixture(scope="module")
def screen():
    """Return a Screen bound to the live headless session."""
    return Screen()
