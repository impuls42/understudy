"""Reference image store.

References are PNG files stored in a per-profile directory (typically
`games/<slug>/refs/`). The RefStore class provides a simple record/load/list
interface so agents can build and retrieve their golden screenshots without
knowing the on-disk layout.

Usage::

    store = RefStore("games/timberborn/refs")
    path = store.record("main_menu", screen_image)   # saves PNG, returns Path
    ref = store.load("main_menu")                     # returns PIL.Image
    names = store.list()                              # ['main_menu', ...]
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .capture import Screen


class RefStore:
    """Manages reference (golden) screenshots for one game profile."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.png"

    def record(
        self,
        name: str,
        source: Path | str | Image.Image | np.ndarray | None = None,
    ) -> Path:
        """Save a reference image.

        If *source* is None, captures the current screen via grim.
        Returns the saved Path.
        """
        dest = self._path(name)
        if source is None:
            Screen().save(path=dest)
            return dest
        if isinstance(source, (str, Path)):
            img = Image.open(str(source)).convert("RGBA")
        elif isinstance(source, np.ndarray):
            img = Image.fromarray(source)
        else:
            img = source.convert("RGBA")
        img.save(str(dest), format="PNG")
        return dest

    def load(self, name: str) -> Image.Image:
        """Load a reference image by name. Raises FileNotFoundError if absent."""
        p = self._path(name)
        if not p.exists():
            raise FileNotFoundError(
                f"Reference '{name}' not found in {self.directory}. "
                f"Create it with `us ref record {name}`."
            )
        return Image.open(str(p)).convert("RGBA")

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def list(self) -> list[str]:
        """Return sorted list of reference names (filenames without .png)."""
        return sorted(p.stem for p in self.directory.glob("*.png"))

    def path(self, name: str) -> Path:
        """Return the on-disk path for a reference name (may not exist yet)."""
        return self._path(name)
