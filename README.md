# understudy

Headless game-mod CI runner for Proton/Steam games on Linux. Drives a
virtual display using sway + gamescope, injects synthetic input, captures
screenshots, and asserts UI state — all from Python or the `us` CLI.

**Designed to be driven by an AI coding agent.** Every command emits
structured JSON, every wait is explicit with a timeout, all artifacts land
at predictable paths an agent can `Read` directly.

---

## Host requirements

| Requirement | Notes |
|---|---|
| **Ubuntu 24.04** (or wlroots ≥ 0.18 / sway ≥ 1.9 distro) | Tested on Ubuntu 24.04 |
| **gamescope ≥ 3.16** | `sudo add-apt-repository ppa:3v1n0/gamescope && sudo apt install gamescope` |
| System packages | `sway cage seatd wayvnc grim wlrctl mesa-utils vulkan-tools` |
| **Vulkan-capable GPU** | Intel UHD 630 (ANV) verified; AMD/NVIDIA expected to work |
| User groups | `video`, `input`, `render` — `sudo usermod -aG video,input,render $USER` (re-login) |
| **Steam installed**, target game downloaded | Launch uses `steam://rungameid/<appid>` |
| **No other Steam running** at launch time | See "known issues" — pre-flight check enforced |
| Python ≥ 3.11 | Bundled via uv |
| TCP/5900 reachable (optional) | Only needed for human observation via TigerVNC |

**Validated hardware:** HP EliteDesk 800 G4 DM (i5-8500T, 16 GB, Intel UHD 630)

---

## One-time install

```bash
git clone <this-repo> ~/Documents/understudy
cd ~/Documents/understudy

# Install Python dependencies (creates .venv/)
pip install uv          # or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev

# Install the sway config
cp sway/headless.conf ~/.config/sway/headless.conf

# Register and start the systemd user units (done automatically by stack up too)
us stack install
```

---

## Agent quickstart (20 lines)

```bash
# 1. Bring up the headless Wayland stack
us stack up

# 2. Verify everything is healthy
us doctor

# 3. Launch the game (profile slug or numeric appid)
us game launch timberborn

# 4. Wait until the main menu is visible
us scene wait-for games/timberborn/refs/main_menu.png --timeout 120

# 5. Click something
us act click 960 540

# 6. Capture the result
us scene capture --json
# → {"ok": true, "path": "/path/to/state/frames/<timestamp>.png"}

# 7. Record a new reference
us ref record post_click --refs-dir games/timberborn/refs

# 8. Kill the game
us game kill

# 9. Tear down the stack
us stack down
```

All commands accept `--json` for machine-readable output.

---

## SDK usage

```python
from understudy import Stack, GameSession, Compositor, Screen, waits
from understudy.profile import load_profile

PROFILE = load_profile("timberborn")

with Stack(), GameSession(PROFILE) as game:
    # GameSession.enter() auto-waits for PROFILE.ready_ref before yielding
    waits.for_template(PROFILE.refs.path("main_menu"), timeout=120)
    Compositor().click(*PROFILE.coords.new_game_button)
    path = Screen().save(PROFILE.artifact_path("after_click.png"))
    # path is printed so an agent can Read the image
```

---

## Adding a new game

```bash
us game scaffold mygame --appid 99999
# → creates games/mygame/ with profile.py and tests/test_smoke.py
# → prints 5-step instructions
```

See `games/README.md` for the full walkthrough.

---

## CLI reference

```
us stack up/down/status/install   — headless stack lifecycle
us doctor                         — §4.3 smoke checks (exits 0 if all pass)
us act click/move/type/key        — synthetic input
us scene capture/wait-for/wait-quiescent/diff  — screen state
us ref record/list/show           — reference image management
us game launch/kill/is-running/status/list/scaffold  — game lifecycle
us run <path>                     — pytest passthrough
```

All commands: `--json` → structured stdout, non-zero exit → `{"ok":false,"code":N,"reason":"...","hint":"..."}`

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Precondition not met (stack not up, stray Steam process, etc.) |
| 3 | Timeout (wait-for exceeded) |
| 4 | Template not matched (scene diff / wait-for below threshold) |
| 5 | External command failure (grim, wlrctl) |

---

## Known issues / deferred items

1. **Stray Steam daemon**: if another Steam is running for this user when
   `us game launch` is called, the `steam://` URL will be forwarded to it and
   the game opens outside gamescope. The pre-flight check (`psutil`) catches
   this and exits with code 2. Fix: `pkill -u $USER steam` before launching.

2. **Sway socket numbering**: sway 1.9 uses auto-numbered sockets
   (`wayland-1`, `wayland-2`, …) regardless of `WAYLAND_DISPLAY`. The
   display name is discovered dynamically via socket mtime correlation, so
   it works correctly after each `stack up`. The `WaylandDisplay` in
   `stack status --json` shows the actual name in use.

3. **VNC client compatibility**: TigerVNC works. RealVNC Viewer and macOS
   Screen Sharing do not (RFB negotiation mismatch with wayvnc).

4. **Per-mod prefix isolation**: all tests share the warmed Proton prefix at
   `~/.steam/steam/steamapps/compatdata/<appid>`. Add per-test isolation if
   mod state bleeds across tests.

5. **pywayland fallback**: `zwlr_virtual_pointer_v1`, `zwlr_virtual_keyboard_v1`,
   and `wlr-screencopy-v1` bindings are not shipped by pywayland; this package
   uses subprocess wrappers (`wlrctl`, `grim`) for these protocols. The public
   API is identical regardless.

---

## Architecture

See `headless-game-ci-design.md` for the full design rationale, component
decisions, and key learnings from prototyping.
