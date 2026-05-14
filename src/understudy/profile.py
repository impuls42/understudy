"""GameProfile: per-game configuration.

A GameProfile captures everything game-specific in one place:
  - Steam appid
  - Expected resolution
  - How long to wait for the game to reach its ready state
  - The reference image name that marks "ready" (auto-waited on GameSession enter)
  - Named coordinates for clickable UI elements
  - Per-game ref store directory

Usage::

    from understudy import load_profile
    profile = load_profile("timberborn")
    # or inline:
    profile = GameProfile(appid=1062090, slug="timberborn", ...)

Discovery: `load_profile("slug")` looks for `games/<slug>/profile.py` or
`games/<slug>/profile.toml` relative to the project root. The Python form is
preferred (allows code hooks); the TOML form is for simple declarative profiles.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .refs import RefStore


# Project root is three levels above this file.
_PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class Coords:
    """Named click coordinates for a game profile.

    Access as attributes::

        profile.coords.new_game_button  # → (x, y) tuple
    """
    _coords: dict[str, tuple[int, int]] = field(default_factory=dict)

    def __init__(self, **kwargs: tuple[int, int]) -> None:
        object.__setattr__(self, "_coords", kwargs)

    def __getattr__(self, name: str) -> tuple[int, int]:
        coords = object.__getattribute__(self, "_coords")
        if name in coords:
            return coords[name]
        raise AttributeError(f"No coordinate named {name!r}. Known: {list(coords)}")

    def all(self) -> dict[str, tuple[int, int]]:
        return dict(object.__getattribute__(self, "_coords"))


@dataclass
class GameProfile:
    """Full configuration for one game's test environment."""

    slug: str
    appid: int
    display_name: str = ""
    resolution: tuple[int, int] = (1920, 1080)
    launch_timeout_s: float = 90.0
    ready_ref: str | None = None  # waits.for_template against this on GameSession enter
    refs_dir: Path | None = None  # default: games/<slug>/refs
    coords: Coords = field(default_factory=Coords)
    extra_gamescope_args: list[str] = field(default_factory=lambda: ["-e", "-f"])

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.slug.title()
        if self.refs_dir is None:
            self.refs_dir = _PROJECT_ROOT / "games" / self.slug / "refs"

    @property
    def refs(self) -> RefStore:
        return RefStore(self.refs_dir)

    def artifact_path(self, name: str) -> Path:
        """Return a timestamped path under state/frames for saving artifacts."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out = _PROJECT_ROOT / "state" / "frames" / self.slug / f"{name}_{ts}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        return out


# ---------------------------------------------------------------------------
# Profile loader
# ---------------------------------------------------------------------------

def load_profile(slug: str) -> GameProfile:
    """Load a GameProfile from games/<slug>/profile.py (or .toml).

    The Python module must define a top-level `PROFILE` variable of type
    `GameProfile`. TOML support is handled as a fallback for simple profiles.
    """
    games_dir = _PROJECT_ROOT / "games"
    py_path = games_dir / slug / "profile.py"
    toml_path = games_dir / slug / "profile.toml"

    if py_path.exists():
        return _load_py_profile(py_path, slug)
    if toml_path.exists():
        return _load_toml_profile(toml_path, slug)

    available = sorted(d.name for d in games_dir.iterdir() if d.is_dir() and d.name != "_template")
    raise FileNotFoundError(
        f"No profile found for {slug!r} at {py_path} or {toml_path}. "
        f"Available: {available}. "
        f"Create one with `us game scaffold {slug} --appid <id>`."
    )


def _load_py_profile(path: Path, slug: str) -> GameProfile:
    spec = importlib.util.spec_from_file_location(f"_understudy_profile_{slug}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "PROFILE"):
        raise AttributeError(f"{path} must define a top-level `PROFILE = GameProfile(...)`")
    return mod.PROFILE


def _load_toml_profile(path: Path, slug: str) -> GameProfile:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    data = tomllib.loads(path.read_text())
    coords_raw: dict[str, Any] = data.pop("coords", {})
    coords = Coords(**{k: tuple(v) for k, v in coords_raw.items()})
    data["coords"] = coords
    data.setdefault("slug", slug)
    return GameProfile(**data)
