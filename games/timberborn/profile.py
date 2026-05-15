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
        # Main menu buttons — all centered at x=960 (1920×1080 layout)
        mods_dialog_ok=(960, 826),      # "OK" on mod load-order dialog at startup
        settings_button=(960, 617),     # opens Settings panel from main menu
        settings_close=(1275, 252),     # X button to close Settings panel
        skip_intro_checkbox=(760, 406), # "Пропустити вступ" checkbox in Settings
    ),
)
