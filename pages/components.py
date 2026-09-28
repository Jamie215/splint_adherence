"""
UI building blocks shared by the home page and the Data Analysis page.
"""
import datetime

from dash import dcc, html
import dash_bootstrap_components as dbc

HOUR_OPTIONS = [{"label": f"{i:02d}", "value": i} for i in range(24)]
MINUTE_OPTIONS = [{"label": f"{i:02d}", "value": i} for i in range(60)]


def start_time_inputs(prefix, date=None, hour=None, minute=None, **date_kwargs):
    """
    Date / Hour / Minute pickers (Eastern time, 24-hour clock) with ids
    ``{prefix}-date``, ``{prefix}-hour`` and ``{prefix}-minute``. Read them back
    with `start_time_from_inputs`.
    """
    def field(label, component):
        return dbc.Col(html.Div([html.Label(label, className="dropdown-label"), component]),
                       width="auto")

    return dbc.Row([
        field("Date", dcc.DatePickerSingle(id=f"{prefix}-date", date=date,
                                           display_format="YYYY-MM-DD",
                                           placeholder="Date", **date_kwargs)),
        field("Hour (ET)", dcc.Dropdown(id=f"{prefix}-hour", options=HOUR_OPTIONS, value=hour,
                                        placeholder="HH", className="time-dropdown")),
        field("Minute", dcc.Dropdown(id=f"{prefix}-minute", options=MINUTE_OPTIONS, value=minute,
                                     placeholder="MM", className="time-dropdown")),
    ], className="mb-2")


def start_time_from_inputs(date, hour, minute):
    """
    Naive datetime (Eastern wall-clock time) from the picker values, or None if
    any is missing. Hour and minute can legitimately be 0, so they are checked
    against None rather than for truthiness.
    """
    if date is None or hour is None or minute is None:
        return None
    return datetime.datetime.strptime(date[:10], "%Y-%m-%d").replace(
        hour=int(hour), minute=int(minute))


def status_message(text, ok=True):
    """A one-line success (green) or error (red) status message."""
    return html.Div(text, className="status-ok" if ok else "status-error")
