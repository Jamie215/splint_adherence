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

def _infer_interval_minutes(time_series, default=5.0):
    """
    Infer the sampling interval (in minutes) from the timestamps.

    The device's wakeup_interval is configurable, so detection windows must be
    derived from the actual cadence rather than assuming a fixed 5-minute one.
    Falls back to `default` if it can't be determined.
    """
    if len(time_series) < 2:
        return default
    diffs = pd.to_datetime(time_series).diff().dt.total_seconds().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return default
    return diffs.median() / 60.0

def dedrift_proximity(prox_series, interval_min, k=4.0, min_excursion=5.0):
    """
    Return a per-sample boolean `covered` mask that is invariant to proximity
    baseline drift.

    The APDS9960 proximity reading carries a slowly-varying DC pedestal that
    climbs over a deployment (optical-front-end / LED drift as the battery
    discharges). A raw ``prox == 0`` test for "sensor covered" therefore decays
    over time -- the quiescent floor walks up from 0 into the tens, so late in a
    record nothing is ever exactly 0 even while worn.

    Instead of the raw value we track the quiescent floor with a ~1-day rolling
    low percentile and work from the residual (raw minus floor). Because the
    drift is additive, subtracting the floor makes an excursion of a given
    physical size read the same regardless of when it occurred -- unlike a
    percentage/ratio, which explodes when the floor is near zero (the entire
    early "true-worn" period) and shrinks an identical event as the floor grows.

    A sample is "covered" (at the quiescent floor => worn) when its residual sits
    below a robust threshold: ``max(min_excursion, k * MAD)``. The MAD is a
    robust noise scale of the residual, and ``min_excursion`` floors it so
    quantisation noise cannot trigger when the MAD collapses toward zero.

    Returns a numpy bool array aligned to `prox_series` positionally.
    """
    prox = pd.to_numeric(prox_series, errors='coerce').reset_index(drop=True)
    prox = prox.ffill().bfill().fillna(0.0)

    # ~1-day window for the quiescent floor; derived from the actual cadence so
    # it is independent of the configured wakeup interval.
    floor_window = max(1, round(1440 / interval_min))
    floor = prox.rolling(floor_window, min_periods=1, center=True).quantile(0.10)
    floor = floor.bfill().ffill()

    resid = (prox - floor).clip(lower=0)

    # Robust noise scale (MAD). The record is mostly quiescent, so the median of
    # |resid - median| reflects the worn-state noise rather than the excursions.
    med = resid.median()
    mad = 1.4826 * (resid - med).abs().median()
    threshold = max(min_excursion, k * mad)

    return (resid <= threshold).to_numpy()


def detect_onsets_offsets(time_series, temp_series, prox_series):
    """
    Advanced detection using a ~15-minute trend filter to prevent false triggers
    on cooling slopes, and relative peak drops for faster offset detection.

    Window sizes are expressed in wall-clock time and converted to a number of
    samples using the inferred sampling interval, so the detector behaves the
    same regardless of the configured wakeup interval.

    Proximity is consumed through `dedrift_proximity` rather than as a raw value,
    so the "sensor covered" gate stays valid as the proximity baseline drifts
    over a long deployment.
    """
    # 1. Pre-processing
    interval_min = _infer_interval_minutes(time_series)
    # ~2-hour window for a stable ambient floor.
    baseline_window = max(1, round(120 / interval_min))
    # ~15-minute trend lookback.
    trend_lag = max(1, round(15 / interval_min))

    baseline = temp_series.rolling(window=baseline_window, min_periods=1, center=True).min()
    delta = temp_series - baseline
    gradient = temp_series.diff()

    # ~15-minute trend: temperature difference compared to `trend_lag` samples ago
    trend = temp_series - temp_series.shift(trend_lag)

    # Drift-invariant "sensor covered" state (replaces the raw prox == 0 test).
    prox_covered = dedrift_proximity(prox_series, interval_min)

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

    for i in range(trend_lag, len(delta)):
        if not in_event:
            # ONSET CONDITIONS:
            # 1. Sensor is covered (proximity at its drift-tracked quiescent floor)
            # 2. Trend is POSITIVE (removes noise on cooling slopes)
            # 3. Thermal Spike (Grad >= 0.8) OR Significant Heat (Delta >= 3.0)
            is_trending_up = trend[i] > 0

            if prox_covered[i] and is_trending_up:
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
            # - Proximity is physically lost (sensor no longer covered)
            # - OR it's cooling fast AND (is back near baseline OR has dropped significantly from peak)
            if (not prox_covered[i]) or (is_cooling_fast and (delta[i] < OFFSET_DELTA or is_below_peak)):
                # If triggered by cooling, the actual removal happened 1 sample (5m) prior
                offset_idx = i - 1 if prox_covered[i] else i
                
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

    # Iterate by value rather than positional/label index: the incoming Series
    # may carry a non-sequential index (e.g. after a sort), so onset_times[i]
    # would be unreliable.
    for onset, offset in zip(onset_times, offset_times):
        start = pd.to_datetime(onset)
        end = pd.to_datetime(offset)

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
                'Start': onset,
                'End': offset
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