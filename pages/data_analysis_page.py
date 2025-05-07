import base64
import io
import pandas as pd
import json

from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from dash.dash_table import DataTable
import plotly.express as px
import plotly.graph_objects as go
from scipy.signal import find_peaks, peak_widths
import numpy as np

from app_instance import app

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
    dcc.Store(id='intermediate-value'),
    dcc.Store(id='metadata-value'),
    dcc.Store(id='column-info'),

    # Aggregation Control (Initially hidden)
    html.Div([
        html.Hr(style={'margin': '20px 0'}),
        html.H4('Time vs Temperature', style={'color': '#2c3e50', 'margin-left': '20px'}),
        dbc.Row([
            dbc.Col(
                html.Label("Select different time interval for aggregate view:", style={'fontWeight': 'bold'}), width=6),
            dbc.Col(
                dcc.Dropdown(
                    id='aggregation-interval',
                    options=[
                        {'label': '5 Min', 'value': '5min'},
                        {'label': '1 Hour', 'value': '1H'},
                        {'label': '1 Day', 'value': '1D'}
                    ],
                    value='5min',
                    clearable=False,
                    style={'width': '150px'}
            ), width=6)
        ], style={'align-items': 'center'})], id='aggregation-control', style={'display': 'none'}),

    # Aggregated Graph (Initially hidden)
    html.Div([
        dcc.Graph(id='temperature-graph', style={'height': '450px'})
    ], id='aggregation-graph-container', style={'display': 'none'}),

    # Statistics and Graph Container
    html.Div(id='output-data-upload', style={
        'padding': '20px',
        'backgroundColor': 'ghostwhite', 
        'borderRadius': '5px'
    })], style={
        'maxWidth':'1200px', 
        'margin': '0 auto', 
        'padding': '20px', 
        'fontFamily': 'Arial, sans-serif'
    })

def parse_custom_csv(contents):
    """
    Parser specifically designed for files with metadata section followed by data table.
    """
    # Decode the file contents
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    
    try:
        # Read file as text
        file_content = decoded.decode('utf-8')
        lines = file_content.strip().split('\n')
        
        # Find where the data table starts (line with headers)
        data_start = None
        for i, line in enumerate(lines):
            line_lower = line.lower()
            # Look for a line that has both timestamp and temperature
            if ('timestamp' in line_lower or 'time' in line_lower) and \
               ('temperature' in line_lower or 'temp' in line_lower):
                data_start = i
                break
        
        # If we can't find a clear data section, try just looking for timestamp
        if data_start is None:
            for i, line in enumerate(lines):
                if 'timestamp' in line.lower():
                    data_start = i
                    break
        
        # If still no header row found, assume traditional CSV
        if data_start is None:
            df = pd.read_csv(io.StringIO(file_content))
            return df, {}, None
        
        # Extract metadata
        metadata = {}
        for i in range(data_start):
            parts = lines[i].split(',', 1)  # Split at first comma only
            if len(parts) >= 2:
                key = parts[0].strip()
                value = parts[1].strip()
                metadata[key] = value
        
        # Parse data section
        data_content = '\n'.join(lines[data_start:])
        df = pd.read_csv(io.StringIO(data_content))
        
        return df, metadata, None
        
    except Exception as e:
        # If our custom parsing fails, try standard CSV
        try:
            df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
            return df, {}, None
        except:
            return None, {}, f"Could not parse file: {str(e)}"
        
def parse_file(contents, filename):
    """Parse uploaded file contents into a pandas DataFrame"""
    if filename.lower().endswith('.csv'):
        return parse_custom_csv(contents)
    
    # For other file types, use the standard approach
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    
    try:
        if 'xls' in filename.lower():
            df = pd.read_excel(io.BytesIO(decoded))
            return df, {}, None
        else:
            return None, {}, "Unsupported file type. Please upload a CSV or Excel file."
    
    except Exception as e:
        return None, {}, f"Error processing file: {str(e)}"

def guess_time_column(df):
    """Try to automatically identify the time/date column"""
    # Check for columns with time-related names first
    time_keywords = ['time', 'date', 'timestamp', 'datetime']
    for col in df.columns:
        col_lower = str(col).lower()
        if any(keyword in col_lower for keyword in time_keywords):
            try:
                pd.to_datetime(df[col], errors='coerce')
                return col
            except:
                pass
    
    # Try all columns to see if they can be converted to datetime
    for col in df.columns:
        try:
            pd.to_datetime(df[col], errors='coerce')
            return col
        except:
            continue
    
    # Fallback to first column
    return df.columns[0] if len(df.columns) > 0 else None

def guess_temperature_column(df, time_col):
    """Try to automatically identify the temperature column"""
    # Check for columns with temperature-related names
    temp_keywords = ['temp', 'temperature', 'celsius', 'fahrenheit']
    for col in df.columns:
        col_lower = str(col).lower()
        if col != time_col and any(keyword in col_lower for keyword in temp_keywords):
            if pd.api.types.is_numeric_dtype(df[col]) or pd.to_numeric(df[col], errors='coerce').notna().all():
                return col
    
    # Try to find any numeric column that's not the time column
    for col in df.columns:
        if col != time_col:
            try:
                if pd.api.types.is_numeric_dtype(df[col]) or pd.to_numeric(df[col], errors='coerce').notna().all():
                    return col
            except:
                continue
    
    # Fallback to second column or first non-time column
    for col in df.columns:
        if col != time_col:
            return col
    
    return df.columns[0]  # Last resort

# Callback #1 - Process file upload
@app.callback(
    [Output('file-info', 'children'),
     Output('file-info', 'style'),
     Output('intermediate-value', 'data'),
     Output('metadata-value', 'data'),
     Output('column-info', 'data')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')]
)
def update_file_information(contents, filename):
    if contents is None:
        return (html.Div(), 
                {'display': 'none'}, 
                None, None, None)
    
    df, metadata, error = parse_file(contents, filename)
    if error:
        return (html.Div([
                    html.H4('Error', style={'color': 'red'}),
                    html.P(error)
                ]), 
                {'display': 'block', 'padding': '20px', 'backgroundColor': 'ghostwhite', 
                 'borderRadius': '5px', 'marginBottom': '20px'},
                None, None, None)
    
    # Try to guess time and temperature columns
    time_col = guess_time_column(df)
    temp_col = guess_temperature_column(df, time_col)
    
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
            json.dumps(metadata),
            json.dumps({'time_col': time_col, 'temp_col': temp_col, 'filename': filename}))

def aggregate_data(df, unit, time_col, temp_col):
    """
    Aggregates temperature data over time.

    Args:
        df (DataFrame): Original data
        unit (str): Aggregation unit ('5min', '1H', '1D')
        time_col (str): Time column name
        temp_col (str): Temperature column name

    Returns:
        DataFrame: Aggregated temperature data
    """
    df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
    df = df.dropna(subset=[time_col])
    df.set_index(time_col, inplace=True)

    df_agg = df[[temp_col]].resample(unit).mean().reset_index()

    return df_agg

def adjust_overlapping_peaks(peaks, df_agg, time_col, temp_col):
    """
    Adjust overlapping peak segments to remove overlap.
    """
    adjusted = []
    i = 0
    peaks = sorted(peaks, key=lambda x: x['Start'])

    # while i < len(peaks):
    #     current = peaks[i].copy()
    #     if i < len(peaks)-1:
    #         next = peaks[i+1]
    #         current_start = current['Start']
    #         current_end = current['End']
    #         next_start = next['Start']
    #         next_end = next['End']

    #         if (current['End'] >= next['End']):
    #             print("first condition", current_start)
    #             new_current = {}
    #             new_next = {}
    #             new_next_next = {}

    #             new_current['Start'] = current_start
    #             new_current['End'] = next_start - pd.Timedelta(minutes=2, seconds=30)
    #             new_next['Start'] = next_start + pd.Timedelta(minutes=2, seconds=30)
    #             new_next['End'] = next_end - pd.Timedelta(minutes=2, seconds=30)
    #             new_next_next['Start'] = next_end + pd.Timedelta(minutes=2, seconds=30)
    #             new_next_next['End'] = current_end

    #             new_current['Duration (Min)'] = (new_current['End'] - new_current['Start']).total_seconds() / 60
    #             new_next['Duration (Min)'] = (new_next['End'] - new_next['Start']).total_seconds() / 60
    #             new_next_next['Duration (Min)'] = (new_next_next['End'] - new_next_next['Start']).total_seconds() / 60

    #             current_mask = (df_agg[time_col] >= new_current['Start']) & (df_agg[time_col] <= new_current['End'])
    #             next_mask = (df_agg[time_col] >= new_next['Start']) & (df_agg[time_col] <= new_next['End'])
    #             next_next_mask = (df_agg[time_col] >= new_next_next['Start']) & (df_agg[time_col] <= new_next_next['End'])
                
    #             current_segment = df_agg.loc[current_mask]
    #             next_segment = df_agg.loc[next_mask]
    #             next_next_segment = df_agg.loc[next_next_mask]
                
    #             new_current['Peak Temperature (°C)'] = current_segment[temp_col].max()
    #             new_next['Peak Temperature (°C)'] = next_segment[temp_col].max()
    #             new_next_next['Peak Temperature (°C)'] = next_next_segment[temp_col].max()

    #             adjusted.append(new_current) if new_current['Duration (Min)'] > 0 else None
    #             adjusted.append(new_next) if new_next['Duration (Min)'] > 0 else None
    #             adjusted.append(new_next_next) if new_next_next['Duration (Min)'] > 0 else None
    #             i += 1 # Skip the "next"
    #         elif (current['End'] == next['Start']):
    #             print("second condition", current_start)
    #             current['End'] -= pd.Timedelta(minutes=2, seconds=30)
    #             adjusted.append(current)
    #         else:
    #             if adjusted[-1] != current:
    #                 adjusted.append(current)
    #     else:
    #         if adjusted[-1] != current:
    #             adjusted.append(current)
    #     i += 1

    return adjusted

def detect_incomplete_peak_after_last_peak(df_peaks, time_col, temp_col, last_offset_idx,
                                           window_points=3, min_consistency=0.8):
    # Return None if there isn't enough data after last peak
    if last_offset_idx >= len(df_peaks) - window_points: return None

    baseline_temp = df_peaks[temp_col].iloc[last_offset_idx+1]
    post_peak_segment = df_peaks.iloc[last_offset_idx+1:]

    for i in range(len(post_peak_segment) - window_points+1):
        window = post_peak_segment[temp_col].iloc[i:i+window_points]

        elevated = abs((window - baseline_temp) / baseline_temp) > 0.05
        consistency = elevated.sum() / window_points

        if consistency >= min_consistency:
            start_idx = post_peak_segment.index[i]-1
            sustained_segment = df_peaks.loc[start_idx:]

            start_ts = df_peaks.loc[start_idx, time_col]
            end_ts = sustained_segment[time_col].iloc[-1]
            duration = (end_ts - start_ts).total_seconds() / 60
            max_temp = sustained_segment[temp_col].max()

            return {
                "Start": start_ts.strftime('%Y-%m-%d %H:%M:%S'),
                "End": end_ts.strftime('%Y-%m-%d %H:%M:%S'),
                "Duration (Min)": duration,
                "Peak Temperature (°C)": max_temp
            }
    return None

def prepare_gantt(onset_times, offset_times):
    split_rows = []

    for i in range(len(onset_times)):
        start = pd.to_datetime(onset_times[i])
        end = pd.to_datetime(offset_times[i])
        
        current = start
        while current.date() <= end.date():
            this_date = current.date()

            if this_date == start.date() and this_date == end.date():
                # Same day: normal case
                start_hr = start.hour + start.minute / 60
                end_hr = end.hour + end.minute / 60
            elif this_date == start.date():
                # First day of a multi-day span
                start_hr = start.hour + start.minute / 60
                end_hr = 24.0
            elif this_date == end.date():
                # Final day of a multi-day span
                start_hr = 0.0
                end_hr = end.hour + end.minute / 60
            else:
                # Middle day
                start_hr = 0.0
                end_hr = 24.0
            
            split_rows.append({
                'Date': str(this_date),
                'StartHour': start_hr,
                'EndHour': end_hr,
                'Start': onset_times[i],
                'End': offset_times[i]
            })

            current += pd.Timedelta(days=1)
    return pd.DataFrame(split_rows)

def prepare_occurance_summary(onset_times, offset_times):
    onset_series = pd.to_datetime(onset_times)
    offset_series = pd.to_datetime(offset_times)

    summary_rows = []

    for start, end in zip(onset_series, offset_series):
        current = start
        while current.date() <= end.date():
            date = current.date()

            if date == start.date() and date == end.date():
                dur = (end - start).total_seconds() / 60.0
            elif date == start.date():
                dur = ((pd.Timestamp.combine(date + pd.Timedelta(days=1), pd.Timestamp.min.time()) - start).total_seconds()) / 60.0
            elif date == end.date():
                dur = ((end - pd.Timestamp.combine(date, pd.Timestamp.min.time())).total_seconds()) / 60.0

            else:
                dur = 1440.0  # full day = 24h = 1440 minutes

            summary_rows.append({'Date': date, 'DurationMin': dur})
            current += pd.Timedelta(days=1)

    summary_df = pd.DataFrame(summary_rows)

    return summary_df.groupby('Date').agg(
                TotalDurationMin=('DurationMin', 'sum'),
                EventCount=('DurationMin', 'count')
            ).reset_index()

# Callback #2- Generate basic information after file upload
@app.callback(
    [Output('output-data-upload', 'children'),
    Output('aggregation-control', 'style'),
    Output('aggregation-graph-container', 'style')],
    [Input('intermediate-value', 'data'),
     Input('column-info', 'data')],
    [State('metadata-value', 'data')]
)
def update_dashboard(json_data, column_info, json_metadata):
    if not json_data or not column_info:
        return html.H6("Upload the file to generate the analysis view.", style={"textAlign":"center"}), {'display': 'none'}, {'display': 'none'}

    df = pd.read_json(json_data, orient='split')
    column_data = json.loads(column_info)
    time_col = column_data.get('time_col')
    temp_col = column_data.get('temp_col')

    if not time_col or not temp_col:
        return html.Div([
            html.H4('Error', style={'color': 'red'}),
            html.P("Could not identify time and temperature columns.")
        ]), {'display': 'none'}, {'display': 'none'}, {'display': 'none'}

    metadata = {}
    if json_metadata:
        try:
            metadata = json.loads(json_metadata)
        except:
            pass
    try:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
        df[temp_col] = pd.to_numeric(df[temp_col], errors='coerce')
        df = df.dropna(subset=[time_col, temp_col])
    except Exception as e:
        return html.Div([
            html.H4('Error', style={'color': 'red'}),
            html.P(str(e))
        ]), {'display': 'none'}, {'display': 'none'}
    
    # Peak detection
    peaks_table = None
    peak_fig = None
    try:
        df_agg = aggregate_data(df.copy(), '5min', time_col, temp_col)

        # Initial Peak Detection
        peak_indices, _ = find_peaks(
            df_agg[temp_col],
            distance=1,
            prominence=0.7)
        
        # Measure each peak's duration
        results_half = peak_widths(df_agg[temp_col], peak_indices, rel_height=0.5)
        left_idx = np.maximum(0, np.round(results_half[2]).astype(int) - 1)
        right_idx = np.round(results_half[3]).astype(int)

        # print("original peak count: ", len(peak_indices))
        # print(df_agg[time_col].iloc[peak_indices].to_list())

        # Validate each peak using the offset temperature as baseline
        validated_peaks = []
        for i, peak_idx in enumerate(peak_indices):
            peak_temp = df_agg[temp_col].iloc[peak_idx]
            onset_idx = max(0, left_idx[i])
            offset_idx = min(len(df_agg)-1, right_idx[i])

            baseline_temp = df_agg[temp_col].iloc[offset_idx+1]
            duration_min = (df_agg[time_col].iloc[offset_idx] - df_agg[time_col].iloc[onset_idx]).total_seconds() / 60

            # if abs((peak_temp-baseline_temp)/baseline_temp) >= 0.05:
            validated_peaks.append({
                "Start": df_agg[time_col].iloc[onset_idx],
                "End": df_agg[time_col].iloc[offset_idx],
                "Duration (Min)": duration_min,
                "Peak Temperature (°C)": peak_temp
            })

        # print("validated peak count: ", len(validated_peaks))
        # print(validated_peaks)
        validated_peaks = sorted(validated_peaks, key=lambda x: x['Start'])
        final_peaks = validated_peaks
        # final_peaks = adjust_overlapping_peaks(validated_peaks, df_agg, time_col, temp_col)

        # print("final peak count: ", len(final_peaks))
        # print(final_peaks)
        for peak in final_peaks:
            peak['Start'] = peak['Start'].strftime('%Y-%m-%d %H:%M:%S')
            peak['End'] = peak['End'].strftime('%Y-%m-%d %H:%M:%S')

        # Find trailing peak near the end of data collection
        last_offset_idx = right_idx[-1]
        
        sustained_event = detect_incomplete_peak_after_last_peak(
            df_peaks=df_agg,
            time_col=time_col,
            temp_col=temp_col,
            last_offset_idx=last_offset_idx,
            window_points=3,
            min_consistency=0.7
        )
        
        # Append if there is any sustained_event near the end
        if sustained_event:
            final_peaks.append(sustained_event)

        onset_times = [peak["Start"] for peak in final_peaks]
        offset_times = [peak["End"] for peak in final_peaks]

        peaks_df = pd.DataFrame(final_peaks)
        peaks_table = html.Div([
            DataTable(
                data=peaks_df.to_dict('records'),
                columns=[{"name": i, "id": i} for i in peaks_df.columns],
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'left', 'padding': '5px'},
                style_header={'backgroundColor': '#f4f4f4', 'fontWeight': 'bold'}
            )
        ])

        peak_fig = px.line(
            df_agg,
            x=time_col,
            y=temp_col,
            labels={time_col: 'Time', temp_col: 'Temperature (°C)'}
        )

        # Highlight the detected peaks
        for i in range(len(final_peaks)):
            peak_fig.add_shape(
                type="rect",
                x0=final_peaks[i]["Start"],
                x1=final_peaks[i]["End"],
                y0=0,
                y1=1,
                xref='x',
                yref='paper',
                fillcolor="LightGreen",
                opacity=0.3,
                layer="below",
                line_width=0,
            )

        peak_fig.update_layout(
            xaxis_title='Time',
            yaxis_title='Temperature (°C)',
            hovermode='closest',
            hoverlabel=dict(
                font=dict(color='white')
            ),
            plot_bgcolor='rgba(240, 240, 240, 0.5)',
            paper_bgcolor='rgba(0, 0, 0, 0)',
            font=dict(color='#2c3e50'),
            margin=dict(t=10)
        )

        # Gantt Chart
        gantt_df = prepare_gantt(onset_times, offset_times)
        gantt_fig = go.Figure()

        for idx, row in gantt_df.iterrows():
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
        daily_summary = prepare_occurance_summary(onset_times, offset_times)
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

        avg_temp = np.mean([peak['Peak Temperature (°C)'] for peak in final_peaks])

        non_peak_mask = np.ones(len(df_agg), dtype=bool)  # Start with all True (non-peak)

        for peak in final_peaks:
            start = pd.to_datetime(peak['Start'])
            end = pd.to_datetime(peak['End'])
            mask = (df_agg[time_col] >= start) & (df_agg[time_col] <= end)
            non_peak_mask &= ~mask  # Exclude peak times

        # Apply the mask to get non-peak temperature readings
        non_peak_temps = df_agg.loc[non_peak_mask, temp_col]
        avg_non_peak_temp = non_peak_temps.mean()
        
        stats_info = html.Div([
            html.Div([html.Strong('Average Non-peak Temperature: '), html.Span(f"{avg_non_peak_temp:.2f}°C")]),
            html.Div([html.Strong('Average Peak Temperature: '), html.Span(f"{avg_temp:.2f}°C")]),
            html.Div([html.Strong('Total Duration Minutes: '), html.Span((f"{np.sum(daily_summary['TotalDurationMin']):.1f} Minutes"))]),
            html.Div([html.Strong('Average Total Duration Minutes Per Day: '), html.Span((f"{np.mean(daily_summary['TotalDurationMin']):.1f} Minutes"))])
        ], style={'marginTop':'10px', 'marginBottom':'10px'})

        return html.Div([
            html.Hr(style={'margin': '20px 0'}),
            html.H4('Occurance Detection', style={'marginTop': '30px'}),
            dcc.Graph(
                id='peak-graph',
                figure=peak_fig,
                config={'displayModeBar': True},
                style={'height': '450px'}
            ) if peak_fig else html.Div(),
            peaks_table,
            html.H4('Splint-Wearing Summary', style={'marginTop': '30px'}),
            stats_info,
            dcc.Graph(
                id='summary-chart',
                figure=summary_fig,
                config={'displayModeBar': True},
            ) if summary_fig else html.Div(),
            # stats_info,
            html.H4('Splint Wearing Periods by Hour of Day', style={'marginTop': '30px'}),
            dcc.Graph(
                id='gantt-chart',
                figure=gantt_fig,
                config={'displayModeBar': True},
            ) if gantt_fig else html.Div()
        ]), {'display': 'block'},{'display': 'block'}
    except Exception as e:
        return html.Div([
            html.H4("Peak Detection Failed", style={'color': 'red'}),
            html.P(str(e))
        ]),{'display': 'none'},{'display': 'none'}

# Callback #3 - Update aggregated graph based on user input
@app.callback(
    Output('temperature-graph', 'figure'),
    [Input('intermediate-value', 'data'),
     Input('column-info', 'data'),
     Input('aggregation-interval', 'value')]
)
def update_aggregated_graph(json_data, column_info, aggregation_interval):
    if not json_data or not column_info: return {}

    df = pd.read_json(json_data, orient='split')
    column_data = json.loads(column_info)
    time_col = column_data.get('time_col')
    temp_col = column_data.get('temp_col')

    if aggregation_interval == 'none':
        df_agg = df.copy()
    else:
        df_agg = aggregate_data(df.copy(), aggregation_interval, time_col, temp_col)

    fig = px.line(
        df_agg,
        x=time_col,
        y=temp_col,
        # title=f'<b>Time vs Temperature ({aggregation_interval}</b>)',
        labels={time_col: 'Time', temp_col: 'Temperature (°C)'}
    )

    fig.update_layout(
        xaxis_title='Time',
        yaxis_title='Temperature (°C)',
        hovermode='closest',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        paper_bgcolor='rgba(0, 0, 0, 0)',
        font=dict(color='#2c3e50'),
        margin=dict(t=10)
    )

    return fig