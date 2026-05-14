# Adding a game to understudy

Each game lives in its own directory under `games/<slug>/`:

```
games/
  timberborn/           ← example
    profile.py          ← GameProfile definition
    refs/               ← golden screenshots (PNG)
    tests/
      test_smoke.py     ← pytest tests
```

## 5-step quickstart

### 1. Scaffold

```bash
us game scaffold <slug> --appid <steam-appid>
```

This creates `games/<slug>/` with a template `profile.py` and `tests/test_smoke.py`.

### 2. Launch and observe

```bash
us stack up
us game launch <slug>
# Connect TigerVNC to :5900 and navigate the game to its main menu
```

### 3. Record the main-menu reference

```bash
us ref record main_menu --refs-dir games/<slug>/refs
```

### 4. Record coordinates

With TigerVNC open and the game at the main menu, note the pixel coordinates of
any UI elements you want to click. Add them to `games/<slug>/profile.py` in the
`Coords(...)` section:

```python
coords=Coords(
    new_game_button=(960, 540),
    mods_button=(960, 620),
),
```

### 5. Run

```bash
us run games/<slug>/tests/
```

## Profile reference

```python
PROFILE = GameProfile(
    slug="mygame",
    appid=12345,
    display_name="My Game",
    resolution=(1920, 1080),      # must match the gamescope -W/-H flags
    launch_timeout_s=90.0,        # how long until main_menu ref is expected
    ready_ref="main_menu",        # auto-waited on GameSession enter
    extra_gamescope_args=["-e", "-f"],  # -e for Steam integration, -f for fullscreen
    coords=Coords(
        some_button=(x, y),
    ),
)
```

## Notes

- Refs live in `games/<slug>/refs/` as PNG files; filenames are the reference names.
- `load_profile("<slug>")` discovers `profile.py` or `profile.toml` automatically.
- `GameSession(PROFILE)` pre-flights, launches, and auto-waits for `ready_ref`.
- See `src/understudy/scaffold/` for the template files used by `us game scaffold`.
