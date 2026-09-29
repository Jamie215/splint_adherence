"""
Data Analysis page: upload a downloaded CSV, rebuild lost timestamps if
needed, and show detected wear events with daily and hour-of-day summaries.
"""
import io
import json

import numpy as np
import pandas as pd

import dash
from dash import dcc, html, Input, Output, State
from dash.dash_table import DataTable
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app_instance import app
import pages.analysis_helper as analysis_helper
from pages.components import start_time_inputs, start_time_from_inputs, status_message

HIDDEN = {"display": "none"}
SHOWN = {"display": "block"}

# Shared look for every figure on the page.
FIGURE_LAYOUT = dict(
    plot_bgcolor="rgba(240, 240, 240, 0.5)",
    paper_bgcolor="rgba(0, 0, 0, 0)",
    font=dict(color="#2c3e50"),
    # Explicit background: the unified hover box on the combined chart
    # otherwise inherits the transparent paper colour, which made white hover
    # text invisible on the white page.
    hoverlabel=dict(bgcolor="white", bordercolor="#adb5bd", font=dict(color="#2c3e50"),
                    namelength=-1),
)
GRAPH_CONFIG = {"displayModeBar": True}
WEAR_COLOR = "mediumseagreen"


def _format_times(events_df):
    """Render the Start/End columns as readable Eastern times for the table."""
    return events_df.assign(**{
        col: events_df[col].dt.strftime("%Y-%m-%d %H:%M %Z") for col in ("Start", "End")
    })


def build_combined_figure(df, baseline, delta, events):
    """
    Temperature, proximity, baseline and delta over time, with detected wear
    events shaded. `df` has naive Eastern wall-clock timestamps.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    traces = [
        ("Proximity Value", df["ProximityVal"], dict(color="red", dash="dot"), True),
        ("Temperature (°C)", df["Temperature"], dict(color="black"), False),
        ("Rolling Min Baseline", baseline, dict(color="blue", dash="dot"), False),
        ("Delta", delta, dict(color="green", dash="dot"), False),
    ]
    for name, y, line, secondary in traces:
        fig.add_trace(go.Scatter(x=df["Timestamp"], y=y, name=name, line=line),
                      secondary_y=secondary)

    for _, row in events.iterrows():
        fig.add_vrect(x0=row["Start"].tz_localize(None), x1=row["End"].tz_localize(None),
                      fillcolor="LightGreen", opacity=0.3, layer="below", line_width=0)

    fig.update_xaxes(title_text="Time (Eastern)")
    fig.update_yaxes(title_text="Proximity Value", secondary_y=True, color="red")
    fig.update_yaxes(title_text="Temperature (°C)", secondary_y=False)
    fig.update_layout(
        title="Temperature and Proximity Value Over Time",
        hovermode="x unified",
        margin=dict(t=60),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        **FIGURE_LAYOUT,
    )
    return fig


def build_daily_figure(daily_summary):
    """Bar chart of total wear minutes per day."""
    fig = go.Figure(go.Bar(
        x=daily_summary["Date"],
        y=daily_summary["TotalDurationMin"],
        name="Total Duration (min)",
        marker=dict(color=WEAR_COLOR),
    ))
    fig.update_layout(
        xaxis=dict(title="Date", type="category"),
        yaxis=dict(title="Daily Total Duration (min)"),
        margin=dict(t=10),
        **FIGURE_LAYOUT,
    )
    return fig


def build_hour_of_day_figure(events):
    """Each day's wear periods drawn as vertical bars against the hour of day."""
    gantt_df = analysis_helper.prepare_gantt(events["Start"], events["End"])
    fig = go.Figure()
    for _, row in gantt_df.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["Date"], row["Date"]],
            y=[row["StartHour"], row["EndHour"]],
            mode="lines",
            hovertemplate=(
                f"Start: {row['Start']:%Y-%m-%d %H:%M %Z}<br>"
                f"End: {row['End']:%Y-%m-%d %H:%M %Z}<extra></extra>"
            ),
            line=dict(color=WEAR_COLOR, width=10),
            showlegend=False,
        ))

    # Invisible markers on the first and last day pad the category axis so the
    # outermost bars aren't clipped.
    for date in (gantt_df["Date"].min(), gantt_df["Date"].max()):
        fig.add_trace(go.Scatter(x=[date], y=[0], mode="markers",
                                 marker=dict(opacity=0), showlegend=False, hoverinfo="skip"))

    # Shade the afternoon/evening half of the day.
    fig.add_shape(type="rect", xref="paper", yref="y", x0=0, x1=1, y0=12, y1=24,
                  fillcolor="rgba(200, 200, 200, 0.3)", layer="below", line_width=0)
    fig.update_layout(
        xaxis=dict(title="Date", type="category"),
        # Full day, so events up to midnight are visible.
        yaxis=dict(title="Hour of Day (24H, Eastern)", range=[24, 0], dtick=1),
        margin=dict(t=10),
        height=600,
        **FIGURE_LAYOUT,
    )
    return fig


def summary_stats(df, time_col, events, peaks_df, daily_summary):
    """Headline numbers shown above the daily chart."""
    in_event = pd.Series(False, index=df.index)
    for _, row in events.iterrows():
        in_event |= time_col.between(row["Start"], row["End"])
    stats = [
        ("Average Non-peak Temperature", f"{df.loc[~in_event, 'Temperature'].mean():.2f}°C"),
        ("Average Peak Temperature", f"{peaks_df['PeakTemp'].mean():.2f}°C"),
        ("Total Wear Time", f"{daily_summary['TotalDurationMin'].sum():.1f} minutes"),
        ("Average Wear Time Per Day", f"{daily_summary['TotalDurationMin'].mean():.1f} minutes"),
    ]
    return html.Div([html.Div([html.Strong(f"{label}: "), html.Span(value)])
                     for label, value in stats], className="my-2")


def error_panel(title, message):
    return html.Div([html.H4(title, className="status-error"), html.P(message)])


data_analysis_layout = html.Div([
    dcc.Upload(
        id="upload-data",
        children=html.Div([
            html.I(className="fas fa-file-upload"),
            " Drag and drop a CSV file here, or ",
            html.A("select a file", className="upload-link"),
        ]),
        className="upload-box",
        multiple=False,
    ),

    html.Div(id="file-info", className="panel", style=HIDDEN),

    # Timestamp recovery, shown when the device lost the logging start time
    html.Div([
        html.H4("Start Time Missing", className="warning-text"),
        html.P(
            "The device lost its logging start time, so the timestamps in this file "
            "are wrong (dates in 1970 / 2106). The readings and the time between them "
            "are intact. Enter the start date and time (Eastern) you chose when initializing "
            "the device to rebuild the real timestamps."
        ),
        start_time_inputs("recovery"),
        html.Div([
            dbc.Button("Rebuild Timestamps", id="recovery-apply", className="action-btn"),
            dbc.Button([html.I(className="fas fa-file-download"), " Download Corrected CSV"],
                       id="recovery-download-btn", className="action-btn ms-2", disabled=True),
        ]),
        html.Div(id="recovery-status", className="mt-2"),
        dcc.Download(id="recovery-download"),
    ], id="recovery-panel", className="panel panel-warning", style=HIDDEN),

    dcc.Store(id="df-value"),
    dcc.Store(id="metadata-value"),
    dcc.Store(id="raw-df-value"),
    dcc.Store(id="recovered-csv"),

    html.Div(id="output-data", className="panel"),
], className="analysis-page")


@app.callback(
    [Output("file-info", "children"),
     Output("file-info", "style"),
     Output("df-value", "data"),
     Output("metadata-value", "data"),
     Output("raw-df-value", "data"),
     Output("recovery-panel", "style"),
     Output("recovery-status", "children"),
     Output("recovered-csv", "data"),
     Output("recovery-download-btn", "disabled")],
    Input("upload-data", "contents"),
    State("upload-data", "filename"),
)
def update_file_information(contents, filename):
    """Parse the uploaded file, show its metadata, and ask for a start time if it was lost."""
    if contents is None:
        return (None, HIDDEN, None, None, None, HIDDEN, None, None, True)

    df, metadata, error = analysis_helper.parse_file(contents)
    if error:
        return (error_panel("Could not read file", error), SHOWN,
                None, None, None, HIDDEN, None, None, True)

    file_info = html.Div(
        [html.H4("File Information", className="mb-3"),
         html.Div([html.Strong("Uploaded File: "), html.Span(filename)])]
        + [html.Div([html.Strong(f"{key}: "), html.Span(value)]) for key, value in metadata.items()]
    )
    df_json = df.to_json(date_format="iso", orient="split")

    # Lost start time: hold the analysis until the user supplies the real start.
    if analysis_helper.needs_timestamp_recovery(metadata):
        return (file_info, SHOWN, None, json.dumps(metadata), df_json,
                SHOWN, None, None, True)

    return (file_info, SHOWN, df_json, json.dumps(metadata), None, HIDDEN, None, None, True)


@app.callback(
    [Output("df-value", "data", allow_duplicate=True),
     Output("recovery-status", "children", allow_duplicate=True),
     Output("recovered-csv", "data", allow_duplicate=True),
     Output("recovery-download-btn", "disabled", allow_duplicate=True)],
    Input("recovery-apply", "n_clicks"),
    [State("recovery-date", "date"),
     State("recovery-hour", "value"),
     State("recovery-minute", "value"),
     State("raw-df-value", "data"),
     State("metadata-value", "data")],
    prevent_initial_call=True
)
def apply_timestamp_recovery(n_clicks, date, hour, minute, raw_json, metadata_json):
    """Rebuild timestamps from the start time entered in the recovery panel."""
    if not n_clicks or not raw_json:
        raise dash.exceptions.PreventUpdate

    def error(msg):
        return None, status_message(msg, ok=False), None, True

    start = start_time_from_inputs(date, hour, minute)
    if start is None:
        return error("Please enter the start date, hour and minute.")

    try:
        df = pd.read_json(io.StringIO(raw_json), orient="split", convert_dates=False)
        metadata = json.loads(metadata_json) if metadata_json else {}
        df, metadata = analysis_helper.recover_timestamps(df, metadata, start)
    except Exception as e:
        return error(f"Could not rebuild timestamps: {e}")

    status = status_message(
        f"Timestamps rebuilt: {df['Timestamp'].iloc[0]} to {df['Timestamp'].iloc[-1]} "
        f"({len(df)} readings)."
    )
    csv_text = analysis_helper.to_csv_with_metadata(df, metadata)
    return df.to_json(date_format="iso", orient="split"), status, csv_text, False


@app.callback(
    Output("recovery-download", "data"),
    Input("recovery-download-btn", "n_clicks"),
    [State("recovered-csv", "data"),
     State("upload-data", "filename")],
    prevent_initial_call=True
)
def download_recovered_csv(n_clicks, csv_text, filename):
    """Download the file with rebuilt timestamps as `<name>_recovered.csv`."""
    if not n_clicks or not csv_text:
        raise dash.exceptions.PreventUpdate
    base = (filename or "data.csv").rsplit(".", 1)[0]
    return dict(content=csv_text, filename=f"{base}_recovered.csv", type="text/csv")


@app.callback(
    Output("output-data", "children"),
    Input("df-value", "data"),
)
def update_dashboard(json_data):
    """Detect wear events and render the plots, events table and summaries."""
    if not json_data:
        return html.H6("Upload a file to see the analysis.", className="text-center")
    try:
        df = pd.read_json(io.StringIO(json_data), orient="split")
        # Tz-aware Eastern time (legacy naive-UTC files are converted too).
        df["Timestamp"] = analysis_helper.to_display_tz(df["Timestamp"])
        df["Temperature"] = pd.to_numeric(df["Temperature"])
        # Older-version datasets have no ProximityVal column; default it to 0.
        if "ProximityVal" in df.columns:
            df["ProximityVal"] = pd.to_numeric(df["ProximityVal"])
        else:
            df["ProximityVal"] = np.zeros(len(df))
        df = df.reset_index(drop=True)
    except Exception as e:
        return error_panel("Could not read data", str(e))

    time_col = df["Timestamp"]
    # Plotly is given naive Eastern wall-clock times so axes and hovers read in
    # Eastern time rather than being shifted by the browser or by plotly.
    plot_df = df.assign(Timestamp=time_col.dt.tz_localize(None))

    try:
        baseline, delta, events_df = analysis_helper.detect_onsets_offsets(
            time_col, df["Temperature"], df["ProximityVal"])

        if events_df.empty:
            empty = pd.DataFrame(columns=["Start", "End"])
            return html.Div([
                html.H4("Detected Wear Events"),
                dcc.Graph(figure=build_combined_figure(plot_df, baseline, delta, empty),
                          config=GRAPH_CONFIG, style={"height": "500px"}),
                html.H4("Summary", className="mt-4"),
                html.P("No wear events were detected in this dataset."),
            ])

        events_df = events_df.reset_index(drop=True)
        events_df["EventID"] = events_df.index
        peaks_df = analysis_helper.extract_peaks(time_col, df["Temperature"], events_df)

        events = (
            events_df.merge(peaks_df[["EventID", "PeakTemp"]], on="EventID")
                     .sort_values("Onset")
                     [["Onset", "Offset", "DurationMin", "PeakTemp"]]
                     .rename(columns={
                         "Onset": "Start",
                         "Offset": "End",
                         "DurationMin": "Duration (Min)",
                         "PeakTemp": "Peak Temperature (°C)",
                     })
                     .reset_index(drop=True)
        )
        daily_summary = analysis_helper.prepare_daily_summary(events["Start"], events["End"])

        return html.Div([
            html.H4("Detected Wear Events"),
            dcc.Graph(figure=build_combined_figure(plot_df, baseline, delta, events),
                      config=GRAPH_CONFIG, style={"height": "500px"}),
            DataTable(
                data=_format_times(events).round(2).to_dict("records"),
                columns=[{"name": col, "id": col} for col in events.columns],
                page_size=20,
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "left", "padding": "5px", "fontFamily": "Roboto, sans-serif"},
                style_header={"backgroundColor": "#f4f4f4", "fontWeight": "bold"},
            ),
            html.H4("Daily Wear Summary", className="mt-4"),
            summary_stats(df, time_col, events, peaks_df, daily_summary),
            dcc.Graph(figure=build_daily_figure(daily_summary), config=GRAPH_CONFIG),
            html.H4("Wear Periods by Hour of Day", className="mt-4"),
            dcc.Graph(figure=build_hour_of_day_figure(events), config=GRAPH_CONFIG),
        ])
    except Exception as e:
        return error_panel("Wear detection failed", str(e))
