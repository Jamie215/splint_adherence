import datetime
import io
import json

import pandas as pd

from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.dash_table import DataTable
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import numpy as np

from app_instance import app
import pages.analysis_helper as analysis_helper


def _format_times(events_df):
    """Render the Start/End columns as readable Eastern times for the table."""
    return events_df.assign(**{
        col: events_df[col].dt.strftime('%Y-%m-%d %H:%M %Z') for col in ('Start', 'End')
    })

def build_combined_figure(df, baseline, delta):
    """
    Build the combined temperature/proximity/baseline/delta figure shared by
    both the "events detected" and "no events" code paths.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=df['Timestamp'],
            y=df['ProximityVal'],
            name="Proximity Value",
            line=dict(color="red", dash='dot')
        ),
        secondary_y=True
    )
    fig.add_trace(
        go.Scatter(
            x=df['Timestamp'],
            y=df['Temperature'],
            name="Temperature (°C)",
            line=dict(color="black")
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=df['Timestamp'],
            y=baseline,
            name="Rolling Min Baseline",
            line=dict(color="blue", dash='dot')
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=df['Timestamp'],
            y=delta,
            name="Delta",
            line=dict(color="green", dash='dot')
        ),
        secondary_y=False
    )

    fig.update_xaxes(title_text="Time (Eastern)")
    fig.update_yaxes(title_text="Proximity Value", secondary_y=True, color='red')
    fig.update_yaxes(title_text="Temperature (°C)", secondary_y=False)
    fig.update_layout(
        title="Temperature and Proximity Value Over Time",
        hovermode="x unified",
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        paper_bgcolor='rgba(0, 0, 0, 0)',
        font=dict(color='#2c3e50'),
        margin=dict(t=60),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.25,
            xanchor="center",
            x=0.5
        )
    )
    return fig


# Define app layout with styling
data_analysis_layout = html.Div([
    # File Upload Component
    html.Div([
        dcc.Upload(
            id='upload-data',
            children=html.Div([
                'Drag and Drop or ',
                html.A('Select Files', style={'color': '#3498db', 'fontWeight': 'bold'})
            ]),
            style={
                'width': '100%',
                'height': '60px',
                'lineHeight': '60px',
                'borderWidth': '1px',
                'borderStyle': 'dashed',
                'borderRadius': '5px',
                'textAlign': 'center',
                'margin': '10px 0'
            },
            multiple=False
        ),
    ], style={
        'padding': '20px', 
        'backgroundColor': 'ghostwhite', 
        'borderRadius': '5px', 
        'marginBottom': '20px'}),
    
    # File info section
    html.Div(id='file-info', style={
        'width': '200px',
        'backgroundColor': 'ghostwhite', 
        'borderRadius': '5px', 
        'marginBottom': '20px',
        'display': 'none'
    }),
    
    # Timestamp recovery, shown when the device lost the logging start time
    html.Div([
        html.H4('Start Time Missing', style={'color': 'darkorange', 'marginBottom': '10px'}),
        html.P(
            "The device lost its logging start time, so the timestamps in this file "
            "are wrong (dates in 1970 / 2106). The readings and the time between them "
            "are intact. Enter the start date and time (Eastern) you chose when initializing "
            "the device to rebuild the real timestamps."
        ),
        html.Div([
            dcc.DatePickerSingle(id='recovery-date', display_format='YYYY-MM-DD',
                                 placeholder='Start date'),
            dcc.Input(id='recovery-time', type='text', placeholder='HH:MM (24h, Eastern)',
                      debounce=True, style={'marginLeft': '10px', 'height': '48px'}),
            html.Button('Rebuild Timestamps', id='recovery-apply', n_clicks=0,
                        className='btn recovery-btn', style={'marginLeft': '10px'}),
            html.Button('Download Corrected CSV', id='recovery-download-btn', n_clicks=0,
                        className='btn recovery-btn', disabled=True,
                        style={'marginLeft': '10px'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap'}),
        html.Div(id='recovery-status', style={'marginTop': '10px'}),
        dcc.Download(id='recovery-download'),
    ], id='recovery-panel', style={'display': 'none'}),

    # Add hidden storage components
    dcc.Store(id='df-value'),
    dcc.Store(id='metadata-value'),
    dcc.Store(id='raw-df-value'),
    dcc.Store(id='recovered-csv'),

    # Statistics and Graph Container
    html.Div(id='output-data', style={
        'padding': '20px',
        'backgroundColor': 'ghostwhite', 
        'borderRadius': '5px'
    })], style={
        'maxWidth':'1200px', 
        'margin': '0 auto', 
        'padding': '20px', 
        'fontFamily': 'Arial, sans-serif'
    })

# Callback #1 - Process file upload
@app.callback(
    [Output('file-info', 'children'),
     Output('file-info', 'style'),
     Output('df-value', 'data'),
     Output('metadata-value', 'data'),
     Output('raw-df-value', 'data'),
     Output('recovery-panel', 'style'),
     Output('recovery-status', 'children'),
     Output('recovered-csv', 'data'),
     Output('recovery-download-btn', 'disabled')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')]
)
def update_file_information(contents, filename):
    hidden = {'display': 'none'}
    if contents is None:
        return (html.Div(), hidden, None, None, None, hidden, None, None, True)

    df, metadata, error = analysis_helper.parse_file(contents)
    if error:
        return (html.Div([
                    html.H4('Error', style={'color': 'red'}),
                    html.P(error)
                ]),
                {'display': 'block', 'padding': '20px', 'backgroundColor': 'ghostwhite',
                 'borderRadius': '5px', 'marginBottom': '20px'},
                None, None, None, hidden, None, None, True)
    
    # Create file info display
    file_info = html.Div([
        html.H4('File Information', style={'marginBottom': '15px', 'color': '#2c3e50'}),
        html.Div([
            html.Div([
                html.Strong('Uploaded File: '),
                html.Span(filename)
            ], style={'marginBottom': '5px'}),
        ])
    ])
    
    # Add metadata section if available
    if metadata:
        metadata_rows = []
        for key, value in metadata.items():
            metadata_rows.append(html.Div([
                html.Strong(f"{key}: "),
                html.Span(value)
            ], style={'marginBottom': '5px'}))
        file_info.children.append(html.Div(metadata_rows))
    
    panel_style = {'display': 'block', 'padding': '20px', 'backgroundColor': 'ghostwhite',
                   'borderRadius': '5px', 'marginBottom': '20px'}
    df_json = df.to_json(date_format='iso', orient='split')

    # Lost start time: hold the analysis until the user supplies the real start.
    if analysis_helper.needs_timestamp_recovery(metadata):
        return (file_info, panel_style, None, json.dumps(metadata), df_json,
                {**panel_style, 'border': '1px solid darkorange'}, None, None, True)

    return (file_info, panel_style, df_json, json.dumps(metadata),
            None, hidden, None, None, True)


# Callback - Rebuild timestamps from a user-supplied start time
@app.callback(
    [Output('df-value', 'data', allow_duplicate=True),
     Output('recovery-status', 'children', allow_duplicate=True),
     Output('recovered-csv', 'data', allow_duplicate=True),
     Output('recovery-download-btn', 'disabled', allow_duplicate=True)],
    [Input('recovery-apply', 'n_clicks')],
    [State('recovery-date', 'date'),
     State('recovery-time', 'value'),
     State('raw-df-value', 'data'),
     State('metadata-value', 'data')],
    prevent_initial_call=True
)
def apply_timestamp_recovery(n_clicks, date, time_str, raw_json, metadata_json):
    if not n_clicks or not raw_json:
        return None, None, None, True

    def error(msg):
        return None, html.Span(msg, style={'color': 'indianred'}), None, True

    if not date or not time_str:
        return error("Please enter both the start date and time.")
    start = None
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            start = datetime.datetime.strptime(f"{date[:10]} {time_str.strip()}", f"%Y-%m-%d {fmt}")
            break
        except ValueError:
            continue
    if start is None:
        return error("Time must be in 24-hour HH:MM format, e.g. 14:30.")

    try:
        df = pd.read_json(io.StringIO(raw_json), orient='split', convert_dates=False)
        metadata = json.loads(metadata_json) if metadata_json else {}
        df, metadata = analysis_helper.recover_timestamps(df, metadata, start)
    except Exception as e:
        return error(f"Could not rebuild timestamps: {e}")

    status = html.Span(
        f"Timestamps rebuilt: {df['Timestamp'].iloc[0]} to {df['Timestamp'].iloc[-1]} "
        f"({len(df)} readings).",
        style={'color': 'mediumseagreen'}
    )
    csv_text = analysis_helper.to_csv_with_metadata(df, metadata)
    return df.to_json(date_format='iso', orient='split'), status, csv_text, False


# Callback - Download the file with rebuilt timestamps
@app.callback(
    Output('recovery-download', 'data'),
    [Input('recovery-download-btn', 'n_clicks')],
    [State('recovered-csv', 'data'),
     State('upload-data', 'filename')],
    prevent_initial_call=True
)
def download_recovered_csv(n_clicks, csv_text, filename):
    if not n_clicks or not csv_text:
        return None
    base = (filename or 'data.csv').rsplit('.', 1)[0]
    return dict(content=csv_text, filename=f"{base}_recovered.csv", type='text/csv')

# Callback #2 - Generate basic information after file upload
@app.callback(
    [Output('output-data', 'children')],
    [Input('df-value', 'data')]
)
def update_dashboard(json_data):
    if not json_data:
        return [html.Div([
            html.H6("Upload the file to generate the analysis view.", style={"textAlign":"center"})
        ])]
    try:
        df = pd.read_json(io.StringIO(json_data), orient='split')
        # Tz-aware Eastern time (legacy naive-UTC files are converted too).
        df['Timestamp'] = analysis_helper.to_display_tz(df['Timestamp'])
        df['Temperature'] = pd.to_numeric(df['Temperature'])
        # Older-version datasets have no ProximityVal column; default it to 0.
        if 'ProximityVal' in df.columns:
            df['ProximityVal'] = pd.to_numeric(df['ProximityVal'])
        else:
            df['ProximityVal'] = np.zeros(len(df))
        df = df.reset_index(drop=True)
    except Exception as e:
        return [html.Div([
            html.H4('Error', style={'color': 'red'}),
            html.P(str(e))
        ])]

    time_col = df["Timestamp"]
    # Plotly is given naive Eastern wall-clock times so axes and hovers read in
    # Eastern time rather than being shifted by the browser or by plotly.
    plot_df = df.assign(Timestamp=time_col.dt.tz_localize(None))
    temp_col = df["Temperature"]
    prox_col = df['ProximityVal']
    
    # Peak detection
    peaks_table = None
    combined_fig = None
    try:
        # Find onsets and offsets event and their peaks
        baseline, delta, events_df = analysis_helper.detect_onsets_offsets(time_col, temp_col, prox_col)

        # No peak detected
        if events_df.empty:
            # No events detected - create basic plots without peak annotations
            combined_fig = build_combined_figure(plot_df, baseline, delta)

            return [html.Div([
                html.Hr(style={'margin': '20px 0'}),
                html.H4('Data Analysis', style={'marginTop': '30px'}),
                dcc.Graph(id='combined-graph', figure=combined_fig, config={'displayModeBar': True}, style={'height': '500px'}),
                html.H4('Summary', style={'marginTop': '30px'}),
                html.P('No significant temperature events were detected in this dataset.')
            ])]
        
        events_df = events_df.reset_index(drop=True)
        events_df['EventID'] = events_df.index
        peaks_df = analysis_helper.extract_peaks(time_col, temp_col, events_df)

        # Merge events_df and peaks_df
        peak_events_df = (
            events_df.merge(peaks_df[["EventID", "PeakTemp", "PeakTime"]], on="EventID")
                    .sort_values("Onset")
        )

        peak_events_df = (
            peak_events_df[["Onset", "Offset", "DurationMin", "PeakTemp"]]
                    .rename(columns={
                        "Onset": "Start",
                        "Offset": "End",
                        "DurationMin": "Duration (Min)",
                        "PeakTemp": "Peak Temperature (°C)"
                    })
                    .reset_index(drop=True)
        )

        combined_fig = build_combined_figure(plot_df, baseline, delta)
        for _, row in peak_events_df.iterrows():
            combined_fig.add_vrect(x0=row['Start'].tz_localize(None), x1=row['End'].tz_localize(None),
                              fillcolor="LightGreen", opacity=0.3,
                              layer="below", line_width=0)

        peaks_table = html.Div([
            DataTable(
                data=_format_times(peak_events_df).to_dict('records'),
                columns=[{"name": i, "id": i} for i in peak_events_df.columns],
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'left', 'padding': '5px'},
                style_header={'backgroundColor': '#f4f4f4', 'fontWeight': 'bold'}
            )
        ])

        # Gantt Chart
        gantt_df = analysis_helper.prepare_gantt(peak_events_df["Start"], peak_events_df["End"])
        gantt_fig = go.Figure()

        for _, row in gantt_df.iterrows():
            gantt_fig.add_trace(go.Scatter(
                x=[row['Date'], row['Date']],
                y=[row['StartHour'], row['EndHour']],
                mode='lines',
                hovertemplate=(
                    f"Start: {row['Start']:%Y-%m-%d %H:%M %Z}<br>"
                    f"End: {row['End']:%Y-%m-%d %H:%M %Z}<extra></extra>"
                ),
                line=dict(color='mediumseagreen', width=10),
                showlegend=False
            ))
        
        #  For padding on the left
        gantt_fig.add_trace(go.Scatter(
            x=[gantt_df['Date'].min()],
            y=[0],  # Arbitrary y within visible range
            mode='markers',
            marker=dict(opacity=0),
            showlegend=False
        ))

        #  For padding on the right
        gantt_fig.add_trace(go.Scatter(
            x=[gantt_df['Date'].max()],
            y=[0],  # Same here
            mode='markers',
            marker=dict(opacity=0),
            showlegend=False
        ))

        gantt_fig.update_layout(
            xaxis=dict(
                title='Date',
                type='category',
            ),
            yaxis=dict(
                title='Hour of Day (24H, Eastern)',
                range=[24, 0],  # full day, so events up to midnight are visible
                dtick=1
            ),
            hoverlabel=dict(
                font=dict(color='white')
            ),
            plot_bgcolor='rgba(240, 240, 240, 0.5)',
            paper_bgcolor='rgba(0, 0, 0, 0)',
            font=dict(color='#2c3e50'),
            margin=dict(t=10),
            height=600
        )

        gantt_fig.add_shape(
            type="rect",
            xref="paper",  # spans entire x-axis
            yref="y",
            x0=0,
            x1=1,
            y0=12,
            y1=24,
            fillcolor="rgba(200, 200, 200, 0.3)",  # adjust color/opacity as needed
            layer="below",
            line_width=0
        )

        # Daily Summary
        daily_summary = analysis_helper.prepare_occurance_summary(peak_events_df["Start"], peak_events_df["End"])
        summary_fig = go.Figure()

        summary_fig.add_trace(go.Bar(
            x=daily_summary['Date'],
            y=daily_summary['TotalDurationMin'],
            name='Total Duration (min)',
            marker=dict(color='mediumseagreen')
        ))

        summary_fig.update_layout(
            xaxis_title="Date",
            yaxis=dict(
                title="Daily Total Duration (min)"
            ),
            xaxis=dict(type='category'),
            legend=dict(x=0, y=1.15, orientation="h"),
            hoverlabel=dict(
                font=dict(color='white')
            ),
            plot_bgcolor='rgba(240,240,240,0.5)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#2c3e50'),
            margin=dict(t=10)
        )

        avg_peak_temp = peaks_df['PeakTemp'].mean()
        non_peak_series = pd.Series(True, index=df.index)
        for _, row in peak_events_df.iterrows():
            in_peak = time_col.between(row['Start'], row['End'])
            non_peak_series &= ~in_peak

        # Apply the mask to get non-peak temperature readings
        non_peak_temps = df.loc[non_peak_series, "Temperature"]
        avg_non_peak_temp = non_peak_temps.mean()
        
        stats_info = html.Div([
            html.Div([html.Strong('Average Non-peak Temperature: '), html.Span(f"{avg_non_peak_temp:.2f}°C")]),
            html.Div([html.Strong('Average Peak Temperature: '), html.Span(f"{avg_peak_temp:.2f}°C")]),
            html.Div([html.Strong('Total Duration Minutes: '), html.Span((f"{np.sum(daily_summary['TotalDurationMin']):.1f} Minutes"))]),
            html.Div([html.Strong('Average Total Duration Minutes Per Day: '), html.Span((f"{np.mean(daily_summary['TotalDurationMin']):.1f} Minutes"))])
        ], style={'marginTop':'10px', 'marginBottom':'10px'})

        return [html.Div([
            html.Hr(style={'margin': '20px 0'}),
            html.H4('Estimated Occurance Detection', style={'marginTop': '30px'}),
            dcc.Graph(
                id='combined-graph',
                figure=combined_fig,
                config={'displayModeBar': True},
                style={'height': '500px'}
            ) if combined_fig else html.Div(),
            peaks_table,
            html.H4('Estimated Splint-Wearing Summary', style={'marginTop': '30px'}),
            stats_info,
            dcc.Graph(
                id='summary-chart',
                figure=summary_fig,
                config={'displayModeBar': True},
            ) if summary_fig else html.Div(),
            html.H4('Splint Wearing Periods by Hour of Day', style={'marginTop': '30px'}),
            dcc.Graph(
                id='gantt-chart',
                figure=gantt_fig,
                config={'displayModeBar': True},
            ) if gantt_fig else html.Div()
        ])]
    except Exception as e:
        return [html.Div([
            html.H4("Peak Detection Failed", style={'color': 'red'}),
            html.P(str(e))
        ])]