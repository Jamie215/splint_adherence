import base64
import io
import pandas as pd
import json

from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.express as px

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
        'padding': '20px', 
        'backgroundColor': 'ghostwhite', 
        'borderRadius': '5px', 
        'marginBottom': '20px',
        'display': 'none'
    }),
    
    # Add hidden storage components
    dcc.Store(id='intermediate-value'),
    dcc.Store(id='metadata-value'),
    dcc.Store(id='column-info'),
    
    # Statistics and Graph Container
    html.Div(id='output-data-upload', style={
        'padding': '20px',
        'backgroundColor': 'ghostwhite', 
        'borderRadius': '5px'
    }),

], style={
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

# First callback - Process file upload
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

# Second callback - Generate dashboard
@app.callback(
    Output('output-data-upload', 'children'),
    [Input('intermediate-value', 'data'),
     Input('column-info', 'data')],
    [State('metadata-value', 'data')]
)
def update_dashboard(json_data, column_info, json_metadata):
    # Don't proceed if we don't have the necessary data
    if not json_data or not column_info:
        return html.Div("Upload a file to generate the dashboard.")
    
    # Parse the stored JSON data
    df = pd.read_json(json_data, orient='split')
    column_data = json.loads(column_info)
    time_col = column_data.get('time_col')
    temp_col = column_data.get('temp_col')
    
    if not time_col or not temp_col:
        return html.Div([
            html.H4('Error', style={'color': 'red'}),
            html.P("Could not identify time and temperature columns.")
        ])

    # Parse metadata if available
    metadata = {}
    if json_metadata:
        try:
            metadata = json.loads(json_metadata)
        except:
            pass
    
    # Convert time column to datetime
    try:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
                
        # Check if any dates failed to parse
        if df[time_col].isna().any():
            bad_count = df[time_col].isna().sum()
            bad_percent = (bad_count / len(df)) * 100
            
            if bad_percent > 5:  # If more than 5% of dates failed
                return html.Div([
                    html.H4('Warning', style={'color': 'orange'}),
                    html.P(f"Could not parse {bad_count} values ({bad_percent:.1f}%) in the time column."),
                    html.P("Please check your data format.")
                ])
            else:
                # Small percentage failed, we can continue but drop those rows
                df = df.dropna(subset=[time_col])
        
    except Exception as e:
        return html.Div([
            html.H4('Error', style={'color': 'red'}),
            html.P(f"Could not convert {time_col} to datetime format: {str(e)}")
        ])
    
    # Make sure temp column is numeric
    try:
        df[temp_col] = pd.to_numeric(df[temp_col], errors='coerce')
        
        # Check if any values failed to convert
        if df[temp_col].isna().any():
            bad_count = df[temp_col].isna().sum()
            
            if bad_count > 0:
                df = df.dropna(subset=[temp_col])
                if len(df) == 0:
                    return html.Div([
                        html.H4('Error', style={'color': 'red'}),
                        html.P(f"No valid numeric values in the temperature column after cleaning.")
                    ])
    except Exception as e:
        return html.Div([
            html.H4('Error', style={'color': 'red'}),
            html.P(f"Could not convert {temp_col} to numeric format: {str(e)}")
        ])
    
    # Sort dataframe by time
    df = df.sort_values(by=time_col)
    
    # Calculate statistics
    avg_temp = df[temp_col].mean()
    min_temp = df[temp_col].min()
    max_temp = df[temp_col].max()
    
    stats_info = html.Div([
        html.H4('Temperature Statistics', style={'color': '#2c3e50', 'marginBottom': '15px'}),
        html.Div([
            html.Strong('Average Temperature: '), 
            html.Span(f"{avg_temp:.2f}°C")
        ], style={'marginBottom': '5px'}),
        html.Div([
            html.Strong('Minimum Temperature: '), 
            html.Span(f"{min_temp:.2f}°C")
        ], style={'marginBottom': '5px'}),
        html.Div([
            html.Strong('Maximum Temperature: '), 
            html.Span(f"{max_temp:.2f}°C")
        ], style={'marginBottom': '5px'}),
    ])

    # Create a violin plot that shows distribution with points
    violin_fig = px.violin(
        df,
        y=temp_col,
        box=True,           # Add box plot inside violin
        points='all',       # Show all points
        title="Temperature Distribution with Data Points",
        labels={temp_col: 'Temperature (°C)'},
    )

    # Update layout
    violin_fig.update_layout(
        showlegend=False,
        xaxis_title='',
        yaxis_title='Temperature (°C)',
        hovermode='closest',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        paper_bgcolor='rgba(0, 0, 0, 0)',
        font=dict(color='#2c3e50'),
        height=400,
        margin=dict(l=40, r=40, t=40, b=30)
    )

    # Add horizontal lines for min, max, and average
    violin_fig.add_shape(
        type="line",
        x0=-0.5,
        y0=avg_temp,
        x1=0.5,
        y1=avg_temp,
        line=dict(
            color="green",
            width=2,
            dash="dash",
        )
    )

    violin_fig.add_annotation(
        x=0.5,
        y=avg_temp,
        text=f"Avg: {avg_temp:.1f}°C",
        showarrow=False,
        xshift=50,
        font=dict(color="green")
    )
    
    # Create interactive time vs temperature graph
    fig = px.line(
        df, 
        x=time_col, 
        y=temp_col, 
        title='Temperature vs Time',
        labels={
            time_col: 'Time',
            temp_col: 'Temperature (°C)'
        }
    )
    
    fig.update_layout(
        xaxis_title='Time',
        yaxis_title='Temperature (°C)',
        hovermode='closest',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        paper_bgcolor='rgba(0, 0, 0, 0)',
        font=dict(color='#2c3e50')
    )
    
    # Add range selector and rangeslider to the graph
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="5m", step="minute", stepmode="backward"),
                dict(count=6, label="1h", step="hour", stepmode="backward"),
                dict(count=1, label="1d", step="day", stepmode="backward"),
                dict(count=7, label="1w", step="day", stepmode="backward"),
                dict(step="all")
            ]),
            bgcolor='#E2E2E2',
            activecolor='#3498db'
        )
    )
    
    # Get filename for download
    filename = "temperature_plot"
    if metadata and 'Personal ID' in metadata:
        filename = f"{metadata['Personal ID']}_temperature_plot"
    
    # Return the complete dashboard content
    return html.Div([
        stats_info,
        html.Hr(style={'margin': '20px 0'}),
        html.H4('Temperature Distribution with Data Points', style={'color': '#2c3e50', 'marginBottom': '15px'}),
        dcc.Graph(
            id='temperature-violin',
            figure=violin_fig,
            config={'displayModeBar': False},
            style={'height': '400px'}
        ),
        html.H4('Interactive Plot', style={'color': '#2c3e50', 'marginBottom': '15px'}),
        dcc.Graph(
            id='temperature-graph',
            figure=fig,
            config={
                'displayModeBar': True,
                'scrollZoom': True,
                'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'eraseshape'],
                'toImageButtonOptions': {
                    'format': 'png',
                    'filename': filename,
                    'height': 500,
                    'width': 900,
                    'scale': 2
                }
            },
            style={'height': '500px'}
        )
    ])