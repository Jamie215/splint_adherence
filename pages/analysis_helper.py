import base64
import io
import pandas as pd
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

def parse_file(contents):
    """
    Parser specifically designed for files with metadata section followed by data table.
    """
    # Decode the file contents
    _, content_string = contents.split(',')
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
            if ('timestamp' in line_lower and 'temperature' in line_lower):
                data_start = i
                break
        
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

def baseline_asls(y, lam=1e6, p=0.4, niter=20):
    """
    Asymmetric least squares smoothing for baseline estimation
        y: input signal
        lam: smoothing penalty parameter
        p: noise level
        niter: number of iterations

    Returns the estimated baseline
    """
    n = len(y)
    D = sparse.diags([1, -2, 1], [0, 1, 2], shape=(n-2, n))
    w = np.ones(n)
    for _ in range(niter):
        W = sparse.spdiags(w, 0, n, n)
        Z = W + lam * (D.T @ D)
        z = spsolve(Z, w * y)
        w = p * (y > z) + (1-p) * (y < z)

    return z

def detect_onsets_offsets(time_series, temp_series, min_samples=2):
    """
    Find onsets and offsets of peaks by tracking the baseline and using dual threshold
    """
    # Compute baseline
    baseline = baseline_asls(temp_series)
    delta = temp_series - baseline

    events = []
    in_event = False
    onset = None
    consec = 0
    threshold = 3

    for idx, dT in enumerate(delta):
        if not in_event:
            # Register as onset if deltaT is higher than high_gate
            if dT >= threshold:
                onset = max(0, idx-1)
                in_event = True

        else:
            # Register as offset if already in event and deltaT is lower than low_gate
            if dT <= threshold:
                consec += 1
                threshold = dT # dT decreases as the offset occurs
                # Register offset if the decrease in dT was not a noise
                if consec >= min_samples:
                    # Temperature cooling takes longer; go back 5 data points to find when the peak happened
                    prev_idx = max(0, idx-5)
                    if prev_idx > 0:
                        max_idx = np.argmax(delta[prev_idx:idx]) + prev_idx
                        if (delta[max_idx] - delta[max_idx+1]) > 1:
                            offset = min(max_idx+1, idx)
                        else:
                            offset = min(max_idx+2, idx)
                    else:
                        offset = idx # Fall back value
                    if offset > onset:
                        events.append((onset, offset))
                    
                    in_event = False
                    consec = 0
                    threshold = 3
                # For rapid cooling, register offset immediately
                elif idx > 0 and dT-delta[idx-1] > threshold:
                    offset = idx
                    if offset > onset:
                        events.append((onset, offset))
                    in_event = False
                    consec = 0
                    threshold = 3
                else:
                    consec = 0

    # Handle open event at the end of the record
    if in_event:
        events.append((onset, len(temp_series)-1))

    out = pd.DataFrame(events, columns=['StartIdx', 'EndIdx'])
    out['Onset'] = time_series.iloc[out['StartIdx']].values
    out['Offset'] = time_series.iloc[out['EndIdx']].values
    out['DurationMin'] = (out['Offset'] - out['Onset']).dt.total_seconds()/60
    return baseline, delta, out
    
def extract_peaks(time_series, temp_series, events_df):
    """
    Returns a DaraFrame composed of PeakTime, PeakTemp
    """
    rows = []
    for _, event in events_df.iterrows():
        seg = temp_series.iloc[event.StartIdx:(event.EndIdx+1)]
        rel_idx = int(np.argmax(seg))
        rows.append({
            "EventID": event.EventID,
            "PeakTemp": seg.iloc[rel_idx],
            "PeakTime": time_series.iloc[event.StartIdx + rel_idx]
        })

    return pd.DataFrame(rows)

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