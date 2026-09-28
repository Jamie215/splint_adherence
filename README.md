# Splint Adherence

A desktop tool for measuring how consistently a patient wears a thermoplastic
splint. A small Arduino-based logger is embedded in the splint and periodically
records temperature and proximity to flash memory. This application configures
the device, downloads the recorded data, and analyzes it to estimate when — and
for how long — the splint was actually worn.

The analysis infers wearing periods from body heat: when the splint is worn, the
temperature sensor rises above the ambient baseline while the proximity sensor is
covered. Onsets and offsets of these events are detected and summarized into
per-day wear totals and an hour-of-day timeline.

> **Taking over this project?** See [HANDOFF.md](HANDOFF.md) for architecture,
> firmware lessons learned, algorithm parameters, known limitations, and the
> release runbook.

## How it works

```
┌─────────────────┐     USB serial      ┌──────────────────────────────┐
│  Arduino logger │ ◀─────────────────▶ │  Desktop GUI (Dash / Flask)  │
│  in the splint  │   ?  !  i  r cmds    │  http://127.0.0.1:8050        │
└─────────────────┘                     └──────────────────────────────┘
   temperature +                          Initialize · Download · Analyze
   proximity to flash
```

The device runs a small state machine. On each power-up it toggles between:

- **Logging mode** – sensors are sampled every `wakeup_interval` seconds and the
  reading (elapsed time, temperature, proximity) is written to flash. Most
  peripherals are powered down between samples to keep sleep current low.
- **Idle mode** – the serial port is active and the device answers commands from
  the GUI.

The GUI talks to the device over a simple serial protocol:

| Command | Meaning                                             |
| ------- | --------------------------------------------------- |
| `?`     | Handshake — device replies `Hello World!`           |
| `!`     | Status — replies `HAS_DATA` or `NEED_CONFIGURATION` |
| `i`     | Initialize — receives a packed config + checksum    |
| `r`     | Read — streams the recorded CSV, ending `END_DATA`  |

## Repository layout

| Path                                       | Purpose                                                        |
| ------------------------------------------ | ------------------------------------------------------------- |
| `app.py`                                   | Entry point: Dash layout, routing, heartbeat/shutdown, launch |
| `app_instance.py`                          | Shared Dash app, Flask server, and SocketIO instances         |
| `arduino.py`                               | `ArduinoClient` — serial handshake, init, and data download   |
| `pages/index_page.py`                      | Home page: Initialize / Download modal flow and callbacks     |
| `pages/data_analysis_page.py`              | Upload a CSV and render plots, table, and summaries           |
| `pages/analysis_helper.py`                 | Parsing, onset/offset detection, gantt and summary helpers    |
| `pages/components.py`                      | Shared UI pieces (start-time pickers, status messages)        |
| `assets/`                                  | CSS, heartbeat websocket JS, vendored fonts/theme/icons (offline) |
| `collect_temperature/collect_temperature.ino` | Arduino firmware for the logger                            |
| `timezone_config.py`                       | Display time zone (America/New_York) used across the app      |
| `tests/`                                   | pytest suite (no hardware needed)                             |
| `setup.py`                                 | `cx_Freeze` configuration for Windows / macOS bundles         |

## Requirements

- Python 3.11+
- An Arduino Nano 33 BLE Sense (nRF52840) with an HS300x temperature/humidity
  sensor and an APDS9960 proximity sensor, flashed with the firmware in
  `collect_temperature/`.

## Getting started

### 1. Flash the firmware

Open `collect_temperature/collect_temperature.ino` in the Arduino IDE, install
the `Arduino_APDS9960` and `Arduino_HS300x` libraries, select the Nano 33 BLE
board, and upload.

### 2. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the app

```bash
python app.py
```

This starts the server on `http://127.0.0.1:8050` and opens it in your browser.
The page sends a periodic heartbeat; if the browser tab is closed the server
shuts itself down after a short timeout.

## Using the app

1. **Initialize Device** – connect the device over USB, then set the start date,
   time (**Eastern time**), and a participant ID (up to 15 letters, digits, `-` or `_`, e.g. `SA-014`). The GUI packs this configuration (with a checksum)
   and sends it to the device, which then powers down and begins logging on its
   next power-up.
2. **Data Download** – connect a device that has recorded data and enter a
   filename. The recorded readings are streamed back and saved as a CSV, with
   epoch timestamps converted to readable UTC.
3. **Data Analysis** – upload a downloaded CSV to view the temperature and
   proximity traces, detected wearing periods, a per-day wear-time summary, and
   an hour-of-day timeline of when the splint was worn.

## Running the tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

The tests cover the analysis helpers and serial-protocol parsing and need no
device. They also run in CI on every pull request.

## Building a standalone executable

The app is packaged with `cx_Freeze`:

```bash
python setup.py build_exe    # Windows -> Splint_Adherence/
python setup.py bdist_mac    # macOS   -> build/Splint_Adherence.app
```

### Releasing

Bump `version` in `setup.py`, merge to `main`, then push a matching tag:

```bash
git tag v1.3.0
git push origin v1.3.0
```

The **Build and Release** GitHub Actions workflow builds both bundles and
attaches `Splint_Adherence-windows.zip` and `Splint_Adherence-macos.zip` to the
GitHub Release. You can also run the workflow manually from the Actions tab to
get the bundles as run artifacts without publishing a release.

## Data format

Downloaded CSVs contain a short metadata header followed by the readings:

```
Initial Timestamp,2026-01-01 08:00:00-05:00
Wake-up Interval (Seconds),300
Personal ID,42
Timezone,America/New_York
Timestamp,Temperature,ProximityVal
2026-01-01 08:00:00-05:00,30.50,0
2026-01-01 08:05:00-05:00,31.00,5
...
```

Timestamps are Eastern time (DST-aware) with their UTC offset. The device
itself records UTC; the app converts on download.

The analysis page also accepts older exports:

- Files without a `ProximityVal` column: those readings are treated as proximity `0`.
- Files downloaded before v1.2.0: their timestamps are naive UTC, and they are
  converted to Eastern time automatically.
