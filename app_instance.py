# Contain Dash app and Flask Server
import os
import sys

from dash import Dash
from flask_socketio import SocketIO

# Resolve the assets folder so the app works regardless of the current working
# directory. In a frozen (cx_Freeze) build, this module lives inside lib/ (or
# library.zip), so __file__ does NOT point next to the executable -- but
# setup.py's include_files places assets/ alongside the executable itself.
# Anchor on sys.executable when frozen, and on this file otherwise.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_FOLDER = os.path.join(BASE_DIR, "assets")

# Style sheets are vendored under assets/vendor/ (rather than loaded from
# CDNs) so the app renders fully styled on offline clinic machines. They are
# listed here explicitly so they always load BEFORE assets/style.css and our
# overrides win. Their `.vendor.css` suffix keeps Dash from also auto-loading
# them (after style.css) -- `assets_ignore` matches file names, not paths.
# See HANDOFF.md ("Vendored front-end assets") for how to update them.
external_stylesheets = [
    "/assets/vendor/roboto/roboto.vendor.css",
    "/assets/vendor/bootswatch-litera/bootstrap.min.vendor.css",
    "/assets/vendor/fontawesome/css/all.min.vendor.css",
]

# Initialize the app
app = Dash(
    __name__,
    external_stylesheets=external_stylesheets,
    assets_folder=ASSETS_FOLDER,
    assets_ignore=r"\.vendor\.css$",
    suppress_callback_exceptions=True,
)
server = app.server
socketio = SocketIO(server, async_mode="gevent")
