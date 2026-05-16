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
    best_score = -1.0
    best_loc: tuple[int, int] = (0, 0)
    last_frame: Image.Image | None = None

    while time.monotonic() < deadline:
        frame = screen.grab(output=output)
        last_frame = frame
        matched, score, loc = template_match(frame, ref, threshold=threshold)
        if score > best_score:
            best_score, best_loc = score, loc
        if matched:
            return score, loc
        time.sleep(poll)

    # On miss, save the last frame so the agent can inspect what the screen
    # actually looked like and compare against the (possibly stale) ref.
    saved_to: Path | None = None
    if last_frame is not None:
        try:
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            saved_to = Path("/tmp") / f"understudy-wait-miss-{ts}.png"
            last_frame.save(str(saved_to), format="PNG")
        except Exception:
            saved_to = None

    ref_name = (
        Path(ref).name if isinstance(ref, (str, Path)) else "<inline>"
    )
    hint_lines = [
        f"Best score was {best_score:.3f} at {best_loc} (threshold {threshold}).",
    ]
    if saved_to is not None:
        hint_lines.append(f"Current frame saved to {saved_to} — compare with the ref.")
    hint_lines.append(
        "If the score is high but below threshold, the screen drifted from the ref "
        "(re-record). If it's low, the screen is showing a different state."
    )
    raise UnderstudyTimeoutError(
        f"Template {ref_name!r} not matched within {timeout:.0f}s "
        f"(best score {best_score:.3f} < threshold {threshold}).",
        hint=" ".join(hint_lines),
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
