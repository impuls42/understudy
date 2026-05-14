"""Timberborn game profile for understudy."""
from understudy.profile import GameProfile, Coords

PROFILE = GameProfile(
    slug="timberborn",
    appid=1062090,
    display_name="Timberborn",
    resolution=(1920, 1080),
    launch_timeout_s=120.0,  # first run after prefix warmup can be slow
    ready_ref="main_menu",   # GameSession waits for this ref before handing control
    extra_gamescope_args=["-f"],
    coords=Coords(
        # Filled in after recording refs from a live session.
        # Use `us scene capture` + VNC to find the correct coordinates.
    ),
)
