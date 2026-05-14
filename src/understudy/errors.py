"""Exception hierarchy.

`.code` on each subclass matches the CLI exit code documented in the plan:

    0  ok
    2  precondition (stack not up, stray Steam, etc.)
    3  timeout
    4  template not matched
    5  external command failure
"""

from __future__ import annotations


class UnderstudyError(Exception):
    """Base for all errors raised by this package."""

    code: int = 1

    def __init__(self, reason: str, hint: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.hint = hint

    def as_dict(self) -> dict:
        return {"ok": False, "code": self.code, "reason": self.reason, "hint": self.hint}


class PreconditionError(UnderstudyError):
    code = 2


class TimeoutError(UnderstudyError):  # noqa: A001 — intentional shadow; never used as builtin here
    code = 3


class TemplateMissError(UnderstudyError):
    code = 4


class ExternalCommandError(UnderstudyError):
    code = 5
