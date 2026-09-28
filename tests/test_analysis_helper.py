"""Tests for the wear-detection and summary helpers (no hardware needed)."""
import base64

import numpy as np
import pandas as pd
import pytest

from pages import analysis_helper as ah

INTERVAL_MIN = 5


def _trace(n_samples=288 * 2, start="2026-01-05 00:00", events=((100, 160),),
           ambient=24.0, worn=32.0):
    """
    Synthetic 5-minute trace: flat ambient temperature with square-ish wear
    events (sharp rise, plateau, sharp fall). Proximity is 0 (covered) during
    wear and high (uncovered) otherwise.
    """
    ts = pd.Series(pd.date_range(start, periods=n_samples, freq=f"{INTERVAL_MIN}min"))
    temp = np.full(n_samples, ambient)
    prox = np.full(n_samples, 200.0)
    for on, off in events:
        temp[on:off] = worn
        prox[on:off] = 0.0
    return ts, pd.Series(temp), pd.Series(prox)


def _detect(ts, temp, prox):
    _, _, events = ah.detect_onsets_offsets(ts, temp, prox)
    return events


def test_detects_single_wear_event():
    ts, temp, prox = _trace(events=((100, 160),))
    events = _detect(ts, temp, prox)
    assert len(events) == 1
    ev = events.iloc[0]
    # Onset is stamped one sample before the rise; offset lands at the drop.
    assert abs(ev.StartIdx - 99) <= 1
    assert abs(ev.EndIdx - 160) <= 1
    assert ev.DurationMin == pytest.approx((ev.EndIdx - ev.StartIdx) * INTERVAL_MIN)


def test_detection_is_invariant_to_proximity_drift():
    ts, temp, prox = _trace(n_samples=288 * 6, events=((100, 160), (1300, 1400)))
    baseline_events = _detect(ts, temp, prox)

    # Add a slow additive pedestal that climbs from 0 to 60 over the record,
    # as seen on real devices. A raw `prox == 0` test would fail late on.
    drift = pd.Series(np.linspace(0, 60, len(prox)))
    drifted_events = _detect(ts, temp, prox + drift)

    assert len(baseline_events) == 2
    pd.testing.assert_frame_equal(
        baseline_events[["StartIdx", "EndIdx"]], drifted_events[["StartIdx", "EndIdx"]])


def test_all_zero_proximity_counts_as_covered():
    prox = pd.Series(np.zeros(500))
    assert ah.dedrift_proximity(prox, INTERVAL_MIN).all()


def test_infer_interval_minutes():
    ts = pd.Series(pd.date_range("2026-01-01", periods=10, freq="10min"))
    assert ah._infer_interval_minutes(ts) == pytest.approx(10.0)
    assert ah._infer_interval_minutes(ts.iloc[:1]) == 5.0  # default


def test_summary_splits_event_across_midnight():
    onset = pd.Series([pd.Timestamp("2026-01-01 23:00")])
    offset = pd.Series([pd.Timestamp("2026-01-02 01:30")])

    summary = ah.prepare_occurance_summary(onset, offset)
    assert list(summary["TotalDurationMin"]) == [60.0, 90.0]
    assert list(summary["EventCount"]) == [1, 1]

    gantt = ah.prepare_gantt(onset, offset)
    assert list(gantt["Date"]) == ["2026-01-01", "2026-01-02"]
    assert list(gantt["StartHour"]) == [23.0, 0.0]
    assert list(gantt["EndHour"]) == [24.0, 1.5]


def test_summary_across_dst_uses_true_elapsed_minutes():
    # 2026-11-01 is the autumn DST change in the US: the 01:00 hour repeats,
    # so 00:00 -> 03:00 Eastern is 4 real hours.
    tz = "America/New_York"
    onset = pd.Series([pd.Timestamp("2026-11-01 00:00").tz_localize(tz)])
    offset = pd.Series([pd.Timestamp("2026-11-01 03:00").tz_localize(tz)])
    summary = ah.prepare_occurance_summary(onset, offset)
    assert summary["TotalDurationMin"].iloc[0] == 240.0


def test_empty_events_give_empty_summaries():
    empty = pd.Series([], dtype="datetime64[ns]")
    summary = ah.prepare_occurance_summary(empty, empty)
    gantt = ah.prepare_gantt(empty, empty)
    assert summary.empty and list(summary.columns) == ["Date", "TotalDurationMin", "EventCount"]
    assert gantt.empty and "StartHour" in gantt.columns


def _upload(text):
    """Encode text the way dcc.Upload hands it to the callback."""
    return "data:text/csv;base64," + base64.b64encode(text.encode()).decode()


def test_parse_file_current_format():
    text = ("Initial Timestamp,2026-01-01 08:00:00-05:00\n"
            "Wake-up Interval (Seconds),300\n"
            "Personal ID,42\n"
            "Timezone,America/New_York\n"
            "Timestamp,Temperature,ProximityVal\n"
            "2026-01-01 08:00:00-05:00,30.50,0\n"
            "2026-01-01 08:05:00-05:00,31.00,5\n")
    df, meta, err = ah.parse_file(_upload(text))
    assert err is None
    assert meta["Personal ID"] == "42"
    assert meta["Timezone"] == "America/New_York"
    assert list(df.columns) == ["Timestamp", "Temperature", "ProximityVal"]
    assert len(df) == 2


def test_parse_file_legacy_format_without_proximity():
    text = ("Initial Timestamp,2025-03-01 13:00:00\n"
            "Timestamp,Temperature\n"
            "2025-03-01 13:00:00,25.0\n")
    df, _, err = ah.parse_file(_upload(text))
    assert err is None
    assert "ProximityVal" not in df.columns


def test_parse_file_without_header_reports_clear_error():
    df, meta, err = ah.parse_file(_upload("just,some\nrandom,rows\n"))
    assert df is None and meta == {}
    assert "no data header" in err


def test_to_display_tz_handles_new_and_legacy_timestamps():
    # New files carry an offset; legacy files are naive UTC. Both should land
    # on the same Eastern wall-clock time.
    new = ah.to_display_tz(pd.Series(["2026-01-01 08:00:00-05:00"]))
    legacy = ah.to_display_tz(pd.Series(["2026-01-01 13:00:00"]))
    assert new.iloc[0] == legacy.iloc[0]
    assert new.iloc[0].strftime("%Y-%m-%d %H:%M %Z") == "2026-01-01 08:00 EST"
    summer = ah.to_display_tz(pd.Series(["2026-07-01 12:00:00"]))
    assert summer.iloc[0].strftime("%H:%M %Z") == "08:00 EDT"


def test_detect_preserves_timezone_on_events():
    ts, temp, prox = _trace()
    ts = ts.dt.tz_localize("America/New_York")
    events = _detect(ts, temp, prox)
    assert str(events["Onset"].dt.tz) == "America/New_York"
