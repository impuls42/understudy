# Headless Game Mod Testing on Ubuntu 24.04

A reproducible CI pipeline for launching a Proton-via-Steam game in a headless
Linux environment, driving its UI with synthetic input, and validating mod load
behavior via screenshot comparison.

---

## 1. Goals and constraints

| | |
|---|---|
| **Game** | Steam title, runs fine via Proton, no anti-cheat, offline, slow-paced |
| **Test scope** | Launch session → click predetermined points → capture screenshots → compare against reference |
| **Host** | HP EliteDesk 800 G4 DM, Ubuntu 24.04, Intel UHD 630, no physical display |
| **Performance** | Not a constraint — game is light and the box has time |
| **Non-goals** | Real-time perf, parallel test runs, multi-user sessions |

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Ubuntu 24.04 (headless host)                  │
│                                                                  │
│   ┌────────────────────────────────────────────────────────┐    │
│   │             sway (WLR_BACKENDS=headless)               │    │
│   │     WAYLAND_DISPLAY=wayland-headless                   │    │
│   │                                                         │    │
│   │   • virtual output HEADLESS-1 (1920x1080)              │    │
│   │   • zwlr_virtual_pointer_v1                            │    │
│   │   • zwlr_virtual_keyboard_v1                           │    │
│   │   • wlr-screencopy-v1                                  │    │
│   │                                                         │    │
│   │   ┌─────────────────────────────────────────────┐      │    │
│   │   │  gamescope (nested Wayland client)          │      │    │
│   │   │  WAYLAND_DISPLAY=gamescope-0                │      │    │
│   │   │  ┌──────────────────────────────────────┐   │      │    │
│   │   │  │  Proton  →  game.exe                 │   │      │    │
│   │   │  └──────────────────────────────────────┘   │      │    │
│   │   └─────────────────────────────────────────────┘      │    │
│   └────────────────────────────────────────────────────────┘    │
│        ▲                ▲                 ▲                      │
│        │ frames+input   │ frames          │ pointer/keyboard     │
│        │                │                 │                      │
│   ┌────┴─────┐    ┌─────┴────┐      ┌─────┴────┐                 │
│   │  wayvnc  │    │   grim   │      │  wlrctl  │                 │
│   │  :5900   │    │  (PNG)   │      │          │                 │
│   └────┬─────┘    └────▲─────┘      └────▲─────┘                 │
│        │               │                 │                       │
│        │          ┌────┴─────────────────┴─────┐                 │
│        │          │   pytest test harness      │                 │
│        │          │   (image diff + control)   │                 │
│        │          └────────────────────────────┘                 │
│        │                                                         │
└────────┼─────────────────────────────────────────────────────────┘
         │ RFB
         ▼
   ┌─────────────┐
   │  TigerVNC   │   developer machine — observe/hijack
   │  on macOS   │
   └─────────────┘
```

The single design idea worth emphasizing: **every layer in this stack
communicates over Wayland protocols, not over the kernel input subsystem.**
That choice flows from how Proton + gamescope + Wayland-native compositors
actually receive input from their parent — discussed in §5.

---

## 3. Component decisions

### 3.1 Display surface — sway in headless mode

A "virtual display" is provided by sway running with `WLR_BACKENDS=headless`.
Picked over alternatives because:

- **Xvfb**: no GPU acceleration, X11-only, awkward fit for Wayland-first tools
- **Xorg + dummy driver**: workable, but doubles down on X11 in a Wayland-native
  game world
- **gamescope `--headless`**: gamescope by itself with `--headless` has no
  output backend at all — designed for "no display *anywhere*". Useful as a
  primitive, but inconvenient for hijacking/observation.
- **cage**: viable single-app alternative to sway. We chose sway for IPC
  ergonomics (`swaymsg -t get_inputs/get_outputs`).

Sway is started with a deterministic display name so other components don't
need a discovery dance, and with a minimal config that removes all window
decorations (every pixel goes to the game):

```bash
# ~/.config/sway/headless.conf
default_border none
default_floating_border none
hide_edge_borders --i3 both
for_window [app_id="gamescope"] border none, fullscreen enable
for_window [class="gamescope"] border none, fullscreen enable
for_window [app_id=".*"] border none
for_window [class=".*"] border none
exec swaymsg "output * adaptive_sync off"
```

```bash
WLR_BACKENDS=headless \
WAYLAND_DISPLAY=wayland-headless \
  sway -c ~/.config/sway/headless.conf
```

Sway rejects `0` for `titlebar_padding` and font size — `default_border none`
makes those unnecessary anyway since the title bar disappears with the border.

### 3.2 Game compositor — gamescope nested inside sway

Gamescope is run as a normal Wayland client inside sway. It provides exactly
the same compositor the game would see on a Steam Deck — Vulkan-first, sane
resolution handling, well-tested with Proton.

```bash
SDL_VIDEODRIVER=wayland \
WAYLAND_DISPLAY=wayland-headless \
  gamescope -W 1920 -H 1080 -- \
  proton run /path/to/game.exe
```

`SDL_VIDEODRIVER=wayland` is required because gamescope uses SDL2 to interact
with its parent compositor, and SDL's auto-detection misbehaved in our setup
(fell back to the `offscreen` driver which has no Vulkan loader).

### 3.3 Input injection — wlrctl over zwlr_virtual_pointer_v1

`wlrctl` talks to sway via the wlroots virtual pointer/keyboard protocols.
Absolute positioning, no calibration, idempotent.

```bash
WAYLAND_DISPLAY=wayland-headless wlrctl pointer move 640 480
WAYLAND_DISPLAY=wayland-headless wlrctl pointer click left
WAYLAND_DISPLAY=wayland-headless wlrctl keyboard type "ok"
```

**Crucially, kernel-level uinput injection does NOT work in this topology.**
See §5 for the full explanation.

### 3.4 Screen capture — grim

```bash
WAYLAND_DISPLAY=wayland-headless grim /tmp/frame.png
```

Uses `wlr-screencopy-v1`, captures the composited output as PNG. Sub-second on
this hardware at 1080p.

### 3.5 Remote viewing — wayvnc + TigerVNC

`wayvnc` exposes sway's framebuffer over RFB and accepts mouse/keyboard input
through the same `zwlr_virtual_pointer_v1` protocol. So a human at TigerVNC and
the automation harness via `wlrctl` use the same input channel — symmetrical
and predictable.

```bash
WAYLAND_DISPLAY=wayland-headless \
XDG_RUNTIME_DIR=/run/user/$(id -u) \
  wayvnc 0.0.0.0 5900
```

**Client compatibility note.** RealVNC Viewer and macOS Screen Sharing both
have RFB-level disagreements with wayvnc. TigerVNC works out of the box.

### 3.6 Game launch — Steam URL handler

Decided on `steam steam://rungameid/<appid>` after a successful end-to-end
launch. Proton-direct invocation is also viable but adds bookkeeping
(`STEAM_COMPAT_*` envs, locating Proton, prefix paths) for no benefit in the
slow-cozy-game case.

```bash
gamescope -W 1920 -H 1080 -e -f -- \
  steam steam://rungameid/<appid>
```

`-e` enables gamescope's Steam integration; `-f` forces fullscreen.

**Wrinkle worth knowing**: the `steam` URL launcher always exits immediately —
its job is to *hand off* the URL to a running Steam daemon. If a Steam daemon
is already running elsewhere on the box (e.g. on the GDM session on TTY2), the
hand-off goes there and the game launches in *that* environment, not in our
gamescope. Symptoms: gamescope shows "Primary child shut down!" and the game
window never appears.

For deterministic CI, set up a **dedicated Steam install for the headless
session** (separate `~/.local/share/Steam-headless` or similar), and make
sure no other Steam is running at launch time:

```bash
pgrep -af steam     # should be empty before launching
```

This is the topic of an open item in §7.

First Proton run per prefix is slow (prefix creation, shader cache warmup ~30–
60s). Bake a warmed prefix into the box's base state so this only happens
once.

### 3.7 Screenshot comparison — TBD

Three flavors, pick per assertion type:
- **Crash/hang detection**: hash consecutive frames, alert if N identical frames
- **"Mod loaded" smoke test**: perceptual hash (`imagehash` Python lib) against
  reference — robust to rendering jitter
- **UI element present**: template matching (`cv2.matchTemplate`) on a sub-region
  containing a known UI element (mod menu entry, version string overlay)

For mod testing, template matching is usually the right tool — survives
weather/time-of-day variance in the game.

### 3.8 Test orchestration — pytest

Each mod becomes a test case. Per-test setup: warm prefix, launch game, wait
for known main-menu signature via template match, then perform the test's
click sequence. Per-test teardown: kill game process, snapshot logs.

### 3.9 Game lifecycle — systemd-run --scope

Verified the hard way: SIGTERM to the gamescope process does *not* shut down
the game. Gamescope's actual process tree is:

```
gamescope
└─ gamescopereaper
   └─ steam (URL handler) ──exits─→ Steam daemon ──launches─→ game
```

The URL handler is the "primary child" gamescope tracks, and it exits
immediately after handing off. The game is then a great-grandchild of Steam
(not of gamescope), so signals to gamescope never reach it. SIGTERM on the
gamescope PID hangs waiting for an Xwayland teardown that never completes;
SIGKILL on `gamescopereaper` is what actually unsticks things.

The clean fix is to put the whole launch inside a transient systemd scope.
All descendants live in one cgroup; `systemctl kill` nukes the cgroup
atomically, no signal-propagation games:

```bash
# launch
systemd-run --user --scope --unit=mod-test \
  --property=Delegate=yes \
  bash -c '
    exec gamescope -W 1920 -H 1080 -e -f -- \
      steam steam://rungameid/<appid>
  '

# stop, from any other shell
systemctl --user kill mod-test.scope --signal=SIGTERM
sleep 3
systemctl --user kill mod-test.scope --signal=SIGKILL 2>/dev/null
systemctl --user reset-failed mod-test.scope 2>/dev/null
```

`Delegate=yes` keeps systemd from interfering with the scope's internal
cgroup management. The Python wrapper for this lives in §6.

---

## 4. Setup procedure

Steps actually walked through during prototyping.

### 4.1 One-time host setup

```bash
# gamescope (not in 24.04 repos for amd64)
sudo add-apt-repository ppa:3v1n0/gamescope
sudo apt update

# everything else
sudo apt install \
  gamescope mesa-utils vulkan-tools \
  sway cage seatd wayvnc grim wlrctl \
  python3-evdev

# seatd was auto-started by package; verify
systemctl status seatd
# socket gated by 'video' group — user must be in it
sudo usermod -aG video,input,render $USER
# (then log out and back in)
```

Notes:
- The Ubuntu `ydotool` package only ships the client (no `ydotoold`). Since
  we settled on `wlrctl` over uinput, this is moot.
- `uinput` is built into the kernel (`CONFIG_INPUT_UINPUT=y`) on Ubuntu 24.04
  generic — no module load needed.

### 4.2 Per-boot stack startup

Today this is manual; eventually a systemd user service. The sequence:

```bash
# sway with a fixed socket name and our headless config
WLR_BACKENDS=headless \
WAYLAND_DISPLAY=wayland-headless \
  sway -c ~/.config/sway/headless.conf > /tmp/sway.log 2>&1 &
sleep 1
export WAYLAND_DISPLAY=wayland-headless
export SWAYSOCK=$(ls /run/user/$(id -u)/sway-ipc.*.sock | tail -1)

# resize the virtual output if desired
swaymsg output HEADLESS-1 mode 1920x1080@60Hz

# remote viewer
wayvnc 0.0.0.0 5900 &
```

### 4.3 Smoke tests (all confirmed passing on the prototype host)

```bash
# 1. sway up?
swaymsg -t get_outputs        # → HEADLESS-1

# 2. VNC up?
ss -lpn | grep 5900           # → wayvnc listening

# 3. gamescope + vulkan?
SDL_VIDEODRIVER=wayland gamescope -W 1280 -H 720 -- vkcube
# → cube visible over VNC

# 4. input injection reaches sway?
wlrctl pointer move 500 500
wlrctl pointer click left
# → cursor moves and click registers in VNC view

# 5. capture works?
grim /tmp/check.png
file /tmp/check.png           # → PNG, expected dimensions

# 6. systemd-run --scope lifecycle works?
systemd-run --user --scope --unit=test-cycle --property=Delegate=yes \
  bash -c 'exec gamescope -W 1280 -H 720 -- vkcube' &
sleep 3
systemctl --user kill test-cycle.scope --signal=SIGKILL
pgrep -af gamescope           # → empty
pgrep -af vkcube              # → empty

# 7. input passes THROUGH gamescope to a nested client?
SDL_VIDEODRIVER=wayland gamescope -W 1280 -H 720 -- foot &
sleep 2
WAYLAND_DISPLAY=wayland-headless \
  wlrctl keyboard type "echo passthrough > /tmp/proof"
sleep 1
cat /tmp/proof                # → "passthrough"

# 8. end-to-end mini-cycle (game launch + capture + click + teardown)
systemd-run --user --scope --unit=game-test --property=Delegate=yes \
  bash -c 'exec gamescope -W 1920 -H 1080 -e -f -- steam steam://rungameid/<appid>' &
sleep 60                      # wait for main menu (template-match it later)
grim /tmp/menu.png
wlrctl pointer move 960 540 && wlrctl pointer click left
sleep 5
grim /tmp/post-click.png
systemctl --user kill game-test.scope --signal=SIGTERM
sleep 3
systemctl --user kill game-test.scope --signal=SIGKILL 2>/dev/null
```

---

## 5. Key learnings (the "why" of this design)

### 5.1 Wayland sockets are not `.sock` files

`/run/user/<uid>/wayland-N` is the socket, `wayland-N.lock` is its lock file —
no extension on the socket itself. Sway IPC sockets, in contrast, *are* named
`sway-ipc.<uid>.<pid>.sock`. Don't conflate them in discovery scripts.

### 5.2 Headless sway ignores libinput by default

With `WLR_BACKENDS=headless`, wlroots does not include a libinput device
source. This means:

- A virtual mouse created via `/dev/uinput` is visible to `libinput list-devices`
- It is **not visible** to `swaymsg -t get_inputs`
- Events sent to it never reach sway, gamescope, or the game

This bit us before we figured out the wlr-virtual-pointer protocol is the
correct channel. To enable libinput in addition, run sway with
`WLR_BACKENDS=headless,libinput` — but for Wayland-native games this is
unnecessary, and adding it pulls in any physical keyboard/mouse on the host.

### 5.3 uinput is the wrong layer for this stack

This was the deepest learning. Three layers can carry input:

| Layer | Reaches | When useful |
|---|---|---|
| `/dev/uinput` → evdev | Apps that read `/dev/input/event*` directly (some native Linux games via SDL2 evdev backend) | Native Linux games, low-level testing |
| libinput | wlroots compositors with libinput backend enabled | Hybrid setups with physical and virtual devices mixed |
| `zwlr_virtual_pointer_v1` (Wayland protocol) | Any wlroots-based compositor (sway, gamescope) | **Wayland-native stacks. This is our case.** |

For Steam + Proton + gamescope under sway, the input chain is:
`source → sway → gamescope → XWayland/SDL → game`. All Wayland. uinput is
never read directly. So the right channel is the Wayland protocol — same one
wayvnc uses to forward your mouse from TigerVNC.

### 5.4 SDL needs to be told it's on Wayland

gamescope embeds SDL2 to talk to its parent compositor. SDL's auto-detection
picked the `offscreen` driver (which has no Vulkan support) in our environment.
Setting `SDL_VIDEODRIVER=wayland` explicitly was needed.

### 5.5 wayvnc has client compatibility quirks

- ✅ **TigerVNC viewer** — works
- ❌ **RealVNC Viewer** — `ZlibInStream inflate failed with error -3`, encoding
  negotiation mismatch
- ❌ **macOS Screen Sharing** — Apple's client wants a security type wayvnc
  doesn't offer by default

Stick with TigerVNC unless you configure wayvnc auth specifically.

### 5.6 GDM may already hold `wayland-0`

If the host has GDM and a user with auto-login or a desktop session, GDM's
GNOME session occupies `wayland-0`. The headless sway will pick the next
free name (`wayland-1`, etc), which is why we set `WAYLAND_DISPLAY` explicitly
*before* starting sway — sway honors the env var and creates that exact
socket name.

### 5.7 Gamescope's process tree fights you on shutdown

Gamescope spawns `gamescopereaper`, which spawns the "primary child". With
`-- steam steam://rungameid/<id>`, the primary child is the `steam` URL
handler — which exits almost immediately after forwarding the URL to the
Steam daemon. The actual game ends up as a descendant of Steam, not of
gamescope. Three downstream consequences:

- SIGTERM to gamescope hangs (waiting on an Xwayland teardown that doesn't
  arrive). SIGKILL to `gamescopereaper` is what worked manually.
- "Primary child shut down!" appears in gamescope's log within seconds of
  launch, even though the game is running fine — it's referring to the URL
  handler, not the game.
- pkill-by-name is unreliable because the process tree is split across two
  parents (gamescope and Steam).

This is why §3.9 lives on `systemd-run --scope`: it puts everything in one
cgroup and lets `systemctl kill` ignore the topology entirely.

### 5.8 grim's "what to capture" model

grim has no notion of "the screen". It connects to whatever compositor is at
`$WAYLAND_DISPLAY`, asks via `wlr-screencopy-v1` for the contents of each
output the compositor advertises, and concatenates them into one PNG. Pick a
specific output with `-o HEADLESS-1`; crop with `-g "x,y wxh"`. There is no
"primary monitor" concept — the env var fully determines what's captured.

---

## 6. Test harness sketch (not yet implemented)

```python
import os, subprocess, time
from pathlib import Path


WL_ENV = {**os.environ, "WAYLAND_DISPLAY": "wayland-headless"}


class Compositor:
    """Wraps wlrctl + grim for the test layer."""
    def click(self, x: int, y: int, button: str = "left"):
        subprocess.run(["wlrctl", "pointer", "move", str(x), str(y)],
                       env=WL_ENV, check=True)
        time.sleep(0.05)
        subprocess.run(["wlrctl", "pointer", "click", button],
                       env=WL_ENV, check=True)

    def type(self, text: str):
        subprocess.run(["wlrctl", "keyboard", "type", text],
                       env=WL_ENV, check=True)

    def screenshot(self, path: Path):
        subprocess.run(["grim", str(path)], env=WL_ENV, check=True)


class GameSession:
    """Launches game in a transient systemd scope; tears it down atomically."""
    def __init__(self, appid: int, unit: str = "mod-test"):
        self.unit = unit
        env = {**WL_ENV, "SDL_VIDEODRIVER": "wayland"}
        subprocess.Popen([
            "systemd-run", "--user", "--scope", f"--unit={unit}",
            "--property=Delegate=yes",
            "gamescope", "-W", "1920", "-H", "1080", "-e", "-f", "--",
            "steam", f"steam://rungameid/{appid}",
        ], env=env)

    def is_active(self) -> bool:
        r = subprocess.run(["systemctl", "--user", "is-active",
                            f"{self.unit}.scope"], capture_output=True)
        return r.returncode == 0

    def stop(self, grace: float = 5.0):
        subprocess.run(["systemctl", "--user", "kill", f"{self.unit}.scope",
                        "--signal=SIGTERM"], check=False)
        time.sleep(grace)
        subprocess.run(["systemctl", "--user", "kill", f"{self.unit}.scope",
                        "--signal=SIGKILL"], check=False)
        subprocess.run(["systemctl", "--user", "reset-failed",
                        f"{self.unit}.scope"], check=False)


# pytest fixture (sketch)
@pytest.fixture(scope="session")
def game():
    session = GameSession(appid=1062090, unit="mod-test")
    wait_for_main_menu()      # template-match grim output against ref/menu.png
    yield Compositor(), session
    session.stop()


def test_mod_loads(game):
    compositor, _ = game
    compositor.click(640, 480)            # navigate into mod menu
    time.sleep(2)
    compositor.screenshot(Path("/tmp/mod_menu.png"))
    assert template_matches("/tmp/mod_menu.png",
                            "ref/mod_loaded_indicator.png")
```

---

## 7. Open work

In rough priority order:

1. **Dedicated headless Steam install** — separate Steam install/profile for
   the CI session so the URL handler doesn't accidentally hand off to a Steam
   running on a shared session (e.g. GDM's GNOME session). See §3.6 wrinkle.
2. **Persistent stack via systemd user units** — `sway-headless.service`,
   `wayvnc.service` so the stack survives reboots and is `systemctl --user`
   manageable. The launch sequence in §4.2 becomes ExecStart lines.
3. **Warmed Proton prefix** — bake compatdata into the box's base state; the
   first run per prefix is 30–60s of irrelevant variance.
4. **`wait_for_main_menu` implementation** — currently the harness sketch
   has a TODO. Likely a poll loop: `grim` every 2s, template-match against a
   reference of the main menu, succeed when match score crosses a threshold.
   Time-bound it (e.g. 90s) and fail clearly if it never matches.
5. **Reference frame management** — where do golden screenshots live, how are
   they versioned alongside the mod-under-test, how is jitter tolerated.
6. **Comparison library choice** — pick one of imagehash / OpenCV
   matchTemplate / pixelmatch after exercising real screenshots. Bias toward
   matchTemplate for "find this UI element"; imagehash for "is this still the
   same frame" (crash/hang detection).
7. **Crash/hang watchdog** — frame-hash N consecutive captures; alert/fail
   when N frames are byte-identical (likely freeze) or game process exits.
8. **Per-mod isolation** — separate Proton prefixes per mod-under-test, or
   clean and re-warm between tests.

---

## 8. Versions observed during prototyping

| Component | Version |
|---|---|
| Ubuntu | 24.04.x |
| Kernel | (Ubuntu generic, `CONFIG_INPUT_UINPUT=y` builtin) |
| gamescope | 3.16.19-1~24.04.3 (from ppa:3v1n0/gamescope) |
| sway | 1.9 |
| wlroots | 0.18 |
| wayvnc | (from 24.04 universe) |
| seatd | (from 24.04 universe, `-g video` gating) |

GPU: Intel UHD 630 (CFL GT2), Vulkan via Intel ANV driver.
