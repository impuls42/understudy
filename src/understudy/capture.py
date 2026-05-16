"""Screen capture via grim → PIL/numpy.

Implements via grim over wlr-screencopy-v1. This is a wlroots-specific
protocol not shipped by pywayland; grim is the stable CLI for it. The
module wraps grim so callers receive PIL Images and numpy arrays directly.

Note (see plan §fallback policy): if pywayland gains wlr-screencopy support
the subprocess call can be replaced with a persistent screencopy client; the
public API is unchanged either way.
"""

from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import numpy as np
from PIL import Image

from ._runtime import wayland_env
from .errors import ExternalCommandError

# Default directory for screenshots saved to disk.
_STATE_FRAMES = Path(__file__).parent.parent.parent / "state" / "frames"


def _state_frames_dir() -> Path:
    _STATE_FRAMES.mkdir(parents=True, exist_ok=True)
    return _STATE_FRAMES


def _default_out_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return _state_frames_dir() / f"{ts}.png"


class Screen:
    """Screenshot driver for the headless sway session.

    Usage::

        screen = Screen()
        img = screen.grab()                     # → PIL.Image.RGBA
        arr = screen.grab_as_array()            # → np.ndarray HxWx4
        path = screen.save()                    # → Path, timestamped
        path = screen.save(Path("/tmp/foo.png"))
        region = screen.grab_region(100, 200, 400, 300)  # x, y, w, h
    """

    def grab(
        self,
        output: str = "HEADLESS-1",
        region: tuple[int, int, int, int] | None = None,
    ) -> Image.Image:
        """Capture the compositor output and return a PIL Image (RGBA).

        *output* names the sway output to capture (default HEADLESS-1).
        *region* is (x, y, width, height) in output pixels; None = full output.
        """
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = Path(f.name)
        try:
            # grim quirk: when both -o and -g are passed, -g is ignored and the
            # full output is captured. -g coords are in layout space, which on
            # our single-output headless setup equals output space, so drop
            # -o whenever a region is requested.
            args = ["grim"]
            if region:
                x, y, w, h = region
                args += ["-g", f"{x},{y} {w}x{h}"]
            elif output:
                args += ["-o", output]
            args.append(str(tmp))
            env = wayland_env()
            result = subprocess.run(args, env=env, capture_output=True)
            if result.returncode != 0:
                msg = result.stderr.decode().strip() or "grim failed"
                raise ExternalCommandError(
                    f"Screen capture failed: {msg}",
                    hint="Is the headless stack running? Try `us stack up`.",
                )
            return Image.open(tmp).convert("RGBA")
        finally:
            tmp.unlink(missing_ok=True)

    def grab_as_array(
        self,
        output: str = "HEADLESS-1",
        region: tuple[int, int, int, int] | None = None,
    ) -> np.ndarray:
        """Capture and return an HxWx4 uint8 numpy array (RGBA)."""
        return np.array(self.grab(output=output, region=region))

    def grab_region(self, x: int, y: int, w: int, h: int) -> Image.Image:
        """Capture a sub-region of HEADLESS-1."""
        return self.grab(output="HEADLESS-1", region=(x, y, w, h))

    def save(
        self,
        path: Path | str | None = None,
        output: str = "HEADLESS-1",
        region: tuple[int, int, int, int] | None = None,
    ) -> Path:
        """Capture and save to *path* (default: state/frames/<timestamp>.png).

        Returns the saved path (useful for the agent to read back).
        """
        out = Path(path) if path else _default_out_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        img = self.grab(output=output, region=region)
        img.save(str(out), format="PNG")
        return out
