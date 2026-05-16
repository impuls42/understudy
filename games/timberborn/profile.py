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
        # Startup
        mods_dialog_ok=(960, 826),      # "OK" on mod load-order dialog at startup

        # Save-load mod-mismatch dialog (appears after clicking Continue when
        # the save's mod set differs from the active set). Pressing Return
        # also confirms (defaults to Так / Yes).
        mods_mismatch_no=(865, 775),    # Ні — cancel load
        mods_mismatch_yes=(1049, 775),  # Так — proceed with active mods

        # Main menu buttons (all x=960, measured from pixel analysis)
        mm_continue=(960, 365),         # Продовжити
        mm_new_game=(960, 406),         # Нова гра
        mm_load_game=(960, 448),        # Завантажити гру
        mm_create_map=(960, 492),       # Створити нову карту
        mm_edit_map=(960, 534),         # Редагувати карту
        mm_mods=(960, 573),             # Моди
        mm_settings=(960, 616),         # Налаштування (confirmed)
        mm_credits=(960, 658),          # Автори
        mm_quit=(960, 784),             # Вийти з гри

        # Settings panel
        settings_close=(1275, 252),     # X button to close Settings panel
        skip_intro_checkbox=(760, 406), # "Пропустити вступ" checkbox in Settings

        # New-game flow navigation buttons (Назад / Далі / Почати share same y=900)
        flow_back=(860, 900),           # Назад (Back) in faction/map/difficulty screens
        flow_next=(1060, 900),          # Далі (Next) / Почати (Start)

        # Faction selection (x≈710 for both factions; y varies)
        faction_folktails=(742, 900),   # left faction icon (Хвостоногодів / Folktails)
        faction_ironteeth=(1100, 900),  # right faction icon (Залізнозубих / Ironteeth)

        # Difficulty selection
        difficulty_easy=(710, 470),     # Легко
        difficulty_normal=(710, 563),   # Нормально
        difficulty_hard=(710, 654),     # Складно

        # Map selection — click map name row to select, then flow_next to confirm
        map_waterfalls=(350, 421),      # Водоспади 128×128 (tutorial)
        map_lakes=(350, 457),           # Озера 256×256
        map_plains=(350, 493),          # Рівнина 256×256
        map_river_bend=(350, 529),      # Вигин річки 128×128
        map_ironworks=(350, 565),       # Вироби 192×192
        map_mountain_ridge=(350, 601),  # Гірський хребет 256×256
        map_canyon=(350, 637),          # Каньйон 128×128
        map_craters=(350, 673),         # Кратери 192×192
        map_spiral_mountain=(350, 709), # Спіральна гора 256×256
        map_terraces=(350, 745),        # Тераси 256×256
        map_thousand_islands=(350, 781),# Тисяча островів 256×256
        map_cliff=(350, 817),           # Урвище 256×256

        # Name-settlement dialog (appears on first game launch after map load)
        name_settlement_input=(960, 838),  # text input field center
        name_settlement_confirm=(960, 892),# Вперед! button
    ),
)
