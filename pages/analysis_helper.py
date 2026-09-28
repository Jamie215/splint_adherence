import base64
import io
import pandas as pd
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from timezone_config import DISPLAY_TZ

def parse_file(contents):
    """
    Parser specifically designed for files with metadata section followed by data table.
    """
    # Decode the file contents
    _, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    
    try:
        return parse_text(decoded.decode('utf-8'))
    except Exception as e:
        return None, {}, f"Could not parse file: {str(e)}"

def parse_text(file_content):
    """
    Parse CSV text (metadata lines, then the data table) into (df, metadata, error).
    """
    try:
        lines = file_content.strip().split('\n')
        
        # Find where the data table starts (line with headers)
        data_start = None
        for i, line in enumerate(lines):
            if ('Temperature' in line):
                data_start = i
                break
            
        if data_start is None:
            return None, {}, ("Could not parse file: no data header row "
                              "(e.g. 'Timestamp,Temperature,ProximityVal') was found.")

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

# The device computes each row's timestamp as (initial timestamp + elapsed
# seconds) in 32-bit arithmetic. If its config was lost, the initial timestamp
# is either a blank flash word (0xFFFFFFFF -> 2106-02-07 06:28:15, older
# firmware) or reported as UNKNOWN (current firmware, which then sends a start
# of 0). In both cases the elapsed seconds survive and the real timestamps can
# be rebuilt from a start time supplied by the user.
_BLANK_FLASH_WORD = 0xFFFFFFFF
_TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
_EPOCH = pd.Timestamp('1970-01-01')


def _lost_start_epoch(metadata):
    """
    Return the epoch the device used in place of the lost start time
    (0xFFFFFFFF or 0), or None if the file's start time looks valid.
    """
    initial = str((metadata or {}).get('Initial Timestamp', '')).strip()
    if initial.upper() == 'UNKNOWN':
        return 0
    if initial.isdigit():
        epoch = int(initial)
    else:
        try:
            epoch = int((pd.Timestamp(initial) - _EPOCH).total_seconds())
        except (ValueError, TypeError):
            return None
    return epoch if epoch == _BLANK_FLASH_WORD else None


def needs_timestamp_recovery(metadata):
    """True if the file's start time was lost on the device."""
    return _lost_start_epoch(metadata) is not None


def recover_timestamps(df, metadata, start_time):
    """
    Rebuild real timestamps for a file whose start time was lost on the device.

    Each row's elapsed time since logging started is recovered by undoing the
    device's 32-bit (placeholder start + elapsed) addition, then added to
    `start_time`, the actual time the device was initialized to start logging.

    Returns (df, metadata) copies with corrected timestamps and header.
    """
    placeholder = _lost_start_epoch(metadata)
    if placeholder is None:
        return df, metadata

    start = pd.Timestamp(start_time)
    row_epochs = ((pd.to_datetime(df['Timestamp']) - _EPOCH)
                  .dt.total_seconds().round().astype('int64'))
    elapsed = (row_epochs - placeholder) % (1 << 32)

    df = df.copy()
    df['Timestamp'] = (start + pd.to_timedelta(elapsed, unit='s')).dt.strftime(_TIMESTAMP_FORMAT)

    metadata = dict(metadata)
    metadata['Initial Timestamp'] = start.strftime(_TIMESTAMP_FORMAT)
    # The configured interval was lost too; report the one the data shows.
    if len(elapsed) > 1:
        metadata['Wake-up Interval (Seconds)'] = str(int(elapsed.diff().median()))
    if metadata.get('Personal ID', 'UNKNOWN') == 'UNKNOWN':
        metadata.pop('Personal ID', None)
    metadata['Timestamp Recovery'] = 'Start time entered manually'
    return df, metadata


def to_csv_with_metadata(df, metadata):
    """Serialize back to the device download format (metadata lines, then data)."""
    lines = [f"{key},{value}" for key, value in (metadata or {}).items()]
    return '\r\n'.join(lines) + '\r\n' + df.to_csv(index=False, lineterminator='\r\n')

def to_display_tz(time_series):
    """
    Convert a column of timestamps to tz-aware Eastern time (see
    timezone_config.DISPLAY_TZ).

    Current downloads carry an explicit UTC offset (``...-05:00``), so they are
    converted exactly. Older downloads have naive timestamps that were written
    in UTC, so naive values are interpreted as UTC -- which puts legacy files on
    the same Eastern clock as new ones.
    """
    return pd.to_datetime(time_series, utc=True).dt.tz_convert(DISPLAY_TZ)

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
                # If triggered by cooling, the actual removal happened 1 sample prior
                offset_idx = i - 1 if prox_covered[i] else i
                
                # Minimum session length check (2 samples, i.e. 10 min at 5-min sampling)
                if (offset_idx - onset_idx) >= 2:
                    events.append((onset_idx, offset_idx))
                
                in_event = False
                current_max_delta = 0

    # DataFrame preparation
    out = pd.DataFrame(events, columns=['StartIdx', 'EndIdx'])
    if not out.empty:
        # reset_index (not .values) keeps any timezone on the timestamps, so
        # durations stay correct across DST changes.
        out['Onset'] = time_series.iloc[out['StartIdx']].reset_index(drop=True)
        out['Offset'] = time_series.iloc[out['EndIdx']].reset_index(drop=True)
        out['DurationMin'] = (out['Offset'] - out['Onset']).dt.total_seconds()/60
    
    return baseline, delta, out

def extract_peaks(time_series, temp_series, events_df):
    """
    Returns a DataFrame composed of EventID, PeakTemp, PeakTime
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

def _split_by_day(onset_times, offset_times):
    """
    Yield (date, segment_start, segment_end, onset, offset) for each calendar
    day an event touches, clipping the event to that day. Works with naive or
    tz-aware timestamps: days are taken in the timestamps' own zone, and each
    midnight is localized separately so DST days keep their true 23/25-hour
    length.
    """
    for onset, offset in zip(onset_times, offset_times):
        start = pd.Timestamp(onset)
        end = pd.Timestamp(offset)
        day = start.date()
        while day <= end.date():
            day_start = pd.Timestamp(day).tz_localize(start.tz)
            day_end = pd.Timestamp(day + pd.Timedelta(days=1)).tz_localize(start.tz)
            yield day, max(start, day_start), min(end, day_end), onset, offset
            day += pd.Timedelta(days=1)

def _hour_of_day(ts, day):
    """Fractional hour of day of `ts` on `day`; 24.0 if `ts` is the next midnight."""
    if ts.date() != day:
        return 24.0
    return ts.hour + ts.minute / 60

def prepare_gantt(onset_times, offset_times):
    """
    Split each wear event into one row per calendar day with its start/end hour
    of day, for the hour-of-day timeline chart.
    """
    # Iterate by value rather than positional/label index: the incoming Series
    # may carry a non-sequential index (e.g. after a sort).
    rows = [{
        'Date': str(day),
        'StartHour': _hour_of_day(seg_start, day),
        'EndHour': _hour_of_day(seg_end, day),
        'Start': onset,
        'End': offset,
    } for day, seg_start, seg_end, onset, offset in _split_by_day(onset_times, offset_times)]
    return pd.DataFrame(rows, columns=['Date', 'StartHour', 'EndHour', 'Start', 'End'])

def prepare_occurance_summary(onset_times, offset_times):
    """
    Total wear minutes and event count per calendar day. Events spanning
    midnight are split so each day gets only its own share.
    """
    rows = [{
        'Date': day,
        'DurationMin': (seg_end - seg_start).total_seconds() / 60.0,
    } for day, seg_start, seg_end, _, _ in _split_by_day(onset_times, offset_times)]
    summary_df = pd.DataFrame(rows, columns=['Date', 'DurationMin'])

    return summary_df.groupby('Date').agg(
                TotalDurationMin=('DurationMin', 'sum'),
                EventCount=('DurationMin', 'count')
            ).reset_index()
