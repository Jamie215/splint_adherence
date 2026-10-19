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

The muscle contraction variant of the project work will not be discussed as it was only explored at a preliminary level and has a different objective: observing how much the splint deactivates the target muscle.

**Where to start**

| If you want to… | Start with |
|--------|--------|
| Know whether the system is ready and what is left to do | §1 |
| Build a logger, run a deployment, or download and analyze data | The SOP (`docs/SOP_Build_and_Use.docx`) |
| Change the app or the firmware | `README.md`, then `HANDOFF.md` (developer reference), then §3–§7 of this document |
| Understand why it works the way it does | §2–§7 |

# 1. State at transition (October 2026)

**Summary.** The system works end to end: a logger can be set up with the app, worn in the splint for up to about a month, and downloaded, and the app turns the recording into daily wear time and an hour-by-hour picture of when the splint was worn. Two prototype loggers have been built. They take a reading every 5 minutes, and the app estimates wear time from those readings. The detection has not yet been fully validated against a record of actual wear.

## 1.1 Current state

- **Working logger.** Arduino Nano 33 BLE Sense Rev2 (nRF52840) with its built-in HS300x temperature and APDS9960 proximity sensors. The logger reserves about 176 KB of its flash memory for readings (15 000 readings of 12 bytes each). At one reading every 5 minutes, this comfortably covers the recommended deployment of up to one month. It is set up and read over USB.
- **Desktop application (v1.3.0).** It initializes loggers, downloads recordings to CSV, recovers lost start times, and shows detected wear events, daily wear totals and an hour-of-day timeline. It is built for Windows and macOS by GitHub Actions on each version tag, and published on the repository's Releases page.
- **Preliminary test.** Recordings of up to about 36 days have been collected and analyzed to tune the wear-detection algorithm. Two loggers have been built: one is ready for deployment; the other needs its rear 3.3 V jumper trace reconnected to update its firmware (it is labelled).
- **Tested so far.** Resting current is below about 750 µA on the bench. The proximity reading was found to drift upward over a 35-day recording, and the analysis now accounts for it (§5.3). 22 automated tests (wear detection, time zones, timestamp recovery, serial protocol) run on every change to the app.

## 1.2 Next steps

All remaining work, in recommended order. Battery life comes first because its result decides how urgent the firmware fixes are.

| Item | Status | What to do | Details |
|----------|----------|------------------------------|-----------|
| 1. Battery life | Not measured with the latest firmware; resting current below ~750 µA | *Why:* sets how long a deployment can safely run, and how urgent item 2 is. Leave one logger on the bench for a full month, or until the battery dies. A CR2450 (~620 mAh) at ~750 µA gives a rough upper bound of about 34 days, consistent with the ~36-day recording. Until it is measured, fit a new cell for every deployment. | §3.2; §4.3 |
| 2. Firmware fixes (start time, timing, storage) | Predicted from code; not bench-tested | *Why:* timestamps are only right if the logger is powered on at the entered start time, and recordings longer than about 7 weeks may be corrupted. First, make data collection start at Initialize. Then add wrap-safe sleep and the storage limit; if item 1 confirms a battery life of 30–40 days, a recording never reaches 15 000 readings, so these two are safeguards rather than urgent work. To confirm the storage issue, initialize a logger with a 1-second interval (a temporary change to `WAKEUP_INTERVAL_SECONDS` in `arduino.py`, running the app from Python; SOP Appendix A) and leave it for 5 hours: the download should stop at exactly 15 000 rows. Release the fixes as one firmware update, bench-test it for a full month, re-flash the loggers after downloading their data, and update the SOP. | §4.4; `HANDOFF.md` §8 |
| 3. Ethics approval | Not started | *Why:* required before any deployment with participants, including the ground-truth deployments in item 5. Prepare the study protocol, including participant wear instructions and how often to check the skin, and the submission covering the device (worn against the skin, battery-powered, research prototype), what is recorded, and how data is handled (item 4). | §7.1 |
| 4. Data-governance plan | Not started; no policy exists | *Why:* the app leaves data handling to the user (§7.1). Decide where recordings and deployment logs are stored, who can access them, the participant ID scheme, how long data is kept, and how it is moved off the study computer. | §7.1 |
| 5. Wear-detection accuracy | Not fully validated | *Why:* needed before wear times are reported as study results. On a few deployments, keep an independent record of when the splint was actually worn (ground truth), e.g. a wear diary or supervised sessions. Compare it with the detected wear, especially overnight, and re-tune the thresholds accordingly. | §5; SOP Appendix C |
| 6. Clock drift | Not measured; expected negligible | *Why:* confirms the timestamps stay accurate over a deployment. Run the bench test in SOP Appendix D once; the difference should be under one interval (5 minutes). | §4.4; SOP Appendix D |
| 7. Daily average definition | To confirm | *Why:* the app averages wear time only over days with detected wear (§5.5). Decide which definition the study uses. If every day of the recording should count, divide Total Wear Time by the number of days (SOP §8), or change the app to do so. | §5.5; SOP §8 |

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
| HS300x | The board's temperature (and humidity) sensor; only temperature is used |
| APDS9960 | The board's proximity sensor. Reads 0–255; a low value means the splint is worn |
| Firmware | The program running on the logger (an Arduino "sketch"). Changing it means re-flashing every logger |
| Flash | The logger's built-in memory, which keeps the settings and readings without power |
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
| Long duration of recording | Record unattended for about a month |
| Simple workflow | Easy for the clinician to set up a logger, download it, and see the results |
| Low cost, off-the-shelf | Easy to build and replace |

**Scope:** wear detection from body heat and sensor covering, at 5-minute resolution, for deployments of up to about a month.

# 3. System architecture

Sections 3–7 explain how the logger and the app are designed, and why. In short, the logger records on its own during a deployment and talks to a computer only before it (Initialize) and after it (Download), over USB (Figure 1).

![Figure 1. The logger's states and what triggers each change.](images/device_lifecycle.png){width=100%}

## 3.1 Record on the device, analyze on the computer

The logger only measures and stores; all interpretation (time zones, wear detection and summaries) happens in the app. Because the raw readings are kept, the detection can be re-tuned later and old recordings analyzed again. It also keeps the firmware small and simple, which suits low-power operation.

The alternatives were to detect wear on the board itself, which would discard the raw data, or to stream readings to a phone over Bluetooth, which needs the patient's phone and more power.

## 3.2 Hardware

The logger is an Arduino Nano 33 BLE Sense Rev2, chosen because its built-in HS300x temperature and APDS9960 proximity sensors need no extra wiring. Its nRF52840 chip has enough flash memory for a month of readings, can run in a low-power state, and has Bluetooth if a wireless version is pursued later. The trade-off is that the board is larger and draws more current than a custom printed circuit board would (§8).

It runs on a CR2450 coin cell connected to the 3.3 V pin. The 3.3 V jumper on the back of the board is cut so that the board's regulator and USB circuitry draw no power. As a result, USB alone cannot power the logger: the cell must be connected whenever the logger is used with the app, and flashing new firmware needs the jumper bridged first and cut again afterwards (SOP §3.2). This is why one of the two loggers needs its jumper reconnected before its firmware can be updated (§1.1).

The board sits in a 3D-printed case (`splint_adherece_case.stl` in the repository), with the sensors facing the skin behind skin-friendly tape. The PI (an orthopedist) moulds the case into each participant's custom splint while making the splint, and Chicago screws secure it through the thermoplastic, so the case and logger can be moved to the next participant's splint.

# 4. Firmware

## 4.1 Mode chosen at power-up

The logger has no buttons or commands to start and stop recording. Instead, the firmware keeps a mode flag in flash and changes it each time the logger is powered up: an initialized logger with no data starts collecting data, and a logger that was collecting data becomes idle (Figure 1). This is needed because USB is switched off during data collection to save power, so the computer cannot send a "stop" command.

As a result, the app cannot see a logger while it is collecting data; the logger has to be power-cycled first. Any reset or power loss counts as a power-cycle, so the recording keeps every reading up to that moment but stops there.

## 4.2 Settings stored twice

The settings (start time, interval, participant ID and mode) are saved in two separate flash pages. Each save goes to the page that does not hold the current copy and carries a sequence number and a checksum (CRC); at power-up the newest valid copy is used. A reset during a save can therefore never destroy the last good copy, which is how the earlier single-page layout could lose the start time.

Loggers flashed before this change hold settings that the current firmware does not recognize. They report `UNKNOWN` start times until they are re-initialized, and need to be updated to the latest firmware.

## 4.3 Low power by switching peripherals off

During data collection the firmware switches off USB, the serial ports, the radio and other unused parts of the chip, and waits between readings with `delay()`. The resting current measured below about 750 µA. A deeper sleep mode (RTC2 timer + `__WFI`) was tried, but the board never woke up from it to take the next reading; it may still be worth revisiting to extend battery life.

## 4.4 Fixed 5-minute interval, elapsed-time records

The logger takes one reading every 5 minutes (`WAKEUP_INTERVAL_SECONDS` in `arduino.py`, sent at Initialize). The board has no real-time clock, so each record stores the seconds elapsed since data collection started (counted by `millis()`), plus the temperature and proximity, in 12 bytes. The app adds the start time when the data are downloaded (Figure 2).

![Figure 2. One reading, from flash to the downloaded CSV.](images/data_row.png){width=100%}

Five minutes resolves wear periods well enough for daily totals, and a month of readings fits in flash. The analysis works out the actual interval from the timestamps, so the interval can be changed without changing the analysis.

This design has three limitations:

- **Start time.** Elapsed time counts from the power-on that starts data collection, while the start time is the one entered at Initialize. Any gap between the two shifts every timestamp by that amount, and nothing in the file shows it. §1.2 item 2 removes this.
- **Rollover.** `millis()` wraps after about 49.7 days, and the sleep check (`nextWakeTime > currentTime`) is not wrap-safe: expect a burst of readings, then a long gap. The stored elapsed times stay correct. §1.2 item 2 fixes this; until then, keep deployments to about a month.
- **Clock accuracy.** Timestamps rely on the board's crystal, with no correction. Its error is typically about 1–2 minutes a month, well under one reading interval; this has not been measured directly (§1.2 item 6).

## 4.5 Reliable proximity readings

The first two proximity readings after the sensor wakes are unsettled, so the firmware discards them. Every wait for the sensor has a time limit, so a faulty sensor logs `0` instead of freezing the logger for the rest of the deployment.

# 5. Wear-detection algorithm

The app decides when the splint was worn from two signals: the skin warms the temperature sensor, and the splint covers the proximity sensor. The full parameter table is in `HANDOFF.md` §4, and SOP Appendix C describes how to re-tune it.

## 5.1 Temperature above a rolling baseline

Room temperature changes over the day, so a fixed temperature threshold would fail. Instead, the app takes the lowest temperature over a rolling window of about 2 hours as the room temperature (the baseline) and looks at the rise above it (delta).

A wear event starts when the proximity sensor is covered, the temperature has risen over the last ~15 minutes, and either it jumped by at least 0.8 °C in one reading or it is at least 3 °C above the baseline. The 15-minute check stops a cooling splint from triggering a false start. An event ends when the proximity sensor is uncovered, or when the temperature falls fast (by at least 0.4 °C per reading) and is back near the baseline or below 80 % of the event's peak rise.

Two limitations follow:

- **Short wear.** Events shorter than 2 readings are dropped, so wear under about 10 minutes is not counted, and each start and end time is accurate to one 5-minute step.
- **Long wear.** After about an hour of continuous wear, the 2-hour window holds only "worn" readings, so the baseline rises to skin temperature and delta falls to about 0. From then on, a single drop of 0.4 °C ends the event, and it cannot restart (that needs delta ≥ 3 °C or a jump ≥ 0.8 °C). On synthetic 8-hour overnight wear, sensor noise of 0.15 °C (standard deviation) split the nights into short pieces, while 0.04 °C left them whole. Possible fixes are in SOP Appendix C; checking overnight wear is part of §1.2 item 5.

## 5.2 Proximity as a gate

The proximity sensor is used only to confirm that the splint is covered, not to detect wear on its own. Temperature alone cannot tell wear from a warm environment, such as a splint left on a radiator or in the sun; requiring the sensor to be covered rules those out.

## 5.3 Drift-invariant "covered"

Over a 35-day recording, the proximity reading while worn crept from 0 into the 50s as the battery discharged. The original test (proximity equal to 0) therefore stopped working after about 11 days, and wear was missed from then on.

The app now tracks the proximity "floor" as the rolling 10th percentile over about a day, subtracts it, and treats the sensor as covered when what remains is within the noise (`max(5, 4 × MAD)`, where MAD is the median absolute deviation).

## 5.4 Thresholds are empirical

All thresholds were set by inspecting a small number of recordings. Finer tuning may be needed once more data are available; SOP Appendix C describes how.

## 5.5 Daily summary

The app's "Average Wear Time Per Day" is the mean over days with at least one detected wear event. A day with no detected wear (e.g. the splint was not worn at all) is therefore not counted, and the partial first and last days count as days. If this is not the definition the study needs, divide Total Wear Time by the number of days in the recording (SOP §8).

# 6. Time handling

The logger knows only UTC time, stored as epoch seconds. The app asks for and shows **Eastern time** (America/New_York, daylight-saving aware) everywhere, because the study runs in Ontario, and writes every timestamp with its UTC offset (e.g. `-04:00`). The offset keeps the repeated hour at the November clock change unambiguous, and durations across the change come out right. To change the time zone, edit `timezone_config.py`.

If a logger loses its start time, the elapsed times survive. The app detects such files and rebuilds the timestamps from a start time the user enters, either during download or on the Data Analysis page.

# 7. Desktop application

The app is a small web application (Dash and Flask-SocketIO, with Plotly charts) that runs a local server on `127.0.0.1:8050` and opens in the browser. While the page is open it sends a heartbeat every 5 seconds; if none arrives for 5 minutes, the server warns the page and exits, so closing the tab does not leave a hidden server holding the logger's connection. All its assets are packaged with it, so it also works offline.

GitHub Actions builds stand-alone Windows and macOS programs, with Python included, each time a version tag (`v*`) is pushed, so staff need no Python (SOP Appendix B). Participant IDs are limited to letters, digits, `-` and `_`, up to 15 characters, because they go into the CSV header and often into file names, where commas or spaces would cause trouble.

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
