import pandas as pd
import json

from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from dash.dash_table import DataTable
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import numpy as np

from app_instance import app
import pages.analysis_helper as analysis_helper

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
    
    # Add hidden storage components
    dcc.Store(id='df-value'),
    dcc.Store(id='metadata-value'),

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
     Output('metadata-value', 'data')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')]
)
def update_file_information(contents, filename):
    if contents is None:
        return (html.Div(),
                {'display': 'none'},
                None, None)
    
    df, metadata, error = analysis_helper.parse_file(contents)
    if error:
        return (html.Div([
                    html.H4('Error', style={'color': 'red'}),
                    html.P(error)
                ]),
                {'display': 'block', 'padding': '20px', 'backgroundColor': 'ghostwhite',
                 'borderRadius': '5px', 'marginBottom': '20px'},
                None, None)
    
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
    
    return (file_info,
            {'display': 'block', 'padding': '20px', 'backgroundColor': 'ghostwhite',
             'borderRadius': '5px', 'marginBottom': '20px'},
            df.to_json(date_format='iso', orient='split'),
            json.dumps(metadata))

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
        df = pd.read_json(json_data, orient='split')
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df['Temperature'] = pd.to_numeric(df['Temperature'])
        df['ProximityVal'] = pd.to_numeric(df['ProximityVal'])
        df = df.reset_index(drop=True)

    except Exception as e:
        print(e)
        # Compatibility with older version data
        if 'proximity' in str(e).lower():
            df['ProximityVal'] = np.zeros(len(df))
        else:
            return [html.Div([
                html.H4('Error', style={'color': 'red'}),
                html.P(str(e))
            ])]
        
    time_col = df["Timestamp"]
    temp_col = df["Temperature"]
    prox_col = df['ProximityVal']
    
    # Peak detection
    peaks_table = None
    combined_fig = None
    try:
        # Find onsets and offsets event and their peaks
        baseline, delta, events_df = analysis_helper.detect_onsets_offsets(time_col, temp_col, prox_col)
        print("events_df: ", events_df)

        # No peak detected
        if events_df.empty:
            # No events detected - create basic plots without peak annotations
            combined_fig = make_subplots(specs=[[{"secondary_y": True}]])
            combined_fig.add_trace(
                go.Scatter(
                    x=df['Timestamp'],
                    y=prox_col,
                    name="Proximity Value",
                    line=dict(color="red", dash='dot')
                ),
                secondary_y=True
            )
            combined_fig.add_trace(
                go.Scatter(
                    x=df["Timestamp"],
                    y=df["Temperature"],
                    name="Temperature (°C)",
                    line=dict(color="black")
                ),
                secondary_y=False
            )
            combined_fig.add_trace(
                go.Scatter(
                    x=df["Timestamp"],
                    y=baseline,
                    name="Rolling Min Baseline",
                    line=dict(color="black", dash='dot')
                ),
                secondary_y=False
            )
            combined_fig.add_trace(
                go.Scatter(
                    x=df["Timestamp"],
                    y=delta,
                    name="Delta",
                    line=dict(color="black", dash='dash')
                ),
                secondary_y=False
            )

            combined_fig.update_xaxes(title_text="Time")
            combined_fig.update_yaxes(title_text="Proximity Value", secondary_y=True, color='red')
            combined_fig.update_yaxes(title_text="Temperature (°C)", secondary_y=False)

            # Optional: Update layout
            combined_fig.update_layout(
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
        )
        print("peak_events_df: ", peak_events_df)

        combined_fig = make_subplots(specs=[[{"secondary_y": True}]])
        combined_fig.add_trace(
            go.Scatter(
                x=df['Timestamp'],
                y=prox_col,
                name="Proximity Value",
                line=dict(color="red", dash='dot')
            ),
            secondary_y=True
        )
        combined_fig.add_trace(
            go.Scatter(
                x=df["Timestamp"],
                y=df["Temperature"],
                name="Temperature (°C)",
                line=dict(color="black")
            ),
            secondary_y=False
        )
        combined_fig.add_trace(
                go.Scatter(
                    x=df["Timestamp"],
                    y=baseline,
                    name="Rolling Min Baseline",
                    line=dict(color="blue", dash='dot')
                ),
                secondary_y=False
            )
        combined_fig.add_trace(
            go.Scatter(
                x=df["Timestamp"],
                y=delta,
                name="Delta",
                line=dict(color="green", dash='dot')
            ),
            secondary_y=False
        )

        combined_fig.update_xaxes(title_text="Time")
        combined_fig.update_yaxes(title_text="Proximity Value", secondary_y=True, color='red')
        combined_fig.update_yaxes(title_text="Temperature (°C)", secondary_y=False)

        # Optional: Update layout
        combined_fig.update_layout(
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
        for _, row in peak_events_df.iterrows():
            combined_fig.add_vrect(x0=row['Start'], x1=row['End'],
                              fillcolor="LightGreen", opacity=0.3,
                              layer="below", line_width=0)

        peaks_table = html.Div([
            DataTable(
                data=peak_events_df.to_dict('records'),
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
                    f"Start: {row['Start']}<br>"
                    f"End: {row['End']}<extra></extra>"
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
                title='Hour of Day (24H)',
                range=[23, 0],
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
            y1=23,
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