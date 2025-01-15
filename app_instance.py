# Contain Dash app and Flask Server
import os
from dash import Dash
import dash_bootstrap_components as dbc
from flask_socketio import SocketIO

# Use external style sheets
external_stylesheets = [
    "https://fonts.googleapis.com/css?family=Roboto:300,400,500,700&display=swap",
    dbc.themes.LITERA,
    dbc.icons.FONT_AWESOME,
    "assets/style.css"
]

# Initialize the app
app = Dash(__name__, external_stylesheets=external_stylesheets, assets_folder=os.getcwd()+'/assets/', suppress_callback_exceptions=True)
server = app.server
socketio = SocketIO(server, async_mode="gevent")