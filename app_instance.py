# Contain Dash app and Flask Server
import os

from dash import Dash
import dash_bootstrap_components as dbc
from flask_socketio import SocketIO

# Resolve the assets folder relative to this file so the app works regardless
# of the current working directory (e.g. when launched as a frozen executable).
ASSETS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# External style sheets. Files under the local assets folder (e.g. style.css)
# are served and injected automatically by Dash, so they are not listed here.
external_stylesheets = [
    "https://fonts.googleapis.com/css?family=Roboto:300,400,500,700&display=swap",
    dbc.themes.LITERA,
    dbc.icons.FONT_AWESOME,
]

# Initialize the app
app = Dash(
    __name__,
    external_stylesheets=external_stylesheets,
    assets_folder=ASSETS_FOLDER,
    suppress_callback_exceptions=True,
)
server = app.server
socketio = SocketIO(server, async_mode="gevent")
