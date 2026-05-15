"""understudy — headless game-mod CI runner.

Public SDK surface. Import from here; don't reach into submodules directly.

Typical agent usage::

    from understudy import Stack, GameSession, Compositor, Screen, waits, load_profile

    PROFILE = load_profile("timberborn")

    with Stack(), GameSession(PROFILE.appid) as game:
        waits.for_template(PROFILE.refs.path(PROFILE.ready_ref), timeout=90)
        Compositor().click(*PROFILE.coords.new_game_button)
        Screen().save(PROFILE.artifact_path("post_click.png"))
"""

from __future__ import annotations

from .errors import (
    ExternalCommandError,
    PreconditionError,
    TemplateMissError,
    TimeoutError as UnderstudyTimeoutError,
    UnderstudyError,
)
from .stack import Stack
from .session import GameSession
from .input import Compositor
from .capture import Screen
from .refs import RefStore
from .profile import GameProfile, Coords, load_profile
from . import compare, waits

__all__ = [
    # Errors
    "UnderstudyError",
    "PreconditionError",
    "UnderstudyTimeoutError",
    "TemplateMissError",
    "ExternalCommandError",
    # SDK classes
    "Stack",
    "GameSession",
    "Compositor",
    "Screen",
    "RefStore",
    "GameProfile",
    "Coords",
    "load_profile",
    # Module namespaces
    "compare",
    "waits",
]

__version__ = "0.1.0"
