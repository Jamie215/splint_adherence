# CLAUDE.md

Desktop tool that estimates how long a patient wears a thermoplastic splint. An
Arduino Nano 33 BLE logger in the splint records temperature and proximity to
flash. A Dash/Flask GUI configures the device over USB serial, downloads the
data and infers wear periods from body heat. See README.md for the full picture.

## Layout

- `app.py`: entry point. Serves the GUI at http://127.0.0.1:8050 (Flask-SocketIO + gevent)
- `app_instance.py`: Dash app setup and stylesheet loading order
- `pages/`: UI pages; `pages/analysis_helper.py` holds the wear-detection algorithm
- `arduino.py`: PC side of the serial protocol (find device, initialize, download)
- `collect_temperature/collect_temperature.ino`: logger firmware
- `timezone_config.py`: the one place the display time zone is set
- `assets/vendor/`: vendored CSS and fonts (Bootstrap theme, Font Awesome, Roboto)
- `tests/`: pytest; the Arduino is replaced by a fake serial port, no hardware needed
- `setup.py`: cx_Freeze config for the Windows/macOS bundles

## Commands

Use **Python 3.11** (same as CI). The pinned `gevent` does not build on 3.13.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest          # all tests must pass before a change is done
python app.py   # run the GUI
```

`cx_Freeze` in requirements.txt is only for building bundles. If it fails to
install, skip it (CI does: `grep -v '^cx_Freeze' requirements.txt`).

## Rules

- **Serial protocol:** single-character commands `?` (ping), `!` (has data?),
  `i` (initialize), `r` (read). These are handled in `processSerialCommand()` in
  the `.ino` and sent from `arduino.py`. If you change one side, change the other
  and update `tests/test_arduino.py`.
- **Algorithm:** if you change detection logic or parameters in
  `pages/analysis_helper.py`, update `tests/test_analysis_helper.py` in the same change.
- **Time:** the device stores UTC epoch seconds only. Conversion to display time
  happens through `timezone_config.py` (`DISPLAY_TZ`). Don't hard-code zones or
  use naive local times elsewhere.
- **Offline:** clinic machines may have no internet. Keep front-end assets
  vendored under `assets/vendor/`. Never add CDN links. Vendored stylesheets end
  in `.vendor.css` and are listed explicitly in `app_instance.py` so they load before
  `assets/style.css`.
- **requirements.txt** is curated by hand, saved as UTF-8. Never `pip freeze` into it.
  `pytz` and `tzdata` must stay in `setup.py` `packages`.
- **Docs** are Markdown only. Don't add `.docx` or other generated copies.
- **Releases:** bump `version` in `setup.py`, then push a `v*` tag.
  `.github/workflows/build-release.yml` builds and attaches the bundles. Don't tag
  or push tags unless asked.
