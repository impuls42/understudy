"""Blocking wait primitives.

All waits are synchronous with explicit timeouts and structured errors — agents
never need to sleep and guess. On success the function returns normally; on
timeout or mismatch it raises a typed UnderstudyError with a `hint` pointing
to the diagnostic path.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .capture import Screen
from .compare import template as template_match, is_frozen
from .errors import TemplateMissError, TimeoutError as UnderstudyTimeoutError

# Re-export so callers can write `from understudy import waits; waits.for_template(...)`
__all__ = [
    "for_template",
    "for_quiescence",
    "for_condition",
]


def for_template(
    ref: Path | str | Image.Image | np.ndarray,
    timeout: float = 90.0,
    threshold: float = 0.85,
    poll: float = 2.0,
    output: str = "HEADLESS-1",
) -> tuple[float, tuple[int, int]]:
    """Poll grim every *poll* seconds until *ref* is visible on screen.

    Returns (score, (x, y)) on success.
    Raises UnderstudyTimeoutError if *timeout* seconds elapse without a match.
    Raises TemplateMissError if the ref cannot be loaded.
    """
    if isinstance(ref, (str, Path)):
        ref_path = Path(ref)
        if not ref_path.exists():
            raise TemplateMissError(
                f"Reference image not found: {ref_path}",
                hint=f"Record it first: `us ref record {ref_path.stem}`.",
            )

    screen = Screen()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        frame = screen.grab(output=output)
        matched, score, loc = template_match(frame, ref, threshold=threshold)
        if matched:
            return score, loc
        time.sleep(poll)

    raise UnderstudyTimeoutError(
        f"Template not matched within {timeout:.0f}s (best score < {threshold}).",
        hint="Check `us scene capture` to see current screen state.",
    )


def for_quiescence(
    identical_frames: int = 5,
    poll: float = 0.5,
    timeout: float = 30.0,
    output: str = "HEADLESS-1",
) -> None:
    """Wait until the screen stops changing.

    Polls every *poll* seconds. Returns once *identical_frames* consecutive
    frames have identical perceptual hashes (i.e. the UI has settled).
    Useful after clicking to wait for transitions to complete.
    """
    screen = Screen()
    buffer: list[Image.Image] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        frame = screen.grab(output=output)
        buffer.append(frame)
        if len(buffer) > identical_frames:
            buffer.pop(0)
        if len(buffer) >= identical_frames and is_frozen(buffer, identical_frames):
            return
        time.sleep(poll)

    raise UnderstudyTimeoutError(
        f"Screen did not quiesce within {timeout:.0f}s.",
        hint="The game may be loading or animating indefinitely.",
    )


def for_condition(
    fn: Callable[[], bool],
    timeout: float = 30.0,
    poll: float = 0.5,
    description: str = "condition",
) -> None:
    """Wait until *fn()* returns True.

    Generic building block for non-screen conditions (unit state, file
    presence, etc.). Raises UnderstudyTimeoutError on expiry.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(poll)
    raise UnderstudyTimeoutError(
        f"Timed out waiting for {description} after {timeout:.0f}s.",
    )
