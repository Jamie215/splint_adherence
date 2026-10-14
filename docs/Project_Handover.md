---
title: "Splint Adherence Logger — Project Handover"
subtitle: "State at transition, design decisions and their rationale, and directions to explore"
---

*October 2026 Ver. Prepared by Jamie Kim.*

# About this document

This is the handover record for the splint adherence logger: a temperature and proximity logger embedded in a thermoplastic splint, and the desktop app that configures it and estimates wear time from its recordings (January 2025 – October 2026). It is composed of the following:

- **Handover summary (§1):** the state of the project at transition, open issues, what to do next, and who to contact. Read this first.
- **Design decisions (§2–§7):** what was decided, why, and which alternatives were considered.
- **Testing and future directions (§8–§9):** what has been verified so far, and the areas to explore.
- **Areas to explore (Appendices A–B):** longer notes on the two changes most worth making next.

Companion documents are listed in §1.4, and technical terms are explained under *Key terms*, after §1.

**Where to start**

| If you want to… | Start with |
|--------|--------|
| Build a logger, run a deployment, or download and analyse data | The SOP (`docs/SOP_Build_and_Use.docx`) |
| Change the app or the firmware | `README.md`, then `HANDOFF.md` (developer reference), then §3–§7 of this document |
| Plan the next stage of research | §1.2, §1.3, §8, §9 and Appendices A–B |
| Understand why it works the way it does | §2–§7 |

# 1. State at transition (October 2026)

## 1.1 Current state

- **Working logger.** Arduino Nano 33 BLE Sense (nRF52840) with its built-in HS300x temperature and APDS9960 proximity sensors. It records one reading every 5 minutes to its own flash memory, for up to about 52 days of storage, and is configured and read over USB. Firmware: `collect_temperature/collect_temperature.ino`.
- **Desktop app v1.3.0.** *Splint Adherence* (Dash/Flask, opens in the browser, works offline). It initializes loggers, downloads recordings to CSV, recovers lost start times, and shows detected wear events, daily wear totals and an hour-of-day timeline. Built for Windows and macOS by GitHub Actions on each version tag, and published on the repository's Releases page.
- **Field use.** Recordings of up to about 36 days have been collected and analysed, and the analysis was hardened against what they showed (proximity drift, §5.3). **\[TODO\]**: number of loggers built, number of deployments and participants so far, and the state of each logger.
- **Tests.** 22 automated tests (wear detection, time zones, timestamp recovery, serial protocol) run on every pull request and need no hardware.
- **Documentation.** SOP for operators (`docs/SOP_Build_and_Use`), developer reference (`HANDOFF.md`), README, and this document.

## 1.2 Open issues

Items 1–3 were found while preparing this handover, by reading the code; they have not been reproduced on hardware.

1. **Timestamps assume the logger was powered on exactly at the start time entered.** The logger stores the start time typed into the app and counts elapsed time from its next power-on (`startMillis`). Any gap between the two shifts every timestamp in the recording by that amount, and nothing in the file shows it. The SOP now tells operators to power on at the entered time and log the actual time. A fix is proposed in Appendix A.
2. **Any reset during a deployment ends the recording.** The mode is toggled on every power-up (§4.1). A reset, brown-out or loose battery while logging therefore puts the logger into idle mode, and it stays there. The data up to that point is kept, but nothing more is recorded. See Appendix A.
3. **Long continuous wear may be cut short by the detector.** The temperature baseline is a rolling minimum over a centred window of about 2 hours (§5.1). After about an hour of continuous wear, the window is all "worn" samples and the temperature rise above baseline falls to about 0. From then on, a single drop of 0.4 °C between samples ends the event. It cannot restart, because restarting needs a rise of ≥ 3 °C above baseline or a jump of ≥ 0.8 °C. On synthetic 8-hour overnight wear, temperature noise with a standard deviation of 0.15 °C was enough to split the nights into short pieces; with 0.04 °C they were detected whole. Check on real overnight recordings before trusting long-wear totals.
4. **Clock rollover at ~49.7 days.** `millis()` wraps, and the sleep check `nextWakeTime > currentTime` is not wrap-safe. Expect a burst of readings followed by a long gap. Proposed fix (HANDOFF.md §8): `if ((int32_t)(nextWakeTime - currentTime) > 0)`, bench-tested with a temporary offset on `millis()`. Until then, deployments are limited to about a month.
5. **Storage bound not enforced.** `saveTemperatureReading` checks against the whole flash rather than `MAX_DATA_ENTRIES` (15 000). Records beyond about 52 days go into pages that were never erased and are never downloaded. In practice item 4 comes first.
6. **Battery life not measured** over a full deployment. Resting current was below about 750 µA on the bench.
7. **Wear-detection thresholds not validated.** They were tuned by eye on a small number of recordings, with no ground-truth record of when the splint was actually worn (§5.4).
8. **No clock correction.** Timestamps rely on the board's crystal drifting very little over weeks; this has not been measured.
9. **Unsigned builds.** Windows SmartScreen and macOS Gatekeeper warn on first launch (the SOP covers the workaround).

## 1.3 Recommended next steps

1. Fix the firmware issues together, in one firmware release (Appendix A): wrap-safe sleep (item 4), the storage bound (item 5), and, ideally, starting the recording at Initialize (item 1) and choosing idle vs. logging by USB presence rather than by power-up count (item 2). Bench-test across the `millis()` wrap. Re-flash all loggers **after downloading their data**.
2. Measure battery life: one logger on the bench for a full month (or until the battery is flat), recording its voltage or current.
3. Collect ground truth (Appendix B): a few deployments with a wear diary or a second reference sensor. Use them to check the detector, especially on overnight wear (item 3), and re-tune the thresholds.
4. Measure clock drift over a month against a reference time.
5. Fill in the **\[TODO\]** hardware sections of the SOP (battery, power switch, enclosure, mounting).

## 1.4 Documents & files reference

| Document | Use it for |
|----------|----------|
| `docs/SOP_Build_and_Use.md` (+ `.docx`) | Building the logger, deployments, download, analysis, troubleshooting |
| `docs/Project_Handover.md` (+ `.docx`) | This document: state, design rationale, future directions |
| `HANDOFF.md` | Developer reference: file roles, flash layout, algorithm parameters table, vendored assets, release runbook |
| `README.md` | Overview, quick start, serial protocol, data format |

| File / folder | Contents |
|----------|----------|
| `collect_temperature/collect_temperature.ino` | Logger firmware |
| `app.py`, `app_instance.py` | App entry point (routing, heartbeat shutdown), shared Dash/Flask/SocketIO objects |
| `arduino.py` | `ArduinoClient`: port search, initialize, download; participant-ID rules |
| `pages/index_page.py` | Home page: Initialize and Download flows |
| `pages/data_analysis_page.py` | Data Analysis page: plots, events table, summaries |
| `pages/analysis_helper.py` | Parsing, time zones, wear detection, timestamp recovery |
| `timezone_config.py` | Display time zone (America/New_York) |
| `tests/` | pytest suite (no hardware) |
| `setup.py` | cx_Freeze build configuration and app version |
| `.github/workflows/tests.yml`, `build-release.yml` | Tests on every pull request; Windows/macOS builds on a `v*` tag |
| `docs/` | SOP, this document, figures (`docs/images/`), and the build script |
| `docs/build_docs.sh` | Regenerates both `.docx` files from their Markdown |

**Editing these documents.** The Markdown files are the master copies. The Word files are generated from them with `bash docs/build_docs.sh` (needs pandoc), so edits made only in Word are lost at the next rebuild.

## 1.5 Handover logistics

- **Hardware:** Room 1588, Elborn College, Western University. It may be relocated after October 2026. **\[TODO\]**: list of loggers and splints and their state.
- **Code and documents:** the GitHub repository (Jamie215/splint_adherence) is owned by Jamie Kim. The successor is expected to fork or clone it and continue the work in their own copy. GitHub turns off automated workflows (Actions) in a fork by default; enable them to keep the tests and the Windows/macOS builds running.
- **Data:** **\[TODO\]**: where study recordings and deployment logs are stored, and who can grant access.
- **Questions:** reach out to Jamie Kim (jamiejmkim.jmk@gmail.com).

# Key terms

| Term | Meaning |
|-----|-----------|
| Logger / device | The Arduino Nano 33 BLE Sense board in the splint, with its sensors |
| HS300x | The board's temperature (and humidity) sensor; only temperature is used |
| APDS9960 | The board's proximity/light/gesture sensor; only proximity is used. Reads 0–255, **low = something close** (splint worn) |
| Firmware | The program running on the logger (an Arduino "sketch"). Changing it means re-flashing every logger |
| Flash | The logger's built-in memory, which keeps the settings and readings without power |
| Initialize | Sending the start time and participant ID to the logger; erases the previous recording |
| Logging / idle mode | Recording with USB off / waiting for the app with USB on. Toggled on every power-up |
| Power-cycle | Turning the logger off and on |
| `millis()` | The board's millisecond counter since power-on; the logger's only clock. 32 bits, so it wraps after ~49.7 days |
| Epoch | Time as seconds since 1 Jan 1970 UTC; how the logger stores the start time |
| Baseline / delta | The rolling-minimum temperature (taken as room temperature), and the temperature above it |
| Onset / offset | The start / end of a detected wear event |
| Dash / Flask | The Python web frameworks the app is built on; the app runs a local web server and opens in the browser |
| cx_Freeze | The tool that packages the Python app into a stand-alone Windows/macOS program |

# 2. Problem and goals

The goal is a low-cost way to measure **how consistently a patient wears a prescribed splint** — when, and for how long each day — without relying on self-report.

| Goal | Explanation |
|------|-------------|
| Objective wear time | Estimate wear periods from sensor data, not patient diaries |
| Long, unattended recording | Record for weeks with no interaction: no charging, no syncing, no app on the patient's phone |
| Simple for research staff | One app to set up a logger, download it, and see the results, with no programming |
| Low cost, off-the-shelf | Use a standard board with built-in sensors, so loggers are easy to build and replace |

**Scope:** wear detection from body heat and sensor covering, at 5-minute resolution, for deployments of up to about a month. Recognising *how* the splint is worn (fit, position) or activity during wear is out of scope.

# 3. System architecture

The logger records on its own during the deployment. It only talks to a computer before (Initialize) and after (Download) a deployment, over USB serial (Figure 1).

![Figure 1. The logger's states. Each power-up moves it along the arrows; the app can only reach it in the idle states (1 and 4).](images/device_lifecycle.png){width=100%}

## 3.1 Record on the device, analyse on the computer

- **Design Decision:** The logger only measures and stores. All interpretation (time zones, wear detection, summaries) happens in the app.
- **Why:** The detection rules are still being tuned. Keeping them on the computer means old recordings can be re-analysed with improved rules, and changes need no re-flashing. It also keeps the firmware small and the stored data raw.
- **Alternatives:** Detecting wear on the board (stores less, but loses the raw data and needs re-flashing to change); streaming over Bluetooth to a phone (needs the patient's phone and much more power).

## 3.2 Hardware

- **Design Decision:** Arduino Nano 33 BLE Sense, using its built-in HS300x temperature and APDS9960 proximity sensors.
- **Why:** Both sensors are already on the board, so there is no extra wiring. The nRF52840 has enough flash for a month of readings and can be put into a low-power state. The board also has Bluetooth for a future wireless version.
- **Trade-off:** The board is larger and draws more current than a purpose-built logger.

## 3.3 Serial protocol

- **Design Decision:** Four one-character commands over USB serial at 9600 baud: `?` handshake (`Hello World!`), `!` status (`HAS_DATA` / `NEED_CONFIGURATION`), `i` initialize (a 28-byte packed record: start epoch, interval, ID, checksum), `r` read (CSV rows ending `END_DATA`).
- **Why:** Simple to implement on both sides and easy to test by hand in the Arduino Serial Monitor. The app finds the logger by sending `?` to every serial port, so the user never has to choose a port.

# 4. Firmware design decisions

## 4.1 Mode chosen by power-up

- **Design Decision:** The logger keeps a mode flag in flash and switches on every power-up: after Initialize (idle, no data) → logging; while logging → idle (Figure 1).
- **Why:** In logging mode USB is switched off to save power, so the computer can't send it a "stop" command. Power-cycling is the only control available without extra buttons.
- **Consequences:** The logger can't be found while logging (the most common support question). Any reset during a deployment ends the recording (§1.2 item 2). Appendix A proposes using USB presence instead.

## 4.2 Settings stored twice (A/B), with a checksum

- **Design Decision:** The settings (start time, interval, participant ID, mode) are kept in two flash pages. Each save writes to the page *not* holding the current copy, with a magic number, sequence number and CRC; on power-up the newest valid copy wins.
- **Why:** The earlier single-page layout could be wiped by a reset during a save, losing the start time. The A/B layout always leaves one good copy.
- **Constraint:** Loggers flashed before this change hold settings the current firmware doesn't recognise. They report `UNKNOWN` start times until re-initialized; download first.

## 4.3 Low power by switching peripherals off, not by deep sleep

- **Design Decision:** In logging mode the firmware disables USB, UART, the radio and other unused peripherals, and waits between readings with `delay()`. Resting current measured below about 750 µA.
- **Why:** Simple and proven on the bench. A deeper sleep (RTC2 timer + `__WFI`, aimed at the ~584 µA that `delay()` leaves) was tried in August 2026 and reverted the same day (commits `b0cdfce` → `c153218`); the reason is not recorded, so treat it as untested rather than ruled out.
- **Lesson:** **Do not disable SPI0/SPI1.** On the nRF52840 they share hardware with the I2C controllers the sensors use. Disabling them stopped the proximity read and nothing was logged.

## 4.4 Fixed 5-minute interval, elapsed-time records

- **Design Decision:** One reading every 300 s (`WAKEUP_INTERVAL_SECONDS` in `arduino.py`, sent at Initialize). Each record stores seconds elapsed since logging started, plus temperature and proximity, in 12 bytes; the app adds the start time.
- **Why:** 5 minutes resolves wear periods well enough for daily totals, and fits a month in flash. The analysis infers the real interval from the timestamps, so the interval can be changed without changing the analysis.

## 4.5 Robust proximity reads

- **Design Decision:** Discard the first 2 proximity samples after the sensor wakes, and bound every wait with a timeout; a missing sensor logs `0`.
- **Why:** The first samples after wake-up are unsettled, and an unbounded wait on a faulty sensor would freeze the logger for the rest of the deployment.

# 5. Wear-detection algorithm (app)

Full parameter table: `HANDOFF.md` §4.

## 5.1 Temperature above a rolling baseline

- **Design Decision:** Take room temperature as the rolling minimum over about 2 hours, and look at the rise above it (delta). An event starts when the sensor is covered, the temperature has risen over the last ~15 minutes, and either the jump is ≥ 0.8 °C in one sample or the rise is ≥ 3 °C. It ends when the sensor is uncovered, or the temperature is falling fast (≥ 0.4 °C per sample) and is near baseline or below 80 % of the event's peak rise.
- **Why:** Room temperature changes over the day, so a fixed threshold would fail; the rolling minimum follows it. The 15-minute trend check stops cooling slopes from triggering false onsets.
- **Known weakness:** see §1.2 item 3: during long wear the baseline catches up with skin temperature.

## 5.2 Proximity as a gate

- **Design Decision:** Use the proximity sensor only to confirm "covered", not to detect wear on its own.
- **Why:** Temperature alone can't tell wear from a warm environment (e.g. the splint left on a radiator or in the sun); the covered sensor rules those out.

## 5.3 Drift-invariant "covered"

- **Design Decision:** Track the proximity floor as the rolling 10th percentile over about a day, subtract it, and call the sensor covered when the remainder is within the noise (`max(5, 4 × MAD)`).
- **Why:** On a 35-day recording the proximity reading while worn crept from 0 into the 50s as the battery discharged. The original test (`prox == 0`) stopped working after about 11 days, and wear was missed from then on.

## 5.4 Thresholds are empirical

All thresholds were set by inspecting a small number of recordings. There is no ground truth yet; Appendix B describes how to get one.

# 6. Time handling

- **Design Decision:** The logger knows only UTC epoch seconds. The app asks for and shows **Eastern time** (America/New_York, daylight-saving aware) everywhere, and writes timestamps with their UTC offset (e.g. `-04:00`).
- **Why:** The study runs in Ontario. The offset keeps the repeated hour at the November change unambiguous, and durations across the change come out right. Plotly is given wall-clock times so the charts show Eastern time whatever the browser's own time zone.
- **Recovery:** If a logger loses its start time, the elapsed times survive. The app detects such files and rebuilds the timestamps from a start time the user enters (`recover_timestamps`), during download or on the Data Analysis page.
- **To change the zone:** edit `timezone_config.py`.

# 7. Desktop app

- **Browser-based UI (Dash + Flask-SocketIO on gevent).** Charts and tables come almost for free with Plotly/Dash; the app runs a local server on `127.0.0.1:8050` and opens the browser.
- **Heartbeat shutdown.** The page sends a heartbeat every 5 s. With none for 5 minutes, the server warns the page and exits, so closing the tab doesn't leave an invisible server holding the serial port.
- **Works offline.** Fonts, theme and icons are bundled under `assets/vendor/` instead of loaded from CDNs, because clinic computers may have no internet.
- **Stand-alone builds.** cx_Freeze bundles Python and all dependencies, so staff need no Python. GitHub Actions builds Windows and macOS on each `v*` tag (SOP Appendix B).
- **Participant IDs.** Letters, digits, `-` and `_`, up to 15 characters: they go into the CSV header and often into file names, where commas or spaces would cause trouble.

# 8. Testing and validation to date

| Area | Status |
|----------|----------|
| Logging over a deployment | Recordings up to ~36 days collected and analysed |
| Resting current | Below ~750 µA on the bench |
| Proximity drift | Seen on a 35-day recording; handled in analysis (§5.3), covered by a test |
| Analysis code | 22 automated tests (detection, drift invariance, DST, legacy files, recovery, serial parsing) |
| Battery life | **Not measured** |
| Clock rollover (~49.7 d), storage bound (~52 d) | **Predicted from code**, not bench-tested |
| Wear-detection accuracy | **Not validated** against ground truth |
| Clock drift | **Not measured** |

# 9. Directions to explore

| Area | Recommendation |
|-------|---------------|
| A. Firmware robustness | Start logging at Initialize, choose idle/logging by USB presence, wrap-safe timing, enforce the storage bound (Appendix A) |
| B. Ground truth and re-tuning | Wear diary or reference sensor on a few deployments; re-tune and fix long-wear handling (Appendix B) |
| C. Battery monitoring | Log the battery voltage with each reading, so a dying battery shows in the data |
| D. Wireless download | Use the board's Bluetooth to download without opening the splint; adds power and pairing complexity |
| E. Real-time clock | An external RTC (or the nRF52840's RTC with drift calibration) would remove the power-on timing error and the rollover limit |

# Appendix A — Firmware robustness

**Status:** Problems identified from the code (§1.2 items 1, 2, 4, 5). Not yet implemented.

## A.1 Start the recording at Initialize

Today the logger powers down at Initialize and starts counting time at the *next* power-on, so the start time is only right if staff power it on at the entered minute. Alternatives:

- **Start at Initialize, from the computer's clock.** The app sends "now" and the logger begins logging immediately (no power-down). The start time is then exact, and the scheduled-start option disappears.
- **Keep the scheduled start, but count from Initialize.** The logger stays on (in low power) after Initialize and starts recording when the entered start time arrives. Also exact, at the cost of a little battery between Initialize and the start.

Either removes the main source of timestamp error. The second keeps today's workflow.

## A.2 Idle vs. logging by USB presence

Choose the mode at power-up by whether USB power is present (the nRF52840 reports this), instead of toggling on every power-up:

- USB connected → idle, answer the app.
- No USB → if initialized, (re)start or **resume** logging, appending after the last record.

This makes resets during a deployment harmless (the logger resumes; record the gap), and "can't find the logger" goes away: plugging it in is enough. Resuming needs the elapsed time to continue across the reset, e.g. by storing a reset counter and leaving a marker row in the data.

## A.3 Timing and storage

- Wrap-safe sleep: `if ((int32_t)(nextWakeTime - currentTime) > 0)`. Test across the wrap with a temporary offset of about 2³² − 10 min added to `millis()` in the logging path.
- Stop at `MAX_DATA_ENTRIES` in `saveTemperatureReading`, or erase all the pages that may be written.
- Consider counting time in seconds from an RTC tick instead of `millis()`.

## A.4 Next steps

Implement A.3 first (small, low risk), then A.1/A.2 together, bench-test for a full month, and update the SOP (§1.1, §6, §7).

# Appendix B — Ground truth and re-tuning the detector

**Status:** Needed before wear times are reported as results.

## B.1 Collecting ground truth

- **Wear diary:** the participant (or staff, in a supervised session) records on/off times. Cheap, but coarse and subject to the same recall bias the logger is meant to avoid.
- **Supervised sessions:** scripted on/off periods in the lab, including long continuous wear and confounders (warm room, splint left on a warm surface, covered but not worn).
- **Reference sensor:** a second, independent sensor (e.g. a commercial temperature button logger on the skin side) for a few deployments.

## B.2 What to check

- Per-event agreement (onset/offset within ±1 sample) and per-day wear minutes.
- **Long wear:** whether overnight wear is split or cut short (§1.2 item 3). Possible fixes: a longer baseline window, freezing the baseline while an event is in progress, or requiring two consecutive cooling samples before ending an event.
- False positives in warm environments, and false negatives with a loose splint.

## B.3 Next steps

Add each labelled recording to `tests/` as a regression case, then re-tune the thresholds in `detect_onsets_offsets` against them and record the new values in `HANDOFF.md` §4.
