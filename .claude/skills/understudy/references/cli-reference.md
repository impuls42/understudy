# understudy CLI reference

Every command accepts `--json` for structured output and `--help` for usage.

Exit codes: **0** ok · **2** precondition error · **3** timeout · **4** template mismatch · **5** external command failure

---

## Top-level

| Command | Description |
|---------|-------------|
| `us version` | Print installed version |
| `us status [--json]` | Stack health + active game unit at a glance |
| `us doctor [--json]` | Run smoke checks (sway, socket, wayvnc port, HEADLESS-1 output, grim capture) |

---

## `us stack` — headless Wayland stack

| Command | Key options | Description |
|---------|-------------|-------------|
| `us stack up` | `--timeout 10` | Start sway + wayvnc; install units if needed; block until socket appears |
| `us stack down` | `--grace 3` | Stop wayvnc then sway |
| `us stack status` | | Show unit ActiveState, socket presence, port |
| `us stack install` | `--force` | Copy `.service` files to `~/.config/systemd/user/` and reload daemon |

---

## `us act` — input injection

All coordinates are absolute pixels in the 1920×1080 HEADLESS-1 output.
Uses xdotool (X11 via gamescope Xwayland) when a game is running, wlrctl (Wayland) otherwise.

| Command | Arguments | Key options | Description |
|---------|-----------|-------------|-------------|
| `us act click X Y` | x y | `--button left\|right\|middle` `--delay 0.05` | Move pointer then click |
| `us act move X Y` | x y | | Move pointer without clicking |
| `us act type TEXT` | text | | Type a string via virtual keyboard |
| `us act key KEYSYM` | keysym | | Press and release one key (XKB names: `Return`, `Escape`, `space`, `Tab`, `F1`, `Control_L`, …). Single keys only — chords are not supported; use `us act type` for text strings. |

---

## `us scene` — capture and comparison

| Command | Arguments | Key options | Description |
|---------|-----------|-------------|-------------|
| `us scene capture` | | `--out PATH` `--output HEADLESS-1` `--crop "x,y WxH"` | Capture headless display to PNG; prints saved path |
| `us scene wait-for REF` | ref name or path | `--timeout 90` `--threshold 0.85` `--poll 2` `--slug SLUG` `--refs-dir DIR` | Block until ref appears; exits 0 on match, 3 on timeout |
| `us scene wait-quiescent` | | `--frames 5` `--poll 0.5` `--timeout 30` | Block until screen stops changing |
| `us scene diff A B` | two image paths | `--method template\|phash\|pixelmatch` | Compare images; exits 0 if similar, 4 if not |

`us scene wait-for` accepts a full path to a `.png`, or a bare ref name resolved
via `--slug`/`--refs-dir` (e.g. `us scene wait-for main_menu --slug timberborn`).

---

## `us ref` — reference image management

All three commands accept `--slug <slug>` to resolve the refs directory from a
game profile automatically (equivalent to `--refs-dir games/<slug>/refs`).

| Command | Arguments | Key options | Description |
|---------|-----------|-------------|-------------|
| `us ref record [NAME]` | optional ref name | `--slug SLUG` `--refs-dir DIR` `--from-file PATH` | Without NAME: interactive loop (prompt → capture → confirm → save). With NAME: single-shot capture. |
| `us ref list` | | `--slug SLUG` `--refs-dir DIR` | List all refs in the store |
| `us ref show NAME` | ref name | `--slug SLUG` `--refs-dir DIR` | Print the path to a ref image |

---

## `us game` — game session management

| Command | Arguments | Key options | Description |
|---------|-----------|-------------|-------------|
| `us game launch SLUG_OR_APPID` | slug or appid | | Pre-flight check, then start game inside a transient systemd scope |
| `us game kill` | | `--grace 5` | SIGTERM → wait → SIGKILL → reset-failed the active game unit |
| `us game is-running` | | | Exits 0 if a game unit is active, 1 if not |
| `us game status` | | | Show active unit name and state |
| `us game list` | | | List available game profile slugs |
| `us game scaffold SLUG` | slug | `--appid ID` `--display-name NAME` | Generate a new game profile directory from the template |

---

## `us run` — pytest passthrough

```bash
us run games/timberborn/tests/                    # run all game tests
us run games/timberborn/tests/ -k test_main_menu  # filter by name
us run games/timberborn/tests/ -v --timeout 300   # extra pytest flags pass through
```

Markers defined in `pyproject.toml`:
- `@pytest.mark.smoke` — no game launch required
- `@pytest.mark.game` — requires a running game session

---

## Common `--json` output shapes

**Success:**
```json
{"ok": true, "path": "/tmp/understudy-...", ...}
```

**Error:**
```json
{"ok": false, "code": 2, "reason": "Headless stack is not up.", "hint": "Run `us stack up` first."}
```

**`us status`:**
```json
{
  "stack": {
    "sway": {"active_state": "active", "socket_exists": true, "wayland_display": "wayland-1"},
    "wayvnc": {"active_state": "active", "port": 5900},
    "healthy": true
  },
  "game": {"unit": "understudy-game-1062090.service", "active": true}
}
```
