# Troubleshooting

Common failure modes and how to diagnose them. If none of these apply, see [Reporting an issue](#reporting-an-issue) at the bottom for what to collect.

---

## Quick triage

| Symptom | Try first |
|---|---|
| `us` commands hang or fail with D-Bus errors | Are you in the login shell? `us` must run from the same user session that owns the systemd user services. Not `su`, not `sudo -u`, not a detached ssh without `loginctl enable-linger`. |
| `us stack up` succeeds, `us doctor` red | Check the specific failing line. `wayland-socket` red → sway didn't actually start (look at `journalctl --user -u understudy-sway.service`). `wayvnc-port-open` red → wayvnc bound somewhere else or port collision. |
| `us game launch` errors with "Steam process already running" | Pre-flight is working. Either you have a stray Steam from a previous run (`pkill -u $USER steam`), or your desktop Steam is up and would steal the launch URL. |
| `us game launch` errors with "Unit ... is already active" | A previous session is still running. `us game kill` first. |
| `us game launch` succeeds but VNC shows blank | Gamescope picked the wrong outer backend. Confirm the launched cmd includes `--backend wayland`: `pgrep -af gamescope`. If it doesn't, you're on an older `us`. |
| `us act click` exits 0 but the game doesn't react | This is the most common confusing case — see [Input not reaching the game](#input-not-reaching-the-game) below. |
| `us scene wait-for <ref>` times out | Error message now includes the best similarity score and a path to a saved frame at `/tmp/understudy-wait-miss-*.png`. Read that frame and compare to the ref — see "Diagnose ref misses" in `SKILL.md`. |

---

## Input not reaching the game

`us doctor`'s `input-probe` only verifies the cursor lands at the right gamescope-Xwayland coordinate; it does NOT verify the click event reaches the game's UI. Unity-under-Proton has several layers between you and the game's input handler. Bisect with:

```bash
# 1. Cursor positioning. Does the cursor land where you asked?
us act move 960 540 -v
DISPLAY=:3 xdotool getmouselocation
#   Expect: X=960 Y=540, WINDOW=<some hex> (steam_app_<appid>)

# 2. The actual click. Run with -v to see the exact subprocess.
us act click 960 540 -v
#   Expect: xdotool windowfocus → mousemove → click

# 3. State change. Did the game actually react?
us scene capture --out /tmp/before.png
us act key Escape -v     # almost every game reacts to Escape
sleep 1
us scene capture --out /tmp/after.png
us scene diff /tmp/before.png /tmp/after.png --method phash
#   If "similar: false" → input is reaching the game
#   If "similar: true"  → no state change; input is being dropped or ignored

# 4. Try the other backend.
us act click 960 540 --backend wlrctl -v
us act click 960 540 --backend xdotool -v
#   xdotool is the auto-default when gamescope is up; wlrctl rarely
#   reaches Steam-launched Unity games on this stack but is worth a try.
```

**Most common causes for "click exits 0 but game ignores it"**:

- **Clicked on empty space.** Use `us scene capture` and Read the PNG visually. Verify the coord actually contains a button. Use `us game show <slug>` to see named coords from the profile.
- **A modal overlay you can't see.** Some mod-update notifiers render with locale-dependent labels that are invisible under non-English locales (e.g. ukUA missing `LV.TimberUi.UpdateDismiss`). The button is there but you can't see it. Either dismiss via the mod's registry keys (see `memory/timberborn_mod_update_dismiss.md`) or capture the dialog and find the click area by trial.
- **Game expects keyboard, not mouse** (or vice versa). Try `us act key Return`, `us act key space`, or `us act key Escape`.

---

## Visual test rig: `us xeyes`

When you suspect "is my input reaching gamescope at all", spin up a non-Steam test rig that doesn't have any of the Steam/Unity/Proton complications:

```bash
us xeyes up
# VNC into :5900 — you should see two eyes
us act move 200 200 -v   # pupils should look toward upper-left
us act move 1700 900 -v  # pupils should look toward lower-right
us xeyes down
```

If the pupils track but a game ignores clicks, the failure is somewhere between gamescope and the game (Unity input filter, modal overlay, mod), not in the input chain itself.

---

## Game launch fails

```bash
us game launch <slug> --json     # capture the structured error
us status --json                  # is the stack still healthy?
systemctl --user status understudy-game-<appid>.service --no-pager
journalctl --user -u understudy-game-<appid>.service -n 100 --no-pager
```

If the unit ended in `failed` state from a previous crash, `us game launch` self-heals (calls `ResetFailedUnit` first). If that's not happening you might be on an older `us`.

---

## Capturing a screenshot

The grim output goes to whatever you pass to `--out`. The default is `state/frames/<timestamp>.png` (printed to stdout in JSON mode).

```bash
us scene capture --out /tmp/snap.png             # full output
us scene capture --out /tmp/snap.png --crop "x,y WxH"   # cropped (e.g. "960,400 200x200")
```

To find the pixel coordinates of a button: capture, open the PNG with any image viewer that shows cursor coords, hover over the button, note (x, y). Or with Python:

```python
from PIL import Image
img = Image.open('/tmp/snap.png')
# img.show()  # or crop a region:
img.crop((800, 700, 1200, 900)).save('/tmp/button-area.png')
```

---

## Reporting an issue

Open a GitHub issue at https://github.com/impuls42/understudy/issues. Include the items below — most of them paste cleanly into the body.

### Always include

1. **`us` version**: `us version`
2. **Distro + gamescope version**: `lsb_release -d && gamescope --version 2>&1 | head -1`
3. **Full `us doctor --json` output** (from the failing state):
   ```bash
   us doctor --json
   ```
4. **`us status --json`** at the failing moment.
5. **The exact `us` command(s) you ran** and their output, ideally with `-v` for input commands:
   ```bash
   us act click 960 540 -v --json
   ```
6. **Description of what should have happened** vs what did.

### If input isn't reaching the game

7. **Active gamescope cmdline** (confirms the launch flags):
   ```bash
   pgrep -af gamescope | head -2
   ```
8. **A screenshot of the failing state**:
   ```bash
   us scene capture --out /tmp/issue-state.png
   # attach /tmp/issue-state.png to the GitHub issue
   ```
9. **Cursor position readback from gamescope's Xwayland**:
   ```bash
   DISPLAY=:3 xdotool getmouselocation
   ```
10. **Game window tree** (so we can see what windows exist inside gamescope's Xwayland):
    ```bash
    DISPLAY=:3 xwininfo -root -tree | head -40
    ```
11. **Result of the diff probe** described above in [Input not reaching the game](#input-not-reaching-the-game) (steps 1–4).

### If launching the game fails

12. **Game unit status + recent log**:
    ```bash
    systemctl --user status understudy-game-<appid>.service --no-pager
    journalctl --user -u understudy-game-<appid>.service -n 200 --no-pager
    ```
13. **Sway log around the failure**:
    ```bash
    journalctl --user -u understudy-sway.service --since "10 minutes ago" --no-pager
    ```
14. **If a Unity/Proton game**: the Unity Player log, e.g. for Timberborn:
    ```
    ~/.steam/steam/steamapps/compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/LocalLow/<Company>/<Game>/Player.log
    ```

### If the stack itself won't come up

15. **Sway service log** (full):
    ```bash
    journalctl --user -u understudy-sway.service -n 200 --no-pager
    ```
16. **wayvnc log**:
    ```bash
    journalctl --user -u understudy-wayvnc.service -n 100 --no-pager
    ```
17. **`XDG_RUNTIME_DIR` contents**:
    ```bash
    ls -la "$XDG_RUNTIME_DIR" | head -20
    ```

A redacted dump is fine — paths with your username, no Steam credentials.
