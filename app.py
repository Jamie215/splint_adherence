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
import psutil
import dash_bootstrap_components as dbc
import requests

from app_instance import app, socketio, server
from pages.data_analysis_page import data_analysis_layout
from pages.index_page import index_layout, register_index_callbacks
import arduino

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
    Shut down the server when the user exists from the browser based on heartbeat timer
    """
    logging.info("No heartbeat received; shutting down server.")
    try:
        func = request.environ.get('werkzeug.server.shutdown')
        func()
    except:
        logging.error("Werkzeug server shutdown function not available.")
        pid = os.getpid()
        process = psutil.Process(pid)
        for proc in process.children(recursive=True):
            proc.kill()
        process.kill()
        logging.error("Killed process.")
    # Exit the process as a fallback
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
    print("Session has timed out")
    return render_template_string("""
            <html>
                <head><title>Server Terminated</title></head>
                <body>
                    <<h1>Interface Terminated</h1>
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
    print("Cleaning up")
    if hasattr(arduino, "arduino_serial"):
        arduino.disconnect_arduino()
        print("Arduino serial connection closed")

atexit.register(clean_up)

def open_browser(port):
    """
    Open the web browser automatically when the application is launched
    """
    webbrowser.open_new(f"http://127.0.0.1:{port}/")

def shutdown(port):
    """
    Shutdown the Flask server when the application is closed
    """
    try:
        requests.post(f"http://127.0.0.1:{port}/shutdown")
    except requests.exceptions.RequestException:
        pass

if __name__ == "__main__":
    reset_heartbeat_timer()
    port = 8050
    Timer(1, open_browser, args=[port]).start()
    try:
        socketio.run(server, port=8050, allow_unsafe_werkzeug=True, debug=False)
    finally:
        shutdown(port)
