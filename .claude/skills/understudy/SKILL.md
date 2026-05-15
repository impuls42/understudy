---
name: understudy
description: >
  Use this skill whenever you need to control a headless game session on this
  machine: bring the Wayland stack up or down, launch/kill a Steam game through
  gamescope, capture screenshots, inject clicks/keys/text, wait for a game state
  to appear, record or compare reference images, or run game smoke tests with
  pytest. Activate for any prompt that involves: "start the game", "take a
  screenshot", "click <button>", "wait for the main menu", "record a ref",
  "run smoke tests", or anything that requires driving game UI programmatically.
license: MIT
compatibility: >
  Linux only; requires systemd user session, sway ≥ 1.9, gamescope ≥ 3.16,
  wayvnc, grim, wlrctl, Steam with the target game installed, Python ≥ 3.11,
  and uv. Designed for Claude Code.
metadata:
  author: impuls42
  version: "0.1"
allowed-tools: Bash Read Glob Grep
---

# understudy

understudy drives a headless Wayland session (sway → gamescope → Steam/Wine)
so you can launch games, capture screenshots, inject input, and assert UI state
— all from the terminal or from Python tests. The `us` CLI is the primary
interface; the Python SDK (`from understudy import ...`) is used inside pytest
suites in `games/<slug>/tests/`.

---

## Standard agent workflow

Follow these steps in order. Adjust as needed based on current state.

### 1. Check current state
```bash
us status          # stack health + active game unit
us game list       # available game profiles (slugs)
```

### 2. Bring up the stack (if not healthy)
```bash
us stack up        # starts sway + wayvnc; blocks until Wayland socket appears
```

### 3. Launch the game
```bash
us game launch timberborn      # use the profile slug
us game launch 1062090         # or raw Steam appid
```
The game takes 30–120 s to reach its main menu depending on whether the Steam
prefix is already warmed up.

### 4. See the current screen
```bash
us scene capture --out /tmp/screen.png
```
Then use the **Read** tool on `/tmp/screen.png` to view the screenshot visually.
This is the primary way to understand what state the game is in.

### 5. Inject input
```bash
us act click 960 406           # click at absolute pixel (x, y)
us act key Return              # press a key by XKB name
us act type "my settlement"    # type a string
us act move 500 300            # move pointer without clicking
```
All coordinates are absolute pixels within the **1920×1080** HEADLESS-1 output.

### 6. Wait for a game state
```bash
# Wait until a ref image appears (bare name resolved via --slug):
us scene wait-for main_menu --slug timberborn --timeout 120

# Or supply the full path directly:
us scene wait-for games/timberborn/refs/main_menu.png --timeout 120

# Wait until the screen stops changing:
us scene wait-quiescent --timeout 30
```

### 7. Record a reference image
```bash
# Interactive session (prompt → capture → confirm → repeat):
us ref record --slug timberborn

# Single shot:
us ref record main_menu --slug timberborn
```
Refs are stored at `games/<slug>/refs/<name>.png`.

### 8. Run smoke tests
```bash
us run games/timberborn/tests/          # runs pytest with game marker
us run games/timberborn/tests/ -k test_main_menu_appears
```

### 9. Clean up
```bash
us game kill       # SIGTERM → SIGKILL → reset-failed the game cgroup
us stack down      # stops wayvnc then sway
```

---

## Game profiles

Every supported game has a profile at `games/<slug>/profile.py` that declares:
- `appid` — Steam application ID
- `resolution` — capture/gamescope resolution (default 1920×1080)
- `coords` — named click targets (`PROFILE.coords.mm_new_game → (960, 406)`)
- `refs_dir` — path to the ref images directory
- `ready_ref` — name of the ref that signals the game reached its main menu
- `launch_timeout_s` — how long to wait for the ready ref

To inspect a profile:
```bash
python3 -c "from understudy.profile import load_profile; p = load_profile('timberborn'); print(p)"
```

---

## Python SDK pattern (for writing tests)

```python
from understudy import Stack, GameSession, Screen, waits, Compositor
from understudy.profile import load_profile

PROFILE = load_profile("timberborn")

with Stack():                                       # brings stack up; tears down on exit
    with GameSession(
        appid=PROFILE.appid,
        width=PROFILE.resolution[0],
        height=PROFILE.resolution[1],
        extra_gamescope_args=PROFILE.extra_gamescope_args,
    ) as session:
        # Wait for main menu
        score, loc = waits.for_template(
            PROFILE.refs.path(PROFILE.ready_ref),
            timeout=PROFILE.launch_timeout_s,
        )
        assert score >= 0.85

        # Click a button
        comp = Compositor()
        comp.click(*PROFILE.coords.mm_new_game)

        # Take a screenshot
        img = Screen().grab()              # → PIL.Image (RGBA, 1920×1080)
```

---

## Reading screenshots

The **Read** tool on any `.png` renders the image inline. Use this to verify
game state, inspect ref images, or debug unexpected UI:

```
Read: /tmp/screen.png
Read: games/timberborn/refs/main_menu.png
Read: state/frames/timberborn/<timestamp>.png
```

---

## Key notes

- **Session requirement**: `us` commands must run in the same login session that
  owns the systemd user units. Running from `su`/`sudo` or a separate shell
  without `DBUS_SESSION_BUS_ADDRESS` will produce a clean error with a hint.
- **All commands accept `--json`** for structured output usable in scripts.
- **Exit codes**: 0 ok · 2 precondition · 3 timeout · 4 template mismatch · 5 external command error
- **Template match threshold**: 0.85 (score below this = not matched)

For the full command listing with all options, read:
`.claude/skills/understudy/references/cli-reference.md`
