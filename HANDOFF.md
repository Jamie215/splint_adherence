# Developer Handoff — Splint Adherence

This is the technical handoff for whoever maintains this project next. The
[README](README.md) covers installing and using the app. This document covers
how it works inside, why it was built this way, what has already been tried,
and what is still unverified.

> A plain-language guide for researchers who run devices and analyze data is
> kept separately as a shared document.

---

## 1. System at a glance

```
 ┌─────────────────────────┐   USB serial (CDC)   ┌──────────────────────────────────┐
 │  Arduino Nano 33 BLE    │ ◀──────────────────▶ │  Desktop app (Dash + Flask-      │
 │  Sense (nRF52840)       │   ? ! i r commands    │  SocketIO on gevent)             │
 │  HS300x temp + APDS9960 │                       │  http://127.0.0.1:8050           │
 │  proximity → own flash  │                       │                                  │
 └─────────────────────────┘                       └──────────────────────────────────┘
      stores UTC epoch +                               Initialize · Download · Analyze
      elapsed seconds                                  (all times shown in Eastern)

 Device flash ──r──▶ arduino.py (epoch → Eastern ISO) ──▶ CSV ──upload──▶ analysis_helper.py
```

| File | Role |
| --- | --- |
| `app.py` | Entry point. Sets up gevent monkey-patching, a stdout/stderr guard for windowed builds, routing, the heartbeat auto-shutdown (5 min without a heartbeat, then a 20 s warning, then exit), and cleanup. |
| `app_instance.py` | Creates the shared Dash app, Flask server, and SocketIO objects. Works out where `assets/` is in both source and frozen builds. Lists the vendored stylesheets. |
| `timezone_config.py` | `DISPLAY_TZ` (America/New_York). The only place the time zone is set. |
| `arduino.py` | `ArduinoClient`: finds the port by handshake, packs and checksums the config, streams and parses the download. `format_epoch()` renders timestamps in Eastern time. |
| `pages/index_page.py` | Home page with the Initialize and Download modal flows. |
| `pages/data_analysis_page.py` | Upload, plots, events table, daily summary, and hour-of-day chart. |
| `pages/analysis_helper.py` | Parsing, time zone conversion, drift-invariant proximity, onset/offset detection, and splitting events by day. |
| `collect_temperature/collect_temperature.ino` | Logger firmware. |
| `tests/` | pytest suite. Needs no hardware; the serial port is faked. |
| `.github/workflows/` | `tests.yml` runs pytest on PRs. `build-release.yml` builds the Windows and macOS bundles. |

## 2. Device lifecycle (read this before touching the firmware)

On every power-up the firmware switches between two modes, based on
`config.mode` in flash and whether any data exists (`setup()`):

| Stored state at power-up | What happens |
| --- | --- |
| `MODE_IDLE` and **no data** (just initialized) | Switches to **logging**. USB, UART and radio are powered down, and it samples every 300 s until flash is full. |
| `MODE_LOGGING` | Switches to **idle**. USB serial is enabled and the device answers `? ! i r`. |
| `MODE_IDLE` with data | Stays idle (serial). |

What this means in practice:

1. **Initialize** (`i`): the device erases the data area, saves the config, and
   enters `SYSTEMOFF`. The USB connection drops; this is expected, and
   `arduino.initialize` treats it as success.
2. The **next power-up** starts logging. In logging mode the serial port is
   off, so the app cannot see the device.
3. To download, **power-cycle once more** to reach idle, then connect over USB
   and run `r`.

If someone "can't find the device", they are almost always in logging mode.
Power-cycling fixes it.

Serial protocol:

| Command | Meaning |
| --- | --- |
| `?` | Handshake. The device replies `Hello World!` |
| `!` | Status. The device replies `HAS_DATA` or `NEED_CONFIGURATION` |
| `i` | Initialize. The device replies `READY_FOR_INIT`, then reads 28 bytes packed as `<II16sI>` (epoch, interval, ID, sum-of-bytes checksum) |
| `r` | Read. The device streams its metadata and CSV rows (UTC epoch, temperature, proximity) and ends with `END_DATA` |

## 3. Firmware notes and hardware lessons

**Flash layout:**
- Config is at `0x70000`.
- Data starts at `0x80000`, as 12-byte `TemperatureData` records (with padding), up to `MAX_DATA_ENTRIES = 15000`.
- At 300 s per sample, that is about **52 days** of capacity.

**Timestamps:** each record stores the seconds elapsed since logging started,
measured with `millis()`. The app adds that to the initial epoch.

**Sampling interval:** fixed at **300 s**. The value is
`arduino.WAKEUP_INTERVAL_SECONDS` and is sent in the init packet. The analysis
works out the actual sampling rate from the timestamps, so its time windows
don't depend on this constant.

**Lessons already learned on hardware (don't repeat these):**
- **Don't disable SPI0/SPI1 in logging mode.** On the nRF52840 they share
  hardware with the I2C controllers the sensors use. Disabling them kills the
  bus, the proximity read hangs, and nothing gets logged (fixed in `c32bda4`).
- **The RTC2 + `__WFI` low-power sleep was tried and reverted** (`b0cdfce` →
  `c153218`). The current approach is peripheral power-down plus `delay()`,
  measured at about 750 µA resting (`23134ae`).
- **Choosing the mode from USB presence was tried and reverted** (`7ca502c` →
  `977a641`). The persisted toggle is the version known to work.
- **Proximity reads discard warm-up samples.** `PROX_WARMUP_SAMPLES = 2`, and
  every wait is bounded by `PROX_WAIT_TIMEOUT_MS`. A stuck or missing sensor
  logs `0` instead of hanging the logger.
- **Baud rate:** 9600 on both sides. The native USB port ignores it.

**Build:** use the Arduino IDE with the Nano 33 BLE (mbed) board package and the
`Arduino_APDS9960` and `Arduino_HS300x` libraries. Record the exact versions you
use in the access checklist (§9).

## 4. Analysis algorithm (`pages/analysis_helper.py`)

The pipeline runs in `data_analysis_page.update_dashboard`:

1. `parse_file`: split the metadata key/value lines from the CSV table. The
   table starts at the first line that contains `Temperature`.
2. `to_display_tz`: convert timestamps to tz-aware Eastern time. Timestamps with
   an offset are converted exactly. Naive (legacy) timestamps are treated as
   UTC.
3. `detect_onsets_offsets(time, temp, prox)`:
   - `interval_min` is the median gap between timestamps.
   - `baseline` is the rolling minimum of temperature over about 2 h (centered).
     `delta = temp - baseline`.
   - `gradient` is the difference between consecutive samples. `trend` is the
     change over about 15 min.
   - `prox_covered = dedrift_proximity(prox)`:
     - It tracks the proximity "floor" as the rolling 10th percentile over
       about 1 day.
     - It subtracts that floor, since the drift adds to every reading rather
       than scaling it.
     - A sample counts as covered when the remainder is at or below
       `max(min_excursion, k·MAD)`, where MAD is a robust measure of noise.
     - This replaced the raw `prox == 0` test, which stopped working after
       about 11 days because the proximity baseline drifts upward as the
       battery drains (`12411dd`).
   - A state machine walks the samples:
     - **Onset**: the sensor is covered, `trend > 0`, and either
       `gradient ≥ ONSET_GRAD` or `delta ≥ ONSET_DELTA`.
     - **Offset**: the sensor is no longer covered, or the temperature is
       cooling fast and is either back near baseline or well below its peak.
     - Events shorter than 2 samples are dropped.
4. `extract_peaks`, `prepare_occurance_summary`, `prepare_gantt`: find the peak
   temperature of each event and split events at midnight (in Eastern time,
   DST-aware) into per-day totals and hour-of-day bars.

### Tunable parameters

All of these are empirical. None have been checked against labeled
ground-truth wear logs (see §7).

| Parameter | Where | Value | Raising it will… |
| --- | --- | --- | --- |
| `ONSET_DELTA` | `detect_onsets_offsets` | 3.0 °C | require more heat above ambient to start an event (fewer false positives, and gentle onsets are missed) |
| `ONSET_GRAD` | `detect_onsets_offsets` | 0.8 °C/sample | require a sharper jump to start an event |
| `OFFSET_GRAD` | `detect_onsets_offsets` | −0.4 °C/sample | (less negative) end events on gentler cooling |
| `OFFSET_DELTA` | `detect_onsets_offsets` | 1.5 °C | end events while still further above ambient |
| `PEAK_DROP_FACTOR` | `detect_onsets_offsets` | 0.8 | end events after a smaller drop from the peak |
| baseline window | `detect_onsets_offsets` | ~120 min | give a steadier ambient floor, but slower to follow room-temperature changes |
| trend lag | `detect_onsets_offsets` | ~15 min | smooth the "is it trending up" check more |
| minimum length | `detect_onsets_offsets` | 2 samples | drop more short events |
| floor window | `dedrift_proximity` | ~1 day | follow drift more slowly |
| floor quantile | `dedrift_proximity` | 0.10 | raise the floor estimate |
| `k` | `dedrift_proximity` | 4.0 | allow more noise and still call the sensor "covered" |
| `min_excursion` | `dedrift_proximity` | 5.0 | set the minimum threshold for being "not covered" |

`baseline_asls` (asymmetric least squares) is present but currently unused.

## 5. Time zone design

- The device only stores UTC epochs; it has no notion of time zone.
- **Initialize**: the date and time the researcher enters are treated as
  Eastern time (`DISPLAY_TZ.localize`), then converted to a UTC epoch.
- **Download**: `format_epoch` writes `YYYY-MM-DD HH:MM:SS±HH:MM` in Eastern
  time. The offset keeps the repeated hour at the November DST change
  unambiguous. A `Timezone,America/New_York` metadata line is added.
- **Analysis**: all calculations use tz-aware Eastern timestamps, so durations
  across DST changes are correct. Plotly receives *naive* Eastern wall-clock
  times so the axes show Eastern time regardless of the browser's zone.
- **Legacy files** (naive UTC, downloaded before v1.2.0) are converted to
  Eastern automatically. Their displayed times will differ from what older
  versions of the app showed; that is expected.
- To change the zone, edit `timezone_config.py`.

## 6. Vendored front-end assets (offline support)

The app used to load its fonts, theme and icons from CDNs, so it rendered
unstyled on offline machines. These files now ship under `assets/vendor/`:

| Directory | npm package | Version |
| --- | --- | --- |
| `bootswatch-litera/` | `bootswatch` (litera theme) | 5.3.3, the same one `dbc.themes.LITERA` pointed to |
| `fontawesome/` | `@fortawesome/fontawesome-free` (`all.min.css` + `webfonts/`) | 6.3.0, the same one `dbc.icons.FONT_AWESOME` pointed to |
| `roboto/` | `@fontsource/roboto`, weights 300/400/500/700 (latin) | 5.3.0 |

- The vendored stylesheets end in **`.vendor.css`**. They are listed in
  `external_stylesheets` so they load before `assets/style.css`.
- `assets_ignore=r"\.vendor\.css$"` stops Dash from also auto-loading them after
  `style.css`. Dash's `assets_ignore` matches file names, not paths.
- **To update**:
  1. Run `npm pack <package>@<version>` and extract the tarball.
  2. Copy the same files over, keeping the `.vendor.css` names and Font
     Awesome's `css/` + `webfonts/` layout.
  3. Strip any `sourceMappingURL` comment.
- **To check**: open the app with networking off. The home page icons and the
  Roboto font should render.

## 7. Known limitations and unverified items

These were known at handoff and **deliberately left unverified** because we
ran out of time. Check them before relying on the results they affect.

1. **`millis()` wraps around at about 49.7 days.**
   - The logger's sleep calculation compares `nextWakeTime > currentTime`.
     Near the wraparound it may skip sleeping and log a burst of samples
     until the counter wraps.
   - Capacity is about 52 days, so a long deployment can hit this.
   - Elapsed-time stamps use unsigned subtraction and are unaffected; only the
     spacing between samples is at risk.
   - Bench-test before any deployment longer than about 45 days.
2. **Detection thresholds and drift parameters** (§4) were tuned on a small
   amount of data. The drift fix was validated on a single 35-day recording.
   No labeled ground truth (for example, wear diaries) is stored in the repo.
3. **Personal ID**: the UI accepts integers 0–65535, but the firmware stores a
   15-character string. The two are compatible, but alphanumeric IDs would
   need a UI change.
4. **Battery life and power draw** of the current sleep approach have not been
   measured over a full-length deployment.
5. **No device-side clock correction.** Timestamps rely on the board's clock
   (`millis()`) drifting very little over weeks.
6. **What happens after about 52 days (15,000 records)**:
   - `saveTemperatureReading` checks bounds against the *whole flash*, not
     `MAX_DATA_ENTRIES`. So logging continues past record 15,000.
   - Those extra records go into pages that initialization never erased,
     which may corrupt them.
   - `findHighestDataIndex` only scans the first 15,000 records, so anything
     after that is **never downloaded**.
   - Treat about 52 days as the hard limit per deployment.
7. The frozen macOS build is unsigned. Gatekeeper will warn on first launch
   (right-click → Open).

## 8. Build, test and release runbook

**Local development:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest                # unit tests, no hardware needed
python app.py         # http://127.0.0.1:8050
```

**Dependencies:**
- Keep `requirements.txt` hand-curated and saved as UTF-8. Never `pip freeze`
  into it (see the header in the file).
- `pytz` and `tzdata` must stay listed in `setup.py` `packages` so frozen
  builds include the time zone data.

**Standalone bundles:**
- Windows: `python setup.py build_exe` produces `Splint_Adherence/`.
- macOS: `python setup.py bdist_mac` produces `build/Splint_Adherence.app`.

**Releasing (CI):**
1. Bump `version` in `setup.py` and merge to `main`.
2. Tag and push:
   ```bash
   git tag v1.2.0
   git push origin v1.2.0
   ```
3. `build-release.yml` builds both bundles and attaches
   `Splint_Adherence-windows.zip` and `Splint_Adherence-macos.zip` to the
   GitHub Release.

To smoke-test a branch without releasing, go to Actions → "Build and Release" →
"Run workflow". The zips appear as run artifacts.

## 9. Access and ownership checklist

Fill these in before the handoff is complete:

- [ ] GitHub: new owner has admin on `Jamie215/splint_adherence` (or the repo has been transferred)
- [ ] Location of raw and processed datasets (not in the repo): ______
- [ ] Data-handling / ethics (IRB) constraints for patient data: ______
- [ ] Hardware inventory (boards, splints, cables, spares) and where it lives: ______
- [ ] Arduino IDE, board package and library versions used for the deployed firmware: ______
- [ ] Contacts: clinical lead ______, previous developer ______
