---
title: "Splint Adherence Logger: How to Build & Use"
subtitle: "Standard operating procedure (SOP) for building, setting up and deploying the logger, and for downloading and analysing its data"
---

*Drafted in October 2026, prepared by Jamie Kim.*

> **About the \[TODO\] markers.** Some details of the physical build (battery, power switch, enclosure, mounting in the splint) are not recorded in the repository. They are marked **\[TODO\]** and should be filled in by whoever holds the hardware before this SOP is used.

# 1. Purpose and scope

This SOP describes how to build the splint adherence logger, set up its software, deploy it with a participant, and download and analyse the recording. It covers the system as it currently exists: one Arduino-based logger embedded in a thermoplastic splint, configured and read over USB by a desktop application.

**How it works.** A small board in the splint wakes up every 5 minutes, measures temperature and how close something is to its proximity sensor, writes both to its own memory, and goes back to sleep. When the splint is worn, the skin warms the temperature sensor and covers the proximity sensor. After the deployment, the desktop application downloads the recording and estimates when, and for how long, the splint was worn.

Key terms used in this SOP:

- **Logger / device.** The Arduino board in the splint, with its temperature and proximity sensors.
- **App.** The desktop program *Splint Adherence* (Windows or macOS). It opens in your web browser but runs entirely on your computer; no internet connection is needed.
- **Firmware / flashing.** The program that runs on the logger, and loading it onto the board (§4.2).
- **Initialize.** Sending a start time and participant ID to the logger from the app. This **erases** any recording still on the logger (§6).
- **Logging mode / idle mode.** The logger is either recording (logging, invisible to the computer) or waiting for the app (idle). It switches between them each time it is powered on (§1.1).
- **Power-cycle.** Turning the logger off and on again. **\[TODO\]**: describe how this is done on the built device (e.g. unplug and reconnect the battery, a switch, or one press of the board's reset button).
- **Participant ID.** Up to 15 letters, digits, `-` or `_` (no spaces), e.g. `SA-014`. It is stored on the logger and in the downloaded file.
- **Wear event.** A period the app judges the splint was worn, from the temperature rise and the covered proximity sensor.

## 1.1 The logger's four states

The most important thing to understand before using the logger: **every time it is powered on, it decides what to do from what happened last time** (Figure 1).

![Figure 1. The logger's states and what triggers each change. The app can connect only in states 1 and 4; in state 2 the board is powered down. Every timestamp is counted from the power-on that starts data collection, so that must happen at the start time entered in the app.](images/device_lifecycle.png){width=100%}

| State | Lights | Can the app see it? | How it gets there |
|--------|--------|--------|-----------|
| 1. Idle; not initialized | Green on | Yes | Freshly flashed board |
| 2. Idle; initialized | Off (powered down) | No | Initialize in the app (from state 1 or 4) |
| 3. Data collection | Off (briefly on at power-on) | No | Powered on after Initialize |
| 4. Idle; collection complete | Green on | Yes | Power-cycle, or any reset, during collection |

What this means in practice:

- A logger that is **collecting data cannot be found by the app.** Power-cycle it once to reach state 4, then connect.
- **Any** reset or power interruption during a deployment (a loose battery, a knock on the reset button) ends the recording. The logger goes to idle and does not resume logging.
- Initializing (state 4 → 2) **erases the previous recording.** Always download first.

> **Safety and use limits.** This is a research prototype worn against the skin. **\[TODO\]**: battery type and its safety precautions, the enclosure's protection against moisture and sweat, and skin-contact checks and how often to inspect the skin. Ethics approval has not yet been obtained; it is required before deployment with participants (Project Handover, §1.2).

# 2. Materials

| Qty | Item | Notes |
|-----|--------|--------------------|
| 1 per splint | Arduino Nano 33 BLE **Sense** | Must be the *Sense* version: its built-in HS300x temperature sensor and APDS9960 proximity sensor are used. Rev1 or Rev2: **\[TODO\]** confirm which revision was used. |
| 1 | USB data cable (micro-USB) | Must be a data cable. Some USB cables only charge, and the computer will not see the board. |
| 1 per splint | Battery / power source | **\[TODO\]**: type, capacity, connector, charging. |
| 1 per splint | Power switch or connector | **\[TODO\]**: how the device is turned off and on (power-cycle). |
| 1 per splint | Enclosure | **\[TODO\]**: design file or source, and how the sensors are exposed to the skin. |
| 1 | Thermoplastic splint | **\[TODO\]**: splint type and how the logger is attached. |
| 1 | Computer | Windows or macOS for the ready-made app (§4.3). Any OS with Python 3.11+ for the Python version (Appendix A). Needed only to initialize and to download, not during the deployment. |

# 3. Building the device

**\[TODO\]**: this section needs the build details. Suggested content, mirroring what is known:

## 3.1 Power

- **\[TODO\]**: how the battery is wired to the board (VIN or 3.3 V pin, or the USB connector), and any protection.
- The firmware already powers down most of the board between readings. A resting current below about 750 µA was measured on the bench with this power-down approach.
- Battery life over a full deployment has **not** been measured (see the Project Handover, §1.2).

## 3.2 Enclosure and mounting in the splint

- **\[TODO\]**: enclosure design, how it is fixed to the splint, and the orientation of the board.
- The **proximity sensor** must face the skin, so it reads "covered" when the splint is worn.
- The **temperature sensor** must be thermally close to the skin side, so that wearing the splint raises the reading clearly (the analysis looks for a rise of about 3 °C or more above room temperature).
- Leave the USB port reachable, or note how the board is removed for download.
- Label each logger (e.g. a device number) so recordings can be matched to devices.

# 4. Software setup (once per computer)

## 4.1 Firmware tools

The Arduino IDE is a free program used to load the firmware onto the logger. It is only needed to flash new or updated boards.

1. Install the Arduino IDE (version 2.x) from arduino.cc.
2. Open **Tools → Board → Boards Manager**, search for **Arduino Mbed OS Nano Boards** and click **Install**. On Windows, accept the driver installation if asked.
3. Open **Tools → Manage Libraries**, then search for and install **Arduino_APDS9960** and **Arduino_HS300x**.
4. Write down the versions of the board package and both libraries you installed. Keep them in the deployment log so every logger can be traced to the exact build.

## 4.2 Flashing the logger

> **Download any recording before re-flashing.** Firmware from before PR #10 stored its settings in an older format. After flashing the current firmware over it, the logger has no valid settings and downloads report the start time as `UNKNOWN`. The readings themselves survive, and the start time can be rebuilt later (§8.2), but it is simpler to download first and initialize again afterwards.

1. Download the project files from the repository (https://github.com/Jamie215/splint_adherence): green **Code** button → **Download ZIP**, then unzip.
2. Connect the logger to the computer by USB. In the Arduino IDE, open `collect_temperature/collect_temperature.ino`.
3. Select the board **Arduino Nano 33 BLE** and its port (**Tools → Port**), then click **Upload** (→ arrow). Wait for **Done uploading**.
4. After flashing, the board restarts in state 1 (idle; not initialized): the green light is on.
5. Optional check: open **Tools → Serial Monitor** (9600 baud). The board prints **Ready for Connection** when it restarts. Type `?` and press Enter: it replies `Hello World!`. **Close the Serial Monitor** afterwards, because only one program can use the connection at a time.

If the upload fails or no port is listed: check the cable is a data cable and try another USB port. If it still fails, press the board's reset button **twice quickly** (the orange light pulses slowly, meaning it is ready to be flashed), then click Upload again.

## 4.3 Installing the app

1. Open the project's **Releases** page (https://github.com/Jamie215/splint_adherence/releases) and, under **Assets** of the latest release, download:
   - Windows: `Splint_Adherence-windows.zip`
   - macOS: `Splint_Adherence-macos.zip`
2. Unzip it to a folder you can write to, e.g. `Documents\Splint_Adherence` (not Program Files).
3. Start it:
   - **Windows:** open the `Splint_Adherence` folder and double-click `app.exe`. The first time, Windows may show "Windows protected your PC", because the program is not signed by a publisher. Click **More info**, then **Run anyway**.
   - **macOS:** right-click `Splint_Adherence.app` → **Open**, then confirm. (A plain double-click is blocked the first time because the app is not signed.)
4. After a few seconds the app opens in your web browser at `http://127.0.0.1:8050` (Figure 2).

![Figure 2. The app's home page.](images/app_home.png){width=80%}

**Keep the browser tab open while you use the app.** The app runs only while its tab is open. About 5 minutes after the tab is closed it shuts itself down; start it again to continue.

To update the app later, download the newer release and replace the old folder.

# 5. Pre-deployment checklist

- [ ] The logger is flashed with the current firmware (§4.2), and the firmware and library versions are recorded.
- [ ] **Any previous recording on this logger has been downloaded and checked** (§8). Initializing will erase it.
- [ ] The battery is charged or new. **\[TODO\]**: acceptance check (e.g. voltage).
- [ ] The logger is in idle mode (green light on). If not, power-cycle it once.
- [ ] A USB **data** cable is at hand, and the Arduino Serial Monitor (or anything else using the logger's port) is closed.
- [ ] The participant ID and the planned start date and time are decided.
- [ ] The deployment is planned to last **no longer than about one month** (§7.2).

# 6. Initializing a logger

Initializing tells the logger its participant ID and when its recording starts, erases the previous recording, and powers it down, ready for the deployment.

1. Connect the logger (in idle mode) by USB.
2. In the app, click **Initialize Device**, then **Connect**. If you see "No device found" (Figure 3), see §11.
3. Fill in the form (Figure 4):
   - **Date**, **Hour (ET)** and **Minute**: when the logger will be powered on to start logging, in **Eastern time** on a **24-hour clock**, whatever time zone the computer is set to. It defaults to now, and can be up to 60 days ahead.
   - **Participant ID**: up to 15 letters, digits, `-` or `_`, e.g. `SA-014`. An invalid ID is flagged in red and Initialize does nothing until it is fixed.
4. Click **Initialize**. The confirmation shows the start time (Figure 5). The logger has now powered down (all lights off) and its USB connection drops; **this is expected.**
5. Disconnect the logger. To prepare another one, connect it and click **Initialize Another**.
6. Record the device label, participant ID and start time in the deployment log.

![Figure 3. "No device found": the logger is not connected, not powered, or still in logging mode.](images/app_no_device.png){width=55%}

![Figure 4. Initialize form: start time (Eastern, 24-hour) and participant ID.](images/app_initialize_form.png){width=55%}

![Figure 5. Initialize succeeded: the logger has powered down and starts logging the next time it is powered on.](images/app_initialize_done.png){width=55%}

> **The start time must match the moment the logger is powered on.** The logger does not have a real clock. It stores the start time you entered and counts the seconds from the moment it is next powered on. If it is powered on at 14:20 but the start time entered was 14:00, every timestamp in the recording will be 20 minutes early. Power it on at the entered time, as closely as you can (§7.1).

# 7. Deployment

## 7.1 Starting the recording

1. At the start time entered in §6, power the logger on. **\[TODO\]**: exact action (battery connection, switch, etc.).
2. The lights come on briefly, then go off when the first reading is taken; after that the logger stays dark. **\[TODO\]**: confirm on the built device. (A logger left with its green light on is in idle mode, not logging: re-check §6.)
3. Do **not** power-cycle or reset the logger again until the deployment ends. Doing so stops the recording (§1.1).
4. Fit the splint. **\[TODO\]**: fitting instructions and participant instructions (wear schedule, removing for washing, keeping it dry, what to do if the device is knocked or the battery comes loose).

## 7.2 How long a deployment can last

Plan deployments for **about one month at most**. The longest full recording tested lasted about 36 days.

- At about **49.7 days** the logger's internal timer rolls over, and its sampling is expected to misbehave (a burst of readings, then possibly a long gap). This is predicted from the code and has not been bench-tested.
- Storage is full after about **52 days** (15 000 readings at one every 5 minutes).
- **Battery life over a full deployment has not been measured.** **\[TODO\]**: add the expected battery life once measured.

Do not run past about 49 days, and check the end of any recording longer than 36 days carefully.

# 8. Downloading data

## 8.1 Download

1. At the end of the deployment, **power-cycle the logger once** to bring it to state 4 (green light on, Figure 1). Note the real time of the power-cycle in the deployment log.
2. Connect it by USB. In the app, click **Data Download**, then **Connect**.
   - "This device has not been initialized, so it has no data to download": the logger holds no recording.
   - "No device found": see §11.
3. Enter a **File name** (Figure 6). The placeholder shows the naming convention `Subject(UID)_(Quarter).(DeviceIteration)`, e.g. `SA014_Q3.1`. Do not add `.csv`; the app adds it.
4. Click **Download Data**. A full month takes about a minute; keep the window open until **Download complete** appears (Figure 7).
5. The file is saved through the browser, normally to your **Downloads** folder. Move it to the study's data storage.
6. Open it on the Data Analysis page (§9) to check that it looks complete before the logger is initialized again.
7. Check the last timestamp in the file against the power-cycle time you noted: it should be no more than about 5 minutes earlier. A larger gap means the logger was powered on late (or early) at the start, or its clock drifted; note it in the log.

![Figure 6. Download: enter a file name and click Download Data.](images/app_download_form.png){width=55%}

![Figure 7. Download complete. The CSV file is saved through the browser.](images/app_download_done.png){width=55%}

Closing the modal window releases the logger. Power-cycling the logger in idle mode keeps it idle; the recording stays on it until the next Initialize.

## 8.2 If the start time is missing

If the logger lost its settings (for example after re-flashing, §4.2), the readings and the time between them are intact but the start time is not. The app then shows **Start time missing** during download (or **Start Time Missing** on the Data Analysis page; the timestamps would otherwise show dates in 1970 or 2106).

1. Enter the start date and time (Eastern) that was used when the logger was initialized (from the deployment log).
2. During download, click **Save Corrected File**; the file is saved under the name you entered. On the Data Analysis page, click **Rebuild Timestamps**, then **Download Corrected CSV**; that copy is named `<original name>_recovered.csv`.
3. If the start time is not known yet, click **Save Without Correcting**; it can be rebuilt later on the Data Analysis page.

# 9. Analysing data

1. Click **Data Analysis** (home page or top bar), then drag the CSV file onto the box, or click **select a file**.
2. The page shows (Figures 8–11):
   - **File Information**: the start time, sampling interval, participant ID and time zone from the file.
   - **Detected Wear Events**: the temperature (black), its rolling minimum baseline (blue), the temperature rise above that baseline (green), and the proximity value (red); detected wear periods are shaded. The table lists each event's start, end, duration and peak temperature.
   - **Daily Wear Summary**: average non-peak and peak temperature, total wear time, average wear time per day, and a bar chart of wear minutes per day.
   - **Wear Periods by Hour of Day**: one column per day showing when the splint was worn.
3. Use the buttons above each chart to zoom, pan, reset the view, or save a picture (camera icon).

All times are Eastern time, with daylight-saving changes handled. The screenshots below use **simulated** data, so real recordings will look less regular.

![Figure 8. Upload and file information (simulated data).](images/app_analysis_upload.png){width=100%}

![Figure 9. Detected wear events: traces with shaded wear periods, and the events table (simulated data).](images/app_analysis_events.png){width=100%}

![Figure 10. Daily wear summary (simulated data).](images/app_analysis_daily.png){width=100%}

![Figure 11. Wear periods by hour of day (simulated data).](images/app_analysis_hourly.png){width=100%}

> **Treat the detected wear times as estimates.** The detection thresholds were tuned on a small amount of data and have not been checked against a record of when the splint was really worn. Long continuous wear (e.g. overnight) may be split or cut short (Project Handover, §5.1). Look at the traces, not only the totals. Appendix C describes how to re-tune the detection.

The page also opens older files: files without a proximity column (treated as covered throughout) and files downloaded before app v1.2.0 (timestamps converted from UTC to Eastern automatically).

# 10. Data handling

Each download is one CSV file, which opens in Excel:

```
Initial Timestamp,2026-01-01 08:00:00-05:00
Wake-up Interval (Seconds),300
Personal ID,SA-014
Timezone,America/New_York
Timestamp,Temperature,ProximityVal
2026-01-01 08:00:00-05:00,30.50,0
2026-01-01 08:05:00-05:00,31.00,5
...
```

| Column | Meaning |
|------|--------------------|
| `Timestamp` | Eastern time with its UTC offset (`-05:00` standard time, `-04:00` daylight time) |
| `Temperature` | °C, from the HS300x sensor |
| `ProximityVal` | 0–255 from the APDS9960 sensor; **low = covered** (worn). Its baseline creeps upward over a long deployment; the analysis allows for this. |

- Keep a **deployment log**: device label, participant ID, firmware/library versions, start time entered, actual power-on time, actual power-cycle (end) time, file name, and notes (device knocked, battery changed, splint removed for long periods, skin issues).
- Keep the original download untouched; save any corrected copy (`_recovered.csv`) alongside it.
- Use a study code, not a name, as the participant ID: it is stored on the logger, in the file and often in the file name.
- **\[TODO\]**: where study data are stored and who can access them (participant data). No policy exists yet; see Project Handover §1.2 item 4.

# 11. Troubleshooting

| Symptom | Likely cause | Action |
|----------|----------|-------------|
| "No device found" | Logger is in **logging mode** (most common), not powered, or not connected | Power-cycle the logger once, check the green light is on, reconnect, click **Try Again** |
| "No device found" with the green light on | Charge-only cable, loose cable, or another program (Arduino Serial Monitor) is using the port | Use a data cable, try another USB port, close the Serial Monitor |
| "This device has not been initialized…" on download | The logger has no recording | Nothing to download; check you have the right logger |
| Initialize shows an error | Connection dropped before the settings were sent, or the logger rejected them (corrupted message) | Click **Try Again**; if it repeats, power-cycle the logger and retry |
| Initialize does nothing | Participant ID is empty or has spaces or other characters | Use letters, digits, `-` or `_` only (max 15) |
| Start time `UNKNOWN`, or dates in 1970 / 2106 | The logger lost its settings (usually re-flashed over old firmware) | Rebuild the timestamps from the deployment log (§8.2) |
| Recording shorter than expected | The logger was reset or lost power during the deployment (it then stops logging) | Check the battery and connections; note it in the log |
| All timestamps shifted by a fixed amount | The logger was powered on at a different time than the start time entered | Correct using the actual power-on time from the deployment log **\[TODO\]**: no tool for this yet; see Project Handover §4.4 |
| Burst of readings or a long gap near day 49–50 | Timer rollover (§7.2) | Use data before day ~49 only |
| Little or no wear detected although the splint was worn | Sensors not against the skin, or a weak temperature rise | Check mounting (§3.2); look at the raw traces |
| Browser shows "Interface Terminated" | The app shut down after its tab was closed or idle | Close the tab and start the app again |
| Page looks unstyled, or icons are missing | Old app version | Download the latest release (§4.3) |
| "Windows protected your PC" / macOS "cannot be opened" | The app is not signed | Windows: More info → Run anyway. macOS: right-click → Open. If IT policy blocks it, ask IT to allow it |
| Arduino IDE upload fails / no port | Charge-only cable, faulty port, or the board is busy | Data cable, another port; double-press reset and upload again (§4.2) |

# 12. After the deployment

1. Download the recording (§8) and check it on the Data Analysis page (§9).
2. Store the CSV with the deployment log (§10).
3. Clean the splint and logger. **\[TODO\]**: cleaning method that is safe for the electronics.
4. Recharge or replace the battery. **\[TODO\]**
5. Note any problems (lights, error messages, short recordings) in the deployment log.

# Appendix A. Running the app from Python (optional)

You only need this to change the app, to run the tests, or to use a system without a ready-made build.

1. Install Python **3.11** or newer from python.org. On Windows, tick **Add Python to PATH**.
2. Open a terminal in the project folder (the one containing `app.py`).
3. Run, one line at a time:

   Windows (Command Prompt):

   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```

   macOS / Linux:

   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python app.py
   ```

4. The app opens in the browser as in §4.3.

**Next time**, open a terminal in the project folder, run the activate line again, then `python app.py`.

**Tests** (no logger needed): `pip install -r requirements-dev.txt`, then `pytest`. All tests should pass.

# Appendix B. Releasing a new app version (for developers)

The Windows and macOS builds are made automatically by GitHub Actions when a version tag is pushed. This needs Git, a clone of the repository (not the ZIP), and write access to it.

1. Check the change locally: `pytest`, then `python app.py` and run through Initialize, Download and Data Analysis with a logger if possible.
2. Bump `version` in `setup.py` (small fix `1.3.1`, new feature `1.4.0`, a change to the CSV format `2.0.0`) and merge to `main`.
3. Tag and push (replace the version):

   ```
   git checkout main
   git pull
   git tag v1.3.1
   git push origin v1.3.1
   ```

4. In the repository's **Actions** tab, the **Build and Release** run builds both versions and attaches `Splint_Adherence-windows.zip` and `Splint_Adherence-macos.zip` to the new release. Edit the release notes to say what changed. If the run fails, fix the problem and use a new version number.
5. To test a build without releasing: **Actions → Build and Release → Run workflow**; the zips appear as downloads on the run's page.

Firmware changes (`collect_temperature.ino`) are not part of the app release: every logger must be re-flashed (§4.2), after downloading its data.

# Appendix C. Tuning the wear-detection parameters (for analysts and developers)

The rules that turn temperature and proximity into wear events were set by inspecting a small number of recordings (Project Handover, §5). Re-tune them once there are recordings with a known record of actual wear ("ground truth"). The parameters are constants in the code (`pages/analysis_helper.py`) with no setting in the app, so a change needs the Python version (Appendix A) and a new app release (Appendix B).

## C.1 Collect ground truth

- **Wear diary:** the participant (or staff, in a supervised session) records on/off times. Cheap, but coarse and subject to recall bias.
- **Supervised sessions:** scripted on/off periods in the lab, including long continuous wear and confounders (warm room, splint left on a warm surface, sensor covered but splint not worn).
- **Reference sensor:** a second, independent sensor on the skin side (e.g. a commercial temperature button logger) for a few deployments.

## C.2 What to check

- Agreement per event (start and end within one 5-minute reading) and per day (total wear minutes).
- **Long wear:** whether overnight wear is split or cut short. After about an hour of continuous wear the baseline catches up with skin temperature, and a single 0.4 °C dip can end the event. Possible fixes: a longer baseline window, freezing the baseline while an event is in progress, or requiring two consecutive cooling readings before ending an event.
- False wear in warm environments, and missed wear with a loose splint.

## C.3 Parameters

| Parameter | Where | Value | Raising it will… |
|------------|---------------|------|-------------------|
| `ONSET_DELTA` | `detect_onsets_offsets` | 3.0 °C | require more heat above room temperature to start an event (fewer false events; gentle onsets missed) |
| `ONSET_GRAD` | `detect_onsets_offsets` | 0.8 °C/reading | require a sharper jump to start an event |
| `OFFSET_GRAD` | `detect_onsets_offsets` | −0.4 °C/reading | (less negative) end events on gentler cooling |
| `OFFSET_DELTA` | `detect_onsets_offsets` | 1.5 °C | end events while still further above room temperature |
| `PEAK_DROP_FACTOR` | `detect_onsets_offsets` | 0.8 | end events after a smaller drop from the peak |
| Baseline window | `detect_onsets_offsets` | ~120 min | give a steadier room-temperature estimate, but slower to follow room changes |
| Trend lag | `detect_onsets_offsets` | ~15 min | smooth the "is it warming up" check more |
| Minimum length | `detect_onsets_offsets` | 2 readings | drop more short events |
| Floor window | `dedrift_proximity` | ~1 day | follow proximity drift more slowly |
| Floor quantile | `dedrift_proximity` | 0.10 | raise the proximity floor estimate |
| `k` | `dedrift_proximity` | 4.0 | allow more noise and still call the sensor covered |
| `min_excursion` | `dedrift_proximity` | 5.0 | raise the minimum threshold for "not covered" |

## C.4 Procedure

1. Change one parameter at a time in `pages/analysis_helper.py`.
2. Run `pytest`; all tests should still pass.
3. Start the app from Python (`python app.py`) and open each labelled recording on the Data Analysis page. Compare the detected events and daily totals with the ground truth.
4. When the results improve, add each labelled recording to `tests/` as a regression case, so later changes can't silently undo the improvement.
5. Record the new values in `HANDOFF.md` §4.
6. Release a new app version (Appendix B). Older downloads can simply be re-opened in the new version, since the raw readings are unchanged.
