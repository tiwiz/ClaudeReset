# ClaudeReset

A desk gauge that shows how much of your **Claude Code** quota you have used, and when the window
resets — no browser, no terminal, no `claude /usage`.

![Wiring diagram](docs/wiring-diagram.png)

A **LOLIN D1 mini (ESP8266)** drives a **round GC9A01 240×240** SPI panel: a progress ring, the
percentage in the middle, the reset time and a live countdown underneath. It refreshes every 30 s.

## Why it is split in two parts

The OAuth token for Claude Code must never leave the machine that owns it, and a microcontroller
sitting on your desk is easy to pick up and read. So the token stays where it already is:

```
┌──────────────────────────┐      ┌────────────────────────┐      ┌───────────────────┐
│  Claude Code             │      │  poller (this repo)    │      │  D1 mini + GC9A01 │
│  ~/.claude/…credentials  │─────▶│  GET api.anthropic.com │─────▶│  GET /claude      │
│  OAuth token, never sent │      │  /api/oauth/usage      │      │  draws every 30 s │
└──────────────────────────┘      │  compact JSON on LAN   │      └───────────────────┘
                                  └────────────────────────┘
```

- **The poller** is a small Python script (standard library only) running on any always-on Linux box.
  It reads the token from Claude Code's own credentials file, calls the usage endpoint, and serves a
  compact JSON document on a LAN port. It is a systemd *user* unit, so it survives reboots with
  `loginctl enable-linger <user>`.
- **The firmware** is a dumb client: it does a plain HTTP GET on the LAN and draws the numbers. No
  secrets on the device, nothing to leak.

## Display layout

| Element | Value |
|---|---|
| Ring track | `circle r=103`, 14 px thick, `#2b2b33` |
| Progress arc | from 12 o'clock, clockwise, `360° × pct`, `#d97757` (`#e05a3a` above 80%) |
| Window label | `7g` (7 days) at y 62, `FreeSansBold12pt` |
| Percentage | y 118, `FreeSansBold24pt` |
| Reset clock | `reset HH:MM` at y 169, `FreeSansBold9pt` |
| Countdown | `2h 41m` at y 191, `FreeSans9pt` |
| Text colour | pure white `#ffffff` on all lines |
| Offline state | grey ring, `--` in the middle, reason printed on the reset line |

The gauge shows the **7-day window** by default because that is the one you can actually run out of
over a week; the 5-hour window is still published by the poller and only needs a one-line change in
`firmware/src/main.cpp` (`p7`/`r7` → `p`/`r`).

## JSON contract

| Endpoint | Returns |
|---|---|
| `GET /claude` | compact JSON for the microcontroller (keys below) |
| `GET /` or `/usage` | human-readable summary |
| `GET /health` | 200 when the reading is fresh, 503 when it is stuck (`age`, `error`) |

```json
{"ok":1,"p":14.0,"r":9206,"p7":65.0,"r7":14006,"age":21,"stale":0,"err":""}
```

| Field | Meaning |
|---|---|
| `ok` | 1 when there is a usable reading |
| `p`, `r` | 5-hour window: used percentage, seconds until it resets |
| `p7`, `r7` | 7-day window: same two values (what the display shows) |
| `age` | seconds since the reading was taken |
| `stale` | 1 when the reading is older than `STALE_SECONDS` |
| `err` | last error in plain words (e.g. `token scaduto`) |

A stale or missing value is a **visible** state on purpose: a display that keeps showing the last
number as if it were live is worse than a display that says "I do not know".

## Hardware

| Part | Notes |
|---|---|
| LOLIN D1 mini V4.0.0 | ESP8266EX, USB-C, CH340 |
| Round GC9A01 module | 1.28", 240×240, 4-wire SPI, **7 pads**: `RST · CS · DC · SDA · SCL · GND · VCC` |
| 7 jumper wires | 8–10 cm each, so the board can go back into a case |
| USB supply | 5 V from any charger; 3.3 V for the panel comes from the board |

| Pad on the module | D1 mini | GPIO | Notes |
|---|---|---|---|
| `RST` | `D1` | GPIO5 | panel reset |
| `CS` | `D6` | GPIO12 | chip select — **never `D8`** |
| `DC` | `D2` | GPIO4 | data/command |
| `SDA` | `D7` | GPIO13 | MOSI (hardware SPI) |
| `SCL` | `D5` | GPIO14 | clock (hardware SPI) |
| `GND` | `GND` | — | common ground |
| `VCC` | `3V3` | — | 3.3 V only |

### Two traps that cost real time

1. **`CS` on `D8`/GPIO15 does not work.** GPIO15 is a boot strapping pin and it must be low at boot;
   these modules have a pull-up on `CS`, so the board neither boots nor accepts a flash. The symptom
   is `Failed to connect to ESP8266: Timed out waiting for packet header` from esptool, which sends
   you hunting for cables and drivers. Proof, reading the boot ROM at 74880 baud:
   `boot mode:(7,6)` instead of `boot mode:(3,6)`. Use `D6`/GPIO12, or tie `CS` to GND with
   `-DTFT_CS=-1` when the display is the only device on the bus.
2. **Solder joints on `VCC` and `GND`.** These are the only two pads that carry current. A dry joint
   on `GND` shows up as a black screen that lights up *only while you press the pad with a probe* —
   it is not the probe feeding it (a voltmeter is ~10 MΩ), it is the pressure restoring contact.

## Poller setup

```bash
git clone https://github.com/tiwiz/ClaudeReset.git && cd ClaudeReset
cp .env.example .env                        # paths, port, intervals
mkdir -p ~/.config/systemd/user
cp systemd/claude-usage.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-usage.service
curl -s localhost:8790/claude | python3 -m json.tool
```

`loginctl enable-linger <user>` is required for the user unit to start at boot. With `ufw`:
`sudo ufw allow from <your-lan>/24 to any port 8790 proto tcp`.

Run it in the foreground for testing with `python3 poller/claude_usage.py`.

## Firmware

```bash
cd firmware
cp include/config.h.example include/config.h   # wifi + poller host, then chmod 600
~/.venvs/pio/bin/pio run                       # build
~/.venvs/pio/bin/pio run -t upload             # flash (board on USB)
~/.venvs/pio/bin/pio device monitor            # serial log at 115200
```

TFT_eSPI is configured entirely from `build_flags` in `platformio.ini` (`-DUSER_SETUP_LOADED=1`
plus the driver and pin defines), so no library file is ever edited. There is no framebuffer:
240×240 at 16 bpp is 115 kB and the ESP8266 has ~40 kB free, so primitives are drawn directly and
only the delta is repainted.

### Diagnostics

`firmware-test/` is a separate PlatformIO project that cycles solid colours, the four rotations and
a test dial, **without WiFi and without `config.h`**. It answers one question in a single flash: is
the panel alive at all?

```bash
cd firmware-test
pio run -e gc9a01 -t upload     # expected driver
pio run -e st7789 -t upload     # if the module turns out to be a different controller
pio run -e ili9341 -t upload
```

No glow at all from a powered module (they have no backlight pin — the LED is wired to `VCC`
internally) means the problem is power, not drivers. More detail in `docs/wiring.md`.

## Repository layout

| Path | Role |
|---|---|
| `poller/claude_usage.py` | reads the token, calls the usage endpoint, serves JSON |
| `systemd/claude-usage.service` | user unit for the poller |
| `firmware/` | ESP8266 firmware (PlatformIO + TFT_eSPI) |
| `firmware-test/` | display test patterns, no WiFi, no secrets |
| `docs/wiring.md` | pin map, dial geometry, palette, troubleshooting (Italian) |
| `docs/wiring-diagram.png` | the wiring sheet |

## Secrets

- The OAuth token is **not** in this repository: it is read at runtime from Claude Code's own
  credentials file and never logged or served.
- `.env` and `firmware/include/config.h` hold local configuration (paths, port, wifi) and are
  git-ignored; only the `.example` files are committed.
- `CLAUDE_OAUTH_TOKEN` exists for testing and lives in `.env` only.

## Status

- [x] poller + systemd user unit, verified on the build machine
- [x] firmware on real hardware: panel, wifi, NTP, live values every 30 s
- [x] 7-day window, pure white text, verified against the real Claude Code quota
- [ ] secondary arc for the second window
- [ ] 3D-printed enclosure
