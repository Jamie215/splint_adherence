---
title: "Measuring Temperature and Muscle Contraction in Custom Orthotic Devices — Project Handover"
subtitle: "State at transition, design decisions and their rationale, and directions to explore"
---

*October 2026 Ver. Prepared by Jamie Kim.*

# About this document

This is the handover record for the project *Measuring Temperature and Muscle Contraction in Custom Orthotic Devices*, specifically its splint adherence logger: a temperature and proximity logger embedded in a thermoplastic splint, and the desktop app that configures it and estimates wear time from its recordings (May 2024 – October 2026). It is composed of the following:

- **Handover summary (§1):** where the project stands, what has been tested, all next steps (including ethics and data governance) in one place, and who to contact. Read this first.
- **Problem and goals (§2):** what the system is for.
- **Design decisions (§3–§7):** what was decided, why, and which alternatives were considered.
- **Directions to explore (§8):** larger changes worth considering later.

Companion documents are listed in §1.3, and terms are explained under *Key terms*, after §1.

The muscle contraction variant of the project work will not be discussed as it was only explored at a preliminary level and has a different objective, where its focus is observing how much does the splint deactivate the target muscle.

**Where to start**

| If you want to… | Start with |
|--------|--------|
| Know whether the system is ready and what is left to do | §1 |
| Build a logger, run a deployment, or download and analyze data | The SOP (`docs/SOP_Build_and_Use.docx`) |
| Change the app or the firmware | `README.md`, then `HANDOFF.md` (developer reference), then §3–§7 of this document |
| Understand why it works the way it does | §2–§7 |

# 1. State at transition (October 2026)

**Summary.** The system works end to end: a logger can be set up with the app, worn in the splint for up to about a month, and downloaded, and the app turns the recording into daily wear time and an hour-by-hour picture of when the splint was worn. Two loggers have been built. They take a reading every 5 minutes, and the app estimates wear time from those readings. The detection has not yet been fully validated against a record of actual wear. Before a study with participants, ethics approval and a data-governance plan are needed, the known firmware issues should be fixed, battery life measured, and wear detection validated (§1.2).

## 1.1 Current state

- **Working logger.** Arduino Nano 33 BLE Sense (nRF52840) with its built-in HS300x temperature and APDS9960 proximity sensors. It records one reading every 5 minutes to its own flash memory, for up to about 52 days of storage, and is configured and read over USB.
- **Desktop application (v1.3.0).** It initializes loggers, downloads recordings to CSV, recovers lost start times, and shows detected wear events, daily wear totals and an hour-of-day timeline. Built for Windows and macOS by GitHub Actions on each version tag, and published on the repository's Releases page.
- **Preliminary test.** Recordings of up to about 36 days have been collected and analyzed to tune the wearing detection algorithm. There are two loggers built, where one of them needs reconnection at the rear 3.3 V trace to update the firmware while the other one is ready for deployment. The logger that requires updated firmware has a tag attached noting that its firmware needs updating.
- **Tested so far.** Resting current below about 750 µA on the bench. The proximity reading was found to drift upward over a 35-day recording, and the analysis now allows for it (§5.3). 22 automated tests (wear detection, time zones, timestamp recovery, serial protocol) run on every change to the app.

## 1.2 Next steps

All remaining work, in recommended order.

| Item | Status | What to do | Details |
|----------|----------|------------------------------|-----------|
| 1. Firmware fixes (timing, storage, start time) | Predicted from code; not bench-tested | *Why:* recordings longer than about 7 weeks may be corrupted, and timestamps are only right if the logger is powered on at the entered start time. First confirm the storage issue: initialize a logger with a 1-second interval (temporary change to `WAKEUP_INTERVAL_SECONDS` in `arduino.py`) and leave it for 5 hours; the download should stop at exactly 15 000 rows. Then fix wrap-safe sleep and the storage limit (small, low risk), then start data collection at Initialize, in one firmware release. Bench-test for a full month, re-flash loggers after downloading their data, and update the SOP. | §4.4; `HANDOFF.md` §8 |
| 2. Battery life | Not measured with the latest firmware; resting current below ~750 µA | *Why:* sets how long a deployment can safely run. A CR2450 (~620 mAh) at ~750 µA gives a rough upper bound of about 34 days, consistent with the ~36-day recording; until measured, fit a new cell for every deployment. One logger on the bench for a full month or until the battery dies, which is the duration of expected battery life. | §3.2; §4.3 |
| 3. Ethics approval | Not started | *Why:* required before any deployment with participants, including the ground-truth deployments in item 5. Prepare the submission covering the device (worn against the skin, battery-powered, research prototype), what is recorded, and how data is handled (item 4). | §7.1; SOP §1 |
| 4. Data-governance plan | Not started; no policy exists | *Why:* the app leaves data handling to the user (§7.1). Decide where recordings and deployment logs are stored, who can access them, the participant ID scheme, how long data is kept, and how it is moved off the study computer; then update the SOP (§10). | §7.1; SOP §10 |
| 5. Wear-detection accuracy | Not fully validated | *Why:* needed before wear times are reported as study results. Collect ground truth on a few deployments (wear diary or reference sensor), check overnight wear especially, and re-tune the thresholds accordingly. | §5; SOP Appendix C |
| 6. Clock drift | Not measured; expected negligible | *Why:* confirms the timestamps stay accurate over a deployment, at no extra cost. At the end of each deployment, note the real time of the power-cycle and compare it with the last timestamp in the file. They should agree within one interval (5 minutes); a larger gap shows drift or a late power-on. | §4.4 |

## 1.3 Documents

| Document | Use it for |
|----------|----------|
| `docs/SOP_Build_and_Use.md` (+ `.docx`) | Building the logger, deployments, download, analysis, troubleshooting, tuning the detection |
| `docs/Project_Handover.md` (+ `.docx`) | This document: state, design rationale, future directions |
| `HANDOFF.md` | Developer reference: code layout, flash layout, algorithm parameters, known firmware issues and fixes, release runbook |
| `README.md` | Overview, quick start, serial protocol, data format |

## 1.4 Handover logistics

- **Hardware location:** Room 1588, Elborn College, Western University. It may be relocated after October 2026.
- **Code and documents:** the GitHub repository (Jamie215/splint_adherence) is owned by Jamie Kim. The successor is expected to fork or clone it and continue the work in their own copy. GitHub turns off automated workflows (Actions) in a fork by default; enable them to keep the tests and the Windows/macOS builds running.
- **Questions:** reach out to Jamie Kim (jamiejmkim.jmk@gmail.com).

# Key terms

| Term | Meaning |
|-----|-----------|
| Logger / device | The Arduino Nano 33 BLE Sense board with programmed hardware, designed to be in the splint |
| App (GUI) | The desktop application used to set up loggers, download recordings and view the analysis |
| Deployment | One period during which a participant wears the splint with a logger collecting data |
| Wear event | A period the app judges the splint was worn, from its start (onset) to its end (offset) |
| Ground truth | An independent record of when the splint was actually worn (e.g. a diary or a second sensor), used to check the detection |
| HS300x | The board's temperature (and humidity) sensor; only temperature is used |
| APDS9960 | The board's proximity sensor. Reads 0–255; a low value means the splint is worn |
| Firmware | The program running on the logger (an Arduino "sketch"). Changing it means re-flashing every logger |
| Flash | The logger's built-in memory, which keeps the settings and readings without power |
| Initialize | Sending the start time and participant ID to the logger; erases the previous recording |
| Data collection / idle | The logger recording with USB off / waiting for the app with USB on. Switches on every power-up |
| Power-cycle | Turning the logger off and on |
| Serial (USB serial) | The text connection over the USB cable between the app and the logger (9600 baud) |
| `millis()` | The board's millisecond counter since power-on; the logger's only clock. 32 bits, so it wraps after ~49.7 days |
| Epoch | Time as seconds since 1 Jan 1970 UTC; how the logger stores the start time |
| Baseline / delta | The rolling-minimum temperature (taken as room temperature), and the temperature above it |
| Dash / Flask | The Python web frameworks the app is built on; the app runs a local web server and opens in the browser |

# 2. Problem and goals

The goal is to measure **how consistently a patient wears a prescribed splint** — when, and for how long each day, without relying on self-report.

| Goal | Explanation |
|------|-------------|
| Objective wear time | Estimate wear periods from sensor data, not patient diaries |
| Long, unattended recording | Record for weeks with no interaction: no charging, no syncing, no app on the patient's phone |
| Simple workflow | One app to set up a logger, download it, and see the results |
| Low cost, off-the-shelf | Use a standard board with built-in sensors, so loggers are easy to build and replace |

**Scope:** wear detection from body heat and sensor covering, at 5-minute resolution, for deployments of up to about a month.

# 3. System architecture

Sections 3–7 explain the technical design; readers who only need the status can stop after §2.

The logger records on its own during the deployment. It only talks to a computer before (Initialize) and after (Download) a deployment, over USB serial (Figure 1).

![Figure 1. The logger's states and what triggers each change.](images/device_lifecycle.png){width=100%}

## 3.1 Record on the device, analyze on the computer

- **Design Decision:** The logger only measures and stores. All interpretation (time zones, wear detection, summaries) happens in the app.
- **Why:** This enables fine-tuning the detection algorithm as raw recordings are preserved. It also keeps the firmware small and simple, ideal for low power mode operation.
- **Alternatives:** Detecting wear directly on the board; streaming over Bluetooth to a phone (needs the patient's phone and consumes more power).

## 3.2 Hardware

- **Design Decision:** Arduino Nano 33 BLE Sense, using its built-in HS300x temperature and APDS9960 proximity sensors.
- **Why:** Both sensors are already on the board, so there is no extra wiring. The nRF52840 has enough flash for a month of readings and can be put into a low-power state. The board also has Bluetooth available if pursuing a wireless version in future.
- **Trade-off:** The board is larger and draws more current than a custom designed printed circuit board.
- **Power:** A CR2450 coin cell on the 3.3 V pin, with the 3.3 V jumper on the back of the board cut so the board's regulator and USB circuitry draw no power. As a result, USB alone cannot power the logger: the cell must be connected whenever it is used with the app, and flashing new firmware needs the jumper bridged, then cut again (SOP §4.2). This is why one logger currently needs its 3.3 V trace reconnected before its firmware can be updated (§1.1).
- **Case and mounting:** A 3D-printed case (`splint_adherece_case.stl` in the repository) holds the board with the sensors facing the skin, behind skin-friendly tape. It is moulded into each participant's custom splint and secured through the thermoplastic with a Chicago screw, so the case and logger can be moved to the next participant's splint.

# 4. Firmware

## 4.1 Mode chosen by power-up

- **Design Decision:** The logger keeps a mode flag in flash and changes it on every power-up: an initialized logger with no data starts data collection; a logger collecting data becomes idle (Figure 1).
- **Why:** During data collection USB is switched off to save power, so the computer can't send a "stop" command. Power-cycling is the only control available without extra buttons.
- **Limitation:** The logger can't be seen by the app during data collection; power-cycle it first. Any reset or power loss during data collection also counts as a power-up, so the recording ends there: the data so far is kept, but nothing more is recorded. Secure the battery and record any interruption in the deployment log.

## 4.2 Settings stored twice (A/B), with a checksum

- **Design Decision:** The settings (start time, interval, participant ID, mode) are kept in two flash pages. Each save writes to the page *not* holding the current copy, with a magic number, sequence number and CRC; on power-up the newest valid copy wins.
- **Why:** The earlier single-page layout could be wiped by a reset during a save, losing the start time. The A/B layout always leaves one good copy.
- **Constraint:** Loggers flashed before this change hold settings the current firmware doesn't recognize. They report `UNKNOWN` start times until re-initialized; these loggers will need to be updated to the latest firmware.

## 4.3 Low power by switching peripherals off

- **Design Decision:** During data collection the firmware disables USB, UART, the radio and other unused peripherals, and waits between readings with `delay()`. Resting current measured below about 750 µA.
- **Why:** A deeper sleep (RTC2 timer + `__WFI`) was tried, but the Arduino never woke up to resume collecting data once in deep sleep; it may still be worth revisiting to further optimize battery life.

## 4.4 Fixed 5-minute interval, elapsed-time records

![Figure 2. One reading, from flash to the downloaded CSV.](images/data_row.png){width=100%}

- **Design Decision:** One reading every 300 seconds (5 minutes) (`WAKEUP_INTERVAL_SECONDS` in `arduino.py`, sent at Initialize). Each record stores seconds elapsed since data collection started (from `millis()`), plus temperature and proximity, in 12 bytes; the app adds the start time.
- **Why:** The board has no real-time clock, so elapsed time is the simplest reliable record. 5 minutes resolves wear periods well enough for daily totals, and fits a month in flash. The analysis infers the real interval from the timestamps, so the interval can be changed without changing the analysis.
- **Limitations:**
  - *Start time.* Elapsed time counts from the power-on that starts data collection, while the start time is the one typed into the app at Initialize. Any gap between the two shifts every timestamp by that amount, and nothing in the file shows it. Fix: §1.2 item 1.
  - *Rollover.* `millis()` is 32-bit and wraps at about 49.7 days, and the sleep check `nextWakeTime > currentTime` is not wrap-safe: expect a burst of readings, then a long gap. The stored elapsed times stay correct. Fix: §1.2 item 1; until then, keep deployments to about a month.
  - *Clock accuracy.* Timestamps rely on the board's oscillator, with no correction. With the board's crystal (tens of ppm) the error is about 1–2 minutes a month, well under one interval; while this is not measured directly, it is a commonly known limitation of using onboard crystal (check: §1.2 item 6).

## 4.5 Robust proximity reads

- **Design Decision:** Discard the first 2 proximity samples after the sensor wakes, and bound every wait with a timeout; a missing sensor logs `0`.
- **Why:** The first samples after wake-up are unsettled, and an unbounded wait on a faulty sensor would freeze the logger for the rest of the deployment.

# 5. Wear-detection algorithm

Full parameter table: `HANDOFF.md` §4. How to re-tune: SOP Appendix C.

## 5.1 Temperature above a rolling baseline

- **Design Decision:** Take room temperature as the rolling minimum over about 2 hours, and look at the rise above it (delta). An event starts when the proximity sensor is covered, the temperature has risen over the last ~15 minutes, and either the jump is ≥ 0.8 °C in one sample or the rise is ≥ 3 °C. It ends when the proximity sensor is uncovered, or the temperature is falling fast (≥ 0.4 °C per sample) and is near baseline or below 80 % of the event's peak rise.
- **Why:** Room temperature changes over the day, so a fixed threshold would fail; the rolling minimum follows it. The 15-minute trend check stops cooling slopes from triggering false onsets.
- **Limitations:**
  - *Short wear.* Events shorter than 2 readings are dropped, so wear periods under about 10 minutes are not counted, and every start and end time is accurate to one 5-minute step.
  - *Long wear.* After about an hour of continuous wear the 2-hour window holds only "worn" samples, so the baseline rises to skin temperature and delta falls to about 0. From then on, a single drop of 0.4 °C between samples ends the event, and it cannot restart (that needs delta ≥ 3 °C or a jump ≥ 0.8 °C). On synthetic 8-hour overnight wear, noise with a standard deviation of 0.15 °C split the nights into short pieces; with 0.04 °C they were detected whole. Possible fixes are in SOP Appendix C; validation is §1.2 item 5.

## 5.2 Proximity as a gate

- **Design Decision:** Use the proximity sensor only to confirm "covered", not to detect wear on its own.
- **Why:** Temperature alone can't tell wear from a warm environment (e.g. the splint left on a radiator or in the sun); the covered sensor rules those out.

## 5.3 Drift-invariant "covered"

- **Design Decision:** Track the proximity floor as the rolling 10th percentile over about a day, subtract it, and call the sensor covered when the remainder is within the noise (`max(5, 4 × MAD)`, where MAD is the median absolute deviation).
- **Why:** On a 35-day recording the proximity reading while worn crept from 0 into the 50s as the battery discharged. The original test (`prox == 0`) stopped working after about 11 days, and wear was missed from then on.

## 5.4 Thresholds are empirical

All thresholds were set by inspecting a small number of recordings. A finer tuning may be required based on the larger sample data; SOP Appendix C describes how.

# 6. Time handling

- **Design Decision:** The logger knows only UTC epoch seconds. The app asks for and shows **Eastern time** (America/New_York, daylight-saving aware) everywhere, and writes timestamps with their UTC offset (e.g. `-04:00`).
- **Why:** The study runs in Ontario. The offset keeps the repeated hour at the November change unambiguous, and durations across the change come out right.
- **Recovery:** If a logger loses its start time, the elapsed times survive. The app detects such files and rebuilds the timestamps from a start time the user enters, during download or on the Data Analysis page.
- **To change the zone:** edit `timezone_config.py`.

# 7. Desktop application

- **Browser-based interface (Dash + Flask-SocketIO).** Plotly/Dash provide the charts and tables; the app runs a local server on `127.0.0.1:8050` and opens the browser.
- **Heartbeat shutdown.** The page sends a heartbeat every 5 s. With none for 5 minutes, the server warns the page and exits, so closing the tab doesn't leave a hidden server holding the serial port for data privacy.
- **Works offline.** All required assets are packaged, allowing the application to be usable in offline conditions as well.
- **Automated releases.** GitHub Actions builds stand-alone Windows and macOS programs on each `v*` tag, with Python included, so staff need no Python (SOP Appendix B).
- **Participant IDs.** Letters, digits, `-` and `_`, up to 15 characters: they go into the CSV header and often into file names, where commas or spaces would cause trouble.

## 7.1 Data handling (app behaviour)

This describes what the software does with data. It is not a data-handling policy; none exists yet (§1.2 item 4).

- **Where data goes.** Everything stays on the study computer. The app runs a local server that only that computer can reach (`127.0.0.1`), and it sends nothing over the internet.
- **On the logger.** Readings and the participant ID are stored unencrypted in the logger's flash memory, and stay there until the logger is initialized again (§4.1). Anyone with the app and the logger can download them.
- **Downloads.** The browser saves each download as a plain CSV file, normally in the Downloads folder. The file holds the participant ID, the start time and every reading. The app keeps no copy.
- **Analysis page.** An uploaded file is processed in memory and is not saved by the app.
- **Participant ID.** It is stored on the logger, in the CSV header and often in file names, so it should be a study code, not a name.
- **Logs.** The app's messages go to its console window only; it writes no log files.

# 8. Directions to explore

| Area | Recommendation |
|-------|---------------|
| Wireless download | Use the board's Bluetooth to download without opening the splint; adds power and pairing complexity |
| Real-time clock | An external RTC would remove the start-time dependence on power-on and the rollover limit |
| Custom printed circuit board | Only the parts needed (microcontroller, temperature and proximity sensors, power regulation) on a board shaped for the splint: smaller, lower current, and better sensor placement against the skin. Needs hardware design and validation |
