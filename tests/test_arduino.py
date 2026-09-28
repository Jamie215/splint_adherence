"""Tests for the serial protocol client, using a fake serial port."""
import io
import struct

import arduino
from arduino import ArduinoClient


def test_process_buffer_converts_epochs_to_eastern_with_timezone_line():
    raw = (b"Initial Timestamp,1767272400\r\n"      # 2026-01-01 13:00 UTC
           b"Wake-up Interval (Seconds),300\r\n"
           b"Personal ID,42\r\n"
           b"Timestamp,Temperature,ProximityVal\r\n"
           b"1767272400,30.50,0\r\n"
           b"1782921600,31.00,5\r\n")                # 2026-07-01 16:00 UTC
    out = io.StringIO()
    in_metadata = ArduinoClient._process_buffer_data(raw, out, True)

    assert in_metadata is False
    assert out.getvalue().split("\r\n")[:-1] == [
        "Initial Timestamp,2026-01-01 08:00:00-05:00",
        "Wake-up Interval (Seconds),300",
        "Personal ID,42",
        "Timezone,America/New_York",
        "Timestamp,Temperature,ProximityVal",
        "2026-01-01 08:00:00-05:00,30.50,0",
        "2026-07-01 12:00:00-04:00,31.00,5",
    ]


class FakeSerial:
    """Minimal stand-in for serial.Serial for the initialize() handshake."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.written = []
        self.is_open = True
        self.in_waiting = 0
        self.port = "FAKE"

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written.append(bytes(data))

    def readline(self):
        return self._responses.pop(0) if self._responses else b""

    def close(self):
        self.is_open = False


def test_initialize_packs_config_with_checksum(monkeypatch):
    monkeypatch.setattr(arduino.time, "sleep", lambda s: None)
    fake = FakeSerial([b"READY_FOR_INIT\r\n"])
    client = ArduinoClient()
    client._serial = fake

    ok, _ = client.initialize(1767272400, 42)

    assert ok
    assert fake.written[0] == b"i"
    packed = fake.written[1]
    ts, interval, pid, checksum = struct.unpack("<II16sI", packed)
    assert (ts, interval) == (1767272400, arduino.WAKEUP_INTERVAL_SECONDS)
    assert pid.rstrip(b"\0") == b"42"
    assert checksum == sum(packed[:-4]) & 0xFFFFFFFF
    assert not fake.is_open  # always disconnects afterwards


def test_initialize_reports_failure_when_no_device(monkeypatch):
    client = ArduinoClient()
    monkeypatch.setattr(client, "_search", lambda: None)
    ok, message = client.initialize(1767272400, 1)
    assert not ok and "No Arduino device found" in message
