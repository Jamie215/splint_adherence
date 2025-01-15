"""
Import Libraries
"""
import datetime
import json
import os
import base64
import io

import pytz
from dash import dcc, html, Input, Output, State, callback_context
import dash
import dash_bootstrap_components as dbc
import pandas as pd

from app_instance import app
import arduino

def set_modal_content(initialize=False, selected_dt=None, download=False, merge=False, error=None, footer_view="None"):
    """
    Set content for modal body and footer

    initialize: set the modal body to be the initialization view of initialization flow
    selected_dt: set the modal body to be the confirmation view of initialization flow
    download: set the modal body view to be the download flow
    merge: set the modal body view to be the data merge flow
    error: set the modal body view to be initialization fail view with the error
    footer_view: set the modal footer view (Type: None, Modal Start, Initialize)
    """
    # Generate modal body content
    status_msg = []
    if initialize:
        status_msg = [
            html.Div("Please set the date and time for device initialization.", className="mb-2"),
        ]
    elif selected_dt:
        status_msg = [
            html.I(className="fas fa-check-circle initiate-success"),
            dbc.Row(
                html.Div([
                    "The device has been initialized for ",
                    html.Span(selected_dt, style={"color": "RoyalBlue", "font-weight":"bold"}),
                    " and powered down. It will be counting steps in the next powerup.",
                    html.Br(),
                    html.Br(),
                    " You may now disconnect the device.",
                    " If you want to continue initializing the device,",
                    " check the connection of the device and",
                    " restart the initializing process."
                ])
            ),
            html.Div([
                    dbc.Button("Re-Initialize", id="re-attempt-btn", className="initialize-btn")
                ],
                style={"text-align":"center"}
            )
        ]
    elif download:
        status_msg = [
            html.Div("Select from below to download the appropriate format.", className="mb-2"),
            dbc.Select(
                id="download-filetype",
                options=[
                    {"label": ".RAW", "value": "1"},
                    {"label": ".CSV", "value": "2"}
                ],
                value=2,
                className="mb-4"
            ),
            html.Div("Enter your filename."),
            dbc.Input(id="download-filename", placeholder="Subject(UID)_(Quarter).(DeviceIteration)", value="Subject_", required=True, className="mb-2"),
            dcc.Loading(
                id="loading-download",
                type="circle",
                children=[
                    html.Div(id="download-file-status")
                ]
            )
        ]
    elif merge:
        status_msg= [
            html.H6("Merge 2 Datasets from the Same Participant"),
            html.Div(["Please ensure that the start datetime of the 2nd file is ",
                      html.B("after "),
                      "the end datetime of the first file."], className="mb-4"),
            dbc.Row([
                dbc.Col(html.H6("Base File: "), width=3),
                dbc.Col(html.Div(id="upload-base-file-status", className="mb-2"), width=9)
            ]),
            dcc.Upload(
                id="base-data",
                children=html.Div([
                    html.I(className="fas fa-upload"),
                    " Drag and Drop or ",
                    html.A("Select Base File")
                ]),
                multiple=False,
                className="upload-box mb-4"
            ),
            dbc.Row([
                dbc.Col(html.H6("2nd File: "), width=3),
                dbc.Col(html.Div(id="upload-append-file-status", className="mb-2"), width=9)
            ]),
            dcc.Upload(
                id="append-data",
                children=html.Div([
                    html.I(className="fas fa-upload"),
                    " Drag and Drop or ",
                    html.A("Select Second File")
                ]),
                multiple=False,
                className="upload-box mb-4"
            ),
            dbc.Button("Download Merged Data", id="download-data-merge-btn", className="merge-btn mb-2"),
            dcc.Loading(
                id="loading-download",
                type="circle",
                children=[
                    html.Div(id="download-merge-df-status"),
                    dcc.Download(id="download-merge-df-csv"),
                ]
            )
        ]
    elif error:
        status_msg = [
            html.I(className="fas fa-times-circle initiate-fail"),
            dbc.Row(
                html.Div([
                        html.Div("Arduino Connection Failed.", style={"text-align": "center", "color": "indianred"}),
                        html.Br(),
                        "Please ensure that the device is ",
                        html.B("powered "),
                        "and ",
                        html.B("properly connected!")
                ])
            ),
            dbc.Col([
                    dbc.Button("Try Again", id="re-attempt-btn", className="initialize-btn")
                ],
                style={"text-align":"center"},
                width=12
            )
        ]
    else:
        status_msg = [html.Div("Please connect Arduino to computer.", className="mb-2")]

    curr_date = datetime.datetime.now()
    initialize_view = [
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.Label(
                        "Date",
                        className="dropdown-label",
                        style={"display":"none"} if not initialize else {}
                    ),
                    dcc.DatePickerSingle(
                        id="date-picker",
                        min_date_allowed=curr_date.date(),
                        max_date_allowed=curr_date.date() + datetime.timedelta(days=60),
                        initial_visible_month=curr_date.date(),
                        date=curr_date.date(),
                        style={"display": "none"} if not initialize else {}
                    ),
                ]),
                width=6
            ),
            dbc.Col(
                html.Div([
                    html.Label(
                        "Hour (24)",
                        className="dropdown-label",
                        style={"display": "none"} if not initialize else {}
                    ),
                    dcc.Dropdown(
                        id="hour",
                        options=[{"label": f"{i:02d}", "value": i} for i in range(24)],
                        value=curr_date.hour,
                        style={"display": "none"} if not initialize else {"width": "100px", "display": "block"}
                    )
                ]),
                width=3
            ),
            dbc.Col(
                html.Div([
                    html.Label(
                        "Minute",
                        className="dropdown-label",
                        style={"display": "none"} if not initialize else {}
                    ),
                    dcc.Dropdown(
                        id="minute",
                        options=[{"label": f"{i:02d}", "value": i} for i in range(60)],
                        value=curr_date.minute,
                        style={"display": "none"} if not initialize else {"width": "100px", "display": "block"}
                    )
                ]),
                width=3
            )
        ])
    ]

    download_view = [
        html.Div(
            [
                dbc.Button(
                        [html.I(className="fas fa-file-download mr-2"), " Download Data"],
                        id="download-btn",
                        className="ms-2 download-btn",
                        disabled=False,
                        style={"display": "none"} if not download else {}
                )
            ],
            className="flex-container"
        ),
        dcc.Download(id="download-data")
    ]

    # Generate modal footer content
    if footer_view == "None":
        modal_footer = dbc.ModalFooter(
            [
                dbc.Button("Connect", id="connect-modal", style={"display":"none"}),
                dbc.Button("Initialize", id="initialize-btn", style={"display":"none"}),
                dbc.Button("Try Again", id="re-attempt-btn", style={"display":"none"})
            ],
            style={"height":"0px"}
        )

    elif footer_view == "Modal Start":
        modal_footer = dbc.ModalFooter(
            dbc.Row([
                dbc.Col(
                    html.I(className="fas fa-exclamation-circle disclaimer-msg"),
                    width=1,
                    align="top"
                ),
                dbc.Col(
                    html.Div("Exiting this pop-up will terminate the Arduino connection process!",
                             className="disclaimer-msg"
                    ),
                    width=8,
                    align="center"
                ),
                dbc.Col(
                    [
                        dbc.Button("Connect", id="connect-modal", color="success", className="ms-auto connect-btn"),
                        dbc.Button("Initialize", id="initialize-btn", style={"display":"none"}),
                        dbc.Button("Try Again", id="re-attempt-btn", style={"display":"none"})
                    ],
                    width=3,
                    align="center"
                )
            ])
        )
    elif footer_view == "Initialize":
        modal_footer = dbc.ModalFooter(
            dbc.Row([
                dbc.Col(
                    html.I(className="fas fa-exclamation-circle disclaimer-msg"),
                    width=1,
                    align="top"
                ),
                dbc.Col(
                    html.Div("Exiting this pop-up will terminate the Arduino connection process!",
                             className="disclaimer-msg"
                    ),
                    width=8,
                    align="center",
                ),
                dbc.Col(
                    [
                        dbc.Button("Connect", id="connect-modal", style={"display":"none"}),
                        dbc.Button("Initialize", id="initialize-btn", color="success", style={"padding":"10px", "color": "White"}),
                        dbc.Button("Try Again", id="re-attempt-btn", style={"display":"none"})
                    ],
                    width=3,
                    align="center"
                )
            ])
        )

    return  [
                dbc.ModalBody(status_msg + initialize_view + download_view, id="modal-body"),
                modal_footer
            ]

def index_layout():
    """
    Return index page layout, displaying the following features
    
        1. Initialize Device
        2. Data Download
        3. Data Analysis
        4. Data Merge
    """
    return html.Div(
        [
            dbc.Button(
                [
                    html.I(className="fas fa-microchip page-btn-icon"),
                    "Initialize Device",
                ],
                id="open-initialize-modal",
                outline=True,
                className="m-4 page-btn",
            ),
            dbc.Button(
                [
                    html.I(className="fas fa-download page-btn-icon"),
                    "Data Download"
                ],
                id="open-download-modal",
                outline=True,
                className="m-4 page-btn",
            ),
            dbc.Button(
                [
                    html.I(className="fas fa-chart-bar page-btn-icon"),
                    "Data Analysis"
                ],
                href="/data-analysis",
                outline=True,
                className="m-4 page-btn",
            ),
            dbc.Button(
                [
                    html.I(className="fas fa-code-fork page-btn-icon"),
                    "Data Merge"
                ],
                id="open-data-merge-modal",
                outline=True,
                className="m-4 page-btn"
            ),
            dbc.Modal(
                [dbc.ModalHeader("Action")] + set_modal_content(),
                id="action-modal",
                centered=True,
                is_open=False
            )
        ],
        style={"height": "80vh"},
        className="flex-container"
    )

def register_index_callbacks():
    @app.callback(
            [Output("action-modal", "is_open"),
            Output("action-modal", "children"),
            Output("action-modal-open-state", "data")],
            [Input("open-initialize-modal", "n_clicks"),
            Input("open-download-modal", "n_clicks"),
            Input("open-data-merge-modal", "n_clicks"),
            Input("re-attempt-btn", "n_clicks"),
            Input("connect-modal", "n_clicks"),
            Input("initialize-btn", "n_clicks")],
            [State("action-modal", "is_open"),
            State("action-modal", "children"),
            State("action-modal-open-state", "data"),
            State("date-picker", "date"),
            State("hour", "value"),
            State("minute", "value")],
            prevent_initial_call=True)
    def toggle_action_modal(init_click, dl_click, merge_click, re_attempt_click, connect_click, init_btn_click, is_open, curr_children, json_data, date, hour, minute):
        """
        Set the appropriate callback based on the user action related to the modal

        init_click: "Initialize Device" button click instance (index page)
        dl_click: "Data Download" button click instance (index page)
        merge_click: "Data Merge" button click instance (index page)
        re_attempt_click: "Try Again" button click instance
        connect_click: "Connect" button click instance
        init_btn_click: "Initialize" button click instance
        is_open: modal open state
        curr_children: modal content
        json_data: json wrapping "is_open", which later is outputted as "action-modal-open-state"
        date: value from datepicker when initializing
        hour: hour from dropdown when initializing
        minute: minute from dropdown when initializing
        """
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if any(x is not None for x in [init_click, dl_click, merge_click,
                                    re_attempt_click, connect_click, init_btn_click]):
            try:
                # Type 1: "Initialize" button triggered from the index page
                if triggered_id == "open-initialize-modal":
                    modal_content = [dbc.ModalHeader("Initialize Arduino", className="modal-header-text")]
                    modal_content.extend(set_modal_content(footer_view="Modal Start"))
                    return True, modal_content, json.dumps({"is_open": True})

                # Type 2: "Download" button triggered from the index page
                if triggered_id == "open-download-modal":
                    modal_content = [dbc.ModalHeader("Download Data", className="modal-header-text")]
                    modal_content.extend(set_modal_content(footer_view="Modal Start"))
                    return True, modal_content, json.dumps({"is_open": True})

                # Type 3: "Data Merge" button triggered from the index page
                if triggered_id == "open-data-merge-modal":
                    modal_content = [dbc.ModalHeader("Merge Data", className="modal-header-text")]
                    modal_content.extend(set_modal_content(merge=True))
                    return True, modal_content, json.dumps({"is_open": True})
                
                # Type 4: "Try Again" button triggered ("Error" from Arduino connection)
                if triggered_id == "re-attempt-btn":
                    updated_children = [curr_children[0]]
                    updated_children.extend(set_modal_content(footer_view="Modal Start"))
                    return True, updated_children, json.dumps({"is_open": True})

                # Type 5: "Connect" button triggered ("Initialize", "Download")
                if triggered_id == "connect-modal":
                    arduino_status = arduino.get_device_status()

                    if arduino.arduino_serial:
                        if "Initialize Arduino" in str(curr_children):
                            if arduino_status in [b"FIRST_POWERON", b"DATA_FILE_EXISTS"]:
                                updated_children = [curr_children[0]]
                                updated_children.extend(set_modal_content(initialize=True, footer_view="Initialize"))
                                return True, updated_children, json.dumps({"is_open": True})
                        elif "Download Data" in str(curr_children):
                            if arduino_status == b"FIRST_POWERON":
                                updated_children = [
                                    curr_children[0],
                                    dbc.ModalBody("First time initiating the device! No data available"),
                                    curr_children[2]
                                ]
                                return True, updated_children, json.dumps({"is_open": True})
                            if arduino_status == b"DATA_FILE_EXISTS":
                                updated_children = [curr_children[0]]
                                updated_children.extend(set_modal_content(download=True))
                                return True, updated_children, json.dumps({"is_open": True})

                # Type 6: "Initialize" button triggered
                if triggered_id == "initialize-btn":
                    # Convert selected date and time to epoch time
                    selected_datetime = datetime.datetime.strptime(date, "%Y-%m-%d")
                    selected_datetime = selected_datetime.replace(hour=int(hour), minute=int(minute))

                    timezone = pytz.timezone("UTC")

                    selected_datetime = timezone.localize(selected_datetime)
                    epoch_time = int(selected_datetime.astimezone(pytz.utc).timestamp())

                    # Send initialization command to Arduino
                    arduino.initialize_arduino(epoch_time)

                    formatted_dt = selected_datetime.strftime("%A, %B %d at %I:%M %p")
                    updated_children = [curr_children[0]]
                    updated_children.extend(set_modal_content(selected_dt=formatted_dt))
                    return True, updated_children, json.dumps({"is_open": True})

            except Exception as e:
                print(f"Following exception triggered: {e}")
                updated_children = [curr_children[0]]
                updated_children.extend(set_modal_content(error=str(e)))
                return True, updated_children, json.dumps({"is_open": True})

        return is_open, dash.no_update, json_data

    @app.callback(
        Output("download-btn", "disabled", allow_duplicate=True),
        [Input("download-btn", "n_clicks")],
        prevent_initial_call=True
    )
    def disable_button(download_click):
        """
        Callback to disable the download-btn when clicked

        download_click: "Download" button click instance
        """
        if download_click:
            return True  # Disable button immediately when clicked
        return False

    @app.callback(
            [Output("download-data", "data"),
            Output("download-filename", "style"),
            Output("download-file-status", "children"),
            Output("download-btn", "disabled", allow_duplicate=True)],
            [Input("download-filetype", "value"),
            Input("download-filename", "value"),
            Input("download-btn", "n_clicks")],
            [State("action-modal-open-state", "data")],
            prevent_initial_call=True)
    def download_data(filetype, filename, download_click, modal_open_state):
        """
        Download the Arduino data in a specified format

        filetype: input filetype (e.g., csv, raw)
        filename: input filename (e.g., Subject1234_1.1.csv)
        download_click: "Download" button click instance
        modal_open_state: State on whether or not the modal is open
        """
        # Check if modal is open before proceeding
        if not json.loads(modal_open_state).get("is_open"):
            raise dash.exceptions.PreventUpdate

        ctx = callback_context

        USER_FILES_DIR = os.getcwd()
        DOWNLOAD_DIR = os.path.join(USER_FILES_DIR, "Downloaded Data")
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # Check if the download button was clicked.
        if ctx.triggered and ctx.triggered[0]['prop_id'].endswith('.n_clicks'):
            if not filename or filename.strip() == "":
                file_status = html.Div("Please enter a filename.", style={"color": "indianred"})
                return (None, {"bordercolor": "red", "boxShadow": "0 0 0 0.25rem rgb(255 0 0 / 25%)"}, file_status, False)

            if filetype == 1:
                filename = f"{filename}.raw"
                get_readable = False
            elif filetype == 2:
                filename = f"{filename}.csv"
                get_readable = True

            file_path = os.path.join(DOWNLOAD_DIR, filename)
            file_content = arduino.download_file(file_path, get_readable)

            # Update the file download status
            file_status = html.Div("Download Complete", style={"color": "mediumseagreen"})
            return (file_content, {}, file_status, False)

        return (None, {}, None, False)

    @app.callback(
            Output("upload-base-file-status", "children"),
            Input("base-data", "contents"),
            State("base-data", "filename"),
            prevent_initial_call=True
    )
    def update_base_file_status(base_data, base_filename):
        """
        Update the display when the base file is uploaded for merging feature

        base_data: uploaded file
        base_filename: uploaded filename
        """
        # Ensure that the file is uploaded
        if base_data is None: return None

        return html.Div(f"{base_filename}", style={"color": "steelblue", "font-weight": "bold", "margin-left": "15px"})

    @app.callback(
            Output("upload-append-file-status", "children"),
            Input("append-data", "contents"),
            State("append-data", "filename"),
            prevent_initial_call=True
    )
    def update_append_file_status(append_data, append_filename):
        """
        Update the display when the file is uploaded for merging feature

        append_data: uploaded file
        append_filename: uploaded filename
        """
        # Ensure that the file is uploaded
        if append_data is None: return None

        return html.Div(f"{append_filename}", style={"color": "steelblue", "font-weight": "bold", "margin-left": "15px"})

    @app.callback(
            Output("download-data-merge-btn", "disabled"),
            [Input("base-data", "contents"),
            Input("append-data", "contents")]
    )
    def toggle_merge_button(base_data, append_data):
        """
        Enable merge button only when both base & append data are uploaded

        base_data: base data
        append_data: appending data
        """
        if base_data is None or append_data is None: return True

        return False

    @app.callback(
        Output("download-data-merge-btn", "disabled", allow_duplicate=True),
        [Input("download-data-merge-btn", "n_clicks")],
        prevent_initial_call=True
    )
    def disable_merge_download_button(download_click):
        """
        Callback to disable the download-data-merge-btn when clicked

        download_click: "Download" button click instance
        """
        if download_click:
            return True  # Disable button immediately when clicked
        return False

    @app.callback(
            Output("download-merge-df-csv", "data"),
            Output("download-merge-df-status", "children"),
            [Input("base-data", "contents"),
            Input("append-data", "contents"),
            Input("download-data-merge-btn", "n_clicks")],
            [State("base-data", "filename")],
            prevent_initial_call=True
    )
    def merge_data(base_data, append_data, merge_btn, base_filename):
        """
        Merge the two csv files with the same format.
        Assumes that the end datetime of the base file is before the start datetime of the second file

        base_data: base file that will be merged
        append_data: additional file that will be appended to the base file
        merge_btn: name of the merged file
        base_filename: name of the base file
        """
        # Ensure that both files are read
        if base_data is None or append_data is None: return None, None

        def read_csv(data):
            _, content_string = data.split(",")
            decoded = base64.b64decode(content_string)
            df = pd.read_csv(io.StringIO(decoded.decode("utf-8")))
            if df.columns[0] == "timestamp" and df.columns[1] == "steps":
                pass  # CSV has header row
            else:
                df = pd.read_csv(io.StringIO(decoded.decode("utf-8")), names=["timestamp", "steps"], skiprows=1)
            # Convert datetime column into datetime type
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df

        if merge_btn and base_data and append_data:
            try:
                base_df = read_csv(base_data)
                append_df = read_csv(append_data)

                # Merge the two dataset
                merge_df = pd.concat([base_df, append_df], ignore_index=True)
                merge_df["timestamp"] = pd.to_datetime(merge_df["timestamp"])
                
                start_dt = merge_df["timestamp"].min().strftime("%Y-%m-%d")
                end_dt = merge_df["timestamp"].max().strftime("%Y-%m-%d")

                # Prepare dataset download
                USER_FILES_DIR = os.getcwd()
                DOWNLOAD_DIR = os.path.join(USER_FILES_DIR, "Downloaded Data")
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                base_uid = base_filename.split("_")[0]

                file_name = f"{base_uid}_merged_{start_dt}_{end_dt}.csv"
                file_path = os.path.join(DOWNLOAD_DIR, file_name)

            # Add error message when failure to download.
            except Exception as e:
                print(f"Following exception triggered: {e}")

            else:
                file_status = html.Div("Download Complete", style={"color": "mediumseagreen", "margin-left": "150px"})
                return (merge_df.to_csv(file_path, index=False, header=False), file_status)

        return None, None

    @app.callback(
        Output("action-modal-open-state", "data", allow_duplicate=True),
        [Input("action-modal", "is_open")],
        prevent_initial_call=True
    )
    def update_modal_state(is_open):
        """
        Update the modal's state when the user closes the modal using the default closing button

        is_open: modal open state
        """
        return json.dumps({"is_open": is_open})

    @app.callback(
            Output("action-modal-status", "children"),
            Input("action-modal-open-state", "data"),
            prevent_initial_call=True
    )
    def manage_arduino_connection(json_data):
        """
        Terminate the Arduino connection if the modal is closed

        json_data: json wrapping "is_open"
        """
        data = json.loads(json_data)

        if data and not data["is_open"]:
            arduino.disconnect_arduino()
            print("Arduino serial connection disconnected")
        return None
