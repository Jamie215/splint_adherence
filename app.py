"""
Import Libraries
"""
# Ensure that the standard Python libraries are compatible with gevent
from gevent import monkey
monkey.patch_all()

import atexit
import os
import logging
import json
from threading import Timer
import webbrowser

from dash import html, dcc, Input, Output
from flask import request, jsonify, render_template_string
import dash_bootstrap_components as dbc

from app_instance import app, socketio, server
from pages.data_analysis_page import data_analysis_layout
from pages.index_page import index_layout, register_index_callbacks
import arduino

# Configure application-wide logging. Without this, the logging.info(...) calls
# below (and in the other modules) would not emit anything.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Register all index page callbacks before app runs
register_index_callbacks()

# Default page layout
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    dbc.NavbarSimple(
        brand="SPLINT ADHERENCE GUI",
        brand_href="/",
        color="mediumaquamarine",
        sticky="top",
        dark=True,
        fluid=True,
        style={"cursor":"pointer"}
    ),
    dcc.Store(id="action-modal-open-state", data=json.dumps({"is_open": False})),
    html.Div(id="action-modal-status"),
    html.Div(id="page-content")
])

# Route to load the appropriate page layout
@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def display_page(pathname):
    if pathname == "/data-analysis":
        return data_analysis_layout
    else:
        return index_layout()

heartbeat_timeout = None

def reset_heartbeat_timer():
    """
    Reset the heartbeat timer
    """
    global heartbeat_timeout
    if heartbeat_timeout:
        heartbeat_timeout.cancel()
    # Set the heartbeat timer to 300 seconds (5 min)
    heartbeat_timeout = Timer(300, notify_server_timeout)
    heartbeat_timeout.start()

def notify_server_timeout():
    """
    Prepare to shut down as no heartbeat received
    """
    logging.info("No heartbeat received. Preparing to shut down server.")
    socketio.emit("server_shutdown_warning")
    # Give 20 seconds for the client to handle the warning
    Timer(20, shutdown_server).start()

def shutdown_server():
    """
    Shut down the server when the user exits from the browser based on the
    heartbeat timer.

    This runs from a background Timer thread with no request context, and the
    app is served by gevent/SocketIO rather than the Werkzeug dev server, so
    there is no in-process "graceful shutdown" hook to call. Exiting the
    process is the reliable option; atexit handlers (see clean_up) still run.
    """
    logging.info("No heartbeat received; shutting down server.")
    os._exit(0)

@server.route("/heartbeat", methods=["POST"])
def heartbeat():
    """
    Receive heartbeat to determine the interface is still active
    """
    logging.info("Received heartbeat")
    reset_heartbeat_timer()
    return "", 204

@server.route("/timeout")
def timeout():
    """
    Navigate to timeout page
    """
    logger.info("Session has timed out")
    return render_template_string("""
            <html>
                <head><title>Server Terminated</title></head>
                <body>
                    <h1>Interface Terminated</h1>
                    <p> The server has terminated due to inactivity. Please close this tab and relaunch the application.</p>
                </body>
            </html>
        """)

@server.route("/log", methods=["POST"])
def log():
    """
    For logging purposes
    """
    data = request.get_json()
    logging.info(f"Client log: {data['message']}")
    return jsonify(success=True)

def clean_up():
    """
    Clean up existing resources
    """
    logger.info("Cleaning up")
    arduino.client.disconnect()
    logger.info("Arduino serial connection closed")

atexit.register(clean_up)

def open_browser(port):
    """
    Open the web browser automatically when the application is launched
    """
    webbrowser.open_new(f"http://127.0.0.1:{port}/")

if __name__ == "__main__":
    reset_heartbeat_timer()
    port = 8050
    Timer(1, open_browser, args=[port]).start()
    # Resource cleanup on exit is handled by the atexit-registered clean_up().
    socketio.run(server, port=port, allow_unsafe_werkzeug=True, debug=False)
