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
            if ('Temperature' in line):
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

def detect_onsets_offsets(time_series, temp_series, prox_series):
    """
    Advanced detection using a 15-minute trend filter to prevent false triggers 
    on cooling slopes, and relative peak drops for faster offset detection.
    """
    # 1. Pre-processing
    # 12-hour window for stable ambient floor (288 samples @ 5min/sample)
    baseline = temp_series.rolling(window=24, min_periods=1, center=True).min()
    delta = temp_series - baseline
    gradient = temp_series.diff()
    
    # 15-minute Trend: Temperature difference compared to 3 samples ago
    trend_15m = temp_series - temp_series.shift(3)

    # Thresholds
    ONSET_DELTA = 3.0      # Minimum heat above ambient to consider human
    ONSET_GRAD = 0.8       # Minimum jump to trigger onset
    OFFSET_GRAD = -0.4     # Detection of the 'cooling cliff'
    OFFSET_DELTA = 1.5     # Safety floor for offset
    PEAK_DROP_FACTOR = 0.8  # Trigger offset if temp drops to 80% of peak delta

    events = []
    in_event = False
    onset_idx = None
    current_max_delta = 0

    for i in range(3, len(delta)):
        if not in_event:
            # ONSET CONDITIONS:
            # 1. Proximity is 0 (something is covering the sensor)
            # 2. Trend is POSITIVE (removes noise on cooling slopes)
            # 3. Thermal Spike (Grad >= 0.8) OR Significant Heat (Delta >= 3.0)
            is_trending_up = trend_15m[i] > 0
            
            if prox_series[i] == 0 and is_trending_up:
                if gradient[i] >= ONSET_GRAD or delta[i] >= ONSET_DELTA:
                    in_event = True
                    onset_idx = i - 1
                    current_max_delta = delta[i]
        else:
            # Track peak delta to enable relative offset detection
            if delta[i] > current_max_delta:
                current_max_delta = delta[i]
            
            # TERMINATION CONDITIONS:
            is_cooling_fast = gradient[i] <= OFFSET_GRAD
            is_below_peak = delta[i] < (current_max_delta * PEAK_DROP_FACTOR)
            
            # End session if:
            # - Proximity is physically lost (>0)
            # - OR it's cooling fast AND (is back near baseline OR has dropped significantly from peak)
            if prox_series[i] > 0 or (is_cooling_fast and (delta[i] < OFFSET_DELTA or is_below_peak)):
                # If triggered by cooling, the actual removal happened 1 sample (5m) prior
                offset_idx = i - 1 if (prox_series[i] == 0) else i
                
                # Minimum session length check (10 mins)
                if (offset_idx - onset_idx) >= 2:
                    events.append((onset_idx, offset_idx))
                
                in_event = False
                current_max_delta = 0

    # DataFrame preparation
    out = pd.DataFrame(events, columns=['StartIdx', 'EndIdx'])
    if not out.empty:
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