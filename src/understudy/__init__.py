"""understudy — headless game-mod CI runner.

Public SDK surface. Importable members are re-exported here so consumers write
`from understudy import Stack, GameSession, ...` rather than reaching into
submodules.

Submodules are populated in later implementation phases; this file grows to
match. Until then, only the items listed in `__all__` are guaranteed.
"""

from __future__ import annotations

from .errors import (
    ExternalCommandError,
    PreconditionError,
    TemplateMissError,
    TimeoutError as UnderstudyTimeoutError,
    UnderstudyError,
)

__all__ = [
    "UnderstudyError",
    "PreconditionError",
    "UnderstudyTimeoutError",
    "TemplateMissError",
    "ExternalCommandError",
]

__version__ = "0.1.0"
