"""
Home page: the Initialize Device and Data Download flows (shown in a modal),
plus the link to the Data Analysis page.
"""
import datetime
import logging

from dash import dcc, html, Input, Output, State, callback_context
import dash
import dash_bootstrap_components as dbc

from app_instance import app
import arduino
import pages.analysis_helper as analysis_helper
from pages.components import start_time_inputs, start_time_from_inputs, status_message
from timezone_config import DISPLAY_TZ

logger = logging.getLogger(__name__)

HIDDEN = {"display": "none"}

MODAL_TITLES = {
    "initialize": "Initialize Device",
    "download": "Download Data",
}

NOT_FOUND_HELP = [
    "Please make sure the device is ",
    html.B("powered"), ", ",
    html.B("connected by USB"), ", and in ",
    html.B("idle mode"),
    ". A device that is logging cannot be seen by this computer: power-cycle it once and try again.",
]


def initialize_form(visible):
    """
    Start time and participant ID fields. Always part of the modal (hidden
    outside the initialize step) because the modal callback reads them as State.
    """
    # Pre-fill with the current Eastern time, independent of the PC's own zone.
    now = datetime.datetime.now(DISPLAY_TZ)
    return html.Div([
        html.Div("Choose when the device should start logging (Eastern time, 24-hour clock) "
                 "and enter the participant ID.", className="mb-3"),
        start_time_inputs(
            "init", date=now.date(), hour=now.hour, minute=now.minute,
            min_date_allowed=now.date(),
            max_date_allowed=now.date() + datetime.timedelta(days=60),
            initial_visible_month=now.date(),
        ),
        html.Label("Participant ID", className="dropdown-label"),
        dbc.Input(id="input-personal-id", type="text", maxLength=arduino.PERSONAL_ID_MAX_LEN,
                  placeholder="e.g. SA-014"),
        dbc.FormFeedback(id="personal-id-feedback", type="invalid"),
    ], style=None if visible else HIDDEN)


def download_form(visible):
    """
    Filename field and download button. The button and dcc.Download are always
    part of the modal; the rest only in the download step.
    """
    fields = []
    if visible:
        fields = [
            html.Label("File name", className="dropdown-label"),
            dbc.Input(id="download-filename", placeholder="Subject(UID)_(Quarter).(DeviceIteration)",
                      value="Subject_", required=True, className="mb-2"),
            dcc.Loading(type="circle", children=html.Div(id="download-file-status")),
            # Filled with a start-time prompt if the device lost its start time
            html.Div(id="download-recovery"),
            dcc.Store(id="download-raw-store"),
        ]
    return html.Div(fields + [
        html.Div(
            dbc.Button([html.I(className="fas fa-file-download"), " Download Data"],
                       id="download-btn", className="action-btn mt-2",
                       style=None if visible else HIDDEN),
            className="flex-container",
        ),
        dcc.Download(id="download-data"),
    ])


def modal_footer(primary=None, retry_label="Try Again"):
    """
    Footer with the step's primary button. All three buttons always exist (the
    modal callback listens to each); only `primary` is shown.
    """
    def button(label, button_id, name):
        return dbc.Button(label, id=button_id, className="action-btn ms-2",
                          style=None if primary == name else HIDDEN)

    warning = None
    if primary in ("connect", "initialize"):
        warning = html.Div([html.I(className="fas fa-exclamation-circle"),
                            " Closing this window cancels the device connection."],
                           className="disclaimer-msg")
    return dbc.ModalFooter(
        [
            warning,
            html.Div([
                button("Connect", "connect-modal", "connect"),
                button("Initialize", "initialize-btn", "initialize"),
                button(retry_label, "re-attempt-btn", "retry"),
            ], className="ms-auto"),
        ],
        className="justify-content-between" if primary else "d-none",
    )


def modal_content(mode, step="start", message=None):
    """
    Header, body and footer of the action modal.

    mode: "initialize" or "download"
    step: "start"       - ask to connect the device
          "initialize"  - start time / participant ID form
          "initialized" - success; `message` is the formatted start time
          "download"    - filename and download button
          "no-data"     - device connected but never initialized
          "error"       - connection or device error; `message` explains it
    """
    body = []
    footer = modal_footer()

    if step == "start":
        body = [html.Div("Connect the device to this computer with a USB cable, then click Connect.")]
        footer = modal_footer("connect")
    elif step == "initialize":
        footer = modal_footer("initialize")
    elif step == "initialized":
        body = [
            html.I(className="fas fa-check-circle status-icon status-ok"),
            html.Div([
                "The device is set to start logging on ",
                html.B(message, className="text-primary"),
                " and has powered down. It will start logging the next time it is powered on.",
            ], className="mb-2"),
            html.Div("You may now disconnect the device. To initialize another device, "
                     "connect it and click Initialize Another."),
        ]
        footer = modal_footer("retry", retry_label="Initialize Another")
    elif step == "no-data":
        body = [html.Div("This device has not been initialized, so it has no data to download. "
                         "Initialize it first.")]
        footer = modal_footer("retry")
    elif step == "error":
        body = [
            html.I(className="fas fa-times-circle status-icon status-error"),
            html.Div(message, className="status-error text-center mb-2") if message else None,
            html.Div(NOT_FOUND_HELP),
        ]
        footer = modal_footer("retry")

    return [
        dbc.ModalHeader(dbc.ModalTitle(MODAL_TITLES.get(mode, "Device"), className="modal-header-text")),
        dbc.ModalBody(body + [initialize_form(step == "initialize"),
                              download_form(step == "download")]),
        footer,
    ]


def recovery_prompt():
    """
    Start-time prompt shown in the download modal when the device's logging
    start time was lost, so the saved file gets real timestamps.
    """
    return html.Div([
        html.Div([html.I(className="fas fa-exclamation-triangle"), html.B(" Start time missing")],
                 className="warning-text"),
        html.Div(
            "The device lost its logging start time, but every reading and the time "
            "between readings are intact. Enter the start date and time (Eastern) you chose "
            "when initializing the device to save the file with real timestamps.",
            className="mb-2"
        ),
        start_time_inputs("dl-recovery"),
        html.Div([
            dbc.Button([html.I(className="fas fa-file-download"), " Save Corrected File"],
                       id="dl-recovery-save", className="action-btn"),
            dbc.Button("Save Without Correcting", id="dl-recovery-save-raw",
                       outline=True, color="secondary", className="ms-2"),
        ]),
        html.Div(id="dl-recovery-status", className="mt-2"),
    ], className="mt-2")


def index_layout():
    """
    Home page layout: Initialize Device, Data Download and Data Analysis.
    """
    def page_button(icon, label, **kwargs):
        return dbc.Button([html.I(className=f"fas {icon} page-btn-icon"), label],
                          outline=True, className="m-3 page-btn", **kwargs)

    return html.Div(
        [
            page_button("fa-microchip", "Initialize Device", id="open-initialize-modal"),
            page_button("fa-download", "Data Download", id="open-download-modal"),
            page_button("fa-chart-bar", "Data Analysis", href="/data-analysis"),
            dcc.Store(id="action-modal-mode"),
            dbc.Modal(modal_content(None), id="action-modal", centered=True, is_open=False),
        ],
        className="flex-container home-page"
    )


def register_index_callbacks():
    @app.callback(
            [Output("input-personal-id", "invalid"),
            Output("personal-id-feedback", "children")],
            [Input("input-personal-id", "value"),
            Input("initialize-btn", "n_clicks")],
            prevent_initial_call=True)
    def validate_personal_id_input(personal_id, _init_click):
        """
        Flag an invalid participant ID on the field as it is typed, and when
        Initialize is clicked (which does nothing until the ID is valid).
        """
        error = arduino.validate_personal_id(personal_id)
        return bool(error), error

    @app.callback(
            [Output("action-modal", "is_open"),
            Output("action-modal", "children"),
            Output("action-modal-mode", "data")],
            [Input("open-initialize-modal", "n_clicks"),
            Input("open-download-modal", "n_clicks"),
            Input("re-attempt-btn", "n_clicks"),
            Input("connect-modal", "n_clicks"),
            Input("initialize-btn", "n_clicks")],
            [State("action-modal-mode", "data"),
            State("init-date", "date"),
            State("init-hour", "value"),
            State("init-minute", "value"),
            State("input-personal-id", "value")],
            prevent_initial_call=True)
    def toggle_action_modal(_init_click, _dl_click, _retry_click, _connect_click, _init_btn_click,
                            mode, date, hour, minute, personal_id):
        """
        Drive the modal through its steps: open (Initialize or Download),
        Connect, Initialize, and Try Again.
        """
        triggered_id = callback_context.triggered_id
        # Buttons re-created with the modal content report n_clicks=None; only
        # real clicks count.
        if not callback_context.triggered[0]["value"]:
            raise dash.exceptions.PreventUpdate

        if triggered_id == "open-initialize-modal":
            mode = "initialize"
        elif triggered_id == "open-download-modal":
            mode = "download"

        def show(step, message=None):
            return True, modal_content(mode, step, message), mode

        try:
            if triggered_id in ("open-initialize-modal", "open-download-modal", "re-attempt-btn"):
                return show("start")

            if triggered_id == "connect-modal":
                status = arduino.client.get_status()
                if status not in (b"NEED_CONFIGURATION", b"HAS_DATA"):
                    logger.info(f"Device not ready (status {status!r})")
                    return show("error", "No device found.")
                if mode == "initialize":
                    return show("initialize")
                if status == b"NEED_CONFIGURATION":
                    return show("no-data")
                return show("download")

            if triggered_id == "initialize-btn":
                # An invalid participant ID is flagged on the field itself
                # (see validate_personal_id_input); keep the form open.
                if arduino.validate_personal_id(personal_id):
                    raise dash.exceptions.PreventUpdate

                start = start_time_from_inputs(date, hour, minute)
                if start is None:
                    return show("error", "Please choose a start date and time.")

                # The entered time is Eastern wall-clock time (DST-aware); the
                # device stores the equivalent UTC epoch.
                start = DISPLAY_TZ.localize(start)
                success, message = arduino.client.initialize(int(start.timestamp()),
                                                             personal_id.strip())
                if not success:
                    return show("error", message)
                return show("initialized", start.strftime("%A, %B %d at %I:%M %p %Z"))

        except dash.exceptions.PreventUpdate:
            raise
        except Exception as e:
            logger.exception("Exception while handling modal action")
            return show("error", str(e))

        raise dash.exceptions.PreventUpdate

    @app.callback(
            [Output("download-data", "data"),
            Output("download-filename", "invalid"),
            Output("download-file-status", "children"),
            Output("download-recovery", "children"),
            Output("download-raw-store", "data")],
            [Input("download-btn", "n_clicks")],
            [State("download-filename", "value"),
            State("action-modal", "is_open")],
            # Disable the button while the device is being read.
            running=[(Output("download-btn", "disabled"), True, False)],
            prevent_initial_call=True)
    def download_data(download_click, filename, is_open):
        """
        Read the data from the device and save it as `<filename>.csv`. If the
        device lost its start time, hold the file and ask for the start first.
        """
        if not download_click or not is_open:
            raise dash.exceptions.PreventUpdate

        if not filename or not filename.strip():
            return (None, True, status_message("Please enter a file name.", ok=False), None, None)

        try:
            file_content = arduino.client.download(f"{filename.strip()}.csv")
        except Exception as e:
            logger.exception("Download failed")
            return (None, False, status_message(str(e), ok=False), None, None)

        _, metadata, error = analysis_helper.parse_text(file_content["content"])
        if not error and analysis_helper.needs_timestamp_recovery(metadata):
            return (None, False, None, recovery_prompt(), file_content)

        return (file_content, False, status_message("Download complete."), None, None)

    @app.callback(
            [Output("download-data", "data", allow_duplicate=True),
            Output("dl-recovery-status", "children")],
            [Input("dl-recovery-save", "n_clicks"),
            Input("dl-recovery-save-raw", "n_clicks")],
            [State("dl-recovery-date", "date"),
            State("dl-recovery-hour", "value"),
            State("dl-recovery-minute", "value"),
            State("download-raw-store", "data")],
            prevent_initial_call=True)
    def save_recovered_download(save_click, save_raw_click, date, hour, minute, raw_file):
        """
        Save a device download whose start time was lost, either with timestamps
        rebuilt from the start time entered in the prompt, or unchanged (it can
        still be corrected later on the Data Analysis page).
        """
        if not raw_file or not (save_click or save_raw_click):
            raise dash.exceptions.PreventUpdate

        if callback_context.triggered_id == "dl-recovery-save-raw":
            return raw_file, status_message(
                "Saved uncorrected. You can rebuild the timestamps later on the Data Analysis page.")

        start = start_time_from_inputs(date, hour, minute)
        if start is None:
            return dash.no_update, status_message("Please enter the start date, hour and minute.",
                                                  ok=False)

        df, metadata, error = analysis_helper.parse_text(raw_file["content"])
        if error:
            return dash.no_update, status_message(error, ok=False)
        df, metadata = analysis_helper.recover_timestamps(df, metadata, start)

        corrected = dict(raw_file, content=analysis_helper.to_csv_with_metadata(df, metadata))
        return corrected, status_message(
            f"Download complete: timestamps rebuilt from {df['Timestamp'].iloc[0]} "
            f"to {df['Timestamp'].iloc[-1]}.")

    @app.callback(
            Output("action-modal-status", "children"),
            Input("action-modal", "is_open"),
            prevent_initial_call=True
    )
    def release_device_on_close(is_open):
        """Close the serial connection when the modal is closed."""
        if not is_open:
            arduino.client.disconnect()
            logger.info("Arduino serial connection disconnected")
        return None
