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

## How it works

```
┌─────────────────┐     USB serial      ┌──────────────────────────────┐
│  Arduino logger │ ◀─────────────────▶ │  Desktop GUI (Dash / Flask)  │
│  in the splint  │   ?  !  i  r cmds    │  http://127.0.0.1:8050        │
└─────────────────┘                     └──────────────────────────────┘
   temperature +                          Initialize · Download · Analyze
   proximity to flash
```

The device runs a small state machine. On each power-up it chooses its mode from
whether a USB host is supplying power (read from the nRF52840's on-chip
`VBUSDETECT`), not from a persisted flag — a normal USB serial connection does
not reset this board, so a toggle that only re-evaluated on reset was unreliable:

- **On USB → idle mode** – the serial port is active and the device answers
  commands from the GUI. It never auto-starts logging or disables USB while on a
  host, so initialization and download are always reachable.
- **On battery → logging mode** – if the device has been configured, sensors are
  sampled every `wakeup_interval` seconds and the reading (elapsed time,
  temperature, proximity) is written to flash. Most peripherals are powered down
  and the CPU deep-sleeps between samples (on-chip RTC wakeup) to keep current low.

Recorded data is preserved on every idle boot; only the `i` command erases it.
To download from a device that is already logging, connect it over USB and press
the reset button once (connecting alone does not reset it) — it then boots idle.

The GUI talks to the device over a simple serial protocol:

| Command | Meaning                                                       |
| ------- | ------------------------------------------------------------- |
| `?`     | Handshake — device replies `Hello World!`                     |
| `!`     | Status — replies `HAS_DATA` or `NEED_CONFIGURATION`           |
| `i`     | Initialize — receives a packed config + checksum              |
| `l`     | Start logging now (bench testing over USB; echoes each reading) |
| `r`     | Read — streams the recorded CSV, ending `END_DATA`            |

## Repository layout

| Path                                       | Purpose                                                        |
| ------------------------------------------ | ------------------------------------------------------------- |
| `app.py`                                   | Entry point: Dash layout, routing, heartbeat/shutdown, launch |
| `app_instance.py`                          | Shared Dash app, Flask server, and SocketIO instances         |
| `arduino.py`                               | `ArduinoClient` — serial handshake, init, and data download   |
| `pages/index_page.py`                      | Home page: Initialize / Download modal flow and callbacks     |
| `pages/data_analysis_page.py`              | Upload a CSV and render plots, table, and summaries           |
| `pages/analysis_helper.py`                 | Parsing, onset/offset detection, gantt and summary helpers    |
| `assets/`                                  | CSS, client-side heartbeat websocket JS                       |
| `collect_temperature/collect_temperature.ino` | Arduino firmware for the logger                            |
| `setup.py`                                 | `cx_Freeze` configuration for building a Windows executable   |

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
   time, and a personal ID. The GUI packs this configuration (with a checksum)
   and sends it to the device. The device stays idle and connected after
   initializing; unplug it and run it from battery to begin logging.
2. **Data Download** – connect a device that has recorded data and enter a
   filename. The recorded readings are streamed back and saved as a CSV, with
   epoch timestamps converted to readable UTC.
3. **Data Analysis** – upload a downloaded CSV to view the temperature and
   proximity traces, detected wearing periods, a per-day wear-time summary, and
   an hour-of-day timeline of when the splint was worn.

## Building a standalone executable

The app can be packaged into a Windows executable with `cx_Freeze`:

```bash
python setup.py build_exe
```

The bundle is written to the `Splint_Adherence/` directory.

## Data format

Downloaded CSVs contain a short metadata header followed by the readings:

```
Initial Timestamp,2026-01-01 08:00:00
Wake-up Interval (Seconds),300
Personal ID,42
Timestamp,Temperature,ProximityVal
2026-01-01 08:00:00,30.50,0
2026-01-01 08:05:00,31.00,5
...
```

The analysis page also accepts older exports that lack the `ProximityVal`
column; those readings are treated as proximity `0`.
